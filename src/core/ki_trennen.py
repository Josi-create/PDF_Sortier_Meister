"""KI-unterstuetztes Trennen: einen Scan-Stapel in seine Dokumente zerlegen.

Ein PDF, das aus vielen hintereinander gescannten Schriftstuecken besteht
(Brief mit 3 Seiten, Stromrechnung mit 5 Seiten ...), wird nicht seitenweise,
sondern an den Dokumentgrenzen getrennt. Die KI bekommt je Seite einen
Textauszug und nennt, auf welcher Seite jedes Dokument beginnt, dazu einen
Dateinamen je Dokument. Leere Seiten bleiben beim vorhergehenden Dokument.

Qt-frei; der Aufruf laeuft ueber :meth:`LLMProvider.answer_with_context`, das
alle Anbieter koennen.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from src.utils.filename_sanitizer import sanitize_filename

ZEICHEN_GESAMT = 48000  # Textmenge im Prompt ueber alle Seiten
ZEICHEN_JE_SEITE_MAX = 1200
ZEICHEN_JE_SEITE_MIN = 300
ENDE_ANTEIL = 0.25  # so viel des Auszugs stammt vom Seitenende (Grussformel, "Seite 2 von 3")
NAME_MAX = 90


@dataclass
class Teil:
    """Ein Dokument im Stapel: 1-basierte Seiten und Dateiname ohne Endung."""

    seiten: list[int] = field(default_factory=list)
    name: str = ""


# --- Seitentexte ------------------------------------------------------------------


def seiten_texte(pdf_path: Path | str, ocr: bool = True) -> list[str]:
    """Text je Seite (Index 0 = Seite 1); Bildseiten ohne Text werden per OCR gelesen.

    Reihenfolge wie im Analyzer: aktueller Eintrag im Suchindex, sonst Textebene;
    was dann noch fehlt, liest Tesseract (wenn vorhanden).
    """
    from src.core import pdf_analyzer as pa
    from src.search import extract as suche_extract

    pfad = str(pdf_path)
    seiten: list = []
    offen: list[int] = []
    anzahl = 0
    index = pa.suchindex_fuer_analyse()
    stand = None
    if index is not None:
        try:
            stand = index.text_fuer_datei(pfad)
        except Exception:  # noqa: BLE001 - Index ist Zusatz
            stand = None
    if stand is not None and stand.get("aktuell") and stand.get("seiten"):
        seiten, offen = list(stand["seiten"]), list(stand.get("ocr_offen") or [])
    else:
        konfig = pa._search_konfig()
        gelesen = suche_extract.pdf_text(pfad, konfig.ocr_min_zeichen if konfig else 25)
        if gelesen["status"] == "verschluesselt":
            raise RuntimeError("Das PDF ist verschlüsselt und kann nicht gelesen werden.")
        if gelesen["status"] == "fehler":
            raise RuntimeError(gelesen.get("fehler") or "Das PDF konnte nicht gelesen werden.")
        seiten, offen, anzahl = list(gelesen["seiten"]), list(gelesen["ohne_text"]), gelesen["anzahl"]

    texte = {nr: (txt or "") for nr, _quelle, txt in seiten}
    if offen and ocr:
        cfg = pa.ocr_einstellungen_fuer_analyse()
        if cfg is not None:
            try:
                res = suche_extract.pdf_ocr(pfad, list(offen), cfg)
                for nr, txt in (res.get("texte") or {}).items():
                    if txt and txt.strip():
                        texte[nr] = txt
            except Exception as e:  # noqa: BLE001 - ohne OCR bleiben die Seiten leer
                print(f"KI-Trennen: OCR-Fehler: {e}")

    if not anzahl:
        import fitz

        with fitz.open(pfad) as doc:
            anzahl = len(doc)
    return [texte.get(nr, "") for nr in range(1, anzahl + 1)]


# --- Prompt und Antwort -----------------------------------------------------------


def _auszug(text: str, laenge: int) -> str:
    """Anfang und Ende der Seite; an beiden Stellen stehen die Hinweise auf Dokumentgrenzen."""
    text = re.sub(r"[ \t]+", " ", text or "")
    text = re.sub(r"\s*\n\s*", "\n", text).strip()
    if len(text) <= laenge:
        return text
    ende = int(laenge * ENDE_ANTEIL)
    return f"{text[:laenge - ende].rstrip()}\n[...]\n{text[-ende:].lstrip()}"


def ki_prompt(texte: Sequence[str]) -> str:
    """Bittet um die Anfangsseiten der Dokumente im Stapel und je einen Dateinamen."""
    n = len(texte)
    je_seite = max(ZEICHEN_JE_SEITE_MIN, min(ZEICHEN_JE_SEITE_MAX, ZEICHEN_GESAMT // max(n, 1)))
    teile = [
        f"Das folgende PDF hat {n} Seiten und ist ein Stapel aus mehreren hintereinander "
        "gescannten Schriftstücken (Briefe, Rechnungen, Bescheide, Verträge ...).",
        "Finde heraus, auf welcher Seite jeweils ein NEUES Dokument beginnt. Hinweise: "
        "Briefkopf, Absender und Anschrift, Datum, Betreff, Anrede am Anfang; Grußformel, "
        "Unterschrift, 'Seite 2 von 3', fortlaufende Seitenzahlen, fortgesetzte Tabellen "
        "oder Sätze sprechen für eine Fortsetzung.",
        "Regeln:",
        "- Jede Seite gehört zu genau einem Dokument; die Dokumente sind zusammenhängende Seitenbereiche.",
        "- Das erste Dokument beginnt auf Seite 1.",
        "- Leere Seiten (Rückseiten) und Anlagen gehören zum vorhergehenden Dokument.",
        "- Trenne nur, wo wirklich ein neues Schriftstück beginnt; im Zweifel zusammenlassen.",
        "- Gib jedem Dokument einen Dateinamen ohne Endung nach dem Muster "
        "JJJJ-MM-TT_Absender_Dokumentart (Datum des Schreibens; ohne Datum nur Absender_Dokumentart; "
        "keine Umlaute, keine Sonderzeichen, Wörter mit Unterstrich verbunden).",
        'Antworte nur mit JSON: {"dokumente": [{"erste_seite": 1, "name": "..."}, '
        '{"erste_seite": 4, "name": "..."}]}',
        "",
    ]
    for i, text in enumerate(texte, 1):
        teile.append(f"=== Seite {i} ===\n{_auszug(text, je_seite) or '(leere Seite / kein Text)'}")
    return "\n".join(teile)


def name_bereinigen(name, ersatz: str = "") -> str:
    """Dateiname ohne Endung, wie die Namen sonst im Programm (ae statt ä, keine Sonderzeichen)."""
    text = sanitize_filename(str(name or "").strip(), ensure_pdf=False)[:NAME_MAX].strip(" _-")
    return text or ersatz


def antwort_auswerten(text: str, seitenzahl: int, ersatzname: str = "Dokument") -> Optional[list[Teil]]:
    """Liest die Dokumente aus der KI-Antwort; None, wenn sie nicht brauchbar ist.

    Massgeblich sind die Anfangsseiten: Daraus ergeben sich lueckenlose Bereiche
    ueber alle Seiten, auch wenn die KI sich bei den Enden verzaehlt haette.
    """
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        daten = json.loads(m.group(0))
    except ValueError:
        return None
    roh = daten.get("dokumente") if isinstance(daten, dict) else None
    if not isinstance(roh, list) or not roh:
        return None
    anfaenge: dict[int, str] = {}
    for eintrag in roh:
        if not isinstance(eintrag, dict):
            continue
        try:
            seite = int(eintrag.get("erste_seite"))
        except (TypeError, ValueError):
            continue
        if 1 <= seite <= seitenzahl and seite not in anfaenge:
            anfaenge[seite] = str(eintrag.get("name") or "")
    if not anfaenge:
        return None
    starts = sorted(anfaenge)
    if starts[0] != 1:  # Seiten vor dem ersten genannten Dokument gehoeren zu diesem
        anfaenge[1] = anfaenge.pop(starts[0])
        starts[0] = 1
    teile = []
    for i, start in enumerate(starts):
        ende = starts[i + 1] - 1 if i + 1 < len(starts) else seitenzahl
        teile.append(Teil(list(range(start, ende + 1)),
                          name_bereinigen(anfaenge[start], f"{ersatzname}_Teil_{i + 1}")))
    return teile


def vorschlagen(provider, texte: Sequence[str], ersatzname: str = "Dokument") -> list[Teil]:
    """Fragt die KI nach den Dokumenten im Stapel.

    Wirft ``RuntimeError`` mit lesbarem Text, wenn der Aufruf scheitert oder die
    Antwort nicht brauchbar ist.
    """
    antwort = provider.answer_with_context(
        system_prompt="Du bist ein Assistent zum Ordnen gescannter Dokumente. Antworte nur mit JSON.",
        context_docs=[],
        user_question=ki_prompt(texte),
        max_tokens=2000,
    )
    antwort = (antwort or "").strip()
    if not antwort:
        raise RuntimeError("Die KI hat nicht geantwortet.")
    if antwort.startswith("[") and "fehler" in antwort[:60].lower():
        raise RuntimeError(antwort.strip("[]"))
    teile = antwort_auswerten(antwort, len(texte), ersatzname)
    if teile is None:
        raise RuntimeError("Die KI hat keine brauchbare Aufteilung genannt.")
    return teile


# --- Seitenangaben ("1-3, 7") -------------------------------------------------------


def seiten_parsen(text: str, seitenzahl: int) -> list[int]:
    """``"1-3, 7"`` -> ``[1, 2, 3, 7]``; wirft ``ValueError`` mit lesbarem Text."""
    seiten: list[int] = []
    for stueck in re.split(r"[,;]", text or ""):
        stueck = stueck.strip()
        if not stueck:
            continue
        m = re.fullmatch(r"(\d+)\s*(?:[-–]\s*(\d+))?", stueck)
        if not m:
            raise ValueError(f"'{stueck}' ist keine Seitenangabe (z.B. 1-3 oder 5).")
        von = int(m.group(1))
        bis = int(m.group(2)) if m.group(2) else von
        if von < 1 or bis > seitenzahl or von > bis:
            raise ValueError(f"'{stueck}': Seiten müssen zwischen 1 und {seitenzahl} liegen.")
        seiten.extend(range(von, bis + 1))
    if not seiten:
        raise ValueError("Keine Seiten angegeben.")
    return sorted(set(seiten))


def seiten_als_text(seiten: Sequence[int]) -> str:
    """``[1, 2, 3, 7]`` -> ``"1-3, 7"``."""
    stuecke: list[str] = []
    lauf: list[int] = []
    for s in sorted(set(seiten)) + [None]:
        if lauf and (s is None or s != lauf[-1] + 1):
            stuecke.append(str(lauf[0]) if len(lauf) == 1 else f"{lauf[0]}-{lauf[-1]}")
            lauf = []
        if s is not None:
            lauf.append(s)
    return ", ".join(stuecke)

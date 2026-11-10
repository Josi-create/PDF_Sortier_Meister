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
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

from src.utils.filename_sanitizer import sanitize_filename

SEITEN_JE_AUFRUF = 20  # grosse Stapel gehen abschnittsweise an die KI
ZEICHEN_GESAMT = 20000  # Textmenge im Prompt je Aufruf
ZEICHEN_JE_SEITE_MAX = 1200
ZEICHEN_JE_SEITE_MIN = 300
ENDE_ANTEIL = 0.25  # so viel des Auszugs stammt vom Seitenende (Grussformel, "Seite 2 von 3")
ANTWORT_TOKENS = 4000  # reichlich: Denkmodelle verbrauchen einen Teil davon, bevor sie antworten
ANTWORT_TOKENS_VERSUCHE = (ANTWORT_TOKENS, 12000, 16000)  # unlesbare Antwort: noch einmal mit mehr Platz
AUFRUFE_GLEICHZEITIG = 3
NAME_MAX = 90

logger = logging.getLogger(__name__)


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


def abschnitte(seitenzahl: int, je_aufruf: int = SEITEN_JE_AUFRUF) -> list[tuple[int, int]]:
    """Teilt die Seiten in Abschnitte ``(von, bis)`` (1-basiert, einschliesslich) fuer je einen KI-Aufruf."""
    if seitenzahl <= 0:
        return []
    anzahl = -(-seitenzahl // je_aufruf)
    groesse = -(-seitenzahl // anzahl)  # gleichmaessig statt eines kleinen Rests am Ende
    return [(von, min(von + groesse - 1, seitenzahl)) for von in range(1, seitenzahl + 1, groesse)]


def ki_prompt(texte: Sequence[str], von: int = 1, bis: Optional[int] = None) -> str:
    """Bittet um die Anfangsseiten der Dokumente (Seiten ``von`` bis ``bis``) und je einen Dateinamen.

    Ab dem zweiten Abschnitt ist die Seite davor zum Vergleich dabei, damit die KI
    erkennt, ob die erste Seite des Abschnitts ein Dokument fortsetzt.
    """
    n = len(texte)
    bis = n if bis is None else bis
    ganz = von == 1 and bis == n
    erste_gezeigt = max(1, von - 1)
    gezeigt = bis - erste_gezeigt + 1
    je_seite = max(ZEICHEN_JE_SEITE_MIN, min(ZEICHEN_JE_SEITE_MAX, ZEICHEN_GESAMT // max(gezeigt, 1)))
    if ganz:
        kopf = (f"Das folgende PDF hat {n} Seiten und ist ein Stapel aus mehreren hintereinander "
                "gescannten Schriftstücken (Briefe, Rechnungen, Bescheide, Verträge ...).")
    else:
        kopf = (f"Ein PDF mit {n} Seiten ist ein Stapel aus mehreren hintereinander gescannten "
                f"Schriftstücken (Briefe, Rechnungen, Bescheide, Verträge ...). Du siehst daraus die "
                f"Seiten {von} bis {bis}.")
    teile = [
        kopf,
        "Finde heraus, auf welcher Seite jeweils ein NEUES Dokument beginnt. Hinweise: "
        "Briefkopf, Absender und Anschrift, Datum, Betreff, Anrede am Anfang; Grußformel, "
        "Unterschrift, 'Seite 2 von 3', fortlaufende Seitenzahlen, fortgesetzte Tabellen "
        "oder Sätze sprechen für eine Fortsetzung.",
        "Regeln:",
        "- Jede Seite gehört zu genau einem Dokument; die Dokumente sind zusammenhängende Seitenbereiche.",
    ]
    if von == 1:
        teile.append("- Das erste Dokument beginnt auf Seite 1.")
    else:
        teile.append(
            f"- Seite {von - 1} gehört zum Abschnitt davor und ist nur zum Vergleich dabei: nenne sie nicht. "
            f"Setzt Seite {von} das Dokument von Seite {von - 1} fort, dann nenne auch Seite {von} nicht.")
    teile += [
        "- Leere Seiten (Rückseiten) und Anlagen gehören zum vorhergehenden Dokument.",
        "- Trenne nur, wo wirklich ein neues Schriftstück beginnt; im Zweifel zusammenlassen.",
        "- Verwende die Seitennummern genau so, wie sie unten über den Seiten stehen.",
        "- Gib jedem Dokument einen Dateinamen ohne Endung nach dem Muster "
        "JJJJ-MM-TT_Absender_Dokumentart (Datum des Schreibens; ohne Datum nur Absender_Dokumentart; "
        "keine Umlaute, keine Sonderzeichen, Wörter mit Unterstrich verbunden).",
        "Antworte nur mit JSON, ohne Erklärung: "
        f'{{"dokumente": [{{"erste_seite": {von}, "name": "..."}}, '
        f'{{"erste_seite": {min(von + 3, bis)}, "name": "..."}}]}}',
        "",
    ]
    for i in range(erste_gezeigt, bis + 1):
        zusatz = " (nur zum Vergleich)" if i < von else ""
        teile.append(f"=== Seite {i}{zusatz} ===\n{_auszug(texte[i - 1], je_seite) or '(leere Seite / kein Text)'}")
    return "\n".join(teile)


def name_bereinigen(name, ersatz: str = "") -> str:
    """Dateiname ohne Endung, wie die Namen sonst im Programm (ae statt ä, keine Sonderzeichen)."""
    text = sanitize_filename(str(name or "").strip(), ensure_pdf=False)[:NAME_MAX].strip(" _-")
    return text or ersatz


_EINTRAG_RE = re.compile(r'"erste_seite"\s*:\s*"?(\d+)"?\s*(?:,\s*"name"\s*:\s*"((?:[^"\\]|\\.)*)")?')


def anfaenge_lesen(text: str, von: int, bis: int) -> Optional[dict[int, str]]:
    """Anfangsseiten ``{seite: name}`` im Bereich ``von``..``bis`` aus einer KI-Antwort; None = unlesbar.

    Liest zuerst das JSON; ist es kaputt oder abgeschnitten (Token-Limit), zaehlen
    die Eintraege, die sich noch einzeln erkennen lassen. Ein leeres Ergebnis ist
    gueltig: Der Abschnitt setzt dann nur das Dokument davor fort.
    """
    text = text or ""
    eintraege: Optional[list] = None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            daten = json.loads(m.group(0))
        except ValueError:
            daten = None
        roh = daten.get("dokumente") if isinstance(daten, dict) else None
        if isinstance(roh, list):
            eintraege = [(e.get("erste_seite"), e.get("name")) for e in roh if isinstance(e, dict)]
    if eintraege is None:
        gefunden = _EINTRAG_RE.findall(text)
        if not gefunden:
            return None
        eintraege = list(gefunden)
    anfaenge: dict[int, str] = {}
    for seite, name in eintraege:
        try:
            seite = int(seite)
        except (TypeError, ValueError):
            continue
        if von <= seite <= bis and seite not in anfaenge:
            anfaenge[seite] = str(name or "")
    return anfaenge


def teile_aus_anfaengen(anfaenge: dict[int, str], seitenzahl: int, ersatzname: str = "Dokument") -> list[Teil]:
    """Lueckenlose Bereiche ueber alle Seiten aus den Anfangsseiten (nicht leer)."""
    anfaenge = dict(anfaenge)
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


def antwort_auswerten(text: str, seitenzahl: int, ersatzname: str = "Dokument") -> Optional[list[Teil]]:
    """Liest die Dokumente aus der KI-Antwort fuer das ganze PDF; None, wenn sie nicht brauchbar ist.

    Massgeblich sind die Anfangsseiten: Daraus ergeben sich lueckenlose Bereiche
    ueber alle Seiten, auch wenn die KI sich bei den Enden verzaehlt haette.
    """
    anfaenge = anfaenge_lesen(text, 1, seitenzahl)
    if not anfaenge:
        return None
    return teile_aus_anfaengen(anfaenge, seitenzahl, ersatzname)


def _abschnitt_fragen(provider, texte: Sequence[str], von: int, bis: int) -> dict[int, str]:
    """Fragt einen Abschnitt ab; bei leerer oder unlesbarer Antwort noch einmal mit mehr Platz.

    Denkmodelle verbrauchen bei schwierigen Seiten (Tabellen, Depotauszuege) das
    ganze Budget fuers Ueberlegen und kommen nicht mehr zum JSON.
    """
    frage = ki_prompt(texte, von, bis)
    fehler = "Die KI hat nicht geantwortet."
    for versuch, tokens in enumerate(ANTWORT_TOKENS_VERSUCHE, 1):
        if versuch > 1:
            frage_jetzt = frage + ("\n\nWICHTIG: Schreibe keine Überlegungen und keine Begründung. "
                                   "Gib sofort und ausschließlich das JSON aus.")
        else:
            frage_jetzt = frage
        antwort = provider.answer_with_context(
            system_prompt="Du bist ein Assistent zum Ordnen gescannter Dokumente. Antworte nur mit JSON.",
            context_docs=[],
            user_question=frage_jetzt,
            max_tokens=tokens,
        )
        antwort = (antwort or "").strip()
        if antwort.startswith("[") and "fehler" in antwort[:60].lower():
            raise RuntimeError(antwort.strip("[]"))
        if not antwort:
            fehler = "Die KI hat nicht geantwortet."
            logger.warning("KI-Trennen: leere Antwort fuer Seiten %s-%s (Versuch %s)", von, bis, versuch)
            continue
        anfaenge = anfaenge_lesen(antwort, von, bis)
        if anfaenge is not None:
            return anfaenge
        fehler = "Die KI hat keine brauchbare Aufteilung genannt."
        logger.warning("KI-Trennen: Antwort fuer Seiten %s-%s nicht lesbar (Versuch %s): %r",
                       von, bis, versuch, antwort[:500])
    raise RuntimeError(fehler)


def vorschlagen(provider, texte: Sequence[str], ersatzname: str = "Dokument",
                fortschritt: Optional[Callable[[int, int], None]] = None,
                abbruch: Optional[Callable[[], bool]] = None) -> list[Teil]:
    """Fragt die KI nach den Dokumenten im Stapel; grosse Stapel abschnittsweise.

    ``fortschritt(fertig, gesamt)`` meldet erledigte Abschnitte (aus dem aufrufenden
    Thread), ``abbruch()`` laesst noch nicht begonnene Abschnitte entfallen.

    Wirft ``RuntimeError`` mit lesbarem Text, wenn ein Aufruf scheitert oder die
    Antworten nicht brauchbar sind.
    """
    bereiche = abschnitte(len(texte))
    if not bereiche:
        raise RuntimeError("Das PDF hat keine Seiten.")
    anfaenge: dict[int, str] = {}
    if fortschritt:
        fortschritt(0, len(bereiche))

    def einer(bereich):
        if abbruch and abbruch():
            return {}
        return _abschnitt_fragen(provider, texte, *bereich)

    with ThreadPoolExecutor(max_workers=min(AUFRUFE_GLEICHZEITIG, len(bereiche)),
                            thread_name_prefix="ki-trennen") as pool:
        laufend = [pool.submit(einer, b) for b in bereiche]
        try:
            for fertig, auftrag in enumerate(laufend, 1):
                anfaenge.update(auftrag.result())
                if fortschritt:
                    fortschritt(fertig, len(bereiche))
        except BaseException:
            for auftrag in laufend:
                auftrag.cancel()
            raise
    if abbruch and abbruch():
        raise RuntimeError("Abgebrochen.")
    if not anfaenge:
        if len(bereiche) == 1:
            raise RuntimeError("Die KI hat keine brauchbare Aufteilung genannt.")
        anfaenge = {1: ""}
    return teile_aus_anfaengen(anfaenge, len(texte), ersatzname)


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

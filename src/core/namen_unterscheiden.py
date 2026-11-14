"""Gleiche Namensvorschlaege im Stapel per KI unterscheiden (Issue #221).

Beim Stapel-Umbenennen/-Verschieben (Issue #218) benennt die KI jede Datei fuer
sich. Aehnliche Schreiben desselben Absenders (z.B. vier Monatsabrechnungen fuer
Vorderhaus, Hinterhaus, Garten ...) bekommen dann denselben Namen, und das
Programm haengt nur " (1)", " (2)" an. Hier fragt ein zusaetzlicher KI-Aufruf je
Gruppe gleicher Namen, was die Dokumente unterscheidet; das Wort kommt vor die
Endung (``..._Hinterhaus.pdf``).

Issue #256: Auch ohne gleiche Namen kann der Stapel uneinheitlich sein - von
mehreren Monatsrechnungen heisst eine ``..._Festnetz Mai 2025``, die naechste nur
``..._Festnetz``. :func:`uneinheitliche_gruppen` findet solche Faelle, und
:func:`ergaenzen` fragt die KI nach dem fehlenden Zusatz.

Qt-frei; der Aufruf laeuft ueber :meth:`LLMProvider.answer_with_context`, das
alle Anbieter koennen.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Optional, Sequence
from src.i18n import tr

TEXT_JE_DOKUMENT = 1500  # Zeichen Textanfang je Dokument im Prompt
WORT_MAX = 30  # Zeichen je Unterscheidungswort
ZUSATZ_MAX = 30  # Zeichen je Zusatz am Namensende (Issue #256)
BASIS_MIN = 5  # kuerzere Namen sind kein tragfaehiger gemeinsamer Anfang
BEISPIELE_MAX = 5  # so viele Namen mit Zusatz zeigt der Prompt

_TRENNER = " _-"
_DATUM = re.compile(r"\d{4}-\d{2}-\d{2}")
_ZAEHLER = re.compile(r"\(?\d{1,3}\)?")  # " (1)", "_2": kein inhaltlicher Zusatz

_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})


def doppelte_gruppen(namen: Sequence[Optional[str]]) -> list[list[int]]:
    """Indizes gleicher Namen (ohne Gross-/Kleinschreibung), nur Gruppen ab zwei; None zaehlt nicht."""
    gruppen: dict[str, list[int]] = {}
    for i, name in enumerate(namen):
        if name:
            gruppen.setdefault(name.casefold(), []).append(i)
    return [g for g in gruppen.values() if len(g) > 1]


def wort_bereinigen(wort) -> Optional[str]:
    """Macht aus der KI-Antwort ein dateinamentaugliches Wort (wie die Namen sonst: ae statt ä)."""
    text = str(wort or "").strip().translate(_UMLAUTE)
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    text = text[:WORT_MAX].strip("-")
    return text or None


def wort_einfuegen(name: str, wort: str) -> str:
    """``a_b.pdf`` + ``Hinterhaus`` -> ``a_b_Hinterhaus.pdf``."""
    p = PurePath(name)
    return f"{p.stem}_{wort}{p.suffix}"


def ki_prompt(name: str, texte: Sequence[str]) -> str:
    """Bittet um je ein Unterscheidungswort fuer Dokumente, die denselben Namen bekaemen."""
    teile = [
        f"Die folgenden {len(texte)} Dokumente sollen alle den Dateinamen \"{name}\" bekommen.",
        "Finde heraus, worin sie sich inhaltlich unterscheiden (z.B. Objekt, Gebaeudeteil, "
        "Leistung, Zeitraum, Vertragsnummer), und nenne fuer jedes Dokument EIN kurzes "
        "Unterscheidungswort (1-3 Woerter, deutsch, keine Wiederholung des Dateinamens).",
        "Die Woerter muessen sich voneinander unterscheiden.",
        'Antworte nur mit JSON: {"unterschiede": ["Wort fuer Dokument 1", "Wort fuer Dokument 2", ...]}',
        "",
    ]
    for i, text in enumerate(texte, 1):
        auszug = re.sub(r"\s+", " ", text or "").strip()[:TEXT_JE_DOKUMENT]
        teile.append(f"--- Dokument {i} ---\n{auszug or '(kein Text)'}")
    return "\n".join(teile)


def antwort_auswerten(text: str, anzahl: int) -> Optional[list[str]]:
    """Liest die Woerter aus der KI-Antwort; None, wenn sie fehlen, leer oder nicht verschieden sind."""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        daten = json.loads(m.group(0))
    except ValueError:
        return None
    roh = daten.get("unterschiede") if isinstance(daten, dict) else None
    if not isinstance(roh, list) or len(roh) != anzahl:
        return None
    woerter = [wort_bereinigen(w) for w in roh]
    if any(w is None for w in woerter) or len({w.casefold() for w in woerter}) != anzahl:
        return None
    return woerter


def unterscheiden(provider, name: str, texte: Sequence[str]) -> list[str]:
    """Fragt die KI nach je einem Unterscheidungswort (Reihenfolge wie ``texte``).

    Einbauen mit :func:`wort_einfuegen`.

    Wirft ``RuntimeError`` mit lesbarem Text, wenn der Aufruf scheitert oder die
    Antwort nicht brauchbar ist.
    """
    antwort = provider.answer_with_context(
        system_prompt="Du bist ein Assistent zum Benennen von Dokumenten. Antworte nur mit JSON.",
        context_docs=[],
        user_question=ki_prompt(name, texte),
        max_tokens=300,
    )
    antwort = (antwort or "").strip()
    if not antwort:
        raise RuntimeError(tr("Die KI hat nicht geantwortet."))
    if antwort.startswith("[") and "fehler" in antwort[:60].lower():
        raise RuntimeError(antwort.strip("[]"))
    woerter = antwort_auswerten(antwort, len(texte))
    if woerter is None:
        raise RuntimeError(tr("Die KI hat keine eindeutigen Unterscheidungen genannt."))
    return woerter


# --- Issue #256: einheitlicher Aufbau der Namen im Stapel ----------------------


@dataclass
class UneinheitlicheGruppe:
    """Gleich aufgebaute Namen, von denen nur einige am Ende einen Zusatz tragen."""

    ohne: list[int]  # Indizes der Namen ohne Zusatz
    mit: dict[int, str]  # Index -> Zusatz samt Trennzeichen davor (" Mai 2025")


def _kern(name: str) -> Optional[tuple[str, str]]:
    """(Vergleichsform, Stamm): Stamm klein und mit "#" statt Datum, damit das Tagesdatum nicht trennt."""
    stamm = PurePath(name).stem
    klein = stamm.lower()
    if len(klein) != len(stamm):  # seltene Zeichen aendern die Laenge; dann lieber nicht vergleichen
        return None
    return _DATUM.sub("#", klein), stamm


def uneinheitliche_gruppen(namen: Sequence[Optional[str]]) -> list[UneinheitlicheGruppe]:
    """Findet Namen, die bis auf einen Zusatz am Ende gleich sind (das Datum im Namen zaehlt nicht).

    ``2025-05-12_Rechnung_X_Festnetz Mai 2025.pdf`` und ``2025-06-11_Rechnung_X_Festnetz.pdf``
    bilden eine Gruppe: der zweite Name ist ohne Zusatz. Gruppen gibt es nur, wenn
    mindestens ein Name mit und einer ohne Zusatz da ist. Reine Zaehler (" (1)")
    gelten nicht als Zusatz.
    """
    kerne: dict[str, list[tuple[int, str]]] = {}
    for i, name in enumerate(namen):
        kern = _kern(name) if name else None
        if kern:
            kerne.setdefault(kern[0], []).append((i, kern[1]))
    gruppen: list[UneinheitlicheGruppe] = []
    vergeben: set[str] = set()
    for basis in sorted(kerne, key=len):
        if basis in vergeben or len(basis) < BASIS_MIN:
            continue
        mit: dict[int, str] = {}
        laengere: list[str] = []
        for kern, eintraege in kerne.items():
            laenge = len(kern) - len(basis)
            if kern in vergeben or laenge < 2 or not kern.startswith(basis) or kern[len(basis)] not in _TRENNER:
                continue
            zusatz = kern[len(basis) + 1:]
            if (laenge - 1 > ZUSATZ_MAX or "#" in zusatz or _ZAEHLER.fullmatch(zusatz)
                    or not any(z.isalnum() for z in zusatz)):
                continue
            laengere.append(kern)
            for i, stamm in eintraege:
                mit[i] = stamm[-laenge:]
        if mit:
            vergeben.add(basis)
            vergeben.update(laengere)
            gruppen.append(UneinheitlicheGruppe(
                ohne=[i for i, _stamm in kerne[basis]], mit=dict(sorted(mit.items()))))
    return gruppen


def zusatz_bereinigen(roh, vorbild: str) -> Optional[str]:
    """Macht aus der KI-Antwort einen Zusatz in der Schreibweise von ``vorbild`` (" Mai 2025" -> " Juni 2025").

    Das erste Zeichen von ``vorbild`` haengt den Zusatz an; Luecken im Zusatz
    werden so gefuellt wie im Vorbild. None, wenn nichts Brauchbares uebrig bleibt.
    """
    davor = vorbild[0]
    innen = next((z for z in vorbild[1:] if z in _TRENNER), davor)
    text = str(roh or "").strip().translate(_UMLAUTE)
    text = re.sub(r"[^A-Za-z0-9]+", innen, text).strip(_TRENNER)[:ZUSATZ_MAX].strip(_TRENNER)
    return davor + text if text else None


def zusatz_einfuegen(name: str, zusatz: str) -> str:
    """``a_b.pdf`` + `` Juni 2025`` -> ``a_b Juni 2025.pdf``."""
    p = PurePath(name)
    return f"{p.stem}{zusatz}{p.suffix}"


def ergaenzen_prompt(beispiele: Sequence[tuple[str, str]], namen: Sequence[str], texte: Sequence[str]) -> str:
    """Bittet um den fehlenden Zusatz; ``beispiele`` sind (Name, Zusatz) der Dokumente, die ihn haben."""
    teile = [
        "Mehrere gleichartige Dokumente werden zusammen umbenannt. Bei einigen steht am Ende des "
        "Dateinamens ein zusaetzliches Merkmal, das sie unterscheidet:",
    ]
    for name, zusatz in list(beispiele)[:BEISPIELE_MAX]:
        teile.append(f'- "{name}" -> Merkmal "{zusatz.strip(_TRENNER)}"')
    teile += [
        f"Bei den folgenden {len(texte)} Dokumenten fehlt dieses Merkmal im Dateinamen.",
        "Nenne fuer jedes das entsprechende Merkmal aus seinem Inhalt, in derselben Art und "
        "Schreibweise wie in den Beispielen (z.B. wieder Monat und Jahr, wieder eine Rechnungsnummer). "
        'Steht im Dokument nichts Entsprechendes, gib "" an. Nichts erfinden.',
        'Antworte nur mit JSON: {"merkmale": ["Merkmal fuer Dokument 1", "Merkmal fuer Dokument 2", ...]}',
        "",
    ]
    for i, (name, text) in enumerate(zip(namen, texte), 1):
        auszug = re.sub(r"\s+", " ", text or "").strip()[:TEXT_JE_DOKUMENT]
        teile.append(f'--- Dokument {i} (Dateiname "{name}") ---\n{auszug or "(kein Text)"}')
    return "\n".join(teile)


def ergaenzen_auswerten(text: str, anzahl: int, vorbild: str) -> Optional[list[Optional[str]]]:
    """Liest die Zusaetze aus der KI-Antwort (None je Dokument ohne Merkmal); None bei unbrauchbarer Antwort."""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        daten = json.loads(m.group(0))
    except ValueError:
        return None
    roh = daten.get("merkmale") if isinstance(daten, dict) else None
    if not isinstance(roh, list) or len(roh) != anzahl:
        return None
    return [zusatz_bereinigen(w, vorbild) for w in roh]


def ergaenzen(provider, beispiele: Sequence[tuple[str, str]], namen: Sequence[str],
              texte: Sequence[str]) -> list[Optional[str]]:
    """Fragt die KI nach dem Zusatz, der ``namen`` fehlt (Reihenfolge wie ``texte``; None = keiner gefunden).

    Einbauen mit :func:`zusatz_einfuegen`. Wirft ``RuntimeError`` mit lesbarem Text,
    wenn der Aufruf scheitert oder die Antwort nicht brauchbar ist.
    """
    antwort = provider.answer_with_context(
        system_prompt="Du bist ein Assistent zum Benennen von Dokumenten. Antworte nur mit JSON.",
        context_docs=[],
        user_question=ergaenzen_prompt(beispiele, namen, texte),
        max_tokens=300,
    )
    antwort = (antwort or "").strip()
    if not antwort:
        raise RuntimeError(tr("Die KI hat nicht geantwortet."))
    if antwort.startswith("[") and "fehler" in antwort[:60].lower():
        raise RuntimeError(antwort.strip("[]"))
    zusaetze = ergaenzen_auswerten(antwort, len(texte), beispiele[0][1])
    if zusaetze is None or not any(zusaetze):
        raise RuntimeError(tr("Die KI hat kein passendes Merkmal für die Namen gefunden."))
    return zusaetze

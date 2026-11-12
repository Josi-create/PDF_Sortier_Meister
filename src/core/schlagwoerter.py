"""
Schlagwoerter mit Ebenen (Issue #231).

Ein Schlagwort ist ein freier Text; ein Schraegstrich trennt Ebenen
(``Steuer/Werbungskosten``). Mehrere Schlagwoerter stehen kommagetrennt in
``pdf:Keywords`` der PDF und in der Spalte ``schlagwoerter`` des Suchindex.

Dasselbe Feld traegt seit jeher die automatisch erkannten Stichwoerter der
Analyse (``rechnung``, ``bank``, ...; ``PDFAnalyzer.extract_keywords``). Sie
bleiben in der Datei, weil die Aehnlichkeitssuche sie braucht, gelten aber
nicht als Schlagwoerter des Nutzers: :func:`aufteilen` trennt beide Gruppen.

Ohne Qt und ohne PDF-Bibliothek, damit Suchindex, Metadaten-Schreiber und
Oberflaeche dieselben Regeln benutzen.
"""

from __future__ import annotations

import re
from typing import Iterable

TRENNER = ", "
EBENE = "/"

# Feste Stichwoerter der Analyse (Schluessel von pdf_analyzer.KEYWORD_PATTERNS;
# ein Test haelt beide Listen gleich). Genau so geschrieben (klein) sind sie
# keine Schlagwoerter des Nutzers.
AUTO_STICHWOERTER = frozenset({
    "rechnung", "vertrag", "steuer", "versicherung", "bank", "gehalt", "arzt", "handwerker", "energie", "telefon",
})

_TEILER = re.compile(r"[,;\n]")


def _saeubern(eintrag: str) -> str:
    """Ein Schlagwort in Normalform: Ebenen ohne Leerraum am Rand, keine leeren Ebenen."""
    teile = [" ".join(t.split()) for t in str(eintrag).replace("\\", EBENE).split(EBENE)]
    return EBENE.join(t for t in teile if t)


def _liste(text, genau: bool = False) -> list[str]:
    """Eintraege in Normalform ohne doppelte; ``genau`` unterscheidet Gross-/Kleinschreibung."""
    if text is None:
        return []
    if isinstance(text, (list, tuple, set, frozenset)):
        roh: Iterable = text
    else:
        roh = _TEILER.split(str(text))
    erg, gesehen = [], set()
    for eintrag in roh:
        wort = _saeubern(eintrag)
        marke = wort if genau else wort.casefold()
        if wort and marke not in gesehen:
            gesehen.add(marke)
            erg.append(wort)
    return erg


def aufteilen(keywords) -> tuple[list[str], list[str]]:
    """Inhalt von ``pdf:Keywords`` in (automatische Stichwoerter, Schlagwoerter des Nutzers) teilen."""
    auto, eigene = [], []
    for wort in _liste(keywords, genau=True):
        (auto if wort in AUTO_STICHWOERTER else eigene).append(wort)
    return auto, eigene


def eigene(keywords) -> list[str]:
    """Nur die Schlagwoerter des Nutzers aus ``pdf:Keywords``."""
    return aufteilen(keywords)[1]


def aus_eingabe(text) -> list[str]:
    """Eingabe des Nutzers (Komma oder Semikolon trennt) als Liste von Schlagwoertern.

    Doppelte fallen weg (Gross-/Kleinschreibung egal, die erste Schreibweise
    bleibt). Wer genau ein automatisches Stichwort tippt (``steuer``), bekommt
    es mit grossem Anfangsbuchstaben, damit es als sein Schlagwort erkennbar bleibt.
    """
    return [w[:1].upper() + w[1:] if w in AUTO_STICHWOERTER else w for w in _liste(text)]


def als_text(schlagwoerter) -> str:
    """Liste als Feldinhalt (``Steuer/Werbungskosten, Haus``)."""
    return TRENNER.join(_liste(schlagwoerter))


def zusammenfuehren(auto, schlagwoerter) -> str:
    """Wert fuer ``pdf:Keywords``: automatische Stichwoerter, dann die Schlagwoerter des Nutzers."""
    return TRENNER.join(_liste(_liste(auto) + _liste(schlagwoerter), genau=True))


def mit_oberebenen(schlagwort: str) -> list[str]:
    """``Steuer/Werbungskosten/Fahrt`` -> ``[Steuer, Steuer/Werbungskosten, Steuer/Werbungskosten/Fahrt]``."""
    sauber = _saeubern(schlagwort or "")
    teile = sauber.split(EBENE) if sauber else []
    return [EBENE.join(teile[:i]) for i in range(1, len(teile) + 1)]


def passt(keywords, schlagwort: str) -> bool:
    """Traegt das Dokument ``schlagwort`` oder eine Unterebene davon? (Schreibweise genau.)"""
    gesucht = _saeubern(schlagwort)
    if not gesucht:
        return False
    return any(w == gesucht or w.startswith(gesucht + EBENE) for w in eigene(keywords))


def zaehlen(keyword_werte: Iterable) -> dict[str, int]:
    """Aus vielen ``pdf:Keywords``-Werten: jedes Schlagwort samt Oberebenen mit seiner Dokumentzahl."""
    anzahl: dict[str, int] = {}
    for wert in keyword_werte:
        stufen: set[str] = set()
        for wort in eigene(wert):
            stufen.update(mit_oberebenen(wort))
        for stufe in stufen:
            anzahl[stufe] = anzahl.get(stufe, 0) + 1
    return anzahl


def nur_bekannte(vorschlag, bekannte: Iterable[str]) -> list[str]:
    """Von der KI genannte Schlagwoerter auf die schon benutzten beschraenken (deren Schreibweise gilt)."""
    nach_klein = {b.casefold(): b for b in bekannte}
    erg = []
    for wort in _liste(vorschlag):
        treffer = nach_klein.get(wort.casefold())
        if treffer and treffer not in erg:
            erg.append(treffer)
    return erg


# --- Schon benutzte Schlagwoerter (Vorschlagsliste im Detail-Panel, Auswahl fuer die KI) ---
# Das Hauptfenster haengt hier den Suchindex ein (wie ``meldungen.konfigurieren``); ohne Quelle
# - etwa in Tests - gibt es keine Vorschlaege, und nichts greift auf die Daten des Nutzers zu.
_quelle = None


def quelle_setzen(funktion) -> None:
    """``funktion(haeufigste: int | None) -> list[str]`` liefert die benutzten Schlagwoerter; None haengt aus."""
    global _quelle
    _quelle = funktion


def benutzte(haeufigste: int | None = None) -> list[str]:
    """Schon benutzte Schlagwoerter samt Oberebenen; mit ``haeufigste`` nur die meistbenutzten."""
    if _quelle is None:
        return []
    try:
        return list(_quelle(haeufigste) or [])
    except Exception:
        return []

"""Sortierung der PDF-Kacheln (Issue #33) - Qt-frei.

Sechs Reihenfolgen: Name (natuerlich, ohne Gross-/Kleinschreibung), Datum
(Aenderungsdatum der Datei) und Groesse, jeweils auf- und absteigend.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable
from src.i18n import tr

# (id, Anzeigetext, Kriterium, absteigend)
SORT_OPTIONEN = (
    ("datum_ab", tr("Datum: neueste zuerst"), "datum", True),
    ("datum_auf", tr("Datum: älteste zuerst"), "datum", False),
    ("name_auf", tr("Name: A–Z"), "name", False),
    ("name_ab", tr("Name: Z–A"), "name", True),
    ("groesse_ab", tr("Größe: größte zuerst"), "groesse", True),
    ("groesse_auf", tr("Größe: kleinste zuerst"), "groesse", False),
)
STANDARD_SORTIERUNG = "datum_ab"  # bisheriges Verhalten (FileManager.get_pdf_files)

_ZAHLEN = re.compile(r"(\d+)")


def sortierung_id(wert) -> str:
    """Unbekannte oder fehlende Werte aus der Konfiguration -> Standard."""
    return wert if any(wert == o[0] for o in SORT_OPTIONEN) else STANDARD_SORTIERUNG


def natuerlicher_schluessel(name: str) -> list:
    """'Scan 10' nach 'Scan 2': Ziffernfolgen als Zahl, Rest klein geschrieben."""
    teile = _ZAHLEN.split(name.casefold())
    return [int(t) if i % 2 else t for i, t in enumerate(teile)]


def _stat(pfad: Path):
    try:
        return pfad.stat()
    except OSError:
        return None


def sortiere_pfade(pfade: Iterable[Path], sortierung: str) -> list[Path]:
    """Gibt die Pfade in der gewaehlten Reihenfolge zurueck (stabil, Name als Zweitschluessel)."""
    _, _, kriterium, absteigend = next(
        o for o in SORT_OPTIONEN if o[0] == sortierung_id(sortierung)
    )
    pfade = list(pfade)
    # Zweitschluessel Name (immer aufsteigend) -> erst danach nach Hauptkriterium
    pfade.sort(key=lambda p: natuerlicher_schluessel(p.name))
    if kriterium == "name":
        pfade.sort(key=lambda p: natuerlicher_schluessel(p.name), reverse=absteigend)
        return pfade

    def wert(p: Path):
        st = _stat(p)
        if st is None:
            return 0
        return st.st_mtime if kriterium == "datum" else st.st_size

    pfade.sort(key=wert, reverse=absteigend)
    return pfade

"""Sortierung der PDF-Kacheln (Issue #33) - Qt-frei.

Acht Reihenfolgen: Name (natuerlich, ohne Gross-/Kleinschreibung), Datum
(Aenderungsdatum der Datei), Datum im Dateinamen (Issue #296) und Groesse, jeweils
auf- und absteigend.
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping, Optional
from src.i18n import tr

# (id, Anzeigetext, Kriterium, absteigend)
SORT_OPTIONEN = (
    ("datum_ab", tr("Datum: neueste zuerst"), "datum", True),
    ("datum_auf", tr("Datum: älteste zuerst"), "datum", False),
    ("namensdatum_ab", tr("Datum im Namen: neueste zuerst"), "namensdatum", True),
    ("namensdatum_auf", tr("Datum im Namen: älteste zuerst"), "namensdatum", False),
    ("name_auf", tr("Name: A–Z"), "name", False),
    ("name_ab", tr("Name: Z–A"), "name", True),
    ("groesse_ab", tr("Größe: größte zuerst"), "groesse", True),
    ("groesse_auf", tr("Größe: kleinste zuerst"), "groesse", False),
)
STANDARD_SORTIERUNG = "datum_ab"  # bisheriges Verhalten (FileManager.get_pdf_files)

_ZAHLEN = re.compile(r"(\d+)")
# Belegdatum am Anfang des Namens: "2010-03-01_Rechnung.pdf" (Issue #296)
_NAMENSDATUM = re.compile(r"\s*(\d{4})-(\d{2})-(\d{2})(?!\d)")


def datum_aus_namen(name: str) -> Optional[float]:
    """Zeitstempel (Sekunden, UTC-Mitternacht) des Datums JJJJ-MM-TT am Namensanfang.

    None, wenn der Name nicht mit einem gueltigen Datum beginnt.
    """
    m = _NAMENSDATUM.match(name)
    if not m:
        return None
    try:
        tag = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:  # z. B. 2024-13-45
        return None
    # timegm statt datetime.timestamp(): klappt unter Windows auch vor 1970
    return float(calendar.timegm(tag.timetuple()))


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


def sortiere_pfade(
    pfade: Iterable[Path], sortierung: str, staende: Optional[Mapping[str, tuple[float, int]]] = None
) -> list[Path]:
    """Gibt die Pfade in der gewaehlten Reihenfolge zurueck (stabil, Name als Zweitschluessel).

    Args:
        staende: schon bekannte (Aenderungszeit, Groesse) je Dateiname, wenn alle Pfade im
            selben Ordner liegen (Ordner-Beobachtung, Issue #232). Fuer diese Dateien wird
            die Platte nicht gefragt.
    """
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
        if kriterium == "namensdatum":
            im_namen = datum_aus_namen(p.name)
            if im_namen is not None:
                return im_namen
            # Ohne Datum im Namen: nach dem Aenderungsdatum der Datei einreihen
        zeit = kriterium != "groesse"
        bekannt = staende.get(p.name) if staende else None
        if bekannt is not None:
            return bekannt[0] if zeit else bekannt[1]
        st = _stat(p)
        if st is None:
            return 0
        return st.st_mtime if zeit else st.st_size

    pfade.sort(key=wert, reverse=absteigend)
    return pfade

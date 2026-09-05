"""Dokumentdatum: finden, auswaehlen und Nutzereingaben parsen (Issue #132).

Bis v0.24 nahm ``PDFAnalyzer.extract_dates()`` das *juengste* Datum im Text
als Dokumentdatum - eine Frist, ein Eingangsstempel oder ein OCR-Lesefehler
mit spaeterem Jahr ueberschrieb damit das Briefdatum, und daraus wurde das
Steuerjahr abgeleitet. Hier steht die Auswahl an einer Stelle:

- :func:`find_dates` liefert alle Datumsangaben mit Position im Text.
- :func:`pick_document_date` waehlt das wahrscheinlichste Dokumentdatum:
  ein Datum hinter "Datum:", "Rechnungsdatum", ", den" oder "Stand" schlaegt
  alle anderen; Daten hinter "geboren", "gueltig bis", "faellig", "Frist",
  "Eingang" u.ae. zaehlen nur als Notnagel; bei Gleichstand gewinnt das erste
  Datum in Lesereihenfolge (Briefkopf), nicht das juengste.
- :func:`parse_user_date` macht aus markiertem oder getipptem Text
  ("12.3.2004", "12. Maerz 2004", "2004-03-12") ein ISO-Datum fuer das
  Feld "Datum" im Detail-Panel.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# Jahresbereich fuer Daten aus dem Dokumenttext (filtert OCR-Rauschen wie
# "1.2.1234"); Nutzereingaben duerfen aelter sein
MIN_TEXT_YEAR = 1990
MIN_USER_YEAR = 1900
MAX_YEAR = 2100

_MONTHS: dict[str, int] = {
    "januar": 1, "jan": 1,
    "februar": 2, "feb": 2,
    "märz": 3, "maerz": 3, "marz": 3, "mrz": 3, "mar": 3,
    "april": 4, "apr": 4,
    "mai": 5,
    "juni": 6, "jun": 6,
    "juli": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "okt": 10,
    "november": 11, "nov": 11,
    "dezember": 12, "dez": 12,
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))

# TT.MM.JJJJ, TT.MM.JJ, TT/MM/JJJJ - nicht mitten in laengeren Ziffernfolgen
_NUMERIC_RE = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4}|\d{2})(?!\d)")
# JJJJ-MM-TT (ISO, auch am Anfang von "2004-03-12 00:00:00" aus dem Cache)
_ISO_RE = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
# 15. Januar 2025, 15 Jan 2025, 15. Maerz 2004
_TEXT_RE = re.compile(
    r"(?<!\d)(\d{1,2})\.?\s*(" + _MONTH_ALT + r")\.?\s+(\d{4})(?!\d)",
    re.IGNORECASE,
)

# Beschriftungen unmittelbar vor dem Datum (Fenster von _LABEL_WINDOW Zeichen)
_LABEL_WINDOW = 30
_POSITIVE_LABEL_RE = re.compile(
    r"(datum|,\s*den|stand)\s*:?\s*$",
    re.IGNORECASE,
)
_NEGATIVE_LABEL_RE = re.compile(
    r"(geboren|geb\.|geburtsdatum|g[üue]+ltig|bis(\s+zum)?|frist|f[äae]+llig|zahlbar|"
    r"zahlungsziel|sp[äae]+testens|termin|eingang|eingegangen)\s*(am|zum)?\s*:?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FoundDate:
    """Ein im Text gefundenes Datum mit seiner Position."""

    pos: int
    end: int
    value: datetime


def _year(raw: str, min_year: int) -> Optional[int]:
    year = int(raw)
    if len(raw) == 2:
        year += 2000 if year < 50 else 1900
    if min_year <= year <= MAX_YEAR:
        return year
    return None


def _make(year: Optional[int], month: int, day: int) -> Optional[datetime]:
    if year is None:
        return None
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def find_dates(text: str, min_year: int = MIN_TEXT_YEAR) -> list[FoundDate]:
    """Alle Datumsangaben im Text, nach Position sortiert (ungueltige fallen weg)."""
    if not text:
        return []
    found: list[FoundDate] = []
    for m in _NUMERIC_RE.finditer(text):
        value = _make(_year(m.group(3), min_year), int(m.group(2)), int(m.group(1)))
        if value:
            found.append(FoundDate(m.start(), m.end(), value))
    for m in _ISO_RE.finditer(text):
        value = _make(_year(m.group(1), min_year), int(m.group(2)), int(m.group(3)))
        if value:
            found.append(FoundDate(m.start(), m.end(), value))
    for m in _TEXT_RE.finditer(text):
        month = _MONTHS.get(m.group(2).lower())
        if month:
            value = _make(_year(m.group(3), min_year), month, int(m.group(1)))
            if value:
                found.append(FoundDate(m.start(), m.end(), value))
    found.sort(key=lambda f: f.pos)
    return found


def _label_score(text: str, found: FoundDate) -> int:
    """+2 fuer eine Dokumentdatum-Beschriftung davor, -2 fuer Frist/Geburt & Co."""
    before = text[max(0, found.pos - _LABEL_WINDOW):found.pos]
    if _POSITIVE_LABEL_RE.search(before):
        return 2
    if _NEGATIVE_LABEL_RE.search(before):
        return -2
    return 0


def pick_document_date(text: str, found: list[FoundDate] | None = None) -> Optional[datetime]:
    """Wahrscheinlichstes Dokumentdatum aus dem Text (None, wenn keins gefunden)."""
    if found is None:
        found = find_dates(text)
    if not found:
        return None
    best = max(found, key=lambda f: (_label_score(text, f), -f.pos))
    return best.value


def ordered_dates(text: str) -> list[datetime]:
    """Dokumentdatum zuerst, danach die uebrigen (ohne Doppelte) absteigend.

    Das ist die Reihenfolge, die ``PDFAnalyzer.extract_dates()`` liefert und
    ueber ``dates[0]`` ueberall als "erkanntes Datum" benutzt wird.
    """
    found = find_dates(text)
    best = pick_document_date(text, found)
    if best is None:
        return []
    others = sorted({f.value for f in found} - {best}, reverse=True)
    return [best] + others


def parse_user_date(text: str) -> Optional[str]:
    """Markierten/getippten Text als ISO-Datum ``JJJJ-MM-TT`` (oder None).

    Nimmt das erste Datum im Text; "01.03.2004 bis 31.03.2004" ergibt also
    den 1. Maerz. Jahre ab 1900 sind erlaubt, zweistellige werden ergaenzt.
    """
    found = find_dates(text or "", min_year=MIN_USER_YEAR)
    if not found:
        return None
    return found[0].value.strftime("%Y-%m-%d")


def is_iso_date(text: str) -> bool:
    """True fuer genau ``JJJJ-MM-TT`` (gueltiges Datum)."""
    if not text or len(text) != 10:
        return False
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return True
    except ValueError:
        return False

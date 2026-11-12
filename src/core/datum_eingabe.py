"""Intelligente Datumseingabe fuer Suche und Detailansicht (Issue #161).

Statt Kalender-Felder gibt es Textfelder, in die man frei tippt:

- :func:`parse_zeitraum` liest einen Zeitraum ("2004", "12/2024", "Jan 2024",
  "Q2 2024", "2004-2006", "ab 2020", "bis 12/2023", ...) und liefert
  ``Zeitraum(von, bis)``; ``None`` heisst "offen". Ein leeres Feld ist
  ``Zeitraum(None, None)`` = keine Grenze.
- :func:`parse_tag` liest genau einen Tag ("3.5.24", "3. Mai 2024", ...).
- :func:`beschreibe` macht daraus die graue Hinweiszeile ("= 01.01.2004 – ...").

Eine Einzelangabe bedeutet genau ihren Zeitraum ("2024" = 01.01. bis 31.12.2024);
ein Bereich nimmt den Anfang der linken und das Ende der rechten Angabe.
Unlesbares ergibt ein :class:`Fehler` mit fertigem Hinweistext. Kein Qt.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import NamedTuple, Optional, Union
from src.i18n import tr

MIN_JAHR = 1900
MAX_JAHR = 2100

HINWEIS_ZEITRAUM = tr("nicht erkannt – z. B. 2024, 12/2024, Jan 2024, 2004-2006")
HINWEIS_TAG = tr("nicht erkannt – z. B. 3.5.2024, 3.5.24 oder 3. Mai 2024")
HINWEIS_TAG_UNGENAU = tr("bitte einen ganzen Tag angeben – z. B. 3.5.2024")


class Zeitraum(NamedTuple):
    """Erster und letzter Tag (einschliesslich); ``None`` = offen."""

    von: Optional[date]
    bis: Optional[date]


@dataclass(frozen=True)
class Fehler:
    """Eingabe nicht lesbar; ``meldung`` ist der Hinweis fuer die Oberflaeche."""

    meldung: str


_MONATE: dict[str, int] = {
    "januar": 1, "jan": 1, "january": 1,
    "februar": 2, "feb": 2, "february": 2,
    "märz": 3, "maerz": 3, "marz": 3, "mrz": 3, "mär": 3, "maer": 3, "mar": 3, "march": 3,
    "april": 4, "apr": 4,
    "mai": 5, "may": 5,
    "juni": 6, "jun": 6, "june": 6,
    "juli": 7, "jul": 7, "july": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "okt": 10, "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "dezember": 12, "dez": 12, "december": 12, "dec": 12,
}
_MONAT_ALT = "|".join(sorted(_MONATE, key=len, reverse=True))
_J = r"(\d{4}|\d{2})"

_RE_JAHR = re.compile(r"^(\d{4})$")
_RE_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_RE_TAG_VOLL = re.compile(r"^(\d{1,2})[./-]\s*(\d{1,2})[./-]\s*" + _J + "$")
_RE_TAG_MONAT = re.compile(r"^(\d{1,2})\.\s*(\d{1,2})\.$")
_RE_MONAT_JAHR = re.compile(r"^(\d{1,2})\s*[./-]\s*" + _J + "$")
_RE_MONATSNAME = re.compile(r"^(" + _MONAT_ALT + r")\.?\s*" + _J + "$")
_RE_TAG_NAME = re.compile(r"^(\d{1,2})\.?\s*(" + _MONAT_ALT + r")\.?\s*" + _J + "$")
_RE_QUARTAL_Q = re.compile(r"^q\s*([1-4])\s*[/ ]?\s*" + _J + "$")
_RE_QUARTAL_WORT = re.compile(r"^([1-4])\.?\s*(?:quartal|quart\.?|qu\.?|q)\s*" + _J + "$")


def _jahr(roh: str, heute: date) -> Optional[int]:
    """Vierstelliges Jahr pruefen, zweistelliges ergaenzen (00 bis heute+1 -> 20xx)."""
    zahl = int(roh)
    if len(roh) == 2:
        zahl += 2000 if zahl <= heute.year % 100 + 1 else 1900
    return zahl if MIN_JAHR <= zahl <= MAX_JAHR else None


def _monat(jahr: Optional[int], monat: int) -> Optional[Zeitraum]:
    if jahr is None or not 1 <= monat <= 12:
        return None
    return Zeitraum(date(jahr, monat, 1), date(jahr, monat, calendar.monthrange(jahr, monat)[1]))


def _tag(jahr: Optional[int], monat: int, tag: int) -> Optional[Zeitraum]:
    if jahr is None:
        return None
    try:
        d = date(jahr, monat, tag)
    except ValueError:
        return None
    return Zeitraum(d, d)


def _normal(text: str) -> str:
    t = (text or "").lower().replace("–", "-").replace("—", "-").replace("−", "-")
    return re.sub(r"\s+", " ", t).strip()


def _einzel(text: str, heute: date) -> Optional[Zeitraum]:
    """Eine einzelne Angabe (Tag, Monat, Quartal, Jahr) als ihr voller Zeitraum."""
    t = _normal(text)
    if not t:
        return None
    if m := _RE_JAHR.match(t):
        j = _jahr(m[1], heute)
        return Zeitraum(date(j, 1, 1), date(j, 12, 31)) if j else None
    if m := _RE_ISO.match(t):
        return _tag(_jahr(m[1], heute), int(m[2]), int(m[3]))
    if m := _RE_TAG_VOLL.match(t):
        return _tag(_jahr(m[3], heute), int(m[2]), int(m[1]))
    if m := _RE_TAG_MONAT.match(t):
        return _tag(heute.year, int(m[2]), int(m[1]))
    if m := _RE_TAG_NAME.match(t):
        return _tag(_jahr(m[3], heute), _MONATE[m[2]], int(m[1]))
    if m := _RE_MONAT_JAHR.match(t):
        return _monat(_jahr(m[2], heute), int(m[1]))
    if m := _RE_MONATSNAME.match(t):
        return _monat(_jahr(m[2], heute), _MONATE[m[1]])
    quartal = _RE_QUARTAL_Q.match(t) or _RE_QUARTAL_WORT.match(t)
    if quartal:
        q, j = int(quartal[1]), _jahr(quartal[2], heute)
        if j is None:
            return None
        erster = _monat(j, 3 * q - 2)
        letzter = _monat(j, 3 * q)
        return Zeitraum(erster.von, letzter.bis)
    return None


def _bereich(links: Zeitraum, rechts: Zeitraum) -> Zeitraum:
    """Anfang der linken, Ende der rechten Angabe; vertauschte Reihenfolge wird getauscht."""
    if links.von > rechts.von:
        links, rechts = rechts, links
    return Zeitraum(links.von, rechts.bis)


def _bereich_text(t: str, heute: date) -> Optional[Zeitraum]:
    """"A bis B" bzw. "A - B" (Bindestrich oder Gedankenstrich)."""
    if " bis " in t:
        teile = t.split(" bis ")
        if len(teile) == 2:
            a, b = _einzel(teile[0], heute), _einzel(teile[1], heute)
            return _bereich(a, b) if a and b else None
        return None
    # Der Bindestrich ist auch Datumstrenner ("12-2024", "2024-05-03"): jede
    # Trennstelle ausprobieren, in der beide Seiten fuer sich lesbar sind;
    # eine Trennstelle mit Leerzeichen auf beiden Seiten gewinnt.
    treffer: list[tuple[bool, Zeitraum]] = []
    for i, zeichen in enumerate(t):
        if zeichen != "-":
            continue
        a, b = _einzel(t[:i], heute), _einzel(t[i + 1:], heute)
        if a and b:
            frei = 0 < i < len(t) - 1 and t[i - 1] == " " and t[i + 1] == " "
            treffer.append((frei, _bereich(a, b)))
    mit_abstand = [z for frei, z in treffer if frei]
    kandidaten = mit_abstand or [z for _frei, z in treffer]
    return kandidaten[0] if len(set(kandidaten)) == 1 else None


def parse_zeitraum(text: str, heute: Optional[date] = None) -> Union[Zeitraum, Fehler]:
    """Zeitraum aus freier Eingabe; leer = ``Zeitraum(None, None)``."""
    heute = heute or date.today()
    t = _normal(text)
    if not t:
        return Zeitraum(None, None)
    fehler = Fehler(HINWEIS_ZEITRAUM)

    if (z := _einzel(t, heute)) is not None:
        return z
    # Offene Bereiche
    for wort in ("ab ", "seit "):
        if t.startswith(wort):
            rest = t[len(wort):]
            if (z := _einzel(rest, heute)) is not None:
                return Zeitraum(z.von, None)
            z = _bereich_text(rest, heute)
            return z if z is not None else fehler
    if t.startswith("bis "):
        z = _einzel(t[4:], heute)
        return Zeitraum(None, z.bis) if z is not None else fehler
    if " bis " in t:
        z = _bereich_text(t, heute)
        return z if z is not None else fehler
    if t.endswith("-") and (z := _einzel(t[:-1], heute)) is not None:
        return Zeitraum(z.von, None)
    if t.startswith("-") and (z := _einzel(t[1:], heute)) is not None:
        return Zeitraum(None, z.bis)
    z = _bereich_text(t, heute)
    return z if z is not None else fehler


def parse_tag(text: str, heute: Optional[date] = None) -> Union[date, Fehler]:
    """Genau ein Tag ("3.5.24", "03.05.2024", "3. Mai 2024", "2024-05-03")."""
    heute = heute or date.today()
    z = _einzel(text, heute)
    if z is None:
        return Fehler(HINWEIS_TAG)
    if z.von != z.bis:
        return Fehler(HINWEIS_TAG_UNGENAU)
    return z.von


def tag_text(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def formatiere(von: Optional[date], bis: Optional[date]) -> str:
    """Grenzen als wieder lesbare Eingabe ("01.01.2024 bis 31.03.2024", "ab ...")."""
    if von and bis:
        return tag_text(von) if von == bis else f"{tag_text(von)} bis {tag_text(bis)}"
    if von:
        return f"ab {tag_text(von)}"
    if bis:
        return f"bis {tag_text(bis)}"
    return ""


def beschreibe(ergebnis: Union[Zeitraum, date, Fehler]) -> str:
    """Hinweiszeile zur Deutung ("= 01.01.2004 – 31.12.2006", "= ab 01.01.2020")."""
    if isinstance(ergebnis, Fehler):
        return ergebnis.meldung
    if isinstance(ergebnis, date):
        return f"= {tag_text(ergebnis)}"
    von, bis = ergebnis
    if von and bis:
        return f"= {tag_text(von)}" if von == bis else f"= {tag_text(von)} – {tag_text(bis)}"
    if von:
        return tr("= ab {0}").format(tag_text(von))
    if bis:
        return tr("= bis {0}").format(tag_text(bis))
    return ""

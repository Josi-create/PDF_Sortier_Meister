"""Auswahllisten fuer Metadaten-Felder im Detail-Panel (Issue #110)."""
from __future__ import annotations

import re
from typing import Iterable

# Kategorien aus dem KI-Antwortschema - Rueckfall, solange die eigene
# Sammlung noch keine 10 verschiedenen Kategorien hergibt
DEFAULT_CATEGORIES: tuple[str, ...] = (
    "Rechnung", "Vertrag", "Steuer", "Versicherung", "Bank",
    "Gehalt", "Arzt", "Energie", "Sonstiges",
)


def category_choices(top_from_db: Iterable[str], limit: int = 10) -> list[str]:
    """Die haeufigsten Kategorien der Sammlung, mit Standardwerten aufgefuellt.

    Reihenfolge: erst die eigenen (nach Haeufigkeit), dann Standardwerte;
    Doppelte (Gross-/Kleinschreibung egal) erscheinen einmal.
    """
    result: list[str] = []
    seen: set[str] = set()
    for name in list(top_from_db) + list(DEFAULT_CATEGORIES):
        name = (name or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        result.append(name)
        if len(result) >= limit:
            break
    return result


_YEAR_RE = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
_CURRENCY_RE = re.compile(r"(?i)\s*(€|eur|euro|\$|usd|chf)\s*")


def normalize_for_field(field_key: str, text: str) -> str:
    """Markierten Text fuer ein Metadaten-Feld aufbereiten (Issue #109).

    Leerraum wird immer zusammengefasst; je nach Feld faellt Beiwerk weg:
    IBAN ohne Leerzeichen, Betraege ohne Waehrungszeichen, MwSt ohne "%",
    Steuerjahr als vierstellige Jahreszahl.
    """
    text = " ".join((text or "").split())
    if field_key == "iban":
        return text.replace(" ", "").upper()
    if field_key in ("betrag_netto", "betrag_brutto"):
        return _CURRENCY_RE.sub(" ", text).strip(" :")
    if field_key == "mwst_satz":
        return text.replace("%", "").strip(" :")
    if field_key == "steuerjahr":
        match = _YEAR_RE.search(text)
        return match.group(0) if match else text
    if field_key == "waehrung":
        return text.upper().replace("€", "EUR")
    return text


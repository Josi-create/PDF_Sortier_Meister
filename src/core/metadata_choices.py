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


RECENT_CATEGORIES_KEY = "recent_categories"
RECENT_CATEGORIES_MAX = 15
# Aus dem Suchindex nur "echte" Kategorien: alte KI-Ausrutscher wie
# "Nebenkosten Schmutzwassergebuehr" sind lang und mehrwortig
MAX_INDEX_CATEGORY_LEN = 20
MAX_INDEX_CATEGORY_WORDS = 2


def remember_category(recent: Iterable[str] | None, category: str) -> list[str]:
    """Kategorie nach vorn in die Zuletzt-verwendet-Liste (max. RECENT_CATEGORIES_MAX)."""
    category = (category or "").strip()
    result = [c for c in (recent or []) if isinstance(c, str) and c.strip()]
    if not category:
        return result
    result = [c for c in result if c.strip().lower() != category.lower()]
    return ([category] + result)[:RECENT_CATEGORIES_MAX]


def _looks_like_category(name: str) -> bool:
    return len(name) <= MAX_INDEX_CATEGORY_LEN and len(name.split()) <= MAX_INDEX_CATEGORY_WORDS


def category_choices(
    recent: Iterable[str] | None,
    top_from_db: Iterable[str] | None = None,
    limit: int = 10,
) -> list[str]:
    """Aufklappliste der Kategorie (Issue #110).

    Reihenfolge: zuletzt vom Nutzer verwendete Kategorien (neueste zuerst),
    dann die haeufigsten aus dem Suchindex (nur kurze, kategorie-artige
    Namen), dann Standardwerte. Doppelte (Gross-/Kleinschreibung egal)
    erscheinen einmal.
    """
    candidates = list(recent or [])
    candidates += [n for n in (top_from_db or []) if n and _looks_like_category(n.strip())]
    candidates += list(DEFAULT_CATEGORIES)
    result: list[str] = []
    seen: set[str] = set()
    for name in candidates:
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
    Steuerjahr als vierstellige Jahreszahl, Datum als JJJJ-MM-TT (Issue #132;
    unlesbares bleibt stehen, damit das Feld die Eingabe zeigt).
    """
    text = " ".join((text or "").split())
    if field_key == "buchungsdatum":
        from src.core.document_date import parse_user_date
        return parse_user_date(text) or text
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


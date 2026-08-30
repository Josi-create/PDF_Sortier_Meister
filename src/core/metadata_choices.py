"""Auswahllisten fuer Metadaten-Felder im Detail-Panel (Issue #110)."""
from __future__ import annotations

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

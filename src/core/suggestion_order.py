"""Rangfolge der Dateinamen-Vorschlaege im Detail-Panel (Issue #106).

Jeder Vorschlag hat eine *Art* (``kind``): KI-Vorschlag, ein bestimmtes
Dateinamen-Muster, „Automatisch erkannt“ usw. Die Liste im Detail-Panel ist
nach Art sortiert; die zuletzt vom Nutzer angeklickte Art steht beim naechsten
Dokument ganz oben und ist damit der Vorschlag, der ins Feld
„Neuer Dateiname“ uebernommen wird. Die Rangfolge liegt in der Config unter
``suggestion_kind_order`` (Liste von Art-Schluesseln, vorne = oben).
"""
from __future__ import annotations

from typing import Iterable, Sequence, TypeVar

from src.core.filename_placeholders import pattern_choices

CONFIG_KEY = "suggestion_kind_order"

KIND_KI = "ki"
KIND_LEARNED = "learned"
KIND_AUTO = "auto"
KIND_DATE_CATEGORY = "date_category"
KIND_CATEGORY_NUMBER = "category_number"
KIND_DATE = "date"
KIND_OTHER = "other"
PATTERN_PREFIX = "pattern:"

T = TypeVar("T")


def pattern_kind(pattern: str) -> str:
    """Art-Schluessel fuer ein Dateinamen-Muster (stabil ueber Sitzungen)."""
    return PATTERN_PREFIX + (pattern or "")


def kind_from_reason(reason: str) -> str:
    """Leitet die Art eines Vorschlags aus seiner Begruendung ab.

    Die Begruendungen werden an mehreren Stellen erzeugt (``rename_dialog``,
    ``main_window``, Detail-Panel); hier ist die einzige Stelle, die sie
    auf Arten abbildet.
    """
    reason = (reason or "").strip()
    if reason.startswith("KI"):
        return KIND_KI
    if reason.startswith("Gelernt"):
        return KIND_LEARNED
    if reason == "Automatisch erkannt":
        return KIND_AUTO
    if reason.startswith("Datum + Kategorie"):
        return KIND_DATE_CATEGORY
    if reason == "Kategorie + Nummer":
        return KIND_CATEGORY_NUMBER
    if reason == "Nur Datum":
        return KIND_DATE
    return KIND_OTHER


def default_order(config_pattern: str = "") -> list[str]:
    """Standard-Rangfolge, solange der Nutzer noch nichts gewaehlt hat.

    KI zuerst, dann das Muster aus den Einstellungen, die uebrigen Vorlagen,
    danach die einfachen Vorschlaege aus der Textanalyse.
    """
    order = [KIND_KI]
    # pattern_choices liefert das Einstellungs-Muster an zweiter Stelle,
    # wenn es keiner Vorlage entspricht - sonst steht es unter den Vorlagen
    choices = [p for _label, p in pattern_choices(config_pattern) if p]
    if config_pattern and config_pattern in choices:
        choices.remove(config_pattern)
        choices.insert(0, config_pattern)
    order.extend(pattern_kind(p) for p in choices)
    order.extend([KIND_LEARNED, KIND_AUTO, KIND_DATE_CATEGORY,
                  KIND_CATEGORY_NUMBER, KIND_DATE, KIND_OTHER])
    return order


def effective_order(saved: Iterable[str] | None, config_pattern: str = "") -> list[str]:
    """Gespeicherte Rangfolge, ergaenzt um alle Arten, die darin noch fehlen."""
    order: list[str] = []
    for kind in list(saved or []) + default_order(config_pattern):
        if isinstance(kind, str) and kind and kind not in order:
            order.append(kind)
    return order


def promote(order: Sequence[str], kind: str) -> list[str]:
    """Setzt ``kind`` an die Spitze; alle anderen ruecken eine Stufe nach unten."""
    return [kind] + [k for k in order if k != kind]


def sort_by_kind(items: Sequence[tuple[T, str]], order: Sequence[str]) -> list[tuple[T, str]]:
    """Sortiert ``(objekt, art)``-Paare stabil nach der Rangfolge.

    Unbekannte Arten landen hinten, in ihrer bisherigen Reihenfolge.
    """
    rank = {kind: idx for idx, kind in enumerate(order)}
    unknown = len(rank)
    return sorted(items, key=lambda pair: rank.get(pair[1], unknown))

"""Bekannte Korrespondenten im Dokumenttext wiederfinden (Issue #109).

Uebernimmt der Nutzer einen Namen aus der Vorschau als Korrespondent, wird
er in der Korrespondenten-Verwaltung angelegt. Bei spaeteren Dokumenten, in
deren Text dieser Name (oder ein Alias) vorkommt, wird er automatisch
vorgeschlagen - die eigene Schreibweise des Nutzers schlaegt dabei den
KI-Vorschlag.
"""
from __future__ import annotations

import re
from typing import Iterable, Mapping

MIN_NAME_LENGTH = 3


def _candidates(entry: Mapping) -> list[str]:
    names = [str(entry.get("name") or "")]
    aliases = entry.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    names.extend(str(a) for a in aliases)
    return [n.strip() for n in names if n and len(n.strip()) >= MIN_NAME_LENGTH]


def _occurs(name: str, text_lower: str) -> bool:
    """Name als ganzes Wort/Phrase im Text (Gross-/Kleinschreibung egal)."""
    pattern = r"(?<![\w-])" + re.escape(name.lower()) + r"(?![\w-])"
    return re.search(pattern, text_lower) is not None


def find_known_korrespondent(text: str, entries: Iterable[Mapping]) -> str | None:
    """Anzeigename des bekannten Korrespondenten, der im Text vorkommt.

    Bei mehreren Treffern gewinnt der laengste passende Name/Alias (der
    spezifischere), bei Gleichstand der zuerst gelistete Eintrag (die Liste
    kommt nach Haeufigkeit sortiert aus der Datenbank).
    """
    text_lower = (text or "").lower()
    if not text_lower.strip():
        return None
    best: tuple[int, int, str] | None = None
    for idx, entry in enumerate(entries):
        display = str(entry.get("name") or "").strip()
        if not display:
            continue
        for candidate in _candidates(entry):
            if _occurs(candidate, text_lower):
                key = (-len(candidate), idx, display)
                if best is None or key < best:
                    best = key
                break
    return best[2] if best else None

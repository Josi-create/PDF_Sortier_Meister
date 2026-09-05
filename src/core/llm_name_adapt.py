"""
KI-Dateinamen an geaenderte Metadaten anpassen (Issue #113).

Ein KI-Vorschlag wie ``2026-03-15_Sonstiges_Muster.pdf`` traegt die Kategorie
nur als Text. Traegt der Nutzer im Detail-Panel eine bessere Kategorie oder
einen anderen Korrespondenten ein, wird das entsprechende Wort im Namen
ersetzt - der Vorschlag bleibt sonst unveraendert. Nichtssagende Platzhalter
(``Sonstiges``, ``Unbekannt``) werden auch dann ersetzt, wenn die KI keine
Kategorie mitgeliefert hat.

Reine Funktionen ohne Qt, damit sie ohne GUI testbar sind.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import re

# Woerter, die im Dateinamen nichts aussagen und durch eine vom Nutzer
# eingetragene Kategorie ersetzt werden duerfen
FALLBACK_CATEGORY_TOKENS = ("Sonstiges", "Unbekannt")

# Zeichen, die innerhalb eines Tokens vorkommen (alles andere trennt Tokens)
_WORD = r"A-Za-z0-9ÄÖÜäöüß"


def _variants(value: str) -> list[str]:
    """Schreibweisen, in denen ein Metadaten-Wert im Dateinamen stehen kann."""
    value = value.strip()
    if not value:
        return []
    seen: list[str] = []
    for v in (value, value.replace(" ", "_"), value.replace(" ", "-")):
        if v and v not in seen:
            seen.append(v)
    return seen


def _for_filename(value: str, filename: str) -> str:
    """Neuen Wert an den Stil des Dateinamens anpassen (Leerzeichen -> _)."""
    value = value.strip()
    if " " in value and " " not in filename:
        return value.replace(" ", "_")
    return value


def replace_token(filename: str, old: str, new: str) -> str:
    """Ersetzt ``old`` als ganzes Token im Dateinamen durch ``new``.

    Token-Grenzen sind ``_``, ``-``, Leerzeichen, Anfang/Ende und ``.pdf``;
    Gross-/Kleinschreibung ist egal. ``Rechnung`` trifft also nicht in
    ``Rechnungen``. Mehrwortige Werte werden in allen Schreibweisen
    (Leerzeichen, ``_``, ``-``) gefunden.
    """
    if not old or not new or not filename:
        return filename
    replacement = _for_filename(new, filename)
    for variant in _variants(old):
        pattern = rf"(?<![{_WORD}]){re.escape(variant)}(?![{_WORD}])"
        filename, count = re.subn(pattern, lambda _m: replacement, filename, flags=re.IGNORECASE)
        if count:
            break
    return filename


def adapt_llm_filename(filename: str, llm_metadata: dict | None, current: dict | None) -> str:
    """Zieht Kategorie und Korrespondent eines KI-Namens nach den aktuellen Feldern nach.

    Args:
        filename: KI-Vorschlag, z.B. ``2026-03-15_Sonstiges_Muster.pdf``
        llm_metadata: Metadaten, die die KI zu diesem Namen geliefert hat
        current: Aktuelle Feldwerte im Panel (``subject``, ``korrespondent``)

    Returns:
        Angepasster Name; unveraendert, wenn nichts zu ersetzen ist.
    """
    if not filename:
        return filename
    llm_metadata = llm_metadata or {}
    current = current or {}
    result = filename

    for key in ("subject", "korrespondent"):
        new = str(current.get(key, "") or "").strip()
        old = str(llm_metadata.get(key, "") or "").strip()
        if not new:
            continue
        if old and old.lower() != new.lower():
            result = replace_token(result, old, new)
        if key == "subject":
            # Nichtssagendes Wort im Namen -> durch die echte Kategorie ersetzen,
            # auch wenn die KI die Kategorie nicht (oder als "Sonstiges") lieferte
            for token in FALLBACK_CATEGORY_TOKENS:
                if token.lower() != new.lower():
                    result = replace_token(result, token, new)
    return result

"""Beispiele aus der Umbenennungs-Historie fuer den KI-Prompt.

Frueher wurden alte Dateinamen als eigene „Gelernt“-Vorschlaege gezeigt -
ein fremder Dateiname ist fuer das aktuelle Dokument aber nie der richtige.
Stattdessen bekommt die KI die Namen, die der Nutzer fuer *wirklich
aehnliche* Dokumente gewaehlt hat, als Stil-Beispiele in den Prompt. Was der
Nutzer waehlt oder korrigiert, landet wieder in der Historie und praegt den
naechsten Vorschlag - das Lernen wird so iterativ.

Aehnlich heisst hier: Namensbestandteile des alten Dateinamens (Firma,
Person, Betreff) kommen im Text des neuen Dokuments vor, oder mindestens
zwei Stichwoerter stimmen ueberein. Ein einzelnes gemeinsames Wort wie
„rechnung“ reicht nicht.
"""
from __future__ import annotations

import re
from typing import Iterable, Protocol, Sequence, TypeVar

_TOKEN_RE = re.compile(r"[A-Za-zÄÖÜäöüß]{4,}")

# Woerter, die in fast jedem Dateinamen stehen und nichts ueber Aehnlichkeit sagen
_GENERIC_TOKENS = frozenset({
    "rechnung", "rechnungen", "beleg", "belege", "vertrag", "brief", "schreiben",
    "dokument", "scan", "sonstiges", "mail", "email", "korrespondenz", "unbekannt",
    "datum", "info", "information", "kopie", "seite", "seiten", "sehr", "geehrte",
    "ueber", "uebermittlung", "zur", "und", "der", "die", "das", "fuer", "vom",
    # Kategorien aus dem KI-Schema - stehen in vielen Namen, identifizieren nichts
    "bank", "steuer", "versicherung", "gehalt", "arzt", "energie", "vertraege",
})

# Punkte je Treffer: Namensbestandteil im Text wiegt doppelt so viel wie ein
# gemeinsames Stichwort; ab MIN_SCORE gilt ein Eintrag als aehnlich
NAME_HIT_WEIGHT = 2
KEYWORD_HIT_WEIGHT = 1
MIN_SCORE = 2
MAX_TEXT_CHARS = 20000


class HistoryEntry(Protocol):
    new_filename: str
    keywords: str | list[str] | None


T = TypeVar("T", bound=HistoryEntry)


def name_tokens(filename: str) -> set[str]:
    """Aussagekraeftige Woerter eines Dateinamens (ohne Datum, Kuerzel, Fuellwoerter)."""
    stem = re.sub(r"\.pdf$", "", filename or "", flags=re.IGNORECASE)
    tokens = {t.lower() for t in _TOKEN_RE.findall(stem)}
    return {t for t in tokens if t not in _GENERIC_TOKENS}


def _keyword_set(keywords: str | Iterable[str] | None) -> set[str]:
    if not keywords:
        return set()
    if isinstance(keywords, str):
        keywords = keywords.split(",")
    return {k.strip().lower() for k in keywords if k and k.strip()}


def score_example(entry_filename: str, entry_keywords, text: str, keywords) -> int:
    """Wie gut passt ein Historien-Eintrag zum aktuellen Dokument? (0 = gar nicht)"""
    # Ganze Woerter vergleichen: "bank" darf nicht in "Commerzbank" treffen
    text_words = {w.lower() for w in _TOKEN_RE.findall((text or "")[:MAX_TEXT_CHARS])}
    name_hits = len(name_tokens(entry_filename) & text_words)
    keyword_hits = len(_keyword_set(entry_keywords) & _keyword_set(keywords))
    return NAME_HIT_WEIGHT * name_hits + KEYWORD_HIT_WEIGHT * keyword_hits


def rank_examples(entries: Sequence[T], text: str, keywords, limit: int = 5) -> list[T]:
    """Die passendsten Eintraege, beste zuerst; bei Gleichstand bleibt die
    Eingabe-Reihenfolge (= neueste zuerst) erhalten. Doppelte Dateinamen
    erscheinen einmal."""
    scored: list[tuple[int, int, T]] = []
    for idx, entry in enumerate(entries):
        score = score_example(entry.new_filename, entry.keywords, text, keywords)
        if score >= MIN_SCORE:
            scored.append((score, idx, entry))
    scored.sort(key=lambda t: (-t[0], t[1]))

    seen: set[str] = set()
    result: list[T] = []
    for _score, _idx, entry in scored:
        key = (entry.new_filename or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(entry)
        if len(result) >= limit:
            break
    return result


def describe_examples_for_prompt(filenames: Sequence[str]) -> str:
    """Prompt-Abschnitt mit den Beispiel-Dateinamen; leer ohne Beispiele."""
    names = [n for n in filenames if n]
    if not names:
        return ""
    lines = [
        "",
        "SO HAT DER NUTZER ÄHNLICHE DOKUMENTE ZULETZT BENANNT:",
    ]
    lines.extend(f"- {n}" for n in names)
    lines.append(
        "Richte Aufbau, Reihenfolge, Abkürzungen und Schreibweisen von Namen daran aus. "
        "Datum, Betreff und Inhalt kommen aber aus DIESEM Dokument - nicht abschreiben."
    )
    return "\n".join(lines)

"""Gleiche Namensvorschlaege im Stapel per KI unterscheiden (Issue #221).

Beim Stapel-Umbenennen/-Verschieben (Issue #218) benennt die KI jede Datei fuer
sich. Aehnliche Schreiben desselben Absenders (z.B. vier Monatsabrechnungen fuer
Vorderhaus, Hinterhaus, Garten ...) bekommen dann denselben Namen, und das
Programm haengt nur " (1)", " (2)" an. Hier fragt ein zusaetzlicher KI-Aufruf je
Gruppe gleicher Namen, was die Dokumente unterscheidet; das Wort kommt vor die
Endung (``..._Hinterhaus.pdf``).

Qt-frei; der Aufruf laeuft ueber :meth:`LLMProvider.answer_with_context`, das
alle Anbieter koennen.
"""
from __future__ import annotations

import json
import re
from pathlib import PurePath
from typing import Optional, Sequence

TEXT_JE_DOKUMENT = 1500  # Zeichen Textanfang je Dokument im Prompt
WORT_MAX = 30  # Zeichen je Unterscheidungswort

_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})


def doppelte_gruppen(namen: Sequence[Optional[str]]) -> list[list[int]]:
    """Indizes gleicher Namen (ohne Gross-/Kleinschreibung), nur Gruppen ab zwei; None zaehlt nicht."""
    gruppen: dict[str, list[int]] = {}
    for i, name in enumerate(namen):
        if name:
            gruppen.setdefault(name.casefold(), []).append(i)
    return [g for g in gruppen.values() if len(g) > 1]


def wort_bereinigen(wort) -> Optional[str]:
    """Macht aus der KI-Antwort ein dateinamentaugliches Wort (wie die Namen sonst: ae statt ä)."""
    text = str(wort or "").strip().translate(_UMLAUTE)
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    text = text[:WORT_MAX].strip("-")
    return text or None


def wort_einfuegen(name: str, wort: str) -> str:
    """``a_b.pdf`` + ``Hinterhaus`` -> ``a_b_Hinterhaus.pdf``."""
    p = PurePath(name)
    return f"{p.stem}_{wort}{p.suffix}"


def ki_prompt(name: str, texte: Sequence[str]) -> str:
    """Bittet um je ein Unterscheidungswort fuer Dokumente, die denselben Namen bekaemen."""
    teile = [
        f"Die folgenden {len(texte)} Dokumente sollen alle den Dateinamen \"{name}\" bekommen.",
        "Finde heraus, worin sie sich inhaltlich unterscheiden (z.B. Objekt, Gebaeudeteil, "
        "Leistung, Zeitraum, Vertragsnummer), und nenne fuer jedes Dokument EIN kurzes "
        "Unterscheidungswort (1-3 Woerter, deutsch, keine Wiederholung des Dateinamens).",
        "Die Woerter muessen sich voneinander unterscheiden.",
        'Antworte nur mit JSON: {"unterschiede": ["Wort fuer Dokument 1", "Wort fuer Dokument 2", ...]}',
        "",
    ]
    for i, text in enumerate(texte, 1):
        auszug = re.sub(r"\s+", " ", text or "").strip()[:TEXT_JE_DOKUMENT]
        teile.append(f"--- Dokument {i} ---\n{auszug or '(kein Text)'}")
    return "\n".join(teile)


def antwort_auswerten(text: str, anzahl: int) -> Optional[list[str]]:
    """Liest die Woerter aus der KI-Antwort; None, wenn sie fehlen, leer oder nicht verschieden sind."""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        daten = json.loads(m.group(0))
    except ValueError:
        return None
    roh = daten.get("unterschiede") if isinstance(daten, dict) else None
    if not isinstance(roh, list) or len(roh) != anzahl:
        return None
    woerter = [wort_bereinigen(w) for w in roh]
    if any(w is None for w in woerter) or len({w.casefold() for w in woerter}) != anzahl:
        return None
    return woerter


def unterscheiden(provider, name: str, texte: Sequence[str]) -> list[str]:
    """Fragt die KI nach je einem Unterscheidungswort (Reihenfolge wie ``texte``).

    Einbauen mit :func:`wort_einfuegen`.

    Wirft ``RuntimeError`` mit lesbarem Text, wenn der Aufruf scheitert oder die
    Antwort nicht brauchbar ist.
    """
    antwort = provider.answer_with_context(
        system_prompt="Du bist ein Assistent zum Benennen von Dokumenten. Antworte nur mit JSON.",
        context_docs=[],
        user_question=ki_prompt(name, texte),
        max_tokens=300,
    )
    antwort = (antwort or "").strip()
    if not antwort:
        raise RuntimeError("Die KI hat nicht geantwortet.")
    if antwort.startswith("[") and "fehler" in antwort[:60].lower():
        raise RuntimeError(antwort.strip("[]"))
    woerter = antwort_auswerten(antwort, len(texte))
    if woerter is None:
        raise RuntimeError("Die KI hat keine eindeutigen Unterscheidungen genannt.")
    return woerter

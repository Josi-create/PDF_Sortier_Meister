"""Issue #221: gleiche Namensvorschlaege im Stapel per KI unterscheiden (Qt-freier Kern)."""
from __future__ import annotations

import json

import pytest

from src.core import namen_unterscheiden as nu


class _Provider:
    def __init__(self, antwort):
        self.antwort = antwort
        self.fragen: list[str] = []

    def answer_with_context(self, system_prompt, context_docs, user_question, max_tokens=1000):
        self.fragen.append(user_question)
        return self.antwort


def test_doppelte_gruppen_ohne_gross_klein_und_ohne_none():
    namen = ["A.pdf", "b.pdf", "a.PDF", None, None, "c.pdf", "B.pdf"]
    assert nu.doppelte_gruppen(namen) == [[0, 2], [1, 6]]
    assert nu.doppelte_gruppen(["x.pdf", None, "y.pdf"]) == []


@pytest.mark.parametrize("roh, erwartet", [
    ("Hinterhaus", "Hinterhaus"),
    ("Gäste-Service", "Gaeste-Service"),
    ("  Garten / Hof ", "Garten-Hof"),
    ("Straße 12", "Strasse-12"),
    ("", None),
    ("?!", None),
])
def test_wort_bereinigen(roh, erwartet):
    assert nu.wort_bereinigen(roh) == erwartet


def test_wort_einfuegen_vor_der_endung():
    assert nu.wort_einfuegen("2026-06-05_Rechnung_X.pdf", "Hinterhaus") == "2026-06-05_Rechnung_X_Hinterhaus.pdf"
    assert nu.wort_einfuegen("Liste.docx", "Mai") == "Liste_Mai.docx"


def test_unterscheiden_liefert_woerter_in_reihenfolge_und_prompt_enthaelt_texte():
    p = _Provider('Hier: {"unterschiede": ["Vorderhaus", "Hinterhaus", "Garten"]}')
    woerter = nu.unterscheiden(p, "R.pdf", ["Text eins", "Text zwei", "Text drei"])
    assert woerter == ["Vorderhaus", "Hinterhaus", "Garten"]
    frage, = p.fragen
    assert '"R.pdf"' in frage and "Dokument 3" in frage and "Text zwei" in frage


@pytest.mark.parametrize("antwort", [
    "",
    "[Claude-Fehler: 401]",
    "keine Ahnung",
    json.dumps({"unterschiede": ["Nur eins"]}),          # falsche Anzahl
    json.dumps({"unterschiede": ["Haus", "haus"]}),       # nicht verschieden
    json.dumps({"unterschiede": ["Haus", "  "]}),         # leer
])
def test_unbrauchbare_antwort_wirft(antwort):
    with pytest.raises(RuntimeError):
        nu.unterscheiden(_Provider(antwort), "R.pdf", ["a", "b"])


def test_langer_text_wird_gekuerzt():
    frage = nu.ki_prompt("R.pdf", ["x" * 10_000])
    assert len(frage) < nu.TEXT_JE_DOKUMENT + 1000

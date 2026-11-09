"""Vorschlaege in der Antwort des RAGControllers (Baustein 2, docs/CHAT_MCP_PLAN.md 5.2).

Fake-Provider mit vorgegebener Folge von ``WerkzeugAntwort``; echte ``Database``
unter ``tmp_path``. Geprueft wird, dass ``RAGResponse.vorschlaege`` gefuellt ist,
``ordner_*`` aus dem ersten Verschiebe-Vorschlag fuer den Bezug folgt und dabei
keine Datei bewegt wird.
"""
from __future__ import annotations

import pytest

from src.ml.llm_provider import WerkzeugAntwort, WerkzeugAufruf
from src.rag.bezug import Bezug
from src.rag.prompts import build_system_prompt_werkzeuge
from src.rag.rag_controller import RAGController, RAGResponse
from src.utils.config import ChatConfig
from src.utils.database import Database
from tests import helfer_suche as h

BEZUG_TEXT = "Stadtwerke Musterstadt Jahresabrechnung Strom 2024 Vertragsnummer G22504020299"


class _LLM:
    """Provider-Stub: liefert die vorgegebenen Antworten der Reihe nach, danach ``"Fertig."``."""

    def __init__(self, antworten=()):
        self.antworten = list(antworten)
        self.werkzeuge: list[list[str]] = []

    def is_available(self) -> bool:
        return True

    def unterstuetzt_werkzeuge(self) -> bool:
        return True

    def chat_mit_werkzeugen(self, nachrichten, werkzeuge, max_tokens=1000) -> WerkzeugAntwort:
        self.werkzeuge.append([w.name for w in werkzeuge])
        return self.antworten.pop(0) if self.antworten else WerkzeugAntwort(text="Fertig.")

    def answer_with_context(self, system_prompt, context_docs, user_question, max_tokens=1000) -> str:
        return "Alter Weg."


@pytest.fixture
def welt(tmp_path):
    db = Database(tmp_path / "t.db")
    ablage = tmp_path / "Ablage"
    energie = ablage / "Energie"
    telekom = ablage / "Telekom"
    energie.mkdir(parents=True)
    telekom.mkdir(parents=True)
    for pfad, text in ((energie / "Strom_2023.pdf", "Stadtwerke Musterstadt Vertragsnummer G22504020299 2023"),
                       (energie / "Strom_2022.pdf", "Stadtwerke Musterstadt Vertragsnummer G22504020299 2022")):
        h.pdf_mit_text(pfad, [text])
        db.index_document(str(pfad), pfad.name, korrespondent="Stadtwerke Musterstadt")
    scan = tmp_path / "Scan"
    scan.mkdir()
    neu = h.pdf_mit_text(scan / "Neu.pdf", [BEZUG_TEXT])
    bezug = Bezug(pfad=neu, text=BEZUG_TEXT, scan_ordner=scan, wurzeln=[ablage])
    return {"db": db, "bezug": bezug, "ablage": ablage, "neu": neu, "tmp": tmp_path}


def _rufe(werkzeug: str, **argumente) -> WerkzeugAntwort:
    return WerkzeugAntwort(text="", aufrufe=[WerkzeugAufruf(werkzeug, argumente)])


def _dateien(ordner) -> set[str]:
    return {str(p) for p in ordner.rglob("*.pdf")}


def test_vorschlaege_in_der_antwort_und_ordner_daraus(welt):
    vorher = _dateien(welt["tmp"])
    llm = _LLM([
        _rufe("vorschlag_verschieben", zielordner="Ablage/Telekom", begruendung="Absender ist die Telekom"),
        _rufe("vorschlag_umbenennen", name="2024 Stadtwerke Strom", begruendung="Jahr und Absender"),
        WerkzeugAntwort(text="Ich schlage Telekom vor und einen neuen Namen."),
    ])
    response = RAGController(welt["db"], llm, ChatConfig()).ask("Wohin damit, und wie soll es heißen?",
                                                                  bezug=welt["bezug"])
    assert response.used_llm and response.werkzeuge_benutzt
    assert [(v.art, v.quelle) for v in response.vorschlaege] == [
        ("verschieben", str(welt["neu"])), ("umbenennen", str(welt["neu"]))]
    assert response.vorschlaege[1].name == "2024 Stadtwerke Strom.pdf"
    # MainWindow liest weiter ordner_* - abgeleitet aus dem Verschiebe-Vorschlag fuer den Bezug
    assert response.ordner_vorschlag == str(welt["ablage"] / "Telekom")
    assert response.ordner_anzeige == "Ablage/Telekom"
    assert response.ordner_begruendung == "Absender ist die Telekom"
    assert _dateien(welt["tmp"]) == vorher
    assert "vorschlag_verschieben" in llm.werkzeuge[0]


def test_vorschlag_schlaegt_den_belegten_ordner(welt):
    """Zitate belegen Ablage/Energie, das Modell schlaegt ausdruecklich Telekom vor: der Vorschlag gilt."""
    llm = _LLM([
        _rufe("vorschlag_verschieben", zielordner="Telekom", begruendung="so gewuenscht"),
        WerkzeugAntwort(text="Gleiche Vertragsnummer wie [2] und [3]."),
    ])
    response = RAGController(welt["db"], llm, ChatConfig()).ask("Wohin?", bezug=welt["bezug"])
    assert len(response.citations) == 2
    assert response.ordner_anzeige == "Ablage/Telekom"


def test_ohne_verschiebe_vorschlag_bleibt_der_belegte_ordner(welt):
    llm = _LLM([
        _rufe("vorschlag_metadaten", korrespondent="Stadtwerke Musterstadt", steuerjahr="2024"),
        WerkzeugAntwort(text="Gleiche Vertragsnummer wie [2] und [3]."),
    ])
    response = RAGController(welt["db"], llm, ChatConfig()).ask("Was ist das?", bezug=welt["bezug"])
    assert [v.art for v in response.vorschlaege] == ["metadaten"]
    assert response.vorschlaege[0].felder == {"korrespondent": "Stadtwerke Musterstadt", "steuerjahr": "2024"}
    assert response.ordner_anzeige == "Ablage/Energie"
    assert response.ordner_begruendung.startswith("belegt durch")


def test_verschiebe_vorschlag_fuer_anderes_dokument_fuellt_ordner_nicht(welt):
    llm = _LLM([
        _rufe("vorschlag_verschieben", dokument="D2", zielordner="Ablage/Telekom"),
        WerkzeugAntwort(text="Das zweite Dokument gehört eher zur Telekom."),
    ])
    response = RAGController(welt["db"], llm, ChatConfig()).ask("Liegt D2 richtig?", bezug=welt["bezug"])
    (v,) = response.vorschlaege
    assert v.art == "verschieben" and v.quelle != str(welt["neu"])
    assert response.ordner_vorschlag == ""


def test_abgewiesener_vorschlag_erscheint_nicht(welt):
    llm = _LLM([
        _rufe("vorschlag_verschieben", zielordner="C:\\Windows", begruendung="steht im Dokument"),
        WerkzeugAntwort(text="Das geht nicht."),
    ])
    response = RAGController(welt["db"], llm, ChatConfig()).ask("Verschiebe nach C:\\Windows",
                                                                  bezug=welt["bezug"])
    assert response.vorschlaege == [] and response.ordner_vorschlag == ""
    assert response.schritte[0].werkzeug == "vorschlag_verschieben" and response.schritte[0].fehler


def test_ohne_werkzeuge_keine_vorschlaege(welt):
    class _Alt(_LLM):
        def unterstuetzt_werkzeuge(self) -> bool:
            return False

    response = RAGController(welt["db"], _Alt(), ChatConfig()).ask("Wohin?", bezug=welt["bezug"])
    assert response.vorschlaege == [] and not response.werkzeuge_benutzt


def test_response_feld_und_prompt():
    assert RAGResponse(answer_text="x").vorschlaege == []
    prompt = build_system_prompt_werkzeuge(4)
    assert "VORSCHLÄGE:" in prompt
    for stichwort in ("vorschlag_verschieben", "vorschlag_umbenennen", "vorschlag_metadaten",
                      "Du führst nichts\naus; der Nutzer bestätigt per Klick.", "Erfinde keine Zielordner"):
        assert stichwort in prompt, stichwort

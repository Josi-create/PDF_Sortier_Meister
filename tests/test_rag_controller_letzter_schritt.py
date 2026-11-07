"""Werkzeug-Schleife, letzter Schritt (Live-Test): Aufforderung, zweiter Anlauf, Zwischenstand statt Fehler."""
from __future__ import annotations

from src.ml.llm_provider import WerkzeugAntwort, WerkzeugAufruf
from src.rag.rag_controller import LETZTER_SCHRITT_HINWEIS, LETZTER_SCHRITT_NACHDRUCK, RAGController
from src.utils.config import ChatConfig
from tests.test_rag_controller import _make_db_with_docs
from tests.test_rag_controller_werkzeuge import _WerkzeugLLM


def _suche(abfrage: str) -> WerkzeugAntwort:
    return WerkzeugAntwort(text="", aufrufe=[WerkzeugAufruf("suche", {"abfrage": abfrage})])


def test_letzter_schritt_bekommt_die_aufforderung_und_antwortet(tmp_path):
    db = _make_db_with_docs(tmp_path)
    llm = _WerkzeugLLM([_suche("Telekom"), WerkzeugAntwort(text="Die Rechnung kostet 49,95 EUR [1].")])
    ctrl = RAGController(db, llm, ChatConfig(werkzeuge_aktiv=True, max_werkzeug_schritte=2))

    response = ctrl.ask("Was kostet die Telekom-Rechnung?")

    assert response.used_llm and response.answer_text.startswith("Die Rechnung kostet")
    assert len(llm.aufrufe) == 2
    nachrichten, werkzeuge, _ = llm.aufrufe[1]
    assert werkzeuge == []
    assert nachrichten[-1] == {"role": "user", "content": LETZTER_SCHRITT_HINWEIS}
    assert nachrichten[-2]["role"] == "tool"  # das Werkzeugergebnis steht davor


def test_letzter_schritt_ruft_weiter_auf_dann_zweiter_anlauf(tmp_path):
    db = _make_db_with_docs(tmp_path)
    llm = _WerkzeugLLM([
        _suche("Telekom"),
        _suche("nochmal"),  # trotz leerer Werkzeugliste ein Aufruf ohne Text
        WerkzeugAntwort(text="Zusammengefasst: 49,95 EUR [1]."),
    ])
    ctrl = RAGController(db, llm, ChatConfig(werkzeuge_aktiv=True, max_werkzeug_schritte=2))

    response = ctrl.ask("Was kostet die Telekom-Rechnung?")

    assert response.used_llm and response.answer_text.startswith("Zusammengefasst")
    assert len(llm.aufrufe) == 3
    nachrichten, werkzeuge, _ = llm.aufrufe[2]
    assert werkzeuge == [] and nachrichten[-1] == {"role": "user", "content": LETZTER_SCHRITT_NACHDRUCK}
    # Der ignorierte Aufruf wurde nicht ausgefuehrt
    assert [s.werkzeug for s in response.schritte] == ["suche"]


def test_bleibt_es_leer_gibt_es_den_zwischenstand_statt_eines_fehlers(tmp_path):
    db = _make_db_with_docs(tmp_path)
    llm = _WerkzeugLLM([_suche("Telekom"), _suche("nochmal"), WerkzeugAntwort(text="")])
    ctrl = RAGController(db, llm, ChatConfig(werkzeuge_aktiv=True, max_werkzeug_schritte=2))

    response = ctrl.ask("Was kostet die Telekom-Rechnung?")

    assert response.used_llm and response.werkzeuge_benutzt
    assert response.answer_text.startswith("Ich konnte die Frage in 2 Schritten nicht abschließend beantworten.")
    assert "- Suche „Telekom“" in response.answer_text
    assert "Werkzeugaufruf fehlgeschlagen" not in response.answer_text
    assert response.citations == [] and len(response.schritte) == 1
    assert len(llm.aufrufe) == 3


def test_fehler_im_letzten_schritt_bleibt_ein_fehler(tmp_path):
    db = _make_db_with_docs(tmp_path)
    llm = _WerkzeugLLM([_suche("Telekom"), WerkzeugAntwort(fehler="HTTP 500")])
    ctrl = RAGController(db, llm, ChatConfig(werkzeuge_aktiv=True, max_werkzeug_schritte=2))
    response = ctrl.ask("Was kostet die Telekom-Rechnung?")
    assert not response.used_llm and response.answer_text == "Werkzeugaufruf fehlgeschlagen: HTTP 500"
    assert len(llm.aufrufe) == 2

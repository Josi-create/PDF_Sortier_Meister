"""Fehlermeldungen der OpenAI-kompatiblen KI-Anbieter auf Englisch (Issue #304)."""
import pytest

from src import i18n
from src.ml import openai_werkzeuge as ow
from src.ml.llm_provider import LLMConfig, Werkzeug


@pytest.fixture
def englisch():
    i18n.set_language("en")
    yield
    i18n.set_language("de")


def _openai():
    from src.ml.openai_provider import OpenAIProvider
    return OpenAIProvider(LLMConfig(api_key="sk-test", model="gpt-4.1-nano"))


def test_fehlerobjekt_ohne_code_deutsch_unveraendert():
    assert ow.fehler_aus_antwort({"message": "kaputt"}, "OpenRouter") == "OpenRouter-Fehler: kaputt"
    assert ow.fehler_aus_antwort("kaputt", "OpenRouter") == "OpenRouter-Fehler: kaputt"


def test_fehlerobjekt_ohne_code_englisch(englisch):
    assert ow.fehler_aus_antwort({"message": "broken"}, "OpenRouter") == "OpenRouter error: broken"
    assert ow.fehler_aus_antwort("broken", "OpenRouter") == "OpenRouter error: broken"


def test_http_helfer_unerwarteter_fehler_englisch(englisch, monkeypatch):
    p = _openai()

    def kaputt(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr("urllib.request.urlopen", kaputt)
    data, fehler = p._http_post_json("https://example.invalid", {}, {})
    assert data is None
    assert fehler == "OpenAI error: boom"


def test_werkzeug_chat_fehler_englisch(englisch, monkeypatch):
    p = _openai()
    werkzeug = Werkzeug(name="suche", beschreibung="x", parameter={"type": "object", "properties": {}})

    def modell_kaputt():
        raise RuntimeError("no model")

    monkeypatch.setattr(p, "_get_model_id", modell_kaputt)
    antwort = p.chat_mit_werkzeugen([{"role": "user", "content": "Hallo"}], [werkzeug])
    assert antwort.fehler == "OpenAI error: no model"

    monkeypatch.setattr(p, "_get_model_id", lambda: "gpt-4.1-nano")

    def post_kaputt(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(p, "_http_post_json", post_kaputt)
    antwort = p.chat_mit_werkzeugen([{"role": "user", "content": "Hallo"}], [werkzeug])
    assert antwort.fehler == "OpenAI error: offline"
    assert "Fehler" not in antwort.fehler

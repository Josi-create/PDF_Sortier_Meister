"""Tests fuer src/ml/strata_provider.py (lokaler Strata-Server, OpenAI-kompatibel)."""
import sys
import types

import pytest

from src.ml.llm_provider import LLMConfig, is_cloud_provider
from src.ml.strata_provider import StrataProvider, normalize_base_url


@pytest.fixture
def fake_openai(monkeypatch):
    captured = {"models": ["modell-b", "modell-a"], "calls": []}

    class _FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            captured["api_key"] = api_key
            captured["base_url"] = base_url

            def create(**kw):
                captured["calls"].append(kw)
                if captured.get("reject_extras") and "reasoning_effort" in kw:
                    raise Exception("Error code: 400 - unknown parameter")
                msg = types.SimpleNamespace(
                    content='{"filename": "2024-01-31_Test.pdf", "confidence": 0.9}')
                return types.SimpleNamespace(
                    choices=[types.SimpleNamespace(finish_reason="stop", message=msg)],
                    usage=None)

            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=create))
            self.models = types.SimpleNamespace(list=lambda: types.SimpleNamespace(
                data=[types.SimpleNamespace(id=m) for m in captured["models"]]))

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_FakeOpenAI))
    return captured


@pytest.mark.parametrize("eingabe, erwartet", [
    ("", "http://127.0.0.1:8080/v1"),
    ("http://127.0.0.1:8080", "http://127.0.0.1:8080/v1"),
    ("http://127.0.0.1:8080/", "http://127.0.0.1:8080/v1"),
    ("http://127.0.0.1:8080/v1/", "http://127.0.0.1:8080/v1"),
    ("192.168.1.10:9000", "http://192.168.1.10:9000/v1"),
])
def test_normalize_base_url(eingabe, erwartet):
    assert normalize_base_url(eingabe) == erwartet


def test_strata_ist_lokal():
    assert is_cloud_provider("strata") is False


def test_client_mit_url_und_key(fake_openai):
    p = StrataProvider(LLMConfig(api_key="sk-strata-test", model="m",
                                 base_url="http://localhost:8080"))
    assert p.is_available()
    assert fake_openai["api_key"] == "sk-strata-test"
    assert fake_openai["base_url"] == "http://localhost:8080/v1"
    assert p.CHAT_COMPLETIONS_URL == "http://localhost:8080/v1/chat/completions"


def test_ohne_key_nicht_verfuegbar(fake_openai):
    p = StrataProvider(LLMConfig(api_key="", model="m"))
    assert not p.is_available()


def test_modell_unveraendert_oder_erstes_vom_server(fake_openai):
    p = StrataProvider(LLMConfig(api_key="k", model="Mein-Modell_IQ2"))
    assert p._get_model_id() == "Mein-Modell_IQ2"
    p = StrataProvider(LLMConfig(api_key="k", model=""))
    assert p.list_models() == ["modell-a", "modell-b"]
    assert p._get_model_id() == "modell-a"


def test_reasoning_effort_mit_rueckfall(fake_openai):
    p = StrataProvider(LLMConfig(api_key="k", model="m"))
    p._create_chat_completion(model="m", messages=[])
    assert fake_openai["calls"][-1]["reasoning_effort"] == "low"

    fake_openai["reject_extras"] = True
    p2 = StrataProvider(LLMConfig(api_key="k", model="m"))
    p2._create_chat_completion(model="m", messages=[])
    assert "reasoning_effort" not in fake_openai["calls"][-1]
    assert p2._extras_rejected


def test_hybrid_classifier_waehlt_strata(fake_openai, monkeypatch):
    from src.ml import hybrid_classifier as hc_mod
    hc = hc_mod.HybridClassifier.__new__(hc_mod.HybridClassifier)
    hc.config = {"llm": {"provider": "strata", "api_key": "k", "model": "m",
                         "base_url": "http://localhost:8080/v1"}}
    hc.llm_provider = None
    hc.llm_enabled = False
    hc._init_llm_provider()
    assert isinstance(hc.llm_provider, StrataProvider)
    assert hc.llm_enabled
    assert hc.get_llm_provider_name() == "Strata"

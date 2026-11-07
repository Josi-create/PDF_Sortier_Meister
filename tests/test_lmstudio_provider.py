"""Tests fuer src/ml/lmstudio_provider.py (LM Studio, OpenAI-kompatibel, Issue #45).

Kein echter Netzwerkzugriff: urlopen und das openai-Paket sind ersetzt.
"""
import io
import json
import sys
import types
import urllib.error

import pytest

from src.ml import lmstudio_provider as lms
from src.ml.llm_hinweis import ki_hinweis
from src.ml.llm_provider import LLMConfig, LLMProviderType, is_cloud_provider
from src.ml.lmstudio_provider import LMStudioProvider, detect_lm_studio

MODELLE = ["qwen2.5-7b-instruct", "text-embedding-nomic-embed-text-v1.5", "llama-3.2-3b-instruct"]


@pytest.fixture
def fake_server(monkeypatch):
    """Ersetzt urlopen: /v1/models liefert MODELLE, oder 'aus' -> Verbindungsfehler."""
    state = {"aus": False, "urls": []}

    def fake_urlopen(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        state["urls"].append(url)
        if state["aus"]:
            raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
        body = {"object": "list", "data": [{"id": m, "object": "model"} for m in MODELLE]}
        return io.BytesIO(json.dumps(body).encode("utf-8"))

    monkeypatch.setattr(lms.urllib.request, "urlopen", fake_urlopen)
    return state


@pytest.fixture
def fake_openai(monkeypatch):
    """Minimales openai-Paket; die Antwort ist pro Test einstellbar."""
    captured = {"calls": [], "antwort": '{"filename": "2024-01-31_Test.pdf", "confidence": 0.9}'}

    class APIConnectionError(Exception):
        pass

    class _FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            captured["api_key"] = api_key
            captured["base_url"] = base_url

            def create(**kw):
                captured["calls"].append(kw)
                if captured.get("aus"):
                    raise APIConnectionError("Connection error.")
                msg = types.SimpleNamespace(content=captured["antwort"])
                return types.SimpleNamespace(
                    choices=[types.SimpleNamespace(finish_reason="stop", message=msg)],
                    usage=None)

            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=create))

    fake = types.SimpleNamespace(
        OpenAI=_FakeOpenAI,
        APIConnectionError=APIConnectionError,
        RateLimitError=type("RateLimitError", (Exception,), {}),
        AuthenticationError=type("AuthenticationError", (Exception,), {}),
    )
    monkeypatch.setitem(sys.modules, "openai", fake)
    return captured


# --- Erkennung ----------------------------------------------------------------

def test_erkennung_listet_chat_modelle_ohne_embeddings(fake_server):
    assert detect_lm_studio() == ["llama-3.2-3b-instruct", "qwen2.5-7b-instruct"]
    assert fake_server["urls"] == ["http://localhost:1234/v1/models"]


def test_erkennung_mit_eigener_url_ohne_v1(fake_server):
    detect_lm_studio("http://192.168.1.5:1234")
    assert fake_server["urls"] == ["http://192.168.1.5:1234/v1/models"]


def test_erkennung_server_aus(fake_server):
    fake_server["aus"] = True
    assert detect_lm_studio() is None


# --- Provider -----------------------------------------------------------------

def test_lokal_und_im_enum():
    assert is_cloud_provider("lmstudio") is False
    assert LLMProviderType("lmstudio") is LLMProviderType.LMSTUDIO


def test_ohne_key_verfuegbar_mit_standard_url(fake_openai):
    p = LMStudioProvider(LLMConfig(api_key="", model="qwen2.5-7b-instruct"))
    assert p.is_available()
    assert fake_openai["base_url"] == "http://localhost:1234/v1"
    assert fake_openai["api_key"]  # Platzhalter, der openai-Client verlangt einen
    assert p.CHAT_COMPLETIONS_URL == "http://localhost:1234/v1/chat/completions"


def test_modelle_listen_und_erstes_als_rueckfall(fake_openai, fake_server):
    p = LMStudioProvider(LLMConfig(api_key="", model=""))
    assert p.list_models() == ["llama-3.2-3b-instruct", "qwen2.5-7b-instruct"]
    assert p._get_model_id() == "llama-3.2-3b-instruct"


def test_dateiname_aus_unsauberer_antwort(fake_openai):
    """Lokale Modelle schreiben gern Text oder Code-Fences um das JSON."""
    fake_openai["antwort"] = (
        "Hier ist mein Vorschlag:\n```json\n"
        '{"filename": "2024-01-31_Stadtwerke_Rechnung.pdf", "reason": "Rechnung", '
        '"confidence": 0.8, "metadata": {"betrag": "12,50"}}\n```'
    )
    p = LMStudioProvider(LLMConfig(api_key="", model="qwen2.5-7b-instruct"))
    r = p.suggest_filename("Rechnung Stadtwerke 31.01.2024", "scan001.pdf")
    assert r.success, r.error_message
    assert r.filename_suggestion == "2024-01-31_Stadtwerke_Rechnung.pdf"
    assert r.confidence == pytest.approx(0.8)
    assert fake_openai["calls"][-1]["model"] == "qwen2.5-7b-instruct"


def test_ordner_aus_antwort(fake_openai):
    fake_openai["antwort"] = '{"folder": "Rechnungen", "reason": "x", "confidence": 0.7}'
    p = LMStudioProvider(LLMConfig(api_key="", model="m"))
    r = p.classify_document("Rechnung", ["Rechnungen", "Vertraege"])
    assert r.success and r.folder_suggestion == "Rechnungen"


def test_server_nicht_erreichbar(fake_openai, fake_server):
    fake_openai["aus"] = True
    fake_server["aus"] = True
    p = LMStudioProvider(LLMConfig(api_key="", model="m"))
    r = p.classify_document("Rechnung", ["Rechnungen"])
    assert not r.success
    assert "Keine Verbindung zur LM Studio API" in r.error_message
    r = p.suggest_filename("Rechnung", "a.pdf")
    assert not r.success and "LM Studio" in r.error_message

    ok, detail = p.ping()
    assert not ok and "Verbindung fehlgeschlagen" in detail
    hinweis = ki_hinweis("LM Studio", detail)
    assert "läuft nicht" in hinweis.problem
    assert hinweis.abhilfe.startswith("LM Studio")


def test_chat_antwort_ueber_konfigurierte_url(fake_openai, monkeypatch):
    p = LMStudioProvider(LLMConfig(api_key="", model="m", base_url="http://127.0.0.1:4321"))
    gesendet = {}

    def fake_post(url, body, headers, timeout=None):
        gesendet.update(url=url, body=body)
        return {"choices": [{"message": {"content": "Antwort [1]"}}]}, None

    monkeypatch.setattr(p, "_http_post_json", fake_post)
    assert p.answer_with_context("System", [], "Frage?") == "Antwort [1]"
    assert gesendet["url"] == "http://127.0.0.1:4321/v1/chat/completions"
    assert gesendet["body"]["model"] == "m"


def test_hybrid_classifier_waehlt_lmstudio_ohne_key(fake_openai):
    from src.ml import hybrid_classifier as hc_mod
    hc = hc_mod.HybridClassifier.__new__(hc_mod.HybridClassifier)
    hc.config = {"llm": {"provider": "lmstudio", "api_key": "", "model": "m", "base_url": ""}}
    hc.llm_provider = None
    hc.llm_enabled = False
    hc._init_llm_provider()
    assert isinstance(hc.llm_provider, LMStudioProvider)
    assert hc.llm_enabled
    assert hc.get_llm_provider_name() == "LM Studio"
    assert hc.llm_connection_checkable()

    assert hc.set_llm_provider(LLMProviderType.LMSTUDIO, api_key="")
    assert isinstance(hc.llm_provider, LMStudioProvider)

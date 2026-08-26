"""Tests: Modell-Download-Stream (/api/pull) und Ollama-Cloud-Provider."""

import json

from src.ml.llm_provider import LLMConfig, is_cloud_provider
from src.ml.ollama_launcher import _consume_pull_stream
from src.ml.ollama_provider import OllamaCloudProvider, OllamaProvider


def _stream(events):
    return [(json.dumps(e) + "\n").encode("utf-8") for e in events]


def test_pull_stream_reports_progress_and_success():
    events = [
        {"status": "pulling manifest"},
        {"status": "pulling abc", "total": 1000, "completed": 250},
        {"status": "pulling abc", "total": 1000, "completed": 1000},
        {"status": "verifying sha256 digest"},
        {"status": "success"},
    ]
    seen = []
    ok, msg = _consume_pull_stream(_stream(events), lambda p, s: seen.append((p, s)), None)
    assert ok is True
    assert msg == "Modell installiert."
    assert (25, "pulling abc") in seen
    assert (100, "pulling abc") in seen
    assert seen[-1] == (100, "success")


def test_pull_stream_error_event():
    ok, msg = _consume_pull_stream(_stream([{"error": "pull model manifest: file does not exist"}]), None, None)
    assert ok is False
    assert "does not exist" in msg


def test_pull_stream_cancel():
    events = [{"status": "pulling manifest"}, {"status": "pulling abc", "total": 10, "completed": 1}]
    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 1

    ok, msg = _consume_pull_stream(_stream(events), None, should_cancel)
    assert ok is False
    assert "abgebrochen" in msg


def test_pull_stream_truncated():
    ok, msg = _consume_pull_stream(_stream([{"status": "pulling manifest"}]), None, None)
    assert ok is False
    assert "unvollstaendig" in msg


def test_ollama_cloud_is_cloud_provider():
    assert is_cloud_provider("ollama_cloud") is True
    assert is_cloud_provider("ollama") is False


def test_cloud_provider_uses_bearer_and_ignores_local_url():
    p = OllamaCloudProvider(LLMConfig(api_key="sk-test", model="", base_url="http://localhost:11434"))
    assert p._get_base_url() == "https://ollama.com"
    assert p._headers()["Authorization"] == "Bearer sk-test"
    assert p._get_model_id() == "gpt-oss:120b"
    assert p.is_available() is True
    assert OllamaCloudProvider(LLMConfig(api_key="", model="")).is_available() is False


def test_local_provider_has_no_auth_header_without_key():
    p = OllamaProvider(LLMConfig(api_key="", model="llama3.1"))
    assert "Authorization" not in p._headers()


def test_cloud_list_models_falls_back_to_static(monkeypatch):
    import urllib.request

    def boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    p = OllamaCloudProvider(LLMConfig(api_key="sk", model=""))
    assert p.list_models() == OllamaCloudProvider.CLOUD_MODELS


def test_cloud_chat_does_not_autostart_local_server(monkeypatch):
    p = OllamaCloudProvider(LLMConfig(api_key="sk", model=""))
    monkeypatch.setattr(p, "_do_chat", lambda *a, **k: (None, "Keine Verbindung zu Ollama (x)"))
    import src.ml.ollama_launcher as launcher
    monkeypatch.setattr(launcher, "ensure_running", lambda *a, **k: (_ for _ in ()).throw(AssertionError("darf nicht")))
    assert p._chat("s", "u") == (None, "Keine Verbindung zu Ollama (x)")

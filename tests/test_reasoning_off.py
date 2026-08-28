"""Reasoning/Thinking wird fuer die kurze Extraktionsaufgabe abgeschaltet oder minimiert."""
import io
import json
import types
import urllib.error


# ---------- OpenAI direkt ----------

def _openai_client(calls, reject_extras=False):
    def create(**kw):
        calls.append(kw)
        if reject_extras and "reasoning_effort" in kw:
            raise Exception("Error code: 400 - Unrecognized request argument: reasoning_effort")
        choice = types.SimpleNamespace(
            finish_reason="stop",
            message=types.SimpleNamespace(content='{"filename": "2024-01-31_Test.pdf", "confidence": 0.9}'),
        )
        return types.SimpleNamespace(choices=[choice], usage=None)
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))


def _openai(model):
    from src.ml.llm_provider import LLMConfig
    from src.ml.openai_provider import OpenAIProvider
    return OpenAIProvider(LLMConfig(api_key="sk-test", model=model))


def test_openai_reasoning_model_gets_minimal_effort():
    p = _openai("gpt-5-mini"); calls = []; p._client = _openai_client(calls)
    p.suggest_filename(text="x", current_filename="a.pdf")
    assert calls[0]["reasoning_effort"] == "minimal"


def test_openai_classic_model_gets_no_effort_param():
    p = _openai("gpt-4.1-nano"); calls = []; p._client = _openai_client(calls)
    p.suggest_filename(text="x", current_filename="a.pdf")
    assert "reasoning_effort" not in calls[0]


def test_rejected_extras_are_remembered():
    p = _openai("o3-mini"); calls = []; p._client = _openai_client(calls, reject_extras=True)
    p.suggest_filename(text="x", current_filename="a.pdf")
    p.suggest_filename(text="x", current_filename="b.pdf")
    # 1. Aufruf: mit Extras (400) + Wiederholung ohne; 2. Aufruf: direkt ohne
    assert len(calls) == 3
    assert "reasoning_effort" in calls[0]
    assert all("reasoning_effort" not in c for c in calls[1:])


# ---------- Ollama ----------

def _ollama(monkeypatch, responses):
    """responses: Liste von (status, body_dict) pro Aufruf; sammelt gesendete Payloads."""
    from src.ml.llm_provider import LLMConfig
    from src.ml.ollama_provider import OllamaProvider
    sent = []

    def fake_urlopen(req, timeout=None):
        sent.append(json.loads(req.data.decode("utf-8")))
        status, body = responses.pop(0)
        if status != 200:
            raise urllib.error.HTTPError(req.full_url, status, "Bad Request", {}, io.BytesIO(b""))
        return io.BytesIO(json.dumps(body).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    p = OllamaProvider(LLMConfig(api_key="", model="gemma3:4b"))
    return p, sent


def test_ollama_sends_think_false(monkeypatch):
    ok = {"message": {"content": '{"filename": "2024-01-31_Test.pdf", "confidence": 0.9}'}}
    p, sent = _ollama(monkeypatch, [(200, ok)])
    r = p.suggest_filename(text="x", current_filename="a.pdf")
    assert r.success is True
    assert sent[0]["think"] is False


def test_ollama_retries_without_think_on_400_and_remembers(monkeypatch):
    ok = {"message": {"content": '{"filename": "2024-01-31_Test.pdf", "confidence": 0.9}'}}
    p, sent = _ollama(monkeypatch, [(400, None), (200, ok), (200, ok)])
    r = p.suggest_filename(text="x", current_filename="a.pdf")
    assert r.success is True
    r2 = p.suggest_filename(text="x", current_filename="b.pdf")
    assert r2.success is True
    assert len(sent) == 3
    assert "think" in sent[0] and "think" not in sent[1] and "think" not in sent[2]

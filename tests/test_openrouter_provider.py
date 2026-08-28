"""Tests fuer src/ml/openrouter_provider.py"""


def _make(model="", api_key=""):
    from src.ml.llm_provider import LLMConfig
    from src.ml.openrouter_provider import OpenRouterProvider
    return OpenRouterProvider(LLMConfig(api_key=api_key, model=model))


def test_uses_openrouter_base_url():
    from src.ml.openrouter_provider import OpenRouterProvider
    assert OpenRouterProvider.BASE_URL == "https://openrouter.ai/api/v1"
    assert OpenRouterProvider.CHAT_COMPLETIONS_URL == (
        "https://openrouter.ai/api/v1/chat/completions"
    )


def test_model_id_passthrough_and_default():
    assert _make("anthropic/claude-sonnet-4")._get_model_id() == "anthropic/claude-sonnet-4"
    assert _make("")._get_model_id() == "openai/gpt-4.1-nano"


def test_not_available_without_api_key():
    p = _make("openai/gpt-4.1-nano", api_key="")
    assert not p.is_available()
    r = p.classify_document("text", ["Rechnungen"])
    assert r.success is False
    assert "OpenRouter" in r.error_message


def test_client_created_with_openrouter_base_url(monkeypatch):
    import types, sys
    captured = {}

    class _FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    fake = types.SimpleNamespace(OpenAI=_FakeOpenAI)
    monkeypatch.setitem(sys.modules, "openai", fake)

    p = _make("openai/gpt-4.1-nano", api_key="sk-or-test")
    assert p.is_available()
    assert captured == {"api_key": "sk-or-test", "base_url": "https://openrouter.ai/api/v1"}


def _fake_client(calls, fail_with_extras=False):
    import types

    def create(**kw):
        calls.append(kw)
        if fail_with_extras and "extra_body" in kw:
            raise Exception("Error code: 400 - {'error': {'message': 'Reasoning not supported'}}")
        choice = types.SimpleNamespace(
            finish_reason="stop",
            message=types.SimpleNamespace(content='{"filename": "2024-01-31_Test.pdf", "confidence": 0.9}'),
        )
        return types.SimpleNamespace(choices=[choice], usage=None)

    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))


def test_openrouter_sends_low_reasoning_effort():
    p = _make("z-ai/glm-5.3-flash", api_key="sk-or-test")
    calls = []
    p._client = _fake_client(calls)
    r = p.suggest_filename(text="Rechnung", current_filename="scan.pdf")
    assert r.success is True and r.filename_suggestion == "2024-01-31_Test.pdf"
    assert calls[0]["extra_body"] == {"reasoning": {"effort": "low"}}


def test_openrouter_retries_without_extras_on_400():
    p = _make("some/model-without-reasoning", api_key="sk-or-test")
    calls = []
    p._client = _fake_client(calls, fail_with_extras=True)
    r = p.suggest_filename(text="Rechnung", current_filename="scan.pdf")
    assert r.success is True
    assert len(calls) == 2
    assert "extra_body" in calls[0] and "extra_body" not in calls[1]


def test_plain_openai_provider_sends_no_extras():
    from src.ml.llm_provider import LLMConfig
    from src.ml.openai_provider import OpenAIProvider
    p = OpenAIProvider(LLMConfig(api_key="sk-test", model="gpt-4.1-nano"))
    calls = []
    p._client = _fake_client(calls)
    p.suggest_filename(text="Rechnung", current_filename="scan.pdf")
    assert "extra_body" not in calls[0]

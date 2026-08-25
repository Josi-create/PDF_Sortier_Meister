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

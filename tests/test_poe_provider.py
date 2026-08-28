"""Tests fuer src/ml/poe_provider.py (Issue #66: Provider wieder aufgenommen)."""


def _make(model="", api_key=""):
    from src.ml.llm_provider import LLMConfig
    from src.ml.poe_provider import PoeProvider
    return PoeProvider(LLMConfig(api_key=api_key, model=model))


def test_uses_poe_base_url():
    from src.ml.poe_provider import PoeProvider
    assert PoeProvider.BASE_URL == "https://api.poe.com/v1"
    assert PoeProvider.DEFAULT_MODEL == "GPT-4o-Mini"


def test_model_id_mapping_and_default():
    # Kurzname aus MODELS wird auf den Poe-Bot-Namen gemappt
    assert _make("claude-3.5-haiku")._get_model_id() == "Claude-3.5-Haiku"
    # Bereits ein Poe-Bot-Name -> unveraendert durchgereicht
    assert _make("Gemini-2.5-Pro")._get_model_id() == "Gemini-2.5-Pro"
    # Kein Modell gesetzt -> Default
    assert _make("")._get_model_id() == "GPT-4o-Mini"


def test_max_tokens_reserve_for_claude_models():
    """Claude via Poe aktiviert Thinking - max_tokens muss dafuer reichen."""
    from src.ml.llm_provider import LLMConfig
    from src.ml.poe_provider import PoeProvider

    claude = PoeProvider(LLMConfig(api_key="", model="claude-3.5-haiku", max_tokens=500))
    assert claude._get_max_tokens() >= 2048

    gpt = PoeProvider(LLMConfig(api_key="", model="gpt-4o-mini", max_tokens=500))
    assert gpt._get_max_tokens() == 500


def test_not_available_without_api_key():
    p = _make("gpt-4o-mini", api_key="")
    assert not p.is_available()
    r = p.classify_document("text", ["Rechnungen"])
    assert r.success is False
    assert "Poe" in r.error_message


def test_answer_with_context_without_key_returns_empty():
    assert _make("gpt-4o-mini", api_key="").answer_with_context("sys", [], "Frage?") == ""


def test_client_created_with_poe_base_url(monkeypatch):
    import types
    import sys
    captured = {}

    class _FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    fake = types.SimpleNamespace(OpenAI=_FakeOpenAI)
    monkeypatch.setitem(sys.modules, "openai", fake)

    p = _make("gpt-4o-mini", api_key="poe-test-key")
    assert p.is_available()
    assert captured == {"api_key": "poe-test-key", "base_url": "https://api.poe.com/v1"}


def test_hybrid_classifier_maps_poe_type():
    """LLMProviderType.POE muss auf den PoeProvider zeigen."""
    from src.ml.llm_provider import LLMProviderType
    from src.ml.poe_provider import PoeProvider
    import src.ml.hybrid_classifier as hc

    assert LLMProviderType.POE.value == "poe"
    assert hc.PoeProvider is PoeProvider

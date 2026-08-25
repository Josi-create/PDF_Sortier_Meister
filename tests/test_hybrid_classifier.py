"""Tests fuer Consent-Gate in src/ml/hybrid_classifier.py"""
import pytest


def _mock_config(provider, consent, api_key="sk-xxx"):
    return {
        "llm": {
            "provider": provider,
            "api_key": api_key,
            "model": "",
            "base_url": "",
            "cloud_consent": consent,
            "max_tokens": 500,
            "temperature": 0.3,
            "text_limit": 1500,
        }
    }


class _StubProvider:
    def __init__(self, config): pass
    def is_available(self): return True


# --- Task 3: Consent-Gate beim Startup-Pfad (_init_llm_provider) ---

def test_cloud_provider_blocked_without_consent(monkeypatch):
    from src.ml import hybrid_classifier

    monkeypatch.setattr(hybrid_classifier, "get_config", lambda: _mock_config("claude", False))
    monkeypatch.setattr(hybrid_classifier, "get_classifier", lambda: None)
    monkeypatch.setattr(hybrid_classifier, "ClaudeProvider", _StubProvider)

    hc = hybrid_classifier.HybridClassifier()
    assert hc.llm_enabled is False


def test_cloud_provider_allowed_with_consent(monkeypatch):
    from src.ml import hybrid_classifier

    monkeypatch.setattr(hybrid_classifier, "get_config", lambda: _mock_config("claude", True))
    monkeypatch.setattr(hybrid_classifier, "get_classifier", lambda: None)
    monkeypatch.setattr(hybrid_classifier, "ClaudeProvider", _StubProvider)

    hc = hybrid_classifier.HybridClassifier()
    assert hc.llm_enabled is True


def test_ollama_no_consent_needed(monkeypatch):
    from src.ml import hybrid_classifier

    monkeypatch.setattr(hybrid_classifier, "get_config", lambda: _mock_config("ollama", False, api_key=""))
    monkeypatch.setattr(hybrid_classifier, "get_classifier", lambda: None)
    monkeypatch.setattr(hybrid_classifier, "OllamaProvider", _StubProvider)

    hc = hybrid_classifier.HybridClassifier()
    assert hc.llm_enabled is True


# --- Task 4: Consent-Gate beim Laufzeit-Wechsel (set_llm_provider) ---

def test_set_cloud_provider_without_consent_returns_false(monkeypatch):
    from src.ml import hybrid_classifier
    from src.ml.llm_provider import LLMProviderType

    # Start with no provider, consent=False
    monkeypatch.setattr(hybrid_classifier, "get_config", lambda: _mock_config("none", False))
    monkeypatch.setattr(hybrid_classifier, "get_classifier", lambda: None)

    hc = hybrid_classifier.HybridClassifier()
    ok = hc.set_llm_provider(LLMProviderType.CLAUDE, api_key="sk-x")
    assert ok is False
    assert hc.llm_enabled is False


def test_set_cloud_provider_with_consent_returns_true(monkeypatch):
    from src.ml import hybrid_classifier
    from src.ml.llm_provider import LLMProviderType

    cfg = _mock_config("none", True)
    monkeypatch.setattr(hybrid_classifier, "get_config", lambda: cfg)
    monkeypatch.setattr(hybrid_classifier, "get_classifier", lambda: None)
    monkeypatch.setattr(hybrid_classifier, "ClaudeProvider", _StubProvider)

    hc = hybrid_classifier.HybridClassifier()
    ok = hc.set_llm_provider(LLMProviderType.CLAUDE, api_key="sk-x")
    assert ok is True
    assert hc.llm_enabled is True

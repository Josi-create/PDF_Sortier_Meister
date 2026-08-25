"""Tests fuer src/ml/llm_provider.py"""


def test_cloud_providers_set():
    from src.ml.llm_provider import CLOUD_PROVIDERS, is_cloud_provider

    assert is_cloud_provider("claude") is True
    assert is_cloud_provider("openai") is True
    assert is_cloud_provider("poe") is True
    assert is_cloud_provider("openrouter") is True
    assert is_cloud_provider("ollama") is False
    assert is_cloud_provider("none") is False

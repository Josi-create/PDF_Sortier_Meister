"""Tests fuer src/utils/config.py"""


def test_llm_defaults_include_cloud_consent():
    from src.utils.config import Config

    cfg = Config.DEFAULTS
    assert cfg["llm"]["cloud_consent"] is False  # Default: keine Zustimmung

"""Tests fuer src/utils/config.py"""


def test_llm_defaults_include_cloud_consent():
    from src.utils.config import Config

    cfg = Config.DEFAULTS
    assert cfg["llm"]["cloud_consent"] is False  # Default: keine Zustimmung


def test_set_llm_api_key_also_stores_per_provider(tmp_path):
    from src.utils.config import Config

    cfg = Config(config_path=tmp_path / "config.json")
    cfg.set_llm_provider("openrouter")
    cfg.set_llm_api_key("sk-or-key")

    llm = cfg.get_llm_config()
    assert llm["api_key"] == "sk-or-key"
    assert llm["api_keys"] == {"openrouter": "sk-or-key"}


def test_set_llm_api_key_ollama_not_stored_per_provider(tmp_path):
    from src.utils.config import Config

    cfg = Config(config_path=tmp_path / "config.json")
    cfg.set_llm_provider("ollama")
    cfg.set_llm_api_key("")
    assert cfg.get_llm_config()["api_keys"] == {}


def test_backup_hint_default_not_dismissed():
    from src.utils.config import Config
    assert Config.DEFAULTS["backup_hint_dismissed"] is False


def test_first_steps_hint_default_not_dismissed():
    from src.utils.config import Config
    assert Config.DEFAULTS["first_steps_hint_dismissed"] is False

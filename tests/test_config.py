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


def test_load_keeps_poe_provider(tmp_path):
    """Issue #66: poe.com vergibt wieder API-Keys, Poe ist wieder waehlbar.

    Eine gespeicherte Config mit ``llm.provider == "poe"`` muss beim Laden
    unveraendert erhalten bleiben - insbesondere darf sie nicht (wie in
    0.19.0) still auf "none" heruntergestuft und der Poe-Key verworfen
    werden.
    """
    import json
    from src.utils.config import Config

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "llm": {
                "provider": "poe",
                "api_key": "poe-key",
                "api_keys": {"poe": "poe-key", "openrouter": "sk-or-key"},
            }
        }),
        encoding="utf-8",
    )

    cfg = Config(config_path=config_path)
    llm = cfg.get_llm_config()

    assert llm["provider"] == "poe"
    assert llm["api_key"] == "poe-key"
    assert llm["api_keys"]["poe"] == "poe-key"
    assert llm["api_keys"]["openrouter"] == "sk-or-key"


def test_backup_hint_default_not_dismissed():
    from src.utils.config import Config
    assert Config.DEFAULTS["backup_hint_dismissed"] is False


def test_first_steps_hint_default_not_dismissed():
    from src.utils.config import Config
    assert Config.DEFAULTS["first_steps_hint_dismissed"] is False

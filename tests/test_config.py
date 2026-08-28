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


def test_load_migrates_poe_provider_to_none(tmp_path):
    """Issue #66: poe.com vergibt keine API-Keys mehr, Provider wurde entfernt.

    Eine bestehende Config mit ``llm.provider == "poe"`` soll beim Laden
    automatisch auf "none" zurueckgesetzt werden, inkl. Entfernen eines
    evtl. gespeicherten Poe-Keys aus ``api_keys``.
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

    assert llm["provider"] == "none"
    assert llm["api_key"] == ""
    assert "poe" not in llm["api_keys"]
    assert llm["api_keys"]["openrouter"] == "sk-or-key"


def test_backup_hint_default_not_dismissed():
    from src.utils.config import Config
    assert Config.DEFAULTS["backup_hint_dismissed"] is False


def test_first_steps_hint_default_not_dismissed():
    from src.utils.config import Config
    assert Config.DEFAULTS["first_steps_hint_dismissed"] is False

"""Alter Default llm.max_tokens=500 wird beim Laden auf den neuen Default angehoben."""
import json


def _load(tmp_path, llm):
    from src.utils.config import Config
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"llm": llm}), encoding="utf-8")
    cfg = Config.__new__(Config)
    cfg.config_path = cfg_path
    cfg._config = {}
    cfg.load()
    return cfg, cfg_path


def test_default_is_2000():
    from src.utils.config import Config
    assert Config.DEFAULTS["llm"]["max_tokens"] == 2000


def test_legacy_500_is_raised_and_persisted(tmp_path):
    cfg, path = _load(tmp_path, {"provider": "openrouter", "max_tokens": 500})
    assert cfg.get("llm")["max_tokens"] == 2000
    assert json.loads(path.read_text(encoding="utf-8"))["llm"]["max_tokens"] == 2000


def test_user_chosen_value_is_kept(tmp_path):
    cfg, _ = _load(tmp_path, {"provider": "openrouter", "max_tokens": 1200})
    assert cfg.get("llm")["max_tokens"] == 1200

"""Config-Migration: folder_naming_initials -> owner_initials, altes
Dateinamen-Muster -> {platzhalter}-Syntax."""
import json


def _load(tmp_path, data):
    from src.utils.config import Config
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    cfg = Config.__new__(Config)
    cfg.config_path = path
    cfg._config = {}
    cfg.load()
    return cfg, path


def test_initials_and_pattern_are_migrated_and_saved(tmp_path):
    cfg, path = _load(tmp_path, {
        "folder_naming_initials": "JW",
        "filename_pattern": "PROJEKTNUMMER_INITIALIEN/AKTENZEICHEN_YYYY-MM-DD_Betreff_Kontakt",
    })
    assert cfg.get("owner_initials") == "JW"
    assert cfg.get("filename_pattern") == "{initialen}_{aktenzeichen}_{datum}_{betreff}_{kontakt}"
    assert "folder_naming_initials" not in cfg._config

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["owner_initials"] == "JW"
    assert "folder_naming_initials" not in saved
    assert saved["filename_pattern"].startswith("{initialen}")


def test_existing_owner_initials_win(tmp_path):
    cfg, _ = _load(tmp_path, {"folder_naming_initials": "JW", "owner_initials": "JHW"})
    assert cfg.get("owner_initials") == "JHW"


def test_new_syntax_is_left_alone(tmp_path):
    cfg, path = _load(tmp_path, {"filename_pattern": "{datum}_{kontakt}"})
    assert cfg.get("filename_pattern") == "{datum}_{kontakt}"

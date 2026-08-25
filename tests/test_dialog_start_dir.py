"""Tests fuer Config.dialog_start_dir (Issue #11: "+ Zielordner" startet im Scan-Ordner)."""


def _cfg(tmp_path, scan):
    from src.utils.config import Config
    cfg = Config(config_path=tmp_path / "config.json")
    if scan is not None:
        cfg.set("scan_folder", str(scan))
    return cfg


def test_uses_parent_of_scan_folder(tmp_path):
    scan = tmp_path / "Dokumente" / "FrischGescannt"
    scan.mkdir(parents=True)
    assert _cfg(tmp_path, scan).dialog_start_dir() == str(tmp_path / "Dokumente")


def test_falls_back_to_scan_folder_when_parent_is_root(tmp_path, monkeypatch):
    from pathlib import Path
    cfg = _cfg(tmp_path, None)
    root = Path(tmp_path.anchor)  # z.B. C:\ - parent == self
    monkeypatch.setattr(cfg, "get_scan_folder", lambda: root)
    assert cfg.dialog_start_dir() == str(root)


def test_empty_without_scan_folder(tmp_path):
    cfg = _cfg(tmp_path, None)
    assert cfg.dialog_start_dir() == ""

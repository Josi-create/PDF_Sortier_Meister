"""Classifier-Ordner-Cache blockiert nie (Issue #28: 16,8 s rglob auf OneDrive)."""
import time
from pathlib import Path


def _classifier(tmp_path, monkeypatch, roots):
    from src.utils import config as cfg_mod, database as db_mod
    from src.ml import classifier as cl_mod
    from tests.conftest import patch_singletons
    cfg = cfg_mod.Config(config_path=tmp_path / "config.json")
    for r in roots:
        cfg.add_target_folder(r)
    db = db_mod.Database(db_path=str(tmp_path / "history.db"))
    patch_singletons(monkeypatch, {"get_config": lambda: cfg, "get_database": lambda: db})
    c = cl_mod.PDFClassifier(); c._ensure_model()
    return c


def test_find_folder_returns_none_until_cache_built_then_resolves(tmp_path, monkeypatch):
    root = tmp_path / "Ziel"; (root / "Steuer 2026" / "Banken").mkdir(parents=True)
    c = _classifier(tmp_path, monkeypatch, [root])
    first = c._find_folder_by_name("banken")  # startet Hintergrund-Aufbau
    assert first is None
    deadline = time.time() + 5
    while time.time() < deadline and c._find_folder_by_name("banken") is None:
        time.sleep(0.05)
    assert c._find_folder_by_name("banken") == root / "Steuer 2026" / "Banken"


def test_warm_folder_cache_is_synchronous(tmp_path, monkeypatch):
    root = tmp_path / "Ziel"; (root / "Briefe 2026").mkdir(parents=True)
    c = _classifier(tmp_path, monkeypatch, [root])
    c.warm_folder_cache()
    assert c._find_folder_by_name("briefe 2026") == root / "Briefe 2026"

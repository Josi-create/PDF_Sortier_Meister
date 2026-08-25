"""Issue #28: Klassifikator laedt im Hintergrund, learn() blockiert nicht mehr."""
import time
from pathlib import Path

import pytest


@pytest.fixture
def classifier(tmp_path, monkeypatch):
    from src.utils import config as cfg_mod, database as db_mod
    from src.ml import classifier as cl_mod
    from tests.conftest import patch_singletons

    cfg = cfg_mod.Config(config_path=tmp_path / "config.json")
    db = db_mod.Database(db_path=str(tmp_path / "history.db"))
    patch_singletons(monkeypatch, {"get_config": lambda: cfg, "get_database": lambda: db})
    c = cl_mod.PDFClassifier()
    c._ensure_model()
    return c


def _learn(c, tmp_path, i, folder, text):
    c.learn(tmp_path / f"s{i}.pdf", folder, text, ["k"], "2026-01-01")


def test_sklearn_not_imported_by_module_import():
    import importlib, sys
    import src.ml.classifier  # noqa: F401
    # Der Modul-Import allein darf sklearn nicht laden (Startzeit!)
    # (In einer Suite kann sklearn schon geladen sein - dann nur pruefen, dass
    # classifier.py selbst keinen Top-Level-Import mehr hat.)
    src = Path(src.ml.classifier.__file__).read_text(encoding="utf-8")
    top = src.split("class PDFClassifier")[0]
    assert "from sklearn" not in top and "import numpy" not in top


def test_learn_returns_fast_and_trains_in_background(classifier, tmp_path):
    classifier.RETRAIN_DELAY_S = 0.05
    folder = tmp_path / "Steuer 2026"; folder.mkdir()

    t0 = time.perf_counter()
    for i in range(3):
        _learn(classifier, tmp_path, i, folder, "rechnung steuer finanzamt " * 20)
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5  # frueher: ~450 ms PRO learn()

    classifier.flush_training()
    assert len(classifier.training_entries) == 3
    assert classifier.tfidf_matrix is not None


def test_suggest_sees_new_training_after_flush(classifier, tmp_path):
    classifier.RETRAIN_DELAY_S = 0.05
    folder = tmp_path / "Banken"; folder.mkdir()
    _learn(classifier, tmp_path, 1, folder, "kontoauszug bank iban ueberweisung " * 20)
    classifier.flush_training()
    out = classifier.suggest("kontoauszug bank iban ueberweisung saldo", ["bank"])
    assert out and out[0].folder_name == "Banken"


def test_model_ready_event_set_even_without_model_file(classifier):
    assert classifier._model_ready.is_set()

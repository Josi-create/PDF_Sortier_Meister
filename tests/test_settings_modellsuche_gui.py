"""GUI-Tests: Modell-Auswahl in den Einstellungen ist durchsuchbar (Issue #293).

Tippen in die Auswahl „Modell“ zeigt nur die Einträge, die den Text irgendwo
im Namen enthalten (Groß-/Kleinschreibung egal) - fuer das allgemeine Modell
und fuer das eigene Chat-Modell.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt

from src.gui.settings_dialog import SettingsDialog

MODELLE = [
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-haiku-4.5",
    "openai/gpt-4o-mini",
    "anthropic/claude-3.5-Haiku",
]


@pytest.fixture(autouse=True)
def kein_netz(monkeypatch):
    def _verboten(*args, **kwargs):
        raise AssertionError("Netzaufruf im Test")
    monkeypatch.setattr("urllib.request.urlopen", _verboten)


@pytest.fixture
def fresh_config(monkeypatch, tmp_path):
    from src.core import pdf_cache as pc_mod
    from src.ml import classifier as cl_mod
    from src.ml import hybrid_classifier as hc_mod
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod
    from tests.conftest import patch_singletons

    fresh = cfg_mod.Config(config_path=tmp_path / "config.json")
    fresh.set("persist_pdf_cache", False)
    monkeypatch.setattr(pc_mod.PDFCache, "_instance", None)
    patch_singletons(monkeypatch, {
        "get_config": lambda: fresh,
        "get_database": lambda: db_mod.Database(db_path=str(tmp_path / "t.db")),
        "get_classifier": cl_mod.PDFClassifier,
        "get_hybrid_classifier": hc_mod.HybridClassifier,
        "get_pdf_cache": pc_mod.PDFCache,
    })
    return fresh


def _treffer(combo, text):
    completer = combo.completer()
    completer.setCompletionPrefix(text)
    model = completer.completionModel()
    return [model.index(i, 0).data() for i in range(model.rowCount())]


def _dialog(qtbot):
    d = SettingsDialog()
    qtbot.addWidget(d)
    d.provider_combo.setCurrentIndex(d._index_for_provider("openrouter"))
    return d


def test_modell_suche_findet_wort_mitten_im_namen(qtbot, fresh_config):
    d = _dialog(qtbot)
    d.model_combo.clear()
    d.model_combo.addItems(MODELLE)

    completer = d.model_combo.completer()
    assert completer.filterMode() == Qt.MatchFlag.MatchContains
    assert completer.caseSensitivity() == Qt.CaseSensitivity.CaseInsensitive
    assert _treffer(d.model_combo, "haiku") == [
        "anthropic/claude-haiku-4.5", "anthropic/claude-3.5-Haiku"]
    assert _treffer(d.model_combo, "gpt") == ["openai/gpt-4o-mini"]


def test_modell_suche_bleibt_nach_providerwechsel_aktuell(qtbot, fresh_config):
    d = _dialog(qtbot)
    d.provider_combo.setCurrentIndex(d._index_for_provider("ollama"))
    d.model_combo.clear()
    d.model_combo.addItems(["qwen3:8b", "llama3.2:3b"])

    assert _treffer(d.model_combo, "WEN") == ["qwen3:8b"]
    assert _treffer(d.model_combo, "haiku") == []


def test_chat_modell_ist_ebenfalls_durchsuchbar(qtbot, fresh_config):
    d = _dialog(qtbot)
    d.chat_model_combo.clear()
    d.chat_model_combo.addItems(MODELLE)

    assert _treffer(d.chat_model_combo, "sonnet") == ["anthropic/claude-sonnet-4.5"]


def test_treffer_auswaehlen_setzt_modell(qtbot, fresh_config):
    """Tippen, Pfeil runter, Enter: der Treffer steht im Feld und wird gespeichert."""
    d = _dialog(qtbot)
    d.model_combo.clear()
    d.model_combo.addItems(MODELLE)
    d.show()
    qtbot.waitExposed(d)

    d.model_combo.lineEdit().clear()
    qtbot.keyClicks(d.model_combo.lineEdit(), "gpt")
    popup = d.model_combo.completer().popup()
    qtbot.keyClick(popup, Qt.Key.Key_Down)
    qtbot.keyClick(popup, Qt.Key.Key_Return)

    assert d.model_combo.currentText() == "openai/gpt-4o-mini"
    d._save_settings()
    assert fresh_config.get_llm_config()["model"] == "openai/gpt-4o-mini"

"""GUI-Test: Reiter „Allgemein“ der Einstellungen scrollt (Issue #235).

Ohne Scrollbereich war die Mindesthoehe des Dialogs so gross wie der ganze
Reiter; auf kleineren Bildschirmen quetschte Windows das Fenster trotzdem auf
Bildschirmhoehe, und Qt schob die Zeilen unleserlich uebereinander.
"""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QScrollArea

from src.gui.settings_dialog import SettingsDialog


@pytest.fixture
def fresh_config(monkeypatch, tmp_path):
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod
    from src.ml import classifier as cl_mod
    from src.ml import hybrid_classifier as hc_mod
    from src.core import pdf_cache as pc_mod

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


def _general_tab(dialog: SettingsDialog):
    assert dialog.show_tab("Allgemein")
    return dialog.tab_widget.currentWidget()


def test_allgemein_liegt_in_scrollbereich(qtbot, fresh_config):
    d = SettingsDialog()
    qtbot.addWidget(d)
    tab = _general_tab(d)
    assert isinstance(tab, QScrollArea)
    assert tab.widgetResizable()
    # Inhalt bleibt erreichbar (Debug-Gruppe ganz unten)
    assert tab.widget().isAncestorOf(d.clear_learning_button)


def test_dialog_darf_kleiner_als_reiterinhalt_sein(qtbot, fresh_config):
    """Die Mindesthoehe haengt nicht mehr an der Hoehe des Reiters."""
    d = SettingsDialog()
    qtbot.addWidget(d)
    inner = _general_tab(d).widget()
    assert d.minimumSizeHint().height() < inner.minimumSizeHint().height()


def test_startgroesse_nie_hoeher_als_bildschirm(qtbot, fresh_config):
    d = SettingsDialog()
    qtbot.addWidget(d)
    screen = d.screen()
    assert screen is not None
    assert d.height() <= int(screen.availableGeometry().height() * 0.9)
    assert d.height() >= d.minimumHeight()

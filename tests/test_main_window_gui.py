"""Smoke-Tests fuer das MainWindow (Phase 19 / STAB-Hardening).

MainWindow ist eine schwere Klasse (3169 Z), die viele Module-Singletons
initialisiert (Config, Database, FileManager, HybridClassifier, PDF-Cache).
Diese Tests pruefen nur die wichtigsten Strukturen:

* Konstruktion laeuft ohne Crash
* QTabWidget mit den Tabs 'Vorschau' und 'Chat' (Issue #20) ist da
* Statusbar existiert
* Folder-Tree ist da
* Tab-Wechsel zwischen 'Vorschau' und 'Chat' funktioniert

Die Singletons werden via ``monkeypatch`` auf ein tmp-DB-Verzeichnis
umgebogen, damit keine echte Datenbank im Test entsteht.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QTabWidget, QStatusBar, QWidget


# --------------------------------------------------------------------- #
# Fixtures: Singletons monkeypatchen
# --------------------------------------------------------------------- #


@pytest.fixture
def fresh_singletons(monkeypatch, tmp_path):
    """Setzt die Module-Singletons auf tmp-Pfade und leere Defaults.

    Dies ist notwendig, weil MainWindow im Konstruktor
    ``get_config()``, ``get_database()``, ``get_classifier()``,
    ``get_hybrid_classifier()`` und ``get_pdf_cache()`` aufruft -
    allesamt Module-Level-Singletons.
    """
    # 1) Config: zeige auf tmp_path
    db_path = tmp_path / "mainwindow_smoke.db"
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod
    from src.ml import classifier as cl_mod
    from src.ml import hybrid_classifier as hc_mod
    from src.core import pdf_cache as pc_mod

    # Frische Config-Instanz pro Test
    fresh_config = cfg_mod.Config(config_path=tmp_path / "config.json")
    monkeypatch.setattr(cfg_mod, "get_config", lambda: fresh_config)
    monkeypatch.setattr(db_mod, "get_database",
                        lambda: db_mod.Database(db_path=str(db_path)))
    monkeypatch.setattr(cl_mod, "get_classifier", cl_mod.PDFClassifier)
    monkeypatch.setattr(hc_mod, "get_hybrid_classifier",
                        hc_mod.HybridClassifier)
    # PDFCache: parameterlose Fabrik, liest Pfad aus Config
    monkeypatch.setattr(pc_mod, "get_pdf_cache", pc_mod.PDFCache)

    return {"config": fresh_config, "tmp_path": tmp_path}


@pytest.fixture
def main_window(qtbot, fresh_singletons, monkeypatch):
    """Eine frische MainWindow-Instanz, headless."""
    # QSettings org/App setzen, damit QSettings nicht in die echte
    # Windows-Registry schreibt
    from PyQt6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)

    # MainWindow in den offscreen-Modus zwingen
    from src.gui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.QMainWindow, "showMaximized", lambda self: None)
    monkeypatch.setattr(mw_mod.QMainWindow, "show", lambda self: None)

    win = mw_mod.MainWindow()
    qtbot.addWidget(win)
    return win


# --------------------------------------------------------------------- #
# 1) Konstruktion
# --------------------------------------------------------------------- #


def test_main_window_instantiates_without_exception(qtbot, fresh_singletons):
    """MainWindow laesst sich mit minimalem Setup konstruieren."""
    from src.gui import main_window as mw_mod
    win = mw_mod.MainWindow()
    qtbot.addWidget(win)
    assert win is not None
    assert isinstance(win, mw_mod.MainWindow)


def test_main_window_has_center_tabs(main_window):
    """MainWindow hat ein QTabWidget 'center_tabs'."""
    assert hasattr(main_window, "center_tabs")
    assert isinstance(main_window.center_tabs, QTabWidget)


def test_main_window_has_statusbar(main_window):
    """MainWindow hat eine QStatusBar."""
    assert hasattr(main_window, "statusbar")
    assert isinstance(main_window.statusbar, QStatusBar)


def test_main_window_has_folder_tree(main_window):
    """MainWindow hat einen folder_tree (FolderTreeWidget im rechten Bereich)."""
    assert hasattr(main_window, "folder_tree")
    assert main_window.folder_tree is not None


# --------------------------------------------------------------------- #
# 2) Tab-Inhalte (Issue #20)
# --------------------------------------------------------------------- #


def test_main_window_has_vorschau_tab(main_window):
    """Tab 'Vorschau' (alter 3-Spalten-Splitter) ist vorhanden."""
    tab_titles = [
        main_window.center_tabs.tabText(i)
        for i in range(main_window.center_tabs.count())
    ]
    assert "Vorschau" in tab_titles, f"Tab-Titel: {tab_titles}"


def test_main_window_has_chat_tab(main_window):
    """Tab 'Chat' (Issue #20) ist vorhanden."""
    tab_titles = [
        main_window.center_tabs.tabText(i)
        for i in range(main_window.center_tabs.count())
    ]
    assert "Chat" in tab_titles, f"Tab-Titel: {tab_titles}"


def test_main_window_has_exactly_two_center_tabs(main_window):
    """Das center_tabs-Widget hat genau 2 Tabs (Vorschau + Chat)."""
    assert main_window.center_tabs.count() == 2


# --------------------------------------------------------------------- #
# 3) Tab-Wechsel
# --------------------------------------------------------------------- #


def test_main_window_can_switch_to_chat_tab(qtbot, main_window):
    """Tab-Wechsel auf 'Chat' setzt den aktuellen Index korrekt."""
    # Finde Index des Chat-Tabs
    chat_idx = None
    for i in range(main_window.center_tabs.count()):
        if main_window.center_tabs.tabText(i) == "Chat":
            chat_idx = i
            break
    assert chat_idx is not None
    # Wechsle
    main_window.center_tabs.setCurrentIndex(chat_idx)
    qtbot.waitUntil(lambda: main_window.center_tabs.currentIndex() == chat_idx,
                    timeout=2000)
    assert main_window.center_tabs.currentIndex() == chat_idx


def test_main_window_can_switch_back_to_vorschau_tab(qtbot, main_window):
    """Tab-Wechsel zurueck auf 'Vorschau' funktioniert ebenfalls."""
    vorschau_idx = None
    for i in range(main_window.center_tabs.count()):
        if main_window.center_tabs.tabText(i) == "Vorschau":
            vorschau_idx = i
            break
    assert vorschau_idx is not None
    main_window.center_tabs.setCurrentIndex(vorschau_idx)
    qtbot.waitUntil(
        lambda: main_window.center_tabs.currentIndex() == vorschau_idx,
        timeout=2000,
    )
    assert main_window.center_tabs.currentIndex() == vorschau_idx


# --------------------------------------------------------------------- #
# 4) DetailPanel und PDF-Listen existieren
# --------------------------------------------------------------------- #


def test_main_window_has_detail_panel(main_window):
    """MainWindow hat ein detail_panel (mittlerer Bereich)."""
    assert hasattr(main_window, "detail_panel")
    assert isinstance(main_window.detail_panel, QWidget)


def test_main_window_has_suggestion_widgets_list(main_window):
    """MainWindow hat eine suggestion_widgets-Liste (linke Spalte)."""
    assert hasattr(main_window, "suggestion_widgets")
    assert isinstance(main_window.suggestion_widgets, list)


def test_main_window_has_pdf_widgets_list(main_window):
    """MainWindow hat eine pdf_widgets-Liste (linke Spalte, PDFs)."""
    assert hasattr(main_window, "pdf_widgets")
    assert isinstance(main_window.pdf_widgets, list)


# --------------------------------------------------------------------- #
# 5) Robustheit
# --------------------------------------------------------------------- #


def test_main_window_handles_multiple_construction(qtbot, fresh_singletons):
    """Mehrere MainWindow-Instanzen hintereinander crashen nicht."""
    from src.gui import main_window as mw_mod
    win1 = mw_mod.MainWindow()
    qtbot.addWidget(win1)
    win2 = mw_mod.MainWindow()
    qtbot.addWidget(win2)
    # Beide haben unabhängige Tab-Widgets
    assert win1.center_tabs is not win2.center_tabs

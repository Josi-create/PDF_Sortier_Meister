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
from PyQt6 import sip
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

    # Frische Config-Instanz pro Test. Die Fabriken werden in ALLEN src-Modulen
    # ersetzt (siehe conftest.patch_singletons) - sonst haengt es von der
    # Import-Reihenfolge ab, welche Config MainWindow tatsaechlich sieht.
    from tests.conftest import patch_singletons
    fresh_config = cfg_mod.Config(config_path=tmp_path / "config.json")
    fresh_config.set("persist_pdf_cache", False)
    monkeypatch.setattr(pc_mod.PDFCache, "_instance", None)
    patch_singletons(monkeypatch, {
        "get_config": lambda: fresh_config,
        "get_database": lambda: db_mod.Database(db_path=str(db_path)),
        "get_classifier": cl_mod.PDFClassifier,
        "get_hybrid_classifier": hc_mod.HybridClassifier,
        "get_pdf_cache": pc_mod.PDFCache,
    })

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
    yield win

    # Bewusst nicht qtbot.addWidget(): das raeumt nur per deleteLater() auf,
    # und MainWindow haengt in einem Referenzzyklus - das alte Fenster lebte
    # so bis zum naechsten GC-Lauf weiter, mitsamt scharfer Timer, die dann
    # waehrend eines spaeteren Tests auf ein halb zerstoertes Fenster feuerten
    # (Access Violation auf langsamen CI-Runnern). Deshalb sofort zerstoeren.
    win.close()
    sip.delete(win)


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


# --------------------------------------------------------------------- #
# Explorer-Gefuehl (Sprint 1, Issues #29/#26): Ordner-Kacheln + Breadcrumb
# --------------------------------------------------------------------- #


def _scan_tree(tmp_path):
    scan = tmp_path / "Dokumente" / "FrischGescannt"
    (scan / "Steuer 2026").mkdir(parents=True)
    (scan / "Banken").mkdir()
    (scan / ".versteckt").mkdir()
    (scan / "Banken" / "kontoauszug.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    return scan


def test_load_pdfs_shows_parent_and_subfolder_tiles(main_window, fresh_singletons):
    scan = _scan_tree(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)

    tiles = main_window.folder_tiles
    assert [t.name_label.text() for t in tiles] == ["..", "Banken", "Steuer 2026"]
    assert tiles[0].is_parent and tiles[0].folder_path == scan.parent
    assert tiles[1].count_label.text() == "1 PDF"
    assert main_window.pdf_scroll_area.isVisibleTo(main_window)  # trotz 0 PDFs sichtbar
    assert "2 Ordner" in main_window.pdf_folder_count_label.text()


def test_tile_double_click_navigates_into_folder(main_window, fresh_singletons):
    scan = _scan_tree(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)

    banken = next(t for t in main_window.folder_tiles if t.name_label.text() == "Banken")
    banken.double_clicked.emit(banken.folder_path)

    assert fresh_singletons["config"].get_scan_folder() == scan / "Banken"
    assert len(main_window.pdf_widgets) == 1
    assert main_window._folder_history[-1] == scan
    # ".." fuehrt wieder nach oben
    assert main_window.folder_tiles[0].is_parent
    assert main_window.folder_tiles[0].folder_path == scan


def test_breadcrumb_lists_path_segments(main_window, fresh_singletons):
    from PyQt6.QtWidgets import QToolButton
    scan = _scan_tree(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)

    buttons = [
        main_window.breadcrumb_layout.itemAt(i).widget()
        for i in range(main_window.breadcrumb_layout.count())
        if isinstance(main_window.breadcrumb_layout.itemAt(i).widget(), QToolButton)
    ]
    assert [b.text() for b in buttons][-2:] == ["Dokumente", "FrischGescannt"]
    assert not buttons[-1].isEnabled()  # aktueller Ordner nicht klickbar
    assert buttons[-2].isEnabled()



# --------------------------------------------------------------------- #
# Erster Klick nach dem Start: nicht blockieren, sondern nachziehen
# --------------------------------------------------------------------- #


def test_click_before_model_ready_defers_and_applies_later(main_window, fresh_singletons, qtbot, monkeypatch):
    from src.core.pdf_cache import PDFAnalysisResult
    from PyQt6.QtWidgets import QApplication

    pdf = fresh_singletons["tmp_path"] / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    main_window.selected_pdf = pdf
    result = PDFAnalysisResult(pdf_path=pdf, extracted_text="rechnung", keywords=["rechnung"])

    ready = {"v": False}
    monkeypatch.setattr(main_window.classifier, "is_model_ready", lambda: ready["v"])
    applied = []
    monkeypatch.setattr(main_window, "display_suggestions", lambda s: applied.append(s))

    main_window._apply_analysis_result(pdf, result)
    assert applied == []                      # noch nichts angewendet ...
    assert main_window._model_wait_active     # ... aber Wartezustand aktiv
    assert QApplication.overrideCursor() is not None
    assert "geladen" in main_window.statusbar.currentMessage()

    ready["v"] = True
    qtbot.waitUntil(lambda: bool(applied), timeout=2000)
    assert not main_window._model_wait_active
    assert QApplication.overrideCursor() is None


def test_model_wait_cancelled_when_selection_changes(main_window, fresh_singletons, qtbot, monkeypatch):
    from src.core.pdf_cache import PDFAnalysisResult
    from PyQt6.QtWidgets import QApplication

    pdf = fresh_singletons["tmp_path"] / "y.pdf"; pdf.write_bytes(b"%PDF-1.4")
    main_window.selected_pdf = pdf
    monkeypatch.setattr(main_window.classifier, "is_model_ready", lambda: False)
    main_window._apply_analysis_result(pdf, PDFAnalysisResult(pdf_path=pdf))
    assert main_window._model_wait_active

    main_window.selected_pdf = None  # Nutzer hat abgewaehlt
    qtbot.waitUntil(lambda: not main_window._model_wait_active, timeout=2000)
    assert QApplication.overrideCursor() is None


def test_close_stops_window_timers(main_window, fresh_singletons):
    """Nach close() darf kein fenstergebundener Timer mehr feuern.

    Sonst trifft z.B. der 500-ms-Pre-Caching-Timer auf ein bereits (teil-)
    zerstoertes Fenster - auf langsamen CI-Runnern ein harter Absturz.
    """
    main_window._schedule_pre_caching([fresh_singletons["tmp_path"] / "a.pdf"])
    main_window._grid_relayout_timer.start()
    assert main_window._precache_timer.isActive()

    main_window.close()

    assert not main_window._precache_timer.isActive()
    assert not main_window._grid_relayout_timer.isActive()


def test_close_waits_for_child_threads(main_window):
    """close() laesst QThreads mit Widget-Parent zu Ende laufen.

    Ordner-Scan und Metadaten-Leser haengen als Kinder am Fenster. Wird das
    Fenster zerstoert, waehrend so ein Thread laeuft, bricht Qt den Prozess
    hart ab - auf langsamen CI-Runnern regelmaessig beim Aufraeumen.
    """
    import time
    from PyQt6.QtCore import QThread

    class _Slow(QThread):
        def run(self):
            time.sleep(0.3)

    thread = _Slow(main_window.detail_panel)
    thread.start()
    assert thread.isRunning()

    main_window.close()

    assert thread.isFinished()


# --------------------------------------------------------------------- #
# 5) Erste-Schritte-Hinweis (Issue #51)
# --------------------------------------------------------------------- #


def test_first_steps_hint_skipped_when_dismissed(main_window, monkeypatch):
    """Bei gesetztem Config-Flag und ohne force wird kein Dialog gezeigt."""
    from PyQt6.QtWidgets import QMessageBox

    main_window.config.set("first_steps_hint_dismissed", True)
    calls = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: calls.append(True))

    main_window.show_first_steps_hint()

    assert calls == []


def test_first_steps_hint_shown_when_not_dismissed(main_window, monkeypatch):
    """Ohne gesetztes Flag erscheint der Dialog beim Start."""
    from PyQt6.QtWidgets import QMessageBox

    main_window.config.set("first_steps_hint_dismissed", False)
    calls = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: calls.append(True))

    main_window.show_first_steps_hint()

    assert calls == [True]


def test_first_steps_hint_force_ignores_dismissed_flag(main_window, monkeypatch):
    """Ueber das Hilfe-Menue (force=True) erscheint der Dialog immer."""
    from PyQt6.QtWidgets import QMessageBox

    main_window.config.set("first_steps_hint_dismissed", True)
    calls = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: calls.append(True))

    main_window.show_first_steps_hint(force=True)

    assert calls == [True]

"""GUI-Tests fuer die Update-Pruefung im Hauptfenster (Issue #73).

Kein Netzwerk: Der Hintergrund-Thread wird nicht gestartet, stattdessen wird
der Ergebnis-Slot ``_on_update_check_finished`` direkt aufgerufen. Der
Update-Dialog wird durch einen Recorder ersetzt, damit nichts modal blockiert.
"""
from __future__ import annotations

import pytest

from src.utils.update_check import UpdateInfo


@pytest.fixture
def fresh_singletons(monkeypatch, tmp_path):
    from src.core import pdf_cache as pc_mod
    from src.ml import classifier as cl_mod
    from src.ml import hybrid_classifier as hc_mod
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod
    from tests.conftest import patch_singletons

    fresh_config = cfg_mod.Config(config_path=tmp_path / "config.json")
    fresh_config.set("persist_pdf_cache", False)
    monkeypatch.setattr(pc_mod.PDFCache, "_instance", None)
    patch_singletons(monkeypatch, {
        "get_config": lambda: fresh_config,
        "get_database": lambda: db_mod.Database(db_path=str(tmp_path / "u.db")),
        "get_classifier": cl_mod.PDFClassifier,
        "get_hybrid_classifier": hc_mod.HybridClassifier,
        "get_pdf_cache": pc_mod.PDFCache,
    })
    return fresh_config


@pytest.fixture
def main_window(qtbot, fresh_singletons, monkeypatch):
    from PyQt6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)

    from src.gui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.QMainWindow, "showMaximized", lambda self: None)
    monkeypatch.setattr(mw_mod.QMainWindow, "show", lambda self: None)

    win = mw_mod.MainWindow()
    qtbot.addWidget(win)
    yield win
    win.close()


@pytest.fixture
def dialog_recorder(monkeypatch):
    """Ersetzt den modalen Update-Dialog durch einen Aufruf-Recorder."""
    from src.gui import main_window as mw_mod

    calls = []
    monkeypatch.setattr(
        mw_mod.MainWindow, "_show_update_dialog", lambda self, info: calls.append(info)
    )
    return calls


def _info(version="0.99.0"):
    return UpdateInfo(
        version=version,
        tag=f"v{version}",
        page_url="https://github.com/Josi-create/PDF_Sortier_Meister/releases/latest",
        download_url="https://dl/Setup.exe",
        asset_name="PDF_Sortier_Meister_Setup.exe",
        notes="Notes",
    )


# --------------------------------------------------------------------- #
# Struktur
# --------------------------------------------------------------------- #


def test_window_has_hidden_update_label_and_help_action(main_window):
    assert main_window.update_status_label.isHidden()
    help_menu = next(
        m for m in main_window.menuBar().findChildren(type(main_window.menuBar().actions()[0].menu()))
        if m.title() == "Hilfe"
    )
    titles = [a.text() for a in help_menu.actions()]
    assert "Nach Updates suchen..." in titles


def test_constructor_does_not_start_update_thread(main_window):
    # Der Netzwerkzugriff wird erst durch main.py via schedule_update_check geplant.
    assert main_window._update_thread is None


# --------------------------------------------------------------------- #
# Ergebnis-Verarbeitung
# --------------------------------------------------------------------- #


def test_update_available_shows_status_and_dialog(main_window, dialog_recorder):
    main_window._on_update_check_finished(_info("0.99.0"), "", manual=False)

    assert not main_window.update_status_label.isHidden()
    assert "0.99.0" in main_window.update_status_label.text()
    assert main_window._available_update is not None
    assert len(dialog_recorder) == 1 and dialog_recorder[0].version == "0.99.0"


def test_skipped_version_is_silent_on_automatic_check(main_window, dialog_recorder, fresh_singletons):
    fresh_singletons.set("update_skipped_version", "0.99.0")

    main_window._on_update_check_finished(_info("0.99.0"), "", manual=False)

    assert main_window.update_status_label.isHidden()
    assert dialog_recorder == []


def test_skipped_version_still_shown_on_manual_check(main_window, dialog_recorder, fresh_singletons):
    fresh_singletons.set("update_skipped_version", "0.99.0")

    main_window._on_update_check_finished(_info("0.99.0"), "", manual=True)

    assert len(dialog_recorder) == 1


def test_newer_release_after_skip_is_shown_again(main_window, dialog_recorder, fresh_singletons):
    fresh_singletons.set("update_skipped_version", "0.99.0")

    main_window._on_update_check_finished(_info("0.99.1"), "", manual=False)

    assert len(dialog_recorder) == 1


def test_skip_update_persists_version_and_hides_label(main_window, dialog_recorder, fresh_singletons):
    info = _info("0.99.0")
    main_window._on_update_check_finished(info, "", manual=False)
    assert not main_window.update_status_label.isHidden()

    main_window._skip_update(info)

    assert fresh_singletons.get("update_skipped_version") == "0.99.0"
    assert main_window.update_status_label.isHidden()
    assert main_window._available_update is None


def test_no_update_is_silent_when_automatic(main_window, dialog_recorder, monkeypatch):
    from src.gui import main_window as mw_mod
    boxes = []
    monkeypatch.setattr(mw_mod.QMessageBox, "information",
                        staticmethod(lambda *a, **k: boxes.append(a)))

    main_window._on_update_check_finished(None, "", manual=False)

    assert boxes == [] and dialog_recorder == []
    assert main_window.update_status_label.isHidden()


def test_no_update_reports_current_version_when_manual(main_window, monkeypatch):
    from src.gui import main_window as mw_mod
    from src.main import __version__
    boxes = []
    monkeypatch.setattr(mw_mod.QMessageBox, "information",
                        staticmethod(lambda *a, **k: boxes.append(a)))

    main_window._on_update_check_finished(None, "", manual=True)

    assert len(boxes) == 1
    assert __version__ in boxes[0][2]


def test_error_is_silent_when_automatic_but_warns_when_manual(main_window, monkeypatch):
    from src.gui import main_window as mw_mod
    warnings = []
    monkeypatch.setattr(mw_mod.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warnings.append(a)))

    main_window._on_update_check_finished(None, "Verbindung fehlgeschlagen", manual=False)
    assert warnings == []

    main_window._on_update_check_finished(None, "Verbindung fehlgeschlagen", manual=True)
    assert len(warnings) == 1
    assert "Verbindung fehlgeschlagen" in warnings[0][2]


# --------------------------------------------------------------------- #
# Planung beim Start + Einstellung
# --------------------------------------------------------------------- #


def test_schedule_respects_setting(main_window, fresh_singletons, monkeypatch):
    from src.gui import main_window as mw_mod
    scheduled = []
    monkeypatch.setattr(mw_mod.QTimer, "singleShot",
                        staticmethod(lambda ms, fn: scheduled.append(ms)))

    assert main_window.schedule_update_check() is True
    assert scheduled == [3000]

    fresh_singletons.set("update_check_enabled", False)
    assert main_window.schedule_update_check() is False
    assert scheduled == [3000]


def test_settings_dialog_round_trips_update_setting(qtbot, fresh_singletons):
    from src.gui.settings_dialog import SettingsDialog

    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    assert dialog.update_check_checkbox.isChecked()

    dialog.update_check_checkbox.setChecked(False)
    dialog._save_settings()

    assert fresh_singletons.get("update_check_enabled") is False

    dialog2 = SettingsDialog()
    qtbot.addWidget(dialog2)
    assert not dialog2.update_check_checkbox.isChecked()

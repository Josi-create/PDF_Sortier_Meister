"""Integration der PDF-Vorschau in Detail-Panel, Hauptfenster und Einstellungen (Issues #74/#76).

Kein Netzwerk, keine echten Prozesse: externes Oeffnen wird abgefangen.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest


def _make_pdf(path: Path, pages: int = 2) -> Path:
    doc = fitz.open()
    try:
        for i in range(pages):
            doc.new_page().insert_text((72, 72), f"Seite {i + 1}")
        doc.save(str(path))
    finally:
        doc.close()
    return path


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
        "get_database": lambda: db_mod.Database(db_path=str(tmp_path / "p.db")),
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
    # Nur das Hauptfenster stumm schalten - das Vorschau-Fenster (auch ein
    # QMainWindow) soll sich in den Tests echt zeigen koennen.
    monkeypatch.setattr(mw_mod.MainWindow, "showMaximized", lambda self: None)
    monkeypatch.setattr(mw_mod.MainWindow, "show", lambda self: None)

    win = mw_mod.MainWindow()
    qtbot.addWidget(win)
    yield win
    win.close()


@pytest.fixture
def external_spy(monkeypatch):
    """Faengt open_pdf_externally im Hauptfenster-Modul ab."""
    from src.gui import main_window as mw_mod
    calls = []

    def fake(path, mode, command):
        calls.append((Path(path), mode, command))
        return True, ""

    monkeypatch.setattr(mw_mod, "open_pdf_externally", fake)
    return calls


# --------------------------------------------------------------------- #
# Detail-Panel: Vorschau unten
# --------------------------------------------------------------------- #


def test_detail_panel_has_preview_below_details(qtbot, tmp_path, monkeypatch):
    from src.core.pdf_metadata import PDFMetadata
    from src.gui import detail_panel as dp
    monkeypatch.setattr("src.core.pdf_metadata.read_metadata", lambda p: PDFMetadata())

    panel = dp.DetailPanel()
    qtbot.addWidget(panel)
    panel.resize(500, 900)
    panel.show()
    assert panel.splitter.count() == 2
    assert panel.splitter.widget(1) is panel.preview
    assert not panel.preview.is_showing_document()

    pdf = _make_pdf(tmp_path / "beleg.pdf", pages=2)
    with qtbot.waitSignal(panel.preview.document_loaded, timeout=5000):
        panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="x", keywords=["rechnung"])

    assert panel.preview.current_path == pdf
    assert panel.preview.page_count() == 2

    panel.clear()
    assert panel.preview.current_path is None
    assert not panel.preview.is_showing_document()


def test_detail_panel_forwards_preview_signals(qtbot, tmp_path, monkeypatch):
    from src.core.pdf_metadata import PDFMetadata
    from src.gui import detail_panel as dp
    monkeypatch.setattr("src.core.pdf_metadata.read_metadata", lambda p: PDFMetadata())

    panel = dp.DetailPanel()
    qtbot.addWidget(panel)
    pdf = _make_pdf(tmp_path / "a.pdf")
    with qtbot.waitSignal(panel.preview.document_loaded, timeout=5000):
        panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="", keywords=[])

    with qtbot.waitSignal(panel.enlarge_preview_requested, timeout=1000) as big:
        panel.preview.enlarge_btn.click()
    assert big.args == [pdf]

    with qtbot.waitSignal(panel.open_pdf_external_requested, timeout=1000) as ext:
        panel.preview.external_btn.click()
    assert ext.args == [pdf]


def test_search_result_double_click_emits_open_request(qtbot, tmp_path):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QListWidgetItem

    from src.gui import detail_panel as dp

    panel = dp.DetailPanel()
    qtbot.addWidget(panel)
    pdf = _make_pdf(tmp_path / "treffer.pdf")
    item = QListWidgetItem("treffer.pdf")
    item.setData(Qt.ItemDataRole.UserRole, str(pdf))

    with qtbot.waitSignal(panel.open_pdf_requested, timeout=1000) as blocker:
        panel._on_search_result_double_clicked(item)
    assert blocker.args == [pdf]


# --------------------------------------------------------------------- #
# Hauptfenster: open_pdf je nach Einstellung
# --------------------------------------------------------------------- #


def test_default_mode_opens_integrated_preview_window(qtbot, tmp_path, main_window, external_spy):
    pdf = _make_pdf(tmp_path / "a.pdf", pages=3)
    assert main_window._preview_window is None

    main_window.open_pdf(pdf)

    win = main_window._preview_window
    assert win is not None and win.isVisible()
    qtbot.waitUntil(lambda: win.preview.page_count() == 3, timeout=5000)
    assert win.current_path() == pdf
    assert external_spy == []

    # Zweites Oeffnen nutzt dasselbe Fenster
    b = _make_pdf(tmp_path / "b.pdf", pages=1)
    main_window.open_pdf(b)
    assert main_window._preview_window is win
    qtbot.waitUntil(lambda: win.current_path() == b, timeout=5000)


def test_double_click_and_thumbnail_open_route_through_open_pdf(qtbot, tmp_path, main_window, monkeypatch):
    opened = []
    monkeypatch.setattr(type(main_window), "open_pdf", lambda self, p: opened.append(Path(p)))
    pdf = tmp_path / "a.pdf"

    main_window.on_pdf_double_clicked(pdf)
    main_window._open_pdf_external(str(pdf))  # Chat-Zitat

    assert opened == [pdf, pdf]


def test_system_mode_opens_externally(qtbot, tmp_path, main_window, fresh_singletons, external_spy):
    fresh_singletons.set("pdf_open_mode", "system")
    pdf = _make_pdf(tmp_path / "a.pdf")

    main_window.open_pdf(pdf)

    assert external_spy == [(pdf, "system", "")]
    assert main_window._preview_window is None


def test_custom_mode_passes_command(qtbot, tmp_path, main_window, fresh_singletons, external_spy):
    fresh_singletons.set("pdf_open_mode", "custom")
    fresh_singletons.set("pdf_open_command", r"C:\Tools\PDFXEdit.exe")
    pdf = _make_pdf(tmp_path / "a.pdf")

    main_window.open_pdf(pdf)

    assert external_spy == [(pdf, "custom", r"C:\Tools\PDFXEdit.exe")]


def test_external_failure_shows_warning(qtbot, tmp_path, main_window, fresh_singletons, monkeypatch):
    from src.gui import main_window as mw_mod
    fresh_singletons.set("pdf_open_mode", "system")
    monkeypatch.setattr(mw_mod, "open_pdf_externally", lambda p, m, c: (False, "Kaputt"))
    warnings = []
    monkeypatch.setattr(mw_mod.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warnings.append(a)))

    main_window.open_pdf(_make_pdf(tmp_path / "a.pdf"))

    assert len(warnings) == 1 and "Kaputt" in warnings[0][2]


def test_preview_window_geometry_is_persisted(qtbot, tmp_path, main_window, fresh_singletons):
    pdf = _make_pdf(tmp_path / "a.pdf")
    main_window.open_pdf(pdf)
    win = main_window._preview_window
    qtbot.waitUntil(lambda: win.preview.page_count() == 2, timeout=5000)
    win.resize(640, 720)

    win.close()

    saved = fresh_singletons.get("preview_window_geometry")
    assert len(saved) == 4 and saved[2] == 640 and saved[3] == 720


def test_thumbnail_open_requested_is_connected(qtbot, tmp_path, main_window, fresh_singletons, monkeypatch):
    """Kontextmenue 'PDF oeffnen' des Thumbnails laeuft ueber open_pdf."""
    from src.gui import pdf_thumbnail as thumb_mod
    from src.gui.pdf_thumbnail import PDFThumbnailWidget
    # Kein Thumbnail-Thread im Test (wuerde beim Teardown noch laufen)
    monkeypatch.setattr(thumb_mod.ThumbnailLoaderThread, "start", lambda self: None)
    opened = []
    monkeypatch.setattr(type(main_window), "open_pdf", lambda self, p: opened.append(Path(p)))

    pdf = _make_pdf(tmp_path / "thumb.pdf")
    widget = PDFThumbnailWidget(pdf)
    qtbot.addWidget(widget)
    widget.open_requested.connect(main_window.open_pdf)
    widget._open_pdf()

    assert opened == [pdf]


# --------------------------------------------------------------------- #
# Einstellungen
# --------------------------------------------------------------------- #


def test_settings_round_trip_pdf_open(qtbot, fresh_singletons):
    from src.gui.settings_dialog import SettingsDialog

    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    assert dialog.pdf_open_mode_combo.currentData() == "integrated"
    assert not dialog.pdf_open_command_input.isEnabled()

    dialog.pdf_open_mode_combo.setCurrentIndex(dialog.pdf_open_mode_combo.findData("custom"))
    assert dialog.pdf_open_command_input.isEnabled()
    dialog.pdf_open_command_input.setText(r"C:\Tools\PDFXEdit.exe")
    dialog._save_settings()

    assert fresh_singletons.get("pdf_open_mode") == "custom"
    assert fresh_singletons.get("pdf_open_command") == r"C:\Tools\PDFXEdit.exe"

    dialog2 = SettingsDialog()
    qtbot.addWidget(dialog2)
    assert dialog2.pdf_open_mode_combo.currentData() == "custom"
    assert dialog2.pdf_open_command_input.text() == r"C:\Tools\PDFXEdit.exe"
    assert dialog2.pdf_open_command_input.isEnabled()


def test_settings_unknown_mode_falls_back_to_integrated(qtbot, fresh_singletons):
    from src.gui.settings_dialog import SettingsDialog
    fresh_singletons.set("pdf_open_mode", "browser")

    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    assert dialog.pdf_open_mode_combo.currentData() == "integrated"

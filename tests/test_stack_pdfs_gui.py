"""GUI-Tests fuers Stapeln: PDF auf eine andere PDF ziehen haengt die Seiten
an (wie in PaperPort), Ctrl+Z macht es rueckgaengig.

Fixtures folgen dem Muster aus ``tests/test_auto_next_after_move_gui.py``.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import fitz
import pytest
from PyQt6 import sip
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PyQt6.QtWidgets import QApplication, QMessageBox

from src.gui.farben import css
from src.gui.pdf_thumbnail import PDFThumbnailWidget

# --------------------------------------------------------------------- #
# Fixtures (wie in test_auto_next_after_move_gui.py)
# --------------------------------------------------------------------- #


@pytest.fixture
def fresh_singletons(monkeypatch, tmp_path):
    db_path = tmp_path / "stack_smoke.db"
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
        "get_database": lambda: db_mod.Database(db_path=str(db_path)),
        "get_classifier": cl_mod.PDFClassifier,
        "get_hybrid_classifier": hc_mod.HybridClassifier,
        "get_pdf_cache": pc_mod.PDFCache,
    })
    return {"config": fresh_config, "tmp_path": tmp_path}


@pytest.fixture
def no_background_threads(monkeypatch):
    # Thumbnail-, Vorschau- und XMP-Leser halten die PDF unter Windows offen
    from src.gui import detail_panel as dp_mod
    from src.gui import pdf_thumbnail as th_mod
    monkeypatch.setattr(th_mod.ThumbnailLoaderThread, "start", lambda self: None)
    monkeypatch.setattr(dp_mod.PdfPreviewWidget, "load_pdf", lambda self, path: None)
    monkeypatch.setattr(dp_mod._PdfMetadataReader, "start", lambda self: None)


@pytest.fixture
def main_window(qtbot, fresh_singletons, no_background_threads, monkeypatch):
    from PyQt6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)

    from src.gui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.QMainWindow, "showMaximized", lambda self: None)
    monkeypatch.setattr(mw_mod.QMainWindow, "show", lambda self: None)
    monkeypatch.setattr(
        mw_mod.QMessageBox, "question",
        lambda *a, **k: QMessageBox.StandardButton.Yes,
    )

    def _critical(*a, **k):
        raise AssertionError(f"QMessageBox.critical: {a[1]!s}: {a[2]!s}")
    monkeypatch.setattr(mw_mod.QMessageBox, "critical", _critical)
    monkeypatch.setattr(mw_mod.QMessageBox, "warning", lambda *a, **k: None)

    win = mw_mod.MainWindow()
    monkeypatch.setattr(win.classifier, "is_model_ready", lambda: True)
    # Analyse/Vorschlaege sind hier egal und starten sonst Hintergrund-Worker
    monkeypatch.setattr(win, "update_suggestions_for_pdf", lambda path: None)
    backup_root = fresh_singletons["tmp_path"] / "stapel_sicherung"
    monkeypatch.setattr(win, "_stack_backup_root", lambda: backup_root)

    yield win

    win.close()
    sip.delete(win)


def _create_pdf(path: Path, pages: int, label: str) -> None:
    doc = fitz.open()
    try:
        for i in range(pages):
            doc.new_page().insert_text((72, 72), f"{label} Seite {i + 1}")
        doc.save(str(path))
    finally:
        doc.close()


def _page_count(path: Path) -> int:
    with fitz.open(str(path)) as doc:
        return len(doc)


def _mime(paths: list[Path]) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


_ACTIONS = Qt.DropAction.MoveAction | Qt.DropAction.CopyAction


def _send_drag_enter(widget, mime) -> QDragEnterEvent:
    event = QDragEnterEvent(QPoint(5, 5), _ACTIONS, mime, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)
    return event


def _send_drop(widget, mime) -> QDropEvent:
    # Qt stellt ein Drop nur nach angenommenem DragEnter zu - wie bei echter Maus
    _send_drag_enter(widget, mime)
    event = QDropEvent(QPointF(5, 5), _ACTIONS, mime, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)
    return event


# --------------------------------------------------------------------- #
# Kachel: PDF darauf ablegen
# --------------------------------------------------------------------- #


def test_thumbnail_accepts_other_pdf_as_copy_and_highlights(qtbot, tmp_path, no_background_threads):
    target = tmp_path / "a.pdf"
    other = tmp_path / "b.pdf"
    _create_pdf(target, 1, "A")
    _create_pdf(other, 1, "B")
    w = PDFThumbnailWidget(target)
    qtbot.addWidget(w)

    enter = _send_drag_enter(w, _mime([other]))
    assert enter.isAccepted()
    assert enter.dropAction() == Qt.DropAction.CopyAction  # nie "Verschieben"
    assert css(w.STACK_BORDER) in w.styleSheet()

    QApplication.sendEvent(w, QDragLeaveEvent())
    assert css(w.STACK_BORDER) not in w.styleSheet()


def test_thumbnail_drop_requests_stack(qtbot, tmp_path, no_background_threads):
    target = tmp_path / "a.pdf"
    other = tmp_path / "b.pdf"
    _create_pdf(target, 1, "A")
    _create_pdf(other, 1, "B")
    w = PDFThumbnailWidget(target)
    qtbot.addWidget(w)

    # Mehrfachauswahl inkl. der Ziel-PDF selbst: nur die anderen werden angehaengt
    with qtbot.waitSignal(w.stack_requested, timeout=1000) as blocker:
        drop = _send_drop(w, _mime([target, other]))
    assert drop.isAccepted()
    assert drop.dropAction() == Qt.DropAction.CopyAction
    assert blocker.args == [[other], target]


def test_thumbnail_ignores_itself_and_non_pdfs(qtbot, tmp_path, no_background_threads):
    target = tmp_path / "a.pdf"
    text = tmp_path / "notiz.txt"
    _create_pdf(target, 1, "A")
    text.write_text("x")
    w = PDFThumbnailWidget(target)
    qtbot.addWidget(w)

    assert not _send_drag_enter(w, _mime([target])).isAccepted()
    assert not _send_drag_enter(w, _mime([text])).isAccepted()
    assert css(w.STACK_BORDER) not in w.styleSheet()


# --------------------------------------------------------------------- #
# Hauptfenster: Stapeln und Rueckgaengig
# --------------------------------------------------------------------- #


def test_stack_appends_pages_removes_tile_and_undo_restores(main_window, fresh_singletons):
    scan = fresh_singletons["tmp_path"] / "Scan"
    scan.mkdir()
    a, b = scan / "a.pdf", scan / "b.pdf"
    _create_pdf(a, 1, "A")
    _create_pdf(b, 2, "B")
    main_window._navigate_to_folder(scan)
    assert len(main_window.pdf_widgets) == 2

    main_window.on_pdf_stacked([b], a)

    assert _page_count(a) == 3
    assert not b.exists()
    assert [w.pdf_path for w in main_window.pdf_widgets] == [a]
    assert main_window.selected_pdf == a
    assert main_window._undo_stack[-1]["type"] == "stack"
    assert "b.pdf" in main_window.undo_action.text()

    main_window.undo_last_action()

    assert _page_count(a) == 1
    assert _page_count(b) == 2
    assert sorted(w.pdf_path.name for w in main_window.pdf_widgets) == ["a.pdf", "b.pdf"]
    assert main_window._undo_stack == []


def test_old_stack_backups_are_pruned(main_window):
    root = main_window._stack_backup_root()
    old = root / "20250101-000000-000000"
    new = root / "neu"
    old.mkdir(parents=True)
    new.mkdir()
    long_ago = time.time() - (main_window.STACK_BACKUP_DAYS + 1) * 86400
    os.utime(old, (long_ago, long_ago))

    main_window._prune_stack_backups()

    assert not old.exists()
    assert new.exists()

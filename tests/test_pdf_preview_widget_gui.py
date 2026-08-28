"""GUI-Tests fuer die integrierte PDF-Vorschau (QtPdf, Issues #74/#76)."""
from __future__ import annotations

import os
from pathlib import Path

import fitz
import pytest
from PyQt6.QtPdfWidgets import QPdfView

from src.gui.pdf_preview_widget import PdfPreviewWidget
from src.gui.pdf_preview_window import PdfPreviewWindow


def _make_pdf(path: Path, pages: int = 3) -> Path:
    doc = fitz.open()
    try:
        for i in range(pages):
            page = doc.new_page()
            page.insert_text((72, 72), f"Seite {i + 1}")
        doc.save(str(path))
    finally:
        doc.close()
    return path


@pytest.fixture
def widget(qtbot):
    w = PdfPreviewWidget(compact=True)
    qtbot.addWidget(w)
    w.resize(400, 600)
    w.show()
    yield w
    w.shutdown()


def test_empty_widget_shows_placeholder(widget):
    assert not widget.is_showing_document()
    assert widget.page_count() == 0
    assert "Keine PDF" in widget.message_label.text()
    assert not widget.next_btn.isEnabled()


def test_load_pdf_async_shows_document(qtbot, tmp_path, widget):
    pdf = _make_pdf(tmp_path / "drei.pdf", pages=3)

    with qtbot.waitSignal(widget.document_loaded, timeout=5000) as blocker:
        widget.load_pdf(pdf)

    assert blocker.args == [pdf]
    assert widget.is_showing_document()
    assert widget.page_count() == 3
    assert widget.current_path == pdf
    assert widget.page_label.text() == "1 / 3"
    assert widget.zoom_mode() == QPdfView.ZoomMode.FitToWidth


def test_page_navigation(qtbot, tmp_path, widget):
    pdf = _make_pdf(tmp_path / "drei.pdf", pages=3)
    with qtbot.waitSignal(widget.document_loaded, timeout=5000):
        widget.load_pdf(pdf)

    assert not widget.prev_btn.isEnabled()
    widget.next_page()
    qtbot.waitUntil(lambda: widget.current_page() == 1, timeout=2000)
    assert widget.page_label.text() == "2 / 3"
    assert widget.prev_btn.isEnabled()

    widget.go_to_page(99)  # wird auf die letzte Seite begrenzt
    qtbot.waitUntil(lambda: widget.current_page() == 2, timeout=2000)
    assert not widget.next_btn.isEnabled()

    widget.previous_page()
    qtbot.waitUntil(lambda: widget.current_page() == 1, timeout=2000)


def test_zoom_controls(qtbot, tmp_path, widget):
    pdf = _make_pdf(tmp_path / "eins.pdf", pages=1)
    with qtbot.waitSignal(widget.document_loaded, timeout=5000):
        widget.load_pdf(pdf)

    widget.zoom_in()
    assert widget.zoom_mode() == QPdfView.ZoomMode.Custom
    factor = widget.zoom_factor()
    widget.zoom_in()
    assert widget.zoom_factor() > factor
    widget.zoom_out()
    assert widget.zoom_factor() == pytest.approx(factor)

    widget.fit_page()
    assert widget.zoom_mode() == QPdfView.ZoomMode.FitInView
    widget.fit_width()
    assert widget.zoom_mode() == QPdfView.ZoomMode.FitToWidth


def test_file_can_be_moved_while_shown(qtbot, tmp_path, widget):
    """Kernanforderung: Die Vorschau darf die Datei nicht sperren (Sortieren!)."""
    pdf = _make_pdf(tmp_path / "quelle.pdf")
    with qtbot.waitSignal(widget.document_loaded, timeout=5000):
        widget.load_pdf(pdf)

    target_dir = tmp_path / "ziel"
    target_dir.mkdir()
    target = target_dir / "umbenannt.pdf"
    os.replace(pdf, target)  # wuerde unter Windows bei offenem Handle scheitern

    assert target.exists() and not pdf.exists()
    assert widget.is_showing_document()  # Anzeige bleibt (Daten sind im Speicher)


def test_invalid_file_shows_error(qtbot, tmp_path, widget):
    bad = tmp_path / "kaputt.pdf"
    bad.write_bytes(b"das ist keine PDF")

    with qtbot.waitSignal(widget.load_failed, timeout=5000) as blocker:
        widget.load_pdf(bad)

    assert blocker.args[0] == bad
    assert "gültige PDF" in blocker.args[1]
    assert not widget.is_showing_document()
    assert "Vorschau nicht möglich" in widget.message_label.text()
    # Extern oeffnen bleibt moeglich, Navigation nicht
    assert widget.external_btn.isEnabled()
    assert not widget.next_btn.isEnabled()


def test_missing_file_shows_error(qtbot, tmp_path, widget):
    with qtbot.waitSignal(widget.load_failed, timeout=5000) as blocker:
        widget.load_pdf(tmp_path / "fehlt.pdf")
    assert "gelesen" in blocker.args[1]


def test_clear_resets_view(qtbot, tmp_path, widget):
    pdf = _make_pdf(tmp_path / "a.pdf")
    with qtbot.waitSignal(widget.document_loaded, timeout=5000):
        widget.load_pdf(pdf)

    widget.clear()

    assert widget.current_path is None
    assert widget.page_count() == 0
    assert not widget.is_showing_document()
    assert widget.page_label.text() == "– / –"


def test_stale_read_result_is_ignored(qtbot, tmp_path, widget):
    """Ergebnis eines aelteren Ladevorgangs darf die aktuelle Auswahl nicht ueberschreiben."""
    a = _make_pdf(tmp_path / "a.pdf", pages=1)
    b = _make_pdf(tmp_path / "b.pdf", pages=2)

    widget.load_pdf(a)
    with qtbot.waitSignal(widget.document_loaded, timeout=5000):
        widget.load_pdf(b)
    qtbot.wait(200)  # evtl. spaet eintreffendes Ergebnis fuer a verarbeiten lassen

    assert widget.current_path == b
    assert widget.page_count() == 2


def test_load_bytes_synchronously(qtbot, tmp_path, widget):
    pdf = _make_pdf(tmp_path / "a.pdf", pages=2)
    assert widget.load_bytes(pdf, pdf.read_bytes()) is True
    assert widget.page_count() == 2
    assert widget.load_bytes(pdf, b"nix") is False


def test_signals_for_enlarge_and_external(qtbot, tmp_path, widget):
    pdf = _make_pdf(tmp_path / "a.pdf")
    with qtbot.waitSignal(widget.document_loaded, timeout=5000):
        widget.load_pdf(pdf)

    with qtbot.waitSignal(widget.enlarge_requested, timeout=1000) as enlarge:
        widget.enlarge_btn.click()
    assert enlarge.args == [pdf]

    with qtbot.waitSignal(widget.open_external_requested, timeout=1000) as ext:
        widget.external_btn.click()
    assert ext.args == [pdf]


def test_non_compact_widget_has_no_enlarge_button(qtbot):
    w = PdfPreviewWidget(compact=False)
    qtbot.addWidget(w)
    assert w.enlarge_btn is None
    assert w.external_btn is not None


# --------------------------------------------------------------------- #
# Vorschau-Fenster
# --------------------------------------------------------------------- #


def test_preview_window_shows_pdf_and_remembers_geometry(qtbot, tmp_path):
    pdf = _make_pdf(tmp_path / "fenster.pdf", pages=2)
    win = PdfPreviewWindow(geometry=[50, 60, 700, 800])
    qtbot.addWidget(win)

    with qtbot.waitSignal(win.preview.document_loaded, timeout=5000):
        win.show_pdf(pdf)

    assert win.isVisible()
    assert "fenster.pdf" in win.windowTitle()
    assert win.current_path() == pdf
    assert win.preview.page_count() == 2
    # Der Fenstermanager darf die gewuenschte Groesse an den Bildschirm
    # anpassen (kleine/skalierte Displays) - entscheidend ist, dass die
    # tatsaechliche Groesse gemerkt wird, nicht der Wunschwert.
    shown_size = (win.width(), win.height())
    assert shown_size[0] > 200 and shown_size[1] > 200

    with qtbot.waitSignal(win.geometry_changed, timeout=1000) as blocker:
        win.close()
    geometry = blocker.args[0]
    assert len(geometry) == 4 and (geometry[2], geometry[3]) == shown_size


def test_preview_window_ignores_bad_geometry(qtbot):
    win = PdfPreviewWindow(geometry=[1, 2, 3])
    qtbot.addWidget(win)
    assert win.width() == 900 and win.height() == 1000


def test_preview_window_reuses_for_next_pdf(qtbot, tmp_path):
    a = _make_pdf(tmp_path / "a.pdf", pages=1)
    b = _make_pdf(tmp_path / "b.pdf", pages=3)
    win = PdfPreviewWindow()
    qtbot.addWidget(win)

    with qtbot.waitSignal(win.preview.document_loaded, timeout=5000):
        win.show_pdf(a)
    with qtbot.waitSignal(win.preview.document_loaded, timeout=5000):
        win.show_pdf(b)

    assert win.current_path() == b
    assert win.preview.page_count() == 3
    assert "b.pdf" in win.windowTitle()

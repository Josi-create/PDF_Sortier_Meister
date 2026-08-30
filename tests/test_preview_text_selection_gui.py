"""Issue #109: Text in der Vorschau markieren und in Metadaten-Felder uebernehmen."""
from pathlib import Path

import fitz
import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest

from src.gui.pdf_preview_widget import SELECTION_TARGETS, PdfPreviewWidget


def _make_pdf(path: Path) -> Path:
    doc = fitz.open()
    try:
        page = doc.new_page()  # A4: 595 x 842 pt
        page.insert_text((72, 72), "Commerzbank AG", fontsize=14)
        page.insert_text((72, 120), "Depotauszug 2024", fontsize=14)
        doc.save(str(path))
    finally:
        doc.close()
    return path


@pytest.fixture
def widget(qtbot, tmp_path):
    w = PdfPreviewWidget(compact=True)
    qtbot.addWidget(w)
    w.resize(500, 700)
    w.show()
    qtbot.waitExposed(w)
    pdf = _make_pdf(tmp_path / "text.pdf")
    assert w.load_bytes(pdf, pdf.read_bytes())
    qtbot.waitUntil(lambda: w.page_count() == 1, timeout=5000)
    yield w
    w.shutdown()


def test_select_page_region_returns_text(widget):
    # Textzeile bei y=72 (Grundlinie), Schrift 14 pt -> Kasten etwa y 58..76
    text = widget.select_page_region(0, QPointF(60, 55), QPointF(220, 80))
    assert text == "Commerzbank AG"
    assert widget.selected_text() == "Commerzbank AG"
    widget.clear_selection()
    assert widget.selected_text() == ""


def test_mouse_drag_selects_text_and_emits_signal(qtbot, widget):
    rect = widget._page_rect_in_viewport(0)
    assert rect is not None and rect.width() > 100
    scale = rect.width() / 595.0

    def vp(x_pt, y_pt) -> QPoint:
        return QPoint(int(rect.x() + x_pt * scale), int(rect.y() + y_pt * scale))

    viewport = widget._view.viewport()
    with qtbot.waitSignal(widget.text_selected, timeout=2000) as blocker:
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=vp(60, 55))
        QTest.mouseMove(viewport, vp(150, 70))
        QTest.mouseMove(viewport, vp(220, 80))
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=vp(220, 80))
    assert blocker.args == ["Commerzbank AG"]
    # Markierung wird gezeichnet (mindestens ein Polygon)
    assert widget._overlay._polygons

    # Klick ohne Ziehen loescht die Markierung
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=vp(300, 400))
    assert widget.selected_text() == ""


def test_context_menu_actions_emit_apply_text(qtbot, widget):
    widget.select_page_region(0, QPointF(60, 105), QPointF(260, 128))
    assert widget.selected_text() == "Depotauszug 2024"
    menu = widget._build_selection_menu()
    actions = [a for a in menu.actions() if a.data()]
    assert [a.data() for a in actions] == [k for k, _l in SELECTION_TARGETS]
    with qtbot.waitSignal(widget.apply_text_requested, timeout=1000) as blocker:
        actions[1].trigger()  # "Als Kategorie uebernehmen"
    assert blocker.args == ["subject", "Depotauszug 2024"]

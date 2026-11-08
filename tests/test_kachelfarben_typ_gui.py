"""Kachelfarben und Etikett nach Dateityp; keine Luecke im Raster nach dem Entfernen."""

from pathlib import Path

import pytest

from src.gui.office_thumbnail import OfficeThumbnailWidget
from src.gui.pdf_thumbnail import PDFThumbnailWidget
from tests.test_auto_next_after_move_gui import _make_scan_folder, fresh_singletons, main_window  # noqa: F401


@pytest.fixture
def kachel(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(OfficeThumbnailWidget, "load_thumbnail", lambda self: None)
    monkeypatch.setattr(PDFThumbnailWidget, "load_thumbnail", lambda self: None)

    def bauen(name, cls=OfficeThumbnailWidget):
        w = cls(tmp_path / name)
        qtbot.addWidget(w)
        return w
    return bauen


@pytest.mark.parametrize("name,etikett,tip,farben", [
    ("a.docx", "DOCX", "Word-Dokument", OfficeThumbnailWidget.OFFICE_FARBEN),
    ("a.xlsx", "XLSX", "Excel-Tabelle", OfficeThumbnailWidget.OFFICE_FARBEN),
    ("a.jpg", "JPG", "Bild", OfficeThumbnailWidget.BILD_FARBEN),
    ("a.tiff", "TIFF", "Bild", OfficeThumbnailWidget.BILD_FARBEN),
])
def test_etikett_und_farben(kachel, name, etikett, tip, farben):
    w = kachel(name)
    assert w.typ_label.text() == etikett and w.typ_label.toolTip() == tip
    assert w.typ_label.x() < w.thumbnail_label.width() // 2  # links, Warndreieck sitzt rechts
    assert "white" in w.styleSheet()  # vor der Erkennung weiss
    w.has_ai_suggestion = True
    assert farben[0] in w.styleSheet() and farben[1] in w.styleSheet()
    assert farben[2] in w.styleSheet()
    assert PDFThumbnailWidget.AI_BACKGROUND not in w.styleSheet()


def test_auswahl_und_stapel_haben_vorrang(kachel):
    w = kachel("a.jpg")
    w.has_ai_suggestion = True
    w.selected = True
    assert "#cce5ff" in w.styleSheet() and OfficeThumbnailWidget.BILD_FARBEN[0] not in w.styleSheet()
    w.selected = False
    w.set_stack_target(True) if hasattr(w, "set_stack_target") else setattr(w, "_stack_target", True)
    w._update_style()
    assert PDFThumbnailWidget.STACK_BORDER in w.styleSheet()


def test_pdf_bleibt_gruen_ohne_etikett(kachel):
    w = kachel("a.pdf", PDFThumbnailWidget)
    assert not hasattr(w, "typ_label")
    assert "white" in w.styleSheet()
    w.has_ai_suggestion = True
    assert PDFThumbnailWidget.AI_BACKGROUND in w.styleSheet()


def test_raster_ohne_luecke_nach_entfernen(main_window, fresh_singletons):  # noqa: F811
    tmp = fresh_singletons["tmp_path"]
    scan = _make_scan_folder(tmp, [f"{c}.pdf" for c in "abcdefg"])
    main_window._navigate_to_folder(scan)
    cols = main_window._grid_cols
    mitte = main_window.pdf_widgets[2].pdf_path
    main_window.remove_pdf_widget(mitte)
    pos = [main_window.pdf_layout.getItemPosition(main_window.pdf_layout.indexOf(w))[:2]
           for w in main_window.pdf_widgets]
    assert pos == [(i // cols, i % cols) for i in range(len(main_window.pdf_widgets))]

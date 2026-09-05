"""Issue #117: Kachelgroesse im Scan-Bereich (Klein / Mittel / Gross) + Hover-Vorschau.

Das Thumbnail wird weiterhin in 140x160 gerendert; die Kachel zeigt je nach
Ansicht eine verkleinerte Kopie. Bei den kompakten Ansichten blendet der
Mauszeiger ueber einer PDF-Kachel das Original ein - Ordner-Kacheln nicht.
"""
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QPixmap

import pytest

from src.gui.tile_view import DEFAULT_TILE_VIEW_ID, TILE_VIEWS, tile_view
from tests.test_main_window_gui import fresh_singletons, main_window, _scan_tree  # noqa: F401 - Fixtures


def _pixmap(w: int = 113, h: int = 160) -> QPixmap:
    """Wie ein gerendertes A4-Thumbnail im 140x160-Rahmen."""
    p = QPixmap(w, h)
    p.fill(Qt.GlobalColor.gray)
    return p


@pytest.fixture
def thumbnail_factory(qtbot, monkeypatch, tmp_path):
    from src.gui import pdf_thumbnail as th
    monkeypatch.setattr(th.ThumbnailLoaderThread, "start", lambda self: None)

    def make(view_id=None, name="a.pdf"):
        pdf = tmp_path / name
        pdf.write_bytes(b"%PDF-1.4")
        widget = th.PDFThumbnailWidget(pdf, view=tile_view(view_id) if view_id else None)
        qtbot.addWidget(widget)
        return widget

    return make


# --------------------------------------------------------------------- #
# Presets
# --------------------------------------------------------------------- #


def test_views_and_fallback():
    assert [v.id for v in TILE_VIEWS] == ["klein", "mittel", "gross"]
    assert tile_view(None).id == DEFAULT_TILE_VIEW_ID == "klein"
    assert tile_view("gibt-es-nicht").id == DEFAULT_TILE_VIEW_ID
    # "gross" = Masse vor #117, damit sich fuer diese Ansicht nichts aendert
    gross = tile_view("gross")
    assert (gross.thumb_w, gross.thumb_h) == (140, 160)
    assert (gross.tile_w, gross.tile_h, gross.tile_max_w, gross.tile_max_h) == (160, 230, 180, 260)
    assert gross.slot_width == 190
    # Kompakte Ansichten sind deutlich schmaler
    assert tile_view("klein").tile_max_w < gross.tile_w // 1.5
    assert tile_view("mittel").tile_max_w < gross.tile_w


# --------------------------------------------------------------------- #
# PDF-Kachel
# --------------------------------------------------------------------- #


def test_default_widget_uses_small_view(thumbnail_factory):
    widget = thumbnail_factory()
    assert widget.view.id == "klein"


def _two_tone_pixmap(w: int = 113, h: int = 160) -> QPixmap:
    """Obere Haelfte rot, untere blau - zeigt, welcher Teil der Seite bleibt."""
    from PyQt6.QtGui import QPainter
    p = QPixmap(w, h)
    p.fill(Qt.GlobalColor.red)
    painter = QPainter(p)
    painter.fillRect(0, h // 2, w, h - h // 2, Qt.GlobalColor.blue)
    painter.end()
    return p


def test_small_view_fills_width_and_crops_bottom(thumbnail_factory):
    """#117-Feedback: In Klein blieb um die winzige Seite zu viel leere Kachel.
    Jetzt fuellt das Bild die Textbreite, unten wird abgeschnitten."""
    widget = thumbnail_factory("klein")
    view = tile_view("klein")
    assert view.thumb_crop and view.thumb_w == view.text_width
    assert widget.thumbnail_label.height() == view.thumb_h
    assert widget.maximumWidth() == view.tile_max_w

    widget._on_thumbnail_loaded(_two_tone_pixmap())
    shown = widget.thumbnail_label.pixmap()
    assert (shown.width(), shown.height()) == (view.thumb_w, view.thumb_h)
    img = shown.toImage()
    assert img.pixelColor(view.thumb_w // 2, 2).red() > 200  # Kopf der Seite oben
    assert img.pixelColor(view.thumb_w // 2, view.thumb_h - 2).blue() > 200  # Mitte der Seite unten
    assert widget._original_pixmap.size() == _two_tone_pixmap().size()


def test_crop_keeps_landscape_pages_centered():
    from src.gui.pdf_thumbnail import PDFThumbnailWidget
    view = tile_view("klein")
    shown = PDFThumbnailWidget._fit_pixmap(_pixmap(140, 70), view)
    assert (shown.width(), shown.height()) == (view.thumb_w, view.thumb_h)


def test_medium_view_scales_whole_page(thumbnail_factory):
    widget = thumbnail_factory("mittel")
    view = tile_view("mittel")
    assert not view.thumb_crop
    widget._on_thumbnail_loaded(_two_tone_pixmap())
    shown = widget.thumbnail_label.pixmap()
    assert shown.height() == view.thumb_h
    assert shown.width() < view.thumb_w  # ganze A4-Seite, schmaler als die Flaeche
    img = shown.toImage()
    assert img.pixelColor(shown.width() // 2, shown.height() - 2).blue() > 200  # Seitenende sichtbar


def test_large_view_shows_original_unscaled(thumbnail_factory):
    widget = thumbnail_factory("gross")
    widget._on_thumbnail_loaded(_pixmap())
    assert widget.thumbnail_label.pixmap().size() == _pixmap().size()


def test_switching_view_rescales_and_resizes(thumbnail_factory):
    widget = thumbnail_factory("klein")
    widget._on_thumbnail_loaded(_pixmap())

    widget.set_view(tile_view("gross"))
    assert widget.thumbnail_label.pixmap().height() == 160
    assert widget.minimumWidth() == tile_view("gross").tile_w
    assert widget.name_label.font().pixelSize() == 11

    widget.set_view(tile_view("mittel"))
    assert widget.thumbnail_label.pixmap().height() == tile_view("mittel").thumb_h
    assert widget.maximumHeight() == tile_view("mittel").tile_max_h
    assert widget.name_label.font().pixelSize() == 10

    widget.set_view(tile_view("klein"))
    assert widget.thumbnail_label.pixmap().width() == tile_view("klein").thumb_w  # wieder zugeschnitten


def _line_widths(label):
    from PyQt6.QtGui import QFontMetrics
    fm = QFontMetrics(label.font())
    return [fm.horizontalAdvance(line) for line in label.text().split("\n")]


def test_long_name_is_wrapped_to_tile_width_and_elided(thumbnail_factory):
    """Namen ohne Leerzeichen liefen seitlich aus der Kachel (Screenshot-Befund)."""
    long_name = "Stadtwerke_Jahresabrechnung_2023_Strom_und_Gas_Kundennummer_4711.pdf"
    widget = thumbnail_factory("klein", name=long_name)
    view = tile_view("klein")
    lines = widget.name_label.text().split("\n")
    assert len(lines) == view.name_lines
    assert all(w <= view.text_width for w in _line_widths(widget.name_label))
    assert "…" in lines[-1]  # letzte Zeile in der Mitte gekuerzt, Ende bleibt sichtbar
    assert lines[-1].endswith("11")
    assert widget.name_label.toolTip() == long_name

    widget.set_view(tile_view("gross"))
    lines = widget.name_label.text().split("\n")
    assert len(lines) <= tile_view("gross").name_lines
    assert all(w <= tile_view("gross").text_width for w in _line_widths(widget.name_label))
    # Gross bietet mehr Platz: mindestens so viel vom Namen sichtbar wie in Klein
    assert len(widget.name_label.text().replace("\n", "")) >= len("".join(lines[:1]))


def test_short_name_is_not_elided(thumbnail_factory):
    """Kurze Namen bleiben vollstaendig (offscreen misst die Schrift breiter,
    deshalb ist hier nur der Umbruch, nicht die Zeilenzahl festgelegt)."""
    from PyQt6.QtGui import QFontMetrics
    widget = thumbnail_factory("klein", name="Scan_0001.pdf")
    assert widget.name_label.text().replace("\n", "") == "Scan_0001"
    fm = QFontMetrics(widget.name_label.font())
    if fm.horizontalAdvance("Scan_0001") <= tile_view("klein").text_width:
        assert widget.name_label.text() == "Scan_0001"


def test_fit_text_lines_prefers_spaces():
    from PyQt6.QtGui import QFont, QFontMetrics
    from src.gui.tile_view import fit_text_lines
    font = QFont()
    font.setPixelSize(10)
    fm = QFontMetrics(font)
    width = fm.horizontalAdvance("Rechnung Telekom") + 2
    text = fit_text_lines("Rechnung Telekom Mai 2026", fm, width, 2)
    lines = text.split("\n")
    assert lines[0] == "Rechnung Telekom"
    assert lines[1].startswith("Mai")
    # Passt alles in eine Zeile, bleibt der Text unveraendert
    assert fit_text_lines("Kurz", fm, width, 2) == "Kurz"


def test_analyzing_style_uses_view_font(thumbnail_factory):
    widget = thumbnail_factory("klein")
    widget.analyzing = True
    assert widget.name_label.text() == widget.ANALYZING_TEXT
    assert widget.name_label.font().pixelSize() == 10
    assert "italic" in widget.name_label.styleSheet()
    widget.set_view(tile_view("gross"))
    assert widget.name_label.text() == widget.ANALYZING_TEXT
    assert widget.name_label.font().pixelSize() == 11
    assert "italic" in widget.name_label.styleSheet()
    widget.analyzing = False
    assert "italic" not in widget.name_label.styleSheet()
    assert widget.name_label.text() == "a"


# --------------------------------------------------------------------- #
# Hover-Vorschau
# --------------------------------------------------------------------- #


def test_hover_preview_shows_original_and_hides_on_leave(thumbnail_factory):
    widget = thumbnail_factory("klein")
    widget._on_thumbnail_loaded(_pixmap())

    widget._show_hover_preview()
    popup = widget._hover_popup
    assert popup is not None and popup.isVisible()
    assert popup.pixmap().size() == _pixmap().size()
    assert popup.isWindow()  # eigenes schwebendes Fenster, nicht in der Kachel

    widget.leaveEvent(QEvent(QEvent.Type.Leave))
    assert not popup.isVisible()


def test_hover_preview_hidden_on_press_and_cleanup(thumbnail_factory):
    widget = thumbnail_factory("mittel")
    widget._on_thumbnail_loaded(_pixmap())
    widget._show_hover_preview()
    assert widget._hover_popup.isVisible()

    widget._hide_hover_preview()
    assert not widget._hover_popup.isVisible()

    widget._show_hover_preview()
    widget.cleanup()
    assert not widget._hover_popup.isVisible()


def test_no_hover_preview_in_large_view_or_before_loading(thumbnail_factory):
    big = thumbnail_factory("gross")
    big._on_thumbnail_loaded(_pixmap())
    big._show_hover_preview()
    assert big._hover_popup is None

    unloaded = thumbnail_factory("klein", name="b.pdf")
    unloaded._show_hover_preview()
    assert unloaded._hover_popup is None


def test_enter_starts_timer_only_in_compact_view(thumbnail_factory):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QEnterEvent
    enter = QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1))

    small = thumbnail_factory("klein")
    small.enterEvent(enter)
    assert not small._hover_timer.isActive()  # Bild noch nicht geladen
    small._on_thumbnail_loaded(_pixmap())
    small.enterEvent(enter)
    assert small._hover_timer.isActive()
    small.leaveEvent(QEvent(QEvent.Type.Leave))
    assert not small._hover_timer.isActive()

    big = thumbnail_factory("gross", name="b.pdf")
    big._on_thumbnail_loaded(_pixmap())
    big.enterEvent(enter)
    assert not big._hover_timer.isActive()


def test_switch_to_large_view_hides_preview(thumbnail_factory):
    widget = thumbnail_factory("klein")
    widget._on_thumbnail_loaded(_pixmap())
    widget._show_hover_preview()
    widget.set_view(tile_view("gross"))
    assert not widget._hover_popup.isVisible()


# --------------------------------------------------------------------- #
# Ordner-Kachel
# --------------------------------------------------------------------- #


def test_folder_tile_matches_pdf_tile_size(qtbot, tmp_path):
    from src.gui.folder_tile import FolderTileWidget
    view = tile_view("klein")
    tile = FolderTileWidget(tmp_path, pdf_count=2, view=view)
    qtbot.addWidget(tile)
    assert (tile.minimumWidth(), tile.maximumWidth()) == (view.tile_w, view.tile_max_w)
    assert (tile.minimumHeight(), tile.maximumHeight()) == (view.tile_h, view.tile_max_h)
    assert tile.count_label.text() == "2 PDFs"
    assert "22px" in tile.icon_label.styleSheet()
    assert tile.name_label.font().pixelSize() == 11 and tile.name_label.font().bold()

    tile.set_view(tile_view("gross"))
    assert tile.minimumWidth() == tile_view("gross").tile_w
    assert "48px" in tile.icon_label.styleSheet()
    assert tile.name_label.font().pixelSize() == 12


def test_folder_tile_wraps_long_name(qtbot, tmp_path):
    from src.gui.folder_tile import FolderTileWidget
    folder = tmp_path / "Versicherungen_und_Altersvorsorge_Unterlagen"
    folder.mkdir()
    view = tile_view("klein")
    tile = FolderTileWidget(folder, pdf_count=0, view=view)
    qtbot.addWidget(tile)
    assert len(tile.name_label.text().split("\n")) == view.name_lines
    assert all(w <= view.text_width for w in _line_widths(tile.name_label))
    assert tile.toolTip().startswith(str(folder))


def test_folder_tile_default_view_is_small(qtbot, tmp_path):
    from src.gui.folder_tile import FolderTileWidget
    tile = FolderTileWidget(tmp_path)
    qtbot.addWidget(tile)
    assert tile.view.id == "klein"
    assert not hasattr(tile, "_hover_popup")  # keine Vorschau fuer Ordner


def test_parent_tile_hides_count_text_in_compact_views(qtbot, tmp_path):
    from src.gui.folder_tile import FolderTileWidget
    tile = FolderTileWidget(tmp_path, is_parent=True, view=tile_view("klein"))
    qtbot.addWidget(tile)
    assert tile.count_label.isHidden()
    tile.set_view(tile_view("gross"))
    assert not tile.count_label.isHidden()


# --------------------------------------------------------------------- #
# Hauptfenster
# --------------------------------------------------------------------- #


def test_main_window_defaults_to_small_tiles_and_switch_persists(main_window, fresh_singletons):
    scan = _scan_tree(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan / "Banken")
    assert main_window.tile_view_combo.currentData() == "klein"
    (widget,) = main_window.pdf_widgets
    assert widget.view.id == "klein"
    assert all(t.view.id == "klein" for t in main_window.folder_tiles)

    main_window.tile_view_combo.setCurrentIndex(main_window.tile_view_combo.findData("gross"))
    assert fresh_singletons["config"].get("tile_view") == "gross"
    assert widget.view.id == "gross"
    assert widget.maximumWidth() == tile_view("gross").tile_max_w
    assert all(t.view.id == "gross" for t in main_window.folder_tiles)


def test_grid_columns_follow_tile_view(main_window, fresh_singletons):
    scan = _scan_tree(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)
    viewport_w = main_window.pdf_scroll_area.viewport().width()
    assert main_window._grid_cols == max(1, viewport_w // tile_view("klein").slot_width)

    main_window.set_tile_view("gross")
    assert main_window._grid_cols == max(1, viewport_w // tile_view("gross").slot_width)
    assert main_window.tile_view_combo.currentData() == "gross"

    # Raster-Positionen folgen der neuen Spaltenzahl
    cols = main_window._grid_cols
    widgets = main_window.folder_tiles + main_window.pdf_widgets
    for i, w in enumerate(widgets):
        idx = main_window.pdf_layout.indexOf(w)
        row, col, _, _ = main_window.pdf_layout.getItemPosition(idx)
        assert (row, col) == (i // cols, i % cols)


def test_stored_view_is_used_at_startup(qtbot, fresh_singletons, monkeypatch):
    fresh_singletons["config"].set("tile_view", "mittel")
    from src.gui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.QMainWindow, "showMaximized", lambda self: None)
    monkeypatch.setattr(mw_mod.MainWindow, "show", lambda self: None)
    win = mw_mod.MainWindow()
    qtbot.addWidget(win)
    assert win._tile_view.id == "mittel"
    assert win.tile_view_combo.currentData() == "mittel"


def test_settings_dialog_has_no_dead_thumbnail_size_setting(fresh_singletons):
    from src.utils.config import Config
    assert "thumbnail_size" not in Config.DEFAULTS
    assert Config.DEFAULTS["tile_view"] == "klein"

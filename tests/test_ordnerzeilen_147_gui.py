"""Issue #147: Ordner im linken Fenster als Zeilen (eine oder zwei Spalten).

Die Unterordner (und "..") stehen als schmale Zeilen in einem eigenen Raster
ueber den PDF-Kacheln. Zwei Spalten gibt es ab 2 x 240 px sichtbarer Breite.
Keine Tests auf feste Textbreiten (Offscreen misst Schriften anders).
"""
from pathlib import Path

from PyQt6.QtCore import QMimeData, Qt, QUrl

from src.gui.folder_tile import FolderTileWidget
from tests.test_main_window_gui import fresh_singletons, main_window, _scan_tree  # noqa: F401 - Fixtures


class _FakeDropEvent:
    def __init__(self, mime):
        self._mime = mime
        self.accepted = None

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


def _positionen(win) -> list[tuple[int, int]]:
    grid = win.folder_rows_layout
    return [tuple(grid.getItemPosition(grid.indexOf(t))[:2]) for t in win.folder_tiles]


def _ordner(scan: Path, *namen: str) -> None:
    for name in namen:
        (scan / name).mkdir(exist_ok=True)


# --- Zeile -------------------------------------------------------------------


def test_zeile_zeigt_symbol_name_und_zaehler(qtbot, tmp_path):
    ordner = tmp_path / "Archiv"
    ordner.mkdir()
    zeile = FolderTileWidget(ordner, pdf_count=365)
    qtbot.addWidget(zeile)
    assert zeile.icon_label.text() == "📁"
    assert zeile.name_label.text() == "Archiv"
    assert zeile.count_label.text() == "365 PDFs"
    assert "#777" in zeile.count_label.styleSheet()  # Zaehler grau
    assert zeile.height() == FolderTileWidget.ROW_HEIGHT


def test_elternzeile(qtbot, tmp_path):
    zeile = FolderTileWidget(tmp_path, is_parent=True)
    qtbot.addWidget(zeile)
    assert zeile.icon_label.text() == "⬆"
    assert zeile.name_label.text() == ".."
    assert zeile.count_label.text() == "übergeordneter Ordner"


def test_langer_name_wird_gekuerzt_tooltip_vollstaendig(qtbot, tmp_path):
    ordner = tmp_path / ("Versicherungen_und_Altersvorsorge_Unterlagen_" * 3)
    ordner.mkdir()
    zeile = FolderTileWidget(ordner, pdf_count=1)
    qtbot.addWidget(zeile)
    zeile.resize(FolderTileWidget.MIN_WIDTH, FolderTileWidget.ROW_HEIGHT)
    zeile.show()
    qtbot.waitExposed(zeile)
    assert zeile.name_label.text() != ordner.name
    assert zeile.name_label.text().endswith("…")
    assert zeile.toolTip().startswith(str(ordner))
    assert zeile.full_name == ordner.name


def test_drop_auf_zeile_loest_pdf_dropped_aus(qtbot, tmp_path):
    zeile = FolderTileWidget(tmp_path, pdf_count=0)
    qtbot.addWidget(zeile)
    empfangen = []
    zeile.pdf_dropped.connect(lambda pdf, ordner: empfangen.append((pdf, ordner)))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / "a.pdf"))])
    ev = _FakeDropEvent(mime)
    zeile.dropEvent(ev)
    assert ev.accepted is True
    assert empfangen == [(tmp_path / "a.pdf", tmp_path)]


def test_hover_stil(qtbot, tmp_path):
    zeile = FolderTileWidget(tmp_path)
    qtbot.addWidget(zeile)
    zeile.enterEvent(None)
    assert zeile.styleSheet() == FolderTileWidget._STYLE_HOVER
    zeile.leaveEvent(None)
    assert zeile.styleSheet() == FolderTileWidget._STYLE_NORMAL


# --- Hauptfenster ------------------------------------------------------------


def test_ordner_stehen_ueber_den_pdfs_im_eigenen_raster(main_window, fresh_singletons):
    scan = _scan_tree(fresh_singletons["tmp_path"])
    (scan / "neu.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    main_window._navigate_to_folder(scan)

    assert [t.full_name for t in main_window.folder_tiles] == ["..", "Banken", "Steuer 2026"]
    for zeile in main_window.folder_tiles:
        assert main_window.folder_rows_layout.indexOf(zeile) >= 0
        assert main_window.pdf_layout.indexOf(zeile) == -1
    (pdf,) = main_window.pdf_widgets
    assert main_window.pdf_layout.getItemPosition(main_window.pdf_layout.indexOf(pdf))[:2] == (0, 0)


def test_schmaler_viewport_eine_spalte(main_window, fresh_singletons, monkeypatch):
    scan = _scan_tree(fresh_singletons["tmp_path"])
    monkeypatch.setattr(main_window, "_scan_viewport_width", lambda: 2 * 240 - 1)
    main_window._navigate_to_folder(scan)
    assert main_window._folder_cols == 1
    assert _positionen(main_window) == [(0, 0), (1, 0), (2, 0)]


def test_breiter_viewport_zwei_spalten(main_window, fresh_singletons, monkeypatch):
    scan = _scan_tree(fresh_singletons["tmp_path"])
    _ordner(scan, "Versicherung")
    monkeypatch.setattr(main_window, "_scan_viewport_width", lambda: 2 * 240)
    main_window._navigate_to_folder(scan)
    assert main_window._folder_cols == 2
    # zeilenweise: ".." und Banken oben, dann Steuer 2026 und Versicherung
    assert _positionen(main_window) == [(0, 0), (0, 1), (1, 0), (1, 1)]


def test_breitenwechsel_ordnet_neu(main_window, fresh_singletons, monkeypatch):
    scan = _scan_tree(fresh_singletons["tmp_path"])
    breite = {"px": 300}
    monkeypatch.setattr(main_window, "_scan_viewport_width", lambda: breite["px"])
    main_window._navigate_to_folder(scan)
    assert main_window._folder_cols == 1

    breite["px"] = 900
    main_window._relayout_pdf_grid()
    assert main_window._folder_cols == 2
    assert _positionen(main_window) == [(0, 0), (0, 1), (1, 0)]

    breite["px"] = 300
    main_window._relayout_pdf_grid()
    assert _positionen(main_window) == [(0, 0), (1, 0), (2, 0)]


def test_kachelgroesse_aendert_ordnerzeilen_nicht(main_window, fresh_singletons):
    scan = _scan_tree(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)
    vorher = [(t.minimumHeight(), t.name_label.font().pixelSize()) for t in main_window.folder_tiles]
    main_window.set_tile_view("gross")
    assert [(t.minimumHeight(), t.name_label.font().pixelSize()) for t in main_window.folder_tiles] == vorher


def test_klick_und_doppelklick_bleiben(main_window, fresh_singletons, qtbot):
    scan = _scan_tree(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan / "Banken")
    eltern = main_window.folder_tiles[0]
    assert eltern.is_parent
    # ".." reagiert auf Einfachklick
    eltern.clicked.emit(eltern.folder_path)
    assert fresh_singletons["config"].get_scan_folder() == scan
    banken = next(t for t in main_window.folder_tiles if t.full_name == "Banken")
    banken.double_clicked.emit(banken.folder_path)
    assert fresh_singletons["config"].get_scan_folder() == scan / "Banken"


def test_drop_signal_der_ordnerzeile_ist_verbunden(main_window, fresh_singletons):
    scan = _scan_tree(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)
    banken = next(t for t in main_window.folder_tiles if t.full_name == "Banken")
    assert banken.receivers(banken.pdf_dropped) >= 1

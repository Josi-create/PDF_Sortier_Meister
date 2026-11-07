"""Issue #150: Rechtsklick "Drehen" (90 Grad links/rechts, 180 Grad) und "OCR neu durchführen"."""
from pathlib import Path

import pytest

from src.core.pdf_rotate import drehung
from tests import helfer_suche as h
from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401 - Fixtures


def _texte(menu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _untermenue(menu, titel_anfang: str):
    for a in menu.actions():
        if a.menu() is not None and a.text().startswith(titel_anfang):
            return a.menu()
    raise AssertionError(f"Kein Untermenue {titel_anfang!r}: {_texte(menu)}")


@pytest.fixture
def thumbnail(qtbot, monkeypatch, tmp_path):
    from src.gui import pdf_thumbnail as th
    monkeypatch.setattr(th.ThumbnailLoaderThread, "start", lambda self: None)
    pdf = h.pdf_mit_text(tmp_path / "a.pdf", ["Text"])
    widget = th.PDFThumbnailWidget(pdf)
    qtbot.addWidget(widget)
    return widget


# --- Kontextmenue der Kachel --------------------------------------------------


def test_menue_hat_drehen_und_ocr_neu(thumbnail):
    menu = thumbnail._build_context_menu()
    texte = _texte(menu)
    assert "Drehen" in texte and "OCR neu durchführen" in texte
    assert texte.index("OCR neu durchführen") == texte.index("Drehen") + 1
    assert _texte(_untermenue(menu, "Drehen")) == ["90° nach links", "90° nach rechts", "180°"]


@pytest.mark.parametrize("eintrag,grad", [("90° nach links", -90), ("90° nach rechts", 90), ("180°", 180)])
def test_drehen_sendet_winkel(thumbnail, eintrag, grad):
    empfangen = []
    thumbnail.rotate_requested.connect(lambda p, g: empfangen.append((p, g)))
    sub = _untermenue(thumbnail._build_context_menu(), "Drehen")
    next(a for a in sub.actions() if a.text() == eintrag).trigger()
    assert empfangen == [(thumbnail.pdf_path, grad)]


def test_ocr_neu_sendet_signal(thumbnail):
    empfangen = []
    thumbnail.reocr_requested.connect(empfangen.append)
    menu = thumbnail._build_context_menu()
    next(a for a in menu.actions() if a.text() == "OCR neu durchführen").trigger()
    assert empfangen == [thumbnail.pdf_path]


def test_mehrfachauswahl_steht_im_menue(thumbnail, monkeypatch):
    monkeypatch.setattr(thumbnail, "_get_selection_count", lambda: 3)
    thumbnail.selected = True
    texte = _texte(thumbnail._build_context_menu())
    assert "Drehen (3 PDFs)" in texte and "OCR neu durchführen (3 PDFs)" in texte
    # Kachel gehoert nicht zur Auswahl -> gilt nur fuer sie
    thumbnail.selected = False
    assert "Drehen" in _texte(thumbnail._build_context_menu())


# --- Hauptfenster ---------------------------------------------------------------


@pytest.fixture
def scan_ordner(fresh_singletons):  # noqa: F811
    scan = fresh_singletons["tmp_path"] / "Scan"
    scan.mkdir()
    for name in ("a", "b", "c"):
        h.pdf_mit_text(scan / f"{name}.pdf", [f"Dokument {name}"])
    return scan


@pytest.fixture
def beobachtet(main_window, monkeypatch):  # noqa: F811
    """Thumbnail-Laden, Cache-Leeren und Indexmeldungen mitschreiben."""
    from src.gui import main_window as mw_mod
    from src.gui.pdf_thumbnail import PDFThumbnailWidget

    log = {"geladen": [], "vergessen": [], "index": [], "warnung": [], "analyse": []}
    monkeypatch.setattr(PDFThumbnailWidget, "load_thumbnail", lambda self: log["geladen"].append(self.pdf_path))
    monkeypatch.setattr(mw_mod, "thumbnail_vergessen", lambda p: log["vergessen"].append(Path(p)))
    monkeypatch.setattr(mw_mod, "index_melden", lambda *a, **k: log["index"].append(a))
    monkeypatch.setattr(mw_mod.QMessageBox, "warning", lambda *a, **k: log["warnung"].append(a[2]))
    monkeypatch.setattr(main_window, "update_suggestions_for_pdf", lambda p: log["analyse"].append(p))
    return log


def _widget(win, name):
    return next(w for w in win.pdf_widgets if w.pdf_path.name == name)


def test_drehen_frischt_kachel_cache_und_index_auf(main_window, scan_ordner, beobachtet):  # noqa: F811
    main_window._navigate_to_folder(scan_ordner)
    beobachtet["geladen"].clear()
    a = scan_ordner / "a.pdf"
    w = _widget(main_window, "a.pdf")

    w.rotate_requested.emit(a, 90)

    assert drehung(a) == [90]
    assert beobachtet["vergessen"] == [a]
    assert beobachtet["geladen"] == [a]
    assert beobachtet["index"] == [("datei_geaendert", str(a))]
    eintrag = main_window._undo_stack[-1]
    assert eintrag["type"] == "rotate" and eintrag["paths"] == [a] and eintrag["grad"] == 90
    assert "gedreht" in main_window.undo_action.text()


def test_rueckgaengig_dreht_zurueck(main_window, scan_ordner, beobachtet):  # noqa: F811
    main_window._navigate_to_folder(scan_ordner)
    a = scan_ordner / "a.pdf"
    main_window.on_pdf_rotate(a, -90)
    assert drehung(a) == [270]

    main_window.undo_last_action()
    assert drehung(a) == [0]
    assert not main_window._undo_stack  # kein neuer Eintrag fuer die Gegenrotation
    assert beobachtet["geladen"].count(a) >= 2


def test_mehrfachauswahl_dreht_alle_markierten(main_window, scan_ordner, beobachtet):  # noqa: F811
    main_window._navigate_to_folder(scan_ordner)
    a, b, c = (scan_ordner / f"{n}.pdf" for n in "abc")
    main_window.selected_pdfs = [a, b]

    main_window.on_pdf_rotate(b, 180)
    assert (drehung(a), drehung(b), drehung(c)) == ([180], [180], [0])
    assert "2 PDFs" in main_window._undo_stack[-1]["description"]

    main_window.undo_last_action()
    assert (drehung(a), drehung(b)) == ([0], [0])

    # Rechtsklick ausserhalb der Auswahl: nur diese PDF
    main_window.on_pdf_rotate(c, 90)
    assert (drehung(a), drehung(c)) == ([0], [90])


def test_ausgewaehlte_pdf_wird_neu_analysiert(main_window, scan_ordner, beobachtet):  # noqa: F811
    main_window._navigate_to_folder(scan_ordner)
    a = scan_ordner / "a.pdf"
    main_window.selected_pdf = a
    main_window.on_pdf_rotate(a, 90)
    assert beobachtet["analyse"] == [a]


def test_signierte_pdf_meldet_und_bleibt(main_window, scan_ordner, beobachtet):  # noqa: F811
    import pikepdf

    main_window._navigate_to_folder(scan_ordner)
    a = scan_ordner / "a.pdf"
    with pikepdf.open(str(a), allow_overwriting_input=True) as pdf:
        pdf.Root.AcroForm = pdf.make_indirect(pikepdf.Dictionary(Fields=pikepdf.Array(), SigFlags=3))
        pdf.save(str(a))

    main_window.on_pdf_rotate(a, 90)
    assert drehung(a) == [0]
    assert len(beobachtet["warnung"]) == 1 and "signiert" in beobachtet["warnung"][0]
    assert not main_window._undo_stack


def test_ocr_neu_im_hintergrund(main_window, scan_ordner, beobachtet, qtbot, monkeypatch):  # noqa: F811
    from src.gui import ocr_neu_worker

    main_window._navigate_to_folder(scan_ordner)
    a, b = scan_ordner / "a.pdf", scan_ordner / "b.pdf"
    erkannt = []
    monkeypatch.setattr(ocr_neu_worker, "ocr_neu_durchfuehren",
                        lambda p, abbrechen=None: erkannt.append(Path(p)) or
                        {"index": True, "seiten": 1, "fehler": None})
    geleert = []
    monkeypatch.setattr(main_window.pdf_cache, "clear_for_pdf", lambda p: geleert.append(p))
    main_window.selected_pdfs = [a, b]
    main_window.selected_pdf = None

    main_window.on_pdf_reocr(a)
    assert _widget(main_window, "a.pdf").analyzing and _widget(main_window, "b.pdf").analyzing
    qtbot.waitUntil(lambda: main_window._ocr_neu_worker is None, timeout=5000)

    assert erkannt == [a, b]
    assert geleert == [a, b]
    assert not _widget(main_window, "a.pdf").analyzing and not _widget(main_window, "b.pdf").analyzing
    assert "2 Seite(n)" in main_window.statusbar.currentMessage()


def test_ocr_neu_laedt_ausgewaehlte_pdf_neu_und_meldet_fehler(main_window, scan_ordner, beobachtet,  # noqa: F811
                                                               qtbot, monkeypatch):
    from src.gui import ocr_neu_worker

    main_window._navigate_to_folder(scan_ordner)
    a = scan_ordner / "a.pdf"
    monkeypatch.setattr(ocr_neu_worker, "ocr_neu_durchfuehren",
                        lambda p, abbrechen=None: {"index": True, "seiten": 0, "fehler": "Tesseract fehlt"})
    main_window.selected_pdf = a
    main_window.selected_pdfs = []

    main_window.on_pdf_reocr(a)
    qtbot.waitUntil(lambda: main_window._ocr_neu_worker is None, timeout=5000)
    assert beobachtet["analyse"] == [a]
    assert beobachtet["warnung"] and "Tesseract fehlt" in beobachtet["warnung"][0]

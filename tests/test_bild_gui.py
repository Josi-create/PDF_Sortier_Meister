"""GUI-Tests fuer Issue #184 (Bilder wie docx) und #187 (Original nach dem Trennen).

Fixtures wie in ``tests/test_office_gui.py``. Der Papierkorb ist per conftest
umgeleitet; die Frage "Original in den Papierkorb?" (``original_wegraeumen._frage``)
und Tesseract sind dort abgeschaltet und werden hier gezielt ersetzt.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from PIL import Image
from PyQt6.QtWidgets import QDialog, QMessageBox

from src.gui import original_wegraeumen as ow
from tests.test_office_gui import _prime_cache_on_load, fresh_singletons, main_window  # noqa: F401 - Fixtures


def _bild(pfad: Path, groesse=(200, 100), farbe="red") -> Path:
    Image.new("RGB", groesse, farbe).save(pfad)
    return pfad


def _pdf(pfad: Path, seiten: int = 1) -> Path:
    doc = pymupdf.open()
    for i in range(seiten):
        doc.new_page().insert_text((50, 100), f"Seite {i + 1}")
    doc.save(str(pfad))
    doc.close()
    return pfad


@pytest.fixture(autouse=True)
def cursor_aufraeumen():
    """Die Auswahl des neuen (echten) PDFs startet eine Analyse mit Wartezeiger, der erst
    spaeter endet; er soll nicht in andere Tests hineinragen."""
    yield
    from PyQt6.QtWidgets import QApplication
    while QApplication.overrideCursor() is not None:
        QApplication.restoreOverrideCursor()


@pytest.fixture
def scan(fresh_singletons):  # noqa: F811
    ordner = fresh_singletons["tmp_path"] / "Scan"
    ordner.mkdir()
    return ordner


def _fragen(monkeypatch, antwort=(True, False)):
    """Ersetzt die Frage; liefert die Liste der gestellten Fragen."""
    gestellt = []
    monkeypatch.setattr(ow, "_frage", lambda parent, text: gestellt.append(text) or antwort)
    return gestellt


def _statusmeldungen(mw) -> list:
    """Merkt alle Statusmeldungen (die spaetere Analyse ueberschreibt die sichtbare)."""
    meldungen = []
    original = mw.statusbar.showMessage
    mw.statusbar.showMessage = lambda text, *a: (meldungen.append(text), original(text, *a))[1]
    return meldungen


def _umwandeln_und_warten(qtbot, mw, pfad):
    mw.on_office_convert(pfad, False)
    qtbot.waitUntil(lambda: mw._bild_worker is None, timeout=10000)


# --- Kacheln und Menue -----------------------------------------------------------------

def test_bilder_erscheinen_als_kacheln_mit_vorschaubild(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    from src.core import bild_convert
    monkeypatch.setattr(bild_convert, "_heif_geprueft", False)  # ohne pillow-heif (Issue #205: jetzt Pflichtpaket)
    for name in ("a.jpg", "b.PNG", "c.tif", "d.bmp", "e.gif", "f.webp"):
        _bild(scan / name)
    (scan / "g.heic").write_bytes(b"x")  # ohne pillow-heif ignoriert
    (scan / "h.csv").write_text("x")
    main_window._navigate_to_folder(scan)
    kacheln = main_window.office_widgets
    assert sorted(w.pdf_path.name for w in kacheln) == ["a.jpg", "b.PNG", "c.tif", "d.bmp", "e.gif", "f.webp"]
    assert all(not w.acceptDrops() for w in kacheln)

    def echte_bilder():  # das echte Bild (200x100) loest den 140x160-Platzhalter ab; Kacheln frisch holen
        try:
            return all(w._original_pixmap.size().width() == 200 for w in main_window.office_widgets)
        except RuntimeError:
            return False

    qtbot.waitUntil(echte_bilder, timeout=8000)


def test_kachelbild_beachtet_exif(qtbot):
    from src.gui.office_thumbnail import bild_kachelbild

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        bild = Image.new("RGB", (200, 100), "red")
        exif = bild.getexif()
        exif[274] = 6
        pfad = Path(tmp) / "foto.jpg"
        bild.save(pfad, exif=exif)
        qimg = bild_kachelbild(pfad)
    assert qimg is not None and qimg.height() > qimg.width()


def test_bild_kontextmenue(main_window, scan):  # noqa: F811
    _bild(scan / "a.jpg")
    main_window._navigate_to_folder(scan)
    menu = main_window.office_widgets[0]._build_context_menu()
    texte = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert "In PDF umwandeln" in texte and "Verschieben nach..." in texte and "Löschen" in texte
    assert not any("PDF/A" in t or "zusammenfügen" in t for t in texte)


def test_menue_zusammenfuegen_nur_bei_mehreren_markierten_bildern(main_window, scan):  # noqa: F811
    for name in ("a.jpg", "b.jpg"):
        _bild(scan / name)
    main_window._navigate_to_folder(scan)
    a, b = scan / "a.jpg", scan / "b.jpg"
    main_window.selected_pdfs = [a, b]
    w = next(x for x in main_window.office_widgets if x.pdf_path == a)
    texte = [x.text() for x in w._build_context_menu().actions()]
    assert "Zu einem PDF zusammenfügen (2 Bilder)" in texte


def test_vorschau_in_der_mitte_fuer_bild(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    from src.gui import office_convert_worker as worker_mod
    from src.core import office_vorschau

    monkeypatch.setattr(worker_mod, "vorschau_pdf", office_vorschau.vorschau_pdf)  # echte Vorschau
    bild = _bild(scan / "a.jpg")
    main_window._navigate_to_folder(scan)
    _prime_cache_on_load(main_window, monkeypatch)
    geladen = []
    monkeypatch.setattr(main_window.detail_panel.preview, "load_pdf", lambda p: geladen.append(p))
    w = next(x for x in main_window.pdf_widgets if x.pdf_path == bild)
    from src.core.pdf_cache import PDFAnalysisResult
    main_window.pdf_cache._cache[bild] = PDFAnalysisResult(pdf_path=bild, file_modified=bild.stat().st_mtime)
    w.clicked.emit(w.pdf_path)
    qtbot.waitUntil(lambda: main_window._office_vorschau_worker is None and bool(geladen), timeout=8000)
    assert main_window.selected_pdf == bild and len(geladen) == 1 and geladen[0].suffix == ".pdf"


# --- Umwandeln mit Frage -------------------------------------------------------------

def test_umwandeln_ohne_wegraeumen_behaelt_original(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    bild = _bild(scan / "a.jpg")
    main_window._navigate_to_folder(scan)
    gestellt = _fragen(monkeypatch, (False, False))
    meldungen = _statusmeldungen(main_window)
    _umwandeln_und_warten(qtbot, main_window, bild)
    assert (scan / "a.pdf").exists() and bild.exists() and len(gestellt) == 1
    assert main_window.selected_pdf == scan / "a.pdf"
    assert any("Tesseract" in m for m in meldungen)


def test_ja_verschiebt_in_papierkorb_und_strg_z_holt_zurueck(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    bild = _bild(scan / "a.jpg")
    main_window._navigate_to_folder(scan)
    gestellt = _fragen(monkeypatch, (True, False))
    _umwandeln_und_warten(qtbot, main_window, bild)

    assert (scan / "a.pdf").exists() and not bild.exists()
    assert all(w.pdf_path != bild for w in main_window.pdf_widgets)
    assert main_window.selected_pdf == scan / "a.pdf"
    assert main_window.config.get("original_wegraeumen")["umwandeln"] is None  # kein Haekchen: nichts gemerkt
    assert main_window._undo_stack[-1]["type"] == "wegraeumen"

    main_window.undo_last_action()
    assert bild.exists() and (scan / "a.pdf").exists()  # das PDF bleibt
    assert any(w.pdf_path == bild for w in main_window.pdf_widgets)
    assert not main_window._undo_stack


def test_haekchen_merkt_ja_und_fragt_nicht_mehr(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    a, b = _bild(scan / "a.jpg"), _bild(scan / "b.jpg")
    main_window._navigate_to_folder(scan)
    gestellt = _fragen(monkeypatch, (True, True))
    _umwandeln_und_warten(qtbot, main_window, a)
    assert main_window.config.get("original_wegraeumen")["umwandeln"] is True and len(gestellt) == 1 and not a.exists()

    _umwandeln_und_warten(qtbot, main_window, b)
    assert len(gestellt) == 1 and not b.exists() and (scan / "b.pdf").exists()  # ohne Frage gelöscht


def test_haekchen_merkt_nein_und_behaelt_kuenftig(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    a, b = _bild(scan / "a.jpg"), _bild(scan / "b.jpg")
    main_window._navigate_to_folder(scan)
    gestellt = _fragen(monkeypatch, (False, True))
    _umwandeln_und_warten(qtbot, main_window, a)
    assert main_window.config.get("original_wegraeumen")["umwandeln"] is False

    _umwandeln_und_warten(qtbot, main_window, b)
    assert len(gestellt) == 1 and a.exists() and b.exists() and (scan / "b.pdf").exists()
    assert not main_window._undo_stack


def test_nein_ohne_haekchen_fragt_naechstes_mal_wieder(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    a, b = _bild(scan / "a.jpg"), _bild(scan / "b.jpg")
    main_window._navigate_to_folder(scan)
    gestellt = _fragen(monkeypatch, (False, False))
    _umwandeln_und_warten(qtbot, main_window, a)
    _umwandeln_und_warten(qtbot, main_window, b)
    assert len(gestellt) == 2


def test_bei_fehler_wird_nicht_gefragt_und_nichts_geloescht(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    kaputt = scan / "kaputt.jpg"
    kaputt.write_bytes(b"kein bild")
    main_window._navigate_to_folder(scan)
    meldungen = []
    from src.gui import bild_aktionen
    monkeypatch.setattr(bild_aktionen.QMessageBox, "warning", lambda *a, **k: meldungen.append(a[2]))
    monkeypatch.setattr(ow, "_frage", lambda *a: pytest.fail("Frage trotz Fehler"))
    main_window.config.set("original_wegraeumen", {"umwandeln": True, "trennen": None})
    _umwandeln_und_warten(qtbot, main_window, kaputt)
    assert kaputt.exists() and meldungen and not (scan / "kaputt.pdf").exists()


def test_ergebnis_nicht_lesbar_loescht_nicht(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    from src.core.bild_convert import BildErgebnis
    from src.gui import bild_convert_worker as bw

    bild = _bild(scan / "a.jpg")
    main_window._navigate_to_folder(scan)

    def falsch(pfade, **k):  # behauptet Erfolg, die Datei ist aber Muell
        ziel = scan / "a.pdf"
        ziel.write_bytes(b"%PDF-1.4\n%%EOF\n")
        return BildErgebnis(pdf=ziel, quellen=list(pfade), seiten=1)

    monkeypatch.setattr(bw, "bilder_in_pdf", falsch)
    monkeypatch.setattr(ow, "_frage", lambda *a: pytest.fail("Frage trotz unlesbarem PDF"))
    main_window.config.set("original_wegraeumen", {"umwandeln": True, "trennen": None})
    _umwandeln_und_warten(qtbot, main_window, bild)
    assert bild.exists()


def test_ocr_hinweis_in_der_statusleiste_und_aufruf(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    from src.core import bild_convert as bc

    bild = _bild(scan / "a.jpg")
    main_window._navigate_to_folder(scan)
    _fragen(monkeypatch, (False, False))
    aufrufe = []
    monkeypatch.setattr(bc, "ocr_einstellungen", lambda: {"sprachen": "deu"})

    def ocr(seite, cfg):
        aufrufe.append(1)
        doc = pymupdf.open()
        doc.new_page(width=100, height=100).insert_text((10, 50), "Strom")
        return "Strom", doc.tobytes()

    monkeypatch.setattr(bc, "ocr_seite", ocr)
    meldungen = _statusmeldungen(main_window)
    _umwandeln_und_warten(qtbot, main_window, bild)
    assert aufrufe == [1]
    with pymupdf.open(scan / "a.pdf") as doc:
        assert "Strom" in doc[0].get_text()
    assert any("durchsuchbar" in m for m in meldungen)


# --- Mehrere Bilder ----------------------------------------------------------------------

def test_zusammenfuegen_mehrerer_bilder(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    vorn, hinten = _bild(scan / "a_vorn.jpg", (100, 50)), _bild(scan / "b_hinten.jpg", (50, 100))
    main_window._navigate_to_folder(scan)
    gestellt = _fragen(monkeypatch, (True, False))
    main_window.selected_pdfs = [hinten, vorn]  # Auswahlreihenfolge egal: Ansicht zaehlt (Name)
    reihenfolge = [w.pdf_path for w in main_window.pdf_widgets]
    assert reihenfolge.index(vorn) < reihenfolge.index(hinten)
    main_window.on_bilder_zusammenfuegen(vorn)
    qtbot.waitUntil(lambda: main_window._bild_worker is None, timeout=10000)

    pdf = scan / "a_vorn.pdf"
    with pymupdf.open(pdf) as doc:
        assert doc.page_count == 2 and doc[0].rect.width > doc[0].rect.height and doc[1].rect.height > doc[1].rect.width
    assert len(gestellt) == 1  # einmal fuer alle
    assert not vorn.exists() and not hinten.exists()
    assert main_window.selected_pdf == pdf
    assert len([e for e in main_window._undo_stack if e["type"] == "wegraeumen"]) == 1

    main_window.undo_last_action()  # ein Strg+Z holt beide zurueck
    assert vorn.exists() and hinten.exists() and pdf.exists()


# --- docx nutzt denselben Dialog -----------------------------------------------------------

def test_docx_umwandlung_nutzt_denselben_dialog(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    from src.core.office_convert import UmwandlungsErgebnis
    from src.gui import office_convert_worker as worker_mod

    docx = scan / "Brief.docx"
    docx.write_bytes(b"PK")
    main_window._navigate_to_folder(scan)

    def umwandeln(pfad, pdfa=False):
        ziel = _pdf(pfad.with_suffix(".pdf"))
        return UmwandlungsErgebnis(pdf=ziel, werkzeug="Word")

    monkeypatch.setattr(worker_mod, "umwandeln", umwandeln)
    gestellt = _fragen(monkeypatch, (True, True))
    main_window.on_office_convert(docx, False)
    qtbot.waitUntil(lambda: main_window._office_worker is None, timeout=5000)

    assert len(gestellt) == 1 and "Brief.pdf" in gestellt[0]
    assert not docx.exists() and (scan / "Brief.pdf").exists()
    assert main_window.config.get("original_wegraeumen")["umwandeln"] is True
    main_window.undo_last_action()
    assert docx.exists()


def test_docx_ohne_lesbares_pdf_wird_nicht_geloescht(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    from src.core.office_convert import UmwandlungsErgebnis
    from src.gui import office_convert_worker as worker_mod

    docx = scan / "Brief.docx"
    docx.write_bytes(b"PK")
    main_window._navigate_to_folder(scan)

    def umwandeln(pfad, pdfa=False):
        ziel = pfad.with_suffix(".pdf")
        ziel.write_bytes(b"leer")
        return UmwandlungsErgebnis(pdf=ziel, werkzeug="Word")

    monkeypatch.setattr(worker_mod, "umwandeln", umwandeln)
    monkeypatch.setattr(ow, "_frage", lambda *a: pytest.fail("Frage trotz unlesbarem PDF"))
    main_window.on_office_convert(docx, False)
    qtbot.waitUntil(lambda: main_window._office_worker is None, timeout=5000)
    assert docx.exists()


# --- Trennen (#187) -------------------------------------------------------------------------

class _FesterSplitDialog:
    """Ersatz fuer SplitPDFDialog: nimmt sofort an und liefert die Seiten."""
    DialogCode = QDialog.DialogCode
    seiten = None

    def __init__(self, *a, **k):
        pass

    def exec(self):
        return QDialog.DialogCode.Accepted

    def get_pages(self):
        return self.seiten


@pytest.fixture
def split_dialog(monkeypatch):
    from src.gui import split_pdf_dialog
    monkeypatch.setattr(split_pdf_dialog, "SplitPDFDialog", _FesterSplitDialog)


def test_trennen_fragt_beim_ersten_mal_dann_nicht_mehr(main_window, scan, split_dialog, monkeypatch):  # noqa: F811
    a, b = _pdf(scan / "a.pdf", 3), _pdf(scan / "b.pdf", 2)
    main_window._navigate_to_folder(scan)
    gestellt = _fragen(monkeypatch, (True, True))

    main_window.on_pdf_split(a)
    assert len(gestellt) == 1 and not a.exists()
    assert sorted(p.name for p in scan.glob("a_Seite_*.pdf")) == ["a_Seite_1.pdf", "a_Seite_2.pdf", "a_Seite_3.pdf"]
    assert main_window.config.get("original_wegraeumen")["trennen"] is True
    assert main_window.config.get("original_wegraeumen")["umwandeln"] is None  # getrennte Schluessel
    assert all(w.pdf_path != a for w in main_window.pdf_widgets)

    main_window.on_pdf_split(b)  # gemerkt: ohne Frage in den Papierkorb
    assert len(gestellt) == 1 and not b.exists()


def test_trennen_strg_z_holt_original_zurueck(main_window, scan, split_dialog, monkeypatch):  # noqa: F811
    a = _pdf(scan / "a.pdf", 2)
    main_window._navigate_to_folder(scan)
    _fragen(monkeypatch, (True, False))
    main_window.on_pdf_split(a)
    assert not a.exists() and main_window._undo_stack[-1]["type"] == "wegraeumen"

    main_window.undo_last_action()
    assert a.exists() and (scan / "a_Seite_1.pdf").exists()  # die Teile bleiben


def test_trennen_nein_behaelt_original(main_window, scan, split_dialog, monkeypatch):  # noqa: F811
    a = _pdf(scan / "a.pdf", 2)
    main_window._navigate_to_folder(scan)
    _fragen(monkeypatch, (False, True))
    main_window.on_pdf_split(a)
    assert a.exists() and main_window.config.get("original_wegraeumen")["trennen"] is False
    main_window.on_pdf_split(a)  # kuenftig behalten, ohne Frage
    assert a.exists()


def test_trennen_fehler_loescht_nicht(main_window, scan, split_dialog, monkeypatch):  # noqa: F811
    a = _pdf(scan / "a.pdf", 2)
    main_window._navigate_to_folder(scan)
    monkeypatch.setattr(main_window.file_manager, "split_pdf", lambda *x, **k: (_ for _ in ()).throw(ValueError("kaputt")))
    monkeypatch.setattr(ow, "_frage", lambda *a: pytest.fail("Frage trotz Fehler"))
    from src.gui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.QMessageBox, "critical", lambda *a, **k: None)
    main_window.on_pdf_split(a)
    assert a.exists()


# --- Dialog und Einstellungen -------------------------------------------------------------

def test_dialog_standard_ja_haekchen_und_hinweis(qtbot):
    dialog = ow.OriginalFragenDialog(None, "Original in den Papierkorb verschieben?")
    qtbot.addWidget(dialog)
    assert dialog.defaultButton() is dialog.button(QMessageBox.StandardButton.Yes)
    assert dialog.nicht_mehr_fragen.text() == "Nicht mehr fragen" and not dialog.nicht_mehr_fragen.isChecked()
    assert "Mit Strg+Z holst du es zurück." in dialog.informativeText()


def test_ohne_papierkorb_bleibt_original_liegen(qtbot, main_window, scan, split_dialog, monkeypatch):  # noqa: F811
    from tests.test_file_manager import _fake_papierkorb

    a = _pdf(scan / "a.pdf", 2)
    main_window._navigate_to_folder(scan)
    _fake_papierkorb(monkeypatch, scan.parent / "trash", ok=False)
    _fragen(monkeypatch, (True, False))
    warnungen = []
    monkeypatch.setattr(ow.QMessageBox, "warning", lambda *x, **k: warnungen.append(x[2]))
    main_window.on_pdf_split(a)
    assert a.exists() and warnungen and "Papierkorb nicht verfügbar" in warnungen[0]


def test_einstellungen_zeigen_und_speichern_antworten(qtbot, fresh_config_dialog):
    d = fresh_config_dialog
    ow.antwort_speichern(d.config, "umwandeln", True)
    d._load_settings()
    assert d.original_combos["umwandeln"].currentData() is True
    assert d.original_combos["trennen"].currentData() is None
    d.original_combos["umwandeln"].setCurrentIndex(d.original_combos["umwandeln"].findData(False))
    d.original_combos["trennen"].setCurrentIndex(d.original_combos["trennen"].findData(True))
    d._save_settings()
    assert d.config.get("original_wegraeumen") == {
        "umwandeln": False, "trennen": True, "zusammenfuegen": None, "entsperren": None}  # Issue #244
    d.original_combos["entsperren"].setCurrentIndex(d.original_combos["entsperren"].findData(True))
    d._save_settings()
    assert ow.gespeicherte_antwort(d.config, "entsperren") is True


@pytest.fixture
def fresh_config_dialog(qtbot, fresh_singletons, monkeypatch):  # noqa: F811
    from src.gui.settings_dialog import SettingsDialog

    monkeypatch.setattr(SettingsDialog, "accept", lambda self: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok)
    d = SettingsDialog()
    qtbot.addWidget(d)
    return d

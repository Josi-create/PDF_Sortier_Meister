"""GUI-Tests fuer Issue #9: .docx/.xlsx in der Ansicht und "In PDF umwandeln".

Fixtures wie in ``tests/test_auto_next_after_move_gui.py``: Singletons auf
tmp-Pfade, keine Hintergrund-Leser, nie die echte Nutzer-Config. Word/LibreOffice
laufen nicht - ``umwandeln`` wird ersetzt.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6 import sip
from PyQt6.QtWidgets import QMessageBox


@pytest.fixture
def fresh_singletons(monkeypatch, tmp_path):
    db_path = tmp_path / "office_smoke.db"
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod
    from src.ml import classifier as cl_mod
    from src.ml import hybrid_classifier as hc_mod
    from src.core import pdf_cache as pc_mod

    from tests.conftest import patch_singletons
    fresh_config = cfg_mod.Config(config_path=tmp_path / "config.json")
    fresh_config.set("persist_pdf_cache", False)
    monkeypatch.setattr(pc_mod.PDFCache, "_instance", None)
    # Eine Datenbank je Test: eine neue je Aufruf liess Haupt- und Hintergrund-Thread
    # gleichzeitig create_all() ausfuehren ("table ... already exists", sporadisch)
    datenbank = db_mod.Database(db_path=str(db_path))
    patch_singletons(monkeypatch, {
        "get_config": lambda: fresh_config,
        "get_database": lambda: datenbank,
        "get_classifier": cl_mod.PDFClassifier,
        "get_hybrid_classifier": hc_mod.HybridClassifier,
        "get_pdf_cache": pc_mod.PDFCache,
    })
    return {"config": fresh_config, "tmp_path": tmp_path}


@pytest.fixture
def main_window(qtbot, fresh_singletons, monkeypatch):
    from PyQt6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)

    from src.gui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.QMainWindow, "showMaximized", lambda self: None)
    monkeypatch.setattr(mw_mod.QMainWindow, "show", lambda self: None)
    from src.gui import pdf_thumbnail as th_mod
    from src.gui import detail_panel as dp_mod
    monkeypatch.setattr(th_mod.ThumbnailLoaderThread, "start", lambda self: None)
    monkeypatch.setattr(dp_mod.PdfPreviewWidget, "load_pdf", lambda self, path: None)
    monkeypatch.setattr(dp_mod._PdfMetadataReader, "start", lambda self: None)
    monkeypatch.setattr(mw_mod, "index_melden", lambda *a, **k: None)
    # Vorschau-Cache nie im echten APPDATA
    from src.core import office_vorschau
    monkeypatch.setattr(office_vorschau, "vorschau_cache_ordner", lambda: fresh_singletons["tmp_path"] / "cache")
    monkeypatch.setattr(mw_mod.QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(mw_mod.QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)

    # Nie Word/LibreOffice starten: Vorschau-Umwandlung scheitert schnell (Tests ueberschreiben das)
    from src.gui import office_convert_worker as worker_mod

    def keine_vorschau(pfad):
        raise RuntimeError("keine Vorschau im Test")

    monkeypatch.setattr(worker_mod, "vorschau_pdf", keine_vorschau)

    # initial_load laeuft im Programm 100 ms nach dem Start per Timer und baut die Kacheln
    # neu. In langsamen CI-Laeufen traf das mitten in einen Test (gemerkte Kachel geloescht).
    # Hier laeuft es sofort; der Timer findet nur noch eine leere Funktion vor.
    echtes_initial_load = mw_mod.MainWindow.initial_load
    monkeypatch.setattr(mw_mod.MainWindow, "initial_load", lambda self: None)
    win = mw_mod.MainWindow()
    monkeypatch.setattr(mw_mod.MainWindow, "initial_load", echtes_initial_load)
    win.initial_load()
    monkeypatch.setattr(win.classifier, "is_model_ready", lambda: True)
    yield win
    win.close()
    sip.delete(win)


def _scan(tmp_path: Path) -> Path:
    scan = tmp_path / "Scan"
    scan.mkdir()
    (scan / "a.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (scan / "Brief.docx").write_bytes(b"PK")
    (scan / "Zahlen.XLSX").write_bytes(b"PK")
    (scan / "~$Brief.docx").write_bytes(b"lock")  # Word-Sperrdatei
    (scan / "alt.doc").write_bytes(b"x")  # nicht unterstuetzt
    return scan


def _prime_cache_on_load(main_window, monkeypatch):
    """Analyse-Ergebnisse synchron in den Cache legen, sobald Kacheln entstehen
    (sonst startet der Klick-Pfad Hintergrund-Analysen)."""
    from src.core.pdf_cache import PDFAnalysisResult

    original = main_window.load_pdfs

    def laden():
        original()
        for w in main_window.pdf_widgets:
            main_window.pdf_cache._cache[w.pdf_path] = PDFAnalysisResult(
                pdf_path=w.pdf_path, file_modified=w.pdf_path.stat().st_mtime)

    monkeypatch.setattr(main_window, "load_pdfs", laden)


def test_file_manager_listet_nur_docx_und_xlsx(tmp_path):
    from src.core.file_manager import FileManager
    fm = FileManager(_scan(tmp_path))
    assert [p.name for p in fm.get_office_files()] == ["Brief.docx", "Zahlen.XLSX"]


def test_office_dateien_erscheinen_als_kacheln(main_window, fresh_singletons):
    main_window._navigate_to_folder(_scan(fresh_singletons["tmp_path"]))
    assert len(main_window.pdf_widgets) == 3  # PDF + 2 Office in derselben Liste
    assert [w.pdf_path.name for w in main_window.pdf_widgets if w not in main_window.office_widgets] == ["a.pdf"]
    # Reihenfolge haengt von der Sortierung (#33, Aenderungsdatum) ab
    assert sorted(w.pdf_path.name for w in main_window.office_widgets) == ["Brief.docx", "Zahlen.XLSX"]
    w = main_window.office_widgets[0]
    assert w.thumbnail_label.pixmap() is not None and not w.thumbnail_label.pixmap().isNull()
    assert not w.acceptDrops()


def test_office_kachel_kontextmenue(main_window, fresh_singletons):
    main_window._navigate_to_folder(_scan(fresh_singletons["tmp_path"]))
    menu = main_window.office_widgets[0]._build_context_menu()
    texte = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert "In PDF umwandeln" in texte
    assert any("PDF/A" in t for t in texte)
    assert "PDF öffnen" not in texte


def test_nur_office_dateien_im_ordner_zeigen_kacheln(main_window, fresh_singletons):
    scan = fresh_singletons["tmp_path"] / "Nur"
    scan.mkdir()
    (scan / "x.docx").write_bytes(b"PK")
    main_window._navigate_to_folder(scan)
    assert len(main_window.pdf_widgets) == 1
    assert len(main_window.office_widgets) == 1


def test_umwandeln_legt_pdf_daneben_an_und_laedt_neu(qtbot, main_window, fresh_singletons, monkeypatch):
    from src.core.office_convert import UmwandlungsErgebnis
    from src.gui import office_convert_worker as worker_mod

    scan = _scan(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)
    aufrufe = []

    def falsch(pfad, pdfa=False):
        aufrufe.append((pfad.name, pdfa))
        ziel = pfad.with_suffix(".pdf")
        ziel.write_bytes(b"%PDF-1.4\n%%EOF\n")
        return UmwandlungsErgebnis(pdf=ziel, werkzeug="Word", pdfa=pdfa)

    monkeypatch.setattr(worker_mod, "umwandeln", falsch)
    _prime_cache_on_load(main_window, monkeypatch)
    main_window.on_office_convert(scan / "Brief.docx", True)
    qtbot.waitUntil(lambda: main_window._office_worker is None, timeout=5000)

    assert aufrufe == [("Brief.docx", True)]
    assert (scan / "Brief.pdf").exists() and (scan / "Brief.docx").exists()
    assert sorted(w.pdf_path.name for w in main_window.pdf_widgets if w.pdf_path.suffix == ".pdf") == ["Brief.pdf", "a.pdf"]
    # Das neue PDF ist ausgewaehlt, als haette der Nutzer es angeklickt
    assert main_window.selected_pdf == scan / "Brief.pdf"
    assert [w.pdf_path.name for w in main_window.pdf_widgets if w.selected] == ["Brief.pdf"]


def test_umwandeln_fehler_wird_gemeldet_ohne_neu_laden(qtbot, main_window, fresh_singletons, monkeypatch):
    from src.core.office_convert import KeinUmwandlerGefunden
    from src.gui import main_window as mw_mod
    from src.gui import office_convert_worker as worker_mod

    scan = _scan(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)
    meldungen = []
    monkeypatch.setattr(mw_mod.QMessageBox, "warning", lambda *a, **k: meldungen.append(a[2]))

    def kaputt(pfad, pdfa=False):
        raise KeinUmwandlerGefunden("Weder Word noch LibreOffice")

    monkeypatch.setattr(worker_mod, "umwandeln", kaputt)
    main_window.on_office_convert(scan / "Brief.docx", False)
    qtbot.waitUntil(lambda: main_window._office_worker is None, timeout=5000)

    assert meldungen and "Weder Word noch LibreOffice" in meldungen[0]
    assert not (scan / "Brief.pdf").exists()


def _prime_text(main_window, pfad: Path, text="Stromrechnung Stadtwerke", keywords=("energie",)):
    """Analyse-Ergebnis mit Text synchron in den Cache (kein Hintergrund-Worker)."""
    from src.core.pdf_cache import PDFAnalysisResult

    main_window.pdf_cache._cache[pfad] = PDFAnalysisResult(
        pdf_path=pfad, extracted_text=text, keywords=list(keywords),
        file_modified=pfad.stat().st_mtime)


def test_klick_auf_office_kachel_waehlt_aus_und_zeigt_vorschau(qtbot, main_window, fresh_singletons, monkeypatch):
    from src.gui import office_convert_worker as worker_mod

    scan = _scan(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)
    vorschau = fresh_singletons["tmp_path"] / "v.pdf"
    vorschau.write_bytes(b"%PDF-1.4\n%%EOF\n")
    monkeypatch.setattr(worker_mod, "vorschau_pdf", lambda pfad: vorschau)
    geladen = []
    monkeypatch.setattr(main_window.detail_panel.preview, "load_pdf", lambda p: geladen.append(p))
    docx = scan / "Brief.docx"
    _prime_text(main_window, docx)

    w = next(x for x in main_window.pdf_widgets if x.pdf_path == docx)
    w.clicked.emit(w.pdf_path)  # wie bei PDFs: normale Auswahl, Analyse aus dem Cache

    assert main_window.selected_pdf == docx and w.selected
    assert main_window.selected_pdf_text == "Stromrechnung Stadtwerke"
    qtbot.waitUntil(lambda: main_window._office_vorschau_worker is None, timeout=5000)
    assert geladen == [vorschau]  # rechts die Seitenvorschau
    # Klick auf eine PDF waehlt um
    monkeypatch.setattr(main_window, "update_suggestions_for_pdf", lambda p: None)
    main_window.on_pdf_clicked(scan / "a.pdf")
    # Die Kachel frisch holen: laedt das Fenster die Liste im Hintergrund neu,
    # ist ``w`` eine alte, nicht mehr angezeigte Kachel (CI, sporadisch)
    aktuell = main_window._pdf_widget_for(docx)
    assert main_window.selected_pdf == scan / "a.pdf"
    assert aktuell is None or not aktuell.selected


def test_analysiere_nutzt_lastprinted_bei_datumsfeldern(tmp_path):
    import zipfile
    from datetime import datetime
    from src.core.office_analyse import analysiere

    feld = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> PRINTDATE \\@ "dd.MM.yyyy" </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>01.01.2001</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p>'
           f'<w:r><w:t>Rechnung Strom </w:t></w:r>{feld}</w:p></w:body></w:document>')
    d = tmp_path / "b.docx"
    with zipfile.ZipFile(d, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
        z.writestr("docProps/core.xml",
                   '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties">'
                   "<cp:lastPrinted>2015-05-08T20:46:00Z</cp:lastPrinted></cp:coreProperties>")
    text, keywords, daten = analysiere(d)
    assert "Rechnung" in text and "rechnung" in keywords
    assert daten[0].date() == datetime(2015, 5, 8).date()


def _office_ausgewaehlt(main_window, scan, name="Brief.docx"):
    main_window._navigate_to_folder(scan)
    docx = scan / name
    _prime_text(main_window, docx)
    main_window.on_pdf_clicked(docx)
    assert main_window.selected_pdf == docx
    return docx


def _ja(monkeypatch):
    from src.gui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)


def test_verschieben_per_vorschlag_behaelt_endung_lernt_und_undo(main_window, fresh_singletons, monkeypatch):
    tmp = fresh_singletons["tmp_path"]
    scan = _scan(tmp)
    ziel = tmp / "Ziel"
    ziel.mkdir()
    docx = _office_ausgewaehlt(main_window, scan)
    _ja(monkeypatch)
    main_window.detail_panel.name_input.setText("2026-05-12_Strom_Stadtwerke")  # kommt mit ".pdf" heraus
    vorher = main_window.classifier.get_training_count()

    main_window.on_suggestion_clicked(ziel)

    assert (ziel / "2026-05-12_Strom_Stadtwerke.docx").exists()
    assert not docx.exists() and not list(ziel.glob("*.pdf"))
    assert main_window.classifier.get_training_count() > vorher  # Lern-Eintrag
    assert docx not in [w.pdf_path for w in main_window.pdf_widgets]

    main_window.undo_last_action()  # wie bei PDFs: zurueck in den Scan-Ordner, mit dem neuen Namen
    assert (scan / "2026-05-12_Strom_Stadtwerke.docx").exists() and not list(ziel.glob("*"))


def test_verschieben_per_baumklick_ohne_umbenennen(main_window, fresh_singletons, monkeypatch):
    tmp = fresh_singletons["tmp_path"]
    scan = _scan(tmp)
    ziel = tmp / "Ziel"
    ziel.mkdir()
    docx = _office_ausgewaehlt(main_window, scan, "Zahlen.XLSX")
    _ja(monkeypatch)
    main_window.detail_panel.name_input.setText("")  # kein neuer Name -> Originalname

    main_window.on_tree_folder_selected(ziel)

    assert (ziel / "Zahlen.XLSX").exists() and not docx.exists()


def test_verschieben_mit_ordner_namensvorlage_behaelt_endung(main_window, fresh_singletons, monkeypatch):
    tmp = fresh_singletons["tmp_path"]
    scan = _scan(tmp)
    ziel = tmp / "JK 069-03 Rohbau"
    ziel.mkdir()
    main_window.config.set("folder_naming_enabled", True, auto_save=False)
    main_window.config.set("owner_initials", "JK", auto_save=False)
    _office_ausgewaehlt(main_window, scan)
    _ja(monkeypatch)
    main_window.detail_panel.name_input.setText("2026-05-12_Rechnung_Elektro")

    main_window._move_rename_and_learn(scan / "Brief.docx", ziel)

    gefunden = list(ziel.glob("*"))
    assert len(gefunden) == 1 and gefunden[0].suffix == ".docx"
    assert gefunden[0].name.startswith("JK 069-03-")


def test_verschieben_per_drop_und_undo(main_window, fresh_singletons, monkeypatch):
    _ja(monkeypatch)  # Rueckfrage beim Rueckgaengig
    tmp = fresh_singletons["tmp_path"]
    scan = _scan(tmp)
    ziel = tmp / "Ziel"
    ziel.mkdir()
    main_window._navigate_to_folder(scan)
    docx = scan / "Brief.docx"

    main_window.on_pdf_dropped_on_folder(docx, ziel)

    assert (ziel / "Brief.docx").exists() and not docx.exists()
    assert docx not in [w.pdf_path for w in main_window.pdf_widgets]
    main_window.undo_last_action()
    assert docx.exists()


def test_mehrfachauswahl_pdf_und_office_wird_verschoben(main_window, fresh_singletons, monkeypatch):
    tmp = fresh_singletons["tmp_path"]
    scan = _scan(tmp)
    ziel = tmp / "Ziel"
    ziel.mkdir()
    main_window._navigate_to_folder(scan)
    _ja(monkeypatch)
    main_window.selected_pdfs = [scan / "a.pdf", scan / "Brief.docx"]

    main_window.on_suggestion_clicked(ziel)

    assert sorted(p.name for p in ziel.iterdir()) == ["Brief.docx", "a.pdf"]
    # PDF-only-Aktionen lassen Office-Dateien in der Auswahl aus
    main_window.selected_pdfs = [scan / "x.pdf", scan / "y.docx"]
    assert main_window._aktion_ziele(scan / "x.pdf") == [scan / "x.pdf"]


def test_ordner_kacheln_nehmen_office_drops_an(qtbot):
    from PyQt6.QtCore import QMimeData, QUrl
    from src.gui.folder_tile import FolderTileWidget

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(Path("C:/x") / n)) for n in ("a.docx", "b.xlsx", "c.pdf", "d.txt")])
    assert [p.name for p in FolderTileWidget._pdf_paths(mime)] == ["a.docx", "b.xlsx", "c.pdf"]


def test_pdf_wird_nicht_auf_office_kachel_gestapelt(main_window, fresh_singletons):
    main_window._navigate_to_folder(_scan(fresh_singletons["tmp_path"]))
    assert all(not w.acceptDrops() for w in main_window.office_widgets)


def test_vorschau_fehler_wird_im_panel_gezeigt(qtbot, main_window, fresh_singletons, monkeypatch):
    from src.gui import office_convert_worker as worker_mod

    main_window._navigate_to_folder(_scan(fresh_singletons["tmp_path"]))

    def kaputt(pfad):
        raise RuntimeError("kein Word")

    monkeypatch.setattr(worker_mod, "vorschau_pdf", kaputt)
    hinweise = []
    monkeypatch.setattr(main_window.detail_panel.preview, "show_message", lambda t: hinweise.append(t))
    w = main_window.office_widgets[0]
    _prime_text(main_window, w.pdf_path)
    w.clicked.emit(w.pdf_path)
    qtbot.waitUntil(lambda: main_window._office_vorschau_worker is None, timeout=5000)
    assert any("kein Word" in h for h in hinweise)


def test_loeschen_fragt_entfernt_kachel_und_cache(main_window, fresh_singletons, monkeypatch):
    from src.core import office_vorschau
    from src.gui import main_window as mw_mod

    scan = _scan(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)
    fragen = []
    monkeypatch.setattr(
        mw_mod.QMessageBox, "question",
        lambda *a, **k: fragen.append(a[1:3]) or QMessageBox.StandardButton.Yes,
    )
    geloescht = []
    monkeypatch.setattr(office_vorschau, "vorschau_loeschen", lambda p: geloescht.append(p))

    # nach Namen waehlen: die Reihenfolge haengt von der Sortierung (#33) ab
    w = next(x for x in main_window.office_widgets if x.pdf_path.name == "Brief.docx")
    assert "Löschen" in [a.text() for a in w._build_context_menu().actions()]
    w.delete_requested.emit(w.pdf_path)

    assert fragen and "Brief.docx" in fragen[0][1]
    assert not (scan / "Brief.docx").exists()
    assert [x.pdf_path.name for x in main_window.office_widgets] == ["Zahlen.XLSX"]
    assert geloescht == [scan / "Brief.docx"]


def test_loeschen_abgelehnt_laesst_alles(main_window, fresh_singletons, monkeypatch):
    from src.gui import main_window as mw_mod

    scan = _scan(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)
    monkeypatch.setattr(mw_mod.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    main_window.on_office_delete(scan / "Brief.docx")
    assert (scan / "Brief.docx").exists() and len(main_window.office_widgets) == 2


def test_text_seite_und_kachelbild_fallback(qtbot, tmp_path):
    from src.gui.office_thumbnail import kachelbild, text_seite

    bild = text_seite(["Erste Zeile", "Zweite Zeile"], Path("x.docx"))
    assert not bild.isNull() and bild.width() == 140
    kaputt = tmp_path / "k.docx"
    kaputt.write_bytes(b"PK")
    assert kachelbild(kaputt) is None  # kein Bild, kein Text -> Platzhalter bleibt

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
    patch_singletons(monkeypatch, {
        "get_config": lambda: fresh_config,
        "get_database": lambda: db_mod.Database(db_path=str(db_path)),
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
    monkeypatch.setattr(mw_mod.QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(mw_mod.QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)

    win = mw_mod.MainWindow()
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


def test_file_manager_listet_nur_docx_und_xlsx(tmp_path):
    from src.core.file_manager import FileManager
    fm = FileManager(_scan(tmp_path))
    assert [p.name for p in fm.get_office_files()] == ["Brief.docx", "Zahlen.XLSX"]


def test_office_dateien_erscheinen_als_kacheln(main_window, fresh_singletons):
    main_window._navigate_to_folder(_scan(fresh_singletons["tmp_path"]))
    assert len(main_window.pdf_widgets) == 1  # PDF-Logik unberuehrt
    assert [w.pdf_path.name for w in main_window.office_widgets] == ["Brief.docx", "Zahlen.XLSX"]
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
    assert len(main_window.pdf_widgets) == 0
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
    main_window.on_office_convert(scan / "Brief.docx", True)
    qtbot.waitUntil(lambda: main_window._office_worker is None, timeout=5000)

    assert aufrufe == [("Brief.docx", True)]
    assert (scan / "Brief.pdf").exists() and (scan / "Brief.docx").exists()
    assert sorted(w.pdf_path.name for w in main_window.pdf_widgets) == ["Brief.pdf", "a.pdf"]


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

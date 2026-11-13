"""Das Hauptfenster darf waehrend Hintergrund-Analyse und KI-Vorabfrage nicht haengen.

Befund vom 13.11.2026 (Scan-Ordner mit 400 Dateien in OneDrive, Fenster minutenlang
"Keine Rückmeldung"): Die Fortschrittsanzeige der Statusleiste fragte bei JEDER fertigen
Analyse und bei jedem Beginn/Ende eines KI-Aufrufs fuer ALLE Kacheln ``PDFCache.get`` - das
prueft je Aufruf mit zwei Dateizugriffen, ob die Datei unveraendert ist. 400 PDFs ergaben so
800 Dateizugriffe je Ereignis im GUI-Thread. Dazu schrieb der GUI-Thread jedes Ergebnis selbst
in die Cache-Datenbank.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest
from PyQt6 import sip

from src.core.pdf_cache import LLMSuggestion, PDFAnalysisResult

# --------------------------------------------------------------------- #
# PDFCache
# --------------------------------------------------------------------- #


def _neuer_cache(tmp_path, monkeypatch, persist: bool):
    from src.core import pdf_cache as pc
    from src.utils import config as cfg_mod

    fresh = cfg_mod.Config(config_path=tmp_path / "config.json")
    fresh.set("persist_pdf_cache", persist)
    monkeypatch.setattr(cfg_mod, "get_config", lambda: fresh)
    monkeypatch.setattr(pc.PDFCache, "_instance", None)
    c = pc.PDFCache()
    assert c._persist_cache is persist
    if persist:
        assert c._db_path.parent == tmp_path  # nie die Datenbank des Nutzers
    monkeypatch.setattr(c, "start_llm_worker", lambda: None)
    c._llm_precache_enabled = False
    return c


def _pdfs(tmp_path, anzahl: int) -> list[Path]:
    pfade = []
    for i in range(anzahl):
        p = tmp_path / f"scan{i}.pdf"
        p.write_bytes(b"%PDF-1.4\n%%EOF\n")
        pfade.append(p)
    return pfade


def _analyse(pdf: Path, mit_ki: bool = False) -> PDFAnalysisResult:
    r = PDFAnalysisResult(pdf_path=pdf, extracted_text="x", file_modified=pdf.stat().st_mtime)
    if mit_ki:
        r.llm_suggestions = [LLMSuggestion(filename="a.pdf", confidence=0.9, source="llm")]
        r.llm_fetched = True
    return r


def _zeilen(db: Path) -> dict[str, int]:
    con = sqlite3.connect(str(db))
    try:
        return dict(con.execute("SELECT pdf_path, llm_fetched FROM pdf_cache"))
    finally:
        con.close()


def test_fortschritt_zaehlt_ohne_dateizugriff(tmp_path, monkeypatch):
    cache = _neuer_cache(tmp_path, monkeypatch, persist=False)
    a, b, c, d = _pdfs(tmp_path, 4)
    cache._cache[a] = _analyse(a)
    cache._cache[b] = _analyse(b, mit_ki=True)
    cache._cache[c] = _analyse(c, mit_ki=True)

    def verboten(*args, **kwargs):
        raise AssertionError("Dateizugriff in der Fortschrittsanzeige")

    monkeypatch.setattr(Path, "stat", verboten)
    monkeypatch.setattr(Path, "exists", verboten)

    assert cache.fortschritt([a, b, c, d]) == (3, 2)
    assert cache.fortschritt([]) == (0, 0)


def test_analyse_ergebnis_wird_nicht_im_aufrufenden_thread_gespeichert(tmp_path, monkeypatch):
    cache = _neuer_cache(tmp_path, monkeypatch, persist=True)
    (pdf,) = _pdfs(tmp_path, 1)
    threads = []
    echt = cache._save_all_to_db

    def merken(results):
        threads.append(threading.get_ident())
        echt(results)

    monkeypatch.setattr(cache, "_save_all_to_db", merken)

    cache._on_analysis_complete(pdf, _analyse(pdf))
    assert cache.db_schreiben_abwarten() is True

    assert threads and threading.get_ident() not in threads
    assert _zeilen(cache._db_path) == {str(pdf): 0}

    cache._on_llm_suggestions_complete(pdf, [LLMSuggestion(filename="neu.pdf", confidence=0.9, source="llm")])
    assert cache.db_schreiben_abwarten() is True
    assert threading.get_ident() not in threads
    assert _zeilen(cache._db_path) == {str(pdf): 1}


def test_loeschen_wartet_auf_ausstehendes_speichern(tmp_path, monkeypatch):
    """Sonst kaeme ein Eintrag, der noch in der Warteschlange steht, nach dem Loeschen zurueck."""
    cache = _neuer_cache(tmp_path, monkeypatch, persist=True)
    pfade = _pdfs(tmp_path, 30)
    for p in pfade:
        cache._on_analysis_complete(p, _analyse(p))

    cache.clear_for_pdf(pfade[-1])

    assert cache.db_schreiben_abwarten() is True
    zeilen = _zeilen(cache._db_path)
    assert str(pfade[-1]) not in zeilen and len(zeilen) == 29


def test_gespeichertes_ueberlebt_den_neustart(tmp_path, monkeypatch):
    from src.core import pdf_cache as pc

    cache = _neuer_cache(tmp_path, monkeypatch, persist=True)
    pfade = _pdfs(tmp_path, 5)
    for p in pfade:
        cache._on_analysis_complete(p, _analyse(p))
    cache.stop_worker()  # Beenden wartet auf die Schreibauftraege

    monkeypatch.setattr(pc.PDFCache, "_instance", None)
    neu = pc.PDFCache()
    assert neu.fortschritt(pfade) == (5, 0)


def test_ohne_gespeicherten_cache_entsteht_kein_schreib_thread(tmp_path, monkeypatch):
    cache = _neuer_cache(tmp_path, monkeypatch, persist=False)
    (pdf,) = _pdfs(tmp_path, 1)

    cache._on_analysis_complete(pdf, _analyse(pdf))

    assert cache._db_schreiber is None and cache.db_schreiben_abwarten() is True


# --------------------------------------------------------------------- #
# Hauptfenster: Statusleiste
# --------------------------------------------------------------------- #


@pytest.fixture
def main_window(qtbot, monkeypatch, tmp_path):
    from PyQt6.QtCore import QSettings

    from src.core import pdf_cache as pc_mod
    from src.gui import detail_panel as dp_mod
    from src.gui import main_window as mw_mod
    from src.gui import pdf_thumbnail as th_mod
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
        "get_database": lambda: db_mod.Database(db_path=str(tmp_path / "haenger.db")),
        "get_classifier": cl_mod.PDFClassifier,
        "get_hybrid_classifier": hc_mod.HybridClassifier,
        "get_pdf_cache": pc_mod.PDFCache,
    })
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    monkeypatch.setattr(th_mod.ThumbnailLoaderThread, "start", lambda self: None)
    monkeypatch.setattr(dp_mod.PdfPreviewWidget, "load_pdf", lambda self, path: None)
    monkeypatch.setattr(dp_mod._PdfMetadataReader, "start", lambda self: None)
    monkeypatch.setattr(mw_mod.QMainWindow, "showMaximized", lambda self: None)
    monkeypatch.setattr(mw_mod.QMainWindow, "show", lambda self: None)

    win = mw_mod.MainWindow()
    # Keine echten Hintergrund-Worker: die Ereignisse loest der Test selbst aus
    monkeypatch.setattr(win, "_schedule_pre_caching", lambda *a, **k: None)
    yield win

    win.close()
    sip.delete(win)


def test_statusleiste_fasst_bei_ereignissen_keine_dateien_an(main_window, tmp_path, monkeypatch):
    win = main_window
    scan = tmp_path / "Scan"
    scan.mkdir()
    pfade = _pdfs(scan, 6)
    win._navigate_to_folder(scan)
    assert len(win.pdf_widgets) == 6
    cache = win.pdf_cache
    for p in pfade[:3]:
        cache._cache[p] = _analyse(p, mit_ki=p == pfade[0])
    monkeypatch.setattr(win.hybrid_classifier, "is_llm_available", lambda: True)

    zugriffe = []
    echt_stat, echt_exists = Path.stat, Path.exists

    def stat(self, *a, **k):
        if self.parent == scan:
            zugriffe.append(self.name)
        return echt_stat(self, *a, **k)

    def exists(self, *a, **k):
        if self.parent == scan:
            zugriffe.append(self.name)
        return echt_exists(self, *a, **k)

    monkeypatch.setattr(Path, "stat", stat)
    monkeypatch.setattr(Path, "exists", exists)

    # Was waehrend der Vorabfrage je PDF im GUI-Thread ankommt
    win._on_pdf_analyzed(pfade[1])
    win._on_llm_activity_changed()
    win._on_llm_suggestions_ready(pfade[0])
    win._update_cache_status()  # Sekundentakt der Uhr

    assert zugriffe == []
    assert win._precache_progress() == (3, 1, 6)
    text = win.cache_status_label.text()
    assert "3/6" in text and "1/6" in text

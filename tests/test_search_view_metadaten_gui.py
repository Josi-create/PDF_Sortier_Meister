"""Reiter „Suche“ mit PDFSM-Metadaten (Phase 5): Filter Steuerjahr/Kategorie/Korrespondent/Betrag,
``suchen()`` von aussen, Metadatenzeile auf den Karten; die Werkzeugleisten-Suche (Strg+F) des
Hauptfensters landet im Reiter."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QSettings

from src.core.pdf_metadata import PDFMetadata, write_metadata
from src.gui.search_view import SearchView
from src.search.indexer import Indexer
from src.utils.config import Config
from tests import helfer_suche as h


@pytest.fixture
def index_konfig(tmp_path):
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    a = h.pdf_mit_text(ablage / "telekom.pdf", ["Rechnung Telekom Festnetz"])
    write_metadata(a, PDFMetadata(subject="Rechnung", korrespondent="Telekom", steuerjahr="2024", betrag_brutto="59.99"))
    b = h.pdf_mit_text(ablage / "stadtwerke.pdf", ["Rechnung Stadtwerke Strom"])
    write_metadata(b, PDFMetadata(subject="Rechnung", korrespondent="Stadtwerke", steuerjahr="2023",
                                  betrag_brutto="142.30"))
    h.pdf_mit_text(ablage / "notiz.pdf", ["Notiz ohne Metadaten"])
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], prioritaet=[str(ablage)])
    assert Indexer(konfig, synchron=True).lauf() == 0
    return konfig


@pytest.fixture
def view(qtbot, tmp_path, index_konfig):
    cfg = Config(config_path=tmp_path / "config.json")
    cfg.set_search_config(index_konfig)
    v = SearchView(cfg)
    qtbot.addWidget(v)
    yield v
    v.shutdown()


def _suche_fertig(qtbot, view, aktion):
    with qtbot.waitSignal(view.suche_fertig, timeout=15000):
        aktion()
    return view.karten()


def test_metadatenfilter_werte_und_suchen_von_aussen(qtbot, view):
    with qtbot.waitSignal(view.status_aktualisiert, timeout=10000):
        view.refresh_status()
    jahre = [view.meta_combos["steuerjahr"].itemText(i) for i in range(view.meta_combos["steuerjahr"].count())]
    assert jahre == ["Alle", "2024", "2023"]
    assert [view.meta_combos["korrespondent"].itemText(i)
            for i in range(view.meta_combos["korrespondent"].count())] == ["Alle", "Stadtwerke", "Telekom"]

    # Reine Filterabfrage ohne Suchbegriff
    karten = _suche_fertig(qtbot, view, lambda: view.suchen("", steuerjahr="2024"))
    assert [k.dok["name"] for k in karten] == ["telekom.pdf"]
    assert "Telekom · Rechnung · Steuerjahr 2024 · 59,99 €" == karten[0].metadaten_label.text()
    assert view.count_label.text().startswith("1 Dokumente")

    # Suchbegriff plus Korrespondent und Betragsspanne
    karten = _suche_fertig(qtbot, view, lambda: view.suchen("Rechnung", korrespondent="Stadtwerke",
                                                             betrag_von=100, betrag_bis=200))
    assert [k.dok["name"] for k in karten] == ["stadtwerke.pdf"]
    assert view.meta_combos["korrespondent"].currentData() == "Stadtwerke"
    assert view.betrag_von_spin.value() == 100 and view.betrag_bis_spin.value() == 200

    # Treffer in den Metadaten (Korrespondent steht nicht im Text der Notiz, aber in der Telekom-PDF)
    karten = _suche_fertig(qtbot, view, lambda: view.suchen("Telekom"))
    assert [k.dok["name"] for k in karten] == ["telekom.pdf"]

    # Filter ueber die Auswahlliste selbst, Suchfeld leer
    view.leeren()
    assert view.karten() == [] and view.meta_combos["korrespondent"].currentIndex() == 0
    combo = view.meta_combos["kategorie"]
    with qtbot.waitSignal(view.suche_fertig, timeout=15000):
        combo.setCurrentIndex(combo.findData("Rechnung"))
    assert len(view.karten()) == 2
    # Filter zurueck auf „Alle“ ohne Suchbegriff: Liste leer, Hilfe wieder sichtbar
    combo.setCurrentIndex(0)
    qtbot.waitUntil(lambda: view.hilfe_label.isVisibleTo(view), timeout=3000)
    assert view.karten() == []


@pytest.fixture
def hauptfenster(qtbot, tmp_path, monkeypatch, index_konfig):
    """MainWindow mit frischen Singletons (wie test_main_window_gui) und eingerichteter Suche."""
    from src.core import pdf_cache as pc_mod
    from src.ml import classifier as cl_mod
    from src.ml import hybrid_classifier as hc_mod
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod
    from tests.conftest import patch_singletons

    cfg = cfg_mod.Config(config_path=tmp_path / "config.json")
    cfg.set("persist_pdf_cache", False)
    cfg.set_search_config(index_konfig)
    db = db_mod.Database(db_path=str(tmp_path / "history.db"))
    monkeypatch.setattr(pc_mod.PDFCache, "_instance", None)
    patch_singletons(monkeypatch, {
        "get_config": lambda: cfg,
        "get_database": lambda: db,
        "get_classifier": cl_mod.PDFClassifier,
        "get_hybrid_classifier": hc_mod.HybridClassifier,
        "get_pdf_cache": pc_mod.PDFCache,
    })
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    from src.gui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.QMainWindow, "showMaximized", lambda self: None)
    monkeypatch.setattr(mw_mod.QMainWindow, "show", lambda self: None)
    win = mw_mod.MainWindow()
    yield win
    win.close()
    from PyQt6 import sip
    sip.delete(win)


def test_werkzeugleisten_suche_landet_im_reiter(qtbot, hauptfenster):
    win = hauptfenster
    assert win.center_tabs.currentWidget() is not win.search_view
    with qtbot.waitSignal(win.search_view.suche_fertig, timeout=15000):
        win.search_input.setText("Stadtwerke")
    assert win.center_tabs.currentWidget() is win.search_view
    assert [k.dok["name"] for k in win.search_view.karten()] == ["stadtwerke.pdf"]
    assert win.search_count_label.text() == "1 Treffer"
    assert win.search_view.search_edit.text() == "Stadtwerke"
    # Filterleiste: Steuerjahr wirkt im Reiter mit
    win.filter_toggle_btn.setChecked(True)
    win.filter_steuerjahr.setCurrentText("2024")
    with qtbot.waitSignal(win.search_view.suche_fertig, timeout=15000):
        win.search_input.setText("Rechnung")
    assert [k.dok["name"] for k in win.search_view.karten()] == ["telekom.pdf"]
    # Filter zuruecksetzen (Suchbegriff bleibt, Suche laeuft erneut an), dann Suche leeren
    win._reset_filters()
    win._clear_search()
    assert win.search_view.karten() == [] and win.search_count_label.text() == ""
    assert win.search_view.search_edit.text() == "" and win.search_view.meta_combos["steuerjahr"].currentIndex() == 0
    qtbot.wait(800)   # eine nachlaufende Antwort der vorigen Abfrage darf die Liste nicht mehr fuellen
    assert win.search_view.karten() == [] and win.search_count_label.text() == ""


def test_zeitraum_feld_der_filterleiste_gibt_grenzen_an_den_reiter(qtbot, hauptfenster):
    win = hauptfenster
    win.filter_toggle_btn.setChecked(True)
    assert not hasattr(win, "filter_datum_von")
    win.filter_zeitraum.setText("2004-2006")
    assert win.filter_zeitraum.hinweis.text() == "= 01.01.2004 – 31.12.2006"
    assert win._has_active_filters()
    with qtbot.waitSignal(win.search_view.suche_fertig, timeout=15000):
        win.filter_zeitraum.edit.returnPressed.emit()
    assert win.search_view._filter_argumente()["von"] == "2004-01-01"
    assert win.search_view._filter_argumente()["bis"] == "2006-12-31"
    assert win.search_view.zeitraum_edit.text() == "01.01.2004 bis 31.12.2006"
    # Unlesbar: roter Rand und Hinweis, es wird keine Suche ausgeloest
    ausgeloest = []
    win.filter_zeitraum.geaendert.connect(lambda: ausgeloest.append(1))
    win.filter_zeitraum.setText("Quatsch")
    win.filter_zeitraum.edit.returnPressed.emit()
    assert "#d32f2f" in win.filter_zeitraum.edit.styleSheet()
    assert win.filter_zeitraum.hinweis.text().startswith("nicht erkannt")
    assert ausgeloest == []
    win._reset_filters()
    assert win.filter_zeitraum.text() == "" and not win._has_active_filters()
    assert win.search_view.zeitraum_edit.text() == ""

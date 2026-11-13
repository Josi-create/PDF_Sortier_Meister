"""Schlagwoerter mit Ebenen an der Oberflaeche (Issue #231): Feld im Detail-Panel mit Vorschlagsliste,
Speichern in der PDF, Filter „Schlagwort“ im Reiter „Suche“ und in der Filterleiste.

Alle Dokumente und Schlagwoerter sind erfunden.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QSettings

from src.core import schlagwoerter as sw
from src.core.pdf_metadata import PDFMetadata, read_metadata, write_metadata
from src.gui.schlagwort_feld import SchlagwortFeld
from src.gui.search_view import SearchView
from src.search.indexer import Indexer
from src.search.meldungen import meldungen
from src.search.suchindex import Suchindex
from src.utils.config import Config
from tests import helfer_suche as h


# --------------------------------------------------------------------------- Eingabefeld

def test_feld_schlaegt_je_eintrag_vor_und_setzt_ein(qtbot):
    feld = SchlagwortFeld()
    qtbot.addWidget(feld)
    feld.set_choices(["Haus", "Steuer", "Steuer/Werbungskosten"])

    feld.setText("Haus, wer")
    feld.setCursorPosition(len("Haus, wer"))
    assert feld.aktueller_anfang() == "wer"
    feld._vorschlagen()
    c = feld._completer
    assert [c.completionModel().index(i, 0).data() for i in range(c.completionCount())] == [
        "Steuer/Werbungskosten"]                                 # Treffer auch mitten im Schlagwort
    feld.eintrag_einsetzen("Steuer/Werbungskosten")
    assert feld.text() == "Haus, Steuer/Werbungskosten"

    # Eintrag in der Mitte ersetzen: der Rest bleibt stehen
    feld.setText("ste, Haus")
    feld.setCursorPosition(3)
    feld.eintrag_einsetzen("Steuer")
    assert feld.text() == "Steuer, Haus" and feld.cursorPosition() == len("Steuer")

    # leerer Eintrag: keine Liste
    feld.setText("Haus, ")
    feld.setCursorPosition(len("Haus, "))
    assert feld.aktueller_anfang() == ""
    feld._vorschlagen()
    assert not c.popup().isVisible()


# --------------------------------------------------------------------------- Detail-Panel

@pytest.fixture
def panel_ohne_threads(monkeypatch):
    """DetailPanel ohne Hintergrund-Threads (Vorschau, Metadaten-Leser): sonst kann ein Thread noch
    laufen, wenn der Test das Panel schon abbaut. Die Metadaten liest der Test selbst ein."""
    from src.gui.detail_panel import DetailPanel

    monkeypatch.setattr(DetailPanel, "_vorschau_laden", lambda self, pfad: None)
    monkeypatch.setattr(DetailPanel, "_start_metadata_reader", lambda self, pfad: None)
    return DetailPanel


def test_panel_zeigt_schlagwoerter_der_pdf_ohne_die_automatischen(qtbot, tmp_path, panel_ohne_threads):
    DetailPanel = panel_ohne_threads

    sw.quelle_setzen(lambda haeufigste=None: ["Haus", "Steuer", "Steuer/Werbungskosten"])
    pdf = h.pdf_mit_text(tmp_path / "Bürostuhl.pdf", ["Rechnung Buerostuhl"])
    assert write_metadata(pdf, PDFMetadata(keywords="rechnung", schlagwoerter="Steuer/Werbungskosten",
                                           steuerjahr="2026"))
    panel = DetailPanel()
    qtbot.addWidget(panel)
    panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="Rechnung Buerostuhl", keywords=["rechnung"])
    panel._on_pdf_metadata_read(pdf, read_metadata(pdf))
    assert panel._metadata_source in ("pdf", "pdf_partial")

    feld = panel._metadata_inputs["schlagwoerter"]
    assert isinstance(feld, SchlagwortFeld)
    assert feld.text() == "Steuer/Werbungskosten"
    assert feld.choices() == ["Haus", "Steuer", "Steuer/Werbungskosten"]
    assert panel.hat_gespeicherte_schlagwoerter()

    # Eingabe kommt in Normalform zurueck und gilt als ungespeicherte Aenderung
    feld.setText(" Steuer / Werbungskosten ;  Garten/Geräte ,")
    assert panel.get_metadata()["schlagwoerter"] == "Steuer/Werbungskosten, Garten/Geräte"
    assert panel.save_metadata_btn.isEnabled()

    # nach dem Speichern steht das neue Schlagwort samt Oberebene sofort in der Vorschlagsliste
    panel.mark_metadata_saved()
    assert feld.choices() == ["Garten", "Garten/Geräte", "Haus", "Steuer", "Steuer/Werbungskosten"]
    assert not panel.save_metadata_btn.isEnabled()

    feld.setText("")
    assert "schlagwoerter" not in panel.get_metadata()


def test_ki_schlagwoerter_kommen_zu_den_eigenen_dazu(qtbot, tmp_path, panel_ohne_threads):
    from types import SimpleNamespace

    DetailPanel = panel_ohne_threads
    pdf = h.pdf_mit_text(tmp_path / "a.pdf", ["Rechnung"])
    panel = DetailPanel()
    qtbot.addWidget(panel)
    panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="Rechnung", keywords=["rechnung"])
    panel._metadata_inputs["schlagwoerter"].setText("Haus")
    ki = SimpleNamespace(filename="2026-01-05_Rechnung.pdf", source="llm",
                         metadata={"subject": "Rechnung", "schlagwoerter": "Steuer/Werbungskosten, Haus"})
    panel._on_llm_metadata_ready(pdf, [ki], "")
    assert panel._metadata_inputs["schlagwoerter"].text() == "Haus, Steuer/Werbungskosten"


# --------------------------------------------------------------------------- Suche und Hauptfenster

@pytest.fixture
def index_konfig(tmp_path):
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    daten = {
        "stuhl.pdf": PDFMetadata(keywords="rechnung", schlagwoerter="Steuer/Werbungskosten", steuerjahr="2026"),
        "spende.pdf": PDFMetadata(keywords="steuer", schlagwoerter="Steuer/Sonderausgaben", steuerjahr="2026"),
        "fahrt.pdf": PDFMetadata(schlagwoerter="Steuer/Werbungskosten", steuerjahr="2025"),
    }
    for name, meta in daten.items():
        assert write_metadata(h.pdf_mit_text(ablage / name, [f"Dokument {name}"]), meta)
    h.pdf_mit_text(ablage / "ohne.pdf", ["Dokument ohne Schlagwort"])
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], prioritaet=[str(ablage)])
    assert Indexer(konfig, synchron=True).lauf() == 0
    return konfig


def _texte(combo) -> list[str]:
    return [combo.itemText(i) for i in range(combo.count())]


def test_reiter_suche_filter_schlagwort(qtbot, tmp_path, index_konfig):
    cfg = Config(config_path=tmp_path / "config.json")
    cfg.set_search_config(index_konfig)
    view = SearchView(cfg)
    qtbot.addWidget(view)
    try:
        with qtbot.waitSignal(view.status_aktualisiert, timeout=10000):
            view.refresh_status()
        combo = view.meta_combos["schlagwort"]
        assert _texte(combo) == ["Alle", "Steuer", "Steuer/Sonderausgaben", "Steuer/Werbungskosten"]

        with qtbot.waitSignal(view.suche_fertig, timeout=15000):
            combo.setCurrentIndex(combo.findData("Steuer"))
        assert sorted(k.dok["name"] for k in view.karten()) == ["fahrt.pdf", "spende.pdf", "stuhl.pdf"]

        # "alle Werbungskosten 2026"
        with qtbot.waitSignal(view.suche_fertig, timeout=15000):
            view.suchen("", schlagwort="Steuer/Werbungskosten", steuerjahr="2026")
        assert [k.dok["name"] for k in view.karten()] == ["stuhl.pdf"]
        assert view._filter_argumente()["schlagwort"] == "Steuer/Werbungskosten"

        view.leeren()
        assert combo.currentIndex() == 0 and view.karten() == []
    finally:
        view.shutdown()


@pytest.fixture
def hauptfenster(qtbot, tmp_path, monkeypatch, index_konfig):
    """MainWindow mit frischen Singletons (wie test_search_view_metadaten_gui) und eingerichteter Suche."""
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
    meldungen.konfigurieren(lambda: Suchindex(index_konfig))
    yield win
    meldungen.warten(10.0)
    meldungen.konfigurieren(None)
    win.close()
    from PyQt6 import sip
    sip.delete(win)


def test_filterleiste_schlagwort_wirkt_im_reiter_suche(qtbot, hauptfenster):
    win = hauptfenster
    win.filter_toggle_btn.setChecked(True)
    assert _texte(win.filter_schlagwort) == ["Alle", "Steuer", "Steuer/Sonderausgaben", "Steuer/Werbungskosten"]
    assert not win._has_active_filters()

    win.filter_steuerjahr.blockSignals(True)
    win.filter_steuerjahr.setCurrentText("2026")
    win.filter_steuerjahr.blockSignals(False)
    with qtbot.waitSignal(win.search_view.suche_fertig, timeout=15000):
        win.filter_schlagwort.setCurrentText("Steuer")
    assert win._has_active_filters()
    assert win.center_tabs.currentWidget() is win.search_view
    assert sorted(k.dok["name"] for k in win.search_view.karten()) == ["spende.pdf", "stuhl.pdf"]
    assert win.search_view.meta_combos["schlagwort"].currentData() == "Steuer"

    win._reset_filters()
    assert win.filter_schlagwort.currentIndex() == 0 and not win._has_active_filters()
    assert win.search_view.meta_combos["schlagwort"].currentIndex() == 0


def test_metadaten_speichern_schreibt_und_entfernt_schlagwoerter(qtbot, hauptfenster, tmp_path, monkeypatch):
    win = hauptfenster
    # kein Hintergrund-Leser, keine Vorschau: sie hielten die Datei offen, waehrend der Test in sie schreibt
    monkeypatch.setattr(type(win.detail_panel), "_start_metadata_reader", lambda self, pfad: None)
    monkeypatch.setattr(type(win.detail_panel), "_vorschau_laden", lambda self, pfad: None)
    # die Vorschlagsliste des Panels und die Auswahl der KI kommen aus dem Suchindex
    assert sw.benutzte() == ["Steuer", "Steuer/Sonderausgaben", "Steuer/Werbungskosten"]

    pdf = tmp_path / "Ablage" / "ohne.pdf"
    win.detail_panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="Dokument", keywords=["rechnung"])
    win.selected_pdf_keywords = ["rechnung"]
    feld = win.detail_panel._metadata_inputs["schlagwoerter"]
    feld.setText("Steuer/Werbungskosten, Büro")
    win._on_save_metadata_in_place()
    gelesen = read_metadata(pdf)
    assert gelesen.keywords == "rechnung, Steuer/Werbungskosten, Büro"
    assert gelesen.schlagwoerter == "Steuer/Werbungskosten, Büro"
    assert meldungen.warten(10.0)
    assert win.db.suchindex.dokument_nach_pfad(str(pdf))["schlagwoerter"] == "rechnung, Steuer/Werbungskosten, Büro"
    assert "Büro" in win.db.suchindex.schlagwoerter()

    # ein anderer Schreibweg ohne das Feld (z. B. Umbenennen-Dialog) laesst die Schlagwoerter stehen
    win._write_pdf_metadata(pdf, pdf.name, ["rechnung"], {"korrespondent": "Möbelhaus Muster"})
    assert read_metadata(pdf).schlagwoerter == "Steuer/Werbungskosten, Büro"

    # Feld leeren und speichern: Schlagwoerter weg, die Stichwoerter der Analyse bleiben
    feld.setText("")
    win._on_save_metadata_in_place()
    gelesen = read_metadata(pdf)
    assert gelesen.keywords == "rechnung" and gelesen.schlagwoerter is None
    assert meldungen.warten(10.0)
    assert win.db.suchindex.dokument_nach_pfad(str(pdf))["schlagwoerter"] == "rechnung"

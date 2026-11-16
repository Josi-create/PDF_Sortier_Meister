"""Notiz zu einem Dokument (Issue #298): Freitextfeld im Detail-Panel, gespeichert in der PDF,
aufgenommen in den Suchindex (Reiter „Suche“, Chat).

Alle Dokumente und Notizen sind erfunden.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QPlainTextEdit

from src.core.pdf_metadata import PDFMetadata, read_metadata, write_metadata
from src.search import db
from src.search.indexer import Indexer
from src.search.meldungen import meldungen
from src.search.suchindex import Suchindex
from tests import helfer_suche as h

NOTIZ = "Kopie ans Finanzamt am 12.3. geschickt.\nOriginal beim Steuerberater Max Mustermann (Bürozeit)."


# --------------------------------------------------------------------------- PDF

def test_notiz_wird_in_der_pdf_gespeichert_bleibt_und_laesst_sich_entfernen(tmp_path):
    pdf = h.pdf_mit_text(tmp_path / "Ärger mit Ölheizung.pdf", ["Rechnung Heizung"])
    assert write_metadata(pdf, PDFMetadata(korrespondent="Muster GmbH", notiz=NOTIZ))
    gelesen = read_metadata(pdf)
    assert gelesen.notiz == NOTIZ.strip() and gelesen.korrespondent == "Muster GmbH"

    # ein anderer Schreibweg ohne Notiz laesst sie stehen
    assert write_metadata(pdf, PDFMetadata(steuerjahr="2026"))
    assert read_metadata(pdf).notiz == NOTIZ.strip()

    # "" entfernt sie, die uebrigen Felder bleiben
    assert write_metadata(pdf, PDFMetadata(notiz=""))
    gelesen = read_metadata(pdf)
    assert gelesen.notiz is None and gelesen.korrespondent == "Muster GmbH" and gelesen.steuerjahr == "2026"


def test_notiz_gibt_es_nur_in_pdfs(tmp_path):
    datei = tmp_path / "brief.docx"
    datei.write_bytes(b"kein PDF")
    assert write_metadata(datei, PDFMetadata(notiz="egal")) is False


# --------------------------------------------------------------------------- Suchindex

def test_indexlauf_liest_die_notiz_und_die_suche_findet_sie(tmp_path):
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    pdf = h.pdf_mit_text(ablage / "bescheid.pdf", ["Bescheid ueber Grundsteuer"])
    assert write_metadata(pdf, PDFMetadata(notiz=NOTIZ))
    h.pdf_mit_text(ablage / "anderes.pdf", ["Bescheid ohne Notiz"])
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], prioritaet=[str(ablage)])
    assert Indexer(konfig, synchron=True).lauf() == 0

    con = db.verbinde(konfig.db_datei, nur_lesen=True)
    try:
        erg = db.suche(con, "Steuerberater")
        assert erg["gesamt"] == 1
        treffer = erg["treffer"][0]
        assert treffer["name"] == "bescheid.pdf" and treffer["im_metadaten"]
        assert treffer["notiz"] == NOTIZ.strip()
        assert db.suche(con, "Burozeit")["gesamt"] == 1  # Umlaute egal wie im uebrigen Index
    finally:
        con.close()


def test_bestehender_index_bekommt_die_notiz_ohne_neuaufbau(tmp_path):
    """Ein Index aus v0.30 (Metadaten-Index ohne Spalte notiz) wird in-place ergaenzt."""
    pfad = tmp_path / "suche.db"
    dok_id = h.v1_datenbank(pfad)
    con = db.verbinde(pfad)
    try:
        db.ergaenze_schema(con)
        # Stand vor Issue #298 nachbauen: Metadaten-Index und Trigger ohne notiz, Spalte fehlt
        alt = "korrespondent, kategorie, zusammenfassung, schlagwoerter"
        alt_neu = ", ".join(f"coalesce(new.{f}, '')" for f in alt.split(", "))
        alt_alt = ", ".join(f"coalesce(old.{f}, '')" for f in alt.split(", "))
        con.executescript("DROP TRIGGER meta_ai; DROP TRIGGER meta_ad; DROP TRIGGER meta_au; "
                          "DROP TABLE metadaten_fts;")
        con.execute("ALTER TABLE dokumente DROP COLUMN notiz")
        con.executescript(db.SCHEMA_V2.replace(db._META_FTS_NEU, alt_neu).replace(db._META_FTS_ALT, alt_alt)
                          .replace(db._META_FTS, alt))
        con.execute("INSERT INTO metadaten_fts(metadaten_fts) VALUES ('rebuild')")
        con.execute("UPDATE dokumente SET korrespondent = 'Stadtwerke Musterstadt', metadaten_quelle = 'pdfsm' "
                    "WHERE id = ?", (dok_id,))
        con.commit()
        assert db.schema_stand(con) == 1
        assert db.suche(con, "Stadtwerke")["gesamt"] == 1

        assert db.ergaenze_schema(con) is True
        assert db.schema_stand(con) == 2
        assert db.ergaenze_schema(con) is False
        # bisherige Metadaten weiter auffindbar, die Notiz ebenso
        assert db.suche(con, "Stadtwerke")["gesamt"] == 1
        assert db.metadaten_setzen(con, dok_id, {"notiz": "Rückruf vereinbart"})
        con.commit()
        assert db.suche(con, "Rückruf")["gesamt"] == 1
        # Notiz entfernen: auch aus dem Metadaten-Index
        assert db.metadaten_setzen(con, dok_id, {"korrespondent": "Stadtwerke Musterstadt", "notiz": None})
        con.commit()
        assert db.suche(con, "Rückruf")["gesamt"] == 0
        assert db.suche(con, "Stadtwerke")["gesamt"] == 1
    finally:
        con.close()


# --------------------------------------------------------------------------- Detail-Panel

@pytest.fixture
def panel_ohne_threads(monkeypatch):
    from src.gui.detail_panel import DetailPanel

    monkeypatch.setattr(DetailPanel, "_vorschau_laden", lambda self, pfad: None)
    monkeypatch.setattr(DetailPanel, "_start_metadata_reader", lambda self, pfad: None)
    return DetailPanel


def test_panel_zeigt_die_notiz_der_pdf(qtbot, tmp_path, panel_ohne_threads):
    DetailPanel = panel_ohne_threads
    pdf = h.pdf_mit_text(tmp_path / "a.pdf", ["Rechnung"])
    assert write_metadata(pdf, PDFMetadata(notiz=NOTIZ))
    panel = DetailPanel()
    qtbot.addWidget(panel)
    panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="Rechnung", keywords=None)
    feld = panel._metadata_inputs["notiz"]
    assert isinstance(feld, QPlainTextEdit) and feld.toPlainText() == ""
    panel._on_pdf_metadata_read(pdf, read_metadata(pdf))

    assert feld.toPlainText() == NOTIZ.strip()
    assert panel.hat_gespeicherte_notiz()
    assert panel._metadata_source == "pdf" and not panel.save_metadata_btn.isEnabled()

    feld.setPlainText("  Neue Notiz  ")
    assert panel.get_metadata()["notiz"] == "Neue Notiz"
    assert panel.save_metadata_btn.isEnabled()
    feld.setPlainText("")
    assert "notiz" not in panel.get_metadata()

    # Die Notiz gehoert nicht in Dateinamen-Vorschlaege oder zum naechsten Dokument
    andere = h.pdf_mit_text(tmp_path / "b.pdf", ["Brief"])
    feld.setPlainText("nur fuer a.pdf")
    panel.set_pdf(pdf_path=andere, suggestions=[], extracted_text="Brief", keywords=None)
    assert feld.toPlainText() == ""


# --------------------------------------------------------------------------- Hauptfenster

@pytest.fixture
def hauptfenster(qtbot, tmp_path, monkeypatch):
    from src.core import pdf_cache as pc_mod
    from src.ml import classifier as cl_mod
    from src.ml import hybrid_classifier as hc_mod
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod
    from tests.conftest import patch_singletons

    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    h.pdf_mit_text(ablage / "vertrag.pdf", ["Vertrag ueber Wartung"])
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], prioritaet=[str(ablage)])
    assert Indexer(konfig, synchron=True).lauf() == 0

    cfg = cfg_mod.Config(config_path=tmp_path / "config.json")
    cfg.set("persist_pdf_cache", False)
    cfg.set_search_config(konfig)
    database = db_mod.Database(db_path=str(tmp_path / "history.db"))
    monkeypatch.setattr(pc_mod.PDFCache, "_instance", None)
    patch_singletons(monkeypatch, {
        "get_config": lambda: cfg,
        "get_database": lambda: database,
        "get_classifier": cl_mod.PDFClassifier,
        "get_hybrid_classifier": hc_mod.HybridClassifier,
        "get_pdf_cache": pc_mod.PDFCache,
    })
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    from src.gui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.QMainWindow, "showMaximized", lambda self: None)
    monkeypatch.setattr(mw_mod.QMainWindow, "show", lambda self: None)
    win = mw_mod.MainWindow()
    meldungen.konfigurieren(lambda: Suchindex(konfig))
    yield win
    meldungen.warten(10.0)
    meldungen.konfigurieren(None)
    win.close()
    from PyQt6 import sip
    sip.delete(win)


def test_metadaten_speichern_schreibt_und_entfernt_die_notiz(qtbot, hauptfenster, tmp_path, monkeypatch):
    win = hauptfenster
    monkeypatch.setattr(type(win.detail_panel), "_start_metadata_reader", lambda self, pfad: None)
    monkeypatch.setattr(type(win.detail_panel), "_vorschau_laden", lambda self, pfad: None)

    pdf = tmp_path / "Ablage" / "vertrag.pdf"
    win.detail_panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="Vertrag", keywords=["vertrag"])
    win.selected_pdf_keywords = ["vertrag"]
    feld = win.detail_panel._metadata_inputs["notiz"]
    feld.setPlainText(NOTIZ)
    win._on_save_metadata_in_place()
    assert read_metadata(pdf).notiz == NOTIZ.strip()
    assert meldungen.warten(10.0)
    assert win.db.suchindex.dokument_nach_pfad(str(pdf))["notiz"] == NOTIZ.strip()
    assert not win.detail_panel.save_metadata_btn.isEnabled()

    # ein anderer Schreibweg ohne das Feld laesst die Notiz stehen
    win._write_pdf_metadata(pdf, pdf.name, ["vertrag"], {"korrespondent": "Wartungsdienst Muster"})
    assert read_metadata(pdf).notiz == NOTIZ.strip()

    # Feld leeren und speichern: Notiz weg, in der PDF und im Index
    feld.setPlainText("")
    win._on_save_metadata_in_place()
    assert read_metadata(pdf).notiz is None
    assert meldungen.warten(10.0)
    assert not win.db.suchindex.dokument_nach_pfad(str(pdf))["notiz"]


# --------------------------------------------------------------------------- Anzeige in Suche und Chat

def test_trefferkarte_und_chat_zeigen_die_notiz(qtbot):
    from src.gui.search_view import TrefferKarte
    from src.rag.werkzeuge import Werkzeugkasten

    dok = {"id": 1, "pfad": "C:/Ablage/vertrag.pdf", "name": "vertrag.pdf", "ordner": "C:/Ablage",
           "typ": "pdf", "format": "pdf", "textstatus": "text", "notiz": "Zeile eins\nZeile zwei",
           "im_metadaten": True, "stellen": []}
    karte = TrefferKarte(dok)
    qtbot.addWidget(karte)
    assert karte.notiz_label is not None and "Zeile eins Zeile zwei" in karte.notiz_label.text()
    ohne = TrefferKarte({**dok, "notiz": None})
    qtbot.addWidget(ohne)
    assert ohne.notiz_label is None

    zeile = Werkzeugkasten._treffer_zeile(3, {"filename": "vertrag.pdf", "file_path": "C:/Ablage/vertrag.pdf",
                                              "typ": "pdf", "notiz": "Original beim\nSteuerberater"})
    assert "Notiz: Original beim Steuerberater" in zeile
    assert "Notiz" not in Werkzeugkasten._treffer_zeile(3, {"filename": "x.pdf", "typ": "pdf"})

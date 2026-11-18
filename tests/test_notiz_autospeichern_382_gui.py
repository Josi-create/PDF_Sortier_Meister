"""Notiz speichert sich von selbst (Issue #382): beim Verlassen des Feldes oder des Dokuments.

Die uebrigen Metadaten-Felder bleiben ungespeichert, bis "Metadaten speichern" geklickt oder die Datei
verschoben wird; es gibt keine Rueckfrage beim Wechsel. Alle Dokumente und Notizen sind erfunden.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QFocusEvent
from PyQt6.QtWidgets import QApplication

from src.core.pdf_metadata import PDFMetadata, read_metadata, write_metadata
from src.search import db
from src.search.meldungen import meldungen
from tests import helfer_suche as h
from tests.test_notiz_298_gui import hauptfenster, panel_ohne_threads  # noqa: F401 - Fixtures

NOTIZ = "Rückruf bei Max Mustermann vereinbart (Ärger mit Ölrechnung)."


@pytest.fixture(autouse=True)
def eigene_konfiguration(monkeypatch, tmp_path):
    """Panel-Tests nie mit Konfiguration und Datenbank des Nutzers."""
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod
    from tests.conftest import patch_singletons

    cfg = cfg_mod.Config(config_path=tmp_path / "config-panel.json")
    database = db_mod.Database(db_path=str(tmp_path / "history-panel.db"))
    patch_singletons(monkeypatch, {"get_config": lambda: cfg, "get_database": lambda: database})


def _feld_verlassen(feld, grund=Qt.FocusReason.OtherFocusReason):
    QApplication.sendEvent(feld, QFocusEvent(QEvent.Type.FocusOut, grund))


# --------------------------------------------------------------------------- Detail-Panel

def test_panel_meldet_geaenderte_notiz_beim_wechsel_und_beim_verlassen(qtbot, tmp_path, panel_ohne_threads):
    DetailPanel = panel_ohne_threads
    a = h.pdf_mit_text(tmp_path / "Ärger a.pdf", ["Rechnung"])
    b = h.pdf_mit_text(tmp_path / "b.pdf", ["Brief"])
    panel = DetailPanel()
    qtbot.addWidget(panel)
    gemeldet = []
    panel.notiz_speichern_requested.connect(lambda pfad, text: gemeldet.append((pfad, text)))
    feld = panel._metadata_inputs["notiz"]

    # unveraendert: nichts melden
    panel.set_pdf(pdf_path=a, suggestions=[], extracted_text="Rechnung", keywords=None)
    _feld_verlassen(feld)
    panel.set_pdf(pdf_path=b, suggestions=[], extracted_text="Brief", keywords=None)
    assert gemeldet == []

    # Feld verlassen speichert; das Kontextmenue des Feldes selbst nicht
    feld.setPlainText(f"  {NOTIZ}  ")
    _feld_verlassen(feld, Qt.FocusReason.PopupFocusReason)
    assert gemeldet == []
    _feld_verlassen(feld)
    assert gemeldet == [(b, NOTIZ)]

    # Dokumentwechsel ohne Feld zu verlassen: Notiz geht an das bisherige Dokument
    gemeldet.clear()
    feld.setPlainText("nur fuer b.pdf")
    panel.set_pdf(pdf_path=a, suggestions=[], extracted_text="Rechnung", keywords=None)
    assert gemeldet == [(b, "nur fuer b.pdf")]
    assert feld.toPlainText() == ""

    # Panel leeren (z. B. letzte Datei abgelegt) ebenso
    gemeldet.clear()
    feld.setPlainText("fuer a.pdf")
    panel.clear()
    assert gemeldet == [(a, "fuer a.pdf")]


def test_gespeicherte_notiz_gilt_als_gespeichert_uebrige_felder_nicht(qtbot, tmp_path, panel_ohne_threads):
    DetailPanel = panel_ohne_threads
    a = h.pdf_mit_text(tmp_path / "a.pdf", ["Rechnung"])
    assert write_metadata(a, PDFMetadata(korrespondent="Muster GmbH"))
    panel = DetailPanel()
    qtbot.addWidget(panel)
    panel.set_pdf(pdf_path=a, suggestions=[], extracted_text="Rechnung", keywords=None)
    panel._on_pdf_metadata_read(a, read_metadata(a))
    assert panel._metadata_source == "pdf"

    # nur die Notiz geaendert und gespeichert: alles wieder "gespeichert"
    panel._metadata_inputs["notiz"].setPlainText(NOTIZ)
    assert panel._metadata_source == "user"
    panel.notiz_gespeichert(a, NOTIZ)
    assert panel._metadata_source == "pdf" and not panel.save_metadata_btn.isEnabled()
    assert panel.hat_gespeicherte_notiz()

    # Korrespondent geaendert: bleibt ungespeichert, auch wenn die Notiz gespeichert wird
    panel._metadata_inputs["korrespondent"].setText("Andere GmbH")
    panel._metadata_inputs["notiz"].setPlainText("")
    panel.notiz_gespeichert(a, "")
    assert not panel.hat_gespeicherte_notiz()
    assert panel._metadata_source == "user" and panel.save_metadata_btn.isEnabled()

    # Meldung fuer ein anderes Dokument aendert nichts
    panel.notiz_gespeichert(tmp_path / "anderes.pdf", "egal")
    assert not panel.hat_gespeicherte_notiz()


# --------------------------------------------------------------------------- Hauptfenster

def test_dokumentwechsel_speichert_nur_die_notiz_in_pdf_und_index(qtbot, hauptfenster, tmp_path, monkeypatch):
    win = hauptfenster
    monkeypatch.setattr(type(win.detail_panel), "_start_metadata_reader", lambda self, pfad: None)
    monkeypatch.setattr(type(win.detail_panel), "_vorschau_laden", lambda self, pfad: None)
    pdf = tmp_path / "Ablage" / "vertrag.pdf"
    andere = h.pdf_mit_text(tmp_path / "Ablage" / "brief.pdf", ["Brief"])

    win.detail_panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="Vertrag", keywords=["vertrag"])
    win.detail_panel._metadata_inputs["korrespondent"].setText("Wartungsdienst Muster")
    win.detail_panel._metadata_inputs["notiz"].setPlainText(NOTIZ)
    win.detail_panel.set_pdf(pdf_path=andere, suggestions=[], extracted_text="Brief", keywords=None)

    gelesen = read_metadata(pdf)
    assert gelesen.notiz == NOTIZ
    assert gelesen.korrespondent is None  # die uebrigen Felder nur auf Klick oder beim Verschieben
    assert meldungen.warten(10.0)
    assert win.db.suchindex.dokument_nach_pfad(str(pdf))["notiz"] == NOTIZ

    # zurueck, Notiz leeren, Feld verlassen: aus PDF und Index entfernt
    win.detail_panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="Vertrag", keywords=["vertrag"])
    win.detail_panel._on_pdf_metadata_read(pdf, read_metadata(pdf))
    feld = win.detail_panel._metadata_inputs["notiz"]
    assert feld.toPlainText() == NOTIZ
    feld.setPlainText("")
    _feld_verlassen(feld)
    assert read_metadata(pdf).notiz is None
    assert meldungen.warten(10.0)
    assert not win.db.suchindex.dokument_nach_pfad(str(pdf))["notiz"]


def test_geleerte_notiz_wird_beim_ablegen_entfernt(qtbot, hauptfenster, tmp_path, monkeypatch):
    """Rest aus #364: Notiz leeren und per Klick verschieben entfernt die Notiz."""
    win = hauptfenster
    monkeypatch.setattr(type(win.detail_panel), "_start_metadata_reader", lambda self, pfad: None)
    monkeypatch.setattr(type(win.detail_panel), "_vorschau_laden", lambda self, pfad: None)
    pdf = tmp_path / "Ablage" / "vertrag.pdf"
    assert write_metadata(pdf, PDFMetadata(notiz=NOTIZ))
    win.detail_panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="Vertrag", keywords=None)
    win.detail_panel._on_pdf_metadata_read(pdf, read_metadata(pdf))
    win.detail_panel._metadata_inputs["notiz"].setPlainText("")

    ziel = tmp_path / "Ziel"
    ziel.mkdir()
    namen = win._ablage_namen(pdf, ziel, "Ziel")
    assert namen.metadata.get("notiz") == ""

    # Notiz steht noch im Feld: sie geht normal mit
    win.detail_panel._metadata_inputs["notiz"].setPlainText("bleibt")
    assert win._ablage_namen(pdf, ziel, "Ziel").metadata["notiz"] == "bleibt"


# --------------------------------------------------------------------------- Suchindex

def test_index_entfernt_eine_geleerte_notiz_auch_allein(tmp_path):
    pfad = tmp_path / "suche.db"
    dok_id = h.v1_datenbank(pfad)
    con = db.verbinde(pfad)
    try:
        db.ergaenze_schema(con)
        assert db.metadaten_setzen(con, dok_id, {"notiz": "Original beim Steuerberater"})
        con.commit()
        assert db.suche(con, "Steuerberater")["gesamt"] == 1
        # None heisst weiter "nichts ueberschreiben", "" entfernt die Notiz
        assert db.metadaten_setzen(con, dok_id, {"notiz": None}) is False
        assert db.suche(con, "Steuerberater")["gesamt"] == 1
        assert db.metadaten_setzen(con, dok_id, {"notiz": ""})
        con.commit()
        assert db.suche(con, "Steuerberater")["gesamt"] == 0
    finally:
        con.close()

"""Oberflaeche der Textebene (Phase 5b der PDFsuche-Integration).

Geprueft werden: die Rueckfrage mit Schaetzung, bevor in den Einstellungen die
Stufe „alle“ gilt (Nein stellt die alte Stufe wieder her), „unbegrenzt“ bei
0 Tagen Aufbewahrung, das Protokoll der geaenderten PDFs mit Rueckgaengig
(auch erzwungen nach einer spaeteren Aenderung) und „Anhalten“ im Reiter Suche.
Alle Dateien entstehen synthetisch in ``tmp_path``; Tesseract ist durch
``helfer_suche.fake_tesseract`` ersetzt, Meldungsfenster sind gepatcht.
"""
from __future__ import annotations

import os

import pymupdf
import pytest
from PyQt6.QtWidgets import QMessageBox

from src.gui.search_view import SearchView
from src.gui.textebene_dialog import TextebeneProtokollDialog, stand_text
from src.search import extract
from src.search import indexer as indexer_modul
from src.search.indexer import Indexer, anhalten_datei
from src.search.suchindex import Suchindex
from src.search.textebene import MELDUNG_GEAENDERT
from src.utils.config import Config
from tests import helfer_suche as h
from tests.test_settings_search_tab_gui import (  # noqa: F401 (autouse-Fixture)
    _dialog,
    plattform_neutral,
)

JA, NEIN = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No


@pytest.fixture
def ebene(tmp_path, monkeypatch):
    """Index mit einem Scan im Eingang (bekommt die Textebene) und einem im Archiv (Altbestand)."""
    h.fake_tesseract(monkeypatch, "Rechnung Nummer 4711 Gesamtbetrag")
    ablage = tmp_path / "Ablage"
    for ordner in ("1A", "Archiv"):
        (ablage / ordner).mkdir(parents=True)
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], prioritaet=[str(ablage / "1A")], ocr_aktiv=True,
                           ocr_tesseract="tesseract-fake", textebene="neue_scans")
    scan = h.scan_pdf(ablage / "1A" / "scan.pdf", ["Darlehen"])
    vorher = scan.read_bytes()
    h.scan_pdf(ablage / "Archiv" / "alt.pdf", ["Altbestand"])
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert scan.read_bytes() != vorher
    return konfig, scan, vorher


def _fragen(monkeypatch, antworten: list) -> list:
    """``QMessageBox.question`` beantwortet der Reihe nach aus ``antworten``; liefert (Titel, Text)."""
    gestellt = []

    def frage(parent, titel, text, *a, **kw):
        gestellt.append((titel, text))
        return antworten.pop(0) if antworten else NEIN

    monkeypatch.setattr(QMessageBox, "question", staticmethod(frage))
    return gestellt


def _meldungen(monkeypatch) -> list:
    gezeigt = []
    for art in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, art, staticmethod(
            lambda parent, titel, text, *a, art=art, **kw: gezeigt.append((art, text))))
    return gezeigt


def _ocr_schriften(pfad) -> int:
    with pymupdf.open(pfad) as d:
        return sum(1 for f in d[0].get_fonts() if extract.OCR_SCHRIFT in f[3])


# --------------------------------------------------------------------------- Einstellungen

def test_stufe_alle_erst_nach_rueckfrage_mit_schaetzung(qtbot, monkeypatch, tmp_path, ebene):
    konfig = ebene[0]
    monkeypatch.setattr("src.search.plattform.onedrive_ordner", lambda: [str(tmp_path / "Ablage" / "Archiv")])
    dlg, cfg = _dialog(qtbot, monkeypatch, tmp_path, suche=konfig.als_dict())
    combo, tage = dlg.search_textlayer_combo, dlg.search_textlayer_backup_days_spin
    assert combo.currentData() == "neue_scans"
    gestellt = _fragen(monkeypatch, [NEIN, JA])

    tage.setValue(0)
    assert tage.text() == "unbegrenzt"
    combo.setCurrentIndex(combo.findData("alle"))
    assert combo.currentData() == "neue_scans" and len(gestellt) == 1       # Nein: alte Stufe zurueck
    text = gestellt[0][1]
    assert "1 texterkannte PDFs mit 1 Seiten" in text and "in OneDrive" in text and "unbegrenzt" in text

    tage.setValue(14)
    combo.setCurrentIndex(combo.findData("alle"))
    assert combo.currentData() == "alle" and len(gestellt) == 2 and "nach 14 Tagen" in gestellt[1][1]
    combo.setCurrentIndex(combo.findData("aus"))
    assert len(gestellt) == 2                                                 # nur „alle“ fragt nach

    combo.setCurrentIndex(combo.findData("alle"))
    assert len(gestellt) == 3 and combo.currentData() == "aus"             # keine Antwort mehr: Nein
    combo.blockSignals(True)
    combo.setCurrentIndex(combo.findData("alle"))
    combo.blockSignals(False)
    dlg._save_settings()
    s = cfg.get_search_config()
    assert s.textebene == "alle" and s.textebene_sicherung_tage == 14
    assert s.textebene_sicherung_ordner == konfig.textebene_sicherung_ordner  # bleibt beim Speichern erhalten

    # Gespeicherte Stufe „alle“ laden fragt nicht noch einmal
    dlg2, _ = _dialog(qtbot, monkeypatch, tmp_path)
    assert dlg2.search_textlayer_combo.currentData() == "alle" and len(gestellt) == 3


def test_schaetzung_ohne_index_und_protokoll_knopf(qtbot, monkeypatch, tmp_path, ebene):
    konfig = ebene[0]
    leer = h.konfig_fuer(tmp_path / "leer")
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path, suche=leer.als_dict())
    gestellt = _fragen(monkeypatch, [])
    dlg.search_textlayer_combo.setCurrentIndex(dlg.search_textlayer_combo.findData("alle"))
    assert "keine texterkannten PDFs" in gestellt[0][1]

    geoeffnet = []
    monkeypatch.setattr(TextebeneProtokollDialog, "exec", lambda self: geoeffnet.append(self) or 0)
    dlg.search_textlayer_protocol_button.click()
    assert geoeffnet[-1].tabelle.rowCount() == 0 and geoeffnet[-1].leer_label.isVisibleTo(geoeffnet[-1])
    dlg.search_db_path_edit.setText(konfig.db_pfad)            # Datenbankpfad aus dem Formular gilt sofort
    dlg.search_textlayer_protocol_button.click()
    assert geoeffnet[-1].tabelle.rowCount() == 1


# --------------------------------------------------------------------------- Protokoll

def test_protokoll_rueckgaengig(qtbot, monkeypatch, ebene):
    konfig, scan, vorher = ebene
    gezeigt = _meldungen(monkeypatch)
    dlg = TextebeneProtokollDialog(konfig)
    qtbot.addWidget(dlg)
    assert dlg.tabelle.rowCount() == 1 and not dlg.leer_label.isVisibleTo(dlg)
    assert os.path.samefile(dlg.tabelle.item(0, 1).text(), scan)
    assert dlg.tabelle.item(0, 3).text() == "Sicherung vorhanden"
    assert not dlg.rueckgaengig_button.isEnabled()
    dlg.tabelle.selectRow(0)
    assert dlg.rueckgaengig_button.isEnabled() and dlg.zeigen_button.isEnabled()

    gestellt = _fragen(monkeypatch, [NEIN])
    dlg.rueckgaengig_button.click()
    assert len(gestellt) == 1 and dlg._thread is None and _ocr_schriften(scan) == 1

    _fragen(monkeypatch, [JA])
    with qtbot.waitSignal(dlg.rueckgaengig_fertig, timeout=30000) as signal:
        dlg.rueckgaengig_button.click()
    assert signal.args[0] is True and gezeigt == [("information", signal.args[1])]
    assert scan.read_bytes() == vorher
    assert dlg.tabelle.item(0, 3).text() == "rückgängig gemacht" and not dlg.rueckgaengig_button.isEnabled()
    dlg.accept()


def test_protokoll_nach_spaeterer_aenderung_nur_nach_zweiter_rueckfrage(qtbot, monkeypatch, ebene):
    konfig, scan, _ = ebene
    with pymupdf.open(scan) as d:
        d.set_metadata({"title": "Später geändert"})
        d.saveIncr()
    gezeigt = _meldungen(monkeypatch)
    dlg = TextebeneProtokollDialog(konfig)
    qtbot.addWidget(dlg)
    dlg.tabelle.selectRow(0)

    gestellt = _fragen(monkeypatch, [JA, NEIN])
    with qtbot.waitSignal(dlg.rueckgaengig_fertig, timeout=30000) as signal:
        dlg.rueckgaengig_button.click()
    assert signal.args == [False, MELDUNG_GEAENDERT] and _ocr_schriften(scan) == 1
    assert [t for t, _ in gestellt] == ["Rückgängig machen", "Datei wurde seither geändert"] and gezeigt == []
    assert dlg.rueckgaengig_button.isEnabled()

    gestellt = _fragen(monkeypatch, [JA, JA])
    with qtbot.waitSignal(dlg.rueckgaengig_fertig, timeout=30000) as signal:
        dlg.rueckgaengig_button.click()
    assert signal.args[0] is True and len(gestellt) == 2 and _ocr_schriften(scan) == 0
    assert dlg.tabelle.item(0, 3).text() == "rückgängig gemacht"
    dlg.accept()


def test_stand_text():
    assert stand_text({"status": "rueckgaengig", "sicherung": "x"}) == "rückgängig gemacht"
    assert stand_text({"status": "geschrieben", "sicherung": "x"}) == "Sicherung vorhanden"
    assert stand_text({"status": "geschrieben", "sicherung": None}) == "Sicherung abgelaufen"


# --------------------------------------------------------------------------- Reiter Suche

def test_anhalten_im_reiter_suche(qtbot, monkeypatch, tmp_path, ebene):
    konfig = ebene[0]
    cfg = Config(config_path=tmp_path / "config.json")
    cfg.set_search_config(konfig)
    v = SearchView(cfg)
    qtbot.addWidget(v)
    try:
        with qtbot.waitSignal(v.status_aktualisiert, timeout=10000):
            v.refresh_status()
        assert "Textebene in 1 PDFs" in v.status_label.text() and not v.anhalten_button.isVisibleTo(v)

        monkeypatch.setattr(Suchindex, "laeuft_gerade", lambda self: True)
        monkeypatch.setattr(indexer_modul, "laeuft_gerade", lambda k: True)
        with qtbot.waitSignal(v.status_aktualisiert, timeout=10000):
            v.refresh_status()
        assert v.anhalten_button.isVisibleTo(v) and v.anhalten_button.isEnabled()
        v.anhalten_button.click()
        assert anhalten_datei(konfig).exists() and not v.anhalten_button.isEnabled()
        assert "hält an" in v.status_label.text()

        monkeypatch.setattr(Suchindex, "laeuft_gerade", lambda self: False)
        monkeypatch.setattr(indexer_modul, "laeuft_gerade", lambda k: False)
        with qtbot.waitSignal(v.status_aktualisiert, timeout=10000):
            v._lauf_anhalten()                      # kein Lauf mehr: nur den Stand neu lesen
        assert not v.anhalten_button.isVisibleTo(v) and v.anhalten_button.isEnabled()
    finally:
        v.shutdown()

"""Gespeicherte Suchen im Reiter „Suche“ (Issue #281): Suchtext und Filter unter einem Namen
merken, per Ausklappliste wieder aufrufen, umbenennen und löschen. Gespeichert wird in der
Konfiguration des Programms (``gespeicherte_suchen``)."""
from __future__ import annotations

import json

import pytest
from PyQt6.QtWidgets import QInputDialog, QMessageBox

from src.core.pdf_metadata import PDFMetadata, write_metadata
from src.gui.search_view import SearchView
from src.search.indexer import Indexer
from src.utils.config import Config
from tests import helfer_suche as h


@pytest.fixture
def index_konfig(tmp_path):
    ablage = tmp_path / "Ablage Büro"
    ablage.mkdir()
    a = h.pdf_mit_text(ablage / "telefon.pdf", ["Rechnung Telefon Festnetz"])
    write_metadata(a, PDFMetadata(subject="Rechnung", korrespondent="Telefon AG", steuerjahr="2024",
                                  betrag_brutto="59.99"))
    b = h.pdf_mit_text(ablage / "strom.pdf", ["Rechnung Strom Abschlag"])
    write_metadata(b, PDFMetadata(subject="Rechnung", korrespondent="Stromwerk", steuerjahr="2023",
                                  betrag_brutto="142.30"))
    h.pdf_mit_text(ablage / "notiz.pdf", ["Notiz ohne Metadaten"])
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], prioritaet=[str(ablage)])
    assert Indexer(konfig, synchron=True).lauf() == 0
    return konfig


@pytest.fixture
def cfg(tmp_path, index_konfig):
    c = Config(config_path=tmp_path / "config.json")
    c.set_search_config(index_konfig)
    return c


@pytest.fixture
def view(qtbot, cfg):
    v = SearchView(cfg)
    qtbot.addWidget(v)
    yield v
    v.shutdown()


@pytest.fixture
def dialoge(monkeypatch):
    """Namensabfrage und Rückfragen ohne Fenster: ``antworten["name"]`` ist der eingegebene Name."""
    antworten = {"name": "", "ok": True, "frage": QMessageBox.StandardButton.Yes, "fragen": [], "hinweise": []}

    def get_text(_parent, _titel, _label, text="", **_kw):
        antworten["vorgabe"] = text
        return antworten["name"], antworten["ok"]

    def frage(_parent, _titel, text, *_a, **_kw):
        antworten["fragen"].append(text)
        return antworten["frage"]

    def hinweis(_parent, _titel, text, *_a, **_kw):
        antworten["hinweise"].append(text)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(get_text))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(frage))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(hinweis))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(hinweis))
    return antworten


def _eintraege(view):
    return [view.gespeichert_combo.itemText(i) for i in range(view.gespeichert_combo.count())]


def _waehlen(qtbot, view, name):
    """Eintrag so wählen wie mit der Maus (``activated``)."""
    i = view.gespeichert_combo.findText(name)
    assert i > 0
    with qtbot.waitSignal(view.suche_fertig, timeout=15000):
        view.gespeichert_combo.setCurrentIndex(i)
        view.gespeichert_combo.activated.emit(i)
    return view.karten()


def test_speichern_und_wieder_aufrufen_setzt_alle_filter(qtbot, view, cfg, dialoge):
    assert _eintraege(view) == ["Gespeicherte Suchen …"]
    assert not view.gespeichert_menue_button.isEnabled()

    view.suchzustand_setzen({"text": "Rechnung", "typ": "pdf", "sortierung": "neu", "ordner": "Büro",
                             "von": "2000-01-01", "bis": "2099-12-31", "steuerjahr": "2023",
                             "kategorie": "Rechnung", "korrespondent": "Stromwerk",
                             "betrag_von": 100, "betrag_bis": 200})
    dialoge["name"] = "  Nebenkosten 2023 "
    view.speichern_button.click()

    gespeichert = cfg.get("gespeicherte_suchen")
    assert gespeichert == [{"name": "Nebenkosten 2023", "suche": {
        "sortierung": "neu", "typ": "pdf", "ordner": "Büro", "von": "2000-01-01", "bis": "2099-12-31",
        "steuerjahr": "2023", "kategorie": "Rechnung", "korrespondent": "Stromwerk",
        "betrag_von": 100.0, "betrag_bis": 200.0, "text": "Rechnung"}}]
    # steht in der Konfigurationsdatei (und damit im Backup), nicht im Index
    assert json.loads(cfg.config_path.read_text(encoding="utf-8"))["gespeicherte_suchen"] == gespeichert
    assert _eintraege(view) == ["Gespeicherte Suchen …", "Nebenkosten 2023"]
    assert view.gespeichert_combo.currentText() == "Nebenkosten 2023"
    assert view.gespeichert_menue_button.isEnabled()

    # „Suche leeren“ setzt auch die Auswahl zurück
    view.leeren()
    assert view.gespeichert_combo.currentIndex() == 0 and not view.search_edit.text()

    karten = _waehlen(qtbot, view, "Nebenkosten 2023")
    assert [k.dok["name"] for k in karten] == ["strom.pdf"]
    assert view.search_edit.text() == "Rechnung"
    assert view.typ_buttons["pdf"].isChecked()
    assert view.sort_combo.currentData() == "neu"
    assert view.ordner_edit.text() == "Büro"
    assert view.zeitraum_edit.grenzen() == ("2000-01-01", "2099-12-31")
    assert view.meta_combos["steuerjahr"].currentData() == "2023"
    assert view.meta_combos["kategorie"].currentData() == "Rechnung"
    assert view.meta_combos["korrespondent"].currentData() == "Stromwerk"
    assert view.meta_combos["schlagwort"].currentIndex() == 0
    assert view.betrag_von_spin.value() == 100 and view.betrag_bis_spin.value() == 200


def test_gespeicherte_suche_ersetzt_vorherige_filter_und_ueberlebt_neustart(qtbot, view, cfg, dialoge):
    view.suchzustand_setzen({"steuerjahr": "2024"})
    dialoge["name"] = "Steuer 2024"
    view.speichern_button.click()
    assert cfg.get("gespeicherte_suchen") == [{"name": "Steuer 2024",
                                               "suche": {"sortierung": "relevanz", "steuerjahr": "2024"}}]

    # andere Filter gesetzt: die gespeicherte Suche raeumt sie wieder ab
    view.suchzustand_setzen({"text": "Notiz", "typ": "office", "ordner": "woanders", "betrag_von": 5})
    karten = _waehlen(qtbot, view, "Steuer 2024")
    assert [k.dok["name"] for k in karten] == ["telefon.pdf"]
    assert view.search_edit.text() == "" and view.ordner_edit.text() == ""
    assert view.typ_buttons[""].isChecked() and view.betrag_von_spin.value() == 0

    # neues Fenster mit derselben Konfigurationsdatei: die Suche ist noch da
    neu = SearchView(Config(config_path=cfg.config_path))
    qtbot.addWidget(neu)
    try:
        assert _eintraege(neu) == ["Gespeicherte Suchen …", "Steuer 2024"]
        assert [k.dok["name"] for k in _waehlen(qtbot, neu, "Steuer 2024")] == ["telefon.pdf"]
    finally:
        neu.shutdown()


def test_leere_suche_wird_nicht_gespeichert_und_abbruch_aendert_nichts(view, cfg, dialoge):
    view.speichern_button.click()
    assert dialoge["hinweise"] == ["Es ist weder ein Suchtext noch ein Filter gesetzt."]
    assert cfg.get("gespeicherte_suchen") == []

    view.suchzustand_setzen({"text": "Rechnung"})
    dialoge.update(name="Rechnungen", ok=False)
    view.speichern_button.click()
    dialoge.update(name="   ", ok=True)
    view.speichern_button.click()
    assert cfg.get("gespeicherte_suchen") == []


def test_gleicher_name_fragt_vor_dem_ueberschreiben(view, cfg, dialoge):
    view.suchzustand_setzen({"text": "Rechnung"})
    dialoge["name"] = "Belege"
    view.speichern_button.click()

    view.suchzustand_setzen({"text": "Notiz"})
    dialoge.update(name="belege", frage=QMessageBox.StandardButton.No)
    view.speichern_button.click()
    assert dialoge["fragen"] == ["Es gibt schon eine gespeicherte Suche „Belege“. Überschreiben?"]
    assert [e["suche"]["text"] for e in cfg.get("gespeicherte_suchen")] == ["Rechnung"]

    dialoge["frage"] = QMessageBox.StandardButton.Yes
    view.speichern_button.click()
    assert cfg.get("gespeicherte_suchen") == [{"name": "belege", "suche": {"sortierung": "relevanz", "text": "Notiz"}}]
    assert _eintraege(view) == ["Gespeicherte Suchen …", "belege"]


def test_umbenennen_und_loeschen(view, cfg, dialoge):
    for name, text in (("Zeta", "Rechnung"), ("alpha", "Notiz")):
        view.suchzustand_setzen({"text": text})
        dialoge["name"] = name
        view.speichern_button.click()
    assert _eintraege(view) == ["Gespeicherte Suchen …", "alpha", "Zeta"]   # nach Namen sortiert
    assert view.gespeichert_combo.currentText() == "alpha"

    # Umbenennen: der alte Name ist vorbelegt; ein schon vergebener Name wird abgelehnt
    dialoge["name"] = "zeta"
    view.umbenennen_aktion.trigger()
    assert dialoge["vorgabe"] == "alpha"
    assert dialoge["hinweise"] == ["Es gibt schon eine gespeicherte Suche „zeta“."]
    assert _eintraege(view) == ["Gespeicherte Suchen …", "alpha", "Zeta"]

    dialoge["name"] = "Notizen"
    view.umbenennen_aktion.trigger()
    assert _eintraege(view) == ["Gespeicherte Suchen …", "Notizen", "Zeta"]
    assert view.gespeichert_combo.currentText() == "Notizen"
    assert {e["name"]: e["suche"]["text"] for e in cfg.get("gespeicherte_suchen")} == {
        "Notizen": "Notiz", "Zeta": "Rechnung"}

    # Löschen fragt nach; „Nein“ lässt alles stehen
    dialoge["frage"] = QMessageBox.StandardButton.No
    view.loeschen_aktion.trigger()
    assert len(cfg.get("gespeicherte_suchen")) == 2
    dialoge["frage"] = QMessageBox.StandardButton.Yes
    view.loeschen_aktion.trigger()
    assert [e["name"] for e in cfg.get("gespeicherte_suchen")] == ["Zeta"]
    assert _eintraege(view) == ["Gespeicherte Suchen …", "Zeta"]
    assert view.gespeichert_combo.currentIndex() == 0 and not view.gespeichert_menue_button.isEnabled()

    # ohne Auswahl tun Umbenennen und Löschen nichts
    view.umbenennen_aktion.trigger()
    view.loeschen_aktion.trigger()
    assert [e["name"] for e in cfg.get("gespeicherte_suchen")] == ["Zeta"]


def test_kaputte_eintraege_in_der_konfiguration_stoeren_nicht(qtbot, cfg):
    cfg.set("gespeicherte_suchen", [
        "kein Eintrag", {"name": "", "suche": {}}, {"name": "ohne Suche"},
        {"name": "Schräg", "suche": {"typ": "gibtsnicht", "von": "kein Datum", "betrag_von": "viel",
                                     "sortierung": "unbekannt", "kategorie": "Gibt es nicht mehr"}},
    ])
    v = SearchView(cfg)
    qtbot.addWidget(v)
    try:
        assert _eintraege(v) == ["Gespeicherte Suchen …", "Schräg"]
        karten = _waehlen(qtbot, v, "Schräg")
        assert karten == []
        assert v.typ_buttons[""].isChecked() and v.zeitraum_edit.grenzen() == ("", "")
        assert v.betrag_von_spin.value() == 0 and v.sort_combo.currentData() == "relevanz"
        assert v.meta_combos["kategorie"].currentData() == "Gibt es nicht mehr"
    finally:
        v.shutdown()

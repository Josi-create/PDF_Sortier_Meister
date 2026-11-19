"""Tests zu Issue #339: nach „Jetzt scannen“ in den Scan-Ordner wechseln und den neuen Scan auswaehlen.

Fixtures aus tests/test_office_gui.py und tests/test_ordner_beobachtung_232_gui.py (tmp-Pfade,
nie die echte Config). Es wird nie ein Programm gestartet, und die beiden Fragen (Ordner,
Wechsel) sind durch notierende Ersatzfunktionen ersetzt.
"""
from __future__ import annotations

import os

import pytest

from src.core import scan_programm
from src.gui import scan_eingang
from tests.test_office_gui import fresh_singletons, main_window  # noqa: F401 - Fixtures
from tests.test_ordner_beobachtung_232_gui import PDF, _ordner, fenster, lesen  # noqa: F401


@pytest.fixture
def gestartet(monkeypatch):
    aufrufe = []
    monkeypatch.setattr(scan_programm, "nach_vorn_holen", lambda d: False)
    monkeypatch.setattr(scan_programm.os, "startfile", lambda pfad, **kw: aufrufe.append(str(pfad)), raising=False)
    monkeypatch.setattr(scan_programm.subprocess, "Popen", lambda befehl, **kw: aufrufe.append(befehl[-1]))
    return aufrufe


@pytest.fixture
def fragen(monkeypatch):
    """Notiert die Fragen; Antworten in ``fragen["ordner"]`` und ``fragen["wechsel"]`` vorgeben."""
    protokoll = {"ordner": "", "wechsel": (True, False), "gestellt": []}

    def ordner(fenster, start):
        protokoll["gestellt"].append(("ordner", start))
        return protokoll["ordner"]

    def wechsel(fenster, ziel):
        protokoll["gestellt"].append(("wechsel", ziel))
        return protokoll["wechsel"]

    monkeypatch.setattr(scan_eingang, "ordner_erfragen", ordner)
    monkeypatch.setattr(scan_eingang, "wechsel_erfragen", wechsel)
    return protokoll


@pytest.fixture
def aufbau(fenster, fresh_singletons, gestartet):  # noqa: F811
    """Scan-Ordner „Eingang“ (mit Umlaut im Namen) und ein anderer Ordner, der gerade gezeigt wird."""
    tmp = fresh_singletons["tmp_path"]
    programm = tmp / "scan.exe"
    programm.write_bytes(b"")
    fresh_singletons["config"].set("scan_programm", str(programm))
    eingang = _ordner(tmp, anzahl=2, name="Eingang Ä")
    anderer = _ordner(tmp, anzahl=2, name="Steuer")
    fenster._navigate_to_folder(anderer)
    lesen(fenster)
    return {"eingang": eingang, "anderer": anderer, "config": fresh_singletons["config"]}


def klick(fenster):
    fenster.scan_starten_action.trigger()


# --- Welcher Ordner? ---

def test_ohne_eingestellten_ordner_wird_einmal_gefragt(fenster, aufbau, fragen, gestartet):
    config = aufbau["config"]
    config.set("favoriten", [{"pfad": str(aufbau["eingang"]), "name": ""}])
    fragen["ordner"] = str(aufbau["eingang"])

    klick(fenster)

    assert fragen["gestellt"][0] == ("ordner", str(aufbau["eingang"]))   # beginnt beim ersten Favoriten
    assert config.get(scan_eingang.KONFIG_ORDNER) == str(aufbau["eingang"])
    assert fenster.file_manager.scan_folder == aufbau["eingang"]
    assert len(gestartet) == 1


def test_abgebrochene_frage_kommt_nicht_wieder(fenster, aufbau, fragen, gestartet):
    klick(fenster)
    klick(fenster)

    assert [f[0] for f in fragen["gestellt"]] == ["ordner"]
    assert fenster.file_manager.scan_folder == aufbau["anderer"]   # kein Wechsel
    assert len(gestartet) == 2                                      # gescannt wird trotzdem


def test_verschwundener_ordner_wird_neu_erfragt(fenster, aufbau, fragen):
    config = aufbau["config"]
    config.set(scan_eingang.KONFIG_GEFRAGT, True)
    config.set(scan_eingang.KONFIG_ORDNER, str(aufbau["eingang"].parent / "gibt es nicht"))

    klick(fenster)

    assert [f[0] for f in fragen["gestellt"]] == ["ordner"]


# --- Rueckfrage vor dem Wechsel ---

def test_rueckfrage_ja_wechselt(fenster, aufbau, fragen):
    aufbau["config"].set(scan_eingang.KONFIG_ORDNER, str(aufbau["eingang"]))

    klick(fenster)

    assert fragen["gestellt"] == [("wechsel", aufbau["eingang"])]
    assert fenster.file_manager.scan_folder == aufbau["eingang"]
    assert not aufbau["config"].get(scan_eingang.KONFIG_AUTOMATISCH)


def test_rueckfrage_nein_bleibt_im_ordner(fenster, aufbau, fragen, gestartet):
    aufbau["config"].set(scan_eingang.KONFIG_ORDNER, str(aufbau["eingang"]))
    fragen["wechsel"] = (False, False)

    klick(fenster)

    assert fenster.file_manager.scan_folder == aufbau["anderer"]
    assert not fenster._scan_eingang.wartet
    assert len(gestartet) == 1


def test_kuenftig_immer_wechselt_danach_ohne_frage(fenster, aufbau, fragen):
    config = aufbau["config"]
    config.set(scan_eingang.KONFIG_ORDNER, str(aufbau["eingang"]))
    fragen["wechsel"] = (True, True)
    klick(fenster)
    assert config.get(scan_eingang.KONFIG_AUTOMATISCH) is True

    fenster._navigate_to_folder(aufbau["anderer"])
    klick(fenster)

    assert len(fragen["gestellt"]) == 1
    assert fenster.file_manager.scan_folder == aufbau["eingang"]


def test_im_scan_ordner_wird_nicht_gefragt(fenster, aufbau, fragen):
    aufbau["config"].set(scan_eingang.KONFIG_ORDNER, str(aufbau["eingang"]) + os.sep)
    fenster._navigate_to_folder(aufbau["eingang"])

    klick(fenster)

    assert fragen["gestellt"] == []
    assert fenster._scan_eingang.wartet


def test_fehlendes_programm_fragt_nichts(fenster, aufbau, fragen, gestartet):
    aufbau["config"].set("scan_programm", str(aufbau["eingang"] / "weg.exe"))

    klick(fenster)

    assert fragen["gestellt"] == [] and gestartet == []
    assert fenster.file_manager.scan_folder == aufbau["anderer"]


def test_laufendes_scanprogramm_wechselt_ebenso(fenster, aufbau, fragen, gestartet, monkeypatch):
    """#337: holt der Knopf nur das laufende Programm nach vorn, wird trotzdem gewechselt."""
    monkeypatch.setattr(scan_programm, "nach_vorn_holen", lambda d: True)
    aufbau["config"].set(scan_eingang.KONFIG_ORDNER, str(aufbau["eingang"]))

    klick(fenster)

    assert gestartet == []
    assert "läuft bereits" in fenster.statusbar.currentMessage()
    assert fenster.file_manager.scan_folder == aufbau["eingang"]
    assert fenster._scan_eingang.wartet


# --- Neuer Scan wird ausgewaehlt ---

def _scharf(fenster, aufbau):
    aufbau["config"].set(scan_eingang.KONFIG_ORDNER, str(aufbau["eingang"]))
    aufbau["config"].set(scan_eingang.KONFIG_AUTOMATISCH, True)
    klick(fenster)
    lesen(fenster)


def test_neuer_scan_wird_ausgewaehlt(fenster, aufbau, monkeypatch):
    gerollt = []
    monkeypatch.setattr(fenster, "zur_kachel_scrollen", lambda p: gerollt.append(p))
    _scharf(fenster, aufbau)
    fenster.on_pdf_clicked(aufbau["eingang"] / "alt_000.pdf")

    (aufbau["eingang"] / "Scan_neu.pdf").write_bytes(PDF)
    lesen(fenster)

    neu = aufbau["eingang"] / "Scan_neu.pdf"
    assert fenster.selected_pdf == neu
    assert gerollt == [neu]
    # nur einmal je Klick: der naechste Scan ohne Klick reisst die Auswahl nicht weg
    (aufbau["eingang"] / "Scan_zwei.pdf").write_bytes(PDF)
    lesen(fenster)
    assert fenster.selected_pdf == neu


def test_ohne_klick_bleibt_die_auswahl(fenster, aufbau):
    fenster._navigate_to_folder(aufbau["eingang"])
    lesen(fenster)
    fenster.on_pdf_clicked(aufbau["eingang"] / "alt_001.pdf")

    (aufbau["eingang"] / "Scan_neu.pdf").write_bytes(PDF)
    lesen(fenster)

    assert fenster.selected_pdf == aufbau["eingang"] / "alt_001.pdf"


def test_nach_wechsel_in_anderen_ordner_wird_nicht_mehr_gewartet(fenster, aufbau):
    _scharf(fenster, aufbau)
    fenster._navigate_to_folder(aufbau["anderer"])
    fenster._navigate_to_folder(aufbau["eingang"])
    lesen(fenster)
    fenster.on_pdf_clicked(aufbau["eingang"] / "alt_000.pdf")

    (aufbau["eingang"] / "Scan_neu.pdf").write_bytes(PDF)
    lesen(fenster)

    assert fenster.selected_pdf == aufbau["eingang"] / "alt_000.pdf"


def test_mehrfachauswahl_wird_nicht_ueberschrieben(fenster, aufbau):
    _scharf(fenster, aufbau)
    a, b = aufbau["eingang"] / "alt_000.pdf", aufbau["eingang"] / "alt_001.pdf"
    fenster.on_pdf_clicked(a)
    fenster.on_pdf_ctrl_clicked(b)
    assert fenster.selected_pdfs

    (aufbau["eingang"] / "Scan_neu.pdf").write_bytes(PDF)
    lesen(fenster)

    assert set(fenster.selected_pdfs) == {a, b}


def test_erster_scan_im_leeren_ordner(fenster, aufbau):
    leer = aufbau["eingang"].parent / "Leer"
    leer.mkdir()
    aufbau["config"].set(scan_eingang.KONFIG_ORDNER, str(leer))
    aufbau["config"].set(scan_eingang.KONFIG_AUTOMATISCH, True)
    klick(fenster)
    lesen(fenster)

    (leer / "erster.pdf").write_bytes(PDF)
    lesen(fenster)

    assert fenster.selected_pdf == leer / "erster.pdf"


def test_von_mehreren_neuen_dateien_die_neueste(qtbot, fenster, aufbau):
    _scharf(fenster, aufbau)
    alt, neu = aufbau["eingang"] / "b_frueher.pdf", aufbau["eingang"] / "a_spaeter.pdf"
    alt.write_bytes(PDF)
    neu.write_bytes(PDF)
    os.utime(alt, (1_600_000_000, 1_600_000_000))
    os.utime(neu, (1_700_000_000, 1_700_000_000))
    lesen(fenster)

    # viele neue Dateien kommen in Portionen; ausgewaehlt wird nach der letzten
    qtbot.waitUntil(lambda: fenster.selected_pdf is not None, timeout=5000)
    assert fenster.selected_pdf == neu


# --- Einstellungen ---

def test_einstellungen_laden_und_speichern(qtbot, fresh_singletons):  # noqa: F811
    from src.gui.settings_dialog import SettingsDialog

    config = fresh_singletons["config"]
    assert config.get(scan_eingang.KONFIG_ORDNER) == ""
    assert config.get(scan_eingang.KONFIG_AUTOMATISCH) is False
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    assert dialog.scan_eingang_input.text() == ""
    assert not dialog.scan_eingang_auto_check.isChecked()
    dialog.scan_eingang_input.setText(' "C:\\Scans\\Eingang Ä" ')
    dialog.scan_eingang_auto_check.setChecked(True)
    dialog._save_settings()
    assert config.get(scan_eingang.KONFIG_ORDNER) == "C:\\Scans\\Eingang Ä"
    assert config.get(scan_eingang.KONFIG_AUTOMATISCH) is True

    zweiter = SettingsDialog()
    qtbot.addWidget(zweiter)
    assert zweiter.scan_eingang_input.text() == "C:\\Scans\\Eingang Ä"
    assert zweiter.scan_eingang_auto_check.isChecked()
    # die Wahl „Künftig immer automatisch wechseln“ laesst sich hier zuruecknehmen
    zweiter.scan_eingang_auto_check.setChecked(False)
    zweiter._save_settings()
    assert config.get(scan_eingang.KONFIG_AUTOMATISCH) is False


def test_durchsuchen_traegt_den_ordner_ein(qtbot, fresh_singletons, monkeypatch):  # noqa: F811
    from PyQt6.QtWidgets import QFileDialog

    from src.gui.settings_dialog import SettingsDialog

    ordner = fresh_singletons["tmp_path"] / "Scans"
    ordner.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: ordner.as_posix())
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.scan_eingang_browse.click()
    assert dialog.scan_eingang_input.text() == str(ordner)


def test_gleicher_ordner_vergleicht_tolerant(tmp_path):
    ordner = tmp_path / "Eingang"
    ordner.mkdir()
    assert scan_eingang.gleicher_ordner(ordner, str(ordner) + "/")
    assert not scan_eingang.gleicher_ordner(ordner, tmp_path)
    assert not scan_eingang.gleicher_ordner(None, ordner)


def test_echte_rueckfrage_hat_das_kaestchen(qtbot, monkeypatch, tmp_path):
    """Die echte Rueckfrage (ohne den Ersatz aus conftest): Text, Kaestchen und Antworten."""
    from PyQt6.QtWidgets import QCheckBox, QMessageBox

    gesehen = {"antwort": QMessageBox.StandardButton.Yes}

    def exec_(box):
        gesehen["text"] = box.text()
        kaestchen = box.checkBox()
        assert isinstance(kaestchen, QCheckBox)
        gesehen["kaestchen"] = kaestchen.text()
        kaestchen.setChecked(True)
        box.button(gesehen["antwort"]).click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", exec_)
    assert scan_eingang._wechsel_dialog(None, tmp_path / "Eingang") == (True, True)
    assert "Eingang" in gesehen["text"]
    assert gesehen["kaestchen"] == "Künftig immer automatisch wechseln"
    gesehen["antwort"] = QMessageBox.StandardButton.No
    assert scan_eingang._wechsel_dialog(None, tmp_path / "Eingang") == (False, False)

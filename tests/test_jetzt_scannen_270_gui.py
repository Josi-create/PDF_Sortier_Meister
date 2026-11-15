"""Tests zu Issue #270: Knopf „Jetzt scannen“ startet das hinterlegte Scanprogramm.

Fixtures aus tests/test_office_gui.py (tmp-Pfade, nie die echte Config). Es wird nie ein
Programm gestartet: ``os.startfile``/``subprocess.Popen`` sind ersetzt.
"""
from __future__ import annotations

import sys

import pytest
from PyQt6.QtWidgets import QToolBar

from src.core import scan_programm
from tests.test_office_gui import fresh_singletons, main_window  # noqa: F401 - Fixtures


@pytest.fixture
def gestartet(monkeypatch):
    """Faengt jeden Programmstart ab und notiert ihn."""
    aufrufe = []
    monkeypatch.setattr(scan_programm.os, "startfile", lambda pfad, **kw: aufrufe.append(str(pfad)), raising=False)
    monkeypatch.setattr(scan_programm.subprocess, "Popen", lambda befehl, **kw: aufrufe.append(befehl[-1]))
    return aufrufe


def _programm(tmp_path, name="Scän Programm.exe"):
    ordner = tmp_path / "Programme mit Leerzeichen"
    ordner.mkdir()
    datei = ordner / name
    datei.write_bytes(b"")
    return datei


# --- Kern (ohne Oberflaeche) ---

def test_starten_ruft_das_programm_auf(tmp_path, gestartet):
    datei = _programm(tmp_path)
    scan_programm.starten(f'  "{datei}"  ')   # aus dem Explorer kopiert: mit Anfuehrungszeichen
    assert gestartet == [str(datei)]


@pytest.mark.parametrize("pfad", ["", "   ", None])
def test_starten_ohne_pfad_meldet_fehler(pfad, gestartet):
    with pytest.raises(scan_programm.ScanprogrammFehler):
        scan_programm.starten(pfad)
    assert gestartet == []


def test_starten_mit_fehlender_datei_meldet_fehler(tmp_path, gestartet):
    with pytest.raises(scan_programm.ScanprogrammFehler):
        scan_programm.starten(str(tmp_path / "gibt_es_nicht.exe"))
    assert gestartet == []


def test_fehler_des_systems_wird_gemeldet(tmp_path, monkeypatch):
    datei = _programm(tmp_path)

    def scheitert(*a, **k):
        raise OSError("Zugriff verweigert")

    monkeypatch.setattr(scan_programm.os, "startfile", scheitert, raising=False)
    monkeypatch.setattr(scan_programm.subprocess, "Popen", scheitert)
    with pytest.raises(scan_programm.ScanprogrammFehler, match="Zugriff verweigert"):
        scan_programm.starten(str(datei))


def test_mac_programmpaket_startet_ueber_open(tmp_path, monkeypatch):
    paket = tmp_path / "Scanprogramm.app"
    paket.mkdir()
    befehle = []
    monkeypatch.setattr(scan_programm.sys, "platform", "darwin")
    monkeypatch.setattr(scan_programm.subprocess, "Popen", lambda befehl, **kw: befehle.append(befehl))
    scan_programm.starten(str(paket))
    assert befehle == [["open", str(paket)]]


# --- Hauptfenster ---

def test_knopf_steht_neben_scan_ordner(main_window):  # noqa: F811
    texte = [a.text() for a in main_window.findChild(QToolBar).actions()]
    assert texte.index("Jetzt scannen") == texte.index("Scan-Ordner") + 1


def test_knopf_startet_hinterlegtes_programm(main_window, fresh_singletons, gestartet):  # noqa: F811
    datei = _programm(fresh_singletons["tmp_path"])
    fresh_singletons["config"].set("scan_programm", str(datei))

    main_window.scan_starten_action.trigger()

    assert gestartet == [str(datei)]
    assert datei.name in main_window.statusbar.currentMessage()


def test_ohne_programm_fuehrt_der_knopf_in_die_einstellungen(main_window, monkeypatch, gestartet):  # noqa: F811
    geoeffnet = []
    monkeypatch.setattr(main_window, "_open_settings_dialog", lambda tab=None: geoeffnet.append(tab))

    main_window.scan_starten_action.trigger()

    assert geoeffnet == ["Allgemein"]
    assert gestartet == []


def test_fehlendes_programm_gibt_eine_meldung(main_window, fresh_singletons, monkeypatch, gestartet):  # noqa: F811
    from src.gui import main_window as mw_mod

    meldungen = []
    monkeypatch.setattr(mw_mod.QMessageBox, "warning", lambda *a, **k: meldungen.append(a[2]))
    fresh_singletons["config"].set("scan_programm", str(fresh_singletons["tmp_path"] / "weg.exe"))

    main_window.scan_starten_action.trigger()

    assert gestartet == []
    assert len(meldungen) == 1 and "weg.exe" in meldungen[0] and "nicht gefunden" in meldungen[0]


# --- Einstellungen ---

def test_einstellung_wird_geladen_und_gespeichert(qtbot, fresh_singletons):  # noqa: F811
    from src.gui.settings_dialog import SettingsDialog

    config = fresh_singletons["config"]
    assert config.get("scan_programm") == ""   # Standard: nichts hinterlegt
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    assert dialog.scan_programm_input.text() == ""
    dialog.scan_programm_input.setText('  "C:\\Programme\\Scan\\scan.exe" ')
    dialog._save_settings()
    assert config.get("scan_programm") == "C:\\Programme\\Scan\\scan.exe"

    zweiter = SettingsDialog()
    qtbot.addWidget(zweiter)
    assert zweiter.scan_programm_input.text() == "C:\\Programme\\Scan\\scan.exe"


def test_durchsuchen_traegt_die_gewaehlte_datei_ein(qtbot, fresh_singletons, monkeypatch):  # noqa: F811
    from PyQt6.QtWidgets import QFileDialog

    from src.gui.settings_dialog import SettingsDialog

    datei = _programm(fresh_singletons["tmp_path"])
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (datei.as_posix(), ""))
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.scan_programm_browse.click()
    assert dialog.scan_programm_input.text() == str(datei)


@pytest.mark.skipif(sys.platform != "win32", reason="os.startfile gibt es nur unter Windows")
def test_windows_startet_im_programmordner(tmp_path, monkeypatch):
    datei = _programm(tmp_path)
    aufrufe = []
    monkeypatch.setattr(scan_programm.os, "startfile", lambda pfad, **kw: aufrufe.append((pfad, kw)))
    scan_programm.starten(str(datei))
    assert aufrufe == [(str(datei), {"cwd": str(datei.parent)})]

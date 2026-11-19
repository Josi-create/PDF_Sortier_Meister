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


# --- Issue #337: laufendes Programm nach vorn holen statt zweimal starten ---

def test_laufendes_programm_wird_nicht_noch_einmal_gestartet(tmp_path, gestartet, monkeypatch):
    datei = _programm(tmp_path)
    geholt = []
    monkeypatch.setattr(scan_programm, "nach_vorn_holen", lambda d: geholt.append(d) or True)
    assert scan_programm.starten(str(datei)) is True
    assert geholt == [datei]
    assert gestartet == []


def test_nicht_laufendes_programm_wird_gestartet(tmp_path, gestartet, monkeypatch):
    datei = _programm(tmp_path)
    monkeypatch.setattr(scan_programm, "nach_vorn_holen", lambda d: False)
    assert scan_programm.starten(str(datei)) is False
    assert gestartet == [str(datei)]


def test_fehler_beim_suchen_fuehrt_zum_normalen_start(tmp_path, gestartet, monkeypatch):
    datei = _programm(tmp_path)
    monkeypatch.setattr(scan_programm.sys, "platform", "win32")

    def kaputt(exe):
        raise OSError("kein Zugriff")

    monkeypatch.setattr(scan_programm, "_fenster_des_programms_windows", kaputt)
    assert scan_programm.nach_vorn_holen(datei) is False


def test_am_mac_wird_nicht_gesucht(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_programm.sys, "platform", "darwin")
    monkeypatch.setattr(scan_programm, "_fenster_des_programms_windows",
                        lambda exe: pytest.fail("darf am Mac nicht suchen"))
    assert scan_programm.nach_vorn_holen(tmp_path / "Scanprogramm.app") is False


def test_knopf_meldet_laufendes_programm(main_window, fresh_singletons, gestartet, monkeypatch):  # noqa: F811
    datei = _programm(fresh_singletons["tmp_path"])
    fresh_singletons["config"].set("scan_programm", str(datei))
    monkeypatch.setattr(scan_programm, "nach_vorn_holen", lambda d: True)

    main_window.scan_starten_action.trigger()

    assert gestartet == []
    meldung = main_window.statusbar.currentMessage()
    assert "läuft bereits" in meldung and datei.name in meldung


@pytest.mark.skipif(sys.platform != "win32", reason="Fenstersuche gibt es nur unter Windows")
def test_fenster_eines_laufenden_programms_wird_gefunden(tmp_path):
    """Echter Prozess mit sichtbarem Fenster: die Suche findet es ueber den exe-Pfad."""
    import subprocess
    import time

    skript = tmp_path / "fenster.py"
    skript.write_text(
        "import sys\n"
        "from PyQt6.QtWidgets import QApplication, QWidget\n"
        "app = QApplication(sys.argv)\n"
        "w = QWidget(); w.setWindowTitle('Testfenster 337'); w.showMinimized()\n"
        "app.exec()\n",
        encoding="utf-8",
    )
    import os

    # Die CI setzt QT_QPA_PLATFORM=offscreen; das Kind soll ein echtes Fenster bekommen
    umgebung = dict(os.environ, QT_QPA_PLATFORM="windows")
    kind = subprocess.Popen([sys.executable, str(skript)], env=umgebung)
    try:
        # Ein venv-python.exe startet unter Windows den Basis-Interpreter als Kindprozess
        kandidaten = {sys.executable, getattr(sys, "_base_executable", sys.executable)}
        gefunden = None
        frist = time.monotonic() + 60
        while gefunden is None and time.monotonic() < frist and kind.poll() is None:
            for exe in kandidaten:
                gefunden = gefunden or scan_programm._fenster_des_programms_windows(exe)
            if gefunden is None:
                time.sleep(0.2)
        if gefunden is None and os.environ.get("CI"):
            # Die gehosteten Windows-Runner zeigen nicht immer echte Fenster an
            pytest.skip(f"kein sichtbares Fenster in der CI (Kind beendet: {kind.poll()})")
        assert gefunden, "Fenster des laufenden Programms nicht gefunden"
        assert scan_programm._fenster_des_programms_windows(str(tmp_path / "anderes.exe")) is None
    finally:
        kind.kill()
        kind.wait(10)


@pytest.mark.skipif(sys.platform != "win32", reason="os.startfile gibt es nur unter Windows")
def test_windows_startet_im_programmordner(tmp_path, monkeypatch):
    datei = _programm(tmp_path)
    aufrufe = []
    monkeypatch.setattr(scan_programm.os, "startfile", lambda pfad, **kw: aufrufe.append((pfad, kw)))
    scan_programm.starten(str(datei))
    assert aufrufe == [(str(datei), {"cwd": str(datei.parent)})]

"""Tests zu Issue #338: Scanprogramm leichter hinterlegen (Vorschlaege, Verknuepfungen).

Es wird nie ein Programm gestartet und nie das echte Startmenue gelesen: Ordner, laufende
Programme und feste Programmorte sind in jedem Test vorgegeben.
"""
from __future__ import annotations

import struct

import pytest

from src.core import scan_programm
from tests.test_office_gui import fresh_singletons  # noqa: F401 - Fixture

_CLSID = bytes.fromhex("0114020000000000c000000000000046")


def _lnk(datei, ziel, *, unicode=True, argumente=False):
    """Schreibt eine minimale Windows-Verknuepfung (MS-SHLLINK) auf ``ziel``."""
    flags = 0x02 | 0x80 | (0x20 if argumente else 0)
    kopf = struct.pack("<I16sI", 0x4C, _CLSID, flags).ljust(0x4C, b"\0")
    ansi = str(ziel).encode("cp1252", errors="replace") + b"\0"
    if unicode:
        h = 0x24
        uni = str(ziel).encode("utf-16-le") + b"\0\0"
        basis_off, suffix_off = h, h + len(ansi)
        basis_u = suffix_off + 1
        suffix_u = basis_u + len(uni)
        rumpf = ansi + b"\0" + uni + b"\0\0"
        info = struct.pack("<IIIIIIIII", h + len(rumpf), h, 1, 0, basis_off, 0, suffix_off,
                           basis_u, suffix_u) + rumpf
    else:
        h = 0x1C
        rumpf = ansi + b"\0"
        info = struct.pack("<IIIIIII", h + len(rumpf), h, 1, 0, h, 0, h + len(ansi)) + rumpf
    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_bytes(kopf + info)
    return datei


def _exe(ordner, name):
    ordner.mkdir(parents=True, exist_ok=True)
    datei = ordner / name
    datei.write_bytes(b"")
    return datei


@pytest.fixture
def keine_festen_orte(monkeypatch):
    monkeypatch.setattr(scan_programm, "_bekannte_programmdateien", lambda: [])


# --- Verknuepfungen ---

def test_ziel_einer_verknuepfung_mit_umlauten(tmp_path):
    ziel = _exe(tmp_path / "Programme" / "Scän Werk", "scän.exe")
    lnk = _lnk(tmp_path / "Scän Werk.lnk", ziel)
    assert scan_programm.verknuepfung_ziel(lnk) == str(ziel)


def test_ziel_einer_alten_verknuepfung_ohne_unicode(tmp_path):
    ziel = _exe(tmp_path / "Programme", "scan.exe")
    lnk = _lnk(tmp_path / "Scan.lnk", ziel, unicode=False)
    assert scan_programm.verknuepfung_ziel(lnk) == str(ziel)


def test_verknuepfung_mit_startparametern_wird_nicht_aufgeloest(tmp_path):
    ziel = _exe(tmp_path / "Programme", "scan.exe")
    lnk = _lnk(tmp_path / "Scan.lnk", ziel, argumente=True)
    assert scan_programm.verknuepfung_ziel(lnk) is None
    assert scan_programm.eintragbarer_pfad(lnk) == str(lnk)   # startet dann ueber die Verknuepfung


@pytest.mark.parametrize("inhalt", [b"", b"keine Verknuepfung", b"\x4c\0\0\0" + b"\0" * 10])
def test_kaputte_verknuepfung_ergibt_kein_ziel(tmp_path, inhalt):
    lnk = tmp_path / "kaputt.lnk"
    lnk.write_bytes(inhalt)
    assert scan_programm.verknuepfung_ziel(lnk) is None
    assert scan_programm.verknuepfung_ziel(tmp_path / "fehlt.lnk") is None


def test_eintragbarer_pfad(tmp_path):
    ziel = _exe(tmp_path / "Programme", "scan.exe")
    assert scan_programm.eintragbarer_pfad(_lnk(tmp_path / "a.lnk", ziel)) == str(ziel)
    weg = _lnk(tmp_path / "b.lnk", tmp_path / "deinstalliert" / "scan.exe")
    assert scan_programm.eintragbarer_pfad(weg) == str(weg)   # Ziel fehlt: Verknuepfung behalten
    assert scan_programm.eintragbarer_pfad(ziel) == str(ziel)


# --- Vorschlaege ---

def test_vorschlaege_aus_dem_startmenue(tmp_path, keine_festen_orte):
    start = tmp_path / "Start Menu" / "Programs"
    vue = _exe(tmp_path / "Programme" / "VueScan", "vuescan.exe")
    naps = _exe(tmp_path / "Programme" / "NAPS2", "NAPS2.exe")
    _lnk(start / "VueScan" / "VueScan.lnk", vue)
    _lnk(start / "VueScan" / "Uninstall VueScan.lnk", vue)          # kein Programm zum Scannen
    _lnk(start / "NAPS2.lnk", naps)
    _lnk(start / "Zubehör" / "NAPS2 (Kopie).lnk", naps)              # gleiches Ziel: nur einmal
    _lnk(start / "Editor.lnk", _exe(tmp_path / "Programme", "editor.exe"))

    gefunden = scan_programm.vorschlaege(laufend=set(), ordner=[start])

    assert [(v.name, v.pfad) for v in gefunden] == [("NAPS2", str(naps)), ("VueScan", str(vue))]
    assert not any(v.laeuft for v in gefunden)


def test_laufendes_scanprogramm_steht_oben(tmp_path, keine_festen_orte):
    start = tmp_path / "Programs"
    _lnk(start / "NAPS2.lnk", _exe(tmp_path / "NAPS2", "NAPS2.exe"))
    _lnk(start / "VueScan.lnk", _exe(tmp_path / "VueScan", "vuescan.exe"))

    gefunden = scan_programm.vorschlaege(laufend={"vuescan.exe", "explorer.exe"}, ordner=[start])

    assert [(v.name, v.laeuft) for v in gefunden] == [("VueScan", True), ("NAPS2", False)]


def test_feste_orte_ergaenzen_das_startmenue(tmp_path, monkeypatch):
    naps = _exe(tmp_path / "NAPS2", "NAPS2.exe")
    monkeypatch.setattr(scan_programm, "_bekannte_programmdateien", lambda: [
        ("NAPS2", naps), ("VueScan", tmp_path / "nicht installiert" / "vuescan.exe"),
    ])
    gefunden = scan_programm.vorschlaege(laufend=set(), ordner=[tmp_path / "gibt es nicht"])
    assert [(v.name, v.pfad) for v in gefunden] == [("NAPS2", str(naps))]


# --- Einstellungen ---

def _dialog(qtbot):
    from src.gui.settings_dialog import SettingsDialog

    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    return dialog


def test_vorschlag_wird_eingetragen(qtbot, fresh_singletons, monkeypatch):  # noqa: F811
    monkeypatch.setattr(scan_programm, "vorschlaege", lambda: [
        scan_programm.Vorschlag("VueScan", r"C:\Programme\VueScan\vuescan.exe", laeuft=True),
        scan_programm.Vorschlag("NAPS2", r"C:\Programme\NAPS2\NAPS2.exe"),
    ])
    dialog = _dialog(qtbot)
    dialog._fuelle_scan_vorschlaege()
    aktionen = dialog.scan_programm_vorschlag_menu.actions()
    assert [a.text() for a in aktionen] == ["VueScan (läuft gerade)", "NAPS2"]

    aktionen[1].trigger()

    assert dialog.scan_programm_input.text() == r"C:\Programme\NAPS2\NAPS2.exe"


def test_ohne_fund_verweist_das_menue_auf_durchsuchen(qtbot, fresh_singletons, monkeypatch):  # noqa: F811
    monkeypatch.setattr(scan_programm, "vorschlaege", lambda: [])
    dialog = _dialog(qtbot)
    dialog._fuelle_scan_vorschlaege()
    dialog._fuelle_scan_vorschlaege()   # zweites Aufklappen: nicht doppelt
    aktionen = dialog.scan_programm_vorschlag_menu.actions()
    assert len(aktionen) == 1 and not aktionen[0].isEnabled()
    assert "Durchsuchen" in aktionen[0].text()


def test_durchsuchen_nimmt_verknuepfungen_an_und_beginnt_im_startmenue(
        qtbot, fresh_singletons, monkeypatch):  # noqa: F811
    from PyQt6.QtWidgets import QFileDialog

    from src.gui import settings_dialog

    tmp_path = fresh_singletons["tmp_path"]
    start = tmp_path / "Start Menu" / "Programs"
    ziel = _exe(tmp_path / "Programme" / "Scän", "scän.exe")
    lnk = _lnk(start / "Scän.lnk", ziel)
    aufrufe = []

    def waehlen(*a, **k):
        aufrufe.append((a, k))
        return lnk.as_posix(), ""

    monkeypatch.setattr(settings_dialog.sys, "platform", "win32")
    monkeypatch.setattr(scan_programm, "startmenue_ordner", lambda: [start])
    monkeypatch.setattr(QFileDialog, "getOpenFileName", waehlen)
    dialog = _dialog(qtbot)
    dialog.scan_programm_browse.click()

    (args, kw), = aufrufe
    assert args[2] == str(start) and "*.lnk" in args[3]
    assert kw["options"] & QFileDialog.Option.DontResolveSymlinks
    assert dialog.scan_programm_input.text() == str(ziel)


def test_durchsuchen_beginnt_beim_eingetragenen_pfad(qtbot, fresh_singletons, monkeypatch):  # noqa: F811
    from PyQt6.QtWidgets import QFileDialog

    aufrufe = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: aufrufe.append(a) or ("", ""))
    dialog = _dialog(qtbot)
    dialog.scan_programm_input.setText(r'"C:\Programme\Scan\scan.exe"')
    dialog.scan_programm_browse.click()
    assert aufrufe[0][2] == r"C:\Programme\Scan\scan.exe"
    assert dialog.scan_programm_input.text() == r'"C:\Programme\Scan\scan.exe"'   # abgebrochen: bleibt

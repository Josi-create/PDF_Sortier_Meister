"""GUI-Tests zu Issue #299: Uebersicht „Doppelte Dateien“ mit Auswahl zum Papierkorb.

Fixtures aus tests/test_doppelte_245_gui.py (tmp-Pfade ueber patch_singletons, nie die echte
Konfiguration; der Papierkorb ist ein Ordner unter tmp_path). Namen sind erfunden.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from src.gui import doppelte_aufraeumen
from src.gui.doppelte_aufraeumen import DoppelteAufraeumenDialog
from tests.test_auto_next_after_move_gui import (  # noqa: F401 - Fixtures
    fresh_singletons,
    main_window,
)
from tests.test_doppelte_245_gui import fenster  # noqa: F401 - Fixture

BRIEF = b"%PDF-1.4\n Brief an Max Mustermann \n%%EOF\n" * 20
ANDERS = b"%PDF-1.4\n Brief an Erika Musterfrau\n%%EOF\n" * 20


def _datei(pfad: Path, inhalt: bytes, mtime: float) -> Path:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(inhalt)
    os.utime(pfad, (mtime, mtime))
    return pfad


@pytest.fixture
def archiv(fenster):  # noqa: F811
    """Ordner mit einem Brief in drei Exemplaren (aeltestes in einem Unterordner) und einer Einzeldatei."""
    wurzel = fenster.tmp / "Ablage Müller"
    dateien = {
        "alt": _datei(wurzel / "Briefe 2023" / "Brief.pdf", BRIEF, 1_700_000_000),
        "mitte": _datei(wurzel / "Brief (1).pdf", BRIEF, 1_750_000_000),
        "neu": _datei(wurzel / "Scan 0001.pdf", BRIEF, 1_800_000_000),
        "einzeln": _datei(wurzel / "Brief Musterfrau.pdf", ANDERS, 1_800_000_000),
    }
    return wurzel, dateien


def _dialog(fenster, ordner, qtbot) -> DoppelteAufraeumenDialog:  # noqa: F811
    dlg = DoppelteAufraeumenDialog(fenster, ordner)
    qtbot.addWidget(dlg)
    qtbot.waitUntil(lambda: not dlg.sucht(), timeout=5000)
    return dlg


def _zeilen(dlg):
    return [[Path(z.data(0, doppelte_aufraeumen.PFAD_ROLLE)) for z in zeilen] for _, zeilen in dlg._zeilen()]


def test_dialog_zeigt_gruppe_mit_ordner_und_datum(fenster, archiv, qtbot):  # noqa: F811
    wurzel, d = archiv
    dlg = _dialog(fenster, wurzel, qtbot)

    assert _zeilen(dlg) == [[d["alt"], d["mitte"], d["neu"]]]
    zeile = dlg.liste.topLevelItem(0).child(0)
    assert zeile.text(0) == "Brief.pdf"
    assert zeile.text(1) == str(Path("Ablage Müller") / "Briefe 2023")
    assert zeile.text(2).count(".") == 2  # Datum dd.mm.yyyy hh:mm
    assert dlg.liste.topLevelItem(0).child(1).text(1) == "Ablage Müller"
    assert dlg.status_label.text() == "Eine Gruppe mit 3 gleichen Dateien gefunden."
    assert not dlg.papierkorb_knopf.isEnabled()  # nichts markiert, nichts geloescht


def test_ohne_doppelte_meldet_der_dialog_das(fenster, qtbot):  # noqa: F811
    leer = fenster.tmp / "Leer"
    _datei(leer / "a.pdf", BRIEF, 1_700_000_000)
    dlg = _dialog(fenster, leer, qtbot)
    assert dlg.liste.topLevelItemCount() == 0
    assert dlg.status_label.text() == "Keine doppelten Dateien gefunden."


def test_markierte_gehen_in_den_papierkorb_und_strg_z_holt_sie_zurueck(fenster, archiv, qtbot, monkeypatch):  # noqa: F811
    wurzel, d = archiv
    dlg = _dialog(fenster, wurzel, qtbot)
    fragen = []
    monkeypatch.setattr(dlg, "_rueckfrage", lambda pfade: fragen.append(list(pfade)) or True)

    dlg.alle_ausser_aeltester_markieren()
    assert dlg.markierte() == [d["mitte"], d["neu"]]
    assert dlg.papierkorb_knopf.text() == "2 in den Papierkorb …"
    dlg.papierkorb_knopf.click()

    assert fragen == [[d["mitte"], d["neu"]]]
    assert d["alt"].exists() and d["einzeln"].exists()
    assert not d["mitte"].exists() and not d["neu"].exists()
    assert sorted(p.name for p in fenster.papierkorb.iterdir()) == ["Brief (1).pdf", "Scan 0001.pdf"]
    assert dlg.liste.topLevelItemCount() == 0  # die Gruppe ist aufgeraeumt
    eintrag = fenster._undo_stack[-1]
    assert eintrag["type"] == "wegraeumen" and len(eintrag["eintraege"]) == 2

    dlg.close()
    fenster.undo_last_action()
    assert d["mitte"].exists() and d["neu"].exists()


def test_ganze_gruppe_markiert_loescht_nichts(fenster, archiv, qtbot, monkeypatch):  # noqa: F811
    wurzel, d = archiv
    dlg = _dialog(fenster, wurzel, qtbot)
    warnungen = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnungen.append(a[2]))
    monkeypatch.setattr(dlg, "_rueckfrage", lambda pfade: pytest.fail("keine Rueckfrage erwartet"))

    dlg._alle_setzen(lambda nr: Qt.CheckState.Checked)
    dlg.markierte_in_papierkorb()

    assert len(warnungen) == 1 and "mindestens eine Datei" in warnungen[0]
    assert all(p.exists() for p in d.values())
    assert fenster._undo_stack == [] or fenster._undo_stack[-1]["type"] != "wegraeumen"


def test_nein_bei_der_rueckfrage_loescht_nichts(fenster, archiv, qtbot, monkeypatch):  # noqa: F811
    wurzel, d = archiv
    dlg = _dialog(fenster, wurzel, qtbot)
    monkeypatch.setattr(dlg, "_rueckfrage", lambda pfade: False)
    dlg.alle_ausser_aeltester_markieren()
    dlg.markierte_in_papierkorb()
    assert all(p.exists() for p in d.values())
    assert len(_zeilen(dlg)[0]) == 3


def test_kachel_im_scan_bereich_verschwindet(fenster, qtbot, monkeypatch):  # noqa: F811
    scan = fenster.tmp / "Scan"
    a = _datei(scan / "a.pdf", BRIEF, 1_700_000_000)
    b = _datei(scan / "b.pdf", BRIEF, 1_800_000_000)
    fenster._navigate_to_folder(scan)
    assert fenster._pdf_widget_for(b) is not None
    dlg = _dialog(fenster, scan, qtbot)
    monkeypatch.setattr(dlg, "_rueckfrage", lambda pfade: True)
    dlg.alle_ausser_aeltester_markieren()
    dlg.markierte_in_papierkorb()
    assert fenster._pdf_widget_for(b) is None
    assert fenster._pdf_widget_for(a) is not None


def test_menue_und_kontextmenue_oeffnen_den_dialog(fenster, archiv, monkeypatch):  # noqa: F811
    wurzel, _ = archiv
    geoeffnet = []
    monkeypatch.setattr(DoppelteAufraeumenDialog, "exec", lambda self: geoeffnet.append(self.ordner) or 0)
    monkeypatch.setattr(DoppelteAufraeumenDialog, "suchen", lambda self: None)

    fenster._navigate_to_folder(wurzel)
    fenster.doppelte_action.trigger()

    menue = fenster.folder_tree._build_context_menu(wurzel / "Briefe 2023")
    eintrag = next(a for a in menue.actions() if "Doppelte Dateien suchen" in a.text())
    eintrag.trigger()

    assert geoeffnet == [Path(fenster.file_manager.scan_folder), wurzel / "Briefe 2023"]

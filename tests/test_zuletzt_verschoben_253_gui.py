"""Issue #253: Nach dem Verschieben mit einem Klick in den Zielordner springen.

Fixtures wie in tests/test_office_gui.py (Singletons auf tmp-Pfade, nie die echte Config).
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PyQt6.QtWidgets import QMenu, QMessageBox

from tests.test_office_gui import (  # noqa: F401 - Fixtures
    _prime_cache_on_load,
    fresh_singletons,
    main_window,
)


def _pdf(pfad: Path) -> Path:
    pfad.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return pfad


def _welt(tmp_path: Path):
    scan = tmp_path / "Scan"
    scan.mkdir()
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        _pdf(scan / name)
    ziel = tmp_path / "Zählerstände 2026"  # Umlaute im Pfad
    ziel.mkdir()
    _pdf(ziel / "schon_da.pdf")
    return scan, ziel


def _verschieben(main_window, dateien, ziel: Path, namen=None):
    """Wie die Verschiebe-Wege des Fensters: Datei bewegen, Undo-Eintrag anlegen."""
    paare = []
    for i, datei in enumerate(dateien):
        neu = ziel / (namen[i] if namen else datei.name)
        shutil.move(str(datei), str(neu))
        paare.append((datei, neu))
    main_window._push_undo({"type": "move", "moves": paare, "description": "Test"})
    return [neu for _alt, neu in paare]


def test_hinweis_erscheint_erst_nach_dem_verschieben(main_window, fresh_singletons, monkeypatch):
    scan, ziel = _welt(fresh_singletons["tmp_path"])
    _prime_cache_on_load(main_window, monkeypatch)
    main_window._navigate_to_folder(scan)
    label = main_window.zuletzt_verschoben_label
    assert label.isHidden()

    # Datei von aussen auf einen Zielordner gezogen: verschiebt ohne Rueckfrage
    main_window.on_pdf_dropped_on_folder(scan / "a.pdf", ziel)

    assert (ziel / "a.pdf").exists()
    assert not label.isHidden()
    assert "Zählerstände 2026" in label.text()
    assert str(ziel) in label.toolTip()
    assert main_window._letzte_ziele == [(ziel, [ziel / "a.pdf"])]


def test_klick_oeffnet_den_ordner_und_markiert_die_dateien(main_window, fresh_singletons, monkeypatch):
    scan, ziel = _welt(fresh_singletons["tmp_path"])
    _prime_cache_on_load(main_window, monkeypatch)
    main_window._navigate_to_folder(scan)
    neu = _verschieben(main_window, [scan / "a.pdf", scan / "b.pdf"], ziel,
                       namen=["2026-01-05 Mustermann Rechnung.pdf", "b.pdf"])
    main_window.left_tabs.setCurrentIndex(1)

    main_window.zuletzt_verschoben_label.clicked.emit()

    assert Path(main_window.config.get_scan_folder()) == ziel
    assert main_window.left_tabs.currentIndex() == 0
    assert sorted(main_window.selected_pdfs) == sorted(neu)
    markiert = {w.pdf_path.name for w in main_window.pdf_widgets if w.selected}
    assert markiert == {"2026-01-05 Mustermann Rechnung.pdf", "b.pdf"}  # schon_da.pdf bleibt unmarkiert
    # Zurueck fuehrt wieder in den Scan-Ordner
    assert main_window._folder_history[-1] == scan


def test_einzelne_datei_wird_ausgewaehlt_auch_beim_zweiten_klick(main_window, fresh_singletons, monkeypatch):
    scan, ziel = _welt(fresh_singletons["tmp_path"])
    _prime_cache_on_load(main_window, monkeypatch)
    main_window._navigate_to_folder(scan)
    (neu,) = _verschieben(main_window, [scan / "a.pdf"], ziel)

    main_window.zuletzt_verschoben_oeffnen()
    assert main_window.selected_pdf == neu and not main_window.selected_pdfs
    assert main_window._pdf_widget_for(neu).selected

    # Zweiter Klick im selben Ordner: die Auswahl bleibt (ein Kachel-Klick wuerde sie aufheben)
    main_window.zuletzt_verschoben_oeffnen()
    assert main_window.selected_pdf == neu
    assert main_window._pdf_widget_for(neu).selected


def test_menue_zeigt_die_letzten_ziele_neuestes_zuerst(main_window, fresh_singletons, monkeypatch):
    scan, ziel = _welt(fresh_singletons["tmp_path"])
    zweites = fresh_singletons["tmp_path"] / "Briefe & Post"
    zweites.mkdir()
    _prime_cache_on_load(main_window, monkeypatch)
    main_window._navigate_to_folder(scan)
    menu = QMenu()

    main_window.zuletzt_verschoben_menue_fuellen(menu)
    assert [a.isEnabled() for a in menu.actions()] == [False]  # "Noch nichts verschoben"

    _verschieben(main_window, [scan / "a.pdf"], ziel)
    _verschieben(main_window, [scan / "b.pdf"], zweites)
    _verschieben(main_window, [scan / "c.pdf"], ziel)  # derselbe Ordner noch einmal: kein zweiter Eintrag

    main_window.zuletzt_verschoben_menue_fuellen(menu)
    assert [a.text() for a in menu.actions()] == ["Zählerstände 2026 (1)", "Briefe && Post (1)"]

    menu.actions()[1].trigger()
    assert Path(main_window.config.get_scan_folder()) == zweites
    assert main_window.selected_pdf == zweites / "b.pdf"


def test_rueckgaengig_nimmt_das_ziel_wieder_heraus(main_window, fresh_singletons, monkeypatch):
    from src.gui import main_window as mw_mod

    scan, ziel = _welt(fresh_singletons["tmp_path"])
    _prime_cache_on_load(main_window, monkeypatch)
    main_window._navigate_to_folder(scan)
    _verschieben(main_window, [scan / "a.pdf"], ziel)
    monkeypatch.setattr(mw_mod.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    main_window.undo_last_action()

    assert (scan / "a.pdf").exists()
    assert main_window._letzte_ziele == []
    assert main_window.zuletzt_verschoben_label.isHidden()


def test_geloeschter_zielordner_wechselt_nicht(main_window, fresh_singletons, monkeypatch):
    scan, ziel = _welt(fresh_singletons["tmp_path"])
    _prime_cache_on_load(main_window, monkeypatch)
    main_window._navigate_to_folder(scan)
    _verschieben(main_window, [scan / "a.pdf"], ziel)
    shutil.rmtree(ziel)

    main_window.zuletzt_verschoben_oeffnen()

    assert Path(main_window.config.get_scan_folder()) == scan
    assert "gibt es nicht mehr" in main_window.statusbar.currentMessage()


def test_umbenannte_datei_oeffnet_nur_den_ordner(main_window, fresh_singletons, monkeypatch):
    scan, ziel = _welt(fresh_singletons["tmp_path"])
    _prime_cache_on_load(main_window, monkeypatch)
    main_window._navigate_to_folder(scan)
    (neu,) = _verschieben(main_window, [scan / "a.pdf"], ziel)
    neu.rename(ziel / "anders.pdf")

    main_window.zuletzt_verschoben_oeffnen()

    assert Path(main_window.config.get_scan_folder()) == ziel
    assert not any(w.selected for w in main_window.pdf_widgets)

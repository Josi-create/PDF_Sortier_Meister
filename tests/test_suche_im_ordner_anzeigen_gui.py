"""Reiter Suche, Rechtsklick "Im Ordner anzeigen" (Live-Test 08.11.2026).

Das Hauptfenster oeffnet den Ordner der Datei in "PDFs", waehlt sie aus und
zeigt sie in der Vorschau - danach kann man sie umbenennen oder verschieben.
Fixtures wie in tests/test_auto_next_after_move_gui.py (nie die echte Konfiguration).
"""
from __future__ import annotations

from pathlib import Path

from tests.test_auto_next_after_move_gui import (  # noqa: F401 - Fixtures
    _make_scan_folder,
    _prime_cache,
    fresh_singletons,
    main_window,
)


def _ordner(tmp_path: Path, name: str, dateien: list[str]) -> Path:
    ordner = tmp_path / name
    ordner.mkdir(parents=True)
    for d in dateien:
        (ordner / d).write_bytes(b"%PDF-1.4\n%%EOF\n")
    return ordner


def test_im_ordner_anzeigen_wechselt_ordner_und_waehlt_aus(main_window, tmp_path, qtbot):
    scan = _make_scan_folder(tmp_path, ["eingang.pdf"])
    archiv = _ordner(tmp_path, "Archiv/2024", ["a.pdf", "gesucht.pdf", "z.pdf"])
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [scan / "eingang.pdf", *archiv.iterdir()])
    # Ausgangslage: anderer Reiter links und "Suche" in der Mitte
    main_window.left_tabs.setCurrentWidget(main_window.korrespondenten_view)
    main_window.center_tabs.setCurrentWidget(main_window.search_view)

    main_window.search_view.im_ordner_anzeigen_requested.emit(archiv / "gesucht.pdf")

    assert Path(main_window.config.get_scan_folder()) == archiv
    assert main_window.left_tabs.currentIndex() == 0
    assert main_window.center_tabs.currentIndex() == 0
    assert main_window.selected_pdf == archiv / "gesucht.pdf"
    assert not main_window.selected_pdfs
    widget = main_window._pdf_widget_for(archiv / "gesucht.pdf")
    assert widget is not None and widget.selected


def test_im_ordner_anzeigen_hebt_bestehende_auswahl_nicht_auf(main_window, tmp_path):
    scan = _make_scan_folder(tmp_path, ["eins.pdf", "zwei.pdf"])
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, list(scan.iterdir()))
    main_window.on_pdf_clicked(scan / "zwei.pdf")

    # Gleicher Ordner, schon ausgewaehlt: kein Umschalten (ein zweiter Klick wuerde abwaehlen)
    main_window.zeige_datei_im_ordner(scan / "zwei.pdf")
    assert main_window.selected_pdf == scan / "zwei.pdf"


def test_im_ordner_anzeigen_datei_fehlt(main_window, tmp_path):
    scan = _make_scan_folder(tmp_path, ["eins.pdf"])
    main_window._navigate_to_folder(scan)

    main_window.zeige_datei_im_ordner(tmp_path / "weg" / "nicht_da.pdf")

    assert Path(main_window.config.get_scan_folder()) == scan
    assert "nicht gefunden" in main_window.statusbar.currentMessage()

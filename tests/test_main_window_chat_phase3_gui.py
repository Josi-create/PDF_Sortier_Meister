"""MainWindow (Phase 3, Issue #166/#167): Chat in der linken Spalte, Bezug beim Reiterwechsel,
"Nach … verschieben" aus dem Chat, belegter Ordner als Vorschlag.

Fixtures stammen aus tests/test_auto_next_after_move_gui.py (tmp-Config, bestaetigte Verschiebe-Dialoge).
"""
from __future__ import annotations

from pathlib import Path

from src.ml.classifier import Suggestion
from tests.test_auto_next_after_move_gui import (  # noqa: F401 - Fixtures werden importiert
    _make_scan_folder,
    _prime_cache,
    fresh_singletons,
    main_window,
)


def _ziel(main_window, tmp_path: Path, name: str = "Energie") -> Path:
    ablage = tmp_path / "Ablage"
    ziel = ablage / name
    ziel.mkdir(parents=True)
    main_window.folder_manager.add_folder(ablage)
    return ziel


def test_chat_sitzt_kompakt_in_der_linken_spalte(main_window):
    assert main_window.chat_view.kompakt is True
    assert main_window.left_tabs.widget(0) is not main_window.chat_view
    assert main_window.left_tabs.widget(1) is main_window.chat_view
    assert main_window.chat_view.schnellfragen_toggle is not None
    assert len(main_window.chat_view.schnellfragen_btns) == 6


def test_wechsel_in_den_chat_setzt_den_bezug(main_window, fresh_singletons):
    scan = _make_scan_folder(fresh_singletons["tmp_path"], ["a.pdf", "b.pdf"])
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [scan / "a.pdf", scan / "b.pdf"])
    main_window.on_pdf_clicked(scan / "a.pdf")

    main_window.show_chat_tab()
    assert main_window.chat_view.bezug == scan / "a.pdf"
    assert not main_window.chat_view.bezug_box.isHidden()

    main_window.left_tabs.setCurrentIndex(0)
    main_window.on_pdf_clicked(scan / "b.pdf")
    main_window.show_chat_tab()
    assert main_window.chat_view.bezug == scan / "b.pdf"


def test_verschieben_aus_dem_chat(main_window, fresh_singletons):
    tmp_path = fresh_singletons["tmp_path"]
    scan = _make_scan_folder(tmp_path, ["a.pdf", "b.pdf"])
    ziel = _ziel(main_window, tmp_path)
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [scan / "a.pdf", scan / "b.pdf"])
    main_window.on_pdf_clicked(scan / "a.pdf")
    main_window.show_chat_tab()
    assert main_window.chat_view.bezug == scan / "a.pdf"

    main_window.chat_view.verschieben_requested.emit(str(ziel))

    assert (ziel / "a.pdf").exists() and not (scan / "a.pdf").exists()
    assert main_window.left_tabs.currentIndex() == 0  # zurueck zu den PDFs
    assert main_window.chat_view.bezug is None  # die Datei liegt nicht mehr im Scan-Ordner
    assert len(main_window.pdf_widgets) == 1


def test_verschieben_per_zielordner_bei_offenem_chat_springt_zurueck(main_window, fresh_singletons):
    """Auch ohne den Chat-Knopf (Klick auf Zielordner oder Vorschlag) kommt die linke Spalte zu den PDFs zurueck."""
    tmp_path = fresh_singletons["tmp_path"]
    scan = _make_scan_folder(tmp_path, ["a.pdf", "b.pdf"])
    ziel = _ziel(main_window, tmp_path)
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [scan / "a.pdf", scan / "b.pdf"])
    main_window.on_pdf_clicked(scan / "a.pdf")
    main_window.show_chat_tab()
    assert main_window.left_tabs.currentWidget() is main_window.chat_view

    main_window.move_pdf_to_folder_and_learn(scan / "a.pdf", ziel)  # wie ein Klick auf den Zielordner

    assert (ziel / "a.pdf").exists()
    assert main_window.left_tabs.currentIndex() == 0
    assert main_window.chat_view.bezug is None

    # Eine andere PDF als Bezug bleibt unberuehrt, wenn nicht sie verschoben wird
    main_window.on_pdf_clicked(scan / "b.pdf")
    main_window.show_chat_tab()
    main_window.chat_view.set_bezug(scan / "b.pdf")
    (scan / "c.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [scan / "b.pdf", scan / "c.pdf"])
    main_window.show_chat_tab()
    main_window.chat_view.set_bezug(scan / "b.pdf")
    main_window.move_pdf_to_folder_and_learn(scan / "c.pdf", ziel)
    assert main_window.left_tabs.currentWidget() is main_window.chat_view
    assert main_window.chat_view.bezug == scan / "b.pdf"


def test_verschieben_ohne_bezug_oder_mit_verschwundener_datei_tut_nichts(main_window, fresh_singletons):
    tmp_path = fresh_singletons["tmp_path"]
    scan = _make_scan_folder(tmp_path, ["a.pdf"])
    ziel = _ziel(main_window, tmp_path)
    main_window._navigate_to_folder(scan)
    main_window.chat_view.verschieben_requested.emit(str(ziel))  # kein Bezug
    assert (scan / "a.pdf").exists()
    main_window.chat_view.set_bezug(scan / "weg.pdf")
    main_window.chat_view.verschieben_requested.emit(str(ziel))  # Datei gibt es nicht
    assert not (ziel / "weg.pdf").exists()


def test_belegter_ordner_wird_vorschlag_im_detailbereich(main_window, fresh_singletons):
    tmp_path = fresh_singletons["tmp_path"]
    scan = _make_scan_folder(tmp_path, ["a.pdf"])
    ziel = _ziel(main_window, tmp_path)
    anderer = tmp_path / "Ablage" / "Telekom"
    anderer.mkdir()
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [scan / "a.pdf"])
    main_window.on_pdf_clicked(scan / "a.pdf")
    main_window.display_suggestions([
        Suggestion(folder_path=anderer, folder_name="Telekom", confidence=0.4, reason="Ähnlicher Name",
                   relative_path="Ablage/Telekom"),
        Suggestion(folder_path=ziel, folder_name="Energie", confidence=0.31, reason="Historie",
                   relative_path="Ablage/Energie"),
    ])
    main_window.show_chat_tab()

    main_window.chat_view.ordner_belegt.emit(str(ziel), "belegt durch [2], [3]")

    erster = main_window._shown_suggestions[0]
    assert Path(erster.folder_path) == ziel
    assert erster.confidence == 0.9 and erster.reason == "Historie + Chat bestätigt"
    assert len(main_window._shown_suggestions) == 2

    # Ohne passenden Bezug (andere Datei ausgewaehlt) bleibt die Liste
    main_window.chat_view.set_bezug(scan / "andere.pdf")
    main_window.chat_view.ordner_belegt.emit(str(anderer), "belegt durch [4]")
    assert Path(main_window._shown_suggestions[0].folder_path) == ziel

"""Live-Test 08.11.2026: Ein neu erzeugtes PDF ist ausgewaehlt UND in "PDFs" ins Bild gescrollt.

Direkt nach ``load_pdfs`` hat eine neue Kachel noch keine Geometrie; ein sofortiges
``ensureWidgetVisible`` blieb wirkungslos. ``zur_kachel_scrollen`` scrollt deshalb erst
nach dem Layout-Durchlauf. Fixtures wie in tests/test_office_gui.py (nie die echte Config).
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QWidget

from tests.test_office_gui import (  # noqa: F401 - Fixtures
    _prime_cache_on_load,
    _scan,
    fresh_singletons,
    main_window,
)


def _sichtbar_im_viewport(main_window, widget) -> bool:
    viewport = main_window.pdf_scroll_area.viewport()
    oben = widget.mapTo(viewport, QPoint(0, 0)).y()
    return oben >= 0 and oben + widget.height() <= viewport.height()


def test_zur_kachel_scrollen_zeigt_die_letzte_kachel(qtbot, main_window, fresh_singletons, monkeypatch):
    scan = fresh_singletons["tmp_path"] / "Viele"
    scan.mkdir()
    for i in range(60):
        (scan / f"dok_{i:02d}.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    main_window.resize(1100, 600)
    QWidget.setVisible(main_window, True)  # show() ist in der Fixture stillgelegt
    qtbot.waitExposed(main_window)
    _prime_cache_on_load(main_window, monkeypatch)
    main_window._navigate_to_folder(scan)
    leiste = main_window.pdf_scroll_area.verticalScrollBar()
    qtbot.waitUntil(lambda: leiste.maximum() > 0, timeout=3000)  # Test braucht eine scrollbare Liste

    # Wie nach dem Umwandeln: neu laden, sofort auswaehlen und scrollen -
    # die Kacheln haben in diesem Moment noch keine Geometrie
    main_window.load_pdfs()
    letzte_pfad = main_window.pdf_widgets[-1].pdf_path
    main_window.on_pdf_clicked(letzte_pfad)
    main_window.zur_kachel_scrollen(letzte_pfad)

    letzte = main_window._pdf_widget_for(letzte_pfad)
    # Erst wenn das Layout steht (Kachel weit unten in der Liste), zaehlt "sichtbar" -
    # vorher liegen alle neuen Kacheln bei (0, 0)
    qtbot.waitUntil(
        lambda: leiste.maximum() > 0 and letzte.y() > leiste.pageStep()
        and _sichtbar_im_viewport(main_window, letzte),
        timeout=3000,
    )
    assert leiste.value() > 0


def test_umwandeln_scrollt_zum_neuen_pdf(qtbot, main_window, fresh_singletons, monkeypatch):
    from src.core.office_convert import UmwandlungsErgebnis
    from src.gui import office_convert_worker as worker_mod

    scan = _scan(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)

    def falsch(pfad, pdfa=False):
        ziel = pfad.with_suffix(".pdf")
        ziel.write_bytes(b"%PDF-1.4\n%%EOF\n")
        return UmwandlungsErgebnis(pdf=ziel, werkzeug="Word", pdfa=pdfa)

    monkeypatch.setattr(worker_mod, "umwandeln", falsch)
    _prime_cache_on_load(main_window, monkeypatch)
    gescrollt = []
    monkeypatch.setattr(main_window, "zur_kachel_scrollen", gescrollt.append)

    main_window.on_office_convert(scan / "Brief.docx", False)
    qtbot.waitUntil(lambda: main_window._office_worker is None, timeout=5000)

    assert main_window.selected_pdf == scan / "Brief.pdf"
    assert gescrollt == [scan / "Brief.pdf"]


def test_zur_kachel_scrollen_nach_schliessen_ohne_fehler(qtbot, main_window, fresh_singletons):
    scan = _scan(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)
    main_window.zur_kachel_scrollen(scan / "a.pdf")
    main_window.zur_kachel_scrollen(scan / "gibt_es_nicht.pdf")  # keine Kachel: nichts tun
    qtbot.wait(200)  # beide Timer laufen ohne Ausnahme durch

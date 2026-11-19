"""Issue #251: Ein erneuter Klick auf die einzige markierte Kachel waehlt sie nicht mehr ab.

Abgewaehlt wird ueber einen Klick in den leeren Bereich der Kachelansicht. Strg-Klick (Umschalten),
Umschalt-Klick (Bereich), Ziehen, Doppelklick und Strg+A verhalten sich wie bisher.

Fixtures wie in tests/test_office_gui.py (Singletons auf tmp-Pfade, nie die echte Konfiguration).
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QApplication, QWidget

from tests.test_office_gui import (  # noqa: F401 - Fixtures
    _prime_cache_on_load,
    fresh_singletons,
    main_window,
)

LINKS = Qt.MouseButton.LeftButton
STRG = Qt.KeyboardModifier.ControlModifier
UMSCHALT = Qt.KeyboardModifier.ShiftModifier
IN_KACHEL = QPoint(10, 10)


def _aufbauen(qtbot, mw, fresh_singletons, monkeypatch, anzahl=4):
    """Sichtbares Fenster mit ``anzahl`` Kacheln; liefert Pfade und das Protokoll der Vorschlags-Abrufe."""
    scan = fresh_singletons["tmp_path"] / "Größe und Maß"  # Umlaute im Pfad
    scan.mkdir()
    pfade = [scan / f"dok_{i}.pdf" for i in range(anzahl)]
    for p in pfade:
        p.write_bytes(b"%PDF-1.4\n%%EOF\n")
    doppelklicks: list = []
    monkeypatch.setattr(mw, "on_pdf_double_clicked", doppelklicks.append)  # sonst oeffnet sich ein Betrachter
    mw.resize(1100, 700)
    QWidget.setVisible(mw, True)  # show() ist in der Fixture stillgelegt
    qtbot.waitExposed(mw)
    _prime_cache_on_load(mw, monkeypatch)
    abrufe: list = []
    monkeypatch.setattr(mw, "update_suggestions_for_pdf", abrufe.append)
    mw._navigate_to_folder(scan)
    qtbot.waitUntil(lambda: len(mw.pdf_widgets) == anzahl, timeout=3000)
    qtbot.waitUntil(lambda: all(w.isVisible() and w.width() > 20 for w in mw.pdf_widgets), timeout=3000)
    return pfade, abrufe, doppelklicks


def _kachel(mw, pfad):
    return mw._pdf_widget_for(pfad)


def _markiert(mw):
    return [w.pdf_path for w in mw.pdf_widgets if w.selected]


def _leere_stelle(mw) -> QPoint:
    container = mw.pdf_container
    for y in range(container.height() - 3, 0, -8):
        for x in range(container.width() - 3, 0, -8):
            if container.childAt(QPoint(x, y)) is None:
                return QPoint(x, y)
    raise AssertionError("keine leere Stelle in der Kachelansicht gefunden")


def test_zweiter_klick_laesst_die_einzige_markierte_kachel_markiert(
        qtbot, main_window, fresh_singletons, monkeypatch):
    pfade, abrufe, _ = _aufbauen(qtbot, main_window, fresh_singletons, monkeypatch)
    geleert: list = []
    monkeypatch.setattr(main_window.detail_panel, "clear", lambda: geleert.append(1))

    qtbot.mouseClick(_kachel(main_window, pfade[1]), LINKS, pos=IN_KACHEL)
    assert main_window.selected_pdf == pfade[1] and _markiert(main_window) == [pfade[1]]

    qtbot.mouseClick(_kachel(main_window, pfade[1]), LINKS, pos=IN_KACHEL)
    qtbot.mouseClick(_kachel(main_window, pfade[1]), LINKS, pos=IN_KACHEL)

    assert main_window.selected_pdf == pfade[1]
    assert main_window.selected_pdfs == []
    assert _markiert(main_window) == [pfade[1]]
    assert geleert == []            # Detail-Panel und Vorschau bleiben stehen
    assert abrufe == [pfade[1]]     # und es wird nichts neu abgerufen


def test_klick_in_den_leeren_bereich_waehlt_ab(qtbot, main_window, fresh_singletons, monkeypatch):
    pfade, _, _ = _aufbauen(qtbot, main_window, fresh_singletons, monkeypatch)
    qtbot.mouseClick(_kachel(main_window, pfade[0]), LINKS, pos=IN_KACHEL)
    assert main_window.selected_pdf == pfade[0]

    qtbot.mouseClick(main_window.pdf_container, LINKS, pos=_leere_stelle(main_window))

    assert main_window.selected_pdf is None and main_window.selected_pdfs == []
    assert _markiert(main_window) == []


def test_klick_auf_andere_kachel_wechselt_die_auswahl(qtbot, main_window, fresh_singletons, monkeypatch):
    pfade, abrufe, _ = _aufbauen(qtbot, main_window, fresh_singletons, monkeypatch)
    qtbot.mouseClick(_kachel(main_window, pfade[0]), LINKS, pos=IN_KACHEL)
    qtbot.mouseClick(_kachel(main_window, pfade[2]), LINKS, pos=IN_KACHEL)

    assert main_window.selected_pdf == pfade[2] and _markiert(main_window) == [pfade[2]]
    assert abrufe == [pfade[0], pfade[2]]


def test_strg_klick_schaltet_weiter_um(qtbot, main_window, fresh_singletons, monkeypatch):
    """Strg-Klick bleibt ein Umschalter - auch auf der einzigen markierten Kachel."""
    pfade, _, _ = _aufbauen(qtbot, main_window, fresh_singletons, monkeypatch)
    qtbot.mouseClick(_kachel(main_window, pfade[0]), LINKS, pos=IN_KACHEL)

    qtbot.mouseClick(_kachel(main_window, pfade[2]), LINKS, STRG, pos=IN_KACHEL)
    assert main_window.selected_pdfs == [pfade[0], pfade[2]]
    assert set(_markiert(main_window)) == {pfade[0], pfade[2]}

    qtbot.mouseClick(_kachel(main_window, pfade[2]), LINKS, STRG, pos=IN_KACHEL)
    assert main_window.selected_pdfs == [pfade[0]] and _markiert(main_window) == [pfade[0]]

    qtbot.mouseClick(_kachel(main_window, pfade[0]), LINKS, STRG, pos=IN_KACHEL)
    assert main_window.selected_pdf is None and main_window.selected_pdfs == []
    assert _markiert(main_window) == []


def test_umschalt_klick_markiert_weiter_den_bereich(qtbot, main_window, fresh_singletons, monkeypatch):
    pfade, _, _ = _aufbauen(qtbot, main_window, fresh_singletons, monkeypatch)
    reihenfolge = [w.pdf_path for w in main_window.pdf_widgets]
    qtbot.mouseClick(_kachel(main_window, reihenfolge[0]), LINKS, pos=IN_KACHEL)

    qtbot.mouseClick(_kachel(main_window, reihenfolge[2]), LINKS, UMSCHALT, pos=IN_KACHEL)

    assert main_window.selected_pdfs == reihenfolge[:3]
    assert _markiert(main_window) == reihenfolge[:3]


def test_klick_in_die_mehrfachauswahl_waehlt_nur_diese_und_bleibt_dann(
        qtbot, main_window, fresh_singletons, monkeypatch):
    pfade, _, _ = _aufbauen(qtbot, main_window, fresh_singletons, monkeypatch)
    qtbot.mouseClick(_kachel(main_window, pfade[0]), LINKS, pos=IN_KACHEL)
    qtbot.mouseClick(_kachel(main_window, pfade[1]), LINKS, STRG, pos=IN_KACHEL)
    qtbot.mouseClick(_kachel(main_window, pfade[2]), LINKS, STRG, pos=IN_KACHEL)
    assert len(main_window.selected_pdfs) == 3

    qtbot.mousePress(_kachel(main_window, pfade[1]), LINKS, pos=IN_KACHEL)
    assert len(main_window.selected_pdfs) == 3  # erst beim Loslassen - vielleicht wird gezogen
    qtbot.mouseRelease(_kachel(main_window, pfade[1]), LINKS, pos=IN_KACHEL)
    assert main_window.selected_pdf == pfade[1] and main_window.selected_pdfs == []
    assert _markiert(main_window) == [pfade[1]]

    qtbot.mouseClick(_kachel(main_window, pfade[1]), LINKS, pos=IN_KACHEL)
    assert main_window.selected_pdf == pfade[1] and _markiert(main_window) == [pfade[1]]


def test_ziehen_der_markierten_kachel_behaelt_die_auswahl(qtbot, main_window, fresh_singletons, monkeypatch):
    pfade, _, _ = _aufbauen(qtbot, main_window, fresh_singletons, monkeypatch)
    kachel = _kachel(main_window, pfade[1])
    gezogen: list = []
    monkeypatch.setattr(kachel, "_start_drag", lambda: gezogen.append(main_window.selected_pdf))
    qtbot.mouseClick(kachel, LINKS, pos=IN_KACHEL)

    qtbot.mousePress(kachel, LINKS, pos=IN_KACHEL)
    weit = IN_KACHEL + QPoint(QApplication.startDragDistance() + 20, 0)
    qtbot.mouseMove(kachel, weit)
    from PyQt6.QtCore import QEvent, QPointF
    from PyQt6.QtGui import QMouseEvent
    QApplication.sendEvent(kachel, QMouseEvent(
        QEvent.Type.MouseMove, QPointF(weit), QPointF(kachel.mapToGlobal(weit)),
        Qt.MouseButton.NoButton, LINKS, Qt.KeyboardModifier.NoModifier))
    qtbot.mouseRelease(kachel, LINKS, pos=weit)

    assert gezogen and gezogen[0] == pfade[1]  # beim Start des Ziehens war sie (noch) markiert
    assert main_window.selected_pdf == pfade[1] and _markiert(main_window) == [pfade[1]]


def test_doppelklick_oeffnet_und_laesst_die_kachel_markiert(qtbot, main_window, fresh_singletons, monkeypatch):
    pfade, _, doppelklicks = _aufbauen(qtbot, main_window, fresh_singletons, monkeypatch)

    # Doppelklick auf eine noch nicht markierte Kachel: Druck, Loslassen, Doppelklick, Loslassen
    qtbot.mouseClick(_kachel(main_window, pfade[3]), LINKS, pos=IN_KACHEL)
    qtbot.mouseDClick(_kachel(main_window, pfade[3]), LINKS, pos=IN_KACHEL)
    assert doppelklicks == [pfade[3]]
    assert main_window.selected_pdf == pfade[3] and _markiert(main_window) == [pfade[3]]

    # und auf die schon markierte: frueher waehlte der erste Druck sie ab
    qtbot.mouseClick(_kachel(main_window, pfade[3]), LINKS, pos=IN_KACHEL)
    qtbot.mouseDClick(_kachel(main_window, pfade[3]), LINKS, pos=IN_KACHEL)
    assert doppelklicks == [pfade[3], pfade[3]]
    assert main_window.selected_pdf == pfade[3] and _markiert(main_window) == [pfade[3]]


def test_strg_a_und_auswahl_aufheben_unveraendert(qtbot, main_window, fresh_singletons, monkeypatch):
    pfade, _, _ = _aufbauen(qtbot, main_window, fresh_singletons, monkeypatch)
    qtbot.mouseClick(_kachel(main_window, pfade[1]), LINKS, pos=IN_KACHEL)

    main_window.select_all_action.trigger()
    assert set(main_window.selected_pdfs) == set(pfade)
    assert main_window.selected_pdf == pfade[1]  # die aktive bleibt die aktive

    main_window._clear_selection()
    assert main_window.selected_pdf is None and _markiert(main_window) == []

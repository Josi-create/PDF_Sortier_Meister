"""Hauptfenster-Splitter: stufenlos ziehbar, Griffe greifbar (Issue #188).

Beim Anzeigen ueber Remote Desktop (grosse Schrift/Skalierung) summierten sich
die inhaltsabhaengigen Mindestbreiten der drei Spalten auf mehr als die
Fensterbreite. Dann liess sich ein Griff nicht greifen oder das Fenster sprang.
"""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QSplitter, QWidget

from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401


def _splitter(win) -> QSplitter:
    return win.main_splitter


def _zeige(win, breite: int, hoehe: int = 720) -> QSplitter:
    # MainWindow.show() ist in der Fixture ersetzt: Basisklasse direkt aufrufen
    win.resize(breite, hoehe)
    QWidget.show(win)
    win.centralWidget().layout().activate()
    return _splitter(win)


def _mindestbreiten(sp: QSplitter) -> int:
    summe = 0
    for i in range(sp.count()):
        w = sp.widget(i)
        summe += max(w.minimumWidth(), w.minimumSizeHint().width() if w.minimumWidth() == 0 else 0)
    return summe + sp.handleWidth() * (sp.count() - 1)


@pytest.mark.parametrize("breite", [1024, 1280])
def test_mindestbreiten_summe_passt_ins_fenster(main_window, breite):
    sp = _zeige(main_window, breite)
    assert _mindestbreiten(sp) < breite
    assert not sp.childrenCollapsible()


def test_inhalt_treibt_mindestbreite_nicht_hoch(main_window):
    """Langer Ordnername und viele Vorschlags-Chips duerfen die Spalten nicht verbreitern."""
    sp = _zeige(main_window, 1024)
    main_window.pdf_header.setText("PDFs in: " + "Sehr langer Ordnername " * 6)
    for i in range(8):
        from PyQt6.QtWidgets import QPushButton

        main_window.suggestions_layout.addWidget(QPushButton(f"Vorschlag Nummer {i} mit Text"))
    main_window.centralWidget().layout().activate()
    assert _mindestbreiten(sp) < 1024


@pytest.mark.parametrize("breite", [1024, 1280])
def test_griffe_stufenlos_ohne_springen(main_window, breite):
    sp = _zeige(main_window, breite)
    gesamt = sum(sp.sizes())
    for handle in (1, 2):
        lo, hi = sp.getRange(handle)
        assert hi - lo > 60, f"Griff {handle} hat kaum Spielraum: {lo}..{hi}"
        for pos in range(lo + 10, hi - 10, max((hi - lo) // 7, 1)):
            sp.moveSplitter(pos, handle)
            erreicht = sp.sizes()
            # Position des Griffs = Summe der Breiten davor (+ Griffbreiten davor)
            ist = sum(erreicht[:handle]) + sp.handleWidth() * (handle - 1)
            assert ist == pos, f"Griff {handle}: Ziel {pos}, erreicht {ist}"
            assert sum(erreicht) == gesamt
            # Mindestbreiten bleiben gewahrt
            assert all(
                g >= sp.widget(i).minimumWidth() for i, g in enumerate(erreicht)
            )


def test_kein_setsizes_durch_rueckkopplung(main_window, monkeypatch):
    """Raster-Neuberechnung und Verschieben duerfen den Splitter nicht per setSizes veraendern."""
    sp = _zeige(main_window, 1024)
    aufrufe = []
    original = QSplitter.setSizes
    monkeypatch.setattr(QSplitter, "setSizes", lambda self, s: (aufrufe.append(s), original(self, s)))
    lo, hi = sp.getRange(1)
    for pos in range(lo + 20, hi - 20, 40):
        sp.moveSplitter(pos, 1)
        main_window._relayout_pdf_grid(force=True)
    main_window.resize(1100, 720)
    main_window._relayout_pdf_grid(force=True)
    assert aufrufe == []

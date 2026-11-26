"""Issue #349: Das Suchfeld der Werkzeugleiste und das Feld im Reiter „Suche“ zeigen denselben Text."""
from __future__ import annotations

from PyQt6.QtWidgets import QApplication, QWidget

from tests.test_search_view_metadaten_gui import hauptfenster, index_konfig  # noqa: F401 (Fixtures)


def test_text_oben_und_im_reiter_bleibt_gleich(qtbot, hauptfenster):  # noqa: F811
    win = hauptfenster
    oben, unten = win.search_input, win.search_view.search_edit

    # Kurze Eingabe oben (noch keine Suche): steht schon unten
    oben.setText("S")
    assert unten.text() == "S"
    assert win.center_tabs.currentWidget() is not win.search_view

    # Weiter oben getippt: Sprung in den Reiter, beide Felder gleich
    with qtbot.waitSignal(win.search_view.suche_fertig, timeout=15000):
        oben.setText("Stadtwerke")
    assert win.center_tabs.currentWidget() is win.search_view
    assert unten.text() == oben.text() == "Stadtwerke"

    # Im Reiter weitergetippt: oben steht derselbe Text, ohne dass oben eine zweite Suche startet
    aufrufe = []
    win.search_view.suchen = lambda *a, **k: aufrufe.append(a)
    unten.setText("Stadtwerke Strom")
    assert oben.text() == "Stadtwerke Strom"
    assert aufrufe == []
    del win.search_view.suchen

    # Im Reiter geleert: oben ebenfalls leer
    unten.clear()
    assert oben.text() == ""


def test_gespeicherte_suche_setzt_text_auch_oben(qtbot, hauptfenster):  # noqa: F811
    win = hauptfenster
    view = win.search_view
    view.suchzustand_setzen({"text": "Telekom"})   # setzt das Feld ohne Signal
    with qtbot.waitSignal(view.suche_fertig, timeout=15000):
        view._suche_starten()
    assert win.search_input.text() == "Telekom"


def test_fokus_bleibt_beim_tippen_oben(qtbot, hauptfenster):  # noqa: F811
    win = hauptfenster
    QWidget.show(win)
    win.activateWindow()
    win.search_input.setFocus()
    qtbot.waitUntil(lambda: QApplication.focusWidget() is win.search_input, timeout=3000)
    with qtbot.waitSignal(win.search_view.suche_fertig, timeout=15000):
        qtbot.keyClicks(win.search_input, "Rech")
    assert win.center_tabs.currentWidget() is win.search_view
    assert QApplication.focusWidget() is win.search_input
    qtbot.keyClicks(win.search_input, "nung")
    assert win.search_input.text() == win.search_view.search_edit.text() == "Rechnung"

"""Issue #349: Das Suchfeld der Werkzeugleiste und das Feld im Reiter „Suche“ zeigen denselben Text."""
from __future__ import annotations

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
    # Ohne aktives Fenster (CI, offscreen) gibt es keinen echten Fokus: Reihenfolge der Aufrufe pruefen
    win = hauptfenster
    oben, unten = win.search_input, win.search_view.search_edit
    fokus = []
    oben.hasFocus = lambda: True
    oben.setFocus = lambda *a: fokus.append("oben")
    unten.setFocus = lambda *a: fokus.append("unten")
    with qtbot.waitSignal(win.search_view.suche_fertig, timeout=15000):
        qtbot.keyClicks(oben, "Rech")
    assert win.center_tabs.currentWidget() is win.search_view
    assert fokus and fokus[-1] == "oben"
    qtbot.keyClicks(oben, "nung")
    assert oben.text() == unten.text() == "Rechnung"


def test_fokus_wechselt_ohne_eingabe_oben_in_den_reiter(qtbot, hauptfenster):  # noqa: F811
    win = hauptfenster
    fokus = []
    win.search_input.hasFocus = lambda: False
    win.search_input.setFocus = lambda *a: fokus.append("oben")
    win.search_view.search_edit.setFocus = lambda *a: fokus.append("unten")
    with qtbot.waitSignal(win.search_view.suche_fertig, timeout=15000):
        win.search_input.setText("Telekom")
    assert fokus == ["unten"]

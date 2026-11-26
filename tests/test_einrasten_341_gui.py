"""Issue #341: Trennlinien rasten beim Loslassen ein.

* Linie zwischen Vorschlaegen und Ordnerbaum: auf ganze Reihen von Vorschlagskacheln oder
  knapp unter die letzte Reihe (dann wieder passend zum Inhalt).
* Linie zwischen linker Spalte und Mitte: links eine ganze Zahl von Kachelspalten
  (Vorgabe des CEO), die Mindestbreite von 300 px bleibt.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from src.gui.einrasten import reihen_hoehe, spalten_breite
from src.gui.main_window import MainWindow
from src.gui.vorschlag_liste import ABSTAND, ZEILEN_HOEHE, VorschlagListe, VorschlagTeiler
from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401

REIHE = ZEILEN_HOEHE + ABSTAND


def _reihen(k: int) -> int:
    return k * REIHE - ABSTAND


# --- reihen_hoehe -------------------------------------------------------------

@pytest.mark.parametrize("gezogen,erwartet", [
    (_reihen(2), _reihen(2)),          # liegt schon richtig
    (_reihen(2) + 20, _reihen(2)),     # knapp darunter: zurueck auf zwei Reihen
    (_reihen(2) + 30, _reihen(3)),     # mehr als die Haelfte der dritten Reihe: drei
    (10, _reihen(1)),                  # nie weniger als eine Reihe
    (_reihen(5) - 3, _reihen(5)),      # knapp ueber der letzten Reihe: alle
    (_reihen(5) + 200, _reihen(5)),    # weit darunter: kein leerer Streifen
])
def test_reihen_hoehe(gezogen, erwartet):
    assert reihen_hoehe(gezogen, _reihen(5), ZEILEN_HOEHE, ABSTAND, 10_000) == erwartet


def test_reihen_hoehe_laesst_dem_baum_seinen_platz():
    # alle fuenf Reihen passen nicht: hoechstens so viele ganze Reihen, wie Platz haben
    assert reihen_hoehe(_reihen(5) + 50, _reihen(5), ZEILEN_HOEHE, ABSTAND, _reihen(3) + 10) == _reihen(3)


# --- spalten_breite -----------------------------------------------------------

def _spalten(n, kachel=104, abstand=10):
    return n * kachel + (n - 1) * abstand


@pytest.mark.parametrize("frei,erwartet", [
    (_spalten(3), _spalten(3)),
    (_spalten(3) + 40, _spalten(3)),   # leerer Streifen: zurueck
    (_spalten(3) + 70, _spalten(4)),   # mehr als halbe Kachel: eine Spalte dazu
    (_spalten(1) - 50, _spalten(1)),
])
def test_spalten_breite(frei, erwartet):
    assert spalten_breite(frei, 104, 10, unten=0, oben=10_000) == erwartet


def test_spalten_breite_haelt_die_grenzen():
    # Mindestbreite links: lieber eine Spalte mehr als darunter
    assert spalten_breite(_spalten(2) + 10, 104, 10, unten=_spalten(2) + 5, oben=10_000) == _spalten(3)
    # Mitte am Minimum: lieber eine Spalte weniger
    assert spalten_breite(_spalten(3) + 70, 104, 10, unten=0, oben=_spalten(3) + 80) == _spalten(3)
    # nichts passt: unveraendert
    assert spalten_breite(_spalten(2) + 30, 104, 10, unten=_spalten(2) + 20, oben=_spalten(2) + 40) == _spalten(2) + 30


# --- Trennlinie ueber dem Ordnerbaum ------------------------------------------

def _sug(tmp_path, i):
    return SimpleNamespace(folder_path=tmp_path / f"Ordner {i}", folder_name=f"Ordner {i}",
                           relative_path=f"Ordner {i}", reason="x", confidence=0.9 - i * 0.01)


@pytest.fixture
def teiler(qtbot, tmp_path):
    host = QWidget()
    qtbot.addWidget(host)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    liste = VorschlagListe()
    unten = QLabel("Baum")
    t = VorschlagTeiler(liste, unten)
    lay.addWidget(t)
    fake = SimpleNamespace(suggestions_layout=liste.spalten, suggestion_widgets=[],
                           no_suggestions_label=QLabel("x"))
    liste.spalten.addWidget(fake.no_suggestions_label)
    fake.clear_suggestions = lambda: MainWindow.clear_suggestions(fake)
    fake.on_suggestion_clicked = fake.on_folder_double_clicked = fake.on_pdf_dropped_on_folder = lambda *a: None
    fake.verbinde_hierhin_kopieren = fake.verbinde_zielkachel = lambda widget: None
    host.resize(300, 900)  # eine Spalte: sieben Reihen
    host.show()
    qtbot.waitExposed(host)
    MainWindow.display_suggestions(fake, [_sug(tmp_path, i) for i in range(7)])
    qtbot.waitUntil(lambda: t.sizes()[0] == liste.bedarf(), timeout=3000)
    assert liste.bedarf() == _reihen(7)
    yield t
    host.close()


def _ziehen_und_loslassen(qtbot, t, hoehe):
    t.moveSplitter(hoehe, 1)
    QTest.mouseRelease(t.handle(1), Qt.MouseButton.LeftButton)
    qtbot.wait(50)


def test_rastet_auf_ganzer_reihe_ein(qtbot, teiler):
    _ziehen_und_loslassen(qtbot, teiler, _reihen(3) + 15)
    assert teiler.sizes()[0] == _reihen(3) and teiler.manuelle_hoehe() == _reihen(3)
    _ziehen_und_loslassen(qtbot, teiler, _reihen(2) + 30)
    assert teiler.sizes()[0] == _reihen(3)


def test_unter_der_letzten_reihe_wieder_passend(qtbot, teiler):
    _ziehen_und_loslassen(qtbot, teiler, _reihen(2))
    assert teiler.manuelle_hoehe() == _reihen(2)
    _ziehen_und_loslassen(qtbot, teiler, _reihen(7) + 120)
    assert teiler.manuelle_hoehe() is None  # wie Doppelklick
    assert teiler.sizes()[0] == _reihen(7)  # kein leerer Streifen


def test_klick_ohne_ziehen_aendert_nichts(qtbot, teiler):
    QTest.mouseRelease(teiler.handle(1), Qt.MouseButton.LeftButton)
    qtbot.wait(50)
    assert teiler.manuelle_hoehe() is None and teiler.sizes()[0] == _reihen(7)


# --- Linie zwischen linker Spalte und Mitte -----------------------------------

def _frei(win) -> int:
    m = win.pdf_container.layout().contentsMargins()
    return win._scan_viewport_width() - m.left() - m.right()


def test_linke_spalte_rastet_auf_ganze_kachelspalten(main_window, qtbot):  # noqa: F811
    win = main_window
    QWidget.show(win)
    win.resize(1500, 900)
    qtbot.waitExposed(win)
    win.empty_label.hide()
    win.pdf_scroll_area.show()  # sonst "Kein Scan-Ordner ausgewaehlt"
    qtbot.wait(100)
    kachel = win._tile_view.tile_w
    abstand = win.pdf_layout.horizontalSpacing()
    for links in (437, 530, 301):
        gesamt = sum(win.main_splitter.sizes())
        win.main_splitter.moveSplitter(links, 1)
        QTest.mouseRelease(win.main_splitter.handle(1), Qt.MouseButton.LeftButton)
        qtbot.wait(100)
        frei = _frei(win)
        assert (frei + abstand) % (kachel + abstand) == 0, (links, frei)
        assert win.main_splitter.sizes()[0] >= 300
        assert sum(win.main_splitter.sizes()) == gesamt


def test_linke_spalte_ohne_ziehen_oder_im_chat_bleibt(main_window, qtbot):  # noqa: F811
    win = main_window
    QWidget.show(win)
    win.resize(1500, 900)
    qtbot.waitExposed(win)
    win.main_splitter.setSizes([437, 600, 463])
    qtbot.wait(50)
    vorher = win.main_splitter.sizes()
    win._links_gezogen = True
    win.linke_spalte_einrasten()  # ohne Scan-Ordner: keine Kacheln
    assert win.main_splitter.sizes() == vorher
    win.empty_label.hide()
    win.pdf_scroll_area.show()
    qtbot.wait(50)
    win.linke_spalte_einrasten()  # nicht gezogen
    assert win.main_splitter.sizes() == vorher
    win.left_tabs.setCurrentIndex(1)  # Chat: keine Kacheln
    win._links_gezogen = True
    win.linke_spalte_einrasten()
    assert win.main_splitter.sizes() == vorher

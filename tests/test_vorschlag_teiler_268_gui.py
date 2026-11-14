"""Vorgeschlagene Ziele ohne Scrollen, Trennlinie zum Ordnerbaum ziehbar (Issue #268)."""

from pathlib import Path
from types import SimpleNamespace

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTreeWidget, QVBoxLayout, QWidget

from src.gui.vorschlag_liste import ABSTAND, ZEILEN_HOEHE, VorschlagListe, VorschlagTeiler, VorschlagZeile
from tests.test_auto_next_after_move_gui import fresh_singletons, main_window  # noqa: F401


def _hoehe(reihen: int) -> int:
    return reihen * ZEILEN_HOEHE + (reihen - 1) * ABSTAND


def _fuellen(liste, tmp_path, n):
    while liste.spalten.count():
        item = liste.spalten.takeAt(0)
        item.widget().setParent(None)
    for i in range(n):
        liste.spalten.addWidget(VorschlagZeile(tmp_path / f"Ordner {i}"))


def _aufbau(qtbot, tmp_path, n, breite, hoehe):
    host = QWidget()
    qtbot.addWidget(host)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    liste = VorschlagListe()
    teiler = VorschlagTeiler(liste, QTreeWidget())
    lay.addWidget(teiler)
    _fuellen(liste, tmp_path, n)
    host.resize(breite, hoehe)
    host.show()
    qtbot.wait(30)
    return host, teiler, liste


def test_acht_vorschlaege_ohne_scrollen(qtbot, tmp_path):
    host, teiler, liste = _aufbau(qtbot, tmp_path, 8, 300, 900)  # eine Spalte: 8 Reihen
    qtbot.waitUntil(lambda: teiler.sizes()[0] == _hoehe(8), timeout=2000)
    assert liste.verticalScrollBar().maximum() == 0


def test_grenzbreite_bleibt_nicht_an_der_bildlaufleiste_haengen(qtbot, tmp_path):
    """440 px: zwei Spalten nur ohne Bildlaufleiste - sie darf die Spaltenzahl nicht druecken."""
    host, teiler, liste = _aufbau(qtbot, tmp_path, 8, 300, 320)  # erst zu klein: scrollt
    qtbot.waitUntil(lambda: liste.verticalScrollBar().maximum() > 0, timeout=2000)
    host.resize(440, 900)
    qtbot.waitUntil(lambda: teiler.sizes()[0] == _hoehe(4), timeout=2000)
    qtbot.waitUntil(lambda: liste.verticalScrollBar().maximum() == 0, timeout=2000)
    assert len({w.x() for w in liste.inhalt.findChildren(VorschlagZeile)}) == 2


def test_breite_und_anzahl_aendern_passt_hoehe_an(qtbot, tmp_path):
    host, teiler, liste = _aufbau(qtbot, tmp_path, 8, 300, 900)
    host.resize(500, 900)  # zwei Spalten: 4 Reihen
    qtbot.waitUntil(lambda: teiler.sizes()[0] == _hoehe(4), timeout=2000)
    _fuellen(liste, tmp_path, 3)  # 2 Reihen
    qtbot.waitUntil(lambda: teiler.sizes()[0] == _hoehe(2), timeout=2000)
    qtbot.waitUntil(lambda: liste.verticalScrollBar().maximum() == 0, timeout=2000)


def test_kleines_fenster_laesst_dem_baum_platz(qtbot, tmp_path):
    host, teiler, liste = _aufbau(qtbot, tmp_path, 8, 300, 320)
    qtbot.waitUntil(lambda: liste.verticalScrollBar().maximum() > 0, timeout=2000)
    oben, unten = teiler.sizes()
    assert unten >= VorschlagTeiler.UNTEN_MIN
    assert ZEILEN_HOEHE <= oben < _hoehe(8)


def test_trennlinie_ziehen_und_doppelklick(qtbot, tmp_path):
    host, teiler, liste = _aufbau(qtbot, tmp_path, 8, 300, 900)
    qtbot.waitUntil(lambda: teiler.sizes()[0] == _hoehe(8), timeout=2000)
    griff = teiler.handle(1)
    assert griff.cursor().shape() == Qt.CursorShape.SplitVCursor
    assert not teiler.childrenCollapsible()

    teiler.moveSplitter(200, 1)  # wie Ziehen mit der Maus
    assert teiler.sizes()[0] == 200 and teiler.manuelle_hoehe() == 200
    qtbot.waitUntil(lambda: liste.verticalScrollBar().maximum() > 0, timeout=2000)  # Darstellung folgt
    assert teiler.sizes()[0] == 200
    _fuellen(liste, tmp_path, 2)  # andere Auswahl: gezogene Hoehe bleibt
    qtbot.wait(30)
    assert teiler.sizes()[0] == 200

    _fuellen(liste, tmp_path, 6)
    qtbot.mouseDClick(griff, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: teiler.sizes()[0] == _hoehe(6), timeout=2000)
    assert teiler.manuelle_hoehe() is None
    assert teiler.gemerkt() == (0, [])


def test_gemerkte_hoehe_nur_bei_gleicher_fenstergroesse(qtbot, tmp_path):
    host, teiler, liste = _aufbau(qtbot, tmp_path, 4, 300, 900)
    teiler.merken(260, [300, 900])
    assert teiler.sizes()[0] == 260
    assert teiler.gemerkt() == (260, [300, 900])

    host2, teiler2, _ = _aufbau(qtbot, tmp_path, 4, 300, 800)  # Fenster anders gross
    teiler2.merken(260, [300, 900])
    assert teiler2.sizes()[0] == _hoehe(4)
    assert teiler2.gemerkt() == (260, [300, 900])  # Merker geht nicht verloren
    teiler2.merken("kaputt", None)  # beschaedigte Konfiguration stoert nicht
    teiler2.merken(0, [])
    assert teiler2.sizes()[0] == _hoehe(4)


def test_hauptfenster_speichert_gezogene_hoehe(main_window, fresh_singletons):
    win = main_window
    assert win.vorschlag_teiler.widget(0) is win.suggestions_container
    win.resize(1200, 800)
    QWidget.show(win)  # MainWindow.show() ist in der Fixture ersetzt
    win.centralWidget().layout().activate()
    win.vorschlag_teiler.moveSplitter(180, 1)
    win.save_settings()
    cfg = fresh_singletons["config"]
    assert cfg.get("vorschlaege_hoehe") == 180
    assert cfg.get("vorschlaege_hoehe_fenster") == [win.width(), win.height()]
    win.vorschlag_teiler.automatisch()
    win.save_settings()
    assert cfg.get("vorschlaege_hoehe") == 0 and cfg.get("vorschlaege_hoehe_fenster") == []


def test_nie_mehr_vorschlaege_als_eingestellt(main_window, fresh_singletons, monkeypatch):
    """KI-, Einheiten- und Neuer-Ordner-Vorschlag kamen zusaetzlich zu "Max. Vorschläge"."""
    tmp = fresh_singletons["tmp_path"]
    fresh_singletons["config"].set("max_suggestions", 6)

    def sug(name, conf, neu=""):
        p = tmp / "Ablage" / name
        s = SimpleNamespace(folder_path=p, folder_name=name, relative_path=f"Ablage/{name}",
                            reason="x", confidence=conf)
        if neu:
            s.new_source = neu
        return s

    basis = [sug(f"Ordner {i}", 0.8 - i * 0.05) for i in range(6)]
    ki, neu = sug("KI", 0.9), sug("Neu 2027", 0.4, neu="jahr")
    monkeypatch.setattr(main_window, "_with_existing_ki_folder", lambda p, s, d=None: [ki, *s])
    monkeypatch.setattr(main_window, "_with_einheit_folder", lambda p, s, d=None: list(s))
    monkeypatch.setattr(main_window, "_with_new_folder", lambda p, s, d=None: [neu, *s])
    out = main_window._with_ki_folder(Path(tmp / "Scan" / "a.pdf"), basis)
    assert len(out) == 6
    # der neue Ordner und der KI-Ordner bleiben, die schwaechsten fallen weg
    assert [s.folder_name for s in out] == ["Neu 2027", "KI", "Ordner 0", "Ordner 1", "Ordner 2", "Ordner 3"]

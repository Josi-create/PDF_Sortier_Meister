"""Kompakte Vorschlagsliste (rechte Spalte) und Reihenfolge der Vorschlaege."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QMimeData, QUrl
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from src.core import neuer_ordner
from src.gui.main_window import MainWindow
from tests.test_auto_next_after_move_gui import fresh_singletons, main_window  # noqa: F401
from src.gui.vorschlag_liste import VorschlagListe, VorschlagZeile, ZEILEN_HOEHE


def _sug(tmp_path, rel, conf, neu=False):
    p = tmp_path / Path(rel)
    s = SimpleNamespace(folder_path=p, folder_name=p.name, relative_path=rel, reason="x", confidence=conf)
    if neu:
        s.new_source = neuer_ordner.QUELLE_JAHR
    return s


def _aufbau(qtbot, tmp_path, n, breite, rels=None):
    host = QWidget()
    qtbot.addWidget(host)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    liste = VorschlagListe()
    lay.addWidget(liste)
    lay.addStretch(1)
    fake = SimpleNamespace()
    fake.suggestions_layout = liste.spalten
    fake.suggestion_widgets = []
    fake.no_suggestions_label = QLabel("x")
    liste.spalten.addWidget(fake.no_suggestions_label)
    fake.clear_suggestions = lambda: MainWindow.clear_suggestions(fake)
    fake.on_suggestion_clicked = fake.on_folder_double_clicked = fake.on_pdf_dropped_on_folder = lambda *a: None
    fake.verbinde_hierhin_kopieren = lambda widget: None
    host.resize(breite, 400)
    host.show()
    rels = rels or [f"Ablage/Ordner {i}" for i in range(n)]
    MainWindow.display_suggestions(fake, [_sug(tmp_path, r, 0.9 - i * 0.05) for i, r in enumerate(rels)])
    host.resize(breite + 1, 400)  # Layout neu anstossen
    host.resize(breite, 400)
    qtbot.wait(20)
    return host, liste, fake


def _geoms(fake):
    return [w.geometry() for w in fake.suggestion_widgets]


@pytest.mark.parametrize("breite,spalten", [(300, 1), (500, 2), (800, 3)])
def test_sieben_vorschlaege_ueberlappen_nicht(qtbot, tmp_path, breite, spalten):
    host, liste, fake = _aufbau(qtbot, tmp_path, 7, breite)
    g = _geoms(fake)
    for i in range(len(g)):
        for j in range(i + 1, len(g)):
            assert not g[i].intersects(g[j]), (i, j, g[i], g[j])
    assert len({r.x() for r in g}) == spalten
    assert all(r.height() == ZEILEN_HOEHE for r in g)
    # zeilenweise: Rang 0 links oben, Rang 1 daneben (bei >1 Spalte)
    assert (g[0].x(), g[0].y()) == (0, 0)
    if spalten > 1:
        assert g[1].y() == 0 and g[1].x() > 0
    else:
        assert g[1].y() > 0


def test_breite_aendern_verteilt_neu(qtbot, tmp_path):
    host, liste, fake = _aufbau(qtbot, tmp_path, 7, 800)
    assert len({r.x() for r in _geoms(fake)}) == 3
    host.resize(500, 400)
    qtbot.wait(20)
    assert len({r.x() for r in _geoms(fake)}) == 2
    host.resize(300, 400)
    qtbot.wait(20)
    assert len({r.x() for r in _geoms(fake)}) == 1


def test_mindestbreite_klein_und_scroll_nur_bei_vielen(qtbot, tmp_path):
    host, liste, fake = _aufbau(qtbot, tmp_path, 7, 300)
    assert liste.minimumSizeHint().width() < 240 and liste.minimumWidth() == 0
    assert liste.spalten.minimumSize().width() < 240
    # 7 Reihen > 3 sichtbare; der Scrollbereich steht erst nach dem Layout (macOS-CI langsamer)
    qtbot.waitUntil(lambda: liste.verticalScrollBar().maximum() > 0, timeout=2000)
    host2, liste2, _ = _aufbau(qtbot, tmp_path, 2, 500)
    assert liste2.verticalScrollBar().maximum() == 0


def test_langer_pfad_gekuerzt_tooltip_voll(qtbot, tmp_path):
    lang = "Ablage/" + "/".join(["Sehr langer Unterordner"] * 5) + "/Ziel"
    host, liste, fake = _aufbau(qtbot, tmp_path, 1, 300, rels=[lang])
    z = fake.suggestion_widgets[0]
    assert z._zeilen[2].endswith("Ziel") and "<b>" in z.name_label.text()  # Ziel unten, fett
    assert z.path_label.text() and z.path_label.text() != z._pfad_voll  # oben gekuerzter Anfang
    assert str(tmp_path / Path(lang)) in z.toolTip()  # voller Pfad samt Laufwerk


def test_regenbogen_und_neu(qtbot, tmp_path):
    host = QWidget()
    qtbot.addWidget(host)
    z = VorschlagZeile(tmp_path / "A")
    z.setParent(host)
    z.set_regenbogen(True)
    assert z.regenbogen
    z.set_regenbogen(False)
    z.is_suggestion = True
    z.set_neu(True)
    assert z.neu and "dashed" in z.styleSheet()
    assert not z.acceptDrops()


def test_klick_doppelklick_drop_menue(qtbot, tmp_path):
    from PyQt6.QtCore import Qt
    zeile = VorschlagZeile(tmp_path / "Ziel")
    qtbot.addWidget(zeile)
    zeile.is_suggestion = True
    zeile.resize(250, ZEILEN_HOEHE)
    zeile.show()
    with qtbot.waitSignal(zeile.clicked):
        qtbot.mouseClick(zeile, Qt.MouseButton.LeftButton)
    with qtbot.waitSignal(zeile.double_clicked):
        qtbot.mouseDClick(zeile, Qt.MouseButton.LeftButton)
    assert zeile.acceptDrops()
    texte = [a.text() for a in zeile._build_context_menu().actions()]
    assert any("hierhin kopieren" in t.lower() for t in texte)
    assert not any("entfernen" in t for t in texte)


# --- Reihenfolge --------------------------------------------------------------

def _ordnen(pdf, sugs):
    return MainWindow._ordnen(pdf, sugs)


def test_ordnen_konfidenz_absteigend_stabil(tmp_path):
    a, b, c = (_sug(tmp_path, r, k) for r, k in (("A", 0.7), ("B", 0.85), ("C", 0.7)))
    out = _ordnen(tmp_path / "x" / "a.pdf", [a, b, c])
    assert out == [b, a, c]


def test_ordnen_neuer_ordner_bleibt_vorne(tmp_path):
    neu = _sug(tmp_path, "Neu", 0.3, neu=True)
    b = _sug(tmp_path, "B", 0.95)
    assert _ordnen(tmp_path / "x" / "a.pdf", [b, neu])[0] is neu


def test_ordnen_eigener_ordner_fehlt(tmp_path):
    eigener = _sug(tmp_path, "Eingang", 0.99)
    b = _sug(tmp_path, "B", 0.5)
    pdf = tmp_path / "EINGANG" / "a.pdf"  # andere Schreibweise
    assert _ordnen(pdf, [eigener, b]) == [b]


def test_ki_ordner_70_steht_nicht_vor_85(main_window, fresh_singletons, monkeypatch):
    tmp = fresh_singletons["tmp_path"]
    ordner = tmp / "Ablage"
    for n in ("KI", "Klassifikator", "Bestaetigt"):
        (ordner / n).mkdir(parents=True)
    pdf = tmp / "Scan" / "a.pdf"
    ki = _sug(ordner, "KI", 0.7)
    ki.folder_path = ordner / "KI"
    kl = _sug(ordner, "Klassifikator", 0.85)
    kl.folder_path = ordner / "Klassifikator"
    monkeypatch.setattr(main_window, "_with_existing_ki_folder", lambda p, s, d=None: [ki, *s])
    monkeypatch.setattr(main_window, "_with_new_folder", lambda p, s, d=None: list(s))
    out = main_window._with_ki_folder(pdf, [kl])
    assert [s.folder_name for s in out] == ["Klassifikator", "KI"]
    bestaetigt = _sug(ordner, "Bestaetigt", 0.9)
    monkeypatch.setattr(main_window, "_with_existing_ki_folder", lambda p, s, d=None: [bestaetigt, *s])
    assert main_window._with_ki_folder(pdf, [kl])[0] is bestaetigt

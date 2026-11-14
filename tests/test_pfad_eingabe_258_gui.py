"""Issue #258: Laufwerk als Zielordner hat einen Namen; Pfad eingeben, hineinspringen, hinzufuegen."""
import os
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from src.core.ordnersuche import anzeigename, pfad_eingabe
from src.gui.folder_tree_widget import FolderTreeWidget
from src.gui.ordner_suchfeld import OrdnerSuchfeld
from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401 - Fixtures


def _ablage(tmp_path):
    """Ablage/{Bänke, Banken/2024, Steuer} ausserhalb der Zielordner, daneben Ziel/Rest."""
    ablage = tmp_path / "Ablage"
    for p in ("Bänke", "Banken/2024", "Steuer", ".versteckt"):
        (ablage / p).mkdir(parents=True)
    (tmp_path / "Ziel" / "Rest").mkdir(parents=True)
    return ablage, tmp_path / "Ziel"


# ------------------------------------------------------------------ Kern
def test_laufwerk_hat_einen_anzeigenamen(tmp_path):
    laufwerk = Path(tmp_path.anchor)  # "C:\" bzw. "/"
    assert laufwerk.name == ""
    assert anzeigename(laufwerk) == tmp_path.anchor
    assert anzeigename(tmp_path / "Ziel") == "Ziel"
    assert FolderTreeWidget._item_text(laufwerk, 0) == f"📁 {tmp_path.anchor}"
    assert FolderTreeWidget._item_text(laufwerk, 3) == f"📁 {tmp_path.anchor}  [3]"


def test_relativer_pfad_bei_laufwerk_als_zielordner(qtbot, tmp_path):
    laufwerk = Path(tmp_path.anchor)
    w = FolderTreeWidget()
    qtbot.addWidget(w)
    w._root_folders = [laufwerk]  # ohne Scan: das ganze Laufwerk zu lesen dauert
    assert w.get_relative_path(laufwerk) == tmp_path.anchor
    erste_ebene = laufwerk / tmp_path.parts[1]
    assert w.get_relative_path(erste_ebene) == tmp_path.parts[1]


def test_pfad_eingabe_erkennt_pfade(tmp_path):
    ablage, _ziel = _ablage(tmp_path)
    assert pfad_eingabe("zeugn*") is None
    assert pfad_eingabe("  ") is None
    assert pfad_eingabe("Ablage/Steuer") is None  # relativ: Namenssuche

    ganz = pfad_eingabe(str(ablage))
    assert ganz.ordner == ablage
    assert [k.name for k in ganz.kinder] == ["Banken", "Bänke", "Steuer"]  # ohne .versteckt
    assert pfad_eingabe(f'"{ablage}{os.sep}"') == ganz  # "Als Pfad kopieren" setzt Anfuehrungszeichen

    angefangen = pfad_eingabe(str(ablage / "ba"))
    assert angefangen.ordner is None
    assert [k.name for k in angefangen.kinder] == ["Banken"]
    assert [k.name for k in pfad_eingabe(str(ablage / "BÄ")).kinder] == ["Bänke"]

    for fehlt in (str(ablage / "gibtesnicht"), str(ablage / "nix" / "tiefer"), str(ablage / "ba") + os.sep):
        assert pfad_eingabe(fehlt).ordner is None and pfad_eingabe(fehlt).kinder == []


# -------------------------------------------------------------- Suchfeld
def _feld(qtbot, wurzeln, **kw):
    f = OrdnerSuchfeld(lambda: wurzeln, **kw)
    f._timer.setInterval(10)
    qtbot.addWidget(f)
    f.show()
    return f


def _texte(f):
    return [f.liste.item(i).text() for i in range(f.liste.count())]


def _gelistet(f):
    return lambda: f.liste.count() > 0 and f.liste.item(0).text() != "Suche …"


def test_pfad_ausserhalb_zeigt_unterordner_und_bietet_hinzufuegen(qtbot, tmp_path):
    ablage, ziel = _ablage(tmp_path)
    f = _feld(qtbot, [ziel], pfad_eingabe=True)
    hinzu, gezeigt = [], []
    f.hinzufuegen_gewuenscht.connect(hinzu.append)
    f.treffer_gewaehlt.connect(gezeigt.append)

    f.eingabe.setText(str(ablage))
    qtbot.waitUntil(_gelistet(f), timeout=5000)
    assert _texte(f) == ["➕ „Ablage“ als Zielordner hinzufügen", "    ↳ Banken", "    ↳ Bänke", "    ↳ Steuer"]

    # Unterordner anklicken springt hinein, statt etwas auszuloesen
    f.liste.itemClicked.emit(f.liste.item(1))
    assert f.eingabe.text() == str(ablage / "Banken") + os.sep
    qtbot.waitUntil(lambda: _gelistet(f)() and f.liste.count() == 2, timeout=5000)
    assert _texte(f)[1] == "    ↳ 2024"
    assert hinzu == [] and gezeigt == []

    # Pfeil runter + Enter: noch eine Ebene tiefer; dort Enter nimmt den Ordner auf
    QTest.keyClick(f.eingabe, Qt.Key.Key_Down)
    QTest.keyClick(f.eingabe, Qt.Key.Key_Return)
    assert f.eingabe.text() == str(ablage / "Banken" / "2024") + os.sep
    QTest.keyClick(f.eingabe, Qt.Key.Key_Return)  # vor Ablauf der Tipp-Pause
    assert hinzu == [ablage / "Banken" / "2024"] and gezeigt == []
    assert f.eingabe.text() == "" and not f.liste.isVisible()


def test_pfad_innerhalb_der_zielordner_wird_gezeigt_statt_angeboten(qtbot, tmp_path):
    _ablage_, ziel = _ablage(tmp_path)
    f = _feld(qtbot, [ziel], pfad_eingabe=True)
    hinzu, gezeigt = [], []
    f.hinzufuegen_gewuenscht.connect(hinzu.append)
    f.treffer_gewaehlt.connect(gezeigt.append)
    f.eingabe.setText(str(ziel / "Rest"))
    qtbot.waitUntil(_gelistet(f), timeout=5000)
    assert _texte(f) == ["📁 Rest"]
    assert f.liste.item(0).toolTip().endswith(str(ziel / "Rest"))
    QTest.keyClick(f.eingabe, Qt.Key.Key_Return)
    assert gezeigt == [ziel / "Rest"] and hinzu == []


def test_unbekannter_pfad_und_feld_ohne_pfadeingabe(qtbot, tmp_path):
    ablage, ziel = _ablage(tmp_path)
    f = _feld(qtbot, [ziel], pfad_eingabe=True)
    f.eingabe.setText(str(tmp_path / "gibtesnicht" / "x"))
    qtbot.waitUntil(_gelistet(f), timeout=5000)
    assert _texte(f) == ["Ordner nicht gefunden"]
    QTest.keyClick(f.eingabe, Qt.Key.Key_Return)  # ohne Wirkung
    assert f.eingabe.text() != ""

    # die Pfadzeile links (ohne pfad_eingabe) sucht weiter nur nach Namen
    links = _feld(qtbot, [ziel])
    links.eingabe.setText(str(ablage))
    qtbot.waitUntil(_gelistet(links), timeout=5000)
    assert _texte(links) == ["Kein Ordner gefunden"]


# ------------------------------------------------------- Baum und Fenster
def test_plus_am_suchfeld(qtbot, tmp_path):
    ablage, ziel = _ablage(tmp_path)
    w = FolderTreeWidget()
    qtbot.addWidget(w)
    w.async_scan = False
    w.set_root_folders([ziel])
    gemeldet = []
    w.zielordner_hinzufuegen.connect(gemeldet.append)

    w.add_btn.click()  # leeres Feld: Auswahldialog (None)
    w.suchfeld.eingabe.setText("rest")
    w.add_btn.click()  # Namenssuche: ebenfalls Dialog, Suchtext bleibt
    assert gemeldet == [None, None] and w.suchfeld.eingabe.text() == "rest"

    w.suchfeld.eingabe.setText(str(ablage))
    w.add_btn.click()
    assert gemeldet[2:] == [ablage] and w.suchfeld.eingabe.text() == ""

    # Teilbaum als Wurzel: ein Ordner aus den uebrigen Zielordnern wird nicht nochmal angeboten
    w.set_view_root(ziel / "Rest")
    meldungen = []
    w.status_message.connect(meldungen.append)
    w.suchfeld.hinzufuegen_gewuenscht.emit(ziel)
    w.suchfeld.hinzufuegen_gewuenscht.emit(ablage / "Steuer")
    assert gemeldet[3:] == [ablage / "Steuer"] and len(meldungen) == 1


def test_getippter_pfad_wird_zielordner(main_window, qtbot, tmp_path, monkeypatch):  # noqa: F811
    ablage, ziel = _ablage(tmp_path)
    baum = main_window.folder_tree
    baum.async_scan = False
    main_window._zielordner_aufnehmen(ziel)
    baum.suchfeld._timer.setInterval(10)

    baum.suchfeld.eingabe.setText(str(ablage))
    qtbot.waitUntil(_gelistet(baum.suchfeld), timeout=5000)
    baum.suchfeld.liste.itemClicked.emit(baum.suchfeld.liste.item(0))

    assert main_window.config.get_target_folders() == [ziel, ablage]
    assert main_window.folder_manager.target_folders == [ziel, ablage]
    assert baum.has_folder(ablage / "Banken")
    assert baum.tree.currentItem() is baum._items[ablage]  # neuer Zielordner ist markiert

    # schon Zielordner: kein zweiter Eintrag; Plus ohne Pfad oeffnet den Dialog
    main_window._on_zielordner_hinzufuegen(ablage)
    assert main_window.config.get_target_folders() == [ziel, ablage]
    dialog = []
    monkeypatch.setattr(main_window, "add_target_folder", lambda: dialog.append(1))
    baum.add_btn.click()
    assert dialog == [1]

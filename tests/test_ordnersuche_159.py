"""Issue #159: Ordnersuche (Kern, Suchfeld, Zielordner-Baum, Pfadzeile links)."""
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from src.core.ordnersuche import MAX_TREFFER, muster_zu_regex, suche_ordner
from src.gui.folder_tree_widget import FolderTreeWidget
from src.gui.ordner_suchfeld import OrdnerSuchfeld
from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401 - Fixtures


def _namen(treffer):
    return [t.name for t in treffer]


@pytest.fixture
def baum(tmp_path):
    root = tmp_path / "Ziel"
    for p in ("Anton/Zeugnisse und Unterlagen", "Berta/Arbeitszeugnisse", "Steuer/2024", "Rest"):
        (root / p).mkdir(parents=True)
    return root


# ----------------------------------------------------------------- Kern
def test_teiltreffer_ohne_grossschreibung(baum):
    assert _namen(suche_ordner([baum], "zeugn")) == ["Zeugnisse und Unterlagen", "Arbeitszeugnisse"]


def test_platzhalter(baum):
    assert _namen(suche_ordner([baum], "Zeugn*Unter")) == ["Zeugnisse und Unterlagen"]
    assert _namen(suche_ordner([baum], "202?")) == ["2024"]
    assert suche_ordner([baum], "   ") == []
    assert muster_zu_regex("a.b").search("xa.by") and not muster_zu_regex("a.b").search("axb")


def test_relativer_pfad_und_wurzel_selbst(baum):
    t = suche_ordner([baum], "zeugnisse und")[0]
    assert t.relativ == "Ziel/Anton"
    assert _namen(suche_ordner([baum], "ziel")) == ["Ziel"]
    assert suche_ordner([baum], "ziel")[0].relativ == ""


def test_tiefenbegrenzung(tmp_path):
    root = tmp_path / "R"
    (root / "a/b/c/d/e/f/g/h/i").mkdir(parents=True)
    assert _namen(suche_ordner([root], "h")) == ["h"]  # Tiefe 8
    assert suche_ordner([root], "i") == []  # Tiefe 9
    assert _namen(suche_ordner([root], "c", max_tiefe=2)) == []


def test_trefferbegrenzung(tmp_path):
    for i in range(80):
        (tmp_path / "R" / f"treffer{i:02d}").mkdir(parents=True)
    assert len(suche_ordner([tmp_path / "R"], "treffer")) == MAX_TREFFER


def test_versteckt_und_abbruch(tmp_path):
    root = tmp_path / "R"
    (root / ".git" / "gesucht").mkdir(parents=True)
    (root / "sichtbar" / "gesucht").mkdir(parents=True)
    treffer = suche_ordner([root], "gesucht")
    assert [t.pfad for t in treffer] == [root / "sichtbar" / "gesucht"]
    assert suche_ordner([root], "gesucht", abgebrochen=lambda: True) == []


def test_ueberlappende_wurzeln_ohne_doppelte(baum):
    treffer = suche_ordner([baum / "Anton", baum], "zeugn")
    assert len(treffer) == len({t.pfad for t in treffer}) == 2


# ----------------------------------------------------------- Suchfeld
def _feld(qtbot, wurzeln):
    f = OrdnerSuchfeld(lambda: wurzeln)
    f._timer.setInterval(10)
    qtbot.addWidget(f)
    f.show()
    return f


def _fertig(f, anzahl):
    return lambda: f.liste.count() == anzahl and f.liste.item(0).text() != "Suche …"


def test_suchfeld_zeigt_hinweis_treffer_und_kein_treffer(qtbot, baum):
    f = _feld(qtbot, [baum])
    f.eingabe.setText("zeugn")
    assert f.liste.item(0).text() == "Suche …"
    qtbot.waitUntil(_fertig(f, 2), timeout=5000)
    assert f.liste.item(0).text() == "Zeugnisse und Unterlagen — Ziel/Anton"
    f.eingabe.setText("gibtesnicht")
    qtbot.waitUntil(lambda: f.liste.item(0).text() == "Kein Ordner gefunden", timeout=5000)


def test_neue_eingabe_verwirft_alte_ergebnisse(qtbot, baum):
    f = _feld(qtbot, [baum])
    f.eingabe.setText("zeugn")
    f._timer.stop()
    f._suche_starten()
    alte_generation = f._generation
    f.eingabe.setText("steuer")  # bricht die laufende Suche ab
    assert f._generation > alte_generation
    f._on_fertig(alte_generation, [])  # spaetes Ergebnis der alten Suche
    assert f.liste.item(0).text() == "Suche …"
    qtbot.waitUntil(lambda: f.liste.item(0).text().startswith("Steuer"), timeout=5000)


def test_esc_leert_feld_und_liste(qtbot, baum):
    f = _feld(qtbot, [baum])
    beendet = []
    f.beendet.connect(lambda: beendet.append(1))
    f.eingabe.setText("zeugn")
    qtbot.waitUntil(_fertig(f, 2), timeout=5000)
    QTest.keyClick(f.eingabe, Qt.Key.Key_Escape)
    assert f.eingabe.text() == ""
    assert not f.liste.isVisible()
    assert beendet == [1]


def test_enter_waehlt_ersten_treffer(qtbot, baum):
    f = _feld(qtbot, [baum])
    gewaehlt = []
    f.treffer_gewaehlt.connect(gewaehlt.append)
    f.eingabe.setText("zeugn")
    QTest.keyClick(f.eingabe, Qt.Key.Key_Return)  # noch vor dem Ergebnis
    qtbot.waitUntil(lambda: bool(gewaehlt), timeout=5000)
    assert gewaehlt == [baum / "Anton" / "Zeugnisse und Unterlagen"]
    assert f.eingabe.text() == "" and not f.liste.isVisible()


# ----------------------------------------------------- Zielordner-Baum
def test_treffer_klappt_baum_auf_markiert_ohne_zu_verschieben(qtbot, tmp_path):
    root = tmp_path / "Ziel"
    ziel = root / "a/b/c/d/e/Zeugnisse und Unterlagen"
    ziel.mkdir(parents=True)
    w = FolderTreeWidget()
    qtbot.addWidget(w)
    w.async_scan = False
    w.set_root_folders([root])
    w.show()
    assert not w.has_folder(ziel)  # liegt unterhalb der Scan-Tiefe
    verschoben = []
    w.folder_selected.connect(verschoben.append)
    w.suchfeld._timer.setInterval(10)

    w.suchfeld.eingabe.setText("Zeugn*")
    qtbot.waitUntil(_fertig(w.suchfeld, 1), timeout=5000)
    w.suchfeld.liste.itemClicked.emit(w.suchfeld.liste.item(0))

    assert w.tree.currentItem() is w._items[ziel]
    assert w._items[ziel].parent().isExpanded()
    assert not w.suchfeld.liste.isVisible() and w.suchfeld.eingabe.text() == ""
    qtbot.wait(w._click_timer.interval() + 100)  # Einfachklick-Verzoegerung abwarten
    assert verschoben == []  # nichts verschoben


def test_reveal_ausserhalb_des_baums(qtbot, tmp_path):
    root = tmp_path / "Ziel"
    root.mkdir()
    w = FolderTreeWidget()
    qtbot.addWidget(w)
    w.async_scan = False
    w.set_root_folders([root])
    meldungen = []
    w.status_message.connect(meldungen.append)
    assert not w.reveal_folder(tmp_path / "woanders")
    assert meldungen


# --------------------------------------------------------- Pfadzeile links
def test_linke_suche_oeffnet_ordner_mit_history(main_window, qtbot, tmp_path):  # noqa: F811
    scan = tmp_path / "scan"
    ziel = tmp_path / "ziel" / "Anton" / "Zeugnisse und Unterlagen"
    scan.mkdir()
    ziel.mkdir(parents=True)
    main_window._navigate_to_folder(scan)
    main_window.config.add_target_folder(tmp_path / "ziel")
    feld = main_window.ordner_suche_links
    feld._timer.setInterval(10)
    assert not feld.isVisibleTo(main_window) and main_window.breadcrumb_widget.isVisibleTo(main_window)
    assert main_window.breadcrumb_widget.height() == 20

    QTest.mouseClick(main_window.breadcrumb_widget, Qt.MouseButton.LeftButton)
    assert feld.isVisibleTo(main_window) and not main_window.breadcrumb_widget.isVisibleTo(main_window)
    assert feld.height() <= 20

    feld.eingabe.setText("zeugn")
    qtbot.waitUntil(_fertig(feld, 1), timeout=5000)
    feld.liste.itemClicked.emit(feld.liste.item(0))

    assert main_window.config.get_scan_folder() == ziel
    assert main_window._folder_history[-1] == scan
    assert not feld.isVisibleTo(main_window) and main_window.breadcrumb_widget.isVisibleTo(main_window)
    main_window.on_navigate_back()
    assert main_window.config.get_scan_folder() == scan


def test_linke_suche_esc_und_rechtsklickmenue(main_window, qtbot, tmp_path):  # noqa: F811
    scan = tmp_path / "scan"
    scan.mkdir()
    main_window._navigate_to_folder(scan)
    main_window.breadcrumb_suche_btn.click()
    assert main_window.ordner_suche_links.isVisibleTo(main_window)
    QTest.keyClick(main_window.ordner_suche_links.eingabe, Qt.Key.Key_Escape)
    assert main_window.breadcrumb_widget.isVisibleTo(main_window)
    # Rechtsklick oeffnet kein Suchfeld
    QTest.mouseClick(main_window.breadcrumb_widget, Qt.MouseButton.RightButton)
    assert not main_window.ordner_suche_links.isVisibleTo(main_window)
    assert main_window.breadcrumb_widget.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu

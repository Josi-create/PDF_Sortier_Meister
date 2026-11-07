"""Issue #114: Favoriten-Leiste ueber der PDF-Ansicht."""
import json
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QMessageBox

from src.gui.favoriten_leiste import FavoritenLeiste
from src.gui.folder_tile import FolderTileWidget
from src.utils.config import Config
from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401 - Fixtures


@pytest.fixture
def cfg(tmp_path):
    return Config(config_path=tmp_path / "config.json")


@pytest.fixture
def ordner(tmp_path):
    pfade = []
    for n in ("1A Frisch gescannt", "Downloads", "Steuer"):
        p = tmp_path / "ord" / n
        p.mkdir(parents=True)
        pfade.append(p)
    return pfade


@pytest.fixture
def leiste(qtbot, cfg):
    w = FavoritenLeiste(cfg)
    qtbot.addWidget(w)
    return w


def _namen(leiste):
    return [FavoritenLeiste.anzeigename(e) for e in leiste.favoriten()]


def test_leer_ist_ausgeblendet(leiste, ordner):
    leiste.show()
    leiste.aktualisieren()
    assert not leiste.isVisible()
    leiste.hinzufuegen(ordner[0])
    assert leiste.isVisible()
    leiste.entfernen(ordner[0])
    assert not leiste.isVisible()


def test_hinzufuegen_entfernen_umschalten(leiste, ordner):
    leiste.hinzufuegen(ordner[0])
    leiste.hinzufuegen(ordner[0])  # keine Doppelten
    leiste.umschalten(ordner[1])
    assert _namen(leiste) == ["1A Frisch gescannt", "Downloads"]
    assert [k.text() for k in leiste.knoepfe] == _namen(leiste)
    assert leiste.knoepfe[1].toolTip() == str(ordner[1])
    leiste.umschalten(ordner[0])
    assert not leiste.ist_favorit(ordner[0])
    assert _namen(leiste) == ["Downloads"]


def test_umbenennen_und_zuruecksetzen(leiste, ordner):
    leiste.hinzufuegen(ordner[0])
    leiste.umbenennen(ordner[0], " Frisch ")
    assert _namen(leiste) == ["Frisch"]
    leiste.umbenennen(ordner[0], "")
    assert _namen(leiste) == ["1A Frisch gescannt"]


def test_reihenfolge(leiste, ordner):
    for p in ordner:
        leiste.hinzufuegen(p)
    leiste.verschieben(ordner[2], -1)
    assert _namen(leiste) == ["1A Frisch gescannt", "Steuer", "Downloads"]
    leiste.verschieben(ordner[0], -1)  # am Anfang: nichts
    leiste.verschieben(ordner[1], 1)  # am Ende: nichts
    assert _namen(leiste) == ["1A Frisch gescannt", "Steuer", "Downloads"]
    leiste.verschieben(ordner[0], 1)
    assert _namen(leiste) == ["Steuer", "1A Frisch gescannt", "Downloads"]


def test_menue_verschieben_aktiv_je_position(leiste, ordner):
    for p in ordner:
        leiste.hinzufuegen(p)
    aktionen = {a.text(): a for a in leiste._knopf_menue(ordner[0]).actions() if a.text()}
    assert not aktionen["Nach links"].isEnabled() and aktionen["Nach rechts"].isEnabled()
    aktionen["Nach rechts"].trigger()
    assert _namen(leiste)[1] == "1A Frisch gescannt"
    aktionen = {a.text(): a for a in leiste._knopf_menue(ordner[0]).actions() if a.text()}
    assert {"Entfernen", "Umbenennen (Anzeigename)"} <= set(aktionen)
    aktionen["Entfernen"].trigger()
    assert not leiste.ist_favorit(ordner[0])


def test_speichern_und_laden(cfg, tmp_path, qtbot, ordner):
    w = FavoritenLeiste(cfg)
    qtbot.addWidget(w)
    w.hinzufuegen(ordner[0], "Frisch")
    w.hinzufuegen(ordner[1])
    roh = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert roh["favoriten"] == [
        {"pfad": str(ordner[0]), "name": "Frisch"},
        {"pfad": str(ordner[1]), "name": ""},
    ]
    cfg2 = Config(config_path=tmp_path / "config.json")
    cfg2.load()
    w2 = FavoritenLeiste(cfg2)
    qtbot.addWidget(w2)
    assert _namen(w2) == ["Frisch", "Downloads"]


def test_klick_sendet_pfad(leiste, ordner, qtbot):
    leiste.hinzufuegen(ordner[1])
    with qtbot.waitSignal(leiste.ordner_geoeffnet) as sig:
        leiste.knoepfe[0].click()
    assert sig.args == [ordner[1]]


def test_hervorhebung_aktueller_ordner(leiste, ordner):
    leiste.hinzufuegen(ordner[0])
    leiste.hinzufuegen(ordner[1])
    leiste.set_aktueller_ordner(ordner[1])
    assert [k.property("aktuell") for k in leiste.knoepfe] == ["false", "true"]
    leiste.set_aktueller_ordner(ordner[2])
    assert [k.property("aktuell") for k in leiste.knoepfe] == ["false", "false"]


def test_fehlender_ordner_grau_und_nachfrage(leiste, tmp_path, monkeypatch, qtbot):
    weg = tmp_path / "gibt es nicht"
    leiste.hinzufuegen(weg)
    k = leiste.knoepfe[0]
    assert k.property("fehlt") == "true"
    assert "Ordner nicht gefunden" in k.toolTip()

    geoeffnet = []
    leiste.ordner_geoeffnet.connect(geoeffnet.append)
    antworten = iter([QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: next(antworten))
    k.click()
    assert leiste.ist_favorit(weg)
    leiste.knoepfe[0].click()
    assert not leiste.ist_favorit(weg)
    assert geoeffnet == []


def test_pfadvergleich_ignoriert_schreibweise_des_trennzeichens(leiste, ordner):
    leiste.hinzufuegen(ordner[0])
    assert leiste.ist_favorit(str(ordner[0]) + "/")


# --- Einbindung ins Hauptfenster ----------------------------------------


def test_tile_menue_eintrag(qtbot, ordner):
    tile = FolderTileWidget(ordner[0])
    qtbot.addWidget(tile)
    empfangen = []
    tile.favorit_umschalten.connect(empfangen.append)
    texte = [a.text() for a in tile._build_context_menu().actions()]
    assert "★ Als Favorit merken" in texte
    tile.favorit_pruefer = lambda p: True
    menue = tile._build_context_menu()
    next(a for a in menue.actions() if a.text() == "Favorit entfernen").trigger()
    assert empfangen == [ordner[0]]
    parent = FolderTileWidget(ordner[0], is_parent=True)
    qtbot.addWidget(parent)
    assert not any("Favorit" in a.text() for a in parent._build_context_menu().actions())


def test_baum_menue_eintrag(main_window, ordner):  # noqa: F811
    baum = main_window.folder_tree
    empfangen = []
    baum.favorit_umschalten.connect(empfangen.append)
    next(a for a in baum._build_context_menu(ordner[0]).actions()
         if a.text() == "★ Als Favorit merken").trigger()
    assert empfangen == [ordner[0]]
    assert main_window.favoriten_leiste.ist_favorit(ordner[0])
    texte = [a.text() for a in baum._build_context_menu(ordner[0]).actions()]
    assert "Favorit entfernen" in texte


def test_klick_navigiert_mit_history_und_zurueck(main_window, ordner):  # noqa: F811
    a, b = ordner[0], ordner[1]
    main_window._navigate_to_folder(a)
    main_window.favoriten_leiste.hinzufuegen(b)
    main_window.favoriten_leiste.knoepfe[0].click()
    assert main_window.config.get_scan_folder() == b
    assert main_window._folder_history[-1] == a
    # Hervorhebung folgt dem geoeffneten Ordner
    assert main_window.favoriten_leiste.knoepfe[0].property("aktuell") == "true"
    main_window.on_navigate_back()
    assert main_window.config.get_scan_folder() == a
    assert main_window.favoriten_leiste.knoepfe[0].property("aktuell") == "false"


def test_pfadzeilen_menue(main_window, ordner):  # noqa: F811
    from src.gui.favoriten_leiste import aktuellen_ordner_menue

    main_window._navigate_to_folder(ordner[2])
    leiste = main_window.favoriten_leiste
    menue = aktuellen_ordner_menue(main_window, leiste, ordner[2])
    assert [a.text() for a in menue.actions()] == ["Aktuellen Ordner als Favorit merken"]
    menue.actions()[0].trigger()
    assert leiste.ist_favorit(ordner[2])
    menue = aktuellen_ordner_menue(main_window, leiste, ordner[2])
    assert [a.text() for a in menue.actions()] == ["Favorit entfernen"]


def test_erststart_belegt_scan_ordner_vor(fresh_singletons, qtbot, monkeypatch):  # noqa: F811
    from src.gui import main_window as mw_mod

    cfg = fresh_singletons["config"]
    scan = fresh_singletons["tmp_path"] / "Scan"
    scan.mkdir()
    cfg.set_scan_folder(str(scan))
    monkeypatch.setattr(mw_mod.QMainWindow, "showMaximized", lambda self: None)
    monkeypatch.setattr(mw_mod.QMainWindow, "show", lambda self: None)
    win = mw_mod.MainWindow()
    qtbot.addWidget(win)
    assert cfg.get("favoriten") == [{"pfad": str(scan), "name": ""}]
    # Bewusst geleert: bleibt leer
    win.favoriten_leiste.entfernen(scan)
    win2 = mw_mod.MainWindow()
    qtbot.addWidget(win2)
    assert cfg.get("favoriten") == []

"""Issue #344: Rechtsklick auf eine Vorschlagskachel bietet ein Untermenue mit den Unterordnern.

Ein Klick auf einen Unterordner verschiebt die Auswahl dorthin (wie ein Klick im Ordnerbaum),
"Neuer Unterordner…" legt den Ordner an und legt die Auswahl hinein.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QInputDialog, QMessageBox

from src.gui.folder_widget import FolderWidget, unterordner
from src.gui.main_window import MainWindow
from src.gui.vorschlag_liste import VorschlagZeile

UNTERMENUE = "📂 Unterordner"
NEU = "➕ Neuer Unterordner…"


def _untermenue(menu):
    for a in menu.actions():
        if a.menu() is not None and a.text() == UNTERMENUE:
            return a.menu()
    return None


def _eintraege(sub) -> dict:
    return {a.text(): a for a in sub.actions() if not a.isSeparator()}


def _zeile(qtbot, ordner: Path, auswahl=None, neu: bool = False) -> VorschlagZeile:
    z = VorschlagZeile(ordner)
    qtbot.addWidget(z)
    z.is_suggestion = True
    if neu:
        z.set_neu(True)
    z.auswahl_pruefer = (lambda: list(auswahl)) if auswahl is not None else None
    return z


@pytest.fixture
def ziel(tmp_path):
    ordner = tmp_path / "Steuer 2026"
    for name in ("Handwerker", "ärzte", "Bank & Börse", ".versteckt"):
        (ordner / name).mkdir(parents=True)
    (ordner / "Beleg.pdf").write_bytes(b"%PDF")  # Dateien gehoeren nicht ins Menue
    return ordner


def test_unterordner_alphabetisch_ohne_versteckte_und_dateien(ziel, tmp_path):
    assert unterordner(ziel) == ["ärzte", "Bank & Börse", "Handwerker"] or \
        unterordner(ziel) == sorted(["ärzte", "Bank & Börse", "Handwerker"], key=str.casefold)
    assert unterordner(tmp_path / "Gibt es nicht") == []


def test_untermenue_listet_die_unterordner_und_verschiebt_per_klick(qtbot, ziel):
    z = _zeile(qtbot, ziel, auswahl=[ziel.parent / "Scan.pdf"])
    sub = _untermenue(z._build_context_menu())
    assert sub is not None
    texte = [a.text() for a in sub.actions() if not a.isSeparator()]
    assert texte == ["Bank && Börse", "Handwerker", "ärzte", NEU]  # "&&": "&" bleibt sichtbar
    gemeldet = []
    z.move_to_subfolder_requested.connect(gemeldet.append)
    eintraege = _eintraege(sub)
    assert all(a.isEnabled() for a in eintraege.values())
    eintraege["ärzte"].trigger()
    eintraege["Bank && Börse"].trigger()
    assert gemeldet == [ziel / "ärzte", ziel / "Bank & Börse"]


def test_ohne_auswahl_sind_die_unterordner_ausgegraut_neu_geht_trotzdem(qtbot, ziel):
    z = _zeile(qtbot, ziel, auswahl=[])
    eintraege = _eintraege(_untermenue(z._build_context_menu()))
    assert not eintraege["Handwerker"].isEnabled()
    assert eintraege[NEU].isEnabled()
    gemeldet = []
    z.new_subfolder_requested.connect(gemeldet.append)
    eintraege[NEU].trigger()
    assert gemeldet == [ziel]


def test_ordner_ohne_unterordner(qtbot, tmp_path):
    z = _zeile(qtbot, tmp_path, auswahl=["x"])
    eintraege = _eintraege(_untermenue(z._build_context_menu()))
    assert list(eintraege) == ["(keine Unterordner)", NEU]
    assert not eintraege["(keine Unterordner)"].isEnabled()


def test_kein_untermenue_bei_neuem_ordner_und_zielkachel(qtbot, tmp_path):
    assert _untermenue(_zeile(qtbot, tmp_path / "Neu", neu=True)._build_context_menu()) is None
    kachel = FolderWidget(tmp_path, 0)
    qtbot.addWidget(kachel)
    assert _untermenue(kachel._build_context_menu()) is None


def test_hauptfenster_verdrahtet_wie_ein_klick_im_baum(qtbot, ziel):
    verschoben, angelegt = [], []
    fake = SimpleNamespace(on_show_in_tree_requested=lambda *a, **k: None,
                           on_tree_folder_selected=verschoben.append,
                           on_new_subfolder_requested=angelegt.append)
    z = _zeile(qtbot, ziel, auswahl=["x"])
    MainWindow.verbinde_zielkachel(fake, z)
    eintraege = _eintraege(_untermenue(z._build_context_menu()))
    eintraege["Handwerker"].trigger()
    eintraege[NEU].trigger()
    assert verschoben == [ziel / "Handwerker"] and angelegt == [ziel]


def _fenster(auswahl):
    aufrufe = SimpleNamespace(verschoben=[], baum=[], meldungen=[], caches=0)
    fake = SimpleNamespace(
        folder_tree=SimpleNamespace(add_folder_incremental=lambda p: aufrufe.baum.append(p) or True),
        kopier_auswahl=lambda: list(auswahl),
        on_tree_folder_selected=aufrufe.verschoben.append,
        statusbar=SimpleNamespace(showMessage=lambda text, ms=0: aufrufe.meldungen.append(text)),
    )

    def _caches():
        aufrufe.caches += 1
    fake._invalidate_folder_caches = _caches
    return fake, aufrufe


def _eingabe(monkeypatch, text, ok=True):
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (text, ok)))


def test_neuer_unterordner_wird_angelegt_und_die_auswahl_wandert_hinein(monkeypatch, tmp_path):
    _eingabe(monkeypatch, "  Übergröße 2026  ")
    fake, aufrufe = _fenster([tmp_path / "Scan.pdf"])
    MainWindow.on_new_subfolder_requested(fake, tmp_path)
    neu = tmp_path / "Übergröße 2026"
    assert neu.is_dir()
    assert aufrufe.baum == [neu] and aufrufe.verschoben == [neu] and aufrufe.caches == 1


def test_neuer_unterordner_ohne_auswahl_meldet_nur(monkeypatch, tmp_path):
    _eingabe(monkeypatch, "Neu")
    fake, aufrufe = _fenster([])
    MainWindow.on_new_subfolder_requested(fake, tmp_path)
    assert (tmp_path / "Neu").is_dir()
    assert aufrufe.verschoben == [] and aufrufe.meldungen


@pytest.mark.parametrize("text,ok", [("", True), ("Neu", False)])
def test_abbrechen_oder_leer_legt_nichts_an(monkeypatch, tmp_path, text, ok):
    _eingabe(monkeypatch, text, ok)
    fake, aufrufe = _fenster(["x"])
    MainWindow.on_new_subfolder_requested(fake, tmp_path)
    assert list(tmp_path.iterdir()) == [] and aufrufe.verschoben == []


@pytest.mark.parametrize("text", ["a/b", ".."])
def test_pfade_statt_namen_werden_abgelehnt(monkeypatch, tmp_path, text):
    _eingabe(monkeypatch, text)
    warnungen = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warnungen.append(a)))
    fake, aufrufe = _fenster(["x"])
    eltern = tmp_path / "Ziel"
    eltern.mkdir()
    MainWindow.on_new_subfolder_requested(fake, eltern)
    assert warnungen and list(eltern.iterdir()) == [] and aufrufe.verschoben == []

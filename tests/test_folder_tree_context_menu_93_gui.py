"""Rechtsklick-Menue des Zielordner-Baums (Issue #93)."""
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt

from src.gui import folder_tree_widget as ftw
from src.gui.folder_tree_widget import FolderTreeWidget
from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401


def _tree(qtbot, tmp_path, *subdirs):
    root = tmp_path / "Ziel"
    root.mkdir()
    for sub in subdirs:
        (root / sub).mkdir(parents=True)
    w = FolderTreeWidget()
    qtbot.addWidget(w)
    w.async_scan = False
    w.set_root_folders([root])
    return w, root


def _aktion(menu, teil):
    for a in menu.actions():
        if teil in a.text():
            return a
    raise AssertionError(f"Eintrag mit '{teil}' fehlt: {[a.text() for a in menu.actions()]}")


def _item(w, path):
    return w._items[Path(path)]


def _pfad(item):
    return Path(item.data(0, Qt.ItemDataRole.UserRole))


def test_menue_ist_gruppiert(qtbot, tmp_path):
    w, root = _tree(qtbot, tmp_path, "Bank")
    menu = w._build_context_menu(root)
    gruppen, aktuell = [], []
    for a in menu.actions():
        if a.isSeparator():
            gruppen.append(aktuell)
            aktuell = []
        else:
            aktuell.append(a.text())
    gruppen.append(aktuell)
    assert len(gruppen) == 4
    assert any("Unterordner öffnen" in t for t in gruppen[0])
    assert any("Hierhin verschieben" in t for t in gruppen[1])
    assert any("umbenennen" in t for t in gruppen[2])
    assert any("Aus Zielliste entfernen" in t for t in gruppen[2])
    assert any("Inhalt anzeigen" in t for t in gruppen[3])


def test_unterordner_untermenue_oeffnet_markiert_ohne_verschieben(qtbot, tmp_path):
    w, root = _tree(qtbot, tmp_path, "Bank/2026", "Versicherung")
    gewaehlt = []
    w.folder_selected.connect(gewaehlt.append)
    sub = _aktion(w._build_context_menu(root), "Unterordner öffnen").menu()
    sub.aboutToShow.emit()
    assert [a.text() for a in sub.actions()] == ["📁 Bank", "📁 Versicherung"]
    sub.actions()[0].trigger()
    assert w.get_selected_folder() == root / "Bank"
    assert _item(w, root / "Bank").isExpanded()
    qtbot.wait(w._click_timer.interval() + 100)
    assert gewaehlt == []


def test_unterordner_untermenue_ist_begrenzt(qtbot, tmp_path):
    maximum = FolderTreeWidget.SUBMENU_MAX_ENTRIES
    w, root = _tree(qtbot, tmp_path, *[f"o{i:03d}" for i in range(maximum + 5)])
    sub = _aktion(w._build_context_menu(root), "Unterordner öffnen").menu()
    sub.aboutToShow.emit()
    assert len(sub.actions()) == maximum + 1
    assert "5 weitere" in sub.actions()[-1].text()


def test_untermenue_deaktiviert_ohne_unterordner(qtbot, tmp_path):
    w, root = _tree(qtbot, tmp_path)
    assert not _aktion(w._build_context_menu(root), "Unterordner öffnen").isEnabled()


def test_unterordner_oeffnen_tief_im_ungeladenen_bereich(qtbot, tmp_path):
    w, root = _tree(qtbot, tmp_path, "a/b/c/d/e")
    tief = root / "a" / "b" / "c" / "d"
    assert not w.has_folder(tief)
    w._open_subfolder(tief)
    assert w.get_selected_folder() == tief
    assert _item(w, tief).isExpanded()


def test_alle_unterordner_aufklappen_begrenzt_auf_drei_ebenen(qtbot, tmp_path):
    w, root = _tree(qtbot, tmp_path, "a/b/c/d/e/f")
    w.tree.collapseAll()
    _aktion(w._build_context_menu(root), "Alle Unterordner aufklappen").trigger()
    assert _item(w, root).isExpanded()
    assert _item(w, root / "a").isExpanded()
    assert _item(w, root / "a/b").isExpanded()
    assert not _item(w, root / "a/b/c").isExpanded()  # 4. Ebene bleibt zu


def test_aufklappen_laedt_nach(qtbot, tmp_path):
    w, root = _tree(qtbot, tmp_path, "a/b/c/d/e/f")
    w.tree.collapseAll()
    w._expand_subtree(root / "a")
    assert _item(w, root / "a/b/c").isExpanded()  # war nicht geladen
    assert w.has_folder(root / "a/b/c/d")
    assert not _item(w, root / "a/b/c/d").isExpanded()


def test_aufklappen_hat_obergrenze(qtbot, tmp_path, monkeypatch):
    w, root = _tree(qtbot, tmp_path, "a/b", "c/d", "e/f")
    w.tree.collapseAll()
    monkeypatch.setattr(FolderTreeWidget, "EXPAND_MAX_FOLDERS", 2)
    w._expand_subtree(root)
    offen = [p for p, it in w._items.items() if it.isExpanded()]
    assert len(offen) == 2


def test_wartecursor_wird_wieder_freigegeben(qtbot, tmp_path):
    from PyQt6.QtWidgets import QApplication
    w, root = _tree(qtbot, tmp_path, "a/b")
    w._expand_subtree(root)
    assert QApplication.overrideCursor() is None


def test_zuklappen_teilbaum_und_alles(qtbot, tmp_path):
    w, root = _tree(qtbot, tmp_path, "a/b", "x/y")
    w._expand_subtree(root)
    _aktion(w._build_context_menu(root / "a"), "Unterordner zuklappen").trigger()
    assert not _item(w, root / "a").isExpanded()
    assert _item(w, root / "x").isExpanded()
    _aktion(w._build_context_menu(root), "Alles zuklappen").trigger()
    assert not _item(w, root).isExpanded()
    assert not _item(w, root / "x").isExpanded()


def test_hierhin_verschieben_deaktiviert_ohne_auswahl(qtbot, tmp_path):
    w, root = _tree(qtbot, tmp_path)
    assert not _aktion(w._build_context_menu(root), "Hierhin verschieben").isEnabled()


def test_hierhin_verschieben_sendet_signal(qtbot, tmp_path):
    w, root = _tree(qtbot, tmp_path)
    w.has_pdf_selection = lambda: True
    gewaehlt = []
    w.folder_selected.connect(gewaehlt.append)
    aktion = _aktion(w._build_context_menu(root), "Hierhin verschieben")
    assert aktion.isEnabled()
    with qtbot.waitSignal(w.move_here_requested) as blocker:
        aktion.trigger()
    assert blocker.args == [root]
    assert gewaehlt == []


def test_umbenennen(qtbot, tmp_path, monkeypatch):
    w, root = _tree(qtbot, tmp_path, "Bank/2026", "Zebra")
    w.set_suggestion_folders([root / "Bank"])
    monkeypatch.setattr(ftw.QInputDialog, "getText", staticmethod(lambda *a, **k: ("Banken", True)))
    gemeldet = []
    w.folder_renamed.connect(lambda a, b: gemeldet.append((a, b)))
    _aktion(w._build_context_menu(root / "Bank"), "umbenennen").trigger()
    neu = root / "Banken"
    assert neu.is_dir() and not (root / "Bank").exists()
    assert gemeldet == [(root / "Bank", neu)]
    assert w.has_folder(neu) and w.has_folder(neu / "2026") and not w.has_folder(root / "Bank")
    assert _pfad(_item(w, neu / "2026")) == neu / "2026"
    assert "Banken" in _item(w, neu).text(0)
    assert w._suggestion_folders == [neu]


def test_umbenennen_wurzel_aktualisiert_wurzelliste(qtbot, tmp_path, monkeypatch):
    w, root = _tree(qtbot, tmp_path, "Bank")
    monkeypatch.setattr(ftw.QInputDialog, "getText", staticmethod(lambda *a, **k: ("Neu", True)))
    w._rename_folder(root)
    assert w._root_folders == [tmp_path / "Neu"]
    assert (tmp_path / "Neu" / "Bank").is_dir()


@pytest.mark.parametrize("name", ['a/b', 'a:b', 'a*', 'a?', 'a"b', 'a|b', 'a<b', 'ende.'])
def test_umbenennen_ungueltige_zeichen(qtbot, tmp_path, monkeypatch, name):
    w, root = _tree(qtbot, tmp_path, "Bank")
    monkeypatch.setattr(ftw.QInputDialog, "getText", staticmethod(lambda *a, **k: (name, True)))
    warnungen = []
    monkeypatch.setattr(ftw.QMessageBox, "warning", staticmethod(lambda *a: warnungen.append(a)))
    w._rename_folder(root / "Bank")
    assert (root / "Bank").is_dir()
    assert len(warnungen) == 1


def test_umbenennen_kollision(qtbot, tmp_path, monkeypatch):
    w, root = _tree(qtbot, tmp_path, "Bank", "Post")
    monkeypatch.setattr(ftw.QInputDialog, "getText", staticmethod(lambda *a, **k: ("Post", True)))
    warnungen = []
    monkeypatch.setattr(ftw.QMessageBox, "warning", staticmethod(lambda *a: warnungen.append(a)))
    w._rename_folder(root / "Bank")
    assert (root / "Bank").is_dir() and (root / "Post").is_dir()
    assert len(warnungen) == 1


def test_umbenennen_nur_gross_klein(qtbot, tmp_path, monkeypatch):
    w, root = _tree(qtbot, tmp_path, "bank")
    monkeypatch.setattr(ftw.QInputDialog, "getText", staticmethod(lambda *a, **k: ("Bank", True)))
    w._rename_folder(root / "bank")
    assert "Bank" in [p.name for p in root.iterdir()]


class _Papierkorb:
    def __init__(self, ok=True):
        self.ok, self.pfade = ok, []

    def moveToTrash(self, pfad):
        self.pfade.append(pfad)
        if self.ok:
            Path(pfad).rmdir()  # wie der echte Papierkorb: Ordner ist danach weg
        return (self.ok, "")


def _ja(monkeypatch):
    monkeypatch.setattr(ftw.QMessageBox, "question",
                        staticmethod(lambda *a: ftw.QMessageBox.StandardButton.Yes))


def test_loeschen_leerer_ordner(qtbot, tmp_path, monkeypatch):
    w, root = _tree(qtbot, tmp_path, "leer", "voll")
    korb = _Papierkorb()
    monkeypatch.setattr(ftw, "QFile", korb)
    _ja(monkeypatch)
    meldungen = []
    w.status_message.connect(meldungen.append)
    aktion = _aktion(w._build_context_menu(root / "leer"), "löschen")
    assert aktion.isEnabled()
    aktion.trigger()
    assert korb.pfade == [str(root / "leer")]
    assert not w.has_folder(root / "leer")
    assert w.has_folder(root / "voll")
    assert meldungen and "leer" in meldungen[0]


def test_loeschen_abgelehnt(qtbot, tmp_path, monkeypatch):
    w, root = _tree(qtbot, tmp_path, "leer")
    korb = _Papierkorb()
    monkeypatch.setattr(ftw, "QFile", korb)
    monkeypatch.setattr(ftw.QMessageBox, "question",
                        staticmethod(lambda *a: ftw.QMessageBox.StandardButton.No))
    w._delete_folder(root / "leer")
    assert korb.pfade == [] and (root / "leer").is_dir() and w.has_folder(root / "leer")


def test_loeschen_nicht_leer_oder_wurzel_deaktiviert(qtbot, tmp_path, monkeypatch):
    w, root = _tree(qtbot, tmp_path, "voll")
    (root / "voll" / "x.txt").write_text("x")
    assert not _aktion(w._build_context_menu(root / "voll"), "löschen").isEnabled()
    assert not _aktion(w._build_context_menu(root), "löschen").isEnabled()  # Wurzel
    # direkter Aufruf auf nicht leeren Ordner loescht nichts
    korb = _Papierkorb()
    monkeypatch.setattr(ftw, "QFile", korb)
    monkeypatch.setattr(ftw.QMessageBox, "information", staticmethod(lambda *a: None))
    w._delete_folder(root / "voll")
    assert korb.pfade == []


def test_loeschen_fehlgeschlagen_behaelt_item(qtbot, tmp_path, monkeypatch):
    w, root = _tree(qtbot, tmp_path, "leer")
    monkeypatch.setattr(ftw, "QFile", _Papierkorb(ok=False))
    _ja(monkeypatch)
    fehler = []
    monkeypatch.setattr(ftw.QMessageBox, "critical", staticmethod(lambda *a: fehler.append(a)))
    w._delete_folder(root / "leer")
    assert w.has_folder(root / "leer") and len(fehler) == 1


def test_inhalt_anzeigen(qtbot, tmp_path):
    w, root = _tree(qtbot, tmp_path, "u1", "u2")
    (root / "a.pdf").write_bytes(b"x")
    (root / "B.PDF").write_bytes(b"x")
    (root / "n.txt").write_text("x")
    with qtbot.waitSignal(w.status_message) as blocker:
        _aktion(w._build_context_menu(root), "Inhalt anzeigen").trigger()
    text = blocker.args[0]
    assert "2 PDFs" in text and "1 weitere Datei" in text and "2 Unterordner" in text


def test_als_wurzel_anzeigen_und_zurueck(qtbot, tmp_path):
    w, root = _tree(qtbot, tmp_path, "Bank/2026", "Post")
    assert w.view_root_bar.isHidden()
    _aktion(w._build_context_menu(root / "Bank"), "als Wurzel anzeigen").trigger()
    assert w.view_root() == root / "Bank"
    assert not w.view_root_bar.isHidden()
    assert w.tree.topLevelItemCount() == 1
    assert _pfad(w.tree.topLevelItem(0)) == root / "Bank"
    assert not w.has_folder(root / "Post")
    # im Ausschnitt ist der Eintrag fuer die aktuelle Wurzel nicht mehr da
    assert all("als Wurzel" not in a.text() for a in w._build_context_menu(root / "Bank").actions())
    w.view_root_back_btn.click()
    assert w.view_root() is None and w.view_root_bar.isHidden()
    assert w.has_folder(root / "Post")


def test_wurzel_ansicht_faellt_zurueck_wenn_ordner_fehlt(qtbot, tmp_path):
    w, root = _tree(qtbot, tmp_path, "Bank")
    w.set_view_root(root / "Bank")
    (root / "Bank").rmdir()
    w.refresh_tree()
    assert w.view_root() is None and w.has_folder(root)


def test_doppelklick_bleibt_navigation(qtbot, tmp_path):
    # Doppelklick oeffnet links (Issue #23/#26); Qt klappt dabei zusaetzlich auf/zu
    w, root = _tree(qtbot, tmp_path, "Bank")
    assert w.tree.expandsOnDoubleClick()


# --- MainWindow-Anbindung ---

def test_mainwindow_hierhin_verschieben_nutzt_drop_weg(main_window, tmp_path, monkeypatch):
    ziel = tmp_path / "Z"
    ziel.mkdir()
    gerufen = []
    monkeypatch.setattr(main_window, "_move_rename_and_learn", lambda p, f: gerufen.append((p, f)))
    pdf = tmp_path / "x.pdf"
    assert not main_window.folder_tree.has_pdf_selection()
    main_window.selected_pdf = pdf
    assert main_window.folder_tree.has_pdf_selection()
    main_window.folder_tree.move_here_requested.emit(ziel)
    assert gerufen == [(pdf, ziel)]


def test_mainwindow_umbenennen_aktualisiert_zielpfade(main_window, tmp_path):
    alt = tmp_path / "Alt"
    (alt / "Sub").mkdir(parents=True)
    main_window.config.add_target_folder(alt)
    main_window.config.add_target_folder(alt / "Sub")
    main_window.folder_manager.add_folder(alt)
    neu = tmp_path / "Neu"
    alt.rename(neu)
    main_window.folder_tree.folder_renamed.emit(alt, neu)
    ziele = main_window.config.get_target_folders()
    assert neu in ziele and neu / "Sub" in ziele and alt not in ziele
    assert neu in main_window.folder_manager.target_folders


def test_mainwindow_inhalt_anzeigen_in_statusleiste(main_window):
    main_window.folder_tree.status_message.emit("ℹ️ Test")
    assert main_window.statusbar.currentMessage() == "ℹ️ Test"

"""Neuer Unterordner per Kontextmenue ist danach im Baum markiert."""
from pathlib import Path

from src.gui import folder_tree_widget as ftw
from src.gui.folder_tree_widget import FolderTreeWidget


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


def _create(monkeypatch, w, parent: Path, name: str):
    monkeypatch.setattr(ftw.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: (name, True)))
    w._create_subfolder(parent)


def _current_path(w):
    item = w.tree.currentItem()
    return Path(item.data(0, ftw.Qt.ItemDataRole.UserRole)) if item else None


def test_neuer_unterordner_ist_markiert(qtbot, tmp_path, monkeypatch):
    w, root = _tree(qtbot, tmp_path, "Bank")
    moved = []
    w.folder_selected.connect(moved.append)

    _create(monkeypatch, w, root / "Bank", " 2026 ")

    neu = root / "Bank" / "2026"
    assert neu.is_dir()
    assert _current_path(w) == neu
    assert w.get_selected_folder() == neu
    assert w.tree.currentItem().parent().isExpanded()
    qtbot.wait(w._click_timer.interval() + 100)
    assert moved == []  # nur markiert, kein "Klick" (wuerde die PDF verschieben)


def test_neuer_ordner_unter_nicht_geladenem_elternteil(qtbot, tmp_path, monkeypatch):
    # Elternordner liegt tiefer als die geladenen Ebenen -> Zwischenordner einhaengen
    w, root = _tree(qtbot, tmp_path, "a/b/c/d/e")
    tief = root / "a" / "b" / "c" / "d" / "e"
    assert not w.has_folder(tief)  # Baum laedt nicht so tief
    _create(monkeypatch, w, tief, "neu")
    assert (tief / "neu").is_dir()
    assert _current_path(w) == tief / "neu"
    item = w.tree.currentItem()
    while item.parent() is not None:  # ganzer Pfad aufgeklappt
        assert item.parent().isExpanded()
        item = item.parent()


def test_abbrechen_legt_nichts_an(qtbot, tmp_path, monkeypatch):
    w, root = _tree(qtbot, tmp_path)
    monkeypatch.setattr(ftw.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("x", False)))
    w._create_subfolder(root)
    assert not (root / "x").exists()

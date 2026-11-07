"""Ordner unterhalb der Scan-Tiefe zeigen einen Pfeil und laden beim Aufklappen nach."""
from src.gui.folder_tree_widget import FolderTreeWidget
from PyQt6.QtWidgets import QTreeWidgetItem

SHOW = QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator


def _tree(qtbot, tmp_path, *subdirs, async_scan=False):
    root = tmp_path / "Ziel"
    root.mkdir()
    for sub in subdirs:
        (root / sub).mkdir(parents=True)
    w = FolderTreeWidget()
    qtbot.addWidget(w)
    w.async_scan = async_scan
    if async_scan:
        with qtbot.waitSignal(w.scan_finished, timeout=5000):
            w.set_root_folders([root])
    else:
        w.set_root_folders([root])
    return w, root


def test_ordner_auf_tiefster_ebene_zeigt_pfeil(qtbot, tmp_path):
    # Ziel(0)/a(1)/b(2)/c(3) wird gescannt, c/d liegt darunter
    w, root = _tree(qtbot, tmp_path, "a/b/c/d/e", "a/b/blatt")
    c = w._items[root / "a" / "b" / "c"]
    assert c.childCount() == 0
    assert not w.has_folder(root / "a" / "b" / "c" / "d")
    assert c.childIndicatorPolicy() == SHOW
    # Ordner ohne Unterordner bekommt keinen Pfeil
    assert w._items[root / "a" / "b" / "blatt"].childIndicatorPolicy() != SHOW


def test_aufklappen_laedt_unterordner_nach(qtbot, tmp_path):
    w, root = _tree(qtbot, tmp_path, "a/b/c/z/tief", "a/b/c/m")
    (root / "a" / "b" / "c" / "m" / "r.pdf").write_bytes(b"%PDF-1.4")
    (root / "a" / "b" / "c" / "notiz.txt").write_text("keine Ordner")
    c = w._items[root / "a" / "b" / "c"]
    c.setExpanded(True)
    namen = [c.child(i).text(0) for i in range(c.childCount())]
    assert namen == ["📁 m  [1]", "📁 z"]
    # die naechste Ebene hat wieder nur den Pfeil
    z = w._items[root / "a" / "b" / "c" / "z"]
    assert z.childCount() == 0 and z.childIndicatorPolicy() == SHOW
    z.setExpanded(True)
    assert w.has_folder(root / "a" / "b" / "c" / "z" / "tief")


def test_aufklappen_im_hintergrund(qtbot, tmp_path):
    w, root = _tree(qtbot, tmp_path, "a/b/c/d", async_scan=True)
    c = w._items[root / "a" / "b" / "c"]
    c.setExpanded(True)
    qtbot.waitUntil(lambda: w.has_folder(root / "a" / "b" / "c" / "d"), timeout=5000)
    assert c.childCount() == 1


def test_leer_gewordener_ordner_verliert_pfeil(qtbot, tmp_path):
    w, root = _tree(qtbot, tmp_path, "a/b/c/d")
    (root / "a" / "b" / "c" / "d").rmdir()
    c = w._items[root / "a" / "b" / "c"]
    c.setExpanded(True)
    assert c.childCount() == 0
    assert c.childIndicatorPolicy() != SHOW


def test_ziehen_klappt_nicht_geladenen_ordner_auf(qtbot, tmp_path):
    w, root = _tree(qtbot, tmp_path, "a/b/c/d")
    c = w._items[root / "a" / "b" / "c"]
    w._drag_hover_item = c
    w._expand_drag_hover_item()
    assert c.isExpanded()
    assert w.has_folder(root / "a" / "b" / "c" / "d")

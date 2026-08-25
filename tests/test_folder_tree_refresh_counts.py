"""FolderTreeWidget.refresh_counts: nur betroffene Ordner neu zaehlen (Issue #28)."""
from src.gui.folder_tree_widget import FolderTreeWidget


def test_refresh_counts_updates_only_known_items(qtbot, tmp_path):
    root = tmp_path / "Ziel"; sub = root / "Steuer 2026"; sub.mkdir(parents=True)
    w = FolderTreeWidget(); qtbot.addWidget(w)
    w.set_root_folders([root])
    item = w._items[sub]
    assert item.text(0) == "📁 Steuer 2026"

    (sub / "a.pdf").write_bytes(b"%PDF"); (sub / "b.pdf").write_bytes(b"%PDF")
    assert w.refresh_counts([sub, tmp_path / "unbekannt"]) == 1
    assert item.text(0) == "📁 Steuer 2026  [2]"

    (sub / "a.pdf").unlink(); (sub / "b.pdf").unlink()
    w.refresh_counts([sub])
    assert item.text(0) == "📁 Steuer 2026"


def test_items_index_rebuilt_on_refresh_tree(qtbot, tmp_path):
    root = tmp_path / "Ziel"; root.mkdir()
    w = FolderTreeWidget(); qtbot.addWidget(w)
    w.set_root_folders([root])
    assert set(w._items) == {root}
    (root / "Neu").mkdir()
    w.refresh_tree()
    assert set(w._items) == {root, root / "Neu"}


def test_has_folder(qtbot, tmp_path):
    root = tmp_path / "Ziel"; (root / "A").mkdir(parents=True)
    w = FolderTreeWidget(); qtbot.addWidget(w)
    w.set_root_folders([root])
    assert w.has_folder(root / "A")
    assert not w.has_folder(tmp_path / "Scan")

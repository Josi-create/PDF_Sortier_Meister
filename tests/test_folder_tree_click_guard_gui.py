"""Doppelklick im Zielordner-Baum darf die selektierte PDF nicht verschieben (Issue #23/#26)."""
from src.gui.folder_tree_widget import FolderTreeWidget


def _tree_with_folder(qtbot, tmp_path):
    root = tmp_path / "Ziel"
    root.mkdir()
    w = FolderTreeWidget()
    qtbot.addWidget(w)
    w.async_scan = False
    w.set_root_folders([root])
    item = w.tree.topLevelItem(0)
    assert item is not None
    return w, root, item


def test_single_click_selects_after_interval(qtbot, tmp_path):
    w, root, item = _tree_with_folder(qtbot, tmp_path)
    with qtbot.waitSignal(w.folder_selected, timeout=2000) as blocker:
        w._on_item_clicked(item, 0)
    assert blocker.args == [root]


def test_double_click_cancels_pending_single_click(qtbot, tmp_path):
    w, root, item = _tree_with_folder(qtbot, tmp_path)
    selected = []
    w.folder_selected.connect(lambda p: selected.append(p))

    w._on_item_clicked(item, 0)  # erster Klick des Doppelklicks
    with qtbot.waitSignal(w.folder_double_clicked, timeout=1000) as blocker:
        w._on_item_double_clicked(item, 0)
    assert blocker.args == [root]

    qtbot.wait(w._click_timer.interval() + 100)
    assert selected == []  # kein Verschieben ausgeloest

"""Ordnerbaum scrollt beim Ziehen einer PDF an den Rand automatisch (wie PaperPort)."""
from pathlib import Path

from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent
from PyQt6.QtWidgets import QApplication

from src.gui.folder_tree_widget import FolderTreeWidget


def _pdf_mime(tmp_path: Path) -> QMimeData:
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(pdf))])
    return mime


def _tree_with_many_folders(qtbot, tmp_path):
    root = tmp_path / "Ziel"
    root.mkdir()
    for i in range(60):
        (root / f"Ordner {i:02d}").mkdir()
    w = FolderTreeWidget()
    qtbot.addWidget(w)
    w.async_scan = False
    w.set_root_folders([root])
    w.tree.expandAll()
    w.resize(250, 200)
    w.show()
    qtbot.waitExposed(w)
    return w


def _drag_to(tree, mime, pos: QPointF):
    viewport = tree.viewport()
    actions = Qt.DropAction.MoveAction | Qt.DropAction.CopyAction
    enter = QDragEnterEvent(pos.toPoint(), actions, mime, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(viewport, enter)
    move = QDragMoveEvent(pos.toPoint(), actions, mime, Qt.MouseButton.LeftButton,
                          Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(viewport, move)
    return move


def test_drag_at_bottom_edge_scrolls_tree(qtbot, tmp_path):
    w = _tree_with_many_folders(qtbot, tmp_path)
    tree = w.tree
    bar = tree.verticalScrollBar()
    assert bar.maximum() > 0
    assert bar.value() == 0

    bottom = QPointF(tree.viewport().width() / 2, tree.viewport().height() - 3)
    move = _drag_to(tree, _pdf_mime(tmp_path), bottom)
    assert move.isAccepted()

    qtbot.waitUntil(lambda: bar.value() > 0, timeout=2000)
    w._tree_drag_leave(None)


def test_drop_target_still_highlighted(qtbot, tmp_path):
    w = _tree_with_many_folders(qtbot, tmp_path)
    tree = w.tree
    item = tree.topLevelItem(0)
    rect = tree.visualItemRect(item)
    _drag_to(tree, _pdf_mime(tmp_path), QPointF(rect.center()))
    assert w._drag_hover_item is item
    w._tree_drag_leave(None)
    assert w._drag_hover_item is None


def test_leaving_tree_stops_autoscroll(qtbot, tmp_path):
    w = _tree_with_many_folders(qtbot, tmp_path)
    tree = w.tree
    bar = tree.verticalScrollBar()
    bottom = QPointF(tree.viewport().width() / 2, tree.viewport().height() - 3)
    _drag_to(tree, _pdf_mime(tmp_path), bottom)
    qtbot.waitUntil(lambda: bar.value() > 0, timeout=2000)

    w._tree_drag_leave(None)
    stopped_at = bar.value()
    qtbot.wait(400)
    assert bar.value() == stopped_at
    assert tree.state() == tree.State.NoState


def test_hovering_collapsed_folder_expands_it(qtbot, tmp_path):
    root = tmp_path / "Ziel"
    (root / "Steuer" / "2025").mkdir(parents=True)
    w = FolderTreeWidget()
    qtbot.addWidget(w)
    w.async_scan = False
    w.set_root_folders([root])
    w.resize(250, 300)
    w.show()
    qtbot.waitExposed(w)
    tree = w.tree
    tree.collapseAll()
    tree.expandItem(tree.topLevelItem(0))
    steuer = tree.topLevelItem(0).child(0)
    assert steuer is not None and steuer.childCount() > 0
    assert not steuer.isExpanded()

    _drag_to(tree, _pdf_mime(tmp_path), QPointF(tree.visualItemRect(steuer).center()))
    qtbot.waitUntil(steuer.isExpanded, timeout=w.DRAG_AUTO_EXPAND_MS + 1500)
    w._tree_drag_leave(None)

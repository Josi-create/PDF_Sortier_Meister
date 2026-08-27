"""GUI-Tests fuer FolderTileWidget (Explorer-Gefuehl, Issue #29)."""
from pathlib import Path

from PyQt6.QtCore import QUrl, QMimeData

from src.gui.folder_tile import FolderTileWidget


class _FakeDropEvent:
    def __init__(self, mime):
        self._mime = mime
        self.accepted = None

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


def _mime(*paths):
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return m


def test_tile_shows_name_and_count(qtbot, tmp_path):
    folder = tmp_path / "Steuer 2026"
    folder.mkdir()
    tile = FolderTileWidget(folder, pdf_count=3)
    qtbot.addWidget(tile)
    assert tile.name_label.text() == "Steuer 2026"
    assert tile.count_label.text() == "3 PDFs"


def test_parent_tile_shows_dots(qtbot, tmp_path):
    tile = FolderTileWidget(tmp_path, is_parent=True)
    qtbot.addWidget(tile)
    assert tile.name_label.text() == ".."
    assert tile.is_parent


def test_double_click_emits_folder(qtbot, tmp_path):
    from PyQt6.QtCore import Qt
    tile = FolderTileWidget(tmp_path)
    qtbot.addWidget(tile)
    tile.show()
    with qtbot.waitSignal(tile.double_clicked, timeout=1000) as blocker:
        qtbot.mouseDClick(tile, Qt.MouseButton.LeftButton)
    assert blocker.args == [tmp_path]


def test_single_click_emits_clicked(qtbot, tmp_path):
    """Issue #50: Einfachklick loest das clicked-Signal aus (fuer die ".."-Kachel)."""
    from PyQt6.QtCore import Qt
    tile = FolderTileWidget(tmp_path, is_parent=True)
    qtbot.addWidget(tile)
    tile.show()
    with qtbot.waitSignal(tile.clicked, timeout=1000) as blocker:
        qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)
    assert blocker.args == [tmp_path]


def test_drop_emits_only_pdfs(qtbot, tmp_path):
    tile = FolderTileWidget(tmp_path)
    qtbot.addWidget(tile)
    received = []
    tile.pdf_dropped.connect(lambda pdf, folder: received.append((pdf, folder)))

    ev = _FakeDropEvent(_mime(tmp_path / "a.pdf", tmp_path / "b.txt", tmp_path / "C.PDF"))
    tile.dropEvent(ev)
    assert ev.accepted is True
    assert received == [(tmp_path / "a.pdf", tmp_path), (tmp_path / "C.PDF", tmp_path)]


def test_drop_without_pdfs_is_ignored(qtbot, tmp_path):
    tile = FolderTileWidget(tmp_path)
    qtbot.addWidget(tile)
    ev = _FakeDropEvent(_mime(tmp_path / "b.txt"))
    tile.dropEvent(ev)
    assert ev.accepted is False

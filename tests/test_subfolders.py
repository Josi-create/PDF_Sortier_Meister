"""FolderManager.get_subfolders / count_pdfs (Explorer-Gefuehl)."""
from src.core.file_manager import FolderManager


def test_subfolders_sorted_and_hidden_skipped(tmp_path):
    for name in ["zebra", "Alpha", ".git", "$RECYCLE.BIN", "mitte"]:
        (tmp_path / name).mkdir()
    (tmp_path / "datei.pdf").write_bytes(b"%PDF")
    fm = FolderManager()
    assert [p.name for p in fm.get_subfolders(tmp_path)] == ["Alpha", "mitte", "zebra"]


def test_subfolders_missing_parent(tmp_path):
    assert FolderManager().get_subfolders(tmp_path / "nope") == []


def test_count_pdfs(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF")
    (tmp_path / "B.PDF").write_bytes(b"%PDF")
    (tmp_path / "c.txt").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "d.pdf").write_bytes(b"%PDF")
    assert FolderManager().count_pdfs(tmp_path) == 2
    assert FolderManager().count_pdfs(tmp_path / "missing") == 0

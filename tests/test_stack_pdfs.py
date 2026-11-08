"""PDF auf PDF ziehen legt die Seiten davor ("Stapeln" wie Papier)."""
import errno
import os
from pathlib import Path

import fitz
import pytest

from src.core.file_manager import FileManager


def _create_pdf(path: Path, pages: int, label: str) -> None:
    doc = fitz.open()
    try:
        for i in range(pages):
            page = doc.new_page()
            page.insert_text((72, 72), f"{label} Seite {i + 1}")
        doc.set_metadata({"title": f"Titel {label}"})
        doc.save(str(path))
    finally:
        doc.close()


def _page_texts(path: Path) -> list[str]:
    with fitz.open(str(path)) as doc:
        return [page.get_text().strip() for page in doc]


def test_stack_appends_pages_and_keeps_target_name(tmp_path: Path) -> None:
    target = tmp_path / "Rechnung.pdf"
    source = tmp_path / "Anlage.pdf"
    _create_pdf(target, 1, "Rechnung")
    _create_pdf(source, 2, "Anlage")

    FileManager().stack_pdfs(target, [source], tmp_path / "undo")

    assert _page_texts(target) == ["Anlage Seite 1", "Anlage Seite 2", "Rechnung Seite 1"]
    assert not source.exists()  # im Stapel aufgegangen
    with fitz.open(str(target)) as doc:
        assert doc.metadata["title"] == "Titel Rechnung"  # Metadaten des Ziels bleiben
    assert not list(tmp_path.glob("*.stapel-tmp.pdf"))


def test_stack_keeps_sources_from_other_folders(tmp_path: Path) -> None:
    target = tmp_path / "Ziel.pdf"
    other = tmp_path / "Explorer"
    other.mkdir()
    source = other / "Extern.pdf"
    _create_pdf(target, 1, "Ziel")
    _create_pdf(source, 1, "Extern")

    backups = FileManager().stack_pdfs(target, [source], tmp_path / "undo")

    assert source.exists()  # nur gelesen
    assert [orig for orig, _ in backups] == [target]
    assert len(_page_texts(target)) == 2


def test_restore_stack_undoes_everything(tmp_path: Path) -> None:
    target = tmp_path / "A.pdf"
    b = tmp_path / "B.pdf"
    c = tmp_path / "C.pdf"
    _create_pdf(target, 1, "A")
    _create_pdf(b, 1, "B")
    _create_pdf(c, 2, "C")
    manager = FileManager()

    backups = manager.stack_pdfs(target, [b, c], tmp_path / "undo")
    assert _page_texts(target) == ["B Seite 1", "C Seite 1", "C Seite 2", "A Seite 1"]

    restored = manager.restore_stack(backups)

    assert restored == [target, b, c]
    assert _page_texts(target) == ["A Seite 1"]
    assert _page_texts(b) == ["B Seite 1"]
    assert _page_texts(c) == ["C Seite 1", "C Seite 2"]


def test_restore_stack_does_not_overwrite_new_file_with_same_name(tmp_path: Path) -> None:
    target = tmp_path / "A.pdf"
    b = tmp_path / "B.pdf"
    _create_pdf(target, 1, "A")
    _create_pdf(b, 1, "B")
    manager = FileManager()
    backups = manager.stack_pdfs(target, [b], tmp_path / "undo")
    _create_pdf(b, 1, "Neu")  # inzwischen neu gescannt

    restored = manager.restore_stack(backups)

    assert _page_texts(b) == ["Neu Seite 1"]
    assert restored[1] == tmp_path / "B (1).pdf"
    assert _page_texts(restored[1]) == ["B Seite 1"]


def test_stack_onto_itself_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "A.pdf"
    _create_pdf(target, 1, "A")
    with pytest.raises(ValueError):
        FileManager().stack_pdfs(target, [target], tmp_path / "undo")
    assert _page_texts(target) == ["A Seite 1"]


def test_failed_stack_leaves_target_untouched(tmp_path: Path) -> None:
    target = tmp_path / "A.pdf"
    broken = tmp_path / "kaputt.pdf"
    _create_pdf(target, 1, "A")
    broken.write_bytes(b"keine PDF")
    with pytest.raises(fitz.FileDataError):
        FileManager().stack_pdfs(target, [broken], tmp_path / "undo")
    assert _page_texts(target) == ["A Seite 1"]
    assert broken.exists()
    assert not list(tmp_path.glob("*.stapel-tmp.pdf"))


def test_stack_multiple_sources_in_order_before_target(tmp_path: Path) -> None:
    target = tmp_path / "Ziel.pdf"
    a = tmp_path / "A.pdf"
    b = tmp_path / "B.pdf"
    _create_pdf(target, 2, "Ziel")
    _create_pdf(a, 1, "A")
    _create_pdf(b, 2, "B")

    FileManager().stack_pdfs(target, [a, b], tmp_path / "undo")

    assert _page_texts(target) == [
        "A Seite 1", "B Seite 1", "B Seite 2", "Ziel Seite 1", "Ziel Seite 2",
    ]


def test_restore_stack_is_byte_identical(tmp_path: Path) -> None:
    target = tmp_path / "A.pdf"
    b = tmp_path / "B.pdf"
    c = tmp_path / "C.pdf"
    _create_pdf(target, 1, "A")
    _create_pdf(b, 1, "B")
    _create_pdf(c, 2, "C")
    vorher = {p: p.read_bytes() for p in (target, b, c)}
    manager = FileManager()

    manager.restore_stack(manager.stack_pdfs(target, [b, c], tmp_path / "undo"))

    for pfad, daten in vorher.items():
        assert pfad.read_bytes() == daten


@pytest.mark.parametrize("winerror", [False, True])
def test_restore_stack_across_drives(tmp_path: Path, monkeypatch, winerror: bool) -> None:
    """Sicherung auf anderem Laufwerk: os.replace scheitert, es wird kopiert statt verloren."""
    docs = tmp_path / "docs"
    undo = tmp_path / "undo"
    docs.mkdir()
    target = docs / "A.pdf"
    b = docs / "B.pdf"
    _create_pdf(target, 1, "A")
    _create_pdf(b, 1, "B")
    vorher = {p: p.read_bytes() for p in (target, b)}
    manager = FileManager()
    backups = manager.stack_pdfs(target, [b], undo)

    echtes_replace = os.replace

    def replace_ueber_laufwerke(src, dst, *args, **kwargs):
        if Path(src).is_relative_to(undo) != Path(dst).is_relative_to(undo):
            if winerror:
                raise OSError(0, "anderes Laufwerk", str(src), 17, str(dst))
            raise OSError(errno.EXDEV, "Invalid cross-device link", str(src))
        return echtes_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace_ueber_laufwerke)
    restored = manager.restore_stack(backups)

    assert restored == [target, b]
    for pfad, daten in vorher.items():
        assert pfad.read_bytes() == daten
    assert not list(docs.glob("*.rueckgaengig-tmp*"))


def test_restore_stack_failure_keeps_backup(tmp_path: Path, monkeypatch) -> None:
    docs = tmp_path / "docs"
    undo = tmp_path / "undo"
    docs.mkdir()
    target = docs / "A.pdf"
    b = docs / "B.pdf"
    _create_pdf(target, 1, "A")
    _create_pdf(b, 1, "B")
    manager = FileManager()
    backups = manager.stack_pdfs(target, [b], undo)
    gestapelt = target.read_bytes()

    def kaputt(src, dst, *args, **kwargs):
        raise OSError(errno.EXDEV, "Invalid cross-device link", str(src))

    def copy_kaputt(*args, **kwargs):
        raise OSError(errno.ENOSPC, "voll")

    monkeypatch.setattr(os, "replace", kaputt)
    monkeypatch.setattr("src.core.file_manager.shutil.copy2", copy_kaputt)
    with pytest.raises(OSError):
        manager.restore_stack(backups)

    assert target.read_bytes() == gestapelt  # Ziel unveraendert
    assert backups[0][1].exists()  # Sicherung nicht verloren
    assert not list(docs.glob("*.rueckgaengig-tmp*"))

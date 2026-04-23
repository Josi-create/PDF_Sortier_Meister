import tempfile
from pathlib import Path

import fitz
import pytest

from src.core.file_manager import FileManager


def _create_pdf(path: Path, pages: int = 1) -> None:
    doc = fitz.open()
    try:
        for _ in range(pages):
            doc.new_page()
        doc.save(str(path))
    finally:
        doc.close()


def test_merge_pdfs_creates_single_pdf(tmp_path: Path) -> None:
    source1 = tmp_path / "doc1.pdf"
    source2 = tmp_path / "doc2.pdf"
    _create_pdf(source1, pages=1)
    _create_pdf(source2, pages=2)

    output_folder = tmp_path / "merged"
    output_folder.mkdir()

    manager = FileManager()
    merged_path = manager.merge_pdfs([source1, source2], output_folder, "zusammen.pdf")

    assert merged_path.exists()
    assert merged_path.suffix == ".pdf"

    with fitz.open(str(merged_path)) as merged_doc:
        assert len(merged_doc) == 3


def test_split_pdf_creates_one_file_per_page(tmp_path: Path) -> None:
    source = tmp_path / "original.pdf"
    _create_pdf(source, pages=3)
    output_folder = tmp_path / "splits"
    output_folder.mkdir()

    manager = FileManager()
    output_files = manager.split_pdf(source, output_folder)

    assert len(output_files) == 3
    for index, output_file in enumerate(output_files, start=1):
        assert output_file.exists()
        assert output_file.name == f"original_Seite_{index}.pdf"
        with fitz.open(str(output_file)) as doc:
            assert len(doc) == 1


def test_split_pdf_invalid_page_raises(tmp_path: Path) -> None:
    source = tmp_path / "original.pdf"
    _create_pdf(source, pages=2)
    output_folder = tmp_path / "splits"
    output_folder.mkdir()

    manager = FileManager()
    with pytest.raises(ValueError, match="Ungültige Seitenzahlen"):
        manager.split_pdf(source, output_folder, pages=[1, 5])

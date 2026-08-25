import sqlite3
from pathlib import Path

import fitz
import pytest

from src.utils.database import Database


def _create_pdf(path: Path) -> None:
    doc = fitz.open()
    try:
        doc.new_page()
        doc.save(str(path))
    finally:
        doc.close()


def _make_db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


def _seed_test_data(db: Database) -> None:
    db.index_document(
        file_path="/docs/a.pdf",
        filename="rechnung_telekom.pdf",
        extracted_text="Rechnung von der Telekom",
        keywords="rechnung,telekom",
        korrespondent="Telekom",
        kategorie="Rechnung",
        steuerjahr="2024",
        betrag="59.99",
    )
    db.index_document(
        file_path="/docs/b.pdf",
        filename="steuer_finanzamt.pdf",
        extracted_text="Steuerbescheid vom Finanzamt",
        keywords="steuer,finanzamt",
        korrespondent="Finanzamt",
        kategorie="Steuer",
        steuerjahr="2024",
        betrag="1200.00",
    )
    db.index_document(
        file_path="/docs/c.pdf",
        filename="vertrag_xy.pdf",
        extracted_text="Mietvertrag mit dem Vermieter",
        keywords="vertrag,vermieter",
        korrespondent="Vermieter GmbH",
        kategorie="Vertrag",
        steuerjahr="2023",
        betrag="850.00",
    )


def test_search_text_only(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    _seed_test_data(db)
    results = db.search_documents(query="Finanzamt")
    filenames = [r["filename"] for r in results]
    assert "steuer_finanzamt.pdf" in filenames
    assert "rechnung_telekom.pdf" not in filenames
    assert "vertrag_xy.pdf" not in filenames


def test_search_filter_kategorie_only(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    _seed_test_data(db)
    results = db.search_documents(query="", kategorie="Steuer")
    assert len(results) == 1
    assert results[0]["filename"] == "steuer_finanzamt.pdf"


def test_search_filter_steuerjahr(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    _seed_test_data(db)
    results = db.search_documents(query="", steuerjahr="2023")
    assert len(results) == 1
    assert results[0]["filename"] == "vertrag_xy.pdf"


def test_search_filter_korrespondent(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    _seed_test_data(db)
    results = db.search_documents(query="", korrespondent="Telekom")
    assert len(results) == 1
    assert results[0]["filename"] == "rechnung_telekom.pdf"


def test_search_filter_betrag_range(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    _seed_test_data(db)

    low = db.search_documents(query="", betrag_von=0.01, betrag_bis=100.0)
    low_names = [r["filename"] for r in low]
    assert "rechnung_telekom.pdf" in low_names
    assert "steuer_finanzamt.pdf" not in low_names
    assert "vertrag_xy.pdf" not in low_names

    high = db.search_documents(query="", betrag_von=100.0, betrag_bis=2000.0)
    high_names = [r["filename"] for r in high]
    assert "steuer_finanzamt.pdf" in high_names
    assert "vertrag_xy.pdf" in high_names
    assert "rechnung_telekom.pdf" not in high_names


def test_search_combined_filters(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    _seed_test_data(db)
    results = db.search_documents(query="", steuerjahr="2024", kategorie="Steuer")
    assert len(results) == 1
    assert results[0]["filename"] == "steuer_finanzamt.pdf"


def test_search_empty_returns_nothing(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    _seed_test_data(db)
    results = db.search_documents(query="")
    assert results == []


def test_get_distinct_steuerjahre_sorted(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    _seed_test_data(db)
    years = db.get_distinct_steuerjahre()
    assert years == ["2024", "2023"]  # DESC
    assert "" not in years


def test_get_distinct_kategorien_sorted(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    _seed_test_data(db)
    kategorien = db.get_distinct_kategorien()
    assert kategorien == sorted(kategorien)
    assert "" not in kategorien
    assert "Rechnung" in kategorien
    assert "Steuer" in kategorien
    assert "Vertrag" in kategorien


def test_get_distinct_korrespondenten_sorted(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    _seed_test_data(db)
    korrespondenten = db.get_distinct_korrespondenten()
    assert korrespondenten == sorted(korrespondenten)
    assert "" not in korrespondenten
    assert "Telekom" in korrespondenten
    assert "Finanzamt" in korrespondenten
    assert "Vermieter GmbH" in korrespondenten


def test_index_document_replaces_existing(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    db.index_document(
        file_path="/docs/unique.pdf",
        filename="unique.pdf",
        kategorie="Rechnung",
        korrespondent="OriginalFirma",
    )
    db.index_document(
        file_path="/docs/unique.pdf",
        filename="unique.pdf",
        kategorie="Steuer",
        korrespondent="NeueFirma",
    )
    rechnung_results = db.search_documents(query="", kategorie="Rechnung")
    steuer_results = db.search_documents(query="", kategorie="Steuer")
    assert all(r["file_path"] != "/docs/unique.pdf" for r in rechnung_results)
    assert any(r["file_path"] == "/docs/unique.pdf" for r in steuer_results)
    assert len(steuer_results) == 1


def test_betrag_text_storage_handles_non_numeric(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    _seed_test_data(db)
    db.index_document(
        file_path="/docs/d.pdf",
        filename="unbekannt.pdf",
        kategorie="Sonstiges",
        betrag="unknown",
    )
    results = db.search_documents(query="", betrag_von=0.01, betrag_bis=100.0)
    filenames = [r["filename"] for r in results]
    assert "unbekannt.pdf" not in filenames
    assert "rechnung_telekom.pdf" in filenames


# === update_pdf_path tests ===

def test_update_pdf_path_noop_same_path(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    db.index_document(file_path="/docs/a.pdf", filename="a.pdf", korrespondent="NoopFirma")
    result = db.update_pdf_path("/docs/a.pdf", "/docs/a.pdf", None)
    assert result is False
    rows = db.search_documents(query="", korrespondent="NoopFirma")
    assert len(rows) == 1
    assert rows[0]["file_path"] == "/docs/a.pdf"


def test_update_pdf_path_preserves_metadata(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    db.index_document(
        file_path="/old/a.pdf",
        filename="old.pdf",
        extracted_text="Alter Text",
        keywords="kw1,kw2",
        korrespondent="MetaFirma",
        kategorie="Rechnung",
        steuerjahr="2024",
        betrag="99.00",
        zusammenfassung="Alte Zusammenfassung",
        target_folder="/old/folder",
    )
    result = db.update_pdf_path("/old/a.pdf", "/new/b.pdf", "new.pdf")
    assert result is True
    rows = db.search_documents(query="", korrespondent="MetaFirma")
    assert len(rows) == 1
    assert rows[0]["file_path"] == "/new/b.pdf"
    assert rows[0]["korrespondent"] == "MetaFirma"
    assert rows[0]["kategorie"] == "Rechnung"
    assert rows[0]["steuerjahr"] == "2024"
    assert rows[0]["betrag"] == "99.00"
    assert rows[0]["zusammenfassung"] == "Alte Zusammenfassung"


def test_update_pdf_path_with_new_filename(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    db.index_document(file_path="/old/a.pdf", filename="old.pdf", korrespondent="RenameFirma")
    db.update_pdf_path("/old/a.pdf", "/new/b.pdf", "new.pdf")
    rows = db.search_documents(query="", korrespondent="RenameFirma")
    assert len(rows) == 1
    assert rows[0]["filename"] == "new.pdf"


def test_update_pdf_path_no_old_row(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    result = db.update_pdf_path("/nonexistent.pdf", "/new/b.pdf", "b.pdf")
    assert result is True
    assert db.get_search_index_count() == 1
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM document_search WHERE file_path = ?", ("/new/b.pdf",))
    row = cursor.fetchone()
    conn.close()
    assert row is not None


# === bulk_index_directory tests ===

def test_bulk_index_directory_analyze_false(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    for name in ("one.pdf", "two.pdf", "three.pdf"):
        _create_pdf(tmp_path / name)
    summary = db.bulk_index_directory(str(tmp_path), analyze=False, recursive=True)
    assert summary == {"scanned": 3, "indexed": 3, "skipped": 0, "errors": []}
    assert db.get_search_index_count() == 3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    cursor = conn.cursor()
    cursor.execute("SELECT extracted_text FROM document_search")
    rows = cursor.fetchall()
    conn.close()
    assert all(row[0] == "" for row in rows)


def test_bulk_index_directory_skips_existing(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    p1 = tmp_path / "x.pdf"
    p2 = tmp_path / "y.pdf"
    _create_pdf(p1)
    _create_pdf(p2)
    db.index_document(file_path=str(p1), filename=p1.name)
    db.index_document(file_path=str(p2), filename=p2.name)
    summary = db.bulk_index_directory(str(tmp_path))
    assert summary["skipped"] == 2
    assert summary["indexed"] == 0
    assert summary["errors"] == []


def test_bulk_index_directory_non_recursive(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    _create_pdf(tmp_path / "top1.pdf")
    _create_pdf(tmp_path / "top2.pdf")
    sub = tmp_path / "sub"
    sub.mkdir()
    _create_pdf(sub / "deep.pdf")
    summary = db.bulk_index_directory(str(tmp_path), recursive=False)
    assert summary["scanned"] == 2
    assert summary["indexed"] == 2


def test_bulk_index_directory_progress_callback_called(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        _create_pdf(tmp_path / name)
    calls = []
    db.bulk_index_directory(str(tmp_path), progress_callback=lambda c, t, f: calls.append((c, t)))
    assert len(calls) == 3


def test_bulk_index_directory_ignores_non_pdf(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    _create_pdf(tmp_path / "real1.pdf")
    _create_pdf(tmp_path / "real2.pdf")
    (tmp_path / "notes.txt").write_text("not a pdf")
    summary = db.bulk_index_directory(str(tmp_path))
    assert summary["scanned"] == 2
    assert summary["indexed"] == 2

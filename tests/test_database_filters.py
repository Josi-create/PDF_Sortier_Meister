from pathlib import Path

import pytest

from src.utils.database import Database


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

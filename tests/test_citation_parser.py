"""Tests fuer CitationParser (Phase 19 / M1 RAG)."""
import pytest

from src.rag.citation import CitationParser


def _retrieved_docs():
    """Vier typische Retrieved-Docs (retrieval.py-Format)."""
    return [
        {"index": 1, "filename": "2024-01-15_Telekom.pdf", "file_path": "/docs/telekom.pdf"},
        {"index": 2, "filename": "2023-12-04_Stadtwerke.pdf", "file_path": "/docs/stadtwerke.pdf"},
        {"index": 3, "filename": "2023-03-01_GEZ.pdf", "file_path": "/docs/gez.pdf"},
    ]


def test_parse_inline_only():
    p = CitationParser()
    raw = "Laut [1] und [3] ist die Lage klar."
    cleaned, valid, dropped = p.parse(raw, _retrieved_docs())
    assert len(valid) == 2
    assert {c.index for c in valid} == {1, 3}
    assert dropped == []
    # Inline-Marker bleiben in der bereinigten Antwort
    assert "[1]" in cleaned
    assert "[3]" in cleaned


def test_parse_footer_only():
    p = CitationParser()
    raw = "Die Rechnung ist hoch.\n\nQuellen:\n[1] 2024-01-15_Telekom.pdf\n[2] 2023-12-04_Stadtwerke.pdf"
    cleaned, valid, dropped = p.parse(raw, _retrieved_docs())
    assert len(valid) == 2
    assert {c.index for c in valid} == {1, 2}


def test_parse_combined():
    p = CitationParser()
    raw = (
        "Wie [1] zeigt und auch [2] bestaetigt, ist alles in Ordnung.\n"
        "\n"
        "Quellen:\n"
        "[1] 2024-01-15_Telekom.pdf\n"
        "[2] 2023-12-04_Stadtwerke.pdf\n"
        "[3] 2023-03-01_GEZ.pdf"
    )
    cleaned, valid, dropped = p.parse(raw, _retrieved_docs())
    assert len(valid) == 3
    assert {c.index for c in valid} == {1, 2, 3}
    assert dropped == []


def test_parse_validates_against_retrieved():
    p = CitationParser()
    # [99] ist nicht im Retrieval-Set -> dropped
    raw = "Laut [1] und [99] stimmt das."
    cleaned, valid, dropped = p.parse(raw, _retrieved_docs())
    assert len(valid) == 1
    assert valid[0].index == 1
    assert len(dropped) == 1
    assert dropped[0].index == 99
    # Der invalide Marker [99] muss aus dem Text entfernt sein
    assert "[99]" not in cleaned


def test_parse_drops_all_invalid():
    p = CitationParser()
    raw = "Laut [50] und [99] stimmt etwas."
    cleaned, valid, dropped = p.parse(raw, _retrieved_docs())
    assert valid == []
    assert len(dropped) == 2
    # Antwort enthaelt keine Marker mehr
    assert "[" not in cleaned
    assert "]" not in cleaned


def test_parse_empty_answer():
    p = CitationParser()
    cleaned, valid, dropped = p.parse("", _retrieved_docs())
    assert cleaned == ""
    assert valid == []
    assert dropped == []


def test_parse_accepts_retrieveddoc_objects():
    """Parser akzeptiert auch RetrievedDoc-Instanzen (Attribute statt Dict-Keys)."""
    from src.rag.retrieval import RetrievedDoc
    p = CitationParser()
    docs = [
        RetrievedDoc(index=1, file_path="/a.pdf", filename="a.pdf",
                     text_snippet="...", rank=0.0),
    ]
    raw = "Laut [1] ist alles klar."
    cleaned, valid, dropped = p.parse(raw, docs)
    assert len(valid) == 1
    assert valid[0].filename == "a.pdf"

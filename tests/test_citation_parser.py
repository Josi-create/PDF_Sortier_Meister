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


# --------------------------------------------------------------------- #
# M3-Hardening: Edge-Cases
# --------------------------------------------------------------------- #

def test_parse_zero_index_marker():
    """[0] ohne weitere gueltige Marker -> dropped, Text bereinigt."""
    p = CitationParser()
    raw = "[0] alleine"
    cleaned, valid, dropped = p.parse(raw, _retrieved_docs())
    assert valid == []
    assert len(dropped) == 1
    assert dropped[0].index == 0
    # Marker wurde aus dem Text entfernt
    assert "[0]" not in cleaned
    assert "alleine" in cleaned


def test_parse_duplicate_inline_no_space():
    """'[1][1]' zaehlt als ein gueltiges Citation (kein doppeltes valid-Item)."""
    p = CitationParser()
    raw = "[1][1] doppelt"
    cleaned, valid, dropped = p.parse(raw, _retrieved_docs())
    assert len(valid) == 1
    assert valid[0].index == 1
    assert dropped == []
    # Beide Marker bleiben im Text (sind valid)
    assert cleaned.count("[1]") == 2


def test_parse_duplicate_inline_with_space():
    """'[1] [1]' wird ebenfalls dedupliziert (valid-Liste enthaelt 1 Eintrag)."""
    p = CitationParser()
    raw = "[1] [1] doppelt mit Leerzeichen"
    cleaned, valid, dropped = p.parse(raw, _retrieved_docs())
    assert len(valid) == 1
    assert valid[0].index == 1
    assert dropped == []


def test_parse_footer_only_no_inline():
    """'Quellen: [1] [2]' ohne [N] im Body -> valid ueber Footer-Match."""
    p = CitationParser()
    raw = (
        "Antwort ohne Body-Marker.\n\n"
        "Quellen:\n"
        "[1] 2024-01-15_Telekom.pdf\n"
        "[2] 2023-12-04_Stadtwerke.pdf"
    )
    cleaned, valid, dropped = p.parse(raw, _retrieved_docs())
    assert {c.index for c in valid} == {1, 2}
    assert dropped == []
    # Body-Text bleibt erhalten
    assert "Antwort ohne Body-Marker." in cleaned


def test_parse_body_only_no_footer():
    """'[1] [2]' im Text ohne 'Quellen:'-Zeile -> valid ueber Inline-Match."""
    p = CitationParser()
    raw = "Laut [1] und [2] ist die Lage klar. Mehr Text ohne Liste."
    cleaned, valid, dropped = p.parse(raw, _retrieved_docs())
    assert {c.index for c in valid} == {1, 2}
    assert dropped == []
    # Es gibt keine Quellen-Zeile, der Body-Text bleibt komplett.
    # "Quellen:" (mit Doppelpunkt) als Fusszeilen-Praefix darf NICHT vorkommen.
    assert "Quellen:" not in cleaned
    assert "Mehr Text ohne Liste." in cleaned


def test_parse_unknown_indices_dropped():
    """[99] und [42] sind nicht in der Whitelist -> werden gedroppt."""
    p = CitationParser()
    raw = "Laut [99] und [42] stimmt etwas."
    cleaned, valid, dropped = p.parse(raw, _retrieved_docs())
    assert valid == []
    assert {c.index for c in dropped} == {42, 99}
    # Beide invaliden Marker muessen aus dem Text entfernt sein
    assert "[99]" not in cleaned
    assert "[42]" not in cleaned
    # Der umgebende Text bleibt erhalten
    assert "Laut" in cleaned
    assert "stimmt etwas." in cleaned


def test_parse_out_of_range_indices():
    """Bei 3 Quellen ist [5] ungueltig -> dropped."""
    p = CitationParser()
    raw = "Laut [5] stimmt etwas."
    cleaned, valid, dropped = p.parse(raw, _retrieved_docs())
    assert valid == []
    assert len(dropped) == 1
    assert dropped[0].index == 5
    assert "[5]" not in cleaned


def test_parse_mixed_valid_and_invalid():
    """'[1] text [2] text [99] text' -> 2 valid, 1 dropped."""
    p = CitationParser()
    raw = "[1] text [2] text [99] text"
    cleaned, valid, dropped = p.parse(raw, _retrieved_docs())
    assert {c.index for c in valid} == {1, 2}
    assert {c.index for c in dropped} == {99}
    # Nur die invaliden Marker werden entfernt, die validen bleiben
    assert "[1]" in cleaned
    assert "[2]" in cleaned
    assert "[99]" not in cleaned


def test_parse_unicode_filenames():
    """Sonderzeichen (Umlaute) in Dateinamen duerfen nicht crashen."""
    docs_unicode = [
        {"index": 1, "filename": "Umlaut_ä_ö_ü.pdf", "file_path": "/docs/umlaut.pdf"},
        {"index": 2, "filename": "Sonderzeichen_ß_&-.pdf", "file_path": "/docs/sz.pdf"},
    ]
    p = CitationParser()
    raw = (
        "Laut [1] und [2] ist alles klar.\n\n"
        "Quellen:\n"
        "[1] Umlaut_ä_ö_ü.pdf\n"
        "[2] Sonderzeichen_ß_&-.pdf"
    )
    cleaned, valid, dropped = p.parse(raw, docs_unicode)
    assert {c.index for c in valid} == {1, 2}
    assert dropped == []
    # Umlaut-Filename kommt in der cleaned-Antwort vor
    assert "Umlaut_ä_ö_ü.pdf" in cleaned


def test_parse_very_long_marker_list():
    """20+ Marker: nur die in der Whitelist werden valid, Rest dropped."""
    p = CitationParser()
    # 1..24 -> 3 valid (1,2,3), 21 dropped (4..24)
    raw = " ".join(f"[{i}]" for i in range(1, 25))
    cleaned, valid, dropped = p.parse(raw, _retrieved_docs())
    assert {c.index for c in valid} == {1, 2, 3}
    assert len(dropped) == 21
    assert max(c.index for c in dropped) == 24
    # Im bereinigten Text nur [1] [2] [3] uebrig
    assert "[1]" in cleaned
    assert "[2]" in cleaned
    assert "[3]" in cleaned
    for invalid in (4, 5, 10, 20, 24):
        assert f"[{invalid}]" not in cleaned


def test_parse_no_markers_in_text():
    """Reine Antwort ohne Quellen-Marker -> 0 valid, 0 dropped, cleaned=text."""
    p = CitationParser()
    raw = "Antwort ohne Quellen"
    cleaned, valid, dropped = p.parse(raw, _retrieved_docs())
    assert cleaned == "Antwort ohne Quellen"
    assert valid == []
    assert dropped == []


def test_parse_no_markers_with_empty_docs():
    """Antwort ohne Marker UND ohne retrieved_docs -> leeres Ergebnis, kein Crash."""
    p = CitationParser()
    raw = "Irgendeine Antwort ohne Citation-Marker."
    cleaned, valid, dropped = p.parse(raw, [])
    assert cleaned == "Irgendeine Antwort ohne Citation-Marker."
    assert valid == []
    assert dropped == []


def test_parse_with_none_retrieved_docs():
    """Defensiv: retrieved_docs=None darf nicht crashen."""
    p = CitationParser()
    raw = "Laut [1] stimmt etwas."
    cleaned, valid, dropped = p.parse(raw, None)
    # Keine Whitelist -> [1] wird gedroppt
    assert valid == []
    assert len(dropped) == 1
    assert dropped[0].index == 1
    assert "[1]" not in cleaned


def test_parse_with_none_answer():
    """Defensiv: raw_answer=None darf nicht crashen."""
    p = CitationParser()
    cleaned, valid, dropped = p.parse(None, _retrieved_docs())
    assert cleaned == ""
    assert valid == []
    assert dropped == []


def test_parse_duplicate_dropped_kept_once():
    """[99][99] (zwei identische ungueltige) -> ein Eintrag in dropped, Text bereinigt."""
    p = CitationParser()
    raw = "Laut [99][99] stimmt etwas."
    cleaned, valid, dropped = p.parse(raw, _retrieved_docs())
    assert valid == []
    assert len(dropped) == 1
    assert dropped[0].index == 99
    assert "[99]" not in cleaned

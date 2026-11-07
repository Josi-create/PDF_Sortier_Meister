"""CitationParser (Issue #166/#167): Zitate in der Form ``[D7]`` zaehlen wie ``[7]``."""
from src.rag.citation import CitationParser

DOCS = [
    {"index": 1, "filename": "scan.pdf", "file_path": "/s/scan.pdf", "seite": 0},
    {"index": 7, "filename": "abrechnung.pdf", "file_path": "/a/abrechnung.pdf", "seite": 2},
]


def test_inline_marker_mit_d_praefix():
    cleaned, valid, dropped = CitationParser().parse(
        "Die Abnahmestelle steht in [D7], der Vertrag in [1]; [D9] gibt es nicht.\n\nQuellen:\n[D7] abrechnung.pdf",
        DOCS,
    )
    assert [c.index for c in valid] == [1, 7]
    assert valid[1].file_path == "/a/abrechnung.pdf" and valid[1].seite == 2
    assert [c.index for c in dropped] == [9]
    # Gueltige Marker bleiben in der Schreibweise des Modells, ungueltige verschwinden
    assert "[D7]" in cleaned and "[1]" in cleaned and "[D9]" not in cleaned


def test_neu_durchnummerierte_quellenliste_meint_die_dokumentnummern():
    docs = DOCS + [{"index": 8, "filename": "uebersicht.xlsx", "file_path": "/u/uebersicht.xlsx", "seite": 1}]
    antwort = (
        "Die Nummer steht in [D1], in [D7] und [D8] fehlt sie.\n\n"
        "**Quellen**\n[1] D1 – Vertragsnummer\n[2] D7 – keine Erwähnung\n[3] D8 – keine Erwähnung\n"
    )
    cleaned, valid, dropped = CitationParser().parse(antwort, docs)
    assert [c.index for c in valid] == [1, 7, 8]
    assert dropped == []
    # Die Liste traegt danach die Dokumentnummern
    assert "[7] D7 – keine" in cleaned and "[8] D8 – keine" in cleaned and "[2] D7" not in cleaned
    # Eine Liste mit Dokumentnummern bleibt unveraendert; "D" mitten im Wort zaehlt nicht
    cleaned2, valid2, _ = CitationParser().parse("Siehe [7].\nQuellen:\n[7] D7 – abrechnung.pdf\n[1] Dokument eins", docs)
    assert [c.index for c in valid2] == [1, 7] and "[7] D7" in cleaned2 and "[1] Dokument eins" in cleaned2


def test_kleines_d_und_gemischte_schreibweisen():
    _cleaned, valid, _dropped = CitationParser().parse("Siehe [d7] und [D1].", DOCS)
    assert [c.index for c in valid] == [1, 7]

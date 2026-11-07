"""Analyse von .docx/.xlsx fuer die Ordner-Vorschlaege (Issue #9) - Qt-frei.

Text kommt aus dem Suchmodul (``src.search.office``), Schluesselwoerter und
Daten aus derselben Logik wie bei PDFs. Bei .docx mit Datumsfeldern
(PRINTDATE/DATE/TIME) steht das ``lastPrinted``-Datum vorn: Das im Text
gespeicherte Feldergebnis ist das Datum irgendeines frueheren Ausdrucks.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.core.office_convert import WORD_ENDUNGEN, druckdatum, hat_datumsfelder


def analysiere(pfad: Path | str) -> tuple[str, list[str], list[datetime]]:
    """Text, Schluesselwoerter und Daten (Dokumentdatum zuerst) einer .docx/.xlsx."""
    from src.core.pdf_analyzer import PDFAnalyzer  # erst hier: zieht fitz/Qt

    pfad = Path(pfad)
    text = ""
    try:
        from src.search.office import office_text

        seiten = office_text(str(pfad), pfad.suffix.lower().lstrip(".")).get("seiten") or []
        text = "\n".join(str(s[2]) for s in seiten)
    except Exception:  # noqa: BLE001 - kaputte/verschluesselte Datei: ohne Text weiter
        pass
    analyzer = PDFAnalyzer.from_text(pfad, text)
    keywords = analyzer.extract_keywords()
    daten = analyzer.extract_dates()
    if pfad.suffix.lower() in WORD_ENDUNGEN and hat_datumsfelder(pfad):
        gedruckt, quelle = druckdatum(pfad)
        if quelle == "lastPrinted":
            daten = [gedruckt] + [d for d in daten if d.date() != gedruckt.date()]
    return text, keywords, daten

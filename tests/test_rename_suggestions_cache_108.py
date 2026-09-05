"""Issue #108: Dateinamen-Vorschlaege duerfen die PDF nicht erneut oeffnen,
wenn Text, Stichwoerter und Datumsangaben schon aus dem Cache vorliegen.

Vorher rief generate_rename_suggestions() trotz uebergebener Cache-Werte
PDFAnalyzer.suggest_filename() auf, das alles neu extrahierte - bei
Scan-PDFs inklusive Tesseract-OCR ueber 5 Seiten im GUI-Thread (7 s Freeze
pro Klick im Log des Users vom 30.08.2026).
"""
from datetime import datetime
from pathlib import Path

import fitz
import pytest

from src.core.pdf_analyzer import PDFAnalyzer, coerce_date, coerce_dates
from src.gui.rename_dialog import generate_rename_suggestions


def _pdf(path: Path, text: str) -> Path:
    d = fitz.open(); p = d.new_page(); p.insert_text((72, 72), text); d.save(str(path)); d.close()
    return path


# --- coerce_date ----------------------------------------------------------

@pytest.mark.parametrize("value", [
    "2026-05-12 00:00:00",          # so speichert der PDF-Cache (str(datetime))
    "2026-05-12",
    "12.05.2026",
    datetime(2026, 5, 12),
])
def test_coerce_date_accepts_cache_formats(value):
    assert coerce_date(value) == datetime(2026, 5, 12)


def test_coerce_dates_drops_garbage():
    assert coerce_dates(["2026-05-12 00:00:00", "kein datum", None]) == [datetime(2026, 5, 12)]
    assert coerce_dates(None) == []


# --- suggest_filename mit Cache-Werten --------------------------------------

def test_suggest_filename_with_cache_values_does_not_open_pdf(tmp_path):
    """Die Datei existiert nicht - jedes Oeffnen wuerde fliegen."""
    analyzer = PDFAnalyzer(tmp_path / "gibt_es_nicht.pdf")
    name = analyzer.suggest_filename(
        text="Rechnung der Muster GmbH vom 15.03.2026",
        keywords=["rechnung"],
        dates=["2026-03-15 00:00:00"],
    )
    assert name == "Rechnung Muster 2026-03.pdf"


def test_suggest_filename_without_args_still_extracts(tmp_path):
    pdf = _pdf(tmp_path / "scan.pdf", "Rechnung Nr. 42 vom 15.03.2026, zahlbar sofort.")
    with PDFAnalyzer(pdf) as a:
        assert a.suggest_filename().startswith("Rechnung")


# --- generate_rename_suggestions --------------------------------------------

def test_generate_suggestions_from_cache_never_opens_pdf(tmp_path, monkeypatch):
    opened = []
    real_open = PDFAnalyzer.open
    monkeypatch.setattr(PDFAnalyzer, "open", lambda self: opened.append(self.pdf_path) or real_open(self))

    suggestions = generate_rename_suggestions(
        pdf_path=tmp_path / "gibt_es_nicht.pdf",
        extracted_text="Rechnung der Muster GmbH vom 15.03.2026",
        keywords=["rechnung"],
        dates=["2026-03-15 00:00:00"],
    )

    assert opened == []
    reasons = {s.reason: s.name for s in suggestions}
    assert reasons["Automatisch erkannt"] == "Rechnung Muster 2026-03.pdf"
    assert reasons["Nur Datum"] == "2026-03-15.pdf"          # vorher "2026-03-15 00:00:00.pdf"
    assert reasons["Datum + Kategorie (Rechnung)"] == "2026-03-15 Rechnung.pdf"


def test_generate_suggestions_empty_cache_text_means_no_ocr_retry(tmp_path, monkeypatch):
    """Leerer Text im Cache (OCR fand nichts) ist ein Ergebnis, kein Fehlen:
    die PDF darf trotzdem nicht erneut geoeffnet werden."""
    opened = []
    monkeypatch.setattr(PDFAnalyzer, "open", lambda self: opened.append(1))

    generate_rename_suggestions(
        pdf_path=tmp_path / "scan.pdf", extracted_text="", keywords=[], dates=[]
    )

    assert opened == []


def test_generate_suggestions_opens_pdf_only_when_something_is_missing(tmp_path):
    pdf = _pdf(tmp_path / "scan.pdf", "Rechnung Nr. 42 vom 15.03.2026, zahlbar sofort.")
    suggestions = generate_rename_suggestions(pdf_path=pdf, extracted_text=None)
    assert any(s.reason == "Automatisch erkannt" for s in suggestions)

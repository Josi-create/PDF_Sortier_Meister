"""Issue #59: Analyse-Methoden waren versehentlich in find_tesseract()
verschachtelt statt Methoden von PDFAnalyzer - jede Hintergrund-Analyse
schlug mit AttributeError fehl."""
import fitz

from src.core.pdf_analyzer import PDFAnalyzer


def _pdf(path, text):
    d = fitz.open(); p = d.new_page(); p.insert_text((72, 72), text); d.save(str(path)); d.close()


def test_analyse_methoden_sind_klassenmethoden():
    for name in ("get_metadata", "extract_dates", "extract_keywords",
                 "suggest_filename", "_extract_company_name"):
        assert callable(getattr(PDFAnalyzer, name, None)), (
            f"PDFAnalyzer.{name} fehlt (Issue #59: in find_tesseract() verschachtelt?)"
        )


def test_analyse_pipeline_liefert_ergebnisse(tmp_path):
    pdf = tmp_path / "rechnung.pdf"
    _pdf(pdf, "Rechnung Nr. 42 vom 15.03.2026 ueber 100 Euro, zahlbar sofort.")

    with PDFAnalyzer(pdf) as analyzer:
        text = analyzer.extract_text(use_ocr=False)
        keywords = analyzer.extract_keywords()
        dates = analyzer.extract_dates()
        metadata = analyzer.get_metadata()

    assert "Rechnung" in text
    assert "rechnung" in keywords
    assert dates, "15.03.2026 sollte als Datum erkannt werden"
    assert metadata["page_count"] == 1

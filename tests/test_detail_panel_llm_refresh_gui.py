"""Detail-Panel zieht KI-Vorschlaege nach, die im Hintergrund fuer die gerade
ausgewaehlte PDF eintreffen - ohne dass man eine andere PDF anklicken muss."""
from PyQt6.QtTest import QTest

from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401 - Fixtures


def _prepare(win, tmp_path, name="scan.pdf"):
    from src.core.pdf_cache import PDFAnalysisResult
    pdf = tmp_path / name
    pdf.write_bytes(b"%PDF-1.4")
    result = PDFAnalysisResult(pdf_path=pdf, extracted_text="Rechnung Testfirma", keywords=["rechnung"], dates=[], file_modified=pdf.stat().st_mtime)
    win.pdf_cache._cache[pdf] = result
    win.selected_pdf = pdf
    win.selected_pdfs = []
    win.detail_panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text=result.extracted_text, keywords=result.keywords)
    return pdf


def _llm_arrives(win, pdf):
    from src.core.pdf_cache import LLMSuggestion
    win.pdf_cache._cache[pdf].llm_suggestions = [LLMSuggestion(
        filename="2024-01-31_Rechnung_Testfirma.pdf", confidence=0.95, source="llm",
        metadata={"korrespondent": "Testfirma GmbH", "subject": "Rechnung"},
    )]
    win.pdf_cache._cache[pdf].llm_fetched = True
    win._on_llm_suggestions_ready(pdf)


def test_panel_updates_when_llm_result_arrives(main_window, tmp_path):
    pdf = _prepare(main_window, tmp_path)
    assert main_window.detail_panel.name_input.text() == ""
    _llm_arrives(main_window, pdf)
    assert main_window.detail_panel.name_input.text() == "2024-01-31_Rechnung_Testfirma"
    assert main_window.detail_panel.get_metadata()["korrespondent"] == "Testfirma GmbH"


def test_no_update_when_user_already_edited(main_window, tmp_path):
    pdf = _prepare(main_window, tmp_path)
    QTest.keyClicks(main_window.detail_panel._metadata_inputs["korrespondent"], "Meine Firma")
    assert main_window.detail_panel.has_user_edits()
    _llm_arrives(main_window, pdf)
    assert main_window.detail_panel.name_input.text() == ""
    assert main_window.detail_panel.get_metadata()["korrespondent"] == "Meine Firma"


def test_no_update_for_other_pdf(main_window, tmp_path):
    pdf = _prepare(main_window, tmp_path)
    other = tmp_path / "andere.pdf"
    other.write_bytes(b"%PDF-1.4")
    from src.core.pdf_cache import PDFAnalysisResult
    main_window.pdf_cache._cache[other] = PDFAnalysisResult(pdf_path=other, extracted_text="x", keywords=[], dates=[])
    _llm_arrives(main_window, other)
    assert main_window.detail_panel.name_input.text() == ""
    assert main_window.detail_panel.get_current_pdf() == pdf


def test_edit_pattern_button_opens_settings_on_dateinamen_tab(main_window, monkeypatch):
    """"Muster bearbeiten" in der Vorschlags-Kopfzeile -> Einstellungen, Tab Dateinamen."""
    from src.gui import main_window as mw_mod
    seen = {}

    def fake_exec(self):
        seen["tab"] = self.tab_widget.tabText(self.tab_widget.currentIndex())
        return 0

    monkeypatch.setattr(mw_mod.SettingsDialog, "exec", fake_exec)
    main_window.detail_panel.edit_pattern_btn.click()
    assert seen["tab"] == "Dateinamen"


def test_settings_change_refreshes_header_switch(main_window):
    cfg = main_window.config
    cfg.set("folder_naming_enabled", True, auto_save=False)
    main_window._on_settings_changed()
    assert main_window.detail_panel.folder_naming_checkbox.isChecked()


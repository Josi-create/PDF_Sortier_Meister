"""Issue #81: Kacheln mit vorhandenem KI-Vorschlag sind gruen hinterlegt."""
from pathlib import Path

import pytest

from tests.test_main_window_gui import fresh_singletons, main_window, _scan_tree  # noqa: F401 - Fixtures


@pytest.fixture
def thumbnail(qtbot, monkeypatch, tmp_path):
    from src.gui import pdf_thumbnail as th
    monkeypatch.setattr(th.ThumbnailLoaderThread, "start", lambda self: None)
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    widget = th.PDFThumbnailWidget(pdf)
    qtbot.addWidget(widget)
    return widget


def test_marker_changes_style_and_tooltip(thumbnail):
    from src.gui.pdf_thumbnail import PDFThumbnailWidget
    assert not thumbnail.has_ai_suggestion
    assert PDFThumbnailWidget.AI_BACKGROUND not in thumbnail.styleSheet()

    thumbnail.has_ai_suggestion = True
    assert PDFThumbnailWidget.AI_BACKGROUND in thumbnail.styleSheet()
    assert "KI-Vorschlag vorhanden" in thumbnail.toolTip()

    thumbnail.has_ai_suggestion = False
    assert PDFThumbnailWidget.AI_BACKGROUND not in thumbnail.styleSheet()
    assert "KI-Vorschlag" not in thumbnail.toolTip()


def test_selection_wins_over_marker_and_returns_to_green(thumbnail):
    from src.gui.pdf_thumbnail import PDFThumbnailWidget
    thumbnail.has_ai_suggestion = True
    thumbnail.selected = True
    assert "#cce5ff" in thumbnail.styleSheet()
    assert PDFThumbnailWidget.AI_BACKGROUND not in thumbnail.styleSheet()
    thumbnail.selected = False
    assert PDFThumbnailWidget.AI_BACKGROUND in thumbnail.styleSheet()


def _cache_llm(win, pdf: Path):
    from src.core.pdf_cache import LLMSuggestion, PDFAnalysisResult
    # file_modified muss stimmen, sonst verwirft PDFCache.get() den Eintrag als veraltet
    result = win.pdf_cache._cache.get(pdf) or PDFAnalysisResult(
        pdf_path=pdf, extracted_text="x", file_modified=pdf.stat().st_mtime
    )
    result.llm_suggestions = [LLMSuggestion(filename="2024-01-31_Bank_Kontoauszug.pdf", confidence=0.9)]
    result.llm_fetched = True
    win.pdf_cache._cache[pdf] = result


def test_widget_is_green_when_cache_already_has_suggestion(main_window, fresh_singletons):
    scan = _scan_tree(fresh_singletons["tmp_path"])
    pdf = scan / "Banken" / "kontoauszug.pdf"
    _cache_llm(main_window, pdf)
    main_window._navigate_to_folder(scan / "Banken")
    (widget,) = main_window.pdf_widgets
    assert widget.has_ai_suggestion


def test_widget_turns_green_when_suggestion_arrives(main_window, fresh_singletons):
    scan = _scan_tree(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan / "Banken")
    (widget,) = main_window.pdf_widgets
    assert not widget.has_ai_suggestion

    _cache_llm(main_window, widget.pdf_path)
    main_window._on_llm_suggestions_ready(widget.pdf_path)
    assert widget.has_ai_suggestion


def test_manual_ki_result_in_detail_panel_marks_widget(main_window, fresh_singletons):
    """update_llm_suggestions (Detail-Panel-Aufruf) meldet sich wie der Hintergrund-Abruf."""
    from src.core.pdf_cache import LLMSuggestion, PDFAnalysisResult
    scan = _scan_tree(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan / "Banken")
    (widget,) = main_window.pdf_widgets
    pdf = widget.pdf_path
    main_window.pdf_cache._cache[pdf] = PDFAnalysisResult(
        pdf_path=pdf, extracted_text="x", file_modified=pdf.stat().st_mtime
    )

    main_window.pdf_cache.update_llm_suggestions(
        pdf, [LLMSuggestion(filename="2024-01-31_Bank_Kontoauszug.pdf", confidence=0.9)]
    )
    assert widget.has_ai_suggestion

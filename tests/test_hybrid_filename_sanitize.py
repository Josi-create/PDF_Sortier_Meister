"""HybridClassifier bereinigt KI-Dateinamen fuer alle Provider (auch ohne
eigenen Sanitizer, z.B. Ollama/OpenRouter)."""
from src.ml.llm_provider import LLMResponse


class _StubProvider:
    def __init__(self, filename):
        self._filename = filename

    def suggest_filename(self, **kwargs):
        return LLMResponse(
            success=True,
            filename_suggestion=self._filename,
            filename_reason="stub",
            confidence=0.8,
        )


def _make_classifier(filename):
    from src.ml.hybrid_classifier import HybridClassifier

    clf = HybridClassifier.__new__(HybridClassifier)
    clf.llm_provider = _StubProvider(filename)
    clf.last_llm_error = None
    clf.total_tokens_used = 0
    return clf


def _call(clf):
    return clf._get_llm_filename_suggestion(
        text="x", current_filename="scan.pdf", keywords=[],
        detected_date=None, target_folder=None,
    )


def test_llm_filename_with_email_is_sanitized():
    clf = _make_classifier("2013-04-23_Meldung_kathrin.haerle@web.de.pdf")
    result = _call(clf)
    assert result is not None
    assert result.filename == "2013-04-23_Meldung_Kathrin_Haerle.pdf"
    assert clf.last_llm_error is None


def test_llm_filename_only_invalid_chars_is_rejected():
    clf = _make_classifier("@@@.pdf")
    assert _call(clf) is None
    assert "ungueltigen Zeichen" in clf.last_llm_error

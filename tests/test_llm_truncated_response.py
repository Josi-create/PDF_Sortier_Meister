"""Leere/abgeschnittene KI-Antworten (Reasoning-Modelle + kleines max_tokens) sind Fehler.

Hintergrund: z-ai/glm-5.3-flash verbrauchte mit max_tokens=500 sein ganzes
Budget fuers Nachdenken, content war leer, finish_reason="length". Die App
wertete das als Erfolg ohne Vorschlag und cachte es still - kein KI-Dateiname.
"""
import types


def _make_provider(content, finish_reason, max_tokens=500):
    from src.ml.llm_provider import LLMConfig
    from src.ml.openai_provider import OpenAIProvider

    p = OpenAIProvider(LLMConfig(api_key="sk-test", model="gpt-4.1-nano", max_tokens=max_tokens))
    choice = types.SimpleNamespace(
        finish_reason=finish_reason,
        message=types.SimpleNamespace(content=content),
    )
    response = types.SimpleNamespace(choices=[choice], usage=None)
    p._openai = types.SimpleNamespace(
        APIConnectionError=type("A", (Exception,), {}),
        RateLimitError=type("B", (Exception,), {}),
        AuthenticationError=type("C", (Exception,), {}),
    )
    p._client = types.SimpleNamespace(
        chat=types.SimpleNamespace(
            completions=types.SimpleNamespace(create=lambda **kw: response)
        )
    )
    p.is_available = lambda: True
    return p


def test_empty_content_with_length_is_failure_and_mentions_max_tokens():
    p = _make_provider("", "length", max_tokens=500)
    r = p.suggest_filename(text="Rechnung", current_filename="scan.pdf")
    assert r.success is False
    assert r.filename_suggestion is None
    assert "500" in r.error_message
    assert "Max. Tokens" in r.error_message


def test_truncated_json_is_failure():
    p = _make_provider('{"filename": "2024-01-31_Rech', "length")
    r = p.suggest_filename(text="Rechnung", current_filename="scan.pdf")
    assert r.success is False
    assert "abgeschnitten" in r.error_message


def test_unparseable_answer_is_failure():
    p = _make_provider("Hier ist mein Vorschlag: Rechnung.pdf", "stop")
    r = p.suggest_filename(text="Rechnung", current_filename="scan.pdf")
    assert r.success is False
    assert "nicht lesbar" in r.error_message


def test_valid_answer_still_succeeds():
    p = _make_provider(
        '{"filename": "2024-01-31_Rechnung_HUK.pdf", "reason": "ok", "confidence": 0.9,'
        ' "metadata": {"category": "Rechnung", "beschreibung": "Leistungsabrechnung"}}',
        "stop",
    )
    r = p.suggest_filename(text="Rechnung", current_filename="scan.pdf")
    assert r.success is True
    assert r.filename_suggestion == "2024-01-31_Rechnung_HUK.pdf"
    assert r.metadata["description"] == "Leistungsabrechnung"


def test_folder_classification_empty_answer_is_failure():
    p = _make_provider("", "length")
    r = p.classify_document("text", ["Rechnungen"])
    assert r.success is False


def test_hybrid_records_last_llm_error():
    from src.ml.hybrid_classifier import HybridClassifier

    hc = HybridClassifier.__new__(HybridClassifier)
    hc.llm_provider = _make_provider("", "length")
    hc.total_tokens_used = 0
    hc.last_llm_error = None
    assert hc._get_llm_filename_suggestion("t", "a.pdf", None, None, None) is None
    assert "Max. Tokens" in hc.last_llm_error

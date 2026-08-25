"""Tests fuer RAG-Prompts (Phase 19 / M1 RAG)."""
from src.rag.prompts import (
    SYSTEM_PROMPT,
    build_context_block,
    build_user_prompt,
)


def test_system_prompt_contains_all_six_rules():
    """System-Prompt muss alle 6 Regeln aus der Architektur enthalten."""
    for needle in [
        "NUR",  # Regel 1
        "NICHT",  # Variante mit caps aus dem System-Prompt
        "Quellen",  # Regel 5
        "Sprache",  # Regel 6
        "[1]",  # Citation-Hinweis
        "Erfinde",  # Regel 3
    ]:
        assert needle in SYSTEM_PROMPT, f"System-Prompt fehlt: {needle!r}"


def test_system_prompt_is_verbatim_per_architecture():
    """Spot-Check: Ein bekannter Satz muss wortwoertlich enthalten sein."""
    assert "private PDF-Sammlung" in SYSTEM_PROMPT
    assert "Antworte NUR" in SYSTEM_PROMPT or "Antworte nur" in SYSTEM_PROMPT.lower()


def test_build_context_block_includes_all_doc_fields():
    docs = [
        {
            "index": 1,
            "filename": "test.pdf",
            "kategorie": "Rechnung",
            "steuerjahr": "2024",
            "betrag": "49.95",
            "korrespondent": "Telekom",
            "text_snippet": "Beispieltext aus dem Dokument.",
        }
    ]
    block = build_context_block(docs)
    assert "=== DOKUMENTE ===" in block
    assert "=== ENDE DOKUMENTE ===" in block
    assert "test.pdf" in block
    assert "Rechnung" in block
    assert "2024" in block
    assert "49.95" in block
    assert "Telekom" in block
    assert "Beispieltext" in block
    # Index [D1] muss da sein
    assert "[D1]" in block


def test_build_context_block_multiple_docs():
    docs = [
        {"index": 1, "filename": "a.pdf", "text_snippet": "Alpha"},
        {"index": 2, "filename": "b.pdf", "text_snippet": "Beta"},
    ]
    block = build_context_block(docs)
    assert "[D1]" in block
    assert "[D2]" in block
    assert "Alpha" in block
    assert "Beta" in block


def test_build_context_block_empty():
    block = build_context_block([])
    assert "=== DOKUMENTE ===" in block
    assert "=== ENDE DOKUMENTE ===" in block


def test_build_user_prompt_contains_question():
    p = build_user_prompt(question="Was kostet Strom?")
    assert "Was kostet Strom?" in p
    # "FRAGE:" als Marker (grossgeschrieben, wie im Prompt-Builder verwendet)
    assert "FRAGE:" in p


def test_build_user_prompt_with_history():
    history = [
        {"role": "user", "content": "Vorfrage"},
        {"role": "assistant", "content": "Antwort"},
    ]
    p = build_user_prompt(question="Folgefrage", history=history)
    assert "Folgefrage" in p
    assert "Vorfrage" in p
    assert "Antwort" in p

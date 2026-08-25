"""Tests fuer ChatSession (Phase 19 / M1 RAG)."""
from datetime import datetime

from src.rag.chat_session import ChatSession, ChatTurn


def test_add_turn_appends_to_list():
    s = ChatSession()
    assert len(s) == 0
    s.add_turn(ChatTurn(role="user", content="Hallo", citations=[], timestamp=datetime.now()))
    assert len(s) == 1
    s.add_turn(ChatTurn(role="assistant", content="Hi", citations=[], timestamp=datetime.now()))
    assert len(s) == 2


def test_get_recent_returns_last_n():
    s = ChatSession()
    for i in range(5):
        s.add_turn(ChatTurn(role="user", content=f"F{i}", citations=[], timestamp=datetime.now()))
    recent = s.get_recent(3)
    assert len(recent) == 3
    # Letzte 3 -> Inhalte "F2", "F3", "F4"
    assert [t.content for t in recent] == ["F2", "F3", "F4"]


def test_get_recent_n_larger_than_session():
    s = ChatSession()
    s.add_turn(ChatTurn(role="user", content="only", citations=[], timestamp=datetime.now()))
    recent = s.get_recent(10)
    assert len(recent) == 1


def test_estimate_tokens_is_positive():
    s = ChatSession()
    s.add_turn(ChatTurn(
        role="user",
        content="Das ist ein längerer Text mit mehreren Wörtern zur Token-Schätzung.",
        citations=[],
        timestamp=datetime.now(),
    ))
    tokens = s.estimate_tokens()
    # Etwa word-count * 1.3; ~13 Wörter -> ~17 tokens
    assert tokens > 10
    assert tokens < 50


def test_estimate_tokens_empty():
    s = ChatSession()
    assert s.estimate_tokens() == 0


def test_clear_resets_session():
    s = ChatSession()
    s.add_turn(ChatTurn(role="user", content="x", citations=[], timestamp=datetime.now()))
    s.clear()
    assert len(s) == 0

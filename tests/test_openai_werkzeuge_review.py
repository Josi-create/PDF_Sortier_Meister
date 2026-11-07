"""OpenAI-kompatible Provider (Issue #166/#167): Review-Befunde - letzter Schritt mit Verlauf, Reasoning-Modelle."""
from __future__ import annotations

from src.ml.llm_provider import LLMConfig, WerkzeugAufruf
from src.ml.openai_provider import OpenAIProvider
from tests.test_openai_werkzeuge import (  # noqa: F401 - autouse-Fixture fake_openai_paket wird importiert
    _antwort,
    _openai,
    _patch_http,
    _tool_call,
    fake_openai_paket,
)
from tests.test_claude_werkzeuge import SUCHE

ROH = {"role": "assistant", "content": None,
       "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "suche", "arguments": "{}"}}]}


def _verlauf() -> list[dict]:
    return [
        {"role": "system", "content": "Du bist ein Assistent."},
        {"role": "user", "content": "Was zahle ich für Miete?"},
        {"role": "assistant", "content": "", "aufrufe": [WerkzeugAufruf("suche", {}, id="call_1")], "roh": ROH},
        {"role": "tool", "content": "2 Treffer", "aufruf_id": "call_1", "name": "suche"},
    ]


def test_letzter_schritt_mit_verlauf_sendet_tools_und_tool_choice_none(monkeypatch):
    p = _openai()
    aufrufe = _patch_http(monkeypatch, p, [
        (_antwort(tool_calls=[_tool_call()], finish_reason="tool_calls"), None),
        (_antwort("Fertig [2]."), None),
    ])
    p.chat_mit_werkzeugen(_verlauf()[:2], [SUCHE])
    antwort = p.chat_mit_werkzeugen(_verlauf(), [])
    body = aufrufe[1][1]
    assert [t["function"]["name"] for t in body["tools"]] == ["suche"]
    assert body["tools"][0]["function"]["parameters"] == SUCHE.parameter
    assert body["tool_choice"] == "none"
    assert antwort.text == "Fertig [2]." and antwort.fehler == ""

    # Frische Instanz ohne bekannte Definitionen: Platzhalter aus dem Verlauf
    q = _openai()
    aufrufe = _patch_http(monkeypatch, q, [(_antwort("Fertig."), None)])
    q.chat_mit_werkzeugen(_verlauf(), [])
    body = aufrufe[0][1]
    assert [t["function"]["name"] for t in body["tools"]] == ["suche"] and body["tool_choice"] == "none"

    # Ohne Werkzeugverlauf wie bisher kein tools-Feld
    aufrufe = _patch_http(monkeypatch, q, [(_antwort("Hallo."), None)])
    q.chat_mit_werkzeugen(_verlauf()[:2], [])
    assert "tools" not in aufrufe[0][1] and "tool_choice" not in aufrufe[0][1]


def test_reasoning_modelle_bekommen_max_completion_tokens_ohne_temperature(monkeypatch):
    p = OpenAIProvider(LLMConfig(api_key="sk-test", model="o3-mini"))
    aufrufe = _patch_http(monkeypatch, p, [(_antwort("Ok."), None), (_antwort("Ok."), None)])
    p.chat_mit_werkzeugen(_verlauf()[:2], [SUCHE], max_tokens=500)
    body = aufrufe[0][1]
    assert body["max_completion_tokens"] == 500 and "max_tokens" not in body and "temperature" not in body
    assert body["tools"]  # Werkzeuge bleiben erhalten
    # Auch der Weg ohne Werkzeuge (Phase 1)
    p.answer_with_context("System", [], "Frage", max_tokens=300)
    body = aufrufe[1][1]
    assert body["max_completion_tokens"] == 300 and "max_tokens" not in body and "temperature" not in body

    # Klassische Modelle unveraendert
    q = _openai()
    aufrufe = _patch_http(monkeypatch, q, [(_antwort("Ok."), None)])
    q.chat_mit_werkzeugen(_verlauf()[:2], [SUCHE], max_tokens=500)
    assert aufrufe[0][1]["max_tokens"] == 500 and "temperature" in aufrufe[0][1]

"""Claude-Provider (Issue #166/#167): letzter Schritt mit Werkzeugverlauf braucht Werkzeugdefinitionen (Review-Befund)."""
from __future__ import annotations

from src.ml.llm_provider import WerkzeugAufruf
from tests.test_claude_werkzeuge import SUCHE, _frage, _make, _patch_post

ROH = [
    {"type": "text", "text": "Ich suche."},
    {"type": "tool_use", "id": "toolu_1", "name": "suche", "input": {"abfrage": "Miete"}},
]


def _verlauf_mit_werkzeug() -> list[dict]:
    nachrichten = list(_frage())
    nachrichten.append({"role": "assistant", "content": "Ich suche.",
                        "aufrufe": [WerkzeugAufruf("suche", {"abfrage": "Miete"}, id="toolu_1")], "roh": ROH})
    nachrichten.append({"role": "tool", "content": "2 Treffer: [D2] a.pdf, [D3] b.pdf", "aufruf_id": "toolu_1",
                        "name": "suche"})
    return nachrichten


def test_letzter_schritt_sendet_bekannte_werkzeuge_mit_tool_choice_none(monkeypatch):
    p = _make()
    aufrufe = _patch_post(monkeypatch, p, [
        {"content": ROH, "stop_reason": "tool_use"},
        {"content": [{"type": "text", "text": "Fertig [2]."}], "stop_reason": "end_turn"},
    ])
    p.chat_mit_werkzeugen(_frage(), [SUCHE])
    antwort = p.chat_mit_werkzeugen(_verlauf_mit_werkzeug(), [])
    body = aufrufe[1]["body"]
    assert [t["name"] for t in body["tools"]] == ["suche"]
    assert body["tools"][0]["input_schema"] == SUCHE.parameter  # die echte Definition der Vorrunde
    assert body["tool_choice"] == {"type": "none"}
    typen = [b.get("type") for m in body["messages"] if isinstance(m.get("content"), list) for b in m["content"]]
    assert "tool_use" in typen and "tool_result" in typen
    assert antwort.text == "Fertig [2]." and antwort.aufrufe == [] and antwort.fehler == ""


def test_letzter_schritt_ohne_bekannte_definitionen_nimmt_platzhalter(monkeypatch):
    p = _make()  # frische Instanz: hat noch nie Werkzeuge gesendet
    aufrufe = _patch_post(monkeypatch, p, [{"content": [{"type": "text", "text": "Fertig."}]}])
    p.chat_mit_werkzeugen(_verlauf_mit_werkzeug(), [])
    body = aufrufe[0]["body"]
    assert [t["name"] for t in body["tools"]] == ["suche"]
    assert body["tools"][0]["input_schema"]["type"] == "object"
    assert body["tool_choice"] == {"type": "none"}


def test_ohne_werkzeugverlauf_bleibt_tools_weg(monkeypatch):
    p = _make()
    aufrufe = _patch_post(monkeypatch, p, [{"content": [{"type": "text", "text": "Hallo."}]}])
    p.chat_mit_werkzeugen(_frage(), [])
    assert "tools" not in aufrufe[0]["body"] and "tool_choice" not in aufrufe[0]["body"]

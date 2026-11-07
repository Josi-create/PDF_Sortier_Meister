"""Tests: Werkzeugaufrufe im Ollama-Provider (Issue #166/#167, Phase 2).

Keine echten Netzaufrufe: ``urllib.request.urlopen`` wird durch einen
Fake-Server ersetzt, der die gesendeten Requests sammelt und je API-Pfad
vorbereitete Antworten (Status, Body) oder Exceptions liefert.

GPL-3.0-or-later - Copyright (c) 2026
"""

import io
import json
import urllib.error

import pytest

from src.ml.llm_provider import LLMConfig, LLMProvider, Werkzeug, WerkzeugAufruf
from src.ml.ollama_provider import OllamaCloudProvider, OllamaProvider


SUCHE = Werkzeug(
    name="suche",
    beschreibung="Durchsucht den Dokumentindex.",
    parameter={
        "type": "object",
        "properties": {"abfrage": {"type": "string"}},
        "required": ["abfrage"],
    },
)

NACHRICHTEN = [
    {"role": "system", "content": "Du bist ein Assistent."},
    {"role": "user", "content": "Suche nach Zählerstände."},
]


def _antwort(content="", tool_calls=None, **extra):
    """Body einer /api/chat-Antwort mit einer Assistentennachricht."""
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    message.update(extra)
    return {"model": "m", "message": message, "done": True}


_STANDARD = object()


def _aufruf(name="suche", arguments=_STANDARD, **extra):
    """Ein tool_calls-Eintrag; ``arguments=None`` sendet wirklich ``null``."""
    if arguments is _STANDARD:
        arguments = {"abfrage": "x"}
    tc = {"function": {"name": name, "arguments": arguments}}
    tc.update(extra)
    return tc


class _FakeServer:
    """Ersatz fuer urllib.request.urlopen.

    ``antworten``: je API-Pfad ("chat", "show") eine Liste von Eintraegen;
    ein Eintrag ist ``(status, body_dict)`` oder eine Exception-Instanz.
    Jeder Request landet in ``requests`` als (url, headers, payload, timeout).
    """

    def __init__(self, antworten):
        self.antworten = {k: list(v) for k, v in antworten.items()}
        self.requests = []

    def __call__(self, req, timeout=None):
        payload = json.loads(req.data.decode("utf-8")) if req.data else None
        self.requests.append((req.full_url, dict(req.headers), payload, timeout))
        pfad = req.full_url.rsplit("/api/", 1)[-1]
        if not self.antworten.get(pfad):
            raise AssertionError(f"unerwarteter Request an /api/{pfad}")
        eintrag = self.antworten[pfad].pop(0)
        if isinstance(eintrag, Exception):
            raise eintrag
        status, body = eintrag
        if status != 200:
            raise urllib.error.HTTPError(
                req.full_url, status, "Bad Request", {},
                io.BytesIO(json.dumps(body).encode("utf-8")),
            )
        return io.BytesIO(json.dumps(body).encode("utf-8"))

    def payloads(self, pfad="chat"):
        return [p for url, _h, p, _t in self.requests if url.endswith("/api/" + pfad)]


@pytest.fixture
def server(monkeypatch):
    def _bauen(antworten):
        fake = _FakeServer(antworten)
        monkeypatch.setattr("urllib.request.urlopen", fake)
        return fake
    return _bauen


def _provider(model="gemma3:4b", api_key=""):
    return OllamaProvider(LLMConfig(api_key=api_key, model=model, base_url="http://localhost:11434"))


# --------------------------------------------------------------------- #
# Runde mit Werkzeugaufruf / Endantwort
# --------------------------------------------------------------------- #


def test_runde_mit_aufruf_argumente_als_objekt(server):
    srv = server({"chat": [(200, _antwort("", [_aufruf(arguments={"abfrage": "Zählerstände"})]))]})
    antwort = _provider().chat_mit_werkzeugen(NACHRICHTEN, [SUCHE], max_tokens=300)
    assert antwort.fehler == ""
    assert antwort.text == ""
    assert len(antwort.aufrufe) == 1
    aufruf = antwort.aufrufe[0]
    assert isinstance(aufruf, WerkzeugAufruf)
    assert aufruf.name == "suche"
    assert aufruf.argumente == {"abfrage": "Zählerstände"}
    assert aufruf.id == "aufruf_1"
    # roh = die Ollama-Nachricht mit role assistant und den tool_calls
    assert antwort.roh["role"] == "assistant"
    assert antwort.roh["tool_calls"][0]["function"]["name"] == "suche"
    assert len(srv.payloads()) == 1


def test_argumente_als_json_string_und_ids(server):
    server({"chat": [(200, _antwort("", [
        _aufruf(arguments='{"abfrage": "Strom"}', id="call_7"),
        _aufruf(arguments="kein json"),
        _aufruf(arguments='["liste"]'),
        _aufruf(arguments=None),
    ]))]})
    antwort = _provider().chat_mit_werkzeugen(NACHRICHTEN, [SUCHE])
    assert antwort.fehler == ""
    assert [a.argumente for a in antwort.aufrufe] == [{"abfrage": "Strom"}, {}, {}, {}]
    # Kennung vom Server, sonst fortlaufend je Position
    assert [a.id for a in antwort.aufrufe] == ["call_7", "aufruf_2", "aufruf_3", "aufruf_4"]


def test_endantwort_ohne_aufruf(server):
    server({"chat": [(200, _antwort("Ich habe zwei Dokumente gefunden."))]})
    antwort = _provider().chat_mit_werkzeugen(NACHRICHTEN, [SUCHE])
    assert antwort.fehler == ""
    assert antwort.text == "Ich habe zwei Dokumente gefunden."
    assert antwort.aufrufe == []
    assert antwort.roh == {"role": "assistant", "content": "Ich habe zwei Dokumente gefunden."}


def test_leere_endantwort_ist_fehler(server):
    # gpt-oss startet mit think="low" - kein zweiter Versuch, leer bleibt leer
    server({"chat": [(200, _antwort(""))]})
    antwort = _provider("gpt-oss:20b").chat_mit_werkzeugen(NACHRICHTEN, [SUCHE])
    assert antwort.aufrufe == []
    assert "leere Antwort" in antwort.fehler


# --------------------------------------------------------------------- #
# Payload-Struktur
# --------------------------------------------------------------------- #


def test_payload_struktur(server):
    srv = server({"chat": [(200, _antwort("Fertig."))]})
    roh = {
        "role": "assistant",
        "content": "",
        "thinking": "Ich suche mal.",
        "tool_calls": [{"function": {"name": "suche", "arguments": {"abfrage": "Zähler"}}}],
    }
    nachrichten = [
        {"role": "system", "content": "System"},
        {"role": "user", "content": "Frage"},
        {"role": "assistant", "content": "", "aufrufe": [WerkzeugAufruf("suche", {"abfrage": "Zähler"}, "aufruf_1")], "roh": roh},
        {"role": "tool", "content": "2 Treffer", "aufruf_id": "aufruf_1", "name": "suche"},
        # ohne roh: aus content + aufrufe nachgebaut
        {"role": "assistant", "content": "Noch eine Suche.", "aufrufe": [WerkzeugAufruf("suche", {"abfrage": "Gas"}, "aufruf_1")]},
        {"role": "tool", "content": "0 Treffer", "aufruf_id": "aufruf_1", "name": "suche"},
        # Endantwort ohne Aufrufe
        {"role": "assistant", "content": "Nichts gefunden."},
        {"role": "user", "content": "Danke"},
    ]
    p = OllamaProvider(LLMConfig(api_key="", model="llama3.1", temperature=0.2, base_url="http://localhost:11434/"))
    antwort = p.chat_mit_werkzeugen(nachrichten, [SUCHE], max_tokens=777)
    assert antwort.text == "Fertig."

    url, headers, payload, timeout = srv.requests[0]
    assert url == "http://localhost:11434/api/chat"
    assert headers["Content-type"] == "application/json"
    assert "Authorization" not in headers
    assert timeout == OllamaProvider.REQUEST_TIMEOUT
    assert payload["model"] == "llama3.1"
    assert payload["stream"] is False
    assert payload["options"] == {"temperature": 0.2, "num_predict": 777}
    assert payload["tools"] == [{
        "type": "function",
        "function": {"name": "suche", "description": "Durchsucht den Dokumentindex.", "parameters": SUCHE.parameter},
    }]
    assert payload["messages"] == [
        {"role": "system", "content": "System"},
        {"role": "user", "content": "Frage"},
        roh,  # unveraendert, inkl. thinking
        {"role": "tool", "content": "2 Treffer", "tool_name": "suche"},
        {"role": "assistant", "content": "Noch eine Suche.",
         "tool_calls": [{"function": {"name": "suche", "arguments": {"abfrage": "Gas"}}}]},
        {"role": "tool", "content": "0 Treffer", "tool_name": "suche"},
        {"role": "assistant", "content": "Nichts gefunden."},
        {"role": "user", "content": "Danke"},
    ]


def test_ohne_werkzeuge_kein_tools_feld(server):
    srv = server({"chat": [(200, _antwort("Antwort"))]})
    antwort = _provider().chat_mit_werkzeugen(NACHRICHTEN, [])
    assert antwort.text == "Antwort"
    assert "tools" not in srv.payloads()[0]


# --------------------------------------------------------------------- #
# Fehler: Ablehnung, Verbindung
# --------------------------------------------------------------------- #


def test_400_does_not_support_tools(server):
    srv = server({"chat": [(400, {"error": "registry.ollama.ai/library/gemma3:4b does not support tools"})]})
    p = _provider()
    antwort = p.chat_mit_werkzeugen(NACHRICHTEN, [SUCHE])
    assert "Werkzeuge" in antwort.fehler
    assert "does not support tools" in antwort.fehler
    assert antwort.aufrufe == []
    # danach: Nein, ohne /api/show zu fragen (der Fake kennt keine show-Antwort)
    assert p.unterstuetzt_werkzeuge() is False
    assert len(srv.requests) == 1
    # gemerkt: naechster Aufruf mit Werkzeugen geht gar nicht mehr zum Server
    nochmal = p.chat_mit_werkzeugen(NACHRICHTEN, [SUCHE])
    assert "Werkzeuge" in nochmal.fehler
    assert len(srv.requests) == 1


def test_400_tools_wird_nicht_als_think_rueckfall_gedeutet(server):
    # gemma sendet think=false; die Ablehnung betrifft aber die Werkzeuge ->
    # kein zweiter Versuch ohne think, think-Modus bleibt
    srv = server({"chat": [(400, {"error": "model does not support tools"})]})
    p = _provider()
    antwort = p.chat_mit_werkzeugen(NACHRICHTEN, [SUCHE])
    assert "Werkzeuge" in antwort.fehler
    assert len(srv.requests) == 1
    assert p._think_mode is False


def test_urlerror_liefert_fehler_ohne_exception(server):
    server({"chat": [urllib.error.URLError("Verbindung verweigert")]})
    p = _provider()
    antwort = p.chat_mit_werkzeugen(NACHRICHTEN, [SUCHE])
    assert antwort.fehler.startswith("Keine Verbindung zu Ollama")
    assert "Verbindung verweigert" in antwort.fehler
    assert antwort.aufrufe == [] and antwort.text == ""
    # Verbindungsfehler ist keine Ablehnung der Werkzeuge
    assert p._werkzeuge_abgelehnt is False


def test_anderer_http_fehler_wird_durchgereicht(server):
    server({"chat": [(500, {"error": "model requires more system memory"})]})
    p = _provider()
    antwort = p.chat_mit_werkzeugen(NACHRICHTEN, [SUCHE])
    assert antwort.fehler == "Ollama HTTP 500: model requires more system memory"
    assert p._werkzeuge_abgelehnt is False


def test_nicht_konfiguriert_liefert_fehler(server):
    srv = server({})
    p = OllamaCloudProvider(LLMConfig(api_key="", model="gpt-oss:20b"))
    antwort = p.chat_mit_werkzeugen(NACHRICHTEN, [SUCHE])
    assert antwort.fehler
    assert srv.requests == []


# --------------------------------------------------------------------- #
# Denkmodus wie in _do_chat
# --------------------------------------------------------------------- #


def test_think_false_wird_gesendet_und_bei_400_entfernt(server):
    srv = server({"chat": [
        (400, {"error": "\"gemma3:4b\" does not support thinking"}),
        (200, _antwort("", [_aufruf()])),
        (200, _antwort("Fertig.")),
    ]})
    p = _provider()
    antwort = p.chat_mit_werkzeugen(NACHRICHTEN, [SUCHE])
    assert antwort.fehler == "" and len(antwort.aufrufe) == 1
    p.chat_mit_werkzeugen(NACHRICHTEN, [SUCHE])
    sent = srv.payloads()
    assert sent[0]["think"] is False
    assert "think" not in sent[1] and "think" not in sent[2]  # gemerkt


def test_think_false_leer_wiederholt_mit_low(server):
    srv = server({"chat": [
        (200, _antwort("")),
        (200, _antwort("", [_aufruf()])),
    ]})
    p = _provider()
    antwort = p.chat_mit_werkzeugen(NACHRICHTEN, [SUCHE])
    assert antwort.fehler == "" and len(antwort.aufrufe) == 1
    sent = srv.payloads()
    assert sent[0]["think"] is False and sent[1]["think"] == "low"
    assert p._think_mode == "low"


def test_gpt_oss_denkt_im_chat_mit_medium(server):
    """Sortierung bleibt bei "low" (_think_mode), die Werkzeug-Schleife schickt "medium"."""
    srv = server({"chat": [(200, _antwort("Hallo"))]})
    p = _provider("gpt-oss-64k:latest")
    p.chat_mit_werkzeugen(NACHRICHTEN, [SUCHE])
    assert srv.payloads()[0]["think"] == "medium"
    assert p._think_mode == "low"
    # Hat der Server das Feld abgelehnt (gemerkt als None), wird es auch hier nicht gesendet
    p._think_mode = None
    assert p._werkzeug_think() is None
    # Andere Modelle behalten ihren Denkmodus
    q = _provider("gemma4:12b")
    q._think_mode = False
    assert q._werkzeug_think() is False


def test_ablehnung_nur_mit_gesendeten_werkzeugen_und_nur_bei_echter_ablehnung(server):
    # Ohne "tools" im Request sagt ein 400 nichts ueber die Werkzeugunterstuetzung
    srv = server({"chat": [(400, {"error": "json: cannot unmarshal string into Go struct field ToolCallFunction"})]})
    p = _provider("gemma4:12b")
    antwort = p.chat_mit_werkzeugen(NACHRICHTEN, [])
    assert antwort.fehler and p.unterstuetzt_werkzeuge() is True
    # Ein 400, in dem "tool" nur im Modellnamen steckt, ist keine Ablehnung
    assert not p._ist_werkzeug_ablehnung("Ollama HTTP 400: model llama3-groq-tool-use: invalid option")
    assert p._ist_werkzeug_ablehnung("Ollama HTTP 400: registry.ollama.ai/library/gemma3:270m does not support tools")


def test_tool_call_ohne_funktionsnamen_wird_uebersprungen(server):
    srv = server({"chat": [(200, {"message": {"role": "assistant", "content": "",
                                               "tool_calls": [{"function": {"arguments": {"a": 1}}},
                                                              {"function": {"name": "suche", "arguments": {}}}]}})]})
    antwort = _provider("gpt-oss-64k:latest").chat_mit_werkzeugen(NACHRICHTEN, [SUCHE])
    assert [a.name for a in antwort.aufrufe] == ["suche"] and antwort.fehler == ""


def test_denkmodelle_bekommen_mehr_token_budget(server):
    """num_predict zaehlt bei Ollama das Nachdenken mit: Denkstufe -> mindestens 4096, sonst max_tokens."""
    srv = server({"chat": [(200, _antwort("Hallo"))]})
    _provider("gpt-oss-64k:latest").chat_mit_werkzeugen(NACHRICHTEN, [SUCHE], max_tokens=1000)
    assert srv.payloads()[0]["options"]["num_predict"] == 4096
    srv = server({"chat": [(200, _antwort("Hallo"))]})
    q = _provider("gemma4:12b")
    q._think_mode = False
    q.chat_mit_werkzeugen(NACHRICHTEN, [SUCHE], max_tokens=1000)
    assert srv.payloads()[0]["options"]["num_predict"] == 1000
    assert _provider("gpt-oss-64k:latest")._werkzeug_num_predict(9000) == 9000


# --------------------------------------------------------------------- #
# unterstuetzt_werkzeuge() und /api/show
# --------------------------------------------------------------------- #


def test_kein_netzaufruf_im_konstruktor(server):
    srv = server({})
    _provider()
    assert srv.requests == []


def test_show_mit_tools_true_und_gecacht(server):
    srv = server({"show": [(200, {"capabilities": ["completion", "tools", "thinking"]})]})
    p = _provider("gpt-oss-64k:latest")
    assert p.unterstuetzt_werkzeuge() is True
    assert p.unterstuetzt_werkzeuge() is True
    url, headers, payload, timeout = srv.requests[0]
    assert url == "http://localhost:11434/api/show"
    assert payload == {"model": "gpt-oss-64k:latest"}
    assert timeout == 5
    assert len(srv.requests) == 1  # einmal je Instanz


def test_show_ohne_tools_false(server):
    srv = server({"show": [(200, {"capabilities": ["completion", "vision"]})]})
    p = _provider()
    assert p.unterstuetzt_werkzeuge() is False
    assert p.unterstuetzt_werkzeuge() is False
    assert len(srv.requests) == 1


@pytest.mark.parametrize("eintrag", [
    urllib.error.URLError("Verbindung verweigert"),
    (404, {"error": "model 'x' not found"}),
    (200, {"details": {"family": "llama"}}),       # aelterer Server ohne capabilities
    (200, {"capabilities": "tools"}),                # unerwarteter Typ
])
def test_show_fehler_oder_unbekannt_gilt_als_true(server, eintrag):
    server({"show": [eintrag]})
    assert _provider().unterstuetzt_werkzeuge() is True


def test_show_exception_bleibt_im_provider(server):
    server({"show": [OSError("kaputt")]})
    assert _provider().unterstuetzt_werkzeuge() is True


# --------------------------------------------------------------------- #
# Basisklasse und Cloud-Provider
# --------------------------------------------------------------------- #


def test_basisklasse_kann_keine_werkzeuge(server):
    srv = server({})
    p = _provider()
    assert LLMProvider.unterstuetzt_werkzeuge(p) is False
    antwort = LLMProvider.chat_mit_werkzeugen(p, NACHRICHTEN, [SUCHE])
    assert "Werkzeuge" in antwort.fehler
    assert antwort.aufrufe == [] and antwort.text == ""
    assert srv.requests == []


def test_cloud_provider_nutzt_ollama_com_und_bearer(server):
    srv = server({
        "show": [(200, {"capabilities": ["completion", "tools"]})],
        "chat": [(200, _antwort("", [_aufruf()]))],
    })
    p = OllamaCloudProvider(LLMConfig(api_key="sk-test", model="", base_url="http://localhost:11434"))
    assert p.unterstuetzt_werkzeuge() is True
    antwort = p.chat_mit_werkzeugen(NACHRICHTEN, [SUCHE])
    assert antwort.fehler == "" and len(antwort.aufrufe) == 1
    urls = [r[0] for r in srv.requests]
    assert urls == ["https://ollama.com/api/show", "https://ollama.com/api/chat"]
    for _url, headers, payload, _t in srv.requests:
        assert headers["Authorization"] == "Bearer sk-test"
        assert payload["model"] == "gpt-oss:120b"

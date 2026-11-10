"""Werkzeugaufrufe der OpenAI-kompatiblen Provider (Issue #166/#167, Phase 2).

OpenAI, OpenRouter, Poe und Strata teilen sich ``OpenAIWerkzeugMixin``
(src/ml/openai_werkzeuge.py). Jeder Test laeuft gegen alle vier Klassen;
``_http_post_json`` wird gepatcht, es gibt keine Netzaufrufe. Das
``openai``-Paket wird durch einen Dummy ersetzt, damit der Konstruktor
keinen echten Client anlegt.
"""
import json
import sys
import types

import pytest

from src.ml.llm_provider import LLMConfig, Werkzeug, WerkzeugAufruf
from src.ml import openai_werkzeuge as ow


# --------------------------------------------------------------------------- #
# Fabriken fuer die vier Provider                                             #
# --------------------------------------------------------------------------- #

def _openai(api_key="sk-test"):
    from src.ml.openai_provider import OpenAIProvider
    return OpenAIProvider(LLMConfig(api_key=api_key, model="gpt-4.1-nano"))


def _openrouter(api_key="sk-or-test"):
    from src.ml.openrouter_provider import OpenRouterProvider
    return OpenRouterProvider(LLMConfig(api_key=api_key, model="openai/gpt-4.1-nano"))


def _poe(api_key="poe-test"):
    from src.ml.poe_provider import PoeProvider
    return PoeProvider(LLMConfig(api_key=api_key, model="gpt-4o-mini"))


def _strata(api_key="sk-strata-test"):
    from src.ml.strata_provider import StrataProvider
    # Modell gesetzt: sonst fragt _get_model_id() den Server nach Modellen.
    return StrataProvider(LLMConfig(api_key=api_key, model="qwen3",
                                    base_url="http://localhost:8080"))


FABRIKEN = [
    pytest.param(_openai, id="openai"),
    pytest.param(_openrouter, id="openrouter"),
    pytest.param(_poe, id="poe"),
    pytest.param(_strata, id="strata"),
]


@pytest.fixture(autouse=True)
def fake_openai_paket(monkeypatch):
    """Dummy-``openai``: Konstruktor ohne Netz und ohne echten Client."""
    class _FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            self.chat = None
            self.models = None

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_FakeOpenAI))


@pytest.fixture(params=FABRIKEN)
def provider(request):
    return request.param()


# --------------------------------------------------------------------------- #
# Helfer                                                                      #
# --------------------------------------------------------------------------- #

def _antwort(content="", tool_calls=None, finish_reason="stop"):
    """chat/completions-Antwort wie vom Server."""
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"choices": [{"index": 0, "message": message, "finish_reason": finish_reason}]}


def _tool_call(id_="call_1", name="suche", arguments='{"frage": "Miete", "jahr": 2024}'):
    return {"id": id_, "type": "function",
            "function": {"name": name, "arguments": arguments}}


def _patch_http(monkeypatch, p, antworten):
    """Ersetzt _http_post_json; ``antworten`` = Liste von (data, error) je Aufruf.

    Liefert die Liste der aufgezeichneten Aufrufe als (url, body, headers).
    """
    aufrufe = []
    antworten = list(antworten)

    def fake(url, body, headers, timeout=None):
        aufrufe.append((url, body, headers))
        if not antworten:
            raise AssertionError("unerwarteter weiterer HTTP-Aufruf")
        return antworten.pop(0)

    monkeypatch.setattr(p, "_http_post_json", fake)
    return aufrufe


WERKZEUGE = [
    Werkzeug(
        name="suche",
        beschreibung="Durchsucht den Dokumentenindex.",
        parameter={"type": "object",
                   "properties": {"frage": {"type": "string"}},
                   "required": ["frage"]},
    ),
    Werkzeug(name="dokument_lesen", beschreibung="Liest ein Dokument.",
             parameter={"type": "object", "properties": {"pfad": {"type": "string"}}}),
]


def _ablehnung(p, status=400):
    return f"{p.API_NAME} HTTP {status}: {{\"error\": {{\"message\": \"This model does not support tools\"}}}}"


# --------------------------------------------------------------------------- #
# Runde mit Werkzeugaufrufen                                                  #
# --------------------------------------------------------------------------- #

def test_unterstuetzt_werkzeuge_anfangs(provider):
    assert provider.unterstuetzt_werkzeuge() is True


def test_runde_mit_tool_calls(provider, monkeypatch):
    message_roh = _antwort(content=None, tool_calls=[_tool_call()])
    _patch_http(monkeypatch, provider, [(message_roh, None)])

    a = provider.chat_mit_werkzeugen(
        [{"role": "system", "content": "Du hilfst."},
         {"role": "user", "content": "Was kostete die Miete 2024?"}],
        WERKZEUGE,
    )
    assert a.fehler == ""
    assert a.text == ""  # content null -> ""
    assert len(a.aufrufe) == 1
    aufruf = a.aufrufe[0]
    assert isinstance(aufruf, WerkzeugAufruf)
    assert aufruf.name == "suche"
    assert aufruf.argumente == {"frage": "Miete", "jahr": 2024}  # String -> Dict
    assert aufruf.id == "call_1"
    # roh = unveraendertes message-Dict
    assert a.roh is message_roh["choices"][0]["message"]


def test_mehrere_tool_calls_und_text(provider, monkeypatch):
    _patch_http(monkeypatch, provider, [(_antwort(
        content="Ich schaue nach.",
        tool_calls=[_tool_call("call_a", "suche", '{"frage": "a"}'),
                    _tool_call("call_b", "dokument_lesen", '{"pfad": "x.pdf"}')],
    ), None)])
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert a.text == "Ich schaue nach."
    assert [x.name for x in a.aufrufe] == ["suche", "dokument_lesen"]
    assert [x.id for x in a.aufrufe] == ["call_a", "call_b"]
    assert a.aufrufe[1].argumente == {"pfad": "x.pdf"}


def test_unparsbare_argumente_werden_leeres_dict(provider, monkeypatch):
    _patch_http(monkeypatch, provider, [(_antwort(
        content=None, tool_calls=[_tool_call(arguments='{"frage": "Miete"')]), None)])
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert a.fehler == ""
    assert a.aufrufe[0].argumente == {}


def test_argumente_als_objekt_oder_leer(provider, monkeypatch):
    """Manche Server schicken arguments als Objekt oder leeren String."""
    _patch_http(monkeypatch, provider, [(_antwort(content=None, tool_calls=[
        _tool_call("c1", "suche", {"frage": "direkt"}),
        _tool_call("c2", "suche", ""),
        _tool_call("c3", "suche", None),
        _tool_call("c4", "suche", "[1, 2]"),
    ]), None)])
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert [x.argumente for x in a.aufrufe] == [{"frage": "direkt"}, {}, {}, {}]


def test_tool_call_ohne_id_bekommt_fortlaufende(provider, monkeypatch):
    tc = {"type": "function", "function": {"name": "suche", "arguments": "{}"}}
    _patch_http(monkeypatch, provider, [(_antwort(content=None, tool_calls=[tc]), None)])
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert a.aufrufe[0].id == "aufruf_1"


# --------------------------------------------------------------------------- #
# Endrunde                                                                    #
# --------------------------------------------------------------------------- #

def test_endrunde_ohne_aufrufe(provider, monkeypatch):
    _patch_http(monkeypatch, provider, [(_antwort(content="Die Miete betrug 900 EUR [1]."), None)])
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert a.fehler == ""
    assert a.text == "Die Miete betrug 900 EUR [1]."
    assert a.aufrufe == []
    assert a.roh == {"role": "assistant", "content": "Die Miete betrug 900 EUR [1]."}


def test_content_null_ohne_aufrufe_ist_leerer_text(provider, monkeypatch):
    _patch_http(monkeypatch, provider, [(_antwort(content=None), None)])
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], [])
    assert a.fehler == ""
    assert a.text == ""
    assert a.aufrufe == []


def test_leere_antwort_wegen_token_limit_ist_fehler(provider, monkeypatch):
    _patch_http(monkeypatch, provider, [(_antwort(content="", finish_reason="length"), None)])
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert a.fehler and "Token" in a.fehler
    assert "Werkzeuge" not in a.fehler  # kein Rueckfall auf "ohne Werkzeuge"
    assert provider.unterstuetzt_werkzeuge() is True


def test_antwort_am_token_limit_ist_als_abgeschnitten_markiert(provider, monkeypatch):
    _patch_http(monkeypatch, provider, [
        (_antwort(content="Die Miete betrug", finish_reason="length"), None),
        (_antwort(content="Die Miete betrug 900 EUR."), None),
    ])
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert a.fehler == "" and a.text == "Die Miete betrug" and a.abgeschnitten is True
    b = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert b.abgeschnitten is False


# --------------------------------------------------------------------------- #
# Payload                                                                     #
# --------------------------------------------------------------------------- #

def test_payload_tools_und_verlauf(provider, monkeypatch):
    aufrufe = _patch_http(monkeypatch, provider, [(_antwort(content="fertig"), None)])
    roh = {"role": "assistant", "content": None, "tool_calls": [_tool_call()],
           "reasoning": "extra-Feld bleibt erhalten"}
    nachrichten = [
        {"role": "system", "content": "Du hilfst."},
        {"role": "user", "content": "Frage?"},
        {"role": "assistant", "content": "",
         "aufrufe": [WerkzeugAufruf(name="suche", argumente={"frage": "Miete"}, id="call_1")],
         "roh": roh},
        {"role": "tool", "content": "Treffer: 2 Dokumente", "aufruf_id": "call_1", "name": "suche"},
    ]
    a = provider.chat_mit_werkzeugen(nachrichten, WERKZEUGE, max_tokens=777)
    assert a.text == "fertig"

    assert len(aufrufe) == 1
    url, body, headers = aufrufe[0]
    assert url == provider.CHAT_COMPLETIONS_URL
    assert headers["Authorization"] == f"Bearer {provider.config.api_key}"
    assert headers["Content-Type"] == "application/json"
    assert body["model"] == provider._get_model_id()
    assert body["max_tokens"] == 777
    assert body["temperature"] == provider.config.temperature

    assert body["tool_choice"] == "auto"
    assert body["tools"] == [
        {"type": "function", "function": {
            "name": "suche", "description": "Durchsucht den Dokumentenindex.",
            "parameters": WERKZEUGE[0].parameter}},
        {"type": "function", "function": {
            "name": "dokument_lesen", "description": "Liest ein Dokument.",
            "parameters": WERKZEUGE[1].parameter}},
    ]

    msgs = body["messages"]
    assert msgs[0] == {"role": "system", "content": "Du hilfst."}
    assert msgs[1] == {"role": "user", "content": "Frage?"}
    assert msgs[2] is roh  # unveraendert, samt tool_calls und Extra-Feldern
    assert msgs[3] == {"role": "tool", "tool_call_id": "call_1",
                       "content": "Treffer: 2 Dokumente"}
    # Reasoning-Extras des SDK-Pfads gehoeren nicht in den urllib-Request
    assert "reasoning_effort" not in body and "extra_body" not in body
    json.dumps(body)  # serialisierbar


def test_assistent_ohne_roh_wird_nachgebaut(provider, monkeypatch):
    aufrufe = _patch_http(monkeypatch, provider, [(_antwort(content="ok"), None)])
    nachrichten = [
        {"role": "user", "content": "Frage?"},
        {"role": "assistant", "content": "",
         "aufrufe": [WerkzeugAufruf(name="suche", argumente={"frage": "Miete", "jahr": 2024},
                                    id="call_9")]},
        {"role": "tool", "content": "nichts", "aufruf_id": "call_9", "name": "suche"},
    ]
    provider.chat_mit_werkzeugen(nachrichten, WERKZEUGE)
    msg = aufrufe[0][1]["messages"][1]
    assert msg["role"] == "assistant"
    assert msg["content"] is None
    assert len(msg["tool_calls"]) == 1
    tc = msg["tool_calls"][0]
    assert tc["id"] == "call_9" and tc["type"] == "function"
    assert tc["function"]["name"] == "suche"
    assert isinstance(tc["function"]["arguments"], str)  # JSON-String!
    assert json.loads(tc["function"]["arguments"]) == {"frage": "Miete", "jahr": 2024}


def test_assistent_ohne_roh_und_ohne_aufrufe(provider, monkeypatch):
    aufrufe = _patch_http(monkeypatch, provider, [(_antwort(content="ok"), None)])
    provider.chat_mit_werkzeugen(
        [{"role": "user", "content": "a"},
         {"role": "assistant", "content": "Antwort 1"},
         {"role": "user", "content": "b"}],
        WERKZEUGE,
    )
    assert aufrufe[0][1]["messages"][1] == {"role": "assistant", "content": "Antwort 1"}


def test_keine_tools_bei_leerer_liste(provider, monkeypatch):
    aufrufe = _patch_http(monkeypatch, provider, [(_antwort(content="ok"), None)])
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], [])
    assert a.text == "ok"
    body = aufrufe[0][1]
    assert "tools" not in body
    assert "tool_choice" not in body


# --------------------------------------------------------------------------- #
# Ablehnung / Fehler                                                          #
# --------------------------------------------------------------------------- #

def test_400_tools_merkt_ablehnung(provider, monkeypatch):
    aufrufe = _patch_http(monkeypatch, provider, [(None, _ablehnung(provider, 400))])
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert a.fehler and "Werkzeuge" in a.fehler
    assert a.aufrufe == [] and a.text == ""
    assert provider.unterstuetzt_werkzeuge() is False
    # Danach kein weiterer Versuch mit Werkzeugen
    a2 = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert "Werkzeuge" in a2.fehler
    assert len(aufrufe) == 1


def test_404_tool_use_merkt_ablehnung(provider, monkeypatch):
    fehler = f"{provider.API_NAME} HTTP 404: No endpoints found that support tool use"
    _patch_http(monkeypatch, provider, [(None, fehler)])
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert "Werkzeuge" in a.fehler
    assert provider.unterstuetzt_werkzeuge() is False


def test_ablehnung_laesst_endrunde_ohne_tools_zu(provider, monkeypatch):
    aufrufe = _patch_http(monkeypatch, provider,
                          [(None, _ablehnung(provider)), (_antwort(content="ok"), None)])
    provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], [])
    assert a.text == "ok" and a.fehler == ""
    assert len(aufrufe) == 2


def test_400_ohne_tool_im_text_bleibt_unterstuetzt(provider, monkeypatch):
    fehler = f"{provider.API_NAME} HTTP 400: Invalid value for max_tokens"
    _patch_http(monkeypatch, provider, [(None, fehler)])
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert a.fehler == fehler
    assert "Werkzeuge" not in a.fehler
    assert provider.unterstuetzt_werkzeuge() is True


def test_500_mit_tool_im_text_bleibt_unterstuetzt(provider, monkeypatch):
    fehler = f"{provider.API_NAME} HTTP 500: tool backend crashed"
    _patch_http(monkeypatch, provider, [(None, fehler)])
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert a.fehler == fehler
    assert provider.unterstuetzt_werkzeuge() is True


def test_ablehnung_ohne_tools_im_request_zaehlt_nicht(provider, monkeypatch):
    """400 mit 'tool' bei leerer Werkzeugliste (z.B. Verlaufsfehler) ist keine Ablehnung."""
    _patch_http(monkeypatch, provider, [(None, _ablehnung(provider))])
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], [])
    assert a.fehler
    assert provider.unterstuetzt_werkzeuge() is True


def test_verbindungsfehler_als_text(provider, monkeypatch):
    fehler = f"Keine Verbindung zur {provider.API_NAME} API: [Errno 111]"
    _patch_http(monkeypatch, provider, [(None, fehler)])
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert a.fehler == fehler
    assert a.text == "" and a.aufrufe == []


def test_exception_im_http_wird_fehlertext(provider, monkeypatch):
    def kaputt(url, body, headers, timeout=None):
        raise RuntimeError("Kabel gezogen")

    monkeypatch.setattr(provider, "_http_post_json", kaputt)
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert "Kabel gezogen" in a.fehler


def test_leere_choices_ist_fehler(provider, monkeypatch):
    _patch_http(monkeypatch, provider, [({"choices": []}, None)])
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert a.fehler and provider.API_NAME in a.fehler


def test_fehlerobjekt_bei_http_200(provider, monkeypatch):
    """OpenRouter & Co. liefern manchmal 200 mit {"error": ...} statt choices."""
    data = {"error": {"message": "No endpoints found that support tool use", "code": 404}}
    _patch_http(monkeypatch, provider, [(data, None)])
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert "Werkzeuge" in a.fehler
    assert provider.unterstuetzt_werkzeuge() is False


def test_fehlerobjekt_bei_http_200_ohne_tool(provider, monkeypatch):
    data = {"error": {"message": "Rate limit exceeded", "code": 429}}
    _patch_http(monkeypatch, provider, [(data, None)])
    a = provider.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert "Rate limit exceeded" in a.fehler
    assert provider.unterstuetzt_werkzeuge() is True


@pytest.mark.parametrize("fabrik", FABRIKEN)
def test_ohne_api_key_fehler_ohne_netz(fabrik, monkeypatch):
    p = fabrik(api_key="")
    aufrufe = _patch_http(monkeypatch, p, [])
    a = p.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert a.fehler and "API-Key" in a.fehler
    assert aufrufe == []


# --------------------------------------------------------------------------- #
# Provider-Besonderheiten                                                     #
# --------------------------------------------------------------------------- #

def test_urls_der_provider():
    assert _openai().CHAT_COMPLETIONS_URL == "https://api.openai.com/v1/chat/completions"
    assert _openrouter().CHAT_COMPLETIONS_URL == "https://openrouter.ai/api/v1/chat/completions"
    assert _poe().CHAT_COMPLETIONS_URL == "https://api.poe.com/v1/chat/completions"
    assert _strata().CHAT_COMPLETIONS_URL == "http://localhost:8080/v1/chat/completions"


def test_poe_claude_modell_hebt_max_tokens_an(monkeypatch):
    from src.ml.poe_provider import PoeProvider
    p = PoeProvider(LLMConfig(api_key="poe-test", model="claude-3.5-haiku"))
    aufrufe = _patch_http(monkeypatch, p, [(_antwort(content="ok"), None)])
    p.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE, max_tokens=500)
    assert aufrufe[0][1]["max_tokens"] == 2048
    assert aufrufe[0][1]["model"] == "Claude-3.5-Haiku"

    gpt = _poe()
    aufrufe = _patch_http(monkeypatch, gpt, [(_antwort(content="ok"), None)])
    gpt.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE, max_tokens=500)
    assert aufrufe[0][1]["max_tokens"] == 500


def test_ablehnung_gilt_nur_fuer_die_instanz(monkeypatch):
    p1 = _openai()
    _patch_http(monkeypatch, p1, [(None, _ablehnung(p1))])
    p1.chat_mit_werkzeugen([{"role": "user", "content": "?"}], WERKZEUGE)
    assert p1.unterstuetzt_werkzeuge() is False
    assert _openai().unterstuetzt_werkzeuge() is True


def test_answer_with_context_weiter_intakt(provider, monkeypatch):
    """Der alte Chat-Weg bleibt unveraendert (gleicher _http_post_json-Helfer)."""
    aufrufe = _patch_http(monkeypatch, provider, [(_antwort(content="Antwort"), None)])
    text = provider.answer_with_context("sys", [], "Frage?")
    assert text == "Antwort"
    assert aufrufe[0][0] == provider.CHAT_COMPLETIONS_URL
    assert "tools" not in aufrufe[0][1]


# --------------------------------------------------------------------------- #
# Helferfunktionen direkt                                                     #
# --------------------------------------------------------------------------- #

def test_ist_werkzeug_ablehnung():
    assert ow.ist_werkzeug_ablehnung("OpenAI HTTP 400: model does not support tools")
    assert ow.ist_werkzeug_ablehnung("Poe HTTP 404: No endpoints found that support tool use")
    assert ow.ist_werkzeug_ablehnung("Strata HTTP 400: Tool_choice unsupported")
    assert not ow.ist_werkzeug_ablehnung("OpenAI HTTP 400: invalid max_tokens")
    assert not ow.ist_werkzeug_ablehnung("OpenAI HTTP 500: tools broken")
    assert not ow.ist_werkzeug_ablehnung("Keine Verbindung zur OpenAI API: tools")
    assert not ow.ist_werkzeug_ablehnung("")
    assert not ow.ist_werkzeug_ablehnung(None)


def test_nachrichten_fremdes_roh_wird_nachgebaut():
    """roh eines anderen Providers (Claude-Bloecke, Ollama ohne Ids) nicht durchreichen."""
    claude_roh = {"role": "assistant", "content": [{"type": "tool_use", "id": "t1"}]}
    ollama_roh = {"role": "assistant", "content": "",
                  "tool_calls": [{"function": {"name": "suche", "arguments": {"frage": "x"}}}]}
    aufrufe = [WerkzeugAufruf(name="suche", argumente={"frage": "x"}, id="t1")]
    msgs = ow.nachrichten_zu_openai([
        {"role": "assistant", "content": "", "aufrufe": aufrufe, "roh": claude_roh},
        {"role": "assistant", "content": "", "aufrufe": aufrufe, "roh": ollama_roh},
        {"role": "assistant", "content": "", "aufrufe": aufrufe, "roh": "kein dict"},
    ])
    for msg in msgs:
        assert msg["content"] is None
        assert msg["tool_calls"][0]["id"] == "t1"
        assert msg["tool_calls"][0]["function"]["arguments"] == '{"frage": "x"}'


def test_nachrichten_roh_ohne_rolle_bekommt_rolle():
    roh = {"content": "Hallo"}
    msgs = ow.nachrichten_zu_openai([{"role": "assistant", "content": "Hallo", "roh": roh}])
    assert msgs == [{"role": "assistant", "content": "Hallo"}]


def test_nachrichten_tool_ohne_aufruf_id_und_content_none():
    msgs = ow.nachrichten_zu_openai([
        {"role": "tool", "content": None},
        {"role": "user", "content": None},
    ])
    assert msgs == [{"role": "tool", "tool_call_id": "", "content": ""},
                    {"role": "user", "content": ""}]


def test_werkzeuge_zu_tools_ohne_parameter_und_ohne_name():
    tools = ow.werkzeuge_zu_tools([
        Werkzeug(name="x", beschreibung="", parameter=None),
        Werkzeug(name="", beschreibung="ohne Namen", parameter={}),
    ])
    assert tools == [{"type": "function", "function": {
        "name": "x", "description": "", "parameters": {"type": "object", "properties": {}}}}]
    assert ow.werkzeuge_zu_tools([]) == []


def test_antwort_parsen_inhaltsbloecke_und_unlesbar():
    data = {"choices": [{"message": {"role": "assistant",
                                     "content": [{"type": "text", "text": "A"}, "B"]}}]}
    assert ow.antwort_parsen(data, "X").text == "AB"
    assert ow.antwort_parsen("kaputt", "X").fehler
    assert ow.antwort_parsen({"choices": [{"message": "kein dict"}]}, "X").fehler

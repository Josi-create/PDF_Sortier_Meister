"""Tests fuer Werkzeugaufrufe im Claude-Provider (Issue #166/#167, Phase 2).

Alle HTTP-Aufrufe werden ueber ``_http_post_json`` bzw. ``urllib.request.urlopen``
abgefangen - es gibt keine echten Netzaufrufe.

GPL-3.0-or-later - Copyright (c) 2026
"""
import io
import json
import urllib.error
import urllib.request

from src.ml.claude_provider import ClaudeProvider
from src.ml.llm_provider import LLMConfig, Werkzeug, WerkzeugAufruf


def _make(api_key="sk-test", model="haiku-4.5"):
    return ClaudeProvider(LLMConfig(api_key=api_key, model=model))


def _patch_post(monkeypatch, provider, antworten):
    """Ersetzt ``_http_post_json``; liefert die Liste der aufgezeichneten Aufrufe.

    ``antworten`` ist eine Liste von Antwort-Dicts oder (data, error)-Tupeln,
    die der Reihe nach zurueckgegeben werden.
    """
    aufrufe = []
    warteschlange = list(antworten)

    def fake(url, body, headers, timeout=120):
        aufrufe.append({"url": url, "body": body, "headers": headers})
        antwort = warteschlange.pop(0)
        if isinstance(antwort, tuple):
            return antwort
        return antwort, None

    monkeypatch.setattr(provider, "_http_post_json", fake)
    return aufrufe


SUCHE = Werkzeug(
    name="suche",
    beschreibung="Durchsucht den Dokumentenindex.",
    parameter={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
)
LESEN = Werkzeug(
    name="dokument_lesen",
    beschreibung="Liest den Volltext eines Dokuments.",
    parameter={
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    },
)


def _antwort_mit_zwei_aufrufen():
    return {
        "id": "msg_1",
        "stop_reason": "tool_use",
        "content": [
            {"type": "text", "text": "Ich suche zuerst."},
            {"type": "tool_use", "id": "toolu_1", "name": "suche",
             "input": {"text": "Rechnung 2024"}},
            {"type": "tool_use", "id": "toolu_2", "name": "dokument_lesen",
             "input": {"id": 7}},
        ],
    }


def _frage():
    return [{"role": "user", "content": "Frage"}]


# --------------------------------------------------------------------------- #
# Anfrage-Drahtformat
# --------------------------------------------------------------------------- #

def test_unterstuetzt_werkzeuge_standardmaessig():
    assert _make().unterstuetzt_werkzeuge() is True


def test_anfrage_im_drahtformat(monkeypatch):
    p = _make(model="haiku-4.5")
    aufrufe = _patch_post(monkeypatch, p, [
        {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"},
    ])
    nachrichten = [
        {"role": "system", "content": "Du bist ein Archivar."},
        {"role": "user", "content": "Finde die Rechnung."},
    ]
    p.chat_mit_werkzeugen(nachrichten, [SUCHE, LESEN], max_tokens=321)

    assert len(aufrufe) == 1
    assert aufrufe[0]["url"] == ClaudeProvider.MESSAGES_URL
    assert aufrufe[0]["headers"]["x-api-key"] == "sk-test"
    assert aufrufe[0]["headers"]["anthropic-version"] == ClaudeProvider.ANTHROPIC_VERSION
    body = aufrufe[0]["body"]
    assert body["model"] == "claude-haiku-4-5-20251001"
    assert body["max_tokens"] == 321
    # system separat, nicht in messages
    assert body["system"] == "Du bist ein Archivar."
    assert body["messages"] == [{"role": "user", "content": "Finde die Rechnung."}]
    assert body["tools"] == [
        {"name": "suche", "description": "Durchsucht den Dokumentenindex.",
         "input_schema": SUCHE.parameter},
        {"name": "dokument_lesen", "description": "Liest den Volltext eines Dokuments.",
         "input_schema": LESEN.parameter},
    ]
    json.dumps(body)  # urllib schickt json.dumps - muss serialisierbar sein


def test_tools_feld_fehlt_bei_leerer_liste(monkeypatch):
    p = _make()
    aufrufe = _patch_post(monkeypatch, p, [{"content": [{"type": "text", "text": "Fertig."}]}])
    antwort = p.chat_mit_werkzeugen(_frage(), [])
    assert "tools" not in aufrufe[0]["body"]
    assert antwort.fehler == ""
    assert antwort.text == "Fertig."
    assert antwort.aufrufe == []


# --------------------------------------------------------------------------- #
# Antwort-Drahtformat
# --------------------------------------------------------------------------- #

def test_runde_mit_zwei_tool_use_bloecken(monkeypatch):
    p = _make()
    daten = _antwort_mit_zwei_aufrufen()
    _patch_post(monkeypatch, p, [daten])

    antwort = p.chat_mit_werkzeugen(_frage(), [SUCHE, LESEN])

    assert antwort.fehler == ""
    assert antwort.text == "Ich suche zuerst."
    assert all(isinstance(a, WerkzeugAufruf) for a in antwort.aufrufe)
    assert [a.id for a in antwort.aufrufe] == ["toolu_1", "toolu_2"]
    assert [a.name for a in antwort.aufrufe] == ["suche", "dokument_lesen"]
    assert antwort.aufrufe[0].argumente == {"text": "Rechnung 2024"}
    assert antwort.aufrufe[1].argumente == {"id": 7}
    # roh ist die content-Liste unveraendert (dasselbe Objekt)
    assert antwort.roh is daten["content"]


def test_endrunde_nur_text_aus_mehreren_bloecken(monkeypatch):
    p = _make()
    _patch_post(monkeypatch, p, [{
        "stop_reason": "end_turn",
        "content": [
            {"type": "text", "text": "Teil 1"},
            {"type": "text", "text": ""},
            {"type": "text", "text": "Teil 2"},
        ],
    }])
    antwort = p.chat_mit_werkzeugen(_frage(), [SUCHE])
    assert antwort.fehler == ""
    assert antwort.aufrufe == []
    assert antwort.text == "Teil 1\nTeil 2"


def test_tool_use_input_als_json_string_wird_geparst(monkeypatch):
    p = _make()
    _patch_post(monkeypatch, p, [{
        "content": [
            {"type": "tool_use", "id": "toolu_5", "name": "suche", "input": '{"text": "x"}'},
            {"type": "tool_use", "id": "toolu_6", "name": "suche", "input": "kein json"},
        ],
    }])
    antwort = p.chat_mit_werkzeugen(_frage(), [SUCHE])
    assert antwort.aufrufe[0].argumente == {"text": "x"}
    assert antwort.aufrufe[1].argumente == {}


# --------------------------------------------------------------------------- #
# Folgerunde: Assistentennachricht + Werkzeugergebnisse
# --------------------------------------------------------------------------- #

def test_folgerunde_buendelt_tool_results_in_einer_user_nachricht(monkeypatch):
    p = _make()
    erste = _antwort_mit_zwei_aufrufen()
    endrunde = {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "Die Rechnung ist Nr. 7."}],
    }
    aufrufe = _patch_post(monkeypatch, p, [erste, endrunde])
    nachrichten = [
        {"role": "system", "content": "Sys"},
        {"role": "user", "content": "Frage"},
    ]
    runde1 = p.chat_mit_werkzeugen(nachrichten, [SUCHE, LESEN])
    # So haengt der Controller Assistenten- und tool-Nachrichten an
    nachrichten.append({"role": "assistant", "content": runde1.text,
                        "aufrufe": runde1.aufrufe, "roh": runde1.roh})
    nachrichten.append({"role": "tool", "content": "Treffer: Rechnung_2024.pdf (7)",
                        "aufruf_id": "toolu_1", "name": "suche"})
    nachrichten.append({"role": "tool", "content": "Rechnung Nr. 7 über 100 €",
                        "aufruf_id": "toolu_2", "name": "dokument_lesen"})

    runde2 = p.chat_mit_werkzeugen(nachrichten, [SUCHE, LESEN])

    assert runde2.fehler == ""
    assert runde2.aufrufe == []
    assert runde2.text == "Die Rechnung ist Nr. 7."
    body = aufrufe[1]["body"]
    assert body["system"] == "Sys"
    msgs = body["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    # Assistentennachricht: die Bloecke unveraendert
    assert msgs[1]["content"] is erste["content"]
    # Werkzeugergebnisse: EINE user-Nachricht, zwei tool_result-Bloecke in Reihenfolge
    assert msgs[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_1",
         "content": "Treffer: Rechnung_2024.pdf (7)"},
        {"type": "tool_result", "tool_use_id": "toolu_2",
         "content": "Rechnung Nr. 7 über 100 €"},
    ]
    json.dumps(body)


def test_zwei_werkzeugrunden_ergeben_getrennte_buendel(monkeypatch):
    p = _make()
    aufrufe = _patch_post(monkeypatch, p, [{"content": [{"type": "text", "text": "ok"}]}])
    runde_a = [{"type": "tool_use", "id": "toolu_a", "name": "suche", "input": {"text": "a"}}]
    runde_b = [{"type": "tool_use", "id": "toolu_b", "name": "dokument_lesen", "input": {"id": 1}}]
    nachrichten = [
        {"role": "user", "content": "Frage"},
        {"role": "assistant", "content": "", "aufrufe": [], "roh": runde_a},
        {"role": "tool", "content": "Treffer 1", "aufruf_id": "toolu_a", "name": "suche"},
        {"role": "assistant", "content": "", "aufrufe": [], "roh": runde_b},
        {"role": "tool", "content": "Text 1", "aufruf_id": "toolu_b", "name": "dokument_lesen"},
    ]
    p.chat_mit_werkzeugen(nachrichten, [SUCHE, LESEN])
    msgs = aufrufe[0]["body"]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant", "user"]
    assert msgs[1]["content"] is runde_a
    assert msgs[2]["content"] == [{"type": "tool_result", "tool_use_id": "toolu_a", "content": "Treffer 1"}]
    assert msgs[3]["content"] is runde_b
    assert msgs[4]["content"] == [{"type": "tool_result", "tool_use_id": "toolu_b", "content": "Text 1"}]


def test_assistent_ohne_roh_wird_nachgebaut(monkeypatch):
    p = _make()
    aufrufe = _patch_post(monkeypatch, p, [{"content": [{"type": "text", "text": "ok"}]}])
    nachrichten = [
        {"role": "user", "content": "Frage"},
        {"role": "assistant", "content": "Ich suche.",
         "aufrufe": [WerkzeugAufruf(name="suche", argumente={"text": "x"}, id="toolu_9")]},
        {"role": "tool", "content": "nichts", "aufruf_id": "toolu_9", "name": "suche"},
    ]
    p.chat_mit_werkzeugen(nachrichten, [SUCHE])
    msgs = aufrufe[0]["body"]["messages"]
    assert msgs[1] == {"role": "assistant", "content": [
        {"type": "text", "text": "Ich suche."},
        {"type": "tool_use", "id": "toolu_9", "name": "suche", "input": {"text": "x"}},
    ]}
    assert msgs[2] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_9", "content": "nichts"},
    ]}


def test_leere_textbloecke_und_leere_assistentennachricht(monkeypatch):
    p = _make()
    aufrufe = _patch_post(monkeypatch, p, [{"content": [{"type": "text", "text": "ok"}]}])
    nachrichten = [
        {"role": "user", "content": "Frage 1"},
        # ganz leer -> wird weggelassen (eine leere Assistentennachricht lehnt die API ab)
        {"role": "assistant", "content": "", "aufrufe": [], "roh": None},
        {"role": "user", "content": "Frage 2"},
        # nur Leerraum -> kein Textblock, nur der tool_use-Block
        {"role": "assistant", "content": "   ",
         "aufrufe": [WerkzeugAufruf(name="suche", argumente={}, id="toolu_3")]},
        {"role": "tool", "content": "x", "aufruf_id": "toolu_3", "name": "suche"},
    ]
    p.chat_mit_werkzeugen(nachrichten, [SUCHE])
    msgs = aufrufe[0]["body"]["messages"]
    assert [m["role"] for m in msgs] == ["user", "user", "assistant", "user"]
    assert msgs[2]["content"] == [
        {"type": "tool_use", "id": "toolu_3", "name": "suche", "input": {}},
    ]


def test_tool_result_ohne_id_nimmt_id_des_aufrufs(monkeypatch):
    """Nachrichten aus anderen Providern tragen evtl. keine aufruf_id."""
    p = _make()
    aufrufe = _patch_post(monkeypatch, p, [{"content": [{"type": "text", "text": "ok"}]}])
    nachrichten = [
        {"role": "user", "content": "Frage"},
        {"role": "assistant", "content": "", "aufrufe": [
            WerkzeugAufruf(name="suche", argumente={"text": "a"}),
            WerkzeugAufruf(name="dokument_lesen", argumente={"id": 2}),
        ]},
        {"role": "tool", "content": "Treffer", "aufruf_id": "", "name": "suche"},
        {"role": "tool", "content": "", "aufruf_id": "", "name": "dokument_lesen"},
    ]
    p.chat_mit_werkzeugen(nachrichten, [SUCHE, LESEN])
    msgs = aufrufe[0]["body"]["messages"]
    tool_uses = [b["id"] for b in msgs[1]["content"] if b["type"] == "tool_use"]
    assert tool_uses == ["aufruf_1", "aufruf_2"]
    assert msgs[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "aufruf_1", "content": "Treffer"},
        {"type": "tool_result", "tool_use_id": "aufruf_2"},  # leeres Ergebnis ohne content
    ]


# --------------------------------------------------------------------------- #
# Fehler: nie Exceptions, Ablehnung merken
# --------------------------------------------------------------------------- #

def test_400_mit_tools_merkt_ablehnung(monkeypatch):
    p = _make()
    fehler = ('Claude HTTP 400: {"type":"error","error":{"type":"invalid_request_error",'
              '"message":"This model does not support tools."}}')
    _patch_post(monkeypatch, p, [(None, fehler)])
    antwort = p.chat_mit_werkzeugen(_frage(), [SUCHE])
    assert antwort.aufrufe == []
    assert antwort.text == ""
    assert "Werkzeuge" in antwort.fehler
    assert p.unterstuetzt_werkzeuge() is False


def test_andere_fehler_merken_keine_ablehnung(monkeypatch):
    p = _make()
    _patch_post(monkeypatch, p, [
        (None, 'Claude HTTP 400: {"error":{"message":"max_tokens: must be positive"}}'),
        (None, 'Claude HTTP 500: {"error":{"message":"tools backend down"}}'),
        (None, 'Claude HTTP 400: {"error":{"message":"tools unknown"}}'),
    ])
    a1 = p.chat_mit_werkzeugen(_frage(), [SUCHE])
    assert a1.fehler.startswith("Claude HTTP 400")
    assert p.unterstuetzt_werkzeuge() is True
    a2 = p.chat_mit_werkzeugen(_frage(), [SUCHE])
    assert a2.fehler.startswith("Claude HTTP 500")
    assert p.unterstuetzt_werkzeuge() is True
    # ohne gesendete Werkzeuge kann die Ablehnung nicht an den Werkzeugen liegen
    a3 = p.chat_mit_werkzeugen(_frage(), [])
    assert a3.fehler.startswith("Claude HTTP 400")
    assert p.unterstuetzt_werkzeuge() is True


def test_verbindungsfehler_ohne_exception(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.URLError("Name or service not known")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    p = _make()
    antwort = p.chat_mit_werkzeugen(_frage(), [SUCHE])
    assert antwort.fehler.startswith("Keine Verbindung zur Claude API")
    assert antwort.aufrufe == []
    assert p.unterstuetzt_werkzeuge() is True


def test_http_400_ueber_urlopen_merkt_ablehnung(monkeypatch):
    """Der ganze Weg ueber _http_post_json: HTTPError 400 mit 'tools' im Body."""
    def boom(*a, **k):
        raise urllib.error.HTTPError(
            ClaudeProvider.MESSAGES_URL, 400, "Bad Request", {},
            io.BytesIO(b'{"error":{"message":"tools are not supported"}}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    p = _make()
    antwort = p.chat_mit_werkzeugen(_frage(), [SUCHE])
    assert "Werkzeuge" in antwort.fehler
    assert "HTTP 400" in antwort.fehler
    assert p.unterstuetzt_werkzeuge() is False


def test_unlesbare_antwort_ohne_exception(monkeypatch):
    p = _make()
    _patch_post(monkeypatch, p, [
        {"type": "message", "content": "keine Liste"},
        {"content": [], "stop_reason": "max_tokens"},
        (None, None),
    ])
    a1 = p.chat_mit_werkzeugen(_frage(), [SUCHE])
    assert a1.fehler and a1.aufrufe == []
    a2 = p.chat_mit_werkzeugen(_frage(), [SUCHE])
    assert "max_tokens" in a2.fehler and a2.aufrufe == [] and a2.text == ""
    a3 = p.chat_mit_werkzeugen(_frage(), [SUCHE])
    assert a3.fehler and a3.aufrufe == []
    assert p.unterstuetzt_werkzeuge() is True


def test_exception_im_helfer_wird_zu_fehler(monkeypatch):
    p = _make()

    def boom(*a, **k):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(p, "_http_post_json", boom)
    antwort = p.chat_mit_werkzeugen(_frage(), [SUCHE])
    assert "kaputt" in antwort.fehler
    assert antwort.aufrufe == []


def test_ohne_api_key_fehler(monkeypatch):
    p = _make(api_key="")

    def boom(*a, **k):
        raise AssertionError("ohne Key darf kein HTTP-Aufruf passieren")

    monkeypatch.setattr(p, "_http_post_json", boom)
    antwort = p.chat_mit_werkzeugen(_frage(), [SUCHE])
    assert "API-Key" in antwort.fehler
    assert antwort.aufrufe == []
    # Der fehlende Key ist keine Ablehnung durch das Modell
    assert p.unterstuetzt_werkzeuge() is True

"""Tests zu Issue #380: Claude (direkt) mit neuer anthropic-Bibliothek und Denk-Bloecken.

- ``temperature`` geht nur an ``messages.create()``, wenn die Bibliothek den
  Parameter kennt (ab anthropic 1.0 nicht mehr) und das Modell ihn annimmt.
- Die HTTP-Wege senden ``temperature`` nur bei aelteren Modellen.
- Der Antworttext kommt aus allen ``text``-Bloecken; Denk-Bloecke davor stoeren nicht.

Keine echten Netzaufrufe: Client und HTTP-Aufruf sind ersetzt.

GPL-3.0-or-later - Copyright (c) 2026
"""
import sys
import types
from types import SimpleNamespace

import pytest

from src.ml.claude_provider import ClaudeProvider
from src.ml.llm_provider import LLMConfig


# --------------------------------------------------------------------- Helfer

def _block(typ, **felder):
    return SimpleNamespace(type=typ, **felder)


def _nachricht(*bloecke, stop_reason="end_turn"):
    return SimpleNamespace(
        content=list(bloecke),
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


class _MessagesNeu:
    """Wie anthropic >= 1.0: ``create()`` kennt kein ``temperature``."""

    def __init__(self, antwort):
        self.antwort = antwort
        self.aufrufe = []

    def create(self, *, model, max_tokens, messages, system=None, thinking=None):
        self.aufrufe.append({"model": model, "max_tokens": max_tokens, "messages": messages})
        return self.antwort


class _MessagesAlt:
    """Wie anthropic 0.x: ``create()`` nimmt ``temperature`` an."""

    def __init__(self, antwort):
        self.antwort = antwort
        self.aufrufe = []

    def create(self, *, model, max_tokens, messages, temperature=None, system=None):
        self.aufrufe.append({"model": model, "temperature": temperature})
        return self.antwort


def _provider(messages, model="haiku-4.5"):
    p = ClaudeProvider(LLMConfig(api_key="", model=model, temperature=0.3))
    p.config.api_key = "sk-test"
    p._client = SimpleNamespace(messages=messages)
    p._anthropic = SimpleNamespace(
        APIConnectionError=type("APIConnectionError", (Exception,), {}),
        RateLimitError=type("RateLimitError", (Exception,), {}),
        AuthenticationError=type("AuthenticationError", (Exception,), {}),
    )
    return p


_JSON_ORDNER = '{"folder": "Rechnungen", "reason": "Rechnung", "confidence": 0.9}'
_JSON_NAME = '{"filename": "2026-01-02_Rechnung_Mustermann", "reason": "x", "confidence": 0.8}'


# ------------------------------------------------- temperature und Bibliothek

def test_klassifizierung_ohne_temperature_parameter_der_bibliothek():
    messages = _MessagesNeu(_nachricht(_block("text", text=_JSON_ORDNER)))
    p = _provider(messages)

    antwort = p.classify_document("Rechnung von Max Mustermann", ["Rechnungen", "Briefe"])

    assert antwort.success, antwort.error_message
    assert antwort.folder_suggestion == "Rechnungen"
    assert len(messages.aufrufe) == 1


def test_umbenennen_ohne_temperature_parameter_der_bibliothek():
    messages = _MessagesNeu(_nachricht(_block("text", text=_JSON_NAME)))
    p = _provider(messages)

    antwort = p.suggest_filename("Rechnung", "scan001.pdf")

    assert antwort.success, antwort.error_message
    assert antwort.filename_suggestion
    assert len(messages.aufrufe) == 1


def test_alte_bibliothek_bekommt_temperature_bei_altem_modell():
    messages = _MessagesAlt(_nachricht(_block("text", text=_JSON_ORDNER)))
    p = _provider(messages, model="haiku-4.5")

    assert p.classify_document("Text", ["Rechnungen"]).success
    assert messages.aufrufe[0]["temperature"] == 0.3


def test_alte_bibliothek_ohne_temperature_bei_neuem_modell():
    messages = _MessagesAlt(_nachricht(_block("text", text=_JSON_ORDNER)))
    p = _provider(messages, model="claude-opus-5-5")

    assert p.classify_document("Text", ["Rechnungen"]).success
    assert messages.aufrufe[0]["temperature"] is None  # nicht mitgegeben


@pytest.mark.parametrize("model_id, erlaubt", [
    ("haiku-4.5", True),
    ("sonnet-4", True),
    ("claude-3-5-haiku-20241022", True),
    ("claude-sonnet-4-5", True),
    ("claude-opus-4-1-20250805", True),
    ("claude-opus-4-20250514", True),
    ("claude-sonnet-4-6", False),
    ("claude-opus-4-7", False),
    ("claude-opus-5-5", False),
    ("claude-haiku-5-5", False),
    ("claude-fable-5-2", False),
])
def test_temperatur_nur_bei_aelteren_modellen(model_id, erlaubt):
    p = _provider(_MessagesNeu(None), model=model_id)
    assert p._temperatur_erlaubt() is erlaubt


def test_http_wege_ohne_temperature_bei_neuem_modell(monkeypatch):
    p = _provider(_MessagesNeu(None), model="claude-opus-5-5")
    bodies = []

    def fake(url, body, headers, timeout=120):
        bodies.append(body)
        return {"content": [{"type": "thinking", "thinking": ""},
                            {"type": "text", "text": "Antwort"}]}, None

    monkeypatch.setattr(p, "_http_post_json", fake)
    monkeypatch.setattr("src.rag.prompts.build_context_block", lambda docs: "")
    monkeypatch.setattr("src.rag.prompts.build_user_prompt", lambda q, context_block="": q)

    assert p.describe_images([b"\xff\xd8"], "Was steht da?") == "Antwort"
    assert p.answer_with_context("System", [], "Frage?") == "Antwort"
    assert p.chat_mit_werkzeugen([{"role": "user", "content": "Hallo"}], []).text == "Antwort"
    assert len(bodies) == 3
    assert all("temperature" not in b for b in bodies)


def test_http_wege_mit_temperature_bei_altem_modell(monkeypatch):
    p = _provider(_MessagesNeu(None), model="haiku-4.5")
    bodies = []
    monkeypatch.setattr(
        p, "_http_post_json",
        lambda url, body, headers, timeout=120: (bodies.append(body)
                                                 or ({"content": [{"type": "text", "text": "ok"}]}, None)),
    )
    p.chat_mit_werkzeugen([{"role": "user", "content": "Hallo"}], [])
    assert bodies[0]["temperature"] == 0.3


# ------------------------------------------------------ Denk-Block und Text

def test_denkblock_vor_dem_text_wird_uebergangen():
    messages = _MessagesNeu(_nachricht(
        _block("thinking", thinking="", signature="abc"),
        _block("text", text=_JSON_ORDNER),
    ))
    p = _provider(messages, model="claude-opus-5-5")

    antwort = p.classify_document("Text", ["Rechnungen"])

    assert antwort.success, antwort.error_message
    assert antwort.folder_suggestion == "Rechnungen"


def test_mehrere_textbloecke_werden_zusammengesetzt():
    nachricht = _nachricht(
        _block("thinking", thinking=""),
        _block("text", text='{"folder": "Rech'),
        _block("text", text='nungen", "confidence": 0.7}'),
    )
    assert ClaudeProvider.antworttext(nachricht) == '{"folder": "Rechnungen", "confidence": 0.7}'


def test_antwort_ohne_textblock_ist_ein_klarer_fehler():
    messages = _MessagesNeu(_nachricht(
        _block("thinking", thinking=""), stop_reason="max_tokens",
    ))
    p = _provider(messages, model="claude-opus-5-5")

    antwort = p.suggest_filename("Text", "scan.pdf")

    assert not antwort.success
    assert "Token-Limit" in antwort.error_message
    assert "ThinkingBlock" not in antwort.error_message


def test_antworttext_ohne_inhalt():
    assert ClaudeProvider.antworttext(SimpleNamespace(content=[])) == ""
    assert ClaudeProvider.antworttext(SimpleNamespace(content=None)) == ""
    assert ClaudeProvider.antworttext(SimpleNamespace()) == ""


# -------------------------------------------------------- Verbindung testen

def test_verbindung_testen_mit_denkblock(monkeypatch, qtbot, fresh_config):
    from src.gui import settings_dialog as modul

    erzeugt = {}

    class _Client:
        def __init__(self, api_key):
            self.messages = _MessagesNeu(_nachricht(
                _block("thinking", thinking=""),
                _block("text", text="OK"),
            ))
            erzeugt["messages"] = self.messages

    fake_anthropic = types.ModuleType("anthropic")
    fake_anthropic.Anthropic = _Client
    fake_anthropic.AuthenticationError = type("AuthenticationError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

    meldungen = []
    # Ganze Klasse ersetzen: so kann nie ein echtes modales Fenster aufgehen
    monkeypatch.setattr(modul, "QMessageBox", SimpleNamespace(
        information=lambda *a, **k: meldungen.append(("info", a)),
        critical=lambda *a, **k: meldungen.append(("fehler", a)),
        warning=lambda *a, **k: meldungen.append(("fehler", a)),
    ))

    modul.SettingsDialog._test_claude(None, "sk-test", "claude-opus-5-5")

    assert [art for art, _ in meldungen] == ["info"], meldungen
    assert "OK" in meldungen[0][1][2]
    assert erzeugt["messages"].aufrufe[0]["max_tokens"] >= 100


def test_echte_installierte_bibliothek():
    """Mit der installierten anthropic-Version: kein unbekannter Parameter."""
    import inspect

    anthropic = pytest.importorskip("anthropic")
    p = ClaudeProvider(LLMConfig(api_key="sk-test", model="haiku-4.5"))
    if p._client is None:
        pytest.skip("anthropic-Client nicht erzeugbar")
    kennt = "temperature" in inspect.signature(p._client.messages.create).parameters
    assert ("temperature" in p._sdk_temperatur()) is kennt

"""LLM-Statusanzeige: rot, wenn der lokale Server (Ollama, Strata) nicht antwortet."""
import json
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from PyQt6.QtWidgets import QLabel

from src.ml.llm_provider import LLMConfig
from src.ml.strata_provider import StrataProvider


@pytest.fixture
def strata_server():
    """Mini-Server: /v1/models mit Key-Pruefung wie Strata."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.headers.get("Authorization") != "Bearer sk-strata-ok":
                self.send_response(401)
                self.end_headers()
                return
            body = json.dumps({"data": [{"id": "m1"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _strata(url, key):
    return StrataProvider(LLMConfig(api_key=key, model="m1", base_url=url))


def test_strata_ping_ok(strata_server):
    ok, detail = _strata(strata_server, "sk-strata-ok").ping()
    assert ok and "1 Modell" in detail


def test_strata_ping_falscher_key(strata_server):
    ok, detail = _strata(strata_server, "sk-strata-falsch").ping()
    assert not ok and "API-Key" in detail


def test_strata_ping_server_aus():
    # Port 9 (discard) ist lokal praktisch nie belegt -> Verbindung abgelehnt
    ok, detail = _strata("http://127.0.0.1:9", "k").ping()
    assert not ok and "Verbindung" in detail


def _classifier(provider):
    from src.ml import hybrid_classifier as hc_mod
    hc = hc_mod.HybridClassifier.__new__(hc_mod.HybridClassifier)
    hc.llm_provider = provider
    hc.llm_enabled = provider is not None
    return hc


def test_pruefbar_nur_lokale_server():
    from src.ml.ollama_provider import OllamaCloudProvider, OllamaProvider
    from src.ml.openrouter_provider import OpenRouterProvider

    cfg = LLMConfig(api_key="k", model="m")
    assert _classifier(OllamaProvider(cfg)).llm_connection_checkable()
    assert _classifier(StrataProvider(cfg)).llm_connection_checkable()
    assert not _classifier(OllamaCloudProvider(cfg)).llm_connection_checkable()
    assert not _classifier(OpenRouterProvider(cfg)).llm_connection_checkable()
    assert not _classifier(None).llm_connection_checkable()
    assert _classifier(OpenRouterProvider(cfg)).check_llm_connection() is None


def test_ollama_nicht_erreichbar_liefert_false():
    from src.ml.ollama_provider import OllamaProvider
    hc = _classifier(OllamaProvider(LLMConfig(api_key="", model="m",
                                              base_url="http://127.0.0.1:9")))
    ok, detail = hc.check_llm_connection()
    assert not ok


@pytest.mark.parametrize("model, installed, ok", [
    ("gpt-oss-64k:latest", [], False),            # Server laeuft, Modell fehlt
    ("gpt-oss-64k:latest", ["gpt-oss-64k:latest"], True),
    ("gpt-oss-64k", ["gpt-oss-64k:latest"], True),
    ("llama3.1:latest", ["llama3.1"], True),
    ("Llama3.1", ["llama3.1:8b"], False),
])
def test_ollama_modell_wird_mitgeprueft(monkeypatch, model, installed, ok):
    from src.ml.ollama_provider import OllamaProvider
    p = OllamaProvider(LLMConfig(api_key="", model=model))
    monkeypatch.setattr(p, "ping", lambda: (True, "0.40.0"))
    monkeypatch.setattr(p, "list_models", lambda: list(installed))
    result = _classifier(p).check_llm_connection()
    assert result[0] is ok
    if not ok:
        assert "nicht installiert" in result[1]


# --- Farbe der Statusanzeige --------------------------------------------------

def _fake_window(qtbot, checkable, connection):
    from src.gui.main_window import MainWindow
    label = QLabel()
    qtbot.addWidget(label)
    hc = types.SimpleNamespace(
        is_llm_available=lambda: True,
        get_llm_provider_name=lambda: "Ollama",
        get_llm_model_name=lambda short=False: "gpt-oss",
        llm_connection_checkable=lambda: checkable,
    )
    win = types.SimpleNamespace(hybrid_classifier=hc, llm_status_label=label,
                                _llm_connection=connection)
    MainWindow._update_llm_status(win)
    return label


@pytest.mark.parametrize("checkable, connection, farbe, tooltip", [
    (True, (False, "Verbindung fehlgeschlagen"), "#c0392b", "nicht einsatzbereit"),
    (True, (True, "0.9.0"), "green", "aktiv"),
    (True, None, "gray", "wird geprüft"),
    (False, None, "green", "aktiv"),  # Cloud: keine Pruefung, wie bisher gruen
])
def test_statusfarbe(qtbot, checkable, connection, farbe, tooltip):
    label = _fake_window(qtbot, checkable, connection)
    assert label.text() == "LLM: Ollama/gpt-oss"
    assert label.styleSheet() == f"color: {farbe};"
    assert tooltip in label.toolTip()

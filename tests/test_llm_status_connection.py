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

LLAMA_FEHLT = ("Ollama HTTP 500: error starting llama-server: "
               "llama-server binary not found")


def _fake_window(qtbot, checkable, connection, request_error=None):
    """Minimales Fenster-Objekt mit den echten MainWindow-Methoden."""
    from src.gui.main_window import MainWindow
    label = QLabel()
    qtbot.addWidget(label)
    hc = types.SimpleNamespace(
        is_llm_available=lambda: True,
        get_llm_provider_name=lambda: "Ollama",
        get_llm_model_name=lambda short=False: "gpt-oss",
        llm_connection_checkable=lambda: checkable,
    )
    win = types.SimpleNamespace(
        hybrid_classifier=hc, llm_status_label=label,
        _llm_connection=connection, _llm_request_error=request_error,
        _last_llm_error=None, _llm_success_since_error=False,
        LLM_STATUS_RED=MainWindow.LLM_STATUS_RED,
        config=types.SimpleNamespace(get=lambda key, default=None: default),
        pings=[], probes=[],
    )
    win.pdf_cache = types.SimpleNamespace(retry_one_failed_llm=lambda: win.probes.append(1))
    win._check_llm_connection = lambda: win.pings.append(1)
    win._update_cache_status = lambda: None
    for name in ("_llm_health", "_update_llm_status", "_set_llm_reachable",
                 "_on_llm_suggestions_failed", "_on_llm_check_tick"):
        setattr(win, name, types.MethodType(getattr(MainWindow, name), win))
    win._update_llm_status()
    return win


@pytest.mark.parametrize("checkable, connection, farbe, tooltip", [
    (True, (True, "0.9.0"), "green", "bereit"),
    (True, None, "gray", "wird geprüft"),
    (False, None, "green", "bereit"),  # Cloud: keine Pruefung, ohne Fehler gruen
])
def test_statusfarbe_ohne_fehler(qtbot, checkable, connection, farbe, tooltip):
    label = _fake_window(qtbot, checkable, connection).llm_status_label
    assert label.text() == "LLM: Ollama/gpt-oss"
    assert label.styleSheet() == f"color: {farbe};"
    assert tooltip in label.toolTip()
    assert "Doppelklick öffnet die Einstellungen" in label.toolTip()


def test_server_aus_rot_mit_abhilfe(qtbot):
    label = _fake_window(qtbot, True, (False, "Verbindung fehlgeschlagen: refused")).llm_status_label
    assert label.text() == "⚠ LLM: Ollama/gpt-oss"
    assert label.styleSheet() == "color: #c0392b;"
    tip = label.toolTip()
    assert "Die KI funktioniert gerade nicht" in tip
    assert "Problem: Ollama läuft nicht" in tip and "Abhilfe: Ollama starten" in tip
    assert "Doppelklick öffnet die Einstellungen" in tip


def test_echter_fehler_schlaegt_minutenpruefung(qtbot):
    """Ollama antwortet und listet das Modell, kann es aber nicht laden:
    die Anzeige bleibt rot, auch wenn die Minutenpruefung OK meldet."""
    from pathlib import Path
    win = _fake_window(qtbot, True, (True, "0.40.0"))
    win._on_llm_suggestions_failed(Path("scan.pdf"), LLAMA_FEHLT)
    label = win.llm_status_label
    assert label.styleSheet() == "color: #c0392b;"
    assert "unvollständig installiert" in label.toolTip()
    assert win.pings == [1]  # Erreichbarkeit wird zusaetzlich neu geprueft

    win._llm_connection = (True, "0.40.0")  # Minutenpruefung: alles OK
    win._update_llm_status()
    assert label.styleSheet() == "color: #c0392b;"

    win._set_llm_reachable(True)  # erste gelungene KI-Anfrage
    assert label.styleSheet() == "color: green;"
    assert win._llm_request_error is None


def test_cloud_anbieter_wird_bei_fehler_rot(qtbot):
    from pathlib import Path
    win = _fake_window(qtbot, False, None)
    win._on_llm_suggestions_failed(Path("scan.pdf"), "Error code: 401 - invalid api key")
    assert win.llm_status_label.styleSheet() == "color: #c0392b;"
    assert "API-Key prüfen" in win.llm_status_label.toolTip()
    win._set_llm_reachable(True)
    assert win.llm_status_label.styleSheet() == "color: green;"


def test_dokumentfehler_macht_nicht_rot(qtbot):
    from pathlib import Path
    win = _fake_window(qtbot, True, (True, "0.40.0"))
    win._on_llm_suggestions_failed(Path("scan.pdf"), "KI hat keinen Vorschlag geliefert.")
    assert win.llm_status_label.styleSheet() == "color: green;"
    assert win._last_llm_error == ("scan.pdf", "KI hat keinen Vorschlag geliefert.")


def test_minutentakt_probt_nur_nach_fehler(qtbot):
    win = _fake_window(qtbot, True, (True, "0.40.0"))
    win._on_llm_check_tick()
    assert win.probes == [] and win.pings == [1]
    win._llm_request_error = LLAMA_FEHLT
    win._on_llm_check_tick()
    assert win.probes == [1] and win.pings == [1, 1]

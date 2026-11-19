"""Ollama: Nach einem Absturz des Modells wird die Anfrage einmal wiederholt (Live-Test 19.11.2026)."""
import subprocess

import pytest

from src.ml import ollama_launcher
from src.ml.llm_hinweis import ist_modellabsturz
from src.ml.llm_provider import LLMConfig
from src.ml.ollama_provider import OllamaProvider

ABSTURZ = ("Ollama HTTP 500: error reading llama-server response: read tcp 127.0.0.1:50556->127.0.0.1:50508: "
           "wsarecv: Eine vorhandene Verbindung wurde vom Remotehost geschlossen.")
URL = "http://localhost:11434/api/chat"


def _provider(monkeypatch, antworten):
    p = OllamaProvider(LLMConfig(api_key="", model="llama3.1"))
    monkeypatch.setattr(p, "ABSTURZ_PAUSE", 0)
    aufrufe = []

    def einmal(url, payload):
        aufrufe.append(payload)
        return antworten[len(aufrufe) - 1]

    monkeypatch.setattr(p, "_post_chat_einmal", einmal)
    return p, aufrufe


@pytest.mark.parametrize("fehler, absturz", [
    (ABSTURZ, True),
    ("Ollama HTTP 500: llama runner process has terminated: exit status 0xc0000409", True),
    ("Ollama HTTP 500: error starting llama-server: llama-server binary not found", False),
    ("Ollama HTTP 500: model requires more system memory", False),
    ("Keine Verbindung zu Ollama (http://localhost:11434). Details: [WinError 10061]", False),
    ("", False),
])
def test_ist_modellabsturz(fehler, absturz):
    assert ist_modellabsturz(fehler) is absturz


def test_nach_absturz_gelingt_der_zweite_versuch(monkeypatch):
    gut = {"message": {"content": "{}"}}
    p, aufrufe = _provider(monkeypatch, [(None, ABSTURZ), (gut, None)])
    assert p._post_chat(URL, {"model": "llama3.1"}) == (gut, None)
    assert len(aufrufe) == 2


def test_nur_ein_zweiter_versuch(monkeypatch):
    p, aufrufe = _provider(monkeypatch, [(None, ABSTURZ), (None, ABSTURZ), (None, ABSTURZ)])
    assert p._post_chat(URL, {"model": "llama3.1"}) == (None, ABSTURZ)
    assert len(aufrufe) == 2


def test_andere_fehler_werden_nicht_wiederholt(monkeypatch):
    fehler = "Ollama HTTP 500: model requires more system memory"
    p, aufrufe = _provider(monkeypatch, [(None, fehler)])
    assert p._post_chat(URL, {"model": "llama3.1"}) == (None, fehler)
    assert len(aufrufe) == 1


def test_selbst_gestarteter_server_schreibt_ein_protokoll(monkeypatch, tmp_path):
    """Die Ausgabe von `ollama serve` landet in ollama_server.log statt im Nichts."""
    import src.utils.logging_config as lc
    monkeypatch.setattr(lc, "get_log_directory", lambda: tmp_path)
    gesehen = {}

    def popen(befehl, **kw):
        gesehen["befehl"] = befehl
        gesehen["stdout"] = kw["stdout"]
        gesehen["stderr"] = kw["stderr"]
        kw["stdout"].write(b"zeile vom server")

    monkeypatch.setattr(subprocess, "Popen", popen)
    assert ollama_launcher._start_server_process("ollama.exe") is True
    assert gesehen["befehl"] == ["ollama.exe", "serve"]
    assert gesehen["stdout"] is gesehen["stderr"] and gesehen["stdout"].closed
    assert (tmp_path / "ollama_server.log").read_bytes() == b"zeile vom server"


def test_ohne_protokoll_startet_der_server_trotzdem(monkeypatch):
    import src.utils.logging_config as lc

    def kaputt():
        raise OSError("kein Ordner")

    monkeypatch.setattr(lc, "get_log_directory", kaputt)
    gesehen = {}
    monkeypatch.setattr(subprocess, "Popen", lambda befehl, **kw: gesehen.update(kw))
    assert ollama_launcher._start_server_process("ollama.exe") is True
    assert gesehen["stdout"] is subprocess.DEVNULL

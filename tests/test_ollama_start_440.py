"""Ollama starten: erst die Ollama-App, laenger warten (Issues #440 und #432).

Kein Test startet ein echtes Ollama: Prozessstart, Ping und Uhr sind ersetzt.
"""
from __future__ import annotations

import pytest

from src.ml import ollama_launcher

# tests/conftest.py ersetzt find_ollama_app in jedem Test; hier die echte Funktion
_FIND_OLLAMA_APP = ollama_launcher.find_ollama_app


class _Uhr:
    """Ersetzt ``time`` im Launcher: sleep laesst die Zeit nur vorruecken."""

    def __init__(self):
        self.jetzt = 0.0

    def monotonic(self):
        return self.jetzt

    def sleep(self, sekunden):
        self.jetzt += sekunden


@pytest.fixture
def start(monkeypatch):
    """Ersetzt alles, was einen Prozess startet; zeichnet die Starts auf."""
    uhr = _Uhr()
    monkeypatch.setattr(ollama_launcher, "time", uhr)
    lage = {"bereit_ab": 2.0, "app": "C:/Programme/Ollama/ollama app.exe",
            "exe": "C:/Programme/Ollama/ollama.exe", "app_ok": True, "starts": []}

    def ping(url, timeout=1.0):
        return bool(lage["starts"]) and uhr.jetzt >= lage["bereit_ab"]

    def app_starten(pfad):
        lage["starts"].append(("app", pfad))
        return lage["app_ok"]

    def serve_starten(pfad):
        lage["starts"].append(("serve", pfad))
        return True

    monkeypatch.setattr(ollama_launcher, "quick_ping", ping)
    monkeypatch.setattr(ollama_launcher, "find_ollama_app", lambda: lage["app"])
    monkeypatch.setattr(ollama_launcher, "find_ollama_executable", lambda: lage["exe"])
    monkeypatch.setattr(ollama_launcher, "_start_app_process", app_starten)
    monkeypatch.setattr(ollama_launcher, "_start_server_process", serve_starten)
    return lage


def test_startet_zuerst_die_ollama_app(start):
    ok, _ = ollama_launcher.ensure_running("http://localhost:11434")
    assert ok
    assert start["starts"] == [("app", start["app"])]


def test_ohne_app_wie_bisher_ollama_serve(start):
    start["app"] = None
    ok, _ = ollama_launcher.ensure_running("http://localhost:11434")
    assert ok
    assert start["starts"] == [("serve", start["exe"])]


def test_app_startet_nicht_dann_ollama_serve(start):
    start["app_ok"] = False
    ok, _ = ollama_launcher.ensure_running("http://localhost:11434")
    assert ok
    assert [art for art, _ in start["starts"]] == ["app", "serve"]


def test_laeuft_schon_startet_nichts(start, monkeypatch):
    monkeypatch.setattr(ollama_launcher, "quick_ping", lambda url, timeout=1.0: True)
    ok, _ = ollama_launcher.ensure_running("http://localhost:11434")
    assert ok
    assert start["starts"] == []


def test_find_ollama_app_unter_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(ollama_launcher.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert _FIND_OLLAMA_APP() is None
    app = tmp_path / "Programs" / "Ollama" / "ollama app.exe"
    app.parent.mkdir(parents=True)
    app.write_bytes(b"")
    assert _FIND_OLLAMA_APP() == str(app)

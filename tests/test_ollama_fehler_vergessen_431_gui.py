"""Antwortet Ollama wieder, verschwindet der gemerkte Fehler „läuft nicht“ sofort (Issue #431).

Fenster-Attrappe mit den echten MainWindow-Methoden; kein echtes Ollama.
"""
from __future__ import annotations

import types
from pathlib import Path

from src.ml import ollama_launcher
from tests.test_llm_status_connection import LLAMA_FEHLT, _fake_window

LAEUFT_NICHT = "Ollama nicht erreichbar und Auto-Start fehlgeschlagen.\nOllama-Server wurde gestartet, ..."


def _fenster(qtbot):
    from src.gui.main_window import MainWindow
    win = _fake_window(qtbot, True, (True, "0.40.0"))
    win.hybrid_classifier.llm_provider = types.SimpleNamespace(_get_base_url=lambda: "http://localhost:11434")
    for name in ("_on_llm_connection_checked", "_veralteten_verbindungsfehler_vergessen",
                 "_ollama_lage_fuer_dialog"):
        setattr(win, name, types.MethodType(getattr(MainWindow, name), win))
    win._llm_check_generation = 1
    return win


def test_verbindungspruefung_ok_vergisst_fehler_laeuft_nicht(qtbot):
    win = _fenster(qtbot)
    win._on_llm_suggestions_failed(Path("scan.pdf"), LAEUFT_NICHT)
    assert win.llm_status_label.text().startswith("⚠")
    assert win._last_llm_error is not None

    win._on_llm_connection_checked(1, (True, "0.40.0"))

    assert win._llm_request_error is None and win._last_llm_error is None
    assert not win.llm_status_label.text().startswith("⚠")
    assert win._llm_health()[0] == "bereit"
    assert win.probes == [1]  # eine gescheiterte PDF wird neu angefragt


def test_gescheiterter_auto_start_heisst_laeuft_nicht():
    """Die Meldung des Launchers nennt den „Ollama-Server“ - das ist kein kaputtes llama-server."""
    from src.ml.llm_hinweis import ki_hinweis
    hinweis = ki_hinweis("Ollama", LAEUFT_NICHT, "gpt-oss")
    assert hinweis.art == "laeuft_nicht"
    assert ki_hinweis("Ollama", LLAMA_FEHLT, "gpt-oss").problem.endswith("unvollständig installiert und kann keine Modelle laden.")


def test_anderer_fehler_bleibt_gemerkt(qtbot):
    win = _fenster(qtbot)
    win._on_llm_suggestions_failed(Path("scan.pdf"), LLAMA_FEHLT)
    win._on_llm_connection_checked(1, (True, "0.40.0"))
    assert win._llm_request_error == LLAMA_FEHLT
    assert win.llm_status_label.text().startswith("⚠")
    assert win.probes == []


def test_verbindungspruefung_fehlgeschlagen_vergisst_nichts(qtbot):
    win = _fenster(qtbot)
    win._on_llm_suggestions_failed(Path("scan.pdf"), LAEUFT_NICHT)
    win._on_llm_connection_checked(1, (False, "Verbindung fehlgeschlagen"))
    assert win._llm_request_error == LAEUFT_NICHT


def test_fenster_hintergrund_analyse_widerspricht_sich_nicht(qtbot, monkeypatch):
    """Die Ollama-Lage im Fenster sagt „läuft“: der alte Fehler gilt nicht mehr."""
    monkeypatch.setattr(ollama_launcher, "ollama_lage", lambda url: (True, ["gpt-oss"]))
    win = _fenster(qtbot)
    win._on_llm_suggestions_failed(Path("scan.pdf"), LAEUFT_NICHT)
    health, hinweis = win._llm_health()
    lage = win._ollama_lage_fuer_dialog(health, hinweis)
    assert lage["laeuft"] and lage["hinweis"].art == "laeuft_nicht"  # Ausgangslage aus dem Live-Test

    assert win._veralteten_verbindungsfehler_vergessen() is True
    assert win._llm_health() == ("bereit", None)
    assert win._ollama_lage_fuer_dialog(*win._llm_health()) is None

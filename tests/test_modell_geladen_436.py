"""Statusleiste: nach einer Pause wieder „Modell wird geladen“ statt einer zu kurzen Schaetzung (Issue #436).

1. Vor einem Aufruf fragt das Programm Ollama (``/api/ps``), ob das als geladen gemerkte
   Modell noch im Speicher ist.
2. Nur eine echte Antwort des Modells zaehlt als „geladen“, nicht der Rueckfall auf die
   lokalen Regeln (Pre-Cache).

Kein Test fragt ein echtes Ollama: ``ollama_geladene_modelle`` bzw. ``loaded_models`` sind ersetzt.
"""
from __future__ import annotations

import json
import types

import pytest

from src.core import llm_activity as la
from src.ml import ollama_launcher

KEY = "ollama|gemma3:4b|suggest"
# tests/conftest.py ersetzt loaded_models in jedem Test; hier die echte Funktion
_LOADED_MODELS = ollama_launcher.loaded_models


def _geladen(activity, key=KEY):
    token = activity.begin(la.KIND_SUGGEST, "a.pdf", key=key)
    activity.end(token, success=True)


def _activity():
    store = la.LLMTimingStore(None)
    store.record(KEY, 6)
    store.record(KEY, 8)
    return la.LLMActivity(store)


def test_nach_pause_entladen_zeigt_wieder_lade_hinweis(monkeypatch):
    activity = _activity()
    _geladen(activity)
    assert not activity.modell_laedt(la.KIND_SUGGEST, KEY)

    monkeypatch.setattr(la, "ollama_geladene_modelle", lambda: [])  # Ollama hat es entladen
    activity.begin(la.KIND_SUGGEST, "b.pdf", key=KEY)
    assert activity.modell_laedt(la.KIND_SUGGEST, KEY)
    assert "Modell wird geladen" in activity.describe()
    assert "ca. 7 s" not in activity.describe()


def test_noch_geladen_bleibt_bei_der_schaetzung(monkeypatch):
    activity = _activity()
    _geladen(activity)
    monkeypatch.setattr(la, "ollama_geladene_modelle", lambda: ["gemma3:4b"])
    activity.begin(la.KIND_SUGGEST, "b.pdf", key=KEY)
    assert not activity.modell_laedt(la.KIND_SUGGEST, KEY)
    assert "ca. " in activity.describe() and "Modell wird geladen" not in activity.describe()


def test_latest_wird_wie_ohne_tag_verglichen(monkeypatch):
    activity = la.LLMActivity(la.LLMTimingStore(None))
    key = "ollama|llama3.1|suggest"
    _geladen(activity, key)
    monkeypatch.setattr(la, "ollama_geladene_modelle", lambda: ["llama3.1:latest"])
    activity.begin(la.KIND_SUGGEST, "b.pdf", key=key)
    assert not activity.modell_laedt(la.KIND_SUGGEST, key)


def test_abfrage_geht_nicht_wie_bisher(monkeypatch):
    activity = _activity()
    _geladen(activity)
    monkeypatch.setattr(la, "ollama_geladene_modelle", lambda: None)
    activity.begin(la.KIND_SUGGEST, "b.pdf", key=KEY)
    assert not activity.modell_laedt(la.KIND_SUGGEST, KEY)


def test_andere_anbieter_fragen_ollama_nicht(monkeypatch):
    def verboten():
        raise AssertionError("darf Ollama nicht fragen")

    monkeypatch.setattr(la, "ollama_geladene_modelle", verboten)
    activity = la.LLMActivity(la.LLMTimingStore(None))
    for key in ("lmstudio|m|suggest", "ollama_cloud|m|suggest", "openrouter|m|chat"):
        _geladen(activity, key)
        activity.begin(la.KIND_SUGGEST, "b.pdf", key=key)
    # noch nie geladenes Ollama-Modell: auch keine Abfrage noetig
    activity.begin(la.KIND_SUGGEST, "b.pdf", key="ollama|neu:1b|suggest")


def test_loaded_models_liest_api_ps(monkeypatch):
    antwort = {"models": [{"name": "gemma3:4b", "model": "gemma3:4b"}, {"name": "qwen3:8b"}]}

    class _Antwort:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(antwort).encode()

    aufrufe = []

    def urlopen(url, timeout):
        aufrufe.append(url)
        return _Antwort()

    echt = _LOADED_MODELS
    monkeypatch.setattr(ollama_launcher.urllib.request, "urlopen", urlopen)
    assert set(echt("http://localhost:11434/")) == {"gemma3:4b", "qwen3:8b"}
    assert aufrufe == ["http://localhost:11434/api/ps"]

    def kaputt(url, timeout):
        raise OSError("refused")

    monkeypatch.setattr(ollama_launcher.urllib.request, "urlopen", kaputt)
    assert echt("http://localhost:11434") is None


# --- Rueckfall auf lokale Regeln zaehlt nicht als „geladen“ ---

@pytest.mark.parametrize("quelle, geladen", [("local", False), ("llm", True)])
def test_vorabfrage_nur_echte_antwort_zaehlt(tmp_path, monkeypatch, quelle, geladen):
    from src.core import pdf_cache as pc

    activity = la.reset_llm_activity()
    monkeypatch.setattr(la, "current_timing_key", lambda kind: KEY)
    monkeypatch.setattr(pc, "get_llm_activity", lambda: activity)

    worker = pc.LLMSuggestionWorker()

    def suggest_filename(**kwargs):
        worker._running = False  # nach dieser einen Aufgabe aufhoeren
        return [types.SimpleNamespace(filename="x.pdf", confidence=0.5, source=quelle, metadata=None)]

    worker._hybrid_classifier = types.SimpleNamespace(
        is_llm_available=lambda: True, suggest_filename=suggest_filename, last_llm_error="Zeitueberschreitung")
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    worker.add_task(pdf, pc.PDFAnalysisResult(pdf_path=pdf, extracted_text="x", file_modified=0.0))
    worker.run()

    assert activity.modell_laedt(la.KIND_SUGGEST, KEY) is (not geladen)
    assert bool(activity.store.samples(KEY)) is geladen

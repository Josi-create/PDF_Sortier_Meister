"""MainWindow: eigenes Chat-Modell und Statuszeile (Issue #166/#167, Phase 2).

Nach dem Muster von ``tests/test_main_window_gui.py`` (Singletons auf tmp-Pfade):

* ohne Chat-Block liefert ``_chat_provider()`` None, die ChatView bekommt die
  Quelle ``chat_provider_quelle``
* mit Chat-Block (Ollama, Modell x) kommt ein OllamaProvider (ohne Netz), die
  Instanz ist gecacht, die Statuszeile zeigt "Chat: Ollama/x"
* Cloud-Anbieter ohne Einwilligung -> None mit Grund, Tooltip nennt ihn
* ``_on_settings_changed`` verwirft den Cache und ruft ``provider_geaendert()``
  der ChatView, falls vorhanden

Kein Test dieser Datei darf ins Netz (``urllib.request.urlopen`` gesperrt).
"""
from __future__ import annotations

import pytest
from PyQt6 import sip


@pytest.fixture(autouse=True)
def kein_netz(monkeypatch):
    def _verboten(*args, **kwargs):
        raise AssertionError("Netzaufruf im Test")
    monkeypatch.setattr("urllib.request.urlopen", _verboten)


@pytest.fixture
def fresh_singletons(monkeypatch, tmp_path):
    """Setzt die Module-Singletons auf tmp-Pfade und leere Defaults."""
    db_path = tmp_path / "mainwindow_chat.db"
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod
    from src.ml import classifier as cl_mod
    from src.ml import hybrid_classifier as hc_mod
    from src.core import pdf_cache as pc_mod

    from tests.conftest import patch_singletons
    fresh_config = cfg_mod.Config(config_path=tmp_path / "config.json")
    fresh_config.set("persist_pdf_cache", False)
    monkeypatch.setattr(pc_mod.PDFCache, "_instance", None)
    patch_singletons(monkeypatch, {
        "get_config": lambda: fresh_config,
        "get_database": lambda: db_mod.Database(db_path=str(db_path)),
        "get_classifier": cl_mod.PDFClassifier,
        "get_hybrid_classifier": hc_mod.HybridClassifier,
        "get_pdf_cache": pc_mod.PDFCache,
    })
    return {"config": fresh_config, "tmp_path": tmp_path}


@pytest.fixture
def fenster(qtbot, fresh_singletons, monkeypatch):
    """Fabrik fuer ein headless MainWindow; der Chat-Block wird vorher gesetzt."""
    from PyQt6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)

    from src.gui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.QMainWindow, "showMaximized", lambda self: None)
    monkeypatch.setattr(mw_mod.QMainWindow, "show", lambda self: None)

    erzeugt = []

    def _bauen(chat: dict | None = None, llm: dict | None = None):
        cfg = fresh_singletons["config"]
        if llm:
            cfg.set("llm", {**cfg.get_llm_config(), **llm})
        if chat is not None:
            cfg.set("chat", chat)
        win = mw_mod.MainWindow()
        erzeugt.append(win)
        return win

    yield _bauen

    # Wie in test_main_window_gui: sofort zerstoeren, nicht per deleteLater()
    for win in erzeugt:
        win.close()
        sip.delete(win)


def test_ohne_chat_block_kein_eigener_provider(fenster):
    win = fenster()
    assert win._chat_provider() is None
    assert win._chat_llm_grund == ""
    assert win.chat_view.chat_provider_quelle == win._chat_provider
    assert win.chat_view.chat_provider_quelle() is None
    assert "Chat:" not in win.llm_status_label.text()
    assert "Chat:" not in win.llm_status_label.toolTip()


def test_ollama_block_liefert_gecachten_ollama_provider_und_status(fenster):
    from src.ml.ollama_provider import OllamaProvider
    win = fenster(chat={"provider": "ollama", "model": "qwen3:8b", "base_url": "http://rechner:11434"})
    provider = win._chat_provider()
    assert isinstance(provider, OllamaProvider)
    assert provider._get_model_id() == "qwen3:8b"
    assert provider._get_base_url() == "http://rechner:11434"
    assert win._chat_llm_grund == ""
    assert win.chat_view.chat_provider_quelle() is provider  # gecacht
    assert win._chat_provider() is provider

    win._update_llm_status()
    label = win.llm_status_label
    assert label.text() == "LLM: Aus · Chat: Ollama/qwen3:8b"
    assert "Chat: Ollama, Modell: qwen3:8b" in label.toolTip()
    assert "Doppelklick öffnet die Einstellungen" in label.toolTip()


def test_modell_kurz_ohne_anbieter_praefix(fenster):
    win = fenster(
        chat={"provider": "openrouter", "model": "z-ai/glm-5.3-flash", "api_key": "sk-or-x"},
        llm={"cloud_consent": True},
    )
    assert win._chat_provider() is not None
    assert "Chat: OpenRouter/glm-5.3-flash" in win.llm_status_label.text()
    assert "Chat: OpenRouter, Modell: z-ai/glm-5.3-flash" in win.llm_status_label.toolTip()


def test_cloud_ohne_einwilligung_liefert_none_mit_grund(fenster):
    from src.ml.provider_factory import GRUND_KEINE_EINWILLIGUNG
    win = fenster(
        chat={"provider": "claude", "model": "sonnet-4", "api_key": "sk-ant-x"},
        llm={"cloud_consent": False},
    )
    assert win._chat_provider() is None
    assert win._chat_llm_grund == GRUND_KEINE_EINWILLIGUNG
    label = win.llm_status_label
    assert "Chat: Claude (aus)" in label.text()
    assert "Chat: Claude – nicht aktiv" in label.toolTip()
    assert "Einwilligung" in label.toolTip()


def test_cloud_ohne_key_liefert_none_mit_grund(fenster):
    from src.ml.provider_factory import GRUND_KEIN_API_KEY
    win = fenster(chat={"provider": "openai", "model": "gpt-4.1-mini"}, llm={"cloud_consent": True})
    assert win._chat_provider() is None
    assert win._chat_llm_grund == GRUND_KEIN_API_KEY
    assert "API-Key" in win.llm_status_label.toolTip()


def test_key_rueckfall_aus_llm_block(fenster):
    """Leerer Chat-Key: der Key des gleichen Anbieters aus dem llm-Block gilt."""
    win = fenster(
        chat={"provider": "claude", "model": "haiku"},
        llm={"cloud_consent": True, "api_keys": {"claude": "sk-ant-oben"}},
    )
    provider = win._chat_provider()
    assert provider is not None and provider.config.api_key == "sk-ant-oben"


def test_einstellungen_geaendert_verwirft_cache_und_meldet_chatview(fenster):
    win = fenster(chat={"provider": "ollama", "model": "qwen3:8b"})
    alt = win._chat_provider()
    assert alt is not None

    meldungen = []
    win.chat_view.provider_geaendert = lambda: meldungen.append(1)
    win.config.update_chat_config(model="gpt-oss:20b")
    win._on_settings_changed()

    assert meldungen == [1]
    neu = win._chat_provider()
    assert neu is not alt and neu._get_model_id() == "gpt-oss:20b"
    assert "Chat: Ollama/gpt-oss:20b" in win.llm_status_label.text()


def test_chat_abgeschaltet_nach_aenderung(fenster):
    win = fenster(chat={"provider": "ollama", "model": "qwen3:8b"})
    assert win._chat_provider() is not None
    win.config.update_chat_config(provider="")
    win._on_settings_changed()
    assert win._chat_provider() is None
    assert "Chat:" not in win.llm_status_label.text()


def test_konfig_aenderung_ohne_settings_signal_wird_erkannt(fenster):
    """Der Cache-Schluessel ist das Konfigurations-Dict: anderes Modell -> neue Instanz."""
    win = fenster(chat={"provider": "ollama", "model": "a"})
    p1 = win._chat_provider()
    win.config.update_chat_config(model="b")
    p2 = win._chat_provider()
    assert p2 is not p1 and p2._get_model_id() == "b"
    assert win._chat_provider() is p2

"""GUI-Tests LM Studio (Issue #45): Einstellungen und Einrichtungsassistent.

Die Erkennung (GET /v1/models) ist ersetzt - kein Netzwerk.
"""
from __future__ import annotations

import pytest

from src.gui import setup_wizard as wiz
from src.gui.settings_dialog import SettingsDialog
from src.gui.setup_wizard import PAGE_API_KEY, PAGE_PROVIDER, SetupWizard, _PROVIDER_IDS
from src.ml import lmstudio_provider as lms
from src.utils.hardware import GpuInfo, OllamaRecommendation

MODELLE = ["llama-3.2-3b-instruct", "qwen2.5-7b-instruct"]


@pytest.fixture
def fresh_config(monkeypatch, tmp_path):
    from src.core import pdf_cache as pc_mod
    from src.ml import classifier as cl_mod
    from src.ml import hybrid_classifier as hc_mod
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod
    from tests.conftest import patch_singletons

    fresh = cfg_mod.Config(config_path=tmp_path / "config.json")
    fresh.set("persist_pdf_cache", False)
    monkeypatch.setattr(pc_mod.PDFCache, "_instance", None)
    patch_singletons(monkeypatch, {
        "get_config": lambda: fresh,
        "get_database": lambda: db_mod.Database(db_path=str(tmp_path / "t.db")),
        "get_classifier": cl_mod.PDFClassifier,
        "get_hybrid_classifier": hc_mod.HybridClassifier,
        "get_pdf_cache": pc_mod.PDFCache,
    })
    return fresh


def _fake_detect(monkeypatch, models):
    calls = []

    def detect(base_url="", timeout=1.0):
        calls.append(base_url)
        return None if models is None else list(models)

    monkeypatch.setattr(lms, "detect_lm_studio", detect)
    return calls


# --- Einstellungen ----------------------------------------------------------------

def _settings_with_lmstudio(qtbot):
    d = SettingsDialog()
    qtbot.addWidget(d)
    d.provider_combo.setCurrentIndex(d._index_for_provider("lmstudio"))
    return d


def test_einstellungen_erkennt_laufendes_lmstudio(qtbot, fresh_config, monkeypatch):
    calls = _fake_detect(monkeypatch, MODELLE)
    d = _settings_with_lmstudio(qtbot)

    assert calls == ["http://localhost:1234/v1"]
    assert [d.model_combo.itemText(i) for i in range(d.model_combo.count())] == MODELLE
    assert not d.lmstudio_status_label.isHidden()
    assert "erkannt" in d.lmstudio_status_label.text()
    assert not d.api_key_input.isEnabled()
    assert d.base_url_input.isEnabled()

    d.model_combo.setCurrentText("qwen2.5-7b-instruct")
    d._save_settings()
    llm = fresh_config.get_llm_config()
    assert llm["provider"] == "lmstudio"
    assert llm["model"] == "qwen2.5-7b-instruct"
    assert llm["api_key"] == ""


def test_einstellungen_hinweis_wenn_lmstudio_nicht_laeuft(qtbot, fresh_config, monkeypatch):
    _fake_detect(monkeypatch, None)
    d = _settings_with_lmstudio(qtbot)

    assert d.model_combo.count() == 0
    assert "LM Studio starten und den lokalen Server aktivieren" in d.lmstudio_status_label.text()
    assert not d.lmstudio_status_label.isHidden()

    # Andere Provider: kein LM-Studio-Hinweis
    d.provider_combo.setCurrentIndex(d._index_for_provider("ollama"))
    assert d.lmstudio_status_label.isHidden()


def test_einstellungen_laden_behaelt_gespeichertes_modell(qtbot, fresh_config, monkeypatch):
    _fake_detect(monkeypatch, MODELLE)
    llm = fresh_config.get_llm_config()
    llm.update(provider="lmstudio", model="qwen2.5-7b-instruct")
    fresh_config.set("llm", llm)
    d = SettingsDialog()
    qtbot.addWidget(d)
    assert d.model_combo.currentText() == "qwen2.5-7b-instruct"


# --- Einrichtungsassistent --------------------------------------------------------

def _fake_env(monkeypatch, lmstudio_models):
    gpu = GpuInfo("NVIDIA GeForce RTX 3060", 12288, True, "nvidia")
    rec = OllamaRecommendation(True, "gemma3:12b", 8.1, "RTX 3060.", gpu)
    monkeypatch.setattr(wiz, "detect_ollama_environment", lambda: {
        "exe": None, "installed": False, "running": False, "recommendation": rec,
        "lmstudio_models": lmstudio_models,
    })


def _wizard_on_provider_page(qtbot):
    w = SetupWizard()
    qtbot.addWidget(w)
    w.show()
    w.next()
    w.next()
    w.next()
    page = w.page(PAGE_PROVIDER)
    qtbot.waitUntil(lambda: page.get_detection() is not None, timeout=5000)
    return w, page


def _lms_radio(page):
    return page._radios[_PROVIDER_IDS.index("lmstudio")]


def test_assistent_ohne_lmstudio_bietet_es_nicht_an(qtbot, fresh_config, monkeypatch):
    _fake_env(monkeypatch, None)
    w, page = _wizard_on_provider_page(qtbot)
    assert _lms_radio(page).isHidden()
    assert page.lmstudio_status_label.isHidden()
    assert page.get_provider_id() == "ollama"


def test_assistent_bietet_laufendes_lmstudio_an(qtbot, fresh_config, monkeypatch):
    _fake_env(monkeypatch, MODELLE)
    w, page = _wizard_on_provider_page(qtbot)

    assert not _lms_radio(page).isHidden()
    assert "LM Studio laeuft (2 Modell(e))" in page.lmstudio_status_label.text()
    # Empfehlung bleibt Ollama
    assert page.get_provider_id() == "ollama"
    assert not _lms_radio(page).text().endswith("(empfohlen)")

    _lms_radio(page).setChecked(True)
    w.next()
    api_page = w.page(PAGE_API_KEY)
    assert not api_page._ollama_box.isHidden()
    assert api_page.key_edit.isHidden()
    assert api_page.pull_btn.isHidden()      # kein Download
    assert not api_page._link_btn.isVisible()  # kein Download-Link
    assert [api_page.model_combo.itemText(i) for i in range(api_page.model_combo.count())] == MODELLE

    api_page.model_combo.setCurrentText("qwen2.5-7b-instruct")
    w.accept()
    llm = fresh_config.get_llm_config()
    assert llm["provider"] == "lmstudio"
    assert llm["model"] == "qwen2.5-7b-instruct"
    assert llm["api_key"] == ""

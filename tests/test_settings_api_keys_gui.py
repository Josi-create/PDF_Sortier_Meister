"""GUI-Tests: API-Keys werden pro Provider im SettingsDialog gehalten."""
from __future__ import annotations

import pytest

from src.gui.settings_dialog import SettingsDialog


@pytest.fixture
def fresh_config(monkeypatch, tmp_path):
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod
    from src.ml import classifier as cl_mod
    from src.ml import hybrid_classifier as hc_mod
    from src.core import pdf_cache as pc_mod

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


def _dialog(qtbot):
    d = SettingsDialog()
    qtbot.addWidget(d)
    return d


def test_switching_provider_swaps_key_and_label(qtbot, fresh_config):
    d = _dialog(qtbot)

    d.provider_combo.setCurrentIndex(1)  # Claude
    assert d.api_key_label.text() == "API-Key (Anthropic Claude):"
    d.api_key_input.setText("claude-key")

    d.provider_combo.setCurrentIndex(4)  # OpenRouter
    assert d.api_key_label.text() == "API-Key (OpenRouter):"
    assert d.api_key_input.text() == ""  # Claude-Key darf nicht mitwandern
    d.api_key_input.setText("sk-or-key")

    d.provider_combo.setCurrentIndex(1)  # zurueck zu Claude
    assert d.api_key_input.text() == "claude-key"

    d.provider_combo.setCurrentIndex(3)  # Ollama: kein Key
    assert d.api_key_label.text() == "API-Key:"
    assert d.api_key_input.text() == ""


def test_save_persists_all_keys_and_mirrors_active(qtbot, fresh_config):
    d = _dialog(qtbot)
    d.provider_combo.setCurrentIndex(1)
    d.api_key_input.setText("claude-key")
    d.provider_combo.setCurrentIndex(4)
    d.api_key_input.setText("sk-or-key")
    d._save_settings()

    llm = fresh_config.get_llm_config()
    assert llm["provider"] == "openrouter"
    assert llm["api_key"] == "sk-or-key"
    assert llm["api_keys"] == {"claude": "claude-key", "openrouter": "sk-or-key"}


def test_load_restores_per_provider_keys(qtbot, fresh_config):
    llm = fresh_config.get_llm_config()
    llm.update({
        "provider": "openrouter",
        "api_key": "sk-or-key",
        "api_keys": {"claude": "claude-key", "openrouter": "sk-or-key"},
    })
    fresh_config.set("llm", llm)

    d = _dialog(qtbot)
    assert d.provider_combo.currentIndex() == 4
    assert d.api_key_input.text() == "sk-or-key"
    d.provider_combo.setCurrentIndex(1)
    assert d.api_key_input.text() == "claude-key"


def test_legacy_single_key_is_assigned_to_active_provider(qtbot, fresh_config):
    llm = fresh_config.get_llm_config()
    llm.update({"provider": "claude", "api_key": "claude-key"})
    llm.pop("api_keys", None)
    fresh_config.set("llm", llm)

    d = _dialog(qtbot)
    assert d.api_key_input.text() == "claude-key"
    d._save_settings()
    assert fresh_config.get_llm_config()["api_keys"] == {"claude": "claude-key"}


def test_save_keeps_consent_and_cached_models(qtbot, fresh_config):
    llm = fresh_config.get_llm_config()
    llm["cloud_consent"] = True
    llm["cached_models"] = {"openrouter": ["openai/gpt-4.1-nano"]}
    fresh_config.set("llm", llm)

    d = _dialog(qtbot)
    d.provider_combo.setCurrentIndex(4)
    d.api_key_input.setText("sk-or-key")
    d._save_settings()

    saved = fresh_config.get_llm_config()
    assert saved["provider"] == "openrouter"
    assert saved["cloud_consent"] is True
    assert saved["cached_models"] == {"openrouter": ["openai/gpt-4.1-nano"]}


def test_consent_checkbox_only_for_cloud_providers(qtbot, fresh_config):
    d = _dialog(qtbot)
    d.provider_combo.setCurrentIndex(3)  # Ollama
    assert not d.cloud_consent_check.isEnabled()

    d.provider_combo.setCurrentIndex(4)  # OpenRouter
    assert d.cloud_consent_check.isEnabled()
    assert "deaktiviert" in d.consent_hint_label.text()

    d.cloud_consent_check.setChecked(True)
    assert d.consent_hint_label.text() == "Einwilligung erteilt."
    d.api_key_input.setText("sk-or-key")
    d._save_settings()
    assert fresh_config.get_llm_config()["cloud_consent"] is True


def test_consent_loaded_from_config(qtbot, fresh_config):
    llm = fresh_config.get_llm_config()
    llm.update({"provider": "openrouter", "api_key": "k", "cloud_consent": True})
    fresh_config.set("llm", llm)
    d = _dialog(qtbot)
    assert d.cloud_consent_check.isChecked()

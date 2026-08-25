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

    from src.gui import settings_dialog as sd_mod

    fresh = cfg_mod.Config(config_path=tmp_path / "config.json")
    monkeypatch.setattr(cfg_mod, "get_config", lambda: fresh)
    # SettingsDialog hat get_config auf Modulebene importiert -> dort patchen,
    # sonst laeuft der Test gegen die echte Nutzer-Config in %APPDATA%.
    monkeypatch.setattr(sd_mod, "get_config", lambda: fresh)
    monkeypatch.setattr(db_mod, "get_database",
                        lambda: db_mod.Database(db_path=str(tmp_path / "t.db")))
    monkeypatch.setattr(cl_mod, "get_classifier", cl_mod.PDFClassifier)
    monkeypatch.setattr(hc_mod, "get_hybrid_classifier", hc_mod.HybridClassifier)
    monkeypatch.setattr(pc_mod, "get_pdf_cache", pc_mod.PDFCache)
    return fresh


def _dialog(qtbot):
    d = SettingsDialog()
    qtbot.addWidget(d)
    return d


def test_switching_provider_swaps_key_and_label(qtbot, fresh_config):
    d = _dialog(qtbot)

    d.provider_combo.setCurrentIndex(3)  # Poe
    assert d.api_key_label.text() == "API-Key (Poe.com):"
    d.api_key_input.setText("poe-key")

    d.provider_combo.setCurrentIndex(5)  # OpenRouter
    assert d.api_key_label.text() == "API-Key (OpenRouter):"
    assert d.api_key_input.text() == ""  # Poe-Key darf nicht mitwandern
    d.api_key_input.setText("sk-or-key")

    d.provider_combo.setCurrentIndex(3)  # zurueck zu Poe
    assert d.api_key_input.text() == "poe-key"

    d.provider_combo.setCurrentIndex(4)  # Ollama: kein Key
    assert d.api_key_label.text() == "API-Key:"
    assert d.api_key_input.text() == ""


def test_save_persists_all_keys_and_mirrors_active(qtbot, fresh_config):
    d = _dialog(qtbot)
    d.provider_combo.setCurrentIndex(3)
    d.api_key_input.setText("poe-key")
    d.provider_combo.setCurrentIndex(5)
    d.api_key_input.setText("sk-or-key")
    d._save_settings()

    llm = fresh_config.get_llm_config()
    assert llm["provider"] == "openrouter"
    assert llm["api_key"] == "sk-or-key"
    assert llm["api_keys"] == {"poe": "poe-key", "openrouter": "sk-or-key"}


def test_load_restores_per_provider_keys(qtbot, fresh_config):
    llm = fresh_config.get_llm_config()
    llm.update({
        "provider": "openrouter",
        "api_key": "sk-or-key",
        "api_keys": {"poe": "poe-key", "openrouter": "sk-or-key"},
    })
    fresh_config.set("llm", llm)

    d = _dialog(qtbot)
    assert d.provider_combo.currentIndex() == 5
    assert d.api_key_input.text() == "sk-or-key"
    d.provider_combo.setCurrentIndex(3)
    assert d.api_key_input.text() == "poe-key"


def test_legacy_single_key_is_assigned_to_active_provider(qtbot, fresh_config):
    llm = fresh_config.get_llm_config()
    llm.update({"provider": "poe", "api_key": "poe-key"})
    llm.pop("api_keys", None)
    fresh_config.set("llm", llm)

    d = _dialog(qtbot)
    assert d.api_key_input.text() == "poe-key"
    d._save_settings()
    assert fresh_config.get_llm_config()["api_keys"] == {"poe": "poe-key"}


def test_save_keeps_consent_and_cached_models(qtbot, fresh_config):
    llm = fresh_config.get_llm_config()
    llm["cloud_consent"] = True
    llm["cached_models"] = {"openrouter": ["openai/gpt-4.1-nano"]}
    fresh_config.set("llm", llm)

    d = _dialog(qtbot)
    d.provider_combo.setCurrentIndex(5)
    d.api_key_input.setText("sk-or-key")
    d._save_settings()

    saved = fresh_config.get_llm_config()
    assert saved["provider"] == "openrouter"
    assert saved["cloud_consent"] is True
    assert saved["cached_models"] == {"openrouter": ["openai/gpt-4.1-nano"]}


def test_consent_checkbox_only_for_cloud_providers(qtbot, fresh_config):
    d = _dialog(qtbot)
    d.provider_combo.setCurrentIndex(4)  # Ollama
    assert not d.cloud_consent_check.isEnabled()

    d.provider_combo.setCurrentIndex(5)  # OpenRouter
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

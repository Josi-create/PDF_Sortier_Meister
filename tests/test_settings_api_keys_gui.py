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


def _select(dialog, provider_id: str):
    """Waehlt einen Provider anhand seiner ID (unabhaengig von der Combo-Reihenfolge)."""
    dialog.provider_combo.setCurrentIndex(dialog._index_for_provider(provider_id))


def test_switching_provider_swaps_key_and_label(qtbot, fresh_config):
    d = _dialog(qtbot)

    _select(d, "claude")
    assert d.api_key_label.text() == "API-Key (Anthropic Claude):"
    d.api_key_input.setText("claude-key")

    _select(d, "openrouter")
    assert d.api_key_label.text() == "API-Key (OpenRouter):"
    assert d.api_key_input.text() == ""  # Claude-Key darf nicht mitwandern
    d.api_key_input.setText("sk-or-key")

    _select(d, "claude")
    assert d.api_key_input.text() == "claude-key"

    _select(d, "ollama")  # kein Key noetig
    assert d.api_key_label.text() == "API-Key:"
    assert d.api_key_input.text() == ""


def test_save_persists_all_keys_and_mirrors_active(qtbot, fresh_config):
    d = _dialog(qtbot)
    _select(d, "claude")
    d.api_key_input.setText("claude-key")
    _select(d, "openrouter")
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
    assert d.provider_combo.currentIndex() == d._index_for_provider("openrouter")
    assert d.api_key_input.text() == "sk-or-key"
    _select(d, "claude")
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
    _select(d, "openrouter")
    d.api_key_input.setText("sk-or-key")
    d._save_settings()

    saved = fresh_config.get_llm_config()
    assert saved["provider"] == "openrouter"
    assert saved["cloud_consent"] is True
    assert saved["cached_models"] == {"openrouter": ["openai/gpt-4.1-nano"]}


def test_poe_is_selectable_with_own_key(qtbot, fresh_config):
    """Issue #66: Poe.com ist wieder waehlbar und haelt einen eigenen Key."""
    d = _dialog(qtbot)

    _select(d, "poe")
    assert d._provider_id_at(d.provider_combo.currentIndex()) == "poe"
    assert d.api_key_label.text() == "API-Key (Poe.com):"
    assert d.cloud_consent_check.isEnabled()  # Poe ist ein Cloud-Anbieter
    d.api_key_input.setText("poe-key")

    _select(d, "openrouter")
    assert d.api_key_input.text() == ""  # Poe-Key darf nicht mitwandern
    d.api_key_input.setText("sk-or-key")

    _select(d, "poe")
    assert d.api_key_input.text() == "poe-key"
    d._save_settings()

    llm = fresh_config.get_llm_config()
    assert llm["provider"] == "poe"
    assert llm["api_key"] == "poe-key"
    assert llm["api_keys"] == {"poe": "poe-key", "openrouter": "sk-or-key"}


def test_poe_provider_from_config_is_preselected(qtbot, fresh_config):
    """Ein gespeicherter Poe-Provider wird beim Oeffnen wieder angezeigt."""
    llm = fresh_config.get_llm_config()
    llm.update({
        "provider": "poe",
        "api_key": "poe-key",
        "api_keys": {"poe": "poe-key"},
    })
    fresh_config.set("llm", llm)

    d = _dialog(qtbot)
    assert d.provider_combo.currentIndex() == d._index_for_provider("poe")
    assert d.api_key_input.text() == "poe-key"


def test_consent_checkbox_only_for_cloud_providers(qtbot, fresh_config):
    d = _dialog(qtbot)
    _select(d, "ollama")
    assert not d.cloud_consent_check.isEnabled()

    _select(d, "openrouter")
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

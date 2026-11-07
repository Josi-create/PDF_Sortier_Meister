"""GUI-Tests: Gruppe „Chat“ im KI-Reiter der Einstellungen (Issue #166/#167, Phase 2).

Geprueft wird die Widget-Ebene des SettingsDialog:

* Laden aus dem Block ``"chat"`` (eigenes Modell, Werkzeuge, Schritte, SQL)
* Checkbox „Eigenes Modell für den Chat verwenden“ schaltet die Felder frei
* Speichern schreibt den Block ueber ``Config.update_chat_config`` (provider ""
  bei abgeschalteter Checkbox), andere Werte des Blocks bleiben erhalten
* API-Keys werden je Chat-Provider getrennt gehalten
* Einwilligungs-Hinweis fuer Cloud-Anbieter ohne Einwilligung
* „Verbindung testen“ / „Modelle aktualisieren“ nutzen die Chat-Werte

Keine Netzaufruf: Verbindungstest und Modellabruf werden durch Spione ersetzt,
``urllib.request.urlopen`` ist zusaetzlich gesperrt.
"""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QMessageBox, QScrollArea

from src.gui.settings_dialog import SettingsDialog


@pytest.fixture(autouse=True)
def kein_netz(monkeypatch):
    """Kein Test dieser Datei darf ins Netz."""
    def _verboten(*args, **kwargs):
        raise AssertionError("Netzaufruf im Test")
    monkeypatch.setattr("urllib.request.urlopen", _verboten)


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


def _select_chat(dialog, provider_id: str):
    """Waehlt einen Chat-Provider anhand seiner ID."""
    dialog.chat_provider_combo.setCurrentIndex(dialog._chat_index_for_provider(provider_id))


def _chat_provider(dialog) -> str:
    return dialog._chat_provider_id_at(dialog.chat_provider_combo.currentIndex())


# --------------------------------------------------------------------- #
# Aufbau und Laden
# --------------------------------------------------------------------- #


def test_ki_reiter_scrollt_und_hat_chat_gruppe(qtbot, fresh_config):
    d = _dialog(qtbot)
    assert isinstance(d.tab_widget.widget(0), QScrollArea)
    assert d.chat_own_model_check.text() == "Eigenes Modell für den Chat verwenden"
    assert "Ohne KI" not in [
        d.chat_provider_combo.itemText(i) for i in range(d.chat_provider_combo.count())
    ]
    assert d.chat_provider_combo.count() == len(d._LLM_PROVIDERS) - 1


def test_defaults_checkbox_aus_und_felder_deaktiviert(qtbot, fresh_config):
    d = _dialog(qtbot)
    assert not d.chat_own_model_check.isChecked()
    for widget in (d.chat_provider_combo, d.chat_model_combo, d.chat_api_key_input,
                   d.chat_base_url_input, d.chat_test_button, d.chat_refresh_models_button):
        assert not widget.isEnabled(), widget
    # Defaults der ChatConfig: Werkzeuge an, 6 Schritte, kein SQL
    assert d.chat_tools_check.isChecked()
    assert d.chat_steps_spin.value() == 6
    assert d.chat_steps_spin.minimum() == 1 and d.chat_steps_spin.maximum() == 12
    assert not d.chat_sql_check.isChecked()
    assert d.chat_steps_spin.isEnabled() and d.chat_sql_check.isEnabled()
    assert d.chat_consent_hint_label.text() == "Die Einwilligung für Cloud-Anbieter gilt auch hier."


def test_laedt_werte_aus_chat_block_ollama(qtbot, fresh_config):
    fresh_config.set("chat", {
        "provider": "ollama", "model": "qwen3:8b", "api_key": "",
        "base_url": "http://rechner:11434", "werkzeuge_aktiv": False,
        "max_werkzeug_schritte": 3, "sql_erlaubt": True, "max_context_docs": 5,
    })
    d = _dialog(qtbot)
    assert d.chat_own_model_check.isChecked()
    assert _chat_provider(d) == "ollama"
    assert d.chat_model_combo.currentText().split(" ")[0] == "qwen3:8b"
    assert d.chat_base_url_input.text() == "http://rechner:11434"
    assert d.chat_provider_combo.isEnabled() and d.chat_model_combo.isEnabled()
    assert d.chat_base_url_input.isEnabled() and d.chat_test_button.isEnabled()
    assert not d.chat_api_key_input.isEnabled()  # Ollama lokal: kein Key
    assert not d.chat_tools_check.isChecked()
    assert d.chat_steps_spin.value() == 3
    assert d.chat_sql_check.isChecked()
    # Ohne Werkzeuge sind Schrittzahl und SQL ausgegraut
    assert not d.chat_steps_spin.isEnabled() and not d.chat_sql_check.isEnabled()


def test_laedt_cloud_provider_mit_eigenem_key(qtbot, fresh_config):
    fresh_config.set("chat", {"provider": "claude", "model": "sonnet-4", "api_key": "sk-ant-chat"})
    d = _dialog(qtbot)
    assert d.chat_own_model_check.isChecked()
    assert _chat_provider(d) == "claude"
    assert d.chat_api_key_label.text() == "API-Key (Anthropic Claude):"
    assert d.chat_api_key_input.text() == "sk-ant-chat"
    assert d.chat_api_key_input.isEnabled()
    assert not d.chat_base_url_input.isEnabled()  # keine Server-URL bei Cloud
    assert d.chat_model_combo.currentText().startswith("sonnet-4")


def test_unbekannter_provider_im_block_gilt_als_aus(qtbot, fresh_config):
    fresh_config.set("chat", {"provider": "tippfehler", "model": "x"})
    d = _dialog(qtbot)
    assert not d.chat_own_model_check.isChecked()
    assert not d.chat_provider_combo.isEnabled()


def test_schrittzahl_wird_auf_1_bis_12_begrenzt(qtbot, fresh_config):
    fresh_config.set("chat", {"max_werkzeug_schritte": 50})
    assert _dialog(qtbot).chat_steps_spin.value() == 12
    fresh_config.set("chat", {"max_werkzeug_schritte": 0})
    assert _dialog(qtbot).chat_steps_spin.value() == 1


# --------------------------------------------------------------------- #
# Bedienung
# --------------------------------------------------------------------- #


def test_checkbox_an_schaltet_felder_frei(qtbot, fresh_config):
    d = _dialog(qtbot)
    d.chat_own_model_check.setChecked(True)
    assert d.chat_provider_combo.isEnabled() and d.chat_model_combo.isEnabled()
    assert d.chat_test_button.isEnabled() and d.chat_refresh_models_button.isEnabled()
    # Erster Eintrag ist Ollama: URL ja, Key nein
    assert _chat_provider(d) == "ollama"
    assert d.chat_base_url_input.isEnabled() and not d.chat_api_key_input.isEnabled()
    _select_chat(d, "openrouter")
    assert d.chat_api_key_input.isEnabled() and not d.chat_base_url_input.isEnabled()
    d.chat_own_model_check.setChecked(False)
    assert not d.chat_api_key_input.isEnabled() and not d.chat_provider_combo.isEnabled()


def test_provider_wechsel_haelt_chat_keys_getrennt(qtbot, fresh_config):
    d = _dialog(qtbot)
    d.chat_own_model_check.setChecked(True)
    _select_chat(d, "claude")
    d.chat_api_key_input.setText("claude-chat")
    _select_chat(d, "openrouter")
    assert d.chat_api_key_input.text() == ""  # Claude-Key wandert nicht mit
    assert d.chat_api_key_label.text() == "API-Key (OpenRouter):"
    d.chat_api_key_input.setText("or-chat")
    _select_chat(d, "claude")
    assert d.chat_api_key_input.text() == "claude-chat"
    _select_chat(d, "openrouter")
    d._save_settings()
    chat = fresh_config.get("chat")
    assert chat["provider"] == "openrouter" and chat["api_key"] == "or-chat"


def test_modell_liste_folgt_dem_chat_provider(qtbot, fresh_config):
    fresh_config.set_cached_models("openrouter", ["a/b", "c/d"])
    d = _dialog(qtbot)
    d.chat_own_model_check.setChecked(True)
    _select_chat(d, "openrouter")
    assert [d.chat_model_combo.itemText(i) for i in range(d.chat_model_combo.count())] == ["a/b", "c/d"]
    _select_chat(d, "ollama")
    items = [d.chat_model_combo.itemText(i) for i in range(d.chat_model_combo.count())]
    assert items == d._PROVIDER_DEFAULT_MODELS["ollama"]


def test_einwilligungshinweis_bei_cloud_ohne_einwilligung(qtbot, fresh_config):
    d = _dialog(qtbot)
    d.chat_own_model_check.setChecked(True)
    _select_chat(d, "claude")
    d.cloud_consent_check.setChecked(False)
    assert "Ohne Einwilligung" in d.chat_consent_hint_label.text()
    assert "c0392b" in d.chat_consent_hint_label.styleSheet()
    d.cloud_consent_check.setChecked(True)
    assert d.chat_consent_hint_label.text() == "Die Einwilligung für Cloud-Anbieter gilt auch hier."
    assert "gray" in d.chat_consent_hint_label.styleSheet()
    d.cloud_consent_check.setChecked(False)
    _select_chat(d, "ollama")  # lokal: kein Hinweis
    assert "Ohne Einwilligung" not in d.chat_consent_hint_label.text()
    _select_chat(d, "claude")
    d.chat_own_model_check.setChecked(False)  # Chat-Modell aus: kein Hinweis
    assert "Ohne Einwilligung" not in d.chat_consent_hint_label.text()


# --------------------------------------------------------------------- #
# Speichern
# --------------------------------------------------------------------- #


def test_speichern_schreibt_chat_block(qtbot, fresh_config):
    d = _dialog(qtbot)
    d.chat_own_model_check.setChecked(True)
    _select_chat(d, "claude")
    d.chat_api_key_input.setText("sk-ant-chat")
    d.chat_model_combo.setCurrentText("sonnet-4 (ausgewogen)")
    d.chat_tools_check.setChecked(False)
    d.chat_steps_spin.setValue(9)
    d.chat_sql_check.setChecked(True)
    d._save_settings()

    chat = fresh_config.get("chat")
    assert chat["provider"] == "claude"
    assert chat["model"] == "sonnet-4"
    assert chat["api_key"] == "sk-ant-chat"
    assert chat["base_url"] == ""
    assert chat["werkzeuge_aktiv"] is False
    assert chat["max_werkzeug_schritte"] == 9
    assert chat["sql_erlaubt"] is True
    # Sortier-LLM unberuehrt
    assert fresh_config.get_llm_config()["provider"] == "none"
    # und fuer die Provider-Fabrik direkt nutzbar
    cfg = fresh_config.get_chat_llm_config()
    assert cfg["provider"] == "claude" and cfg["model"] == "sonnet-4" and cfg["api_key"] == "sk-ant-chat"


def test_speichern_ollama_mit_server_url(qtbot, fresh_config):
    d = _dialog(qtbot)
    d.chat_own_model_check.setChecked(True)
    _select_chat(d, "ollama")
    d.chat_base_url_input.setText("http://rechner:11434")
    d.chat_model_combo.setCurrentText("qwen3:8b")
    d._save_settings()
    chat = fresh_config.get("chat")
    assert chat["provider"] == "ollama" and chat["model"] == "qwen3:8b"
    assert chat["base_url"] == "http://rechner:11434" and chat["api_key"] == ""


def test_speichern_bei_checkbox_aus_schreibt_leeren_provider(qtbot, fresh_config):
    fresh_config.set("chat", {
        "provider": "ollama", "model": "qwen3:8b", "base_url": "http://x:1",
        "max_context_docs": 5, "snippet_max_chars": 1234,
    })
    d = _dialog(qtbot)
    d.chat_own_model_check.setChecked(False)
    d._save_settings()
    chat = fresh_config.get("chat")
    assert chat["provider"] == ""
    # Modell/URL bleiben fuers Wiedereinschalten, andere Felder unberuehrt
    assert chat["model"] == "qwen3:8b" and chat["base_url"] == "http://x:1"
    assert chat["max_context_docs"] == 5 and chat["snippet_max_chars"] == 1234
    assert chat["werkzeuge_aktiv"] is True and chat["max_werkzeug_schritte"] == 6
    assert fresh_config.get_chat_llm_config() is None


def test_speichern_und_neu_laden_rundreise(qtbot, fresh_config):
    d = _dialog(qtbot)
    d.chat_own_model_check.setChecked(True)
    _select_chat(d, "ollama_cloud")
    d.chat_api_key_input.setText("oc-key")
    d.chat_model_combo.setCurrentText("gpt-oss:120b")
    d.chat_steps_spin.setValue(2)
    d._save_settings()

    d2 = _dialog(qtbot)
    assert d2.chat_own_model_check.isChecked()
    assert _chat_provider(d2) == "ollama_cloud"
    assert d2.chat_api_key_input.text() == "oc-key"
    assert d2.chat_model_combo.currentText().startswith("gpt-oss:120b")
    assert d2.chat_steps_spin.value() == 2


# --------------------------------------------------------------------- #
# Verbindung testen / Modelle aktualisieren
# --------------------------------------------------------------------- #


def test_verbindung_testen_nutzt_chat_werte(qtbot, fresh_config, monkeypatch):
    d = _dialog(qtbot)
    aufrufe = []
    monkeypatch.setattr(d, "_run_connection_test", lambda *a: aufrufe.append(a))
    d.chat_own_model_check.setChecked(True)
    _select_chat(d, "ollama")
    d.chat_base_url_input.setText("http://chat-host:1")
    d.chat_model_combo.setCurrentText("qwen3:8b (Test)")
    d.chat_test_button.click()
    assert aufrufe == [("ollama", "", "qwen3:8b", "http://chat-host:1", d.chat_test_button)]

    # Der Knopf unten testet weiterhin das Sortier-Modell
    aufrufe.clear()
    d.provider_combo.setCurrentIndex(d._index_for_provider("ollama"))
    d.model_combo.setCurrentText("llama3.1")
    d.test_button.click()
    assert aufrufe == [("ollama", "", "llama3.1", "http://localhost:11434", d.test_button)]


def test_verbindung_testen_faellt_auf_key_und_url_von_oben_zurueck(qtbot, fresh_config, monkeypatch):
    """Leerer Chat-Key/-URL: Werte des gleichen Anbieters aus der API-Konfiguration."""
    d = _dialog(qtbot)
    aufrufe = []
    monkeypatch.setattr(d, "_run_connection_test", lambda *a: aufrufe.append(a))
    d.provider_combo.setCurrentIndex(d._index_for_provider("claude"))
    d.api_key_input.setText("sk-ant-oben")
    d.chat_own_model_check.setChecked(True)
    _select_chat(d, "claude")
    d.chat_model_combo.setCurrentText("haiku")
    d.chat_test_button.click()
    assert aufrufe[-1][:3] == ("claude", "sk-ant-oben", "haiku")

    _select_chat(d, "ollama")
    d.chat_model_combo.setCurrentText("qwen3:8b")
    d.chat_test_button.click()
    assert aufrufe[-1][:4] == ("ollama", "", "qwen3:8b", "http://localhost:11434")


def test_verbindungstest_ohne_key_warnt_ohne_netz(qtbot, fresh_config, monkeypatch):
    d = _dialog(qtbot)
    warnungen = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnungen.append(a[2]))
    d.chat_own_model_check.setChecked(True)
    _select_chat(d, "openrouter")
    d.chat_test_button.click()
    assert warnungen == ["Bitte geben Sie einen API-Key ein."]
    assert d.chat_test_button.isEnabled() and d.chat_test_button.text() == "Verbindung testen"


def test_modelle_aktualisieren_fuellt_chat_combo(qtbot, fresh_config, monkeypatch):
    d = _dialog(qtbot)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    gefragt = []

    def _fetch(provider_id, api_key, base_url):
        gefragt.append((provider_id, api_key, base_url))
        return ["qwen3:8b", "gpt-oss:20b"]

    monkeypatch.setattr(d, "_fetch_models_for", _fetch)
    d.chat_own_model_check.setChecked(True)
    _select_chat(d, "ollama")
    d.chat_model_combo.setCurrentText("gpt-oss:20b")
    d.chat_refresh_models_button.click()
    assert gefragt == [("ollama", "", "http://localhost:11434")]
    assert [d.chat_model_combo.itemText(i) for i in range(d.chat_model_combo.count())] == [
        "qwen3:8b", "gpt-oss:20b"
    ]
    assert d.chat_model_combo.currentText() == "gpt-oss:20b"  # Auswahl bleibt
    assert fresh_config.get_cached_models("ollama") == ["qwen3:8b", "gpt-oss:20b"]
    assert d.chat_refresh_models_button.isEnabled()
    assert d.chat_refresh_models_button.text() == "Modelle aktualisieren"
    # Die Sortier-Combo bleibt unberuehrt
    assert "qwen3:8b" not in [d.model_combo.itemText(i) for i in range(d.model_combo.count())]

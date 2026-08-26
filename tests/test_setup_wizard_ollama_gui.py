"""GUI-Tests: Ollama-Erkennung, Hardware-Empfehlung und Modell-Seite im Wizard."""
from __future__ import annotations

import pytest

from src.gui import setup_wizard as wiz
from src.gui.setup_wizard import SetupWizard, PAGE_PROVIDER, PAGE_API_KEY, _PROVIDER_IDS
from src.utils.hardware import GpuInfo, OllamaRecommendation


@pytest.fixture
def fresh_config(monkeypatch, tmp_path):
    from src.utils import config as cfg_mod
    from tests.conftest import patch_singletons

    fresh = cfg_mod.Config(config_path=tmp_path / "config.json")
    patch_singletons(monkeypatch, {"get_config": lambda: fresh})
    return fresh


def _rec_local(model="gemma3:12b"):
    gpu = GpuInfo("NVIDIA GeForce RTX 3060", 12288, True, "nvidia")
    return OllamaRecommendation(True, model, 8.1, f"RTX 3060 mit 12 GB - empfohlen: {model}.", gpu)


def _rec_cloud():
    gpu = GpuInfo("Intel(R) UHD Graphics 770", 0, False, "intel")
    return OllamaRecommendation(False, None, 0.0, "Nur integrierte Grafik erkannt.", gpu)


def _fake_env(monkeypatch, installed, running, rec):
    monkeypatch.setattr(wiz, "detect_ollama_environment", lambda: {
        "exe": r"C:\ollama.exe" if installed else None,
        "installed": installed, "running": running, "recommendation": rec,
    })


def _wizard_on_provider_page(qtbot):
    w = SetupWizard()
    qtbot.addWidget(w)
    w.show()
    w.next()  # Welcome -> Scan
    w.next()  # Scan -> Provider (startet die Erkennung)
    page = w.page(PAGE_PROVIDER)
    qtbot.waitUntil(lambda: page.get_detection() is not None, timeout=5000)
    return w, page


def test_local_recommendation_preselects_ollama(qtbot, fresh_config, monkeypatch):
    _fake_env(monkeypatch, installed=True, running=True, rec=_rec_local())
    w, page = _wizard_on_provider_page(qtbot)

    assert page.get_provider_id() == "ollama"
    assert "installiert und laeuft" in page.ollama_status_label.text()
    assert "Ollama lokal" in page.hardware_label.text()
    ollama_radio = page._radios[_PROVIDER_IDS.index("ollama")]
    assert ollama_radio.text().endswith("(empfohlen)")


def test_cloud_recommendation_when_no_dedicated_gpu(qtbot, fresh_config, monkeypatch):
    _fake_env(monkeypatch, installed=False, running=False, rec=_rec_cloud())
    w, page = _wizard_on_provider_page(qtbot)

    assert page.get_provider_id() == "ollama_cloud"
    assert "nicht installiert" in page.ollama_status_label.text()
    assert "nicht empfohlen" in page.hardware_label.text()
    assert "Ollama Cloud" in page.hardware_label.text()
    cloud_radio = page._radios[_PROVIDER_IDS.index("ollama_cloud")]
    assert cloud_radio.text().endswith("(empfohlen)")


def test_existing_choice_is_not_overridden(qtbot, fresh_config, monkeypatch):
    fresh_config.set_llm_provider("claude")
    _fake_env(monkeypatch, installed=True, running=True, rec=_rec_local())
    w, page = _wizard_on_provider_page(qtbot)
    assert page.get_provider_id() == "claude"


def test_ollama_page_lists_models_and_saves_choice(qtbot, fresh_config, monkeypatch):
    _fake_env(monkeypatch, installed=True, running=True, rec=_rec_local("gemma3:12b"))
    monkeypatch.setattr(wiz, "probe_ollama_models", lambda: (True, "ok", ["llama3.1:latest", "gemma3:12b"]))
    w, page = _wizard_on_provider_page(qtbot)
    assert page.get_provider_id() == "ollama"

    w.next()  # -> Ollama-Seite
    api_page = w.page(PAGE_API_KEY)
    assert api_page._ollama_box.isVisible()
    qtbot.waitUntil(lambda: api_page.model_combo.count() == 2, timeout=5000)
    assert api_page.model_combo.currentText() == "gemma3:12b"  # Empfehlung bevorzugt
    assert "bereits installiert" in api_page.pull_btn.text()   # Empfehlung schon da
    assert not api_page.pull_btn.isEnabled()
    assert not api_page.ollama_warning_label.isVisible()

    w.accept()
    llm = fresh_config.get_llm_config()
    assert llm["provider"] == "ollama"
    assert llm["model"] == "gemma3:12b"
    assert llm["api_key"] == ""


def test_pull_button_active_when_recommended_model_missing(qtbot, fresh_config, monkeypatch):
    _fake_env(monkeypatch, installed=True, running=True, rec=_rec_local("gemma3:12b"))
    monkeypatch.setattr(wiz, "probe_ollama_models", lambda: (True, "ok", ["llama3.1:latest"]))
    w, page = _wizard_on_provider_page(qtbot)
    w.next()
    api_page = w.page(PAGE_API_KEY)
    qtbot.waitUntil(lambda: api_page.model_combo.count() == 1, timeout=5000)
    assert api_page.pull_btn.isEnabled()
    assert "gemma3:12b" in api_page.pull_btn.text()
    assert "8 GB" in api_page.pull_btn.text()


def test_ollama_page_without_installation(qtbot, fresh_config, monkeypatch):
    _fake_env(monkeypatch, installed=False, running=False, rec=_rec_cloud())
    w, page = _wizard_on_provider_page(qtbot)
    # Nutzer waehlt trotz Empfehlung Ollama lokal
    page._radios[_PROVIDER_IDS.index("ollama")].setChecked(True)
    w.next()
    api_page = w.page(PAGE_API_KEY)
    assert not api_page.pull_btn.isEnabled()
    assert "Erneut pruefen" in api_page.models_status_label.text()
    assert api_page.ollama_warning_label.isVisible()
    assert "gemma3:4b" in api_page.pull_btn.text()  # Fallback-Modell


def test_pull_progress_updates_ui(qtbot, fresh_config, monkeypatch):
    _fake_env(monkeypatch, installed=True, running=True, rec=_rec_local("gemma3:4b"))
    monkeypatch.setattr(wiz, "probe_ollama_models", lambda: (True, "ok", []))

    def fake_pull(base_url, model, progress_cb=None, should_cancel=None):
        progress_cb(10, "pulling manifest")
        progress_cb(100, "success")
        return True, "Modell installiert."

    import src.ml.ollama_launcher as launcher
    monkeypatch.setattr(launcher, "pull_model", fake_pull)

    w, page = _wizard_on_provider_page(qtbot)
    w.next()
    api_page = w.page(PAGE_API_KEY)
    qtbot.waitUntil(lambda: "kein Modell" in api_page.models_status_label.text(), timeout=5000)
    assert api_page.model_combo.currentText() == "gemma3:4b"

    api_page._start_pull()
    qtbot.waitUntil(lambda: "Modell installiert" in api_page.models_status_label.text()
                    or api_page.pull_progress.value() == 100, timeout=5000)
    assert api_page.pull_progress.value() == 100


def test_ollama_cloud_page_saves_key_and_default_model(qtbot, fresh_config, monkeypatch):
    _fake_env(monkeypatch, installed=False, running=False, rec=_rec_cloud())
    w, page = _wizard_on_provider_page(qtbot)
    assert page.get_provider_id() == "ollama_cloud"
    w.next()
    api_page = w.page(PAGE_API_KEY)
    assert not api_page._ollama_box.isVisible()
    assert "ollama.com/settings/keys" in api_page._link_btn.text()
    api_page.key_edit.setText("ol-secret")
    w.accept()
    llm = fresh_config.get_llm_config()
    assert llm["provider"] == "ollama_cloud"
    assert llm["api_key"] == "ol-secret"
    assert llm["model"] == "gpt-oss:120b"

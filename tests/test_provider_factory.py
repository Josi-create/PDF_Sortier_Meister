"""Tests fuer src/ml/provider_factory.py und die Chat-Modell-Konfiguration (Issue #166/#167).

Kein Provider-Konstruktor macht Netzaufrufe (Claude/OpenAI-Familie bauen nur
SDK-Clients, Ollama merkt sich die URL); ``_kein_netz`` stellt das sicher.
"""
import json

import pytest

from src.ml import provider_factory as pf
from src.ml.claude_provider import ClaudeProvider
from src.ml.ollama_provider import OllamaCloudProvider, OllamaProvider
from src.ml.openai_provider import OpenAIProvider
from src.ml.openrouter_provider import OpenRouterProvider
from src.ml.poe_provider import PoeProvider
from src.ml.strata_provider import StrataProvider
from src.ml.lmstudio_provider import LMStudioProvider
from src.utils.config import ChatConfig, Config


@pytest.fixture(autouse=True)
def _kein_netz(monkeypatch):
    """Jeder HTTP-Aufruf waehrend der Tests ist ein Fehler."""
    import urllib.request

    def _verboten(*args, **kwargs):
        raise AssertionError("Netzaufruf im Test: urllib.request.urlopen")

    monkeypatch.setattr(urllib.request, "urlopen", _verboten)


def _llm(provider, api_key="k", consent=True, **extra):
    d = {"provider": provider, "api_key": api_key, "model": "", "base_url": "",
         "cloud_consent": consent}
    d.update(extra)
    return d


# --- erzeuge_provider: Zuordnung -------------------------------------------

@pytest.mark.parametrize("provider, klasse", [
    ("claude", ClaudeProvider),
    ("openai", OpenAIProvider),
    ("poe", PoeProvider),
    ("openrouter", OpenRouterProvider),
    ("ollama", OllamaProvider),
    ("ollama_cloud", OllamaCloudProvider),
    ("strata", StrataProvider),
    ("lmstudio", LMStudioProvider),
])
def test_jeder_provider_typ_wird_ohne_netz_instanziert(provider, klasse):
    p, grund = pf.erzeuge_provider(_llm(provider))
    assert grund == ""
    assert type(p) is klasse


def test_ollama_cloud_ist_nicht_ollama():
    """Die Unterklasse darf nicht mit dem lokalen Ollama verwechselt werden."""
    p, _ = pf.erzeuge_provider(_llm("ollama"))
    assert type(p) is OllamaProvider


def test_ollama_ohne_key_ok():
    p, grund = pf.erzeuge_provider(_llm("ollama", api_key="", consent=False))
    assert grund == ""
    assert isinstance(p, OllamaProvider)
    assert p.is_available()


def test_lmstudio_ohne_key_und_ohne_einwilligung_ok():
    """LM Studio (#45) laeuft lokal: kein Key, keine Cloud-Einwilligung noetig."""
    p, grund = pf.erzeuge_provider(_llm("lmstudio", api_key="", consent=False))
    assert grund == ""
    assert type(p) is LMStudioProvider
    assert p.base_url == "http://localhost:1234/v1"
    # OpenAI-kompatibel: Werkzeug-Schleife wie bei Strata
    assert p.unterstuetzt_werkzeuge()


def test_lmstudio_base_url_wird_durchgereicht():
    p, _ = pf.erzeuge_provider(_llm("lmstudio", api_key="", base_url="http://pc:4321"))
    assert p.base_url == "http://pc:4321/v1"
    assert p.CHAT_COMPLETIONS_URL == "http://pc:4321/v1/chat/completions"


def test_claude_ohne_key():
    assert pf.erzeuge_provider(_llm("claude", api_key="")) == (None, "kein_api_key")


def test_strata_ohne_key():
    assert pf.erzeuge_provider(_llm("strata", api_key=None)) == (None, "kein_api_key")


@pytest.mark.parametrize("provider", ["claude", "openai", "poe", "openrouter", "ollama_cloud"])
def test_cloud_ohne_einwilligung(provider):
    assert pf.erzeuge_provider(_llm(provider, consent=False)) == (None, "keine_einwilligung")


def test_einwilligung_vor_api_key_geprueft():
    """Ohne Einwilligung ist der fehlende Key zweitrangig (wie bisher im HybridClassifier)."""
    assert pf.erzeuge_provider(_llm("claude", api_key="", consent=False)) == (None, "keine_einwilligung")


def test_cloud_consent_parameter_hat_vorrang_vor_dict():
    ok, grund = pf.erzeuge_provider(_llm("claude", consent=False), cloud_consent=True)
    assert grund == "" and isinstance(ok, ClaudeProvider)
    assert pf.erzeuge_provider(_llm("claude", consent=True), cloud_consent=False) == (None, "keine_einwilligung")


def test_cloud_consent_none_liest_dict_default_false():
    d = _llm("openai")
    del d["cloud_consent"]
    assert pf.erzeuge_provider(d) == (None, "keine_einwilligung")


@pytest.mark.parametrize("llm_config", [
    _llm("unbekannt"),
    _llm("none"),
    _llm(""),
    _llm(None),
    {"api_key": "k"},
    {},
])
def test_unbekannter_oder_fehlender_provider(llm_config):
    assert pf.erzeuge_provider(llm_config) == (None, "kein_provider")


def test_kein_dict():
    assert pf.erzeuge_provider(None) == (None, "kein_provider")


def test_provider_kennung_unabhaengig_von_schreibweise():
    p, grund = pf.erzeuge_provider(_llm(" Ollama "))
    assert grund == "" and isinstance(p, OllamaProvider)


# --- erzeuge_provider: LLMConfig und Fehler --------------------------------

def test_llm_config_felder_werden_uebernommen():
    p, _ = pf.erzeuge_provider(_llm(
        "ollama", api_key="", model="qwen3:8b", base_url="http://srv:11434/",
        max_tokens=4000, temperature=0.1, text_limit=9000,
    ))
    assert p.config.model == "qwen3:8b"
    assert p.config.base_url == "http://srv:11434/"
    assert p.config.max_tokens == 4000
    assert p.config.temperature == 0.1
    assert p.config.text_limit == 9000
    assert p._get_base_url() == "http://srv:11434"


def test_llm_config_defaults_wie_bisher():
    p, _ = pf.erzeuge_provider({"provider": "ollama", "model": None, "base_url": None})
    assert (p.config.max_tokens, p.config.temperature, p.config.text_limit) == (2000, 0.3, 1500)
    assert p.config.model == "" and p.config.base_url == "" and p.config.api_key == ""


def test_konstruktor_exception_wird_zu_fehlertext(monkeypatch):
    class _Kaputt:
        def __init__(self, config):
            raise RuntimeError("boom")

    monkeypatch.setattr(pf, "ClaudeProvider", _Kaputt)
    assert pf.erzeuge_provider(_llm("claude")) == (None, "fehler: boom")


def test_klassen_parameter_ersetzt_zuordnung():
    class _Stub:
        def __init__(self, config):
            self.config = config

    p, grund = pf.erzeuge_provider(_llm("claude"), klassen={"claude": _Stub})
    assert grund == "" and isinstance(p, _Stub) and p.config.api_key == "k"
    # Nicht in der Zuordnung -> kein Provider
    assert pf.erzeuge_provider(_llm("openai"), klassen={"claude": _Stub}) == (None, "kein_provider")


# --- grund_text --------------------------------------------------------------

def test_grund_text():
    assert pf.grund_text("") == ""
    assert "Anbieter" in pf.grund_text("kein_provider")
    assert "Einwilligung" in pf.grund_text("keine_einwilligung")
    assert "API-Key" in pf.grund_text("kein_api_key")
    assert pf.grund_text("fehler: boom").endswith("boom")
    assert pf.grund_text("irgendwas") == "irgendwas"


# --- HybridClassifier nutzt die Fabrik ----------------------------------------

def test_hybrid_classifier_init_ueber_fabrik_mit_stub(monkeypatch):
    """Stubs im Modul hybrid_classifier greifen weiterhin (klassen-Parameter)."""
    from src.ml import hybrid_classifier as hc_mod

    class _Stub:
        def __init__(self, config):
            self.config = config

        def is_available(self):
            return True

    monkeypatch.setattr(hc_mod, "OllamaProvider", _Stub)
    hc = hc_mod.HybridClassifier.__new__(hc_mod.HybridClassifier)
    hc.config = {"llm": {"provider": "ollama", "api_key": "", "model": "m"}}
    hc.llm_provider = None
    hc.llm_enabled = False
    hc._init_llm_provider()
    assert isinstance(hc.llm_provider, _Stub)
    assert hc.llm_enabled is True


def test_hybrid_classifier_init_konstruktorfehler(monkeypatch, capsys):
    from src.ml import hybrid_classifier as hc_mod

    class _Kaputt:
        def __init__(self, config):
            raise RuntimeError("kaputt")

    monkeypatch.setattr(hc_mod, "OllamaProvider", _Kaputt)
    hc = hc_mod.HybridClassifier.__new__(hc_mod.HybridClassifier)
    hc.config = {"llm": {"provider": "ollama", "api_key": ""}}
    hc.llm_provider = None
    hc.llm_enabled = True
    hc._init_llm_provider()
    assert hc.llm_enabled is False
    assert "Fehler bei LLM-Initialisierung: kaputt" in capsys.readouterr().out


def test_hybrid_classifier_set_llm_provider_ollama_ohne_key(monkeypatch):
    from src.ml import hybrid_classifier as hc_mod
    from src.ml.llm_provider import LLMProviderType

    hc = hc_mod.HybridClassifier.__new__(hc_mod.HybridClassifier)
    hc.config = {"llm": {"cloud_consent": False}}
    hc.llm_provider = None
    hc.llm_enabled = False
    assert hc.set_llm_provider(LLMProviderType.OLLAMA, api_key="", base_url="http://x:1/") is True
    assert isinstance(hc.llm_provider, OllamaProvider)
    assert hc.llm_provider.config.model == OllamaProvider.DEFAULT_MODEL
    assert hc.set_llm_provider(LLMProviderType.NONE, api_key="") is False
    assert hc.llm_provider is None


def test_hybrid_classifier_set_llm_provider_ohne_key_verwirft(monkeypatch):
    from src.ml import hybrid_classifier as hc_mod
    from src.ml.llm_provider import LLMProviderType

    hc = hc_mod.HybridClassifier.__new__(hc_mod.HybridClassifier)
    hc.config = {"llm": {"cloud_consent": True}}
    hc.llm_provider = object()
    hc.llm_enabled = True
    assert hc.set_llm_provider(LLMProviderType.STRATA, api_key="") is False
    assert hc.llm_provider is None and hc.llm_enabled is False


# --- Config: eigenes Chat-Modell ---------------------------------------------

def _config(tmp_path, **json_inhalt):
    pfad = tmp_path / "config.json"
    if json_inhalt:
        pfad.write_text(json.dumps(json_inhalt), encoding="utf-8")
    return Config(config_path=pfad)


def test_get_chat_llm_config_ohne_provider(tmp_path):
    cfg = _config(tmp_path)
    assert cfg.get_chat_llm_config() is None
    cfg.update_chat_config(provider="none", model="x")
    assert cfg.get_chat_llm_config() is None
    cfg.update_chat_config(provider="  ")
    assert cfg.get_chat_llm_config() is None


def test_get_chat_llm_config_mit_provider(tmp_path):
    cfg = _config(
        tmp_path,
        llm={"provider": "ollama", "api_key": "", "model": "llama3.1", "base_url": "http://l:11434",
             "cloud_consent": True, "max_tokens": 3000, "temperature": 0.5, "text_limit": 4000},
        chat={"provider": "openrouter", "model": "z-ai/glm-5.3", "api_key": "sk-or",
              "base_url": "", "werkzeuge_aktiv": True},
    )
    d = cfg.get_chat_llm_config()
    assert d == {
        "provider": "openrouter",
        "model": "z-ai/glm-5.3",
        "api_key": "sk-or",
        "base_url": "",
        "cloud_consent": True,
        "max_tokens": 3000,
        "temperature": 0.5,
        "text_limit": 4000,
    }
    # Das Dict ist direkt fuer die Fabrik brauchbar
    p, grund = pf.erzeuge_provider(d)
    assert grund == "" and isinstance(p, OpenRouterProvider)
    assert p.config.max_tokens == 3000


def test_get_chat_llm_config_defaults_aus_llm_block(tmp_path):
    cfg = _config(tmp_path, chat={"provider": "ollama"})
    d = cfg.get_chat_llm_config()
    assert d["cloud_consent"] is False
    assert (d["max_tokens"], d["temperature"], d["text_limit"]) == (2000, 0.3, 1500)
    assert d["model"] == "" and d["api_key"] == "" and d["base_url"] == ""


def test_get_chat_llm_config_key_und_url_rueckfall(tmp_path):
    """Leerer Chat-Key/-URL -> gespeicherter Wert des Anbieters aus dem llm-Block."""
    cfg = _config(
        tmp_path,
        llm={"provider": "openrouter", "api_key": "sk-or", "api_keys": {"openrouter": "sk-or", "poe": "p-key"},
             "base_urls": {"strata": "http://s:8080/v1"}},
        chat={"provider": "poe"},
    )
    assert cfg.get_chat_llm_config()["api_key"] == "p-key"
    cfg.update_chat_config(provider="strata")
    d = cfg.get_chat_llm_config()
    assert d["api_key"] == "" and d["base_url"] == "http://s:8080/v1"
    cfg.update_chat_config(api_key="eigener", base_url="http://anders")
    d = cfg.get_chat_llm_config()
    assert d["api_key"] == "eigener" and d["base_url"] == "http://anders"


def test_update_chat_config_merged_und_speichert(tmp_path):
    cfg = _config(tmp_path, chat={"max_context_docs": 3, "sql_erlaubt": True})
    cfg.update_chat_config(provider="ollama", model="qwen3:8b", werkzeuge_aktiv=False)

    chat = cfg.get_chat_config()
    assert isinstance(chat, ChatConfig)
    assert chat.max_context_docs == 3 and chat.sql_erlaubt is True  # bleibt
    assert chat.provider == "ollama" and chat.model == "qwen3:8b"
    assert chat.werkzeuge_aktiv is False

    # gespeichert: frische Instanz liest dieselben Werte
    neu = Config(config_path=tmp_path / "config.json")
    assert neu.get("chat") == {
        "max_context_docs": 3, "sql_erlaubt": True,
        "provider": "ollama", "model": "qwen3:8b", "werkzeuge_aktiv": False,
    }


def test_update_chat_config_ignoriert_unbekannte_felder(tmp_path):
    cfg = _config(tmp_path)
    cfg.update_chat_config(provider="ollama", tippfehler=1)
    assert cfg.get("chat") == {"provider": "ollama"}
    assert cfg.get_chat_config().provider == "ollama"


def test_update_chat_config_bei_kaputtem_block(tmp_path):
    cfg = _config(tmp_path, chat="unsinn")
    cfg.update_chat_config(model="m")
    assert cfg.get("chat") == {"model": "m"}

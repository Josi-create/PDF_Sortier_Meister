"""
Provider-Fabrik fuer LLM-Anbieter (Issue #166/#167, Phase 2).

Baut aus einem Konfigurations-Dict im Format des ``"llm"``-Blocks
(``provider``, ``api_key``, ``model``, ``base_url``, ``cloud_consent``,
``max_tokens``, ``temperature``, ``text_limit``) den passenden
:class:`~src.ml.llm_provider.LLMProvider`. Bis 0.25 steckte diese Logik im
:class:`~src.ml.hybrid_classifier.HybridClassifier`; seit der Chat ein eigenes
Modell haben kann (``Config.get_chat_llm_config()``), brauchen Sortierung und
Chat dieselbe Fabrik mit denselben Regeln:

* ``"none"``, leer oder unbekannt -> kein Provider;
* Cloud-Anbieter (:func:`~src.ml.llm_provider.is_cloud_provider`) nur mit
  Einwilligung zur Datenuebertragung;
* alle Anbieter ausser dem lokalen Ollama brauchen einen API-Key.

Die Fabrik wirft keine Exceptions nach aussen: Das Ergebnis ist ein Tupel
``(provider, grund)``; ``grund`` ist leer, wenn alles gut ging, sonst einer der
``GRUND_*``-Codes, den :func:`grund_text` fuer die Oberflaeche uebersetzt.

Qt-frei.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

from typing import Optional

from src.ml.llm_provider import LLMConfig, LLMProvider, is_cloud_provider
from src.ml.claude_provider import ClaudeProvider
from src.ml.openai_provider import OpenAIProvider
from src.ml.poe_provider import PoeProvider
from src.ml.openrouter_provider import OpenRouterProvider
from src.ml.ollama_provider import OllamaProvider, OllamaCloudProvider
from src.ml.strata_provider import StrataProvider


# Grund-Codes von erzeuge_provider()
GRUND_OK = ""
GRUND_KEIN_PROVIDER = "kein_provider"            # provider fehlt, "none" oder unbekannt
GRUND_KEINE_EINWILLIGUNG = "keine_einwilligung"  # Cloud-Anbieter ohne cloud_consent
GRUND_KEIN_API_KEY = "kein_api_key"              # Anbieter braucht einen Key, keiner da
GRUND_FEHLER = "fehler: "                        # Praefix; dahinter der Exception-Text

# Anbieter, die ohne API-Key laufen (lokaler Server)
PROVIDER_OHNE_API_KEY = frozenset({"ollama"})

# Defaults der LLMConfig-Felder, wenn sie im Dict fehlen (wie bisher im
# HybridClassifier; identisch mit den Dataclass-Defaults von LLMConfig)
_DEFAULT_MAX_TOKENS = 2000
_DEFAULT_TEMPERATURE = 0.3
_DEFAULT_TEXT_LIMIT = 1500


def provider_klassen() -> dict[str, type]:
    """Zuordnung Provider-Kennung -> Provider-Klasse.

    Wird bei jedem Aufruf neu aus den Modul-Namen gebaut, damit Tests einzelne
    Klassen per ``monkeypatch.setattr(provider_factory, "ClaudeProvider", Stub)``
    ersetzen koennen.
    """
    return {
        "claude": ClaudeProvider,
        "openai": OpenAIProvider,
        "poe": PoeProvider,
        "openrouter": OpenRouterProvider,
        "ollama": OllamaProvider,
        "ollama_cloud": OllamaCloudProvider,
        "strata": StrataProvider,
    }


def llm_config_aus_dict(llm_config: dict) -> LLMConfig:
    """Baut die :class:`LLMConfig` aus einem Dict im Format des ``"llm"``-Blocks.

    Fehlende Felder bekommen die bisherigen Defaults (max_tokens 2000,
    temperature 0.3, text_limit 1500); ``None``-Werte bei Key, Modell und URL
    werden zu leeren Strings.
    """
    return LLMConfig(
        api_key=str(llm_config.get("api_key") or ""),
        model=str(llm_config.get("model") or ""),
        max_tokens=llm_config.get("max_tokens", _DEFAULT_MAX_TOKENS),
        temperature=llm_config.get("temperature", _DEFAULT_TEMPERATURE),
        text_limit=llm_config.get("text_limit", _DEFAULT_TEXT_LIMIT),
        base_url=str(llm_config.get("base_url") or ""),
    )


def erzeuge_provider(
    llm_config: dict,
    cloud_consent: bool | None = None,
    *,
    klassen: dict[str, type] | None = None,
) -> tuple[Optional[LLMProvider], str]:
    """Erzeugt den LLM-Provider zu einer Konfiguration.

    Args:
        llm_config: Dict im Format des ``"llm"``-Blocks der Konfiguration
            (``Config.get_llm_config()`` oder ``Config.get_chat_llm_config()``).
            Gelesen werden ``provider``, ``api_key``, ``model``, ``base_url``,
            ``max_tokens``, ``temperature``, ``text_limit`` und - wenn
            ``cloud_consent`` nicht uebergeben wird - ``cloud_consent``.
        cloud_consent: Einwilligung zur Datenuebertragung an Cloud-Anbieter.
            ``None`` = aus ``llm_config["cloud_consent"]`` lesen (Default False).
        klassen: Abweichende Zuordnung Kennung -> Klasse (Default:
            :func:`provider_klassen`). Der HybridClassifier reicht hier seine
            eigenen Modul-Namen durch, damit bestehende Tests, die dort
            Provider-Klassen ersetzen, weiter greifen.

    Returns:
        ``(provider, grund)``. ``provider`` ist ``None``, wenn keiner gebaut
        werden konnte; ``grund`` ist dann ``GRUND_KEIN_PROVIDER``,
        ``GRUND_KEINE_EINWILLIGUNG``, ``GRUND_KEIN_API_KEY`` oder
        ``"fehler: <Text>"`` (Exception im Konstruktor). Bei Erfolg ist
        ``grund`` leer. Ob der Provider auch wirklich einsatzbereit ist
        (SDK installiert, Server erreichbar), sagt erst ``provider.is_available()``.
    """
    if not isinstance(llm_config, dict):
        return None, GRUND_KEIN_PROVIDER

    provider_typ = str(llm_config.get("provider") or "none").strip().lower()
    zuordnung = provider_klassen() if klassen is None else klassen
    klasse = zuordnung.get(provider_typ)
    if provider_typ == "none" or klasse is None:
        return None, GRUND_KEIN_PROVIDER

    # Cloud-Anbieter nur bei vorliegender Einwilligung (gilt global, aus dem
    # "llm"-Block; der Chat-Block hat keine eigene).
    if cloud_consent is None:
        cloud_consent = bool(llm_config.get("cloud_consent", False))
    if is_cloud_provider(provider_typ) and not cloud_consent:
        return None, GRUND_KEINE_EINWILLIGUNG

    config = llm_config_aus_dict(llm_config)

    # Ollama laeuft lokal und braucht keinen API-Key; alle anderen schon.
    if provider_typ not in PROVIDER_OHNE_API_KEY and not config.api_key:
        return None, GRUND_KEIN_API_KEY

    try:
        return klasse(config), GRUND_OK
    except Exception as e:  # noqa: BLE001 - Fehler kommen als Text zurueck
        return None, f"{GRUND_FEHLER}{e}"


def grund_text(grund: str) -> str:
    """Deutscher Hinweis fuer die Oberflaeche zu einem Grund-Code von :func:`erzeuge_provider`.

    Leerer Grund (Erfolg) liefert einen leeren String.
    """
    if not grund:
        return ""
    if grund == GRUND_KEIN_PROVIDER:
        return "Kein KI-Anbieter eingestellt."
    if grund == GRUND_KEINE_EINWILLIGUNG:
        return (
            "Für diesen Cloud-Anbieter fehlt die Einwilligung zur Übertragung "
            "von Dokumentinhalten (Einstellungen → KI)."
        )
    if grund == GRUND_KEIN_API_KEY:
        return "Für diesen Anbieter fehlt der API-Key (Einstellungen → KI)."
    if grund.startswith(GRUND_FEHLER):
        return f"Der KI-Anbieter konnte nicht gestartet werden: {grund[len(GRUND_FEHLER):]}"
    return grund

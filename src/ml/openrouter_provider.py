"""
OpenRouter API Provider für PDF Sortier Meister

OpenRouter (openrouter.ai) bündelt viele Modelle (OpenAI, Anthropic, Google,
Meta, Mistral, ...) hinter einer OpenAI-kompatiblen API. Daher wird hier nur
die Basis-URL und das Modell-Mapping gegenüber dem OpenAI-Provider angepasst.

GPL-3.0-or-later - Copyright (c) 2026
"""

from src.ml.openai_provider import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    """LLM-Provider für OpenRouter (OpenAI-kompatible API)."""

    API_NAME = "OpenRouter"
    BASE_URL = "https://openrouter.ai/api/v1"
    CHAT_COMPLETIONS_URL = f"{BASE_URL}/chat/completions"

    # Modell-IDs bei OpenRouter haben immer die Form "<anbieter>/<modell>".
    MODELS = {
        "openai/gpt-4.1-nano": "openai/gpt-4.1-nano",
        "openai/gpt-4.1-mini": "openai/gpt-4.1-mini",
        "openai/gpt-4o-mini": "openai/gpt-4o-mini",
        "anthropic/claude-3.5-haiku": "anthropic/claude-3.5-haiku",
        "anthropic/claude-sonnet-4": "anthropic/claude-sonnet-4",
        "google/gemini-2.5-flash": "google/gemini-2.5-flash",
        "meta-llama/llama-3.1-70b-instruct": "meta-llama/llama-3.1-70b-instruct",
        "mistralai/mistral-small": "mistralai/mistral-small",
    }

    DEFAULT_MODEL = "openai/gpt-4.1-nano"

    def _initialize_client(self):
        """Initialisiert den OpenAI-kompatiblen Client mit OpenRouter-URL."""
        if not self.config.api_key:
            return

        try:
            import openai
            self._openai = openai
            self._client = openai.OpenAI(
                api_key=self.config.api_key,
                base_url=self.BASE_URL,
            )
        except ImportError:
            print("Warnung: openai Paket nicht installiert. "
                  "Installieren mit: pip install openai")
            self._client = None
        except Exception as e:
            print(f"Fehler bei {self.API_NAME}-Initialisierung: {e}")
            self._client = None

    # Reasoning-Modelle (GLM-5.x, DeepSeek-R1, ...) denken bei der kurzen
    # Dateinamen-/Metadaten-Aufgabe sonst tausende Tokens lang - langsam und
    # bei kleinem max_tokens kommt gar kein Text mehr. "low" begrenzt das
    # Nachdenken (gemessen: 3-4 s statt 10-18 s, gleiche Qualitaet). Modelle
    # ohne Reasoning ignorieren den Parameter; lehnt eines ihn ab, wiederholt
    # OpenAIProvider._create_chat_completion den Aufruf ohne ihn.
    REASONING_EFFORT = "low"

    def _extra_request_kwargs(self) -> dict:
        return {"extra_body": {"reasoning": {"effort": self.REASONING_EFFORT}}}

    def _get_model_id(self) -> str:
        """OpenRouter-IDs werden unverändert durchgereicht ("anbieter/modell")."""
        model = (self.config.model or "").strip()
        return model if model else self.DEFAULT_MODEL

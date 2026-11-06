"""
Strata-Provider fuer PDF Sortier Meister

Strata ist ein lokaler Modell-Server mit OpenAI-kompatibler API
(Standard: http://127.0.0.1:8080/v1). Er verlangt einen eigenen API-Key
("sk-strata-..."), schickt aber nichts ins Internet - deshalb zaehlt er
nicht als Cloud-Anbieter. Gegenueber dem OpenAI-Provider aendern sich nur
die Server-URL (einstellbar) und die Modellwahl (frei, ohne Mapping).

GPL-3.0-or-later - Copyright (c) 2026
"""

from typing import Optional

from src.ml.llm_provider import LLMConfig
from src.ml.openai_provider import OpenAIProvider


def normalize_base_url(url: str) -> str:
    """Bringt die Server-URL in die Form ".../v1".

    Strata zeigt fuer manche Programme die URL ohne "/v1" an; beides soll
    funktionieren. Leer -> Standard-URL.
    """
    url = (url or "").strip().rstrip("/")
    if not url:
        return StrataProvider.DEFAULT_BASE_URL
    if not url.lower().startswith(("http://", "https://")):
        url = "http://" + url
    if not url.endswith("/v1"):
        url += "/v1"
    return url


class StrataProvider(OpenAIProvider):
    """LLM-Provider fuer einen lokalen Strata-Server (OpenAI-kompatibel)."""

    API_NAME = "Strata"
    DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"
    MODELS: dict = {}
    DEFAULT_MODEL = ""

    # Lokale Reasoning-Modelle (Qwen3 u.a.) sollen bei der kurzen
    # Dateinamen-/Metadaten-Aufgabe nicht lange nachdenken. Lehnt der Server
    # den Parameter ab, wiederholt _create_chat_completion ohne ihn.
    REASONING_EFFORT = "low"

    def __init__(self, config: LLMConfig):
        self.base_url = normalize_base_url(config.base_url)
        # Instanz-Attribut: answer_with_context (RAG-Chat) nutzt diese URL.
        self.CHAT_COMPLETIONS_URL = f"{self.base_url}/chat/completions"
        self._auto_model: Optional[str] = None
        super().__init__(config)

    def _initialize_client(self):
        """Initialisiert den OpenAI-kompatiblen Client mit der Strata-URL."""
        if not self.config.api_key:
            return
        try:
            import openai
            self._openai = openai
            self._client = openai.OpenAI(
                api_key=self.config.api_key,
                base_url=self.base_url,
            )
        except ImportError:
            print("Warnung: openai Paket nicht installiert. "
                  "Installieren mit: pip install openai")
            self._client = None
        except Exception as e:
            print(f"Fehler bei {self.API_NAME}-Initialisierung: {e}")
            self._client = None

    def _extra_request_kwargs(self) -> dict:
        return {"reasoning_effort": self.REASONING_EFFORT}

    def list_models(self) -> list[str]:
        """Liefert die Modell-IDs, die der Server gerade anbietet."""
        if self._client is None:
            return []
        try:
            return sorted(m.id for m in self._client.models.list().data)
        except Exception:
            return []

    PING_TIMEOUT = 5

    def ping(self) -> tuple[bool, str]:
        """Prueft per kurzem HTTP-Request, ob der Server antwortet und den Key annimmt.

        Bewusst ohne openai-Client: dessen Standard-Timeout betraegt Minuten.
        """
        import json
        import urllib.error
        import urllib.request

        req = urllib.request.Request(
            f"{self.base_url}/models",
            headers={"Authorization": f"Bearer {self.config.api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.PING_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            anzahl = len(data.get("data") or [])
            return True, f"{anzahl} Modell(e) geladen"
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return False, "API-Key wird nicht angenommen"
            return False, f"HTTP {e.code}"
        except urllib.error.URLError as e:
            return False, f"Verbindung fehlgeschlagen: {e.reason}"
        except Exception as e:  # noqa: BLE001
            return False, f"Fehler: {e}"

    def _get_model_id(self) -> str:
        """Eingestelltes Modell unveraendert; leer -> erstes Modell des Servers."""
        model = (self.config.model or "").strip()
        if model:
            return model
        if self._auto_model is None:
            models = self.list_models()
            self._auto_model = models[0] if models else ""
        return self._auto_model

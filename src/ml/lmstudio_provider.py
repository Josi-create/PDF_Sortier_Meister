"""
LM-Studio-Provider fuer PDF Sortier Meister (Issue #45)

LM Studio (lmstudio.ai) stellt geladene Modelle ueber einen lokalen Server
mit OpenAI-kompatibler API bereit (Standard: http://localhost:1234/v1).
Ein API-Key ist nicht noetig, Daten verlassen den Rechner nicht.

Technisch ist das derselbe Weg wie beim Strata-Server (einstellbare URL,
freie Modellwahl, erstes Modell als Rueckfall). Unterschiede:
- kein Key: der openai-Client verlangt trotzdem einen, daher ein Platzhalter
- /v1/models listet auch Embedding-Modelle; die taugen nicht zum Chatten
  und werden herausgefiltert
- Modellliste per kurzem HTTP-Request (Erkennung in Einstellungen und
  Einrichtungsassistent), nicht ueber den openai-Client mit Minuten-Timeout

Die App bietet LM Studio nie zum Download an - sie nutzt es nur, wenn es
bereits laeuft.

GPL-3.0-or-later - Copyright (c) 2026
"""

import dataclasses
import json
import urllib.request
from typing import Optional

from src.ml.llm_provider import LLMConfig
from src.ml.strata_provider import StrataProvider, normalize_base_url

DEFAULT_BASE_URL = "http://localhost:1234/v1"


def _ist_chat_modell(model_id: str) -> bool:
    """Embedding-Modelle (z.B. text-embedding-nomic-embed-text-v1.5) aussortieren."""
    return "embed" not in model_id.lower()


def detect_lm_studio(base_url: str = "", timeout: float = 1.0) -> Optional[list[str]]:
    """Fragt GET /v1/models eines laufenden LM Studio ab.

    Returns:
        Liste der Chat-Modelle (sortiert, evtl. leer), wenn der Server
        antwortet; None, wenn LM Studio nicht erreichbar ist.
    """
    url = normalize_base_url(base_url or DEFAULT_BASE_URL)
    try:
        with urllib.request.urlopen(f"{url}/models", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - jeder Fehler heisst "nicht erkannt"
        return None
    if not isinstance(data, dict):
        return None
    ids = [m.get("id", "") for m in data.get("data") or [] if isinstance(m, dict)]
    return sorted(i for i in ids if i and _ist_chat_modell(i))


class LMStudioProvider(StrataProvider):
    """LLM-Provider fuer einen lokalen LM-Studio-Server (OpenAI-kompatibel)."""

    API_NAME = "LM Studio"
    DEFAULT_BASE_URL = DEFAULT_BASE_URL
    # LM Studio prueft keinen Key; der openai-Client braucht aber einen Wert.
    PLATZHALTER_KEY = "lm-studio"

    def __init__(self, config: LLMConfig):
        config = dataclasses.replace(
            config,
            api_key=config.api_key or self.PLATZHALTER_KEY,
            base_url=config.base_url or self.DEFAULT_BASE_URL,
        )
        super().__init__(config)

    def list_models(self) -> list[str]:
        """Chat-Modelle, die LM Studio gerade anbietet (leer, wenn nicht erreichbar)."""
        return detect_lm_studio(self.base_url, timeout=self.PING_TIMEOUT) or []

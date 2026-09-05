"""
Poe API Provider für PDF Sortier Meister

Implementiert die LLM-Schnittstelle für Poe.com's API.
Poe bietet Zugang zu verschiedenen Modellen (GPT, Claude, Gemini, etc.)
über eine einheitliche OpenAI-kompatible API.

GPL-3.0-or-later - Copyright (c) 2026
"""

import json
import urllib.error
import urllib.request
from typing import Optional

from src.ml.llm_provider import LLMProvider, LLMConfig, LLMResponse


class PoeProvider(LLMProvider):
    """
    LLM-Provider für Poe.com API.

    Poe bietet Zugang zu vielen verschiedenen Modellen über eine
    OpenAI-kompatible API. Unterstützt GPT, Claude, Gemini und mehr.
    """

    # Verfügbare Poe Modelle (Stand: März 2026)
    # Hinweis: Poe-Bot-Namen können sich ändern. Bei Fehler auf poe.com prüfen.
    MODELS = {
        # Claude Modelle (Anthropic)
        "claude-3.5-haiku": "Claude-3.5-Haiku",
        "claude-3.5-sonnet": "Claude-3.5-Sonnet",
        "claude-4-sonnet": "Claude-Sonnet-4",
        "claude-4.5-sonnet": "Claude-Sonnet-4.5",
        "claude-4-opus": "Claude-Opus-4",
        # GPT Modelle (OpenAI)
        "gpt-4o-mini": "GPT-4o-Mini",
        "gpt-4o": "GPT-4o",
        "gpt-4.1-mini": "GPT-4.1-Mini",
        "gpt-4.1": "GPT-4.1",
        "o3-mini": "o3-Mini",
        "o4-mini": "o4-Mini",
        # Gemini Modelle (Google)
        "gemini-2-flash": "Gemini-2-Flash",
        "gemini-2.5-flash": "Gemini-2.5-Flash",
        "gemini-2.5-pro": "Gemini-2.5-Pro",
        # Weitere
        "llama-3.1-405b": "Llama-3.1-405B",
        "mistral-large": "Mistral-Large",
    }

    # Standard-Modell (gutes Preis-Leistungs-Verhältnis)
    DEFAULT_MODEL = "GPT-4o-Mini"

    # Poe API Base URL
    BASE_URL = "https://api.poe.com/v1"

    def __init__(self, config: LLMConfig):
        """
        Initialisiert den Poe Provider.

        Args:
            config: Konfiguration mit API-Key und Modell
        """
        super().__init__(config)
        self._openai = None
        self._initialize_client()

    def _initialize_client(self):
        """Initialisiert den OpenAI-kompatiblen API-Client für Poe."""
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
            print(f"Fehler bei Poe-Initialisierung: {e}")
            self._client = None

    def is_available(self) -> bool:
        """Prüft, ob Poe verfügbar ist."""
        return self._client is not None and self.config.api_key

    def _get_model_id(self) -> str:
        """Gibt die Poe Modell-ID zurück."""
        model = self.config.model.lower() if self.config.model else ""

        # Prüfe ob Modellname in unserem Mapping ist
        if model in self.MODELS:
            return self.MODELS[model]

        # Falls bereits ein Poe-Modellname (mit Großbuchstaben)
        if self.config.model and "-" in self.config.model:
            return self.config.model

        return self.DEFAULT_MODEL

    def _get_max_tokens(self) -> int:
        """Gibt max_tokens zurück.

        Claude-Modelle via Poe aktivieren Thinking automatisch. Damit Poe's
        intern abgeleitetes budget_tokens >= 1024 ist, muss max_tokens deutlich
        höher sein (Response-Reserve wird vorher abgezogen).
        """
        model_id = self._get_model_id().lower()
        min_tokens = 2048 if "claude" in model_id else 0
        return max(self.config.max_tokens, min_tokens)

    def classify_document(
        self,
        text: str,
        available_folders: list[str],
        keywords: list[str] = None,
        detected_date: str = None,
    ) -> LLMResponse:
        """
        Klassifiziert ein Dokument mit Poe.

        Args:
            text: Extrahierter Text aus dem Dokument
            available_folders: Liste der verfügbaren Zielordner
            keywords: Erkannte Schlüsselwörter
            detected_date: Erkanntes Datum im Dokument

        Returns:
            LLMResponse mit Ordnervorschlag
        """
        if not self.is_available():
            return LLMResponse(
                success=False,
                error_message="Poe API nicht verfügbar. API-Key prüfen."
            )

        if not available_folders:
            return LLMResponse(
                success=False,
                error_message="Keine Zielordner verfügbar."
            )

        prompt = self._build_classification_prompt(
            text, available_folders, keywords, detected_date
        )

        try:
            response = self._client.chat.completions.create(
                model=self._get_model_id(),
                max_tokens=self._get_max_tokens(),
                temperature=self.config.temperature,
                messages=[
                    {
                        "role": "system",
                        "content": "Du bist ein Assistent zum Sortieren von Dokumenten. "
                                   "Antworte präzise im geforderten Format."
                    },
                    {"role": "user", "content": prompt}
                ]
            )

            choice = response.choices[0]
            response_text = choice.message.content
            problem = self._check_response_text(
                response_text, getattr(choice, "finish_reason", None)
            )
            if problem:
                return LLMResponse(success=False, error_message=problem)
            parsed = self._parse_response(response_text)
            if parsed.get("error"):
                return LLMResponse(
                    success=False,
                    error_message=f"KI-Antwort nicht lesbar: {parsed['error']}",
                )

            # Prüfen ob der vorgeschlagene Ordner existiert
            suggested_folder = parsed.get("folder")
            if suggested_folder and suggested_folder not in available_folders:
                suggested_folder = self._find_similar_folder(
                    suggested_folder, available_folders
                )

            tokens_used = response.usage.total_tokens if response.usage else 0

            return LLMResponse(
                success=True,
                folder_suggestion=suggested_folder,
                folder_reason=parsed.get("reason"),
                confidence=parsed.get("confidence", 0.5),
                tokens_used=tokens_used,
            )

        except self._openai.APIConnectionError:
            return LLMResponse(
                success=False,
                error_message="Keine Verbindung zur Poe API."
            )
        except self._openai.RateLimitError:
            return LLMResponse(
                success=False,
                error_message="Poe API Rate-Limit erreicht. Bitte später versuchen."
            )
        except self._openai.AuthenticationError:
            return LLMResponse(
                success=False,
                error_message="Ungültiger Poe API-Key."
            )
        except Exception as e:
            return LLMResponse(
                success=False,
                error_message=f"Poe API Fehler: {str(e)}"
            )

    def suggest_filename(
        self,
        text: str,
        current_filename: str,
        keywords: list[str] = None,
        detected_date: str = None,
        target_folder: str = None,
        file_date: str = None,
        examples: list[str] | None = None,
    ) -> LLMResponse:
        """
        Schlägt einen Dateinamen mit Poe vor.

        Args:
            text: Extrahierter Text aus dem Dokument
            current_filename: Aktueller Dateiname
            keywords: Erkannte Schlüsselwörter
            detected_date: Erkanntes Datum im Dokument
            target_folder: Zielordner
            file_date: Änderungsdatum der Datei (Fallback)

        Returns:
            LLMResponse mit Dateinamenvorschlag
        """
        if not self.is_available():
            return LLMResponse(
                success=False,
                error_message="Poe API nicht verfügbar. API-Key prüfen."
            )

        prompt = self._build_filename_prompt(
            text, current_filename, keywords, detected_date, target_folder, file_date,
            examples=examples,
        )

        try:
            response = self._client.chat.completions.create(
                model=self._get_model_id(),
                max_tokens=self._get_max_tokens(),
                temperature=self.config.temperature,
                messages=[
                    {
                        "role": "system",
                        "content": "Du bist ein Assistent zum Benennen von Dokumenten. "
                                   "Antworte präzise im geforderten Format."
                    },
                    {"role": "user", "content": prompt}
                ]
            )

            choice = response.choices[0]
            response_text = choice.message.content
            problem = self._check_response_text(
                response_text, getattr(choice, "finish_reason", None)
            )
            if problem:
                return LLMResponse(success=False, error_message=problem)
            parsed = self._parse_response(response_text)
            if parsed.get("error"):
                return LLMResponse(
                    success=False,
                    error_message=f"KI-Antwort nicht lesbar: {parsed['error']}",
                )

            # Dateiname validieren
            filename = parsed.get("filename")
            if filename:
                filename = self._sanitize_filename(filename)

            tokens_used = response.usage.total_tokens if response.usage else 0

            return LLMResponse(
                success=True,
                filename_suggestion=filename,
                filename_reason=parsed.get("reason"),
                confidence=parsed.get("confidence", 0.5),
                tokens_used=tokens_used,
                metadata=parsed.get("metadata"),
            )

        except Exception as e:
            return LLMResponse(
                success=False,
                error_message=f"Poe API Fehler: {str(e)}"
            )

    def _find_similar_folder(
        self, suggested: str, available: list[str]
    ) -> Optional[str]:
        """
        Findet einen ähnlichen Ordner aus der Liste.

        Args:
            suggested: Vorgeschlagener Ordnername
            available: Verfügbare Ordner

        Returns:
            Ähnlicher Ordnername oder None
        """
        suggested_lower = suggested.lower()

        # Exakte Übereinstimmung (case-insensitive)
        for folder in available:
            if folder.lower() == suggested_lower:
                return folder

        # Teilübereinstimmung
        for folder in available:
            if suggested_lower in folder.lower() or folder.lower() in suggested_lower:
                return folder

        return None

    def _sanitize_filename(self, filename: str) -> str:
        """Bereinigt einen Dateinamen (zentral in src.utils.filename_sanitizer)."""
        from src.utils.filename_sanitizer import sanitize_filename
        return sanitize_filename(filename)

    @classmethod
    def get_available_models(cls) -> list[tuple[str, str]]:
        """
        Gibt eine Liste der verfügbaren Modelle zurück.

        Returns:
            Liste von (display_name, model_id) Tupeln
        """
        return [(f"{v} ({k})", v) for k, v in cls.MODELS.items()]

    # ------------------------------------------------------------------ #
    # RAG-Chat (Phase 19, M1)                                            #
    # ------------------------------------------------------------------ #

    REQUEST_TIMEOUT = 120

    def _http_post_json(
        self,
        url: str,
        body: dict,
        headers: dict,
        timeout: int = None,
    ) -> tuple[Optional[dict], Optional[str]]:
        """
        Minimaler HTTP-POST-Wrapper. Liefert (parsed_dict, error_str).
        Bei urllib-Fehlern wird ``(None, fehlertext)`` zurueckgegeben.
        """
        if timeout is None:
            timeout = self.REQUEST_TIMEOUT
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8")), None
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            return None, f"Poe HTTP {e.code}: {detail}"
        except urllib.error.URLError as e:
            return None, f"Keine Verbindung zur Poe API: {e.reason}"
        except Exception as e:
            return None, f"Poe-Fehler: {e}"

    def answer_with_context(
        self,
        system_prompt: str,
        context_docs: list[dict],
        user_question: str,
        max_tokens: int = 1000,
    ) -> str:
        """
        Beantwortet eine Nutzerfrage im Kontext der uebergebenen Dokumente.

        Poe nutzt eine OpenAI-kompatible ``chat/completions`` API -
        der einzige Unterschied ist die Basis-URL (``self.BASE_URL``).
        Wir gehen ebenfalls ueber ``urllib``, um keine zusaetzliche
        Dependency einzufuehren.
        """
        if not self.config.api_key:
            return ""

        from src.rag.prompts import build_context_block, build_user_prompt

        context_block = build_context_block(context_docs)
        user_prompt = build_user_prompt(user_question, context_block=context_block)

        body = {
            "model": self._get_model_id(),
            "max_tokens": self._get_max_tokens(),
            "temperature": self.config.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }
        url = f"{self.BASE_URL}/chat/completions"
        data, error = self._http_post_json(url, body, headers)
        if error or not data:
            return f"[Poe-Fehler: {error}]"

        choices = data.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        return message.get("content", "") or ""

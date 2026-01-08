"""
Poe API Provider für PDF Sortier Meister

Implementiert die LLM-Schnittstelle für Poe.com's API.
Poe bietet Zugang zu verschiedenen Modellen (GPT, Claude, Gemini, etc.)
über eine einheitliche OpenAI-kompatible API.

MIT License - Copyright (c) 2026
"""

from typing import Optional

from src.ml.llm_provider import LLMProvider, LLMConfig, LLMResponse


class PoeProvider(LLMProvider):
    """
    LLM-Provider für Poe.com API.

    Poe bietet Zugang zu vielen verschiedenen Modellen über eine
    OpenAI-kompatible API. Unterstützt GPT, Claude, Gemini und mehr.
    """

    # Verfügbare Poe Modelle (Auswahl der wichtigsten)
    MODELS = {
        # Claude Modelle
        "claude-3-opus": "Claude-3-Opus",
        "claude-3.5-sonnet": "Claude-3.5-Sonnet",
        "claude-3-haiku": "Claude-3-Haiku",
        # GPT Modelle
        "gpt-4o": "GPT-4o",
        "gpt-4o-mini": "GPT-4o-Mini",
        "gpt-4-turbo": "GPT-4-Turbo",
        "gpt-5": "GPT-5",
        # Gemini Modelle
        "gemini-2-flash": "Gemini-2-Flash",
        "gemini-pro": "Gemini-Pro",
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
                max_tokens=self.config.max_tokens,
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

            response_text = response.choices[0].message.content
            parsed = self._parse_response(response_text)

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
            text, current_filename, keywords, detected_date, target_folder, file_date
        )

        try:
            response = self._client.chat.completions.create(
                model=self._get_model_id(),
                max_tokens=self.config.max_tokens,
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

            response_text = response.choices[0].message.content
            parsed = self._parse_response(response_text)

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
        """
        Bereinigt einen Dateinamen.

        Args:
            filename: Roher Dateiname

        Returns:
            Bereinigter Dateiname
        """
        # Entferne ungültige Zeichen
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, "_")

        # Umlaute ersetzen
        replacements = {
            "ä": "ae", "ö": "oe", "ü": "ue",
            "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
            "ß": "ss"
        }
        for old, new in replacements.items():
            filename = filename.replace(old, new)

        # Leerzeichen durch Unterstriche
        filename = filename.replace(" ", "_")

        # Sicherstellen, dass .pdf Endung vorhanden
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"

        # Maximale Länge
        if len(filename) > 84:  # 80 + .pdf
            filename = filename[:80] + ".pdf"

        return filename

    @classmethod
    def get_available_models(cls) -> list[tuple[str, str]]:
        """
        Gibt eine Liste der verfügbaren Modelle zurück.

        Returns:
            Liste von (display_name, model_id) Tupeln
        """
        return [
            ("GPT-4o-Mini (schnell & günstig)", "GPT-4o-Mini"),
            ("GPT-4o (ausgewogen)", "GPT-4o"),
            ("GPT-5 (neuestes GPT)", "GPT-5"),
            ("Claude-3.5-Sonnet (Anthropic)", "Claude-3.5-Sonnet"),
            ("Claude-3-Haiku (schnell)", "Claude-3-Haiku"),
            ("Gemini-2-Flash (Google)", "Gemini-2-Flash"),
            ("Llama-3.1-405B (Meta)", "Llama-3.1-405B"),
            ("Mistral-Large (Mistral)", "Mistral-Large"),
        ]

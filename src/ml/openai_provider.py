"""
OpenAI API Provider für PDF Sortier Meister

Implementiert die LLM-Schnittstelle für OpenAI's GPT API.

MIT License - Copyright (c) 2026
"""

from typing import Optional

from src.ml.llm_provider import LLMProvider, LLMConfig, LLMResponse


class OpenAIProvider(LLMProvider):
    """
    LLM-Provider für OpenAI's GPT API.

    Unterstützt GPT-3.5 und GPT-4 Modelle.
    """

    # Verfügbare OpenAI Modelle
    MODELS = {
        "gpt-3.5": "gpt-3.5-turbo",
        "gpt-4": "gpt-4",
        "gpt-4-turbo": "gpt-4-turbo-preview",
        "gpt-4o": "gpt-4o",
        "gpt-4o-mini": "gpt-4o-mini",
    }

    DEFAULT_MODEL = "gpt-4o-mini"  # Günstigstes aktuelles Modell

    def __init__(self, config: LLMConfig):
        """
        Initialisiert den OpenAI Provider.

        Args:
            config: Konfiguration mit API-Key und Modell
        """
        super().__init__(config)
        self._openai = None
        self._initialize_client()

    def _initialize_client(self):
        """Initialisiert den OpenAI API-Client."""
        if not self.config.api_key:
            return

        try:
            import openai
            self._openai = openai
            self._client = openai.OpenAI(api_key=self.config.api_key)
        except ImportError:
            print("Warnung: openai Paket nicht installiert. "
                  "Installieren mit: pip install openai")
            self._client = None
        except Exception as e:
            print(f"Fehler bei OpenAI-Initialisierung: {e}")
            self._client = None

    def is_available(self) -> bool:
        """Prüft, ob OpenAI verfügbar ist."""
        return self._client is not None and self.config.api_key

    def _get_model_id(self) -> str:
        """Gibt die vollständige Modell-ID zurück."""
        model = self.config.model.lower()
        if model in self.MODELS:
            return self.MODELS[model]
        # Falls vollständige ID angegeben
        if model.startswith("gpt"):
            return model
        return self.MODELS[self.DEFAULT_MODEL]

    def classify_document(
        self,
        text: str,
        available_folders: list[str],
        keywords: list[str] = None,
        detected_date: str = None,
    ) -> LLMResponse:
        """
        Klassifiziert ein Dokument mit OpenAI.

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
                error_message="OpenAI API nicht verfügbar. API-Key prüfen."
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
                error_message="Keine Verbindung zur OpenAI API."
            )
        except self._openai.RateLimitError:
            return LLMResponse(
                success=False,
                error_message="OpenAI API Rate-Limit erreicht. Bitte später versuchen."
            )
        except self._openai.AuthenticationError:
            return LLMResponse(
                success=False,
                error_message="Ungültiger OpenAI API-Key."
            )
        except Exception as e:
            return LLMResponse(
                success=False,
                error_message=f"OpenAI API Fehler: {str(e)}"
            )

    def suggest_filename(
        self,
        text: str,
        current_filename: str,
        keywords: list[str] = None,
        detected_date: str = None,
        target_folder: str = None,
    ) -> LLMResponse:
        """
        Schlägt einen Dateinamen mit OpenAI vor.

        Args:
            text: Extrahierter Text aus dem Dokument
            current_filename: Aktueller Dateiname
            keywords: Erkannte Schlüsselwörter
            detected_date: Erkanntes Datum im Dokument
            target_folder: Zielordner

        Returns:
            LLMResponse mit Dateinamenvorschlag
        """
        if not self.is_available():
            return LLMResponse(
                success=False,
                error_message="OpenAI API nicht verfügbar. API-Key prüfen."
            )

        prompt = self._build_filename_prompt(
            text, current_filename, keywords, detected_date, target_folder
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
                error_message=f"OpenAI API Fehler: {str(e)}"
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

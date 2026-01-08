"""
LLM Provider-Abstraktion für PDF Sortier Meister

Bietet eine einheitliche Schnittstelle für verschiedene LLM-Anbieter
(Claude, OpenAI, etc.) zur Klassifikation und Benennung von PDFs.

MIT License - Copyright (c) 2026
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from enum import Enum


class LLMProviderType(Enum):
    """Unterstützte LLM-Anbieter."""
    CLAUDE = "claude"
    OPENAI = "openai"
    NONE = "none"  # Kein LLM verwenden


@dataclass
class LLMResponse:
    """Antwort eines LLM-Providers."""
    success: bool
    folder_suggestion: Optional[str] = None  # Vorgeschlagener Ordnername
    folder_reason: Optional[str] = None  # Begründung für Ordner
    filename_suggestion: Optional[str] = None  # Vorgeschlagener Dateiname
    filename_reason: Optional[str] = None  # Begründung für Dateiname
    confidence: float = 0.0  # 0.0 - 1.0
    error_message: Optional[str] = None
    tokens_used: int = 0


@dataclass
class LLMConfig:
    """Konfiguration für einen LLM-Provider."""
    api_key: str
    model: str
    max_tokens: int = 500
    temperature: float = 0.3  # Niedrig für konsistente Antworten


class LLMProvider(ABC):
    """
    Abstrakte Basisklasse für LLM-Provider.

    Definiert die Schnittstelle, die alle LLM-Provider implementieren müssen.
    """

    def __init__(self, config: LLMConfig):
        """
        Initialisiert den Provider.

        Args:
            config: Konfiguration mit API-Key und Modell
        """
        self.config = config
        self._client = None

    @abstractmethod
    def _initialize_client(self):
        """Initialisiert den API-Client. Wird von Subklassen implementiert."""
        pass

    @abstractmethod
    def classify_document(
        self,
        text: str,
        available_folders: list[str],
        keywords: list[str] = None,
        detected_date: str = None,
    ) -> LLMResponse:
        """
        Klassifiziert ein Dokument und schlägt einen Zielordner vor.

        Args:
            text: Extrahierter Text aus dem Dokument (gekürzt)
            available_folders: Liste der verfügbaren Zielordner
            keywords: Erkannte Schlüsselwörter
            detected_date: Erkanntes Datum im Dokument

        Returns:
            LLMResponse mit Ordnervorschlag und Begründung
        """
        pass

    @abstractmethod
    def suggest_filename(
        self,
        text: str,
        current_filename: str,
        keywords: list[str] = None,
        detected_date: str = None,
        target_folder: str = None,
    ) -> LLMResponse:
        """
        Schlägt einen Dateinamen für das Dokument vor.

        Args:
            text: Extrahierter Text aus dem Dokument (gekürzt)
            current_filename: Aktueller Dateiname
            keywords: Erkannte Schlüsselwörter
            detected_date: Erkanntes Datum im Dokument
            target_folder: Zielordner (falls bekannt)

        Returns:
            LLMResponse mit Dateinamenvorschlag und Begründung
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Prüft, ob der Provider verfügbar ist (API-Key vorhanden, etc.).

        Returns:
            True wenn der Provider verwendet werden kann
        """
        pass

    def _truncate_text(self, text: str, max_chars: int = 3000) -> str:
        """
        Kürzt Text auf eine maximale Länge für API-Calls.

        Args:
            text: Der zu kürzende Text
            max_chars: Maximale Zeichenanzahl

        Returns:
            Gekürzter Text
        """
        if not text:
            return ""
        if len(text) <= max_chars:
            return text
        # Text kürzen und Hinweis anhängen
        return text[:max_chars] + "\n[... Text gekürzt ...]"

    def _build_classification_prompt(
        self,
        text: str,
        available_folders: list[str],
        keywords: list[str] = None,
        detected_date: str = None,
    ) -> str:
        """
        Erstellt den Prompt für die Dokumentklassifikation.

        Args:
            text: Dokumenttext
            available_folders: Verfügbare Ordner
            keywords: Schlüsselwörter
            detected_date: Erkanntes Datum

        Returns:
            Formatierter Prompt
        """
        folder_list = "\n".join(f"- {folder}" for folder in available_folders)

        keyword_info = ""
        if keywords:
            keyword_info = f"\nErkannte Schlüsselwörter: {', '.join(keywords)}"

        date_info = ""
        if detected_date:
            date_info = f"\nErkanntes Datum im Dokument: {detected_date}"

        return f"""Du bist ein Assistent zum Sortieren von Dokumenten.

Analysiere das folgende Dokument und wähle den passendsten Zielordner aus der Liste.

VERFÜGBARE ORDNER:
{folder_list}

DOKUMENTINHALT:
{self._truncate_text(text)}
{keyword_info}{date_info}

AUFGABE:
1. Analysiere den Dokumentinhalt
2. Wähle den passendsten Ordner aus der Liste
3. Begründe deine Wahl kurz

Antworte im folgenden Format:
ORDNER: [Exakter Ordnername aus der Liste]
BEGRÜNDUNG: [Kurze Begründung, max 1-2 Sätze]
KONFIDENZ: [Zahl von 0-100]"""

    def _build_filename_prompt(
        self,
        text: str,
        current_filename: str,
        keywords: list[str] = None,
        detected_date: str = None,
        target_folder: str = None,
    ) -> str:
        """
        Erstellt den Prompt für Dateinamenvorschläge.

        Args:
            text: Dokumenttext
            current_filename: Aktueller Dateiname
            keywords: Schlüsselwörter
            detected_date: Erkanntes Datum
            target_folder: Zielordner

        Returns:
            Formatierter Prompt
        """
        keyword_info = ""
        if keywords:
            keyword_info = f"\nErkannte Schlüsselwörter: {', '.join(keywords)}"

        date_info = ""
        if detected_date:
            date_info = f"\nErkanntes Datum im Dokument: {detected_date}"

        folder_info = ""
        if target_folder:
            folder_info = f"\nZielordner: {target_folder}"

        return f"""Du bist ein Assistent zum Benennen von Dokumenten.

Analysiere das folgende Dokument und schlage einen aussagekräftigen Dateinamen vor.

AKTUELLER DATEINAME: {current_filename}

DOKUMENTINHALT:
{self._truncate_text(text)}
{keyword_info}{date_info}{folder_info}

REGELN FÜR DEN DATEINAMEN:
1. Format: YYYY-MM-DD_Kategorie_Beschreibung.pdf (wenn Datum vorhanden)
2. Nur Buchstaben, Zahlen, Unterstriche und Bindestriche verwenden
3. Keine Sonderzeichen, keine Leerzeichen, keine Umlaute
4. Maximal 80 Zeichen (ohne .pdf)
5. Aussagekräftig und prägnant

Antworte im folgenden Format:
DATEINAME: [Vorgeschlagener Dateiname mit .pdf]
BEGRÜNDUNG: [Kurze Begründung, max 1-2 Sätze]
KONFIDENZ: [Zahl von 0-100]"""

    def _parse_response(self, response_text: str) -> dict:
        """
        Parst die LLM-Antwort.

        Args:
            response_text: Rohe Antwort vom LLM

        Returns:
            Dictionary mit geparsten Werten
        """
        result = {
            "folder": None,
            "filename": None,
            "reason": None,
            "confidence": 0.0,
        }

        lines = response_text.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("ORDNER:"):
                result["folder"] = line.replace("ORDNER:", "").strip()
            elif line.startswith("DATEINAME:"):
                result["filename"] = line.replace("DATEINAME:", "").strip()
            elif line.startswith("BEGRÜNDUNG:"):
                result["reason"] = line.replace("BEGRÜNDUNG:", "").strip()
            elif line.startswith("KONFIDENZ:"):
                try:
                    conf_str = line.replace("KONFIDENZ:", "").strip()
                    conf_str = conf_str.replace("%", "")
                    result["confidence"] = float(conf_str) / 100.0
                except ValueError:
                    result["confidence"] = 0.5

        return result

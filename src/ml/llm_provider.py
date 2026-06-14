"""
LLM Provider-Abstraktion für PDF Sortier Meister

Bietet eine einheitliche Schnittstelle für verschiedene LLM-Anbieter
(Claude, OpenAI, etc.) zur Klassifikation und Benennung von PDFs.

MIT License - Copyright (c) 2026
"""

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Any
from enum import Enum


class LLMProviderType(Enum):
    """Unterstützte LLM-Anbieter."""
    CLAUDE = "claude"
    OPENAI = "openai"
    POE = "poe"  # Poe.com - Zugang zu vielen Modellen
    OLLAMA = "ollama"  # Lokaler Ollama-Server (kein API-Key noetig)
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
    # Metadaten-Felder (Phase 16)
    metadata: Optional[dict] = None  # Extrahierte Metadaten


@dataclass
class LLMConfig:
    """Konfiguration für einen LLM-Provider."""
    api_key: str
    model: str
    max_tokens: int = 700
    temperature: float = 0.3  # Niedrig für konsistente Antworten
    text_limit: int = 1500  # Max. Zeichen die an LLM gesendet werden
    # Optional: Basis-URL fuer lokale/selbst-gehostete Provider (z.B. Ollama).
    # Bei Cloud-Providern bleibt der Wert leer und wird ignoriert.
    base_url: str = ""
    # Kontext-Fenster des Modells in Tokens. Wird fuer RAG-Budget-Berechnungen
    # verwendet (Phase 19 / RAG-Chat, M1). Default 8000 ist ein konservativer
    # Wert, der mit lokalen 8B-Modellen und kleinen Cloud-Modellen funktioniert.
    context_window: int = 8000


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
            available_folders: Liste der verfügbare Zielordner
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
        file_date: str = None,
    ) -> LLMResponse:
        """
        Schlägt einen Dateinamen für das Dokument vor.

        Args:
            text: Extrahierter Text aus dem Dokument (gekürzt)
            current_filename: Aktueller Dateiname
            keywords: Erkannte Schlüsselwörter
            detected_date: Erkanntes Datum im Dokument
            target_folder: Zielordner (falls bekannt)
            file_date: Änderungsdatum der Datei (Fallback wenn kein Datum im Dokument)

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

    @abstractmethod
    def answer_with_context(
        self,
        system_prompt: str,
        context_docs: list[dict],
        user_question: str,
        max_tokens: int = 1000,
    ) -> str:
        """
        Beantwortet eine Nutzerfrage im Kontext bereitgestellter Dokumente (RAG).

        Wird in Phase 19 (RAG-Chat, M1) eingefuehrt. Die Implementierung
        baut aus ``context_docs`` und dem ``system_prompt`` einen Chat-Request
        an den Provider und liefert die rohe LLM-Antwort als String zurueck
        (inkl. eventueller ``[N]``-Citation-Marker). Das Parsen der
        Citation-Marker uebernimmt spaeter der ``CitationParser`` (M3).

        Args:
            system_prompt: System-Prompt mit Anweisungen + ggf. Citation-Regeln.
            context_docs: Liste von Dicts mit den Feldern
                ``index`` (int, 1-basiert), ``filename``, ``kategorie``,
                ``steuerjahr``, ``betrag``, ``korrespondent`` und
                ``text_snippet``. ``index`` ist der Identifier, auf den
                die ``[N]``-Marker im Antworttext verweisen.
            user_question: Die konkrete Nutzerfrage.
            max_tokens: Max. Tokens fuer die Antwort (Provider-spezifisch).

        Returns:
            Die rohe LLM-Antwort als String. Bei Fehlern sollte ein
            leerer String (oder eine sinnvolle Fehlermeldung als Klartext)
            zurueckgegeben werden.
        """
        pass

    def _truncate_text(self, text: str, max_chars: int = None) -> str:
        """
        Kürzt Text auf eine maximale Länge für API-Calls.

        Args:
            text: Der zu kürzende Text
            max_chars: Maximale Zeichenanzahl (None = aus Config)

        Returns:
            Gekürzter Text
        """
        if not text:
            return ""

        # Text-Limit aus Config verwenden wenn nicht explizit angegeben
        if max_chars is None:
            max_chars = self.config.text_limit

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
            detected_date: Erkanntes Datum im Dokument

        Returns:
            Formatierter Prompt (JSON Format gefordert)
        """
        folder_list = "\n".join(f"- {folder}" for folder in available_folders)

        keyword_info = ""
        if keywords:
            keyword_info = f"\nErkannte Schlüsselwörter: {', '.join(keywords)}"

        date_info = ""
        if detected_date:
            date_info = f"\nErkanntes Datum im Dokument: {detected_date}"

        return f"""Du bist ein Assistent zum Sortieren von Dokumenten. Analysiere das folgende Dokument und wähle den passendsten Zielordner aus der Liste.

VERFÜGBARE ORDNER:
{folder_list}

DOKUMENTINHALT:
{self._truncate_text(text)}
{keyword_info}{date_info}

AUFGABE:
1. Analysiere den Dokumentinhalt.
2. Wähle den passendsten Ordner aus der Liste (exakter Name).
3. Begründe deine Wahl kurz.

Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt im folgenden Format:
{{
  "folder": "Exakter Ordnername aus der Liste oder NULL",
  "reason": "Kurze Begründung (max 2 Sätze)",
  "confidence": 0.9,
  "metadata": {{
    "category": "Rechnung/Vertrag/Steuer/Versicherung/Bank/Gehalt/Arzt/Energie/Sonstiges",
    "korrespondent": "Firmenname des Absenders",
    "betrag_netto": "123.45 oder UNBEKANNT",
    "betrag_brutto": "123.45 oder UNBEKANNT",
    "waehrung": "EUR/USD oder UNBEKANNT",
    "mwst": 7,
    "iban": "IBAN oder UNBEKANNT",
    "steuerjahr": 2024,
    "beschreibung": "Zusammenfassung des Dokuments in einem Satz"
  }}
}}"""

    def _build_filename_prompt(
        self,
        text: str,
        current_filename: str,
        keywords: list[str] = None,
        detected_date: str = None,
        target_folder: str = None,
        file_date: str = None,
    ) -> str:
        """
        Erstellt den Prompt für Dateinamenvorschläge.

        Args:
            text: Dokumenttext
            current_filename: Aktueller Dateiname
            keywords: Schlüsselwörter
            detected_date: Erkanntes Datum im Dokument
            target_folder: Zielordner (falls bekannt)
            file_date: Änderungsdatum der Datei (Fallback wenn kein Datum im Dokument)

        Returns:
            Formatierter Prompt (JSON Format gefordert)
        """
        keyword_info = ""
        if keywords:
            keyword_info = f"\nErkannte Schlüsselwörter: {', '.join(keywords)}"

        date_info = ""
        if detected_date:
            date_info = f"\nErkanntes Datum im Dokument: {detected_date}"

        file_date_info = ""
        if file_date:
            file_date_info = f"\nÄnderungsdatum der Datei (Scandatum): {file_date}"

        folder_info = ""
        if target_folder:
            folder_info = f"\nZielordner: {target_folder}"

        owner_info = self._build_owner_info()
        pattern_info = self._build_filename_pattern_info()

        return f"""Du bist ein Assistent zum Benennen und Analysieren von Dokumenten. Schlage einen aussagekräftigen Dateinamen vor und extrahiere Metadaten.
{owner_info}
AKTUELLER DATEINAME: {current_filename}

DOKUMENTINHALT:
{self._truncate_text(text)}
{keyword_info}{date_info}{file_date_info}{folder_info}
{pattern_info}

REGELN FÜR DEN DATEINAMEN:
1. Format (falls nicht durch Muster vorgegeben): YYYY-MM-DD_Kategorie_Beschreibung.pdf
2. Nur Buchstaben, Zahlen, Unterstriche und Bindestriche verwenden. Keine Umlaute/Leerzeichen.
3. Maximal 80 Zeichen (ohne .pdf).
4. Datum aus dem Dokument verwenden! Wenn kein Datum vorhanden, nutze das Scandatum.

Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt im folgenden Format:
{{
  "filename": "Vorgeschlagener_Dateiname.pdf",
  "reason": "Kurze Begründung für den Dateinamen",
  "confidence": 0.9,
  "metadata": {{
    "category": "Rechnung/Vertrag/Steuer/Versicherung/Bank/Gehalt/Arzt/Energie/Sonstiges",
    "korrespondent": "Firmenname des Absenders",
    "betrag_netto": "123.45 oder UNBEKANNT",
    "betrag_brutto": "123.45 oder UNBEKANNT",
    "waehrung": "EUR/USD oder UNBEKANNT",
    "mwst": 7,
    "iban": "IBAN oder UNBEKANNT",
    "steuerjahr": 2024,
    "beschreibung": "Zusammenfassung in einem Satz"
  }}
}}"""

    def _build_filename_pattern_info(self) -> str:
        """Erstellt einen Hinweis-Abschnitt fuer den Filename-Prompt."""
        try:
            from src.utils.config import get_config
            pattern = get_config().get("filename_pattern", "").strip()
        except Exception:
            return ""

        if not pattern:
            return ""

        return (
            "\nBENUTZERDEFINIERTES DATEINAMEN-MUSTER:\n"
            f"    {pattern}\n"
            "Nutze dieses Muster als Strukturvorlage für den Dateinamen.\n"
        )

    def _build_owner_info(self) -> str:
        """Erstellt den Benutzer-Identitäts-Abschnitt für den Prompt."""
        try:
            from src.utils.config import get_config
            config = get_config()
            owner_name = config.get("owner_name", "")
            owner_variants = config.get("owner_name_variants", "")
            owner_company = config.get("owner_company", "")
            owner_emails = config.get("owner_emails", "")

            if not owner_name and not owner_emails:
                return ""

            names = []
            if owner_name:
                names.append(owner_name)
            if owner_variants:
                names.extend(v.strip() for v in owner_variants.split(",") if v.strip())
            if owner_company:
                names.append(owner_company)

            emails = [
                e.strip() for e in owner_emails.split(",") if e.strip()
            ] if owner_emails else []

            parts = ["\nWICHTIG - DOKUMENTBESITZER:"]
            if names:
                names_str = ", ".join(f'"{n}"' for n in names)
                parts.append(
                    f" Die folgenden Namen gehören dem Benutzer "
                    f"(Empfänger/Besitzer der Dokumente): {names_str}."
                )
            if emails:
                emails_str = ", ".join(f'"{e}"' for e in emails)
                parts.append(
                    f" Die folgenden E-Mail-Adressen gehören ebenfalls dem "
                    f"Benutzer: {emails_str}."
                )
            parts.append(
                " Diese Namen und Adressen sind NICHT der Korrespondent! "
                "Der Korrespondent ist immer der ABSENDER/die andere Partei."
            )
            return "".join(parts)
        except Exception:
            return ""

    def _truncate_text(self, text: str, max_chars: int = None) -> str:
        """Kürzt Text auf eine maximale Länge für API-Calls."""
        if not text:
            return ""
        if max_chars is None:
            max_chars = self.config.text_limit
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n[... Text gekürzt ...]"

    def _parse_json_response(self, response_text: str) -> tuple[Optional[dict], Optional[str]]:
        """
        Extrahiert und parst das JSON aus einer Antwort.

        Args:
            response_text: Der rohe Text vom LLM (kann Text vor/nach dem JSON enthalten).

        Returns:
            Ein Tupel (erfolgreiches_dict, fehlermeldung). Bei Fehler ist dict None.
        """
        try:
            # Suche nach dem ersten '{' und dem letzten '}' um den JSON-Block zu finden
            match = re.search(r"(\{.*\})", response_text, re.DOTALL | re.MULTILINE)
            if not match:
                return None, "Kein gültiges JSON im Antworttext gefunden."

            json_str = match.group(1)
            data = json.loads(json_str)

            if not isinstance(data, dict):
                return None, "JSON ist kein Objekt (Dictionary)."

            return data, None
        except json.JSONDecodeError as e:
            return None, f"JSON Parsing Fehler: {str(e)}"
        except Exception as e:
            return None, f"Fehler beim Extrahieren von JSON: {str(e)}"

    def _parse_response(self, response_text: str) -> dict:
        """
        Parst die (JSON-)Antwort des LLMs in das von den Cloud-Providern
        erwartete Dictionary-Format (folder/filename/reason/confidence/metadata).

        Nutzt intern die robuste JSON-Extraktion. Schlaegt das Parsen fehl,
        wird ein leeres Default-Dict zurueckgegeben.
        """
        result = {
            "folder": None,
            "filename": None,
            "reason": None,
            "confidence": 0.0,
            "metadata": {},
        }

        data, error = self._parse_json_response(response_text)
        if error or not data:
            return result

        folder = data.get("folder")
        result["folder"] = folder if folder != "NULL" else None
        filename = data.get("filename")
        result["filename"] = filename if filename != "NULL" else None
        result["reason"] = data.get("reason")
        try:
            result["confidence"] = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            result["confidence"] = 0.5
        if isinstance(data.get("metadata"), dict):
            result["metadata"] = data["metadata"]

        return result

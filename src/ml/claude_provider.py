"""
Claude API Provider für PDF Sortier Meister

Implementiert die LLM-Schnittstelle für Anthropic's Claude API.

MIT License - Copyright (c) 2026
"""

import json
import urllib.error
import urllib.request
from typing import Optional

from src.ml.llm_provider import LLMProvider, LLMConfig, LLMResponse


class ClaudeProvider(LLMProvider):
    """
    LLM-Provider für Anthropic's Claude API.

    Unterstützt Claude 3 Modelle (Haiku, Sonnet, Opus).
    """

    # Verfügbare Claude Modelle (Stand: März 2026)
    MODELS = {
        "haiku-3.5": "claude-3-5-haiku-20241022",
        "haiku-4.5": "claude-haiku-4-5-20251001",
        "sonnet-3.5": "claude-3-5-sonnet-20241022",
        "sonnet-4": "claude-sonnet-4-20250514",
        "sonnet-4.5": "claude-sonnet-4-5-20250514",
        "opus-4": "claude-opus-4-20250514",
    }

    DEFAULT_MODEL = "haiku-4.5"  # Günstigstes aktuelles Modell

    def __init__(self, config: LLMConfig):
        """
        Initialisiert den Claude Provider.

        Args:
            config: Konfiguration mit API-Key und Modell
        """
        super().__init__(config)
        self._anthropic = None
        self._initialize_client()

    def _initialize_client(self):
        """Initialisiert den Anthropic API-Client."""
        if not self.config.api_key:
            return

        try:
            import anthropic
            self._anthropic = anthropic
            self._client = anthropic.Anthropic(api_key=self.config.api_key)
        except ImportError:
            print("Warnung: anthropic Paket nicht installiert. "
                  "Installieren mit: pip install anthropic")
            self._client = None
        except Exception as e:
            print(f"Fehler bei Claude-Initialisierung: {e}")
            self._client = None

    def is_available(self) -> bool:
        """Prüft, ob Claude verfügbar ist."""
        return self._client is not None and self.config.api_key

    def _get_model_id(self) -> str:
        """Gibt die vollständige Modell-ID zurück."""
        model = self.config.model.lower()
        if model in self.MODELS:
            return self.MODELS[model]
        # Falls vollständige ID angegeben
        if model.startswith("claude"):
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
        Klassifiziert ein Dokument mit Claude.

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
                error_message="Claude API nicht verfügbar. API-Key prüfen."
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
            message = self._client.messages.create(
                model=self._get_model_id(),
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            response_text = message.content[0].text
            parsed = self._parse_response(response_text)

            # Prüfen ob der vorgeschlagene Ordner existiert
            suggested_folder = parsed.get("folder")
            if suggested_folder and suggested_folder not in available_folders:
                # Versuche ähnlichen Ordner zu finden
                suggested_folder = self._find_similar_folder(
                    suggested_folder, available_folders
                )

            tokens_used = message.usage.input_tokens + message.usage.output_tokens

            return LLMResponse(
                success=True,
                folder_suggestion=suggested_folder,
                folder_reason=parsed.get("reason"),
                confidence=parsed.get("confidence", 0.5),
                tokens_used=tokens_used,
            )

        except self._anthropic.APIConnectionError:
            return LLMResponse(
                success=False,
                error_message="Keine Verbindung zur Claude API."
            )
        except self._anthropic.RateLimitError:
            return LLMResponse(
                success=False,
                error_message="Claude API Rate-Limit erreicht. Bitte später versuchen."
            )
        except self._anthropic.AuthenticationError:
            return LLMResponse(
                success=False,
                error_message="Ungültiger Claude API-Key."
            )
        except Exception as e:
            return LLMResponse(
                success=False,
                error_message=f"Claude API Fehler: {str(e)}"
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
        Schlägt einen Dateinamen mit Claude vor.

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
                error_message="Claude API nicht verfügbar. API-Key prüfen."
            )

        prompt = self._build_filename_prompt(
            text, current_filename, keywords, detected_date, target_folder, file_date
        )

        try:
            message = self._client.messages.create(
                model=self._get_model_id(),
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            response_text = message.content[0].text
            parsed = self._parse_response(response_text)

            # Dateiname validieren
            filename = parsed.get("filename")
            if filename:
                filename = self._sanitize_filename(filename)

            tokens_used = message.usage.input_tokens + message.usage.output_tokens

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
                error_message=f"Claude API Fehler: {str(e)}"
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

    # ------------------------------------------------------------------ #
    # RAG-Chat (Phase 19, M1)                                            #
    # ------------------------------------------------------------------ #

    # Anthropic Messages API URL (konfigurierbar fuer Proxies)
    MESSAGES_URL = "https://api.anthropic.com/v1/messages"
    # Aktuelle API-Version (Stand 2026)
    ANTHROPIC_VERSION = "2023-06-01"

    def _http_post_json(
        self,
        url: str,
        body: dict,
        headers: dict,
        timeout: int = 120,
    ) -> tuple[Optional[dict], Optional[str]]:
        """
        Minimaler HTTP-POST-Wrapper. Liefert (parsed_dict, error_str).
        Bei urllib-Fehlern wird ``(None, fehlertext)`` zurueckgegeben.
        """
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
            return None, f"Claude HTTP {e.code}: {detail}"
        except urllib.error.URLError as e:
            return None, f"Keine Verbindung zur Claude API: {e.reason}"
        except Exception as e:
            return None, f"Claude-Fehler: {e}"

    def answer_with_context(
        self,
        system_prompt: str,
        context_docs: list[dict],
        user_question: str,
        max_tokens: int = 1000,
    ) -> str:
        """
        Beantwortet eine Nutzerfrage im Kontext der uebergebenen Dokumente.

        Verwendet die Anthropic ``messages`` API. Der ``system``-Parameter
        wird separat uebergeben (nicht in ``messages``). Wir nutzen
        bewusst ``urllib`` (kein anthropic SDK noetig), damit keine
        zusaetzliche Dependency eingefuehrt wird - das Verhalten ist
        identisch zu dem der anderen Provider.
        """
        if not self.config.api_key:
            return ""

        from src.rag.prompts import build_context_block, build_user_prompt

        context_block = build_context_block(context_docs)
        user_prompt = build_user_prompt(user_question, context_block=context_block)

        body = {
            "model": self._get_model_id(),
            "max_tokens": max_tokens,
            "temperature": self.config.temperature,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.config.api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
        }
        data, error = self._http_post_json(self.MESSAGES_URL, body, headers)
        if error or not data:
            return f"[Claude-Fehler: {error}]"

        content = data.get("content") or []
        # Antwort ist eine Liste von Bloecken; wir suchen den ersten text-Block.
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "") or ""
        return ""

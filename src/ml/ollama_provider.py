"""
Ollama Provider fuer PDF Sortier Meister

Implementiert die LLM-Schnittstelle fuer einen lokal laufenden
Ollama-Server (https://ollama.com).

Vorteile lokaler Modelle:
- Keine API-Kosten, keine Cloud
- Daten verlassen den Rechner nicht
- Funktioniert offline

Nachteile:
- Erfordert Installation und Modell-Download (z.B. "ollama pull llama3.1")
- Qualitaet haengt stark vom Modell ab; kleine Modelle sind beim
  strukturierten Antworten weniger zuverlaessig als Cloud-Modelle.

Diese Implementierung spricht die native Ollama-API (/api/chat) ueber
urllib (stdlib), um keine zusaetzliche Dependency einzufuehren.

MIT License - Copyright (c) 2026
"""

import json
import urllib.error
import urllib.request
from typing import Optional

from src.ml.llm_provider import LLMProvider, LLMConfig, LLMResponse


class OllamaProvider(LLMProvider):
    """
    LLM-Provider fuer einen lokal laufenden Ollama-Server.

    Die Verbindung erfolgt ueber die native Ollama HTTP-API
    (Default: http://localhost:11434). Es wird kein API-Key benoetigt;
    stattdessen wird ueber ``LLMConfig.base_url`` der Server-Endpunkt
    konfiguriert und ueber ``LLMConfig.model`` der Modellname.

    Beispiel-Modelle: ``llama3.1``, ``llama3.2``, ``qwen2.5``,
    ``gemma3:12b``, ``mistral``.
    """

    DEFAULT_BASE_URL = "http://localhost:11434"
    DEFAULT_MODEL = "llama3.1"

    # Timeout fuer einen einzelnen Request in Sekunden.
    # Lokale Modelle koennen je nach Hardware lange brauchen.
    REQUEST_TIMEOUT = 120

    def __init__(self, config: LLMConfig):
        """
        Initialisiert den Ollama Provider.

        Args:
            config: Konfiguration mit Modellname und (optional) base_url
        """
        super().__init__(config)
        self._initialize_client()

    def _initialize_client(self):
        """
        Bereitet die Server-URL vor.

        Anders als bei den Cloud-Providern gibt es hier kein SDK-Objekt.
        Wir markieren den Provider einfach als bereit, sobald eine URL
        bekannt ist.
        """
        # _client wird als "Marker" benutzt, damit is_available() konsistent
        # mit den anderen Providern bleibt.
        self._client = self._get_base_url()

    def _get_base_url(self) -> str:
        """Liefert die zu verwendende Ollama-Basis-URL ohne Trailing-Slash."""
        url = (self.config.base_url or self.DEFAULT_BASE_URL).strip()
        return url.rstrip("/")

    def _get_model_id(self) -> str:
        """Gibt den Modellnamen zurueck (ohne weiteres Mapping)."""
        return self.config.model.strip() if self.config.model else self.DEFAULT_MODEL

    def is_available(self) -> bool:
        """
        Prueft, ob Ollama verfuegbar ist.

        Anders als bei Cloud-Providern reicht hier eine URL — ein API-Key
        ist nicht noetig. Wir machen hier KEINEN Netzwerk-Roundtrip,
        damit die App nicht jedes Mal beim Start blockiert. Den echten
        Verbindungstest macht ``ping()`` bzw. der erste API-Call.
        """
        return bool(self._get_base_url())

    def ping(self) -> tuple[bool, str]:
        """
        Prueft per HTTP-Request, ob der Ollama-Server erreichbar ist.

        Returns:
            (ok, message). Bei Erfolg enthaelt ``message`` die Ollama-Version.
        """
        url = f"{self._get_base_url()}/api/version"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return True, data.get("version", "unbekannt")
        except urllib.error.URLError as e:
            return False, f"Verbindung fehlgeschlagen: {e.reason}"
        except Exception as e:
            return False, f"Fehler: {e}"

    def list_models(self) -> list[str]:
        """
        Holt die Liste der lokal installierten Modelle vom Server.

        Returns:
            Liste der Modellnamen (z.B. ``["llama3.1", "gemma3:12b"]``).
            Leere Liste bei Fehler.
        """
        url = f"{self._get_base_url()}/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except Exception:
            return []

    # ------------------------------------------------------------------ #
    # Interne HTTP-Hilfsfunktion                                         #
    # ------------------------------------------------------------------ #

    def _chat(self, system_prompt: str, user_prompt: str) -> tuple[Optional[str], Optional[str]]:
        """
        Schickt einen Chat-Request an Ollama.

        Returns:
            (response_text, error_message). Genau eins ist None.
        """
        url = f"{self._get_base_url()}/api/chat"
        payload = {
            "model": self._get_model_id(),
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
        }

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            return None, f"Ollama HTTP {e.code}: {detail or e.reason}"
        except urllib.error.URLError as e:
            return None, (
                f"Keine Verbindung zu Ollama ({self._get_base_url()}). "
                f"Laeuft der Server? Details: {e.reason}"
            )
        except Exception as e:
            return None, f"Ollama-Fehler: {e}"

        message = data.get("message") or {}
        content = message.get("content", "")
        if not content:
            return None, "Ollama hat eine leere Antwort geliefert."
        return content, None

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """
        Entfernt Markdown-Code-Fences, falls das Modell die Antwort
        in ``` eingewickelt hat. Lokale Modelle tun das oft, obwohl der
        Prompt KEIN JSON verlangt.
        """
        s = text.strip()
        if s.startswith("```"):
            # Erste Zeile (z.B. ```json oder ```) entfernen
            s = s.split("\n", 1)[1] if "\n" in s else s[3:]
            if s.endswith("```"):
                s = s[:-3]
            s = s.strip()
        return s

    # ------------------------------------------------------------------ #
    # Pflicht-API                                                        #
    # ------------------------------------------------------------------ #

    def classify_document(
        self,
        text: str,
        available_folders: list[str],
        keywords: list[str] = None,
        detected_date: str = None,
    ) -> LLMResponse:
        if not self.is_available():
            return LLMResponse(
                success=False,
                error_message="Ollama-Provider ist nicht konfiguriert (URL fehlt).",
            )
        if not available_folders:
            return LLMResponse(success=False, error_message="Keine Zielordner verfuegbar.")

        prompt = self._build_classification_prompt(
            text, available_folders, keywords, detected_date
        )
        # Defensiver System-Prompt fuer lokale Modelle: explizit auf Format
        # bestehen, sonst kommen Erklaerungen, Code-Fences etc. mit.
        system_prompt = (
            "Du bist ein Assistent zum Sortieren von Dokumenten. "
            "Antworte AUSSCHLIESSLICH im geforderten Zeilen-Format. "
            "Keine Einleitung, keine Erklaerung, keine Code-Bloecke."
        )

        response_text, error = self._chat(system_prompt, prompt)
        if error:
            return LLMResponse(success=False, error_message=error)

        cleaned = self._strip_code_fences(response_text)
        parsed = self._parse_response(cleaned)

        suggested_folder = parsed.get("folder")
        if suggested_folder and suggested_folder not in available_folders:
            suggested_folder = self._find_similar_folder(suggested_folder, available_folders)

        return LLMResponse(
            success=True,
            folder_suggestion=suggested_folder,
            folder_reason=parsed.get("reason"),
            confidence=parsed.get("confidence", 0.5),
            tokens_used=0,  # Ollama liefert prompt_eval_count/eval_count, fuer Kosten irrelevant
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
        if not self.is_available():
            return LLMResponse(
                success=False,
                error_message="Ollama-Provider ist nicht konfiguriert (URL fehlt).",
            )

        prompt = self._build_filename_prompt(
            text, current_filename, keywords, detected_date, target_folder, file_date
        )
        system_prompt = (
            "Du bist ein Assistent zum Benennen von Dokumenten. "
            "Antworte AUSSCHLIESSLICH im geforderten Zeilen-Format "
            "(jedes Feld mit seinem GROSSBUCHSTABEN-Praefix auf einer eigenen Zeile). "
            "Keine Einleitung, keine Erklaerung, keine Code-Bloecke, kein JSON."
        )

        response_text, error = self._chat(system_prompt, prompt)
        if error:
            return LLMResponse(success=False, error_message=error)

        cleaned = self._strip_code_fences(response_text)
        parsed = self._parse_response(cleaned)

        filename = parsed.get("filename")
        if filename:
            filename = self._sanitize_filename(filename)

        return LLMResponse(
            success=True,
            filename_suggestion=filename,
            filename_reason=parsed.get("reason"),
            confidence=parsed.get("confidence", 0.5),
            tokens_used=0,
            metadata=parsed.get("metadata"),
        )

    # ------------------------------------------------------------------ #
    # Helfer (gleich wie in den anderen Providern)                       #
    # ------------------------------------------------------------------ #

    def _find_similar_folder(
        self, suggested: str, available: list[str]
    ) -> Optional[str]:
        """Findet einen aehnlichen Ordner aus der Liste."""
        suggested_lower = suggested.lower()
        for folder in available:
            if folder.lower() == suggested_lower:
                return folder
        for folder in available:
            if suggested_lower in folder.lower() or folder.lower() in suggested_lower:
                return folder
        return None

    def _sanitize_filename(self, filename: str) -> str:
        """Bereinigt einen Dateinamen."""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, "_")
        replacements = {
            "ä": "ae", "ö": "oe", "ü": "ue",
            "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
            "ß": "ss",
        }
        for old, new in replacements.items():
            filename = filename.replace(old, new)
        filename = filename.replace(" ", "_")
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        if len(filename) > 84:  # 80 + .pdf
            filename = filename[:80] + ".pdf"
        return filename

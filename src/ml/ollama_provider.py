"""
Ollama Provider fuer PDF Sortier Meister

Implementiert die LLM-Schnittstelle fuer einen lokal laufenden
Ollama-Server (https://ollama.com).

Vorteile lokaler Modelle:
- Keine API-Kosten, keine Cloud
- Daten verlassen den Rechner nicht
- Funktioniert offline
- JSON Mode ermoeglicht sehr stabile strukturierte Antworten

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
from typing import Optional, Any

from src.ml.llm_provider import LLMProvider, LLMConfig, LLMResponse


class OllamaProvider(LLMProvider):
    """
    LLM-Provider fuer einen lokal laufenden Ollama-Server.

    Die Verbindung erfolgt ueber die native Ollama HTTP-API (Default: http://localhost:11434).
    Es wird kein API-Key benoetigt; stattdessen wird ueber ``LLMConfig.base_url`` der Server-Endpunkt
    und ueber ``LLMConfig.model`` das Modell konfiguriert.
    """

    DEFAULT_BASE_URL = "http://localhost:11434"
    DEFAULT_MODEL = "llama3.1"

    # Timeout fuer einen einzelnen Request in Sekunden.
    REQUEST_TIMEOUT = 120

    def __init__(self, config: LLMConfig):
        """
        Initialisiert den Ollama Provider.

        Args:
            config: Konfiguration mit Modellname und (optional) base_url
        """
        super().__init__(config)
        # Einmaliger Auto-Start-Versuch pro Provider-Instanz.
        self._autostart_attempted = False
        self._initialize_client()

    def _initialize_client(self):
        """
        Bereitete die Server-URL vor.
        """
        self._client = self._get_base_url()

    def _get_base_url(self) -> str:
        """Liefert die zu verwendende Ollama-Basis-URL ohne Trailing-Slash."""
        url = (self.config.base_url or self.DEFAULT_BASE_URL).strip()
        return url.rstrip("/")

    def _get_model_id(self) -> str:
        """Gibt den Modellnamen zurueck."""
        return self.config.model.strip() if self.config.model else self.DEFAULT_MODEL

    def _headers(self) -> dict[str, str]:
        """HTTP-Header; mit Bearer-Token, wenn ein API-Key konfiguriert ist."""
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def is_available(self) -> bool:
        """Prueft, ob Ollama verfuegbar ist."""
        return bool(self._get_base_url())

    def ping(self) -> tuple[bool, str]:
        """Prueft per HTTP-Request, ob der Ollama-Server erreichbar ist."""
        url = f"{self._get_base_url()}/api/version"
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return True, data.get("version", "unbekannt")
        except urllib.error.URLError as e:
            return False, f"Verbindung fehlgeschlagen: {e.reason}"
        except Exception as e:
            return False, f"Fehler: {e}"

    def list_models(self) -> list[str]:
        """Holt die Liste der lokal installierten Modelle vom Server."""
        url = f"{self._get_base_url()}/api/tags"
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except Exception:
            return []

    # ------------------------------------------------------------------ #
    # Interne HTTP-Hilfsfunktion                                         #
    # ------------------------------------------------------------------ #

    def _chat(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> tuple[Optional[str], Optional[str]]:
        """
        Schickt einen Chat-Request an Ollama.
        """
        result, error = self._do_chat(system_prompt, user_prompt, json_mode=json_mode)
        if result is not None or error is None:
            return result, error

        # Nur bei echten Verbindungsfehlern (URLError) Auto-Start versuchen
        if self._autostart_attempted or not error.startswith("Keine Verbindung"):
            return result, error

        self._autostart_attempted = True
        try:
            from src.ml.ollama_launcher import ensure_running
        except ImportError:
            return result, error

        ok, msg = ensure_running(self._get_base_url())
        if not ok:
            return None, (
                f"Ollama nicht erreichbar und Auto-Start fehlgeschlagen.\n"
                f"{msg}"
            )

        # Server laeuft jetzt - Request wiederholen.
        return self._do_chat(system_prompt, user_prompt, json_mode=json_mode)

    def _do_chat(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> tuple[Optional[str], Optional[str]]:
        """
        Eigentlicher HTTP-Request an /api/chat.
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
        if json_mode:
            payload["format"] = "json"

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers=self._headers(),
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return None, f"Ollama HTTP {e.code}"
        except urllib.error.URLError as e:
            return None, f"Keine Verbindung zu Ollama ({self._get_base_url()}). Details: {e.reason}"
        except Exception as e:
            return None, f"Ollama-Fehler: {e}"

        message = data.get("message") or {}
        content = message.get("content", "")
        if not content:
            return None, "Ollama hat eine leere Antwort geliefert."
        return content, None

    def _strip_code_fences(self, text: str) -> str:
        """Entfernt Markdown-Code-Fences."""
        s = text.strip()
        if s.startswith("```"):
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
            return LLMResponse(success=False, error_message="Ollama-Provider nicht konfiguriert.")
        if not available_folders:
            return LLMResponse(success=False, error_message="Keine Zielordner verfuegbar.")

        prompt = self._build_classification_prompt(text, available_folders, keywords, detected_date)
        system_prompt = "Du bist ein Assistent zum Sortieren von Dokumenten. Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt."

        response_text, error = self._chat(system_prompt, prompt, json_mode=True)
        if error:
            return LLMResponse(success=False, error_message=error)

        cleaned = self._strip_code_fences(response_text)
        parsed, parse_err = self._parse_json_response(cleaned)

        if parse_err:
            return LLMResponse(success=False, error_message=parse_err)

        suggested_folder = parsed.get("folder") if parsed.get("folder") != "NULL" else None

        return LLMResponse(
            success=True,
            folder_suggestion=suggested_folder,
            folder_reason=parsed.get("reason"),
            confidence=float(parsed.get("confidence", 0.5)),
            metadata=parsed.get("metadata")
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
            return LLMResponse(success=False, error_message="Ollama-Provider nicht konfiguriert.")

        prompt = self._build_filename_prompt(text, current_filename, keywords, detected_date, target_folder, file_date)
        system_prompt = "Du bist ein Assistent zum Benennen von Dokumenten. Antworte AUSSCHLIESSLICH mit einem validem JSON-Objekt."

        response_text, error = self._chat(system_prompt, prompt, json_mode=True)
        if error:
            return LLMResponse(success=False, error_message=error)

        cleaned = self._strip_code_fences(response_text)
        parsed, parse_err = self._parse_json_response(cleaned)

        if parse_err:
            return LLMResponse(success=False, error_message=parse_err)

        filename = parsed.get("filename") if parsed.get("filename") != "NULL" else None

        return LLMResponse(
            success=True,
            filename_suggestion=filename,
            filename_reason=parsed.get("reason"),
            confidence=float(parsed.get("confidence", 0.5)),
            metadata=parsed.get("metadata")
        )

    # ------------------------------------------------------------------ #
    # Helfer                                                             #
    # ------------------------------------------------------------------ #

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
        return filename

    def _find_similar_folder(self, suggested: str, available: list[str]) -> Optional[str]:
        # Placeholder
        return None

    # ------------------------------------------------------------------ #
    # RAG-Chat (Phase 19, M1)                                            #
    # ------------------------------------------------------------------ #

    def answer_with_context(
        self,
        system_prompt: str,
        context_docs: list[dict],
        user_question: str,
        max_tokens: int = 1000,
    ) -> str:
        """
        Beantwortet eine Nutzerfrage im Kontext der uebergebenen Dokumente.

        Sendet einen Chat-Request an ``/api/chat`` mit System- und
        User-Message. ``format:json`` ist bewusst deaktiviert, damit
        das Modell ``[N]``-Citation-Marker im natuerlichen Text
        ausgeben kann. Die Verarbeitung der Marker uebernimmt der
        ``CitationParser`` in M3.

        Timeout: ``REQUEST_TIMEOUT`` (120s).
        """
        if not self.is_available():
            return ""

        from src.rag.prompts import build_context_block, build_user_prompt

        context_block = build_context_block(context_docs)
        user_prompt = build_user_prompt(user_question, context_block=context_block)

        payload = {
            "model": self._get_model_id(),
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "temperature": self.config.temperature,
                "num_predict": max_tokens,
            },
        }
        # KEIN format:json - wir wollen natuerliche Sprache mit [N]-Markern.

        body = json.dumps(payload).encode("utf-8")
        url = f"{self._get_base_url()}/api/chat"
        req = urllib.request.Request(
            url,
            data=body,
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            return f"[Ollama nicht erreichbar: {e.reason}]"
        except Exception as e:
            return f"[Ollama-Fehler: {e}]"

        message = data.get("message") or {}
        return message.get("content", "") or ""

class OllamaCloudProvider(OllamaProvider):
    """
    Ollama-Modelle in der Cloud (https://ollama.com) - gleiche API wie der
    lokale Server, aber mit API-Key (Bearer-Token) und ohne eigene Hardware.

    Gedacht fuer Rechner ohne dedizierte Grafikkarte: Dokumentinhalte werden
    dabei an ollama.com uebertragen, der Provider zaehlt deshalb als
    Cloud-Provider (Einwilligung noetig).
    """

    DEFAULT_BASE_URL = "https://ollama.com"
    DEFAULT_MODEL = "gpt-oss:120b"

    # Bekannte Cloud-Modelle (Stand 2026); die Liste dient als Fallback,
    # falls /api/tags auf ollama.com nicht erreichbar ist.
    CLOUD_MODELS = [
        "gpt-oss:120b",
        "gpt-oss:20b",
        "qwen3-coder:480b",
        "deepseek-v3.1:671b",
        "kimi-k2:1t",
        "glm-4.6",
        "minimax-m2",
    ]

    def _get_base_url(self) -> str:
        # Eine in der Config verbliebene lokale URL (Wechsel von Ollama lokal)
        # darf hier nicht greifen.
        return self.DEFAULT_BASE_URL

    def is_available(self) -> bool:
        return bool(self.config.api_key)

    def list_models(self) -> list[str]:
        models = super().list_models()
        return models or list(self.CLOUD_MODELS)

    def _chat(self, system_prompt: str, user_prompt: str, json_mode: bool = False):
        # Kein Auto-Start eines lokalen Servers bei Verbindungsfehlern.
        return self._do_chat(system_prompt, user_prompt, json_mode=json_mode)

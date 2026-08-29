"""
OpenAI API Provider für PDF Sortier Meister

Implementiert die LLM-Schnittstelle für OpenAI's GPT API.

MIT License - Copyright (c) 2026
"""

import json
import urllib.error
import urllib.request
import re
from typing import Optional

from src.ml.llm_provider import LLMProvider, LLMConfig, LLMResponse


class OpenAIProvider(LLMProvider):
    """
    LLM-Provider für OpenAI's GPT API.

    Unterstützt GPT-3.5 und GPT-4 Modelle.
    """

    # Verfügbare OpenAI Modelle (Stand: März 2026)
    MODELS = {
        "gpt-4o-mini": "gpt-4o-mini",
        "gpt-4o": "gpt-4o",
        "gpt-4.1-nano": "gpt-4.1-nano",
        "gpt-4.1-mini": "gpt-4.1-mini",
        "gpt-4.1": "gpt-4.1",
        "o3-mini": "o3-mini",
        "o3": "o3",
        "o4-mini": "o4-mini",
    }

    DEFAULT_MODEL = "gpt-4.1-nano"  # Günstigstes aktuelles Modell

    # Anzeigename in Fehlermeldungen (Subklassen ueberschreiben)
    API_NAME = "OpenAI"

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
            print(f"Fehler bei {self.API_NAME}-Initialisierung: {e}")
            self._client = None

    def is_available(self) -> bool:
        """Prüft, ob OpenAI verfügbar ist."""
        return self._client is not None and self.config.api_key

    def _get_model_id(self) -> str:
        """Gibt die vollständige Modell-ID zurück."""
        model = self.config.model.lower()
        if model in self.MODELS:
            return self.MODELS[model]
        # Falls vollständige ID angegeben (gpt-*, o1-*, o3-*, o4-*, chatgpt-*)
        if any(model.startswith(p) for p in ("gpt", "o1", "o3", "o4", "chatgpt")):
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
                error_message=f"{self.API_NAME} API nicht verfügbar. API-Key prüfen."
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
            response = self._create_chat_completion(
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
                error_message=f"Keine Verbindung zur {self.API_NAME} API."
            )
        except self._openai.RateLimitError:
            return LLMResponse(
                success=False,
                error_message=f"{self.API_NAME} API Rate-Limit erreicht. Bitte später versuchen."
            )
        except self._openai.AuthenticationError:
            return LLMResponse(
                success=False,
                error_message=f"Ungültiger {self.API_NAME} API-Key."
            )
        except Exception as e:
            return LLMResponse(
                success=False,
                error_message=f"{self.API_NAME} API Fehler: {str(e)}"
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
        Schlägt einen Dateinamen mit OpenAI vor.

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
                error_message=f"{self.API_NAME} API nicht verfügbar. API-Key prüfen."
            )

        prompt = self._build_filename_prompt(
            text, current_filename, keywords, detected_date, target_folder, file_date
        )

        try:
            response = self._create_chat_completion(
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
                error_message=f"{self.API_NAME} API Fehler: {str(e)}"
            )

    # Reasoning-Modelle bei OpenAI direkt: o1/o3/o4-mini, gpt-5-Familie.
    # Fuer die kurze Extraktionsaufgabe reicht minimales Nachdenken; das
    # spart Zeit und Tokens. Klassische Modelle (gpt-4o, gpt-4.1) kennen den
    # Parameter nicht - sie bekommen ihn gar nicht erst.
    _REASONING_MODEL_RE = re.compile(r"^(o\d|gpt-5)", re.IGNORECASE)

    def _extra_request_kwargs(self) -> dict:
        """Zusaetzliche Parameter fuer chat.completions.create."""
        if self._REASONING_MODEL_RE.match(self._get_model_id() or ""):
            return {"reasoning_effort": "minimal"}
        return {}

    # Nach einer Ablehnung (HTTP 400) werden Extras fuer diese Instanz nicht
    # mehr mitgeschickt - sonst kostet jeder Aufruf einen Fehlversuch extra.
    _extras_rejected = False

    def _create_chat_completion(self, **kwargs):
        """Ruft die Chat-API auf; provider-spezifische Extras mit Rueckfall.

        Lehnt das Modell einen Zusatzparameter ab (HTTP 400), wird der Aufruf
        ohne die Extras wiederholt und die Ablehnung gemerkt.
        """
        extras = {} if self._extras_rejected else self._extra_request_kwargs()
        if not extras:
            return self._client.chat.completions.create(**kwargs)
        try:
            return self._client.chat.completions.create(**kwargs, **extras)
        except Exception as e:  # noqa: BLE001 - nur 400er auf Extras zurueckfallen
            status = getattr(e, "status_code", None)
            if status == 400 or "400" in str(e):
                self._extras_rejected = True
                return self._client.chat.completions.create(**kwargs)
            raise

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

    # ------------------------------------------------------------------ #
    # RAG-Chat (Phase 19, M1)                                            #
    # ------------------------------------------------------------------ #

    CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
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
            return None, f"{self.API_NAME} HTTP {e.code}: {detail}"
        except urllib.error.URLError as e:
            return None, f"Keine Verbindung zur {self.API_NAME} API: {e.reason}"
        except Exception as e:
            return None, f"{self.API_NAME}-Fehler: {e}"

    def answer_with_context(
        self,
        system_prompt: str,
        context_docs: list[dict],
        user_question: str,
        max_tokens: int = 1000,
    ) -> str:
        """
        Beantwortet eine Nutzerfrage im Kontext der uebergebenen Dokumente.

        Verwendet die OpenAI ``chat/completions`` API mit System- und
        User-Message. Es wird bewusst ``urllib`` benutzt (kein openai
        SDK noetig), um keine zusaetzliche Dependency einzufuehren.
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
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }
        data, error = self._http_post_json(self.CHAT_COMPLETIONS_URL, body, headers)
        if error or not data:
            return f"[{self.API_NAME}-Fehler: {error}]"

        choices = data.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        return message.get("content", "") or ""

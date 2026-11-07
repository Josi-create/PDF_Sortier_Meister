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

GPL-3.0-or-later - Copyright (c) 2026
"""

import json
import urllib.error
import urllib.request
from typing import Optional, Any

from src.ml.llm_provider import (
    LLMProvider,
    LLMConfig,
    LLMResponse,
    Werkzeug,
    WerkzeugAufruf,
    WerkzeugAntwort,
)
from src.ml.ollama_launcher import http_error_text


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
        # Werkzeuge im Chat (Issue #166/#167): Hat der Server Werkzeuge
        # abgelehnt (HTTP 400 "does not support tools"), bleibt das fuer diese
        # Instanz gemerkt. Das /api/show-Ergebnis wird einmal je Instanz
        # gecacht (None = noch nicht abgefragt); kein Netzaufruf hier.
        self._werkzeuge_abgelehnt = False
        self._werkzeuge_laut_server: Optional[bool] = None
        # gpt-oss kennt nur die Denkstufen low/medium/high; think=false liefert
        # dort leeren oder mit Denktext vermischten Inhalt. Direkt "low" senden
        # spart den vergeblichen ersten Versuch.
        if self._is_gpt_oss():
            self._think_mode = self.THINK_FALLBACK
        self._initialize_client()

    def _is_gpt_oss(self) -> bool:
        """Erkennt gpt-oss-Modelle am Namen (auch eigene Varianten wie gpt-oss-64k)."""
        name = self._get_model_id().lower().replace("_", "-")
        return "gpt-oss" in name or "gptoss" in name

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
        # Denk-Modelle (qwen3, deepseek-r1, gemma4, ...) sollen fuer die kurze
        # Extraktionsaufgabe nicht "nachdenken": schneller, und das Budget
        # (num_predict) geht nicht im Denkteil verloren. Zwei Rueckfaelle,
        # jeweils fuer diese Instanz gemerkt:
        # - HTTP 400: Server/Modell kennt das Feld nicht -> ohne wiederholen.
        # - HTTP 200 mit leerem Inhalt (oder im JSON-Modus ohne JSON-Objekt):
        #   Modelle wie gpt-oss koennen das Denken nicht abschalten (nur
        #   low/medium/high) und liefern bei think=false nichts oder Denktext
        #   im Inhalt -> mit think="low" wiederholen.
        if self._think_mode is not None:
            payload["think"] = self._think_mode

        data, error = self._post_chat(url, payload)
        if error and "HTTP 400" in error and "think" in payload:
            self._think_mode = None
            payload.pop("think", None)
            data, error = self._post_chat(url, payload)
        if error:
            return None, error

        content = self._extract_content(data)
        unusable = not content or (json_mode and not self._contains_json_object(content))
        if unusable and payload.get("think") is False:
            self._think_mode = self.THINK_FALLBACK
            payload["think"] = self.THINK_FALLBACK
            data, error = self._post_chat(url, payload)
            if error:
                return None, error
            content = self._extract_content(data)
        if not content:
            return None, "Ollama hat eine leere Antwort geliefert."
        return content, None

    # Aktueller Wert fuer das "think"-Feld: False = aus, "low" = minimal,
    # None = Feld nicht senden (vom Server abgelehnt).
    _think_mode: Any = False
    THINK_FALLBACK = "low"

    @staticmethod
    def _extract_content(data: dict) -> str:
        """Liest message.content aus einer /api/chat-Antwort."""
        message = data.get("message") or {}
        return message.get("content", "") or ""

    @staticmethod
    def _contains_json_object(text: str) -> bool:
        """True, wenn im Text ein parsebares JSON-Objekt steckt."""
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return False
        try:
            return isinstance(json.loads(text[start:end + 1]), dict)
        except ValueError:
            return False

    def _post_chat(self, url: str, payload: dict) -> tuple[Optional[dict], Optional[str]]:
        """POST an /api/chat; liefert (JSON-Antwort, Fehlertext)."""
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8")), None
        except urllib.error.HTTPError as e:
            return None, http_error_text(e)
        except urllib.error.URLError as e:
            return None, f"Keine Verbindung zu Ollama ({self._get_base_url()}). Details: {e.reason}"
        except Exception as e:
            return None, f"Ollama-Fehler: {e}"

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
        parsed, parse_err = self._parse_json_response(cleaned, document_text=text)

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
        examples: list[str] | None = None,
        source_folder: str | None = None,
        similar_info: str = "",
    ) -> LLMResponse:
        if not self.is_available():
            return LLMResponse(success=False, error_message="Ollama-Provider nicht konfiguriert.")

        prompt = self._build_filename_prompt(
            text, current_filename, keywords, detected_date, target_folder, file_date,
            examples=examples, source_folder=source_folder, similar_info=similar_info,
        )
        system_prompt = "Du bist ein Assistent zum Benennen von Dokumenten. Antworte AUSSCHLIESSLICH mit einem validem JSON-Objekt."

        response_text, error = self._chat(system_prompt, prompt, json_mode=True)
        if error:
            return LLMResponse(success=False, error_message=error)

        cleaned = self._strip_code_fences(response_text)
        parsed, parse_err = self._parse_json_response(cleaned, document_text=text)

        if parse_err:
            return LLMResponse(success=False, error_message=parse_err)

        filename = parsed.get("filename") if parsed.get("filename") != "NULL" else None
        if filename:
            filename = self._sanitize_filename(filename)

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
        """Bereinigt einen Dateinamen (zentral in src.utils.filename_sanitizer)."""
        from src.utils.filename_sanitizer import sanitize_filename
        return sanitize_filename(filename)

    def _find_similar_folder(self, suggested: str, available: list[str]) -> Optional[str]:
        # Placeholder
        return None

    # ------------------------------------------------------------------ #
    # RAG-Chat (Phase 19, M1)                                            #
    # ------------------------------------------------------------------ #

    def describe_images(self, images: list[bytes], prompt: str, max_tokens: int = 3000) -> str:
        """Bilder (JPEG) mit Anweisung an ``/api/chat`` schicken (``images`` als Base64; Issue #47).

        Braucht ein Vision-Modell (llava, qwen2.5vl, llama3.2-vision, ...).
        Gilt auch fuer Ollama Cloud.
        """
        import base64

        if not self.is_available():
            raise RuntimeError("Ollama ist nicht eingerichtet oder nicht erreichbar.")
        payload = {
            "model": self._get_model_id(),
            "stream": False,
            "messages": [{
                "role": "user",
                "content": prompt,
                "images": [base64.b64encode(img).decode("ascii") for img in images],
            }],
            "options": {"temperature": self.config.temperature, "num_predict": max_tokens},
        }
        data, error = self._post_chat(f"{self._get_base_url()}/api/chat", payload)
        if error or not data:
            raise RuntimeError(error or "Leere Antwort von Ollama.")
        return (data.get("message") or {}).get("content", "") or ""

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

    # ------------------------------------------------------------------ #
    # Werkzeuge im Chat (Issue #166/#167, Phase 2)                       #
    # ------------------------------------------------------------------ #

    # Timeout fuer die Faehigkeitsabfrage (/api/show) in Sekunden.
    SHOW_TIMEOUT = 5
    # Denkstufe von gpt-oss in der Werkzeug-Schleife: "low" reicht fuer die kurze
    # Sortieraufgabe, beim Chat entscheidet das Nachdenken darueber, ob das Modell
    # die Kennungs-Treffer richtig verknuepft statt einer Wortuebereinstimmung
    # zu folgen (Probelauf 2026-11-07). Andere Modelle behalten _think_mode.
    WERKZEUG_THINK = "medium"

    # Mindestbudget (num_predict) fuer Denkmodelle in der Werkzeug-Schleife: das
    # Nachdenken zaehlt bei Ollama zu den erzeugten Token; mit 1000 blieb bei
    # gpt-oss (medium) fuer Antwort und Werkzeugaufruf nichts uebrig (leere
    # Antwort, Probelauf 2026-11-07).
    WERKZEUG_NUM_PREDICT_MIN = 4096

    def _werkzeug_think(self) -> Any:
        """Wert des ``think``-Felds fuer ``chat_mit_werkzeugen``; None = nicht senden."""
        if self._think_mode is None:
            return None
        if self._is_gpt_oss():
            return self.WERKZEUG_THINK
        return self._think_mode

    def _werkzeug_num_predict(self, max_tokens: int) -> int:
        """Token-Budget eines Schritts: fuer Denkmodelle (think = Stufe) mindestens ``WERKZEUG_NUM_PREDICT_MIN``."""
        try:
            budget = int(max_tokens)
        except (TypeError, ValueError):
            budget = self.WERKZEUG_NUM_PREDICT_MIN
        if isinstance(self._werkzeug_think(), str):
            return max(budget, self.WERKZEUG_NUM_PREDICT_MIN)
        return budget

    def unterstuetzt_werkzeuge(self) -> bool:
        """True, ausser der Server hat Werkzeuge abgelehnt oder ``/api/show``
        nennt fuer das Modell ``capabilities`` ohne ``"tools"``.

        Die Abfrage laeuft beim ersten Aufruf (nicht im Konstruktor) und wird
        je Instanz gecacht; Netzfehler gelten als "ja" - den Beweis liefert
        dann der erste Chat-Schritt selbst (HTTP 400 -> Ablehnung gemerkt).
        """
        if self._werkzeuge_abgelehnt:
            return False
        if self._werkzeuge_laut_server is None:
            self._werkzeuge_laut_server = self._modell_nennt_werkzeuge()
        return self._werkzeuge_laut_server

    def _modell_nennt_werkzeuge(self) -> bool:
        """Fragt ``POST /api/show`` nach den Faehigkeiten des Modells.

        False nur, wenn der Server eine Liste ``capabilities`` ohne ``"tools"``
        liefert. Netzfehler, HTTP-Fehler, fehlendes Feld (aeltere Server) oder
        unlesbare Antwort -> True.
        """
        url = f"{self._get_base_url()}/api/show"
        body = json.dumps({"model": self._get_model_id()}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.SHOW_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return True
        faehigkeiten = data.get("capabilities") if isinstance(data, dict) else None
        if not isinstance(faehigkeiten, list):
            return True
        return "tools" in faehigkeiten

    def chat_mit_werkzeugen(
        self,
        nachrichten: list[dict],
        werkzeuge: list[Werkzeug],
        max_tokens: int = 1000,
    ) -> WerkzeugAntwort:
        """Ein Schritt der Werkzeug-Schleife ueber ``/api/chat`` (stream=false).

        Die provider-neutralen Nachrichten (siehe Modul-Kommentar in
        :mod:`src.ml.llm_provider`) werden ins Ollama-Format uebersetzt,
        ``werkzeuge`` als ``tools`` mitgeschickt (nur wenn nicht leer).
        Denkmodus wie in :meth:`_do_chat` (``think`` samt HTTP-400-Rueckfall
        und Wiederholung mit ``"low"`` bei leerer Antwort). Fehler kommen als
        ``fehler``-Text zurueck, nie als Exception; wie
        :meth:`answer_with_context` ohne Auto-Start des Servers.
        """
        if not self.is_available():
            return WerkzeugAntwort(fehler="Ollama-Provider nicht konfiguriert.")
        if werkzeuge and self._werkzeuge_abgelehnt:
            return WerkzeugAntwort(fehler=self._werkzeuge_fehlertext("bereits abgelehnt"))

        url = f"{self._get_base_url()}/api/chat"
        payload = {
            "model": self._get_model_id(),
            "stream": False,
            "messages": [self._nachricht_fuer_ollama(n) for n in nachrichten],
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self._werkzeug_num_predict(max_tokens),
            },
        }
        if werkzeuge:
            payload["tools"] = [self._werkzeug_fuer_ollama(w) for w in werkzeuge]
        think = self._werkzeug_think()
        if think is not None:
            payload["think"] = think

        data, error = self._post_chat(url, payload)
        # HTTP 400 wegen "think" (Server/Modell kennt das Feld nicht): ohne
        # wiederholen und merken - aber nicht, wenn es um die Werkzeuge geht.
        ablehnung = bool(werkzeuge) and bool(error) and self._ist_werkzeug_ablehnung(error)
        if error and "HTTP 400" in error and "think" in payload and not ablehnung:
            self._think_mode = None
            payload.pop("think", None)
            data, error = self._post_chat(url, payload)
            ablehnung = bool(werkzeuge) and bool(error) and self._ist_werkzeug_ablehnung(error)
        if error:
            # Nur gemerkt, wenn wirklich Werkzeuge gesendet wurden (ohne "tools"
            # kann ein 400 nichts ueber die Werkzeugunterstuetzung sagen)
            if ablehnung:
                self._werkzeuge_abgelehnt = True
                return WerkzeugAntwort(fehler=self._werkzeuge_fehlertext(error))
            return WerkzeugAntwort(fehler=error)

        antwort = self._werkzeug_antwort_aus(data)
        # Wie in _do_chat: think=false liefert bei gpt-oss & Co. nichts ->
        # einmal mit "low" wiederholen und das fuer die Instanz merken.
        if not antwort.text and not antwort.aufrufe and payload.get("think") is False:
            self._think_mode = self.THINK_FALLBACK
            payload["think"] = self.THINK_FALLBACK
            data, error = self._post_chat(url, payload)
            if error:
                return WerkzeugAntwort(fehler=error)
            antwort = self._werkzeug_antwort_aus(data)
        if not antwort.text and not antwort.aufrufe:
            antwort.fehler = "Ollama hat eine leere Antwort geliefert."
        return antwort

    @staticmethod
    def _ist_werkzeug_ablehnung(error: str) -> bool:
        """HTTP 400 ``... does not support tools`` (nicht jedes 400, in dem "tool" vorkommt:
        Ollama nennt im Fehlertext auch Modellnamen wie ``llama3-groq-tool-use``)."""
        text = (error or "").lower()
        return "http 400" in text and "tool" in text and ("not support" in text or "unsupported" in text)

    def _werkzeuge_fehlertext(self, grund: str) -> str:
        """Fehlertext mit dem Wort "Werkzeuge" (Signal fuer den Controller)."""
        return f"Das Modell '{self._get_model_id()}' unterstützt keine Werkzeuge ({grund})."

    @staticmethod
    def _werkzeug_fuer_ollama(werkzeug: Werkzeug) -> dict:
        """Werkzeugbeschreibung im Ollama-/OpenAI-Format ("tools"-Eintrag)."""
        return {
            "type": "function",
            "function": {
                "name": werkzeug.name,
                "description": werkzeug.beschreibung,
                "parameters": werkzeug.parameter,
            },
        }

    @staticmethod
    def _nachricht_fuer_ollama(nachricht: dict) -> dict:
        """Provider-neutrale Nachricht -> Ollama-Nachricht.

        system/user 1:1; assistant mit ``roh`` -> die fruehere Ollama-Nachricht
        unveraendert, sonst aus ``content`` + ``aufrufe`` nachgebaut; tool ->
        ``{"role": "tool", "content", "tool_name"}`` (``tool_name`` ab Ollama
        0.4, aeltere Server ignorieren das Feld).
        """
        rolle = nachricht.get("role") or "user"
        inhalt = nachricht.get("content") or ""
        if rolle == "assistant":
            roh = nachricht.get("roh")
            if isinstance(roh, dict):
                return roh
            nachgebaut: dict = {"role": "assistant", "content": inhalt}
            tool_calls = [
                {"function": {"name": aufruf.name, "arguments": aufruf.argumente or {}}}
                for aufruf in (nachricht.get("aufrufe") or [])
            ]
            if tool_calls:
                nachgebaut["tool_calls"] = tool_calls
            return nachgebaut
        if rolle == "tool":
            return {"role": "tool", "content": inhalt, "tool_name": nachricht.get("name") or ""}
        return {"role": rolle, "content": inhalt}

    @staticmethod
    def _werkzeug_antwort_aus(data: Optional[dict]) -> WerkzeugAntwort:
        """Baut die :class:`WerkzeugAntwort` aus einer /api/chat-Antwort.

        ``roh`` ist die Ollama-Nachricht (mit ``role: assistant``), damit sie
        in der naechsten Runde unveraendert zurueckgeht (inkl. ``thinking``,
        das gpt-oss bei Werkzeugaufrufen wieder sehen will).
        """
        message = (data or {}).get("message") if isinstance(data, dict) else None
        if not isinstance(message, dict):
            message = {}
        aufrufe: list[WerkzeugAufruf] = []
        for n, tc in enumerate(message.get("tool_calls") or [], start=1):
            if not isinstance(tc, dict):
                continue
            funktion = tc.get("function")
            if not isinstance(funktion, dict):
                funktion = {}
            name = str(funktion.get("name") or "").strip()
            if not name:
                continue  # Eintrag ohne Funktionsnamen: kein Aufruf (verschenkter Schritt)
            aufrufe.append(WerkzeugAufruf(
                name=name,
                argumente=OllamaProvider._argumente_als_dict(funktion.get("arguments")),
                id=str(tc.get("id") or f"aufruf_{n}"),
            ))
        roh = dict(message)
        roh["role"] = "assistant"
        return WerkzeugAntwort(text=message.get("content") or "", aufrufe=aufrufe, roh=roh)

    @staticmethod
    def _argumente_als_dict(argumente: Any) -> dict:
        """Argumente eines Aufrufs als Dict; JSON-String wird geparst, Unparsbares -> {}."""
        if isinstance(argumente, dict):
            return argumente
        if isinstance(argumente, str) and argumente.strip():
            try:
                geparst = json.loads(argumente)
            except ValueError:
                return {}
            return geparst if isinstance(geparst, dict) else {}
        return {}


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

    # Bekannte Cloud-Modelle (Stand 11/2026, aus https://ollama.com/api/tags);
    # die Liste dient als Fallback, falls /api/tags nicht erreichbar ist.
    CLOUD_MODELS = [
        "gpt-oss:120b",
        "gpt-oss:20b",
        "gemma4:31b",
        "deepseek-v4.1-flash",
        "kimi-k3",
        "glm-5.3",
        "minimax-m3",
        "mistral-large-4",
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

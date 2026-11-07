"""
Claude API Provider für PDF Sortier Meister

Implementiert die LLM-Schnittstelle für Anthropic's Claude API.

GPL-3.0-or-later - Copyright (c) 2026
"""

import json
import urllib.error
import urllib.request
from typing import Optional

from src.ml.llm_provider import (
    LLMProvider,
    LLMConfig,
    LLMResponse,
    Werkzeug,
    WerkzeugAufruf,
    WerkzeugAntwort,
)


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
        # Issue #166/#167: merkt sich, wenn die API Werkzeuge mit HTTP 400
        # abgelehnt hat - danach laeuft der Chat ohne Werkzeuge weiter.
        self._werkzeuge_abgelehnt = False
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

            response_text = message.content[0].text if message.content else ""
            problem = self._check_response_text(
                response_text, getattr(message, "stop_reason", None)
            )
            if problem:
                return LLMResponse(success=False, error_message=problem)
            parsed = self._parse_response(response_text, document_text=text)
            if parsed.get("error"):
                return LLMResponse(
                    success=False,
                    error_message=f"KI-Antwort nicht lesbar: {parsed['error']}",
                )

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
        examples: list[str] | None = None,
        source_folder: str | None = None,
        similar_info: str = "",
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
            text, current_filename, keywords, detected_date, target_folder, file_date,
            examples=examples, source_folder=source_folder, similar_info=similar_info,
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

            response_text = message.content[0].text if message.content else ""
            problem = self._check_response_text(
                response_text, getattr(message, "stop_reason", None)
            )
            if problem:
                return LLMResponse(success=False, error_message=problem)
            parsed = self._parse_response(response_text, document_text=text)
            if parsed.get("error"):
                return LLMResponse(
                    success=False,
                    error_message=f"KI-Antwort nicht lesbar: {parsed['error']}",
                )

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
        """Bereinigt einen Dateinamen (zentral in src.utils.filename_sanitizer)."""
        from src.utils.filename_sanitizer import sanitize_filename
        return sanitize_filename(filename)

    # ------------------------------------------------------------------ #
    # RAG-Chat (Phase 19, M1)                                            #
    # ------------------------------------------------------------------ #

    # Anthropic Messages API URL (konfigurierbar fuer Proxies)
    MESSAGES_URL = "https://api.anthropic.com/v1/messages"
    # Aktuelle API-Version (Stand 2026)
    ANTHROPIC_VERSION = "2023-06-01"

    def _api_headers(self) -> dict:
        """HTTP-Header fuer die Messages-API (Key, API-Version, JSON)."""
        return {
            "Content-Type": "application/json",
            "x-api-key": self.config.api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
        }

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
        data, error = self._http_post_json(self.MESSAGES_URL, body, self._api_headers())
        if error or not data:
            return f"[Claude-Fehler: {error}]"

        content = data.get("content") or []
        # Antwort ist eine Liste von Bloecken; wir suchen den ersten text-Block.
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "") or ""
        return ""

    # ------------------------------------------------------------------ #
    # Werkzeuge im Chat (Issue #166/#167, Phase 2)                       #
    #                                                                    #
    # Drahtformat der Messages-API:                                      #
    #   Anfrage:  "tools": [{"name", "description", "input_schema"}]      #
    #   Antwort:  "content": [{"type": "text", "text"},                   #
    #                         {"type": "tool_use", "id", "name", "input"}]#
    #             "stop_reason": "tool_use"                               #
    #   Ergebnis: EINE user-Nachricht mit                                 #
    #             [{"type": "tool_result", "tool_use_id", "content"}]      #
    # ------------------------------------------------------------------ #

    def unterstuetzt_werkzeuge(self) -> bool:
        """Claude kann Werkzeuge - bis die API sie einmal mit HTTP 400 ablehnt."""
        return not self._werkzeuge_abgelehnt

    @staticmethod
    def _werkzeuge_fuer_api(werkzeuge: list[Werkzeug]) -> list[dict]:
        """Uebersetzt :class:`Werkzeug` in das ``tools``-Feld der Messages-API."""
        tools = []
        for w in werkzeuge:
            schema = w.parameter if isinstance(w.parameter, dict) and w.parameter else None
            tools.append({
                "name": w.name,
                "description": w.beschreibung,
                "input_schema": schema or {"type": "object", "properties": {}},
            })
        return tools

    @staticmethod
    def _aufruf_feld(aufruf, feld: str, standard=None):
        """Liest ein Feld aus einem :class:`WerkzeugAufruf` oder gleichnamigen Dict."""
        if isinstance(aufruf, dict):
            return aufruf.get(feld, standard)
        return getattr(aufruf, feld, standard)

    def _assistent_bloecke(self, nachricht: dict) -> list[dict]:
        """Inhaltsbloecke einer Assistentennachricht fuer die API.

        Liegt ``roh`` (die content-Liste der frueheren Antwort) vor, geht sie
        unveraendert zurueck. Sonst wird sie aus ``content`` und ``aufrufe``
        nachgebaut; leere Textbloecke werden weggelassen.
        """
        roh = nachricht.get("roh")
        if isinstance(roh, list) and roh:
            return roh
        bloecke: list[dict] = []
        text = nachricht.get("content") or ""
        if isinstance(text, str) and text.strip():
            bloecke.append({"type": "text", "text": text})
        for nr, aufruf in enumerate(nachricht.get("aufrufe") or [], start=1):
            argumente = self._aufruf_feld(aufruf, "argumente") or {}
            if not isinstance(argumente, dict):
                argumente = {}
            bloecke.append({
                "type": "tool_use",
                "id": self._aufruf_feld(aufruf, "id") or f"aufruf_{nr}",
                "name": self._aufruf_feld(aufruf, "name") or "",
                "input": argumente,
            })
        return bloecke

    def _nachrichten_fuer_api(self, nachrichten: list[dict]) -> tuple[str, list[dict]]:
        """Provider-neutrale Nachrichten -> (system-Text, ``messages``-Liste).

        system-Nachrichten wandern in den separaten ``system``-Parameter.
        Alle ``tool``-Nachrichten, die auf dieselbe Assistentenrunde folgen,
        werden in EINER user-Nachricht mit ``tool_result``-Bloecken gebuendelt
        (Reihenfolge bleibt erhalten). Fehlt einer tool-Nachricht die
        ``aufruf_id``, wird die Id des gleichrangigen ``tool_use``-Blocks der
        vorangehenden Assistentennachricht genommen.
        """
        system_teile: list[str] = []
        messages: list[dict] = []
        offene_ids: list[str] = []  # tool_use-Ids der letzten Assistentenrunde
        for nachricht in nachrichten:
            rolle = nachricht.get("role")
            if rolle == "system":
                if nachricht.get("content"):
                    system_teile.append(str(nachricht["content"]))
            elif rolle == "user":
                messages.append({"role": "user", "content": nachricht.get("content") or ""})
                offene_ids = []
            elif rolle == "assistant":
                bloecke = self._assistent_bloecke(nachricht)
                if not bloecke:
                    continue  # eine leere Assistentennachricht lehnt die API ab
                messages.append({"role": "assistant", "content": bloecke})
                offene_ids = [
                    str(b.get("id") or "") for b in bloecke
                    if isinstance(b, dict) and b.get("type") == "tool_use"
                ]
            elif rolle == "tool":
                letzte = messages[-1] if messages else None
                buendel = (
                    letzte["content"]
                    if letzte and letzte["role"] == "user" and isinstance(letzte["content"], list)
                    else None
                )
                if buendel is None:
                    buendel = []
                    messages.append({"role": "user", "content": buendel})
                aufruf_id = str(nachricht.get("aufruf_id") or "")
                if not aufruf_id and len(buendel) < len(offene_ids):
                    aufruf_id = offene_ids[len(buendel)]
                ergebnis = {"type": "tool_result", "tool_use_id": aufruf_id}
                inhalt = nachricht.get("content")
                if inhalt:
                    ergebnis["content"] = str(inhalt)
                buendel.append(ergebnis)
        return "\n\n".join(system_teile), messages

    # Zuletzt gesendete Werkzeugdefinitionen (je Instanz neu zugewiesen, nie
    # veraendert): fuer den letzten Schritt ohne neue Werkzeuge, siehe unten.
    _letzte_werkzeuge: list = []

    @staticmethod
    def _hat_werkzeugbloecke(messages: list[dict]) -> bool:
        """True, wenn im Verlauf tool_use- oder tool_result-Bloecke stehen."""
        for m in messages or ():
            inhalt = m.get("content") if isinstance(m, dict) else None
            if not isinstance(inhalt, list):
                continue
            for block in inhalt:
                if isinstance(block, dict) and block.get("type") in ("tool_use", "tool_result"):
                    return True
        return False

    @staticmethod
    def _platzhalter_werkzeuge(messages: list[dict]) -> list[dict]:
        """Minimale Definitionen fuer die im Verlauf benutzten Werkzeugnamen."""
        namen: list[str] = []
        for m in messages or ():
            inhalt = m.get("content") if isinstance(m, dict) else None
            if not isinstance(inhalt, list):
                continue
            for block in inhalt:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = str(block.get("name") or "").strip()
                    if name and name not in namen:
                        namen.append(name)
        return [{
            "name": name,
            "description": "Werkzeug aus dem bisherigen Verlauf (nicht mehr aufrufen).",
            "input_schema": {"type": "object", "properties": {}},
        } for name in namen] or [{
            "name": "verlauf",
            "description": "Werkzeug aus dem bisherigen Verlauf (nicht mehr aufrufen).",
            "input_schema": {"type": "object", "properties": {}},
        }]

    def chat_mit_werkzeugen(
        self,
        nachrichten: list[dict],
        werkzeuge: list[Werkzeug],
        max_tokens: int = 1000,
    ) -> WerkzeugAntwort:
        """Ein Schritt der Werkzeug-Schleife ueber die Messages-API (urllib).

        ``text`` ist der Text aller text-Bloecke (mit Zeilenumbruch verbunden),
        ``aufrufe`` kommen aus den tool_use-Bloecken (id, name, input), ``roh``
        ist die content-Liste der Antwort unveraendert. Fehler (kein Key,
        Verbindung, HTTP) stehen in ``fehler``; es wird nichts geworfen. Ein
        HTTP 400, das "tool" nennt, gilt als fehlende Werkzeugunterstuetzung
        des Modells und wird fuer die Instanz gemerkt.
        """
        if not self.config.api_key:
            return WerkzeugAntwort(fehler="Kein API-Key für Claude hinterlegt.")
        try:
            system, messages = self._nachrichten_fuer_api(nachrichten)
            body = {
                "model": self._get_model_id(),
                "max_tokens": max_tokens,
                "temperature": self.config.temperature,
                "messages": messages,
            }
            if system:
                body["system"] = system
            if werkzeuge:
                body["tools"] = self._werkzeuge_fuer_api(werkzeuge)
                self._letzte_werkzeuge = list(werkzeuge)
            elif self._hat_werkzeugbloecke(messages):
                # Die Messages-API verlangt Werkzeugdefinitionen, sobald der
                # Verlauf tool_use-/tool_result-Bloecke enthaelt - auch im
                # letzten Schritt der Schleife, in dem das Modell nur noch
                # antworten soll (Review-Befund: sonst HTTP 400 "Requests which
                # include tool_use or tool_result blocks must define tools").
                # tool_choice "none" verbietet weitere Aufrufe.
                bekannte = self._letzte_werkzeuge or []
                body["tools"] = (self._werkzeuge_fuer_api(bekannte) if bekannte
                                 else self._platzhalter_werkzeuge(messages))
                body["tool_choice"] = {"type": "none"}
            data, error = self._http_post_json(self.MESSAGES_URL, body, self._api_headers())
        except Exception as e:  # Umsetzung oder Aufruf darf nie werfen
            return WerkzeugAntwort(fehler=f"Claude-Fehler: {e}")

        if error:
            if werkzeuge and error.startswith("Claude HTTP 400") and "tool" in error.lower():
                self._werkzeuge_abgelehnt = True
                return WerkzeugAntwort(
                    fehler=f"Werkzeuge werden von diesem Modell nicht unterstützt ({error})"
                )
            return WerkzeugAntwort(fehler=error)
        if not isinstance(data, dict):
            return WerkzeugAntwort(fehler="Claude-Antwort unlesbar.")
        content = data.get("content")
        if not isinstance(content, list):
            return WerkzeugAntwort(fehler=f"Claude-Antwort ohne Inhalt: {str(data)[:300]}")

        texte: list[str] = []
        aufrufe: list[WerkzeugAufruf] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            typ = block.get("type")
            if typ == "text":
                text = block.get("text") or ""
                if text:
                    texte.append(text)
            elif typ == "tool_use":
                argumente = block.get("input")
                if isinstance(argumente, str):  # vorsichtshalber JSON-String parsen
                    try:
                        argumente = json.loads(argumente)
                    except ValueError:
                        argumente = {}
                if not isinstance(argumente, dict):
                    argumente = {}
                aufrufe.append(WerkzeugAufruf(
                    name=str(block.get("name") or ""),
                    argumente=argumente,
                    id=str(block.get("id") or ""),
                ))
        if not texte and not aufrufe:
            return WerkzeugAntwort(
                fehler=f"Claude lieferte keine Antwort (stop_reason={data.get('stop_reason')}).",
                roh=content,
            )
        return WerkzeugAntwort(text="\n".join(texte), aufrufe=aufrufe, roh=content)

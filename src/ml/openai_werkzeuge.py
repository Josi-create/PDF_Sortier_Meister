"""
Werkzeugaufrufe fuer OpenAI-kompatible Provider (Issue #166/#167, Phase 2)

OpenAI, OpenRouter, Poe und Strata sprechen dasselbe ``chat/completions``-
Drahtformat fuer Werkzeuge:

    Request:  "tools": [{"type": "function",
                         "function": {"name", "description", "parameters"}}],
              "tool_choice": "auto"
    Antwort:  choices[0].message.content (kann null sein) und
              choices[0].message.tool_calls: [{"id", "type": "function",
                         "function": {"name", "arguments": "<JSON-String>"}}]
    Ergebnis: {"role": "tool", "tool_call_id": <id>, "content": "..."}

Der :class:`OpenAIWerkzeugMixin` setzt :meth:`chat_mit_werkzeugen` fuer alle
vier Provider gemeinsam um. Er geht denselben Weg wie ``answer_with_context``:
``urllib`` ueber den ``_http_post_json``-Helfer des Providers, kein SDK, keine
Reasoning-Extras. Fehler kommen als ``WerkzeugAntwort.fehler`` zurueck, nie
als Exception. Lehnt der Server Werkzeuge ab (HTTP 400/404 mit "tool" im
Fehlertext), merkt sich die Instanz das; ``unterstuetzt_werkzeuge()`` sagt
danach Nein, und der Chat laeuft ohne Werkzeuge weiter.

GPL-3.0-or-later - Copyright (c) 2026
"""

import json
import re
from typing import Any, Optional

from src.ml.llm_provider import Werkzeug, WerkzeugAntwort, WerkzeugAufruf


# "OpenAI HTTP 400: ..." / "Poe HTTP 404: ..." - so formatieren die
# _http_post_json-Helfer der Provider ihre HTTP-Fehler.
_HTTP_STATUS_RE = re.compile(r"\bHTTP (\d{3})\b")

# Statuscodes, mit denen Server fehlende Werkzeugunterstuetzung melden:
# 400 "This model does not support tools" (OpenAI-kompatible Server),
# 404 "No endpoints found that support tool use" (OpenRouter).
_ABLEHNUNGS_STATUS = ("400", "404")


def ist_werkzeug_ablehnung(fehler: Optional[str]) -> bool:
    """True, wenn ein Fehlertext fehlende Werkzeugunterstuetzung bedeutet.

    Kriterium: HTTP 400 oder 404 und das Wort "tool" im Text (deckt
    "tools", "tool use", "tool_choice", "function calling"-Meldungen mit
    "tool" ab). Andere 400er (z.B. ungueltiges max_tokens) zaehlen nicht.
    """
    if not fehler:
        return False
    m = _HTTP_STATUS_RE.search(fehler)
    if not m or m.group(1) not in _ABLEHNUNGS_STATUS:
        return False
    return "tool" in fehler.lower()


def werkzeuge_zu_tools(werkzeuge: list[Werkzeug]) -> list[dict]:
    """Uebersetzt :class:`Werkzeug`-Objekte ins "tools"-Feld des Requests."""
    tools = []
    for w in werkzeuge or []:
        name = _feld(w, "name", "")
        if not name:
            continue
        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": _feld(w, "beschreibung", "") or "",
                "parameters": _feld(w, "parameter", None)
                or {"type": "object", "properties": {}},
            },
        })
    return tools


def argumente_parsen(roh: Any) -> dict:
    """Macht aus dem "arguments"-Feld ein Dict.

    OpenAI liefert einen JSON-String; manche Server schicken direkt ein
    Objekt. Unparsbares oder Nicht-Objekte ergeben ``{}`` - das Werkzeug
    meldet dann selbst, was ihm fehlt.
    """
    if isinstance(roh, dict):
        return roh
    if roh is None:
        return {}
    if isinstance(roh, (bytes, bytearray)):
        roh = roh.decode("utf-8", errors="replace")
    if not isinstance(roh, str) or not roh.strip():
        return {}
    try:
        wert = json.loads(roh)
    except (TypeError, ValueError):
        return {}
    return wert if isinstance(wert, dict) else {}


def _feld(obj: Any, name: str, standard: Any) -> Any:
    """Attribut oder Dict-Schluessel lesen (Dataclass und Dict gleich behandeln)."""
    if isinstance(obj, dict):
        return obj.get(name, standard)
    return getattr(obj, name, standard)


def _roh_verwendbar(roh: Any) -> bool:
    """Ist ``roh`` eine chat/completions-Assistentennachricht, die zurueck darf?

    Claude legt Inhaltsbloecke (Liste) unter ``content`` ab, Ollama schickt
    ``tool_calls`` ohne ``id``/``type`` - beides wuerde ein OpenAI-kompatibler
    Server ablehnen. Dann wird die Nachricht aus ``content`` + ``aufrufe``
    nachgebaut.
    """
    if not isinstance(roh, dict):
        return False
    if isinstance(roh.get("content"), list):
        return False
    for aufruf in roh.get("tool_calls") or []:
        if not isinstance(aufruf, dict) or not aufruf.get("id"):
            return False
        funktion = aufruf.get("function")
        if not isinstance(funktion, dict) or not isinstance(funktion.get("arguments"), str):
            return False
    return True


def _assistent_nachbauen(nachricht: dict) -> dict:
    """Baut eine Assistentennachricht aus ``content`` und ``aufrufe`` nach.

    ``arguments`` muss ein JSON-String sein (Drahtformat); ohne Text und mit
    Aufrufen ist ``content`` null, wie es der Server selbst liefert.
    """
    text = nachricht.get("content") or ""
    tool_calls = []
    for i, aufruf in enumerate(nachricht.get("aufrufe") or [], start=1):
        name = _feld(aufruf, "name", "")
        if not name:
            continue
        argumente = _feld(aufruf, "argumente", None)
        if not isinstance(argumente, dict):
            argumente = {}
        tool_calls.append({
            "id": str(_feld(aufruf, "id", "") or f"aufruf_{i}"),
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(argumente, ensure_ascii=False),
            },
        })
    if not tool_calls:
        return {"role": "assistant", "content": text}
    return {"role": "assistant", "content": text or None, "tool_calls": tool_calls}


def nachrichten_zu_openai(nachrichten: list[dict]) -> list[dict]:
    """Uebersetzt das provider-neutrale Gespraech ins "messages"-Feld.

    - system/user: ``role`` + ``content`` unveraendert.
    - assistant: ``roh`` (die Rohnachricht derselben Antwort) unveraendert,
      damit die ``tool_calls`` mit ihren Ids im Verlauf stehen; ohne
      brauchbares ``roh`` nachgebaut aus ``content`` + ``aufrufe``.
    - tool: ``{"role": "tool", "tool_call_id": aufruf_id, "content": ...}``.
    """
    ergebnis: list[dict] = []
    for n in nachrichten or []:
        if not isinstance(n, dict):
            continue
        rolle = n.get("role") or "user"
        if rolle == "assistant":
            roh = n.get("roh")
            if _roh_verwendbar(roh):
                # Rolle fehlt bei manchen Servern in der Antwort - ergaenzen,
                # sonst unveraendert durchreichen.
                ergebnis.append(roh if roh.get("role") else {"role": "assistant", **roh})
            else:
                ergebnis.append(_assistent_nachbauen(n))
        elif rolle == "tool":
            ergebnis.append({
                "role": "tool",
                "tool_call_id": str(n.get("aufruf_id") or ""),
                "content": _als_text(n.get("content")),
            })
        else:
            ergebnis.append({"role": rolle, "content": _als_text(n.get("content"))})
    return ergebnis


def _als_text(wert: Any) -> str:
    """Inhalt als String; None -> ""."""
    if wert is None:
        return ""
    if isinstance(wert, str):
        return wert
    try:
        return json.dumps(wert, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(wert)


def _inhalt_als_text(content: Any) -> str:
    """content der Antwort als Text; null -> "", Inhaltsbloecke -> Textteile."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        teile = []
        for block in content:
            if isinstance(block, dict):
                teile.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                teile.append(block)
        return "".join(teile)
    return str(content)


def antwort_parsen(data: Any, api_name: str) -> WerkzeugAntwort:
    """Macht aus der chat/completions-Antwort eine :class:`WerkzeugAntwort`.

    ``roh`` ist das unveraenderte ``message``-Dict, damit der Controller es
    in die naechste Assistentennachricht legen kann.
    """
    if not isinstance(data, dict):
        return WerkzeugAntwort(fehler=f"{api_name}: unlesbare Antwort vom Server.")
    choices = data.get("choices") or []
    if not choices:
        fehler = data.get("error")
        if fehler:
            return WerkzeugAntwort(fehler=fehler_aus_antwort(fehler, api_name))
        return WerkzeugAntwort(fehler=f"{api_name}: keine Antwort vom Modell (choices leer).")
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") or {}
    if not isinstance(message, dict):
        return WerkzeugAntwort(fehler=f"{api_name}: unlesbare Nachricht vom Modell.")

    text = _inhalt_als_text(message.get("content"))
    aufrufe: list[WerkzeugAufruf] = []
    for i, tc in enumerate(message.get("tool_calls") or [], start=1):
        if not isinstance(tc, dict):
            continue
        funktion = tc.get("function") or {}
        name = funktion.get("name") if isinstance(funktion, dict) else None
        if not name:
            continue
        aufrufe.append(WerkzeugAufruf(
            name=str(name),
            argumente=argumente_parsen(funktion.get("arguments")),
            id=str(tc.get("id") or f"aufruf_{i}"),
        ))

    finish_reason = str(choice.get("finish_reason") or "").lower()
    if not text.strip() and not aufrufe and finish_reason in ("length", "max_tokens"):
        return WerkzeugAntwort(
            roh=message,
            fehler=f"{api_name}: Antwort leer, Token-Limit erreicht "
                   "(Max. Tokens erhöhen oder Modell ohne Reasoning wählen).",
        )
    return WerkzeugAntwort(text=text, aufrufe=aufrufe, roh=message,
                           abgeschnitten=finish_reason in ("length", "max_tokens") and not aufrufe)


def fehler_aus_antwort(fehler: Any, api_name: str) -> str:
    """Fehlertext aus einem "error"-Feld (HTTP 200 mit Fehlerobjekt, z.B. OpenRouter).

    Baut dieselbe Form wie ``_http_post_json`` ("<Name> HTTP <code>: ..."),
    damit :func:`ist_werkzeug_ablehnung` auch hier greift.
    """
    if isinstance(fehler, dict):
        meldung = fehler.get("message") or json.dumps(fehler, ensure_ascii=False)
        code = fehler.get("code") or fehler.get("status")
        if isinstance(code, int) or (isinstance(code, str) and code.isdigit()):
            return f"{api_name} HTTP {code}: {meldung}"
        return f"{api_name}-Fehler: {meldung}"
    return f"{api_name}-Fehler: {fehler}"


class OpenAIWerkzeugMixin:
    """Werkzeug-Schleife fuer OpenAI-kompatible Provider.

    Erwartet vom Provider: ``config`` (api_key, temperature),
    ``_get_model_id()``, ``_http_post_json(url, body, headers)``,
    ``CHAT_COMPLETIONS_URL`` und ``API_NAME``. Muss in der Vererbung VOR
    :class:`~src.ml.llm_provider.LLMProvider` stehen, damit die Methoden
    hier die Basis-Standards ueberschreiben.
    """

    # Nach einer Ablehnung (HTTP 400/404 "... tool ...") fuer diese Instanz
    # gemerkt - sonst kostet jede Frage einen Fehlversuch extra.
    _werkzeuge_abgelehnt = False

    def unterstuetzt_werkzeuge(self) -> bool:
        """Ja, solange der Server Werkzeuge nicht abgelehnt hat."""
        return not self._werkzeuge_abgelehnt

    def _werkzeug_chat_url(self) -> str:
        """URL des chat/completions-Endpunkts (Strata: Instanz-Attribut)."""
        return self.CHAT_COMPLETIONS_URL

    def _werkzeug_max_tokens(self, max_tokens: int) -> int:
        """Hook fuer Provider mit Mindestbudget (Poe + Claude-Modelle)."""
        return max_tokens

    def _werkzeug_body_anpassen(self, body: dict) -> dict:
        """Hook fuer Modelle mit abweichenden Feldern (OpenAI-Reasoning: max_completion_tokens)."""
        return body

    # Zuletzt gesendete Werkzeugdefinitionen (je Instanz neu zugewiesen)
    _letzte_werkzeuge: list = []

    @staticmethod
    def _hat_werkzeugnachrichten(messages: list[dict]) -> bool:
        """True, wenn der Verlauf tool_calls bzw. tool-Nachrichten enthaelt."""
        for m in messages or ():
            if not isinstance(m, dict):
                continue
            if m.get("role") == "tool" or m.get("tool_calls"):
                return True
        return False

    @staticmethod
    def _platzhalter_tools(messages: list[dict]) -> list[dict]:
        """Minimale Definitionen fuer die im Verlauf benutzten Werkzeugnamen."""
        namen: list[str] = []
        for m in messages or ():
            if not isinstance(m, dict):
                continue
            for tc in m.get("tool_calls") or ():
                name = str(((tc or {}).get("function") or {}).get("name") or "").strip()
                if name and name not in namen:
                    namen.append(name)
        return [{"type": "function", "function": {
            "name": name, "description": "Werkzeug aus dem bisherigen Verlauf (nicht mehr aufrufen).",
            "parameters": {"type": "object", "properties": {}},
        }} for name in (namen or ["verlauf"])]

    def chat_mit_werkzeugen(
        self,
        nachrichten: list[dict],
        werkzeuge: list[Werkzeug],
        max_tokens: int = 1000,
    ) -> WerkzeugAntwort:
        """Ein Schritt der Werkzeug-Schleife ueber chat/completions.

        Siehe :meth:`src.ml.llm_provider.LLMProvider.chat_mit_werkzeugen`.
        """
        api_name = getattr(self, "API_NAME", "LLM")
        if not self.config.api_key:
            return WerkzeugAntwort(fehler=f"{api_name}: kein API-Key hinterlegt.")

        tools = werkzeuge_zu_tools(werkzeuge)
        if tools and self._werkzeuge_abgelehnt:
            return WerkzeugAntwort(
                fehler=f"{api_name}: Modell unterstützt keine Werkzeuge (bereits abgelehnt)."
            )

        try:
            model = self._get_model_id()
        except Exception as e:  # noqa: BLE001 - Provider werfen nicht nach aussen
            return WerkzeugAntwort(fehler=f"{api_name}-Fehler: {e}")

        messages = nachrichten_zu_openai(nachrichten)
        body: dict = {
            "model": model,
            "max_tokens": self._werkzeug_max_tokens(max_tokens),
            "temperature": self.config.temperature,
            "messages": messages,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
            self._letzte_werkzeuge = list(werkzeuge)
        elif self._hat_werkzeugnachrichten(messages):
            # Letzter Schritt ohne neue Werkzeuge, aber mit Werkzeugverlauf:
            # Anthropic-Modelle hinter OpenRouter/Poe verlangen dann die
            # Definitionen (Review-Befund); tool_choice "none" verbietet Aufrufe.
            bekannte = self._letzte_werkzeuge or []
            body["tools"] = werkzeuge_zu_tools(bekannte) if bekannte else self._platzhalter_tools(messages)
            body["tool_choice"] = "none"
        body = self._werkzeug_body_anpassen(body)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }

        try:
            data, error = self._http_post_json(self._werkzeug_chat_url(), body, headers)
        except Exception as e:  # noqa: BLE001 - Provider werfen nicht nach aussen
            return WerkzeugAntwort(fehler=f"{api_name}-Fehler: {e}")

        # HTTP 200 mit Fehlerobjekt statt choices (OpenRouter, manche Proxys)
        if not error and isinstance(data, dict) and not data.get("choices") and data.get("error"):
            error = fehler_aus_antwort(data.get("error"), api_name)

        if error or not data:
            error = error or f"{api_name}: leere Antwort vom Server."
            if tools and ist_werkzeug_ablehnung(error):
                self._werkzeuge_abgelehnt = True
                return WerkzeugAntwort(
                    fehler=f"Modell '{model}' unterstützt keine Werkzeuge - {error}"
                )
            return WerkzeugAntwort(fehler=error)

        return antwort_parsen(data, api_name)

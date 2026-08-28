"""
QA Smoke-Test fuer alle LLM-Provider (PDF Sortier Meister).

Zweck:
    Verifiziert, dass ollama, claude und openai als Provider-Module
    sauber geladen werden, mit ``LLMConfig`` instanziiert werden koennen
    und ohne konfigurierten API-Key ``graceful`` mit
    ``answer_with_context()`` umgehen - d.h. sie duerfen einen leeren
    String oder eine saubere Fehlermeldung liefern, aber sie duerfen
    *nicht* mit einer unsauberen Exception (z.B. ``AttributeError`` auf
    ``None``) abstuerzen.

Verwendung:
    python scripts/qa_all_providers.py

Exit-Code:
    0 wenn alle Provider sauber geladen wurden
    1 bei mindestens einem harten Fehler
    Am Ende wird zusaetzlich "ALL_OK" oder "FAIL: <provider> - <reason>"
    auf stdout geschrieben (fuer CI-Logs).

Hinweis:
    Es wird *kein* gueltiger API-Key und *kein* laufender Ollama-Server
    erwartet. Genau das ist der Sinn dieses Smoke-Tests: die "nicht
    verfuegbar"-Pfade sollen sauber sein.
"""

from __future__ import annotations

import importlib
import sys
import traceback
from dataclasses import dataclass
from typing import Any, Optional, Tuple

# Projekt-Root zum sys.path hinzufuegen, damit ``src.ml.*`` als Package
# importierbar ist - unabhängig davon, von wo das Script aufgerufen wird.
import os
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Provider-Spezifikation
# ---------------------------------------------------------------------------
# Jeder Provider hat:
#   * einen Anzeigenamen
#   * das vollqualifizierte Modul
#   * den Klassennamen
#   * ein Default-Modell
#   * einen Test-Modus:
#       - "needs_api_key"   -> is_available() MUSS False sein
#       - "local_server"    -> Ollama: is_available() ist True wenn base_url
#                              gesetzt; Server-Ping ist zusaetzlicher Check
# ---------------------------------------------------------------------------
@dataclass
class ProviderSpec:
    name: str
    module: str
    class_name: str
    model: str
    mode: str  # "needs_api_key" | "local_server"


PROVIDERS: list[ProviderSpec] = [
    ProviderSpec(
        name="ollama",
        module="src.ml.ollama_provider",
        class_name="OllamaProvider",
        model="llama3.1",
        mode="local_server",
    ),
    ProviderSpec(
        name="claude",
        module="src.ml.claude_provider",
        class_name="ClaudeProvider",
        model="haiku-4.5",
        mode="needs_api_key",
    ),
    ProviderSpec(
        name="openai",
        module="src.ml.openai_provider",
        class_name="OpenAIProvider",
        model="gpt-4.1-nano",
        mode="needs_api_key",
    ),
]


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
def _get_provider_version(spec: ProviderSpec) -> Optional[str]:
    """Liefert (best-effort) die Version des Provider-Pakets.

    - ``anthropic``     -> claude
    - ``openai``        -> openai
    - Ollama hat kein separates Python-Paket (nur Server).
    """
    try:
        if spec.name == "claude":
            mod = importlib.import_module("anthropic")
            return getattr(mod, "__version__", None)
        if spec.name == "openai":
            mod = importlib.import_module("openai")
            return getattr(mod, "__version__", None)
        if spec.name == "ollama":
            return "n/a (HTTP/urllib, kein Python-Paket)"
    except ImportError:
        return "Paket nicht installiert"
    except Exception as e:
        return f"unbekannt ({e})"
    return None


def _make_config(spec: ProviderSpec) -> Tuple[Any, str]:
    """Erzeugt eine leere ``LLMConfig`` (ohne API-Key)."""
    from src.ml.llm_provider import LLMConfig

    api_key = ""
    base_url = ""
    if spec.name == "ollama":
        # Ollama laeuft per Default auf localhost:11434.
        base_url = "http://localhost:11434"

    return (
        LLMConfig(
            api_key=api_key,
            model=spec.model,
            base_url=base_url,
        ),
        spec.model,
    )


def _ping_ollama(base_url: str, timeout: int = 3) -> Tuple[bool, str]:
    """Prueft, ob ein Ollama-Server unter ``base_url`` erreichbar ist.

    KEIN Hard-Fail - nur Statusmeldung.
    """
    import json
    import urllib.error
    import urllib.request

    url = f"{base_url.rstrip('/')}/api/version"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return True, data.get("version", "unbekannt")
    except urllib.error.URLError as e:
        return False, f"nicht erreichbar ({e.reason})"
    except Exception as e:
        return False, f"Fehler: {e}"


# ---------------------------------------------------------------------------
# Test-Schritte
# ---------------------------------------------------------------------------
@dataclass
class ProviderResult:
    name: str
    ok: bool
    reason: str = ""  # nur bei FAIL befuellt
    notes: list = None  # zusaetzliche Info-Zeilen (z.B. "Ollama offline")

    def __post_init__(self):
        if self.notes is None:
            self.notes = []


def _test_provider(spec: ProviderSpec) -> ProviderResult:
    """Durchlaeuft a) Import, b) Instanziierung, c) is_available,
    d) answer_with_context fuer einen Provider.

    Gibt ein :class:`ProviderResult` zurueck. ``ok`` ist genau dann False,
    wenn ein *harter* Fehler aufgetreten ist (ImportError, Crash beim
    Instanziieren, NoneType-Error in answer_with_context o.ae.).
    "Provider ist nicht verfuegbar" zaehlt *nicht* als Fehler - das
    ist genau der Pfad, den wir testen wollen.
    """
    result = ProviderResult(name=spec.name, ok=True)
    provider_instance: Any = None
    config: Any = None

    # --- (a) Importierbarkeit ------------------------------------------------
    try:
        mod = importlib.import_module(spec.module)
    except Exception as e:
        result.ok = False
        result.reason = f"Import fehlgeschlagen: {e}"
        return result

    cls = getattr(mod, spec.class_name, None)
    if cls is None:
        result.ok = False
        result.reason = (
            f"Klasse {spec.class_name} nicht in Modul {spec.module} gefunden"
        )
        return result

    # LLMConfig-Import pruefen (wird fuer Instanziierung gebraucht).
    try:
        from src.ml.llm_provider import LLMConfig  # noqa: F401
    except Exception as e:
        result.ok = False
        result.reason = f"LLMConfig nicht importierbar: {e}"
        return result

    # --- (b) Instanziierung ohne API-Key ------------------------------------
    try:
        config, model_id = _make_config(spec)
        provider_instance = cls(config)
    except Exception as e:
        result.ok = False
        result.reason = (
            f"Instanziierung fehlgeschlagen: {type(e).__name__}: {e}"
        )
        return result

    # --- (d) is_available() - darf nicht crashen ----------------------------
    # Anforderung 2d: ohne API-Key False. Bei Ollama ist das per Design
    # anders (kein Key noetig) -> das ist KEIN Fehler, nur eine Note.
    try:
        is_avail = bool(provider_instance.is_available())
    except Exception as e:
        result.ok = False
        result.reason = f"is_available() crashed: {type(e).__name__}: {e}"
        return result

    if spec.mode == "needs_api_key":
        if is_avail:
            # Hard-Fehler: Cloud-Provider darf ohne Key nicht "available" sein.
            result.ok = False
            result.reason = (
                "is_available() ist True, obwohl kein API-Key konfiguriert "
                "ist - das ist ein Bug."
            )
            return result
        result.notes.append("is_available()=False (kein API-Key) OK")
    else:  # local_server / ollama
        if is_avail:
            result.notes.append("is_available()=True (kein Key noetig)")
        else:
            result.notes.append("is_available()=False (unerwartet fuer Ollama)")

    # --- (c) answer_with_context() graceful ---------------------------------
    # Wir rufen es mit einem Minimal-Kontext auf. Erwartung: liefert einen
    # String (leer oder Fehlermeldung) oder wirft eine *dokumentierte*
    # Exception (z.B. urllib-Fehler). Ein AttributeError / TypeError / NoneType
    # waere ein Bug.
    try:
        answer = provider_instance.answer_with_context(
            system_prompt="QA-Test: bitte antworte mit 'OK'.",
            context_docs=[
                {
                    "index": 1,
                    "filename": "qa-test.pdf",
                    "kategorie": "Test",
                    "steuerjahr": "",
                    "betrag": "",
                    "korrespondent": "",
                    "text_snippet": "Inhalt des QA-Test-Dokuments.",
                }
            ],
            user_question="Ist das ein Test?",
            max_tokens=50,
        )
    except Exception as e:
        # Wenn answer_with_context eine Exception wirft, ist das in
        # Ordnung, solange es eine "saubere" Exception ist (z.B. ein
        # erwarteter Verbindungsfehler). Ein NoneType-Error waere nicht OK,
        # aber das koennen wir hier generisch nicht unterscheiden - daher:
        # wirft es eine Exception, werten wir das als FAIL, weil der
        # Vertrag laut Doku lautet: "Bei Fehlern sollte ein leerer String
        # (oder eine sinnvolle Fehlermeldung als Klartext) zurueckgegeben
        # werden." - also *kein* Raise.
        result.ok = False
        result.reason = (
            f"answer_with_context() wirft Exception statt String "
            f"zurueckzugeben: {type(e).__name__}: {e}"
        )
        return result

    if not isinstance(answer, str):
        result.ok = False
        result.reason = (
            f"answer_with_context() liefert {type(answer).__name__}, "
            f"erwartet wird str (leer oder Fehlermeldung)."
        )
        return result

    # Gueltige Rueckgabe dokumentieren.
    if spec.mode == "needs_api_key":
        # Erwartung: leerer String, weil kein Key.
        if answer == "":
            result.notes.append("answer_with_context()='' (kein Key) OK")
        else:
            # Manche Provider geben auch ohne Key eine Fehlermeldung
            # zurueck - das ist ebenfalls akzeptabel.
            preview = answer[:60].replace("\n", " ")
            result.notes.append(
                f"answer_with_context()={preview!r} (akzeptabel)"
            )
    else:  # ollama
        if answer == "":
            result.notes.append("answer_with_context()='' (vermutlich offline)")
        elif answer.startswith("["):
            # Format "[Ollama nicht erreichbar: ...]" oder "[Ollama-Fehler: ...]"
            preview = answer[:60].replace("\n", " ")
            result.notes.append(f"answer_with_context()={preview!r}")
        else:
            preview = answer[:60].replace("\n", " ")
            result.notes.append(
                f"answer_with_context()={preview!r} (Antwort erhalten)"
            )

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    print("=" * 72)
    print("QA-Smoketest: LLM-Provider (ollama, claude, openai)")
    print("=" * 72)
    print()

    results: list[ProviderResult] = []
    exit_code = 0

    for spec in PROVIDERS:
        print(f"--- {spec.name} -----------------------------------------------")
        print(f"  Modul:    {spec.module}")
        print(f"  Klasse:   {spec.class_name}")
        print(f"  Modell:   {spec.model}")
        version = _get_provider_version(spec)
        if version is not None:
            print(f"  Version:  {version}")

        result = _test_provider(spec)

        # Fuer Ollama: zusaetzlicher Server-Ping (KEIN Hard-Fail).
        if spec.name == "ollama":
            base_url = "http://localhost:11434"
            online, info = _ping_ollama(base_url)
            if online:
                result.notes.append(f"Ollama-Server online (Version: {info})")
            else:
                result.notes.append(
                    f"Ollama not running (offline) - {info}"
                )

        results.append(result)

        # Pro-Provider-Zeile: OK oder FAIL
        if result.ok:
            print(f"  -> [OK]   {spec.name}")
        else:
            print(f"  -> [FAIL] {spec.name}: {result.reason}")
            exit_code = 1

        for note in result.notes:
            print(f"     - {note}")
        print()

    # Zusammenfassung
    print("=" * 72)
    print("Zusammenfassung:")
    for r in results:
        status = "OK  " if r.ok else "FAIL"
        line = f"  [{status}] {r.name}"
        if not r.ok:
            line += f" - {r.reason}"
        print(line)
    print("=" * 72)

    if exit_code == 0:
        # Letzte Zeile bewusst ohne Prefix -> einfaches Greppen in CI.
        print("ALL_OK")
    else:
        failed = [r for r in results if not r.ok]
        first = failed[0]
        # Auch hier: einfaches Greppen, eine Zeile pro FAIL.
        print(f"FAIL: {first.name} - {first.reason}")
        for extra in failed[1:]:
            print(f"FAIL: {extra.name} - {extra.reason}")

    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # Absolute Sicherheitsleine: das Script darf nicht mit einem
        # Traceback-Only-Exit enden, sondern soll eine FAIL-Zeile schreiben.
        print(f"FAIL: unerwartete Exception: {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)

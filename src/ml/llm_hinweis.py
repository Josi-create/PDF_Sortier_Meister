"""Verstaendliche Hinweise zu KI-Fehlern fuer die Statusanzeige.

Die Anbieter liefern technische Meldungen ("Ollama HTTP 500: error starting
llama-server ..."). Fuer die Statusleiste werden sie in zwei kurze Saetze
uebersetzt: was los ist und was der Nutzer tun kann. Qt-frei, damit testbar.
"""

from __future__ import annotations

from dataclasses import dataclass
from src.i18n import tr

LOKALE_SERVER = {"Ollama": tr("Ollama"), "Strata": tr("den Strata-Server"),
                 "LM Studio": tr("LM Studio (mit lokalem Server)")}


@dataclass(frozen=True)
class KIHinweis:
    problem: str   # was los ist (ein Satz)
    abhilfe: str   # was der Nutzer tun kann (ein Satz)
    # Art des Problems fuer Knoepfe im Dialog (Issue #390): "modell_fehlt",
    # "laeuft_nicht", "absturz" oder leer
    art: str = ""


# Klassenname des Providers -> Anzeigename (wie HybridClassifier.get_llm_provider_name,
# aber ohne die Provider-Module zu importieren)
_ANBIETER_NAMEN = {
    "OllamaCloudProvider": "Ollama Cloud",
    "OllamaProvider": "Ollama",
    "ClaudeProvider": "Claude",
    "OpenRouterProvider": "OpenRouter",
    "LMStudioProvider": "LM Studio",
    "StrataProvider": "Strata",
    "OpenAIProvider": "OpenAI",
    "PoeProvider": "Poe",
}


def anbieter_name(provider) -> str:
    """Anzeigename eines Provider-Objekts (Issue #356), sonst „Die KI“."""
    for klasse in type(provider).__mro__:
        name = _ANBIETER_NAMEN.get(klasse.__name__)
        if name:
            return name
    return tr("Die KI")


def modell_von(provider) -> str:
    """Modell-ID eines Provider-Objekts (leer, wenn unbekannt). Wirft nie."""
    getter = getattr(provider, "_get_model_id", None)
    if callable(getter):
        try:
            return str(getter() or "")
        except Exception:  # noqa: BLE001 - nur fuer die Anzeige
            return ""
    return str(getattr(getattr(provider, "config", None), "model", "") or "")


# Meldungen, die nur ein einzelnes Dokument betreffen: der Anbieter
# funktioniert, hat fuer diese PDF aber nichts Brauchbares geliefert.
_NUR_DOKUMENT = (
    "keinen vorschlag",
    "keinen dateinamen",
    "nur aus ungueltigen zeichen",
    # dieselben Meldungen in der englischen Oberflaeche (src/i18n/locale/en.po)
    "not return a suggestion",
    "not return a file name",
    "only of invalid characters",
)


def betrifft_nur_dokument(fehler: str) -> bool:
    """True, wenn der Fehler kein Problem des KI-Anbieters ist."""
    text = (fehler or "").lower()
    return any(muster in text for muster in _NUR_DOKUMENT)


def _enthaelt(text: str, *muster: str) -> bool:
    return any(m in text for m in muster)


def ki_hinweis(provider: str, fehler: str, modell: str = "") -> KIHinweis:
    """Uebersetzt eine technische Fehlermeldung in Problem + Abhilfe."""
    text = (fehler or "").lower()
    server = LOKALE_SERVER.get(provider)
    modell_name = f"„{modell}“" if modell else tr("das eingestellte Modell")

    # Chat (Issue #356): Das Modell kann keine Werkzeuge - kein Fehler des Anbieters
    if _enthaelt(text, "support tool", "tool use", "keine werkzeuge", "werkzeuge werden von diesem modell"):
        return KIHinweis(
            tr("Das Modell {modell_name} kann nicht selbst in den Dokumenten suchen.").format(
                modell_name=modell_name) if modell else
            tr("Das KI-Modell kann nicht selbst in den Dokumenten suchen."),
            tr("Wer die Suche durch die KI möchte, wählt in den Einstellungen ein Modell, das "
               "Werkzeuge beherrscht (z. B. gpt-oss)."),
            "werkzeuge",
        )
    # Issue #356: Das Modell ist waehrend der Arbeit abgestuerzt ("llama runner
    # process has terminated: exit status ...") - meist reicht der Grafikspeicher
    # nicht. Startet der llama-server gar nicht, ist es eine Installationsfrage.
    if (_enthaelt(text, "has terminated", "no longer running", "exit status")
            and not _enthaelt(text, "error starting", "binary not found")):
        return KIHinweis(
            tr("Das Modell {modell_name} ist abgestürzt, meist weil der Grafikspeicher nicht "
               "reicht.").format(modell_name=modell_name) if modell else
            tr("Das KI-Modell ist abgestürzt, meist weil der Grafikspeicher nicht reicht."),
            tr("In den Einstellungen ein kleineres Modell wählen oder {provider} neu starten.").format(
                provider=provider) if server else
            tr("In den Einstellungen ein kleineres Modell wählen."),
            "absturz",
        )
    if _enthaelt(text, "llama-server", "llama runner", "runner process"):
        return KIHinweis(
            tr("{provider} ist unvollständig installiert und kann keine Modelle laden.").format(provider=provider),
            tr(
                "{provider} neu installieren bzw. aktualisieren (ollama.com) und danach neu "
                "starten."
            ).format(provider=provider),
        )
    # Ollama nennt den Namen mitten in der Meldung: model 'abc' not found (Issue #291)
    modell_fehlt = _enthaelt(text, "model '", 'model "') and "not found" in text
    if modell_fehlt or _enthaelt(text, "nicht installiert", "is not installed", "not found, try pulling",
                                 "model not found", "does not exist", "no such model"):
        if server:
            # Issue #390: Der Server hat geantwortet - also laeuft er; nur das Modell fehlt
            return KIHinweis(
                tr("{provider} läuft, aber das Modell {modell_name} ist dort nicht installiert.").format(
                    modell_name=modell_name, provider=provider),
                tr("Eines der installierten Modelle übernehmen (in den Einstellungen oder "
                   "im Fenster „Hintergrund-Analyse“)."),
                "modell_fehlt",
            )
        return KIHinweis(
            tr("Das Modell {modell_name} gibt es bei {provider} nicht.").format(modell_name=modell_name, provider=provider),
            tr("In den Einstellungen ein vorhandenes Modell auswählen."),
            "modell_fehlt",
        )
    if _enthaelt(text, "system memory", "out of memory", "not enough memory",
                 "insufficient memory", "cuda error"):
        return KIHinweis(
            tr("Das Modell {modell_name} passt nicht in den Speicher des Rechners.").format(modell_name=modell_name),
            tr("In den Einstellungen ein kleineres Modell auswählen."),
        )
    if _enthaelt(text, "api-key", "api key", "http 401", "http 403", "code: 401",
                 "code: 403", "unauthorized",
                 "forbidden", "authentication", "invalid_api_key"):
        return KIHinweis(
            tr("{provider} nimmt den API-Key nicht an.").format(provider=provider),
            tr("In den Einstellungen den API-Key prüfen bzw. neu eintragen."),
        )
    if _enthaelt(text, "insufficient_quota", "quota", "credit", "guthaben",
                 "billing", "payment", "http 402", "code: 402"):
        return KIHinweis(
            tr("Das Guthaben bzw. Kontingent bei {provider} ist aufgebraucht.").format(provider=provider),
            tr(
                "Guthaben bei {provider} aufladen oder in den Einstellungen einen anderen "
                "Anbieter wählen."
            ).format(provider=provider),
        )
    if _enthaelt(text, "http 429", "code: 429", "rate limit", "rate_limit", "too many requests"):
        return KIHinweis(
            tr("{provider} lehnt gerade zu viele Anfragen ab.").format(provider=provider),
            tr("Kurz warten, es geht danach von selbst weiter."),
        )
    if _enthaelt(text, "timed out", "timeout", "zeitüberschreitung"):
        return KIHinweis(
            tr("{provider} antwortet zu langsam.").format(provider=provider),
            tr("Kurz warten oder in den Einstellungen ein schnelleres Modell wählen."),
        )
    if _enthaelt(text, "verbindung", "nicht erreichbar", "not reachable", "connection", "refused",
                 "10061", "getaddrinfo", "name or service", "unreachable"):
        if server:
            return KIHinweis(
                tr("{provider} läuft nicht oder ist nicht erreichbar.").format(provider=provider),
                tr(
                    "{0}{1} starten; falls das nicht hilft, in den Einstellungen die Adresse "
                    "prüfen."
                ).format(server[0].upper(), server[1:]),
                "laeuft_nicht",
            )
        return KIHinweis(
            tr("Keine Verbindung zu {provider}.").format(provider=provider),
            tr("Internetverbindung prüfen; falls das nicht hilft, "
            "in den Einstellungen einen anderen Anbieter wählen."),
        )
    return KIHinweis(
        tr("{provider} meldet einen Fehler.").format(provider=provider),
        tr("Einstellungen öffnen und dort mit „Verbindung testen“ prüfen; "
        "Details stehen in der Log-Datei."),
    )

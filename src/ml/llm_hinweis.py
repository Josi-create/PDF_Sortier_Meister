"""Verstaendliche Hinweise zu KI-Fehlern fuer die Statusanzeige.

Die Anbieter liefern technische Meldungen ("Ollama HTTP 500: error starting
llama-server ..."). Fuer die Statusleiste werden sie in zwei kurze Saetze
uebersetzt: was los ist und was der Nutzer tun kann. Qt-frei, damit testbar.
"""

from __future__ import annotations

from dataclasses import dataclass

LOKALE_SERVER = {"Ollama": "Ollama", "Strata": "den Strata-Server"}


@dataclass(frozen=True)
class KIHinweis:
    problem: str   # was los ist (ein Satz)
    abhilfe: str   # was der Nutzer tun kann (ein Satz)


# Meldungen, die nur ein einzelnes Dokument betreffen: der Anbieter
# funktioniert, hat fuer diese PDF aber nichts Brauchbares geliefert.
_NUR_DOKUMENT = (
    "keinen vorschlag",
    "keinen dateinamen",
    "nur aus ungueltigen zeichen",
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
    modell_name = f"„{modell}“" if modell else "das eingestellte Modell"

    if _enthaelt(text, "llama-server", "llama runner", "runner process"):
        return KIHinweis(
            f"{provider} ist unvollständig installiert und kann keine Modelle laden.",
            f"{provider} neu installieren bzw. aktualisieren (ollama.com) "
            "und danach neu starten.",
        )
    if _enthaelt(text, "nicht installiert", "not found, try pulling", "model not found",
                 "does not exist", "no such model"):
        return KIHinweis(
            f"Das Modell {modell_name} gibt es bei {provider} nicht.",
            "In den Einstellungen ein vorhandenes Modell auswählen.",
        )
    if _enthaelt(text, "system memory", "out of memory", "not enough memory",
                 "insufficient memory", "cuda error"):
        return KIHinweis(
            f"Das Modell {modell_name} passt nicht in den Speicher des Rechners.",
            "In den Einstellungen ein kleineres Modell auswählen.",
        )
    if _enthaelt(text, "api-key", "api key", "http 401", "http 403", "code: 401",
                 "code: 403", "unauthorized",
                 "forbidden", "authentication", "invalid_api_key"):
        return KIHinweis(
            f"{provider} nimmt den API-Key nicht an.",
            "In den Einstellungen den API-Key prüfen bzw. neu eintragen.",
        )
    if _enthaelt(text, "insufficient_quota", "quota", "credit", "guthaben",
                 "billing", "payment", "http 402", "code: 402"):
        return KIHinweis(
            f"Das Guthaben bzw. Kontingent bei {provider} ist aufgebraucht.",
            f"Guthaben bei {provider} aufladen oder in den Einstellungen "
            "einen anderen Anbieter wählen.",
        )
    if _enthaelt(text, "http 429", "code: 429", "rate limit", "rate_limit", "too many requests"):
        return KIHinweis(
            f"{provider} lehnt gerade zu viele Anfragen ab.",
            "Kurz warten, es geht danach von selbst weiter.",
        )
    if _enthaelt(text, "timed out", "timeout", "zeitüberschreitung"):
        return KIHinweis(
            f"{provider} antwortet zu langsam.",
            "Kurz warten oder in den Einstellungen ein schnelleres Modell wählen.",
        )
    if _enthaelt(text, "verbindung", "nicht erreichbar", "connection", "refused",
                 "10061", "getaddrinfo", "name or service", "unreachable"):
        if server:
            return KIHinweis(
                f"{provider} läuft nicht oder ist nicht erreichbar.",
                f"{server[0].upper()}{server[1:]} starten; falls das nicht hilft, "
                "in den Einstellungen die Adresse prüfen.",
            )
        return KIHinweis(
            f"Keine Verbindung zu {provider}.",
            "Internetverbindung prüfen; falls das nicht hilft, "
            "in den Einstellungen einen anderen Anbieter wählen.",
        )
    return KIHinweis(
        f"{provider} meldet einen Fehler.",
        "Einstellungen öffnen und dort mit „Verbindung testen“ prüfen; "
        "Details stehen in der Log-Datei.",
    )

"""Freiwillige Unterstuetzung (Issue #115) - reine Logik, ohne Qt.

Unterstuetzen ist ein freiwilliger Beitrag: keine Gegenleistung, keine
Freischaltung von Funktionen (GPL-3.0). Die App prueft nichts nach, der Nutzer
meldet seine Unterstuetzung selbst (Selbstauskunft). Die Stufe bestimmt nur,
wie lange der Hinweis pausiert.

Config-Schluessel (alle ueber ``config.get``/``config.set``):
    support_hint_disabled   bool   "Nicht mehr erinnern"
    support_hint_last_shown str    ISO-Datum der letzten Anzeige
    support_tier            str    Schluessel der gemeldeten Stufe (s. TIERS)
    support_since           str    ISO-Datum der ersten Meldung
    support_until           str    ISO-Datum bis zu dem pausiert wird, oder "lifetime"

Spaeterer Lizenzschluessel: ``record_support`` bzw. ``supporter_label`` sind die
einzigen Stellen, die den Status schreiben/lesen - ein Anbieter mit Schluessel-API
setzt dieselben Felder, ohne dass der Dialog umgebaut werden muss.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
from src.i18n import tr

# Zahlungsseite (Buy Me a Coffee). Leer = kein Spenden-Link.
DONATE_URL = "https://buymeacoffee.com/josicreate"
# Link zum Impressum. Leer = nicht anzeigen (noch zu ergaenzen, siehe Issue #115).
IMPRESSUM_URL = ""

MIN_SORTED_DOCUMENTS = 50   # Erstanzeige erst ab so vielen sortierten Dokumenten
REMIND_INTERVAL_DAYS = 30   # danach alle 30 Tage
LIFETIME = "lifetime"

# Pausen in Tagen (Monat = 30, halbes Jahr = 182, Jahr = 365)
_PAUSE_MONTH = 30
_PAUSE_HALF_YEAR = 182
_PAUSE_YEAR = 365


@dataclass(frozen=True)
class Tier:
    key: str
    label: str
    amount: int  # Euro


TIERS: tuple[Tier, ...] = (
    Tier("zigarette", tr("Eine Zigarette"), 1),
    Tier("kaffee", tr("Ein Kaffee"), 3),
    Tier("bier", tr("Zwei Bier"), 5),
    Tier("mittag", tr("Mittagessen"), 12),
    Tier("abend", tr("Abendessen"), 25),
    Tier("pro", tr("PRO-Unterstützerlizenz"), 49),
    Tier("porsche", tr("Ein neuer Porsche"), 999),
)


def tier_by_key(key: str) -> Optional[Tier]:
    return next((t for t in TIERS if t.key == key), None)


def pause_days(amount: float) -> Optional[int]:
    """Pause des Hinweises je Zahlung in Tagen; ``None`` = fuer immer.

    Bis 1 EUR ein Monat, unter 5 EUR ein halbes Jahr, ab 5 EUR ein Jahr,
    ueber 48 EUR fuer immer. Genau 5 EUR zaehlt nach oben.
    """
    if amount <= 1:
        return _PAUSE_MONTH
    if amount < 5:
        return _PAUSE_HALF_YEAR
    if amount <= 48:
        return _PAUSE_YEAR
    return None


def _parse_date(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def should_show(config, sorted_count: int, today: date) -> bool:
    """Soll der Unterstuetzen-Hinweis jetzt automatisch erscheinen?"""
    if config.get("support_hint_disabled", False):
        return False
    until = config.get("support_until", "")
    if until == LIFETIME:
        return False
    until_date = _parse_date(until)
    if until_date is not None and today <= until_date:
        return False
    if sorted_count < MIN_SORTED_DOCUMENTS:
        return False
    last = _parse_date(config.get("support_hint_last_shown", ""))
    if last is None:
        return True
    return today >= last + timedelta(days=REMIND_INTERVAL_DAYS)


def mark_shown(config, today: date) -> None:
    config.set("support_hint_last_shown", today.isoformat())


def record_support(config, tier_key: str, today: date) -> bool:
    """Speichert die Selbstauskunft "Ich habe unterstuetzt". False bei unbekannter Stufe."""
    tier = tier_by_key(tier_key)
    if tier is None:
        return False
    days = pause_days(tier.amount)
    until = LIFETIME if days is None else (today + timedelta(days=days)).isoformat()
    # Eine laengere bestehende Pause wird nie verkuerzt.
    old_until = config.get("support_until", "")
    if old_until == LIFETIME:
        until = LIFETIME
    elif until != LIFETIME:
        old_date = _parse_date(old_until)
        if old_date is not None and old_date.isoformat() > until:
            until = old_date.isoformat()
    since = config.get("support_since", "") or today.isoformat()
    # Bei mehreren Meldungen zaehlt die hoechste Stufe fuer die Anzeige.
    old = tier_by_key(config.get("support_tier", ""))
    shown_tier = old if old and old.amount > tier.amount else tier
    config.set("support_tier", shown_tier.key, auto_save=False)
    config.set("support_since", since, auto_save=False)
    config.set("support_until", until)
    return True


def supporter_label(config) -> str:
    """Text fuer den Ueber-Dialog; leer, wenn nicht unterstuetzt."""
    since = _parse_date(config.get("support_since", ""))
    if since is None:
        return ""
    datum = since.strftime("%d.%m.%Y")
    if config.get("support_tier", "") == "pro":
        return tr("PRO-Unterstützer seit {datum}").format(datum=datum)
    return tr("Unterstützer seit {datum}").format(datum=datum)

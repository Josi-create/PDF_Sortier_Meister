"""Tests fuer die Unterstuetzen-Logik (Issue #115), ohne Qt."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.core import support

HEUTE = date(2026, 11, 7)


class FakeConfig:
    def __init__(self, **werte):
        self.werte = dict(werte)

    def get(self, key, default=None):
        return self.werte.get(key, default)

    def set(self, key, value, auto_save=True):
        self.werte[key] = value


@pytest.mark.parametrize("betrag,tage", [
    (0.5, 30), (1, 30),          # bis 1 EUR: ein Monat
    (1.01, 182), (3, 182), (4.99, 182),  # unter 5 EUR: sechs Monate
    (5, 365), (12, 365), (48, 365),      # ab 5 EUR: ein Jahr; 5 zaehlt nach oben
    (48.01, None), (49, None), (999, None),  # ueber 48 EUR: fuer immer
])
def test_pause_days(betrag, tage):
    assert support.pause_days(betrag) == tage


def test_tiers_entsprechen_der_tabelle():
    assert [(t.label, t.amount) for t in support.TIERS] == [
        ("Eine Zigarette", 1), ("Ein Kaffee", 3), ("Zwei Bier", 5), ("Mittagessen", 12),
        ("Abendessen", 25), ("PRO-Unterstützerlizenz", 49), ("Ein neuer Porsche", 999),
    ]


def test_should_show_erststart_ohne_dokumente_nie():
    assert not support.should_show(FakeConfig(), 0, HEUTE)


def test_should_show_unter_50_nie():
    assert not support.should_show(FakeConfig(), 49, HEUTE)


def test_should_show_ab_50_erstmals():
    assert support.should_show(FakeConfig(), 50, HEUTE)


def test_should_show_30_tage_rhythmus():
    def cfg(vor_tagen):
        return FakeConfig(support_hint_last_shown=(HEUTE - timedelta(days=vor_tagen)).isoformat())
    assert not support.should_show(cfg(0), 100, HEUTE)
    assert not support.should_show(cfg(29), 100, HEUTE)
    assert support.should_show(cfg(30), 100, HEUTE)


def test_should_show_nicht_mehr_erinnern():
    assert not support.should_show(FakeConfig(support_hint_disabled=True), 500, HEUTE)


def test_should_show_lifetime():
    assert not support.should_show(FakeConfig(support_until="lifetime"), 500, HEUTE)


def test_should_show_pausiert_und_danach_wieder():
    bis = (HEUTE + timedelta(days=10)).isoformat()
    assert not support.should_show(FakeConfig(support_until=bis), 500, HEUTE)
    assert not support.should_show(FakeConfig(support_until=bis), 500, HEUTE + timedelta(days=10))
    assert support.should_show(FakeConfig(support_until=bis), 500, HEUTE + timedelta(days=11))


def test_should_show_kaputtes_datum_wird_ignoriert():
    cfg = FakeConfig(support_hint_last_shown="kaputt", support_until="auch kaputt")
    assert support.should_show(cfg, 50, HEUTE)


@pytest.mark.parametrize("key,tage", [("zigarette", 30), ("kaffee", 182), ("bier", 365), ("abend", 365)])
def test_record_support_pause(key, tage):
    cfg = FakeConfig()
    assert support.record_support(cfg, key, HEUTE)
    assert cfg.get("support_until") == (HEUTE + timedelta(days=tage)).isoformat()
    assert cfg.get("support_since") == HEUTE.isoformat()
    assert cfg.get("support_tier") == key


@pytest.mark.parametrize("key", ["pro", "porsche"])
def test_record_support_lifetime(key):
    cfg = FakeConfig()
    support.record_support(cfg, key, HEUTE)
    assert cfg.get("support_until") == "lifetime"


def test_record_support_unbekannte_stufe():
    cfg = FakeConfig()
    assert not support.record_support(cfg, "gibts-nicht", HEUTE)
    assert cfg.werte == {}


def test_record_support_verkuerzt_nie():
    cfg = FakeConfig()
    support.record_support(cfg, "pro", HEUTE)
    support.record_support(cfg, "zigarette", HEUTE + timedelta(days=5))
    assert cfg.get("support_until") == "lifetime"
    assert cfg.get("support_tier") == "pro"
    assert cfg.get("support_since") == HEUTE.isoformat()


def test_record_support_laengere_pause_bleibt():
    cfg = FakeConfig()
    support.record_support(cfg, "bier", HEUTE)  # ein Jahr
    support.record_support(cfg, "zigarette", HEUTE)  # ein Monat
    assert cfg.get("support_until") == (HEUTE + timedelta(days=365)).isoformat()


def test_supporter_label():
    assert support.supporter_label(FakeConfig()) == ""
    cfg = FakeConfig()
    support.record_support(cfg, "kaffee", HEUTE)
    assert support.supporter_label(cfg) == "Unterstützer seit 07.11.2026"
    support.record_support(cfg, "pro", HEUTE)
    assert support.supporter_label(cfg) == "PRO-Unterstützer seit 07.11.2026"


def test_mark_shown():
    cfg = FakeConfig()
    support.mark_shown(cfg, HEUTE)
    assert cfg.get("support_hint_last_shown") == "2026-11-07"

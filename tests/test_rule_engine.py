"""Tests fuer die RuleEngine (Phase 21 / Issue #22).

Testet ``RuleEngine.evaluate()`` und ``RuleEngine.apply_actions()``
anhand in-memory-Datenbanken mit ``tmp_path``-Isolation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.rule_engine import RuleEngine, RuleMatch
from src.utils.database import Database


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def fresh_db(tmp_path: Path) -> Database:
    """Frische In-Memory-DB pro Test."""
    return Database(db_path=str(tmp_path / "rule_engine_test.db"))


@pytest.fixture
def engine(fresh_db: Database) -> RuleEngine:
    return RuleEngine(fresh_db)


# --------------------------------------------------------------------------- #
# 1) Bedingungs-Auswertung (evaluate)
# --------------------------------------------------------------------------- #


def test_korrespondent_equals_matches(engine: RuleEngine, fresh_db: Database):
    """Einfache Korrespondent-equals-Bedingung matcht exakt."""
    fresh_db.add_rule(
        "FA",
        priority=10,
        conditions=[{"type": "korrespondent", "operator": "equals", "value": "Finanzamt"}],
        actions=[],
    )
    matches = engine.evaluate({"korrespondent": "Finanzamt"})
    assert len(matches) == 1
    assert matches[0].rule["name"] == "FA"
    assert matches[0].confidence == 1.0


def test_korrespondent_equals_no_match(engine: RuleEngine, fresh_db: Database):
    """Equals-Bedingung schlaegt bei abweichendem Wert fehl."""
    fresh_db.add_rule(
        "FA",
        conditions=[{"type": "korrespondent", "operator": "equals", "value": "Finanzamt"}],
    )
    matches = engine.evaluate({"korrespondent": "Stadtwerke"})
    assert matches == []


def test_betrag_gt_matches_when_above_threshold(engine: RuleEngine, fresh_db: Database):
    """Betrag > 100 matcht nur wenn der Wert ueber 100 liegt."""
    fresh_db.add_rule(
        "Hohe-Betraege",
        conditions=[{"type": "betrag", "operator": "gt", "value": 100.0}],
    )
    assert len(engine.evaluate({"betrag_brutto": 150.0})) == 1
    assert engine.evaluate({"betrag_brutto": 100.0}) == []
    assert engine.evaluate({"betrag_brutto": 50.0}) == []


def test_betrag_between_matches_within_range(engine: RuleEngine, fresh_db: Database):
    """Betrag between [100, 500] matcht nur innerhalb der Grenzen."""
    fresh_db.add_rule(
        "Mittel",
        conditions=[{"type": "betrag", "operator": "between", "value": [100, 500]}],
    )
    assert len(engine.evaluate({"betrag_brutto": 250.0})) == 1
    assert engine.evaluate({"betrag_brutto": 50.0}) == []
    assert engine.evaluate({"betrag_brutto": 750.0}) == []
    # Grenzwerte inklusive
    assert len(engine.evaluate({"betrag_brutto": 100.0})) == 1
    assert len(engine.evaluate({"betrag_brutto": 500.0})) == 1


def test_datum_after_matches_later_dates(engine: RuleEngine, fresh_db: Database):
    """Datum after "2024-01-01" matcht nur spaetere Daten."""
    fresh_db.add_rule(
        "Ab-2024",
        conditions=[{"type": "datum", "operator": "after", "value": "2024-01-01"}],
    )
    assert len(engine.evaluate({"datum": "2024-06-01"})) == 1
    assert engine.evaluate({"datum": "2023-12-31"}) == []
    # ISO-String mit Zeit wird ebenfalls korrekt verarbeitet
    assert len(engine.evaluate({"datum": "2024-06-01T10:00:00"})) == 1


def test_keywords_any_and_all(engine: RuleEngine, fresh_db: Database):
    """Keywords any/all matchen mit den richtigen Semantiken."""
    fresh_db.add_rule(
        "any-keywords",
        conditions=[{"type": "keywords", "operator": "any", "value": ["steuer", "bescheid"]}],
    )
    fresh_db.add_rule(
        "all-keywords",
        conditions=[{"type": "keywords", "operator": "all", "value": ["steuer", "bescheid"]}],
    )

    md = {"keywords": ["steuer", "bescheid", "finanzamt"]}
    names = sorted(m.rule["name"] for m in engine.evaluate(md))
    assert names == ["all-keywords", "any-keywords"]

    md2 = {"keywords": ["steuer", "finanzamt"]}
    names2 = sorted(m.rule["name"] for m in engine.evaluate(md2))
    # "all" schlaegt fehl (bescheid fehlt), "any" passt noch.
    assert names2 == ["any-keywords"]


def test_empty_conditions_always_matches(engine: RuleEngine, fresh_db: Database):
    """Leere conditions-Liste matcht immer mit confidence=1.0."""
    fresh_db.add_rule("Fallback", conditions=[], actions=[])
    matches = engine.evaluate({"korrespondent": "Irgendwas"})
    assert len(matches) == 1
    assert matches[0].confidence == 1.0


def test_priority_orders_matches(engine: RuleEngine, fresh_db: Database):
    """Hoehere priority erscheint zuerst im Ergebnis."""
    fresh_db.add_rule("low", priority=1, conditions=[])
    fresh_db.add_rule("high", priority=99, conditions=[])
    fresh_db.add_rule("mid", priority=50, conditions=[])
    matches = engine.evaluate({})
    assert [m.rule["name"] for m in matches] == ["high", "mid", "low"]


def test_disabled_rule_is_skipped(engine: RuleEngine, fresh_db: Database):
    """Deaktivierte Regeln tauchen nicht im Ergebnis auf."""
    fresh_db.add_rule(
        "Aktiv",
        priority=10,
        enabled=True,
        conditions=[{"type": "korrespondent", "operator": "equals", "value": "X"}],
    )
    fresh_db.add_rule(
        "Inaktiv",
        priority=99,  # hoechste Prio, aber disabled
        enabled=False,
        conditions=[{"type": "korrespondent", "operator": "equals", "value": "X"}],
    )
    matches = engine.evaluate({"korrespondent": "X"})
    assert len(matches) == 1
    assert matches[0].rule["name"] == "Aktiv"


def test_unknown_condition_type_skips_rule(engine: RuleEngine, fresh_db: Database):
    """Unbekannter condition.type fuehrt zum Ueberspringen der Regel."""
    fresh_db.add_rule(
        "Bad",
        conditions=[{"type": "no_such_type", "operator": "equals", "value": "x"}],
    )
    matches = engine.evaluate({"korrespondent": "x"})
    assert matches == []


def test_confidence_partial_match(engine: RuleEngine, fresh_db: Database):
    """Bei Teil-Match entspricht die Konfidenz N/M."""
    fresh_db.add_rule(
        "two-of-three",
        conditions=[
            {"type": "korrespondent", "operator": "equals", "value": "Finanzamt"},  # matcht
            {"type": "kategorie", "operator": "equals", "value": "Steuer"},         # matcht nicht
            {"type": "betrag", "operator": "gt", "value": 0},                        # matcht
        ],
    )
    matches = engine.evaluate(
        {"korrespondent": "Finanzamt", "kategorie": "Rechnung", "betrag_brutto": 50}
    )
    assert len(matches) == 1
    # 2 von 3 Bedingungen matchen -> 2/3 ~= 0.6666
    assert matches[0].confidence == pytest.approx(2 / 3)


def test_contains_gives_0_8_confidence(engine: RuleEngine, fresh_db: Database):
    """Substring-Match via 'contains' liefert Konfidenz 0.8."""
    fresh_db.add_rule(
        "FA-contains",
        conditions=[{"type": "korrespondent", "operator": "contains", "value": "finanz"}],
    )
    matches = engine.evaluate({"korrespondent": "Finanzamt Musterstadt"})
    assert len(matches) == 1
    assert matches[0].confidence == 0.8


# --------------------------------------------------------------------------- #
# 2) apply_actions
# --------------------------------------------------------------------------- #


def test_apply_actions_replaces_placeholders(engine: RuleEngine):
    """Platzhalter {datum}, {steuerjahr}, {korrespondent} werden aufgeloest."""
    out = engine.apply_actions(
        [
            {"type": "target_folder", "template": "Steuern/{steuerjahr}"},
            {"type": "filename_pattern", "template": "{datum}_{kategorie}_{korrespondent}.pdf"},
        ],
        {
            "datum": "2024-05-01",
            "steuerjahr": "2024",
            "kategorie": "Steuerbescheid",
            "korrespondent": "Finanzamt",
        },
    )
    assert out["target_folder"] == "Steuern/2024"
    assert out["filename_pattern"] == "2024-05-01_Steuerbescheid_Finanzamt.pdf"


def test_apply_actions_sets_metadata_field(engine: RuleEngine):
    """metadata_field-Aktion setzt den benannten Feldwert."""
    out = engine.apply_actions(
        [{"type": "metadata_field", "field": "steuerjahr", "value": "auto"}],
        {"steuerjahr": "2024"},
    )
    # "auto" ist Sonderwert -> Feld bleibt unveraendert
    assert out["steuerjahr"] == "2024"

    out2 = engine.apply_actions(
        [{"type": "metadata_field", "field": "mwst_satz", "value": "19"}],
        {},
    )
    assert out2["mwst_satz"] == "19"


def test_apply_actions_adds_tag(engine: RuleEngine):
    """tag-Aktion fuegt einen Eintrag zur tags-Liste hinzu."""
    out = engine.apply_actions(
        [{"type": "tag", "value": "steuerlich-relevant"}],
        {"korrespondent": "Finanzamt"},
    )
    assert "steuerlich-relevant" in out["tags"]

    # Mehrfaches Anfuegen desselben Tags fuehrt zu genau einem Eintrag
    out2 = engine.apply_actions(
        [
            {"type": "tag", "value": "x"},
            {"type": "tag", "value": "x"},
            {"type": "tag", "value": "y"},
        ],
        {},
    )
    assert out2["tags"].count("x") == 1
    assert out2["tags"].count("y") == 1


def test_apply_actions_returns_new_dict(engine: RuleEngine):
    """apply_actions mutiert das Input-Dict nicht."""
    md = {"korrespondent": "X"}
    out = engine.apply_actions([{"type": "tag", "value": "t1"}], md)
    assert md == {"korrespondent": "X"}  # unveraendert
    assert "tags" not in md
    assert "t1" in out["tags"]


def test_apply_actions_empty_actions_is_noop(engine: RuleEngine):
    """Leere Aktions-Liste ist ein No-op (ausser tags-Initialisierung)."""
    out = engine.apply_actions([], {"korrespondent": "X"})
    assert out.get("korrespondent") == "X"
    assert out.get("tags") == []


def test_apply_actions_unknown_action_ignored(engine: RuleEngine):
    """Unbekannte Aktionen werden stillschweigend uebergangen."""
    out = engine.apply_actions(
        [{"type": "no_such_action", "foo": "bar"}],
        {"korrespondent": "X"},
    )
    assert out["korrespondent"] == "X"
    assert "no_such_action" not in out


def test_apply_actions_filters_target_folder_by_available_folders(
    engine: RuleEngine,
):
    """target_folder-Aktionen ohne gueltigen Pfad werden aussortiert."""
    matches = engine.evaluate(
        {"korrespondent": "Finanzamt"},
        available_folders=["Steuern/2024"],
    )
    # Regel direkt hinzufuegen, dann auswerten
    # (hier ohne DB: nur Engine + apply_actions testen)
    actions = [
        {"type": "target_folder", "template": "Steuern/2024"},
        {"type": "target_folder", "template": "Steuern/2025"},
        {"type": "tag", "value": "t"},
    ]
    filtered = engine._filter_actions_for_available_folders(
        actions, ["Steuern/2024"]
    )
    # "Steuern/2025" faellt raus, der Rest bleibt.
    types = [a.get("type") + ":" + str(a.get("template", a.get("value")))
             for a in filtered]
    assert any("Steuern/2024" in t for t in types)
    assert not any("Steuern/2025" in t for t in types)
    assert any(t.startswith("tag:") for t in types)


# --------------------------------------------------------------------------- #
# 3) Allgemeines / Edge-Cases
# --------------------------------------------------------------------------- #


def test_rule_match_dataclass(engine: RuleEngine, fresh_db: Database):
    """RuleMatch ist ein Dataclass mit den erwarteten Feldern."""
    fresh_db.add_rule(
        "Test",
        priority=1,
        conditions=[],
        actions=[{"type": "tag", "value": "x"}],
    )
    matches = engine.evaluate({})
    assert isinstance(matches[0], RuleMatch)
    assert matches[0].rule["name"] == "Test"
    assert matches[0].confidence == 1.0
    assert len(matches[0].matched_actions) == 1


def test_evaluate_returns_sorted_by_priority_then_id(engine: RuleEngine, fresh_db: Database):
    """Bei gleicher Prioritaet wird nach id ASC sortiert (stabil)."""
    a = fresh_db.add_rule("A", priority=5, conditions=[])
    b = fresh_db.add_rule("B", priority=5, conditions=[])
    c = fresh_db.add_rule("C", priority=5, conditions=[])
    matches = engine.evaluate({})
    assert [m.rule["id"] for m in matches] == [a["id"], b["id"], c["id"]]
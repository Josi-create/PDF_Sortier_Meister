"""Tests fuer jeden Condition-Type der RuleEngine (Phase 21 / Issue #22).

Testet ``RuleEngine.evaluate_condition`` direkt mit dict-Bedingungen,
ohne den Umweg ueber die DB. So lassen sich einzelne Operatoren
isolation testen und Edge-Cases (None, leerer String, fehlender Key)
sind einfach abzudecken.
"""
from __future__ import annotations

import pytest

from src.core.rule_engine import RuleEngine


# Kleine Hilfs-DB (wird nicht fuer evaluate_condition benoetigt, aber
# RuleEngine-Konstruktor erwartet eine DB-Referenz).
@pytest.fixture
def engine() -> RuleEngine:
    class _StubDB:
        def list_rules(self, enabled_only: bool = False):
            return []

    return RuleEngine(_StubDB())


# --------------------------------------------------------------------------- #
# korrespondent
# --------------------------------------------------------------------------- #


def test_korrespondent_equals_exact(engine: RuleEngine):
    """equals: exakter (case-insensitiver) String-Vergleich."""
    assert engine.evaluate_condition(
        {"type": "korrespondent", "operator": "equals", "value": "Finanzamt"},
        {"korrespondent": "Finanzamt"},
    ) == 1.0
    assert engine.evaluate_condition(
        {"type": "korrespondent", "operator": "equals", "value": "finanzamt"},
        {"korrespondent": "Finanzamt"},
    ) == 1.0


def test_korrespondent_contains_substring(engine: RuleEngine):
    """contains: Substring-Match liefert 0.8."""
    assert engine.evaluate_condition(
        {"type": "korrespondent", "operator": "contains", "value": "finanz"},
        {"korrespondent": "Finanzamt Musterstadt"},
    ) == 0.8
    assert engine.evaluate_condition(
        {"type": "korrespondent", "operator": "contains", "value": "stadt"},
        {"korrespondent": "Finanzamt Musterstadt"},
    ) == 0.8


def test_korrespondent_unknown_operator_returns_none(engine: RuleEngine):
    """Unbekannter Operator -> None (Regel wird uebersprungen)."""
    assert engine.evaluate_condition(
        {"type": "korrespondent", "operator": "regex", "value": "x"},
        {"korrespondent": "X"},
    ) is None


def test_korrespondent_missing_value(engine: RuleEngine):
    """Fehlender 'korrespondent' im Metadaten-Dict -> 0.0 (kein Match)."""
    assert engine.evaluate_condition(
        {"type": "korrespondent", "operator": "equals", "value": "X"},
        {},
    ) == 0.0


def test_korrespondent_none_value(engine: RuleEngine):
    """None-Wert in Metadaten -> 0.0."""
    assert engine.evaluate_condition(
        {"type": "korrespondent", "operator": "equals", "value": "X"},
        {"korrespondent": None},
    ) == 0.0


def test_korrespondent_empty_string(engine: RuleEngine):
    """Leerer String im Metadaten-Wert -> 0.0."""
    assert engine.evaluate_condition(
        {"type": "korrespondent", "operator": "equals", "value": "X"},
        {"korrespondent": ""},
    ) == 0.0


# --------------------------------------------------------------------------- #
# kategorie
# --------------------------------------------------------------------------- #


def test_kategorie_equals(engine: RuleEngine):
    """equals: exakter Kategorie-Vergleich."""
    assert engine.evaluate_condition(
        {"type": "kategorie", "operator": "equals", "value": "Rechnung"},
        {"kategorie": "Rechnung"},
    ) == 1.0
    assert engine.evaluate_condition(
        {"type": "kategorie", "operator": "equals", "value": "Rechnung"},
        {"kategorie": "Vertrag"},
    ) == 0.0


def test_kategorie_in_list(engine: RuleEngine):
    """in: Wert muss in Liste vorkommen."""
    assert engine.evaluate_condition(
        {"type": "kategorie", "operator": "in", "value": ["Rechnung", "Vertrag"]},
        {"kategorie": "Vertrag"},
    ) == 1.0
    assert engine.evaluate_condition(
        {"type": "kategorie", "operator": "in", "value": ["Rechnung", "Vertrag"]},
        {"kategorie": "Steuerbescheid"},
    ) == 0.0


def test_kategorie_in_unknown_operator(engine: RuleEngine):
    """Unbekannter kategorie-Operator -> None."""
    assert engine.evaluate_condition(
        {"type": "kategorie", "operator": "starts_with", "value": "R"},
        {"kategorie": "Rechnung"},
    ) is None


# --------------------------------------------------------------------------- #
# betrag
# --------------------------------------------------------------------------- #


def test_betrag_gt(engine: RuleEngine):
    """gt: nur strikt groesser."""
    assert engine.evaluate_condition(
        {"type": "betrag", "operator": "gt", "value": 100},
        {"betrag_brutto": 200},
    ) == 1.0
    assert engine.evaluate_condition(
        {"type": "betrag", "operator": "gt", "value": 100},
        {"betrag_brutto": 100},
    ) == 0.0
    assert engine.evaluate_condition(
        {"type": "betrag", "operator": "gt", "value": 100},
        {"betrag_brutto": 50},
    ) == 0.0


def test_betrag_gte(engine: RuleEngine):
    """gte: inklusive Grenzwert."""
    assert engine.evaluate_condition(
        {"type": "betrag", "operator": "gte", "value": 100},
        {"betrag_brutto": 100},
    ) == 1.0
    assert engine.evaluate_condition(
        {"type": "betrag", "operator": "gte", "value": 100},
        {"betrag_brutto": 99},
    ) == 0.0


def test_betrag_lt(engine: RuleEngine):
    """lt: strikt kleiner."""
    assert engine.evaluate_condition(
        {"type": "betrag", "operator": "lt", "value": 100},
        {"betrag_brutto": 50},
    ) == 1.0
    assert engine.evaluate_condition(
        {"type": "betrag", "operator": "lt", "value": 100},
        {"betrag_brutto": 100},
    ) == 0.0


def test_betrag_lte(engine: RuleEngine):
    """lte: inklusive Grenzwert."""
    assert engine.evaluate_condition(
        {"type": "betrag", "operator": "lte", "value": 100},
        {"betrag_brutto": 100},
    ) == 1.0
    assert engine.evaluate_condition(
        {"type": "betrag", "operator": "lte", "value": 100},
        {"betrag_brutto": 101},
    ) == 0.0


def test_betrag_between(engine: RuleEngine):
    """between: Werte innerhalb [min, max] matchen (inklusive Grenzen)."""
    cond = {"type": "betrag", "operator": "between", "value": [100, 500]}
    assert engine.evaluate_condition(cond, {"betrag_brutto": 250}) == 1.0
    assert engine.evaluate_condition(cond, {"betrag_brutto": 100}) == 1.0
    assert engine.evaluate_condition(cond, {"betrag_brutto": 500}) == 1.0
    assert engine.evaluate_condition(cond, {"betrag_brutto": 50}) == 0.0
    assert engine.evaluate_condition(cond, {"betrag_brutto": 1000}) == 0.0


def test_betrag_accepts_string_values(engine: RuleEngine):
    """Strings mit Komma oder Punkt werden zu float normalisiert."""
    assert engine.evaluate_condition(
        {"type": "betrag", "operator": "gt", "value": 100},
        {"betrag_brutto": "150,50"},
    ) == 1.0
    assert engine.evaluate_condition(
        {"type": "betrag", "operator": "gt", "value": 100},
        {"betrag_brutto": "150.99"},
    ) == 1.0


def test_betrag_falls_back_to_betrag_netto(engine: RuleEngine):
    """Wenn betrag_brutto fehlt, wird betrag_netto verwendet."""
    assert engine.evaluate_condition(
        {"type": "betrag", "operator": "gt", "value": 100},
        {"betrag_netto": 200},
    ) == 1.0


def test_betrag_missing_value(engine: RuleEngine):
    """Kein Betrag im Metadaten-Dict -> 0.0."""
    assert engine.evaluate_condition(
        {"type": "betrag", "operator": "gt", "value": 100},
        {},
    ) == 0.0


def test_betrag_unknown_operator(engine: RuleEngine):
    """Unbekannter betrag-Operator -> None."""
    assert engine.evaluate_condition(
        {"type": "betrag", "operator": "equals", "value": 100},
        {"betrag_brutto": 100},
    ) is None


def test_betrag_between_malformed_value(engine: RuleEngine):
    """between ohne gueltige [min, max]-Liste -> None."""
    assert engine.evaluate_condition(
        {"type": "betrag", "operator": "between", "value": "100"},
        {"betrag_brutto": 100},
    ) is None


# --------------------------------------------------------------------------- #
# datum
# --------------------------------------------------------------------------- #


def test_datum_after(engine: RuleEngine):
    """after: nur strikt spaeter."""
    assert engine.evaluate_condition(
        {"type": "datum", "operator": "after", "value": "2024-01-01"},
        {"datum": "2024-06-01"},
    ) == 1.0
    assert engine.evaluate_condition(
        {"type": "datum", "operator": "after", "value": "2024-01-01"},
        {"datum": "2023-12-31"},
    ) == 0.0
    # gleich zaehlt NICHT als after
    assert engine.evaluate_condition(
        {"type": "datum", "operator": "after", "value": "2024-01-01"},
        {"datum": "2024-01-01"},
    ) == 0.0


def test_datum_before(engine: RuleEngine):
    """before: nur strikt frueher."""
    assert engine.evaluate_condition(
        {"type": "datum", "operator": "before", "value": "2024-01-01"},
        {"datum": "2023-06-01"},
    ) == 1.0
    assert engine.evaluate_condition(
        {"type": "datum", "operator": "before", "value": "2024-01-01"},
        {"datum": "2024-06-01"},
    ) == 0.0


def test_datum_between(engine: RuleEngine):
    """between: Datumsbereich (inklusive Grenzen)."""
    cond = {"type": "datum", "operator": "between", "value": ["2024-01-01", "2024-12-31"]}
    assert engine.evaluate_condition(cond, {"datum": "2024-06-15"}) == 1.0
    assert engine.evaluate_condition(cond, {"datum": "2024-01-01"}) == 1.0
    assert engine.evaluate_condition(cond, {"datum": "2024-12-31"}) == 1.0
    assert engine.evaluate_condition(cond, {"datum": "2023-12-31"}) == 0.0
    assert engine.evaluate_condition(cond, {"datum": "2025-01-01"}) == 0.0


def test_datum_accepts_iso_with_time(engine: RuleEngine):
    """ISO-String mit Zeitkomponente (YYYY-MM-DDTHH:MM:SS) wird korrekt verarbeitet."""
    assert engine.evaluate_condition(
        {"type": "datum", "operator": "after", "value": "2024-01-01"},
        {"datum": "2024-06-01T10:30:00"},
    ) == 1.0


def test_datum_falls_back_to_buchungsdatum(engine: RuleEngine):
    """Wenn 'datum' fehlt, wird 'buchungsdatum' verwendet."""
    assert engine.evaluate_condition(
        {"type": "datum", "operator": "after", "value": "2024-01-01"},
        {"buchungsdatum": "2024-06-01"},
    ) == 1.0


def test_datum_missing_value(engine: RuleEngine):
    """Kein Datum im Dict -> 0.0."""
    assert engine.evaluate_condition(
        {"type": "datum", "operator": "after", "value": "2024-01-01"},
        {},
    ) == 0.0


def test_datum_malformed_value(engine: RuleEngine):
    """Wert kein ISO-Datum -> None (Operator-Konflikt)."""
    assert engine.evaluate_condition(
        {"type": "datum", "operator": "after", "value": "not-a-date"},
        {"datum": "2024-06-01"},
    ) is None


def test_datum_unknown_operator(engine: RuleEngine):
    """Unbekannter datum-Operator -> None."""
    assert engine.evaluate_condition(
        {"type": "datum", "operator": "on", "value": "2024-01-01"},
        {"datum": "2024-01-01"},
    ) is None


# --------------------------------------------------------------------------- #
# keywords
# --------------------------------------------------------------------------- #


def test_keywords_any(engine: RuleEngine):
    """any: mindestens ein Treffer reicht."""
    assert engine.evaluate_condition(
        {"type": "keywords", "operator": "any", "value": ["steuer", "bescheid"]},
        {"keywords": ["finanzamt", "bescheid"]},
    ) == 1.0
    assert engine.evaluate_condition(
        {"type": "keywords", "operator": "any", "value": ["steuer", "bescheid"]},
        {"keywords": ["finanzamt", "vertrag"]},
    ) == 0.0


def test_keywords_all(engine: RuleEngine):
    """all: alle Suchbegriffe muessen vorkommen."""
    assert engine.evaluate_condition(
        {"type": "keywords", "operator": "all", "value": ["steuer", "bescheid"]},
        {"keywords": ["steuer", "bescheid", "finanzamt"]},
    ) == 1.0
    assert engine.evaluate_condition(
        {"type": "keywords", "operator": "all", "value": ["steuer", "bescheid"]},
        {"keywords": ["steuer"]},
    ) == 0.0


def test_keywords_accepts_comma_string(engine: RuleEngine):
    """Komma-getrennter keywords-String wird korrekt zerlegt."""
    assert engine.evaluate_condition(
        {"type": "keywords", "operator": "any", "value": ["steuer"]},
        {"keywords": "finanzamt, steuer, bescheid"},
    ) == 1.0
    assert engine.evaluate_condition(
        {"type": "keywords", "operator": "all", "value": ["steuer", "bescheid"]},
        {"keywords": "Finanzamt, Steuer, Bescheid"},
    ) == 1.0


def test_keywords_missing_value(engine: RuleEngine):
    """Fehlender 'keywords'-Eintrag -> 0.0 (bei any/all)."""
    assert engine.evaluate_condition(
        {"type": "keywords", "operator": "any", "value": ["x"]},
        {},
    ) == 0.0


def test_keywords_empty_value(engine: RuleEngine):
    """Leere Suchliste -> 0.0."""
    assert engine.evaluate_condition(
        {"type": "keywords", "operator": "any", "value": []},
        {"keywords": ["x"]},
    ) == 0.0


def test_keywords_unknown_operator(engine: RuleEngine):
    """Unbekannter keywords-Operator -> None."""
    assert engine.evaluate_condition(
        {"type": "keywords", "operator": "none_of", "value": ["x"]},
        {"keywords": ["x"]},
    ) is None


# --------------------------------------------------------------------------- #
# Sonstige Edge-Cases
# --------------------------------------------------------------------------- #


def test_unknown_type_returns_none(engine: RuleEngine):
    """Vollstaendig unbekannter Condition-Typ -> None."""
    assert engine.evaluate_condition(
        {"type": "no_such_type", "operator": "equals", "value": "x"},
        {"x": 1},
    ) is None


def test_non_dict_condition_is_skipped(engine: RuleEngine):
    """Kaputte (nicht-dict) Bedingungen werden via _match_rule uebergangen."""
    # Direkter Aufruf von evaluate_condition liefert None fuer kaputte
    # Strukturen, weil der Typ 'equals' nicht zu den bekannten Typen gehoert.
    # Wir testen hier, dass ein String als 'condition' keine Exception wirft.
    assert engine.evaluate_condition("not-a-dict", {"x": 1}) is None


def test_combined_partial_match(engine: RuleEngine):
    """Mehrere Bedingungen unterschiedlicher Typen kombiniert (Konfidenz-Berechnung)."""
    conds = [
        {"type": "korrespondent", "operator": "equals", "value": "Finanzamt"},
        {"type": "betrag", "operator": "gt", "value": 100},
        {"type": "datum", "operator": "after", "value": "2024-01-01"},
        {"type": "keywords", "operator": "any", "value": ["steuer"]},
    ]
    md = {
        "korrespondent": "Finanzamt",        # match (1.0)
        "betrag_brutto": 50,                  # NO match
        "datum": "2024-06-01",                # match
        "keywords": ["vertrag"],              # NO match (kein "steuer")
    }
    scores = [engine.evaluate_condition(c, md) for c in conds]
    # 2 von 4 matchen
    assert all(s is not None for s in scores)
    assert sum(scores) / len(scores) == pytest.approx(0.5)
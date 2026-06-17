"""DB-Tests fuer die Automatisierungs-Regeln (Phase 21 / Issue #22).

Testet die Tabelle ``automation_rules`` und ihre CRUD-Methoden
``add_rule``, ``list_rules``, ``get_rule``, ``update_rule``,
``delete_rule`` und ``reorder_rules`` sowie die Schema-Migration.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from src.utils.database import Database


# --------------------------------------------------------------------------- #
# Fixture
# --------------------------------------------------------------------------- #


@pytest.fixture
def fresh_db(tmp_path: Path) -> Database:
    """Frische DB pro Test in tmp_path."""
    return Database(db_path=str(tmp_path / "rules_db_test.db"))


# --------------------------------------------------------------------------- #
# 1) add_rule
# --------------------------------------------------------------------------- #


def test_add_rule_stores_and_returns_full_dict(fresh_db: Database):
    """add_rule speichert die Regel und liefert ein vollstaendiges Dict."""
    rule = fresh_db.add_rule(
        "Steuerbescheide",
        priority=50,
        enabled=True,
        conditions=[{"type": "kategorie", "operator": "equals", "value": "Steuerbescheid"}],
        actions=[{"type": "target_folder", "template": "Steuern/{steuerjahr}"}],
    )
    assert rule["id"] is not None and rule["id"] > 0
    assert rule["name"] == "Steuerbescheide"
    assert rule["priority"] == 50
    assert rule["enabled"] is True
    assert rule["conditions"] == [
        {"type": "kategorie", "operator": "equals", "value": "Steuerbescheid"}
    ]
    assert rule["actions"] == [
        {"type": "target_folder", "template": "Steuern/{steuerjahr}"}
    ]
    assert rule["created_at"] is not None
    assert rule["updated_at"] is not None


def test_add_rule_defaults(fresh_db: Database):
    """Default-Werte fuer priority=0, enabled=True, conditions=[], actions=[]."""
    rule = fresh_db.add_rule("Default")
    assert rule["priority"] == 0
    assert rule["enabled"] is True
    assert rule["conditions"] == []
    assert rule["actions"] == []


def test_add_rule_rejects_empty_name(fresh_db: Database):
    """add_rule wirft ValueError bei leerem Namen."""
    with pytest.raises(ValueError):
        fresh_db.add_rule("")
    with pytest.raises(ValueError):
        fresh_db.add_rule("   ")


def test_add_rule_unique_name(fresh_db: Database):
    """Zwei Regeln mit demselben Namen -> IntegrityError."""
    fresh_db.add_rule("Dup")
    with pytest.raises(IntegrityError):
        fresh_db.add_rule("Dup")


# --------------------------------------------------------------------------- #
# 2) list_rules
# --------------------------------------------------------------------------- #


def test_list_rules_sorted_by_priority_desc(fresh_db: Database):
    """list_rules liefert Regeln in Reihenfolge priority DESC, id ASC."""
    fresh_db.add_rule("low", priority=1, conditions=[])
    fresh_db.add_rule("high", priority=99, conditions=[])
    fresh_db.add_rule("mid", priority=50, conditions=[])
    result = fresh_db.list_rules()
    assert [r["name"] for r in result] == ["high", "mid", "low"]


def test_list_rules_enabled_only_filter(fresh_db: Database):
    """list_rules(enabled_only=True) liefert nur aktivierte Regeln."""
    fresh_db.add_rule("Aktiv", enabled=True, conditions=[])
    fresh_db.add_rule("Inaktiv", enabled=False, conditions=[])
    result = fresh_db.list_rules(enabled_only=True)
    assert [r["name"] for r in result] == ["Aktiv"]


def test_list_rules_empty_initially(fresh_db: Database):
    """Eine leere DB liefert eine leere Liste."""
    assert fresh_db.list_rules() == []


# --------------------------------------------------------------------------- #
# 3) get_rule
# --------------------------------------------------------------------------- #


def test_get_rule_returns_dict_or_none(fresh_db: Database):
    """get_rule liefert Dict fuer existent, None fuer unbekannt."""
    rule = fresh_db.add_rule("X", conditions=[])
    assert fresh_db.get_rule(rule["id"]) is not None
    assert fresh_db.get_rule(99999) is None


# --------------------------------------------------------------------------- #
# 4) update_rule
# --------------------------------------------------------------------------- #


def test_update_rule_changes_only_given_fields(fresh_db: Database):
    """update_rule aktualisiert nur die explizit angegebenen Felder."""
    rule = fresh_db.add_rule(
        "X",
        priority=10,
        enabled=True,
        conditions=[{"type": "kategorie", "operator": "equals", "value": "A"}],
        actions=[{"type": "tag", "value": "v1"}],
    )
    updated = fresh_db.update_rule(rule["id"], priority=42)
    assert updated["priority"] == 42
    # unverändert:
    assert updated["name"] == "X"
    assert updated["enabled"] is True
    assert updated["conditions"] == [{"type": "kategorie", "operator": "equals", "value": "A"}]
    assert updated["actions"] == [{"type": "tag", "value": "v1"}]


def test_update_rule_serializes_conditions_and_actions(fresh_db: Database):
    """Bedingungen und Aktionen werden korrekt JSON-serialisiert."""
    rule = fresh_db.add_rule("X", conditions=[])
    fresh_db.update_rule(
        rule["id"],
        conditions=[{"type": "betrag", "operator": "gt", "value": 100}],
        actions=[{"type": "target_folder", "template": "F/{steuerjahr}"}],
    )
    updated = fresh_db.get_rule(rule["id"])
    assert updated["conditions"] == [{"type": "betrag", "operator": "gt", "value": 100}]
    assert updated["actions"] == [{"type": "target_folder", "template": "F/{steuerjahr}"}]


def test_update_rule_disables_and_enables(fresh_db: Database):
    """enabled-Flag laesst sich umschalten."""
    rule = fresh_db.add_rule("X", enabled=True, conditions=[])
    fresh_db.update_rule(rule["id"], enabled=False)
    assert fresh_db.get_rule(rule["id"])["enabled"] is False
    fresh_db.update_rule(rule["id"], enabled=True)
    assert fresh_db.get_rule(rule["id"])["enabled"] is True


def test_update_rule_rejects_unknown_field(fresh_db: Database):
    """Unbekannte Keyword-Argumente fuehren zu ValueError."""
    rule = fresh_db.add_rule("X", conditions=[])
    with pytest.raises(ValueError):
        fresh_db.update_rule(rule["id"], no_such_field="y")


def test_update_rule_raises_for_missing_id(fresh_db: Database):
    """update_rule auf unbekannte ID -> ValueError."""
    with pytest.raises(ValueError):
        fresh_db.update_rule(99999, priority=1)


# --------------------------------------------------------------------------- #
# 5) delete_rule
# --------------------------------------------------------------------------- #


def test_delete_rule_removes_entry(fresh_db: Database):
    """delete_rule loescht den Eintrag und liefert True."""
    rule = fresh_db.add_rule("X", conditions=[])
    assert fresh_db.delete_rule(rule["id"]) is True
    assert fresh_db.get_rule(rule["id"]) is None


def test_delete_rule_returns_false_for_unknown(fresh_db: Database):
    """delete_rule auf unbekannte ID liefert False (kein Crash)."""
    assert fresh_db.delete_rule(99999) is False


# --------------------------------------------------------------------------- #
# 6) reorder_rules
# --------------------------------------------------------------------------- #


def test_reorder_rules_assigns_100_99_98(fresh_db: Database):
    """reorder_rules setzt Prioritaeten 100, 99, 98, ... in der Reihenfolge."""
    a = fresh_db.add_rule("A", priority=0)
    b = fresh_db.add_rule("B", priority=0)
    c = fresh_db.add_rule("C", priority=0)
    # Neue Reihenfolge: C, A, B -> 100, 99, 98
    fresh_db.reorder_rules([c["id"], a["id"], b["id"]])
    rules = {r["name"]: r["priority"] for r in fresh_db.list_rules()}
    assert rules["C"] == 100
    assert rules["A"] == 99
    assert rules["B"] == 98


def test_reorder_rules_empty_is_noop(fresh_db: Database):
    """reorder_rules([]) aendert nichts und crasht nicht."""
    rule = fresh_db.add_rule("X", priority=5)
    fresh_db.reorder_rules([])
    assert fresh_db.get_rule(rule["id"])["priority"] == 5


# --------------------------------------------------------------------------- #
# 7) Schema-Migration
# --------------------------------------------------------------------------- #


def test_schema_migration_idempotent(tmp_path: Path):
    """DB-Init kann mehrfach aufgerufen werden (idempotente Migration)."""
    db_path = tmp_path / "idem_rules.db"
    Database(db_path=str(db_path))
    db2 = Database(db_path=str(db_path))  # darf nicht crashen
    # Tabelle existiert und ist benutzbar.
    rule = db2.add_rule("PostIdem", conditions=[])
    assert rule["id"] is not None


def test_schema_migration_creates_automation_rules_table(tmp_path: Path):
    """Die Tabelle ``automation_rules`` wird beim Init angelegt."""
    db_path = tmp_path / "schema_test.db"
    db = Database(db_path=str(db_path))
    # Direkte SQL-Pruefung: Tabelle muss da sein.
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='automation_rules'"
        )
        assert cur.fetchone() is not None
    finally:
        conn.close()


def test_json_roundtrip_with_german_chars(fresh_db: Database):
    """Umlaute in conditions/actions werden JSON-korrekt gespeichert."""
    rule = fresh_db.add_rule(
        "Umlaut-Test",
        conditions=[{"type": "korrespondent", "operator": "contains", "value": "Müller"}],
        actions=[{"type": "target_folder", "template": "Steuern/Bescheid/{steuerjahr}"}],
    )
    out = fresh_db.get_rule(rule["id"])
    assert out["conditions"][0]["value"] == "Müller"
    assert out["actions"][0]["template"] == "Steuern/Bescheid/{steuerjahr}"
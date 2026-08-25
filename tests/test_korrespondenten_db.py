"""DB-Tests fuer die Korrespondenten-Verwaltung (Phase 20 / Issue #21).

Testet die neue Tabelle ``korrespondenten`` und ihre CRUD-Methoden
sowie ``auto_collect_from_history`` und ``merge_korrespondenten``.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.utils.database import Database


@pytest.fixture
def fresh_db(tmp_path) -> Database:
    """Frische DB in tmp_path."""
    return Database(db_path=str(tmp_path / "korr_test.db"))


# --------------------------------------------------------------------- #
# 1) add_or_update
# --------------------------------------------------------------------- #


def test_add_korrespondent_inserts_new(fresh_db):
    """Ein neuer Korrespondent wird angelegt mit usage_count=0."""
    result = fresh_db.add_or_update_korrespondent(
        "Telekom",
        aliases=["T-Mobile", "T-Mobile Deutschland"],
        kategorie="Telekommunikation",
        farbe="#FF0000",
    )
    assert result["name"] == "Telekom"
    assert result["aliases"] == ["T-Mobile", "T-Mobile Deutschland"]
    assert result["kategorie"] == "Telekommunikation"
    assert result["farbe"] == "#FF0000"
    assert result["usage_count"] == 0
    assert result["id"] is not None


def test_add_or_update_increments_usage_count(fresh_db):
    """Bei erneutem add_or_update desselben Namens wird usage_count inkrementiert."""
    fresh_db.add_or_update_korrespondent("Telekom")
    fresh_db.add_or_update_korrespondent("Telekom")
    fresh_db.add_or_update_korrespondent("Telekom")
    result = fresh_db.get_korrespondent("Telekom")
    assert result["usage_count"] == 2  # 1. INSERT + 2. + 3. UPDATE = 2 Increments


def test_add_or_update_merges_aliases(fresh_db):
    """Beim Update werden neue Aliasse gemerged (Union)."""
    fresh_db.add_or_update_korrespondent("Telekom", aliases=["T-Mobile"])
    fresh_db.add_or_update_korrespondent("Telekom", aliases=["Congstar", "T-Mobile"])
    result = fresh_db.get_korrespondent("Telekom")
    # "Telekom" selbst + T-Mobile + Congstar (Unions-Menge)
    assert "T-Mobile" in result["aliases"]
    assert "Congstar" in result["aliases"]


# --------------------------------------------------------------------- #
# 2) get
# --------------------------------------------------------------------- #


def test_get_korrespondent_returns_dict_or_none(fresh_db):
    """get_korrespondent returnt dict fuer existent, None fuer unbekannt."""
    assert fresh_db.get_korrespondent("Niemand") is None
    fresh_db.add_or_update_korrespondent("Telekom")
    result = fresh_db.get_korrespondent("Telekom")
    assert result is not None
    assert result["name"] == "Telekom"


def test_get_korrespondent_normalizes_empty(fresh_db):
    """Leere Argumente werden als None behandelt (kein Crash)."""
    assert fresh_db.get_korrespondent("") is None
    assert fresh_db.get_korrespondent(None) is None


# --------------------------------------------------------------------- #
# 3) list
# --------------------------------------------------------------------- #


def test_list_korrespondenten_returns_empty_initially(fresh_db):
    """Eine leere DB liefert eine leere Liste."""
    assert fresh_db.list_korrespondenten() == []


def test_list_korrespondenten_sorted_by_usage_count_desc(fresh_db):
    """Hoechster usage_count zuerst, dann alphabetisch."""
    fresh_db.add_or_update_korrespondent("Telekom")
    fresh_db.add_or_update_korrespondent("Telekom")  # 1
    fresh_db.add_or_update_korrespondent("Telekom")  # 2
    fresh_db.add_or_update_korrespondent("Ista")
    fresh_db.add_or_update_korrespondent("Ista")  # 1
    result = fresh_db.list_korrespondenten()
    assert [k["name"] for k in result] == ["Telekom", "Ista"]


# --------------------------------------------------------------------- #
# 4) delete
# --------------------------------------------------------------------- #


def test_delete_korrespondent_removes_it(fresh_db):
    """delete returnt True und entfernt den Eintrag."""
    fresh_db.add_or_update_korrespondent("Telekom")
    assert fresh_db.delete_korrespondent("Telekom") is True
    assert fresh_db.get_korrespondent("Telekom") is None


def test_delete_korrespondent_returns_false_for_unknown(fresh_db):
    """delete fuer unbekannten Namen returnt False (kein Crash)."""
    assert fresh_db.delete_korrespondent("Niemand") is False


# --------------------------------------------------------------------- #
# 5) merge
# --------------------------------------------------------------------- #


def test_merge_korrespondenten_keeps_primary(fresh_db):
    """Beim Merge bleibt der Primary erhalten."""
    fresh_db.add_or_update_korrespondent("Telekom")
    fresh_db.add_or_update_korrespondent("T-Mobile")
    fresh_db.merge_korrespondenten(primary_name="Telekom",
                                    secondary_names=["T-Mobile"])
    assert fresh_db.get_korrespondent("Telekom") is not None
    assert fresh_db.get_korrespondent("T-Mobile") is None


def test_merge_korrespondenten_sums_usage_count(fresh_db):
    """Beim Merge werden die usage_counts summiert."""
    fresh_db.add_or_update_korrespondent("Telekom")
    fresh_db.add_or_update_korrespondent("Telekom")  # count=1
    fresh_db.add_or_update_korrespondent("T-Mobile")
    fresh_db.add_or_update_korrespondent("T-Mobile")  # count=1
    fresh_db.merge_korrespondenten(primary_name="Telekom",
                                    secondary_names=["T-Mobile"])
    primary = fresh_db.get_korrespondent("Telekom")
    assert primary["usage_count"] == 2


def test_merge_korrespondenten_updates_fts5(fresh_db):
    """FTS5-Eintraege mit secondary-Namen werden auf primary umgeschrieben."""
    # Indiziere ein PDF mit korrespondent="T-Mobile"
    fresh_db.index_document(
        file_path="/tmp/a.pdf",
        filename="rechnung_tmob.pdf",
        extracted_text="T-Mobile Rechnung",
        korrespondent="T-Mobile",
    )
    assert "T-Mobile" in [d["korrespondent"] for d in fresh_db.search_documents("T-Mobile")]
    # Merge
    fresh_db.add_or_update_korrespondent("Telekom")
    fresh_db.add_or_update_korrespondent("T-Mobile")
    fresh_db.merge_korrespondenten(primary_name="Telekom",
                                    secondary_names=["T-Mobile"])
    # FTS5-Suche nach "Telekom" sollte jetzt den Eintrag finden
    results = fresh_db.search_documents("Telekom")
    assert any(d["korrespondent"] == "Telekom" for d in results)


# --------------------------------------------------------------------- #
# 6) auto_collect_from_history
# --------------------------------------------------------------------- #


def test_auto_collect_creates_new_from_sorting_history(fresh_db):
    """Korrespondenten aus sorting_history werden automatisch gesammelt."""
    fresh_db.add_sorting_entry(
        original_filename="t.pdf",
        original_path="/tmp/t.pdf",
        target_folder="/tmp/out",
        target_folder_name="out",
        metadata={"korrespondent": "Telekom"},
    )
    fresh_db.add_sorting_entry(
        original_filename="i.pdf",
        original_path="/tmp/i.pdf",
        target_folder="/tmp/out",
        target_folder_name="out",
        metadata={"korrespondent": "Ista"},
    )
    n = fresh_db.auto_collect_from_history()
    assert n == 2
    assert fresh_db.get_korrespondent("Telekom") is not None
    assert fresh_db.get_korrespondent("Ista") is not None


def test_auto_collect_does_not_duplicate_existing(fresh_db):
    """Existierende Korrespondenten werden nicht doppelt angelegt."""
    fresh_db.add_or_update_korrespondent("Telekom")
    fresh_db.add_sorting_entry(
        original_filename="t.pdf",
        original_path="/tmp/t.pdf",
        target_folder="/tmp/out",
        target_folder_name="out",
        metadata={"korrespondent": "Telekom"},
    )
    n = fresh_db.auto_collect_from_history()
    # "Telekom" existiert schon, also keine neuen
    assert n == 0
    assert len(fresh_db.list_korrespondenten()) == 1


def test_auto_collect_increments_usage_count(fresh_db):
    """Bereits existierender Korrespondent erhaelt usage_count+1 pro Vorkommen."""
    fresh_db.add_or_update_korrespondent("Telekom")
    fresh_db.add_sorting_entry(
        original_filename="t1.pdf",
        original_path="/tmp/t1.pdf",
        target_folder="/tmp/out",
        target_folder_name="out",
        metadata={"korrespondent": "Telekom"},
    )
    fresh_db.add_sorting_entry(
        original_filename="t2.pdf",
        original_path="/tmp/t2.pdf",
        target_folder="/tmp/out",
        target_folder_name="out",
        metadata={"korrespondent": "Telekom"},
    )
    fresh_db.auto_collect_from_history()
    k = fresh_db.get_korrespondent("Telekom")
    assert k["usage_count"] == 2  # 2 Updates (count startete bei 0)


# --------------------------------------------------------------------- #
# 7) Schema-Migration (idempotent)
# --------------------------------------------------------------------- #


def test_schema_migration_idempotent(tmp_path):
    """DB-Init kann mehrfach aufgerufen werden ohne Crash (idempotente Migration)."""
    db_path = tmp_path / "idem.db"
    # Erstelle DB, dann re-instanziiere
    Database(db_path=str(db_path))
    db2 = Database(db_path=str(db_path))  # sollte nicht crashen
    # Korrespondent-Tabelle existiert
    assert db2.get_korrespondent("anything") is None

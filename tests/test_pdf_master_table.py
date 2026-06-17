"""Tests fuer die pdfs-Master-Tabelle (Issue #25 / Phase 1).

Die Master-Tabelle bildet eine physische PDF auf eine stabile UUID
ab, die Verschieben und Umbenennen ueberlebt. Diese Tests pruefen:
    * get_or_create_pdf_id ist idempotent
    * get_pdf_by_path liefert None / Dict korrekt
    * update_pdf_metadata aktualisiert file_path/filename und last_seen_at
    * update_pdf_metadata legt einen fehlenden Eintrag neu an (UPSERT)
    * update_pdf_path migriert pdfs-Eintrag konsistent mit document_search
"""

import sqlite3
import tempfile
import uuid
from pathlib import Path

import pytest

from src.utils.database import Database


def _make_db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


def test_get_or_create_pdf_id_returns_stable_uuid(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    pid_a = db.get_or_create_pdf_id("/tmp/foo.pdf", "foo.pdf")
    pid_b = db.get_or_create_pdf_id("/tmp/foo.pdf", "foo.pdf")
    assert pid_a == pid_b
    # 32-Zeichen Hex-UUID
    assert len(pid_a) == 32
    uuid.UUID(hex=pid_a)  # raises ValueError wenn kein valides Hex


def test_get_or_create_pdf_id_creates_row(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    pid = db.get_or_create_pdf_id("/tmp/bar.pdf", "bar.pdf")
    entry = db.get_pdf_by_path("/tmp/bar.pdf")
    assert entry is not None
    assert entry["pdf_id"] == pid
    assert entry["file_path"] == "/tmp/bar.pdf"
    assert entry["filename"] == "bar.pdf"
    assert entry["indexed_at"]  # ISO-Datetime gesetzt
    assert entry["last_seen_at"]


def test_get_pdf_by_path_returns_none_for_unknown(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    assert db.get_pdf_by_path("/tmp/nonexistent.pdf") is None


def test_update_pdf_metadata_updates_path_and_filename(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    pid = db.get_or_create_pdf_id("/old/x.pdf", "old.pdf")
    ok = db.update_pdf_metadata(pid, file_path="/new/x.pdf", filename="new.pdf")
    assert ok is True

    entry = db.get_pdf_by_path("/new/x.pdf")
    assert entry is not None
    assert entry["pdf_id"] == pid
    assert entry["filename"] == "new.pdf"
    # alter Pfad darf nicht mehr erreichbar sein
    assert db.get_pdf_by_path("/old/x.pdf") is None


def test_update_pdf_metadata_upserts_when_pdf_id_unknown(tmp_path: Path) -> None:
    """Edge-Case: pdf_id noch nicht in pdfs -> INSERT statt UPDATE."""
    db = _make_db(tmp_path)
    new_uuid = uuid.uuid4().hex
    ok = db.update_pdf_metadata(
        new_uuid, file_path="/upsert/a.pdf", filename="a.pdf"
    )
    assert ok is True
    entry = db.get_pdf_by_path("/upsert/a.pdf")
    assert entry is not None
    assert entry["pdf_id"] == new_uuid


def test_update_pdf_path_migrates_pdfs_master(tmp_path: Path) -> None:
    """update_pdf_path haelt pdfs-Eintrag konsistent: gleiche pdf_id nach Move."""
    db = _make_db(tmp_path)
    pid = db.get_or_create_pdf_id("/src/a.pdf", "a.pdf")
    # Simuliert eine Move-Operation ohne vorherige document_search-Indexierung
    db.update_pdf_path("/src/a.pdf", "/dst/a.pdf", "renamed.pdf")
    entry = db.get_pdf_by_path("/dst/a.pdf")
    assert entry is not None
    assert entry["pdf_id"] == pid
    assert entry["filename"] == "renamed.pdf"

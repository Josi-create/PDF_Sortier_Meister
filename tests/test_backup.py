"""Issue #98: Anwendungsdaten sichern (ZIP) und wiederherstellen (kein Qt)."""
import json
import sqlite3
import zipfile

import pytest

from src.utils.backup import (
    INFO_NAME,
    PENDING_DIR,
    PREVIOUS_DIR,
    apply_pending_restore,
    create_backup,
    default_backup_name,
    inspect_backup,
    stage_restore,
)


def _make_db(path, rows):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.executemany("INSERT INTO t VALUES (?)", [(r,) for r in rows])
    conn.commit()
    conn.close()


def _rows(path):
    conn = sqlite3.connect(str(path))
    try:
        return [r[0] for r in conn.execute("SELECT v FROM t ORDER BY v")]
    finally:
        conn.close()


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "appdata"
    d.mkdir()
    (d / "config.json").write_text(json.dumps({"scan_folder": "C:/Scans"}), encoding="utf-8")
    _make_db(d / "history.db", ["alpha", "beta"])
    _make_db(d / "pdf_cache.db", ["cache"])
    (d / "llm_timing.json").write_text("{}", encoding="utf-8")
    (d / "model").mkdir()
    (d / "model" / "classifier.pkl").write_bytes(b"MODEL")
    # Caches, die NICHT ins Backup gehoeren
    (d / "thumbnails").mkdir()
    (d / "thumbnails" / "x.png").write_bytes(b"PNG")
    (d / "logs").mkdir()
    (d / "logs" / "app.log").write_text("log", encoding="utf-8")
    (d / "launcher.cmd").write_text("rem", encoding="utf-8")
    return d


def test_create_backup_contains_data_but_not_caches(data_dir, tmp_path):
    zip_path = tmp_path / "out" / "b.zip"
    info = create_backup(data_dir, zip_path, version="0.22.0")

    assert zip_path.exists()
    assert set(info.entries) == {
        "config.json", "history.db", "pdf_cache.db", "llm_timing.json", "model/classifier.pkl",
    }
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert names == set(info.entries) | {INFO_NAME}
        meta = json.loads(zf.read(INFO_NAME))
    assert meta["version"] == "0.22.0"
    assert meta["entries"] == info.entries
    assert info.total_bytes > 0


def test_sqlite_snapshot_is_consistent_while_connection_is_open(data_dir, tmp_path):
    # Offene Verbindung mit unbestaetigter Aenderung: Backup sieht nur den Commit-Stand
    conn = sqlite3.connect(str(data_dir / "history.db"))
    conn.execute("INSERT INTO t VALUES ('uncommitted')")
    try:
        info = create_backup(data_dir, tmp_path / "b.zip")
    finally:
        conn.rollback()
        conn.close()
    with zipfile.ZipFile(info.path) as zf:
        zf.extract("history.db", tmp_path / "x")
    assert _rows(tmp_path / "x" / "history.db") == ["alpha", "beta"]


def test_create_backup_without_data_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        create_backup(empty, tmp_path / "b.zip")


def test_inspect_backup_reads_info_and_rejects_foreign_zip(data_dir, tmp_path):
    created = create_backup(data_dir, tmp_path / "b.zip", version="0.22.0")
    info = inspect_backup(tmp_path / "b.zip")
    assert info.version == "0.22.0"
    assert info.created_at == created.created_at
    assert info.created_display == created.created_at[:16].replace("T", " ")
    assert set(info.entries) == set(created.entries)

    foreign = tmp_path / "foreign.zip"
    with zipfile.ZipFile(foreign, "w") as zf:
        zf.writestr("readme.txt", "hi")
        zf.writestr("../evil.db", "x")
    with pytest.raises(ValueError):
        inspect_backup(foreign)
    (tmp_path / "not.zip").write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError):
        inspect_backup(tmp_path / "not.zip")


def test_stage_and_apply_restore_replaces_files_and_keeps_previous(data_dir, tmp_path):
    zip_path = tmp_path / "b.zip"
    create_backup(data_dir, zip_path)

    # Danach veraendert sich der Bestand ...
    _make_db(tmp_path / "new.db", ["gamma"])
    (tmp_path / "new.db").replace(data_dir / "history.db")
    (data_dir / "config.json").write_text("{}", encoding="utf-8")
    (data_dir / "model" / "classifier.pkl").write_bytes(b"NEWMODEL")

    info = stage_restore(zip_path, data_dir)
    pending = data_dir / PENDING_DIR
    assert (pending / "history.db").exists()
    assert (pending / "model" / "classifier.pkl").read_bytes() == b"MODEL"
    assert INFO_NAME not in {p.name for p in pending.iterdir()}
    assert "history.db" in info.entries

    restored = apply_pending_restore(data_dir)
    assert set(restored) == {"config.json", "history.db", "pdf_cache.db", "llm_timing.json", "model"}
    assert not pending.exists()
    assert _rows(data_dir / "history.db") == ["alpha", "beta"]
    assert json.loads((data_dir / "config.json").read_text(encoding="utf-8")) == {"scan_folder": "C:/Scans"}
    assert (data_dir / "model" / "classifier.pkl").read_bytes() == b"MODEL"
    # Ersetzte Dateien bleiben erhalten
    previous = data_dir / PREVIOUS_DIR
    assert _rows(previous / "history.db") == ["gamma"]
    assert (previous / "model" / "classifier.pkl").read_bytes() == b"NEWMODEL"
    # Caches unangetastet
    assert (data_dir / "thumbnails" / "x.png").exists()


def test_apply_without_pending_is_noop(data_dir):
    assert apply_pending_restore(data_dir) == []
    (data_dir / PENDING_DIR).mkdir()
    assert apply_pending_restore(data_dir) == []
    assert not (data_dir / PENDING_DIR).exists()


def test_stage_restore_replaces_older_pending(data_dir, tmp_path):
    zip_path = tmp_path / "b.zip"
    create_backup(data_dir, zip_path)
    pending = data_dir / PENDING_DIR
    pending.mkdir()
    (pending / "stale.txt").write_text("alt", encoding="utf-8")
    stage_restore(zip_path, data_dir)
    assert not (pending / "stale.txt").exists()


def test_default_backup_name():
    from datetime import datetime
    assert default_backup_name(datetime(2026, 8, 29, 18, 30)) == "PDF_Sortier_Meister_Backup_2026-08-29_1830.zip"

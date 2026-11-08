"""Tests fuer die pdfs-Master-Tabelle (Issue #25 / Phase 1).

Die Master-Tabelle bildet eine physische PDF auf eine stabile UUID
ab, die Verschieben und Umbenennen ueberlebt. Diese Tests pruefen:
    * get_or_create_pdf_id ist idempotent
    * get_pdf_by_path liefert None / Dict korrekt
    * update_pdf_metadata aktualisiert file_path/filename und last_seen_at
    * update_pdf_metadata legt einen fehlenden Eintrag neu an (UPSERT)
    * update_pdf_path migriert pdfs-Eintrag konsistent mit dem Suchindex
    * search_documents liefert pdf_id im Result (Phase 2)
    * pdf_id ist stabil ueber Re-Indizierung hinweg (Phase 2)
    * search_documents akzeptiert pdf_id als Filter (Phase 2)
    * die alte FTS5-Tabelle ``document_search`` wird einmalig in den Suchindex
      uebernommen und dann entfernt (Phase 5 der PDFsuche-Integration)
"""

import sqlite3
import uuid
from pathlib import Path

import fitz
import pytest

from src.search.konfig import norm_pfad
from src.utils.database import Database


def _pdf(path: Path, text: str) -> Path:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()
    return path


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


# === Phase 2 (Issue #25): pdf_id in FTS5 document_search ===

def test_search_documents_returns_pdf_id(tmp_path: Path) -> None:
    """search_documents liefert fuer jeden Treffer eine pdf_id im Result-Dict.

    Phase 2 (Issue #25): pdf_id ist neu im Result, kommt aus der
    pdfs-Master-Tabelle. Bestehende Keys (file_path, filename, ...)
    bleiben erhalten.
    """
    db = _make_db(tmp_path)
    db.index_document(
        "/tmp/x.pdf", "x.pdf", "Inhalt X",
        korrespondent="FirmaX", kategorie="Rechnung",
    )
    db.index_document(
        "/tmp/y.pdf", "y.pdf", "Inhalt Y",
        korrespondent="FirmaY", kategorie="Vertrag",
    )
    results = db.search_documents("Inhalt")
    assert len(results) == 2
    for r in results:
        # pdf_id vorhanden und 32-Zeichen Hex-UUID
        assert "pdf_id" in r
        assert len(r["pdf_id"]) == 32
        uuid.UUID(hex=r["pdf_id"])
        # Bestehende Felder unveraendert vorhanden
        assert r["file_path"]
        assert r["filename"]
        # pdf_id stimmt mit dem Master-Eintrag ueberein (dort steht der Pfad wie uebergeben)
        master = db.get_pdf_by_path("/tmp/" + r["filename"])
        assert master is not None
        assert master["pdf_id"] == r["pdf_id"]


def test_search_documents_pdf_id_is_stable_across_reindex(tmp_path: Path) -> None:
    """pdf_id bleibt stabil, auch wenn das Dokument neu indiziert wird.

    Phase 2 (Issue #25): Re-Index (gleicher file_path, andere Inhalte)
    darf die pdf_id nicht aendern, da sie der stabile Identitaetsanker
    ueber die Lebensdauer einer PDF-Datei ist.
    """
    db = _make_db(tmp_path)
    db.index_document(
        "/tmp/stable.pdf", "stable.pdf", "Erste Version",
        korrespondent="StabilAG",
    )
    first = db.search_documents("Erste")
    assert len(first) == 1
    pid_first = first[0]["pdf_id"]

    # Re-Index: gleicher Pfad, anderer Inhalt
    db.index_document(
        "/tmp/stable.pdf", "stable.pdf", "Zweite Version",
        korrespondent="StabilAG",
    )
    second = db.search_documents("Zweite")
    assert len(second) == 1
    pid_second = second[0]["pdf_id"]
    assert pid_first == pid_second
    assert second[0]["file_path"] == norm_pfad("/tmp/stable.pdf")

    # Master-Tabelle hat konsistent dieselbe pdf_id
    master = db.get_pdf_by_path("/tmp/stable.pdf")
    assert master is not None
    assert master["pdf_id"] == pid_first


def test_search_documents_filter_by_pdf_id(tmp_path: Path) -> None:
    """search_documents akzeptiert pdf_id als exakten Filter.

    Phase 2 (Issue #25): Optionaler pdf_id-Filter. Erwartet wird,
    dass nur Treffer mit der angegebenen pdf_id zurueckkommen
    (rueckwaertskompatibel: ohne Filter funktioniert weiter alles).
    """
    db = _make_db(tmp_path)
    db.index_document(
        "/tmp/filter_a.pdf", "filter_a.pdf", "alpha bravo",
        korrespondent="FilterA",
    )
    db.index_document(
        "/tmp/filter_b.pdf", "filter_b.pdf", "alpha charlie",
        korrespondent="FilterB",
    )

    # Ohne Filter: beide Treffer
    both = db.search_documents("alpha")
    assert len(both) == 2

    # pdf_id von Treffer A holen
    a_entry = next(r for r in both if r["filename"] == "filter_a.pdf")
    pid_a = a_entry["pdf_id"]

    # Mit pdf_id-Filter: nur A
    only_a = db.search_documents("alpha", pdf_id=pid_a)
    assert len(only_a) == 1
    assert only_a[0]["filename"] == "filter_a.pdf"
    assert only_a[0]["pdf_id"] == pid_a

    # Mit unbekannter pdf_id: leeres Result
    empty = db.search_documents("alpha", pdf_id=uuid.uuid4().hex)
    assert empty == []

    # Reines Filter-Query (kein Text) nur mit pdf_id liefert den Eintrag
    pure_filter = db.search_documents("", pdf_id=pid_a)
    assert len(pure_filter) == 1
    assert pure_filter[0]["pdf_id"] == pid_a


def _legacy_db(db_path: Path, rows: list[tuple], mit_pdf_id: bool = False) -> None:
    """``history.db`` mit der FTS5-Tabelle ``document_search`` (Stand v0.23) anlegen."""
    conn = sqlite3.connect(str(db_path))
    spalten = ("pdf_id UNINDEXED, " if mit_pdf_id else "") + (
        "file_path, filename, extracted_text, keywords, korrespondent, kategorie, steuerjahr, betrag, "
        "zusammenfassung, target_folder")
    conn.execute(f"CREATE VIRTUAL TABLE document_search USING fts5({spalten}, tokenize='unicode61')")
    n = 11 if mit_pdf_id else 10
    conn.executemany(f"INSERT INTO document_search VALUES ({','.join('?' * n)})", rows)
    conn.commit()
    conn.close()


def test_uebernahme_document_search_in_den_suchindex(tmp_path: Path) -> None:
    """Die alte Tabelle wird beim ersten Start in den Suchindex uebernommen und entfernt (Phase 5).

    Zeilen mit vorhandener Datei behalten Metadaten (Quelle 'pdfsm') und den alten
    Text als Notnagel, bis der naechste Lauf die Datei liest; Zeilen ohne Datei
    werden verworfen. Der zweite Start findet keine Tabelle mehr vor.
    """
    db_path = tmp_path / "legacy.db"
    vorhanden = _pdf(tmp_path / "legacy_a.pdf", "Neuer Text aus der Datei")
    _legacy_db(db_path, [
        (str(vorhanden), "legacy_a.pdf", "Legacy Inhalt A", "kw1,kw2", "LegacyFirma", "Rechnung", "2023",
         "42.00", "Legacy Zsam A", "/legacy/folder"),
        ("/legacy/weg.pdf", "weg.pdf", "Legacy Inhalt B", "", "WegFirma", "Rechnung", "2022", "1.00", "", ""),
    ])

    db = Database(db_path)

    conn = sqlite3.connect(str(db_path))
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'document_search'").fetchone() is None
    conn.close()
    results = db.search_documents("Legacy")
    assert [r["filename"] for r in results] == ["legacy_a.pdf"]
    r = results[0]
    assert r["file_path"] == str(vorhanden)
    assert r["korrespondent"] == "LegacyFirma" and r["kategorie"] == "Rechnung"
    assert r["steuerjahr"] == "2023" and r["betrag"] == "42.00" and r["keywords"] == "kw1,kw2"
    assert len(r["pdf_id"]) == 32
    uuid.UUID(hex=r["pdf_id"])
    master = db.get_pdf_by_path(str(vorhanden))
    assert master is not None and master["pdf_id"] == r["pdf_id"]
    eintrag = db.suchindex.dokument_nach_pfad(str(vorhanden))
    assert eintrag["textstatus"] == "ausstehend" and eintrag["metadaten_quelle"] == "pdfsm"
    assert db.get_search_index_count() == 1

    # Der naechste Lauf liest die Datei: Text aus der Datei, Metadaten bleiben
    assert db.suchindex.datei_geaendert(str(vorhanden)) is not None
    eintrag = db.suchindex.dokument_nach_pfad(str(vorhanden))
    assert eintrag["textstatus"] == "text" and eintrag["korrespondent"] == "LegacyFirma"
    assert db.search_documents("Neuer") and not db.search_documents("Legacy Inhalt")

    # Idempotent: ein zweites Database-Init darf nicht crashen und nichts doppeln
    db2 = Database(db_path)
    assert db2.get_search_index_count() == 1


def test_uebernahme_verwendet_vorhandene_pdf_id(tmp_path: Path) -> None:
    """Die Uebernahme nutzt die pdf_id der alten Zeile bzw. des pdfs-Eintrags (kein Doppel-Insert)."""
    db_path = tmp_path / "preexisting.db"
    pre_pid = uuid.uuid4().hex
    datei = _pdf(tmp_path / "pre_a.pdf", "Pre content")
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE pdfs (
            pdf_id TEXT PRIMARY KEY,
            file_path TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL,
            indexed_at TEXT,
            last_seen_at TEXT,
            size_bytes INTEGER,
            page_count INTEGER
        )
    """)
    conn.execute("INSERT INTO pdfs VALUES (?, ?, ?, ?, ?, NULL, NULL)",
                 (pre_pid, str(datei), "pre_a.pdf", "2024-01-01", "2024-01-01"))
    conn.commit()
    conn.close()
    _legacy_db(db_path, [(str(datei), "pre_a.pdf", "Pre content", "kw", "PreFirma", "Kat", "2024", "10.00", "Zsam",
                          "/pre/folder")])

    db = Database(db_path)
    results = db.search_documents("Pre")
    assert len(results) == 1
    assert results[0]["pdf_id"] == pre_pid
    master = db.get_pdf_by_path(str(datei))
    assert master is not None and master["pdf_id"] == pre_pid


def test_update_pdf_path_ziel_mit_veraltetem_eintrag(tmp_path: Path) -> None:
    """Live-Test 2026-11-08: am Zielpfad stand noch der Eintrag einer frueheren Datei.

    Vorher scheiterte das Umtragen an UNIQUE(file_path) - und weil die Ausnahme alles
    abbrach, bekam auch der Suchindex das Verschieben nicht mit.
    """
    db = _make_db(tmp_path)
    pid = db.get_or_create_pdf_id("/src/a.pdf", "a.pdf")
    alt = db.get_or_create_pdf_id("/dst/a.pdf", "a.pdf")
    assert alt != pid

    assert db.update_pdf_path("/src/a.pdf", "/dst/a.pdf", "a.pdf") is True
    entry = db.get_pdf_by_path("/dst/a.pdf")
    assert entry["pdf_id"] == pid
    assert db.get_pdf_by_path("/src/a.pdf") is None


def test_update_pdf_path_nur_ziel_bekannt(tmp_path: Path) -> None:
    """Kennt ``pdfs`` die Datei nur unter dem neuen Pfad, wird dieser Eintrag weitergefuehrt."""
    db = _make_db(tmp_path)
    pid = db.get_or_create_pdf_id("/dst/b.pdf", "b.pdf")

    assert db.update_pdf_path("/src/b.pdf", "/dst/b.pdf", "b.pdf") is True
    assert db.get_pdf_by_path("/dst/b.pdf")["pdf_id"] == pid
    assert db.get_pdf_by_path("/src/b.pdf") is None


def test_update_pdf_path_ziel_konflikt_suchindex_zieht_mit(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    quelle = _pdf(tmp_path / "quelle.pdf", "Auftrag Balkonabdichtung")
    ziel = tmp_path / "ablage" / "quelle.pdf"
    ziel.parent.mkdir()
    db.suchindex.datei_aufnehmen(str(quelle))
    db.get_or_create_pdf_id(str(quelle), quelle.name)
    db.get_or_create_pdf_id(str(ziel), ziel.name)  # veralteter Eintrag
    quelle.rename(ziel)

    assert db.update_pdf_path(str(quelle), str(ziel), ziel.name) is True
    assert db.suchindex.dokument_nach_pfad(str(ziel)) is not None
    assert db.suchindex.dokument_nach_pfad(str(quelle)) is None

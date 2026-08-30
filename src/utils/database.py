"""
Datenbank-Modul für PDF Sortier Meister

Speichert die Sortierhistorie für das lernfähige Klassifikationssystem.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Float
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool

from src.utils.config import get_config

Base = declarative_base()


class SortingHistory(Base):
    """Tabelle für die Sortierhistorie."""

    __tablename__ = "sorting_history"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Originale PDF-Informationen
    original_filename = Column(String(500), nullable=False)
    original_path = Column(String(1000), nullable=False)

    # Extrahierter Text (für Ähnlichkeitssuche)
    extracted_text = Column(Text, nullable=True)

    # Erkannte Merkmale
    keywords = Column(String(500), nullable=True)  # Komma-getrennt
    detected_date = Column(String(50), nullable=True)

    # Zielordner (das Lernziel)
    target_folder = Column(String(1000), nullable=False)
    target_folder_name = Column(String(255), nullable=False)

    # NEU: Relativer Pfad für hierarchische Struktur (z.B. "Steuer 2026/Banken")
    target_relative_path = Column(String(1000), nullable=True)

    # Neuer Dateiname (falls umbenannt)
    new_filename = Column(String(500), nullable=True)

    # Dokument-Metadaten (Phase 16)
    korrespondent = Column(String(500), nullable=True)    # Firmenname/Absender
    betrag = Column(String(50), nullable=True)            # Rechnungsbetrag (legacy)
    betrag_netto = Column(String(50), nullable=True)      # Nettobetrag
    betrag_brutto = Column(String(50), nullable=True)     # Bruttobetrag
    iban = Column(String(50), nullable=True)              # IBAN des Absenders
    waehrung = Column(String(10), nullable=True)          # EUR/USD
    mwst_satz = Column(String(10), nullable=True)         # 7 / 19
    steuerjahr = Column(String(10), nullable=True)        # z.B. "2024"
    steuerlich_absetzbar = Column(String(20), nullable=True)  # ja/nein/teilweise
    kategorie = Column(String(100), nullable=True)        # Rechnung/Vertrag/etc.
    zusammenfassung = Column(String(1000), nullable=True)  # Kurzbeschreibung

    # System-Metadaten
    created_at = Column(DateTime, default=datetime.utcnow)
    confidence = Column(Float, default=1.0)  # 1.0 = Benutzerentscheidung


class TargetFolder(Base):
    """Tabelle für Zielordner mit Statistiken."""

    __tablename__ = "target_folders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(String(1000), nullable=False, unique=True)
    name = Column(String(255), nullable=False)

    # NEU: Relativer Pfad für hierarchische Struktur
    relative_path = Column(String(1000), nullable=True)
    # NEU: Übergeordneter Ordner (für Hierarchie-Lernen)
    parent_path = Column(String(1000), nullable=True)

    usage_count = Column(Integer, default=0)
    last_used = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class RenameHistory(Base):
    """Tabelle für die Umbenennungshistorie (zum Lernen von Mustern)."""

    __tablename__ = "rename_history"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Original- und neuer Dateiname
    original_filename = Column(String(500), nullable=False)
    new_filename = Column(String(500), nullable=False)

    # Kontext aus der PDF
    extracted_text = Column(Text, nullable=True)
    keywords = Column(String(500), nullable=True)  # Komma-getrennt
    detected_date = Column(String(50), nullable=True)

    # Zielordner (falls beim Umbenennen bekannt)
    target_folder = Column(String(1000), nullable=True)

    # Metadaten
    created_at = Column(DateTime, default=datetime.utcnow)


class KorrespondentMetadata(Base):
    """Gelernte Metadaten-Zuordnungen pro Korrespondent.

    Wenn ein Nutzer Metadaten für einen Korrespondenten korrigiert
    (z.B. "ista" → Kategorie "Hausverwaltung" statt "Energie"),
    wird diese Zuordnung gespeichert und bei künftigen Dokumenten
    desselben Absenders automatisch angewendet.
    """

    __tablename__ = "korrespondent_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    korrespondent = Column(String(500), nullable=False, unique=True)

    # Gelernte Metadaten-Felder
    kategorie = Column(String(100), nullable=True)
    waehrung = Column(String(10), nullable=True)
    mwst_satz = Column(String(10), nullable=True)
    steuerlich_absetzbar = Column(String(20), nullable=True)

    # Tracking
    usage_count = Column(Integer, default=1)
    updated_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class Korrespondent(Base):
    """Verwaltungstabelle fuer bekannte Korrespondenten (Phase 20 / Issue #21).

    Separates Konzept zu ``KorrespondentMetadata`` (gelernte Defaults pro
    Korrespondent): diese Tabelle haelt kuratierte Stammdaten
    (Name, Aliasse, Kategorie, Farbe, Notizen) und ist die
    Hauptansicht der Sidebar in der GUI.

    Felder:
        id: Primaerschluessel
        name: Anzeigename (eindeutig)
        aliases: JSON-Liste alternativer Namen (z.B. '["ista", "IST"]')
        kategorie: Zuordnung (Energie, Versicherung, Telekommunikation, Steuer, Sonstiges)
        farbe: Hex-String fuer Sidebar-Markierung (z.B. "#FF5733")
        notizen: Freitext
        usage_count: Wie oft der Korrespondent in sorting_history vorkam
        created_at/updated_at: Zeitstempel
    """

    __tablename__ = "korrespondenten"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(500), nullable=False, unique=True)
    aliases = Column(Text, nullable=True)  # JSON-String
    kategorie = Column(String(100), nullable=True)
    farbe = Column(String(20), nullable=True)
    notizen = Column(Text, nullable=True)
    usage_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class AutomationRule(Base):
    """Regeln fuer automatische Sortierung (Phase 21 / Issue #22).

    Bedingungen (``conditions_json``) und Aktionen (``actions_json``)
    werden als JSON-Listen persistiert und vom ``RuleEngine`` ausgewertet.

    Felder:
        id: Primaerschluessel
        name: Anzeigename (eindeutig)
        priority: Hoeher = wichtiger (fuer Sortierung in evaluate())
        enabled: Deaktivierte Regeln werden uebersprungen
        conditions_json: JSON-String der Bedingungs-Liste
        actions_json: JSON-String der Aktions-Liste
        created_at/updated_at: Zeitstempel
    """

    __tablename__ = "automation_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    priority = Column(Integer, default=0)
    enabled = Column(Integer, default=1)  # 0/1 (SQLite hat kein BOOLEAN)
    conditions_json = Column(Text, nullable=True)
    actions_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class PDFMaster(Base):
    """Master-Tabelle fuer eindeutige PDF-Identitaet (Issue #25 / Phase 1).

    Bildet eine physische PDF-Datei ueber ihren Lebenszyklus (Index,
    Verschieben, Umbenennen) auf eine stabile ``pdf_id`` (UUID) ab.
    ``file_path`` und ``filename`` werden bei Moves aktualisiert;
    die ``pdf_id`` bleibt konstant und ist der primaere Schluessel
    fuer Verknuepfungen mit anderen Tabellen (LLM-Cache, Historie, etc.).

    Felder:
        pdf_id: Primaerschluessel (UUID als Hex-String)
        file_path: Aktueller absoluter Pfad (eindeutig; aendert sich bei Move)
        filename: Aktueller Dateiname (aendert sich bei Rename)
        indexed_at: ISO-Datetime der ersten Indizierung
        last_seen_at: ISO-Datetime der letzten Sichtung (Move/Rename)
        size_bytes: Dateigroesse in Bytes (optional)
        page_count: Seitenzahl (optional)
    """

    __tablename__ = "pdfs"

    pdf_id = Column(String(36), primary_key=True, nullable=False)
    file_path = Column(String(2000), nullable=False, unique=True)
    filename = Column(String(500), nullable=False)
    indexed_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    size_bytes = Column(Integer, nullable=True)
    page_count = Column(Integer, nullable=True)




# Maximale Laenge des extrahierten Textes pro Row in document_search
# (RAG-Chat / Phase 19 / Architektur-Entscheidung Q3).
MAX_EXTRACTED_TEXT_LENGTH = 5000


def _truncate_extracted_text(text, max_len: int = MAX_EXTRACTED_TEXT_LENGTH):
    """Begrenzt den FTS5-indexierten Text auf ``max_len`` Zeichen.

    Verhindert, dass sehr grosse PDFs das DB-Wachstum und den
    Token-Verbrauch im RAG-Retrieval sprengen.
    """
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "...[truncated]"




class Database:
    """Datenbankverbindung und -operationen."""

    def __init__(self, db_path: Path = None):
        """
        Initialisiert die Datenbankverbindung.

        Args:
            db_path: Pfad zur SQLite-Datenbank. Standard: aus Config.
        """
        if db_path is None:
            config = get_config()
            db_path = config.database_path

        self.db_path = db_path
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        # Tabellen erstellen
        Base.metadata.create_all(self.engine)

        # Migration: Neue Spalten hinzufügen (falls nicht vorhanden)
        self._migrate_database()

        # FTS5-Volltextsuche erstellen (Phase 17)
        self._create_fts_index()

        # Session-Factory
        self.Session = sessionmaker(bind=self.engine)

    def get_session(self):
        """Erstellt eine neue Datenbank-Session."""
        return self.Session()

    def _migrate_database(self):
        """
        Führt Datenbank-Migrationen durch.

        Fügt neue Spalten hinzu, falls sie in einer älteren Datenbank fehlen.
        """
        from sqlalchemy import text

        with self.engine.connect() as conn:
            # Pruefen und fuege fehlende Spalten hinzu
            migrations = [
                # (Tabelle, Spalte, SQL-Typ)
                ("sorting_history", "target_relative_path", "VARCHAR(1000)"),
                ("target_folders", "relative_path", "VARCHAR(1000)"),
                ("target_folders", "parent_path", "VARCHAR(1000)"),
                # Phase 16: Dokument-Metadaten
                ("sorting_history", "korrespondent", "VARCHAR(500)"),
                ("sorting_history", "betrag", "VARCHAR(50)"),
                ("sorting_history", "waehrung", "VARCHAR(10)"),
                ("sorting_history", "mwst_satz", "VARCHAR(10)"),
                ("sorting_history", "steuerjahr", "VARCHAR(10)"),
                ("sorting_history", "steuerlich_absetzbar", "VARCHAR(20)"),
                ("sorting_history", "kategorie", "VARCHAR(100)"),
                ("sorting_history", "zusammenfassung", "VARCHAR(1000)"),
                # Phase 18: Buchhaltungsfelder
                ("sorting_history", "betrag_netto", "VARCHAR(50)"),
                ("sorting_history", "betrag_brutto", "VARCHAR(50)"),
                ("sorting_history", "iban", "VARCHAR(50)"),
            ]

            for table, column, sql_type in migrations:
                try:
                    # Pruefen ob Spalte existiert
                    result = conn.execute(text(f"PRAGMA table_info({table})"))
                    columns = [row[1] for row in result.fetchall()]

                    if column not in columns:
                        # Spalte hinzufuegen
                        conn.execute(text(
                            f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
                        ))
                        conn.commit()
                        print(f"Migration: Spalte '{column}' zu '{table}' hinzugefügt")
                except Exception as e:
                    print(f"Migration-Warnung für {table}.{column}: {e}")

            # Phase 20 (Issue #21): Korrespondenten-Verwaltungstabelle.
            # Base.metadata.create_all() legt die Tabelle fuer NEUE Datenbanken
            # automatisch an, aber als idempotente Sicherheitsmassnahme
            # fuer bestehende Datenbanken (z.B. externe SQLite-Files, die
            # nicht von Base.metadata.create_all() erfasst wurden) hier
            # nochmal explizit CREATE TABLE IF NOT EXISTS.
            try:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS korrespondenten (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(500) NOT NULL UNIQUE,
                        aliases TEXT,
                        kategorie VARCHAR(100),
                        farbe VARCHAR(20),
                        notizen TEXT,
                        usage_count INTEGER DEFAULT 0,
                        created_at DATETIME,
                        updated_at DATETIME
                    )
                """))
                conn.commit()
            except Exception as e:
                print(f"Migration-Warnung fuer korrespondenten-Tabelle: {e}")

            # Phase 21 (Issue #22): Automatisierungs-Regeln fuer die
            # RuleEngine. Idempotente Anlage auch fuer externe DBs.
            try:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS automation_rules (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(255) NOT NULL UNIQUE,
                        priority INTEGER DEFAULT 0,
                        enabled INTEGER DEFAULT 1,
                        conditions_json TEXT,
                        actions_json TEXT,
                        created_at DATETIME,
                        updated_at DATETIME
                    )
                """))
                conn.commit()
            except Exception as e:
                print(f"Migration-Warnung fuer automation_rules-Tabelle: {e}")

            # Phase 1 (Issue #25): Master-Tabelle fuer PDF-Identitaet.
            # Jede indizierte PDF erhaelt eine stabile UUID (pdf_id), die
            # Verschieben und Umbenennen ueberlebt. file_path/filename
            # werden bei Moves aktualisiert (idempotente Anlage).
            try:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS pdfs (
                        pdf_id TEXT PRIMARY KEY,
                        file_path TEXT UNIQUE NOT NULL,
                        filename TEXT NOT NULL,
                        indexed_at TEXT,
                        last_seen_at TEXT,
                        size_bytes INTEGER,
                        page_count INTEGER
                    )
                """))
                conn.commit()
            except Exception as e:
                print(f"Migration-Warnung fuer pdfs-Tabelle: {e}")

    # Volltext-Suchindex-Schemata (Phase 17 / Issue #25 Phase 2).
    # Die ``document_search``-Tabelle hat in Phase 2 eine zusaetzliche
    # ``pdf_id``-Spalte (UNINDEXED) als Verknuepfung zur ``pdfs``-
    # Master-Tabelle. ``file_path`` bleibt in der Tabelle, damit
    # bestehende search_documents-Aufrufer unveraendert funktionieren.
    # Aeltere DBs (vor Phase 2) muessen migriert werden.
    _FTS5_NEW_SCHEMA: str = """
        CREATE VIRTUAL TABLE document_search
        USING fts5(
            pdf_id UNINDEXED,
            file_path,
            filename,
            extracted_text,
            keywords,
            korrespondent,
            kategorie,
            steuerjahr,
            betrag,
            zusammenfassung,
            target_folder,
            tokenize='unicode61'
        )
    """

    def _create_fts_index(self):
        """Erstellt die FTS5-Volltextsuche-Tabelle (Phase 17).

        Delegiert an ``_migrate_document_search`` (Phase 2 / Issue #25),
        das idempotent sowohl neue Datenbanken mit dem aktuellen
        Schema anlegt als auch bestehende Datenbanken von der
        Phase-1-Schema-Version migriert.
        """
        self._migrate_document_search()

    def _migrate_document_search(self) -> None:
        """Stellt sicher, dass die FTS5-Tabelle das aktuelle Schema hat.

        Drei Faelle (alle idempotent):

        1. Tabelle existiert nicht:
           - CREATE VIRTUAL TABLE mit aktuellem Schema (inkl. ``pdf_id``)
        2. Tabelle existiert und hat bereits eine ``pdf_id``-Spalte:
           - Nichts tun (Migration bereits gelaufen)
        3. Tabelle existiert ohne ``pdf_id``-Spalte (Phase-1-Schema):
           - ALTER TABLE RENAME -> ``document_search_v1``
           - CREATE VIRTUAL TABLE mit aktuellem Schema
           - Datenmigration: fuer jede Zeile aus ``document_search_v1``
             wird die ``pdf_id`` aus ``pdfs`` (per ``file_path``)
             nachgeschlagen oder eine neue UUID angelegt.
           - ``document_search_v1`` wird gedroppt.

        Die Migration laeuft in einer einzigen Transaktion, damit bei
        einem Fehler kein halbfertiger Zustand zurueckbleibt.
        """
        import sqlite3

        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.cursor()

            # 1) Existiert die Tabelle ueberhaupt?
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='document_search'"
            )
            table_exists = cursor.fetchone() is not None

            if not table_exists:
                # Frische Datenbank: aktuelles Schema anlegen.
                cursor.execute(self._FTS5_NEW_SCHEMA)
                conn.commit()
                return

            # 2) Hat die existierende Tabelle schon eine pdf_id-Spalte?
            cursor.execute("PRAGMA table_info(document_search)")
            columns = [row[1] for row in cursor.fetchall()]
            if "pdf_id" in columns:
                # Schema ist aktuell: nichts tun.
                return

            # 3) Migration vom alten (Phase-1-)Schema auf neues Schema.
            # Alles in einer Transaktion.
            cursor.execute("BEGIN")
            try:
                cursor.execute(
                    "ALTER TABLE document_search RENAME TO document_search_v1"
                )
                cursor.execute(self._FTS5_NEW_SCHEMA)

                # Datenmigration: pro Zeile aus v1 die pdf_id
                # nachschlagen (per file_path in pdfs) oder neu erzeugen.
                cursor.execute(
                    "SELECT rowid, file_path, filename, extracted_text, "
                    "keywords, korrespondent, kategorie, steuerjahr, "
                    "betrag, zusammenfassung, target_folder "
                    "FROM document_search_v1"
                )
                now_iso = datetime.utcnow().isoformat()
                for v1_row in cursor.fetchall():
                    (
                        _v1_rowid,
                        v1_path,
                        v1_filename,
                        v1_text,
                        v1_kw,
                        v1_korr,
                        v1_kat,
                        v1_jahr,
                        v1_betrag,
                        v1_zus,
                        v1_folder,
                    ) = v1_row

                    # pdf_id aus Master-Tabelle (Phase 1) holen oder neu anlegen.
                    pdfs_row = self._get_pdf_row_by_path(cursor, v1_path)
                    if pdfs_row is not None:
                        pdf_id = pdfs_row[0]
                    else:
                        pdf_id = self._ensure_pdf_id(
                            cursor,
                            v1_path,
                            v1_filename or Path(v1_path).name if v1_path else "",
                            None,
                            now_iso,
                        )

                    cursor.execute(
                        "INSERT INTO document_search "
                        "(pdf_id, file_path, filename, extracted_text, keywords, "
                        "korrespondent, kategorie, steuerjahr, betrag, "
                        "zusammenfassung, target_folder) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            pdf_id,
                            v1_path or "",
                            v1_filename or "",
                            v1_text or "",
                            v1_kw or "",
                            v1_korr or "",
                            v1_kat or "",
                            v1_jahr or "",
                            v1_betrag or "",
                            v1_zus or "",
                            v1_folder or "",
                        ),
                    )

                cursor.execute("DROP TABLE document_search_v1")
                cursor.execute("COMMIT")
            except Exception:
                cursor.execute("ROLLBACK")
                raise
        except Exception as e:
            print(f"FTS5-Migration Warnung: {e}")
        finally:
            conn.close()

    # === Volltextsuche (Phase 17) ===

    def index_document(
        self,
        file_path: str,
        filename: str,
        extracted_text: str = "",
        keywords: str = "",
        korrespondent: str = "",
        kategorie: str = "",
        steuerjahr: str = "",
        betrag: str = "",
        zusammenfassung: str = "",
        target_folder: str = "",
    ):
        """
        Fügt ein Dokument zum Volltext-Suchindex hinzu.

        Wird beim Verschieben/Sortieren aufgerufen, damit das Dokument
        später per Suche gefunden werden kann.

        Phase 2 (Issue #25): Vor dem INSERT in ``document_search`` wird
        ueber ``get_or_create_pdf_id`` sichergestellt, dass ein
        passender ``pdfs``-Master-Eintrag existiert. Die ``pdf_id``
        wird in der FTS5-Tabelle als UNINDEXED-Spalte persistiert,
        damit Suchergebnisse eine stabile Identitaet haben (ueberlebt
        Moves und Renames).
        """
        import sqlite3

        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Phase 2: stabile pdf_id aus Master-Tabelle (oder neu anlegen).
            pdf_id = self.get_or_create_pdf_id(file_path, filename)

            # Alten Eintrag für diesen Pfad löschen (falls vorhanden)
            cursor.execute(
                "DELETE FROM document_search WHERE file_path = ?",
                (file_path,)
            )

            # Neuen Eintrag einfügen (Phase 2: inkl. pdf_id)
            cursor.execute("""
                INSERT INTO document_search
                (pdf_id, file_path, filename, extracted_text, keywords,
                 korrespondent, kategorie, steuerjahr, betrag,
                 zusammenfassung, target_folder)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pdf_id, file_path, filename, _truncate_extracted_text(extracted_text or ""), keywords or "",
                korrespondent or "", kategorie or "", steuerjahr or "",
                betrag or "", zusammenfassung or "", target_folder or "",
            ))

            conn.commit()
            conn.close()
        except Exception as e:
            print(f"FTS5-Indexierung Fehler: {e}")

    def update_pdf_path(
        self,
        old_path: str,
        new_path: str,
        new_filename: str = None,
        extracted_text: str = None,
        keywords: str = None,
        korrespondent: str = None,
        kategorie: str = None,
        steuerjahr: str = None,
        betrag: str = None,
        zusammenfassung: str = None,
        target_folder: str = None,
    ) -> bool:
        """Verschiebt einen Suchindex-Eintrag atomar von old_path zu new_path.

        Felder aus dem alten Eintrag werden beibehalten; explizit übergebene
        Parameter überschreiben die kopierten Werte. Gibt True zurück wenn
        Daten migriert/angelegt wurden, False bei No-op.

        Phase 1 (Issue #25): Statt DELETE+INSERT wird der vorhandene Eintrag
        per UPDATE migriert, damit Metadaten und LLM-bezogene Felder
        erhalten bleiben. Die Master-Tabelle ``pdfs`` wird konsistent
        mitgepflegt (file_path/filename/last_seen_at aktualisiert).
        """
        import sqlite3

        if old_path == new_path and new_filename is None:
            return False

        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute(
                "SELECT rowid, filename, extracted_text, keywords, korrespondent, "
                "kategorie, steuerjahr, betrag, zusammenfassung, target_folder "
                "FROM document_search WHERE file_path = ?",
                (old_path,)
            )
            row = cursor.fetchone()

            # pdfs-Master-Eintrag (Lookup by old_path) - koennte bereits
            # durch get_or_create_pdf_id angelegt worden sein.
            pdfs_row = self._get_pdf_row_by_path(cursor, old_path)

            now_iso = datetime.utcnow().isoformat()

            if row is None:
                # Kein alter document_search-Eintrag: neuen anlegen,
                # ggf. pdfs-Master neu erzeugen oder den vorhandenen wiederverwenden.
                pdf_id = self._ensure_pdf_id(
                    cursor, old_path, new_filename, pdfs_row, now_iso
                )

                cursor.execute("""
                    INSERT INTO document_search
                    (pdf_id, file_path, filename, extracted_text, keywords,
                     korrespondent, kategorie, steuerjahr, betrag,
                     zusammenfassung, target_folder)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pdf_id,
                    new_path,
                    new_filename or Path(new_path).name,
                    _truncate_extracted_text(extracted_text or ""),
                    keywords or "",
                    korrespondent or "",
                    kategorie or "",
                    steuerjahr or "",
                    betrag or "",
                    zusammenfassung or "",
                    target_folder or "",
                ))

                # pdfs-Pfad konsistent halten (kann alter Pfad gewesen sein)
                if old_path != new_path or new_filename is not None:
                    self._update_pdf_master(
                        cursor, pdf_id, file_path=new_path,
                        filename=new_filename, now_iso=now_iso,
                    )

                conn.commit()
                conn.close()
                return True

            rowid, old_fn, old_text, old_kw, old_korr, old_kat, old_jahr, old_betrag, old_zus, old_folder = row

            final_filename = new_filename if new_filename is not None else old_fn
            final_text = extracted_text if extracted_text is not None else (old_text or "")
            final_kw = keywords if keywords is not None else (old_kw or "")
            final_korr = korrespondent if korrespondent is not None else (old_korr or "")
            final_kat = kategorie if kategorie is not None else (old_kat or "")
            final_jahr = steuerjahr if steuerjahr is not None else (old_jahr or "")
            final_betrag = betrag if betrag is not None else (old_betrag or "")
            final_zus = zusammenfassung if zusammenfassung is not None else (old_zus or "")
            final_folder = target_folder if target_folder is not None else (old_folder or "")

            # pdfs-Master-Eintrag: erzeugen falls fehlt, dann Pfad/Filename updaten.
            # Die ``pdf_id`` wird hier gleich mitermittelt, damit das
            # nachfolgende document_search-UPDATE sie in Phase 2 mitschreiben
            # kann (sonst waere der Eintrag nach dem Update ohne pdf_id).
            pdf_id = self._ensure_pdf_id(
                cursor, old_path, old_fn, pdfs_row, now_iso
            )

            # UPDATE statt DELETE+INSERT: Metadaten (z.B. LLM-Suggestionen)
            # bleiben erhalten. file_path/filename werden ueberschrieben;
            # explizit uebergebene Metadaten ueberschreiben die alten Werte.
            # Phase 2: ``pdf_id`` wird explizit mitgeschrieben.
            cursor.execute("""
                UPDATE document_search
                SET pdf_id = ?, file_path = ?, filename = ?, extracted_text = ?,
                    keywords = ?, korrespondent = ?, kategorie = ?, steuerjahr = ?,
                    betrag = ?, zusammenfassung = ?, target_folder = ?
                WHERE rowid = ?
            """, (
                pdf_id,
                new_path, final_filename,
                _truncate_extracted_text(final_text), final_kw,
                final_korr, final_kat, final_jahr, final_betrag,
                final_zus, final_folder,
                rowid,
            ))

            self._update_pdf_master(
                cursor, pdf_id, file_path=new_path,
                filename=new_filename, now_iso=now_iso,
            )

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            print(f"update_pdf_path Fehler: {e}")
            return False

    # === pdfs Master-Tabelle (Issue #25 / Phase 1) ===

    def _generate_pdf_id(self) -> str:
        """Erzeugt eine neue UUID fuer die pdfs-Master-Tabelle.

        Verwendet ``uuid.uuid4().hex`` (32 Zeichen ohne Bindestriche),
        das als PRIMARY KEY in ``pdfs`` dient. Hex-Form ist in
        Logs und URLs handlicher als die Standard-URN-Darstellung.
        """
        return uuid.uuid4().hex

    def get_or_create_pdf_id(self, file_path: str, filename: str) -> str:
        """Gibt die stabile ``pdf_id`` fuer ``file_path`` zurueck.

        Existiert bereits ein Eintrag in ``pdfs`` mit diesem Pfad,
        wird der vorhandene ``pdf_id`` ohne Update zurueckgegeben
        (idempotent). Andernfalls wird ein neuer Eintrag mit
        frischer UUID angelegt und ``indexed_at`` auf jetzt gesetzt.

        Args:
            file_path: Aktueller absoluter Pfad der PDF.
            filename: Aktueller Dateiname (zur Initial-Anlage).

        Returns:
            Die ``pdf_id`` (32-Zeichen-Hex-UUID) als String.
        """
        import sqlite3

        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT pdf_id FROM pdfs WHERE file_path = ?",
                (file_path,)
            )
            row = cursor.fetchone()
            if row is not None:
                return row[0]

            pdf_id = self._generate_pdf_id()
            now_iso = datetime.utcnow().isoformat()
            cursor.execute(
                "INSERT INTO pdfs (pdf_id, file_path, filename, indexed_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (pdf_id, file_path, filename, now_iso, now_iso),
            )
            conn.commit()
            return pdf_id

    def update_pdf_metadata(
        self,
        pdf_id: str,
        file_path: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> bool:
        """Aktualisiert ``file_path`` und/oder ``filename`` fuer eine ``pdf_id``.

        Setzt ``last_seen_at`` immer auf die aktuelle Zeit. Wenn
        ``pdf_id`` noch nicht existiert, wird ein neuer Eintrag mit
        ``indexed_at = last_seen_at = now`` angelegt (UPSERT-Verhalten
        fuer Edge-Cases, in denen ``get_or_create_pdf_id`` noch nicht
        gelaufen ist).

        Args:
            pdf_id: Primaerschluessel der Master-Tabelle.
            file_path: Optional, neuer Pfad.
            filename: Optional, neuer Dateiname.

        Returns:
            ``True`` bei Erfolg, ``False`` bei DB-Fehler.
        """
        import sqlite3

        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                now_iso = datetime.utcnow().isoformat()

                cursor.execute(
                    "SELECT 1 FROM pdfs WHERE pdf_id = ?",
                    (pdf_id,)
                )
                exists = cursor.fetchone() is not None

                if exists:
                    sets = ["last_seen_at = ?"]
                    params: list = [now_iso]
                    if file_path is not None:
                        sets.append("file_path = ?")
                        params.append(file_path)
                    if filename is not None:
                        sets.append("filename = ?")
                        params.append(filename)
                    params.append(pdf_id)
                    cursor.execute(
                        f"UPDATE pdfs SET {', '.join(sets)} WHERE pdf_id = ?",
                        params,
                    )
                else:
                    # UPSERT: neuen Eintrag anlegen
                    cursor.execute(
                        "INSERT INTO pdfs (pdf_id, file_path, filename, "
                        "indexed_at, last_seen_at) VALUES (?, ?, ?, ?, ?)",
                        (
                            pdf_id,
                            file_path if file_path is not None else "",
                            filename if filename is not None else "",
                            now_iso,
                            now_iso,
                        ),
                    )
                conn.commit()
                return True
        except Exception as e:
            print(f"update_pdf_metadata Fehler: {e}")
            return False

    def get_pdf_by_path(self, file_path: str) -> Optional[dict]:
        """Liefert den pdfs-Master-Eintrag fuer ``file_path`` als Dict.

        Args:
            file_path: Aktueller absoluter Pfad der PDF.

        Returns:
            Dict mit den Schluesseln ``pdf_id``, ``file_path``,
            ``filename``, ``indexed_at``, ``last_seen_at``,
            ``size_bytes``, ``page_count`` oder ``None`` falls
            kein Eintrag existiert.
        """
        import sqlite3

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT pdf_id, file_path, filename, indexed_at, last_seen_at, "
                "size_bytes, page_count FROM pdfs WHERE file_path = ?",
                (file_path,)
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "pdf_id": row["pdf_id"],
                "file_path": row["file_path"],
                "filename": row["filename"],
                "indexed_at": row["indexed_at"],
                "last_seen_at": row["last_seen_at"],
                "size_bytes": row["size_bytes"],
                "page_count": row["page_count"],
            }

    # === Interne Helfer fuer pdfs-Master (Issue #25 / Phase 1) ===

    @staticmethod
    def _get_pdf_row_by_path(cursor, file_path: str) -> Optional[tuple]:
        """Lookup in ``pdfs`` per ``file_path``. Gibt ``(pdf_id, filename)`` oder ``None`` zurueck.

        Wird intern von ``update_pdf_path`` verwendet, um zu entscheiden ob
        der Master-Eintrag wiederverwendet oder neu angelegt wird.
        """
        cursor.execute(
            "SELECT pdf_id, filename FROM pdfs WHERE file_path = ?",
            (file_path,)
        )
        return cursor.fetchone()

    @staticmethod
    def _ensure_pdf_id(
        cursor,
        old_path: str,
        fallback_filename: Optional[str],
        existing_pdfs_row: Optional[tuple],
        now_iso: str,
    ) -> str:
        """Stellt sicher, dass ein pdfs-Eintrag existiert und liefert die pdf_id.

        Verwendet ``existing_pdfs_row`` wenn vorhanden, sonst wird ein
        neuer Eintrag angelegt. ``old_path`` wird als initialer Pfad
        genutzt; ein spaeteres ``_update_pdf_master``-Call setzt den
        finalen neuen Pfad.
        """
        if existing_pdfs_row is not None:
            return existing_pdfs_row[0]

        pdf_id = uuid.uuid4().hex
        cursor.execute(
            "INSERT INTO pdfs (pdf_id, file_path, filename, indexed_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                pdf_id,
                old_path,
                fallback_filename or "",
                now_iso,
                now_iso,
            ),
        )
        return pdf_id

    @staticmethod
    def _update_pdf_master(
        cursor,
        pdf_id: str,
        file_path: Optional[str] = None,
        filename: Optional[str] = None,
        now_iso: Optional[str] = None,
    ) -> None:
        """Aktualisiert den pdfs-Eintrag fuer ``pdf_id`` (Path/Filename/last_seen_at).

        Wird von ``update_pdf_path`` aufgerufen. Setzt nur Felder die
        explizit uebergeben wurden (``None`` = nicht aendern, ausser
        ``last_seen_at`` welches immer aktualisiert wird).
        """
        sets = ["last_seen_at = ?"]
        params: list = [now_iso or datetime.utcnow().isoformat()]
        if file_path is not None:
            sets.append("file_path = ?")
            params.append(file_path)
        if filename is not None:
            sets.append("filename = ?")
            params.append(filename)
        params.append(pdf_id)
        cursor.execute(
            f"UPDATE pdfs SET {', '.join(sets)} WHERE pdf_id = ?",
            params,
        )

    def search_documents(
        self,
        query: str,
        limit: int = 50,
        steuerjahr: str = "",
        kategorie: str = "",
        korrespondent: str = "",
        datum_von: str = "",
        datum_bis: str = "",
        betrag_von: float = 0.0,
        betrag_bis: float = 0.0,
        pdf_id: str = "",
    ) -> list[dict]:
        """
        Durchsucht alle indexierten Dokumente per Volltextsuche.

        query ist optional – wenn leer aber Filter gesetzt, werden alle
        passenden Dokumente zurückgegeben. datum_von/datum_bis (YYYY-MM-DD)
        werden gegen das Steuerjahr verglichen (Jahresanteil).
        betrag_von/betrag_bis = 0 bedeutet inaktiv.

        Phase 2 (Issue #25): Jedes Result enthaelt zusaetzlich ``pdf_id``
        (stabile UUID aus der ``pdfs``-Master-Tabelle) und es kann
        optional nach einer konkreten ``pdf_id`` gefiltert werden
        (exakter Match; rueckwaertskompatibel - Default ``""`` = inaktiv).
        """
        import sqlite3

        has_text = bool(query and query.strip())
        has_filter = any([
            steuerjahr, kategorie, korrespondent,
            datum_von, datum_bis,
            betrag_von > 0, betrag_bis > 0,
            pdf_id,
        ])

        if not has_text and not has_filter:
            return []

        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            conditions: list[str] = []
            params: list = []

            if has_text:
                # Wenn die Query bereits FTS5-Operatoren (OR, AND, NEAR, NOT) enthaelt,
                # nutzen wir sie direkt. Andernfalls behandeln wir sie als Whitespace-
                # getrennte Terme und joinen mit AND (Default-Verhalten).
                q = query.strip()
                if any(op in q for op in (" OR ", " AND ", " NEAR ", " NOT ")):
                    fts_query = q
                else:
                    terms = q.split()
                    fts_query = " AND ".join(f'"{t}"*' for t in terms if t)
                if fts_query:
                    conditions.append("document_search MATCH ?")
                    params.append(fts_query)

            if steuerjahr:
                conditions.append("steuerjahr = ?")
                params.append(steuerjahr)

            if kategorie:
                conditions.append("kategorie = ?")
                params.append(kategorie)

            if korrespondent:
                conditions.append("korrespondent = ?")
                params.append(korrespondent)

            if datum_von:
                conditions.append("steuerjahr >= ?")
                params.append(datum_von[:4])

            if datum_bis:
                conditions.append("steuerjahr <= ?")
                params.append(datum_bis[:4])

            if betrag_von > 0:
                conditions.append("CAST(NULLIF(betrag, '') AS REAL) >= ?")
                params.append(betrag_von)

            if betrag_bis > 0:
                conditions.append("CAST(NULLIF(betrag, '') AS REAL) <= ?")
                params.append(betrag_bis)

            if pdf_id:
                conditions.append("pdf_id = ?")
                params.append(pdf_id)

            where_clause = " AND ".join(conditions)

            if has_text:
                snippet_expr = "snippet(document_search, 2, '>>>', '<<<', '...', 30)"
                order_clause = "ORDER BY rank"
            else:
                snippet_expr = "''"
                order_clause = "ORDER BY filename"

            params.append(limit)
            cursor.execute(f"""
                SELECT
                    pdf_id,
                    file_path,
                    filename,
                    {snippet_expr} as text_snippet,
                    keywords,
                    korrespondent,
                    kategorie,
                    steuerjahr,
                    betrag,
                    zusammenfassung,
                    target_folder
                FROM document_search
                WHERE {where_clause}
                {order_clause}
                LIMIT ?
            """, params)

            results = []
            for row in cursor.fetchall():
                results.append({
                    "pdf_id": row[0],
                    "file_path": row[1],
                    "filename": row[2],
                    "text_snippet": row[3],
                    "keywords": row[4],
                    "korrespondent": row[5],
                    "kategorie": row[6],
                    "steuerjahr": row[7],
                    "betrag": row[8],
                    "zusammenfassung": row[9],
                    "target_folder": row[10],
                })

            conn.close()
            return results

        except Exception as e:
            print(f"FTS5-Suche Fehler: {e}")
            return []

    def get_distinct_steuerjahre(self) -> list[str]:
        """Gibt sortierte Liste eindeutiger Steuerjahre zurück."""
        import sqlite3
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT steuerjahr FROM document_search "
                "WHERE steuerjahr != '' ORDER BY steuerjahr DESC"
            )
            result = [row[0] for row in cursor.fetchall()]
            conn.close()
            return result
        except Exception:
            return []

    def get_distinct_kategorien(self) -> list[str]:
        """Gibt sortierte Liste eindeutiger Kategorien zurück."""
        import sqlite3
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT kategorie FROM document_search "
                "WHERE kategorie != '' ORDER BY kategorie"
            )
            result = [row[0] for row in cursor.fetchall()]
            conn.close()
            return result
        except Exception:
            return []

    def get_top_kategorien(self, limit: int = 10) -> list[str]:
        """Die haeufigsten Kategorien der Sammlung, haeufigste zuerst (Issue #110)."""
        import sqlite3
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT kategorie, COUNT(*) AS n FROM document_search "
                "WHERE kategorie != '' GROUP BY kategorie ORDER BY n DESC, kategorie LIMIT ?",
                (int(limit),),
            )
            result = [row[0] for row in cursor.fetchall()]
            conn.close()
            return result
        except Exception:
            return []

    def get_distinct_korrespondenten(self) -> list[str]:
        """Gibt sortierte Liste eindeutiger Korrespondenten zurück."""
        import sqlite3
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT korrespondent FROM document_search "
                "WHERE korrespondent != '' ORDER BY korrespondent"
            )
            result = [row[0] for row in cursor.fetchall()]
            conn.close()
            return result
        except Exception:
            return []

    def get_search_index_count(self) -> int:
        """Gibt die Anzahl der indexierten Dokumente zurück."""
        import sqlite3
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM document_search")
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0

    def bulk_index_directory(
        self,
        folder: str,
        recursive: bool = True,
        analyze: bool = False,
        progress_callback=None,
    ) -> dict:
        """Indiziert alle PDFs in einem Verzeichnis in den Volltext-Suchindex.

        Returns:
            Dict mit scanned, indexed, skipped, errors.
        """
        import sqlite3

        folder_path = Path(folder)
        pattern = "**/*.pdf" if recursive else "*.pdf"
        pdf_files = sorted(folder_path.glob(pattern))
        total = len(pdf_files)

        indexed = 0
        skipped = 0
        errors = []

        for i, path in enumerate(pdf_files):
            if progress_callback is not None:
                progress_callback(i + 1, total, path)

            try:
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM document_search WHERE file_path = ?",
                    (str(path),)
                )
                already_indexed = cursor.fetchone()[0] > 0
                conn.close()

                if already_indexed:
                    skipped += 1
                    continue

                extracted_text = ""
                kw_str = ""

                if analyze:
                    from src.core.pdf_analyzer import PDFAnalyzer
                    with PDFAnalyzer(path) as analyzer:
                        extracted_text = analyzer.extract_text() or ""
                        kw_list = analyzer.extract_keywords() or []
                        kw_str = ", ".join(kw_list)

                self.index_document(
                    file_path=str(path),
                    filename=path.name,
                    extracted_text=extracted_text,
                    keywords=kw_str,
                )
                indexed += 1

            except Exception as e:
                errors.append((str(path), str(e)))

        return {
            "scanned": total,
            "indexed": indexed,
            "skipped": skipped,
            "errors": errors,
        }

    # === Sortierhistorie ===

    def add_sorting_entry(
        self,
        original_filename: str,
        original_path: str,
        target_folder: str,
        target_folder_name: str,
        extracted_text: str = None,
        keywords: list[str] = None,
        detected_date: str = None,
        new_filename: str = None,
        confidence: float = 1.0,
        target_relative_path: str = None,
        metadata: dict = None,
    ) -> SortingHistory:
        """
        Fügt einen neuen Eintrag zur Sortierhistorie hinzu.

        Args:
            original_filename: Ursprünglicher Dateiname
            original_path: Ursprünglicher Pfad
            target_folder: Zielordner-Pfad
            target_folder_name: Zielordner-Name
            extracted_text: Extrahierter Text aus der PDF
            keywords: Liste erkannter Schlüsselwörter
            detected_date: Erkanntes Datum
            new_filename: Neuer Dateiname (falls umbenannt)
            confidence: Konfidenz (1.0 = Benutzerentscheidung)
            target_relative_path: Relativer Pfad (z.B. "Steuer 2026/Banken")
            metadata: Dokument-Metadaten (Phase 16)

        Returns:
            Der erstellte Eintrag
        """
        session = self.get_session()
        try:
            entry = SortingHistory(
                original_filename=original_filename,
                original_path=original_path,
                target_folder=target_folder,
                target_folder_name=target_folder_name,
                target_relative_path=target_relative_path,
                extracted_text=extracted_text,
                keywords=",".join(keywords) if keywords else None,
                detected_date=detected_date,
                new_filename=new_filename,
                confidence=confidence,
            )

            # Metadaten-Felder setzen (Phase 16 + 18)
            if metadata:
                entry.korrespondent = metadata.get("korrespondent")
                entry.betrag = metadata.get("betrag_brutto") or metadata.get("betrag")
                entry.betrag_netto = metadata.get("betrag_netto")
                entry.betrag_brutto = metadata.get("betrag_brutto")
                entry.iban = metadata.get("iban")
                entry.waehrung = metadata.get("waehrung")
                entry.mwst_satz = metadata.get("mwst_satz")
                entry.steuerjahr = metadata.get("steuerjahr")
                entry.steuerlich_absetzbar = metadata.get("steuerlich_absetzbar")
                entry.kategorie = metadata.get("subject")
                entry.zusammenfassung = metadata.get("description")

            session.add(entry)

            # Zielordner-Statistik aktualisieren
            self._update_folder_stats(
                session, target_folder, target_folder_name, target_relative_path
            )

            session.commit()
            return entry
        finally:
            session.close()

    def get_all_sorting_entries(self) -> list[SortingHistory]:
        """Gibt alle Sortierhistorie-Einträge zurück."""
        session = self.get_session()
        try:
            return session.query(SortingHistory).order_by(
                SortingHistory.created_at.desc()
            ).all()
        finally:
            session.close()

    def get_entries_for_folder(self, target_folder: str) -> list[SortingHistory]:
        """Gibt alle Einträge für einen bestimmten Zielordner zurück."""
        session = self.get_session()
        try:
            return session.query(SortingHistory).filter(
                SortingHistory.target_folder == target_folder
            ).all()
        finally:
            session.close()

    def get_entry_count(self) -> int:
        """Gibt die Anzahl der Einträge zurück."""
        session = self.get_session()
        try:
            return session.query(SortingHistory).count()
        finally:
            session.close()

    # === Zielordner-Statistiken ===

    def _update_folder_stats(
        self,
        session,
        folder_path: str,
        folder_name: str,
        relative_path: str = None
    ):
        """Aktualisiert die Statistiken eines Zielordners."""
        folder = session.query(TargetFolder).filter(
            TargetFolder.path == folder_path
        ).first()

        if folder:
            folder.usage_count += 1
            folder.last_used = datetime.utcnow()
            # Relativen Pfad aktualisieren wenn vorhanden
            if relative_path and not folder.relative_path:
                folder.relative_path = relative_path
        else:
            # Parent-Pfad ermitteln
            from pathlib import Path
            parent_path = str(Path(folder_path).parent)

            folder = TargetFolder(
                path=folder_path,
                name=folder_name,
                relative_path=relative_path,
                parent_path=parent_path,
                usage_count=1,
            )
            session.add(folder)

    def get_folder_stats(self) -> list[TargetFolder]:
        """Gibt alle Zielordner mit Statistiken zurück."""
        session = self.get_session()
        try:
            return session.query(TargetFolder).order_by(
                TargetFolder.usage_count.desc()
            ).all()
        finally:
            session.close()

    def get_most_used_folders(self, limit: int = 5) -> list[TargetFolder]:
        """Gibt die am häufigsten verwendeten Ordner zurück."""
        session = self.get_session()
        try:
            return session.query(TargetFolder).order_by(
                TargetFolder.usage_count.desc()
            ).limit(limit).all()
        finally:
            session.close()

    def get_subfolders_for_parent(self, parent_path: str) -> list[TargetFolder]:
        """
        Gibt alle genutzten Unterordner eines Parent-Ordners zurück.

        Args:
            parent_path: Pfad zum übergeordneten Ordner

        Returns:
            Liste der Unterordner (nach Nutzung sortiert)
        """
        session = self.get_session()
        try:
            return session.query(TargetFolder).filter(
                TargetFolder.parent_path == parent_path
            ).order_by(
                TargetFolder.usage_count.desc()
            ).all()
        finally:
            session.close()

    def get_folders_by_relative_path_pattern(
        self, pattern: str, limit: int = 10
    ) -> list[TargetFolder]:
        """
        Sucht Ordner deren relativer Pfad ein Muster enthält.

        Args:
            pattern: Suchmuster (z.B. "Steuer" oder "Banken")
            limit: Maximale Anzahl

        Returns:
            Liste passender Ordner
        """
        session = self.get_session()
        try:
            return session.query(TargetFolder).filter(
                TargetFolder.relative_path.ilike(f"%{pattern}%")
            ).order_by(
                TargetFolder.usage_count.desc()
            ).limit(limit).all()
        finally:
            session.close()

    def get_sorting_history_by_relative_path(
        self, relative_path: str, limit: int = 10
    ) -> list[SortingHistory]:
        """
        Gibt Sortierhistorie für einen relativen Pfad zurück.

        Args:
            relative_path: Der relative Pfad (z.B. "Steuer 2026/Banken")
            limit: Maximale Anzahl

        Returns:
            Liste der Sortierhistorie-Einträge
        """
        session = self.get_session()
        try:
            return session.query(SortingHistory).filter(
                SortingHistory.target_relative_path == relative_path
            ).order_by(
                SortingHistory.created_at.desc()
            ).limit(limit).all()
        finally:
            session.close()

    # === Textsuche für Ähnlichkeit ===

    def get_entries_with_text(self) -> list[SortingHistory]:
        """Gibt alle Einträge mit extrahiertem Text zurück."""
        session = self.get_session()
        try:
            return session.query(SortingHistory).filter(
                SortingHistory.extracted_text.isnot(None),
                SortingHistory.extracted_text != "",
            ).all()
        finally:
            session.close()

    def search_similar_keywords(self, keywords: list[str]) -> list[SortingHistory]:
        """
        Sucht nach Einträgen mit ähnlichen Schlüsselwörtern.

        Args:
            keywords: Liste von Schlüsselwörtern

        Returns:
            Liste passender Einträge
        """
        session = self.get_session()
        try:
            results = []
            for entry in session.query(SortingHistory).all():
                if entry.keywords:
                    entry_keywords = set(entry.keywords.lower().split(","))
                    search_keywords = set(k.lower() for k in keywords)
                    if entry_keywords & search_keywords:  # Schnittmenge
                        results.append(entry)
            return results
        finally:
            session.close()

    def get_learned_folder_names(self) -> dict[str, int]:
        """
        Gibt alle gelernten Ordnernamen mit ihrer Nutzungshäufigkeit zurück.

        Diese Methode ist unabhängig von absoluten Pfaden - sie gibt nur
        die Ordnernamen zurück, die gelernt wurden.

        Returns:
            Dict mit Ordnername -> Anzahl der Nutzungen
        """
        session = self.get_session()
        try:
            folder_counts: dict[str, int] = {}
            for entry in session.query(SortingHistory).all():
                name = entry.target_folder_name
                if name:
                    folder_counts[name] = folder_counts.get(name, 0) + 1
            return folder_counts
        finally:
            session.close()

    def get_learned_relative_paths(self) -> dict[str, int]:
        """
        Gibt alle gelernten relativen Pfade mit ihrer Nutzungshäufigkeit zurück.

        Relativer Pfad z.B. "Steuer 2026/Banken" - unabhängig vom Root-Ordner.

        Returns:
            Dict mit relativer Pfad -> Anzahl der Nutzungen
        """
        session = self.get_session()
        try:
            path_counts: dict[str, int] = {}
            for entry in session.query(SortingHistory).all():
                rel_path = entry.target_relative_path
                if rel_path:
                    path_counts[rel_path] = path_counts.get(rel_path, 0) + 1
            return path_counts
        finally:
            session.close()

    def get_folder_name_to_keywords_mapping(self) -> dict[str, set[str]]:
        """
        Gibt ein Mapping von Ordnernamen zu gelernten Keywords zurück.

        Returns:
            Dict mit Ordnername -> Set von Keywords die zu diesem Ordner führten
        """
        session = self.get_session()
        try:
            folder_keywords: dict[str, set[str]] = {}
            for entry in session.query(SortingHistory).all():
                name = entry.target_folder_name
                if name and entry.keywords:
                    if name not in folder_keywords:
                        folder_keywords[name] = set()
                    keywords = entry.keywords.lower().split(",")
                    folder_keywords[name].update(k.strip() for k in keywords if k.strip())
            return folder_keywords
        finally:
            session.close()

    # === Umbenennungshistorie ===

    def add_rename_entry(
        self,
        original_filename: str,
        new_filename: str,
        extracted_text: str = None,
        keywords: list[str] = None,
        detected_date: str = None,
        target_folder: str = None,
    ) -> RenameHistory:
        """
        Fügt einen neuen Eintrag zur Umbenennungshistorie hinzu.

        Args:
            original_filename: Ursprünglicher Dateiname
            new_filename: Neuer Dateiname
            extracted_text: Extrahierter Text aus der PDF
            keywords: Liste erkannter Schlüsselwörter
            detected_date: Erkanntes Datum
            target_folder: Zielordner (falls bekannt)

        Returns:
            Der erstellte Eintrag
        """
        session = self.get_session()
        try:
            entry = RenameHistory(
                original_filename=original_filename,
                new_filename=new_filename,
                extracted_text=extracted_text,
                keywords=",".join(keywords) if keywords else None,
                detected_date=detected_date,
                target_folder=target_folder,
            )
            session.add(entry)
            session.commit()
            return entry
        finally:
            session.close()

    def get_rename_suggestions_by_keywords(
        self, keywords: list[str], limit: int = 5
    ) -> list[RenameHistory]:
        """
        Sucht nach ähnlichen Umbenennungen basierend auf Schlüsselwörtern.

        Args:
            keywords: Liste von Schlüsselwörtern
            limit: Maximale Anzahl Ergebnisse

        Returns:
            Liste passender Umbenennungseinträge
        """
        session = self.get_session()
        try:
            results = []
            for entry in session.query(RenameHistory).order_by(
                RenameHistory.created_at.desc()
            ).all():
                if entry.keywords:
                    entry_keywords = set(entry.keywords.lower().split(","))
                    search_keywords = set(k.lower() for k in keywords)
                    if entry_keywords & search_keywords:
                        results.append(entry)
                        if len(results) >= limit:
                            break
            return results
        finally:
            session.close()

    def get_rename_examples(
        self, text: str, keywords: list[str] | None, limit: int = 5
    ) -> list[RenameHistory]:
        """Umbenennungen aehnlicher Dokumente als Stil-Beispiele fuer die KI.

        Aehnlichkeit siehe :mod:`src.core.rename_examples` - ein einzelnes
        gemeinsames Stichwort reicht nicht.
        """
        from src.core.rename_examples import rank_examples

        session = self.get_session()
        try:
            rows = (
                session.query(RenameHistory)
                .order_by(RenameHistory.created_at.desc())
                .limit(2000)
                .all()
            )
            return rank_examples(rows, text or "", keywords or [], limit=limit)
        finally:
            session.close()

    def get_rename_suggestions_by_folder(
        self, target_folder: str, limit: int = 5
    ) -> list[RenameHistory]:
        """
        Sucht nach Umbenennungen für einen bestimmten Zielordner.

        Args:
            target_folder: Pfad zum Zielordner
            limit: Maximale Anzahl Ergebnisse

        Returns:
            Liste passender Umbenennungseinträge
        """
        session = self.get_session()
        try:
            return session.query(RenameHistory).filter(
                RenameHistory.target_folder == target_folder
            ).order_by(
                RenameHistory.created_at.desc()
            ).limit(limit).all()
        finally:
            session.close()

    def get_rename_count(self) -> int:
        """Gibt die Anzahl der Umbenennungseinträge zurück."""
        session = self.get_session()
        try:
            return session.query(RenameHistory).count()
        finally:
            session.close()

    # === Korrespondent-Metadaten (lernendes System) ===

    def learn_korrespondent_metadata(self, korrespondent: str, metadata: dict):
        """
        Speichert/aktualisiert gelernte Metadaten für einen Korrespondenten.

        Wird aufgerufen wenn der Nutzer im Umbenennungsdialog Metadaten
        bestätigt oder korrigiert. Das System merkt sich die Zuordnung
        und wendet sie bei künftigen Dokumenten desselben Absenders an.

        Args:
            korrespondent: Firmenname/Absender (z.B. "ista")
            metadata: Dict mit Feldern wie kategorie, waehrung, mwst_satz, etc.
        """
        if not korrespondent or not korrespondent.strip():
            return

        korrespondent = korrespondent.strip()
        session = self.get_session()
        try:
            existing = session.query(KorrespondentMetadata).filter(
                KorrespondentMetadata.korrespondent == korrespondent
            ).first()

            if existing:
                # Bestehenden Eintrag aktualisieren
                if metadata.get("subject"):
                    existing.kategorie = metadata["subject"]
                if metadata.get("waehrung"):
                    existing.waehrung = metadata["waehrung"]
                if metadata.get("mwst_satz"):
                    existing.mwst_satz = metadata["mwst_satz"]
                if metadata.get("steuerlich_absetzbar"):
                    existing.steuerlich_absetzbar = metadata["steuerlich_absetzbar"]
                existing.usage_count += 1
                existing.updated_at = datetime.utcnow()
            else:
                # Neuen Eintrag erstellen
                entry = KorrespondentMetadata(
                    korrespondent=korrespondent,
                    kategorie=metadata.get("subject"),
                    waehrung=metadata.get("waehrung"),
                    mwst_satz=metadata.get("mwst_satz"),
                    steuerlich_absetzbar=metadata.get("steuerlich_absetzbar"),
                )
                session.add(entry)

            session.commit()
        finally:
            session.close()

    def get_korrespondent_metadata(self, korrespondent: str) -> Optional[dict]:
        """
        Gibt gelernte Metadaten für einen Korrespondenten zurück.

        Args:
            korrespondent: Firmenname/Absender

        Returns:
            Dict mit gelernten Feldern oder None
        """
        if not korrespondent or not korrespondent.strip():
            return None

        session = self.get_session()
        try:
            entry = session.query(KorrespondentMetadata).filter(
                KorrespondentMetadata.korrespondent == korrespondent.strip()
            ).first()

            if not entry:
                # Fuzzy-Suche: Teilübereinstimmung (z.B. "ista GmbH" findet "ista")
                entries = session.query(KorrespondentMetadata).all()
                korr_lower = korrespondent.strip().lower()
                for e in entries:
                    if (e.korrespondent.lower() in korr_lower
                            or korr_lower in e.korrespondent.lower()):
                        entry = e
                        break

            if not entry:
                return None

            result = {}
            if entry.kategorie:
                result["subject"] = entry.kategorie
            if entry.waehrung:
                result["waehrung"] = entry.waehrung
            if entry.mwst_satz:
                result["mwst_satz"] = entry.mwst_satz
            if entry.steuerlich_absetzbar:
                result["steuerlich_absetzbar"] = entry.steuerlich_absetzbar
            return result if result else None
        finally:
            session.close()

    def get_steuerauswertung(self) -> list[dict]:
        """
        Gibt eine Steuerauswertung pro Steuerjahr und Kategorie zurueck.

        Returns:
            Liste von Dicts mit steuerjahr, kategorie, anzahl,
            summe_brutto, summe_netto, summe_absetzbar
        """
        session = self.get_session()
        try:
            entries = session.query(SortingHistory).filter(
                SortingHistory.steuerjahr.isnot(None),
                SortingHistory.steuerjahr != "",
            ).all()

            # Aggregieren nach (steuerjahr, kategorie)
            agg: dict[tuple, dict] = {}
            for e in entries:
                key = (e.steuerjahr or "", e.kategorie or "Sonstiges")
                if key not in agg:
                    agg[key] = {
                        "steuerjahr": e.steuerjahr,
                        "kategorie": e.kategorie or "Sonstiges",
                        "anzahl": 0,
                        "summe_brutto": 0.0,
                        "summe_netto": 0.0,
                        "summe_absetzbar": 0.0,
                    }
                rec = agg[key]
                rec["anzahl"] += 1

                # Brutto
                brutto_str = e.betrag_brutto or e.betrag or ""
                try:
                    rec["summe_brutto"] += float(brutto_str.replace(",", "."))
                except (ValueError, AttributeError):
                    pass

                # Netto
                netto_str = e.betrag_netto or ""
                try:
                    rec["summe_netto"] += float(netto_str.replace(",", "."))
                except (ValueError, AttributeError):
                    pass

                # Steuerlich absetzbar: Bruttobetrag zählen wenn "ja"
                if (e.steuerlich_absetzbar or "").lower() == "ja":
                    try:
                        rec["summe_absetzbar"] += float(brutto_str.replace(",", "."))
                    except (ValueError, AttributeError):
                        pass

            result = sorted(agg.values(), key=lambda r: (r["steuerjahr"], r["kategorie"]))
            return result
        finally:
            session.close()

    def get_all_korrespondenten(self) -> list[str]:
        """Gibt alle bekannten Korrespondenten zurück (für Autovervollständigung)."""
        session = self.get_session()
        try:
            entries = session.query(KorrespondentMetadata).order_by(
                KorrespondentMetadata.usage_count.desc()
            ).all()
            return [e.korrespondent for e in entries]
        finally:
            session.close()

    # === Korrespondenten-Verwaltung (Phase 20 / Issue #21) ===

    # Standard-Kategorien fuer die GUI-Kombobox
    KORRESPONDENT_KATEGORIEN: list[str] = [
        "Energie",
        "Versicherung",
        "Telekommunikation",
        "Steuer",
        "Bank",
        "Behoerde",
        "Vermieter",
        "Sonstiges",
    ]

    def list_korrespondenten(self) -> list[dict]:
        """Gibt alle verwalteten Korrespondenten zurueck.

        Sortiert nach ``usage_count`` (absteigend), dann nach ``name``.

        Returns:
            Liste von Dicts mit allen Feldern (id, name, aliases, kategorie,
            farbe, notizen, usage_count, created_at, updated_at). ``aliases``
            ist als Python-Liste deserialisiert; leere Werte sind ``None``.
        """
        session = self.get_session()
        try:
            entries = (
                session.query(Korrespondent)
                .order_by(Korrespondent.usage_count.desc(), Korrespondent.name.asc())
                .all()
            )
            return [self._korrespondent_to_dict(e) for e in entries]
        finally:
            session.close()

    def get_korrespondent(self, name: str) -> Optional[dict]:
        """Gibt einen einzelnen Korrespondenten per Name zurueck.

        Args:
            name: Anzeigename (case-sensitive, exakter Match)

        Returns:
            Dict oder ``None`` falls nicht gefunden.
        """
        if not name or not name.strip():
            return None
        session = self.get_session()
        try:
            entry = (
                session.query(Korrespondent)
                .filter(Korrespondent.name == name.strip())
                .first()
            )
            return self._korrespondent_to_dict(entry) if entry else None
        finally:
            session.close()

    def add_or_update_korrespondent(
        self,
        name: str,
        aliases: Optional[list[str]] = None,
        kategorie: Optional[str] = None,
        farbe: Optional[str] = None,
        notizen: Optional[str] = None,
    ) -> dict:
        """Legt einen Korrespondenten neu an oder aktualisiert ihn.

        Idempotent:
            * Existiert der Name noch nicht: INSERT, ``usage_count`` bleibt 0.
            * Existiert der Name: UPDATE, ``usage_count`` wird um 1 erhoeht.

        ``aliases`` wird als JSON-String persistiert (Liste). Wird ``None``
        uebergeben und der Eintrag existiert bereits, bleiben die
        vorhandenen Aliasse unveraendert (partielles Update).

        Args:
            name: Anzeigename (eindeutig)
            aliases: Optionale Liste alternativer Namen
            kategorie: Optionale Kategorie
            farbe: Optionaler Hex-String (z.B. ``"#FF5733"``)
            notizen: Optionaler Freitext

        Returns:
            Dict des gespeicherten Korrespondenten
        """
        if not name or not name.strip():
            raise ValueError("Korrespondent-Name darf nicht leer sein")

        name = name.strip()
        aliases_json = self._serialize_aliases(aliases)

        session = self.get_session()
        try:
            existing = (
                session.query(Korrespondent)
                .filter(Korrespondent.name == name)
                .first()
            )
            if existing is None:
                # INSERT
                entry = Korrespondent(
                    name=name,
                    aliases=aliases_json,
                    kategorie=kategorie,
                    farbe=farbe,
                    notizen=notizen,
                    usage_count=0,
                )
                session.add(entry)
                session.commit()
                return self._korrespondent_to_dict(entry)

            # UPDATE: usage_count++, Felder nur ueberschreiben wenn nicht None
            existing.usage_count = (existing.usage_count or 0) + 1
            existing.updated_at = datetime.utcnow()
            if aliases_json is not None:
                existing.aliases = aliases_json
            if kategorie is not None:
                existing.kategorie = kategorie
            if farbe is not None:
                existing.farbe = farbe
            if notizen is not None:
                existing.notizen = notizen
            session.commit()
            return self._korrespondent_to_dict(existing)
        finally:
            session.close()

    def delete_korrespondent(self, name: str) -> bool:
        """Loescht einen Korrespondenten.

        Args:
            name: Name des Korrespondenten

        Returns:
            ``True`` wenn geloescht, ``False`` wenn nicht gefunden.
        """
        if not name or not name.strip():
            return False
        session = self.get_session()
        try:
            entry = (
                session.query(Korrespondent)
                .filter(Korrespondent.name == name.strip())
                .first()
            )
            if not entry:
                return False
            session.delete(entry)
            session.commit()
            return True
        finally:
            session.close()

    def merge_korrespondenten(
        self, primary_name: str, secondary_names: list[str]
    ) -> None:
        """Fuehrt mehrere Korrespondenten zu einem Primaerkorrespondenten zusammen.

        Verhalten:
            * ``primary_name`` bleibt erhalten; ``usage_count`` wird um die
              usage_counts der Sekundaere aufsummiert.
            * Alle Sekundaer-Eintraege werden geloescht.
            * Sekundaer-Namen werden als Aliasse in den Primaer-Eintrag
              gemerged (Duplikate werden gefiltert, Reihenfolge bleibt stabil).
            * FTS5-Eintraege (``document_search``) mit
              ``korrespondent = secondary`` werden auf ``primary_name``
              umgeschrieben.
            * ``sorting_history.korrespondent`` wird ebenfalls aktualisiert.
            * ``KorrespondentMetadata.korrespondent`` (gelernte Defaults)
              wird umbenannt, sodass vorhandene Lerneffekte erhalten bleiben.

        Args:
            primary_name: Name des Primaerkorrespondenten (muss existieren)
            secondary_names: Liste von Sekundaernamen (werden geloescht)
        """
        import sqlite3

        if not primary_name or not primary_name.strip():
            raise ValueError("primary_name darf nicht leer sein")
        primary_name = primary_name.strip()
        secondary_names = [s.strip() for s in (secondary_names or []) if s and s.strip()]
        if primary_name in secondary_names:
            secondary_names = [s for s in secondary_names if s != primary_name]

        session = self.get_session()
        try:
            primary = (
                session.query(Korrespondent)
                .filter(Korrespondent.name == primary_name)
                .first()
            )
            if primary is None:
                raise ValueError(
                    f"Primaerkorrespondent '{primary_name}' existiert nicht"
                )

            # Bestehende Aliasse des Primaers laden
            existing_aliases = self._deserialize_aliases(primary.aliases)
            merged_aliases = list(existing_aliases)

            total_usage = primary.usage_count or 0

            for sec_name in secondary_names:
                sec_entry = (
                    session.query(Korrespondent)
                    .filter(Korrespondent.name == sec_name)
                    .first()
                )
                if sec_entry is None:
                    continue
                total_usage += sec_entry.usage_count or 0
                # Sekundaer-Aliasse mergen
                sec_aliases = self._deserialize_aliases(sec_entry.aliases)
                for a in sec_aliases:
                    if a not in merged_aliases and a != primary_name:
                        merged_aliases.append(a)
                if sec_name not in merged_aliases and sec_name != primary_name:
                    merged_aliases.append(sec_name)
                session.delete(sec_entry)

            primary.usage_count = total_usage
            primary.aliases = self._serialize_aliases(merged_aliases)
            primary.updated_at = datetime.utcnow()

            session.commit()
        finally:
            session.close()

        # FTS5 + sorting_history + KorrespondentMetadata ausserhalb der
        # SQLAlchemy-Session aktualisieren (FTS5 ist eine virtuelle Tabelle
        # und sorting_history hat ggf. NULL-Werte).
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            for sec_name in secondary_names:
                if not sec_name:
                    continue
                # FTS5: alten Eintrag loeschen, mit neuem Korrespondent neu einfuegen
                cursor.execute(
                    "SELECT file_path, filename, extracted_text, keywords, "
                    "kategorie, steuerjahr, betrag, zusammenfassung, target_folder "
                    "FROM document_search WHERE korrespondent = ?",
                    (sec_name,),
                )
                rows = cursor.fetchall()
                for row in rows:
                    (file_path, filename, text_, kw, kat, jahr, betrag, zus, folder) = row
                    cursor.execute(
                        "DELETE FROM document_search WHERE file_path = ?",
                        (file_path,),
                    )
                    cursor.execute(
                        """
                        INSERT INTO document_search
                        (file_path, filename, extracted_text, keywords,
                         korrespondent, kategorie, steuerjahr, betrag,
                         zusammenfassung, target_folder)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            file_path, filename, text_ or "", kw or "",
                            primary_name, kat or "", jahr or "",
                            betrag or "", zus or "", folder or "",
                        ),
                    )

                # sorting_history: schlichte Umbenennung der Spalte
                cursor.execute(
                    "UPDATE sorting_history SET korrespondent = ? "
                    "WHERE korrespondent = ?",
                    (primary_name, sec_name),
                )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"merge_korrespondenten FTS5-Update Warnung: {e}")

        # KorrespondentMetadata (gelernte Defaults) - Lookup-Name beibehalten,
        # aber den Primaer-Namen mitverwenden damit get_korrespondent_metadata
        # weiterhin die Defaults findet.
        try:
            session = self.get_session()
            try:
                # Wenn ein Metadata-Eintrag fuer einen sekundaer Namen
                # existiert und KEINER fuer den Primaer -> primaer befuellen.
                for sec_name in secondary_names:
                    sec_meta = (
                        session.query(KorrespondentMetadata)
                        .filter(KorrespondentMetadata.korrespondent == sec_name)
                        .first()
                    )
                    if sec_meta is None:
                        continue
                    primary_meta = (
                        session.query(KorrespondentMetadata)
                        .filter(KorrespondentMetadata.korrespondent == primary_name)
                        .first()
                    )
                    if primary_meta is None:
                        # Sekundaer-Metadaten auf Primaer umbenennen
                        sec_meta.korrespondent = primary_name
                    else:
                        # Primaer hat schon eigene Defaults - sekundaer loeschen
                        # (oder Felder primaer einverleiben - wir wählen Loeschen
                        # fuer deterministisches Verhalten)
                        session.delete(sec_meta)
                session.commit()
            finally:
                session.close()
        except Exception as e:
            print(f"merge_korrespondenten Metadata-Update Warnung: {e}")

    def auto_collect_from_history(self) -> int:
        """Extrahiert alle Korrespondenten aus ``sorting_history`` und
        legt fehlende Eintraege in der Verwaltungstabelle an.

        Bestehende Eintraege (per Name) werden nicht ueberschrieben -
        ``usage_count`` wird aus der History gelesen, NICHT inkrementiert.

        Returns:
            Anzahl NEU angelegter Eintraege.
        """
        import sqlite3

        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT korrespondent, COUNT(*) FROM sorting_history "
                "WHERE korrespondent IS NOT NULL AND korrespondent != '' "
                "GROUP BY korrespondent"
            )
            history_counts: dict[str, int] = {
                row[0]: row[1] for row in cursor.fetchall()
            }
            conn.close()
        except Exception:
            return 0

        new_count = 0
        for name, count in history_counts.items():
            session = self.get_session()
            try:
                existing = (
                    session.query(Korrespondent)
                    .filter(Korrespondent.name == name)
                    .first()
                )
                if existing is None:
                    entry = Korrespondent(
                        name=name,
                        usage_count=count,
                        kategorie=None,
                        farbe=None,
                        notizen=None,
                        aliases=None,
                    )
                    session.add(entry)
                    new_count += 1
                else:
                    # Usage-Count aus History uebernehmen wenn hoeher
                    if count > (existing.usage_count or 0):
                        existing.usage_count = count
                        existing.updated_at = datetime.utcnow()
                session.commit()
            finally:
                session.close()

        return new_count

    # === Automatisierungs-Regeln (Phase 21 / Issue #22) ===

    # Konfigurierbare Bedingungs-/Aktionstypen fuer den GUI-Editor.
    # Werden vom RuleEngine unterstuetzt; weitere Typen koennen in
    # ``src/core/rule_engine.py`` ergaenzt werden.
    AVAILABLE_CONDITION_TYPES: list[str] = [
        "korrespondent",   # operator: equals, contains
        "kategorie",       # operator: equals, in
        "betrag",          # operator: gt, gte, lt, lte, between
        "datum",           # operator: after, before, between (ISO-String)
        "keywords",        # operator: any, all
    ]

    AVAILABLE_ACTION_TYPES: list[str] = [
        "target_folder",       # template: Zielordner mit Platzhaltern
        "filename_pattern",    # template: Dateinamenmuster mit Platzhaltern
        "metadata_field",      # field + value: Metadatenfeld setzen
        "tag",                 # value: Tag zur Tag-Liste hinzufuegen
    ]

    def list_rules(self, enabled_only: bool = False) -> list[dict]:
        """Gibt alle Automatisierungs-Regeln zurueck.

        Sortierung: ``priority`` DESC, dann ``id`` ASC (deterministisch).

        Args:
            enabled_only: Wenn ``True``, werden nur aktivierte Regeln
                zurueckgegeben.

        Returns:
            Liste von Dicts mit allen Feldern (``id``, ``name``,
            ``priority``, ``enabled``, ``conditions``, ``actions``,
            ``created_at``, ``updated_at``). ``conditions`` und
            ``actions`` sind als Python-Listen deserialisiert.
        """
        session = self.get_session()
        try:
            query = session.query(AutomationRule).order_by(
                AutomationRule.priority.desc(),
                AutomationRule.id.asc(),
            )
            if enabled_only:
                query = query.filter(AutomationRule.enabled == 1)
            return [self._rule_to_dict(r) for r in query.all()]
        finally:
            session.close()

    def get_rule(self, rule_id: int) -> Optional[dict]:
        """Gibt eine einzelne Regel per ID zurueck.

        Args:
            rule_id: Primaerschluessel der Regel

        Returns:
            Dict oder ``None`` falls nicht gefunden.
        """
        session = self.get_session()
        try:
            entry = (
                session.query(AutomationRule)
                .filter(AutomationRule.id == rule_id)
                .first()
            )
            return self._rule_to_dict(entry) if entry else None
        finally:
            session.close()

    def add_rule(
        self,
        name: str,
        priority: int = 0,
        enabled: bool = True,
        conditions: Optional[list[dict]] = None,
        actions: Optional[list[dict]] = None,
    ) -> dict:
        """Legt eine neue Automatisierungs-Regel an.

        Args:
            name: Anzeigename (eindeutig, NOT NULL)
            priority: Hoeher = wichtiger (Default 0)
            enabled: Aktiv/Inaktiv (Default True)
            conditions: Liste von Bedingungs-Dicts (Default [])
            actions: Liste von Aktions-Dicts (Default [])

        Returns:
            Vollstaendiges Dict der gespeicherten Regel (inkl. ``id``)

        Raises:
            ValueError: Wenn ``name`` leer ist.
            sqlalchemy.exc.IntegrityError: Wenn ``name`` bereits existiert.
        """
        if not name or not str(name).strip():
            raise ValueError("Regelname darf nicht leer sein")

        name = str(name).strip()
        conditions_json = json.dumps(conditions or [], ensure_ascii=False)
        actions_json = json.dumps(actions or [], ensure_ascii=False)

        session = self.get_session()
        try:
            entry = AutomationRule(
                name=name,
                priority=int(priority) if priority is not None else 0,
                enabled=1 if enabled else 0,
                conditions_json=conditions_json,
                actions_json=actions_json,
            )
            session.add(entry)
            session.commit()
            return self._rule_to_dict(entry)
        finally:
            session.close()

    def update_rule(self, rule_id: int, **kwargs) -> dict:
        """Aktualisiert eine vorhandene Regel (partielles Update).

        Akzeptierte Keyword-Argumente:
            ``name`` (str), ``priority`` (int), ``enabled`` (bool),
            ``conditions`` (list[dict]), ``actions`` (list[dict]).

        ``conditions`` und ``actions`` werden automatisch JSON-serialisiert.

        Args:
            rule_id: Primaerschluessel der zu aendernden Regel

        Returns:
            Aktualisiertes Dict der Regel.

        Raises:
            ValueError: Wenn die Regel nicht existiert oder ein
                unbekannter Parameter uebergeben wird.
        """
        allowed = {"name", "priority", "enabled", "conditions", "actions"}
        unknown = set(kwargs) - allowed
        if unknown:
            raise ValueError(
                f"Unbekannte Parameter fuer update_rule: {sorted(unknown)}"
            )

        session = self.get_session()
        try:
            entry = (
                session.query(AutomationRule)
                .filter(AutomationRule.id == rule_id)
                .first()
            )
            if entry is None:
                raise ValueError(f"Regel mit id={rule_id} existiert nicht")

            if "name" in kwargs:
                new_name = kwargs["name"]
                if not new_name or not str(new_name).strip():
                    raise ValueError("Regelname darf nicht leer sein")
                entry.name = str(new_name).strip()
            if "priority" in kwargs:
                entry.priority = int(kwargs["priority"]) if kwargs["priority"] is not None else 0
            if "enabled" in kwargs:
                entry.enabled = 1 if kwargs["enabled"] else 0
            if "conditions" in kwargs:
                entry.conditions_json = json.dumps(
                    kwargs["conditions"] or [], ensure_ascii=False
                )
            if "actions" in kwargs:
                entry.actions_json = json.dumps(
                    kwargs["actions"] or [], ensure_ascii=False
                )
            entry.updated_at = datetime.utcnow()
            session.commit()
            return self._rule_to_dict(entry)
        finally:
            session.close()

    def delete_rule(self, rule_id: int) -> bool:
        """Loescht eine Regel.

        Args:
            rule_id: Primaerschluessel der Regel

        Returns:
            ``True`` wenn geloescht, ``False`` wenn nicht gefunden.
        """
        session = self.get_session()
        try:
            entry = (
                session.query(AutomationRule)
                .filter(AutomationRule.id == rule_id)
                .first()
            )
            if entry is None:
                return False
            session.delete(entry)
            session.commit()
            return True
        finally:
            session.close()

    def reorder_rules(self, rule_ids_in_new_order: list[int]) -> None:
        """Setzt die Prioritaeten in der angegebenen Reihenfolge.

        Die erste ID erhaelt ``priority=100``, die zweite ``99``, usw.
        Nicht in der Liste enthaltene Regeln behalten ihre Prioritaet.

        Args:
            rule_ids_in_new_order: Liste der Regel-IDs in der
                gewuenschten Reihenfolge (Index 0 = hoechste Prio).
        """
        if not rule_ids_in_new_order:
            return

        session = self.get_session()
        try:
            for new_pos, rule_id in enumerate(rule_ids_in_new_order):
                priority = 100 - new_pos
                session.query(AutomationRule).filter(
                    AutomationRule.id == rule_id
                ).update({
                    "priority": priority,
                    "updated_at": datetime.utcnow(),
                })
            session.commit()
        finally:
            session.close()

    # === Interne Helper (Korrespondent) ===

    @staticmethod
    def _serialize_aliases(aliases) -> Optional[str]:
        """Serialisiert eine Alias-Liste in einen JSON-String.

        Akzeptiert:
            * ``None`` → ``None``
            * Liste → ``json.dumps`` der Liste
            * Bereits ein String → wird unveraendert zurueckgegeben
              (idempotent gegen Mehrfachspeicherung)
        """
        if aliases is None:
            return None
        if isinstance(aliases, str):
            return aliases
        if isinstance(aliases, (list, tuple)):
            cleaned = [str(a).strip() for a in aliases if a and str(a).strip()]
            return json.dumps(cleaned, ensure_ascii=False)
        return str(aliases)

    @staticmethod
    def _deserialize_aliases(value) -> list[str]:
        """Deserialisiert einen Alias-JSON-String in eine Python-Liste.

        Robust gegen kaputte/leere Werte.
        """
        if not value:
            return []
        if isinstance(value, (list, tuple)):
            return [str(a) for a in value]
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(a) for a in parsed]
            return [str(parsed)]
        except (ValueError, TypeError):
            # Fallback: versuch als Komma-getrennte Liste zu interpretieren
            return [a.strip() for a in str(value).split(",") if a.strip()]

    @staticmethod
    def _rule_to_dict(entry: Optional[AutomationRule]) -> Optional[dict]:
        """Konvertiert ein ``AutomationRule``-ORM-Objekt in ein Dict.

        ``conditions_json`` und ``actions_json`` werden als Listen
        deserialisiert; korrupte Werte werden durch ``[]`` ersetzt
        (defensiv, damit der RuleEngine nicht abstuerzt).
        """
        if entry is None:
            return None

        def _safe_load(value) -> list:
            if not value:
                return []
            if isinstance(value, (list, tuple)):
                return [dict(x) if isinstance(x, dict) else x for x in value]
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [dict(x) if isinstance(x, dict) else x for x in parsed]
                return []
            except (ValueError, TypeError):
                return []

        return {
            "id": entry.id,
            "name": entry.name,
            "priority": entry.priority if entry.priority is not None else 0,
            "enabled": bool(entry.enabled),
            "conditions": _safe_load(entry.conditions_json),
            "actions": _safe_load(entry.actions_json),
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
        }

    @staticmethod
    def _korrespondent_to_dict(entry: Optional[Korrespondent]) -> Optional[dict]:
        """Konvertiert ein ``Korrespondent``-ORM-Objekt in ein serialisierbares Dict."""
        if entry is None:
            return None
        return {
            "id": entry.id,
            "name": entry.name,
            "aliases": Database._deserialize_aliases(entry.aliases),
            "aliases_raw": entry.aliases,
            "kategorie": entry.kategorie,
            "farbe": entry.farbe,
            "notizen": entry.notizen,
            "usage_count": entry.usage_count or 0,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
        }


# Globale Datenbankinstanz
_db_instance: Optional[Database] = None


def get_database() -> Database:
    """Gibt die globale Datenbankinstanz zurück."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance

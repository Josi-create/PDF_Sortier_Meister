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

    Ungenutzt seit #125 (Feature entfernt), Tabelle bleibt fuer bestehende
    Datenbanken, damit sie ohne Migration weiter oeffnen und nichts verlieren.

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




# Maximale Laenge des Volltexts je Treffer in ``search_documents`` (RAG-Chat /
# Phase 19 / Architektur-Entscheidung Q3): mehr liest der Kontextblock nicht.
MAX_EXTRACTED_TEXT_LENGTH = 5000


def _betrag_text(wert) -> str:
    """REAL aus dem Suchindex als Text wie frueher in ``document_search`` ("59.99")."""
    if wert is None or wert == "":
        return ""
    try:
        return f"{float(wert):.2f}"
    except (TypeError, ValueError):
        return str(wert)


def _ausschnitt(stellen: list) -> str:
    """Fundstellen (``\x02``/``\x03``-Marker) als Ausschnitt mit den bisherigen Markern ``>>>``/``<<<``."""
    teile = []
    for s in stellen or []:
        text = " ".join((s.get("text") or "").split())
        teile.append(text.replace("\x02", ">>>").replace("\x03", "<<<"))
    return " … ".join(t for t in teile if t)




class Database:
    """Datenbankverbindung und -operationen.

    Seit Phase 5 der PDFsuche-Integration gibt es nur noch eine Such-Datenbank:
    Volltext und PDFSM-Metadaten liegen im Suchindex (``src/search``,
    ``suche.db``); ``history.db`` behaelt Lern- und Historienbestand (``pdfs``,
    Sortierhistorie, Korrespondenten, Regeln). ``search_documents()``,
    ``index_document()`` und die Werte-Listen sind Fassaden auf ``self.suchindex``.
    """

    def __init__(self, db_path: Path = None, suchindex=None):
        """
        Initialisiert die Datenbankverbindung.

        Args:
            db_path: Pfad zur SQLite-Datenbank. Standard: aus Config.
            suchindex: :class:`~src.search.suchindex.Suchindex` fuer Volltext und
                Metadaten. Standard: aus der Konfiguration des Nutzers, wenn auch
                ``db_path`` daher kommt; bei eigenem ``db_path`` (Tests, Werkzeuge)
                ein Index daneben (``<ordner>/suche/suche.db``), nie der des Nutzers.
        """
        if db_path is None:
            config = get_config()
            db_path = config.database_path
            if suchindex is None:
                from src.search.suchindex import Suchindex
                suchindex = Suchindex(config.get_search_config())

        self.db_path = db_path
        if suchindex is None:
            from src.search.konfig import SearchConfig
            from src.search.suchindex import Suchindex
            suchindex = Suchindex(SearchConfig(
                aktiv=True, db_pfad=str(Path(db_path).parent / "suche" / "suche.db"),
                ocr_aktiv=False, mails_aktiv=False,
            ))
        self.suchindex = suchindex
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        # Tabellen erstellen
        Base.metadata.create_all(self.engine)

        # Migration: Neue Spalten hinzufügen (falls nicht vorhanden)
        self._migrate_database()

        # Einmalige Uebernahme der alten FTS5-Tabelle ``document_search`` (Phase 5)
        self._document_search_uebernehmen()

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

            # Ungenutzt seit #125, Tabelle bleibt fuer bestehende
            # Datenbanken. Idempotente Anlage auch fuer externe DBs.
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

    # === Volltextsuche (Phase 17; seit Phase 5 der PDFsuche-Integration ueber den Suchindex) ===

    _METADATEN = ("korrespondent", "kategorie", "steuerjahr", "betrag", "zusammenfassung", "schlagwoerter")

    @staticmethod
    def _felder(korrespondent=None, kategorie=None, steuerjahr=None, betrag=None, zusammenfassung=None,
                keywords=None, nur_gesetzte: bool = False) -> dict:
        felder = {"korrespondent": korrespondent, "kategorie": kategorie, "steuerjahr": steuerjahr, "betrag": betrag,
                  "zusammenfassung": zusammenfassung, "schlagwoerter": keywords}
        if nur_gesetzte:
            felder = {k: v for k, v in felder.items() if v not in (None, "")}
        return felder

    def _document_search_uebernehmen(self) -> int:
        """Einmalige Uebernahme der alten FTS5-Tabelle ``document_search`` (bis v0.23) in den Suchindex.

        Zeilen, deren Datei noch existiert, bekommen ihre Metadaten (Quelle
        ``'pdfsm'``) und den alten Text als Notnagel, bis der naechste Lauf die
        Datei liest; Zeilen ohne Datei werden verworfen (ihre ``pdfs``-Eintraege
        bleiben). Danach wird die Tabelle entfernt. Bei einem Fehler bleibt sie
        stehen, der naechste Start versucht es erneut.
        """
        import sqlite3

        try:
            conn = sqlite3.connect(str(self.db_path))
        except Exception:
            return 0
        try:
            cursor = conn.cursor()
            if not cursor.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'document_search'").fetchone():
                return 0
            spalten = [r[1] for r in cursor.execute("PRAGMA table_info(document_search)")]
            hat_id = "pdf_id" in spalten
            rows = cursor.execute(
                f"SELECT {'pdf_id, ' if hat_id else ''}file_path, filename, extracted_text, keywords, "
                "korrespondent, kategorie, steuerjahr, betrag, zusammenfassung FROM document_search").fetchall()
            n = 0
            for row in rows:
                if hat_id:
                    pdf_id, fp, fn, text, kw, korr, kat, jahr, betrag, zus = row
                else:
                    pdf_id = None
                    fp, fn, text, kw, korr, kat, jahr, betrag, zus = row
                if not fp or not Path(fp).exists():
                    continue
                if not pdf_id:
                    pdf_id = self.get_or_create_pdf_id(fp, fn or Path(fp).name)
                felder = self._felder(korr, kat, jahr, betrag, zus, kw)
                self.suchindex.metadaten_setzen(fp, felder, pdf_id, text=text or None, lesen=False)
                n += 1
            cursor.execute("DROP TABLE document_search")
            conn.commit()
            print(f"Suchindex: {n} Dokumente aus der fruehren Tabelle document_search uebernommen")
            return n
        except Exception as e:
            print(f"Uebernahme von document_search verschoben: {e}")
            return 0
        finally:
            conn.close()

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
        Nimmt ein Dokument mit seinen PDFSM-Metadaten in den Suchindex auf.

        Die Datei wird gelesen (Textebene; Bildseiten erkennt der naechste
        OCR-Lauf), die Metadaten bekommen Quelle ``'pdfsm'`` und damit Vorrang
        vor Werten aus der PDF. ``extracted_text`` dient nur noch als Notnagel,
        wenn die Datei nicht lesbar ist (z. B. nicht mehr vorhanden); der Index
        liest den Text selbst. ``target_folder`` ist ohne Bedeutung (der Ordner
        kommt aus dem Pfad).
        """
        try:
            pdf_id = self.get_or_create_pdf_id(file_path, filename)
            felder = self._felder(korrespondent, kategorie, steuerjahr, betrag, zusammenfassung, keywords)
            self.suchindex.metadaten_setzen(file_path, felder, pdf_id, text=extracted_text or None,
                                            name=filename or None)
        except Exception as e:
            print(f"Suchindex-Aufnahme Fehler: {e}")

    def set_document_metadata(self, file_path: str, felder: dict, pdf_id: Optional[str] = None,
                              sofort: bool = True) -> bool:
        """PDFSM-Metadaten (Korrespondent, Kategorie, Steuerjahr, Betrag, Buchungsdatum, Zusammenfassung,
        Schlagwoerter) fuer eine Datei in den Suchindex schreiben; die Datei wird bei Bedarf aufgenommen.

        ``sofort=False`` reiht die Meldung in die Warteschlange ein (nie im GUI-Thread).
        """
        felder = {k: v for k, v in (felder or {}).items()
                  if k in ("korrespondent", "kategorie", "steuerjahr", "betrag", "buchungsdatum", "zusammenfassung",
                           "schlagwoerter")}
        if not felder:
            return False
        try:
            if not pdf_id:
                pdf_id = self.get_or_create_pdf_id(str(file_path), Path(file_path).name)
            if sofort:
                return bool(self.suchindex.metadaten_setzen(str(file_path), felder, pdf_id))
            from src.search.meldungen import melden
            return melden("metadaten_setzen", str(file_path), felder, pdf_id, index=self.suchindex)
        except Exception as e:
            print(f"Suchindex: Metadaten nicht gesetzt: {e}")
            return False

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
        """Meldet Umbenennen/Verschieben an ``pdfs`` und den Suchindex.

        Der Eintrag im Suchindex behaelt Text, OCR und Metadaten (``datei_verschoben``);
        explizit uebergebene Metadaten ueberschreiben die alten Werte. Gab es noch
        keinen Eintrag, wird die Datei unter dem neuen Pfad aufgenommen
        (``extracted_text`` nur als Notnagel, wenn sie nicht lesbar ist). Gibt
        True zurueck, wenn Daten migriert/angelegt wurden, False bei No-op.
        """
        import sqlite3

        if old_path == new_path and new_filename is None:
            return False

        try:
            conn = sqlite3.connect(str(self.db_path))
            try:
                cursor = conn.cursor()
                pdfs_row = self._get_pdf_row_by_path(cursor, old_path)
                now_iso = datetime.utcnow().isoformat()
                pdf_id = self._ensure_pdf_id(
                    cursor, old_path, new_filename or Path(new_path).name, pdfs_row, now_iso
                )
                self._update_pdf_master(
                    cursor, pdf_id, file_path=new_path, filename=new_filename, now_iso=now_iso,
                )
                conn.commit()
            finally:
                conn.close()

            verschoben = self.suchindex.datei_verschoben(old_path, new_path)
            felder = self._felder(korrespondent, kategorie, steuerjahr, betrag, zusammenfassung, keywords,
                                  nur_gesetzte=True)
            if not verschoben:
                self.suchindex.metadaten_setzen(new_path, felder, pdf_id, text=extracted_text or None,
                                                name=new_filename or None)
            else:
                self.suchindex.metadaten_setzen(new_path, felder, pdf_id)
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
        typ: str = "",
        ordner: str = "",
        von: str = "",
        bis: str = "",
        sortierung: str = "",
    ) -> list[dict]:
        """
        Durchsucht den Suchindex (Volltext in PDFs, Office-Dateien, Markdown und Mails).

        query ist optional – wenn leer aber Filter gesetzt, werden alle
        passenden Dokumente zurückgegeben. datum_von/datum_bis (YYYY-MM-DD)
        werden gegen das Steuerjahr verglichen (Jahresanteil).
        betrag_von/betrag_bis = 0 bedeutet inaktiv. ``typ`` schraenkt auf 'pdf',
        'office', 'md' oder 'mail' ein (auch Kombination 'pdf,office'; Issue #166).

        Werkzeuge des Chats (Issue #166/#167, Phase 2) filtern zusaetzlich wie
        das MCP-Werkzeug ``suche``: ``ordner`` (Teil des Dateipfads bzw.
        Postfachnamens), ``von``/``bis`` (JJJJ-MM-TT, Datei- bzw. Mail-Datum)
        und ``sortierung`` ('relevanz' | 'neu' | 'alt'; leer = Relevanz).
        Alle vier werden nur durchgereicht, wenn sie gesetzt sind.

        Ergebnisschluessel wie bisher (``pdf_id``, ``file_path``, ``filename``,
        ``text_snippet``, ``keywords``, ``korrespondent``, ``kategorie``,
        ``steuerjahr``, ``betrag``, ``zusammenfassung``, ``target_folder``),
        dazu ``dok_id``, ``seite`` (erste Fundstelle), ``typ``, ``format``,
        ``groesse``, ``datum`` (Unix-Zeit), ``rang`` (bm25, kleiner = besser)
        und ``extracted_text`` (Volltext, gekappt).
        """
        has_text = bool(query and query.strip())
        has_filter = any([
            steuerjahr, kategorie, korrespondent,
            datum_von, datum_bis,
            betrag_von > 0, betrag_bis > 0,
            pdf_id, typ,
            ordner, von, bis,
        ])
        if not has_text and not has_filter:
            return []

        q = ""
        if has_text:
            q = query.strip()
            # Ohne FTS5-Operatoren: Woerter als Wortanfaenge, alle muessen vorkommen (bisheriges Verhalten)
            if not any(op in q for op in (" OR ", " AND ", " NEAR ", " NOT ", '"', "*")):
                q = " AND ".join(f'"{t}"*' for t in q.split() if t)

        # Issue #166/#167: Filter der Chat-Werkzeuge nur mitgeben, wenn gesetzt
        zusatz: dict = {}
        if ordner:
            zusatz["ordner"] = ordner
        if von:
            zusatz["von"] = von
        if bis:
            zusatz["bis"] = bis
        if sortierung:
            zusatz["sortierung"] = sortierung

        try:
            erg = self.suchindex.suche(
                q,
                steuerjahr=steuerjahr or None,
                kategorie=kategorie or None,
                korrespondent=korrespondent or None,
                steuerjahr_von=datum_von or None,
                steuerjahr_bis=datum_bis or None,
                betrag_von=betrag_von if betrag_von and betrag_von > 0 else None,
                betrag_bis=betrag_bis if betrag_bis and betrag_bis > 0 else None,
                pdf_id=pdf_id or None,
                typ=typ or None,
                anzahl=int(limit),
                **zusatz,
            )
        except Exception as e:
            print(f"Suchindex-Suche Fehler: {e}")
            return []

        results = []
        for d in erg.get("treffer") or []:
            pid = d.get("pdf_id") or ""
            if not pid:
                master = self.get_pdf_by_path(d.get("pfad") or "")
                pid = master["pdf_id"] if master else ""
            stellen = d.get("stellen") or []
            results.append({
                "pdf_id": pid,
                "file_path": d.get("pfad") or "",
                "filename": d.get("name") or "",
                "text_snippet": _ausschnitt(stellen),
                "keywords": d.get("schlagwoerter") or "",
                "korrespondent": d.get("korrespondent") or "",
                "kategorie": d.get("kategorie") or "",
                "steuerjahr": d.get("steuerjahr") or "",
                "betrag": _betrag_text(d.get("betrag")),
                "zusammenfassung": d.get("zusammenfassung") or "",
                "target_folder": d.get("ordner") or "",
                "dok_id": d.get("id"),
                "seite": int(stellen[0].get("seite") or 1) if stellen else 1,
                "typ": d.get("typ") or "",
                "format": d.get("format") or "",
                "groesse": d.get("groesse"),
                "datum": d.get("datum"),
                "rang": d.get("rang"),
                "extracted_text": self.suchindex.volltext(d["id"], MAX_EXTRACTED_TEXT_LENGTH),
            })
        return results

    def get_distinct_steuerjahre(self) -> list[str]:
        """Gibt sortierte Liste eindeutiger Steuerjahre zurück (neueste zuerst)."""
        return self.suchindex.werte("steuerjahr", absteigend=True)

    def get_distinct_kategorien(self) -> list[str]:
        """Gibt sortierte Liste eindeutiger Kategorien zurück."""
        return self.suchindex.werte("kategorie")

    def get_top_kategorien(self, limit: int = 10) -> list[str]:
        """Die haeufigsten Kategorien der Sammlung, haeufigste zuerst (Issue #110)."""
        return self.suchindex.top_werte("kategorie", limit)

    def get_distinct_korrespondenten(self) -> list[str]:
        """Gibt sortierte Liste eindeutiger Korrespondenten zurück."""
        return self.suchindex.werte("korrespondent")

    def get_search_index_count(self) -> int:
        """Gibt die Anzahl der Dokumente im Suchindex zurück."""
        try:
            return self.suchindex.anzahl()
        except Exception:
            return 0

    def get_indexed_documents_brief(self, limit: int = 20000) -> list[dict]:
        """Indizierte PDFs ohne Volltext (fuer die Aehnlichkeitssuche)."""
        try:
            return self.suchindex.dokumente_kurz(typ="pdf", limit=limit)
        except Exception as e:
            print(f"Suchindex lesen fehlgeschlagen: {e}")
            return []

    def bulk_index_directory(
        self,
        folder: str,
        recursive: bool = True,
        analyze: bool = False,
        progress_callback=None,
    ) -> dict:
        """Indiziert alle PDFs in einem Verzeichnis in den Suchindex (synchron, im Prozess).

        Fuer grosse Ordner startet die Oberflaeche stattdessen einen Lauf des
        Dienstes (``Suchindex.lauf_starten(pfad=...)``).

        Returns:
            Dict mit scanned, indexed, skipped, errors.
        """
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
                if self.suchindex.dokument_nach_pfad(str(path)) is not None:
                    skipped += 1
                    continue

                kw_str = ""
                if analyze:
                    from src.core.pdf_analyzer import PDFAnalyzer
                    with PDFAnalyzer(path) as analyzer:
                        kw_list = analyzer.extract_keywords() or []
                        kw_str = ", ".join(kw_list)

                self.index_document(file_path=str(path), filename=path.name, keywords=kw_str)
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

    def get_history_brief(self, limit: int = 20000) -> list[dict]:
        """Sortierhistorie ohne Volltext (fuer die Aehnlichkeitssuche), neueste zuerst."""
        session = self.get_session()
        try:
            rows = (
                session.query(
                    SortingHistory.new_filename,
                    SortingHistory.original_filename,
                    SortingHistory.keywords,
                    SortingHistory.korrespondent,
                    SortingHistory.steuerjahr,
                    SortingHistory.detected_date,
                    SortingHistory.target_relative_path,
                    SortingHistory.target_folder,
                )
                .order_by(SortingHistory.id.desc())
                .limit(limit)
                .all()
            )
            keys = ("new_filename", "original_filename", "keywords", "korrespondent",
                    "steuerjahr", "detected_date", "target_relative_path", "target_folder")
            return [dict(zip(keys, row)) for row in rows]
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
            * Dokumente im Suchindex mit ``korrespondent = secondary`` werden
              auf ``primary_name`` umgeschrieben (``metadaten_ersetzen``).
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

        # Suchindex + sorting_history + KorrespondentMetadata ausserhalb der
        # SQLAlchemy-Session aktualisieren (sorting_history hat ggf. NULL-Werte).
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            for sec_name in secondary_names:
                if not sec_name:
                    continue
                # Suchindex: Korrespondent in allen Dokumenten umschreiben (Text und OCR bleiben)
                try:
                    self.suchindex.metadaten_ersetzen("korrespondent", sec_name, primary_name)
                except Exception as e:
                    print(f"merge_korrespondenten Suchindex-Warnung: {e}")

                # sorting_history: schlichte Umbenennung der Spalte
                cursor.execute(
                    "UPDATE sorting_history SET korrespondent = ? "
                    "WHERE korrespondent = ?",
                    (primary_name, sec_name),
                )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"merge_korrespondenten Update Warnung: {e}")

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

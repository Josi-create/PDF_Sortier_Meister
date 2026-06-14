"""
Datenbank-Modul für PDF Sortier Meister

Speichert die Sortierhistorie für das lernfähige Klassifikationssystem.
"""

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
            # Prüfe und füge fehlende Spalten hinzu
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
                    # Prüfen ob Spalte existiert
                    result = conn.execute(text(f"PRAGMA table_info({table})"))
                    columns = [row[1] for row in result.fetchall()]

                    if column not in columns:
                        # Spalte hinzufügen
                        conn.execute(text(
                            f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
                        ))
                        conn.commit()
                        print(f"Migration: Spalte '{column}' zu '{table}' hinzugefügt")
                except Exception as e:
                    print(f"Migration-Warnung für {table}.{column}: {e}")

    def _create_fts_index(self):
        """Erstellt die FTS5-Volltextsuche-Tabelle (Phase 17)."""
        import sqlite3

        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # FTS5 Virtual Table für Volltextsuche
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS document_search
                USING fts5(
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
            """)

            conn.commit()
            conn.close()
        except Exception as e:
            print(f"FTS5-Index Warnung: {e}")

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
        """
        import sqlite3

        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Alten Eintrag für diesen Pfad löschen (falls vorhanden)
            cursor.execute(
                "DELETE FROM document_search WHERE file_path = ?",
                (file_path,)
            )

            # Neuen Eintrag einfügen
            cursor.execute("""
                INSERT INTO document_search
                (file_path, filename, extracted_text, keywords,
                 korrespondent, kategorie, steuerjahr, betrag,
                 zusammenfassung, target_folder)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                file_path, filename, _truncate_extracted_text(extracted_text or ""), keywords or "",
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

        Felder aus dem alten Eintrag werden kopiert; explizit übergebene
        Parameter überschreiben die kopierten Werte. Gibt True zurück wenn
        Daten migriert/angelegt wurden, False bei No-op.
        """
        import sqlite3

        if old_path == new_path and new_filename is None:
            return False

        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute(
                "SELECT filename, extracted_text, keywords, korrespondent, "
                "kategorie, steuerjahr, betrag, zusammenfassung, target_folder "
                "FROM document_search WHERE file_path = ?",
                (old_path,)
            )
            row = cursor.fetchone()

            if row is None:
                cursor.execute("""
                    INSERT INTO document_search
                    (file_path, filename, extracted_text, keywords,
                     korrespondent, kategorie, steuerjahr, betrag,
                     zusammenfassung, target_folder)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    new_path,
                    new_filename or Path(new_path).name,
                    extracted_text or "",
                    keywords or "",
                    korrespondent or "",
                    kategorie or "",
                    steuerjahr or "",
                    betrag or "",
                    zusammenfassung or "",
                    target_folder or "",
                ))
                conn.commit()
                conn.close()
                return True

            old_fn, old_text, old_kw, old_korr, old_kat, old_jahr, old_betrag, old_zus, old_folder = row

            final_filename = new_filename if new_filename is not None else old_fn
            final_text = extracted_text if extracted_text is not None else (old_text or "")
            final_kw = keywords if keywords is not None else (old_kw or "")
            final_korr = korrespondent if korrespondent is not None else (old_korr or "")
            final_kat = kategorie if kategorie is not None else (old_kat or "")
            final_jahr = steuerjahr if steuerjahr is not None else (old_jahr or "")
            final_betrag = betrag if betrag is not None else (old_betrag or "")
            final_zus = zusammenfassung if zusammenfassung is not None else (old_zus or "")
            final_folder = target_folder if target_folder is not None else (old_folder or "")

            cursor.execute(
                "DELETE FROM document_search WHERE file_path = ?",
                (old_path,)
            )
            cursor.execute("""
                INSERT INTO document_search
                (file_path, filename, extracted_text, keywords,
                 korrespondent, kategorie, steuerjahr, betrag,
                 zusammenfassung, target_folder)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                new_path, final_filename, final_text, final_kw,
                final_korr, final_kat, final_jahr, final_betrag,
                final_zus, final_folder,
            ))
            conn.commit()
            conn.close()
            return True

        except Exception as e:
            print(f"update_pdf_path Fehler: {e}")
            return False

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
    ) -> list[dict]:
        """
        Durchsucht alle indexierten Dokumente per Volltextsuche.

        query ist optional – wenn leer aber Filter gesetzt, werden alle
        passenden Dokumente zurückgegeben. datum_von/datum_bis (YYYY-MM-DD)
        werden gegen das Steuerjahr verglichen (Jahresanteil).
        betrag_von/betrag_bis = 0 bedeutet inaktiv.
        """
        import sqlite3

        has_text = bool(query and query.strip())
        has_filter = any([
            steuerjahr, kategorie, korrespondent,
            datum_von, datum_bis,
            betrag_von > 0, betrag_bis > 0,
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
                    "file_path": row[0],
                    "filename": row[1],
                    "text_snippet": row[2],
                    "keywords": row[3],
                    "korrespondent": row[4],
                    "kategorie": row[5],
                    "steuerjahr": row[6],
                    "betrag": row[7],
                    "zusammenfassung": row[8],
                    "target_folder": row[9],
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


# Globale Datenbankinstanz
_db_instance: Optional[Database] = None


def get_database() -> Database:
    """Gibt die globale Datenbankinstanz zurück."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance

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

    # Metadaten
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


# Globale Datenbankinstanz
_db_instance: Optional[Database] = None


def get_database() -> Database:
    """Gibt die globale Datenbankinstanz zurück."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance

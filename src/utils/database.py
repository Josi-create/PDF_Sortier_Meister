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

        # Session-Factory
        self.Session = sessionmaker(bind=self.engine)

    def get_session(self):
        """Erstellt eine neue Datenbank-Session."""
        return self.Session()

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
                extracted_text=extracted_text,
                keywords=",".join(keywords) if keywords else None,
                detected_date=detected_date,
                new_filename=new_filename,
                confidence=confidence,
            )
            session.add(entry)

            # Zielordner-Statistik aktualisieren
            self._update_folder_stats(session, target_folder, target_folder_name)

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

    def _update_folder_stats(self, session, folder_path: str, folder_name: str):
        """Aktualisiert die Statistiken eines Zielordners."""
        folder = session.query(TargetFolder).filter(
            TargetFolder.path == folder_path
        ).first()

        if folder:
            folder.usage_count += 1
            folder.last_used = datetime.utcnow()
        else:
            folder = TargetFolder(
                path=folder_path,
                name=folder_name,
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

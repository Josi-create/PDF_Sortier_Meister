"""
Dateimanager für PDF Sortier Meister

Funktionen:
- PDFs im Scan-Ordner finden
- Dateien verschieben und umbenennen
- Ordnerstruktur verwalten
"""

import os
import shutil
from pathlib import Path
from typing import Optional, Generator
from datetime import datetime


class FileManager:
    """Verwaltet Dateioperationen für PDFs."""

    def __init__(self, scan_folder: Path | str = None):
        """
        Initialisiert den FileManager.

        Args:
            scan_folder: Der Ordner, der nach PDFs durchsucht wird
        """
        self._scan_folder: Optional[Path] = None
        if scan_folder:
            self.set_scan_folder(scan_folder)

    @property
    def scan_folder(self) -> Optional[Path]:
        """Gibt den aktuellen Scan-Ordner zurück."""
        return self._scan_folder

    def set_scan_folder(self, folder: Path | str) -> None:
        """
        Setzt den Scan-Ordner.

        Args:
            folder: Pfad zum Scan-Ordner

        Raises:
            ValueError: Wenn der Ordner nicht existiert
        """
        folder = Path(folder)
        if not folder.exists():
            raise ValueError(f"Ordner existiert nicht: {folder}")
        if not folder.is_dir():
            raise ValueError(f"Pfad ist kein Ordner: {folder}")
        self._scan_folder = folder

    def get_pdf_files(self) -> list[Path]:
        """
        Findet alle PDF-Dateien im Scan-Ordner.

        Returns:
            Liste von Pfaden zu PDF-Dateien, sortiert nach Änderungsdatum (neueste zuerst)
        """
        if self._scan_folder is None:
            return []

        # Alle Dateien mit .pdf Endung (case-insensitive)
        pdf_files = [
            f for f in self._scan_folder.iterdir()
            if f.is_file() and f.suffix.lower() == ".pdf"
        ]

        # Nach Änderungsdatum sortieren (neueste zuerst)
        pdf_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        return pdf_files

    def get_pdf_count(self) -> int:
        """Gibt die Anzahl der PDFs im Scan-Ordner zurück."""
        return len(self.get_pdf_files())

    def move_file(
        self,
        source: Path | str,
        target_folder: Path | str,
        new_name: Optional[str] = None
    ) -> Path:
        """
        Verschiebt eine Datei in einen Zielordner.

        Args:
            source: Quelldatei
            target_folder: Zielordner
            new_name: Optionaler neuer Dateiname

        Returns:
            Pfad zur verschobenen Datei

        Raises:
            FileNotFoundError: Wenn Quelldatei nicht existiert
            ValueError: Wenn Zielordner nicht existiert
        """
        source = Path(source)
        target_folder = Path(target_folder)

        if not source.exists():
            raise FileNotFoundError(f"Quelldatei nicht gefunden: {source}")

        if not target_folder.exists():
            raise ValueError(f"Zielordner existiert nicht: {target_folder}")

        # Zieldateiname bestimmen
        if new_name:
            # Sicherstellen, dass .pdf Endung vorhanden ist
            if not new_name.lower().endswith('.pdf'):
                new_name += '.pdf'
            target_name = new_name
        else:
            target_name = source.name

        target_path = target_folder / target_name

        # Falls Datei bereits existiert, Nummer anhängen
        target_path = self._get_unique_path(target_path)

        # Datei verschieben
        shutil.move(str(source), str(target_path))

        return target_path

    def copy_file(
        self,
        source: Path | str,
        target_folder: Path | str,
        new_name: Optional[str] = None
    ) -> Path:
        """
        Kopiert eine Datei in einen Zielordner.

        Args:
            source: Quelldatei
            target_folder: Zielordner
            new_name: Optionaler neuer Dateiname

        Returns:
            Pfad zur kopierten Datei
        """
        source = Path(source)
        target_folder = Path(target_folder)

        if not source.exists():
            raise FileNotFoundError(f"Quelldatei nicht gefunden: {source}")

        if not target_folder.exists():
            raise ValueError(f"Zielordner existiert nicht: {target_folder}")

        # Zieldateiname bestimmen
        if new_name:
            if not new_name.lower().endswith('.pdf'):
                new_name += '.pdf'
            target_name = new_name
        else:
            target_name = source.name

        target_path = target_folder / target_name
        target_path = self._get_unique_path(target_path)

        shutil.copy2(str(source), str(target_path))

        return target_path

    def rename_file(self, source: Path | str, new_name: str) -> Path:
        """
        Benennt eine Datei um.

        Args:
            source: Quelldatei
            new_name: Neuer Dateiname

        Returns:
            Pfad zur umbenannten Datei
        """
        source = Path(source)

        if not source.exists():
            raise FileNotFoundError(f"Datei nicht gefunden: {source}")

        if not new_name.lower().endswith('.pdf'):
            new_name += '.pdf'

        target_path = source.parent / new_name
        target_path = self._get_unique_path(target_path)

        source.rename(target_path)

        return target_path

    def delete_file(self, file_path: Path | str) -> None:
        """
        Löscht eine Datei.

        Args:
            file_path: Zu löschende Datei
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Datei nicht gefunden: {file_path}")

        file_path.unlink()

    def _get_unique_path(self, path: Path) -> Path:
        """
        Gibt einen einzigartigen Pfad zurück (fügt Nummer hinzu wenn nötig).

        Args:
            path: Gewünschter Pfad

        Returns:
            Einzigartiger Pfad
        """
        if not path.exists():
            return path

        stem = path.stem
        suffix = path.suffix
        parent = path.parent

        counter = 1
        while True:
            new_path = parent / f"{stem} ({counter}){suffix}"
            if not new_path.exists():
                return new_path
            counter += 1

    def get_file_info(self, file_path: Path | str) -> dict:
        """
        Gibt Informationen über eine Datei zurück.

        Args:
            file_path: Pfad zur Datei

        Returns:
            Dictionary mit Dateiinformationen
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Datei nicht gefunden: {file_path}")

        stat = file_path.stat()

        return {
            "path": str(file_path),
            "name": file_path.name,
            "stem": file_path.stem,
            "suffix": file_path.suffix,
            "size": stat.st_size,
            "size_human": self._format_size(stat.st_size),
            "created": datetime.fromtimestamp(stat.st_ctime),
            "modified": datetime.fromtimestamp(stat.st_mtime),
            "parent": str(file_path.parent),
        }

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Formatiert eine Dateigröße menschenlesbar."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"


class FolderManager:
    """Verwaltet Zielordner für die Sortierung."""

    def __init__(self):
        """Initialisiert den FolderManager."""
        self._target_folders: list[Path] = []

    @property
    def target_folders(self) -> list[Path]:
        """Gibt die Liste der Zielordner zurück."""
        return self._target_folders.copy()

    def add_folder(self, folder: Path | str) -> None:
        """
        Fügt einen Zielordner hinzu.

        Args:
            folder: Pfad zum Ordner
        """
        folder = Path(folder)

        if not folder.exists():
            raise ValueError(f"Ordner existiert nicht: {folder}")

        if folder not in self._target_folders:
            self._target_folders.append(folder)

    def remove_folder(self, folder: Path | str) -> None:
        """
        Entfernt einen Zielordner.

        Args:
            folder: Pfad zum Ordner
        """
        folder = Path(folder)

        if folder in self._target_folders:
            self._target_folders.remove(folder)

    def load_folders(self, folders: list[str | Path]) -> None:
        """
        Lädt eine Liste von Ordnern.

        Args:
            folders: Liste von Ordnerpfaden
        """
        self._target_folders.clear()
        for folder in folders:
            try:
                self.add_folder(folder)
            except ValueError:
                # Ordner existiert nicht mehr, überspringen
                pass

    def get_folder_info(self, folder: Path | str) -> dict:
        """
        Gibt Informationen über einen Ordner zurück.

        Args:
            folder: Pfad zum Ordner

        Returns:
            Dictionary mit Ordnerinformationen
        """
        folder = Path(folder)

        if not folder.exists():
            raise ValueError(f"Ordner existiert nicht: {folder}")

        # PDFs im Ordner zählen
        pdf_count = len(list(folder.glob("*.pdf"))) + len(list(folder.glob("*.PDF")))

        return {
            "path": str(folder),
            "name": folder.name,
            "pdf_count": pdf_count,
            "parent": str(folder.parent),
        }

    def get_subfolders(self, parent: Path | str) -> list[Path]:
        """
        Gibt alle Unterordner eines Ordners zurück.

        Args:
            parent: Übergeordneter Ordner

        Returns:
            Liste von Unterordnern
        """
        parent = Path(parent)

        if not parent.exists():
            return []

        return [p for p in parent.iterdir() if p.is_dir()]

    def create_folder(self, parent: Path | str, name: str) -> Path:
        """
        Erstellt einen neuen Unterordner.

        Args:
            parent: Übergeordneter Ordner
            name: Name des neuen Ordners

        Returns:
            Pfad zum neuen Ordner
        """
        parent = Path(parent)
        new_folder = parent / name

        new_folder.mkdir(parents=True, exist_ok=True)

        return new_folder

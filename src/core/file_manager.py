"""
Dateimanager für PDF Sortier Meister

Funktionen:
- PDFs im Scan-Ordner finden
- Dateien verschieben und umbenennen
- Ordnerstruktur verwalten

Jede Dateiaenderung wird an den Suchindex gemeldet (``src.search.meldungen``,
Phase 5 der PDFsuche-Integration): Verschieben und Umbenennen behalten Text,
OCR und Metadaten im Index, Loeschen entfernt den Eintrag, neue bzw. veraenderte
Dateien (Kopie, Stapel, Teilen, Zusammenfuegen) werden gelesen. Die Meldungen
laufen in einem eigenen Thread und sind ohne eingerichtete Suche wirkungslos.
"""

import os
import shutil
import time
from pathlib import Path
from typing import Optional, Generator
from datetime import datetime

import fitz  # PyMuPDF
from PyQt6.QtCore import QFile

from src.search.meldungen import melden as index_melden


class PapierkorbNichtVerfuegbar(OSError):
    """Die Datei konnte nicht in den System-Papierkorb verschoben werden."""


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

    @staticmethod
    def _mit_endung(source: Path, new_name: str) -> str:
        """Neuer Name mit der passenden Endung: ".pdf", bei .docx/.xlsx deren eigene (Issue #9)."""
        from src.core.office_convert import endung_tauschen, ist_office_datei

        if ist_office_datei(source):
            return endung_tauschen(new_name, source.suffix.lower())
        return new_name if new_name.lower().endswith('.pdf') else new_name + '.pdf'

    def get_office_files(self) -> list[Path]:
        """Findet .docx/.xlsx und Bilder im Scan-Ordner (Issues #9, #184), nach Name sortiert.

        Word legt waehrend des Bearbeitens Sperrdateien ``~$name.docx`` an;
        die werden ausgelassen.
        """
        if self._scan_folder is None:
            return []
        from src.core.office_convert import sortierbare_endungen

        endungen = sortierbare_endungen()
        dateien = [
            f for f in self._scan_folder.iterdir()
            if f.is_file() and f.suffix.lower() in endungen and not f.name.startswith("~$")
        ]
        dateien.sort(key=lambda p: p.name.lower())
        return dateien

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
            # Sicherstellen, dass die Endung stimmt (.pdf; bei Office-Dateien deren eigene)
            target_name = self._mit_endung(source, new_name)
        else:
            target_name = source.name

        target_path = target_folder / target_name

        # Falls Datei bereits existiert, Nummer anhängen
        target_path = self._get_unique_path(target_path)

        # Datei verschieben
        self._move_with_retry(source, target_path)
        index_melden("datei_verschoben", str(source), str(target_path))

        return target_path

    # Kurzzeitige Sperren (Vorschau-/Metadaten-Reader, Virenscanner, OneDrive)
    # loesen sich meist binnen Millisekunden - deshalb mehrere Versuche, bevor
    # "Verschieben fehlgeschlagen" gemeldet wird.
    MOVE_RETRY_DELAYS = (0.1, 0.2, 0.3, 0.5, 0.8)

    @classmethod
    def _move_with_retry(cls, source: Path, target_path: Path) -> None:
        """``shutil.move`` mit Wiederholung bei ``PermissionError`` (Windows-Dateisperre)."""
        for delay in cls.MOVE_RETRY_DELAYS:
            try:
                shutil.move(str(source), str(target_path))
                return
            except PermissionError:
                time.sleep(delay)
        shutil.move(str(source), str(target_path))

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
            # Endung wie beim Verschieben (.pdf; bei Office-Dateien deren eigene)
            target_name = self._mit_endung(source, new_name)
        else:
            target_name = source.name

        target_path = target_folder / target_name
        target_path = self._get_unique_path(target_path)

        try:
            shutil.copy2(str(source), str(target_path))
        except BaseException:
            # Halbfertige Kopie nicht liegen lassen; das Original wird nie angefasst
            try:
                target_path.unlink()
            except OSError:
                pass
            raise
        index_melden("datei_aufnehmen", str(target_path))

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

        new_name = self._mit_endung(source, new_name)

        target_path = source.parent / new_name
        target_path = self._get_unique_path(target_path)

        source.rename(target_path)
        index_melden("datei_verschoben", str(source), str(target_path))

        return target_path

    def delete_file(self, file_path: Path | str, endgueltig: bool = False) -> Optional[Path]:
        """
        Verschiebt eine Datei in den System-Papierkorb.

        Args:
            file_path: Zu löschende Datei
            endgueltig: True löscht ohne Papierkorb (nur nach ausdrücklicher Rückfrage)

        Returns:
            Pfad der Datei im Papierkorb (None bei endgültigem Löschen oder
            wenn das System keinen Pfad liefert)

        Raises:
            PapierkorbNichtVerfuegbar: Papierkorb geht nicht (z. B. Netzlaufwerk);
                es wird dann NICHT still endgültig gelöscht.
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Datei nicht gefunden: {file_path}")

        papierkorb_pfad: Optional[Path] = None
        if endgueltig:
            file_path.unlink()
        else:
            ok, pfad = QFile.moveToTrash(str(file_path))
            if not ok:
                raise PapierkorbNichtVerfuegbar(
                    f"Papierkorb nicht verfügbar: {file_path}"
                )
            papierkorb_pfad = Path(pfad) if pfad else None
        index_melden("datei_geloescht", str(file_path))
        return papierkorb_pfad

    def merge_pdfs(
        self,
        sources: list[Path | str],
        target_folder: Path | str,
        output_name: str,
    ) -> Path:
        """
        Führt mehrere PDFs zu einer einzigen Datei zusammen.

        Args:
            sources: Liste der zu verbindenden PDF-Dateien
            target_folder: Ordner für das Ergebnis
            output_name: Name der Ziel-PDF-Datei

        Returns:
            Pfad zur zusammengeführten PDF
        """
        if not sources:
            raise ValueError("Es müssen mindestens zwei PDF-Quelldateien angegeben werden.")

        target_folder = Path(target_folder)
        if not target_folder.exists():
            raise ValueError(f"Zielordner existiert nicht: {target_folder}")

        output_name = str(output_name)
        if not output_name.lower().endswith('.pdf'):
            output_name += '.pdf'

        output_path = target_folder / output_name
        output_path = self._get_unique_path(output_path)

        merged_doc = fitz.open()
        try:
            for source in sources:
                source_path = Path(source)
                if not source_path.exists():
                    merged_doc.close()
                    raise FileNotFoundError(f"Quelldatei nicht gefunden: {source_path}")
                with fitz.open(str(source_path)) as src_doc:
                    merged_doc.insert_pdf(src_doc)
            merged_doc.save(str(output_path))
        finally:
            merged_doc.close()
        index_melden("datei_aufnehmen", str(output_path))

        return output_path

    def stack_pdfs(
        self,
        target: Path | str,
        sources: list[Path | str],
        backup_dir: Path | str,
    ) -> list[tuple[Path, Path]]:
        """
        Haengt die Seiten der Quell-PDFs hinten an die Ziel-PDF an
        ("Stapeln" wie in PaperPort: PDF auf eine andere PDF ziehen).

        Die Ziel-PDF behaelt Namen und Metadaten (XMP). Quellen aus dem
        Ordner der Ziel-PDF gehen im Stapel auf und verschwinden dort;
        Quellen aus anderen Ordnern (z. B. aus dem Explorer gezogen) werden
        nur gelesen und bleiben, wo sie sind. Alles, was ueberschrieben oder
        entfernt wird, landet vorher in backup_dir - restore_stack() macht
        den Vorgang damit rueckgaengig.

        Args:
            target: PDF, an die angehaengt wird
            sources: PDFs, deren Seiten angehaengt werden (in dieser Reihenfolge)
            backup_dir: Ordner fuer die Sicherung der Originale (wird angelegt)

        Returns:
            Liste (Originalpfad, Sicherungspfad); der erste Eintrag ist die
            Ziel-PDF, danach die aufgegangenen Quellen
        """
        target = Path(target)
        source_paths = [Path(s) for s in sources]
        if not source_paths:
            raise ValueError("Es muss mindestens eine PDF zum Anhaengen angegeben werden.")
        if not target.exists():
            raise FileNotFoundError(f"Ziel-PDF nicht gefunden: {target}")
        for source in source_paths:
            if source == target:
                raise ValueError("Eine PDF kann nicht auf sich selbst gestapelt werden.")
            if not source.exists():
                raise FileNotFoundError(f"Quelldatei nicht gefunden: {source}")

        temp_path = target.with_name(f"{target.stem}.stapel-tmp.pdf")
        try:
            with fitz.open(str(target)) as doc:
                for source in source_paths:
                    with fitz.open(str(source)) as src_doc:
                        doc.insert_pdf(src_doc)
                doc.save(str(temp_path), garbage=3, deflate=True)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        target_backup = backup_dir / f"0_{target.name}"
        shutil.copy2(str(target), str(target_backup))
        os.replace(str(temp_path), str(target))
        backups = [(target, target_backup)]

        for i, source in enumerate(source_paths, start=1):
            if source.parent != target.parent:
                continue
            source_backup = backup_dir / f"{i}_{source.name}"
            shutil.move(str(source), str(source_backup))
            backups.append((source, source_backup))
            index_melden("datei_geloescht", str(source))
        # Die Ziel-PDF hat neuen Inhalt (Textebene neu, OCR-Seiten aus dem Cache)
        index_melden("datei_geaendert", str(target))

        return backups

    def restore_stack(self, backups: list[tuple[Path, Path]]) -> list[Path]:
        """
        Macht stack_pdfs() rueckgaengig: Die Ziel-PDF bekommt ihren alten
        Inhalt zurueck, aufgegangene Quellen kehren an ihren Platz zurueck.
        Ist ein Name inzwischen neu vergeben, erhaelt die Quelle einen
        freien Namen ("datei (1).pdf").

        Args:
            backups: Rueckgabe von stack_pdfs()

        Returns:
            Die wiederhergestellten Pfade (Ziel zuerst)
        """
        restored = []
        for i, (original, backup) in enumerate(backups):
            original, backup = Path(original), Path(backup)
            if not backup.exists():
                raise FileNotFoundError(f"Sicherung nicht gefunden: {backup}")
            if i == 0:
                os.replace(str(backup), str(original))
                restored.append(original)
                index_melden("datei_geaendert", str(original))
            else:
                dest = self._get_unique_path(original)
                shutil.move(str(backup), str(dest))
                restored.append(dest)
                index_melden("datei_aufnehmen", str(dest))
        return restored

    def split_pdf(
        self,
        source: Path | str,
        target_folder: Path | str,
        pages: Optional[list[int]] = None,
    ) -> list[Path]:
        """
        Teilt ein PDF in einzelne Seiten auf oder extrahiert ausgewählte Seiten.

        Args:
            source: Quelldatei
            target_folder: Ordner für die geteilten PDFs
            pages: Optional Liste von 1-basierten Seitenzahlen. Wenn None, werden alle Seiten einzeln gespeichert.

        Returns:
            Liste der erzeugten PDF-Dateien
        """
        source = Path(source)
        target_folder = Path(target_folder)

        if not source.exists():
            raise FileNotFoundError(f"Quelldatei nicht gefunden: {source}")

        if not target_folder.exists():
            raise ValueError(f"Zielordner existiert nicht: {target_folder}")

        with fitz.open(str(source)) as doc:
            page_count = len(doc)
            if page_count == 0:
                return []

            if pages is None:
                pages = list(range(1, page_count + 1))
            else:
                invalid_pages = [p for p in pages if p < 1 or p > page_count]
                if invalid_pages:
                    raise ValueError(f"Ungültige Seitenzahlen: {invalid_pages}")

            output_paths: list[Path] = []
            for page_number in pages:
                page_index = page_number - 1
                output_name = f"{source.stem}_Seite_{page_number}.pdf"
                output_path = target_folder / output_name
                output_path = self._get_unique_path(output_path)

                new_doc = fitz.open()
                try:
                    new_doc.insert_pdf(doc, from_page=page_index, to_page=page_index)
                    new_doc.save(str(output_path))
                finally:
                    new_doc.close()

                output_paths.append(output_path)
                index_melden("datei_aufnehmen", str(output_path))

        return output_paths

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

    def count_pdfs(self, folder: Path | str) -> int:
        """Anzahl der PDFs direkt in einem Ordner (ohne Unterordner)."""
        folder = Path(folder)
        try:
            return sum(
                1 for p in folder.iterdir()
                if p.is_file() and p.suffix.lower() == ".pdf"
            )
        except (PermissionError, OSError):
            return 0

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

        try:
            folders = [
                p for p in parent.iterdir()
                if p.is_dir() and not p.name.startswith((".", "$", "~"))
            ]
        except (PermissionError, OSError):
            return []
        folders.sort(key=lambda p: p.name.lower())
        return folders

    def get_all_subfolders_recursive(
        self,
        parent: Path | str,
        max_depth: int = 5
    ) -> list[Path]:
        """
        Gibt alle Unterordner rekursiv zurück.

        Args:
            parent: Übergeordneter Ordner
            max_depth: Maximale Tiefe

        Returns:
            Liste aller Unterordner (flach)
        """
        parent = Path(parent)
        result = []

        def recurse(folder: Path, depth: int):
            if depth > max_depth:
                return
            try:
                for p in folder.iterdir():
                    if p.is_dir() and not p.name.startswith('.'):
                        result.append(p)
                        recurse(p, depth + 1)
            except PermissionError:
                pass

        if parent.exists():
            recurse(parent, 0)

        return result

    def get_folder_tree(
        self,
        parent: Path | str,
        max_depth: int = 3
    ) -> dict:
        """
        Gibt eine hierarchische Ordnerstruktur zurück.

        Args:
            parent: Übergeordneter Ordner
            max_depth: Maximale Tiefe

        Returns:
            Dictionary mit Ordnerstruktur:
            {
                'path': Path,
                'name': str,
                'pdf_count': int,
                'children': [...]
            }
        """
        parent = Path(parent)

        def build_tree(folder: Path, depth: int) -> dict:
            pdf_count = len([
                f for f in folder.iterdir()
                if f.is_file() and f.suffix.lower() == '.pdf'
            ]) if folder.exists() else 0

            node = {
                'path': folder,
                'name': folder.name,
                'pdf_count': pdf_count,
                'children': []
            }

            if depth < max_depth:
                try:
                    subfolders = sorted([
                        p for p in folder.iterdir()
                        if p.is_dir() and not p.name.startswith('.')
                    ])
                    for subfolder in subfolders:
                        node['children'].append(build_tree(subfolder, depth + 1))
                except PermissionError:
                    pass

            return node

        if not parent.exists():
            return {'path': parent, 'name': parent.name, 'pdf_count': 0, 'children': []}

        return build_tree(parent, 0)

    def get_relative_path_from_root(
        self,
        folder: Path | str,
        root_folders: list[Path]
    ) -> str:
        """
        Gibt den relativen Pfad eines Ordners zu seinem Root zurück.

        Args:
            folder: Der Ordner
            root_folders: Liste der Root-Ordner

        Returns:
            Relativer Pfad (z.B. "Steuer 2026/Banken")
        """
        folder = Path(folder)

        for root in root_folders:
            try:
                # Prüfen ob folder unter root liegt
                relative = folder.relative_to(root)
                # Root-Name + relativer Pfad
                return str(root.name / relative) if str(relative) != '.' else root.name
            except ValueError:
                continue

        return folder.name

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

    def ensure_folder_exists(self, folder_path: Path | str) -> Path:
        """
        Stellt sicher, dass ein Ordner existiert (erstellt ihn ggf.).

        Args:
            folder_path: Pfad zum Ordner

        Returns:
            Der Ordner-Pfad
        """
        folder_path = Path(folder_path)
        folder_path.mkdir(parents=True, exist_ok=True)
        return folder_path

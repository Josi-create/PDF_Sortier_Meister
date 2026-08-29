"""Sicherung und Wiederherstellung der Anwendungsdaten (Issue #98).

Alles, was PDF Sortier Meister ueber die Zeit ansammelt, liegt im
Datenverzeichnis (siehe ``platform_paths.get_app_data_dir``):

- ``history.db``     Verlauf, Suchindex (FTS5 / RAG), Korrespondenten, Regeln
- ``pdf_cache.db``   Analyse- und KI-Vorschlags-Cache
- ``config.json``    Einstellungen inkl. API-Schluessel
- ``llm_timing.json`` Laufzeit-Schaetzungen fuer die KI-Anzeige
- ``model/``         trainiertes TF-IDF-Modell

Ein Backup ist ein ZIP mit genau diesen Eintraegen plus ``backup_info.json``.
SQLite-Dateien werden ueber die Backup-API kopiert, damit der Schnappschuss
auch bei laufender Anwendung konsistent ist.

Wiederherstellen laeuft zweistufig: ``stage_restore`` entpackt das Archiv
nach ``restore_pending/``; beim naechsten Start (bevor Config/Datenbank
geoeffnet werden) verschiebt ``apply_pending_restore`` die Dateien an ihren
Platz und hebt die ersetzten Dateien unter ``restore_previous/`` auf.
Thumbnails und Logs sind reine Caches und werden nicht gesichert.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

BACKUP_FILES: tuple[str, ...] = ("config.json", "history.db", "pdf_cache.db", "llm_timing.json")
BACKUP_DIRS: tuple[str, ...] = ("model",)
INFO_NAME = "backup_info.json"
PENDING_DIR = "restore_pending"
PREVIOUS_DIR = "restore_previous"


@dataclass
class BackupInfo:
    """Inhalt eines Backups (aus ``backup_info.json`` bzw. beim Erstellen)."""
    created_at: str = ""
    version: str = ""
    entries: list[str] = field(default_factory=list)
    total_bytes: int = 0
    path: Path | None = None

    @property
    def created_display(self) -> str:
        """``2026-08-29 18:30`` (oder der Rohwert, falls unlesbar)."""
        try:
            return datetime.fromisoformat(self.created_at).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return self.created_at or "unbekannt"


def default_backup_name(now: datetime | None = None) -> str:
    """``PDF_Sortier_Meister_Backup_2026-08-29_1830.zip``."""
    now = now or datetime.now()
    return f"PDF_Sortier_Meister_Backup_{now:%Y-%m-%d_%H%M}.zip"


def _snapshot_sqlite(src: Path, dest: Path) -> None:
    """Konsistente Kopie einer SQLite-Datenbank (auch bei offenen Verbindungen)."""
    source = sqlite3.connect(str(src))
    try:
        target = sqlite3.connect(str(dest))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _is_safe_entry(name: str) -> bool:
    """Nur relative Pfade ohne ``..`` innerhalb der bekannten Eintraege."""
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        return False
    top = p.parts[0]
    if len(p.parts) == 1:
        return top in BACKUP_FILES
    return top in BACKUP_DIRS


def create_backup(data_dir: Path, zip_path: Path, version: str = "") -> BackupInfo:
    """Packt die Anwendungsdaten aus ``data_dir`` in ``zip_path``.

    Raises:
        FileNotFoundError: wenn in ``data_dir`` keine bekannte Datei liegt.
    """
    data_dir = Path(data_dir)
    zip_path = Path(zip_path)
    with tempfile.TemporaryDirectory(prefix="pdfsm_backup_") as tmp:
        staged: list[tuple[Path, str]] = []  # (Datei auf Platte, Name im Archiv)
        for name in BACKUP_FILES:
            src = data_dir / name
            if not src.is_file():
                continue
            if src.suffix == ".db":
                dest = Path(tmp) / name
                _snapshot_sqlite(src, dest)
                staged.append((dest, name))
            else:
                staged.append((src, name))
        for dname in BACKUP_DIRS:
            folder = data_dir / dname
            if folder.is_dir():
                for f in sorted(folder.rglob("*")):
                    if f.is_file():
                        staged.append((f, f.relative_to(data_dir).as_posix()))
        if not staged:
            raise FileNotFoundError(f"Keine Anwendungsdaten gefunden in {data_dir}")

        info = BackupInfo(
            created_at=datetime.now().isoformat(timespec="seconds"),
            version=version,
            entries=[arc for _f, arc in staged],
            total_bytes=sum(f.stat().st_size for f, _a in staged),
            path=zip_path,
        )
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f, arc in staged:
                zf.write(f, arc)
            zf.writestr(INFO_NAME, json.dumps({
                "created_at": info.created_at,
                "version": info.version,
                "entries": info.entries,
                "total_bytes": info.total_bytes,
            }, indent=2, ensure_ascii=False))
    return info


def inspect_backup(zip_path: Path) -> BackupInfo:
    """Liest ``backup_info.json`` und prueft, ob das Archiv ein Backup ist.

    Raises:
        ValueError: kein ZIP oder keine bekannten Eintraege.
    """
    zip_path = Path(zip_path)
    if not zipfile.is_zipfile(zip_path):
        raise ValueError(f"{zip_path.name} ist kein ZIP-Archiv.")
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        entries = [n for n in names if not n.endswith("/") and _is_safe_entry(n)]
        if not entries:
            raise ValueError(
                f"{zip_path.name} enthaelt keine Daten von PDF Sortier Meister "
                f"(erwartet z.B. {BACKUP_FILES[1]} oder {BACKUP_FILES[0]})."
            )
        info = BackupInfo(entries=entries, path=zip_path)
        if INFO_NAME in names:
            try:
                raw = json.loads(zf.read(INFO_NAME).decode("utf-8"))
                info.created_at = str(raw.get("created_at", ""))
                info.version = str(raw.get("version", ""))
                info.total_bytes = int(raw.get("total_bytes", 0) or 0)
            except (ValueError, UnicodeDecodeError):
                pass
        if not info.total_bytes:
            info.total_bytes = sum(zf.getinfo(n).file_size for n in entries)
    return info


def stage_restore(zip_path: Path, data_dir: Path) -> BackupInfo:
    """Entpackt das Backup nach ``data_dir/restore_pending`` (eingespielt beim Start)."""
    info = inspect_backup(zip_path)
    pending = Path(data_dir) / PENDING_DIR
    if pending.exists():
        shutil.rmtree(pending)
    pending.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as zf:
        for name in info.entries:
            zf.extract(name, pending)
    return info


def apply_pending_restore(data_dir: Path) -> list[str]:
    """Spielt eine vorbereitete Wiederherstellung ein (vor dem Oeffnen von Config/DB).

    Ersetzte Dateien und Ordner landen unter ``restore_previous/`` (wird
    vorher geleert). Liefert die Namen der eingespielten Eintraege; ``[]``
    wenn nichts ansteht.
    """
    data_dir = Path(data_dir)
    pending = data_dir / PENDING_DIR
    if not pending.is_dir():
        return []
    entries = sorted(pending.iterdir(), key=lambda p: p.name)
    if not entries:
        shutil.rmtree(pending, ignore_errors=True)
        return []

    previous = data_dir / PREVIOUS_DIR
    if previous.exists():
        shutil.rmtree(previous)
    previous.mkdir()

    restored: list[str] = []
    for entry in entries:
        target = data_dir / entry.name
        if target.exists():
            shutil.move(str(target), str(previous / entry.name))
        shutil.move(str(entry), str(target))
        restored.append(entry.name)
    shutil.rmtree(pending, ignore_errors=True)
    return restored

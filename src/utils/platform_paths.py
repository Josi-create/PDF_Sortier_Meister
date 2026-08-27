"""
Zentrale Plattform-Abstraktion fuer Pfade und Shell-Integration.

Alle plattformabhaengigen Basisfunktionen (Datenverzeichnis, Datei/Ordner
mit der Standard-Anwendung oeffnen, Name des Dateimanagers) liegen hier,
damit der Rest der Codebasis ohne verstreute sys.platform-Abfragen
auskommt. sys.platform wird bewusst erst zur Aufrufzeit gelesen, damit
Tests die Plattform per monkeypatch simulieren koennen.

Windows-Verhalten ist byte-identisch zum bisherigen Code: Das
Datenverzeichnis bleibt %APPDATA%\\PDF_Sortier_Meister (Fallback: ~).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP_DIR_NAME = "PDF_Sortier_Meister"


def get_app_data_dir(create: bool = True) -> Path:
    """
    Liefert das Datenverzeichnis der Anwendung (Config, Datenbanken, Logs).

    - Windows: %APPDATA%\\PDF_Sortier_Meister (Fallback: ~\\PDF_Sortier_Meister)
    - macOS:   ~/Library/Application Support/PDF_Sortier_Meister
    - sonst:   $XDG_DATA_HOME/PDF_Sortier_Meister (Fallback: ~/.local/share/...)
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", os.path.expanduser("~")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    path = base / APP_DIR_NAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def open_with_default_app(path: Path | str) -> None:
    """Oeffnet eine Datei oder einen Ordner mit der Standard-Anwendung des Systems."""
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 - gewollter Shell-Aufruf
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)])
    else:
        subprocess.run(["xdg-open", str(path)])


def file_manager_name() -> str:
    """Name des System-Dateimanagers fuer UI-Texte."""
    if sys.platform == "win32":
        return "Explorer"
    if sys.platform == "darwin":
        return "Finder"
    return "Dateimanager"

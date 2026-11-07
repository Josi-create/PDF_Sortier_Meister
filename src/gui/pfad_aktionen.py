"""
Gemeinsame Pfad-Aktionen fuer die Kontextmenues (Issue #154).

"Pfad kopieren" und "Im Explorer anzeigen" gibt es auf den PDF-Kacheln, den
Ordnerzeilen links, im Zielordner-Baum, auf den Vorschlagskacheln und im
Reiter "Suche". Die Beschriftung folgt dem Dateimanager des Systems
(Explorer, Finder).

GPL-3.0-or-later - Copyright (c) 2026
"""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from src.search.plattform import im_dateimanager_zeigen as _datei_markieren
from src.utils.platform_paths import file_manager_name, open_with_default_app

PFAD_KOPIEREN_TEXT = "Pfad kopieren"


def zeigen_text() -> str:
    """Menuetext fuer eine Datei: im Dateimanager markieren."""
    if sys.platform == "darwin":
        return "Im Finder zeigen"
    return f"Im {file_manager_name()} anzeigen"


def oeffnen_text() -> str:
    """Menuetext fuer einen Ordner: im Dateimanager oeffnen."""
    return f"Im {file_manager_name()} öffnen"


def pfad_kopieren(path: Path | str) -> None:
    """Legt den vollstaendigen Pfad (Schreibweise des Systems) in die Zwischenablage."""
    QApplication.clipboard().setText(str(Path(path)))


def im_dateimanager_zeigen(path: Path | str) -> None:
    """Datei im Explorer/Finder markieren, einen Ordner darin oeffnen."""
    p = Path(path)
    if p.is_dir():
        open_with_default_app(p)
    else:
        _datei_markieren(str(p))

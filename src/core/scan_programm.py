"""Hinterlegtes Scanprogramm starten (Issue #270) - Qt-frei.

Der Knopf „Jetzt scannen“ startet nur das Programm, das in den Einstellungen
hinterlegt ist (z. B. VueScan). Gescannt wird dort; die neue Datei erscheint
ueber die Ordner-Beobachtung (Issue #232) von selbst.

GPL-3.0-or-later - Copyright (c) 2026
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

KONFIG_SCHLUESSEL = "scan_programm"


class ScanprogrammFehler(Exception):
    """Das Scanprogramm liess sich nicht starten."""


def bereinigt(pfad: str | None) -> str:
    """Pfad aus der Einstellung ohne Leerraum und umschliessende Anfuehrungszeichen."""
    return (pfad or "").strip().strip('"').strip()


def starten(pfad: str | None) -> None:
    """Startet das Programm unter ``pfad`` und kehrt sofort zurueck.

    Windows: wie ein Doppelklick im Explorer (auch Verknuepfungen .lnk).
    macOS: ein Programmpaket (.app) ueber ``open``. Sonst die Datei direkt.
    """
    pfad = bereinigt(pfad)
    if not pfad:
        raise ScanprogrammFehler("kein Scanprogramm hinterlegt")
    datei = Path(pfad)
    if not datei.exists():
        raise ScanprogrammFehler(f"nicht gefunden: {pfad}")
    try:
        if sys.platform == "win32":
            # Arbeitsordner = Programmordner, wie beim Start ueber das Startmenue
            os.startfile(str(datei), cwd=str(datei.parent))  # noqa: S606 - gewollter Shell-Aufruf
        elif sys.platform == "darwin" and datei.is_dir():
            subprocess.Popen(["open", str(datei)])  # noqa: S603, S607
        else:
            subprocess.Popen([str(datei)], cwd=str(datei.parent))  # noqa: S603
    except OSError as e:
        raise ScanprogrammFehler(str(e)) from e

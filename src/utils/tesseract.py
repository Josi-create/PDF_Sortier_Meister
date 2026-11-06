"""Tesseract-Suche (Qt-frei).

Wird vom PDF-Analyzer (``src/core/pdf_analyzer.py``) und von der
Dokumentensuche (``src/search``) gemeinsam genutzt. ``pdf_analyzer`` importiert
PyQt6, deshalb liegt die Suche hier, damit Hintergrunddienst, MCP-Server und
Arbeitsprozesse sie ohne Qt laden koennen.

Reihenfolge der Suche:
1. Mit der App gebuendelt (PyInstaller: ``<_internal>/tesseract/``)
2. Standard-Installationsorte (Windows: Programme / LocalAppData, macOS: Homebrew)
3. PATH

``sys.platform`` wird bewusst erst zur Aufrufzeit gelesen, damit Tests die
Plattform per monkeypatch simulieren koennen.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional


def _tesseract_candidates() -> list[Path]:
    """Moegliche Tesseract-Installationsorte in Prioritaetsreihenfolge."""
    exe_name = "tesseract.exe" if sys.platform == "win32" else "tesseract"
    candidates = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "tesseract" / exe_name)
    if sys.platform == "win32":
        for env_var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(env_var)
            if not base:
                continue
            candidates.append(Path(base) / "Tesseract-OCR" / "tesseract.exe")
            if env_var == "LOCALAPPDATA":
                candidates.append(Path(base) / "Programs" / "Tesseract-OCR" / "tesseract.exe")
    elif sys.platform == "darwin":
        # Aus dem Finder gestartete Apps haben Homebrew nicht im PATH,
        # darum die Standardpfade explizit pruefen.
        candidates.append(Path("/opt/homebrew/bin/tesseract"))
        candidates.append(Path("/usr/local/bin/tesseract"))
    return candidates


def find_tesseract() -> Optional[str]:
    """Voller Pfad zur Tesseract-Binary oder None."""
    for candidate in _tesseract_candidates():
        if candidate.is_file():
            return str(candidate)
    return shutil.which("tesseract")


def tessdata_dir(tesseract_cmd: Optional[str]) -> Optional[str]:
    """Ordner mit den Sprachdaten zur angegebenen Binary, falls er sich finden laesst.

    Gebuendelt und bei der Windows-Standardinstallation liegt ``tessdata`` neben
    der Binary, bei Homebrew unter ``../share/tessdata``. Sonst None: Tesseract
    nutzt dann seinen eingebauten Standardpfad bzw. ``TESSDATA_PREFIX``.
    """
    if not tesseract_cmd:
        return None
    binary = Path(tesseract_cmd)
    for ordner in (binary.parent / "tessdata", binary.parent.parent / "share" / "tessdata"):
        if ordner.is_dir():
            return str(ordner)
    return None


def fehlende_sprachen(tessdata: str | None, sprachen: str) -> list[str]:
    """Sprachen aus ``deu+eng``, deren ``<sprache>.traineddata`` im Ordner fehlt.

    Leer, wenn der Ordner unbekannt ist (dann entscheidet Tesseract selbst)
    oder alle Sprachdaten vorhanden sind. Die Dokumentensuche schaltet die OCR
    bei fehlenden Daten aus und nennt den Grund im Status, statt jede Seite
    scheitern zu lassen.
    """
    if not tessdata or not os.path.isdir(tessdata):
        return []
    fehlt = []
    for s in sprachen.split("+"):
        s = s.strip()
        if s and not os.path.isfile(os.path.join(tessdata, s + ".traineddata")):
            fehlt.append(s)
    return fehlt

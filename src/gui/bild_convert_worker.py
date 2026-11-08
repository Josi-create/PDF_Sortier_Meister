"""Bilder -> PDF im Hintergrund (Issue #184).

Tesseract braucht je Seite einige Sekunden; der Thread wandelt ein oder mehrere
Bilder in *ein* PDF um und meldet am Ende das Ergebnis.

GPL-3.0-or-later - Copyright (c) 2026
"""

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

# Modulweit importieren (siehe ocr_neu_worker: keine Lazy-Imports im Thread)
from src.core.bild_convert import bilder_in_pdf


class BildConvertWorker(QThread):
    """Wandelt Bilder (Reihenfolge = Seitenfolge) in ein PDF um; die Bilder bleiben unveraendert."""

    # (Quellen, BildErgebnis | None, Fehlertext | None)
    fertig = pyqtSignal(list, object, object)

    def __init__(self, paths: list[Path], parent=None):
        super().__init__(parent)
        self.paths = [Path(p) for p in paths]

    def run(self):
        try:
            self.fertig.emit(self.paths, bilder_in_pdf(self.paths), None)
        except Exception as e:  # noqa: BLE001 - melden, nie den Thread verlieren
            self.fertig.emit(self.paths, None, str(e))

"""
"OCR neu durchführen" im Hintergrund (Issue #150).

Tesseract braucht je Seite einige Sekunden; der Thread erkennt die markierten
PDFs nacheinander und meldet am Ende alle Ergebnisse auf einmal. Beim
Beenden des Programms bricht er vor der naechsten Seite ab
(``requestInterruption``).

GPL-3.0-or-later - Copyright (c) 2026
"""

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

# Modulweit importieren, nicht erst im Thread (Lazy-Imports in Worker-Threads
# veraendern sys.modules waehrend der Tests, siehe conftest.patch_singletons)
from src.core.pdf_analyzer import ocr_neu_durchfuehren


class OcrNeuWorker(QThread):
    """Erkennt die Bildseiten der uebergebenen PDFs neu (am OCR-Cache vorbei)."""

    # Fortschritt: (Nummer ab 1, Anzahl, aktuelle PDF)
    fortschritt = pyqtSignal(int, int, Path)
    # Ergebnis: [(Path, {"index": bool, "seiten": int, "fehler": str | None}), ...]
    fertig = pyqtSignal(list)

    def __init__(self, paths: list[Path], parent=None):
        super().__init__(parent)
        self.paths = [Path(p) for p in paths]

    def run(self):
        ergebnisse = []
        for i, path in enumerate(self.paths, start=1):
            if self.isInterruptionRequested():
                break
            self.fortschritt.emit(i, len(self.paths), path)
            try:
                erg = ocr_neu_durchfuehren(path, abbrechen=self.isInterruptionRequested)
            except Exception as e:  # noqa: BLE001 - je Datei melden, nie den Thread verlieren
                erg = {"index": False, "seiten": 0, "fehler": str(e)}
            ergebnisse.append((path, erg))
        self.fertig.emit(ergebnisse)

"""Word/Excel -> PDF im Hintergrund (Issue #9).

Word oder LibreOffice brauchen einige Sekunden je Datei; der Thread wandelt
die Dateien nacheinander um und meldet am Ende alle Ergebnisse auf einmal.

GPL-3.0-or-later - Copyright (c) 2026
"""

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

# Modulweit importieren (siehe ocr_neu_worker: keine Lazy-Imports im Thread)
from src.core.office_convert import umwandeln


class OfficeConvertWorker(QThread):
    """Wandelt .docx/.xlsx in PDF um; die Originale bleiben unveraendert."""

    # Fortschritt: (Nummer ab 1, Anzahl, aktuelle Datei)
    fortschritt = pyqtSignal(int, int, Path)
    # Ergebnis: [(Quelle, UmwandlungsErgebnis | None, Fehlertext | None), ...]
    fertig = pyqtSignal(list)

    def __init__(self, paths: list[Path], pdfa: bool = False, parent=None):
        super().__init__(parent)
        self.paths = [Path(p) for p in paths]
        self.pdfa = pdfa

    def run(self):
        ergebnisse = []
        for i, path in enumerate(self.paths, start=1):
            if self.isInterruptionRequested():
                break
            self.fortschritt.emit(i, len(self.paths), path)
            try:
                ergebnisse.append((path, umwandeln(path, pdfa=self.pdfa), None))
            except Exception as e:  # noqa: BLE001 - je Datei melden, nie den Thread verlieren
                ergebnisse.append((path, None, str(e)))
        self.fertig.emit(ergebnisse)

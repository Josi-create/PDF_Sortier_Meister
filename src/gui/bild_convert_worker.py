"""Bilder -> PDF im Hintergrund (Issue #184).

Tesseract braucht je Seite einige Sekunden; ``BildConvertWorker`` wandelt ein oder
mehrere Bilder in *ein* PDF um, ``BilderEinzelnWorker`` jedes Bild in ein eigenes.

GPL-3.0-or-later - Copyright (c) 2026
"""

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

# Modulweit importieren (siehe ocr_neu_worker: keine Lazy-Imports im Thread)
from src.core.bild_convert import bilder_in_pdf
from src.core.entzerren import bild_laden, blatt_finden


class BildConvertWorker(QThread):
    """Wandelt Bilder (Reihenfolge = Seitenfolge) in ein PDF um; die Bilder bleiben unveraendert."""

    # (Quellen, BildErgebnis | None, Fehlertext | None)
    fertig = pyqtSignal(list, object, object)

    def __init__(self, paths: list[Path], parent=None, entzerrung: dict | None = None):
        super().__init__(parent)
        self.paths = [Path(p) for p in paths]
        self.entzerrung = entzerrung  # {Bild: Entzerrung} (Issue #205)

    def run(self):
        try:
            self.fertig.emit(self.paths, bilder_in_pdf(self.paths, entzerrung=self.entzerrung), None)
        except Exception as e:  # noqa: BLE001 - melden, nie den Thread verlieren
            self.fertig.emit(self.paths, None, str(e))


class BilderEinzelnWorker(QThread):
    """Wandelt mehrere Bilder je in ein eigenes PDF um (Live-Test 08.11.2026)."""

    # Fortschritt: (Nummer ab 1, Anzahl, aktuelles Bild)
    fortschritt = pyqtSignal(int, int, Path)
    # Ergebnis: [(Quelle, BildErgebnis | None, Fehlertext | None), ...]
    fertig = pyqtSignal(list)

    def __init__(self, paths: list[Path], parent=None, entzerrung: dict | None = None):
        super().__init__(parent)
        self.paths = [Path(p) for p in paths]
        self.entzerrung = entzerrung  # {Bild: Entzerrung} (Issue #205)

    def run(self):
        ergebnisse = []
        for i, path in enumerate(self.paths, start=1):
            if self.isInterruptionRequested():
                break
            self.fortschritt.emit(i, len(self.paths), path)
            try:
                ergebnisse.append((path, bilder_in_pdf([path], entzerrung=self.entzerrung), None))
            except Exception as e:  # noqa: BLE001 - je Bild melden, nie den Thread verlieren
                ergebnisse.append((path, None, str(e)))
        self.fertig.emit(ergebnisse)


class EntzerrErkennungWorker(QThread):
    """Sucht in jedem Foto das Blatt (Issue #205); die Ecken belegen den Dialog vor oder gehen direkt in die Umwandlung."""

    # Ergebnis: [(Bild, Erkennung | None, Fehlertext | None), ...]
    fertig = pyqtSignal(list)

    def __init__(self, paths: list[Path], parent=None):
        super().__init__(parent)
        self.paths = [Path(p) for p in paths]

    def run(self):
        ergebnisse = []
        for path in self.paths:
            if self.isInterruptionRequested():
                break
            try:
                ergebnisse.append((path, blatt_finden(bild_laden(path)), None))
            except Exception as e:  # noqa: BLE001 - je Bild melden, nie den Thread verlieren
                ergebnisse.append((path, None, str(e)))
        self.fertig.emit(ergebnisse)

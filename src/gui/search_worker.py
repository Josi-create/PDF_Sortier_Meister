"""Hintergrund-Threads des Reiters „Suche“ (Phase 4 der PDFsuche-Integration).

Jede Abfrage laeuft in einem eigenen ``QThread``; die ``Suchindex``-Fassade
oeffnet je Aufruf eine eigene Nur-Lese-Verbindung, deshalb blockiert die
Oberflaeche nie und mehrere Abfragen duerfen sich ueberlappen. Jede Anfrage
traegt eine Generation: die Ansicht verwirft Ergebnisse veralteter
Generationen (schnelles Weitertippen, Filterwechsel), statt sie noch
anzuzeigen. Eine laufende SQLite-Abfrage selbst laesst sich nicht abbrechen,
sie ist aber kurz.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal


class SuchAbfrage(QThread):
    """Volltextsuche im Hintergrund.

    Signale:
        fertig(generation, ergebnis): Ergebnis-Dict wie ``Suchindex.suche``
        fehler(generation, text): Abfrage ist fehlgeschlagen (z. B. Datumsfilter)
    """

    fertig = pyqtSignal(int, object)
    fehler = pyqtSignal(int, str)

    def __init__(self, index, generation: int, abfrage: str, argumente: dict | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.index = index
        self.generation = generation
        self.abfrage = abfrage
        self.argumente = dict(argumente or {})

    def run(self) -> None:
        try:
            ergebnis = self.index.suche(self.abfrage, **self.argumente)
        except Exception as e:  # noqa: BLE001 - Fehler gehoeren in die Oberflaeche, nicht in den Thread
            self.fehler.emit(self.generation, str(e))
            return
        self.fertig.emit(self.generation, ergebnis)


class DokumentLaden(QThread):
    """Dokument samt Seitentext (Fundstellen markiert) fuer die Textvorschau.

    Signal ``fertig(generation, dokument, seiten)``; ``dokument`` ist None,
    wenn es den Eintrag nicht mehr gibt, ``seiten`` wie ``Suchindex.seiten_text``.
    """

    fertig = pyqtSignal(int, object, object)

    def __init__(self, index, generation: int, dok_id: int, hervorheben: str | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.index = index
        self.generation = generation
        self.dok_id = dok_id
        self.hervorheben = hervorheben

    def run(self) -> None:
        try:
            dokument = self.index.dokument(self.dok_id)
            seiten = self.index.seiten_text(self.dok_id, hervorheben=self.hervorheben) if dokument else []
        except Exception as e:  # noqa: BLE001
            dokument, seiten = None, [{"seite": 0, "quelle": "fehler", "text": f"Fehler beim Lesen: {e}"}]
        self.fertig.emit(self.generation, dokument, seiten)


class StatusAbfrage(QThread):
    """Indexstand (``Suchindex.status``) im Hintergrund; bei grossen Datenbanken dauert das Zaehlen."""

    fertig = pyqtSignal(object)

    def __init__(self, index, parent=None) -> None:
        super().__init__(parent)
        self.index = index

    def run(self) -> None:
        try:
            status = self.index.status()
        except Exception as e:  # noqa: BLE001
            status = {"vorhanden": False, "fehler": str(e)}
        self.fertig.emit(status)

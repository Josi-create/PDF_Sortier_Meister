"""
Suchfeld fuer Ordner mit Trefferliste (Issue #159)

Wiederverwendbar fuer den Zielordner-Baum (Liste unter dem Feld, schiebt den
Baum nach unten) und die Pfadzeile der PDF-Ansicht (Liste schwebt ueber dem
Inhalt, die Zeile bleibt 20 px hoch). Die Suche (src/core/ordnersuche.py)
laeuft nach ca. 300 ms Tipp-Pause in einem Hintergrund-Thread und wird bei
neuer Eingabe abgebrochen.

Signale: ``treffer_gewaehlt(Path)`` bei Klick oder Enter, ``beendet`` bei Esc,
Fokusverlust oder nach der Auswahl.

GPL-3.0-or-later - Copyright (c) 2026
"""

import threading
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QEvent, QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QLineEdit, QListWidget, QListWidgetItem, QSizePolicy, QVBoxLayout, QWidget

from src.core.ordnersuche import Treffer, suche_ordner

# Laufende Suchthreads: so lange festhalten, bis sie fertig sind (ein
# zerstoerter, noch laufender QThread wuerde das Programm abstuerzen lassen).
_LAUFENDE_THREADS: set["_SucheThread"] = set()

_ROLLE_PFAD = Qt.ItemDataRole.UserRole


class _SucheThread(QThread):
    fertig = pyqtSignal(int, list)  # (Generation, Treffer)

    def __init__(self, generation: int, wurzeln: list[Path], text: str):
        super().__init__()
        self._generation = generation
        self._wurzeln = wurzeln
        self._text = text
        self._stopp = threading.Event()

    def abbrechen(self):
        self._stopp.set()

    def run(self):
        treffer = suche_ordner(self._wurzeln, self._text, abgebrochen=self._stopp.is_set)
        if not self._stopp.is_set():
            self.fertig.emit(self._generation, treffer)


class OrdnerSuchfeld(QWidget):
    """Eingabefeld plus Trefferliste fuer die Ordnersuche."""

    treffer_gewaehlt = pyqtSignal(Path)
    beendet = pyqtSignal()

    VERZOEGERUNG_MS = 300
    ZEILEN_MAX = 6

    def __init__(
        self,
        wurzeln: Callable[[], list[Path]],
        platzhalter: str = "Ordner suchen … (z. B. Zeugn*)",
        schwebend: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._wurzeln = wurzeln
        self._schwebend = schwebend
        self._generation = 0
        self._thread = None
        self._treffer: list[Treffer] = []
        self._enter_vorgemerkt = False  # Enter vor dem Ergebnis: ersten Treffer nehmen

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.eingabe = QLineEdit()
        self.eingabe.setPlaceholderText(platzhalter)
        self.eingabe.setClearButtonEnabled(True)
        self.eingabe.installEventFilter(self)
        layout.addWidget(self.eingabe)

        # Fokus bleibt im Eingabefeld: ein Klick in die Liste nimmt ihn nicht weg
        self.liste = QListWidget(None if schwebend else self)
        self.liste.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.liste.setStyleSheet(
            "QListWidget { font-size: 11px; border: 1px solid #daa520; background: #fffef5; color: black; }"
            " QListWidget::item { padding: 2px 4px; }"
            " QListWidget::item:selected { background: #fff3cd; color: black; }"
        )
        self.liste.itemClicked.connect(self._on_item_geklickt)
        self.liste.setVisible(False)
        if not schwebend:
            layout.addWidget(self.liste)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.VERZOEGERUNG_MS)
        self._timer.timeout.connect(self._suche_starten)
        self.eingabe.textChanged.connect(self._on_text_geaendert)

    # ----------------------------------------------------------------- Suche
    def _on_text_geaendert(self, text: str):
        self._abbrechen()
        if not text.strip():
            self._timer.stop()
            self._treffer = []
            self.liste.setVisible(False)
            return
        self._zeige_hinweis("Suche …")
        self._timer.start()

    def _suche_starten(self):
        text = self.eingabe.text()
        if not text.strip():
            return
        self._abbrechen()
        thread = _SucheThread(self._generation, list(self._wurzeln()), text)
        thread.fertig.connect(self._on_fertig)
        _LAUFENDE_THREADS.add(thread)
        thread.finished.connect(lambda t=thread: _LAUFENDE_THREADS.discard(t))
        self._thread = thread
        thread.start()

    def _abbrechen(self):
        """Verwirft die laufende Suche (neue Eingabe, Esc)."""
        self._enter_vorgemerkt = False
        self._generation += 1
        if self._thread is not None:
            self._thread.abbrechen()
            self._thread = None

    def _on_fertig(self, generation: int, treffer: list):
        if generation != self._generation:
            return
        self._thread = None
        self._treffer = treffer
        self.liste.clear()
        if not treffer:
            self._zeige_hinweis("Kein Ordner gefunden")
            return
        for t in treffer:
            text = t.name if not t.relativ else f"{t.name} — {t.relativ}"
            item = QListWidgetItem(text)
            item.setData(_ROLLE_PFAD, str(t.pfad))
            item.setToolTip(str(t.pfad))
            self.liste.addItem(item)
        self.liste.setCurrentRow(0)
        self._liste_zeigen()
        if self._enter_vorgemerkt:
            self._waehlen(treffer[0].pfad)

    def _zeige_hinweis(self, text: str):
        self.liste.clear()
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.liste.addItem(item)
        self._liste_zeigen()

    def _liste_zeigen(self):
        zeilen = min(max(self.liste.count(), 1), self.ZEILEN_MAX)
        hoehe = zeilen * self.liste.sizeHintForRow(0) + 2 * self.liste.frameWidth() + 2
        self.liste.setFixedHeight(hoehe)
        if self._schwebend:
            fenster = self.window()
            if self.liste.parent() is not fenster:
                self.liste.setParent(fenster)
            self.liste.setFixedWidth(max(self.width(), 320))
            self.liste.move(self.mapTo(fenster, self.eingabe.rect().bottomLeft()))
            self.liste.raise_()
        self.liste.setVisible(True)

    # ------------------------------------------------------------- Auswahl
    def _on_item_geklickt(self, item: QListWidgetItem):
        pfad = item.data(_ROLLE_PFAD)
        if pfad:
            self._waehlen(Path(pfad))

    def _waehlen(self, pfad: Path):
        self.zuruecksetzen()
        self.treffer_gewaehlt.emit(pfad)
        self.beendet.emit()

    def zuruecksetzen(self):
        """Leert Feld und Liste und bricht eine laufende Suche ab."""
        self._abbrechen()
        self._timer.stop()
        self._treffer = []
        self.eingabe.clear()
        self.liste.clear()
        self.liste.setVisible(False)

    def fokus_setzen(self):
        self.eingabe.setFocus()
        self.eingabe.selectAll()

    # --------------------------------------------------------- Tastatur/Fokus
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.eingabe:
            if event.type() == QEvent.Type.KeyPress:
                taste = event.key()
                if taste == Qt.Key.Key_Escape:
                    self.zuruecksetzen()
                    self.beendet.emit()
                    return True
                if taste in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._enter()
                    return True
                if taste in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self._treffer:
                    zeile = self.liste.currentRow() + (1 if taste == Qt.Key.Key_Down else -1)
                    self.liste.setCurrentRow(max(0, min(zeile, self.liste.count() - 1)))
                    return True
            elif event.type() == QEvent.Type.FocusOut and self._schwebend:
                if event.reason() not in (
                    Qt.FocusReason.ActiveWindowFocusReason,
                    Qt.FocusReason.PopupFocusReason,
                ):
                    self.zuruecksetzen()
                    self.beendet.emit()
        return super().eventFilter(obj, event)

    def _enter(self):
        """Enter: markierter Treffer (sonst der erste); Suche noch offen -> sofort."""
        if self._timer.isActive() or self._thread is not None:
            # Ergebnis liegt noch nicht vor: ersten Treffer nehmen, sobald er da ist
            if self._timer.isActive():
                self._timer.stop()
                self._suche_starten()
            self._enter_vorgemerkt = True
            return
        if not self._treffer:
            return
        zeile = max(self.liste.currentRow(), 0)
        self._waehlen(self._treffer[zeile].pfad)

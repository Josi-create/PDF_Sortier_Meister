"""
Suchfeld fuer Ordner mit Trefferliste (Issue #159)

Wiederverwendbar fuer den Zielordner-Baum (Liste unter dem Feld, schiebt den
Baum nach unten) und die Pfadzeile der PDF-Ansicht (Liste schwebt ueber dem
Inhalt, die Zeile bleibt 20 px hoch). Gesucht wird nach ca. 300 ms
Tipp-Pause im Ordner-Index (src/core/ordnersuche.py), der jede Wurzel einmal
im Hintergrund einliest. Solange das laeuft (OneDrive auf dem Mac: Minuten),
zeigt die Liste die bisherigen Treffer und wird alle 500 ms aufgefrischt.

Signale: ``treffer_gewaehlt(Path)`` bei Klick oder Enter, ``beendet`` bei Esc,
Fokusverlust oder nach der Auswahl.

GPL-3.0-or-later - Copyright (c) 2026
"""

from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QLineEdit, QListWidget, QListWidgetItem, QSizePolicy, QVBoxLayout, QWidget

from src.core.ordnersuche import Treffer, indizes_vorwaermen, suche_im_index

_ROLLE_PFAD = Qt.ItemDataRole.UserRole


class OrdnerSuchfeld(QWidget):
    """Eingabefeld plus Trefferliste fuer die Ordnersuche."""

    treffer_gewaehlt = pyqtSignal(Path)
    beendet = pyqtSignal()

    VERZOEGERUNG_MS = 300
    NACHLAUF_MS = 500  # Liste auffrischen, solange der Index noch einliest
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
        self._treffer: list[Treffer] = []
        self.vollstaendig = True  # False: Index liest noch ein, Liste kann wachsen
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
        self._timer.timeout.connect(self._suchen)
        self._nachlauf = QTimer(self)
        self._nachlauf.setSingleShot(True)
        self._nachlauf.setInterval(self.NACHLAUF_MS)
        self._nachlauf.timeout.connect(self._suchen)
        self.eingabe.textChanged.connect(self._on_text_geaendert)

    # ----------------------------------------------------------------- Suche
    def _on_text_geaendert(self, text: str):
        self._abbrechen()
        self._treffer = []  # gehoeren zum alten Text
        if not text.strip():
            self._timer.stop()
            self.liste.setVisible(False)
            return
        self._zeige_hinweis("Suche …")
        self._timer.start()

    def _abbrechen(self):
        """Verwirft die laufende Suche (neue Eingabe, Esc)."""
        self._enter_vorgemerkt = False
        self.vollstaendig = True
        self._nachlauf.stop()

    def _suchen(self):
        """Filtert den Ordner-Index (im Speicher, schnell); liest er noch ein: gleich nochmal."""
        text = self.eingabe.text()
        if not text.strip():
            return
        treffer, self.vollstaendig, gelesen = suche_im_index(self._wurzeln(), text)
        zeile = max(self.liste.currentRow(), 0) if self._treffer else 0
        self._treffer = treffer
        if not self.vollstaendig:
            self._nachlauf.start()
        if not treffer:
            if self.vollstaendig:
                self._zeige_hinweis("Kein Ordner gefunden")
            else:
                self._zeige_hinweis("Suche …")
                self.liste.item(0).setToolTip(f"Bisher {gelesen} Ordner gelesen")
            return
        self.liste.clear()
        for t in treffer:
            text = t.name if not t.relativ else f"{t.name} — {t.relativ}"
            item = QListWidgetItem(text)
            item.setData(_ROLLE_PFAD, str(t.pfad))
            item.setToolTip(str(t.pfad))
            self.liste.addItem(item)
        if not self.vollstaendig:
            hinweis = QListWidgetItem(f"… Ordner werden noch eingelesen ({gelesen} bisher)")
            hinweis.setFlags(Qt.ItemFlag.NoItemFlags)
            self.liste.addItem(hinweis)
        self.liste.setCurrentRow(min(zeile, len(treffer) - 1))
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
        indizes_vorwaermen(self._wurzeln())
        self.eingabe.setFocus()
        self.eingabe.selectAll()

    # --------------------------------------------------------- Tastatur/Fokus
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.eingabe:
            if event.type() == QEvent.Type.FocusIn:
                # Ordner schon einlesen, waehrend getippt wird
                indizes_vorwaermen(self._wurzeln())
            elif event.type() == QEvent.Type.KeyPress:
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
                    self.liste.setCurrentRow(max(0, min(zeile, len(self._treffer) - 1)))
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
        """Enter: markierter Treffer (sonst der erste); noch kein Ergebnis -> sobald eins da ist."""
        if self._timer.isActive():
            self._timer.stop()
            self._suchen()
        if self._treffer:
            zeile = max(self.liste.currentRow(), 0)
            self._waehlen(self._treffer[min(zeile, len(self._treffer) - 1)].pfad)
        elif not self.vollstaendig:
            self._enter_vorgemerkt = True  # Index liest noch ein: ersten Treffer nehmen

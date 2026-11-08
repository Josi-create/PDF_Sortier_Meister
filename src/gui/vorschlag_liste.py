"""
Kompakte Ordnervorschlaege (rechte Spalte "Vorgeschlagene Ziele").

* ``VorschlagZeile``: ein FolderWidget als schlanke Zeile (Symbol, fetter Name,
  darunter grau der volle Pfad des Elternordners, Prozentzahl rechts). Passt der
  Pfad nicht, faellt er von links in ganzen Ordnern weg (``pfad_kuerzen``): der
  Ordner direkt ueber dem Ziel bleibt am laengsten sichtbar. Drop, Menue, Regenbogen und Signale
  erbt sie unveraendert von FolderWidget.
* ``SpaltenLayout``: verteilt die Zeilen zeilenweise auf 1 bis 3 Spalten, je
  nach verfuegbarer Breite. Die Mindestbreite bleibt klein (keine Rueckkopplung
  auf den Splitter).
* ``VorschlagListe``: Scrollbereich darum; scrollt erst ab ``MAX_ZEILEN`` Reihen.
"""

from typing import Callable

from PyQt6.QtCore import QEvent, QRect, QSize, Qt
from PyQt6.QtGui import QCursor, QFont, QFontMetrics
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from src.gui.folder_widget import FolderWidget

ZEILEN_HOEHE = 44
ZEILEN_MIN_BREITE = 210  # darunter wird eine Spalte weniger genommen
MAX_SPALTEN = 3
ABSTAND = 6
MAX_ZEILEN = 3  # sichtbare Reihen, danach vertikal scrollen
AUSLASSUNG = "…"


def pfad_kuerzen(pfad: str, messen: Callable[[str], int], breite: int) -> str:
    r"""Kuerzt einen Pfad von links in ganzen Ordnern, rechts hat Vorrang.

    ``C:\A\B\C\E`` wird je nach Breite zu ``…\B\C\E``, ``…\C\E`` oder ``…\E``.
    Passt selbst der letzte Ordner nicht, wird er links gekuerzt (Ende bleibt lesbar).
    ``messen`` liefert die Textbreite in Pixeln (QFontMetrics.horizontalAdvance).
    """
    if not pfad or messen(pfad) <= breite:
        return pfad
    sep = "\\" if "\\" in pfad else "/"
    teile = [t for t in pfad.replace("/", sep).split(sep) if t]
    for anzahl in range(len(teile) - 1, 0, -1):
        kandidat = AUSLASSUNG + sep + sep.join(teile[-anzahl:])
        if messen(kandidat) <= breite:
            return kandidat
    letzter = teile[-1] if teile else pfad
    for start in range(1, len(letzter)):
        kandidat = AUSLASSUNG + letzter[start:]
        if messen(kandidat) <= breite:
            return kandidat
    return AUSLASSUNG


class VorschlagZeile(FolderWidget):
    """Kompakte Vorschlagszeile (name_label = Ordnername, path_label = voller Elternpfad)."""

    def __init__(self, folder_path, parent=None):
        self._name_voll = ""
        self._pfad_voll = ""
        self._geometrie_bekannt = False
        super().__init__(folder_path, 0, parent)

    def setup_ui(self):
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setLineWidth(1)
        self.setFixedHeight(ZEILEN_HOEHE)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._update_style()
        self.setToolTip(f"{self.folder_path}\nAnklicken verschiebt die ausgewählte PDF hierher.")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)

        self.icon_label = QLabel("📁")
        self.icon_label.setStyleSheet("font-size: 16px; background: transparent; border: none;")
        layout.addWidget(self.icon_label)

        textspalte = QVBoxLayout()
        textspalte.setSpacing(0)
        textspalte.setContentsMargins(0, 0, 0, 0)
        self.name_label = self._label(bold=True, px=12)
        self.path_label = self._label(bold=False, px=10, farbe="#666")
        textspalte.addWidget(self.name_label)
        textspalte.addWidget(self.path_label)
        layout.addLayout(textspalte, 1)

        self.count_label = QLabel()
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.count_label.setStyleSheet("font-size: 11px; color: #666; background: transparent; border: none;")
        layout.addWidget(self.count_label)

        self.set_anzeige(self.folder_path.name, "")

    @staticmethod
    def _label(bold: bool, px: int, farbe: str = "#222") -> QLabel:
        lab = QLabel()
        lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lab.setStyleSheet(f"color: {farbe}; background: transparent; border: none;")
        font = QFont(lab.font())
        font.setPixelSize(px)
        font.setBold(bold)
        lab.setFont(font)
        return lab

    def _update_count_label(self):
        pass  # Prozentzahl setzt das Hauptfenster

    def set_anzeige(self, name: str, pfad: str):
        """Setzt Ordnername und Elternpfad (ungekuerzt); Kuerzen passiert nach Breite.

        Der Name wird rechts gekuerzt, der Pfad von links in ganzen Ordnern.
        """
        self._name_voll = name
        self._pfad_voll = pfad
        self.path_label.setVisible(bool(pfad))
        self._kuerzen()

    def _kuerzen(self):
        name, pfad = self._name_voll, self._pfad_voll
        if self._geometrie_bekannt:
            breite = self.name_label.width()
            if breite > 1:
                name = QFontMetrics(self.name_label.font()).elidedText(
                    name, Qt.TextElideMode.ElideRight, breite)
            breite = self.path_label.width()
            if breite > 1:
                pfad = pfad_kuerzen(pfad, QFontMetrics(self.path_label.font()).horizontalAdvance, breite)
        self.name_label.setText(name)
        self.path_label.setText(pfad)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._geometrie_bekannt = True
        self._kuerzen()

    def showEvent(self, event):
        super().showEvent(event)
        self._kuerzen()


class SpaltenLayout(QLayout):
    """Zeilenweise Verteilung auf 1..MAX_SPALTEN gleich breite Spalten."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def _sichtbar(self):
        return [i for i in self._items if not i.isEmpty()]

    def spalten(self, breite: int) -> int:
        """Spaltenzahl fuer die Breite; andere Inhalte (Platzhalter) bekommen die ganze Breite."""
        items = self._sichtbar()
        if any(not isinstance(i.widget(), VorschlagZeile) for i in items):
            return 1
        return max(1, min(MAX_SPALTEN, (breite + ABSTAND) // (ZEILEN_MIN_BREITE + ABSTAND)))

    def _reihen_hoehen(self, spalten: int):
        items = self._sichtbar()
        hoehen = []
        for start in range(0, len(items), spalten):
            hoehen.append(max(i.sizeHint().height() for i in items[start:start + spalten]))
        return hoehen

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, breite):
        m = self.contentsMargins()
        innen = breite - m.left() - m.right()
        hoehen = self._reihen_hoehen(self.spalten(innen))
        gesamt = sum(hoehen) + ABSTAND * max(len(hoehen) - 1, 0)
        return gesamt + m.top() + m.bottom()

    def setGeometry(self, rect):
        super().setGeometry(rect)
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        n = self.spalten(r.width())
        zelle = (r.width() - ABSTAND * (n - 1)) // n
        items = self._sichtbar()
        y = r.top()
        for start in range(0, len(items), n):
            reihe = items[start:start + n]
            hoehe = max(i.sizeHint().height() for i in reihe)
            for k, item in enumerate(reihe):
                item.setGeometry(QRect(r.left() + k * (zelle + ABSTAND), y, zelle, hoehe))
            y += hoehe + ABSTAND

    def sizeHint(self):
        return QSize(ZEILEN_MIN_BREITE, self.heightForWidth(ZEILEN_MIN_BREITE))

    def minimumSize(self):
        # bewusst klein: der Inhalt darf die Splitter-Spalte nie aufweiten
        return QSize(60, 0)


class _Inhalt(QWidget):
    """Innenwidget; meldet Layout- und Groessenaenderungen an die Liste."""

    def __init__(self, liste):
        super().__init__()
        self._liste = liste

    def event(self, e):
        ergebnis = super().event(e)
        if e.type() in (QEvent.Type.LayoutRequest, QEvent.Type.Resize):
            self._liste._hoehe_anpassen()
        return ergebnis


class VorschlagListe(QScrollArea):
    """Scrollbereich mit ``spalten`` (SpaltenLayout); Hoehe waechst bis MAX_ZEILEN Reihen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.inhalt = _Inhalt(self)
        # Nur dieses Widget: ein Stylesheet ohne Selektor erben auch die Tooltips
        # der Zeilen - transparent wird unter Windows zu schwarzen Tooltips
        self.inhalt.setObjectName("vorschlagInhalt")
        self.inhalt.setStyleSheet("QWidget#vorschlagInhalt { background: transparent; }")
        self.viewport().setAutoFillBackground(False)
        self.spalten = SpaltenLayout(self.inhalt)
        self.setWidget(self.inhalt)
        self._hoehe_anpassen()

    def _hoehe_anpassen(self):
        breite = max(self.viewport().width(), 1)
        bedarf = self.spalten.heightForWidth(breite)
        deckel = MAX_ZEILEN * ZEILEN_HOEHE + (MAX_ZEILEN - 1) * ABSTAND
        ziel = max(min(bedarf, deckel), 1)
        if self.height() != ziel:
            self.setFixedHeight(ziel)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._hoehe_anpassen()

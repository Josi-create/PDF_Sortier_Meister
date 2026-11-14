"""Kopfzeile ueber den Kacheln: Ordnername, der bei Platzmangel lesbar bleibt (Issue #269)."""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QLabel

# Rechter Block der Kopfzeile: Anzahl (sehr klein) ueber den Auswahlfeldern. Zusammen
# 28 px - so hoch sind die Navigationsknoepfe links daneben; damit wird die Zeile mit
# keiner Schrift hoeher als vorher.
KOPF_ZAHL_SCHRIFT = 9
KOPF_ZAHL_HOEHE = 10
KOPF_AUSWAHL_HOEHE = 18


class OrdnerTitel(QLabel):
    """Einzeilige Ueberschrift "PDFs in: <Ordner>", die den Ordnernamen bevorzugt.

    Reicht der Platz nicht fuer den ganzen Text, steht nur der Ordnername da; ist
    auch der zu lang, bleibt sein rechter Teil stehen ("…Rechnungen 2026").
    ``text()`` liefert weiter den ganzen Text. Die Mindestbreite ist gedeckelt,
    damit ein langer Name die Spalte nicht verbreitert (Issue #188).
    """

    MINDESTBREITE = 40
    # Bis zu dieser Breite geht der Ordnername vor den Auswahlfeldern daneben
    VORRANG_BREITE = 130

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._kurz = ""

    def setText(self, text: str) -> None:
        self._kurz = ""
        super().setText(text)

    def setze_ordner(self, text: str, ordnername: str) -> None:
        """Setzt den ganzen Text und den Ordnernamen, der bei Platzmangel allein steht."""
        super().setText(text)
        self._kurz = ordnername
        self.updateGeometry()
        self.update()

    def angezeigter_text(self) -> str:
        """Der Text, der bei der aktuellen Breite gemalt wird."""
        breite = self.contentsRect().width()
        fm = self.fontMetrics()
        if fm.horizontalAdvance(self.text()) <= breite:
            return self.text()
        return fm.elidedText(self._kurz or self.text(), Qt.TextElideMode.ElideLeft, breite)

    def minimumSizeHint(self) -> QSize:
        raender = self.contentsMargins()
        bedarf = self.fontMetrics().horizontalAdvance(self._kurz) + raender.left() + raender.right()
        breite = max(self.MINDESTBREITE, min(bedarf, self.VORRANG_BREITE))
        return QSize(breite, super().minimumSizeHint().height())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(
            self.contentsRect(),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.angezeigter_text(),
        )
        painter.end()

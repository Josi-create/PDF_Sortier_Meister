"""
Einfarbiges Lupen-Symbol (Issue #295)

Das Emoji 🔍 ist bunt (blaues Glas, farbiger Griff) und im dunklen Schema
schlecht als Lupe zu erkennen. Dieses Symbol wird in der Textfarbe des
aktiven Farbschemas gezeichnet: dunkel auf hellem, hell auf dunklem Grund.

GPL-3.0-or-later - Copyright (c) 2026
"""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from src.gui.farben import qfarbe


def lupen_pixmap(farbe: QColor, groesse: int = 16) -> QPixmap:
    """Zeichnet eine Lupe (Ring plus Griff) in einer Farbe auf transparentem Grund."""
    pix = QPixmap(groesse, groesse)
    pix.fill(Qt.GlobalColor.transparent)
    maler = QPainter(pix)
    maler.setRenderHint(QPainter.RenderHint.Antialiasing)
    strich = max(1.5, groesse / 9)
    stift = QPen(farbe, strich)
    stift.setCapStyle(Qt.PenCapStyle.RoundCap)
    maler.setPen(stift)
    maler.setBrush(Qt.BrushStyle.NoBrush)
    rand = strich / 2 + 0.5
    durchmesser = groesse * 0.62
    maler.drawEllipse(QRectF(rand, rand, durchmesser, durchmesser))
    # Griff vom Ring schraeg nach rechts unten
    mitte = rand + durchmesser / 2
    ansatz = mitte + durchmesser / 2 * 0.7071
    ende = groesse - rand
    maler.setPen(QPen(farbe, strich * 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    maler.drawLine(QPointF(ansatz, ansatz), QPointF(ende, ende))
    maler.end()
    return pix


def lupen_symbol(groesse: int = 16) -> QIcon:
    """Lupe in der Textfarbe des aktiven Farbschemas.

    Mehrere Groessen, damit sie bei Bildschirm-Skalierung (125 %, 150 %, 200 %)
    scharf bleibt; Qt waehlt die passende.
    """
    farbe = qfarbe("schwarz")
    symbol = QIcon()
    for faktor in (1, 1.25, 1.5, 2, 3):
        symbol.addPixmap(lupen_pixmap(farbe, round(groesse * faktor)))
    return symbol

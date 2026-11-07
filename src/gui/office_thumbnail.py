"""Kachel fuer .docx/.xlsx im Scan-Ordner (Issue #9).

Wie eine PDF-Kachel, aber mit einfachem Platzhalter-Bild, ohne Auswahl,
Analyse und Drag & Drop. Kontextmenue: Oeffnen, Ablageort, "In PDF umwandeln".
Das PDF entsteht neben der Originaldatei und wird danach wie jedes andere
Scan-Ordner-PDF einsortiert.

GPL-3.0-or-later - Copyright (c) 2026
"""

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu

from src.core.office_convert import WORD_ENDUNGEN
from src.gui.pdf_thumbnail import PDFThumbnailWidget
from src.gui.pfad_aktionen import (
    PFAD_KOPIEREN_TEXT,
    im_dateimanager_zeigen,
    pfad_kopieren,
    zeigen_text,
)
from src.gui.tile_view import TileView

WORD_FARBE = "#2b579a"
EXCEL_FARBE = "#217346"


def platzhalter_bild(pfad: Path, breite: int = 140, hoehe: int = 160) -> QPixmap:
    """Einfaches Seitenbild: weisse Seite, farbiger Balken mit Dateityp."""
    farbe = QColor(WORD_FARBE if pfad.suffix.lower() in WORD_ENDUNGEN else EXCEL_FARBE)
    pixmap = QPixmap(breite, hoehe)
    pixmap.fill(QColor("white"))
    p = QPainter(pixmap)
    try:
        p.fillRect(0, 0, breite, 38, farbe)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(20)
        p.setFont(font)
        p.setPen(QColor("white"))
        p.drawText(0, 0, breite, 38, int(Qt.AlignmentFlag.AlignCenter), pfad.suffix.upper().lstrip("."))
        # Textzeilen andeuten
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#d0d0d0"))
        for i in range(6):
            p.drawRect(14, 56 + i * 16, breite - 28 - (i % 3) * 18, 6)
    finally:
        p.end()
    return pixmap


class OfficeThumbnailWidget(PDFThumbnailWidget):
    """Kachel einer Word-/Excel-Datei. ``pdf_path`` ist hier der Pfad der Office-Datei."""

    convert_requested = pyqtSignal(Path, bool)  # (Datei, als PDF/A)

    _BASE_TOOLTIP = (
        "Word-/Excel-Datei. Doppelklick öffnet sie im Standardprogramm.\n"
        "Rechtsklick: In PDF umwandeln (die Originaldatei bleibt erhalten)."
    )

    def __init__(self, pfad: Path, parent=None, view: Optional[TileView] = None):
        super().__init__(pfad, parent, view)
        self.setAcceptDrops(False)  # kein Stapeln auf Office-Dateien

    def load_thumbnail(self):
        """Statt PDF-Render: Platzhalter (kein Hintergrund-Thread)."""
        self._on_thumbnail_loaded(platzhalter_bild(self.pdf_path))

    def mousePressEvent(self, event: QMouseEvent):
        """Kein Auswahl-/Analyse-Ablauf: nur die Hover-Vorschau ausblenden."""
        self._hide_hover_preview()

    def mouseMoveEvent(self, event: QMouseEvent):
        """Kein Drag & Drop in Zielordner (dort gehoeren PDFs hin)."""

    def _build_context_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("Öffnen").triggered.connect(lambda: self.open_requested.emit(self.pdf_path))
        menu.addAction(zeigen_text()).triggered.connect(lambda: im_dateimanager_zeigen(self.pdf_path))
        menu.addAction(PFAD_KOPIEREN_TEXT).triggered.connect(lambda: pfad_kopieren(self.pdf_path))
        menu.addSeparator()
        convert = menu.addAction("In PDF umwandeln")
        convert.setToolTip("Erzeugt ein PDF neben der Datei; das Original bleibt erhalten")
        convert.triggered.connect(lambda: self.convert_requested.emit(self.pdf_path, False))
        convert_a = menu.addAction("In PDF/A umwandeln (Langzeitarchiv)")
        convert_a.setToolTip("Wie oben, als archivfähiges PDF/A")
        convert_a.triggered.connect(lambda: self.convert_requested.emit(self.pdf_path, True))
        return menu

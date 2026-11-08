"""Kachel fuer .docx/.xlsx im Scan-Ordner (Issue #9).

Wie eine PDF-Kachel, aber mit einfachem Platzhalter-Bild, ohne Auswahl,
Analyse und Drag & Drop. Kontextmenue: Oeffnen, Ablageort, "In PDF umwandeln".
Das PDF entsteht neben der Originaldatei und wird danach wie jedes andere
Scan-Ordner-PDF einsortiert.

GPL-3.0-or-later - Copyright (c) 2026
"""

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QImageReader, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu

from src.core import office_vorschau
from src.core.bild_convert import erste_seite_png, ist_bild_datei
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
BILD_FARBE = "#7a5195"


def _typfarbe(pfad: Path) -> str:
    if ist_bild_datei(pfad):
        return BILD_FARBE
    return WORD_FARBE if pfad.suffix.lower() in WORD_ENDUNGEN else EXCEL_FARBE


def platzhalter_bild(pfad: Path, breite: int = 140, hoehe: int = 160) -> QPixmap:
    """Einfaches Seitenbild: weisse Seite, farbiger Balken mit Dateityp."""
    farbe = QColor(_typfarbe(pfad))
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


def text_seite(zeilen: list[str], pfad: Path, breite: int = 140, hoehe: int = 160) -> QImage:
    """Kleine weisse Seite mit den ersten Textzeilen (selbst gezeichnet)."""
    bild = QImage(breite, hoehe, QImage.Format.Format_ARGB32_Premultiplied)
    bild.fill(QColor("white"))
    p = QPainter(bild)
    try:
        farbe = QColor(_typfarbe(pfad))
        p.fillRect(0, 0, breite, 4, farbe)
        font = QFont()
        font.setPixelSize(9)
        p.setFont(font)
        p.setPen(QColor("#333333"))
        fm = p.fontMetrics()
        y = 8
        for zeile in zeilen:
            if y + fm.height() > hoehe - 4:
                break
            p.drawText(6, y, breite - 12, fm.height(), int(Qt.AlignmentFlag.AlignLeft),
                       fm.elidedText(zeile, Qt.TextElideMode.ElideRight, breite - 12))
            y += fm.height() + 1
    finally:
        p.end()
    return bild


def bild_kachelbild(pfad: Path, groesse: int = 400) -> Optional[QImage]:
    """Kachelbild einer Bilddatei (Issue #184): Qt liest es (mit EXIF-Ausrichtung), sonst pymupdf/Pillow."""
    leser = QImageReader(str(pfad))
    leser.setAutoTransform(True)
    original = leser.size()
    if original.isValid() and max(original.width(), original.height()) > groesse:
        leser.setScaledSize(original.scaled(groesse, groesse, Qt.AspectRatioMode.KeepAspectRatio))
    bild = leser.read()
    if not bild.isNull():
        return bild
    roh = erste_seite_png(pfad, groesse)
    if roh:
        bild = QImage.fromData(roh)
        if not bild.isNull():
            return bild
    return None


def kachelbild(pfad: Path) -> Optional[QImage]:
    """Bestes schnell verfuegbares Bild: eingebettet, Windows-Shell, erste Textzeilen.

    Startet weder Word noch Excel. Laeuft im Hintergrund-Thread (nur QImage).
    """
    if ist_bild_datei(pfad):
        return bild_kachelbild(pfad)
    roh = office_vorschau.eingebettetes_bild(pfad)
    if roh:
        bild = QImage.fromData(roh)
        if not bild.isNull():
            return bild
    shell = office_vorschau.shell_bild(pfad)
    if shell:
        b, h, daten = shell
        bild = QImage(daten, b, h, b * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()
        weiss = QImage(b, h, QImage.Format.Format_ARGB32_Premultiplied)
        weiss.fill(QColor("white"))
        q = QPainter(weiss)
        q.drawImage(0, 0, bild)
        q.end()
        return weiss
    zeilen = office_vorschau.erste_zeilen(pfad)
    return text_seite(zeilen, pfad) if zeilen else None


class KachelbildThread(QThread):
    """Laedt das Kachelbild im Hintergrund; ohne Ergebnis bleibt der Platzhalter."""

    bild_fertig = pyqtSignal(QImage)

    def __init__(self, pfad: Path, parent=None):
        super().__init__(parent)
        self.pfad = pfad

    def run(self):
        try:
            bild = kachelbild(self.pfad)
        except Exception:  # noqa: BLE001 - Platzhalter genuegt
            bild = None
        if bild is not None and not bild.isNull():
            self.bild_fertig.emit(bild)


class OfficeThumbnailWidget(PDFThumbnailWidget):
    """Kachel einer Word-/Excel-Datei. ``pdf_path`` ist hier der Pfad der Office-Datei."""

    convert_requested = pyqtSignal(Path, bool)  # (Datei, als PDF/A)
    bilder_zusammenfuegen_requested = pyqtSignal(Path)  # markierte Bilder zu einem PDF (Issue #184)

    _OFFICE_TOOLTIP = (
        "Word-/Excel-Datei. Anklicken wählt sie aus (Strg/Umschalt für Mehrfachauswahl).\n"
        "Ziehen verschiebt sie per Drag & Drop in einen Zielordner.\n"
        "Doppelklick öffnet sie im Standardprogramm.\n"
        "Rechtsklick: In PDF umwandeln (die Originaldatei bleibt erhalten)."
    )

    _BILD_TOOLTIP = (
        "Bild. Anklicken wählt es aus (Strg/Umschalt für Mehrfachauswahl).\n"
        "Ziehen verschiebt es per Drag & Drop in einen Zielordner.\n"
        "Doppelklick öffnet es im Standardprogramm.\n"
        "Rechtsklick: In PDF umwandeln (mit Texterkennung; das Bild bleibt erhalten)."
    )

    @property
    def _BASE_TOOLTIP(self) -> str:  # noqa: N802 - ersetzt das Klassenattribut der PDF-Kachel
        return self._BILD_TOOLTIP if ist_bild_datei(self.pdf_path) else self._OFFICE_TOOLTIP

    def __init__(self, pfad: Path, parent=None, view: Optional[TileView] = None):
        super().__init__(pfad, parent, view)
        self.setAcceptDrops(False)  # Stapeln (PDF auf PDF) gibt es nur bei PDFs

    def load_thumbnail(self):
        """Sofort der Platzhalter, danach (im Hintergrund) das beste echte Bild."""
        self._on_thumbnail_loaded(platzhalter_bild(self.pdf_path))
        thread = KachelbildThread(self.pdf_path, self)
        thread.bild_fertig.connect(self._on_kachelbild)
        self._loader_thread = thread  # cleanup() wartet darauf
        thread.start()

    def _on_kachelbild(self, bild: QImage):
        pixmap = QPixmap.fromImage(bild)
        if not pixmap.isNull():
            self._original_pixmap = pixmap
            self._apply_thumbnail_pixmap()

    def _markierte_bilder(self) -> list[Path]:
        """Die markierten Bilder, wenn diese Kachel zur Mehrfachauswahl gehoert (sonst leer)."""
        auswahl = getattr(self.window(), "selected_pdfs", None) or []
        bilder = [p for p in auswahl if ist_bild_datei(p)]
        return bilder if self.pdf_path in bilder else []

    def _build_context_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("Öffnen").triggered.connect(lambda: self.open_requested.emit(self.pdf_path))
        menu.addAction(zeigen_text()).triggered.connect(lambda: im_dateimanager_zeigen(self.pdf_path))
        menu.addAction(PFAD_KOPIEREN_TEXT).triggered.connect(lambda: pfad_kopieren(self.pdf_path))
        menu.addSeparator()
        menu.addAction("Verschieben nach...").triggered.connect(lambda: self.move_requested.emit(self.pdf_path))
        menu.addSeparator()
        if ist_bild_datei(self.pdf_path):
            convert = menu.addAction("In PDF umwandeln")
            convert.setToolTip("Erzeugt ein durchsuchbares PDF (Texterkennung) neben dem Bild")
            convert.triggered.connect(lambda: self.convert_requested.emit(self.pdf_path, False))
            bilder = self._markierte_bilder()
            if len(bilder) > 1:
                zusammen = menu.addAction(f"Zu einem PDF zusammenfügen ({len(bilder)} Bilder)")
                zusammen.setToolTip("Ein PDF aus den markierten Bildern, in der Reihenfolge der Ansicht")
                zusammen.triggered.connect(lambda: self.bilder_zusammenfuegen_requested.emit(self.pdf_path))
            menu.addSeparator()
            menu.addAction("Löschen").triggered.connect(lambda: self.delete_requested.emit(self.pdf_path))
            return menu
        convert = menu.addAction("In PDF umwandeln")
        convert.setToolTip("Erzeugt ein PDF neben der Datei; das Original bleibt erhalten")
        convert.triggered.connect(lambda: self.convert_requested.emit(self.pdf_path, False))
        convert_a = menu.addAction("In PDF/A umwandeln (Langzeitarchiv)")
        convert_a.setToolTip("Wie oben, als archivfähiges PDF/A")
        convert_a.triggered.connect(lambda: self.convert_requested.emit(self.pdf_path, True))
        menu.addSeparator()
        menu.addAction("Löschen").triggered.connect(lambda: self.delete_requested.emit(self.pdf_path))
        return menu

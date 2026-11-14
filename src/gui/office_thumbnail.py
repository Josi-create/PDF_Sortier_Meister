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
from PyQt6.QtWidgets import QLabel, QMenu

from src.core import office_vorschau
from src.core.bild_convert import erste_seite_png, ist_bild_datei
from src.core.bild_drehen import ist_drehbares_bild
from src.core.office_convert import TEXT_ENDUNGEN, WORD_ENDUNGEN, ist_office_datei
from src.gui.farben import stil
from src.gui.pdf_thumbnail import PDFThumbnailWidget
from src.gui.pfad_aktionen import (
    PFAD_KOPIEREN_TEXT,
    im_dateimanager_zeigen,
    pfad_kopieren,
    zeigen_text,
)
from src.gui.tile_view import TileView
from src.i18n import tr

WORD_FARBE = "#2b579a"
EXCEL_FARBE = "#217346"
BILD_FARBE = "#7a5195"
TEXT_FARBE = "#5f6368"  # .txt (Issue #227)


def _typfarbe(pfad: Path) -> str:
    if ist_bild_datei(pfad):
        return BILD_FARBE
    if pfad.suffix.lower() in TEXT_ENDUNGEN:
        return TEXT_FARBE
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
    # Foto(s) entzerren und umwandeln (Issue #205): (Bild, "einzeln" | "zusammen", "auto" | "hand")
    bild_entzerren_requested = pyqtSignal(Path, str, str)
    # Markierte Dateien je einzeln in PDF: (Dateien, als PDF/A) - Live-Test 08.11.2026
    mehrere_umwandeln_requested = pyqtSignal(list, bool)

    _OFFICE_TOOLTIP = (
        tr("Word-/Excel-Datei. Anklicken wählt sie aus (Strg/Umschalt für Mehrfachauswahl).\n"
        "Ziehen verschiebt sie per Drag & Drop in einen Zielordner.\n"
        "Doppelklick öffnet sie im Standardprogramm.\n"
        "Rechtsklick: In PDF umwandeln (die Originaldatei bleibt erhalten).")
    )

    _BILD_TOOLTIP = (
        tr("Bild. Anklicken wählt es aus (Strg/Umschalt für Mehrfachauswahl).\n"
        "Ziehen verschiebt es per Drag & Drop in einen Zielordner.\n"
        "Doppelklick öffnet es im Standardprogramm.\n"
        "Rechtsklick: In PDF umwandeln (mit Texterkennung; das Bild bleibt erhalten).")
    )

    _TEXT_TOOLTIP = (
        tr("Textdatei. Anklicken wählt sie aus (Strg/Umschalt für Mehrfachauswahl).\n"
        "Ziehen verschiebt sie per Drag & Drop in einen Zielordner.\n"
        "Doppelklick öffnet sie im Standardprogramm.\n"
        "Rechtsklick: In PDF umwandeln (die Originaldatei bleibt erhalten).")
    )

    @property
    def _BASE_TOOLTIP(self) -> str:  # noqa: N802 - ersetzt das Klassenattribut der PDF-Kachel
        if ist_bild_datei(self.pdf_path):
            return self._BILD_TOOLTIP
        return self._TEXT_TOOLTIP if self.pdf_path.suffix.lower() in TEXT_ENDUNGEN else self._OFFICE_TOOLTIP

    # Farben nach Dateityp (nach der Erkennung statt Gruen): (Hintergrund, Rahmen, Hover-Hintergrund, Hover-Rahmen)
    OFFICE_FARBEN = ("$kachel_office_flaeche", "$kachel_office_rand", "$kachel_office_hover", "$kachel_office_hover_rand")
    BILD_FARBEN = ("$kachel_bild_flaeche", "$kachel_bild_rand", "$kachel_bild_hover", "$kachel_bild_hover_rand")
    # Etikett mit der Dateiendung (oben links; oben rechts sitzt das Warndreieck, unten "kopiert nach")
    OFFICE_ETIKETT = "#2b579a"
    BILD_ETIKETT = "#d6336c"

    def __init__(self, pfad: Path, parent=None, view: Optional[TileView] = None):
        super().__init__(pfad, parent, view)
        self.setAcceptDrops(False)  # Stapeln (PDF auf PDF) gibt es nur bei PDFs
        self._ist_bild = ist_bild_datei(pfad)
        farbe = self.BILD_ETIKETT if self._ist_bild else self.OFFICE_ETIKETT
        self.typ_label = QLabel(pfad.suffix.upper().lstrip("."), self.thumbnail_label)
        # Mit Selektor: sonst erbt der Tooltip des Etiketts Farbe und Mini-Schrift
        self.typ_label.setObjectName("typEtikett")
        stil(self.typ_label,
            f"QLabel#typEtikett {{ background-color: {farbe}; color: $weiss_schrift; font-size: 9px; "
            "font-weight: bold; border: none; border-radius: 3px; padding: 1px 4px; }"
        )
        self.typ_label.setToolTip(
            tr("Bild") if self._ist_bild
            else (tr("OpenDocument-Text") if pfad.suffix.lower() == ".odt"
                  else tr("Textdatei") if pfad.suffix.lower() in TEXT_ENDUNGEN
                  else tr("Word-Dokument") if pfad.suffix.lower() in WORD_ENDUNGEN else tr("Excel-Tabelle"))
        )
        self.typ_label.adjustSize()
        self.typ_label.move(3, 3)
        self.typ_label.raise_()
        self._update_style()

    def _typ_farben(self):
        return self.BILD_FARBEN if getattr(self, "_ist_bild", ist_bild_datei(self.pdf_path)) else self.OFFICE_FARBEN

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

    def _markierte_office(self) -> list[Path]:
        """Die markierten docx/xlsx, wenn diese Kachel zur Mehrfachauswahl gehoert (sonst leer)."""
        auswahl = getattr(self.window(), "selected_pdfs", None) or []
        dateien = [p for p in auswahl if ist_office_datei(p) and not ist_bild_datei(p)]
        return dateien if self.pdf_path in dateien else []

    def _build_context_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction(tr("Öffnen")).triggered.connect(lambda: self.open_requested.emit(self.pdf_path))
        menu.addAction(zeigen_text()).triggered.connect(lambda: im_dateimanager_zeigen(self.pdf_path))
        menu.addAction(PFAD_KOPIEREN_TEXT).triggered.connect(lambda: pfad_kopieren(self.pdf_path))
        menu.addSeparator()
        menu.addAction(tr("Verschieben nach...")).triggered.connect(lambda: self.move_requested.emit(self.pdf_path))
        menu.addSeparator()
        if ist_bild_datei(self.pdf_path):
            bilder = self._markierte_bilder()
            if len(bilder) > 1:
                # Mehrfachauswahl: jedes markierte Bild ein eigenes PDF (vorher nur das angeklickte)
                convert = menu.addAction(tr("Einzeln in PDFs umwandeln ({anzahl} Bilder)").format(anzahl=len(bilder)))
                convert.setToolTip(tr("Je Bild ein durchsuchbares PDF (Texterkennung) neben dem Bild"))
                convert.triggered.connect(lambda: self.mehrere_umwandeln_requested.emit(bilder, False))
            else:
                convert = menu.addAction(tr("In PDF umwandeln"))
                convert.setToolTip(tr("Erzeugt ein durchsuchbares PDF (Texterkennung) neben dem Bild"))
                convert.triggered.connect(lambda: self.convert_requested.emit(self.pdf_path, False))
                for text, modus, tipp in (
                    (tr("In PDF umwandeln und automatisch entzerren"), "auto",
                     tr("Erkennt das Blatt im Foto, zieht es gerade und gleicht die Tonwerte an. "
                     "Ist die Erkennung unsicher, öffnet sich das Entzerren-Fenster.")),
                    (tr("In PDF umwandeln und von Hand entzerren"), "hand",
                     tr("Öffnet ein Fenster, in dem Sie die vier Ecken des Blatts selbst setzen.")),
                ):
                    aktion = menu.addAction(text)
                    aktion.setToolTip(tipp)
                    aktion.triggered.connect(
                        lambda _c=False, m=modus: self.bild_entzerren_requested.emit(self.pdf_path, "einzeln", m))
            if len(bilder) > 1:
                zusammen = menu.addAction(tr("Zu einem PDF zusammenfügen ({anzahl} Bilder)").format(anzahl=len(bilder)))
                zusammen.setToolTip(tr("Ein PDF aus den markierten Bildern, in der Reihenfolge der Ansicht"))
                zusammen.triggered.connect(lambda: self.bilder_zusammenfuegen_requested.emit(self.pdf_path))
                # Entzerren (Issue #205): Untermenue, damit das Menue schlank bleibt
                sub = menu.addMenu(tr("Fotos entzerren ({anzahl} Bilder)").format(anzahl=len(bilder)))
                for text, art, modus, tipp in (
                    (tr("Einzeln in PDFs umwandeln und automatisch entzerren"), "einzeln", "auto",
                     tr("Je Foto ein PDF; das Blatt wird erkannt und gerade gezogen. "
                     "Bei unsicherer Erkennung öffnet sich das Entzerren-Fenster.")),
                    (tr("Einzeln in PDFs umwandeln und von Hand entzerren"), "einzeln", "hand",
                     tr("Je Foto ein PDF; die Ecken legen Sie selbst im Entzerren-Fenster fest.")),
                    (tr("Zu einem PDF zusammenfügen und automatisch entzerren"), "zusammen", "auto",
                     tr("Ein PDF aus allen markierten Fotos; Blatt erkannt und gerade gezogen.")),
                    (tr("Zu einem PDF zusammenfügen und von Hand entzerren"), "zusammen", "hand",
                     tr("Ein PDF aus allen markierten Fotos; die Ecken legen Sie selbst fest.")),
                ):
                    aktion = sub.addAction(text)
                    aktion.setToolTip(tipp)
                    aktion.triggered.connect(
                        lambda _c=False, a=art, m=modus: self.bild_entzerren_requested.emit(self.pdf_path, a, m))
            if ist_drehbares_bild(self.pdf_path):
                # Issue #252: Bild drehen wie eine PDF; bei Mehrfachauswahl alle markierten drehbaren Bilder
                menu.addSeparator()
                count = len([b for b in bilder if ist_drehbares_bild(b)])
                suffix = tr(" ({count} Bilder)").format(count=count) if count > 1 else ""
                rotate_menu = menu.addMenu(tr("Drehen{suffix}").format(suffix=suffix))
                rotate_menu.addAction(tr("90° nach links")).triggered.connect(self._rotate_left)
                rotate_menu.addAction(tr("90° nach rechts")).triggered.connect(self._rotate_right)
                rotate_menu.addAction("180°").triggered.connect(self._rotate_180)
            menu.addSeparator()
            menu.addAction(tr("Löschen")).triggered.connect(lambda: self.delete_requested.emit(self.pdf_path))
            return menu
        dateien = self._markierte_office()
        # Textdateien (.txt, Issue #227) wandelt PDFSM selbst um - ohne PDF/A
        nur_text = all(p.suffix.lower() in TEXT_ENDUNGEN for p in (dateien or [self.pdf_path]))
        if len(dateien) > 1:
            # Mehrfachauswahl: alle markierten Dateien, je ein PDF (Live-Test 08.11.2026)
            convert = menu.addAction(tr("In PDF umwandeln ({anzahl} Dateien)").format(anzahl=len(dateien)))
            convert.setToolTip(tr("Je Datei ein PDF neben der Datei"))
            convert.triggered.connect(lambda: self.mehrere_umwandeln_requested.emit(dateien, False))
            if not nur_text:
                convert_a = menu.addAction(tr("In PDF/A umwandeln ({anzahl} Dateien)").format(anzahl=len(dateien)))
                convert_a.setToolTip(tr("Wie oben, als archivfähiges PDF/A"))
                convert_a.triggered.connect(lambda: self.mehrere_umwandeln_requested.emit(dateien, True))
        else:
            convert = menu.addAction(tr("In PDF umwandeln"))
            convert.setToolTip(tr("Erzeugt ein PDF neben der Datei; das Original bleibt erhalten"))
            convert.triggered.connect(lambda: self.convert_requested.emit(self.pdf_path, False))
            if not nur_text:
                convert_a = menu.addAction(tr("In PDF/A umwandeln (Langzeitarchiv)"))
                convert_a.setToolTip(tr("Wie oben, als archivfähiges PDF/A"))
                convert_a.triggered.connect(lambda: self.convert_requested.emit(self.pdf_path, True))
        menu.addSeparator()
        menu.addAction(tr("Löschen")).triggered.connect(lambda: self.delete_requested.emit(self.pdf_path))
        return menu

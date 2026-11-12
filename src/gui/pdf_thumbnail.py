"""
PDF-Thumbnail Widget für PDF Sortier Meister

Zeigt eine Miniaturansicht einer PDF-Datei mit Dateinamen und Aktionen.
"""

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QSize, QMimeData, QUrl, QPoint, QTimer
from PyQt6.QtGui import QPixmap, QMouseEvent, QCursor, QDrag, QFontMetrics, QPainter, QColor, QPolygonF, QFont
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QWidget,
    QApplication,
    QToolTip,
)

from src.gui.pfad_aktionen import (
    PFAD_KOPIEREN_TEXT,
    im_dateimanager_zeigen,
    pfad_kopieren,
    zeigen_text,
)
from src.gui.tile_view import TileView, fit_text_lines, tile_view
from src.i18n import tr


class ThumbnailLoaderThread(QThread):
    """Thread zum asynchronen Laden von PDF-Thumbnails."""

    thumbnail_loaded = pyqtSignal(QPixmap)
    error_occurred = pyqtSignal(str)

    def __init__(self, pdf_path: Path, width: int = 140, height: int = 160):
        super().__init__()
        self.pdf_path = pdf_path
        self.width = width
        self.height = height

    def run(self):
        """Lädt das Thumbnail im Hintergrund."""
        try:
            from src.core.pdf_analyzer import get_thumbnail
            pixmap = get_thumbnail(self.pdf_path, self.width, self.height)
            self.thumbnail_loaded.emit(pixmap)
        except Exception as e:
            self.error_occurred.emit(str(e))


class OcrWarnSymbol(QWidget):
    """Kleines orangefarbenes Warndreieck mit "!" (Issue #47: Text schlecht erkannt).

    Selbst gezeichnet statt Unicode-Zeichen: Das Aussehen haengt dann nicht von
    der Schrift des Systems ab. Mausereignisse gehen an die Kachel durch.
    """

    SIZE = (20, 18)
    FARBE = "#f39c12"
    RAND = "#b9770e"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(*self.SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(self.FARBE))
        p.setPen(QColor(self.RAND))
        p.drawPolygon(QPolygonF([QPointF(w / 2, 1), QPointF(w - 1, h - 1), QPointF(1, h - 1)]))
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(max(8, h - 7))
        p.setFont(font)
        p.setPen(QColor("white"))
        p.drawText(self.rect().adjusted(0, 4, 0, 0), Qt.AlignmentFlag.AlignCenter, "!")
        p.end()


class PDFThumbnailWidget(QFrame):
    """Widget zur Anzeige einer PDF-Miniatur mit Interaktionsmöglichkeiten."""

    # Signale
    clicked = pyqtSignal(Path)  # PDF wurde angeklickt
    ctrl_clicked = pyqtSignal(Path)  # PDF wurde mit Ctrl angeklickt (Mehrfachauswahl)
    shift_clicked = pyqtSignal(Path)  # PDF wurde mit Shift angeklickt (Bereichsauswahl)
    double_clicked = pyqtSignal(Path)  # PDF wurde doppelgeklickt
    open_requested = pyqtSignal(Path)  # "PDF öffnen" im Kontextmenü (Issue #76)
    rename_requested = pyqtSignal(Path)  # Umbenennung angefordert
    delete_requested = pyqtSignal(Path)  # Löschen angefordert
    move_requested = pyqtSignal(Path)  # Verschieben angefordert
    copy_requested = pyqtSignal(Path)  # Kopie erstellen angefordert
    batch_rename_requested = pyqtSignal()  # Batch-Umbenennung für ausgewählte PDFs
    split_requested = pyqtSignal(Path)  # PDF trennen angefordert
    ki_split_requested = pyqtSignal(Path)  # Stapel per KI in Dokumente trennen
    merge_requested = pyqtSignal()  # Ausgewählte PDFs zusammenfügen
    stack_requested = pyqtSignal(list, Path)  # (abgelegte PDFs, diese PDF): Seiten davorlegen
    rotate_requested = pyqtSignal(Path, int)  # Drehen um Grad im Uhrzeigersinn (Issue #150)
    reocr_requested = pyqtSignal(Path)  # "OCR neu durchführen" (Issue #150)
    straighten_requested = pyqtSignal(Path)  # "Gerade ausrichten" (Issue #165)
    reocr_sprache_requested = pyqtSignal(Path, str)  # "OCR wiederholen mit ..." (Tesseract-Sprachen, Issue #47)
    handschrift_requested = pyqtSignal(Path)  # "Handschrift mit KI entziffern" (Issue #47)
    thumbnail_ready = pyqtSignal()  # Thumbnail wurde geladen (für SplashScreen)

    _BASE_TOOLTIP = (
        tr("Anklicken wählt diese PDF aus (Strg/Umschalt für Mehrfachauswahl).\n"
        "Ziehen verschiebt sie per Drag & Drop in einen Zielordner.\n"
        "Auf eine andere PDF gelegt, kommen ihre Seiten davor (Stapeln, wie Papier).\n"
        "Doppelklick öffnet die PDF im Standardprogramm.")
    )
    AI_TOOLTIP_SUFFIX = tr("\n\nKI-Vorschlag vorhanden (grün hinterlegt).")
    OCR_TOOLTIP_SUFFIX = tr("\n\nText schlecht erkannt – Rechtsklick für andere Erkennung")

    # Wartezeit, bis der Mauszeiger ueber einer kompakten Kachel die grosse
    # Vorschau einblendet (Issue #117)
    HOVER_PREVIEW_DELAY_MS = 350

    def __init__(self, pdf_path: Path, parent=None, view: Optional[TileView] = None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self._view = view or tile_view(None)
        self._selected = False
        self._stack_target = False  # gerade wird eine PDF darueber gezogen
        self._has_ai_suggestion = False  # Issue #81: KI-Vorschlag im Cache
        self._ocr_schlecht = False  # Issue #47: OCR-Text schlecht erkannt (Warndreieck)
        self._analyzing = False  # Issue #108: Erst-Analyse (OCR) laeuft gerade
        self._loader_thread: Optional[ThumbnailLoaderThread] = None
        self._drag_start_position: Optional[QPoint] = None
        # Klick auf eine Kachel der Mehrfachauswahl: erst beim Loslassen auswerten,
        # sonst hebt schon das Druecken zum Ziehen die Auswahl auf (Issue #218)
        self._klick_beim_loslassen = False
        # Original-Thumbnail (140x160-Render); die Kachel zeigt je nach
        # Ansicht eine verkleinerte Kopie, die Hover-Vorschau das Original
        self._original_pixmap: Optional[QPixmap] = None
        self._hover_popup: Optional[QLabel] = None
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(self.HOVER_PREVIEW_DELAY_MS)
        self._hover_timer.timeout.connect(self._show_hover_preview)

        self.setup_ui()
        self.load_thumbnail()

    def setup_ui(self):
        """Initialisiert die UI-Komponenten."""
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setLineWidth(1)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        # Hover-Effekt
        self.setMouseTracking(True)
        # Andere PDFs koennen hier abgelegt werden (Stapeln wie in PaperPort)
        self.setAcceptDrops(True)
        self._update_style()
        self.setToolTip(self._BASE_TOOLTIP)

        self._layout = QVBoxLayout(self)

        # Thumbnail-Bereich
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet(
            "background-color: #f5f5f5; border: 1px solid #ddd; border-radius: 3px;"
        )
        self.thumbnail_label.setText(tr("Laden..."))
        self._layout.addWidget(self.thumbnail_label, 0, Qt.AlignmentFlag.AlignHCenter)

        # Dateiname (mehrzeilig, pixelgenau umgebrochen; voller Name im Tooltip)
        self.name_label = QLabel()
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self.name_label)

        # Warndreieck "Text schlecht erkannt" (Issue #47), oben rechts auf dem Bild
        self._ocr_symbol = OcrWarnSymbol(self.thumbnail_label)
        self._ocr_symbol.hide()

        # Hinweis "kopiert nach ..." (Issue #179): schmaler Streifen am unteren
        # Bildrand, ohne Einfluss auf die Kachelgroesse
        self.kopie_label = QLabel(self.thumbnail_label)
        self.kopie_label.setStyleSheet(
            "background-color: rgba(255, 243, 205, 230); color: #6b4e00; "
            "border: none; border-top: 1px solid #daa520; padding: 0 2px;"
        )
        self.kopie_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.kopie_label.hide()
        self._kopie_text = ""
        self._kopie_kurz = ""

        self._apply_view()

    @property
    def view(self) -> TileView:
        """Aktuelle Kachelgroesse (Issue #117)."""
        return self._view

    def set_view(self, view: TileView):
        """Schaltet die Kachelgroesse um; das Bild wird passend neu skaliert."""
        if view.id == self._view.id:
            return
        self._view = view
        self._hide_hover_preview()
        self._apply_view()

    def _apply_view(self):
        """Wendet Masse und Schriftgroessen der aktuellen Ansicht an."""
        v = self._view
        self.setMinimumSize(v.tile_w, v.tile_h)
        self.setMaximumSize(v.tile_max_w, v.tile_max_h)
        self._layout.setContentsMargins(v.margin, v.margin, v.margin, v.margin)
        self._layout.setSpacing(v.spacing)
        self.thumbnail_label.setFixedSize(v.thumb_w, v.thumb_h)
        self._ocr_symbol.move(max(0, v.thumb_w - self._ocr_symbol.width() - 3), 3)
        self._kopie_label_anpassen()
        self.name_label.setMaximumHeight(v.name_max_height)
        self._apply_name_style()
        if self._original_pixmap is not None:
            self._apply_thumbnail_pixmap()
        if self._analyzing:
            self.name_label.setText(self.ANALYZING_TEXT)
        else:
            self.update_name_display()

    def set_kopie_hinweis(self, text: str, tooltip: str = "", kurz: str = ""):
        """Zeigt "kopiert nach ..." auf der Kachel (leerer Text blendet aus, Issue #179).

        ``kurz`` ist die Kurzform fuer schmale Kacheln, wenn ``text`` nicht passt.
        """
        self._kopie_text = text
        self._kopie_kurz = kurz
        self.kopie_label.setToolTip(tooltip)
        self._kopie_label_anpassen()

    def _kopie_label_anpassen(self):
        """Setzt Groesse, Schrift und (gekuerzten) Text des Kopie-Hinweises."""
        if not self._kopie_text:
            self.kopie_label.hide()
            return
        v = self._view
        font = self.kopie_label.font()
        font.setPixelSize(max(8, v.font_px - 1))
        self.kopie_label.setFont(font)
        h = max(12, v.font_px + 4)
        self.kopie_label.setGeometry(0, v.thumb_h - h, v.thumb_w, h)
        fm = QFontMetrics(font)
        breite = max(10, v.thumb_w - 6)
        text = self._kopie_text
        if self._kopie_kurz and fm.horizontalAdvance(text) > breite:
            text = self._kopie_kurz
        self.kopie_label.setText(fm.elidedText(text, Qt.TextElideMode.ElideRight, breite))
        self.kopie_label.show()

    def _apply_name_style(self):
        """Schrift ueber QFont (nicht Stylesheet), damit QFontMetrics fuer den
        Umbruch dieselbe Schrift misst, die gezeichnet wird."""
        font = self.name_label.font()
        font.setPixelSize(self._view.font_px)
        self.name_label.setFont(font)
        if self._analyzing:
            self.name_label.setStyleSheet("color: #b8860b; font-style: italic;")
        else:
            self.name_label.setStyleSheet("")

    def update_name_display(self):
        """Befuellt name_label mit dem umgebrochenen stem + vollem Namen als Tooltip."""
        v = self._view
        text = fit_text_lines(
            self.pdf_path.stem, QFontMetrics(self.name_label.font()), v.text_width, v.name_lines
        )
        self.name_label.setText(text)
        self.name_label.setToolTip(self.pdf_path.name)

    def load_thumbnail(self):
        """Startet das asynchrone Laden des Thumbnails."""
        self._loader_thread = ThumbnailLoaderThread(self.pdf_path)
        self._loader_thread.thumbnail_loaded.connect(self._on_thumbnail_loaded)
        self._loader_thread.error_occurred.connect(self._on_thumbnail_error)
        self._loader_thread.start()

    def _on_thumbnail_loaded(self, pixmap: QPixmap):
        """Wird aufgerufen wenn das Thumbnail geladen wurde."""
        self._original_pixmap = pixmap
        self._apply_thumbnail_pixmap()
        self.thumbnail_label.setStyleSheet(
            "background-color: white; border: 1px solid #ddd; border-radius: 3px;"
        )
        self.thumbnail_ready.emit()

    def _apply_thumbnail_pixmap(self):
        """Zeigt das Original-Thumbnail, auf die Bildflaeche der Ansicht angepasst."""
        pixmap = self._original_pixmap
        if pixmap is None or pixmap.isNull():
            return
        self.thumbnail_label.setPixmap(self._fit_pixmap(pixmap, self._view))

    @staticmethod
    def _fit_pixmap(pixmap: QPixmap, view: TileView) -> QPixmap:
        """Passt das Original in die Bildflaeche der Ansicht ein.

        thumb_crop: Bild fuellt die Breite, unten wird abgeschnitten - die
        Kachel zeigt den Kopf der Seite (Briefkopf, Betreff) statt einer
        winzigen Gesamtseite mit leerem Rand. Sonst wird die ganze Seite
        eingepasst (nur verkleinert, nie vergroessert).
        """
        if view.thumb_crop:
            scaled = pixmap.scaled(
                view.thumb_w, view.thumb_h,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            w = min(view.thumb_w, scaled.width())
            h = min(view.thumb_h, scaled.height())
            x = (scaled.width() - w) // 2  # horizontal mittig, oben buendig
            return scaled.copy(x, 0, w, h)
        if pixmap.width() <= view.thumb_w and pixmap.height() <= view.thumb_h:
            return pixmap
        return pixmap.scaled(
            view.thumb_w, view.thumb_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    # --- Hover-Vorschau (Issue #117) --------------------------------------

    def _show_hover_preview(self):
        """Blendet das Original-Thumbnail neben der Kachel ein.

        Nur bei kompakten Ansichten und nur, wenn das Bild schon geladen ist;
        Ordnerzeilen haben keine solche Vorschau.
        """
        pixmap = self._original_pixmap
        if not self._view.hover_preview or pixmap is None or pixmap.isNull():
            return
        if self._hover_popup is None:
            popup = QLabel(
                self,
                Qt.WindowType.ToolTip
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowTransparentForInput,
            )
            popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            popup.setStyleSheet(
                "QLabel { background-color: white; border: 1px solid #999; padding: 4px; }"
            )
            self._hover_popup = popup
        popup = self._hover_popup
        popup.setPixmap(pixmap)
        popup.adjustSize()

        # Rechts neben der Kachel; passt es nicht auf den Bildschirm, links davon
        top_right = self.mapToGlobal(self.rect().topRight())
        pos = QPoint(top_right.x() + 6, top_right.y())
        screen = QApplication.screenAt(top_right) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            if pos.x() + popup.width() > area.right():
                left = self.mapToGlobal(self.rect().topLeft()).x()
                pos.setX(max(area.left(), left - popup.width() - 6))
            if pos.y() + popup.height() > area.bottom():
                pos.setY(max(area.top(), area.bottom() - popup.height()))
        popup.move(pos)
        popup.show()

    def _hide_hover_preview(self):
        self._hover_timer.stop()
        if self._hover_popup is not None:
            self._hover_popup.hide()

    def enterEvent(self, event):
        if self._view.hover_preview and self._original_pixmap is not None:
            self._hover_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hide_hover_preview()
        super().leaveEvent(event)

    def _on_thumbnail_error(self, error: str):
        """Wird aufgerufen wenn ein Fehler beim Laden auftrat."""
        self.thumbnail_label.setText(tr("Fehler\nbeim Laden"))
        self.thumbnail_label.setStyleSheet(
            "background-color: #ffe0e0; border: 1px solid #ffaaaa; border-radius: 3px; color: #cc0000;"
        )
        self.thumbnail_ready.emit()  # Auch bei Fehler Signal senden

    # Farben fuer "KI-Vorschlag vorhanden" (Issue #81)
    AI_BACKGROUND = "#e6f4e6"
    AI_BORDER = "#7cc47f"

    # Farben fuer "hier ablegen = Seiten davorlegen"
    STACK_BACKGROUND = "#fff3e0"
    STACK_BORDER = "#e67e22"

    def _typ_farben(self):
        """(Hintergrund, Rahmen, Hover-Hintergrund, Hover-Rahmen) nach KI-Vorschlag; None = gruen (PDF)."""
        return None

    def _update_style(self):
        """Aktualisiert den Style: Stapel-Ziel (orange) vor Auswahl (blau)
        vor KI-Markierung (grün)."""
        if self._stack_target:
            self.setStyleSheet(
                f"PDFThumbnailWidget {{ background-color: {self.STACK_BACKGROUND}; "
                f"border: 2px dashed {self.STACK_BORDER}; border-radius: 5px; }}"
            )
        elif self._selected:
            self.setStyleSheet(
                "PDFThumbnailWidget { background-color: #cce5ff; border: 2px solid #0066cc; border-radius: 5px; }"
            )
        elif self._has_ai_suggestion:
            bg, border, hover_bg, hover_border = self._typ_farben() or (
                self.AI_BACKGROUND, self.AI_BORDER, "#d5ecd6", "#5cb860")
            self.setStyleSheet(
                f"PDFThumbnailWidget {{ background-color: {bg}; "
                f"border: 1px solid {border}; border-radius: 5px; }}"
                f"PDFThumbnailWidget:hover {{ background-color: {hover_bg}; border: 1px solid {hover_border}; }}"
            )
        else:
            self.setStyleSheet(
                "PDFThumbnailWidget { background-color: white; border: 1px solid #ccc; border-radius: 5px; }"
                "PDFThumbnailWidget:hover { background-color: #f0f7ff; border: 1px solid #99c2ff; }"
            )

    @property
    def has_ai_suggestion(self) -> bool:
        """True, wenn fuer diese PDF ein KI-Vorschlag vorliegt (gruene Kachel)."""
        return self._has_ai_suggestion

    @has_ai_suggestion.setter
    def has_ai_suggestion(self, value: bool):
        value = bool(value)
        if value == self._has_ai_suggestion:
            return
        self._has_ai_suggestion = value
        self._update_tooltip()
        self._update_style()

    def _update_tooltip(self):
        self.setToolTip(
            self._BASE_TOOLTIP
            + (self.AI_TOOLTIP_SUFFIX if self._has_ai_suggestion else "")
            + (self.OCR_TOOLTIP_SUFFIX if self._ocr_schlecht else "")
        )

    @property
    def ocr_schlecht(self) -> bool:
        """True, wenn der OCR-Text dieser PDF schlecht erkannt ist (Warndreieck, Issue #47)."""
        return self._ocr_schlecht

    @ocr_schlecht.setter
    def ocr_schlecht(self, value: bool):
        value = bool(value)
        if value == self._ocr_schlecht:
            return
        self._ocr_schlecht = value
        self._ocr_symbol.setVisible(value)
        self._update_tooltip()

    ANALYZING_TEXT = tr("Analysiere…")

    @property
    def analyzing(self) -> bool:
        """True, waehrend die Erst-Analyse (Text/OCR) fuer diese PDF laeuft."""
        return self._analyzing

    @analyzing.setter
    def analyzing(self, value: bool):
        value = bool(value)
        if value == self._analyzing:
            return
        self._analyzing = value
        self._apply_name_style()
        if value:
            self.name_label.setText(self.ANALYZING_TEXT)
        else:
            self.update_name_display()

    @property
    def selected(self) -> bool:
        """Gibt zurück, ob das Widget ausgewählt ist."""
        return self._selected

    @selected.setter
    def selected(self, value: bool):
        """Setzt den Auswahlstatus."""
        self._selected = value
        self._update_style()

    def mousePressEvent(self, event: QMouseEvent):
        """Behandelt Mausklicks und startet Drag-Vorbereitung."""
        self._hide_hover_preview()
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_position = event.pos()
            # Shift+Klick für Bereichsauswahl
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.shift_clicked.emit(self.pdf_path)
            # Ctrl+Klick für Mehrfachauswahl
            elif event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.ctrl_clicked.emit(self.pdf_path)
            elif self._in_mehrfachauswahl():
                self._klick_beim_loslassen = True  # vielleicht wird die ganze Auswahl gezogen
            else:
                self.clicked.emit(self.pdf_path)
        super().mousePressEvent(event)

    def _in_mehrfachauswahl(self) -> bool:
        main_window = self.window()
        auswahl = getattr(main_window, "selected_pdfs", None) or []
        return len(auswahl) > 1 and self.pdf_path in auswahl

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Ein nicht gezogener Klick in die Mehrfachauswahl waehlt wie gewohnt nur diese Kachel."""
        if event.button() == Qt.MouseButton.LeftButton and self._klick_beim_loslassen:
            self._klick_beim_loslassen = False
            self.clicked.emit(self.pdf_path)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        """Behandelt Mausbewegungen und startet Drag & Drop."""
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return

        if self._drag_start_position is None:
            return

        # Prüfen ob genug Distanz für Drag
        distance = (event.pos() - self._drag_start_position).manhattanLength()
        if distance < QApplication.startDragDistance():
            return

        # Drag starten (die Mehrfachauswahl bleibt dabei bestehen)
        self._klick_beim_loslassen = False
        self._start_drag()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Behandelt Doppelklicks."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.pdf_path)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        """Zeigt das Kontextmenü an."""
        self._build_context_menu().exec(event.globalPos())

    def _build_context_menu(self) -> QMenu:
        """Baut das Kontextmenue (getrennt, damit es testbar ist)."""
        menu = QMenu(self)

        # Prüfen ob Mehrfachauswahl aktiv ist
        selection_count = self._get_selection_count()

        # Öffnen
        open_action = menu.addAction(tr("PDF öffnen"))
        open_action.triggered.connect(lambda: self._open_pdf())

        # Issue #154: Ablageort zeigen und Pfad kopieren
        show_action = menu.addAction(zeigen_text())
        show_action.triggered.connect(self._show_in_file_manager)
        copy_path_action = menu.addAction(PFAD_KOPIEREN_TEXT)
        copy_path_action.triggered.connect(self._copy_path)

        menu.addSeparator()

        # Umbenennen
        rename_action = menu.addAction(tr("Umbenennen..."))
        rename_action.triggered.connect(lambda: self.rename_requested.emit(self.pdf_path))

        # Batch-Umbenennung wenn mehrere ausgewählt
        if selection_count > 1:
            batch_rename_action = menu.addAction(tr("Ausgewählte ({selection_count}) auto-umbenennen (LLM)").format(selection_count=selection_count))
            batch_rename_action.triggered.connect(lambda: self.batch_rename_requested.emit())

        # Verschieben
        move_action = menu.addAction(tr("Verschieben nach..."))
        move_action.triggered.connect(lambda: self.move_requested.emit(self.pdf_path))

        # Kopie erstellen
        copy_action = menu.addAction(tr("Kopie erstellen"))
        copy_action.triggered.connect(lambda: self.copy_requested.emit(self.pdf_path))

        menu.addSeparator()

        # PDF trennen
        split_action = menu.addAction(tr("PDF trennen..."))
        split_action.triggered.connect(lambda: self.split_requested.emit(self.pdf_path))
        ki_split_action = menu.addAction(tr("KI-unterstütztes Trennen..."))
        ki_split_action.setToolTip(tr("Scan-Stapel von der KI in einzelne Dokumente zerlegen lassen"))
        ki_split_action.triggered.connect(lambda: self.ki_split_requested.emit(self.pdf_path))

        # PDFs zusammenfügen wenn mehrere ausgewählt
        if selection_count > 1:
            merge_action = menu.addAction(tr("Ausgewählte ({selection_count}) PDFs zusammenfügen...").format(selection_count=selection_count))
            merge_action.triggered.connect(lambda: self.merge_requested.emit())

        menu.addSeparator()

        # Issue #150: ganze PDF verlustfrei drehen, Texterkennung neu. Bei
        # Mehrfachauswahl (diese Kachel gehoert dazu) gilt es fuer alle.
        count = selection_count if selection_count > 1 and self.selected else 1
        suffix = tr(" ({count} PDFs)").format(count=count) if count > 1 else ""
        rotate_menu = menu.addMenu(tr("Drehen{suffix}").format(suffix=suffix))
        rotate_left = rotate_menu.addAction(tr("90° nach links"))
        rotate_left.triggered.connect(self._rotate_left)
        rotate_right = rotate_menu.addAction(tr("90° nach rechts"))
        rotate_right.triggered.connect(self._rotate_right)
        rotate_half = rotate_menu.addAction("180°")
        rotate_half.triggered.connect(self._rotate_180)
        # Issue #165: schief gescannte Seiten um den kleinen Winkel gerade drehen
        rotate_menu.addSeparator()
        straighten_action = rotate_menu.addAction(tr("Gerade ausrichten (schief gescannt)"))
        straighten_action.setToolTip(tr("Schief eingezogene Seiten messen und gerade drehen"))
        straighten_action.triggered.connect(self._request_straighten)
        reocr_action = menu.addAction(tr("OCR neu durchführen{suffix}").format(suffix=suffix))
        reocr_action.setToolTip(tr("Gescannte Seiten neu erkennen, z. B. nach dem Drehen"))
        reocr_action.triggered.connect(self._request_reocr)
        # Issue #47: andere Erkennung - Sprachen/Fraktur per Tesseract, Handschrift per KI-Bilderkennung.
        # Die Sprachen werden erst beim Aufklappen gelesen (``tesseract --list-langs`` dauert).
        self.ocr_sprache_menu = menu.addMenu(tr("OCR wiederholen mit …"))
        self.ocr_sprache_menu.setToolTip(tr("Seiten mit anderen Tesseract-Sprachen neu erkennen, z. B. Fraktur"))
        self.ocr_sprache_menu.addAction(tr("Sprachen werden gelesen …")).setEnabled(False)
        self.ocr_sprache_menu.aboutToShow.connect(self._fill_ocr_sprache_menu)
        handschrift_action = menu.addAction(tr("Handschrift mit KI entziffern (Bilderkennung)"))
        handschrift_action.setToolTip(tr("Schickt die Seiten als Bilder an das KI-Modell, falls es Bilder versteht"))
        handschrift_action.triggered.connect(self._request_handschrift)

        menu.addSeparator()

        # Löschen
        delete_action = menu.addAction(tr("Löschen"))
        delete_action.triggered.connect(lambda: self.delete_requested.emit(self.pdf_path))

        return menu

    def _rotate_left(self):
        self.rotate_requested.emit(self.pdf_path, -90)

    def _rotate_right(self):
        self.rotate_requested.emit(self.pdf_path, 90)

    def _rotate_180(self):
        self.rotate_requested.emit(self.pdf_path, 180)

    def _request_reocr(self):
        self.reocr_requested.emit(self.pdf_path)

    def _request_handschrift(self):
        self.handschrift_requested.emit(self.pdf_path)

    def _ocr_sprachangebot(self) -> dict:
        """Installierte Tesseract-Sprachen fuer das Menue (getrennt, damit Tests sie ersetzen koennen)."""
        from src.core.pdf_analyzer import ocr_sprachangebot
        return ocr_sprachangebot()

    def _fill_ocr_sprache_menu(self):
        """Fuellt "OCR wiederholen mit ..." mit den installierten Sprachen; fehlt Fraktur, kommt ein Installationshinweis."""
        menu = self.ocr_sprache_menu
        menu.clear()
        angebot = self._ocr_sprachangebot()
        if not angebot["tesseract"]:
            menu.addAction(tr("Tesseract nicht gefunden")).setEnabled(False)
            return
        for code, name in angebot["sprachen"]:
            action = menu.addAction(name)
            action.setToolTip(tr("Tesseract-Sprache: {code}").format(code=code))
            action.triggered.connect(lambda _checked=False, c=code: self.reocr_sprache_requested.emit(self.pdf_path, c))
        if not angebot["fraktur"]:
            menu.addSeparator()
            hinweis = menu.addAction(tr("Fraktur (nicht installiert) – so installieren …"))
            hinweis.triggered.connect(lambda _checked=False: self._show_fraktur_hint(angebot["tessdata"]))

    def _show_fraktur_hint(self, tessdata):
        from src.utils.tesseract import fraktur_hinweis
        QMessageBox.information(self, tr("Fraktur installieren"), fraktur_hinweis(tessdata))

    def _request_straighten(self):
        self.straighten_requested.emit(self.pdf_path)

    def _show_in_file_manager(self):
        """Markiert die PDF im Explorer/Finder (Issue #154)."""
        im_dateimanager_zeigen(self.pdf_path)

    def _copy_path(self):
        """Legt den vollstaendigen Pfad in die Zwischenablage (Issue #154)."""
        pfad_kopieren(self.pdf_path)

    def _get_selection_count(self) -> int:
        """Gibt die Anzahl der ausgewählten PDFs zurück."""
        # Verwende self.window() um direkt das Hauptfenster zu finden
        main_window = self.window()
        if main_window and hasattr(main_window, 'selected_pdfs'):
            return len(main_window.selected_pdfs)
        return 0

    def _open_pdf(self):
        """Meldet den Öffnen-Wunsch; das Hauptfenster entscheidet nach
        Einstellung zwischen integrierter Vorschau und externem Programm."""
        self.open_requested.emit(self.pdf_path)

    def cleanup(self):
        """Bereinigt Ressourcen."""
        self._hide_hover_preview()
        if self._loader_thread and self._loader_thread.isRunning():
            self._loader_thread.quit()
            self._loader_thread.wait(1000)

    # --- Stapeln: andere PDF hier ablegen ---------------------------------

    def _dropped_pdfs(self, mime_data) -> list[Path]:
        """Die gezogenen PDFs ausser dieser selbst (leer = kein Stapeln)."""
        if not mime_data.hasUrls():
            return []
        paths = [Path(url.toLocalFile()) for url in mime_data.urls() if url.isLocalFile()]
        return [p for p in paths if p.suffix.lower() == ".pdf" and p != self.pdf_path]

    @staticmethod
    def _accept_as_copy(event):
        # Immer als Kopie annehmen: bei "Verschieben" loescht der Explorer
        # nach dem Ablegen sonst die Originaldatei
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def _set_stack_target(self, active: bool):
        if active != self._stack_target:
            self._stack_target = active
            self._update_style()

    def dragEnterEvent(self, event):
        if self._dropped_pdfs(event.mimeData()):
            self._hide_hover_preview()
            self._accept_as_copy(event)
            self._set_stack_target(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._dropped_pdfs(event.mimeData()):
            self._accept_as_copy(event)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_stack_target(False)

    def dropEvent(self, event):
        self._set_stack_target(False)
        pdfs = self._dropped_pdfs(event.mimeData())
        if not pdfs:
            event.ignore()
            return
        self._accept_as_copy(event)
        # Erst nach dem Ende des Ziehvorgangs auswerten: das Hauptfenster
        # entfernt dabei die Kachel, von der gezogen wurde
        target = self.pdf_path
        QTimer.singleShot(0, lambda: self.stack_requested.emit(pdfs, target))

    def _start_drag(self):
        """Startet den Drag & Drop Vorgang."""
        self._hide_hover_preview()
        drag = QDrag(self)

        # MIME-Daten mit Datei-URL erstellen
        mime_data = QMimeData()

        # Prüfe ob Mehrfachauswahl aktiv ist (über self.window())
        urls = [QUrl.fromLocalFile(str(self.pdf_path))]

        # Mehrfachauswahl: Alle ausgewählten PDFs hinzufügen
        main_window = self.window()
        if main_window and hasattr(main_window, 'selected_pdfs'):
            if self.pdf_path in main_window.selected_pdfs:
                urls = [QUrl.fromLocalFile(str(p)) for p in main_window.selected_pdfs]

        mime_data.setUrls(urls)

        # Optional: Auch Text setzen für andere Anwendungen
        if len(urls) == 1:
            mime_data.setText(str(self.pdf_path))
        else:
            mime_data.setText(tr("{anzahl} PDFs").format(anzahl=len(urls)))

        drag.setMimeData(mime_data)

        # Thumbnail als Drag-Pixmap verwenden (verkleinert, aus dem Original)
        source = self._original_pixmap or self.thumbnail_label.pixmap()
        if source and not source.isNull():
            scaled_pixmap = source.scaled(
                80, 100,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            drag.setPixmap(scaled_pixmap)
            drag.setHotSpot(QPoint(scaled_pixmap.width() // 2, scaled_pixmap.height() // 2))

        # Drag ausführen
        drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction)

        # Drag-Position zurücksetzen
        self._drag_start_position = None

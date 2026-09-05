"""
PDF-Thumbnail Widget für PDF Sortier Meister

Zeigt eine Miniaturansicht einer PDF-Datei mit Dateinamen und Aktionen.
"""

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QSize, QMimeData, QUrl, QPoint, QTimer
from PyQt6.QtGui import QPixmap, QMouseEvent, QCursor, QDrag, QFontMetrics
from PyQt6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QLabel,
    QMenu,
    QApplication,
    QToolTip,
)

from src.gui.tile_view import TileView, fit_text_lines, tile_view


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
    merge_requested = pyqtSignal()  # Ausgewählte PDFs zusammenfügen
    thumbnail_ready = pyqtSignal()  # Thumbnail wurde geladen (für SplashScreen)

    _BASE_TOOLTIP = (
        "Anklicken wählt diese PDF aus (Strg/Umschalt für Mehrfachauswahl).\n"
        "Ziehen verschiebt sie per Drag & Drop in einen Zielordner.\n"
        "Doppelklick öffnet die PDF im Standardprogramm."
    )
    AI_TOOLTIP_SUFFIX = "\n\nKI-Vorschlag vorhanden (grün hinterlegt)."

    # Wartezeit, bis der Mauszeiger ueber einer kompakten Kachel die grosse
    # Vorschau einblendet (Issue #117)
    HOVER_PREVIEW_DELAY_MS = 350

    def __init__(self, pdf_path: Path, parent=None, view: Optional[TileView] = None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self._view = view or tile_view(None)
        self._selected = False
        self._has_ai_suggestion = False  # Issue #81: KI-Vorschlag im Cache
        self._analyzing = False  # Issue #108: Erst-Analyse (OCR) laeuft gerade
        self._loader_thread: Optional[ThumbnailLoaderThread] = None
        self._drag_start_position: Optional[QPoint] = None
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
        self._update_style()
        self.setToolTip(self._BASE_TOOLTIP)

        self._layout = QVBoxLayout(self)

        # Thumbnail-Bereich
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet(
            "background-color: #f5f5f5; border: 1px solid #ddd; border-radius: 3px;"
        )
        self.thumbnail_label.setText("Laden...")
        self._layout.addWidget(self.thumbnail_label, 0, Qt.AlignmentFlag.AlignHCenter)

        # Dateiname (mehrzeilig, pixelgenau umgebrochen; voller Name im Tooltip)
        self.name_label = QLabel()
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self.name_label)

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
        self.name_label.setMaximumHeight(v.name_max_height)
        self._apply_name_style()
        if self._original_pixmap is not None:
            self._apply_thumbnail_pixmap()
        if self._analyzing:
            self.name_label.setText(self.ANALYZING_TEXT)
        else:
            self.update_name_display()

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
        Ordner-Kacheln haben keine solche Vorschau.
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
        self.thumbnail_label.setText("Fehler\nbeim Laden")
        self.thumbnail_label.setStyleSheet(
            "background-color: #ffe0e0; border: 1px solid #ffaaaa; border-radius: 3px; color: #cc0000;"
        )
        self.thumbnail_ready.emit()  # Auch bei Fehler Signal senden

    # Farben fuer "KI-Vorschlag vorhanden" (Issue #81)
    AI_BACKGROUND = "#e6f4e6"
    AI_BORDER = "#7cc47f"

    def _update_style(self):
        """Aktualisiert den Style: Auswahl (blau) vor KI-Markierung (grün)."""
        if self._selected:
            self.setStyleSheet(
                "PDFThumbnailWidget { background-color: #cce5ff; border: 2px solid #0066cc; border-radius: 5px; }"
            )
        elif self._has_ai_suggestion:
            self.setStyleSheet(
                f"PDFThumbnailWidget {{ background-color: {self.AI_BACKGROUND}; "
                f"border: 1px solid {self.AI_BORDER}; border-radius: 5px; }}"
                "PDFThumbnailWidget:hover { background-color: #d5ecd6; border: 1px solid #5cb860; }"
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
        self.setToolTip(self._BASE_TOOLTIP + (self.AI_TOOLTIP_SUFFIX if value else ""))
        self._update_style()

    ANALYZING_TEXT = "Analysiere…"

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
            else:
                self.clicked.emit(self.pdf_path)
        super().mousePressEvent(event)

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

        # Drag starten
        self._start_drag()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Behandelt Doppelklicks."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.pdf_path)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        """Zeigt das Kontextmenü an."""
        menu = QMenu(self)

        # Prüfen ob Mehrfachauswahl aktiv ist
        selection_count = self._get_selection_count()

        # Öffnen
        open_action = menu.addAction("PDF öffnen")
        open_action.triggered.connect(lambda: self._open_pdf())

        menu.addSeparator()

        # Umbenennen
        rename_action = menu.addAction("Umbenennen...")
        rename_action.triggered.connect(lambda: self.rename_requested.emit(self.pdf_path))

        # Batch-Umbenennung wenn mehrere ausgewählt
        if selection_count > 1:
            batch_rename_action = menu.addAction(f"Ausgewählte ({selection_count}) auto-umbenennen (LLM)")
            batch_rename_action.triggered.connect(lambda: self.batch_rename_requested.emit())

        # Verschieben
        move_action = menu.addAction("Verschieben nach...")
        move_action.triggered.connect(lambda: self.move_requested.emit(self.pdf_path))

        # Kopie erstellen
        copy_action = menu.addAction("Kopie erstellen")
        copy_action.triggered.connect(lambda: self.copy_requested.emit(self.pdf_path))

        menu.addSeparator()

        # PDF trennen
        split_action = menu.addAction("PDF trennen...")
        split_action.triggered.connect(lambda: self.split_requested.emit(self.pdf_path))

        # PDFs zusammenfügen wenn mehrere ausgewählt
        if selection_count > 1:
            merge_action = menu.addAction(f"Ausgewählte ({selection_count}) PDFs zusammenfügen...")
            merge_action.triggered.connect(lambda: self.merge_requested.emit())

        menu.addSeparator()

        # Löschen
        delete_action = menu.addAction("Löschen")
        delete_action.triggered.connect(lambda: self.delete_requested.emit(self.pdf_path))

        menu.exec(event.globalPos())

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
            mime_data.setText(f"{len(urls)} PDFs")

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

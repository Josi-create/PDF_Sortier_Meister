"""
PDF-Thumbnail Widget für PDF Sortier Meister

Zeigt eine Miniaturansicht einer PDF-Datei mit Dateinamen und Aktionen.
"""

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QSize
from PyQt6.QtGui import QPixmap, QMouseEvent, QCursor
from PyQt6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QLabel,
    QMenu,
    QApplication,
    QToolTip,
)


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
    double_clicked = pyqtSignal(Path)  # PDF wurde doppelgeklickt
    rename_requested = pyqtSignal(Path)  # Umbenennung angefordert
    delete_requested = pyqtSignal(Path)  # Löschen angefordert
    move_requested = pyqtSignal(Path)  # Verschieben angefordert

    def __init__(self, pdf_path: Path, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self._selected = False
        self._loader_thread: Optional[ThumbnailLoaderThread] = None

        self.setup_ui()
        self.load_thumbnail()

    def setup_ui(self):
        """Initialisiert die UI-Komponenten."""
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setLineWidth(1)
        self.setMinimumSize(160, 220)
        self.setMaximumSize(180, 250)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        # Hover-Effekt
        self.setMouseTracking(True)
        self._update_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        # Thumbnail-Bereich
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setMinimumSize(140, 160)
        self.thumbnail_label.setMaximumSize(160, 180)
        self.thumbnail_label.setStyleSheet(
            "background-color: #f5f5f5; border: 1px solid #ddd; border-radius: 3px;"
        )
        self.thumbnail_label.setText("Laden...")
        layout.addWidget(self.thumbnail_label)

        # Dateiname
        self.name_label = QLabel()
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setMaximumHeight(45)
        self.name_label.setStyleSheet("font-size: 11px;")

        # Dateinamen kürzen wenn zu lang
        name = self.pdf_path.name
        if len(name) > 25:
            name = name[:22] + "..."
        self.name_label.setText(name)
        self.name_label.setToolTip(self.pdf_path.name)

        layout.addWidget(self.name_label)

    def load_thumbnail(self):
        """Startet das asynchrone Laden des Thumbnails."""
        self._loader_thread = ThumbnailLoaderThread(self.pdf_path)
        self._loader_thread.thumbnail_loaded.connect(self._on_thumbnail_loaded)
        self._loader_thread.error_occurred.connect(self._on_thumbnail_error)
        self._loader_thread.start()

    def _on_thumbnail_loaded(self, pixmap: QPixmap):
        """Wird aufgerufen wenn das Thumbnail geladen wurde."""
        self.thumbnail_label.setPixmap(pixmap)
        self.thumbnail_label.setStyleSheet(
            "background-color: white; border: 1px solid #ddd; border-radius: 3px;"
        )

    def _on_thumbnail_error(self, error: str):
        """Wird aufgerufen wenn ein Fehler beim Laden auftrat."""
        self.thumbnail_label.setText("Fehler\nbeim Laden")
        self.thumbnail_label.setStyleSheet(
            "background-color: #ffe0e0; border: 1px solid #ffaaaa; border-radius: 3px; color: #cc0000;"
        )

    def _update_style(self):
        """Aktualisiert den Style basierend auf dem Auswahlstatus."""
        if self._selected:
            self.setStyleSheet(
                "PDFThumbnailWidget { background-color: #cce5ff; border: 2px solid #0066cc; border-radius: 5px; }"
            )
        else:
            self.setStyleSheet(
                "PDFThumbnailWidget { background-color: white; border: 1px solid #ccc; border-radius: 5px; }"
                "PDFThumbnailWidget:hover { background-color: #f0f7ff; border: 1px solid #99c2ff; }"
            )

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
        """Behandelt Mausklicks."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.pdf_path)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Behandelt Doppelklicks."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.pdf_path)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        """Zeigt das Kontextmenü an."""
        menu = QMenu(self)

        # Öffnen
        open_action = menu.addAction("PDF öffnen")
        open_action.triggered.connect(lambda: self._open_pdf())

        menu.addSeparator()

        # Umbenennen
        rename_action = menu.addAction("Umbenennen...")
        rename_action.triggered.connect(lambda: self.rename_requested.emit(self.pdf_path))

        # Verschieben
        move_action = menu.addAction("Verschieben nach...")
        move_action.triggered.connect(lambda: self.move_requested.emit(self.pdf_path))

        menu.addSeparator()

        # Löschen
        delete_action = menu.addAction("Löschen")
        delete_action.triggered.connect(lambda: self.delete_requested.emit(self.pdf_path))

        menu.exec(event.globalPos())

    def _open_pdf(self):
        """Öffnet die PDF mit dem Standardprogramm."""
        import os
        import subprocess
        import sys

        if sys.platform == 'win32':
            os.startfile(str(self.pdf_path))
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(self.pdf_path)])
        else:
            subprocess.run(['xdg-open', str(self.pdf_path)])

    def cleanup(self):
        """Bereinigt Ressourcen."""
        if self._loader_thread and self._loader_thread.isRunning():
            self._loader_thread.quit()
            self._loader_thread.wait(1000)

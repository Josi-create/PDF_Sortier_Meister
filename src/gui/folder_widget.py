"""
Ordner-Widget für PDF Sortier Meister

Zeigt einen Zielordner als Kachel an.
"""

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QCursor, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QLabel,
    QMenu,
)


class FolderWidget(QFrame):
    """Widget zur Anzeige eines Zielordners."""

    # Signale
    clicked = pyqtSignal(Path)  # Ordner wurde angeklickt
    double_clicked = pyqtSignal(Path)  # Ordner wurde doppelgeklickt
    pdf_dropped = pyqtSignal(Path, Path)  # PDF wurde auf Ordner gezogen (pdf_path, folder_path)
    remove_requested = pyqtSignal(Path)  # Ordner soll entfernt werden

    def __init__(self, folder_path: Path, pdf_count: int = 0, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        self.pdf_count = pdf_count
        self._selected = False
        self._is_suggestion = False

        self.setup_ui()
        self.setAcceptDrops(True)

    def setup_ui(self):
        """Initialisiert die UI-Komponenten."""
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setLineWidth(1)
        self.setMinimumSize(140, 120)
        self.setMaximumSize(170, 155)  # Mehr Höhe für dreizeilige Namen
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self._update_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(3)

        # Ordner-Icon
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setText("📁")
        self.icon_label.setStyleSheet("font-size: 36px; background: transparent;")
        layout.addWidget(self.icon_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Ordnername (dreizeilig für lange Namen)
        self.name_label = QLabel()
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setMaximumHeight(48)  # Platz für 3 Zeilen
        self.name_label.setStyleSheet("font-size: 10px; font-weight: bold; line-height: 1.2;")

        # Namen umbrechen statt kürzen - WordWrap übernimmt das
        name = self.folder_path.name
        # Nur kürzen wenn wirklich extrem lang (>50 Zeichen)
        if len(name) > 50:
            name = name[:47] + "..."
        self.name_label.setText(name)
        self.name_label.setToolTip(str(self.folder_path))

        # Standard-Tooltip für die ganze Kachel (main_window.py setzt bei
        # Vorschlägen einen ausführlicheren Tooltip, der diesen ersetzt).
        self.setToolTip(f"{self.folder_path}\nAnklicken verschiebt die ausgewählte PDF hierher.")

        layout.addWidget(self.name_label)

        # PDF-Anzahl
        self.count_label = QLabel()
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count_label.setStyleSheet("font-size: 10px; color: #666;")
        self._update_count_label()
        layout.addWidget(self.count_label)

    def _update_count_label(self):
        """Aktualisiert die Anzeige der PDF-Anzahl."""
        if self.pdf_count == 1:
            self.count_label.setText("1 PDF")
        else:
            self.count_label.setText(f"{self.pdf_count} PDFs")

    def _update_style(self):
        """Aktualisiert den Style basierend auf Status."""
        if self._selected:
            self.setStyleSheet(
                "FolderWidget { background-color: #fff3cd; border: 2px solid #ffc107; border-radius: 8px; }"
            )
        elif self._is_suggestion:
            self.setStyleSheet(
                "FolderWidget { background-color: #d4edda; border: 2px solid #28a745; border-radius: 8px; }"
                "FolderWidget:hover { background-color: #c3e6cb; }"
            )
        else:
            self.setStyleSheet(
                "FolderWidget { background-color: #fff8e7; border: 1px solid #daa520; border-radius: 8px; }"
                "FolderWidget:hover { background-color: #ffecb3; border: 1px solid #ffc107; }"
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

    @property
    def is_suggestion(self) -> bool:
        """Gibt zurück, ob dies ein vorgeschlagener Ordner ist."""
        return self._is_suggestion

    @is_suggestion.setter
    def is_suggestion(self, value: bool):
        """Markiert diesen Ordner als Vorschlag."""
        self._is_suggestion = value
        self._update_style()

    def set_pdf_count(self, count: int):
        """Aktualisiert die PDF-Anzahl."""
        self.pdf_count = count
        self._update_count_label()

    def mousePressEvent(self, event: QMouseEvent):
        """Behandelt Mausklicks."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.folder_path)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Behandelt Doppelklicks."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.folder_path)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        """Zeigt das Kontextmenü an."""
        self._build_context_menu().exec(event.globalPos())

    def _build_context_menu(self) -> QMenu:
        """Baut das Kontextmenue (getrennt, damit es testbar ist)."""
        menu = QMenu(self)

        # Im Dateimanager öffnen
        from src.utils.platform_paths import file_manager_name
        open_action = menu.addAction(f"Im {file_manager_name()} öffnen")
        open_action.triggered.connect(lambda: self._open_in_explorer())

        # Aus Liste entfernen - nur fuer echte Zielordner-Kacheln. Auf den
        # gruenen Vorschlagskacheln war der Eintrag wirkungslos (Signal nie
        # verbunden) und inhaltlich falsch: Vorschlaege sind meist Unterordner,
        # keine Eintraege der Zielliste.
        if not self._is_suggestion:
            menu.addSeparator()
            remove_action = menu.addAction("Aus Zielliste entfernen")
            remove_action.triggered.connect(lambda: self.remove_requested.emit(self.folder_path))

        return menu

    def _open_in_explorer(self):
        """Öffnet den Ordner im Dateimanager des Systems."""
        from src.utils.platform_paths import open_with_default_app

        open_with_default_app(self.folder_path)

    # Drag & Drop Unterstützung
    def dragEnterEvent(self, event: QDragEnterEvent):
        """Behandelt das Eintreten eines Drag-Objekts."""
        if event.mimeData().hasUrls():
            # Prüfen ob es PDF-Dateien sind
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith('.pdf'):
                    event.acceptProposedAction()
                    self.setStyleSheet(
                        "FolderWidget { background-color: #b8daff; border: 3px solid #007bff; border-radius: 8px; }"
                    )
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        """Behandelt das Verlassen eines Drag-Objekts."""
        self._update_style()

    def dropEvent(self, event: QDropEvent):
        """Behandelt das Ablegen von Dateien."""
        self._update_style()

        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                file_path = Path(url.toLocalFile())
                if file_path.suffix.lower() == '.pdf':
                    self.pdf_dropped.emit(file_path, self.folder_path)

            event.acceptProposedAction()

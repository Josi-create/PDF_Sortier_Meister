"""
Ordner-Kachel für den Scan-Bereich (Explorer-Gefühl, Issue #29)

Zeigt einen Unterordner (oder ".." für den übergeordneten Ordner) als Kachel
im selben Raster wie die PDF-Thumbnails. Doppelklick wechselt in den Ordner,
PDFs können per Drag & Drop hineingeschoben werden.

GPL-3.0-or-later - Copyright (c) 2026
"""

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout


class FolderTileWidget(QFrame):
    """Kachel für einen Ordner im Scan-Bereich."""

    clicked = pyqtSignal(Path)  # Einfachklick (nur fuer ".." verbunden, Issue #50)
    double_clicked = pyqtSignal(Path)  # In den Ordner wechseln
    pdf_dropped = pyqtSignal(Path, Path)  # (pdf_path, folder_path)

    _STYLE_NORMAL = (
        "FolderTileWidget { background-color: #fbf8ec; border: 1px solid #d8cfae; "
        "border-radius: 4px; }"
    )
    _STYLE_HOVER = (
        "FolderTileWidget { background-color: #fff3cd; border: 1px solid #daa520; "
        "border-radius: 4px; }"
    )
    _STYLE_DROP = (
        "FolderTileWidget { background-color: #d9f2d9; border: 2px solid #4caf50; "
        "border-radius: 4px; }"
    )

    def __init__(
        self,
        folder_path: Path,
        pdf_count: Optional[int] = None,
        is_parent: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.folder_path = Path(folder_path)
        self.is_parent = is_parent
        self._pdf_count = pdf_count
        self._setup_ui()

    def _setup_ui(self):
        # Gleiche Masse wie PDFThumbnailWidget, damit das Raster buendig bleibt
        self.setMinimumSize(160, 230)
        self.setMaximumSize(180, 260)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setAcceptDrops(True)
        self.setStyleSheet(self._STYLE_NORMAL)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        layout.addStretch()

        icon = QLabel("⬆📁" if self.is_parent else "📁")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 48px; background: transparent;")
        layout.addWidget(icon)

        self.name_label = QLabel(".." if self.is_parent else self.folder_path.name)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setStyleSheet("font-size: 12px; font-weight: bold; background: transparent;")
        layout.addWidget(self.name_label)

        self.count_label = QLabel(self._count_text())
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count_label.setStyleSheet("font-size: 11px; color: #777; background: transparent;")
        layout.addWidget(self.count_label)
        layout.addStretch()

        if self.is_parent:
            self.setToolTip(
                f"Übergeordneter Ordner: {self.folder_path}\n"
                "Klick wechselt nach oben, PDFs hierher ziehen verschiebt sie."
            )
        else:
            self.setToolTip(
                f"{self.folder_path}\n"
                "Doppelklick öffnet den Ordner, PDFs hierher ziehen verschiebt sie."
            )

    def _count_text(self) -> str:
        if self.is_parent:
            return "übergeordneter Ordner"
        if self._pdf_count is None:
            return ""
        return f"{self._pdf_count} {'PDF' if self._pdf_count == 1 else 'PDFs'}"

    # --- Maus -----------------------------------------------------------

    def mouseReleaseEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit(self.folder_path)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.folder_path)
        super().mouseDoubleClickEvent(event)

    def enterEvent(self, event):
        self.setStyleSheet(self._STYLE_HOVER)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self._STYLE_NORMAL)
        super().leaveEvent(event)

    # --- Drag & Drop ------------------------------------------------------

    @staticmethod
    def _pdf_paths(mime) -> list[Path]:
        if not mime.hasUrls():
            return []
        paths = [Path(url.toLocalFile()) for url in mime.urls()]
        return [p for p in paths if p.suffix.lower() == ".pdf"]

    def dragEnterEvent(self, event: QDragEnterEvent):
        if self._pdf_paths(event.mimeData()):
            self.setStyleSheet(self._STYLE_DROP)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self._STYLE_NORMAL)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet(self._STYLE_NORMAL)
        pdfs = self._pdf_paths(event.mimeData())
        if not pdfs:
            event.ignore()
            return
        for pdf in pdfs:
            self.pdf_dropped.emit(pdf, self.folder_path)
        event.acceptProposedAction()

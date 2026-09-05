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
from PyQt6.QtGui import QCursor, QDragEnterEvent, QDropEvent, QFontMetrics
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from src.gui.tile_view import TileView, fit_text_lines, tile_view


class FolderTileWidget(QFrame):
    """Kachel für einen Ordner im Scan-Bereich.

    Hat dieselben Masse wie die PDF-Kachel der jeweiligen Ansicht (Issue #117),
    damit das Raster buendig bleibt - aber keine Hover-Vorschau.
    """

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
        view: Optional[TileView] = None,
    ):
        super().__init__(parent)
        self.folder_path = Path(folder_path)
        self.is_parent = is_parent
        self._pdf_count = pdf_count
        self._view = view or tile_view(None)
        self._setup_ui()

    def _setup_ui(self):
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setAcceptDrops(True)
        self.setStyleSheet(self._STYLE_NORMAL)

        self._layout = QVBoxLayout(self)
        self._layout.addStretch()

        self.icon_label = QLabel("⬆📁" if self.is_parent else "📁")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self.icon_label)

        self.name_label = QLabel()
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self.name_label)

        self.count_label = QLabel(self._count_text())
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self.count_label)
        self._layout.addStretch()

        self._apply_view()

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

    @property
    def view(self) -> TileView:
        """Aktuelle Kachelgroesse (Issue #117)."""
        return self._view

    def set_view(self, view: TileView):
        """Schaltet die Kachelgroesse um (gleiche Masse wie die PDF-Kacheln)."""
        if view.id == self._view.id:
            return
        self._view = view
        self._apply_view()

    def _apply_view(self):
        v = self._view
        # Gleiche Masse wie PDFThumbnailWidget, damit das Raster buendig bleibt
        self.setMinimumSize(v.tile_w, v.tile_h)
        self.setMaximumSize(v.tile_max_w, v.tile_max_h)
        self._layout.setContentsMargins(v.margin, v.margin, v.margin, v.margin)
        self._layout.setSpacing(v.spacing)
        self.icon_label.setStyleSheet(
            f"font-size: {v.folder_icon_px}px; background: transparent;"
        )
        # Schrift ueber QFont, damit QFontMetrics fuer den Umbruch stimmt
        name_font = self.name_label.font()
        name_font.setPixelSize(v.font_px + 1)
        name_font.setBold(True)
        self.name_label.setFont(name_font)
        self.name_label.setStyleSheet("background: transparent;")
        count_font = self.count_label.font()
        count_font.setPixelSize(v.font_px)
        self.count_label.setFont(count_font)
        self.count_label.setStyleSheet("color: #777; background: transparent;")
        # In den kompakten Ansichten fehlt der Platz fuer den Zaehler-Text
        # unter langen Ordnernamen - er steht dann nur im Tooltip.
        self.count_label.setVisible(v.id == "gross" or not self.is_parent)
        self._update_name()

    def _update_name(self):
        """Ordnername pixelgenau auf die Kachelbreite umgebrochen."""
        v = self._view
        name = ".." if self.is_parent else self.folder_path.name
        self.name_label.setText(
            fit_text_lines(name, QFontMetrics(self.name_label.font()), v.text_width, v.name_lines)
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

"""
Ordnerzeile fuer den Scan-Bereich (Explorer-Gefuehl, Issues #29 und #147)

Zeigt einen Unterordner (oder ".." fuer den uebergeordneten Ordner) als
schmale Zeile ueber dem PDF-Raster: Symbol links, Name (bei Platzmangel
gekuerzt, voller Pfad im Tooltip), Anzahl PDFs rechts in grau. Hoehe und
Schrift sind fest und haengen nicht von der Kachelgroesse der PDFs ab
(Issue #117). Doppelklick wechselt in den Ordner, die ".."-Zeile reagiert
auf Einfachklick, PDFs koennen per Drag & Drop hineingeschoben werden.

GPL-3.0-or-later - Copyright (c) 2026
"""

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QDragEnterEvent, QDropEvent, QFontMetrics
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QSizePolicy

from src.gui.pfad_aktionen import (
    PFAD_KOPIEREN_TEXT,
    im_dateimanager_zeigen,
    oeffnen_text,
    pfad_kopieren,
)


class FolderTileWidget(QFrame):
    """Zeile fuer einen Ordner im Scan-Bereich (Issue #147).

    Der Klassenname bleibt aus Kompatibilitaet "Tile"; dargestellt wird eine
    Zeile. Das Hauptfenster ordnet die Zeilen in einem eigenen Raster mit ein
    oder zwei Spalten ueber den PDF-Kacheln an.
    """

    clicked = pyqtSignal(Path)  # Einfachklick (nur fuer ".." verbunden, Issue #50)
    double_clicked = pyqtSignal(Path)  # In den Ordner wechseln
    pdf_dropped = pyqtSignal(Path, Path)  # (pdf_path, folder_path)

    ROW_HEIGHT = 26  # feste Zeilenhoehe in Pixeln
    NAME_PX = 12  # Schriftgroesse des Ordnernamens
    COUNT_PX = 11  # Schriftgroesse des Zaehlers
    ICON_PX = 14  # Schriftgroesse des Symbols
    MIN_WIDTH = 120  # schmaler wird eine Zeile nie

    _STYLE_NORMAL = (
        "FolderTileWidget { background-color: #fbf8ec; border: 1px solid #e3dcc2; "
        "border-radius: 3px; }"
    )
    _STYLE_HOVER = (
        "FolderTileWidget { background-color: #fff3cd; border: 1px solid #daa520; "
        "border-radius: 3px; }"
    )
    _STYLE_DROP = (
        "FolderTileWidget { background-color: #d9f2d9; border: 2px solid #4caf50; "
        "border-radius: 3px; }"
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
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setAcceptDrops(True)
        self.setStyleSheet(self._STYLE_NORMAL)
        self.setFixedHeight(self.ROW_HEIGHT)
        self.setMinimumWidth(self.MIN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 8, 0)
        layout.setSpacing(6)

        self.icon_label = QLabel("⬆" if self.is_parent else "📁")
        self.icon_label.setStyleSheet("background: transparent; border: none;")
        icon_font = self.icon_label.font()
        icon_font.setPixelSize(self.ICON_PX)
        self.icon_label.setFont(icon_font)
        layout.addWidget(self.icon_label)

        # Name: darf schrumpfen (Ignored), wird dann mit "…" gekuerzt
        self.name_label = QLabel()
        self.name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.name_label.setStyleSheet("background: transparent; border: none;")
        # Schrift ueber QFont, damit QFontMetrics fuers Kuerzen dieselbe misst
        name_font = self.name_label.font()
        name_font.setPixelSize(self.NAME_PX)
        name_font.setBold(not self.is_parent)
        self.name_label.setFont(name_font)
        layout.addWidget(self.name_label, 1)

        self.count_label = QLabel(self._count_text())
        self.count_label.setStyleSheet("color: #777; background: transparent; border: none;")
        count_font = self.count_label.font()
        count_font.setPixelSize(self.COUNT_PX)
        self.count_label.setFont(count_font)
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.count_label)

        self._update_name()

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
    def full_name(self) -> str:
        """Ungekuerzter Anzeigename (".." fuer den uebergeordneten Ordner)."""
        return ".." if self.is_parent else self.folder_path.name

    def _update_name(self):
        """Name in die verfuegbare Breite einpassen (rechts mit "…" gekuerzt).

        Solange die Zeile nicht angezeigt wird, steht der volle Name da; das
        Kuerzen holt resizeEvent nach.
        """
        name = self.full_name
        width = self.name_label.width()
        if self.isVisible() and width > 0:
            fm = QFontMetrics(self.name_label.font())
            name = fm.elidedText(name, Qt.TextElideMode.ElideRight, width)
        self.name_label.setText(name)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_name()

    def showEvent(self, event):
        super().showEvent(event)
        self._update_name()

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

    def contextMenuEvent(self, event):
        """Rechtsklick: im Dateimanager oeffnen, Pfad kopieren (Issue #154)."""
        self._build_context_menu().exec(event.globalPos())

    def _build_context_menu(self) -> QMenu:
        """Baut das Kontextmenue (getrennt, damit es testbar ist)."""
        menu = QMenu(self)
        open_action = menu.addAction(oeffnen_text())
        open_action.triggered.connect(self._open_in_file_manager)
        copy_action = menu.addAction(PFAD_KOPIEREN_TEXT)
        copy_action.triggered.connect(self._copy_path)
        return menu

    def _open_in_file_manager(self):
        im_dateimanager_zeigen(self.folder_path)

    def _copy_path(self):
        pfad_kopieren(self.folder_path)

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

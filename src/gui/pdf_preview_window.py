"""
Eigenstaendiges Vorschau-Fenster fuer eine PDF (Issue #76).

Ersetzt das Oeffnen im Browser/Office beim Doppelklick, wenn in den
Einstellungen "Integrierte Vorschau" gewaehlt ist (Default). Nicht-modal,
wird wiederverwendet: ein weiterer Doppelklick laedt die naechste PDF in
dasselbe Fenster.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QMainWindow

from src.gui.pdf_preview_widget import PdfPreviewWidget

_DEFAULT_SIZE = (900, 1000)


class PdfPreviewWindow(QMainWindow):
    """Fenster mit grosser PDF-Vorschau.

    Signals:
        open_external_requested(Path): "Extern oeffnen" gedrueckt
        geometry_changed(list): Fenstergeometrie [x, y, w, h] zum Merken
    """

    open_external_requested = pyqtSignal(Path)
    geometry_changed = pyqtSignal(list)
    # Markierter Text -> Metadaten-Feld (Issue #109), weitergereicht aus der Vorschau
    apply_text_requested = pyqtSignal(str, str)

    def __init__(self, parent=None, geometry: list | None = None):
        super().__init__(parent)
        self.setWindowTitle("PDF-Vorschau")
        # Eigenes Top-Level-Fenster (nicht im Hauptfenster eingebettet),
        # bleibt aber dem Hauptfenster zugeordnet und schliesst mit ihm.
        self.setWindowFlag(Qt.WindowType.Window, True)

        self.preview = PdfPreviewWidget(self, compact=False)
        self.preview.open_external_requested.connect(self.open_external_requested)
        self.preview.apply_text_requested.connect(self.apply_text_requested)
        self.setCentralWidget(self.preview)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close)
        QShortcut(QKeySequence.StandardKey.Close, self, activated=self.close)

        self._apply_geometry(geometry)

    def _apply_geometry(self, geometry: list | None):
        if geometry and len(geometry) == 4 and all(isinstance(v, int) for v in geometry):
            x, y, w, h = geometry
            if w > 200 and h > 200:
                self.setGeometry(x, y, w, h)
                return
        self.resize(*_DEFAULT_SIZE)

    def show_pdf(self, path: Path | str) -> None:
        """Zeigt die PDF und bringt das Fenster nach vorn."""
        path = Path(path)
        self.setWindowTitle(f"PDF-Vorschau – {path.name}")
        self.preview.load_pdf(path)
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def current_path(self) -> Path | None:
        return self.preview.current_path

    def closeEvent(self, event):
        g = self.geometry()
        self.geometry_changed.emit([g.x(), g.y(), g.width(), g.height()])
        self.preview.shutdown()
        self.preview.clear()
        super().closeEvent(event)

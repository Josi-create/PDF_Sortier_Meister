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
from src.i18n import tr

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
        self.setWindowTitle(tr("PDF-Vorschau"))
        # Eigenes Top-Level-Fenster (nicht im Hauptfenster eingebettet),
        # bleibt aber dem Hauptfenster zugeordnet und schliesst mit ihm.
        self.setWindowFlag(Qt.WindowType.Window, True)

        self.preview = PdfPreviewWidget(self, compact=False)
        self.preview.open_external_requested.connect(self.open_external_requested)
        self.preview.apply_text_requested.connect(self.apply_text_requested)
        # Seite, die nach dem Laden angesprungen wird (Zitate aus Chat und Suche, Phase 5)
        self._pending_seite: tuple[Path, int] | None = None
        self.preview.document_loaded.connect(self._on_document_loaded)
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

    def show_pdf(self, path: Path | str, seite: int | None = None) -> None:
        """Zeigt die PDF (optional direkt auf ``seite``, 1-basiert) und bringt das Fenster nach vorn."""
        path = Path(path)
        self.setWindowTitle(tr("PDF-Vorschau – {name}").format(name=path.name))
        self._pending_seite = (path, int(seite)) if seite and int(seite) > 0 else None
        self.preview.load_pdf(path)
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def current_path(self) -> Path | None:
        return self.preview.current_path

    def _on_document_loaded(self, path: Path) -> None:
        """Vorgemerkte Seite (``show_pdf(..., seite)``) anspringen, sobald das Dokument steht."""
        pending = getattr(self, "_pending_seite", None)
        if pending and Path(path) == pending[0]:
            self.preview.go_to_page(pending[1] - 1)
            self._pending_seite = None

    def closeEvent(self, event):
        g = self.geometry()
        self.geometry_changed.emit([g.x(), g.y(), g.width(), g.height()])
        self.preview.shutdown()
        self.preview.clear()
        super().closeEvent(event)

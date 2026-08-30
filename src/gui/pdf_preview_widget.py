"""
Integrierte PDF-Vorschau auf Basis von QtPdf (Issues #74, #76).

``QPdfView`` ist Qts eigener, PDFium-basierter Viewer - schnell, ohne
Chromium (kein QtWebEngine) und ohne eigenen Renderer. Das Widget wird an
zwei Stellen verwendet: kompakt unten im Detail-Panel und gross im
Vorschau-Fenster.

Wichtig fuer den Sortier-Workflow: Die PDF wird NICHT ueber den Dateipfad
geladen, sondern als Bytes in einen ``QBuffer`` gelesen. So haelt die
Vorschau keinen Datei-Handle offen, und die PDF kann waehrend der Anzeige
verschoben oder umbenannt werden (Windows sperrt sonst die Datei). Das
Lesen laeuft in einem Thread, damit OneDrive-"Files On-Demand" die GUI
nicht blockiert (siehe Issue #39-Analyse im Detail-Panel).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import (
    QBuffer, QEvent, QIODevice, QPoint, QPointF, QRect, QSize, QSizeF, Qt, QThread, pyqtSignal,
)
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPolygonF
from PyQt6.QtPdf import QPdfDocument, QPdfSelection
from PyQt6.QtPdfWidgets import QPdfView
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QStackedLayout,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# Groessere Dateien werden nicht komplett in den Speicher gelesen.
MAX_PREVIEW_BYTES = 300 * 1024 * 1024

ZOOM_STEP = 1.25
ZOOM_MIN = 0.2
ZOOM_MAX = 8.0

# Rechtsklick auf markierten Text: in welches Metadaten-Feld? (Issue #109)
SELECTION_TARGETS: tuple[tuple[str, str], ...] = (
    ("korrespondent", "Als Korrespondent übernehmen"),
    ("subject", "Als Kategorie übernehmen"),
    ("description", "Als Zusammenfassung übernehmen"),
    ("betrag_netto", "Als Betrag Netto übernehmen"),
    ("betrag_brutto", "Als Betrag Brutto übernehmen"),
    ("waehrung", "Als Währung übernehmen"),
    ("mwst_satz", "Als MwSt-Satz übernehmen"),
    ("iban", "Als IBAN übernehmen"),
    ("steuerjahr", "Als Steuerjahr übernehmen"),
)


class _SelectionOverlay(QWidget):
    """Zeichnet die Textmarkierung ueber den Viewport der QPdfView."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._polygons: list[QPolygonF] = []

    def set_polygons(self, polygons):
        self._polygons = list(polygons)
        self.update()

    def paintEvent(self, _event):
        if not self._polygons:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(51, 120, 220, 80))
        for poly in self._polygons:
            painter.drawPolygon(poly)
        painter.end()


class _PdfBytesReader(QThread):
    """Liest eine PDF-Datei im Hintergrund komplett ein."""

    # (generation, bytes | None, fehlertext)
    finished_read = pyqtSignal(int, object, str)

    def __init__(self, path: Path, generation: int, parent=None):
        super().__init__(parent)
        self._path = path
        self._generation = generation

    def run(self):
        try:
            size = self._path.stat().st_size
            if size > MAX_PREVIEW_BYTES:
                self.finished_read.emit(
                    self._generation, None,
                    f"Datei zu groß für die Vorschau ({size // (1024 * 1024)} MB).",
                )
                return
            data = self._path.read_bytes()
        except OSError as e:
            self.finished_read.emit(self._generation, None, f"Datei konnte nicht gelesen werden: {e}")
            return
        self.finished_read.emit(self._generation, data, "")


class PdfPreviewWidget(QWidget):
    """PDF-Ansicht mit Seiten-Navigation und Zoom.

    Signals:
        document_loaded(Path): Dokument ist angezeigt (auch fuer Tests)
        load_failed(Path, str): Datei konnte nicht angezeigt werden
        enlarge_requested(Path): Nutzer moechte die grosse Ansicht (Doppelklick / Button)
        open_external_requested(Path): Nutzer moechte die PDF extern oeffnen
    """

    document_loaded = pyqtSignal(Path)
    load_failed = pyqtSignal(Path, str)
    enlarge_requested = pyqtSignal(Path)
    open_external_requested = pyqtSignal(Path)
    # Textauswahl (Issue #109): markierter Text; "uebernehmen in Feld X"
    text_selected = pyqtSignal(str)
    apply_text_requested = pyqtSignal(str, str)  # (feld, text)

    def __init__(self, parent=None, compact: bool = False):
        super().__init__(parent)
        self._compact = compact
        self._current_path: Path | None = None
        self._buffer: QBuffer | None = None
        self._generation = 0
        self._readers: list[_PdfBytesReader] = []
        # Textauswahl mit der Maus
        self._selection: QPdfSelection | None = None
        self._sel_page: int = -1
        self._sel_start: QPointF = QPointF()
        self._selecting: bool = False
        self._line_boxes: dict[int, list] = {}  # Seite -> Textzeilen-Rechtecke (pt)

        self._document = QPdfDocument(self)
        self._document.statusChanged.connect(self._on_status_changed)
        # Gebundene Methoden statt Lambdas: Qt trennt sie beim Zerstoeren des
        # Widgets selbst, ein Lambda liefe sonst noch auf halb abgebaute Objekte.
        self._document.pageCountChanged.connect(self._on_page_count_changed)

        self._setup_ui()
        self._set_controls_enabled(False)

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Werkzeugleiste
        bar = QHBoxLayout()
        bar.setContentsMargins(4, 2, 4, 2)
        bar.setSpacing(2)
        style = self.style()

        self.prev_btn = self._tool_button(
            style.standardIcon(QStyle.StandardPixmap.SP_ArrowLeft), "Vorherige Seite (Bild auf)"
        )
        self.prev_btn.clicked.connect(self.previous_page)
        bar.addWidget(self.prev_btn)

        self.page_label = QLabel("– / –")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setMinimumWidth(56)
        self.page_label.setToolTip("Aktuelle Seite / Seitenzahl")
        bar.addWidget(self.page_label)

        self.next_btn = self._tool_button(
            style.standardIcon(QStyle.StandardPixmap.SP_ArrowRight), "Nächste Seite (Bild ab)"
        )
        self.next_btn.clicked.connect(self.next_page)
        bar.addWidget(self.next_btn)

        bar.addSpacing(8)

        self.zoom_out_btn = self._tool_button(None, "Verkleinern", text="−")
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        bar.addWidget(self.zoom_out_btn)

        self.zoom_in_btn = self._tool_button(None, "Vergrößern", text="+")
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        bar.addWidget(self.zoom_in_btn)

        self.fit_width_btn = self._tool_button(None, "An Breite anpassen", text="Breite")
        self.fit_width_btn.clicked.connect(self.fit_width)
        bar.addWidget(self.fit_width_btn)

        self.fit_page_btn = self._tool_button(None, "Ganze Seite anzeigen", text="Seite")
        self.fit_page_btn.clicked.connect(self.fit_page)
        bar.addWidget(self.fit_page_btn)

        bar.addStretch()

        if self._compact:
            self.enlarge_btn = self._tool_button(
                None, "Große Vorschau in eigenem Fenster (auch Doppelklick auf die Seite)",
                text="Groß",
            )
            self.enlarge_btn.clicked.connect(self._emit_enlarge)
            bar.addWidget(self.enlarge_btn)
        else:
            self.enlarge_btn = None

        self.external_btn = self._tool_button(
            None, "Im externen Programm öffnen (siehe Einstellungen > Allgemein)",
            text="Extern öffnen",
        )
        self.external_btn.clicked.connect(self._emit_open_external)
        bar.addWidget(self.external_btn)

        layout.addLayout(bar)

        # Ansicht + Platzhalter/Fehler uebereinander
        self._stack_host = QWidget()
        self._stack = QStackedLayout(self._stack_host)
        self._stack.setContentsMargins(0, 0, 0, 0)

        self._view = QPdfView(self._stack_host)
        self._view.setDocument(self._document)
        self._view.setPageMode(QPdfView.PageMode.MultiPage)
        self._view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self._view.setPageSpacing(6)
        self._view.pageNavigator().currentPageChanged.connect(self._on_current_page_changed)
        self._view.viewport().installEventFilter(self)
        self._view.setToolTip(
            "Text mit der Maus markieren, dann Rechtsklick: "
            "in ein Metadaten-Feld übernehmen (Korrespondent, Betrag, IBAN, ...)."
        )
        self._stack.addWidget(self._view)

        # Markierung ueber dem Viewport; folgt Scrollen und Zoom
        self._overlay = _SelectionOverlay(self._view.viewport())
        self._overlay.resize(self._view.viewport().size())
        self._view.verticalScrollBar().valueChanged.connect(self._refresh_overlay)
        self._view.horizontalScrollBar().valueChanged.connect(self._refresh_overlay)
        self._view.zoomFactorChanged.connect(self._refresh_overlay)
        self._view.zoomModeChanged.connect(self._refresh_overlay)

        self.message_label = QLabel("Keine PDF ausgewählt")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet("color: #888; padding: 16px;")
        self._stack.addWidget(self.message_label)
        self._stack.setCurrentWidget(self.message_label)

        self._stack_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._stack_host, 1)

    @staticmethod
    def _tool_button(icon, tooltip: str, text: str = "") -> QToolButton:
        btn = QToolButton()
        if icon is not None:
            btn.setIcon(icon)
        if text:
            btn.setText(text)
        btn.setToolTip(tooltip)
        btn.setAutoRaise(True)
        return btn

    def _set_controls_enabled(self, enabled: bool):
        for btn in (self.prev_btn, self.next_btn, self.zoom_in_btn, self.zoom_out_btn,
                    self.fit_width_btn, self.fit_page_btn, self.external_btn):
            btn.setEnabled(enabled)
        if self.enlarge_btn is not None:
            self.enlarge_btn.setEnabled(enabled)

    # ------------------------------------------------------------------ #
    # Laden
    # ------------------------------------------------------------------ #

    def load_pdf(self, path: Path | str) -> None:
        """Zeigt die PDF an; das Einlesen laeuft im Hintergrund."""
        path = Path(path)
        self._generation += 1
        generation = self._generation
        self._current_path = path
        self._show_message(f"Lade {path.name} …")
        self._set_controls_enabled(False)

        reader = _PdfBytesReader(path, generation, self)
        reader.finished_read.connect(self._on_bytes_read)
        # Nur Qt-seitige Verbindungen (kein Lambda): Wird das Widget samt
        # Reader zerstoert, bevor der Slot laeuft, raeumt Qt die ausstehenden
        # Aufrufe selbst ab - ein Lambda liefe sonst auf ein totes Objekt.
        reader.finished.connect(reader.deleteLater)
        reader.finished.connect(self._prune_readers)
        self._prune_readers()
        self._readers.append(reader)
        reader.start()

    def load_bytes(self, path: Path | str, data: bytes) -> bool:
        """Zeigt bereits eingelesene PDF-Daten an (synchron).

        Returns:
            True, wenn das Dokument angezeigt werden kann.
        """
        path = Path(path)
        self._generation += 1
        self._current_path = path
        self._release_document()

        buffer = QBuffer(self)
        buffer.setData(data)
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self._buffer = buffer
        self._document.load(buffer)

        if self._document.status() == QPdfDocument.Status.Error:
            self._fail(path, self._error_text(self._document.error()))
            return False

        self._view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self._view.pageNavigator().jump(0, QPointF(0, 0))
        self._line_boxes = {}
        self.clear_selection()
        self._stack.setCurrentWidget(self._view)
        self._set_controls_enabled(True)
        self._update_page_label()
        self.document_loaded.emit(path)
        return True

    def clear(self) -> None:
        """Leert die Ansicht (keine PDF ausgewaehlt)."""
        self._generation += 1
        self._current_path = None
        self._line_boxes = {}
        self.clear_selection()
        self._release_document()
        self._show_message("Keine PDF ausgewählt")
        self._set_controls_enabled(False)
        self.page_label.setText("– / –")

    def shutdown(self, timeout_ms: int = 3000) -> None:
        """Wartet auf laufende Lese-Threads (beim Schliessen)."""
        for reader in list(self._readers):
            if not sip.isdeleted(reader):
                reader.wait(timeout_ms)
        self._prune_readers()

    def _on_bytes_read(self, generation: int, data, error: str):
        if generation != self._generation or self._current_path is None:
            return  # Inzwischen wurde eine andere PDF gewaehlt
        path = self._current_path
        if data is None:
            self._fail(path, error or "Unbekannter Fehler")
            return
        self.load_bytes(path, data)

    def _prune_readers(self):
        """Fertige oder bereits geloeschte Reader aus der Liste entfernen."""
        self._readers = [
            r for r in self._readers if not sip.isdeleted(r) and r.isRunning()
        ]

    def _release_document(self):
        if self._document.status() != QPdfDocument.Status.Null:
            self._document.close()
        if self._buffer is not None:
            self._buffer.close()
            self._buffer.deleteLater()
            self._buffer = None

    def _fail(self, path: Path, message: str):
        self._release_document()
        self._show_message(f"Vorschau nicht möglich:\n{message}")
        self._set_controls_enabled(False)
        self.external_btn.setEnabled(True)
        self.load_failed.emit(path, message)

    def _show_message(self, text: str):
        self.message_label.setText(text)
        self._stack.setCurrentWidget(self.message_label)

    @staticmethod
    def _error_text(error) -> str:
        mapping = {
            QPdfDocument.Error.FileNotFound: "Datei nicht gefunden.",
            QPdfDocument.Error.InvalidFileFormat: "Keine gültige PDF-Datei.",
            QPdfDocument.Error.IncorrectPassword: "Die PDF ist passwortgeschützt.",
            QPdfDocument.Error.UnsupportedSecurityScheme: "Nicht unterstützte Verschlüsselung.",
        }
        return mapping.get(error, "Die PDF konnte nicht gelesen werden.")

    def _on_page_count_changed(self, _count: int):
        self._update_page_label()

    def _on_current_page_changed(self, _page: int):
        self._update_page_label()

    def _on_status_changed(self, status):
        if status == QPdfDocument.Status.Error and self._current_path is not None:
            self._fail(self._current_path, self._error_text(self._document.error()))
        elif status == QPdfDocument.Status.Ready:
            self._update_page_label()

    # ------------------------------------------------------------------ #
    # Zustand
    # ------------------------------------------------------------------ #

    @property
    def current_path(self) -> Path | None:
        return self._current_path

    def is_showing_document(self) -> bool:
        return (self._stack.currentWidget() is self._view
                and self._document.status() == QPdfDocument.Status.Ready)

    def page_count(self) -> int:
        if sip.isdeleted(self._document) or self._document.status() != QPdfDocument.Status.Ready:
            return 0
        return self._document.pageCount()

    def current_page(self) -> int:
        """0-basierter Seitenindex."""
        return self._view.pageNavigator().currentPage()

    # ------------------------------------------------------------------ #
    # Navigation / Zoom
    # ------------------------------------------------------------------ #

    def go_to_page(self, index: int) -> None:
        count = self.page_count()
        if count == 0:
            return
        index = max(0, min(index, count - 1))
        self._view.pageNavigator().jump(index, QPointF(0, 0))
        self._update_page_label()

    def next_page(self) -> None:
        self.go_to_page(self.current_page() + 1)

    def previous_page(self) -> None:
        self.go_to_page(self.current_page() - 1)

    def zoom_in(self) -> None:
        self._set_zoom(self._effective_zoom() * ZOOM_STEP)

    def zoom_out(self) -> None:
        self._set_zoom(self._effective_zoom() / ZOOM_STEP)

    def fit_width(self) -> None:
        self._view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

    def fit_page(self) -> None:
        self._view.setZoomMode(QPdfView.ZoomMode.FitInView)

    def zoom_mode(self):
        return self._view.zoomMode()

    def zoom_factor(self) -> float:
        return self._view.zoomFactor()

    def _effective_zoom(self) -> float:
        if self._view.zoomMode() == QPdfView.ZoomMode.Custom:
            return self._view.zoomFactor()
        # Bei "an Breite anpassen" den tatsaechlichen Faktor aus der
        # Seitenbreite ableiten, damit +/- nicht bei 100% springt.
        if self.page_count() > 0:
            page_width_pt = self._document.pagePointSize(self.current_page()).width()
            viewport_width = self._view.viewport().width() - 2 * self._view.documentMargins().left()
            if page_width_pt > 0 and viewport_width > 0:
                # QPdfView rendert 1 pt = 1 px bei Faktor 1 (72 dpi-Basis)
                return max(ZOOM_MIN, viewport_width / page_width_pt)
        return self._view.zoomFactor()

    def _set_zoom(self, factor: float) -> None:
        factor = max(ZOOM_MIN, min(ZOOM_MAX, factor))
        self._view.setZoomMode(QPdfView.ZoomMode.Custom)
        self._view.setZoomFactor(factor)

    def _update_page_label(self):
        if sip.isdeleted(self) or sip.isdeleted(self.page_label):
            return
        count = self.page_count()
        if count == 0:
            self.page_label.setText("– / –")
            return
        current = self.current_page() + 1
        self.page_label.setText(f"{current} / {count}")
        self.prev_btn.setEnabled(current > 1)
        self.next_btn.setEnabled(current < count)

    # ------------------------------------------------------------------ #
    # Interaktion
    # ------------------------------------------------------------------ #

    def _emit_enlarge(self):
        if self._current_path is not None:
            self.enlarge_requested.emit(self._current_path)

    def _emit_open_external(self):
        if self._current_path is not None:
            self.open_external_requested.emit(self._current_path)

    def eventFilter(self, obj, event):
        if obj is self._view.viewport():
            etype = event.type()
            if (etype == QEvent.Type.MouseButtonDblClick
                    and self._compact and self._current_path is not None):
                self.enlarge_requested.emit(self._current_path)
                return True
            if etype == QEvent.Type.Wheel and (
                event.modifiers() & Qt.KeyboardModifier.ControlModifier
            ):
                if event.angleDelta().y() > 0:
                    self.zoom_in()
                elif event.angleDelta().y() < 0:
                    self.zoom_out()
                return True
            if etype == QEvent.Type.Resize:
                self._overlay.resize(event.size())
                self._refresh_overlay()
            elif etype == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._begin_selection(event.position().toPoint())
                elif event.button() == Qt.MouseButton.RightButton and self.selected_text():
                    self._show_selection_menu(event.globalPosition().toPoint())
                    return True
            elif etype == QEvent.Type.MouseMove and self._selecting:
                if event.buttons() & Qt.MouseButton.LeftButton:
                    self._update_selection(event.position().toPoint())
                    return True
            elif etype == QEvent.Type.MouseButtonRelease and self._selecting:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._selecting = False
                    self._update_selection(event.position().toPoint())
                    text = self.selected_text()
                    if text:
                        self.text_selected.emit(text)
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------ #
    # Textauswahl (Issue #109)
    # ------------------------------------------------------------------ #

    def selected_text(self) -> str:
        """Markierter Text, Leerraum normalisiert; "" ohne Markierung."""
        if self._selection is None:
            return ""
        return " ".join(self._selection.text().split())

    def clear_selection(self) -> None:
        self._selection = None
        self._sel_page = -1
        self._selecting = False
        self._refresh_overlay()

    def _text_line_boxes(self, page: int) -> list:
        """Rechtecke der Textzeilen einer Seite (pt), einmal pro Dokument ermittelt."""
        boxes = self._line_boxes.get(page)
        if boxes is None:
            boxes = []
            try:
                all_text = self._document.getAllText(page)
                if all_text.isValid():
                    boxes = [poly.boundingRect() for poly in all_text.bounds()]
            except Exception:  # noqa: BLE001 - dann eben ohne Einrasten
                boxes = []
            self._line_boxes[page] = boxes
        return boxes

    def _snap_to_text(self, page: int, point: QPointF) -> QPointF:
        """Punkt auf die naechste Textzeile ziehen.

        PDFium liefert nur eine Auswahl, wenn Start- UND Endpunkt ein Zeichen
        treffen. Wer im Weissraum zu ziehen beginnt oder ueber das Zeilenende
        hinaus zieht, bekaeme sonst nichts markiert.
        """
        boxes = self._text_line_boxes(page)
        if not boxes:
            return point
        best = None
        for box in boxes:
            dx = max(box.left() - point.x(), 0.0, point.x() - box.right())
            dy = max(box.top() - point.y(), 0.0, point.y() - box.bottom())
            key = (dy, dx)
            if best is None or key < best[0]:
                best = (key, box)
        box = best[1]
        inset = 1.0
        x = min(max(point.x(), box.left() + inset), max(box.left() + inset, box.right() - inset))
        y = min(max(point.y(), box.top() + inset), max(box.top() + inset, box.bottom() - inset))
        return QPointF(x, y)

    def _begin_selection(self, pos: QPoint) -> None:
        self.clear_selection()
        if not self.is_showing_document():
            return
        hit = self._page_at(pos)
        if hit is None:
            return
        page, rect = hit
        self._sel_page = page
        self._sel_start = self._snap_to_text(page, self._to_page_point(rect, page, pos))
        self._selecting = True

    def _update_selection(self, pos: QPoint) -> None:
        if self._sel_page < 0:
            return
        rect = self._page_rect_in_viewport(self._sel_page)
        if rect is None:
            return
        end = self._snap_to_text(self._sel_page, self._to_page_point(rect, self._sel_page, pos))
        selection = self._document.getSelection(self._sel_page, self._sel_start, end)
        self._selection = selection if selection.isValid() and selection.text().strip() else None
        self._refresh_overlay()

    def select_page_region(self, page: int, start: QPointF, end: QPointF) -> str:
        """Markiert den Text zwischen zwei Punkten (Seiten-Koordinaten in pt).

        Fuer Tests und Skripte - die Maus macht dasselbe ueber den Viewport.
        """
        self.clear_selection()
        if not self.is_showing_document() or not 0 <= page < self.page_count():
            return ""
        self._sel_page = page
        self._sel_start = self._snap_to_text(page, start)
        selection = self._document.getSelection(page, self._sel_start, self._snap_to_text(page, end))
        self._selection = selection if selection.isValid() and selection.text().strip() else None
        self._refresh_overlay()
        return self.selected_text()

    def _refresh_overlay(self, *_args) -> None:
        overlay = getattr(self, "_overlay", None)
        if overlay is None or sip.isdeleted(overlay):
            return
        polygons: list[QPolygonF] = []
        if self._selection is not None and self._sel_page >= 0:
            rect = self._page_rect_in_viewport(self._sel_page)
            if rect is not None:
                polygons = [
                    self._polygon_to_viewport(rect, self._sel_page, poly)
                    for poly in self._selection.bounds()
                ]
        overlay.set_polygons(polygons)

    def _build_selection_menu(self) -> QMenu:
        """Kontextmenue fuer den markierten Text (ohne exec, fuer Tests)."""
        text = self.selected_text()
        menu = QMenu(self)
        short = text if len(text) <= 40 else text[:37] + "…"
        menu.addSection(f"„{short}“")
        for field_key, label in SELECTION_TARGETS:
            action = menu.addAction(label)
            action.setData(field_key)
            action.triggered.connect(
                lambda _checked=False, k=field_key, t=text: self.apply_text_requested.emit(k, t)
            )
        menu.addSeparator()
        copy_action = menu.addAction("Kopieren")
        copy_action.triggered.connect(lambda _checked=False, t=text: QApplication.clipboard().setText(t))
        return menu

    def _show_selection_menu(self, global_pos: QPoint) -> None:
        self._build_selection_menu().exec(global_pos)

    # -- Seitengeometrie (wie QPdfViewPrivate::calculateDocumentLayout) ---- #

    @staticmethod
    def _screen_resolution() -> float:
        screen = QGuiApplication.primaryScreen()
        return (screen.logicalDotsPerInch() / 72.0) if screen is not None else 1.0

    def _page_geometries(self) -> dict[int, QRect]:
        """Seiten-Rechtecke in Dokument-Koordinaten (Pixel, vor dem Scrollen)."""
        count = self.page_count()
        if count == 0:
            return {}
        view = self._view
        viewport = view.viewport()
        margins = view.documentMargins()
        spacing = view.pageSpacing()
        res = self._screen_resolution()
        mode = view.zoomMode()

        sizes: dict[int, QSize] = {}
        total_width = 0
        for page in range(count):
            points = self._document.pagePointSize(page)
            if mode == QPdfView.ZoomMode.Custom:
                size = QSizeF(points * res * view.zoomFactor()).toSize()
            elif mode == QPdfView.ZoomMode.FitToWidth:
                size = QSizeF(points * res).toSize()
                avail = viewport.width() - margins.left() - margins.right()
                factor = avail / max(1, size.width())
                size = QSize(round(size.width() * factor), round(size.height() * factor))
            else:  # FitInView
                avail = viewport.size() + QSize(-margins.left() - margins.right(), -spacing)
                size = QSizeF(points * res).toSize().scaled(avail, Qt.AspectRatioMode.KeepAspectRatio)
            sizes[page] = size
            total_width = max(total_width, size.width())
        total_width += margins.left() + margins.right()

        geometries: dict[int, QRect] = {}
        y = margins.top()
        for page in range(count):
            size = sizes[page]
            x = (max(total_width, viewport.width()) - size.width()) // 2
            geometries[page] = QRect(QPoint(x, y), size)
            y += size.height() + spacing
        return geometries

    def _scroll_offset(self) -> QPoint:
        return QPoint(self._view.horizontalScrollBar().value(), self._view.verticalScrollBar().value())

    def _page_rect_in_viewport(self, page: int) -> QRect | None:
        rect = self._page_geometries().get(page)
        if rect is None:
            return None
        offset = self._scroll_offset()
        return rect.translated(-offset.x(), -offset.y())

    def _page_at(self, pos: QPoint) -> tuple[int, QRect] | None:
        offset = self._scroll_offset()
        for page, rect in self._page_geometries().items():
            shifted = rect.translated(-offset.x(), -offset.y())
            if shifted.contains(pos):
                return page, shifted
        return None

    def _to_page_point(self, rect: QRect, page: int, pos: QPoint) -> QPointF:
        """Viewport-Pixel -> Seiten-Koordinaten in pt (auf die Seite begrenzt)."""
        points = self._document.pagePointSize(page)
        sx = points.width() / max(1, rect.width())
        sy = points.height() / max(1, rect.height())
        x = min(max((pos.x() - rect.x()) * sx, 0.0), points.width())
        y = min(max((pos.y() - rect.y()) * sy, 0.0), points.height())
        return QPointF(x, y)

    def _polygon_to_viewport(self, rect: QRect, page: int, polygon: QPolygonF) -> QPolygonF:
        points = self._document.pagePointSize(page)
        sx = rect.width() / max(1.0, points.width())
        sy = rect.height() / max(1.0, points.height())
        return QPolygonF([
            QPointF(rect.x() + polygon[i].x() * sx, rect.y() + polygon[i].y() * sy)
            for i in range(len(polygon))
        ])

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_PageDown:
            self.next_page()
        elif key == Qt.Key.Key_PageUp:
            self.previous_page()
        elif key == Qt.Key.Key_Plus and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_in()
        elif key == Qt.Key.Key_Minus and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_out()
        else:
            super().keyPressEvent(event)

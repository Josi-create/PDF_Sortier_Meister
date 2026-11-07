"""
Hauptfenster der PDF Sortier Meister Anwendung
"""

import logging
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QDate, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QDesktopServices
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QTabWidget,
    QLabel,
    QScrollArea,
    QFrame,
    QToolBar,
    QStatusBar,
    QFileDialog,
    QMessageBox,
    QGridLayout,
    QInputDialog,
    QApplication,
    QPushButton,
    QLineEdit,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QToolButton,
)

from src.utils.config import get_config
from src.utils.database import get_database
from src.gui.pdf_thumbnail import PDFThumbnailWidget
from src.gui.folder_tile import FolderTileWidget
from src.utils.timing import StepTimer
from src.gui.folder_widget import FolderWidget, REGENBOGEN_SCHWELLE
from src.gui.folder_tree_widget import FolderTreeWidget
from src.core.sortierung import SORT_OPTIONEN, sortiere_pfade, sortierung_id
from src.gui.tile_view import TILE_VIEWS, tile_view
from src.gui.rename_dialog import RenameDialog, RenameSuggestion, generate_rename_suggestions
from src.gui.detail_panel import DetailPanel
from src.utils.update_check import UpdateCheckError, UpdateInfo, check_for_update
from src.utils.pdf_open import OPEN_MODE_INTEGRATED, normalize_open_mode, open_pdf_externally
from src.gui.pdf_preview_window import PdfPreviewWindow
from src.gui.settings_dialog import SettingsDialog
from src.gui.setup_wizard import SetupWizard
from src.gui.korrespondent_sidebar import KorrespondentSidebar
from src.core.backup_reminder import is_question_due, macrium_last_backup, parse_date
from src.core.file_manager import FileManager, FolderManager, PapierkorbNichtVerfuegbar
from src.core.folder_naming import DEFAULT_TEMPLATE, build_folder_based_name, coerce_date


def _iso_to_date(value):
    """"JJJJ-MM-TT" -> date (None bei leer/unlesbar), Issue #132."""
    from datetime import date as _date

    if not value:
        return None
    try:
        return _date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
from src.core.pdf_cache import get_pdf_cache, PDFAnalysisResult
from src.core.pdf_analyzer import thumbnail_vergessen
from src.core.pdf_rotate import (
    DrehenNichtMoeglich,
    ausrichtung_zuruecknehmen,
    gegenrichtung,
    gerade_ausrichten,
    rotate_pdf,
)
from src.gui.ocr_neu_worker import OcrNeuWorker
from src.core import office_vorschau
from src.core.office_convert import endung_tauschen, ist_office_datei
from src.gui.office_convert_worker import OfficeConvertWorker, OfficeVorschauWorker
from src.gui.office_thumbnail import OfficeThumbnailWidget
from src.ml.classifier import get_classifier, Suggestion
from src.ml.hybrid_classifier import get_hybrid_classifier, source_folder_hint
from src.gui.chat_view import ChatView
from src.rag.bezug import Bezug
from src.gui.search_view import SearchView
from src.search.meldungen import melden as index_melden


class _ClickableLabel(QLabel):
    """QLabel, das bei Doppelklick ein Signal sendet (Statusleiste)."""

    doubleClicked = pyqtSignal()
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class _UpdateCheckThread(QThread):
    """Fragt im Hintergrund das neueste GitHub-Release ab (Issue #73)."""

    # (UpdateInfo | None, Fehlertext) - leerer Fehlertext = Pruefung ok
    result_ready = pyqtSignal(object, str)

    def __init__(self, current_version: str, parent=None):
        super().__init__(parent)
        self._current_version = current_version

    def run(self):
        try:
            info = check_for_update(self._current_version)
        except UpdateCheckError as e:
            self.result_ready.emit(None, str(e))
            return
        except Exception as e:  # noqa: BLE001 - Hintergrund-Thread darf nie crashen
            self.result_ready.emit(None, f"Unerwarteter Fehler: {e}")
            return
        self.result_ready.emit(info, "")


class MainWindow(QMainWindow):
    """Hauptfenster der Anwendung."""

    # Signal das gefeuert wird wenn alle Thumbnails geladen sind
    thumbnails_loaded = pyqtSignal()
    # (Generation, (erreichbar, Detail) | None) aus dem Pruef-Thread
    _llm_connection_checked = pyqtSignal(int, object)
    LLM_CHECK_INTERVAL_MS = 60_000

    def __init__(self):
        super().__init__()
        self.config = get_config()
        self.db = get_database()
        self.file_manager = FileManager()
        self.folder_manager = FolderManager()
        self.classifier = get_classifier()
        self.hybrid_classifier = get_hybrid_classifier()
        self.pdf_cache = get_pdf_cache()

        # UI-Elemente
        self.pdf_widgets: list[PDFThumbnailWidget] = []
        self.folder_widgets: list[FolderWidget] = []
        self.suggestion_widgets: list[FolderWidget] = []
        self.selected_pdf: Optional[Path] = None
        self.selected_pdf_text: Optional[str] = None
        self.selected_pdf_keywords: Optional[list[str]] = None
        self.selected_pdf_dates: Optional[list] = None
        self.selected_pdfs: list[Path] = []  # Mehrfachauswahl
        # Angezeigte Ordnervorschlaege der Auswahl (fuer den Chat, Issue #148)
        self._shown_suggestions: list = []

        # Undo-Historie für Verschiebe- und Umbenennungs-Aktionen
        # Move-Eintrag: {"type": "move", "moves": [(source, dest), ...], "description": str}
        # Rename-Eintrag: {"type": "rename", "old_path": Path, "new_path": Path, "description": str}
        # Loesch-Eintrag: {"type": "delete", "original": Path, "papierkorb": Path, "description": str}
        # Stapel-Eintrag: {"type": "stack", "backups": [(original, sicherung), ...], "description": str}
        self._undo_stack: list[dict] = []

        # Ordner-Navigations-Historie für Zurück-Button
        self._folder_history: list[Path] = []

        # Debounce-Timer: Raster-Spaltenzahl an Panelbreite anpassen (Issue #50)
        self._grid_relayout_timer = QTimer(self)
        self._grid_relayout_timer.setSingleShot(True)
        self._grid_relayout_timer.setInterval(150)
        self._grid_relayout_timer.timeout.connect(self._relayout_pdf_grid)
        self._grid_cols = 3
        self._folder_cols = 1  # Ordnerzeilen-Spalten (Issue #147)
        self.folder_tiles: list = []
        # Kachelgroesse im Scan-Bereich: Klein / Mittel / Gross (Issue #117)
        self._tile_view = tile_view(self.config.get("tile_view"))
        self._sortierung = sortierung_id(self.config.get("kachel_sortierung"))  # Issue #33

        self.setup_ui()
        self.setup_menu()
        self.setup_toolbar()
        self.setup_statusbar()
        self.load_settings()

        # PDF-Cache Signale verbinden
        self.pdf_cache.pdf_analyzed.connect(self._on_pdf_analyzed)
        self.pdf_cache.llm_suggestions_ready.connect(self._on_llm_suggestions_ready)
        # Aktivitaetsanzeige (Issue #68): solange die KI arbeitet, tickt die
        # Statusleiste sekuendlich mit laufender Uhr und Schaetzung.
        from src.core.llm_activity import get_llm_activity
        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(1000)
        self._activity_timer.timeout.connect(self._update_cache_status)
        get_llm_activity().changed.connect(self._on_llm_activity_changed)
        self.pdf_cache.llm_suggestions_failed.connect(self._on_llm_suggestions_failed)
        self._last_llm_error: Optional[tuple[str, str]] = None  # (pdf_name, fehler)
        self._llm_success_since_error = False  # seit dem letzten Fehler kam ein Erfolg
        # Wiederverwendetes Vorschau-Fenster (Issue #76), erst bei Bedarf erzeugt
        self._preview_window: Optional[PdfPreviewWindow] = None
        # "OCR neu durchführen" im Hintergrund (Issue #150)
        self._ocr_neu_worker: Optional[OcrNeuWorker] = None
        self._office_worker: Optional[OfficeConvertWorker] = None
        self._office_vorschau_worker: Optional[OfficeVorschauWorker] = None
        self._office_preview_pfad: Optional[Path] = None  # .docx/.xlsx, deren Seitenvorschau gewuenscht ist
        self._ocr_neu_paths: list[Path] = []
        # Laufende Hintergrund-Schreibvorgaenge (XMP-Metadaten) je Zielpfad
        self._pending_metadata_writes: dict[Path, "threading.Thread"] = {}

        # Initial laden
        QTimer.singleShot(100, self.initial_load)
        QTimer.singleShot(300, self._start_warmup)

    def setup_ui(self):
        """Initialisiert die Haupt-UI-Komponenten."""
        self.setWindowTitle("PDF Sortier Meister")
        self.setMinimumSize(800, 600)
        # Anzeige (maximiert oder gespeicherte Groesse) entscheidet load_settings()

        # Zentrales Widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Hauptlayout (vertikal: Filterleiste + Inhalt)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Filterleiste (initial ausgeblendet, Phase 18)
        self.filter_bar = self._create_filter_bar()
        main_layout.addWidget(self.filter_bar)

        # Center-Bereich: QTabWidget mit Tabs "Vorschau" + "Chat" (Phase 19)
        self.center_tabs = QTabWidget()
        main_layout.addWidget(self.center_tabs, 1)

        # Tab "Vorschau": der bisherige 3-Spalten-Splitter
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)

        # Splitter für flexible Größenanpassung
        splitter = QSplitter(Qt.Orientation.Horizontal)
        preview_layout.addWidget(splitter, 1)

        # Linke Spalte: PDF-Thumbnails
        pdf_panel = self.create_pdf_panel()
        splitter.addWidget(pdf_panel)

        # Mittlere Spalte: Detail-Panel (Umbenennung + Metadaten)
        self.detail_panel = DetailPanel()
        self.detail_panel.save_metadata_requested.connect(self._on_save_metadata_in_place)
        self.detail_panel.rename_and_save_metadata_requested.connect(self._on_rename_and_save_metadata)
        self.detail_panel.open_pdf_requested.connect(self.open_pdf)
        self.detail_panel.open_pdf_external_requested.connect(self.open_pdf_external)
        self.detail_panel.office_preview_requested.connect(self._on_office_preview_requested)
        self.detail_panel.enlarge_preview_requested.connect(self.show_preview_window)
        self.detail_panel.edit_pattern_requested.connect(self.open_filename_settings)
        # Aufteilung Details/Vorschau aus der letzten Sitzung wiederherstellen
        saved_sizes = self.config.get("detail_splitter_sizes") or []
        if (len(saved_sizes) == 2 and all(isinstance(v, int) and v > 0 for v in saved_sizes)):
            self.detail_panel.splitter.setSizes(saved_sizes)
        splitter.addWidget(self.detail_panel)

        # Rechte Spalte: Zielordner
        folder_panel = self.create_folder_panel()
        splitter.addWidget(folder_panel)

        # Splitter-Größenverhältnis fixieren (30/40/30%)
        splitter.setStretchFactor(0, 3)  # Links: 30%
        splitter.setStretchFactor(1, 4)  # Mitte: 40%
        splitter.setStretchFactor(2, 3)  # Rechts: 30%
        splitter.setSizes([300, 400, 300])
        # Beim Verschieben des Splitters die Raster-Spalten anpassen (Issue #50)
        splitter.splitterMoved.connect(lambda *_: self._grid_relayout_timer.start())

        self.center_tabs.addTab(preview_container, "Vorschau")
        self.center_tabs.setTabToolTip(
            0, "3-Spalten-Ansicht: PDF auswählen, Details prüfen, Zielordner anklicken"
        )

        # Tab "Chat": RAG-Chat (Phase 19 / M2)
        self.chat_view = ChatView(
            self.db,
            self.hybrid_classifier,
            self.config.get_chat_config(),
        )
        self.chat_view.open_pdf_requested.connect(self._open_pdf_external)
        self.chat_view.open_pdf_page_requested.connect(self._open_pdf_page)
        # Bezugsdokument (Issue #148): Text, KI-Metadaten, Ordnervorschlaege
        self.chat_view.bezug_daten = self._chat_bezug_daten
        self.center_tabs.addTab(self.chat_view, "Chat")
        self.center_tabs.setTabToolTip(1, "Fragen zu Ihren sortierten Dokumenten per KI beantworten lassen")

        # Tab "Suche": Volltextsuche im Index der Dokumentensuche (PDFsuche-Integration, Phase 4)
        self.search_view = SearchView(self.config)
        self.search_view.open_pdf_requested.connect(self.open_pdf)
        self.search_view.open_pdf_external_requested.connect(self.open_pdf_external)
        self.search_view.einrichten_requested.connect(lambda: self._open_settings_dialog(tab="Suche"))
        self.search_view.suche_fertig.connect(self._on_search_view_result)
        self.center_tabs.addTab(self.search_view, "Suche")
        self.center_tabs.setTabToolTip(
            2, "Volltextsuche in PDFs (auch gescannten), Office-Dateien, Markdown und Mails"
        )

        # LLM-Status bzw. Indexstand aktualisieren, wenn der Tab gewaehlt wird
        self.center_tabs.currentChanged.connect(self._on_center_tab_changed)

    def _on_center_tab_changed(self, index: int) -> None:
        """Aktualisiert den LLM-Status (Chat) bzw. den Indexstand (Suche), wenn der Tab sichtbar wird.

        Beim Wechsel in den Chat wird das ausgewaehlte PDF zum Bezugsdokument (Issue #148).
        """
        widget = self.center_tabs.widget(index)
        if widget is self.chat_view:
            self.chat_view.set_bezug(self._chat_bezug_pfad())
            self.chat_view.refresh_llm_status()
        elif widget is self.search_view:
            self.search_view.tab_gezeigt()

    def _chat_bezug_pfad(self) -> Optional[Path]:
        """Das ausgewaehlte PDF als Bezug fuer den Chat; bei Mehrfachauswahl keins."""
        if len(self.selected_pdfs) > 1:
            return None
        path = self.selected_pdf
        if path is None or not Path(path).exists():
            return None
        return Path(path)

    def _chat_bezug_daten(self, path: Path) -> Bezug:
        """Was die Oberflaeche zum Bezugsdokument schon weiss (Issue #148).

        Text und KI-Metadaten aus dem Analyse-Cache, die angezeigten
        Ordnervorschlaege (Sortierlogik inkl. KI-Zielordner) und die
        Zielordner. Der Chat liest zuerst den Suchindex und nimmt diese
        Werte nur, wo dort etwas fehlt.
        """
        path = Path(path)
        ist_auswahl = self.selected_pdf is not None and Path(self.selected_pdf) == path
        text = ""
        metadaten: dict = {}
        try:
            result = self.pdf_cache.get(path)
            if result is not None:
                text = result.extracted_text or ""
            for s in self.pdf_cache.get_llm_suggestions(path) or []:
                meta = getattr(s, "metadata", None)
                if isinstance(meta, dict) and meta:
                    metadaten = _bezug_metadaten(meta)
                    break
        except Exception as e:  # noqa: BLE001 - Zusatzdaten sind optional
            logging.getLogger(__name__).debug(f"Chat-Bezug ohne Cache-Daten: {e}")
        if not text and ist_auswahl:
            text = self.selected_pdf_text or ""
        vorschlaege: list[str] = []
        if ist_auswahl:
            for s in self._shown_suggestions:
                name = s.relative_path or s.folder_name
                angabe = f"{int(round(s.confidence * 100))} %"
                if s.reason:
                    angabe += f", {s.reason}"
                vorschlaege.append(f"{name} ({angabe})")
        return Bezug(
            pfad=path,
            text=text,
            metadaten=metadaten,
            sortier_vorschlaege=vorschlaege,
            wurzeln=list(self.folder_manager.target_folders),
        )

    def show_search_tab(self) -> None:
        """Wechselt auf den Reiter „Suche“ und setzt den Fokus ins Suchfeld (Strg+Umschalt+F)."""
        self.center_tabs.setCurrentWidget(self.search_view)
        self.search_view.fokus()

    def _open_pdf_external(self, file_path: str) -> None:
        """Oeffnet eine PDF aus dem Chat (Zitat-Link) - je nach Einstellung."""
        if not file_path:
            return
        self.open_pdf(Path(file_path))

    def _open_pdf_page(self, file_path: str, seite: int) -> None:
        """Zitat mit Seite (Phase 5): die integrierte Vorschau springt auf die Fundstelle."""
        if not file_path:
            return
        self.open_pdf(Path(file_path), seite=seite)

    # ------------------------------------------------------------------ #
    # PDF oeffnen / Vorschau (Issues #74, #76)
    # ------------------------------------------------------------------ #

    def open_pdf(self, pdf_path: Path, seite: int | None = None) -> None:
        """Oeffnet eine PDF so, wie es in den Einstellungen gewaehlt ist.

        Default ist die integrierte Vorschau (QtPdf, schnell); alternativ das
        Standardprogramm des Systems oder ein eigenes Programm (PDF-XChange, ...).
        ``seite`` (1-basiert) springt in der integrierten Vorschau auf die Fundstelle.
        """
        pdf_path = Path(pdf_path)
        mode = normalize_open_mode(self.config.get("pdf_open_mode"))
        if mode == OPEN_MODE_INTEGRATED:
            self.show_preview_window(pdf_path, seite)
        else:
            self.open_pdf_external(pdf_path)

    def open_pdf_external(self, pdf_path: Path) -> None:
        """Oeffnet eine PDF ausserhalb der App (Standard- oder eigenes Programm)."""
        mode = normalize_open_mode(self.config.get("pdf_open_mode"))
        command = self.config.get("pdf_open_command", "") or ""
        ok, note = open_pdf_externally(Path(pdf_path), mode, command)
        if note:
            self.statusbar.showMessage(note, 6000)
        if not ok:
            QMessageBox.warning(self, "PDF öffnen", note)

    def show_preview_window(self, pdf_path: Path, seite: int | None = None) -> None:
        """Zeigt die PDF im (wiederverwendeten) Vorschau-Fenster, optional direkt auf ``seite``."""
        if self._preview_window is None:
            self._preview_window = PdfPreviewWindow(
                self, geometry=self.config.get("preview_window_geometry") or None
            )
            self._preview_window.open_external_requested.connect(self.open_pdf_external)
            self._preview_window.geometry_changed.connect(self._on_preview_geometry_changed)
            self._preview_window.apply_text_requested.connect(self._on_preview_window_text_applied)
        self._preview_window.show_pdf(Path(pdf_path), seite)

    def _on_preview_window_text_applied(self, field_key: str, text: str) -> None:
        """Markierter Text aus dem grossen Vorschau-Fenster -> Metadaten-Feld (Issue #109).

        Nur, wenn das Fenster dieselbe PDF zeigt wie das Detail-Panel - sonst
        landete der Text bei einem anderen Dokument.
        """
        shown = self._preview_window.current_path() if self._preview_window else None
        selected = self.detail_panel.get_current_pdf()
        if shown is None or selected is None or Path(shown) != Path(selected):
            self.statusbar.showMessage(
                "Die Vorschau zeigt nicht die ausgewählte PDF - Text nicht übernommen.", 5000
            )
            return
        self.detail_panel.apply_preview_text(field_key, text)

    def _on_preview_geometry_changed(self, geometry: list) -> None:
        self.config.set("preview_window_geometry", list(geometry))

    def create_pdf_panel(self) -> QWidget:
        """Erstellt das Panel für die PDF-Anzeige."""
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Header mit Ordnerpfad und Navigation
        header_layout = QHBoxLayout()

        # Zurück-Button (vorheriger Ordner)
        self.navigate_back_btn = QPushButton("⬅")
        self.navigate_back_btn.setFixedSize(28, 28)
        self.navigate_back_btn.setToolTip("Zurück zum vorherigen Ordner (Alt+Left)")
        self.navigate_back_btn.clicked.connect(self.on_navigate_back)
        self.navigate_back_btn.setEnabled(False)
        header_layout.addWidget(self.navigate_back_btn)

        # Nach-oben-Button (ein Verzeichnis höher)
        self.navigate_up_btn = QPushButton("⬆")
        self.navigate_up_btn.setFixedSize(28, 28)
        self.navigate_up_btn.setToolTip("Ein Verzeichnis nach oben (Alt+Up)")
        self.navigate_up_btn.clicked.connect(self.on_navigate_up)
        header_layout.addWidget(self.navigate_up_btn)

        # Überschrift mit Ordnerpfad
        self.pdf_header = QLabel("Neue PDFs im Scan-Ordner")
        self.pdf_header.setStyleSheet("font-size: 14px; font-weight: bold; padding: 5px;")
        header_layout.addWidget(self.pdf_header)
        header_layout.addStretch()

        # Anzahl der PDFs im Ordner
        self.pdf_folder_count_label = QLabel("")
        self.pdf_folder_count_label.setStyleSheet(
            "color: #888; font-size: 12px; padding: 5px;"
        )
        header_layout.addWidget(self.pdf_folder_count_label)

        # Kachelgroesse wie im Explorer umschalten (Issue #117)
        self.tile_view_combo = QComboBox()
        for view in TILE_VIEWS:
            self.tile_view_combo.addItem(view.label, view.id)
        self.tile_view_combo.setCurrentIndex(self.tile_view_combo.findData(self._tile_view.id))
        self.tile_view_combo.setToolTip(
            "Größe der Kacheln im Scan-Bereich.\n"
            "Bei kleinen und mittleren Kacheln zeigt der Mauszeiger auf einer PDF\n"
            "kurz darauf die große Vorschau."
        )
        self.tile_view_combo.currentIndexChanged.connect(self._on_tile_view_combo_changed)
        view_label = QLabel("Ansicht:")
        view_label.setStyleSheet("color: #888; font-size: 12px;")
        header_layout.addWidget(view_label)
        header_layout.addWidget(self.tile_view_combo)

        # Sortierung der Kacheln (Issue #33)
        self.sort_combo = QComboBox()
        for sid, text, _kriterium, _ab in SORT_OPTIONEN:
            self.sort_combo.addItem(text, sid)
        self.sort_combo.setCurrentIndex(self.sort_combo.findData(self._sortierung))
        self.sort_combo.setToolTip("Reihenfolge der Dateien im Scan-Bereich.")
        self.sort_combo.currentIndexChanged.connect(self._on_sort_combo_changed)
        sort_label = QLabel("Sortieren:")
        sort_label.setStyleSheet("color: #888; font-size: 12px;")
        header_layout.addWidget(sort_label)
        header_layout.addWidget(self.sort_combo)

        layout.addLayout(header_layout)

        # Breadcrumb: klickbarer Pfad zum aktuellen Scan-Ordner (Explorer-Gefuehl)
        self.breadcrumb_layout = QHBoxLayout()
        self.breadcrumb_layout.setContentsMargins(6, 0, 6, 2)
        self.breadcrumb_layout.setSpacing(2)
        self.breadcrumb_layout.addStretch()
        layout.addLayout(self.breadcrumb_layout)

        # Info-Label für leeren Ordner
        self.empty_label = QLabel(
            "Kein Scan-Ordner ausgewählt.\n\n"
            "Klicken Sie auf 'Scan-Ordner' in der Werkzeugleiste,\n"
            "um einen Ordner mit PDFs auszuwählen."
        )
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #666; padding: 40px;")
        layout.addWidget(self.empty_label)

        # Scroll-Bereich für PDF-Thumbnails
        self.pdf_scroll_area = QScrollArea()
        self.pdf_scroll_area.setWidgetResizable(True)
        self.pdf_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        # Container für Ordnerzeilen und Thumbnails
        self.pdf_container = QWidget()
        self.pdf_container.mousePressEvent = self._on_pdf_container_clicked
        container_layout = QVBoxLayout(self.pdf_container)
        container_layout.setSpacing(10)
        # Ordner als Zeilen (Issue #147): eigenes Raster mit 1 oder 2 Spalten
        # ueber den PDF-Kacheln; Hoehe und Schrift unabhaengig von der
        # Kachelgroesse (#117)
        self.folder_rows_layout = QGridLayout()
        self.folder_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.folder_rows_layout.setHorizontalSpacing(8)
        self.folder_rows_layout.setVerticalSpacing(3)
        container_layout.addLayout(self.folder_rows_layout)
        self.pdf_layout = QGridLayout()
        self.pdf_layout.setContentsMargins(0, 0, 0, 0)
        self.pdf_layout.setSpacing(10)
        self.pdf_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        container_layout.addLayout(self.pdf_layout)
        container_layout.addStretch(1)

        self.pdf_scroll_area.setWidget(self.pdf_container)
        self.pdf_scroll_area.hide()  # Anfangs versteckt
        layout.addWidget(self.pdf_scroll_area)

        return panel

    def create_folder_panel(self) -> QWidget:
        """Erstellt das Panel für die Zielordner und Korrespondenten (Phase 20).

        Inhalt:
            * Kopfzeile (Titel + Buttons)
            * Vorschlagsbereich
            * Trennlinie
            * QTabWidget mit zwei Tabs:
                - "Zielordner"   -> FolderTreeWidget (bisheriges Verhalten)
                - "Korrespondenten" -> KorrespondentSidebar (Phase 20)
        """
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Überschrift mit Buttons
        header_layout = QHBoxLayout()
        header = QLabel("Zielordner & Korrespondenten")
        header.setStyleSheet("font-size: 14px; font-weight: bold; padding: 5px;")
        header_layout.addWidget(header)
        header_layout.addStretch()

        # Button: Zielordner hinzufügen
        add_folder_btn = QPushButton("+ Hinzufügen")
        add_folder_btn.setToolTip("Neuen Zielordner hinzufügen")
        add_folder_btn.setStyleSheet("padding: 3px 8px;")
        add_folder_btn.clicked.connect(self.add_target_folder)
        header_layout.addWidget(add_folder_btn)

        # Button: Zielordner neu aufbauen
        rebuild_btn = QPushButton("↻ Neu laden")
        rebuild_btn.setToolTip("Zielordner-Ansicht neu aufbauen (Lerninhalte bleiben erhalten)")
        rebuild_btn.setStyleSheet("padding: 3px 8px;")
        rebuild_btn.clicked.connect(self.rebuild_folder_view)
        header_layout.addWidget(rebuild_btn)

        # Button: Zielordner-Ansicht leeren
        clear_btn = QPushButton("🗑 Leeren")
        clear_btn.setToolTip("Zielordner-Ansicht leeren (Lerninhalte bleiben erhalten)")
        clear_btn.setStyleSheet("padding: 3px 8px;")
        clear_btn.clicked.connect(self.clear_folder_view)
        header_layout.addWidget(clear_btn)

        layout.addLayout(header_layout)

        # Vorschläge-Bereich
        self.suggestions_label = QLabel("Vorgeschlagene Ziele:")
        self.suggestions_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(self.suggestions_label)

        self.suggestions_container = QWidget()
        self.suggestions_layout = QHBoxLayout(self.suggestions_container)
        self.suggestions_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.suggestions_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.suggestions_container)

        # Platzhalter wenn keine Vorschläge
        self.no_suggestions_label = QLabel("Wählen Sie eine PDF aus für Vorschläge")
        self.no_suggestions_label.setStyleSheet("color: #999; font-style: italic; padding: 10px;")
        self.suggestions_layout.addWidget(self.no_suggestions_label)

        # Trennlinie
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # Tab-Widget: Zielordner + Korrespondenten (Phase 20 / Issue #21)
        self.right_panel_tabs = QTabWidget()
        self.right_panel_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.right_panel_tabs.setStyleSheet("QTabBar::tab { padding: 4px 10px; }")

        # --- Tab "Zielordner" (bisheriges Verhalten) ---
        folder_tree_container = QWidget()
        ft_layout = QVBoxLayout(folder_tree_container)
        ft_layout.setContentsMargins(0, 0, 0, 0)
        ft_layout.setSpacing(0)

        # NEU: Ordner-Baumansicht für hierarchische Struktur
        self.folder_tree = FolderTreeWidget()
        self.folder_tree.folder_selected.connect(self.on_tree_folder_selected)
        self.folder_tree.folder_double_clicked.connect(self.on_tree_folder_double_clicked)
        self.folder_tree.pdf_dropped.connect(self.on_pdf_dropped_on_folder)
        self.folder_tree.folder_removed.connect(self.on_folder_remove)
        self.folder_tree.move_here_requested.connect(self.on_tree_folder_selected)  # Issue #93
        self.folder_tree.folder_renamed.connect(self.on_tree_folder_renamed)
        self.folder_tree.status_message.connect(lambda t: self.statusbar.showMessage(t, 8000))
        self.folder_tree.has_pdf_selection = lambda: bool(self.selected_pdf or self.selected_pdfs)
        ft_layout.addWidget(self.folder_tree, stretch=1)

        # Alte Grid-Ansicht (ausgeblendet, für Kompatibilität)
        self.folder_container = QWidget()
        self.folder_layout = QGridLayout(self.folder_container)
        self.folder_layout.setSpacing(10)
        self.folder_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.folder_container.hide()  # Grid-Ansicht versteckt
        ft_layout.addWidget(self.folder_container)

        self.right_panel_tabs.addTab(folder_tree_container, "Zielordner")
        self.right_panel_tabs.setTabToolTip(
            0, "Zielordner-Baum: hier klicken, um die ausgewählte PDF zu verschieben"
        )

        # --- Tab "Korrespondenten" (Phase 20 / Issue #21) ---
        self.korrespondent_sidebar = KorrespondentSidebar(self.db, parent=self)
        self.korrespondent_sidebar.korrespondent_selected.connect(
            self._on_korrespondent_sidebar_selected
        )
        self.right_panel_tabs.addTab(self.korrespondent_sidebar, "Korrespondenten")
        self.right_panel_tabs.setTabToolTip(
            1, "Bekannte Korrespondenten - anklicken filtert die Dokumente danach"
        )

        layout.addWidget(self.right_panel_tabs, stretch=1)

        return panel

    def _on_korrespondent_sidebar_selected(self, name_or_none) -> None:
        """Wird aufgerufen, wenn in der Korrespondenten-Sidebar ein Eintrag
        angeklickt wird. Setzt den Korrespondent-Filter in der Filterleiste
        und loest eine Suche aus.

        Args:
            name_or_none: Name des Korrespondenten oder ``None`` fuer "Alle".
        """
        if not hasattr(self, "filter_korrespondent"):
            return
        # Filter-Dropdown aktualisieren
        self.filter_korrespondent.blockSignals(True)
        if name_or_none is None:
            # "Alle" -> ersten Eintrag
            self.filter_korrespondent.setCurrentIndex(0)
        else:
            # Dropdown neu befuellen, falls der Name fehlt
            current = self.filter_korrespondent.currentText()
            items = [self.filter_korrespondent.itemText(i)
                     for i in range(self.filter_korrespondent.count())]
            if name_or_none not in items:
                self.filter_korrespondent.addItem(name_or_none)
            idx = self.filter_korrespondent.findText(name_or_none)
            if idx >= 0:
                self.filter_korrespondent.setCurrentIndex(idx)
            else:
                self.filter_korrespondent.setCurrentIndex(0)
        self.filter_korrespondent.blockSignals(False)
        # Suche ausloesen
        if hasattr(self, "_execute_search"):
            self._execute_search()
        # Statusmeldung
        if name_or_none:
            self.statusbar.showMessage(
                f"Filter: Korrespondent '{name_or_none}'", 3000
            )
        else:
            self.statusbar.showMessage("Filter aufgehoben (Alle)", 2000)

    def _check_automation_rules(self, pdf_path: Path, metadata: dict = None) -> None:
        """Phase 21: Prueft Automatisierungs-Regeln VOR dem Verschieben.

        Wenn eine Regel mit hoher Konfidenz (>= 0.9) und target_folder-Aktion
        matcht, wird der Zielordner als Vorschlag im Statusbar angezeigt
        (KEIN Auto-Move ohne User-Bestaetigung in v1).
        """
        try:
            from src.utils.database import get_database
            from src.core.rule_engine import RuleEngine

            db = get_database()
            engine = RuleEngine(db)
            md = dict(metadata or {})
            md.setdefault("dateiname", pdf_path.name)
            matches = engine.evaluate(md)
            if matches:
                top = matches[0]
                folders = []
                for a in top.matched_actions:
                    if a.get("type") == "target_folder":
                        tmpl = a.get("template", "")
                        try:
                            resolved = engine.apply_actions([a], md).get(
                                "target_folder", tmpl
                            )
                        except Exception:
                            resolved = tmpl
                        folders.append(resolved)
                if folders:
                    self.statusbar.showMessage(
                        f"Regel '{top.rule['name']}' wuerde vorschlagen: "
                        f"{', '.join(folders)}",
                        5000,
                    )
        except Exception:
            pass

    def _auto_collect_korrespondenten(self) -> None:
        """Phase 20: Sammelt Korrespondenten aus der Sortierhistorie
        in die Verwaltungstabelle und refresht die Sidebar.

        Wird nach jedem PDF-Move aufgerufen. Idempotent: bereits
        vorhandene Korrespondenten werden nicht doppelt angelegt.
        Wir cachen den letzten Collection-Status (pro Session), um
        in schnellen Bulk-Moves nicht jedes Mal die DB zu scannen.
        """
        if not hasattr(self, "_auto_collect_done"):
            self._auto_collect_done = False
        if self._auto_collect_done:
            return
        try:
            new_count = self.db.auto_collect_from_history()
            if new_count > 0 and hasattr(self, "korrespondent_sidebar"):
                self.korrespondent_sidebar.refresh()
            # Nach dem ersten Sammeln pro Session sind alle
            # bisherigen Korrespondenten erfasst; neue Moves
            # fuegen nur weitere hinzu (was auto_collect_from_history
            # ebenfalls korrekt behandelt). Wir setzen den Flag
            # NICHT permanent, damit z.B. nach einem
            # historisch-Import die Liste neu befuellt wird.
        except Exception as e:
            print(f"Auto-Collect Korrespondenten Warnung: {e}")

    def initial_load(self):
        """Lädt die initialen Daten nach dem Start."""
        # Scan-Ordner laden
        scan_folder = self.config.get_scan_folder()
        if scan_folder and scan_folder.exists():
            self.file_manager.set_scan_folder(scan_folder)
            self.load_pdfs()

        # Zielordner laden
        target_folders = self.config.get_target_folders()
        self.folder_manager.load_folders(target_folders)
        self.load_folders()

    def load_pdfs(self):
        """Lädt die PDFs aus dem Scan-Ordner."""
        # Alte Widgets aus beiden Rastern entfernen (Ordnerzeilen, PDFs)
        for grid in (self.folder_rows_layout, self.pdf_layout):
            while grid.count():
                item = grid.takeAt(0)
                if item.widget():
                    item.widget().cleanup() if hasattr(item.widget(), 'cleanup') else None
                    item.widget().deleteLater()
        self.pdf_widgets.clear()
        self.folder_tiles = []

        # PDFs und Unterordner laden (Explorer-Gefuehl, Issue #29)
        pdf_files = self.file_manager.get_pdf_files()
        office_files = self.file_manager.get_office_files()
        scan_folder = self.file_manager.scan_folder
        subfolders = self.folder_manager.get_subfolders(scan_folder) if scan_folder else []
        parent_folder = None
        if scan_folder and scan_folder.parent != scan_folder and scan_folder.parent.exists():
            parent_folder = scan_folder.parent
        self._update_breadcrumb(scan_folder)

        if not pdf_files and not office_files and not subfolders and parent_folder is None:
            self.empty_label.setText(
                "Keine PDFs im Scan-Ordner gefunden.\n\n"
                f"Ordner: {self.file_manager.scan_folder}"
            )
            self.empty_label.show()
            self.pdf_scroll_area.hide()
            self.pdf_count_label.setText("PDFs: 0")
            self.pdf_folder_count_label.setText("0 Dateien")
            return

        self.empty_label.hide()
        self.pdf_scroll_area.show()

        # Header aktualisieren
        self.pdf_header.setText(f"PDFs in: {self.file_manager.scan_folder.name}")
        self.pdf_header.setToolTip(str(self.file_manager.scan_folder))
        count = len(pdf_files) + len(office_files)
        count_text = f"{count} {'Datei' if count == 1 else 'Dateien'}"
        if subfolders:
            count_text += f" · {len(subfolders)} {'Ordner' if len(subfolders) == 1 else 'Ordner'}"
        self.pdf_folder_count_label.setText(count_text)

        # Ordnerzeilen zuerst (".." und Unterordner, Issue #147), darunter die PDFs
        self._grid_cols = self._pdf_grid_columns()
        self._folder_cols = self._folder_grid_columns()
        tile_folders = ([(parent_folder, True)] if parent_folder else []) + [
            (f, False) for f in subfolders
        ]
        for folder, is_parent in tile_folders:
            tile = FolderTileWidget(
                folder,
                pdf_count=None if is_parent else self.folder_manager.count_pdfs(folder),
                is_parent=is_parent,
            )
            tile.double_clicked.connect(self.on_folder_tile_double_clicked)
            if is_parent:
                # Die ".."-Zeile wirkt wie eine Schaltflaeche -> Einfachklick (Issue #50)
                tile.clicked.connect(self.on_parent_tile_clicked)
            tile.pdf_dropped.connect(self.on_pdf_dropped_on_folder)
            self.folder_tiles.append(tile)
        self._place_folder_rows()

        if not pdf_files:
            self._add_office_widgets(office_files, 0)
            self.pdf_count_label.setText("PDFs: 0")
            self._pending_thumbnails = 0
            self._thumbnails_signal_emitted = True
            self.thumbnails_loaded.emit()
            self._schedule_pre_caching([])
            return

        # Thumbnail-Ladetracking initialisieren
        self._pending_thumbnails = len(pdf_files)
        self._thumbnails_signal_emitted = False

        # Widgets erstellen
        for i, pdf_path in enumerate(pdf_files):
            widget = PDFThumbnailWidget(pdf_path, view=self._tile_view)
            widget.clicked.connect(self.on_pdf_clicked)
            widget.ctrl_clicked.connect(self.on_pdf_ctrl_clicked)
            widget.shift_clicked.connect(self.on_pdf_shift_clicked)
            widget.double_clicked.connect(self.on_pdf_double_clicked)
            widget.open_requested.connect(self.open_pdf)
            widget.rename_requested.connect(self.on_pdf_rename)
            widget.delete_requested.connect(self.on_pdf_delete)
            widget.move_requested.connect(self.on_pdf_move)
            widget.copy_requested.connect(self.on_pdf_copy)
            widget.batch_rename_requested.connect(self.on_batch_rename)
            widget.split_requested.connect(self.on_pdf_split)
            widget.merge_requested.connect(self.on_pdf_merge)
            widget.stack_requested.connect(self.on_pdf_stacked)
            widget.rotate_requested.connect(self.on_pdf_rotate)
            widget.reocr_requested.connect(self.on_pdf_reocr)
            widget.straighten_requested.connect(self.on_pdf_straighten)
            # Thumbnail-Ladetracking
            widget.thumbnail_ready.connect(self._on_thumbnail_loaded)
            # Gruen, wenn schon ein KI-Vorschlag im Cache liegt (Issue #81)
            widget.has_ai_suggestion = self.pdf_cache.has_llm_suggestions(pdf_path)

            self.pdf_layout.addWidget(widget, i // self._grid_cols, i % self._grid_cols)
            self.pdf_widgets.append(widget)

        self._add_office_widgets(office_files, len(pdf_files))

        # Falls keine PDFs, Signal sofort senden
        if self._pending_thumbnails == 0:
            self.thumbnails_loaded.emit()
            self._thumbnails_signal_emitted = True

        self._sortiere_kacheln()

        # Statusleiste aktualisieren
        self.pdf_count_label.setText(f"PDFs: {len(pdf_files)}")
        self.statusbar.showMessage(f"{len(pdf_files)} PDFs geladen", 3000)

        # Pre-Caching starten: PDFs im Hintergrund analysieren
        # Verzögert starten damit UI erstmal fertig geladen wird
        self._schedule_pre_caching(pdf_files)

    @property
    def office_widgets(self) -> list[OfficeThumbnailWidget]:
        """Die Kacheln der .docx/.xlsx (sie stehen mit den PDFs in ``pdf_widgets``, Issue #9)."""
        return [w for w in self.pdf_widgets if isinstance(w, OfficeThumbnailWidget)]

    def _add_office_widgets(self, office_files: list[Path], start_index: int):
        """Kacheln fuer .docx/.xlsx hinter den PDFs im Raster (Issue #9).

        Sie nutzen dieselben Signale und Wege wie PDF-Kacheln (Auswahl,
        Vorschlaege, Verschieben, Ziehen); Stapeln, Drehen, OCR usw. gibt es
        nur bei PDFs.
        """
        for j, pfad in enumerate(office_files):
            widget = OfficeThumbnailWidget(pfad, view=self._tile_view)
            widget.clicked.connect(self.on_pdf_clicked)
            widget.ctrl_clicked.connect(self.on_pdf_ctrl_clicked)
            widget.shift_clicked.connect(self.on_pdf_shift_clicked)
            widget.double_clicked.connect(self.open_office_file)
            widget.open_requested.connect(self.open_office_file)
            widget.move_requested.connect(self.on_pdf_move)
            widget.delete_requested.connect(self.on_office_delete)
            widget.convert_requested.connect(self.on_office_convert)
            widget.selected = pfad == self.selected_pdf or pfad in self.selected_pdfs
            i = start_index + j
            self.pdf_layout.addWidget(widget, i // self._grid_cols, i % self._grid_cols)
            self.pdf_widgets.append(widget)

    def _on_office_preview_requested(self, pfad: Path):
        """Das Detail-Panel zeigt eine .docx/.xlsx: Seitenvorschau im Hintergrund erzeugen."""
        self._office_preview_pfad = pfad
        self._start_office_vorschau()

    def _start_office_vorschau(self):
        """Erzeugt die gewuenschte Vorschau; es laeuft hoechstens eine Umwandlung zugleich."""
        if self._office_vorschau_worker is not None or self._office_preview_pfad is None:
            return
        worker = OfficeVorschauWorker(self._office_preview_pfad, self)
        worker.fertig.connect(self._on_office_vorschau)
        self._office_vorschau_worker = worker
        worker.start()

    def _on_office_vorschau(self, pfad: Path, pdf, fehler):
        self._office_vorschau_worker = None
        if self._office_preview_pfad is None:
            return
        if self._office_preview_pfad != pfad:
            self._start_office_vorschau()  # inzwischen eine andere Datei gewuenscht
            return
        if self.selected_pdf != pfad:
            return  # inzwischen etwas anderes ausgewaehlt
        if pdf is not None:
            self.detail_panel.preview.load_pdf(pdf)
        else:
            self.detail_panel.preview.show_message(f"Vorschau nicht möglich:\n{fehler}")

    def on_office_delete(self, pfad: Path):
        """Kontextmenue "Loeschen" einer .docx/.xlsx (gleicher Weg und gleiche Rueckfrage wie bei PDFs)."""
        self._datei_loeschen(pfad, "Datei löschen", "diese Datei", self._remove_office_widget)

    def _remove_office_widget(self, pfad: Path):
        was_selected = self.selected_pdf == pfad
        self.remove_pdf_widget(pfad)
        if was_selected:
            self.detail_panel.clear()
        office_vorschau.vorschau_loeschen(pfad)
        self._relayout_pdf_grid(force=True)

    def open_office_file(self, pfad: Path):
        """Oeffnet eine .docx/.xlsx im Standardprogramm."""
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(pfad))):
            QMessageBox.warning(self, "Öffnen", f"Datei konnte nicht geöffnet werden:\n{pfad}")

    def on_office_convert(self, pfad: Path, pdfa: bool):
        """Kontextmenue "In PDF umwandeln": Hintergrund-Thread, PDF entsteht neben der Datei."""
        if self._office_worker is not None:
            self.statusbar.showMessage("Eine Umwandlung läuft noch - bitte warten.", 4000)
            return
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        self.statusbar.showMessage(f"Wandle in PDF um: {pfad.name}…")
        worker = OfficeConvertWorker([pfad], pdfa, self)
        worker.fertig.connect(self._on_office_converted)
        self._office_worker = worker
        worker.start()

    def _on_office_converted(self, ergebnisse: list):
        self._office_worker = None
        QApplication.restoreOverrideCursor()
        fehler = []
        hinweise = []
        erzeugt = []
        for quelle, erg, fehlertext in ergebnisse:
            if erg is None:
                fehler.append(f"{quelle.name}: {fehlertext}")
                continue
            erzeugt.append(erg.pdf)
            index_melden("datei_aufnehmen", str(erg.pdf))
            hinweise.extend(f"{quelle.name}: {h}" for h in erg.hinweise)
            self.statusbar.showMessage(
                f"PDF erstellt ({erg.werkzeug}{', PDF/A' if erg.pdfa else ''}): {erg.pdf.name}", 6000
            )
        if erzeugt:
            self.load_pdfs()
            # Das neue PDF wie angeklickt auswaehlen (load_pdfs baut die Kacheln synchron)
            widget = self._pdf_widget_for(erzeugt[0])
            if widget is not None:
                self.on_pdf_clicked(erzeugt[0])
                self.pdf_scroll_area.ensureWidgetVisible(widget)
        if fehler:
            QMessageBox.warning(self, "In PDF umwandeln", "\n".join(fehler))
        elif hinweise:
            QMessageBox.information(self, "In PDF umwandeln", "\n".join(hinweise))

    def _schedule_pre_caching(self, pdf_files: list[Path], delay_ms: int = 500):
        """Startet das Pre-Caching verzoegert ueber einen fenstergebundenen Timer.

        Ein freies QTimer.singleShot(lambda) wuerde auch nach dem Schliessen des
        Fensters noch feuern und auf geloeschte Widgets zugreifen.
        """
        if not hasattr(self, "_precache_timer"):
            self._precache_timer = QTimer(self)
            self._precache_timer.setSingleShot(True)
            self._precache_timer.timeout.connect(
                lambda: self._start_pre_caching(self._precache_pending or [])
            )
        self._precache_pending = list(pdf_files)
        self._precache_timer.start(delay_ms)

    def _start_pre_caching(self, pdf_files: list[Path]):
        """Startet das Pre-Caching für alle PDFs im Hintergrund."""
        analysis_n, llm_n = self.pdf_cache.pre_cache(pdf_files)
        self._update_cache_status()
        if analysis_n:
            self.statusbar.showMessage(f"Analysiere {analysis_n} PDFs im Hintergrund...", 2000)
        elif llm_n:
            self.statusbar.showMessage(f"Hole KI-Vorschläge für {llm_n} PDFs im Hintergrund...", 2000)

    def _precache_progress(self) -> tuple[int, int, int]:
        """Liefert (analysiert, mit KI-Vorschlägen, gesamt) für die geladenen PDFs."""
        total = analyzed = llm_done = 0
        for widget in self.pdf_widgets:
            total += 1
            result = self.pdf_cache.get(widget.pdf_path)
            if result:
                analyzed += 1
                if result.llm_fetched:
                    llm_done += 1
        return analyzed, llm_done, total

    def _on_llm_activity_changed(self):
        """KI-Aufruf hat begonnen oder geendet: Uhr starten/stoppen."""
        from src.core.llm_activity import get_llm_activity
        if get_llm_activity().is_busy():
            if not self._activity_timer.isActive():
                self._activity_timer.start()
        else:
            self._activity_timer.stop()
        self._update_cache_status()

    def _update_cache_status(self):
        """Aktualisiert die Fortschrittsanzeige der Hintergrund-Analyse."""
        from src.core.llm_activity import get_llm_activity
        activity = get_llm_activity()
        analyzed, llm_done, total = self._precache_progress()
        parts = []
        if total > 0:
            if analyzed < total:
                parts.append(f"Durchsuche PDFs… {analyzed}/{total}")
            llm_active = (
                self.hybrid_classifier.is_llm_available()
                and self.config.get("llm_precache_enabled", True)
            )
            if llm_active and llm_done < total:
                parts.append(f"KI verschlagwortet Ihre PDFs… {llm_done}/{total} abgeschlossen")
        # Laufender KI-Aufruf (Pre-Cache, Metadaten, Chat): Uhr + Schaetzung (Issue #68)
        jobs = activity.jobs()
        if jobs:
            job = jobs[0]
            label = f" „{job.label}“" if job.label else ""
            parts.append(f"KI arbeitet{label} {activity.describe()}")
        if self._last_llm_error:
            name, error = self._last_llm_error
            parts.append("⚠ KI-Fehler (Doppelklick)")
            self.cache_status_label.setToolTip(
                f"Letzter KI-Fehler bei „{name}“:\n{error}\n\n"
                "Doppelklick zeigt Details und öffnet die Log-Datei."
            )
        else:
            self.cache_status_label.setToolTip("Doppelklick zeigt Details zur Hintergrund-Analyse.")
        self.cache_status_label.setText(" | ".join(parts))

    def _on_llm_suggestions_ready(self, pdf_path: Path):
        """KI-Vorschläge für eine PDF wurden abgerufen (Cache-Signal)."""
        self._clear_llm_error_if_recovered(pdf_path)
        self._set_llm_reachable(True)
        self._update_cache_status()
        self._mark_thumbnail_ai_suggestion(pdf_path)
        self._refresh_detail_panel_after_llm(pdf_path)

    def _mark_thumbnail_ai_suggestion(self, pdf_path: Path):
        """Hinterlegt die Kachel der PDF gruen, sobald ein KI-Vorschlag da ist (Issue #81)."""
        for widget in self.pdf_widgets:
            if widget.pdf_path == pdf_path:
                widget.has_ai_suggestion = self.pdf_cache.has_llm_suggestions(pdf_path)
                break

    def _clear_llm_error_if_recovered(self, pdf_path: Path):
        """Setzt „KI-Fehler“ zurück, wenn der Fehler behoben ist.

        Behoben heißt: die betroffene PDF hat jetzt ein Ergebnis, oder der
        Pre-Cache-Lauf ist zu Ende und nach dem Fehler kamen nur noch Erfolge
        (z.B. weil der Provider auf einen Rückfall umgeschaltet hat).
        """
        if not self._last_llm_error:
            return
        self._llm_success_since_error = True
        failed_name = self._last_llm_error[0]
        run_finished = self.pdf_cache.llm_pending_count() == 0
        if pdf_path.name == failed_name or run_finished:
            self._last_llm_error = None
            self._llm_success_since_error = False

    def _refresh_detail_panel_after_llm(self, pdf_path: Path) -> bool:
        """Traegt frische KI-Vorschlaege ins Detail-Panel ein, wenn die PDF
        gerade ausgewaehlt ist und der Nutzer dort noch nichts geaendert hat.

        Vorher blieb das Panel auf dem Stand von vor der KI-Abfrage stehen; man
        musste eine andere PDF und dann wieder diese anklicken.

        Returns:
            True, wenn das Panel aktualisiert wurde.
        """
        if self.selected_pdf != pdf_path or self.selected_pdfs:
            return False
        panel = getattr(self, "detail_panel", None)
        if panel is None or panel.get_current_pdf() != pdf_path:
            return False
        if panel.has_user_edits():
            return False
        result = self.pdf_cache.get(pdf_path)
        if result is None or not self.pdf_cache.get_llm_suggestions(pdf_path):
            return False
        detected_date = self._detected_date_from(result.dates)
        self._populate_detail_panel(pdf_path, result, detected_date)
        # Ordnervorschlaege nachziehen: die KI nennt jetzt evtl. einen Ablageort
        base = getattr(self, "_folder_suggestions_base", None)
        if base is not None:
            suggestions = self._with_ki_folder(pdf_path, base, detected_date)
            self.display_suggestions(suggestions)
            self.folder_tree.set_suggestion_folders([s.folder_path for s in suggestions])
        self.statusbar.showMessage(f"KI-Vorschläge für {pdf_path.name} eingetragen", 4000)
        return True

    def _with_ki_folder(self, pdf_path: Path, suggestions: list, detected_date: str = None) -> list:
        """Ergaenzt die Ordnervorschlaege um den "zielordner" aus dem KI-Vorschlag.

        Die KI kennt die Ablageorte aehnlicher Dokumente (Sortierhistorie und
        Suchindex) und nennt den passenden Ordner mit dem Jahr DIESES Dokuments.
        """
        try:
            from src.core.similar_documents import (
                document_year, folder_suggestion_from_metadata, merge_folder_suggestion,
            )
            roots = self.folder_manager.target_folders
            ki = None
            for s in self.pdf_cache.get_llm_suggestions(pdf_path) or []:
                ki = folder_suggestion_from_metadata(
                    getattr(s, "metadata", None), roots, document_year(detected_date),
                )
                if ki:
                    break
            return merge_folder_suggestion(suggestions, ki)
        except Exception as e:  # noqa: BLE001 - KI-Ordner ist optional
            logging.getLogger(__name__).debug(f"KI-Ordnervorschlag nicht verfuegbar: {e}")
            return list(suggestions)

    @staticmethod
    def _detected_date_from(dates) -> Optional[str]:
        """Erstes erkanntes Datum als YYYY-MM-DD (oder None)."""
        if not dates:
            return None
        first_date = dates[0]
        if hasattr(first_date, "strftime"):
            return first_date.strftime("%Y-%m-%d")
        return str(first_date)

    def _on_llm_suggestions_failed(self, pdf_path: Path, error: str):
        """KI-Abruf für eine PDF ist fehlgeschlagen (Cache-Signal)."""
        self._last_llm_error = (pdf_path.name, error)
        self._llm_success_since_error = False
        from src.ml.llm_hinweis import betrifft_nur_dokument
        if not betrifft_nur_dokument(error):
            # Anbieter-Problem: Anzeige bleibt rot, bis wieder eine Anfrage
            # gelingt - die Minutenpruefung allein macht sie nicht gruen.
            self._llm_request_error = error
            self._set_llm_reachable(False)
        self._update_cache_status()

    def _show_precache_details(self):
        """Zeigt Details zur Hintergrund-Analyse (Doppelklick auf Statuslabel)."""
        from src.utils.logging_config import get_log_directory
        analyzed, llm_done, total = self._precache_progress()
        health, hinweis = self._llm_health()
        provider = self.hybrid_classifier.get_llm_provider_name()
        if health == "fehler":
            llm_state = (f"{provider} funktioniert gerade nicht.\n"
                         f"  Problem: {hinweis.problem}\n"
                         f"  Abhilfe: {hinweis.abhilfe}")
        elif health == "pruefen":
            llm_state = f"{provider} (Verbindung wird geprüft …)"
        elif health == "bereit":
            llm_state = f"bereit ({provider})"
        else:
            llm_state = "aus"
        precache = "an" if self.config.get("llm_precache_enabled", True) else "aus"
        lines = [
            f"PDFs im Ordner: {total}",
            f"Analysiert (Text/Datum): {analyzed}/{total}",
            f"KI-Vorschläge vorhanden: {llm_done}/{total}",
            f"KI-Assistent: {llm_state}",
            f"KI-Vorabfrage im Hintergrund: {precache}",
        ]
        if self._last_llm_error:
            name, error = self._last_llm_error
            lines.append(f"\nLetzter KI-Fehler ({name}):\n{error}")
        log_file = get_log_directory() / "pdf_sortier_meister.log"
        lines.append(f"\nLog-Datei: {log_file}")

        box = QMessageBox(self)
        box.setWindowTitle("Hintergrund-Analyse")
        warn = bool(self._last_llm_error) or health == "fehler"
        box.setIcon(QMessageBox.Icon.Warning if warn else QMessageBox.Icon.Information)
        box.setText("\n".join(lines))
        settings_btn = box.addButton("Einstellungen öffnen", QMessageBox.ButtonRole.ActionRole)
        open_log_btn = box.addButton("Log-Datei öffnen", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is settings_btn:
            self.open_settings()
        elif box.clickedButton() is open_log_btn:
            from src.utils.platform_paths import open_with_default_app
            try:
                open_with_default_app(log_file)
            except Exception as e:
                QMessageBox.warning(self, "Log-Datei", f"Konnte die Log-Datei nicht öffnen:\n{e}")

    def _on_thumbnail_loaded(self):
        """Wird aufgerufen wenn ein Thumbnail fertig geladen ist."""
        self._pending_thumbnails -= 1
        if self._pending_thumbnails <= 0 and not self._thumbnails_signal_emitted:
            self._thumbnails_signal_emitted = True
            self.thumbnails_loaded.emit()

    def remove_pdf_widget(self, pdf_path: Path) -> Optional[int]:
        """Entfernt ein einzelnes PDF-Widget aus der Ansicht (ohne vollständigen Refresh).

        Gibt die Rasterposition zurück, an der das Widget stand (Issue #75:
        automatische Auswahl der nächsten PDF), oder None falls nicht gefunden.
        """
        index = None
        for i, widget in enumerate(self.pdf_widgets):
            if widget.pdf_path == pdf_path:
                index = i
                # Widget aus Layout entfernen
                self.pdf_layout.removeWidget(widget)
                widget.cleanup() if hasattr(widget, 'cleanup') else None
                widget.deleteLater()
                self.pdf_widgets.remove(widget)
                break

        # PDF-Zähler aktualisieren
        self.pdf_count_label.setText(f"PDFs: {len(self.pdf_widgets)}")

        # Falls es die ausgewählte PDF war, Auswahl zurücksetzen
        if self.selected_pdf == pdf_path:
            self.selected_pdf = None
            self.selected_pdf_text = None
            self.selected_pdf_keywords = None

        # Aus Mehrfachauswahl entfernen
        if pdf_path in self.selected_pdfs:
            self.selected_pdfs.remove(pdf_path)

        return index

    def _remove_pdf_widget_and_select_next(self, pdf_path: Path) -> bool:
        """Entfernt ein PDF-Widget und wählt danach automatisch die nächste PDF
        an derselben Rasterposition aus, falls die entfernte PDF die aktuell
        ausgewählte war (Issue #75: nach dem Wegsortieren automatisch weiter).

        Läuft über den normalen Klick-Pfad (on_pdf_clicked), damit Detail-Panel,
        Vorschläge und Ordner-Highlights wie bei einem echten Klick aktualisiert
        werden. Gibt True zurück, wenn eine Folge-PDF automatisch ausgewählt wurde.
        """
        was_selected = self.selected_pdf == pdf_path
        index = self.remove_pdf_widget(pdf_path)
        if was_selected and index is not None and self.pdf_widgets:
            next_index = min(index, len(self.pdf_widgets) - 1)
            next_path = self.pdf_widgets[next_index].pdf_path
            self.on_pdf_clicked(next_path)
            return True
        return False

    def _update_pdf_widget_path(self, old_path: Path, new_path: Path):
        """Aktualisiert den Pfad eines PDF-Widgets nach Umbenennung."""
        for widget in self.pdf_widgets:
            if widget.pdf_path == old_path:
                # Pfad aktualisieren
                widget.pdf_path = new_path

                # Namen-Label aktualisieren
                name = new_path.name
                if len(name) > 25:
                    name = name[:22] + "..."
                widget.name_label.setText(name)
                widget.name_label.setToolTip(new_path.name)

                # Falls ausgewählt, auch selected_pdf aktualisieren
                if self.selected_pdf == old_path:
                    self.selected_pdf = new_path

                # In Mehrfachauswahl aktualisieren
                if old_path in self.selected_pdfs:
                    self.selected_pdfs.remove(old_path)
                    self.selected_pdfs.append(new_path)

                break

    def _start_warmup(self):
        """Laedt teure Module im Hintergrund vor, damit der erste Klick nicht wartet."""
        import threading

        def _run():
            try:
                import pikepdf  # noqa: F401  (Detail-Panel liest Metadaten aus der PDF)
                import sklearn.metrics.pairwise  # noqa: F401  (erste Aehnlichkeitssuche)
                # Ordner-Cache des Klassifikators (rglob ueber alle Zielordner) vorab
                self.classifier.warm_folder_cache()
            except Exception:
                pass

        threading.Thread(target=_run, name="warmup", daemon=True).start()

    def _wait_for_model_then_apply(self, pdf_path: Path, result: PDFAnalysisResult):
        """
        Der Klassifikator laedt nach dem Start noch im Hintergrund. Statt den
        UI-Thread zu blockieren: Wartecursor + Statusmeldung, und sobald das
        Modell da ist, werden die Vorschlaege nachgezogen.
        """
        if self.selected_pdf != pdf_path:
            self._end_model_wait()
            return
        if self.classifier.is_model_ready():
            self._end_model_wait()
            self._apply_analysis_result(pdf_path, result)
            return
        if not getattr(self, "_model_wait_active", False):
            self._model_wait_active = True
            QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
            self.statusbar.showMessage("KI-Modell wird geladen, Vorschläge folgen gleich…")
        if not hasattr(self, "_model_wait_timer"):
            self._model_wait_timer = QTimer(self)
            self._model_wait_timer.setSingleShot(True)
            self._model_wait_timer.timeout.connect(
                lambda: self._wait_for_model_then_apply(*self._model_wait_args)
            )
        self._model_wait_args = (pdf_path, result)
        self._model_wait_timer.start(100)

    def _end_model_wait(self):
        if getattr(self, "_model_wait_active", False):
            self._model_wait_active = False
            QApplication.restoreOverrideCursor()

    def _refresh_after_move(self, target_folder: Path, *source_folders: Path):
        """Aktualisiert nach einem Verschieben nur die betroffenen Zaehler (Issue #28).

        Der Scan-Ordner (Quelle) ist meist kein Zielordner und daher nicht im
        Baum - das ist kein Grund fuer einen Voll-Neuaufbau. Nur wenn der
        Zielordner selbst fehlt (z.B. gerade neu angelegt), wird neu geladen.
        """
        target_folder = Path(target_folder)
        if not self.folder_tree.has_folder(target_folder):
            # Neuer Ordner: unter dem Elternteil einhaengen; nur wenn auch der
            # fehlt, den Baum neu scannen (laeuft im Hintergrund, blockiert nicht)
            if not self.folder_tree.add_folder_incremental(target_folder):
                self.folder_tree.refresh_tree()
                return
        self.folder_tree.refresh_counts({target_folder, *(Path(f) for f in source_folders if f)})

    def _write_pdf_metadata_async(self, pdf_path: Path, new_name: str,
                                  keywords: list[str] = None, dialog_metadata: dict = None):
        """Schreibt XMP-Metadaten im Hintergrund; Undo wartet ggf. darauf."""
        import threading

        def _run():
            try:
                self._write_pdf_metadata(pdf_path, new_name, keywords, dialog_metadata)
            finally:
                self._pending_metadata_writes.pop(pdf_path, None)

        t = threading.Thread(target=_run, name="pdf-metadata-write", daemon=True)
        self._pending_metadata_writes[pdf_path] = t
        t.start()

    def _wait_for_metadata_writes(self, paths, timeout: float = 15.0):
        """Wartet, bis Hintergrund-Schreibvorgaenge fuer diese Pfade fertig sind."""
        for p in paths:
            t = self._pending_metadata_writes.get(Path(p))
            if t is not None:
                t.join(timeout)

    def load_folders(self):
        """Lädt die Zielordner in die Baumansicht."""
        # Ordner laden
        folders = self.folder_manager.target_folders

        # Baumansicht aktualisieren
        self.folder_tree.set_root_folders(folders)

        # Alte Grid-Ansicht auch aktualisieren (für Kompatibilität)
        while self.folder_layout.count():
            item = self.folder_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.folder_widgets.clear()

        if not folders:
            return

        # Widgets für Grid erstellen (optional, versteckt)
        for i, folder_path in enumerate(folders):
            try:
                folder_info = self.folder_manager.get_folder_info(folder_path)
                pdf_count = folder_info.get("pdf_count", 0)
            except ValueError:
                pdf_count = 0

            widget = FolderWidget(folder_path, pdf_count)
            widget.clicked.connect(self.on_folder_clicked)
            widget.double_clicked.connect(self.on_folder_double_clicked)
            widget.pdf_dropped.connect(self.on_pdf_dropped_on_folder)
            widget.remove_requested.connect(self.on_folder_remove)

            row = i // 4
            col = i % 4
            self.folder_layout.addWidget(widget, row, col)
            self.folder_widgets.append(widget)

    def rebuild_folder_view(self):
        """
        Baut die Zielordner-Ansicht komplett neu auf.

        Die Lerninhalte (Datenbank) bleiben erhalten, nur die Ansicht wird
        neu eingelesen. Nützlich wenn:
        - Der Zielordner gewechselt wurde
        - Die Ordnerstruktur sich geändert hat
        - Neue Ordner angelegt wurden
        """
        # Bestätigungsdialog
        reply = QMessageBox.question(
            self,
            "Zielordner neu laden",
            "Möchten Sie die Zielordner-Ansicht neu aufbauen?\n\n"
            "• Die Ordnerstruktur wird neu eingelesen\n"
            "• Gelernte Zuordnungen bleiben erhalten\n"
            "• Nicht mehr existierende Ordner werden entfernt",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Aktuelle Zielordner aus Config holen
        target_folders = self.config.get_target_folders()

        # Prüfen welche noch existieren
        existing_folders = [f for f in target_folders if f.exists()]
        removed_count = len(target_folders) - len(existing_folders)

        # Ordner neu laden
        self.folder_manager.load_folders(existing_folders)

        # Config aktualisieren (nur existierende Ordner behalten)
        if removed_count > 0:
            # Nicht mehr existierende Ordner aus Config entfernen
            for folder in target_folders:
                if folder not in existing_folders:
                    self.config.remove_target_folder(folder)

        # Ansicht neu aufbauen
        self.load_folders()

        # Classifier-Cache invalidieren (damit neue Ordnerstruktur erkannt wird)
        if hasattr(self, 'classifier'):
            self.classifier._folder_cache = {}
            self.classifier._folder_cache_roots = []

        # Statusmeldung
        if removed_count > 0:
            self.statusbar.showMessage(
                f"Zielordner neu geladen. {removed_count} nicht mehr existierende Ordner entfernt.",
                5000
            )
        else:
            self.statusbar.showMessage("Zielordner-Ansicht neu aufgebaut.", 3000)

    def clear_folder_view(self):
        """
        Leert die Zielordner-Ansicht komplett.

        Die Lerninhalte (Datenbank) bleiben erhalten, nur die Ansicht wird
        geleert. Danach können Zielordner manuell neu hinzugefügt werden.
        """
        # Bestätigungsdialog
        reply = QMessageBox.question(
            self,
            "Zielordner-Ansicht leeren",
            "Möchten Sie alle Zielordner aus der Ansicht entfernen?\n\n"
            "• Die Ansicht wird geleert\n"
            "• Gelernte Zuordnungen bleiben erhalten\n"
            "• Sie können danach neue Zielordner hinzufügen",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            # Ordner aus Config entfernen (einzeln, da set_target_folders nicht existiert)
            current_folders = self.config.get_target_folders()
            for folder in current_folders:
                self.config.remove_target_folder(folder)

            # FolderManager leeren
            self.folder_manager.load_folders([])

            # Ansicht leeren
            self.folder_tree.set_root_folders([])

            # Grid-Ansicht auch leeren
            while self.folder_layout.count():
                item = self.folder_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.folder_widgets.clear()

            # Classifier-Cache invalidieren
            if hasattr(self, 'classifier'):
                self.classifier._folder_cache = {}
                self.classifier._folder_cache_roots = []

            self.statusbar.showMessage("Zielordner-Ansicht geleert. Fügen Sie neue Zielordner hinzu.", 5000)

        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Fehler beim Leeren der Ansicht:\n{e}")

    def setup_menu(self):
        """Erstellt die Menüleiste."""
        menubar = self.menuBar()

        # Datei-Menü
        file_menu = menubar.addMenu("Datei")

        open_folder_action = QAction("Scan-Ordner öffnen...", self)
        open_folder_action.setShortcut("Ctrl+O")
        open_folder_action.triggered.connect(self.open_scan_folder)
        file_menu.addAction(open_folder_action)

        add_target_action = QAction("Zielordner hinzufügen...", self)
        add_target_action.triggered.connect(self.add_target_folder)
        file_menu.addAction(add_target_action)

        file_menu.addSeparator()

        exit_action = QAction("Beenden", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Bearbeiten-Menü
        edit_menu = menubar.addMenu("Bearbeiten")

        self.undo_action = QAction("Rückgängig", self)
        self.undo_action.setShortcut("Ctrl+Z")
        self.undo_action.setToolTip("Letzte Aktion rückgängig machen (Verschieben/Umbenennen)")
        self.undo_action.triggered.connect(self.undo_last_action)
        self.undo_action.setEnabled(False)
        edit_menu.addAction(self.undo_action)

        rename_action = QAction("Umbenennen...", self)
        rename_action.setShortcut("F2")
        rename_action.setToolTip("Ausgewählte PDF umbenennen (F2)")
        rename_action.triggered.connect(self._rename_selected_pdf)
        edit_menu.addAction(rename_action)

        edit_menu.addSeparator()

        deselect_action = QAction("Auswahl aufheben", self)
        deselect_action.setShortcut("Escape")
        deselect_action.setToolTip("Alle Selektionen aufheben (Escape)")
        deselect_action.triggered.connect(self._clear_selection)
        edit_menu.addAction(deselect_action)

        # Ansicht-Menü
        view_menu = menubar.addMenu("Ansicht")

        refresh_action = QAction("Aktualisieren", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self.refresh_view)
        view_menu.addAction(refresh_action)

        view_menu.addSeparator()

        back_action = QAction("Zurück", self)
        back_action.setShortcut("Alt+Left")
        back_action.setToolTip("Zum vorherigen Scan-Ordner zurückkehren")
        back_action.triggered.connect(self.on_navigate_back)
        view_menu.addAction(back_action)

        up_action = QAction("Übergeordneter Ordner", self)
        up_action.setShortcut("Alt+Up")
        up_action.setToolTip("Ein Verzeichnis nach oben (wie im Dateimanager)")
        up_action.triggered.connect(self.on_navigate_up)
        view_menu.addAction(up_action)

        view_menu.addSeparator()

        search_action = QAction("Dokumentensuche...", self)
        search_action.setShortcut("Ctrl+F")
        search_action.setToolTip("Alle sortierten Dokumente durchsuchen")
        search_action.triggered.connect(lambda: self.search_input.setFocus())
        view_menu.addAction(search_action)

        volltext_action = QAction("Volltextsuche (Reiter „Suche“)", self)
        volltext_action.setShortcut("Ctrl+Shift+F")
        volltext_action.setToolTip("PDFs, Office-Dateien, Markdown und Mails im Suchindex durchsuchen")
        volltext_action.triggered.connect(self.show_search_tab)
        view_menu.addAction(volltext_action)

        # Extras-Menü
        extras_menu = menubar.addMenu("Extras")

        steuer_action = QAction("Steuerauswertung...", self)
        steuer_action.setToolTip("Jahressummen nach Kategorie anzeigen und als CSV exportieren")
        steuer_action.triggered.connect(self._open_steuerauswertung)
        extras_menu.addAction(steuer_action)

        extras_menu.addSeparator()

        index_folder_action = QAction("Ordner zum Suchindex hinzufügen...", self)
        index_folder_action.setToolTip("Bestehende PDF-Sammlung scannen und in den Suchindex aufnehmen")
        index_folder_action.triggered.connect(self._index_folder_dialog)
        extras_menu.addAction(index_folder_action)

        extras_menu.addSeparator()

        backup_action = QAction("Backup-Status prüfen", self)
        backup_action.triggered.connect(self.check_backup_status)
        extras_menu.addAction(backup_action)

        # Anwendungsdaten sichern/wiederherstellen (Issue #98)
        self.backup_data_action = QAction("Daten sichern (ZIP)...", self)
        self.backup_data_action.setToolTip(
            "Datenbank, Suchindex, KI-Cache, Modell und Einstellungen als ZIP sichern"
        )
        self.backup_data_action.triggered.connect(self.backup_app_data)
        extras_menu.addAction(self.backup_data_action)

        self.restore_data_action = QAction("Daten aus Sicherung wiederherstellen...", self)
        self.restore_data_action.setToolTip(
            "Eine mit „Daten sichern“ erstellte ZIP-Datei beim nächsten Start einspielen"
        )
        self.restore_data_action.triggered.connect(self.restore_app_data)
        extras_menu.addAction(self.restore_data_action)

        extras_menu.addSeparator()

        wizard_action = QAction("Einrichtungs-Assistent...", self)
        wizard_action.triggered.connect(self.open_setup_wizard)
        extras_menu.addAction(wizard_action)

        settings_action = QAction("Einstellungen...", self)
        settings_action.triggered.connect(self.open_settings)
        extras_menu.addAction(settings_action)

        # Hilfe-Menü
        help_menu = menubar.addMenu("Hilfe")

        first_steps_action = QAction("Erste Schritte", self)
        first_steps_action.setToolTip("Zeigt die Kurzanleitung zum 3-Spalten-Workflow erneut an")
        first_steps_action.triggered.connect(lambda: self.show_first_steps_hint(force=True))
        help_menu.addAction(first_steps_action)

        update_action = QAction("Nach Updates suchen...", self)
        update_action.setToolTip("Prüft, ob auf GitHub eine neuere Version veröffentlicht wurde")
        update_action.triggered.connect(lambda: self.check_for_updates(manual=True))
        help_menu.addAction(update_action)

        about_action = QAction("Über PDF Sortier Meister", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def setup_toolbar(self):
        """Erstellt die Werkzeugleiste."""
        toolbar = QToolBar("Hauptwerkzeugleiste")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # Aktualisieren-Button
        refresh_action = QAction("Aktualisieren", self)
        refresh_action.setToolTip("Scan-Ordner neu einlesen (F5)")
        refresh_action.triggered.connect(self.refresh_view)
        toolbar.addAction(refresh_action)

        toolbar.addSeparator()

        # Scan-Ordner öffnen
        open_action = QAction("Scan-Ordner", self)
        open_action.setToolTip("Scan-Ordner auswählen")
        open_action.triggered.connect(self.open_scan_folder)
        toolbar.addAction(open_action)

        # Zielordner hinzufügen
        add_folder_action = QAction("+ Zielordner", self)
        add_folder_action.setToolTip("Neuen Zielordner hinzufügen")
        add_folder_action.triggered.connect(self.add_target_folder)
        toolbar.addAction(add_folder_action)

        toolbar.addSeparator()

        # Rückgängig-Button
        self.undo_toolbar_action = QAction("↩ Rückgängig", self)
        self.undo_toolbar_action.setToolTip("Letzte Aktion rückgängig machen (Ctrl+Z)")
        self.undo_toolbar_action.triggered.connect(self.undo_last_action)
        self.undo_toolbar_action.setEnabled(False)
        toolbar.addAction(self.undo_toolbar_action)

        toolbar.addSeparator()

        # Suchleiste (Phase 17)
        search_label = QLabel(" Suche: ")
        toolbar.addWidget(search_label)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Dokumente durchsuchen... (Ctrl+F)")
        self.search_input.setFixedWidth(250)
        self.search_input.setStyleSheet("padding: 3px 6px;")
        self.search_input.returnPressed.connect(self._execute_search)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        toolbar.addWidget(self.search_input)

        self.search_count_label = QLabel("")
        self.search_count_label.setStyleSheet("color: #666; padding-left: 5px;")
        toolbar.addWidget(self.search_count_label)

        clear_search_action = QAction("Suche leeren", self)
        clear_search_action.setToolTip("Suchfilter zurücksetzen")
        clear_search_action.triggered.connect(self._clear_search)
        toolbar.addAction(clear_search_action)

        # Filter-Leiste Toggle (Phase 18)
        self.filter_toggle_btn = QToolButton()
        self.filter_toggle_btn.setText("Filter ▼")
        self.filter_toggle_btn.setToolTip("Erweiterte Filter ein-/ausblenden")
        self.filter_toggle_btn.setCheckable(True)
        self.filter_toggle_btn.setChecked(False)
        self.filter_toggle_btn.toggled.connect(self._toggle_filter_bar)
        toolbar.addWidget(self.filter_toggle_btn)

    def setup_statusbar(self):
        """Erstellt die Statusleiste."""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)

        # Permanente Anzeigen
        self.pdf_count_label = QLabel("PDFs: 0")
        self.statusbar.addPermanentWidget(self.pdf_count_label)

        # Trainingsstand anzeigen
        training_count = self.classifier.get_training_count()
        self.training_label = QLabel(f"Gelernt: {training_count}")
        self.training_label.setToolTip("Anzahl gelernter Sortierentscheidungen")
        self.statusbar.addPermanentWidget(self.training_label)

        # Cache-Status (Pre-Caching-Fortschritt)
        self.cache_status_label = _ClickableLabel("")
        self.cache_status_label.setStyleSheet("color: #888; font-size: 11px;")
        self.cache_status_label.setToolTip("Doppelklick zeigt Details zur Hintergrund-Analyse.")
        self.cache_status_label.doubleClicked.connect(self._show_precache_details)
        self.statusbar.addPermanentWidget(self.cache_status_label)

        # LLM-Status anzeigen
        self.llm_status_label = _ClickableLabel("")
        self.llm_status_label.doubleClicked.connect(self.open_settings)
        # Erreichbarkeit lokaler Server (Ollama, Strata): Ergebnis der letzten
        # Hintergrund-Pruefung, None = noch offen / nicht pruefbar
        self._llm_connection: Optional[tuple[bool, str]] = None
        # Letzter echter KI-Fehler (Anbieter-Problem), bis wieder eine Anfrage
        # gelingt oder die Einstellungen geaendert werden. None = kein Fehler.
        self._llm_request_error: Optional[str] = None
        self._llm_check_generation = 0
        self._llm_connection_checked.connect(self._on_llm_connection_checked)
        self._llm_check_timer = QTimer(self)
        self._llm_check_timer.setInterval(self.LLM_CHECK_INTERVAL_MS)
        self._llm_check_timer.timeout.connect(self._on_llm_check_tick)
        self._llm_check_timer.start()
        self._update_llm_status()
        self._check_llm_connection()
        self.statusbar.addPermanentWidget(self.llm_status_label)

        # Backup-Erinnerung (Issue #14): nur sichtbar, solange "Nein" gilt
        self.backup_status_label = _ClickableLabel("Kein aktuelles Backup gemacht")
        self.backup_status_label.setStyleSheet("color: #d17a00; font-weight: bold;")
        self.backup_status_label.setToolTip("Klicken, um ein gemachtes Backup zu bestätigen.")
        self.backup_status_label.clicked.connect(self.confirm_backup_done)
        self.backup_status_label.setVisible(bool(self.config.get("backup_pending", False)))
        self.statusbar.addPermanentWidget(self.backup_status_label)

        # Update-Hinweis (Issue #73): erst sichtbar, wenn ein Update gefunden wurde
        self.update_status_label = _ClickableLabel("")
        self.update_status_label.setStyleSheet("color: #d17a00; font-weight: bold;")
        self.update_status_label.setToolTip("Doppelklick zeigt Details zum Update.")
        self.update_status_label.doubleClicked.connect(self._show_available_update)
        self.update_status_label.setVisible(False)
        self.statusbar.addPermanentWidget(self.update_status_label)
        self._update_thread: Optional[_UpdateCheckThread] = None
        self._available_update: Optional[UpdateInfo] = None

        self.statusbar.showMessage("Bereit")

    def load_settings(self):
        """Lädt die gespeicherten Einstellungen."""
        width = self.config.get("window_width", 1200)
        height = self.config.get("window_height", 800)
        # Auf den verfügbaren Bildschirm begrenzen: gespeicherte Größen von
        # einem anderen Monitor / anderer Windows-Skalierung würden sonst
        # über den Bildschirmrand hinausragen (Issue #50, Titelleiste)
        screen = self.screen() or QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            width = min(width, available.width())
            height = min(height, available.height())
        self.resize(width, height)
        if self.config.get("window_maximized", True):
            self.showMaximized()

    def save_settings(self):
        """Speichert die aktuellen Einstellungen."""
        # Im maximierten Zustand die normale (wiederhergestellte) Größe
        # speichern, nicht die Bildschirmgröße (Issue #50)
        size = self.normalGeometry().size() if self.isMaximized() else self.size()
        self.config.set("window_width", size.width(), auto_save=False)
        self.config.set("window_maximized", self.isMaximized(), auto_save=False)
        # Aufteilung Details/Vorschau im mittleren Panel (Issue #74)
        sizes = self.detail_panel.splitter.sizes()
        if len(sizes) == 2 and all(v > 0 for v in sizes):
            self.config.set("detail_splitter_sizes", list(sizes), auto_save=False)
        self.config.set("window_height", size.height(), auto_save=True)

    def closeEvent(self, event):
        """Wird beim Schließen des Fensters aufgerufen."""
        self.save_settings()

        # Fenstergebundene Timer anhalten: Nach dem Schliessen darf kein
        # verzoegerter Callback (Pre-Caching, Modell-Warten, Raster-Relayout)
        # mehr auf ein halb zerstoertes Fenster treffen.
        for name in ("_precache_timer", "_model_wait_timer", "_grid_relayout_timer",
                     "_activity_timer"):
            timer = getattr(self, name, None)
            if timer is not None:
                timer.stop()

        # Thumbnail-Threads beenden
        for widget in self.pdf_widgets:
            widget.cleanup()

        # Kind-Threads (Ordner-Scan, Metadaten-Leser) zu Ende laufen lassen.
        # Wird ein noch laufender QThread mitsamt seinem Eltern-Widget
        # zerstoert, bricht Qt den Prozess hart ab.
        # Vorschau-Fenster schliessen; Lese-Threads der Vorschau sind Kinder
        # des Detail-Panels und werden unten mit abgewartet.
        if self._preview_window is not None:
            self._preview_window.close()
        # Reiter „Suche“: Abfrage-Threads und PDF-Leser der eigenen Vorschau
        self.search_view.shutdown()

        # "OCR neu" bricht vor der naechsten Seite ab (Issue #150)
        if self._ocr_neu_worker is not None:
            self._ocr_neu_worker.requestInterruption()
        if self._office_worker is not None:
            self._office_worker.requestInterruption()
        self._office_preview_pfad = None  # laufende Vorschau-Umwandlung nicht mehr nachziehen

        for thread in self.findChildren(QThread):
            thread.wait(5000)

        # Ausstehendes Hintergrund-Training des Klassifikators abschliessen
        try:
            self.classifier.flush_training(timeout=10)
        except Exception:
            pass

        # PDF-Cache Worker stoppen
        self.pdf_cache.stop_worker()
        self.pdf_cache.stop_llm_worker()

        event.accept()

    def resizeEvent(self, event):
        """Passt bei Größenänderung die Raster-Spaltenzahl an (Issue #50)."""
        super().resizeEvent(event)
        if hasattr(self, "_grid_relayout_timer"):
            self._grid_relayout_timer.start()

    # Ordnerzeilen in zwei Spalten erst ab dieser Breite je Spalte (Issue #147)
    FOLDER_ROW_COLUMN_MIN_WIDTH = 240

    def _scan_viewport_width(self) -> int:
        """Sichtbare Breite des Scan-Bereichs (eigene Methode, damit Tests sie setzen koennen)."""
        return self.pdf_scroll_area.viewport().width()

    def _pdf_grid_columns(self) -> int:
        """Spaltenzahl fürs PDF-Raster aus der sichtbaren Panelbreite.

        Die Rasterbreite pro Kachel (max. Kachelbreite plus 10 px Abstand)
        haengt von der gewaehlten Kachelgroesse ab (Issue #117).
        """
        return max(1, self._scan_viewport_width() // self._tile_view.slot_width)

    def _folder_grid_columns(self) -> int:
        """Ordnerzeilen: 2 Spalten ab 2 x 240 px sichtbarer Breite, sonst 1 (Issue #147)."""
        if self._scan_viewport_width() >= 2 * self.FOLDER_ROW_COLUMN_MIN_WIDTH:
            return 2
        return 1

    def _place_folder_rows(self):
        """Verteilt die Ordnerzeilen zeilenweise auf self._folder_cols Spalten."""
        cols = self._folder_cols
        grid = self.folder_rows_layout
        for tile in self.folder_tiles:
            grid.removeWidget(tile)
        for c in range(2):
            grid.setColumnStretch(c, 1 if c < cols else 0)
        for i, tile in enumerate(self.folder_tiles):
            grid.addWidget(tile, i // cols, i % cols)

    def _relayout_pdf_grid(self, force: bool = False):
        """Ordnet Ordnerzeilen und Thumbnails neu an, wenn sich die
        nutzbare Spaltenzahl geändert hat (Issues #50, #147)."""
        cols = self._pdf_grid_columns()
        folder_cols = self._folder_grid_columns()
        if cols == self._grid_cols and folder_cols == self._folder_cols and not force:
            return
        if folder_cols != self._folder_cols or force:
            self._folder_cols = folder_cols
            self._place_folder_rows()
        if cols != self._grid_cols or force:
            self._grid_cols = cols
            for i, widget in enumerate(self.pdf_widgets):
                self.pdf_layout.addWidget(widget, i // cols, i % cols)

    def set_tile_view(self, view_id: str):
        """Schaltet die Kachelgroesse im Scan-Bereich um (Issue #117).

        Wirkt sofort auf alle PDF-Thumbnails (die Ordnerzeilen haben eine
        feste Groesse, Issue #147), ordnet das
        Raster neu und merkt sich die Wahl in der Konfiguration.
        """
        view = tile_view(view_id)
        if view.id != self._tile_view.id:
            self._tile_view = view
            self.config.set("tile_view", view.id)
            # Ordnerzeilen haben eine feste Groesse (Issue #147)
            for widget in self.pdf_widgets:
                widget.set_view(view)
            self._relayout_pdf_grid(force=True)
        combo = getattr(self, "tile_view_combo", None)
        if combo is not None and combo.currentData() != view.id:
            combo.blockSignals(True)
            combo.setCurrentIndex(combo.findData(view.id))
            combo.blockSignals(False)

    def _sortiere_kacheln(self):
        """Ordnet die vorhandenen Kacheln nach ``self._sortierung`` um (Issue #33).

        Es werden keine Widgets neu gebaut - Thumbnails, Analyse und Auswahl
        bleiben unberuehrt, nur das Raster wird neu belegt. Weitere Kachellisten
        (Office-Kacheln, Issue #9) werden je fuer sich sortiert und stehen
        weiter hinter den PDFs.
        """
        geaendert = False
        for liste in [self.pdf_widgets] + (
            [self.office_widgets] if hasattr(self, "office_widgets") else []
        ):
            nach_pfad = {w.pdf_path: w for w in liste}
            neu = [nach_pfad[p] for p in sortiere_pfade(nach_pfad, self._sortierung)]
            if neu != liste:
                liste[:] = neu
                geaendert = True
        if geaendert:
            self._relayout_pdf_grid(force=True)

    def set_sortierung(self, sortierung: str):
        """Schaltet die Sortierung um, speichert sie und ordnet das Raster neu."""
        sortierung = sortierung_id(sortierung)
        if sortierung != self._sortierung:
            self._sortierung = sortierung
            self.config.set("kachel_sortierung", sortierung)
            self._sortiere_kacheln()
        combo = getattr(self, "sort_combo", None)
        if combo is not None and combo.currentData() != sortierung:
            combo.blockSignals(True)
            combo.setCurrentIndex(combo.findData(sortierung))
            combo.blockSignals(False)

    def _on_sort_combo_changed(self, index: int):
        self.set_sortierung(self.sort_combo.itemData(index))

    def _on_tile_view_combo_changed(self, index: int):
        view_id = self.tile_view_combo.itemData(index)
        if view_id:
            self.set_tile_view(view_id)

    # === PDF-Aktionen ===

    def on_pdf_clicked(self, pdf_path: Path):
        """Wird aufgerufen wenn eine PDF angeklickt wird."""
        # Klick auf bereits ausgewähltes PDF -> Auswahl aufheben
        # Nur wenn wirklich eine Einzelauswahl vorliegt (nicht bei Mehrfachauswahl)
        if self.selected_pdf == pdf_path and not self.selected_pdfs:
            self._clear_selection()
            return

        # Alte Auswahl aufheben (Einzelauswahl)
        for widget in self.pdf_widgets:
            widget.selected = False

        # Mehrfachauswahl zurücksetzen
        self.selected_pdfs = []

        # Neue Auswahl setzen
        self.selected_pdf = pdf_path
        for widget in self.pdf_widgets:
            if widget.pdf_path == pdf_path:
                widget.selected = True
                break

        self.statusbar.showMessage(f"Ausgewählt: {pdf_path.name}")

        # Wartezustand einer noch laufenden Erst-Analyse fuer die vorige PDF beenden
        self._end_analysis_wait()

        # PDF analysieren und Vorschläge aktualisieren
        self._click_timer = StepTimer("Klick")
        self.update_suggestions_for_pdf(pdf_path)
        self._click_timer.step("vorschlaege+detail")
        self._click_timer.done()

    def on_pdf_ctrl_clicked(self, pdf_path: Path):
        """Wird aufgerufen wenn eine PDF mit Ctrl angeklickt wird (Mehrfachauswahl)."""
        # Falls noch keine Mehrfachauswahl aktiv ist, aber eine Einzelauswahl existiert,
        # diese in die Mehrfachauswahl übernehmen
        if not self.selected_pdfs and self.selected_pdf:
            self.selected_pdfs.append(self.selected_pdf)

        # Toggle-Verhalten: Wenn bereits ausgewählt, entfernen
        if pdf_path in self.selected_pdfs:
            self.selected_pdfs.remove(pdf_path)
            for widget in self.pdf_widgets:
                if widget.pdf_path == pdf_path:
                    widget.selected = False
                    break
        else:
            # Zur Mehrfachauswahl hinzufügen
            self.selected_pdfs.append(pdf_path)
            for widget in self.pdf_widgets:
                if widget.pdf_path == pdf_path:
                    widget.selected = True
                    break

        # Statusbar aktualisieren
        self._update_selection_status()

    def on_pdf_shift_clicked(self, pdf_path: Path):
        """Wird aufgerufen wenn eine PDF mit Shift angeklickt wird (Bereichsauswahl)."""
        # Für Bereichsauswahl brauchen wir einen Ankerpunkt
        # Der Ankerpunkt ist entweder die letzte Einzelauswahl oder die letzte aus der Mehrfachauswahl
        anchor = self.selected_pdf
        if not anchor:
            # Kein Ankerpunkt - verhält sich wie normaler Klick
            self.on_pdf_clicked(pdf_path)
            return

        # Indizes der Widgets finden
        anchor_index = -1
        target_index = -1
        for i, widget in enumerate(self.pdf_widgets):
            if widget.pdf_path == anchor:
                anchor_index = i
            if widget.pdf_path == pdf_path:
                target_index = i

        if anchor_index == -1 or target_index == -1:
            # Eines der PDFs nicht gefunden
            self.on_pdf_clicked(pdf_path)
            return

        # Bereich bestimmen (von...bis)
        start_index = min(anchor_index, target_index)
        end_index = max(anchor_index, target_index)

        # Alle PDFs im Bereich auswählen
        self.selected_pdfs = []
        for i in range(start_index, end_index + 1):
            widget = self.pdf_widgets[i]
            widget.selected = True
            self.selected_pdfs.append(widget.pdf_path)

        # Widgets außerhalb des Bereichs deselektieren
        for i, widget in enumerate(self.pdf_widgets):
            if i < start_index or i > end_index:
                widget.selected = False

        # Statusbar aktualisieren
        self._update_selection_status()

    def _update_selection_status(self):
        """Aktualisiert die Statusbar basierend auf der aktuellen Auswahl."""
        count = len(self.selected_pdfs)
        if count == 0:
            self.statusbar.showMessage("Keine Auswahl")
            self.selected_pdf = None
        elif count == 1:
            self.selected_pdf = self.selected_pdfs[0]
            self.statusbar.showMessage(f"Ausgewählt: {self.selected_pdf.name}")
            self.update_suggestions_for_pdf(self.selected_pdf)
        else:
            self.selected_pdf = self.selected_pdfs[-1]  # Letzte PDF als "aktiv" für Vorschläge
            self.statusbar.showMessage(f"{count} PDFs ausgewählt (Shift/Ctrl+Klick für weitere)")
            # Vorschläge für die letzte ausgewählte PDF anzeigen
            self.update_suggestions_for_pdf(self.selected_pdf)

    def _clear_selection(self):
        """Hebt die aktuelle Auswahl vollständig auf."""
        self._end_analysis_wait()
        try:
            # Alle Widgets deselektieren
            for widget in self.pdf_widgets:
                widget.selected = False

            # Auswahl-Listen zurücksetzen
            self.selected_pdf = None
            self.selected_pdfs = []
            self.selected_pdf_text = None
            self.selected_pdf_keywords = None

            # Vorschläge im Ordner-Baum und grüne Buttons leeren
            if hasattr(self, 'folder_tree'):
                self.folder_tree.clear_suggestions()
            self.clear_suggestions()

            # Detail-Panel leeren
            if hasattr(self, 'detail_panel'):
                self.detail_panel.clear()

            self.statusbar.showMessage("Auswahl aufgehoben", 2000)
        except Exception as e:
            print(f"Fehler beim Aufheben der Auswahl: {e}")

    def _on_pdf_container_clicked(self, event):
        """Wird aufgerufen wenn auf die leere Fläche im PDF-Container geklickt wird."""
        # Nur bei linkem Mausklick
        if event.button() == Qt.MouseButton.LeftButton:
            # Prüfen ob Klick wirklich auf leere Fläche war (nicht auf ein PDF-Widget)
            # Events von Child-Widgets werden via super().mousePressEvent() weitergeleitet,
            # daher muss geprüft werden ob unter dem Klickpunkt ein Widget liegt
            child = self.pdf_container.childAt(event.pos())
            if child is None and (self.selected_pdf or self.selected_pdfs):
                self._clear_selection()

    def update_suggestions_for_pdf(self, pdf_path: Path):
        """Aktualisiert die Vorschläge für eine ausgewählte PDF."""
        # Prüfe ob im Cache
        cached_result = self.pdf_cache.get(pdf_path)

        if cached_result:
            # Sofort aus Cache verwenden - keine Verzögerung!
            self._apply_analysis_result(pdf_path, cached_result)
        else:
            # Noch nicht analysiert - Hintergrund-Analyse starten. Bei Scan-PDFs
            # ist das die OCR (mehrere Sekunden): Wartezeiger + Kachelzustand,
            # damit der Klick sichtbar angekommen ist (Issue #108)
            self._begin_analysis_wait(pdf_path)

            # Analyse anfordern mit Callback
            self.pdf_cache.request_analysis(
                pdf_path,
                callback=lambda result: self._on_analysis_result_ready(pdf_path, result),
                urgent=True  # Höchste Priorität weil User geklickt hat
            )

    def _begin_analysis_wait(self, pdf_path: Path):
        """Wartezeiger + "Analysiere…" auf der Kachel, bis die Erst-Analyse da ist."""
        self._end_analysis_wait()
        self._analysis_wait_pdf = pdf_path
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        self.statusbar.showMessage(
            f"Analysiere {pdf_path.name}… (Texterkennung kann einige Sekunden dauern)"
        )
        widget = self._pdf_widget_for(pdf_path)
        if widget is not None:
            widget.analyzing = True

    def _end_analysis_wait(self):
        """Beendet den Wartezustand der Erst-Analyse (idempotent)."""
        pdf_path = getattr(self, "_analysis_wait_pdf", None)
        if pdf_path is None:
            return
        self._analysis_wait_pdf = None
        QApplication.restoreOverrideCursor()
        widget = self._pdf_widget_for(pdf_path)
        if widget is not None:
            widget.analyzing = False

    def _pdf_widget_for(self, pdf_path: Path):
        for widget in self.pdf_widgets:
            try:
                if widget.pdf_path == pdf_path:
                    return widget
            except RuntimeError:
                continue  # Widget bereits von Qt geloescht
        return None

    def _on_analysis_result_ready(self, pdf_path: Path, result: PDFAnalysisResult):
        """Wird aufgerufen wenn eine Analyse fertig ist (aus Cache-Worker)."""
        # Wartezustand IMMER zuruecksetzen - auch wenn der Nutzer inzwischen
        # etwas anderes ausgewaehlt hat, sonst bleibt der Wartezeiger haengen
        if getattr(self, "_analysis_wait_pdf", None) == pdf_path:
            self._end_analysis_wait()
        # Nur anwenden wenn diese PDF noch ausgewählt ist
        if self.selected_pdf == pdf_path:
            # Eigene Log-Zeile fuer den asynchronen Pfad: der "Klick"-Timer
            # ist laengst abgeschlossen, seine Schritte gingen bisher verloren
            self._click_timer = StepTimer("Klick nach Analyse")
            self._apply_analysis_result(pdf_path, result)
            self._click_timer.done()

    def _on_pdf_analyzed(self, pdf_path: Path):
        """Wird aufgerufen wenn irgendeine PDF analysiert wurde (Cache-Signal)."""
        self._update_cache_status()

    def _apply_analysis_result(self, pdf_path: Path, result: PDFAnalysisResult):
        """Wendet ein Analyse-Ergebnis an und zeigt Vorschläge."""
        if not self.classifier.is_model_ready():
            self._wait_for_model_then_apply(pdf_path, result)
            return
        try:
            # Ergebnisse speichern
            self.selected_pdf_text = result.extracted_text
            self.selected_pdf_keywords = result.keywords
            self.selected_pdf_dates = result.dates

            # Erkanntes Datum für Jahr-Erkennung
            detected_date = None
            if self.selected_pdf_dates and len(self.selected_pdf_dates) > 0:
                first_date = self.selected_pdf_dates[0]
                if hasattr(first_date, 'strftime'):
                    detected_date = first_date.strftime("%Y-%m-%d")
                else:
                    detected_date = str(first_date)

            timer = getattr(self, "_click_timer", None) or StepTimer("Vorschlaege")
            # Vorschläge mit hierarchischen Pfaden holen
            suggestions = self.classifier.suggest_with_subfolders(
                text=self.selected_pdf_text,
                keywords=self.selected_pdf_keywords,
                detected_date=detected_date,
                root_folders=self.folder_manager.target_folders,
                max_suggestions=self.config.get("max_suggestions", 5),
            )
            # KI-Ordner (aus dem Ablageort aehnlicher Dokumente) an die Spitze,
            # sobald ein gecachter KI-Vorschlag ihn nennt
            self._folder_suggestions_base = list(suggestions)
            suggestions = self._with_ki_folder(pdf_path, suggestions, detected_date)
            timer.step("suggest")

            # Vorschläge anzeigen (alte grüne Buttons)
            self.display_suggestions(suggestions)
            timer.step("buttons")

            # Vorgeschlagene Ordner in der Baumansicht hervorheben
            suggested_folders = [s.folder_path for s in suggestions]
            self.folder_tree.set_suggestion_folders(suggested_folders)
            timer.step("baum")

            # Detail-Panel befüllen (3-Spalten-Layout)
            self._populate_detail_panel(pdf_path, result, detected_date)
            timer.step("detail")

            if suggestions:
                self.statusbar.showMessage(
                    f"Ausgewählt: {pdf_path.name} - {len(suggestions)} Vorschläge", 3000
                )
            else:
                self.statusbar.showMessage(
                    f"Ausgewählt: {pdf_path.name} - Keine Vorschläge verfügbar", 3000
                )

        except Exception as e:
            print(f"Fehler bei Vorschlägen: {e}")
            self.selected_pdf_text = None
            self.selected_pdf_keywords = None
            self.selected_pdf_dates = None
            self.clear_suggestions()
            self.folder_tree.clear_suggestions()
            self.statusbar.showMessage(f"Ausgewählt: {pdf_path.name}", 3000)

    def _populate_detail_panel(self, pdf_path: Path, result: PDFAnalysisResult, detected_date: str = None):
        """Befüllt das Detail-Panel mit Umbenennungsvorschlägen und Metadaten."""
        try:
            # Rename-Suggestions generieren (gleiche Logik wie on_pdf_rename)
            rename_suggestions = generate_rename_suggestions(
                pdf_path=pdf_path,
                extracted_text=result.extracted_text,
                keywords=result.keywords,
                dates=result.dates,
            )

            # Gelernte Muster aus DB
            if result.keywords:
                from src.utils.database import get_database
                rename_history = get_database().get_rename_suggestions_by_keywords(result.keywords, limit=3)
                for entry in rename_history:
                    rename_suggestions.append(RenameSuggestion(
                        name=entry.new_filename,
                        reason=f"Gelernt: ähnlich zu {entry.original_filename}",
                        confidence=0.7,
                    ))

            # Gecachte LLM-Vorschläge hinzufügen
            cached_llm = self.pdf_cache.get_llm_suggestions(pdf_path)
            if cached_llm:
                for llm_s in cached_llm:
                    rename_suggestions.insert(0, RenameSuggestion(
                        name=llm_s.filename,
                        reason="KI-Vorschlag",
                        confidence=llm_s.confidence,
                        metadata=getattr(llm_s, 'metadata', None),
                    ))

            # Detail-Panel befüllen
            self.detail_panel.set_pdf(
                pdf_path=pdf_path,
                suggestions=rename_suggestions,
                extracted_text=result.extracted_text,
                keywords=result.keywords,
                detected_date=detected_date,
            )

        except Exception as e:
            print(f"Fehler beim Befüllen des Detail-Panels: {e}")

    def display_suggestions(self, suggestions: list):
        """Zeigt die Sortiervorschläge an."""
        # Alte Vorschläge entfernen
        self.clear_suggestions()
        # Fuer den Chat mit Bezugsdokument (Issue #148)
        self._shown_suggestions = list(suggestions or [])

        if not suggestions:
            self.no_suggestions_label.show()
            return

        self.no_suggestions_label.hide()

        # Vorschlag-Widgets erstellen
        for suggestion in suggestions:
            widget = FolderWidget(suggestion.folder_path, 0)
            widget.is_suggestion = True

            # NEU: Relativen Pfad anzeigen wenn vorhanden
            display_name = suggestion.relative_path if suggestion.relative_path else suggestion.folder_name
            # Nur bei extrem langen Namen kürzen (WordWrap übernimmt den Rest)
            if len(display_name) > 50:
                display_name = "..." + display_name[-47:]
            widget.name_label.setText(display_name)

            # Tooltip mit vollständigem Pfad, Begründung und Konfidenz
            tooltip = f"Pfad: {suggestion.relative_path or suggestion.folder_name}\n"
            tooltip += f"{suggestion.reason}\n"
            tooltip += f"Konfidenz: {int(suggestion.confidence * 100)}%\n"
            tooltip += "Anklicken verschiebt die ausgewählte PDF hierher."
            widget.setToolTip(tooltip)

            # Konfidenz im Namen anzeigen
            confidence_text = f"{int(suggestion.confidence * 100)}%"
            widget.count_label.setText(confidence_text)
            widget.count_label.setStyleSheet("font-size: 10px; color: #28a745; font-weight: bold;")

            widget.clicked.connect(self.on_suggestion_clicked)
            widget.double_clicked.connect(self.on_folder_double_clicked)
            # Drop auf eine gruene Vorschlagskachel verschiebt wie ein Drop
            # auf den Baum (vorher stilles No-op, weil nie verbunden)
            widget.pdf_dropped.connect(self.on_pdf_dropped_on_folder)

            # Issue #32: nur der erste (beste) Vorschlag, nur bei hoher Konfidenz
            if not self.suggestion_widgets and suggestion.confidence >= REGENBOGEN_SCHWELLE:
                widget.set_regenbogen(True)

            self.suggestions_layout.addWidget(widget)
            self.suggestion_widgets.append(widget)

    def clear_suggestions(self):
        """Entfernt alle Vorschlag-Widgets."""
        for widget in self.suggestion_widgets:
            widget.set_regenbogen(False)  # Animation sauber stoppen (Issue #32)
            widget.deleteLater()
        self.suggestion_widgets.clear()
        self._shown_suggestions = []
        self.no_suggestions_label.show()
        # Auch Hervorhebungen in der Baumansicht entfernen
        if hasattr(self, 'folder_tree'):
            self.folder_tree.clear_suggestions()

    def on_suggestion_clicked(self, folder_path: Path):
        """Wird aufgerufen wenn ein Vorschlag angeklickt wird."""
        # Multi-Selektion: Mehrere PDFs verschieben
        if len(self.selected_pdfs) > 1:
            self.move_multiple_pdfs_to_folder(self.selected_pdfs, folder_path)
        elif self.selected_pdf:
            self._move_rename_and_learn(self.selected_pdf, folder_path)

    def _move_rename_and_learn(self, pdf_path: Path, folder_path: Path):
        """Verschiebt eine PDF mit optionaler Umbenennung und Metadaten (3-Spalten-Workflow)."""
        relative_path = self.folder_tree.get_relative_path(folder_path)

        new_name = self.detail_panel.get_new_name()
        metadata = self.detail_panel.get_metadata()
        # .docx/.xlsx behalten beim Umbenennen ihre Endung (der Name kommt mit ".pdf")
        office_ext = pdf_path.suffix.lower() if ist_office_datei(pdf_path) else None
        if office_ext and new_name:
            new_name = endung_tauschen(new_name, office_ext)

        # Der vom Nutzer gewaehlte/korrigierte Name ist das, was die KI
        # kuenftig liefern soll - nur er geht als Beispiel in die Historie.
        # Das Ordner-Praefix (#42) kommt beim Verschieben dazu und wuerde
        # die KI sonst dazu verleiten, selbst Ordnernummern zu erfinden.
        learned_name = new_name
        folder_naming_applied = False

        # Dateiname aus Ordnerstruktur aufbauen (Issue #42, Opt-in)
        if self.config.get("folder_naming_enabled", False):
            folder_naming_applied = True
            # Datum aus dem Feld "Datum" des Detail-Panels (Issue #132),
            # sonst das erkannte Datum der Analyse
            fallback_date = _iso_to_date(metadata.get("buchungsdatum") if metadata else None)
            if fallback_date is None and self.selected_pdf_dates:
                fallback_date = coerce_date(self.selected_pdf_dates[0])
            basis_name = new_name or pdf_path.name
            if office_ext:
                basis_name = basis_name[: -len(office_ext)] if basis_name.lower().endswith(office_ext) else basis_name
            new_name = build_folder_based_name(
                basis_name,
                folder_path,
                relative_path,
                template=self.config.get("folder_naming_template", "") or DEFAULT_TEMPLATE,
                initials=self.config.get("owner_initials", ""),
                fallback_date=fallback_date,
            )
            if office_ext:
                new_name = endung_tauschen(new_name, office_ext)

        # Prüfen ob umbenannt wird
        name_changed = new_name and new_name != pdf_path.name

        # Bestätigungsdialog
        if name_changed:
            msg = f"'{pdf_path.name}'\n→ '{new_name}'\n\nnach '{relative_path}' verschieben?"
        else:
            msg = f"'{pdf_path.name}' nach '{relative_path}' verschieben?"
            new_name = None  # Originalname beibehalten

        reply = QMessageBox.question(
            self, "PDF verschieben",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        timer = StepTimer("Verschieben")
        try:
            # Datei verschieben (mit optionalem neuen Namen)
            new_path = self.file_manager.move_file(pdf_path, folder_path, new_name=new_name)
            timer.step("move")

            # Cache-Eintrag migrieren
            self.pdf_cache.migrate_cache_entry(pdf_path, new_path)
            timer.step("cache")

            # Metadaten in PDF schreiben (pikepdf schreibt die Datei komplett neu
            # -> auf OneDrive/Netzlaufwerken langsam, daher im Hintergrund)
            if metadata:
                if not office_ext:  # in .docx/.xlsx schreiben wir keine PDF-Metadaten
                    self._write_pdf_metadata_async(new_path, new_path.name,
                                                   self.selected_pdf_keywords, metadata)
                # Korrespondent-Zuordnung lernen
                if metadata.get("korrespondent"):
                    self.db.learn_korrespondent_metadata(
                        metadata["korrespondent"], metadata
                    )
            timer.step("metadata")

            # Undo-Eintrag
            desc = f"{pdf_path.name} → {relative_path}"
            if name_changed:
                desc = f"{pdf_path.name} → {new_path.name} → {relative_path}"
            self._push_undo({
                "type": "move",
                "moves": [(pdf_path, new_path)],
                "description": desc,
            })

            # Aus der Entscheidung lernen
            if self.selected_pdf_text:
                self.classifier.learn(
                    pdf_path=pdf_path,
                    target_folder=folder_path,
                    extracted_text=self.selected_pdf_text,
                    keywords=self.selected_pdf_keywords,
                    relative_path=relative_path,
                )
            timer.step("learn")

            # Umbenennung lernen (falls Name geändert)
            if name_changed:
                # Vom Nutzer bestaetigtes/korrigiertes Datum (Issue #132) vor dem erkannten
                detected_date = metadata.get("buchungsdatum") if metadata else None
                if not detected_date and self.selected_pdf_dates:
                    try:
                        d = self.selected_pdf_dates[0]
                        detected_date = d.strftime("%Y-%m-%d") if hasattr(d, 'strftime') else str(d)
                    except Exception:
                        pass
                history_name = (
                    learned_name if folder_naming_applied and learned_name else new_path.name
                )
                if history_name != pdf_path.name:
                    self.db.add_rename_entry(
                        original_filename=pdf_path.name,
                        new_filename=history_name,
                        extracted_text=self.selected_pdf_text,
                        keywords=self.selected_pdf_keywords,
                        detected_date=detected_date,
                        target_folder=str(folder_path),
                    )

            # Volltext-Suchindex befüllen (Phase 17)
            self.db.update_pdf_path(
                old_path=str(pdf_path),
                new_path=str(new_path),
                new_filename=new_path.name,
                extracted_text=self.selected_pdf_text or "",
                keywords=", ".join(self.selected_pdf_keywords) if self.selected_pdf_keywords else "",
                korrespondent=metadata.get("korrespondent", "") if metadata else "",
                kategorie=metadata.get("subject", "") if metadata else "",
                steuerjahr=metadata.get("steuerjahr", "") if metadata else "",
                betrag=metadata.get("betrag", "") if metadata else "",
                zusammenfassung=metadata.get("description", "") if metadata else "",
                target_folder=relative_path,
            )
            timer.step("index")

            # Status
            training_count = self.classifier.get_training_count()
            self.training_label.setText(f"Gelernt: {training_count}")

            meta_info = f" + {len(metadata)} Metadaten" if metadata else ""
            rename_info = f" (umbenannt)" if name_changed else ""
            self.statusbar.showMessage(
                f"Verschoben nach '{relative_path}'{rename_info}{meta_info}", 3000
            )

            # UI aktualisieren
            self.config.add_to_last_used(folder_path)
            if not self._remove_pdf_widget_and_select_next(pdf_path):
                self.detail_panel.clear()
            timer.step("ui")
            self._refresh_after_move(folder_path, pdf_path.parent)
            timer.step("tree")
            # Phase 21: Automation-Regeln (Vorschlag im Statusbar)
            self._check_automation_rules(
                pdf_path, metadata=self.detail_panel.get_metadata()
            )
            timer.step("rules")
            # Phase 20: Korrespondenten aus Historie in Verwaltungstabelle sammeln
            self._auto_collect_korrespondenten()
            timer.step("korrespondenten")
            timer.done()

        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Verschieben fehlgeschlagen:\n{e}")

    def move_pdf_to_folder_and_learn(self, pdf_path: Path, folder_path: Path):
        """Verschiebt eine PDF und lernt aus der Entscheidung."""
        # Relativen Pfad für die Baumansicht berechnen
        relative_path = self.folder_tree.get_relative_path(folder_path)

        reply = QMessageBox.question(
            self,
            "PDF verschieben",
            f"PDF '{pdf_path.name}' nach '{relative_path}' verschieben?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                # Datei verschieben
                new_path = self.file_manager.move_file(pdf_path, folder_path)

                # Cache-Eintrag migrieren (behält LLM-Vorschläge bei)
                self.pdf_cache.migrate_cache_entry(pdf_path, new_path)

                # Undo-Eintrag erstellen
                self._push_undo({
                    "type": "move",
                    "moves": [(pdf_path, new_path)],
                    "description": f"{pdf_path.name} → {relative_path}",
                })

                # Aus der Entscheidung lernen (mit relativem Pfad)
                if self.selected_pdf_text:
                    self.classifier.learn(
                        pdf_path=pdf_path,
                        target_folder=folder_path,
                        extracted_text=self.selected_pdf_text,
                        keywords=self.selected_pdf_keywords,
                        relative_path=relative_path,  # NEU: Relativer Pfad
                    )
                    training_count = self.classifier.get_training_count()
                    self.training_label.setText(f"Gelernt: {training_count}")
                    self.statusbar.showMessage(
                        f"Verschoben nach '{relative_path}' und gelernt! ({training_count} Trainingsbeispiele)", 3000
                    )
                else:
                    self.statusbar.showMessage(f"Verschoben nach: {relative_path}", 3000)

                # Volltext-Suchindex befüllen (Phase 17)
                self.db.update_pdf_path(
                    old_path=str(pdf_path),
                    new_path=str(new_path),
                    new_filename=new_path.name,
                    extracted_text=self.selected_pdf_text or "",
                    keywords=", ".join(self.selected_pdf_keywords) if self.selected_pdf_keywords else "",
                    target_folder=relative_path,
                )

                # Zuletzt verwendet aktualisieren
                self.config.add_to_last_used(folder_path)

                # Nur das verschobene PDF-Widget entfernen (NICHT refresh_view!)
                self._remove_pdf_widget_and_select_next(pdf_path)

                # Ordneransicht aktualisieren (um PDF-Zähler zu aktualisieren)
                self._refresh_after_move(folder_path, pdf_path.parent)

                # Phase 21: Automation-Regeln (Vorschlag im Statusbar)
                self._check_automation_rules(pdf_path)
                # Phase 20: Korrespondenten aus Historie sammeln
                self._auto_collect_korrespondenten()

            except Exception as e:
                QMessageBox.critical(self, "Fehler", f"Verschieben fehlgeschlagen:\n{e}")

    def move_multiple_pdfs_to_folder(self, pdf_paths: list[Path], folder_path: Path):
        """Verschiebt mehrere PDFs in einen Zielordner."""
        relative_path = self.folder_tree.get_relative_path(folder_path)

        # Bestätigung
        reply = QMessageBox.question(
            self,
            "Mehrere PDFs verschieben",
            f"{len(pdf_paths)} PDFs nach '{relative_path}' verschieben?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        moved_count = 0
        moved_pdfs = []
        move_pairs = []  # (source, dest) für Undo
        errors = []
        original_selected = self.selected_pdf

        for pdf_path in pdf_paths:
            try:
                # Datei verschieben
                new_path = self.file_manager.move_file(pdf_path, folder_path)

                # Cache-Eintrag migrieren
                self.pdf_cache.migrate_cache_entry(pdf_path, new_path)

                moved_count += 1
                moved_pdfs.append(pdf_path)
                move_pairs.append((pdf_path, new_path))

                # Versuchen zu lernen (wenn PDF analysiert wurde)
                cached_result = self.pdf_cache.get(new_path)
                if cached_result and cached_result.extracted_text:
                    self.classifier.learn(
                        pdf_path=pdf_path,
                        target_folder=folder_path,
                        extracted_text=cached_result.extracted_text,
                        keywords=cached_result.keywords,
                        relative_path=relative_path,
                    )

            except Exception as e:
                errors.append(f"{pdf_path.name}: {e}")

        # Status aktualisieren
        training_count = self.classifier.get_training_count()
        self.training_label.setText(f"Gelernt: {training_count}")

        if moved_count > 0:
            self.statusbar.showMessage(
                f"{moved_count} PDFs nach '{relative_path}' verschoben", 3000
            )

        # Fehler anzeigen
        if errors:
            QMessageBox.warning(
                self,
                "Teilweise fehlgeschlagen",
                f"Einige Dateien konnten nicht verschoben werden:\n" + "\n".join(errors)
            )

        # Undo-Eintrag erstellen (nur wenn Dateien verschoben wurden)
        if move_pairs:
            if moved_count == 1:
                desc = f"{move_pairs[0][0].name} → {relative_path}"
            else:
                desc = f"{moved_count} PDFs → {relative_path}"
            self._push_undo({"type": "move", "moves": move_pairs, "description": desc})

        # Verschobene PDF-Widgets entfernen; Position der zuvor ausgewählten
        # PDF merken, um danach die nächste automatisch auszuwählen (Issue #75)
        selected_removed_index = None
        for moved_pdf in moved_pdfs:
            index = self.remove_pdf_widget(moved_pdf)
            if moved_pdf == original_selected:
                selected_removed_index = index

        # Auswahl zurücksetzen
        self.selected_pdfs = []
        auto_selected = False
        if selected_removed_index is not None and self.pdf_widgets:
            next_index = min(selected_removed_index, len(self.pdf_widgets) - 1)
            next_path = self.pdf_widgets[next_index].pdf_path
            self.on_pdf_clicked(next_path)
            auto_selected = True
        else:
            self.selected_pdf = None
            self.selected_pdf_text = None
            self.selected_pdf_keywords = None

        # Zuletzt verwendet aktualisieren
        self.config.add_to_last_used(folder_path)

        # Ordneransicht aktualisieren
        self._refresh_after_move(folder_path, *{p.parent for p in pdf_paths})

        # Vorschläge leeren (nur wenn keine Folge-PDF automatisch ausgewählt wurde)
        if not auto_selected:
            self.clear_suggestions()

    def on_pdf_double_clicked(self, pdf_path: Path):
        """Doppelklick auf ein Thumbnail: PDF öffnen (Vorschau oder extern)."""
        self.open_pdf(pdf_path)

    def _write_pdf_metadata(
        self,
        pdf_path: Path,
        new_name: str,
        keywords: list[str] = None,
        dialog_metadata: dict = None,
    ):
        """Schreibt Metadaten in die PDF-Datei (XMP + Info Dictionary)."""
        try:
            from src.core.pdf_metadata import PDFMetadata, write_metadata

            metadata = PDFMetadata()

            # Titel aus neuem Dateinamen (ohne .pdf)
            metadata.title = Path(new_name).stem.replace("_", " ").replace("-", " ")

            # Keywords aus Analyse
            if keywords:
                metadata.keywords = ", ".join(keywords)
                # Erste Kategorie als Subject (falls nicht aus Dialog)
                if not (dialog_metadata and dialog_metadata.get("subject")):
                    metadata.subject = keywords[0].capitalize()

            # Felder aus dem Dialog (LLM-Vorschläge, ggf. vom User editiert)
            if dialog_metadata:
                if dialog_metadata.get("subject"):
                    metadata.subject = dialog_metadata["subject"]
                if dialog_metadata.get("buchungsdatum"):
                    metadata.buchungsdatum = dialog_metadata["buchungsdatum"]
                if dialog_metadata.get("korrespondent"):
                    metadata.korrespondent = dialog_metadata["korrespondent"]
                if dialog_metadata.get("betrag_netto"):
                    metadata.betrag_netto = dialog_metadata["betrag_netto"]
                if dialog_metadata.get("betrag_brutto"):
                    metadata.betrag_brutto = dialog_metadata["betrag_brutto"]
                if dialog_metadata.get("iban"):
                    metadata.iban = dialog_metadata["iban"]
                if dialog_metadata.get("waehrung"):
                    metadata.waehrung = dialog_metadata["waehrung"]
                if dialog_metadata.get("mwst_satz"):
                    metadata.mwst_satz = dialog_metadata["mwst_satz"]
                if dialog_metadata.get("steuerjahr"):
                    metadata.steuerjahr = dialog_metadata["steuerjahr"]
                if dialog_metadata.get("description"):
                    metadata.description = dialog_metadata["description"]

            if metadata.has_any_data():
                success = write_metadata(pdf_path, metadata)
                if success:
                    print(f"Metadaten in {pdf_path.name} geschrieben: {metadata.to_dict()}")
                    self._metadaten_an_index(pdf_path, metadata)
                else:
                    print(f"Metadaten konnten nicht in {pdf_path.name} geschrieben werden")

        except ImportError:
            pass  # pikepdf nicht installiert - kein Fehler
        except Exception as e:
            print(f"Fehler beim Schreiben der PDF-Metadaten: {e}")

    def _metadaten_an_index(self, pdf_path: Path, metadata) -> None:
        """Nach dem Schreiben in die PDF: Inhalt neu lesen lassen und die PDFSM-Metadaten (Vorrang)
        in den Suchindex melden - beides ueber die Warteschlange, nie im GUI-Thread (Phase 5)."""
        try:
            index_melden("datei_geaendert", str(pdf_path))
            felder = {
                "korrespondent": metadata.korrespondent,
                "kategorie": metadata.subject,
                "steuerjahr": metadata.steuerjahr,
                "betrag": metadata.betrag_brutto or metadata.betrag,
                "buchungsdatum": metadata.buchungsdatum,
                "zusammenfassung": metadata.description,
                "schlagwoerter": metadata.keywords,
            }
            self.db.set_document_metadata(str(pdf_path), {k: v for k, v in felder.items() if v}, sofort=False)
        except Exception as e:  # noqa: BLE001 - der Index ist Zusatz, nie Blocker
            print(f"Suchindex: Metadaten nicht gemeldet: {e}")

    def _on_save_metadata_in_place(self):
        """Speichert Metadaten aus dem Detail-Panel in die PDF, ohne sie zu verschieben."""
        pdf_path = self.detail_panel.get_current_pdf()
        if not pdf_path or not pdf_path.exists():
            self.statusbar.showMessage("Keine PDF ausgewaehlt", 2000)
            return
        if ist_office_datei(pdf_path):
            self.statusbar.showMessage("Metadaten lassen sich nur in PDFs speichern - erst in PDF umwandeln", 4000)
            return

        metadata = self.detail_panel.get_metadata()
        if not metadata:
            self.statusbar.showMessage("Keine Metadaten eingegeben", 2000)
            return

        self._write_pdf_metadata(
            pdf_path,
            pdf_path.name,
            self.selected_pdf_keywords,
            metadata,
        )

        # Korrespondent-Zuordnung lernen
        if metadata.get("korrespondent"):
            self.db.learn_korrespondent_metadata(metadata["korrespondent"], metadata)

        self.detail_panel.mark_metadata_saved()
        self.statusbar.showMessage(
            f"Metadaten in '{pdf_path.name}' gespeichert", 3000
        )

    def _on_rename_and_save_metadata(self):
        """Benennt die PDF um (Dateiname aus Detail-Panel) und speichert Metadaten in-place."""
        pdf_path = self.detail_panel.get_current_pdf()
        if not pdf_path or not pdf_path.exists():
            self.statusbar.showMessage("Keine PDF ausgewaehlt", 2000)
            return
        if ist_office_datei(pdf_path):
            self.statusbar.showMessage("Metadaten lassen sich nur in PDFs speichern - erst in PDF umwandeln", 4000)
            return

        new_name = self.detail_panel.get_new_name()
        metadata = self.detail_panel.get_metadata()

        if not new_name:
            self.statusbar.showMessage("Kein Dateiname eingegeben", 2000)
            return

        name_changed = new_name != pdf_path.name

        try:
            if name_changed:
                new_path = self.file_manager.rename_file(pdf_path, new_name)
                self.pdf_cache.migrate_cache_entry(pdf_path, new_path)
                # Undo-Eintrag
                self._push_undo({
                    "type": "rename",
                    "old_path": pdf_path,
                    "new_path": new_path,
                    "description": f"{pdf_path.name} → {new_name}",
                })
                # Umbenennung lernen
                if self.selected_pdf_keywords:
                    self.db.add_rename_entry(
                        original_filename=pdf_path.name,
                        new_filename=new_path.name,
                        extracted_text=self.selected_pdf_text,
                        keywords=self.selected_pdf_keywords,
                        detected_date=None,
                    )
                self.selected_pdf = new_path
                self.detail_panel._current_pdf = new_path
                self.detail_panel.header_label.setText(f"Original: {new_path.name}")
            else:
                new_path = pdf_path

            if metadata:
                self._write_pdf_metadata(new_path, new_path.name, self.selected_pdf_keywords, metadata)
                if metadata.get("korrespondent"):
                    self.db.learn_korrespondent_metadata(metadata["korrespondent"], metadata)

            self.detail_panel.mark_metadata_saved()

            rename_info = f" und umbenannt zu '{new_name}'" if name_changed else ""
            self.statusbar.showMessage(
                f"Metadaten in '{new_path.name}' gespeichert{rename_info}", 3000
            )

            # Thumbnail-Widget aktualisieren falls umbenannt
            if name_changed:
                for widget in self.pdf_widgets:
                    if widget.pdf_path == pdf_path:
                        widget.pdf_path = new_path
                        widget.update_name_display()
                        break

        except Exception as e:
            QMessageBox.warning(self, "Fehler", f"Umbenennen/Speichern fehlgeschlagen:\n{e}")

    def _rename_selected_pdf(self):
        """F2-Shortcut: Öffnet den Umbenennungsdialog für die ausgewählte PDF."""
        if self.selected_pdf and self.selected_pdf.exists():
            self.on_pdf_rename(self.selected_pdf)
        else:
            self.statusbar.showMessage("Keine PDF ausgewählt zum Umbenennen", 2000)

    def on_pdf_rename(self, pdf_path: Path):
        """Wird aufgerufen wenn eine PDF umbenannt werden soll."""
        if ist_office_datei(pdf_path):
            self.statusbar.showMessage(
                "Word-/Excel-Dateien werden beim Verschieben umbenannt (Namensfeld rechts)", 4000)
            return
        from src.core.pdf_cache import get_pdf_cache

        # Prüfe ob gecachte LLM-Vorschläge vorhanden sind
        pdf_cache = get_pdf_cache()
        cached_llm = pdf_cache.get_llm_suggestions(pdf_path)

        if cached_llm:
            self.statusbar.showMessage("Verwende gecachte KI-Vorschläge...")
        else:
            self.statusbar.showMessage("Analysiere PDF für Umbenennung...")
        QApplication.processEvents()

        # PDF analysieren falls noch nicht geschehen
        extracted_text = None
        keywords = None
        dates = None

        # Erst aus Cache versuchen
        cached_result = pdf_cache.get(pdf_path)
        if cached_result:
            extracted_text = cached_result.extracted_text
            keywords = cached_result.keywords
            dates = cached_result.dates
        elif pdf_path == self.selected_pdf:
            # Bereits analysiert (lokale Variablen)
            extracted_text = self.selected_pdf_text
            keywords = self.selected_pdf_keywords
            dates = self.selected_pdf_dates
        else:
            # Neu analysieren
            try:
                from src.core.pdf_analyzer import PDFAnalyzer
                with PDFAnalyzer(pdf_path) as analyzer:
                    extracted_text = analyzer.extract_text()
                    keywords = analyzer.extract_keywords()
                    dates = analyzer.extract_dates()
            except Exception as e:
                print(f"Fehler bei PDF-Analyse: {e}")

        # Gelernte Muster aus Datenbank holen
        learned_patterns = []
        if keywords:
            rename_history = self.db.get_rename_suggestions_by_keywords(keywords, limit=3)
            for entry in rename_history:
                learned_patterns.append(RenameSuggestion(
                    name=entry.new_filename,
                    reason=f"Gelernt: ähnlich zu {entry.original_filename}",
                    confidence=0.7
                ))

        # Vorschläge generieren (lokal)
        suggestions = generate_rename_suggestions(
            pdf_path=pdf_path,
            extracted_text=extracted_text,
            keywords=keywords,
            dates=dates,
            learned_patterns=learned_patterns if learned_patterns else None
        )

        # Datum als String für Dialog und LLM
        detected_date_str = None
        if dates and len(dates) > 0:
            first_date = dates[0]
            if hasattr(first_date, 'strftime'):
                detected_date_str = first_date.strftime("%Y-%m-%d")
            else:
                detected_date_str = str(first_date)

        # Gecachte LLM-Vorschläge verwenden wenn vorhanden
        if cached_llm:
            for llm_s in cached_llm:
                suggestions.insert(0, RenameSuggestion(
                    name=llm_s.filename,
                    reason=f"KI (gecacht): Vorschlag",
                    confidence=llm_s.confidence,
                    metadata=getattr(llm_s, 'metadata', None),
                ))
        # Sonst: LLM-Vorschlag live holen wenn verfügbar
        elif self.hybrid_classifier.is_llm_available():
            self.statusbar.showMessage("Frage KI nach Vorschlag...")
            QApplication.processEvents()
            try:
                # Datei-Änderungsdatum als Fallback (Scandatum)
                from datetime import datetime
                file_mtime = pdf_path.stat().st_mtime
                file_date = datetime.fromtimestamp(file_mtime).strftime("%Y-%m-%d")

                llm_suggestions = self.hybrid_classifier.suggest_filename(
                    text=extracted_text or "",
                    current_filename=pdf_path.name,
                    keywords=keywords,
                    detected_date=detected_date_str,
                    use_llm=True,
                    file_date=file_date,
                    source_folder=source_folder_hint(pdf_path),
                )

                # LLM-Vorschläge zu den Suggestions hinzufügen
                for llm_s in llm_suggestions:
                    if llm_s.source == "llm":
                        suggestions.insert(0, RenameSuggestion(
                            name=llm_s.filename,
                            reason=f"KI: {llm_s.reason}",
                            confidence=llm_s.confidence,
                            metadata=llm_s.metadata,
                        ))
            except Exception as e:
                print(f"Fehler bei LLM-Vorschlag: {e}")

        # Dialog anzeigen
        dialog = RenameDialog(
            pdf_path=pdf_path,
            suggestions=suggestions,
            extracted_text=extracted_text,
            keywords=keywords,
            detected_date=detected_date_str,
            parent=self
        )

        if dialog.exec() == RenameDialog.DialogCode.Accepted:
            new_name = dialog.get_new_name()
            dialog_metadata = dialog.get_metadata()
            if new_name:
                try:
                    # Datei umbenennen
                    new_path = self.file_manager.rename_file(pdf_path, new_name)

                    # Cache-Eintrag migrieren (behält LLM-Vorschläge bei)
                    self.pdf_cache.migrate_cache_entry(pdf_path, new_path)

                    # Gewählten LLM-Vorschlag für neuen Pfad im Cache speichern
                    from src.core.pdf_cache import LLMSuggestion as CacheLLMSuggestion
                    chosen_conf = 0.85
                    for s in suggestions:
                        if (s.name or '').replace('.pdf', '') == new_name and "KI" in (s.reason or ''):
                            chosen_conf = s.confidence
                            break
                    self.pdf_cache.update_llm_suggestions(new_path, [CacheLLMSuggestion(
                        filename=new_path.name,
                        confidence=chosen_conf,
                        source="llm",
                        metadata=dialog_metadata,
                    )])
                    if self.detail_panel._current_pdf == pdf_path:
                        self.detail_panel._current_pdf = new_path
                        self.detail_panel.header_label.setText(f"Original: {new_path.name}")

                    # Metadaten in PDF schreiben (Phase 16)
                    self._write_pdf_metadata(new_path, new_name, keywords, dialog_metadata)

                    # Korrespondent-Metadaten lernen (für künftige Dokumente)
                    if dialog_metadata and dialog_metadata.get("korrespondent"):
                        self.db.learn_korrespondent_metadata(
                            dialog_metadata["korrespondent"], dialog_metadata
                        )

                    # Aus der Umbenennung lernen
                    detected_date = None
                    if dates and len(dates) > 0:
                        try:
                            first_date = dates[0]
                            if hasattr(first_date, 'strftime'):
                                detected_date = first_date.strftime("%Y-%m-%d")
                            else:
                                detected_date = str(first_date)
                        except Exception:
                            pass

                    self.db.add_rename_entry(
                        original_filename=pdf_path.name,
                        new_filename=new_path.name,
                        extracted_text=extracted_text,
                        keywords=keywords,
                        detected_date=detected_date,
                    )

                    # Undo-Eintrag für Umbenennung
                    self._push_undo({
                        "type": "rename",
                        "old_path": pdf_path,
                        "new_path": new_path,
                        "description": f"Umbenennung: {pdf_path.name} → {new_path.name}",
                    })

                    meta_info = ""
                    if dialog_metadata:
                        meta_info = f" + {len(dialog_metadata)} Metadaten"
                    self.statusbar.showMessage(
                        f"Umbenannt zu: {new_path.name} (gelernt{meta_info})", 3000
                    )
                    # Widget-Namen aktualisieren statt vollständigem Refresh
                    self._update_pdf_widget_path(pdf_path, new_path)

                except Exception as e:
                    QMessageBox.critical(self, "Fehler", f"Umbenennung fehlgeschlagen:\n{e}")

    def on_pdf_delete(self, pdf_path: Path):
        """Wird aufgerufen wenn eine PDF gelöscht werden soll."""
        self._datei_loeschen(pdf_path, "PDF löschen", "diese PDF", self.remove_pdf_widget)

    def _datei_loeschen(self, pdf_path: Path, titel: str, objekt: str, widget_entfernen):
        """Rueckfrage, Loeschen und Kachel entfernen - gemeinsam fuer PDFs und Office-Dateien.

        Verschiebt in den Papierkorb (Issue #124), mit Undo-Eintrag; ohne
        Papierkorb nur nach ausdruecklicher Rueckfrage endgueltig.
        """
        reply = QMessageBox.question(
            self,
            titel,
            f"Möchten Sie {objekt} in den Papierkorb verschieben?\n\n{pdf_path.name}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                try:
                    papierkorb = self.file_manager.delete_file(pdf_path)
                except PapierkorbNichtVerfuegbar:
                    antwort = QMessageBox.question(
                        self,
                        "Papierkorb nicht verfügbar",
                        f"Papierkorb nicht verfügbar – endgültig löschen?\n\n{pdf_path.name}",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if antwort != QMessageBox.StandardButton.Yes:
                        return
                    papierkorb = self.file_manager.delete_file(pdf_path, endgueltig=True)
                self.statusbar.showMessage(f"Gelöscht: {pdf_path.name}", 3000)
                if papierkorb is not None:
                    self._push_undo({
                        "type": "delete",
                        "original": pdf_path,
                        "papierkorb": papierkorb,
                        "description": f"Löschen: {pdf_path.name}",
                    })
                # Nur das gelöschte Widget entfernen
                widget_entfernen(pdf_path)
            except Exception as e:
                QMessageBox.critical(self, "Fehler", f"Löschen fehlgeschlagen:\n{e}")

    def on_pdf_move(self, pdf_path: Path):
        """Wird aufgerufen wenn eine PDF verschoben werden soll."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Zielordner auswählen",
        )

        if folder:
            try:
                new_path = self.file_manager.move_file(pdf_path, folder)
                self.statusbar.showMessage(f"Verschoben nach: {new_path.parent.name}", 3000)

                # Undo-Eintrag erstellen
                self._push_undo({
                    "type": "move",
                    "moves": [(pdf_path, new_path)],
                    "description": f"{pdf_path.name} → {new_path.parent.name}",
                })

                # Nur das verschobene PDF-Widget entfernen
                self._remove_pdf_widget_and_select_next(pdf_path)
                # Ordneransicht aktualisieren
                self._refresh_after_move(Path(folder), pdf_path.parent)
                # Phase 21: Automation-Regeln (Vorschlag im Statusbar)
                self._check_automation_rules(pdf_path)
                # Phase 20: Korrespondenten aus Historie sammeln
                self._auto_collect_korrespondenten()
            except Exception as e:
                QMessageBox.critical(self, "Fehler", f"Verschieben fehlgeschlagen:\n{e}")

    def on_pdf_copy(self, pdf_path: Path):
        """Erstellt eine Kopie der PDF im selben Verzeichnis mit Suffix '_kopie'."""
        try:
            import shutil
            # Neuen Dateinamen erstellen: name_kopie.pdf
            new_name = pdf_path.stem + "_kopie" + pdf_path.suffix
            new_path = pdf_path.parent / new_name

            # Falls Datei bereits existiert, nummerieren
            counter = 2
            while new_path.exists():
                new_name = f"{pdf_path.stem}_kopie_{counter}{pdf_path.suffix}"
                new_path = pdf_path.parent / new_name
                counter += 1

            # Datei kopieren
            shutil.copy2(pdf_path, new_path)
            index_melden("datei_aufnehmen", str(new_path))

            self.statusbar.showMessage(f"Kopie erstellt: {new_name}", 3000)

            # PDF-Ansicht aktualisieren um neue Datei anzuzeigen
            self.load_pdfs()

        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Kopieren fehlgeschlagen:\n{e}")

    def on_pdf_split(self, pdf_path: Path):
        """Wird aufgerufen wenn eine PDF getrennt werden soll."""
        from src.gui.split_pdf_dialog import SplitPDFDialog

        # Seitenanzahl ermitteln
        try:
            import fitz
            with fitz.open(str(pdf_path)) as doc:
                page_count = len(doc)
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"PDF konnte nicht geöffnet werden:\n{e}")
            return

        if page_count < 2:
            QMessageBox.information(
                self, "PDF trennen",
                f"'{pdf_path.name}' hat nur eine Seite und kann nicht getrennt werden."
            )
            return

        dialog = SplitPDFDialog(pdf_path, page_count, parent=self)
        if dialog.exec() != SplitPDFDialog.DialogCode.Accepted:
            return

        pages = dialog.get_pages()
        target_folder = pdf_path.parent

        try:
            output_files = self.file_manager.split_pdf(pdf_path, target_folder, pages)
            n = len(output_files)
            self.statusbar.showMessage(f"PDF getrennt: {n} Datei(en) erstellt", 4000)
            self.load_pdfs()
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"PDF trennen fehlgeschlagen:\n{e}")

    def on_pdf_merge(self):
        """Wird aufgerufen wenn ausgewählte PDFs zusammengefügt werden sollen."""
        pdfs_to_merge = [p for p in self.selected_pdfs if p.suffix.lower() == ".pdf"]
        if len(pdfs_to_merge) < 2:
            QMessageBox.information(
                self, "PDFs zusammenfügen",
                "Bitte mindestens 2 PDFs mit Ctrl+Klick auswählen."
            )
            return

        # Standard-Ausgabename vorschlagen
        first_stem = pdfs_to_merge[0].stem
        default_name = f"{first_stem}_zusammengefuegt.pdf"

        new_name, ok = QInputDialog.getText(
            self,
            "PDFs zusammenfügen",
            f"{len(pdfs_to_merge)} PDFs zusammenfügen.\n\nName der Zieldatei:",
            text=default_name,
        )

        if not ok or not new_name.strip():
            return

        new_name = new_name.strip()
        target_folder = pdfs_to_merge[0].parent

        try:
            merged_path = self.file_manager.merge_pdfs(pdfs_to_merge, target_folder, new_name)
            self.statusbar.showMessage(f"Zusammengefügt: {merged_path.name}", 4000)
            self.selected_pdfs = []
            self.load_pdfs()
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Zusammenfügen fehlgeschlagen:\n{e}")

    # --- Stapeln: PDF auf PDF ziehen (wie PaperPort) ---

    # Sicherungen fuer "Stapeln rueckgaengig" werden so lange aufbewahrt
    STACK_BACKUP_DAYS = 30

    def _stack_backup_root(self) -> Path:
        from src.utils.platform_paths import get_app_data_dir
        return get_app_data_dir() / "stapel_sicherung"

    def _prune_stack_backups(self):
        """Loescht Stapel-Sicherungen, die aelter als STACK_BACKUP_DAYS sind."""
        import shutil
        root = self._stack_backup_root()
        if not root.is_dir():
            return
        cutoff = time.time() - self.STACK_BACKUP_DAYS * 86400
        for entry in root.iterdir():
            try:
                if entry.is_dir() and entry.stat().st_mtime < cutoff:
                    shutil.rmtree(entry)
            except OSError as e:
                logging.getLogger(__name__).warning(
                    "Alte Stapel-Sicherung nicht entfernt: %s (%s)", entry, e
                )

    def on_pdf_stacked(self, sources: list, target: Path):
        """Haengt die auf eine PDF gezogenen PDFs an diese an - ohne Rueckfrage,
        rueckgaengig mit Ctrl+Z."""
        from datetime import datetime
        sources = [Path(s) for s in sources if Path(s) != target]
        if not sources:
            return
        self._wait_for_metadata_writes([target, *sources])

        backup_dir = self._stack_backup_root() / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        try:
            backups = self.file_manager.stack_pdfs(target, sources, backup_dir)
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Stapeln fehlgeschlagen:\n{e}")
            return
        self._prune_stack_backups()

        if len(sources) == 1:
            desc = f"{sources[0].name} an {target.name} angehängt"
        else:
            desc = f"{len(sources)} PDFs an {target.name} angehängt"
        self._push_undo({"type": "stack", "backups": backups, "description": desc})

        # Inhalt der Ziel-PDF hat sich geaendert: Analyse neu, Vorschau neu
        self.pdf_cache.clear_for_pdf(target)
        for original, _ in backups[1:]:
            self.pdf_cache.clear_for_pdf(original)
            self.remove_pdf_widget(original)
        for widget in self.pdf_widgets:
            if widget.pdf_path == target:
                widget.load_thumbnail()
                break
        # Stapel auswaehlen (ein Klick auf die schon gewaehlte PDF wuerde abwaehlen)
        if self.selected_pdf != target or self.selected_pdfs:
            self.on_pdf_clicked(target)
        self.statusbar.showMessage(f"{desc} (Ctrl+Z macht es rückgängig)", 5000)

    def _undo_stack_pdfs(self, entry: dict):
        """Macht ein Stapeln rueckgaengig."""
        backups = entry["backups"]
        target = backups[0][0]
        reply = QMessageBox.question(
            self, "Rückgängig machen",
            f"Stapeln rückgängig machen?\n\n{entry['description']}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self.file_manager.restore_stack(backups)
        except Exception as e:
            QMessageBox.critical(
                self, "Fehler", f"Stapeln konnte nicht rückgängig gemacht werden:\n{e}"
            )
            return
        finally:
            self._undo_stack.pop()
            self._update_undo_ui()

        for original, _ in backups:
            self.pdf_cache.clear_for_pdf(original)
        self.statusbar.showMessage(f"Rückgängig: {entry['description']}", 3000)
        self.load_pdfs()

    # --- Drehen und OCR neu (Issue #150) ---

    def _aktion_ziele(self, pdf_path: Path) -> list[Path]:
        """Gehoert die Kachel zur Mehrfachauswahl, gilt die Aktion fuer alle markierten PDFs."""
        if len(self.selected_pdfs) > 1 and pdf_path in self.selected_pdfs:
            ziele = list(self.selected_pdfs)
        else:
            ziele = [pdf_path]
        return [p for p in ziele if p.suffix.lower() == ".pdf"]  # Office-Dateien in der Auswahl auslassen

    def on_pdf_rotate(self, pdf_path: Path, grad: int):
        """Kontextmenue "Drehen": ganze PDF(s) verlustfrei drehen."""
        self._rotate_pdfs(self._aktion_ziele(pdf_path), grad)

    def _rotate_pdfs(self, paths: list[Path], grad: int, undo: bool = True) -> list[Path]:
        """Dreht die PDFs um ``grad`` (im Uhrzeigersinn) und frischt Kachel, Vorschau und Index auf.

        Mit ``undo`` kommt ein Eintrag mit der Gegenrotation auf den
        Rueckgaengig-Stapel. Liefert die gedrehten Pfade.
        """
        gedreht: list[Path] = []
        fehler: list[str] = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for path in paths:
                try:
                    rotate_pdf(path, grad)
                except DrehenNichtMoeglich as e:
                    fehler.append(f"{path.name}: {e}")
                    continue
                except PermissionError:
                    fehler.append(f"{path.name}: Die Datei ist geöffnet oder gesperrt.")
                    continue
                except Exception as e:  # noqa: BLE001 - je Datei melden
                    fehler.append(f"{path.name}: {e}")
                    continue
                gedreht.append(path)
                self._pdf_inhalt_geaendert(path)
        finally:
            QApplication.restoreOverrideCursor()

        richtung = {90: "90° nach rechts", -90: "90° nach links", 270: "90° nach links", 180: "180°"}[grad]
        wer = gedreht[0].name if len(gedreht) == 1 else f"{len(gedreht)} PDFs"
        if gedreht and undo:
            self._push_undo({
                "type": "rotate",
                "paths": list(gedreht),
                "grad": grad,
                "description": f"{wer} {richtung} gedreht",
            })
            self.statusbar.showMessage(f"{wer} {richtung} gedreht (Ctrl+Z macht es rückgängig)", 5000)
        if fehler:
            QMessageBox.warning(self, "Drehen", "Nicht gedreht:\n\n" + "\n".join(fehler))
        return gedreht

    def _undo_rotate(self, entry: dict):
        """Dreht die PDFs zurueck (Gegenrotation)."""
        self._undo_stack.pop()
        self._update_undo_ui()
        vorhanden = [p for p in entry["paths"] if Path(p).exists()]
        fehlen = len(entry["paths"]) - len(vorhanden)
        if vorhanden:
            self._rotate_pdfs(vorhanden, gegenrichtung(entry["grad"]), undo=False)
        text = f"Rückgängig: {entry['description']}"
        if fehlen:
            text += f" ({fehlen} PDF(s) nicht mehr am alten Ort)"
        self.statusbar.showMessage(text, 5000)

    # --- Gerade ausrichten (Issue #165) ---

    def on_pdf_straighten(self, pdf_path: Path):
        """Kontextmenue "Drehen > Gerade ausrichten": schief gescannte Seiten gerade drehen."""
        self._straighten_pdfs(self._aktion_ziele(pdf_path))

    def _straighten_pdfs(self, paths: list[Path]) -> dict[Path, dict[int, float]]:
        """Misst die Seiten, richtet schiefe gerade aus und frischt Kachel, Vorschau und Index auf.

        Messen und Schreiben dauern je Seite nur Bruchteile einer Sekunde (wie
        beim Drehen ohne eigenen Thread). Ausgerichtete PDFs kommen mit ihren
        Seiten auf den Rueckgaengig-Stapel. Liefert ``{pfad: {seite: winkel}}``.
        """
        ausgerichtet: dict[Path, dict[int, float]] = {}
        schon_gerade = 0
        fehler: list[str] = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for path in paths:
                try:
                    winkel = gerade_ausrichten(path)
                except DrehenNichtMoeglich as e:
                    fehler.append(f"{path.name}: {e}")
                    continue
                except PermissionError:
                    fehler.append(f"{path.name}: Die Datei ist geöffnet oder gesperrt.")
                    continue
                except Exception as e:  # noqa: BLE001 - je Datei melden
                    fehler.append(f"{path.name}: {e}")
                    continue
                if not winkel:
                    schon_gerade += 1
                    continue
                ausgerichtet[path] = winkel
                self._pdf_inhalt_geaendert(path)
        finally:
            QApplication.restoreOverrideCursor()

        if ausgerichtet:
            erste = next(iter(ausgerichtet))
            if len(ausgerichtet) == 1:
                wer = erste.name
                was = ", ".join(f"S. {s}: {f'{abs(w):.1f}'.replace('.', ',')}°"
                                for s, w in sorted(ausgerichtet[erste].items()))
            else:
                wer = f"{len(ausgerichtet)} PDFs"
                was = f"{sum(len(w) for w in ausgerichtet.values())} Seiten"
            self._push_undo({
                "type": "gerade",
                "seiten": {p: sorted(w) for p, w in ausgerichtet.items()},
                "description": f"{wer} gerade ausgerichtet",
            })
            text = f"{wer} gerade ausgerichtet ({was})"
            if schon_gerade:
                text += f", {schon_gerade} PDF(s) waren schon gerade"
            self.statusbar.showMessage(text + " – Ctrl+Z macht es rückgängig", 6000)
        elif not fehler:
            self.statusbar.showMessage("Keine schief gescannte Seite gefunden – nichts geändert.", 5000)
        if fehler:
            QMessageBox.warning(self, "Gerade ausrichten", "Nicht ausgerichtet:\n\n" + "\n".join(fehler))
        return ausgerichtet

    def _undo_gerade(self, entry: dict):
        """Nimmt die Ausrichtung wieder heraus (die Seiten stehen danach wie vorher)."""
        self._undo_stack.pop()
        self._update_undo_ui()
        nicht = 0
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for path, seiten in entry["seiten"].items():
                path = Path(path)
                try:
                    ok = path.exists() and bool(ausrichtung_zuruecknehmen(path, seiten))
                except Exception:  # noqa: BLE001 - je Datei zaehlen
                    ok = False
                if ok:
                    self._pdf_inhalt_geaendert(path)
                else:
                    nicht += 1
        finally:
            QApplication.restoreOverrideCursor()
        text = f"Rückgängig: {entry['description']}"
        if nicht:
            text += f" ({nicht} PDF(s) nicht mehr möglich)"
        self.statusbar.showMessage(text, 5000)

    def _pdf_inhalt_geaendert(self, path: Path):
        """Nach einer Aenderung am Inhalt (Drehen): Thumbnail, Analyse, Vorschau und Index auffrischen."""
        thumbnail_vergessen(path)
        widget = self._pdf_widget_for(path)
        if widget is not None:
            widget.load_thumbnail()
        self.pdf_cache.clear_for_pdf(path)
        index_melden("datei_geaendert", str(path))
        if self._preview_window is not None and self._preview_window.current_path() == path:
            self._preview_window.show_pdf(path)
        if self.selected_pdf == path and not self.selected_pdfs:
            if self.detail_panel.has_user_edits():
                # Eingaben des Nutzers nicht verwerfen: nur die Vorschau neu laden
                self.detail_panel.preview.load_pdf(path)
            else:
                self.update_suggestions_for_pdf(path)

    def on_pdf_reocr(self, pdf_path: Path):
        """Kontextmenue "OCR neu durchführen"."""
        self._reocr_pdfs(self._aktion_ziele(pdf_path))

    def _reocr_pdfs(self, paths: list[Path]):
        """Startet die neue Texterkennung im Hintergrund (Wartezeiger, Kacheln "Analysiere…")."""
        if self._ocr_neu_worker is not None:
            self.statusbar.showMessage("Die Texterkennung läuft noch - bitte warten.", 4000)
            return
        self._ocr_neu_paths = list(paths)
        for path in paths:
            widget = self._pdf_widget_for(path)
            if widget is not None:
                widget.analyzing = True
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        self.statusbar.showMessage(f"Texterkennung neu: {len(paths)} PDF(s)…")
        worker = OcrNeuWorker(paths, self)
        worker.fortschritt.connect(self._on_reocr_progress)
        worker.fertig.connect(self._on_reocr_done)
        self._ocr_neu_worker = worker
        worker.start()

    def _on_reocr_progress(self, nummer: int, anzahl: int, path: Path):
        self.statusbar.showMessage(f"Texterkennung neu ({nummer}/{anzahl}): {path.name}…")

    def _on_reocr_done(self, ergebnisse: list):
        """Ergebnis der neuen Texterkennung: Analysen verwerfen, ausgewaehlte PDF neu laden."""
        self._ocr_neu_worker = None
        QApplication.restoreOverrideCursor()
        for path in self._ocr_neu_paths:
            widget = self._pdf_widget_for(path)
            if widget is not None:
                widget.analyzing = False
        self._ocr_neu_paths = []
        fehler = []
        seiten = 0
        gedreht = 0
        for path, erg in ergebnisse:
            self.pdf_cache.clear_for_pdf(path)
            seiten += int(erg.get("seiten") or 0)
            gedreht += int(erg.get("gedreht") or 0)
            if erg.get("fehler"):
                fehler.append(f"{path.name}: {erg['fehler']}")
        if self.selected_pdf is not None and not self.selected_pdfs and any(
            path == self.selected_pdf for path, _ in ergebnisse
        ):
            self.update_suggestions_for_pdf(self.selected_pdf)
        text = f"Texterkennung neu: {len(ergebnisse)} PDF(s)"
        if seiten:
            text += f", {seiten} Seite(n) erkannt"
        if gedreht:
            # Issue #151: die Datei dreht der naechste Indexlauf (je nach Einstellung)
            text += f", {gedreht} davon erst gedreht lesbar"
        self.statusbar.showMessage(text, 6000)
        if fehler:
            QMessageBox.warning(self, "OCR neu durchführen", "\n".join(fehler))

    # --- Undo-Funktionalität ---

    def _push_undo(self, entry: dict):
        """Fügt einen Eintrag zum Undo-Stack hinzu."""
        self._undo_stack.append(entry)
        # Maximal 20 Einträge behalten
        if len(self._undo_stack) > 20:
            self._undo_stack.pop(0)
        self._update_undo_ui()

    def _update_undo_ui(self):
        """Aktualisiert den Zustand der Undo-Buttons und Menüeinträge."""
        has_undo = len(self._undo_stack) > 0
        if has_undo:
            desc = self._undo_stack[-1]["description"]
            text = f"Rückgängig: {desc}"
            self.undo_action.setText(text)
            self.undo_action.setEnabled(True)
            self.undo_toolbar_action.setText(f"↩ Rückgängig")
            self.undo_toolbar_action.setToolTip(f"Rückgängig: {desc} (Ctrl+Z)")
            self.undo_toolbar_action.setEnabled(True)
        else:
            self.undo_action.setText("Rückgängig")
            self.undo_action.setEnabled(False)
            self.undo_toolbar_action.setText("↩ Rückgängig")
            self.undo_toolbar_action.setToolTip("Keine Aktion zum Rückgängig machen")
            self.undo_toolbar_action.setEnabled(False)

    def undo_last_action(self):
        """Macht die letzte Aktion (Verschiebung oder Umbenennung) rückgängig."""
        if not self._undo_stack:
            return

        entry = self._undo_stack[-1]
        entry_type = entry.get("type", "move")

        if entry_type == "rename":
            self._undo_rename(entry)
        elif entry_type == "stack":
            self._undo_stack_pdfs(entry)
        elif entry_type == "rotate":
            self._undo_rotate(entry)
        elif entry_type == "gerade":
            self._undo_gerade(entry)
        elif entry_type == "delete":
            self._undo_delete(entry)
        else:
            self._undo_move(entry)

    def _undo_delete(self, entry: dict):
        """Holt eine gelöschte Datei aus dem Papierkorb zurück."""
        import shutil
        original = Path(entry["original"])
        papierkorb = Path(entry["papierkorb"])
        self._undo_stack.pop()
        self._update_undo_ui()
        if not papierkorb.exists():
            QMessageBox.warning(
                self, "Rückgängig nicht möglich",
                f"'{original.name}' ist nicht mehr im Papierkorb.\n\n"
                "Möglicherweise wurde der Papierkorb geleert oder die Datei wiederhergestellt."
            )
            return
        if original.exists():
            QMessageBox.warning(
                self, "Rückgängig nicht möglich",
                f"Am ursprünglichen Ort existiert bereits eine Datei '{original.name}'."
            )
            return
        try:
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(papierkorb), str(original))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Rückgängig fehlgeschlagen", f"{original.name}:\n{e}")
            return
        index_melden("datei_aufnehmen", str(original))
        self.statusbar.showMessage(f"Rückgängig: {entry['description']}", 3000)
        self.refresh_view()

    def _undo_rename(self, entry: dict):
        """Macht eine Umbenennung rückgängig."""
        old_path = entry["old_path"]  # Originaler Pfad
        new_path = entry["new_path"]  # Aktueller Pfad (nach Umbenennung)
        desc = entry["description"]

        # Prüfen ob die Datei noch am neuen Ort existiert
        if not new_path.exists():
            QMessageBox.warning(
                self, "Rückgängig nicht möglich",
                f"Die Datei '{new_path.name}' wurde nicht gefunden.\n\n"
                "Möglicherweise wurde sie bereits manuell umbenannt oder gelöscht."
            )
            self._undo_stack.pop()
            self._update_undo_ui()
            return

        # Prüfen ob der alte Name schon vergeben ist
        if old_path.exists():
            QMessageBox.warning(
                self, "Rückgängig nicht möglich",
                f"Eine Datei mit dem Namen '{old_path.name}' existiert bereits."
            )
            self._undo_stack.pop()
            self._update_undo_ui()
            return

        # Bestätigung
        reply = QMessageBox.question(
            self, "Umbenennung rückgängig",
            f"Umbenennung rückgängig machen?\n\n"
            f"'{new_path.name}'\n→ '{old_path.name}'",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            # Datei zurückbenennen
            restored_path = self.file_manager.rename_file(new_path, old_path.name)

            # Cache-Eintrag migrieren
            self.pdf_cache.migrate_cache_entry(new_path, restored_path)

            # Undo-Eintrag entfernen
            self._undo_stack.pop()
            self._update_undo_ui()

            self.statusbar.showMessage(f"Rückgängig: {old_path.name}", 3000)

            # Widget-Namen aktualisieren
            self._update_pdf_widget_path(new_path, restored_path)

        except Exception as e:
            QMessageBox.critical(
                self, "Fehler",
                f"Umbenennung konnte nicht rückgängig gemacht werden:\n{e}"
            )

    def _undo_move(self, entry: dict):
        """Macht eine Verschiebe-Aktion rückgängig."""
        moves = entry["moves"]
        desc = entry["description"]

        # Laufende Hintergrund-Schreibvorgaenge (XMP) erst abschliessen lassen
        self._wait_for_metadata_writes([dest for _, dest in moves])

        # Prüfen ob alle Dateien noch existieren (am Zielort)
        missing = [dest for _, dest in moves if not dest.exists()]
        if missing:
            names = "\n".join(p.name for p in missing)
            QMessageBox.warning(
                self, "Rückgängig nicht möglich",
                f"Folgende Dateien wurden am Zielort nicht mehr gefunden:\n{names}\n\n"
                "Möglicherweise wurden sie bereits manuell verschoben oder gelöscht."
            )
            # Eintrag trotzdem entfernen, da ungültig
            self._undo_stack.pop()
            self._update_undo_ui()
            return

        # Bestätigung
        if len(moves) == 1:
            source, dest = moves[0]
            msg = f"Datei zurückverschieben?\n\n{dest.name}\nvon: {dest.parent}\nnach: {source.parent}"
        else:
            msg = f"{len(moves)} Dateien zurückverschieben?\n\nVon: {moves[0][1].parent}\nNach: {moves[0][0].parent}"

        reply = QMessageBox.question(
            self, "Rückgängig machen",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Dateien zurückverschieben
        import shutil
        restored = 0
        errors = []

        for source_orig, dest_path in moves:
            try:
                # Zurück zum ursprünglichen Ordner verschieben
                target_dir = source_orig.parent
                if not target_dir.exists():
                    target_dir.mkdir(parents=True, exist_ok=True)
                restored_path = target_dir / dest_path.name
                shutil.move(str(dest_path), str(restored_path))
                index_melden("datei_verschoben", str(dest_path), str(restored_path))
                restored += 1
            except Exception as e:
                errors.append(f"{dest_path.name}: {e}")

        # Undo-Eintrag entfernen
        self._undo_stack.pop()
        self._update_undo_ui()

        if errors:
            QMessageBox.warning(
                self, "Teilweise fehlgeschlagen",
                f"{restored} von {len(moves)} Dateien zurückverschoben.\n\n"
                f"Fehler:\n" + "\n".join(errors)
            )
        else:
            if restored == 1:
                self.statusbar.showMessage(f"Rückgängig: {desc}", 3000)
            else:
                self.statusbar.showMessage(f"Rückgängig: {restored} Dateien zurückverschoben", 3000)

        # Ansichten aktualisieren
        self.load_pdfs()
        self.load_folders()

    def on_batch_rename(self):
        """
        Benennt alle ausgewählten PDFs automatisch mit LLM-Vorschlägen um.
        """
        if len(self.selected_pdfs) < 2:
            QMessageBox.information(
                self, "Batch-Umbenennung",
                "Bitte mindestens 2 PDFs mit Ctrl+Klick auswählen."
            )
            return

        # Prüfen ob LLM verfügbar ist
        from src.ml.hybrid_classifier import get_hybrid_classifier
        classifier = get_hybrid_classifier()
        if not classifier.is_llm_available():
            QMessageBox.warning(
                self, "LLM nicht verfügbar",
                "Für die automatische Umbenennung wird ein LLM benötigt.\n"
                "Bitte konfigurieren Sie einen LLM-Provider unter Extras → Einstellungen."
            )
            return

        # Bestätigung anfordern
        reply = QMessageBox.question(
            self,
            "Batch-Umbenennung",
            f"{len(self.selected_pdfs)} PDFs automatisch mit LLM umbenennen?\n\n"
            "Die PDFs werden analysiert und mit dem besten LLM-Vorschlag umbenannt.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Fortschritts-Dialog erstellen
        from PyQt6.QtWidgets import QProgressDialog
        progress = QProgressDialog(
            "Batch-Umbenennung läuft...", "Abbrechen", 0, len(self.selected_pdfs), self
        )
        progress.setWindowTitle("Automatische Umbenennung")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        renamed_count = 0
        skipped_count = 0
        error_count = 0
        pdfs_to_process = [p for p in self.selected_pdfs if p.suffix.lower() == ".pdf"]  # Office-Dateien auslassen

        for i, pdf_path in enumerate(pdfs_to_process):
            if progress.wasCanceled():
                break

            progress.setValue(i)
            progress.setLabelText(f"Verarbeite: {pdf_path.name}")
            QApplication.processEvents()

            try:
                # Prüfen ob PDF noch existiert
                if not pdf_path.exists():
                    skipped_count += 1
                    continue

                # PDF-Analyse aus Cache oder neu
                analysis = self.pdf_cache.get(pdf_path)
                if not analysis:
                    # Synchron analysieren
                    from src.core.pdf_analyzer import PDFAnalyzer
                    with PDFAnalyzer(pdf_path) as analyzer:
                        extracted_text = analyzer.extract_text()
                        keywords = analyzer.extract_keywords()
                        dates = analyzer.extract_dates()
                else:
                    extracted_text = analysis.extracted_text
                    keywords = analysis.keywords
                    dates = analysis.dates

                # Datum für Dateinamen
                detected_date = None
                if dates:
                    try:
                        first_date = dates[0]
                        if hasattr(first_date, 'strftime'):
                            detected_date = first_date.strftime("%Y-%m-%d")
                        else:
                            detected_date = str(first_date)
                    except Exception:
                        pass

                # Datei-Änderungsdatum als Fallback
                from datetime import datetime as dt
                file_mtime = pdf_path.stat().st_mtime
                file_date = dt.fromtimestamp(file_mtime).strftime("%Y-%m-%d")

                # LLM-Vorschlag abrufen
                suggestions = classifier.suggest_filename(
                    text=extracted_text or "",
                    current_filename=pdf_path.name,
                    keywords=keywords,
                    detected_date=detected_date,
                    use_llm=True,
                    file_date=file_date,
                    source_folder=source_folder_hint(pdf_path),
                )

                # Besten LLM-Vorschlag finden
                llm_suggestion = None
                for s in suggestions:
                    if s.source == "llm" and s.confidence > 0.5:
                        llm_suggestion = s
                        break

                if not llm_suggestion:
                    skipped_count += 1
                    continue

                new_name = llm_suggestion.filename

                # Prüfen ob der Name sich tatsächlich ändert
                if new_name == pdf_path.name:
                    skipped_count += 1
                    continue

                # Datei umbenennen
                new_path = self.file_manager.rename_file(pdf_path, new_name)

                # Cache migrieren
                self.pdf_cache.migrate_cache_entry(pdf_path, new_path)

                # Metadaten in PDF schreiben (Phase 16)
                self._write_pdf_metadata(
                    new_path, new_name, keywords, llm_suggestion.metadata
                )

                # Korrespondent-Metadaten lernen (für künftige Dokumente)
                if llm_suggestion.metadata and llm_suggestion.metadata.get("korrespondent"):
                    self.db.learn_korrespondent_metadata(
                        llm_suggestion.metadata["korrespondent"], llm_suggestion.metadata
                    )

                # Widget aktualisieren
                self._update_pdf_widget_path(pdf_path, new_path)

                # In selected_pdfs aktualisieren
                if pdf_path in self.selected_pdfs:
                    self.selected_pdfs.remove(pdf_path)
                    self.selected_pdfs.append(new_path)

                renamed_count += 1

            except Exception as e:
                print(f"Batch-Rename Fehler für {pdf_path.name}: {e}")
                error_count += 1

        progress.setValue(len(pdfs_to_process))
        progress.close()

        # Ergebnis anzeigen
        result_msg = f"Batch-Umbenennung abgeschlossen:\n\n"
        result_msg += f"✓ Umbenannt: {renamed_count}\n"
        if skipped_count > 0:
            result_msg += f"○ Übersprungen: {skipped_count}\n"
        if error_count > 0:
            result_msg += f"✗ Fehler: {error_count}"

        QMessageBox.information(self, "Batch-Umbenennung", result_msg)

        # Auswahl aufheben
        self.selected_pdfs = []
        for widget in self.pdf_widgets:
            widget.selected = False

    # === Ordner-Aktionen ===

    # --- Ordner-Navigation ---

    def handle_external_path(self, external_path: str):
        """
        Wird vom SingleInstanceServer aufgerufen, wenn ein zweiter
        Programmstart einen Pfad uebergibt (z.B. aus dem Explorer-
        Kontextmenue). Akzeptiert einen Ordner ODER eine .pdf-Datei.

        - Ordner: Scan-Ordner wechseln.
        - PDF-Datei: enthaltenden Ordner setzen, die Datei selektieren
          und direkt den Rename-Dialog (inkl. LLM-Vorschlag) oeffnen.
        """
        # Fenster nach vorne holen.
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

        if not external_path:
            return
        try:
            p = Path(external_path)
        except OSError:
            return
        if not p.exists():
            return

        if p.is_dir():
            self._navigate_to_folder(p.resolve())
            return

        if p.is_file() and p.suffix.lower() == ".pdf":
            pdf = p.resolve()
            parent = pdf.parent

            # Nur wechseln, wenn wir noch nicht im richtigen Ordner sind
            # (vermeidet unnoetiges Neuladen aller PDFs).
            current = self.config.get_scan_folder()
            if not current or Path(current).resolve() != parent:
                self._navigate_to_folder(parent)

            # Auto-Selektion + Rename-Dialog leicht verzoegert, damit
            # load_pdfs() die Widgets erstellt hat und das UI rendern
            # kann, bevor der modale Dialog erscheint.
            QTimer.singleShot(
                150,
                lambda path=pdf: self._select_pdf_and_open_rename(path),
            )

    def _select_pdf_and_open_rename(self, pdf_path: Path):
        """
        Hilfsmethode fuer handle_external_path: selektiert eine PDF
        im Thumbnail-Grid und oeffnet danach den Umbenennungsdialog.
        """
        if not pdf_path.exists():
            return
        # Pruefen ob die PDF tatsaechlich im aktuellen Ordner ist
        # (z.B. weil load_pdfs noch nicht durch ist).
        found = any(w.pdf_path == pdf_path for w in self.pdf_widgets)
        if not found:
            # Nochmal kurz warten und erneut versuchen.
            QTimer.singleShot(
                200,
                lambda: self._select_pdf_and_open_rename(pdf_path),
            )
            return
        self.on_pdf_clicked(pdf_path)
        # Rename-Dialog im naechsten Event-Loop-Durchgang oeffnen,
        # damit das Selektions-Highlight schon sichtbar ist.
        QTimer.singleShot(0, lambda: self.on_pdf_rename(pdf_path))

    def _navigate_to_folder(self, folder_path: Path, add_to_history: bool = True):
        """Zentrale Methode zum Wechseln des Scan-Ordners mit History-Tracking."""
        current = self.config.get_scan_folder()
        if current and add_to_history:
            current_path = Path(current)
            if current_path != folder_path:
                self._folder_history.append(current_path)
                # Maximal 50 Einträge behalten
                if len(self._folder_history) > 50:
                    self._folder_history.pop(0)

        self.config.set_scan_folder(str(folder_path))
        self.file_manager.set_scan_folder(str(folder_path))
        self.load_pdfs()
        self._update_navigation_buttons()

    def _update_navigation_buttons(self):
        """Aktualisiert den Zustand des Zurück-Buttons."""
        has_history = len(self._folder_history) > 0
        self.navigate_back_btn.setEnabled(has_history)
        if has_history:
            prev = self._folder_history[-1]
            self.navigate_back_btn.setToolTip(f"Zurück zu: {prev.name} (Alt+Left)")
        else:
            self.navigate_back_btn.setToolTip("Kein vorheriger Ordner")

    def on_navigate_back(self):
        """Navigiert zum vorherigen Scan-Ordner aus der History."""
        if not self._folder_history:
            self.statusbar.showMessage("Kein vorheriger Ordner in der History", 2000)
            return

        previous_folder = self._folder_history.pop()

        if previous_folder.exists():
            self._navigate_to_folder(previous_folder, add_to_history=False)
            self.statusbar.showMessage(f"Zurück zu: {previous_folder.name}", 3000)
        else:
            self.statusbar.showMessage(f"Ordner existiert nicht mehr: {previous_folder}", 3000)
            self._update_navigation_buttons()

    def on_folder_clicked(self, folder_path: Path):
        """Wird aufgerufen wenn ein Ordner angeklickt wird."""
        # Wenn eine PDF ausgewählt ist, diese verschieben
        if self.selected_pdf:
            self.move_selected_pdf_to_folder(folder_path)

    def on_parent_tile_clicked(self, folder_path: Path):
        """Einfachklick auf die ".."-Kachel: eine Ebene nach oben (Issue #50).

        Zeitfenster-Guard: Nach dem Wechsel wird das Raster neu aufgebaut und
        die neue ".."-Kachel liegt an derselben Stelle - der zweite Klick eines
        Doppelklicks wuerde sonst gleich zwei Ebenen nach oben springen.
        """
        now = time.monotonic()
        last = getattr(self, "_last_parent_tile_click", 0.0)
        if (now - last) * 1000 < QApplication.doubleClickInterval():
            return
        self._last_parent_tile_click = now
        self.on_folder_tile_double_clicked(folder_path)

    def on_folder_tile_double_clicked(self, folder_path: Path):
        """Doppelklick auf eine Ordner-Kachel im Scan-Bereich: hineinwechseln."""
        if not folder_path.exists():
            self.statusbar.showMessage(f"Ordner existiert nicht mehr: {folder_path}", 3000)
            self.load_pdfs()
            return
        self._navigate_to_folder(folder_path)
        self.statusbar.showMessage(f"Ordner geöffnet: {folder_path.name}", 3000)

    def _update_breadcrumb(self, folder: Optional[Path]):
        """Baut den klickbaren Pfad zum aktuellen Scan-Ordner neu auf."""
        while self.breadcrumb_layout.count() > 1:  # letzter Eintrag ist der Stretch
            item = self.breadcrumb_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not folder:
            return
        parts = list(Path(folder).parts)
        max_parts = 5
        start = max(0, len(parts) - max_parts)
        pos = 0
        if start > 0:
            ellipsis = QLabel("…")
            ellipsis.setStyleSheet("color: #888; padding: 0 2px;")
            self.breadcrumb_layout.insertWidget(pos, ellipsis)
            pos += 1
        for i in range(start, len(parts)):
            target = Path(*parts[: i + 1])
            is_last = i == len(parts) - 1
            btn = QToolButton()
            btn.setAutoRaise(True)
            btn.setText(parts[i].rstrip("\\/") or parts[i])
            btn.setToolTip(str(target))
            btn.setEnabled(not is_last)
            btn.setStyleSheet(
                "QToolButton { padding: 1px 4px; font-size: 11px; }"
                + (" QToolButton:disabled { color: #222; font-weight: bold; }" if is_last else "")
            )
            btn.clicked.connect(lambda _=False, p=target: self.on_folder_tile_double_clicked(p))
            self.breadcrumb_layout.insertWidget(pos, btn)
            pos += 1
            if not is_last:
                sep = QLabel("›")
                sep.setStyleSheet("color: #999;")
                self.breadcrumb_layout.insertWidget(pos, sep)
                pos += 1

    def on_folder_double_clicked(self, folder_path: Path):
        """Wird aufgerufen wenn ein Ordner doppelgeklickt wird."""
        self._navigate_to_folder(folder_path)
        self.statusbar.showMessage(f"Scan-Ordner gewechselt: {folder_path.name}", 3000)

    def on_tree_folder_selected(self, folder_path: Path):
        """Wird aufgerufen wenn ein Ordner in der Baumansicht ausgewählt wird."""
        # Multi-Selektion: Mehrere PDFs verschieben
        if len(self.selected_pdfs) > 1:
            self.move_multiple_pdfs_to_folder(self.selected_pdfs, folder_path)
        elif self.selected_pdf:
            self._move_rename_and_learn(self.selected_pdf, folder_path)

    def on_tree_folder_renamed(self, old: Path, new: Path):
        """Zieht gespeicherte Zielordner nach, wenn ein Ordner im Baum umbenannt wurde."""
        for folder in self.config.get_target_folders():
            if folder == old or old in folder.parents:
                moved = new / folder.relative_to(old)
                self.config.remove_target_folder(folder)
                self.config.add_target_folder(moved)
                self.folder_manager.remove_folder(folder)
                self.folder_manager.add_folder(moved)
        self.statusbar.showMessage(f"Ordner umbenannt: {old.name} -> {new.name}", 3000)

    def on_tree_folder_double_clicked(self, folder_path: Path):
        """Wird aufgerufen wenn ein Ordner in der Baumansicht doppelgeklickt wird."""
        self._navigate_to_folder(folder_path)
        self.statusbar.showMessage(f"Scan-Ordner gewechselt: {folder_path.name}", 3000)

    def on_navigate_up(self):
        """Navigiert ein Verzeichnis nach oben (übergeordneter Ordner)."""
        current_scan_folder = Path(self.config.get_scan_folder())
        parent_folder = current_scan_folder.parent

        # Prüfen ob wir noch höher navigieren können
        if parent_folder.exists() and parent_folder != current_scan_folder:
            self._navigate_to_folder(parent_folder)
            self.statusbar.showMessage(f"Navigiert zu: {parent_folder.name}", 3000)
        else:
            self.statusbar.showMessage("Bereits im obersten Verzeichnis", 2000)

    def on_pdf_dropped_on_folder(self, pdf_path: Path, folder_path: Path):
        """Wird aufgerufen wenn eine oder mehrere PDFs auf einen Ordner gezogen werden."""
        # Relativen Pfad für die Baumansicht berechnen
        relative_path = self.folder_tree.get_relative_path(folder_path)

        # Prüfen ob mehrere PDFs gedroppt wurden (durch Mehrfachauswahl)
        pdfs_to_move = []
        if len(self.selected_pdfs) > 1 and pdf_path in self.selected_pdfs:
            pdfs_to_move = list(self.selected_pdfs)
        else:
            pdfs_to_move = [pdf_path]

        moved_count = 0
        moved_pdfs = []
        move_pairs = []  # (source, dest) für Undo
        errors = []

        for current_pdf in pdfs_to_move:
            try:
                # Datei verschieben
                new_path = self.file_manager.move_file(current_pdf, folder_path)
                moved_count += 1
                moved_pdfs.append(current_pdf)
                move_pairs.append((current_pdf, new_path))

                # Versuchen zu lernen (wenn PDF vorher analysiert wurde)
                if current_pdf == self.selected_pdf and self.selected_pdf_text:
                    self.classifier.learn(
                        pdf_path=current_pdf,
                        target_folder=folder_path,
                        extracted_text=self.selected_pdf_text,
                        keywords=self.selected_pdf_keywords,
                        relative_path=relative_path,
                    )

            except Exception as e:
                errors.append(f"{current_pdf.name}: {e}")

        # Status aktualisieren
        training_count = self.classifier.get_training_count()
        self.training_label.setText(f"Gelernt: {training_count}")

        if moved_count == 1:
            self.statusbar.showMessage(f"Verschoben nach: {relative_path}", 3000)
        else:
            self.statusbar.showMessage(f"{moved_count} PDFs nach '{relative_path}' verschoben", 3000)

        # Fehler anzeigen
        if errors:
            QMessageBox.warning(
                self,
                "Teilweise fehlgeschlagen",
                f"Einige Dateien konnten nicht verschoben werden:\n" + "\n".join(errors)
            )

        # Undo-Eintrag erstellen (nur wenn Dateien verschoben wurden)
        if move_pairs:
            if moved_count == 1:
                desc = f"{move_pairs[0][0].name} → {relative_path}"
            else:
                desc = f"{moved_count} PDFs → {relative_path}"
            self._push_undo({"type": "move", "moves": move_pairs, "description": desc})

        # Nur die verschobenen PDF-Widgets entfernen (NICHT refresh_view!)
        for moved_pdf in moved_pdfs:
            self.remove_pdf_widget(moved_pdf)

        # Auswahl zurücksetzen (falls noch nicht durch remove_pdf_widget geschehen)
        self.selected_pdf = None
        self.selected_pdf_text = None
        self.selected_pdf_keywords = None
        self.selected_pdfs = []

        # Zuletzt verwendet aktualisieren
        self.config.add_to_last_used(folder_path)

        # Ordneransicht aktualisieren (um PDF-Zähler zu aktualisieren)
        self._refresh_after_move(folder_path, *{p.parent for p in pdfs_to_move})

    def on_folder_remove(self, folder_path: Path):
        """Wird aufgerufen wenn ein Ordner aus der Liste entfernt werden soll."""
        self.config.remove_target_folder(folder_path)
        self.folder_manager.remove_folder(folder_path)
        # Der Baum hat sich beim Kontextmenue-Aufruf bereits selbst neu
        # gescannt; ein zweiter Voll-Scan ueber load_folders() ist nur noetig,
        # wenn der Aufruf von woanders kam (z.B. aus dem versteckten Raster).
        if self.folder_tree.has_folder(Path(folder_path)):
            self.load_folders()

        # Auch aus den Vorschlag-Widgets entfernen (grüne Buttons)
        for widget in self.suggestion_widgets[:]:  # Kopie der Liste für sichere Iteration
            if widget.folder_path == folder_path:
                self.suggestions_layout.removeWidget(widget)
                widget.deleteLater()
                self.suggestion_widgets.remove(widget)

        # Falls keine Vorschläge mehr übrig, Platzhalter anzeigen
        if not self.suggestion_widgets:
            self.no_suggestions_label.show()

        self.statusbar.showMessage(f"Ordner entfernt: {folder_path.name}", 3000)

    def move_selected_pdf_to_folder(self, folder_path: Path):
        """Verschiebt die ausgewählte PDF in den angegebenen Ordner."""
        if not self.selected_pdf:
            return

        # Nutze die Lern-Funktion für alle Verschiebungen
        self.move_pdf_to_folder_and_learn(self.selected_pdf, folder_path)

    # === Menü-Aktionen ===

    def open_scan_folder(self):
        """Öffnet einen Dialog zur Auswahl des Scan-Ordners."""
        current = self.config.get_scan_folder()
        folder = QFileDialog.getExistingDirectory(
            self,
            "Scan-Ordner auswählen",
            str(current) if current else "",
        )
        if folder:
            self._navigate_to_folder(Path(folder))
            self.statusbar.showMessage(f"Scan-Ordner gesetzt: {folder}")

    def add_target_folder(self):
        """Öffnet einen Dialog zum Hinzufügen eines Zielordners."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Zielordner auswählen",
            self.config.dialog_start_dir(),
        )
        if folder:
            folder_path = Path(folder)
            self.config.add_target_folder(folder_path)
            self.folder_manager.add_folder(folder_path)
            self.load_folders()
            self.statusbar.showMessage(f"Zielordner hinzugefügt: {folder_path.name}", 3000)

    # === Volltextsuche mit kombinierbaren Filtern (Phase 17/18) ===

    def _create_filter_bar(self) -> QWidget:
        """Erstellt die ausklappbare Filterleiste."""
        bar = QWidget()
        bar.setVisible(False)
        bar.setStyleSheet(
            "QWidget { background: #f5f5f5; border-bottom: 1px solid #ccc; }"
        )

        layout = QGridLayout(bar)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        # Zeile 0: Steuerjahr, Kategorie, Korrespondent
        layout.addWidget(QLabel("Steuerjahr:"), 0, 0)
        self.filter_steuerjahr = QComboBox()
        self.filter_steuerjahr.addItem("Alle")
        self.filter_steuerjahr.setMinimumWidth(90)
        self.filter_steuerjahr.setToolTip("Nur Dokumente aus diesem Steuerjahr anzeigen")
        layout.addWidget(self.filter_steuerjahr, 0, 1)

        layout.addWidget(QLabel("Kategorie:"), 0, 2)
        self.filter_kategorie = QComboBox()
        self.filter_kategorie.addItem("Alle")
        self.filter_kategorie.setMinimumWidth(130)
        self.filter_kategorie.setToolTip("Nur Dokumente dieser Kategorie anzeigen")
        layout.addWidget(self.filter_kategorie, 0, 3)

        layout.addWidget(QLabel("Korrespondent:"), 0, 4)
        self.filter_korrespondent = QComboBox()
        self.filter_korrespondent.addItem("Alle")
        self.filter_korrespondent.setMinimumWidth(150)
        self.filter_korrespondent.setToolTip("Nur Dokumente dieses Korrespondenten anzeigen")
        layout.addWidget(self.filter_korrespondent, 0, 5)

        # Reset-Button (Zeile 0–1, letzte Spalte)
        reset_btn = QPushButton("Filter zurücksetzen")
        reset_btn.setToolTip("Alle Filter dieser Leiste auf 'Alle' zurücksetzen")
        reset_btn.clicked.connect(self._reset_filters)
        layout.addWidget(reset_btn, 0, 6, 2, 1)

        # Zeile 1: Datum, Betrag
        self.filter_datum_von_cb = QCheckBox("Datum von:")
        self.filter_datum_von_cb.setToolTip("Aktivieren, um nur Dokumente ab diesem Datum anzuzeigen")
        layout.addWidget(self.filter_datum_von_cb, 1, 0)
        self.filter_datum_von = QDateEdit()
        self.filter_datum_von.setCalendarPopup(True)
        self.filter_datum_von.setDate(QDate.currentDate().addYears(-1))
        self.filter_datum_von.setEnabled(False)
        layout.addWidget(self.filter_datum_von, 1, 1)

        self.filter_datum_bis_cb = QCheckBox("Datum bis:")
        self.filter_datum_bis_cb.setToolTip("Aktivieren, um nur Dokumente bis zu diesem Datum anzuzeigen")
        layout.addWidget(self.filter_datum_bis_cb, 1, 2)
        self.filter_datum_bis = QDateEdit()
        self.filter_datum_bis.setCalendarPopup(True)
        self.filter_datum_bis.setDate(QDate.currentDate())
        self.filter_datum_bis.setEnabled(False)
        layout.addWidget(self.filter_datum_bis, 1, 3)

        betrag_label = QLabel("Betrag (€):")
        layout.addWidget(betrag_label, 1, 4)
        betrag_widget = QWidget()
        betrag_layout = QHBoxLayout(betrag_widget)
        betrag_layout.setContentsMargins(0, 0, 0, 0)
        betrag_layout.setSpacing(4)
        self.filter_betrag_von = QDoubleSpinBox()
        self.filter_betrag_von.setRange(0, 999999.99)
        self.filter_betrag_von.setDecimals(2)
        self.filter_betrag_von.setSpecialValueText("ab –")
        self.filter_betrag_von.setValue(0.0)
        self.filter_betrag_von.setMinimumWidth(80)
        self.filter_betrag_von.setToolTip("Nur Dokumente mit mindestens diesem Betrag anzeigen")
        betrag_layout.addWidget(self.filter_betrag_von)
        self.filter_betrag_bis = QDoubleSpinBox()
        self.filter_betrag_bis.setRange(0, 999999.99)
        self.filter_betrag_bis.setDecimals(2)
        self.filter_betrag_bis.setSpecialValueText("bis –")
        self.filter_betrag_bis.setValue(0.0)
        self.filter_betrag_bis.setMinimumWidth(80)
        self.filter_betrag_bis.setToolTip("Nur Dokumente bis zu diesem Betrag anzeigen")
        betrag_layout.addWidget(self.filter_betrag_bis)
        layout.addWidget(betrag_widget, 1, 5)

        # Signals verdrahten
        self.filter_steuerjahr.currentTextChanged.connect(self._execute_search)
        self.filter_kategorie.currentTextChanged.connect(self._execute_search)
        self.filter_korrespondent.currentTextChanged.connect(self._execute_search)
        self.filter_datum_von_cb.toggled.connect(self.filter_datum_von.setEnabled)
        self.filter_datum_von_cb.toggled.connect(self._execute_search)
        self.filter_datum_von.dateChanged.connect(self._execute_search)
        self.filter_datum_bis_cb.toggled.connect(self.filter_datum_bis.setEnabled)
        self.filter_datum_bis_cb.toggled.connect(self._execute_search)
        self.filter_datum_bis.dateChanged.connect(self._execute_search)
        self.filter_betrag_von.valueChanged.connect(self._execute_search)
        self.filter_betrag_bis.valueChanged.connect(self._execute_search)

        return bar

    def _toggle_filter_bar(self, checked: bool):
        """Blendet die Filterleiste ein oder aus."""
        self.filter_bar.setVisible(checked)
        self.filter_toggle_btn.setText("Filter ▲" if checked else "Filter ▼")
        if checked:
            self._populate_filter_dropdowns()

    def _populate_filter_dropdowns(self):
        """Befüllt die Filter-Dropdowns mit aktuellen Datenbankwerten."""
        for combo, getter in (
            (self.filter_steuerjahr, self.db.get_distinct_steuerjahre),
            (self.filter_kategorie, self.db.get_distinct_kategorien),
            (self.filter_korrespondent, self.db.get_distinct_korrespondenten),
        ):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Alle")
            combo.addItems(getter())
            idx = combo.findText(current)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)

    def _has_active_filters(self) -> bool:
        """Prüft ob mindestens ein Filter aktiv ist."""
        if not hasattr(self, 'filter_steuerjahr'):
            return False
        if self.filter_steuerjahr.currentText() not in ("", "Alle"):
            return True
        if self.filter_kategorie.currentText() not in ("", "Alle"):
            return True
        if self.filter_korrespondent.currentText() not in ("", "Alle"):
            return True
        if self.filter_datum_von_cb.isChecked() or self.filter_datum_bis_cb.isChecked():
            return True
        if self.filter_betrag_von.value() > 0 or self.filter_betrag_bis.value() > 0:
            return True
        return False

    def _reset_filters(self):
        """Setzt alle Filterfelder zurück."""
        widgets = [
            self.filter_steuerjahr, self.filter_kategorie, self.filter_korrespondent,
            self.filter_datum_von_cb, self.filter_datum_bis_cb,
            self.filter_betrag_von, self.filter_betrag_bis,
        ]
        for w in widgets:
            w.blockSignals(True)
        self.filter_steuerjahr.setCurrentIndex(0)
        self.filter_kategorie.setCurrentIndex(0)
        self.filter_korrespondent.setCurrentIndex(0)
        self.filter_datum_von_cb.setChecked(False)
        self.filter_datum_von.setEnabled(False)
        self.filter_datum_bis_cb.setChecked(False)
        self.filter_datum_bis.setEnabled(False)
        self.filter_betrag_von.setValue(0.0)
        self.filter_betrag_bis.setValue(0.0)
        for w in widgets:
            w.blockSignals(False)
        self._execute_search()

    def _on_search_text_changed(self, text: str):
        """Live-Suche bei Texteingabe (mit Verzögerung)."""
        if not text.strip():
            if not self._has_active_filters():
                self._clear_search()
                return
            self._execute_search()
            return
        if len(text.strip()) >= 2:
            self._execute_search()

    def _execute_search(self):
        """Führt die Volltextsuche mit allen aktiven Filtern aus."""
        query = self.search_input.text().strip()

        # Filter-Werte sammeln
        steuerjahr = ""
        kategorie = ""
        korrespondent = ""
        datum_von = ""
        datum_bis = ""
        betrag_von = 0.0
        betrag_bis = 0.0

        if hasattr(self, 'filter_steuerjahr'):
            val = self.filter_steuerjahr.currentText()
            steuerjahr = "" if val == "Alle" else val
            val = self.filter_kategorie.currentText()
            kategorie = "" if val == "Alle" else val
            val = self.filter_korrespondent.currentText()
            korrespondent = "" if val == "Alle" else val
            if self.filter_datum_von_cb.isChecked():
                datum_von = self.filter_datum_von.date().toString("yyyy-MM-dd")
            if self.filter_datum_bis_cb.isChecked():
                datum_bis = self.filter_datum_bis.date().toString("yyyy-MM-dd")
            betrag_von = self.filter_betrag_von.value()
            betrag_bis = self.filter_betrag_bis.value()

        has_filters = any([steuerjahr, kategorie, korrespondent,
                           datum_von, datum_bis, betrag_von > 0, betrag_bis > 0])

        if not query and not has_filters:
            self._clear_search()
            return

        # Phase 5 der PDFsuche-Integration: Die Treffer erscheinen im Reiter „Suche“
        # (Volltext in PDFs, Office-Dateien, Markdown und Mails), die Metadatenfilter
        # der Filterleiste gelten dort mit.
        self.search_view.suchen(
            query,
            steuerjahr=steuerjahr,
            kategorie=kategorie,
            korrespondent=korrespondent,
            von=datum_von,
            bis=datum_bis,
            betrag_von=betrag_von,
            betrag_bis=betrag_bis,
        )
        if self.center_tabs.currentWidget() is not self.search_view:
            self.center_tabs.setCurrentWidget(self.search_view)

    def _on_search_view_result(self, ergebnis: dict) -> None:
        """Trefferzahl des Reiters „Suche“ in der Werkzeugleiste anzeigen."""
        gesamt = int(ergebnis.get("gesamt") or 0)
        self.search_count_label.setText(f"{gesamt} Treffer" if gesamt else "Keine Treffer")

    def _show_search_results(self, results: list[dict]):
        """Zeigt Suchergebnisse der alten Fassade im Detail-Panel an (nur noch fuer Aufrufer von aussen)."""
        self.detail_panel.show_search_results(results)

    def _clear_search(self):
        """Setzt den Suchfilter zurück."""
        self.search_input.clear()
        self.search_count_label.setText("")
        self.search_view.leeren()
        # Zurück zur normalen Ansicht wenn ein PDF ausgewählt war
        if self.selected_pdf:
            cached = self.pdf_cache.get(self.selected_pdf)
            if cached:
                detected_date = None
                if cached.dates:
                    d = cached.dates[0]
                    detected_date = d.strftime("%Y-%m-%d") if hasattr(d, 'strftime') else str(d)
                self._populate_detail_panel(self.selected_pdf, cached, detected_date)
        else:
            self.detail_panel.clear()

    def _open_steuerauswertung(self):
        """Oeffnet den Steuerauswertungs-Dialog."""
        from src.gui.steuerauswertung_dialog import SteuerauswertungDialog
        dlg = SteuerauswertungDialog(self)
        dlg.exec()

    def _index_folder_dialog(self):
        """Dialog: Ordner zum Suchindex hinzufügen."""
        from PyQt6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QFormLayout

        # Ordner auswählen
        folder = QFileDialog.getExistingDirectory(
            self, "Ordner zum Suchindex hinzufügen"
        )
        if not folder:
            return

        folder_path = Path(folder)

        # Optionen-Dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Indexierungs-Optionen")
        dlg.setMinimumWidth(400)
        form = QFormLayout(dlg)

        folder_label = QLabel(str(folder_path))
        folder_label.setWordWrap(True)
        folder_label.setStyleSheet("font-weight: bold;")
        form.addRow("Ordner:", folder_label)

        include_subfolders = QCheckBox("Unterordner einbeziehen")
        include_subfolders.setChecked(True)
        form.addRow(include_subfolders)

        use_llm = QCheckBox("KI-Metadaten generieren (Zusammenfassung, Kategorie, ...)")
        llm_available = bool(self.hybrid_classifier.is_llm_available())
        use_llm.setChecked(llm_available)
        use_llm.setEnabled(llm_available)
        if not self.hybrid_classifier.is_llm_available():
            use_llm.setToolTip("Kein LLM konfiguriert - nur Textextraktion")
        form.addRow(use_llm)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # PDFs sammeln
        if include_subfolders.isChecked():
            pdf_files = list(folder_path.rglob("*.pdf"))
        else:
            pdf_files = list(folder_path.glob("*.pdf"))

        if not pdf_files:
            QMessageBox.information(self, "Keine PDFs", f"Keine PDF-Dateien in '{folder_path.name}' gefunden.")
            return

        if not use_llm.isChecked():
            # Ohne KI-Metadaten liest der Hintergrunddienst den Ordner (Phase 5): Textebene, OCR,
            # Metadaten aus den PDFs - die Oberflaeche bleibt frei
            self._index_folder_im_dienst(folder_path, len(pdf_files))
            return

        # Batch-Indexierung starten
        self._index_pdfs_batch(pdf_files, use_llm=True)

    def _index_folder_im_dienst(self, folder_path: Path, anzahl: int) -> None:
        """Startet ``pdfsm-dienst index --pfad`` fuer den Ordner als eigenen Prozess."""
        try:
            prozess = self.db.suchindex.lauf_starten(pfad=str(folder_path))
        except OSError as e:
            QMessageBox.warning(self, "Suchindex", f"Der Indexlauf konnte nicht gestartet werden:\n{e}")
            return
        if prozess is None:
            self.statusbar.showMessage("Ein Indexlauf läuft bereits – der Ordner kommt beim nächsten Lauf dazu.",
                                       6000)
            return
        self.statusbar.showMessage(
            f"Suchindex: {anzahl} PDFs in '{folder_path.name}' werden im Hintergrund gelesen", 6000
        )
        self.search_view.refresh_status()

    def _index_pdfs_batch(self, pdf_files: list[Path], use_llm: bool = False):
        """Indexiert eine Liste von PDFs in den Suchindex (mit Fortschrittsanzeige)."""
        from PyQt6.QtWidgets import QProgressDialog

        progress = QProgressDialog(
            "Indexiere PDFs...", "Abbrechen", 0, len(pdf_files), self
        )
        progress.setWindowTitle("Suchindex aufbauen")
        progress.setMinimumDuration(0)
        progress.setWindowModality(Qt.WindowModality.WindowModal)

        indexed = 0
        skipped = 0
        errors = 0

        for i, pdf_path in enumerate(pdf_files):
            if progress.wasCanceled():
                break

            progress.setValue(i)
            progress.setLabelText(f"Analysiere: {pdf_path.name}\n({i+1}/{len(pdf_files)})")
            QApplication.processEvents()

            try:
                # Text extrahieren
                from src.core.pdf_analyzer import PDFAnalyzer
                extracted_text = ""
                keywords = []
                detected_date = None

                try:
                    with PDFAnalyzer(pdf_path) as analyzer:
                        extracted_text = analyzer.extract_text() or ""
                        keywords = analyzer.extract_keywords() or []
                        dates = analyzer.extract_dates()
                        if dates:
                            d = dates[0]
                            detected_date = d.strftime("%Y-%m-%d") if hasattr(d, 'strftime') else str(d)
                except Exception as e:
                    print(f"Analyse-Fehler {pdf_path.name}: {e}")
                    errors += 1
                    continue

                # LLM-Metadaten holen (optional)
                metadata = {}
                if use_llm and extracted_text:
                    try:
                        from datetime import datetime
                        file_mtime = pdf_path.stat().st_mtime
                        file_date = datetime.fromtimestamp(file_mtime).strftime("%Y-%m-%d")

                        suggestions = self.hybrid_classifier.suggest_filename(
                            text=extracted_text,
                            current_filename=pdf_path.name,
                            keywords=keywords,
                            detected_date=detected_date,
                            use_llm=True,
                            file_date=file_date,
                            source_folder=source_folder_hint(pdf_path),
                        )
                        for s in suggestions:
                            if s.source == "llm" and s.metadata:
                                metadata = s.metadata
                                break
                    except Exception as e:
                        print(f"LLM-Fehler {pdf_path.name}: {e}")

                # Gelernte Korrespondent-Overrides anwenden
                korrespondent = metadata.get("korrespondent", "")
                if korrespondent:
                    learned = self.db.get_korrespondent_metadata(korrespondent)
                    if learned:
                        metadata.update(learned)

                # Relative Ordner-Position ermitteln
                target_folder = str(pdf_path.parent)

                # In Suchindex aufnehmen
                self.db.index_document(
                    file_path=str(pdf_path),
                    filename=pdf_path.name,
                    extracted_text=extracted_text,
                    keywords=", ".join(keywords) if keywords else "",
                    korrespondent=metadata.get("korrespondent", ""),
                    kategorie=metadata.get("subject", ""),
                    steuerjahr=metadata.get("steuerjahr", ""),
                    betrag=metadata.get("betrag", ""),
                    zusammenfassung=metadata.get("description", ""),
                    target_folder=target_folder,
                )

                # XMP-Metadaten in PDF schreiben (falls LLM-Daten vorhanden)
                if metadata:
                    self._write_pdf_metadata(pdf_path, pdf_path.name, keywords, metadata)

                indexed += 1

            except Exception as e:
                print(f"Indexierung Fehler {pdf_path.name}: {e}")
                errors += 1

        progress.setValue(len(pdf_files))

        # Ergebnis
        msg = f"{indexed} PDFs indexiert"
        if skipped:
            msg += f", {skipped} übersprungen"
        if errors:
            msg += f", {errors} Fehler"
        if progress.wasCanceled():
            msg += " (abgebrochen)"

        total_indexed = self.db.get_search_index_count()
        self.statusbar.showMessage(f"{msg} | Gesamt im Index: {total_indexed}", 5000)

        QMessageBox.information(
            self, "Indexierung abgeschlossen",
            f"{msg}\n\nGesamt im Suchindex: {total_indexed} Dokumente"
        )

    def refresh_view(self):
        """Aktualisiert die Ansicht."""
        self.statusbar.showMessage("Aktualisiere...")
        QApplication.processEvents()

        self.load_pdfs()
        self.load_folders()

        self.statusbar.showMessage("Ansicht aktualisiert", 3000)

    def check_backup_status(self):
        """Zeigt den Backup-Hinweis (Menue). Macrium-Log-Parsing: Issue #14."""
        self.show_backup_hint(force=True)

    # === Anwendungsdaten sichern / wiederherstellen (Issue #98) ===

    @staticmethod
    def _documents_dir() -> str:
        from PyQt6.QtCore import QStandardPaths
        return QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        ) or str(Path.home())

    def backup_app_data(self):
        """Extras > Daten sichern: ZIP mit Datenbank, Cache, Modell und Einstellungen."""
        from src.utils.backup import create_backup, default_backup_name

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Daten sichern",
            str(Path(self._documents_dir()) / default_backup_name()),
            "ZIP-Archiv (*.zip)",
        )
        if not path:
            return
        version = QApplication.applicationVersion() or ""
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        try:
            info = create_backup(self.config.data_dir, Path(path), version=version)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Sicherung fehlgeschlagen", str(e))
            return
        QApplication.restoreOverrideCursor()
        size_mb = info.total_bytes / (1024 * 1024)
        QMessageBox.information(
            self,
            "Daten gesichert",
            f"{len(info.entries)} Dateien ({size_mb:.1f} MB) gesichert nach:\n{path}\n\n"
            "Enthalten: Datenbank (Verlauf, Suchindex, Korrespondenten, Regeln), "
            "KI-Cache, ML-Modell und Einstellungen.\n\n"
            "Hinweis: Die Einstellungen enthalten Ihre API-Schlüssel – bewahren "
            "Sie das Archiv entsprechend geschützt auf.",
        )
        self.statusbar.showMessage(f"Daten gesichert: {Path(path).name}", 5000)

    def restore_app_data(self):
        """Extras > Daten wiederherstellen: ZIP vormerken, beim naechsten Start einspielen."""
        from src.utils.backup import PREVIOUS_DIR, inspect_backup, stage_restore

        path, _ = QFileDialog.getOpenFileName(
            self, "Sicherung wiederherstellen", self._documents_dir(), "ZIP-Archiv (*.zip)"
        )
        if not path:
            return
        try:
            info = inspect_backup(Path(path))
        except Exception as e:
            QMessageBox.critical(self, "Keine gültige Sicherung", str(e))
            return

        version = info.version or "unbekannt"
        answer = QMessageBox.question(
            self,
            "Sicherung wiederherstellen?",
            f"Sicherung vom {info.created_display} (Version {version}, "
            f"{len(info.entries)} Dateien).\n\n"
            "Beim nächsten Start ersetzen diese Daten die aktuelle Datenbank, den "
            "KI-Cache, das Modell und die Einstellungen. Die bisherigen Dateien "
            f"bleiben im Datenordner unter „{PREVIOUS_DIR}“ erhalten.\n\n"
            "PDF Sortier Meister wird dazu jetzt beendet. Fortfahren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            stage_restore(Path(path), self.config.data_dir)
        except Exception as e:
            QMessageBox.critical(self, "Wiederherstellung fehlgeschlagen", str(e))
            return
        QMessageBox.information(
            self,
            "Wiederherstellung vorbereitet",
            "Bitte PDF Sortier Meister jetzt neu starten – die Sicherung wird "
            "beim Start eingespielt.",
        )
        self.close()

    def show_first_steps_hint(self, force: bool = False):
        """
        Erklaert den 3-Spalten-Workflow beim ersten Start (Issue #51).
        Erscheint vor dem Backup-Hinweis, bis der Nutzer "nicht mehr
        anzeigen" abhakt; ueber das Hilfe-Menue jederzeit erneut.
        """
        if not force and self.config.get("first_steps_hint_dismissed", False):
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Erste Schritte")
        box.setText("So sortieren Sie eine PDF in drei Schritten:")
        box.setInformativeText(
            "1. Links: Ein PDF anklicken, um es auszuwaehlen.\n"
            "2. Mitte: Vorgeschlagenen Namen und Metadaten pruefen und bei "
            "Bedarf anpassen.\n"
            "3. Rechts: Auf einen Zielordner klicken - das PDF wird dorthin "
            "verschoben, umbenannt und die Metadaten werden gespeichert.\n\n"
            "Doppelklick auf einen Ordner im Baum (rechts) oeffnet ihn nur "
            "zur Ansicht links, ohne etwas zu verschieben."
        )
        dismiss = QCheckBox("Diesen Hinweis nicht mehr anzeigen")
        dismiss.setChecked(self.config.get("first_steps_hint_dismissed", False))
        box.setCheckBox(dismiss)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()
        self.config.set("first_steps_hint_dismissed", dismiss.isChecked())

    def check_backup_reminder(self):
        """Fragt alle X Tage, ob ein Backup gemacht wurde (Issue #14)."""
        days = self.config.get("backup_check_days", 7)
        if not is_question_due(
            days,
            parse_date(self.config.get("backup_last_confirmed", "")),
            bool(self.config.get("backup_pending", False)),
            macrium_last_backup(),
        ):
            return
        antwort = QMessageBox.question(
            self, "Backup-Erinnerung",
            f"Haben Sie in den letzten {int(days)} Tagen ein Backup gemacht?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if antwort == QMessageBox.StandardButton.Yes:
            self.confirm_backup_done()
        else:
            self.config.set("backup_pending", True)
            self.backup_status_label.setVisible(True)

    def confirm_backup_done(self):
        """Backup bestaetigt: Datum speichern, Statusleisten-Hinweis ausblenden."""
        from datetime import datetime
        self.config.set("backup_last_confirmed", datetime.now().isoformat(timespec="seconds"))
        self.config.set("backup_pending", False)
        self.backup_status_label.setVisible(False)

    def show_backup_hint(self, force: bool = False):
        """
        Erinnert daran, dass die App Dateien veraendert und ein Backup
        ratsam ist (Issue #7). Erscheint beim Start, bis der Nutzer
        "nicht mehr anzeigen" abhakt; ueber das Menue jederzeit erneut.
        """
        if not force and self.config.get("backup_hint_dismissed", False):
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Backup empfohlen")
        box.setText("PDF Sortier Meister verschiebt, benennt um und schreibt Metadaten "
                    "direkt in Ihre PDF-Dateien.")
        box.setInformativeText(
            "Legen Sie regelmaessig ein Backup Ihres Arbeitsordners an - z.B. per "
            "Cloud-Sync (OneDrive, Dropbox) oder einem Backup-Programm wie "
            "Macrium Reflect.\n\n"
            "Rueckgaengig (Strg+Z) hilft bei Ausrutschern, ersetzt aber kein Backup."
        )
        dismiss = QCheckBox("Diesen Hinweis nicht mehr anzeigen")
        dismiss.setChecked(self.config.get("backup_hint_dismissed", False))
        box.setCheckBox(dismiss)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()
        self.config.set("backup_hint_dismissed", dismiss.isChecked())

    # ------------------------------------------------------------------ #
    # Update-Pruefung (Issue #73)
    # ------------------------------------------------------------------ #

    def schedule_update_check(self, delay_ms: int = 3000) -> bool:
        """Plant die automatische Update-Pruefung kurz nach dem Start.

        Returns:
            True, wenn eine Pruefung geplant wurde (Einstellung aktiv).
        """
        if not self.config.get("update_check_enabled", True):
            return False
        QTimer.singleShot(delay_ms, lambda: self.check_for_updates(manual=False))
        return True

    def check_for_updates(self, manual: bool = False) -> None:
        """Startet die Update-Pruefung im Hintergrund.

        Args:
            manual: True bei Aufruf ueber das Hilfe-Menue - dann wird auch
                    "keine neue Version" bzw. ein Fehler als Dialog gemeldet.
        """
        if self._update_thread is not None and self._update_thread.isRunning():
            if manual:
                self.statusbar.showMessage("Update-Prüfung läuft bereits...", 3000)
            return
        from src.main import __version__

        thread = _UpdateCheckThread(__version__, self)
        thread.result_ready.connect(
            lambda info, error, m=manual: self._on_update_check_finished(info, error, m)
        )
        self._update_thread = thread
        if manual:
            self.statusbar.showMessage("Suche nach Updates...", 5000)
        thread.start()

    def _on_update_check_finished(self, info: Optional[UpdateInfo], error: str,
                                  manual: bool = False) -> None:
        """Verarbeitet das Ergebnis der Update-Pruefung im GUI-Thread."""
        from src.main import __version__

        if error:
            logging.getLogger(__name__).info("Update-Pruefung fehlgeschlagen: %s", error)
            if manual:
                QMessageBox.warning(
                    self,
                    "Update-Prüfung fehlgeschlagen",
                    "Die Update-Prüfung konnte nicht durchgeführt werden:\n"
                    f"{error}\n\n"
                    "Bitte prüfen Sie Ihre Internetverbindung oder versuchen Sie es später erneut.",
                )
            return

        if info is None:
            if manual:
                QMessageBox.information(
                    self,
                    "Kein Update verfügbar",
                    f"Sie verwenden bereits die aktuelle Version {__version__}.",
                )
            return

        skipped = self.config.get("update_skipped_version", "")
        if not manual and info.version == skipped:
            # Nutzer hat diese Version bewusst ausgeblendet - nicht nerven.
            logging.getLogger(__name__).info(
                "Update %s verfuegbar, vom Nutzer uebersprungen", info.version
            )
            return

        self._available_update = info
        self.update_status_label.setText(f"Update: v{info.version} verfügbar")
        self.update_status_label.setVisible(True)
        self._show_update_dialog(info)

    def _show_available_update(self) -> None:
        """Doppelklick auf den Statusleisten-Hinweis: Dialog erneut zeigen."""
        if self._available_update is not None:
            self._show_update_dialog(self._available_update)

    def _show_update_dialog(self, info: UpdateInfo) -> None:
        """Zeigt den Update-Dialog (Download-Seite / Überspringen / Später)."""
        from src.main import __version__

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Update verfügbar")
        box.setText(
            f"<b>Version {info.version}</b> von PDF Sortier Meister ist verfügbar.<br>"
            f"Installiert ist Version {__version__}."
        )
        hint = (
            "Auf der Download-Seite finden Sie den Installer und die Liste der "
            "Änderungen. Installieren Sie die neue Version einfach über die "
            "bestehende - Ihre Einstellungen und Lerndaten bleiben erhalten."
        )
        if info.asset_name:
            hint += f"\n\nDatei für Ihr System: {info.asset_name}"
        box.setInformativeText(hint)
        if info.notes:
            box.setDetailedText(info.notes)

        download_btn = box.addButton("Download-Seite öffnen", QMessageBox.ButtonRole.AcceptRole)
        skip_btn = box.addButton("Diese Version überspringen", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Später", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(download_btn)
        box.exec()

        clicked = box.clickedButton()
        if clicked is download_btn:
            QDesktopServices.openUrl(QUrl(info.page_url))
        elif clicked is skip_btn:
            self._skip_update(info)

    def _skip_update(self, info: UpdateInfo) -> None:
        """Blendet diese Version bis zum naechsten Release aus."""
        self.config.set("update_skipped_version", info.version)
        self._available_update = None
        self.update_status_label.setVisible(False)
        self.statusbar.showMessage(
            f"Version {info.version} wird übersprungen "
            "(Hilfe > Nach Updates suchen zeigt sie erneut).",
            5000,
        )

    def open_setup_wizard(self):
        """Oeffnet den Einrichtungs-Assistenten (auch nachtraeglich nutzbar)."""
        wizard = SetupWizard(self)
        wizard.exec()
        # Scan-Ordner, Zielordner und LLM-Status aktualisieren (Closes #61, #64):
        # initial_load() laedt beides neu, nicht nur die PDFs.
        self.initial_load()
        self._on_settings_changed()

    def open_settings(self):
        """Öffnet den Einstellungsdialog."""
        self._open_settings_dialog()

    def open_filename_settings(self):
        """Einstellungen direkt auf dem Tab "Dateinamen" (Muster bearbeiten)."""
        self._open_settings_dialog(tab="Dateinamen")

    def _open_settings_dialog(self, tab: str | None = None):
        dialog = SettingsDialog(self, example_values_provider=self._settings_example_values)
        dialog.settings_changed.connect(self._on_settings_changed)
        if tab:
            dialog.show_tab(tab)
        dialog.exec()

    def _settings_example_values(self):
        """Platzhalter-Werte der ausgewaehlten PDF fuer die Muster-Vorschau
        in den Einstellungen ("Mit aktueller PDF"). None = keine PDF gewaehlt."""
        if not self.detail_panel.get_current_pdf():
            return None
        from src.core.filename_placeholders import placeholder_values_from_metadata
        doc_date = coerce_date(self.selected_pdf_dates[0]) if self.selected_pdf_dates else None
        values = placeholder_values_from_metadata(
            self.detail_panel.get_metadata(),
            doc_date.isoformat() if doc_date else None,
        )
        return values or None

    def _on_settings_changed(self):
        """Wird aufgerufen wenn Einstellungen geändert wurden."""
        # Hybrid-Klassifikator neu initialisieren
        self.hybrid_classifier._init_llm_provider()
        self._llm_connection = None  # anderer Provider/Server: neu pruefen
        self._llm_request_error = None
        self._update_llm_status()
        self._check_llm_connection()
        # Kopfzeile der Vorschlaege (Ordnerstruktur-Schalter) nachziehen
        self.detail_panel.refresh_settings()
        # Reiter „Suche“: Suche ein-/ausgeschaltet, anderer Speicherort
        self.search_view.refresh_settings()
        self.statusbar.showMessage("Einstellungen gespeichert", 3000)
        # KI-Vorabfrage neu anstossen: PDFs, die ohne verfuegbares LLM
        # uebersprungen wurden, werden jetzt eingereiht.
        self._last_llm_error = None
        if self.pdf_widgets and self.hybrid_classifier.is_llm_available():
            self._start_pre_caching([w.pdf_path for w in self.pdf_widgets])
        else:
            self._update_cache_status()

    LLM_STATUS_RED = "#c0392b"

    def _llm_health(self):
        """Zustand des KI-Assistenten fuer Statusleiste und Details-Dialog.

        Liefert (zustand, hinweis): zustand ist "aus", "pruefen", "bereit" oder
        "fehler"; hinweis (nur bei "fehler") sagt verstaendlich, was los ist
        und was der Nutzer tun kann. Ein echter Fehler einer KI-Anfrage zaehlt
        mehr als die Minutenpruefung: Ollama kann z.B. antworten und Modelle
        auflisten, sie aber nicht laden (fehlender llama-server).
        """
        hc = self.hybrid_classifier
        if not hc.is_llm_available():
            return "aus", None
        from src.ml.llm_hinweis import ki_hinweis
        provider = hc.get_llm_provider_name()
        model = hc.get_llm_model_name()
        request_error = getattr(self, "_llm_request_error", None)
        if request_error:
            return "fehler", ki_hinweis(provider, request_error, model)
        if not hc.llm_connection_checkable():
            return "bereit", None
        connection = self._llm_connection
        if connection is None:
            return "pruefen", None
        if connection[0]:
            return "bereit", None
        return "fehler", ki_hinweis(provider, connection[1], model)

    def _update_llm_status(self):
        """Aktualisiert die LLM-Statusanzeige (Farbe, Text, Tooltip)."""
        health, hinweis = self._llm_health()
        if health != "aus":
            provider = self.hybrid_classifier.get_llm_provider_name()
            model_short = self.hybrid_classifier.get_llm_model_name(short=True)
            model_full = self.hybrid_classifier.get_llm_model_name()
            # z.B. "LLM: OpenRouter/glm-5.3-flash" - das Modell entscheidet
            # ueber Tempo und Qualitaet, deshalb gehoert es in die Anzeige
            text = f"LLM: {provider}/{model_short}" if model_short else f"LLM: {provider}"
            detail = f"{provider}, Modell: {model_full}" if model_full else provider
            if health == "pruefen":
                color = "gray"
                state = f"KI-Assistent eingerichtet ({detail}).\nVerbindung wird geprüft …"
            elif health == "bereit":
                color = "green"
                state = f"KI-Assistent bereit ({detail})."
            else:
                color = self.LLM_STATUS_RED
                text = f"⚠ {text}"
                state = (f"Die KI funktioniert gerade nicht ({detail}).\n\n"
                         f"Problem: {hinweis.problem}\n"
                         f"Abhilfe: {hinweis.abhilfe}")
            self.llm_status_label.setText(text)
            self.llm_status_label.setStyleSheet(f"color: {color};")
            self.llm_status_label.setToolTip(
                f"{state}\n\nDoppelklick öffnet die Einstellungen."
            )
        else:
            from src.ml.llm_provider import is_cloud_provider
            llm_cfg = self.config.get_llm_config()
            if (is_cloud_provider(llm_cfg.get("provider", "none"))
                    and not llm_cfg.get("cloud_consent", False)):
                reason = "Keine Einwilligung zur Datenübertragung erteilt."
            else:
                reason = "Nicht konfiguriert."
            self.llm_status_label.setText("LLM: Aus")
            self.llm_status_label.setStyleSheet("color: gray;")
            self.llm_status_label.setToolTip(
                f"KI-Assistent deaktiviert. {reason}\nDoppelklick öffnet die Einstellungen."
            )

    def _on_llm_check_tick(self):
        """Minuten-Takt: Erreichbarkeit pruefen; nach einem KI-Fehler zusaetzlich
        eine gescheiterte PDF erneut anfragen, damit sich die Anzeige nach der
        Behebung (z.B. Ollama neu installiert) von selbst wieder erholt."""
        if self._llm_request_error and self.hybrid_classifier.is_llm_available():
            if self.config.get("llm_precache_enabled", True):
                self.pdf_cache.retry_one_failed_llm()
        self._check_llm_connection()

    def _check_llm_connection(self):
        """Prueft im Hintergrund, ob der lokale LLM-Server (Ollama, Strata) antwortet."""
        if not self.hybrid_classifier.llm_connection_checkable():
            return
        import threading

        self._llm_check_generation += 1
        generation = self._llm_check_generation
        classifier = self.hybrid_classifier

        def _run():
            try:
                result = classifier.check_llm_connection()
            except Exception as e:  # noqa: BLE001
                result = (False, f"Fehler: {e}")
            try:
                self._llm_connection_checked.emit(generation, result)
            except RuntimeError:
                pass  # Fenster bereits geschlossen

        threading.Thread(target=_run, name="llm-ping", daemon=True).start()

    def _on_llm_connection_checked(self, generation: int, result):
        """Ergebnis der Erreichbarkeitspruefung (GUI-Thread)."""
        if generation != self._llm_check_generation:
            return  # inzwischen neu gestartet (z.B. Einstellungen geaendert)
        self._llm_connection = result
        self._update_llm_status()

    def _set_llm_reachable(self, reachable: bool):
        """Echte KI-Antwort bzw. -Fehler: Anzeige sofort anpassen."""
        if reachable:
            changed = self._llm_request_error is not None
            self._llm_request_error = None
            if (self.hybrid_classifier.llm_connection_checkable()
                    and (self._llm_connection is None or not self._llm_connection[0])):
                self._llm_connection = (True, "")
                changed = True
            if changed:
                self._update_llm_status()
        else:
            self._update_llm_status()
            self._check_llm_connection()

    def show_about(self):
        """Zeigt den Über-Dialog an."""
        from src.main import __version__
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton
        from PyQt6.QtCore import Qt

        # LLM-Status ermitteln
        llm_status = "Nicht konfiguriert"
        if self.hybrid_classifier.is_llm_available():
            llm_status = self.hybrid_classifier.get_llm_provider_name()

        # Lernstatistik holen
        try:
            from src.utils.database import get_database
            db = get_database()
            learn_count = db.get_entry_count()
        except Exception:
            learn_count = 0

        # Dialog erstellen
        dialog = QDialog(self)
        dialog.setWindowTitle("Über PDF Sortier Meister")
        dialog.setFixedSize(450, 380)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)

        # Titel und Version
        title_label = QLabel(
            f"<h2>PDF Sortier Meister</h2>"
            f"<p style='color: #666;'>Version {__version__}</p>"
        )
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # Beschreibung
        desc_label = QLabel(
            "Ein intelligentes Programm zum Sortieren und<br>"
            "Umbenennen von gescannten PDF-Dokumenten."
        )
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc_label)

        # Status-Info
        status_label = QLabel(
            f"<table style='margin: 10px;'>"
            f"<tr><td><b>LLM-Provider:</b></td><td>{llm_status}</td></tr>"
            f"<tr><td><b>Gelernte Zuordnungen:</b></td><td>{learn_count}</td></tr>"
            f"</table>"
        )
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(status_label)

        # GitHub-Link
        github_label = QLabel(
            '<p><b>GitHub:</b> '
            '<a href="https://github.com/Josi-create/PDF_Sortier_Meister">'
            'github.com/Josi-create/PDF_Sortier_Meister</a></p>'
        )
        github_label.setOpenExternalLinks(True)
        github_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(github_label)

        # Lizenz
        license_label = QLabel(
            "<p style='color: #666; font-size: 11px;'>"
            "<b>Lizenz:</b> GPL-3.0-or-later<br>"
            "Copyright (c) 2024-2026<br>"
            "Freie Software - Open Source. Lizenztext: "
            '<a href="https://www.gnu.org/licenses/gpl-3.0.html">gnu.org/licenses/gpl-3.0</a></p>'
        )
        license_label.setOpenExternalLinks(True)
        license_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(license_label)

        # Log-Pfad (für Support)
        from src.utils.logging_config import get_log_file_path
        log_path = get_log_file_path()
        log_label = QLabel(
            f"<p style='color: #999; font-size: 10px;'>"
            f"Log-Datei: {log_path}</p>"
        )
        log_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        log_label.setWordWrap(True)
        layout.addWidget(log_label)

        layout.addStretch()

        # OK-Button
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        ok_button = QPushButton("OK")
        ok_button.setFixedWidth(80)
        ok_button.clicked.connect(dialog.accept)
        button_layout.addWidget(ok_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        dialog.exec()


def _bezug_metadaten(meta: dict) -> dict:
    """KI-Metadaten (kanonische Schluessel) auf die Felder des Chat-Bezugs abbilden (Issue #148)."""
    unbekannt = {"", "unbekannt", "unknown", "null", "none", "n/a", "-"}

    def wert(*schluessel):
        for s in schluessel:
            v = meta.get(s)
            if v is not None and str(v).strip().lower() not in unbekannt:
                return str(v).strip()
        return ""

    felder = {
        "korrespondent": wert("korrespondent"),
        "kategorie": wert("kategorie", "subject"),
        "steuerjahr": wert("steuerjahr"),
        "betrag": wert("betrag", "betrag_brutto"),
    }
    return {k: v for k, v in felder.items() if v}

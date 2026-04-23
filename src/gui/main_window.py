"""
Hauptfenster der PDF Sortier Meister Anwendung
"""

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
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
)

from src.utils.config import get_config
from src.utils.database import get_database
from src.gui.pdf_thumbnail import PDFThumbnailWidget
from src.gui.folder_widget import FolderWidget
from src.gui.folder_tree_widget import FolderTreeWidget
from src.gui.rename_dialog import RenameDialog, RenameSuggestion, generate_rename_suggestions
from src.gui.detail_panel import DetailPanel
from src.gui.settings_dialog import SettingsDialog
from src.core.file_manager import FileManager, FolderManager
from src.core.pdf_cache import get_pdf_cache, PDFAnalysisResult
from src.ml.classifier import get_classifier, Suggestion
from src.ml.hybrid_classifier import get_hybrid_classifier


class MainWindow(QMainWindow):
    """Hauptfenster der Anwendung."""

    # Signal das gefeuert wird wenn alle Thumbnails geladen sind
    thumbnails_loaded = pyqtSignal()

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

        # Undo-Historie für Verschiebe- und Umbenennungs-Aktionen
        # Move-Eintrag: {"type": "move", "moves": [(source, dest), ...], "description": str}
        # Rename-Eintrag: {"type": "rename", "old_path": Path, "new_path": Path, "description": str}
        self._undo_stack: list[dict] = []

        # Ordner-Navigations-Historie für Zurück-Button
        self._folder_history: list[Path] = []

        self.setup_ui()
        self.setup_menu()
        self.setup_toolbar()
        self.setup_statusbar()
        self.load_settings()

        # PDF-Cache Signale verbinden
        self.pdf_cache.pdf_analyzed.connect(self._on_pdf_analyzed)

        # Initial laden
        QTimer.singleShot(100, self.initial_load)

    def setup_ui(self):
        """Initialisiert die Haupt-UI-Komponenten."""
        self.setWindowTitle("PDF Sortier Meister")
        self.setMinimumSize(800, 600)
        self.showMaximized()

        # Zentrales Widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Hauptlayout
        main_layout = QHBoxLayout(central_widget)

        # Splitter für flexible Größenanpassung
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # Linke Spalte: PDF-Thumbnails
        pdf_panel = self.create_pdf_panel()
        splitter.addWidget(pdf_panel)

        # Mittlere Spalte: Detail-Panel (Umbenennung + Metadaten)
        self.detail_panel = DetailPanel()
        splitter.addWidget(self.detail_panel)

        # Rechte Spalte: Zielordner
        folder_panel = self.create_folder_panel()
        splitter.addWidget(folder_panel)

        # Splitter-Größenverhältnis fixieren (30/40/30%)
        splitter.setStretchFactor(0, 3)  # Links: 30%
        splitter.setStretchFactor(1, 4)  # Mitte: 40%
        splitter.setStretchFactor(2, 3)  # Rechts: 30%
        splitter.setSizes([300, 400, 300])

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
        self.navigate_up_btn.setToolTip("Ein Verzeichnis nach oben (übergeordneter Ordner)")
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

        layout.addLayout(header_layout)

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
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        # Container für Thumbnails
        self.pdf_container = QWidget()
        self.pdf_container.mousePressEvent = self._on_pdf_container_clicked
        self.pdf_layout = QGridLayout(self.pdf_container)
        self.pdf_layout.setSpacing(10)
        self.pdf_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self.pdf_scroll_area.setWidget(self.pdf_container)
        self.pdf_scroll_area.hide()  # Anfangs versteckt
        layout.addWidget(self.pdf_scroll_area)

        return panel

    def create_folder_panel(self) -> QWidget:
        """Erstellt das Panel für die Zielordner."""
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Überschrift mit Buttons
        header_layout = QHBoxLayout()
        header = QLabel("Zielordner")
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

        # NEU: Ordner-Baumansicht für hierarchische Struktur
        self.folder_tree = FolderTreeWidget()
        self.folder_tree.folder_selected.connect(self.on_tree_folder_selected)
        self.folder_tree.folder_double_clicked.connect(self.on_tree_folder_double_clicked)
        self.folder_tree.pdf_dropped.connect(self.on_pdf_dropped_on_folder)
        self.folder_tree.folder_removed.connect(self.on_folder_remove)
        layout.addWidget(self.folder_tree, stretch=1)

        # Alte Grid-Ansicht (ausgeblendet, für Kompatibilität)
        self.folder_container = QWidget()
        self.folder_layout = QGridLayout(self.folder_container)
        self.folder_layout.setSpacing(10)
        self.folder_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.folder_container.hide()  # Grid-Ansicht versteckt
        layout.addWidget(self.folder_container)

        return panel

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
        # Alte Widgets aus Layout entfernen
        while self.pdf_layout.count():
            item = self.pdf_layout.takeAt(0)
            if item.widget():
                item.widget().cleanup() if hasattr(item.widget(), 'cleanup') else None
                item.widget().deleteLater()
        self.pdf_widgets.clear()

        # PDFs laden
        pdf_files = self.file_manager.get_pdf_files()

        if not pdf_files:
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
        count = len(pdf_files)
        self.pdf_folder_count_label.setText(f"{count} {'Datei' if count == 1 else 'Dateien'}")

        # Thumbnail-Ladetracking initialisieren
        self._pending_thumbnails = len(pdf_files)
        self._thumbnails_signal_emitted = False

        # Widgets erstellen
        for i, pdf_path in enumerate(pdf_files):
            widget = PDFThumbnailWidget(pdf_path)
            widget.clicked.connect(self.on_pdf_clicked)
            widget.ctrl_clicked.connect(self.on_pdf_ctrl_clicked)
            widget.shift_clicked.connect(self.on_pdf_shift_clicked)
            widget.double_clicked.connect(self.on_pdf_double_clicked)
            widget.rename_requested.connect(self.on_pdf_rename)
            widget.delete_requested.connect(self.on_pdf_delete)
            widget.move_requested.connect(self.on_pdf_move)
            widget.copy_requested.connect(self.on_pdf_copy)
            widget.batch_rename_requested.connect(self.on_batch_rename)
            # Thumbnail-Ladetracking
            widget.thumbnail_ready.connect(self._on_thumbnail_loaded)

            row = i // 3
            col = i % 3
            self.pdf_layout.addWidget(widget, row, col)
            self.pdf_widgets.append(widget)

        # Falls keine PDFs, Signal sofort senden
        if self._pending_thumbnails == 0:
            self.thumbnails_loaded.emit()
            self._thumbnails_signal_emitted = True

        # Statusleiste aktualisieren
        self.pdf_count_label.setText(f"PDFs: {len(pdf_files)}")
        self.statusbar.showMessage(f"{len(pdf_files)} PDFs geladen", 3000)

        # Pre-Caching starten: PDFs im Hintergrund analysieren
        # Verzögert starten damit UI erstmal fertig geladen wird
        QTimer.singleShot(500, lambda: self._start_pre_caching(pdf_files))

    def _start_pre_caching(self, pdf_files: list[Path]):
        """Startet das Pre-Caching für alle PDFs im Hintergrund."""
        self.pdf_cache.pre_cache(pdf_files)
        self.cache_status_label.setText(f"Analyse: 0/{len(pdf_files)} PDFs...")
        self.statusbar.showMessage(f"Analysiere {len(pdf_files)} PDFs im Hintergrund...", 2000)

    def _on_thumbnail_loaded(self):
        """Wird aufgerufen wenn ein Thumbnail fertig geladen ist."""
        self._pending_thumbnails -= 1
        if self._pending_thumbnails <= 0 and not self._thumbnails_signal_emitted:
            self._thumbnails_signal_emitted = True
            self.thumbnails_loaded.emit()

    def remove_pdf_widget(self, pdf_path: Path):
        """Entfernt ein einzelnes PDF-Widget aus der Ansicht (ohne vollständigen Refresh)."""
        for widget in self.pdf_widgets:
            if widget.pdf_path == pdf_path:
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

        view_menu.addSeparator()

        search_action = QAction("Dokumentensuche...", self)
        search_action.setShortcut("Ctrl+F")
        search_action.setToolTip("Alle sortierten Dokumente durchsuchen")
        search_action.triggered.connect(lambda: self.search_input.setFocus())
        view_menu.addAction(search_action)

        # Extras-Menü
        extras_menu = menubar.addMenu("Extras")

        index_folder_action = QAction("Ordner zum Suchindex hinzufügen...", self)
        index_folder_action.setToolTip("Bestehende PDF-Sammlung scannen und in den Suchindex aufnehmen")
        index_folder_action.triggered.connect(self._index_folder_dialog)
        extras_menu.addAction(index_folder_action)

        extras_menu.addSeparator()

        backup_action = QAction("Backup-Status prüfen", self)
        backup_action.triggered.connect(self.check_backup_status)
        extras_menu.addAction(backup_action)

        extras_menu.addSeparator()

        settings_action = QAction("Einstellungen...", self)
        settings_action.triggered.connect(self.open_settings)
        extras_menu.addAction(settings_action)

        # Hilfe-Menü
        help_menu = menubar.addMenu("Hilfe")

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
        self.cache_status_label = QLabel("")
        self.cache_status_label.setStyleSheet("color: #888; font-size: 11px;")
        self.statusbar.addPermanentWidget(self.cache_status_label)

        # LLM-Status anzeigen
        self.llm_status_label = QLabel("")
        self._update_llm_status()
        self.statusbar.addPermanentWidget(self.llm_status_label)

        self.backup_status_label = QLabel("Backup: Nicht geprüft")
        self.statusbar.addPermanentWidget(self.backup_status_label)

        self.statusbar.showMessage("Bereit")

    def load_settings(self):
        """Lädt die gespeicherten Einstellungen."""
        width = self.config.get("window_width", 1200)
        height = self.config.get("window_height", 800)
        self.resize(width, height)

    def save_settings(self):
        """Speichert die aktuellen Einstellungen."""
        self.config.set("window_width", self.width(), auto_save=False)
        self.config.set("window_height", self.height(), auto_save=True)

    def closeEvent(self, event):
        """Wird beim Schließen des Fensters aufgerufen."""
        self.save_settings()

        # Thumbnail-Threads beenden
        for widget in self.pdf_widgets:
            widget.cleanup()

        # PDF-Cache Worker stoppen
        self.pdf_cache.stop_worker()
        self.pdf_cache.stop_llm_worker()

        event.accept()

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

        # PDF analysieren und Vorschläge aktualisieren
        self.update_suggestions_for_pdf(pdf_path)

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
            # Noch nicht analysiert - Hintergrund-Analyse starten
            self.statusbar.showMessage(f"Analysiere {pdf_path.name}...")

            # Analyse anfordern mit Callback
            self.pdf_cache.request_analysis(
                pdf_path,
                callback=lambda result: self._on_analysis_result_ready(pdf_path, result),
                urgent=True  # Höchste Priorität weil User geklickt hat
            )

    def _on_analysis_result_ready(self, pdf_path: Path, result: PDFAnalysisResult):
        """Wird aufgerufen wenn eine Analyse fertig ist (aus Cache-Worker)."""
        # Nur anwenden wenn diese PDF noch ausgewählt ist
        if self.selected_pdf == pdf_path:
            self._apply_analysis_result(pdf_path, result)

    def _on_pdf_analyzed(self, pdf_path: Path):
        """Wird aufgerufen wenn irgendeine PDF analysiert wurde (Cache-Signal)."""
        stats = self.pdf_cache.get_stats()
        total_pdfs = len(self.pdf_widgets)
        cached = stats.get("cached_count", 0)

        if total_pdfs > 0 and cached < total_pdfs:
            self.cache_status_label.setText(f"Analyse: {pdf_path.name[:30]}... ({cached}/{total_pdfs})")
        else:
            self.cache_status_label.setText("")

    def _apply_analysis_result(self, pdf_path: Path, result: PDFAnalysisResult):
        """Wendet ein Analyse-Ergebnis an und zeigt Vorschläge."""
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

            # Vorschläge mit hierarchischen Pfaden holen
            suggestions = self.classifier.suggest_with_subfolders(
                text=self.selected_pdf_text,
                keywords=self.selected_pdf_keywords,
                detected_date=detected_date,
                root_folders=self.folder_manager.target_folders,
                max_suggestions=self.config.get("max_suggestions", 5),
            )

            # Vorschläge anzeigen (alte grüne Buttons)
            self.display_suggestions(suggestions)

            # Vorgeschlagene Ordner in der Baumansicht hervorheben
            suggested_folders = [s.folder_path for s in suggestions]
            self.folder_tree.set_suggestion_folders(suggested_folders)

            # Detail-Panel befüllen (3-Spalten-Layout)
            self._populate_detail_panel(pdf_path, result, detected_date)

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
            tooltip += f"Konfidenz: {int(suggestion.confidence * 100)}%"
            widget.setToolTip(tooltip)

            # Konfidenz im Namen anzeigen
            confidence_text = f"{int(suggestion.confidence * 100)}%"
            widget.count_label.setText(confidence_text)
            widget.count_label.setStyleSheet("font-size: 10px; color: #28a745; font-weight: bold;")

            widget.clicked.connect(self.on_suggestion_clicked)
            widget.double_clicked.connect(self.on_folder_double_clicked)

            self.suggestions_layout.addWidget(widget)
            self.suggestion_widgets.append(widget)

    def clear_suggestions(self):
        """Entfernt alle Vorschlag-Widgets."""
        for widget in self.suggestion_widgets:
            widget.deleteLater()
        self.suggestion_widgets.clear()
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

        # Name und Metadaten aus Detail-Panel holen
        new_name = self.detail_panel.get_new_name()
        metadata = self.detail_panel.get_metadata()

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

        try:
            # Datei verschieben (mit optionalem neuen Namen)
            new_path = self.file_manager.move_file(pdf_path, folder_path, new_name=new_name)

            # Cache-Eintrag migrieren
            self.pdf_cache.migrate_cache_entry(pdf_path, new_path)

            # Metadaten in PDF schreiben
            if metadata:
                self._write_pdf_metadata(new_path, new_path.name,
                                         self.selected_pdf_keywords, metadata)
                # Korrespondent-Zuordnung lernen
                if metadata.get("korrespondent"):
                    self.db.learn_korrespondent_metadata(
                        metadata["korrespondent"], metadata
                    )

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

            # Umbenennung lernen (falls Name geändert)
            if name_changed:
                detected_date = None
                if self.selected_pdf_dates:
                    try:
                        d = self.selected_pdf_dates[0]
                        detected_date = d.strftime("%Y-%m-%d") if hasattr(d, 'strftime') else str(d)
                    except Exception:
                        pass
                self.db.add_rename_entry(
                    original_filename=pdf_path.name,
                    new_filename=new_path.name,
                    extracted_text=self.selected_pdf_text,
                    keywords=self.selected_pdf_keywords,
                    detected_date=detected_date,
                )

            # Volltext-Suchindex befüllen (Phase 17)
            self.db.index_document(
                file_path=str(new_path),
                filename=new_path.name,
                extracted_text=self.selected_pdf_text or "",
                keywords=", ".join(self.selected_pdf_keywords) if self.selected_pdf_keywords else "",
                korrespondent=metadata.get("korrespondent", "") if metadata else "",
                kategorie=metadata.get("subject", "") if metadata else "",
                steuerjahr=metadata.get("steuerjahr", "") if metadata else "",
                betrag=metadata.get("betrag", "") if metadata else "",
                zusammenfassung=metadata.get("description", "") if metadata else "",
                target_folder=relative_path,
            )

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
            self.remove_pdf_widget(pdf_path)
            self.detail_panel.clear()
            self.load_folders()

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
                self.db.index_document(
                    file_path=str(new_path),
                    filename=new_path.name,
                    extracted_text=self.selected_pdf_text or "",
                    keywords=", ".join(self.selected_pdf_keywords) if self.selected_pdf_keywords else "",
                    target_folder=relative_path,
                )

                # Zuletzt verwendet aktualisieren
                self.config.add_to_last_used(folder_path)

                # Nur das verschobene PDF-Widget entfernen (NICHT refresh_view!)
                self.remove_pdf_widget(pdf_path)

                # Ordneransicht aktualisieren (um PDF-Zähler zu aktualisieren)
                self.load_folders()

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

        # Verschobene PDF-Widgets entfernen
        for moved_pdf in moved_pdfs:
            self.remove_pdf_widget(moved_pdf)

        # Auswahl zurücksetzen
        self.selected_pdf = None
        self.selected_pdf_text = None
        self.selected_pdf_keywords = None
        self.selected_pdfs = []

        # Zuletzt verwendet aktualisieren
        self.config.add_to_last_used(folder_path)

        # Ordneransicht aktualisieren
        self.load_folders()

        # Vorschläge leeren
        self.clear_suggestions()

    def on_pdf_double_clicked(self, pdf_path: Path):
        """Wird aufgerufen wenn eine PDF doppelgeklickt wird."""
        # PDF mit Standardprogramm öffnen
        import os
        os.startfile(str(pdf_path))

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
                if dialog_metadata.get("korrespondent"):
                    metadata.korrespondent = dialog_metadata["korrespondent"]
                if dialog_metadata.get("betrag"):
                    metadata.betrag = dialog_metadata["betrag"]
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
                else:
                    print(f"Metadaten konnten nicht in {pdf_path.name} geschrieben werden")

        except ImportError:
            pass  # pikepdf nicht installiert - kein Fehler
        except Exception as e:
            print(f"Fehler beim Schreiben der PDF-Metadaten: {e}")

    def _rename_selected_pdf(self):
        """F2-Shortcut: Öffnet den Umbenennungsdialog für die ausgewählte PDF."""
        if self.selected_pdf and self.selected_pdf.exists():
            self.on_pdf_rename(self.selected_pdf)
        else:
            self.statusbar.showMessage("Keine PDF ausgewählt zum Umbenennen", 2000)

    def on_pdf_rename(self, pdf_path: Path):
        """Wird aufgerufen wenn eine PDF umbenannt werden soll."""
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
        reply = QMessageBox.question(
            self,
            "PDF löschen",
            f"Möchten Sie diese PDF wirklich löschen?\n\n{pdf_path.name}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.file_manager.delete_file(pdf_path)
                self.statusbar.showMessage(f"Gelöscht: {pdf_path.name}", 3000)
                # Nur das gelöschte PDF-Widget entfernen
                self.remove_pdf_widget(pdf_path)
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
                self.remove_pdf_widget(pdf_path)
                # Ordneransicht aktualisieren
                self.load_folders()
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

            self.statusbar.showMessage(f"Kopie erstellt: {new_name}", 3000)

            # PDF-Ansicht aktualisieren um neue Datei anzuzeigen
            self.load_pdfs()

        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Kopieren fehlgeschlagen:\n{e}")

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
        else:
            self._undo_move(entry)

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
        pdfs_to_process = list(self.selected_pdfs)  # Kopie der Liste

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
        self.load_folders()

    def on_folder_remove(self, folder_path: Path):
        """Wird aufgerufen wenn ein Ordner aus der Liste entfernt werden soll."""
        self.config.remove_target_folder(folder_path)
        self.folder_manager.remove_folder(folder_path)
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
        )
        if folder:
            folder_path = Path(folder)
            self.config.add_target_folder(folder_path)
            self.folder_manager.add_folder(folder_path)
            self.load_folders()
            self.statusbar.showMessage(f"Zielordner hinzugefügt: {folder_path.name}", 3000)

    # === Volltextsuche (Phase 17) ===

    def _on_search_text_changed(self, text: str):
        """Live-Suche bei Texteingabe (mit Verzögerung)."""
        if not text.strip():
            self._clear_search()
            return
        # Suche erst ab 2 Zeichen auslösen
        if len(text.strip()) >= 2:
            self._execute_search()

    def _execute_search(self):
        """Führt die Volltextsuche aus und zeigt Ergebnisse."""
        query = self.search_input.text().strip()
        if not query:
            self._clear_search()
            return

        results = self.db.search_documents(query, limit=50)

        if results:
            self.search_count_label.setText(f"{len(results)} Treffer")
            self._show_search_results(results)
        else:
            self.search_count_label.setText("Keine Treffer")
            self.detail_panel.clear()
            self.statusbar.showMessage(f"Keine Dokumente gefunden für '{query}'", 3000)

    def _show_search_results(self, results: list[dict]):
        """Zeigt Suchergebnisse im Detail-Panel an."""
        # Suchergebnisse als HTML im Detail-Panel darstellen
        self.detail_panel.show_search_results(results)

    def _clear_search(self):
        """Setzt den Suchfilter zurück."""
        self.search_input.clear()
        self.search_count_label.setText("")
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

        # Batch-Indexierung starten
        self._index_pdfs_batch(pdf_files, use_llm=use_llm.isChecked())

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
        """Überprüft den Backup-Status."""
        # TODO: Macrium Reflect Integration (Phase 7)
        QMessageBox.information(
            self,
            "Backup-Status",
            "Backup-Prüfung wird in Phase 7 implementiert.",
        )

    def open_settings(self):
        """Öffnet den Einstellungsdialog."""
        dialog = SettingsDialog(self)
        dialog.settings_changed.connect(self._on_settings_changed)
        dialog.exec()

    def _on_settings_changed(self):
        """Wird aufgerufen wenn Einstellungen geändert wurden."""
        # Hybrid-Klassifikator neu initialisieren
        self.hybrid_classifier._init_llm_provider()
        self._update_llm_status()
        self.statusbar.showMessage("Einstellungen gespeichert", 3000)

    def _update_llm_status(self):
        """Aktualisiert die LLM-Statusanzeige."""
        if self.hybrid_classifier.is_llm_available():
            provider = self.hybrid_classifier.get_llm_provider_name()
            self.llm_status_label.setText(f"LLM: {provider}")
            self.llm_status_label.setStyleSheet("color: green;")
            self.llm_status_label.setToolTip(f"KI-Assistent aktiv ({provider})")
        else:
            self.llm_status_label.setText("LLM: Aus")
            self.llm_status_label.setStyleSheet("color: gray;")
            self.llm_status_label.setToolTip(
                "KI-Assistent deaktiviert. In Einstellungen konfigurieren."
            )

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
            "<b>Lizenz:</b> MIT License<br>"
            "Copyright (c) 2024-2026<br>"
            "Freie Software - Open Source</p>"
        )
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

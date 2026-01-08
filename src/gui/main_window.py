"""
Hauptfenster der PDF Sortier Meister Anwendung
"""

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
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
)

from src.utils.config import get_config
from src.utils.database import get_database
from src.gui.pdf_thumbnail import PDFThumbnailWidget
from src.gui.folder_widget import FolderWidget
from src.gui.folder_tree_widget import FolderTreeWidget
from src.gui.rename_dialog import RenameDialog, RenameSuggestion, generate_rename_suggestions
from src.gui.settings_dialog import SettingsDialog
from src.core.file_manager import FileManager, FolderManager
from src.core.pdf_cache import get_pdf_cache, PDFAnalysisResult
from src.ml.classifier import get_classifier, Suggestion
from src.ml.hybrid_classifier import get_hybrid_classifier


class MainWindow(QMainWindow):
    """Hauptfenster der Anwendung."""

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

        # Zentrales Widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Hauptlayout
        main_layout = QHBoxLayout(central_widget)

        # Splitter für flexible Größenanpassung
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # Linke Seite: PDF-Bereich
        pdf_panel = self.create_pdf_panel()
        splitter.addWidget(pdf_panel)

        # Rechte Seite: Zielordner-Bereich
        folder_panel = self.create_folder_panel()
        splitter.addWidget(folder_panel)

        # Splitter-Größenverhältnis (60% PDF, 40% Ordner)
        splitter.setSizes([600, 400])

    def create_pdf_panel(self) -> QWidget:
        """Erstellt das Panel für die PDF-Anzeige."""
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Überschrift mit Ordnerpfad
        self.pdf_header = QLabel("Neue PDFs im Scan-Ordner")
        self.pdf_header.setStyleSheet("font-size: 14px; font-weight: bold; padding: 5px;")
        layout.addWidget(self.pdf_header)

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

        # Überschrift
        header = QLabel("Zielordner")
        header.setStyleSheet("font-size: 14px; font-weight: bold; padding: 5px;")
        layout.addWidget(header)

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
            return

        self.empty_label.hide()
        self.pdf_scroll_area.show()

        # Header aktualisieren
        self.pdf_header.setText(f"PDFs in: {self.file_manager.scan_folder.name}")
        self.pdf_header.setToolTip(str(self.file_manager.scan_folder))

        # Widgets erstellen
        for i, pdf_path in enumerate(pdf_files):
            widget = PDFThumbnailWidget(pdf_path)
            widget.clicked.connect(self.on_pdf_clicked)
            widget.ctrl_clicked.connect(self.on_pdf_ctrl_clicked)
            widget.double_clicked.connect(self.on_pdf_double_clicked)
            widget.rename_requested.connect(self.on_pdf_rename)
            widget.delete_requested.connect(self.on_pdf_delete)
            widget.move_requested.connect(self.on_pdf_move)

            row = i // 3
            col = i % 3
            self.pdf_layout.addWidget(widget, row, col)
            self.pdf_widgets.append(widget)

        # Statusleiste aktualisieren
        self.pdf_count_label.setText(f"PDFs: {len(pdf_files)}")
        self.statusbar.showMessage(f"{len(pdf_files)} PDFs geladen", 3000)

        # Pre-Caching starten: PDFs im Hintergrund analysieren
        # Verzögert starten damit UI erstmal fertig geladen wird
        QTimer.singleShot(500, lambda: self._start_pre_caching(pdf_files))

    def _start_pre_caching(self, pdf_files: list[Path]):
        """Startet das Pre-Caching für alle PDFs im Hintergrund."""
        self.pdf_cache.pre_cache(pdf_files)
        self.statusbar.showMessage(f"Analysiere {len(pdf_files)} PDFs im Hintergrund...", 2000)

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

        # Ansicht-Menü
        view_menu = menubar.addMenu("Ansicht")

        refresh_action = QAction("Aktualisieren", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self.refresh_view)
        view_menu.addAction(refresh_action)

        # Extras-Menü
        extras_menu = menubar.addMenu("Extras")

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

        event.accept()

    # === PDF-Aktionen ===

    def on_pdf_clicked(self, pdf_path: Path):
        """Wird aufgerufen wenn eine PDF angeklickt wird."""
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
            self.statusbar.showMessage(f"{count} PDFs ausgewählt (Ctrl+Klick für weitere)")
            # Vorschläge für die letzte ausgewählte PDF anzeigen
            self.update_suggestions_for_pdf(self.selected_pdf)

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
        # Könnte für Status-Updates genutzt werden
        stats = self.pdf_cache.get_stats()
        # Optional: Cache-Status in Statusleiste anzeigen

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

            # Vorschläge anzeigen
            self.display_suggestions(suggestions)

            # Vorgeschlagene Ordner in der Baumansicht hervorheben
            suggested_folders = [s.folder_path for s in suggestions]
            self.folder_tree.set_suggestion_folders(suggested_folders)

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
            # Kürzen wenn zu lang
            if len(display_name) > 20:
                display_name = "..." + display_name[-17:]
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
        if self.selected_pdf:
            self.move_pdf_to_folder_and_learn(self.selected_pdf, folder_path)

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
                self.file_manager.move_file(pdf_path, folder_path)

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

                # Zuletzt verwendet aktualisieren
                self.config.add_to_last_used(folder_path)

                # Nur das verschobene PDF-Widget entfernen (NICHT refresh_view!)
                self.remove_pdf_widget(pdf_path)

                # Ordneransicht aktualisieren (um PDF-Zähler zu aktualisieren)
                self.load_folders()

            except Exception as e:
                QMessageBox.critical(self, "Fehler", f"Verschieben fehlgeschlagen:\n{e}")

    def on_pdf_double_clicked(self, pdf_path: Path):
        """Wird aufgerufen wenn eine PDF doppelgeklickt wird."""
        # PDF mit Standardprogramm öffnen
        import os
        os.startfile(str(pdf_path))

    def on_pdf_rename(self, pdf_path: Path):
        """Wird aufgerufen wenn eine PDF umbenannt werden soll."""
        self.statusbar.showMessage("Analysiere PDF für Umbenennung...")
        QApplication.processEvents()

        # PDF analysieren falls noch nicht geschehen
        extracted_text = None
        keywords = None
        dates = None

        if pdf_path == self.selected_pdf:
            # Bereits analysiert
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

        # LLM-Vorschlag holen wenn verfügbar
        if self.hybrid_classifier.is_llm_available():
            self.statusbar.showMessage("Frage KI nach Vorschlag...")
            QApplication.processEvents()
            try:
                # Datum als String für LLM
                detected_date = None
                if dates and len(dates) > 0:
                    first_date = dates[0]
                    if hasattr(first_date, 'strftime'):
                        detected_date = first_date.strftime("%Y-%m-%d")
                    else:
                        detected_date = str(first_date)

                llm_suggestions = self.hybrid_classifier.suggest_filename(
                    text=extracted_text or "",
                    current_filename=pdf_path.name,
                    keywords=keywords,
                    detected_date=detected_date,
                    use_llm=True,
                )

                # LLM-Vorschläge zu den Suggestions hinzufügen
                for llm_s in llm_suggestions:
                    if llm_s.source == "llm":
                        suggestions.insert(0, RenameSuggestion(
                            name=llm_s.filename,
                            reason=f"KI: {llm_s.reason}",
                            confidence=llm_s.confidence
                        ))
            except Exception as e:
                print(f"Fehler bei LLM-Vorschlag: {e}")

        # Dialog anzeigen
        dialog = RenameDialog(
            pdf_path=pdf_path,
            suggestions=suggestions,
            extracted_text=extracted_text,
            keywords=keywords,
            parent=self
        )

        if dialog.exec() == RenameDialog.DialogCode.Accepted:
            new_name = dialog.get_new_name()
            if new_name:
                try:
                    # Datei umbenennen
                    new_path = self.file_manager.rename_file(pdf_path, new_name)

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

                    self.statusbar.showMessage(
                        f"Umbenannt zu: {new_path.name} (gelernt)", 3000
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
                # Nur das verschobene PDF-Widget entfernen
                self.remove_pdf_widget(pdf_path)
                # Ordneransicht aktualisieren
                self.load_folders()
            except Exception as e:
                QMessageBox.critical(self, "Fehler", f"Verschieben fehlgeschlagen:\n{e}")

    # === Ordner-Aktionen ===

    def on_folder_clicked(self, folder_path: Path):
        """Wird aufgerufen wenn ein Ordner angeklickt wird."""
        # Wenn eine PDF ausgewählt ist, diese verschieben
        if self.selected_pdf:
            self.move_selected_pdf_to_folder(folder_path)

    def on_folder_double_clicked(self, folder_path: Path):
        """Wird aufgerufen wenn ein Ordner doppelgeklickt wird."""
        # Ordner im Explorer öffnen
        import os
        os.startfile(str(folder_path))

    def on_tree_folder_selected(self, folder_path: Path):
        """Wird aufgerufen wenn ein Ordner in der Baumansicht ausgewählt wird."""
        # Wenn eine PDF ausgewählt ist, diese verschieben
        if self.selected_pdf:
            self.move_selected_pdf_to_folder(folder_path)

    def on_tree_folder_double_clicked(self, folder_path: Path):
        """Wird aufgerufen wenn ein Ordner in der Baumansicht doppelgeklickt wird."""
        # Ordner im Explorer öffnen
        import os
        os.startfile(str(folder_path))

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
        errors = []

        for current_pdf in pdfs_to_move:
            try:
                # Datei verschieben
                self.file_manager.move_file(current_pdf, folder_path)
                moved_count += 1
                moved_pdfs.append(current_pdf)

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
            self.config.set_scan_folder(folder)
            self.file_manager.set_scan_folder(folder)
            self.statusbar.showMessage(f"Scan-Ordner gesetzt: {folder}")
            self.load_pdfs()

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
        llm_info = ""
        if self.hybrid_classifier.is_llm_available():
            llm_info = f"\n- LLM aktiv: {self.hybrid_classifier.get_llm_provider_name()}"

        QMessageBox.about(
            self,
            "Über PDF Sortier Meister",
            "PDF Sortier Meister\n\n"
            "Version 0.5.0\n\n"
            "Ein intelligentes Programm zum Sortieren und\n"
            "Umbenennen von gescannten PDF-Dokumenten.\n\n"
            "Features:\n"
            "- Lernfähige TF-IDF Klassifikation\n"
            "- Optionale LLM-Integration (Claude/OpenAI)\n"
            "- Hybrid-Ansatz: Lokal + KI kombiniert\n"
            "- Intelligente Umbenennungsvorschläge\n"
            f"- Lernt aus Benutzerentscheidungen{llm_info}",
        )

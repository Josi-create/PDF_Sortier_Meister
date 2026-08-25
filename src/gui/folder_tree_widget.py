"""
Ordner-Baum-Widget für PDF Sortier Meister

Zeigt eine hierarchische Ordnerstruktur als Baumansicht an.
Unterstützt Unterordner und zeigt PDF-Anzahlen an.

MIT License - Copyright (c) 2026
"""

import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QLabel,
    QPushButton,
    QMenu,
    QInputDialog,
    QMessageBox,
    QAbstractItemView,
)


class _TreeScanThread(QThread):
    """Listet die Zielordner-Hierarchie im Hintergrund (Issue #28).

    Auf OneDrive/Netzlaufwerken dauert das Listen aller Ordner 3 Ebenen tief
    inkl. PDF-Zaehlung viele Sekunden - im UI-Thread friert dabei alles ein.
    Ergebnis: Liste von (folder_path, parent_path | None, pdf_count).
    """

    scanned = pyqtSignal(int, list)  # (generation, entries)

    def __init__(self, roots: list[Path], generation: int, max_depth: int = 3, parent=None):
        super().__init__(parent)
        self._roots = roots
        self._generation = generation
        self._max_depth = max_depth

    def run(self):
        entries: list[tuple[Path, Optional[Path], int]] = []

        def scan(folder: Path, parent: Optional[Path], depth: int):
            pdf_count = 0
            subfolders = []
            try:
                with os.scandir(folder) as it:
                    for entry in it:
                        try:
                            if entry.is_file() and entry.name.lower().endswith('.pdf'):
                                pdf_count += 1
                            elif entry.is_dir() and not entry.name.startswith('.'):
                                subfolders.append(Path(entry.path))
                        except OSError:
                            continue
            except (PermissionError, OSError):
                pass
            entries.append((folder, parent, pdf_count))
            if depth < self._max_depth:
                for sub in sorted(subfolders):
                    scan(sub, folder, depth + 1)

        for root in self._roots:
            if root.exists():
                scan(root, None, 0)
        self.scanned.emit(self._generation, entries)


class FolderTreeWidget(QWidget):
    """Widget zur hierarchischen Anzeige von Zielordnern."""

    # Signale
    folder_selected = pyqtSignal(Path)  # Ordner wurde ausgewählt
    folder_double_clicked = pyqtSignal(Path)  # Ordner wurde doppelgeklickt
    pdf_dropped = pyqtSignal(Path, Path)  # PDF auf Ordner gezogen (pdf_path, folder_path)
    folder_removed = pyqtSignal(Path)  # Ordner aus Liste entfernt
    scan_finished = pyqtSignal()  # Baum wurde (neu) befuellt

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root_folders: list[Path] = []
        self._items: dict[Path, QTreeWidgetItem] = {}  # Pfad -> Item (fuer refresh_counts)
        self._scan_generation = 0  # verwirft Ergebnisse veralteter Scans
        self._scan_thread: Optional[_TreeScanThread] = None
        self.async_scan = True  # Tests koennen synchron scannen
        self._selected_folder: Optional[Path] = None
        self._suggestion_folders: list[Path] = []  # Vorgeschlagene Ordner
        self._drag_hover_item: Optional[QTreeWidgetItem] = None  # Aktuell gehoverte Item beim Drag

        # Einfachklick verzoegert ausfuehren, damit ein Doppelklick (Navigation)
        # nicht vorher die selektierte PDF verschiebt (Issue #23/#26).
        self._pending_click_item: Optional[QTreeWidgetItem] = None
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        from PyQt6.QtWidgets import QApplication
        self._click_timer.setInterval(QApplication.doubleClickInterval())
        self._click_timer.timeout.connect(self._fire_pending_click)

        self.setup_ui()

    def setup_ui(self):
        """Initialisiert die UI-Komponenten."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # Header
        header_layout = QHBoxLayout()
        header_label = QLabel("📁 Zielordner")
        header_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        header_layout.addWidget(header_label)
        header_layout.addStretch()

        # Refresh-Button
        self.refresh_btn = QPushButton("🔄")
        self.refresh_btn.setFixedSize(24, 24)
        self.refresh_btn.setToolTip("Ordnerstruktur aktualisieren")
        self.refresh_btn.clicked.connect(self.refresh_tree)
        header_layout.addWidget(self.refresh_btn)

        layout.addLayout(header_layout)

        # Tree Widget
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(20)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)

        # Styling
        self.tree.setStyleSheet("""
            QTreeWidget {
                border: 1px solid #daa520;
                border-radius: 5px;
                background-color: #fffef5;
            }
            QTreeWidget::item {
                padding: 4px;
                border-radius: 3px;
            }
            QTreeWidget::item:selected {
                background-color: #fff3cd;
                color: black;
            }
            QTreeWidget::item:hover {
                background-color: #ffecb3;
            }
        """)

        # Signale verbinden
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)

        # Drag & Drop Events überschreiben
        self.tree.dragEnterEvent = self._tree_drag_enter
        self.tree.dragMoveEvent = self._tree_drag_move
        self.tree.dragLeaveEvent = self._tree_drag_leave
        self.tree.dropEvent = self._tree_drop

        layout.addWidget(self.tree)

    def set_root_folders(self, folders: list[Path]):
        """
        Setzt die Root-Ordner für die Baumansicht.

        Args:
            folders: Liste von Pfaden zu Root-Ordnern
        """
        self._root_folders = [Path(f) for f in folders if Path(f).exists()]
        self.refresh_tree()

    def add_root_folder(self, folder: Path):
        """Fügt einen Root-Ordner hinzu."""
        folder = Path(folder)
        if folder.exists() and folder not in self._root_folders:
            self._root_folders.append(folder)
            self.refresh_tree()

    def remove_root_folder(self, folder: Path):
        """Entfernt einen Root-Ordner."""
        folder = Path(folder)
        if folder in self._root_folders:
            self._root_folders.remove(folder)
            self.refresh_tree()

    def set_suggestion_folders(self, folders: list[Path]):
        """
        Markiert Ordner als Vorschläge (werden hervorgehoben).

        Args:
            folders: Liste von vorgeschlagenen Ordnerpfaden
        """
        self._suggestion_folders = [Path(f) for f in folders]
        self._update_item_styles()

    def clear_suggestions(self):
        """Entfernt alle Vorschlag-Markierungen."""
        self._suggestion_folders = []
        self._update_item_styles()

    def refresh_tree(self):
        """Baut den Baum neu auf - das Verzeichnis-Listing laeuft im Hintergrund."""
        self._scan_generation += 1
        roots = [r for r in self._root_folders if r.exists()]
        if not self.async_scan:
            thread = _TreeScanThread(roots, self._scan_generation)
            thread.scanned.connect(self._on_scan_finished)
            thread.run()  # synchron, im aktuellen Thread
            return

        # Sofort etwas zeigen: Wurzeln ohne Zaehler, Rest folgt nach dem Scan
        self.tree.clear()
        self._items.clear()
        for root in roots:
            item = QTreeWidgetItem(self.tree)
            item.setText(0, f"📁 {root.name}  …")
            item.setData(0, Qt.ItemDataRole.UserRole, str(root))
            item.setToolTip(0, f"{root}\nOrdner werden geladen…")
            self._items[root] = item

        thread = _TreeScanThread(roots, self._scan_generation, parent=self)
        thread.scanned.connect(self._on_scan_finished)
        thread.finished.connect(thread.deleteLater)
        self._scan_thread = thread
        thread.start()

    def _on_scan_finished(self, generation: int, entries: list):
        """Befuellt den Baum aus dem Scan-Ergebnis (UI-Thread)."""
        if generation != self._scan_generation:
            return  # veralteter Scan
        self.tree.clear()
        self._items.clear()
        for folder_path, parent_path, pdf_count in entries:
            parent_item = self._items.get(parent_path) if parent_path else None
            if parent_path is not None and parent_item is None:
                continue
            item = QTreeWidgetItem(self.tree) if parent_item is None else QTreeWidgetItem(parent_item)
            item.setText(0, self._item_text(folder_path, pdf_count))
            item.setData(0, Qt.ItemDataRole.UserRole, str(folder_path))
            item.setToolTip(0, str(folder_path))
            if folder_path in self._suggestion_folders:
                item.setBackground(0, Qt.GlobalColor.green)
            self._items[folder_path] = item

        # Alle Einträge expandieren (erste Ebene)
        self.tree.expandToDepth(0)
        self.scan_finished.emit()

    @staticmethod
    def _item_text(folder_path: Path, pdf_count: int) -> str:
        return f"📁 {folder_path.name}  [{pdf_count}]" if pdf_count > 0 else f"📁 {folder_path.name}"

    def add_folder_incremental(self, folder_path: Path) -> bool:
        """Fuegt einen einzelnen Ordner unter seinem (vorhandenen) Elternteil ein."""
        folder_path = Path(folder_path)
        if folder_path in self._items:
            return True
        parent_item = self._items.get(folder_path.parent)
        if parent_item is None:
            return False
        item = QTreeWidgetItem(parent_item)
        item.setText(0, self._item_text(folder_path, self._count_pdfs(folder_path)))
        item.setData(0, Qt.ItemDataRole.UserRole, str(folder_path))
        item.setToolTip(0, str(folder_path))
        self._items[folder_path] = item
        parent_item.sortChildren(0, Qt.SortOrder.AscendingOrder)
        return True

    def _add_folder_item(
        self,
        folder_path: Path,
        parent_item: Optional[QTreeWidgetItem],
        max_depth: int = 3,
        current_depth: int = 0
    ) -> QTreeWidgetItem:
        """
        Fügt einen Ordner und seine Unterordner zum Baum hinzu.

        Args:
            folder_path: Pfad zum Ordner
            parent_item: Übergeordnetes Item (None für Root)
            max_depth: Maximale Tiefe für Unterordner
            current_depth: Aktuelle Tiefe

        Returns:
            Das erstellte QTreeWidgetItem
        """
        # PDF-Anzahl im Ordner zählen
        pdf_count = self._count_pdfs(folder_path)

        # Item-Text formatieren
        display_name = folder_path.name
        if pdf_count > 0:
            display_text = f"📁 {display_name}  [{pdf_count}]"
        else:
            display_text = f"📁 {display_name}"

        # Item erstellen
        if parent_item is None:
            item = QTreeWidgetItem(self.tree)
        else:
            item = QTreeWidgetItem(parent_item)

        item.setText(0, display_text)
        item.setData(0, Qt.ItemDataRole.UserRole, str(folder_path))
        item.setToolTip(0, str(folder_path))
        self._items[folder_path] = item

        # Styling für Vorschläge
        if folder_path in self._suggestion_folders:
            item.setBackground(0, Qt.GlobalColor.green)

        # Unterordner hinzufügen (rekursiv, bis max_depth)
        if current_depth < max_depth:
            try:
                subfolders = sorted([
                    p for p in folder_path.iterdir()
                    if p.is_dir() and not p.name.startswith('.')
                ])
                for subfolder in subfolders:
                    self._add_folder_item(
                        subfolder,
                        item,
                        max_depth,
                        current_depth + 1
                    )
            except PermissionError:
                pass  # Keine Berechtigung, überspringen

        return item

    def has_folder(self, folder: Path) -> bool:
        """True, wenn der Ordner als Item im Baum vorhanden ist."""
        return Path(folder) in self._items

    def refresh_counts(self, folders) -> int:
        """
        Aktualisiert nur die PDF-Zaehler der angegebenen Ordner (Issue #28).

        Nach einem Verschieben aendern sich nur Quell- und Zielordner - ein
        kompletter Neuaufbau (alle Ordner 3 Ebenen tief listen) ist auf
        OneDrive/Netzlaufwerken der teuerste Teil des Vorgangs.

        Returns:
            Anzahl der aktualisierten Items
        """
        updated = 0
        for folder in folders:
            item = self._items.get(Path(folder))
            if item is None:
                continue
            folder_path = Path(folder)
            item.setText(0, self._item_text(folder_path, self._count_pdfs(folder_path)))
            updated += 1
        return updated

    def _count_pdfs(self, folder: Path) -> int:
        """Zählt PDFs in einem Ordner (nicht rekursiv)."""
        try:
            return sum(
                1 for f in folder.iterdir()
                if f.is_file() and f.suffix.lower() == '.pdf'
            )
        except PermissionError:
            return 0

    def _update_item_styles(self):
        """Aktualisiert die Styles aller Items basierend auf Vorschlägen."""
        def update_recursive(item: QTreeWidgetItem):
            folder_path = Path(item.data(0, Qt.ItemDataRole.UserRole))
            if folder_path in self._suggestion_folders:
                item.setBackground(0, Qt.GlobalColor.green)
            else:
                item.setBackground(0, Qt.GlobalColor.transparent)

            for i in range(item.childCount()):
                update_recursive(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            update_recursive(self.tree.topLevelItem(i))

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Merkt den Klick vor; ausgefuehrt wird er erst, wenn kein Doppelklick folgt."""
        self._pending_click_item = item
        self._click_timer.start()

    def _fire_pending_click(self):
        """Fuehrt den vorgemerkten Einfachklick aus (Auswahl -> PDF verschieben)."""
        item = self._pending_click_item
        self._pending_click_item = None
        if item is None:
            return
        folder_path = Path(item.data(0, Qt.ItemDataRole.UserRole))
        self._selected_folder = folder_path
        self.folder_selected.emit(folder_path)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Doppelklick = Ordner links oeffnen; der vorgemerkte Klick verfaellt."""
        self._click_timer.stop()
        self._pending_click_item = None
        folder_path = Path(item.data(0, Qt.ItemDataRole.UserRole))
        self.folder_double_clicked.emit(folder_path)

    def _show_context_menu(self, position):
        """Zeigt das Kontextmenü an."""
        item = self.tree.itemAt(position)
        if item is None:
            return

        folder_path = Path(item.data(0, Qt.ItemDataRole.UserRole))
        menu = QMenu(self)

        # Links im Scan-Bereich oeffnen (wie Doppelklick)
        goto_action = menu.addAction("📁 Ordner links öffnen")
        goto_action.triggered.connect(lambda: self.folder_double_clicked.emit(folder_path))

        # Im Explorer öffnen
        open_action = menu.addAction("📂 Im Windows-Explorer öffnen")
        open_action.triggered.connect(lambda: self._open_in_explorer(folder_path))

        menu.addSeparator()

        # Neuen Unterordner erstellen
        new_folder_action = menu.addAction("➕ Neuen Unterordner erstellen")
        new_folder_action.triggered.connect(lambda: self._create_subfolder(folder_path))

        menu.addSeparator()

        # Aus Liste entfernen (nur für Root-Ordner)
        if folder_path in self._root_folders:
            remove_action = menu.addAction("❌ Aus Zielliste entfernen")
            remove_action.triggered.connect(lambda: self._remove_folder(folder_path))

        menu.exec(self.tree.mapToGlobal(position))

    def _open_in_explorer(self, folder_path: Path):
        """Öffnet den Ordner im Explorer."""
        import os
        import subprocess
        import sys

        if sys.platform == 'win32':
            os.startfile(str(folder_path))
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(folder_path)])
        else:
            subprocess.run(['xdg-open', str(folder_path)])

    def _create_subfolder(self, parent_folder: Path):
        """Erstellt einen neuen Unterordner."""
        name, ok = QInputDialog.getText(
            self,
            "Neuer Unterordner",
            "Name des neuen Ordners:",
        )

        if ok and name:
            new_folder = parent_folder / name
            try:
                new_folder.mkdir(exist_ok=True)
                self.refresh_tree()
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Fehler",
                    f"Ordner konnte nicht erstellt werden:\n{e}"
                )

    def _remove_folder(self, folder_path: Path):
        """Entfernt einen Ordner aus der Liste (löscht nicht vom Dateisystem)."""
        self.remove_root_folder(folder_path)
        self.folder_removed.emit(folder_path)

    # === Drag & Drop ===

    def _tree_drag_enter(self, event: QDragEnterEvent):
        """Behandelt das Eintreten eines Drag-Objekts."""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith('.pdf'):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def _tree_drag_move(self, event):
        """Behandelt die Bewegung eines Drag-Objekts mit visuellem Feedback."""
        if event.mimeData().hasUrls():
            item = self.tree.itemAt(event.position().toPoint())

            # Altes Hover-Item zurücksetzen
            if self._drag_hover_item and self._drag_hover_item != item:
                self._reset_item_style(self._drag_hover_item)

            if item:
                # Neues Item hervorheben
                self._drag_hover_item = item
                self._highlight_drop_target(item)
                event.acceptProposedAction()
                return

        # Kein gültiges Ziel - altes Hover zurücksetzen
        if self._drag_hover_item:
            self._reset_item_style(self._drag_hover_item)
            self._drag_hover_item = None
        event.ignore()

    def _tree_drag_leave(self, event):
        """Behandelt das Verlassen des Drag-Bereichs."""
        if self._drag_hover_item:
            self._reset_item_style(self._drag_hover_item)
            self._drag_hover_item = None

    def _tree_drop(self, event: QDropEvent):
        """Behandelt das Ablegen von Dateien."""
        # Hover-Highlighting zurücksetzen
        if self._drag_hover_item:
            self._reset_item_style(self._drag_hover_item)
            self._drag_hover_item = None

        if not event.mimeData().hasUrls():
            event.ignore()
            return

        item = self.tree.itemAt(event.position().toPoint())
        if item is None:
            event.ignore()
            return

        folder_path = Path(item.data(0, Qt.ItemDataRole.UserRole))

        for url in event.mimeData().urls():
            file_path = Path(url.toLocalFile())
            if file_path.suffix.lower() == '.pdf':
                self.pdf_dropped.emit(file_path, folder_path)

        event.acceptProposedAction()

    def _highlight_drop_target(self, item: QTreeWidgetItem):
        """Hebt ein Item als Drop-Ziel hervor."""
        from PyQt6.QtGui import QBrush, QColor
        item.setBackground(0, QBrush(QColor("#90EE90")))  # Hellgrün

    def _reset_item_style(self, item: QTreeWidgetItem):
        """Setzt den Style eines Items zurück."""
        folder_path = Path(item.data(0, Qt.ItemDataRole.UserRole))
        if folder_path in self._suggestion_folders:
            item.setBackground(0, Qt.GlobalColor.green)
        else:
            item.setBackground(0, Qt.GlobalColor.transparent)

    def get_selected_folder(self) -> Optional[Path]:
        """Gibt den aktuell ausgewählten Ordner zurück."""
        return self._selected_folder

    def select_folder(self, folder_path: Path):
        """
        Wählt einen Ordner im Baum aus und expandiert den Pfad dorthin.

        Args:
            folder_path: Pfad zum Ordner
        """
        folder_path = Path(folder_path)

        def find_and_select(item: QTreeWidgetItem) -> bool:
            item_path = Path(item.data(0, Qt.ItemDataRole.UserRole))
            if item_path == folder_path:
                self.tree.setCurrentItem(item)
                self._selected_folder = folder_path
                return True

            for i in range(item.childCount()):
                if find_and_select(item.child(i)):
                    item.setExpanded(True)
                    return True
            return False

        for i in range(self.tree.topLevelItemCount()):
            if find_and_select(self.tree.topLevelItem(i)):
                break

    def get_relative_path(self, folder_path: Path) -> str:
        """
        Gibt den relativen Pfad eines Ordners zu seinem Root-Ordner zurück.

        Args:
            folder_path: Absoluter Pfad zum Ordner

        Returns:
            Relativer Pfad (z.B. "Steuer 2026/Banken") oder Ordnername wenn Root
        """
        folder_path = Path(folder_path)

        for root in self._root_folders:
            try:
                relative = folder_path.relative_to(root.parent)
                return str(relative)
            except ValueError:
                continue

        return folder_path.name

    def expand_to_folder(self, folder_path: Path):
        """Expandiert den Baum bis zum angegebenen Ordner."""
        self.select_folder(folder_path)

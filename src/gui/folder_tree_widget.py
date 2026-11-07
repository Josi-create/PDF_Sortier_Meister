"""
Ordner-Baum-Widget für PDF Sortier Meister

Zeigt eine hierarchische Ordnerstruktur als Baumansicht an.
Unterstützt Unterordner und zeigt PDF-Anzahlen an.

GPL-3.0-or-later - Copyright (c) 2026
"""

import os
import re
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread, QFile
from PyQt6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
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
    QApplication,
)


class _TreeScanThread(QThread):
    """Listet die Zielordner-Hierarchie im Hintergrund (Issue #28).

    Auf OneDrive/Netzlaufwerken dauert das Listen aller Ordner 3 Ebenen tief
    inkl. PDF-Zaehlung viele Sekunden - im UI-Thread friert dabei alles ein.
    Ergebnis: Liste von (folder_path, parent_path | None, pdf_count, has_more).
    has_more: Ordner auf der tiefsten Ebene hat weitere Unterordner, die erst
    beim Aufklappen nachgeladen werden.
    """

    scanned = pyqtSignal(int, list, list)  # (generation, roots, entries)

    def __init__(self, roots: list[Path], generation: int, max_depth: int = 3, parent=None):
        super().__init__(parent)
        self._roots = roots
        self._generation = generation
        self._max_depth = max_depth

    def run(self):
        entries: list[tuple[Path, Optional[Path], int, bool]] = []

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
            at_limit = depth >= self._max_depth
            entries.append((folder, parent, pdf_count, at_limit and bool(subfolders)))
            if not at_limit:
                for sub in sorted(subfolders):
                    scan(sub, folder, depth + 1)

        for root in self._roots:
            if root.exists():
                scan(root, None, 0)
        self.scanned.emit(self._generation, self._roots, entries)


class FolderTreeWidget(QWidget):
    """Widget zur hierarchischen Anzeige von Zielordnern."""

    # Zusatztext fuer die Tooltips einzelner Ordner-Items: erklaert den
    # Kern-Workflow, der sonst fuer neue Nutzer unsichtbar ist (Issue #51).
    _CLICK_HINT = (
        "\n\nEinfachklick: ausgewaehlte PDF hierher verschieben.\n"
        "Doppelklick: als Scan-Ordner links oeffnen (Navigation).\n"
        "Pfeil rechts klappt auf, * klappt alle Unterordner auf.\n"
        "Rechtsklick: weitere Aktionen."
    )

    # Verweildauer, nach der ein zugeklappter Ordner beim Darueberziehen
    # einer PDF aufklappt
    DRAG_AUTO_EXPAND_MS = 700

    # Signale
    folder_selected = pyqtSignal(Path)  # Ordner wurde ausgewählt
    folder_double_clicked = pyqtSignal(Path)  # Ordner wurde doppelgeklickt
    pdf_dropped = pyqtSignal(Path, Path)  # PDF auf Ordner gezogen (pdf_path, folder_path)
    folder_removed = pyqtSignal(Path)  # Ordner aus Liste entfernt
    scan_finished = pyqtSignal()  # Baum wurde (neu) befuellt
    move_here_requested = pyqtSignal(Path)  # Kontextmenue "Hierhin verschieben" (Issue #93)
    folder_renamed = pyqtSignal(Path, Path)  # Ordner umbenannt (alt, neu)
    status_message = pyqtSignal(str)  # Kurzinfo fuer die Statusleiste

    # Kontextmenue (Issue #93)
    EXPAND_LEVELS = 3  # "Alle Unterordner aufklappen": so viele Ebenen tief
    EXPAND_MAX_FOLDERS = 300  # Obergrenze, damit grosse Baeume bedienbar bleiben
    SUBMENU_MAX_ENTRIES = 40  # "Unterordner oeffnen": mehr Eintraege -> Rest im Baum
    _INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root_folders: list[Path] = []
        self._items: dict[Path, QTreeWidgetItem] = {}  # Pfad -> Item (fuer refresh_counts)
        # Ordner mit noch nicht geladenen Unterordnern (unterhalb der Scan-Tiefe)
        self._unloaded: set[Path] = set()
        self._subtree_threads: set[_TreeScanThread] = set()
        self._scan_generation = 0  # verwirft Ergebnisse veralteter Scans
        self._scan_thread: Optional[_TreeScanThread] = None
        self.async_scan = True  # Tests koennen synchron scannen
        self._selected_folder: Optional[Path] = None
        # MainWindow setzt hier eine Funktion, die sagt, ob links PDFs ausgewaehlt
        # sind ("Hierhin verschieben" ist sonst deaktiviert).
        self.has_pdf_selection = lambda: False
        self._view_root: Optional[Path] = None  # "Als Wurzel anzeigen" (nicht gespeichert)
        self._pending_expand: dict[Path, int] = {}  # Ordner -> Restebenen nach dem Nachladen
        self._expand_budget = 0
        self._suggestion_folders: list[Path] = []  # Vorgeschlagene Ordner
        self._drag_hover_item: Optional[QTreeWidgetItem] = None  # Aktuell gehoverte Item beim Drag
        # Klappt den Ordner unter der gezogenen PDF nach kurzem Verweilen auf.
        # Eigener Timer statt Qts autoExpandDelay: der fragt die echte
        # Mausposition ab und greift nur fuer baum-eigene Eintraege.
        self._drag_expand_timer = QTimer(self)
        self._drag_expand_timer.setSingleShot(True)
        self._drag_expand_timer.setInterval(self.DRAG_AUTO_EXPAND_MS)
        self._drag_expand_timer.timeout.connect(self._expand_drag_hover_item)

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

        # Leiste "Teilbaum als Wurzel" (Issue #93); nur sichtbar, wenn aktiv
        self.view_root_bar = QWidget()
        bar_layout = QHBoxLayout(self.view_root_bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        self.view_root_label = QLabel()
        self.view_root_label.setStyleSheet("font-size: 11px;")
        bar_layout.addWidget(self.view_root_label, stretch=1)
        self.view_root_back_btn = QPushButton("↩ Zurück zur Gesamtansicht")
        self.view_root_back_btn.clicked.connect(lambda: self.set_view_root(None))
        bar_layout.addWidget(self.view_root_back_btn)
        self.view_root_bar.setVisible(False)
        layout.addWidget(self.view_root_bar)

        # Tree Widget
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(20)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        # Beim Ziehen einer PDF: am Rand automatisch scrollen und zugeklappte
        # Ordner nach kurzem Verweilen aufklappen - wie in PaperPort erreicht
        # man so jeden Ordner, ohne die Maus loszulassen.
        self.tree.setAutoScroll(True)
        self.tree.setToolTip(
            "Einfachklick auf einen Ordner: ausgewaehlte PDF hierher verschieben.\n"
            "Doppelklick: Ordner links als Scan-Ordner oeffnen (Navigation).\n"
            "Pfeil rechts klappt einen Ordner auf, * alle Unterordner.\n"
            "Rechtsklick: weitere Aktionen.\n"
            "PDFs koennen auch per Drag & Drop hierher gezogen werden."
        )

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
        self.tree.itemExpanded.connect(self._on_item_expanded)
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
        self._pending_expand.clear()
        roots = self._effective_roots()
        if not self.async_scan:
            thread = _TreeScanThread(roots, self._scan_generation)
            thread.scanned.connect(self._on_scan_finished)
            thread.run()  # synchron, im aktuellen Thread
            return

        # Sofort etwas zeigen: Wurzeln ohne Zaehler, Rest folgt nach dem Scan
        self.tree.clear()
        self._items.clear()
        self._unloaded.clear()
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

    def _effective_roots(self) -> list[Path]:
        """Wurzeln der Anzeige: der gewaehlte Teilbaum oder alle Zielordner."""
        if self._view_root is not None:
            if self._view_root.is_dir():
                return [self._view_root]
            self._view_root = None  # Teilbaum existiert nicht mehr
            self.view_root_bar.setVisible(False)
        return [r for r in self._root_folders if r.exists()]

    def view_root(self) -> Optional[Path]:
        """Aktueller Teilbaum-Ausschnitt oder None bei Gesamtansicht."""
        return self._view_root

    def set_view_root(self, folder: Optional[Path]):
        """Zeigt nur den Teilbaum ab folder (None = Gesamtansicht)."""
        self._view_root = Path(folder) if folder is not None else None
        if self._view_root is not None:
            self.view_root_label.setText(f"🔎 Ansicht: {self._view_root.name}")
            self.view_root_label.setToolTip(str(self._view_root))
        self.view_root_bar.setVisible(self._view_root is not None)
        self.refresh_tree()

    def _on_scan_finished(self, generation: int, roots: list, entries: list):
        """Befuellt den Baum aus dem Scan-Ergebnis (UI-Thread)."""
        if generation != self._scan_generation:
            return  # veralteter Scan
        self.tree.clear()
        self._items.clear()
        self._unloaded.clear()
        self._insert_entries(entries)

        # Alle Einträge expandieren (erste Ebene)
        self.tree.expandToDepth(0)
        self.scan_finished.emit()

    def _insert_entries(self, entries: list):
        """Haengt Scan-Eintraege ein; schon vorhandene Ordner bleiben unberuehrt."""
        for folder_path, parent_path, pdf_count, has_more in entries:
            if folder_path in self._items:
                continue
            parent_item = self._items.get(parent_path) if parent_path else None
            if parent_path is not None and parent_item is None:
                continue
            item = QTreeWidgetItem(self.tree) if parent_item is None else QTreeWidgetItem(parent_item)
            item.setText(0, self._item_text(folder_path, pdf_count))
            item.setData(0, Qt.ItemDataRole.UserRole, str(folder_path))
            item.setToolTip(0, str(folder_path) + self._CLICK_HINT)
            if folder_path in self._suggestion_folders:
                item.setBackground(0, Qt.GlobalColor.green)
            self._items[folder_path] = item
            if has_more:
                self._mark_unloaded(folder_path, item)

    def _mark_unloaded(self, folder_path: Path, item: QTreeWidgetItem):
        """Zeigt den Aufklapp-Pfeil, obwohl die Unterordner noch fehlen."""
        self._unloaded.add(folder_path)
        item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)

    def _on_item_expanded(self, item: QTreeWidgetItem):
        """Laedt beim ersten Aufklappen die Unterordner unterhalb der Scan-Tiefe nach."""
        folder_path = Path(item.data(0, Qt.ItemDataRole.UserRole))
        if folder_path not in self._unloaded:
            return
        self._unloaded.discard(folder_path)
        # eine Ebene listen; deren Unterordner bekommen wieder nur den Pfeil
        thread = _TreeScanThread([folder_path], self._scan_generation, max_depth=1, parent=self)
        thread.scanned.connect(self._on_subtree_scanned)
        if not self.async_scan:
            thread.run()  # synchron, im aktuellen Thread
            return
        self._subtree_threads.add(thread)
        thread.finished.connect(lambda t=thread: self._subtree_threads.discard(t))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _on_subtree_scanned(self, generation: int, roots: list, entries: list):
        """Haengt nachgeladene Unterordner unter den aufgeklappten Ordner."""
        if generation != self._scan_generation:
            return  # Baum wurde inzwischen neu aufgebaut
        item = self._items.get(roots[0]) if roots else None
        if item is None:
            return
        self._insert_entries(entries)
        item.sortChildren(0, Qt.SortOrder.AscendingOrder)
        # Pfeil wieder vom Inhalt abhaengig machen (Ordner evtl. inzwischen leer)
        item.setChildIndicatorPolicy(
            QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicatorWhenChildless
        )
        # "Alle Unterordner aufklappen" ging hier weiter, sobald die Ebene geladen ist
        levels = self._pending_expand.pop(roots[0], 0)
        if levels > 1:
            for i in range(item.childCount()):
                self._expand_levels(item.child(i), levels - 1)

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
        item.setToolTip(0, str(folder_path) + self._CLICK_HINT)
        self._items[folder_path] = item
        if self._has_subfolders(folder_path):
            self._mark_unloaded(folder_path, item)
        parent_item.sortChildren(0, Qt.SortOrder.AscendingOrder)
        return True

    @staticmethod
    def _has_subfolders(folder: Path) -> bool:
        try:
            with os.scandir(folder) as it:
                return any(
                    e.is_dir() and not e.name.startswith('.') for e in it
                )
        except OSError:
            return False

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
        item.setToolTip(0, str(folder_path) + self._CLICK_HINT)
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
        self._build_context_menu(folder_path).exec(self.tree.mapToGlobal(position))

    def _build_context_menu(self, folder_path: Path) -> QMenu:
        """Baut das Kontextmenue fuer einen Ordner (getrennt, damit es testbar ist)."""
        from src.gui.pfad_aktionen import PFAD_KOPIEREN_TEXT, pfad_kopieren
        from src.utils.platform_paths import file_manager_name

        menu = QMenu(self)
        item = self._items.get(folder_path)
        is_root = folder_path in self._root_folders

        # --- Navigation ---
        goto_action = menu.addAction("📁 Ordner links öffnen")
        goto_action.triggered.connect(lambda: self.folder_double_clicked.emit(folder_path))

        sub_menu = menu.addMenu("📂 Unterordner öffnen")
        sub_menu.setStyleSheet("QMenu { menu-scrollable: 1; }")
        sub_menu.aboutToShow.connect(lambda: self._fill_subfolder_menu(sub_menu, folder_path))
        sub_menu.setEnabled(self._has_subfolders(folder_path))

        has_children = item is not None and (
            item.childCount() > 0 or folder_path in self._unloaded
        )
        expand_action = menu.addAction("➕ Alle Unterordner aufklappen")
        expand_action.setEnabled(has_children)
        expand_action.triggered.connect(lambda: self._expand_subtree(folder_path))

        collapse_action = menu.addAction("➖ Unterordner zuklappen")
        collapse_action.setEnabled(item is not None and item.childCount() > 0)
        collapse_action.triggered.connect(lambda: self._collapse_subtree(folder_path))

        collapse_all_action = menu.addAction("➖ Alles zuklappen")
        collapse_all_action.triggered.connect(self.tree.collapseAll)

        if folder_path != self._view_root:
            view_root_action = menu.addAction("🔎 Diesen Ordner als Wurzel anzeigen")
            view_root_action.triggered.connect(lambda: self.set_view_root(folder_path))

        menu.addSeparator()

        # --- Aktionen mit PDFs ---
        move_action = menu.addAction("📥 Hierhin verschieben")
        has_pdfs = bool(self.has_pdf_selection())
        move_action.setEnabled(has_pdfs)
        if not has_pdfs:
            move_action.setToolTip("Links ist keine PDF ausgewählt")
        move_action.triggered.connect(lambda: self.move_here_requested.emit(folder_path))

        menu.addSeparator()

        # --- Ordner verwalten ---
        new_folder_action = menu.addAction("➕ Neuen Unterordner erstellen")
        new_folder_action.triggered.connect(lambda: self._create_subfolder(folder_path))

        rename_action = menu.addAction("✏️ Ordner umbenennen")
        rename_action.triggered.connect(lambda: self._rename_folder(folder_path))

        delete_action = menu.addAction("🗑️ Ordner löschen (in den Papierkorb)")
        if is_root:
            delete_action.setEnabled(False)
            delete_action.setToolTip("Zielordner zuerst aus der Zielliste entfernen")
        elif not self._is_empty_dir(folder_path):
            delete_action.setEnabled(False)
            delete_action.setToolTip("Nur leere Ordner können gelöscht werden")
        delete_action.triggered.connect(lambda: self._delete_folder(folder_path))

        # Aus Liste entfernen (nur für Root-Ordner)
        if is_root:
            remove_action = menu.addAction("❌ Aus Zielliste entfernen")
            remove_action.triggered.connect(lambda: self._remove_folder(folder_path))

        menu.addSeparator()

        # --- Info / Dateimanager ---
        info_action = menu.addAction("ℹ️ Inhalt anzeigen")
        info_action.triggered.connect(lambda: self._show_folder_info(folder_path))

        # Im Dateimanager öffnen
        open_action = menu.addAction(f"📂 Im {file_manager_name()} öffnen")
        open_action.triggered.connect(lambda: self._open_in_explorer(folder_path))

        # Issue #154: Pfad in die Zwischenablage
        copy_action = menu.addAction(f"📋 {PFAD_KOPIEREN_TEXT}")
        copy_action.triggered.connect(lambda: pfad_kopieren(folder_path))

        return menu

    # === Kontextmenue-Aktionen (Issue #93) ===

    @staticmethod
    def _list_subfolders(folder: Path) -> list[Path]:
        """Direkte Unterordner (ohne versteckte), sortiert."""
        try:
            with os.scandir(folder) as it:
                subs = [Path(e.path) for e in it
                        if e.is_dir() and not e.name.startswith('.')]
        except OSError:
            return []
        return sorted(subs, key=lambda p: p.name.lower())

    @staticmethod
    def _is_empty_dir(folder: Path) -> bool:
        try:
            with os.scandir(folder) as it:
                return next(it, None) is None
        except OSError:
            return False

    def _fill_subfolder_menu(self, sub_menu: QMenu, folder: Path):
        """Fuellt das Untermenue erst beim Oeffnen (Listing nur auf Anforderung)."""
        sub_menu.clear()
        subs = self._list_subfolders(folder)
        for sub in subs[:self.SUBMENU_MAX_ENTRIES]:
            action = sub_menu.addAction(f"📁 {sub.name}")
            action.triggered.connect(lambda checked=False, p=sub: self._open_subfolder(p))
        rest = len(subs) - self.SUBMENU_MAX_ENTRIES
        if rest > 0:
            more = sub_menu.addAction(f"… {rest} weitere (im Baum aufklappen)")
            more.triggered.connect(lambda: self._expand_one(folder))
        if not subs:
            sub_menu.addAction("(keine Unterordner)").setEnabled(False)

    def _expand_one(self, folder: Path):
        item = self._items.get(Path(folder))
        if item is not None:
            item.setExpanded(True)
            self.tree.scrollToItem(item)

    def _open_subfolder(self, folder: Path):
        """Klappt den Ordner auf, markiert ihn und scrollt hin (ohne PDF-Verschiebung)."""
        folder = Path(folder)
        if not self._ensure_folder_item(folder):
            return
        self._mark_folder(folder)
        item = self._items.get(folder)
        if item is not None:
            item.setExpanded(True)
            self.tree.scrollToItem(item)

    def _expand_levels(self, item: QTreeWidgetItem, levels: int):
        """Klappt item und darunter bis zu `levels` Ebenen auf (begrenzt, mit Nachladen)."""
        if levels <= 0 or self._expand_budget <= 0:
            return
        path = Path(item.data(0, Qt.ItemDataRole.UserRole))
        unloaded = path in self._unloaded
        if item.childCount() == 0 and not unloaded:
            return
        self._expand_budget -= 1
        if unloaded:
            # Nachladen beim Aufklappen; _on_subtree_scanned setzt fort
            self._pending_expand[path] = levels
            item.setExpanded(True)
            return
        item.setExpanded(True)
        for i in range(item.childCount()):
            self._expand_levels(item.child(i), levels - 1)

    def _expand_subtree(self, folder: Path):
        item = self._items.get(Path(folder))
        if item is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.tree.setUpdatesEnabled(False)
        try:
            self._expand_budget = self.EXPAND_MAX_FOLDERS
            self._expand_levels(item, self.EXPAND_LEVELS)
        finally:
            self.tree.setUpdatesEnabled(True)
            QApplication.restoreOverrideCursor()
        self.tree.scrollToItem(item)

    def _collapse_subtree(self, folder: Path):
        item = self._items.get(Path(folder))
        if item is None:
            return

        def collapse(it: QTreeWidgetItem):
            for i in range(it.childCount()):
                collapse(it.child(i))
            it.setExpanded(False)

        collapse(item)

    def _show_folder_info(self, folder: Path):
        """Kurzinfo (nicht rekursiv): Anzahl PDFs, weitere Dateien und Unterordner."""
        pdfs = others = dirs = 0
        try:
            with os.scandir(folder) as it:
                for e in it:
                    try:
                        if e.is_dir():
                            dirs += 1
                        elif e.name.lower().endswith('.pdf'):
                            pdfs += 1
                        else:
                            others += 1
                    except OSError:
                        continue
        except OSError as e:
            self.status_message.emit(f"Inhalt von {folder.name} nicht lesbar: {e}")
            return
        self.status_message.emit(
            f"ℹ️ {folder.name}: {pdfs} PDF{'s' if pdfs != 1 else ''}, "
            f"{others} weitere Datei{'en' if others != 1 else ''}, "
            f"{dirs} Unterordner"
        )

    def _validate_new_name(self, old: Path, name: str) -> Optional[str]:
        """None wenn der Name passt, sonst die Fehlermeldung."""
        if self._INVALID_NAME.search(name):
            return 'Der Name darf keines dieser Zeichen enthalten: < > : " / \\ | ? *'
        if name.endswith(('.', ' ')) or name in ('.', '..'):
            return "Der Name darf nicht mit Punkt oder Leerzeichen enden."
        new = old.parent / name
        case_only = name.lower() == old.name.lower()
        if new.exists() and not case_only:
            return f"Es gibt hier bereits einen Eintrag namens „{name}“."
        return None

    def _rename_folder(self, folder: Path):
        """Benennt den Ordner um und zieht Baum und Zielpfade nach."""
        folder = Path(folder)
        name, ok = QInputDialog.getText(
            self, "Ordner umbenennen", "Neuer Name:", text=folder.name
        )
        name = (name or "").strip()
        if not ok or not name or name == folder.name:
            return
        error = self._validate_new_name(folder, name)
        if error:
            QMessageBox.warning(self, "Umbenennen nicht möglich", error)
            return
        new = folder.parent / name
        try:
            folder.rename(new)
        except OSError as e:
            QMessageBox.critical(
                self, "Fehler", f"Ordner konnte nicht umbenannt werden:\n{e}"
            )
            return
        self._remap_paths(folder, new)
        self.folder_renamed.emit(folder, new)

    def _remap_paths(self, old: Path, new: Path):
        """Schreibt die Pfade des umbenannten Teilbaums im Baum um (ohne Neuscan)."""
        def conv(p: Path) -> Path:
            return new / p.relative_to(old) if p == old or old in p.parents else p

        old_items = self._items
        self._items = {}
        for path, item in old_items.items():
            target = conv(path)
            self._items[target] = item
            if target != path:
                item.setData(0, Qt.ItemDataRole.UserRole, str(target))
                item.setToolTip(0, str(target) + self._CLICK_HINT)
        self._unloaded = {conv(p) for p in self._unloaded}
        self._root_folders = [conv(p) for p in self._root_folders]
        self._suggestion_folders = [conv(p) for p in self._suggestion_folders]
        self._pending_expand = {}
        if self._selected_folder is not None:
            self._selected_folder = conv(self._selected_folder)
        if self._view_root is not None:
            self._view_root = conv(self._view_root)
            self.view_root_label.setText(f"🔎 Ansicht: {self._view_root.name}")
            self.view_root_label.setToolTip(str(self._view_root))
        item = self._items.get(new)
        if item is not None:
            item.setText(0, item.text(0).replace(f"📁 {old.name}", f"📁 {new.name}", 1))
            parent = item.parent()
            if parent is not None:
                parent.sortChildren(0, Qt.SortOrder.AscendingOrder)

    def _delete_folder(self, folder: Path):
        """Legt einen leeren Ordner in den Papierkorb (nach Rueckfrage)."""
        folder = Path(folder)
        if not self._is_empty_dir(folder):
            QMessageBox.information(
                self, "Ordner nicht leer",
                "Es können nur leere Ordner gelöscht werden.",
            )
            return
        answer = QMessageBox.question(
            self, "Ordner löschen",
            f"Leeren Ordner „{folder.name}“ in den Papierkorb legen?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = QFile.moveToTrash(str(folder))
        trashed = result[0] if isinstance(result, tuple) else bool(result)
        if not trashed:
            QMessageBox.critical(
                self, "Fehler", f"Ordner konnte nicht in den Papierkorb gelegt werden:\n{folder}"
            )
            return
        item = self._items.pop(folder, None)
        self._unloaded.discard(folder)
        if item is not None:
            parent = item.parent()
            if parent is not None:
                parent.removeChild(item)
            else:
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        if self._selected_folder == folder:
            self._selected_folder = None
        self.status_message.emit(f"🗑️ Ordner in den Papierkorb gelegt: {folder.name}")

    def _open_in_explorer(self, folder_path: Path):
        """Öffnet den Ordner im Dateimanager des Systems."""
        from src.utils.platform_paths import open_with_default_app

        open_with_default_app(folder_path)

    def _create_subfolder(self, parent_folder: Path):
        """Erstellt einen neuen Unterordner."""
        name, ok = QInputDialog.getText(
            self,
            "Neuer Unterordner",
            "Name des neuen Ordners:",
        )

        name = (name or "").strip()
        if ok and name:
            new_folder = parent_folder / name
            try:
                new_folder.mkdir(exist_ok=True)
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Fehler",
                    f"Ordner konnte nicht erstellt werden:\n{e}"
                )
                return
            self._show_new_folder(new_folder)

    def _show_new_folder(self, new_folder: Path):
        """Zeigt einen frisch angelegten Ordner markiert im Baum an.

        Nur markieren, nicht "anklicken": ein Klick (folder_selected) wuerde
        die ausgewaehlte PDF sofort dorthin verschieben.
        """
        if self._ensure_folder_item(new_folder):
            self._mark_folder(new_folder)
            return

        # Kein Vorfahr im Baum (z.B. Baum wird gerade noch geladen):
        # neu scannen und danach markieren.
        def _after_scan():
            try:
                self.scan_finished.disconnect(_after_scan)
            except TypeError:
                pass
            if self._ensure_folder_item(new_folder):
                self._mark_folder(new_folder)

        self.scan_finished.connect(_after_scan)
        self.refresh_tree()

    def _ensure_folder_item(self, folder: Path) -> bool:
        """Haengt den Ordner samt fehlender Zwischenordner in den Baum ein.

        Der Baum laedt nur wenige Ebenen tief; ein neuer Ordner darunter haette
        sonst keinen sichtbaren Elternteil.
        """
        folder = Path(folder)
        missing = []
        current = folder
        while current not in self._items:
            if current.parent == current:
                return False  # kein Vorfahr im Baum
            missing.append(current)
            current = current.parent
        for path in reversed(missing):
            if not self.add_folder_incremental(path):
                return False
        return True

    def _mark_folder(self, folder: Path):
        """Markiert den Ordner, klappt den Pfad auf und scrollt ihn ins Bild."""
        self.select_folder(folder)
        item = self._items.get(Path(folder))
        if item is not None:
            self.tree.scrollToItem(item)

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

    def _end_tree_drag(self):
        """Beendet Auto-Scroll und Auto-Aufklappen nach Drop oder Verlassen.

        Qts eigenes dragLeaveEvent stoppt den Scroll-Timer und setzt den
        Zustand zurueck (stopAutoScroll ist in PyQt nicht erreichbar).
        """
        self._drag_expand_timer.stop()
        QTreeWidget.dragLeaveEvent(self.tree, QDragLeaveEvent())

    def _expand_drag_hover_item(self):
        """Klappt den Ordner auf, ueber dem die PDF gerade verweilt."""
        item = self._drag_hover_item
        if item is None or item.isExpanded():
            return
        folder_path = Path(item.data(0, Qt.ItemDataRole.UserRole))
        if item.childCount() > 0 or folder_path in self._unloaded:
            item.setExpanded(True)

    def _tree_drag_move(self, event):
        """Behandelt die Bewegung eines Drag-Objekts mit visuellem Feedback."""
        # Qt-Grundverhalten zuerst: startet Auto-Scroll am Rand.
        # Annehmen/Ablehnen entscheidet danach der Code unten.
        QTreeWidget.dragMoveEvent(self.tree, event)
        if event.mimeData().hasUrls():
            item = self.tree.itemAt(event.position().toPoint())

            # Altes Hover-Item zurücksetzen
            if self._drag_hover_item and self._drag_hover_item != item:
                self._reset_item_style(self._drag_hover_item)

            if item:
                # Neues Item hervorheben; Verweilzeit fuers Aufklappen neu starten
                if item is not self._drag_hover_item:
                    self._drag_expand_timer.start()
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
        self._end_tree_drag()
        if self._drag_hover_item:
            self._reset_item_style(self._drag_hover_item)
            self._drag_hover_item = None

    def _tree_drop(self, event: QDropEvent):
        """Behandelt das Ablegen von Dateien."""
        self._end_tree_drag()
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

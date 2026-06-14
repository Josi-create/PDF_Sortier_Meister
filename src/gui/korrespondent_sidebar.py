"""
Sidebar-Widget fuer die Korrespondenten-Verwaltung (Phase 20 / Issue #21).

Zeigt eine QListView mit allen verwalteten Korrespondenten. Ein Klick
auf einen Eintrag emittiert das Signal ``korrespondent_selected`` mit
dem Namen (oder ``None`` fuer den "Alle"-Eintrag oben).

Buttons:
    * "+ Neu" - legt einen neuen Korrespondenten an
    * "Bearbeiten" - bearbeitet den aktuell ausgewaehlten Korrespondenten
    * "Zusammenfuehren" - oeffnet den Merge-Dialog (Multi-Select 2+)
    * "Aktualisieren" - laedt die Liste neu aus der DB
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.utils.database import Database, Korrespondent
from src.gui.korrespondent_edit_dialog import KorrespondentEditDialog
from src.gui.korrespondent_merge_dialog import KorrespondentMergeDialog


# Sentinel-Datenwert fuer "Alle" (None-Eintrag)
_ALL_USERDATA = "__ALL__"


class _KorrespondentListItem(QListWidgetItem):
    """ListItem mit Farbpunkt-Darstellung.

    Setzt das Icon auf einen kleinen farbigen Kreis, wenn der
    Korrespondent eine ``farbe`` hat. Andernfalls bleibt der Default-Indikator.
    """

    def __init__(self, korr: dict, is_all: bool = False):
        super().__init__()
        self.korr = korr
        self.is_all = is_all
        name = korr.get("name", "") if not is_all else "Alle"
        kategorie = korr.get("kategorie") if not is_all else None
        usage = korr.get("usage_count", 0) if not is_all else 0
        text = str(name)
        if kategorie and not is_all:
            text = f"{name}  ({kategorie})"
        if usage and not is_all:
            text = f"{text}  -  {usage}x"
        self.setText(text)
        # UserData ist der Name (oder "" fuer "Alle")
        self.setData(Qt.ItemDataRole.UserRole, "" if is_all else str(name))

        # Tooltip mit Details
        if is_all:
            self.setToolTip("Filter aufheben - alle Dokumente anzeigen")
        else:
            aliases = korr.get("aliases") or []
            notiz = korr.get("notizen") or ""
            tip_parts = [f"Name: {name}"]
            if kategorie:
                tip_parts.append(f"Kategorie: {kategorie}")
            if aliases:
                tip_parts.append(f"Aliasse: {', '.join(aliases)}")
            if korr.get("farbe"):
                tip_parts.append(f"Farbe: {korr.get('farbe')}")
            tip_parts.append(f"Verwendet: {usage}x")
            if notiz:
                tip_parts.append(f"\nNotizen: {notiz}")
            self.setToolTip("\n".join(tip_parts))


class KorrespondentSidebar(QWidget):
    """Sidebar zur Korrespondenten-Verwaltung."""

    # Signal: Name des gewaehlten Korrespondenten, oder None fuer "Alle"
    korrespondent_selected = pyqtSignal(object)

    def __init__(self, db: Database, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.db = db
        self._setup_ui()
        self.refresh()

    # ------------------------------------------------------------------ #
    # UI-Aufbau
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Header
        header = QLabel("Korrespondenten")
        header.setStyleSheet("font-weight: bold; font-size: 13px; padding: 2px;")
        layout.addWidget(header)

        # Suchfeld (optional, nicht gefordert - bewusst weggelassen fuer KISS)

        # Liste
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list_widget, 1)

        # Buttons-Reihe 1: Aktionen
        button_row_1 = QHBoxLayout()
        self.new_btn = QPushButton("+ Neu")
        self.new_btn.setToolTip("Neuen Korrespondenten anlegen")
        self.new_btn.clicked.connect(self._on_new)
        button_row_1.addWidget(self.new_btn)

        self.edit_btn = QPushButton("Bearbeiten")
        self.edit_btn.setToolTip("Ausgewaehlten Korrespondenten bearbeiten")
        self.edit_btn.clicked.connect(self._on_edit)
        button_row_1.addWidget(self.edit_btn)

        layout.addLayout(button_row_1)

        # Buttons-Reihe 2: Merge + Refresh
        button_row_2 = QHBoxLayout()
        self.merge_btn = QPushButton("Zusammenfuehren")
        self.merge_btn.setToolTip(
            "2+ ausgewaehlte Korrespondenten zu einem Primaer zusammenfuehren"
        )
        self.merge_btn.clicked.connect(self._on_merge)
        button_row_2.addWidget(self.merge_btn)

        self.refresh_btn = QPushButton("Aktualisieren")
        self.refresh_btn.setToolTip("Liste aus der Datenbank neu laden")
        self.refresh_btn.clicked.connect(self.refresh)
        button_row_2.addWidget(self.refresh_btn)

        layout.addLayout(button_row_2)

        # Auto-Collect-Button
        self.collect_btn = QPushButton("Aus Historie sammeln")
        self.collect_btn.setToolTip(
            "Alle Korrespondenten aus der Sortierhistorie in die "
            "Verwaltungstabelle uebernehmen (einmalig pro Session)"
        )
        self.collect_btn.clicked.connect(self._on_collect_from_history)
        layout.addWidget(self.collect_btn)

    # ------------------------------------------------------------------ #
    # Daten-Refresh
    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        """Laedt die Korrespondenten-Liste aus der DB."""
        self.list_widget.clear()
        # "Alle"-Eintrag oben
        all_item = _KorrespondentListItem({}, is_all=True)
        self.list_widget.addItem(all_item)
        # Sortiert nach usage_count DESC, dann name ASC
        try:
            items = self.db.list_korrespondenten()
        except Exception as e:
            QMessageBox.warning(
                self, "Fehler",
                f"Korrespondenten konnten nicht geladen werden:\n{e}",
            )
            items = []
        for korr in items:
            self.list_widget.addItem(_KorrespondentListItem(korr))

    # ------------------------------------------------------------------ #
    # Slot / Handler
    # ------------------------------------------------------------------ #

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        """Klick in der Liste -> Signal emittieren."""
        if not isinstance(item, _KorrespondentListItem):
            return
        if item.is_all:
            self.korrespondent_selected.emit(None)
        else:
            name = item.data(Qt.ItemDataRole.UserRole) or ""
            self.korrespondent_selected.emit(name)

    def _on_new(self) -> None:
        """Oeffnet den Edit-Dialog fuer einen NEUEN Korrespondenten."""
        dlg = KorrespondentEditDialog(
            initial_data=None,
            title="Neuen Korrespondenten anlegen",
            parent=self,
        )
        if dlg.exec() != KorrespondentEditDialog.DialogCode.Accepted:
            return
        data = dlg.get_data()
        if not data or not data.get("name"):
            return
        try:
            self.db.add_or_update_korrespondent(
                name=data["name"],
                aliases=data.get("aliases") or None,
                kategorie=data.get("kategorie"),
                farbe=data.get("farbe"),
                notizen=data.get("notizen"),
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Fehler",
                f"Korrespondent konnte nicht angelegt werden:\n{e}",
            )
            return
        self.refresh()

    def _on_edit(self) -> None:
        """Bearbeitet den ersten ausgewaehlten Korrespondenten."""
        korr = self._current_korrespondent()
        if not korr:
            return
        dlg = KorrespondentEditDialog(
            initial_data=korr,
            title=f"Korrespondent bearbeiten: {korr.get('name', '')}",
            parent=self,
        )
        if dlg.exec() != KorrespondentEditDialog.DialogCode.Accepted:
            return
        data = dlg.get_data()
        if not data or not data.get("name"):
            return
        try:
            self.db.add_or_update_korrespondent(
                name=data["name"],
                aliases=data.get("aliases") or None,
                kategorie=data.get("kategorie"),
                farbe=data.get("farbe"),
                notizen=data.get("notizen"),
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Fehler",
                f"Aktualisierung fehlgeschlagen:\n{e}",
            )
            return
        self.refresh()

    def _on_merge(self) -> None:
        """Oeffnet den Merge-Dialog fuer 2+ ausgewaehlte Korrespondenten."""
        items = self.list_widget.selectedItems()
        names: list[str] = []
        for item in items:
            if not isinstance(item, _KorrespondentListItem):
                continue
            if item.is_all:
                continue
            data = item.data(Qt.ItemDataRole.UserRole)
            if data:
                names.append(str(data))
        if len(names) < 2:
            QMessageBox.information(
                self, "Zusammenfuehren",
                "Bitte mindestens 2 Korrespondenten auswaehlen (mit "
                "Strg+Klick oder Shift+Klick).",
            )
            return
        all_korrs = self.db.list_korrespondenten()
        all_korrs_filtered = [k for k in all_korrs if k.get("name") in names]
        dlg = KorrespondentMergeDialog(
            korrespondenten=all_korrs_filtered,
            preselected=names,
            parent=self,
        )
        if dlg.exec() != KorrespondentMergeDialog.DialogCode.Accepted:
            return
        merge = dlg.get_merge_data()
        if not merge:
            return
        primary, secondary = merge
        try:
            self.db.merge_korrespondenten(primary, secondary)
        except Exception as e:
            QMessageBox.critical(
                self, "Fehler",
                f"Zusammenfuehren fehlgeschlagen:\n{e}",
            )
            return
        self.refresh()

    def _on_collect_from_history(self) -> None:
        """Sammelt Korrespondenten aus sorting_history."""
        try:
            n = self.db.auto_collect_from_history()
        except Exception as e:
            QMessageBox.critical(
                self, "Fehler",
                f"Sammeln fehlgeschlagen:\n{e}",
            )
            return
        QMessageBox.information(
            self, "Gesammelt",
            f"{n} neue Korrespondenten aus der Sortierhistorie uebernommen.",
        )
        self.refresh()

    # ------------------------------------------------------------------ #
    # Helper
    # ------------------------------------------------------------------ #

    def _current_korrespondent(self) -> Optional[dict]:
        """Gibt den aktuell (einfach) ausgewaehlten Korrespondenten zurueck."""
        item = self.list_widget.currentItem()
        if not isinstance(item, _KorrespondentListItem) or item.is_all:
            return None
        name = item.data(Qt.ItemDataRole.UserRole) or ""
        if not name:
            return None
        return self.db.get_korrespondent(name)

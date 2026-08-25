"""
Merge-Dialog fuer Korrespondenten (Phase 20 / Issue #21).

Wird von der ``KorrespondentSidebar`` zum Zusammenfuehren mehrerer
Korrespondenten verwendet.

Ablauf:
    1. Primaerkorrespondent waehlen (QComboBox)
    2. Sekundaerkorrespondenten waehlen (QListWidget mit Mehrfachauswahl)
    3. Bestaetigen -> ``get_merge_data()`` liefert
       ``(primary_name, secondary_names)`` oder ``None`` bei Cancel.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)


class KorrespondentMergeDialog(QDialog):
    """Dialog zum Zusammenfuehren mehrerer Korrespondenten."""

    def __init__(
        self,
        korrespondenten: list[dict],
        preselected: Optional[list[str]] = None,
        parent: Optional[QWidget] = None,
    ):
        """Args:
            korrespondenten: Liste von Dicts mit ``{"name", "kategorie", ...}``
            preselected: Optionale Liste von Namen, die initial ausgewaehlt sind
        """
        super().__init__(parent)
        self._korrespondenten = list(korrespondenten)
        self._preselected = list(preselected or [])
        self.setWindowTitle("Korrespondenten zusammenfuehren")
        self.setMinimumSize(500, 400)
        self._setup_ui()
        self._populate()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Erklaerung
        intro = QLabel(
            "Waehlen Sie einen Primaerkorrespondenten und mindestens einen\n"
            "Sekundaerkorrespondenten. Die Sekundaere werden geloescht und ihre\n"
            "Namen als Aliasse in den Primaer uebernommen. Verknuepfte\n"
            "Dokumente (FTS5 + Sortierhistorie) werden auf den Primaer\n"
            "umgeschrieben."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #444; padding: 6px;")
        layout.addWidget(intro)

        # Primaerauswahl
        layout.addWidget(QLabel("Primaerkorrespondent (bleibt erhalten):"))
        self.primary_combo = QComboBox()
        self.primary_combo.setToolTip(
            "Dieser Korrespondent bleibt erhalten; alle anderen werden gemerged."
        )
        layout.addWidget(self.primary_combo)

        # Sekundaerauswahl
        layout.addWidget(QLabel(
            "Sekundaerkorrespondenten (werden geloescht, Mehrfachauswahl moeglich):"
        ))
        self.secondary_list = QListWidget()
        self.secondary_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.secondary_list.setAlternatingRowColors(True)
        layout.addWidget(self.secondary_list, 1)

        # Hinweis
        self.hint_label = QLabel("")
        self.hint_label.setStyleSheet("color: #888; font-style: italic; padding: 4px;")
        layout.addWidget(self.hint_label)
        self.secondary_list.itemSelectionChanged.connect(self._update_hint)
        self.primary_combo.currentTextChanged.connect(self._update_hint)

        # Standard-Buttons
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _populate(self) -> None:
        """Befuellt die Auswahl-Widgets."""
        for korr in self._korrespondenten:
            name = str(korr.get("name", "")).strip()
            if not name:
                continue
            kategorie = korr.get("kategorie") or ""
            label = f"{name}" + (f"  ({kategorie})" if kategorie else "")
            self.primary_combo.addItem(label, userData=name)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.secondary_list.addItem(item)
            if name in self._preselected:
                item.setSelected(True)
        self._update_hint()

    def _update_hint(self) -> None:
        primary = self.primary_combo.currentData()
        selected = self._selected_secondary_names()
        sec_count = len(selected)
        if sec_count == 0:
            self.hint_label.setText("Bitte mindestens einen Sekundaer auswaehlen.")
        elif primary and primary in selected:
            self.hint_label.setText(
                "Hinweis: Primaer ist auch als Sekundaer markiert - wird ignoriert."
            )
        else:
            self.hint_label.setText(
                f"{sec_count} Sekundaer ausgewaehlt. "
                f"Zusammenfuehren mit '{primary}' als Primaer."
            )

    def _selected_secondary_names(self) -> list[str]:
        names: list[str] = []
        for item in self.secondary_list.selectedItems():
            data = item.data(Qt.ItemDataRole.UserRole)
            if data:
                names.append(str(data))
        return names

    def _on_accept(self) -> None:
        primary = self.primary_combo.currentData()
        secondary = [
            n for n in self._selected_secondary_names() if n and n != primary
        ]
        if not primary:
            QMessageBox.warning(
                self, "Kein Primaer",
                "Bitte einen Primaerkorrespondenten auswaehlen.",
            )
            return
        if len(secondary) < 1:
            QMessageBox.warning(
                self, "Zu wenige Sekundaere",
                "Bitte mindestens einen anderen Korrespondenten als Sekundaer "
                "auswaehlen.",
            )
            return
        self.accept()

    # ------------------------------------------------------------------ #
    # Oeffentliche API
    # ------------------------------------------------------------------ #

    def get_merge_data(self) -> Optional[tuple[str, list[str]]]:
        """Gibt ``(primary_name, secondary_names)`` zurueck.

        Returns:
            Tuple ``(primary, secondary)`` bei OK, sonst ``None``.
        """
        if self.result() != QDialog.DialogCode.Accepted:
            return None
        primary = self.primary_combo.currentData()
        secondary = [
            n for n in self._selected_secondary_names() if n and n != primary
        ]
        return (str(primary), secondary)

"""
Bearbeitungsdialog fuer einen Korrespondenten (Phase 20 / Issue #21).

Wird von der ``KorrespondentSidebar`` zum Anlegen und Bearbeiten von
Eintraegen in der Verwaltungstabelle ``korrespondenten`` verwendet.

Form-Felder:
    * name (QLineEdit, Pflichtfeld)
    * aliases (QLineEdit, komma-getrennt)
    * kategorie (QComboBox mit Standard-Kategorien + Sonstiges)
    * farbe (QPushButton -> QColorDialog)
    * notizen (QPlainTextEdit, Freitext)

API:
    * ``get_data() -> dict`` liefert die Form-Werte als Python-Dict
      (aliases als Liste, name gestrippt, leere Strings als ``None``).
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.utils.database import Database


# Standard-Kategorien (gleich wie in der DB-Klasse, aber als Tuple fuer
# Reihenfolgegarantie)
DEFAULT_KATEGORIEN: list[str] = list(Database.KORRESPONDENT_KATEGORIEN)


class KorrespondentEditDialog(QDialog):
    """Dialog zum Anlegen / Bearbeiten eines Korrespondenten."""

    def __init__(
        self,
        initial_data: Optional[dict] = None,
        title: str = "Korrespondent bearbeiten",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._initial = initial_data or {}
        self.setWindowTitle(title)
        self.setMinimumWidth(450)
        self._setup_ui()
        self._populate_from_initial()

    # ------------------------------------------------------------------ #
    # UI-Aufbau
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Name (Pflichtfeld)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("z.B. 'Telekom', 'ista', 'Finanzamt Koeln'")
        form.addRow("Name*:", self.name_edit)

        # Aliasse (Komma-getrennt)
        self.aliases_edit = QLineEdit()
        self.aliases_edit.setPlaceholderText("Komma-getrennt, z.B. 'ista, IST Deutschland'")
        form.addRow("Aliasse:", self.aliases_edit)

        # Kategorie
        self.kategorie_combo = QComboBox()
        self.kategorie_combo.setEditable(False)
        for kat in DEFAULT_KATEGORIEN:
            self.kategorie_combo.addItem(kat)
        form.addRow("Kategorie:", self.kategorie_combo)

        # Farbe (QPushButton mit QColorDialog)
        farbe_widget = QWidget()
        farbe_layout = QHBoxLayout(farbe_widget)
        farbe_layout.setContentsMargins(0, 0, 0, 0)
        farbe_layout.setSpacing(6)

        self.farbe_btn = QPushButton()
        self.farbe_btn.setFixedSize(40, 24)
        self.farbe_btn.setToolTip("Farbe fuer die Sidebar-Markierung auswaehlen")
        self.farbe_btn.clicked.connect(self._pick_farbe)

        self.farbe_clear_btn = QPushButton("Keine")
        self.farbe_clear_btn.setFixedHeight(24)
        self.farbe_clear_btn.clicked.connect(self._clear_farbe)

        self.farbe_label = QLabel("(keine)")
        self.farbe_label.setStyleSheet("color: #888;")

        farbe_layout.addWidget(self.farbe_btn)
        farbe_layout.addWidget(self.farbe_label)
        farbe_layout.addWidget(self.farbe_clear_btn)
        farbe_layout.addStretch()
        form.addRow("Farbe:", farbe_widget)

        # Notizen
        self.notizen_edit = QPlainTextEdit()
        self.notizen_edit.setPlaceholderText("Optionale Notizen zu diesem Korrespondenten")
        self.notizen_edit.setFixedHeight(80)
        form.addRow("Notizen:", self.notizen_edit)

        layout.addLayout(form)

        # OK / Cancel (Standard-Buttons)
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _populate_from_initial(self) -> None:
        """Befuellt die Form mit ``initial_data`` falls vorhanden."""
        if not self._initial:
            self._update_farbe_preview(None)
            return

        self.name_edit.setText(str(self._initial.get("name", "") or ""))

        aliases = self._initial.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [a.strip() for a in aliases.split(",") if a.strip()]
        self.aliases_edit.setText(", ".join(aliases))

        kategorie = self._initial.get("kategorie")
        if kategorie:
            idx = self.kategorie_combo.findText(kategorie)
            if idx >= 0:
                self.kategorie_combo.setCurrentIndex(idx)
            else:
                # Unbekannte Kategorie ergaenzen
                self.kategorie_combo.addItem(kategorie)
                self.kategorie_combo.setCurrentText(kategorie)

        self._update_farbe_preview(self._initial.get("farbe"))

        notizen = self._initial.get("notizen")
        if notizen:
            self.notizen_edit.setPlainText(str(notizen))

    # ------------------------------------------------------------------ #
    # Slot / Helpers
    # ------------------------------------------------------------------ #

    def _pick_farbe(self) -> None:
        """Oeffnet den QColorDialog und aktualisiert die Vorschau."""
        start = QColor(self._current_farbe()) if self._current_farbe() else QColor("#3F51B5")
        chosen = QColorDialog.getColor(start, self, "Farbe auswaehlen")
        if chosen.isValid():
            self._update_farbe_preview(chosen.name())

    def _clear_farbe(self) -> None:
        """Setzt die Farbe zurueck auf '(keine)'."""
        self._update_farbe_preview(None)

    def _current_farbe(self) -> Optional[str]:
        """Liefert die aktuelle Farbe (Hex) oder None."""
        text = self.farbe_label.text().strip()
        if not text or text == "(keine)" or not text.startswith("#"):
            return None
        return text

    def _update_farbe_preview(self, hex_color: Optional[str]) -> None:
        """Aktualisiert Button- und Label-Vorschau."""
        if hex_color and hex_color.startswith("#"):
            self.farbe_btn.setStyleSheet(
                f"background-color: {hex_color}; border: 1px solid #888;"
            )
            self.farbe_label.setText(hex_color)
            self.farbe_label.setStyleSheet("color: #333;")
        else:
            self.farbe_btn.setStyleSheet(
                "background-color: #f0f0f0; border: 1px solid #ccc;"
            )
            self.farbe_label.setText("(keine)")
            self.farbe_label.setStyleSheet("color: #888;")

    def _on_accept(self) -> None:
        """Validiert die Pflichtfelder und schliesst den Dialog mit OK."""
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(
                self, "Name fehlt",
                "Bitte einen Anzeigenamen eingeben.",
            )
            self.name_edit.setFocus()
            return
        self.accept()

    # ------------------------------------------------------------------ #
    # Oeffentliche API
    # ------------------------------------------------------------------ #

    def get_data(self) -> Optional[dict]:
        """Gibt die Form-Werte als Dict zurueck (oder None bei Cancel).

        ``aliases`` wird als Liste zurueckgegeben, ``name`` ist gestrippt,
        leere Strings werden zu ``None`` normalisiert.
        """
        if self.result() != QDialog.DialogCode.Accepted:
            return None

        name = self.name_edit.text().strip()
        aliases_raw = self.aliases_edit.text().strip()
        aliases: list[str] = []
        if aliases_raw:
            aliases = [a.strip() for a in aliases_raw.split(",") if a.strip()]

        kategorie = self.kategorie_combo.currentText().strip() or None
        farbe = self._current_farbe()
        notizen = self.notizen_edit.toPlainText().strip() or None

        return {
            "name": name,
            "aliases": aliases,
            "kategorie": kategorie,
            "farbe": farbe,
            "notizen": notizen,
        }

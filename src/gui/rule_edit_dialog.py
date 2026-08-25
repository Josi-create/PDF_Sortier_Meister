"""Visueller Editor fuer eine einzelne Automatisierungs-Regel (Phase 21).

Bietet ein einfaches Formular zum Erstellen/Bearbeiten einer Regel:
* Name (Pflicht)
* Prioritaet (Spinbox, hoeher = wichtiger)
* Enabled (Checkbox)
* Bedingungen (Liste mit +/- Buttons, jede Bedingung hat Typ+Operator+Wert)
* Aktionen (Liste mit +/- Buttons, jede Aktion hat Typ+Wert)

Kein anthropic/openai-Import noetig. Nutzt nur stdlib + PyQt6.
"""
from __future__ import annotations

import json
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


# Vereinfachte Sets fuer den visuellen Editor.
# Konsistent mit Database.AVAILABLE_CONDITION_TYPES / AVAILABLE_ACTION_TYPES.
CONDITION_TYPES = [
    ("korrespondent", "Korrespondent (exakt)", "equals|contains"),
    ("kategorie", "Kategorie", "equals|in"),
    ("betrag", "Betrag (EUR)", "gt|gte|lt|lte|between"),
    ("datum", "Datum (YYYY-MM-DD)", "after|before|between"),
    ("keywords", "Schluesselwoerter", "any|all"),
]

ACTION_TYPES = [
    ("target_folder", "Zielordner", "Vorlage mit {platzhaltern}"),
    ("filename_pattern", "Dateinamen-Muster", "Vorlage mit {platzhaltern}"),
    ("metadata_field", "Metadaten-Feld setzen", "Feldname + Wert"),
    ("tag", "Tag hinzufuegen", "Schlagwort"),
]


class RuleEditDialog(QDialog):
    """Dialog zum Erstellen/Bearbeiten einer Automatisierungs-Regel."""

    def __init__(self, initial_data: Optional[dict] = None,
                 title: str = "Regel bearbeiten",
                 parent=None):
        super().__init__(parent)
        self._initial = initial_data or {}
        self.setWindowTitle(title)
        self.setMinimumWidth(550)

        layout = QVBoxLayout(self)

        # 1) Basis-Felder
        form = QFormLayout()
        self.name_edit = QLineEdit(self._initial.get("name", ""))
        self.name_edit.setPlaceholderText("z.B. 'Finanzamt-Steuerbescheide'")
        form.addRow("Name*:", self.name_edit)

        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(-1000, 1000)
        self.priority_spin.setValue(int(self._initial.get("priority", 0)))
        form.addRow("Prioritaet:", self.priority_spin)

        self.enabled_check = QCheckBox()
        self.enabled_check.setChecked(bool(self._initial.get("enabled", True)))
        form.addRow("Aktiviert:", self.enabled_check)

        layout.addLayout(form)

        # 2) Bedingungen
        cond_group = QGroupBox("Bedingungen (UND-verknuepft)")
        cond_layout = QVBoxLayout(cond_group)
        self.cond_list = QListWidget()
        self.cond_list.setMinimumHeight(120)
        cond_layout.addWidget(self.cond_list)

        cond_btn_row = QHBoxLayout()
        self.cond_add_btn = QPushButton("+ Bedingung")
        self.cond_add_btn.clicked.connect(self._add_condition)
        self.cond_remove_btn = QPushButton("- Entfernen")
        self.cond_remove_btn.clicked.connect(self._remove_condition)
        cond_btn_row.addWidget(self.cond_add_btn)
        cond_btn_row.addWidget(self.cond_remove_btn)
        cond_btn_row.addStretch()
        cond_layout.addLayout(cond_btn_row)
        layout.addWidget(cond_group)

        # 3) Aktionen
        act_group = QGroupBox("Aktionen")
        act_layout = QVBoxLayout(act_group)
        self.act_list = QListWidget()
        self.act_list.setMinimumHeight(120)
        act_layout.addWidget(self.act_list)

        act_btn_row = QHBoxLayout()
        self.act_add_btn = QPushButton("+ Aktion")
        self.act_add_btn.clicked.connect(self._add_action)
        self.act_remove_btn = QPushButton("- Entfernen")
        self.act_remove_btn.clicked.connect(self._remove_action)
        act_btn_row.addWidget(self.act_add_btn)
        act_btn_row.addWidget(self.act_remove_btn)
        act_btn_row.addStretch()
        act_layout.addLayout(act_btn_row)
        layout.addWidget(act_group)

        # 4) OK/Cancel
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # Initial data befuellen
        for cond in self._initial.get("conditions", []):
            self._append_condition(cond)
        for act in self._initial.get("actions", []):
            self._append_action(act)

    # ------------------------------------------------------------------ #
    # Conditions helpers
    # ------------------------------------------------------------------ #

    def _add_condition(self):
        """Oeffnet einen kleinen Dialog, um eine neue Bedingung zu definieren."""
        ctype, ok = QInputDialog.getItem(
            self, "Bedingung hinzufuegen", "Typ:",
            [t[1] for t in CONDITION_TYPES], 0, False
        )
        if not ok:
            return
        # Finde Typ-Key
        type_key = next(k for k, label, _ in CONDITION_TYPES if label == ctype)
        operator_str = next(op for k, _, op in CONDITION_TYPES if k == type_key)
        operators = operator_str.split("|")
        cop, ok = QInputDialog.getItem(
            self, "Operator", "Operator:", operators, 0, False
        )
        if not ok:
            return
        value, ok = QInputDialog.getText(
            self, "Wert", "Wert (bei 'between': zwei Werte mit Komma):"
        )
        if not ok:
            return
        cond = {"type": type_key, "operator": cop, "value": value}
        self._append_condition(cond)

    def _append_condition(self, cond: dict):
        """Haengt eine fertige Bedingung an die Liste an."""
        text = f"[{cond.get('type','?')}] {cond.get('operator','?')} '{cond.get('value','')}'"
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, cond)
        self.cond_list.addItem(item)

    def _remove_condition(self):
        row = self.cond_list.currentRow()
        if row >= 0:
            self.cond_list.takeItem(row)

    # ------------------------------------------------------------------ #
    # Actions helpers
    # ------------------------------------------------------------------ #

    def _add_action(self):
        atype, ok = QInputDialog.getItem(
            self, "Aktion hinzufuegen", "Typ:",
            [t[1] for t in ACTION_TYPES], 0, False
        )
        if not ok:
            return
        type_key = next(k for k, label, _ in ACTION_TYPES if label == atype)
        if type_key == "metadata_field":
            # Zwei Werte: Feldname + Wert
            field, ok = QInputDialog.getText(self, "Metadaten-Feld",
                                             "Feldname (z.B. 'steuerjahr'):")
            if not ok:
                return
            value, ok = QInputDialog.getText(self, "Wert", "Wert (z.B. 'auto'):")
            if not ok:
                return
            action = {"type": type_key, "field": field, "value": value}
        else:
            value, ok = QInputDialog.getText(
                self, "Wert", "Wert (Vorlage/Tag):"
            )
            if not ok:
                return
            action = {"type": type_key,
                      "template" if type_key in ("target_folder", "filename_pattern") else "value": value}
        self._append_action(action)

    def _append_action(self, action: dict):
        if action.get("type") == "metadata_field":
            text = f"[{action.get('type','?')}] {action.get('field','?')} = '{action.get('value','')}'"
        elif "template" in action:
            text = f"[{action.get('type','?')}] template='{action.get('template','')}'"
        else:
            text = f"[{action.get('type','?')}] '{action.get('value','')}'"
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, action)
        self.act_list.addItem(item)

    def _remove_action(self):
        row = self.act_list.currentRow()
        if row >= 0:
            self.act_list.takeItem(row)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get_data(self) -> Optional[dict]:
        """Liefert die Form-Werte als Dict, oder None bei Cancel."""
        if self.result() != QDialog.DialogCode.Accepted:
            return None
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Validierung", "Name ist Pflicht.")
            return None
        conditions = []
        for i in range(self.cond_list.count()):
            item = self.cond_list.item(i)
            cond = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(cond, dict):
                conditions.append(cond)
        actions = []
        for i in range(self.act_list.count()):
            item = self.act_list.item(i)
            act = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(act, dict):
                actions.append(act)
        return {
            "name": name,
            "priority": self.priority_spin.value(),
            "enabled": self.enabled_check.isChecked(),
            "conditions": conditions,
            "actions": actions,
        }

"""
Rueckfrage der Stapel-Ablage (Issue #218): Liste alt -> neu vor dem Verschieben
bzw. Umbenennen mehrerer Dateien.

Eigenes, schlankes Modul (nur PyQt): ``tests/conftest.py`` ersetzt :func:`frage`
in jedem Test, ohne dafuer Detail-Panel und Vorschau laden zu muessen.

GPL-3.0-or-later - Copyright (c) 2026
"""

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

# Antworten der Rueckfrage
UMBENENNEN = "umbenennen"  # mit neuen Namen (und Metadaten)
NUR_VERSCHIEBEN = "nur_verschieben"  # wie bisher: Namen bleiben, keine Metadaten

NAME_BLEIBT = "(Name bleibt)"


class StapelDialog(QDialog):
    """Rueckfrage mit der Liste alt -> neu; ``wahl`` ist danach UMBENENNEN, NUR_VERSCHIEBEN oder None."""

    def __init__(self, titel: str, text: str, zeilen: list[tuple[str, Optional[str]]],
                 ja_text: str, nur_text: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(titel)
        self.wahl: Optional[str] = None

        layout = QVBoxLayout(self)
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)

        self.liste = QTreeWidget()
        self.liste.setHeaderLabels(["Bisher", "Neu"])
        self.liste.setRootIsDecorated(False)
        self.liste.setUniformRowHeights(True)
        self.liste.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.liste.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        grau = self.palette().color(QPalette.ColorRole.PlaceholderText)
        for alt, neu in zeilen:
            item = QTreeWidgetItem([alt, neu or NAME_BLEIBT])
            item.setToolTip(0, alt)
            item.setToolTip(1, neu or alt)
            if not neu:
                item.setForeground(1, grau)
            self.liste.addTopLevelItem(item)
        kopf = self.liste.header()
        kopf.setStretchLastSection(True)
        kopf.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.liste.resizeColumnToContents(0)
        self.liste.setColumnWidth(0, min(self.liste.columnWidth(0) + 16, 320))
        layout.addWidget(self.liste)

        knoepfe = QDialogButtonBox()
        self.ja_knopf = knoepfe.addButton(ja_text, QDialogButtonBox.ButtonRole.AcceptRole)
        self.ja_knopf.setDefault(True)
        self.ja_knopf.clicked.connect(lambda: self._waehle(UMBENENNEN))
        self.nur_knopf = None
        if nur_text:
            self.nur_knopf = knoepfe.addButton(nur_text, QDialogButtonBox.ButtonRole.ActionRole)
            self.nur_knopf.clicked.connect(lambda: self._waehle(NUR_VERSCHIEBEN))
        knoepfe.addButton("Abbrechen", QDialogButtonBox.ButtonRole.RejectRole)
        knoepfe.rejected.connect(self.reject)
        layout.addWidget(knoepfe)

        zeilen_hoehe = max(self.liste.sizeHintForRow(0), 20) if zeilen else 20
        self.resize(760, min(560, 170 + zeilen_hoehe * max(len(zeilen), 2)))

    def _waehle(self, wahl: str):
        self.wahl = wahl
        self.accept()


def frage(parent, titel: str, text: str, zeilen: list[tuple[str, Optional[str]]],
          ja_text: str, nur_text: Optional[str]) -> Optional[str]:
    """Zeigt den :class:`StapelDialog` modal und gibt die Wahl zurueck (None = Abbrechen)."""
    dialog = StapelDialog(titel, text, zeilen, ja_text, nur_text, parent)
    dialog.exec()
    wahl = dialog.wahl
    dialog.deleteLater()
    return wahl

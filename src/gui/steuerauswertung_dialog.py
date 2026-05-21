"""
Steuerauswertungs-Dialog fuer PDF Sortier Meister (Phase 18).

Zeigt eine Tabelle mit Jahressummen (Brutto, Netto, absetzbar)
aufgeschluesselt nach Kategorie. Ermoeglicht CSV-Export.
"""

import csv
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QLabel,
    QFileDialog,
    QMessageBox,
    QHeaderView,
)


class SteuerauswertungDialog(QDialog):
    """Dialog zur Steuerauswertung: Jahressummen nach Kategorie."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Steuerauswertung")
        self.setMinimumSize(750, 450)
        self._data: list[dict] = []
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        header = QLabel("Steuerauswertung nach Jahr und Kategorie")
        header.setStyleSheet("font-size: 14px; font-weight: bold; padding: 4px;")
        layout.addWidget(header)

        hint = QLabel(
            "Grundlage: alle sortierten Dokumente mit gespeichertem Steuerjahr. "
            "Betraege in EUR."
        )
        hint.setStyleSheet("font-size: 10px; color: #666; padding: 2px;")
        layout.addWidget(hint)

        columns = [
            "Steuerjahr",
            "Kategorie",
            "Anzahl",
            "Summe Brutto",
            "Summe Netto",
            "Summe absetzbar",
        ]
        self.table = QTableWidget()
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.refresh_btn = QPushButton("Aktualisieren")
        self.refresh_btn.clicked.connect(self._load_data)
        btn_row.addWidget(self.refresh_btn)

        self.export_btn = QPushButton("Als CSV exportieren")
        self.export_btn.setStyleSheet(
            "QPushButton { background-color: #1565c0; color: white; "
            "padding: 4px 12px; border: none; border-radius: 3px; }"
            "QPushButton:hover { background-color: #0d47a1; }"
            "QPushButton:disabled { background-color: #bdbdbd; }"
        )
        self.export_btn.clicked.connect(self._export_csv)
        btn_row.addWidget(self.export_btn)

        close_btn = QPushButton("Schliessen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _load_data(self):
        """Laedt die Auswertungsdaten aus der Datenbank."""
        try:
            from src.utils.database import get_database
            self._data = get_database().get_steuerauswertung()
        except Exception as e:
            QMessageBox.warning(self, "Fehler", f"Daten konnten nicht geladen werden:\n{e}")
            self._data = []

        self._fill_table()

    def _fill_table(self):
        """Befuellt die Tabelle mit den geladenen Daten."""
        self.table.setRowCount(len(self._data))
        for row, rec in enumerate(self._data):
            def item(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
                it = QTableWidgetItem(text)
                it.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                return it

            right = Qt.AlignmentFlag.AlignRight
            self.table.setItem(row, 0, item(rec.get("steuerjahr", "")))
            self.table.setItem(row, 1, item(rec.get("kategorie", "")))
            self.table.setItem(row, 2, item(str(rec.get("anzahl", 0)), right))
            self.table.setItem(
                row, 3, item(f"{rec.get('summe_brutto', 0.0):.2f}", right)
            )
            self.table.setItem(
                row, 4, item(f"{rec.get('summe_netto', 0.0):.2f}", right)
            )
            self.table.setItem(
                row, 5, item(f"{rec.get('summe_absetzbar', 0.0):.2f}", right)
            )

        self.export_btn.setEnabled(bool(self._data))

    def _export_csv(self):
        """Exportiert die Tabelle als CSV-Datei."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "CSV exportieren",
            str(Path.home() / "Steuerauswertung.csv"),
            "CSV-Dateien (*.csv)",
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow([
                    "Steuerjahr", "Kategorie", "Anzahl",
                    "Summe Brutto", "Summe Netto", "Summe absetzbar",
                ])
                for rec in self._data:
                    writer.writerow([
                        rec.get("steuerjahr", ""),
                        rec.get("kategorie", ""),
                        rec.get("anzahl", 0),
                        f"{rec.get('summe_brutto', 0.0):.2f}",
                        f"{rec.get('summe_netto', 0.0):.2f}",
                        f"{rec.get('summe_absetzbar', 0.0):.2f}",
                    ])
            QMessageBox.information(
                self, "Export erfolgreich", f"Datei gespeichert:\n{path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Exportfehler", f"Fehler beim Speichern:\n{e}")

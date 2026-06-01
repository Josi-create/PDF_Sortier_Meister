"""
Dialog zum Trennen einer PDF-Datei.

Erlaubt dem Benutzer zu wählen, ob alle Seiten einzeln gespeichert werden
oder nur ein bestimmter Seitenbereich extrahiert werden soll.
"""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QLineEdit,
    QPushButton,
    QButtonGroup,
    QGroupBox,
)


class SplitPDFDialog(QDialog):
    """Dialog zur Auswahl der Split-Optionen für eine PDF."""

    def __init__(self, pdf_path: Path, page_count: int, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.page_count = page_count
        self._pages: list[int] | None = None  # None = alle Seiten

        self.setWindowTitle("PDF trennen")
        self.setMinimumWidth(380)
        self.setModal(True)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Info-Zeile
        info = QLabel(f"<b>{self.pdf_path.name}</b><br>{self.page_count} Seiten")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)

        # Optionsgruppe
        group = QGroupBox("Trennmodus")
        group_layout = QVBoxLayout(group)

        self._btn_group = QButtonGroup(self)

        # Option 1: Alle Seiten einzeln
        self._radio_all = QRadioButton(f"Alle {self.page_count} Seiten einzeln speichern")
        self._radio_all.setChecked(True)
        self._btn_group.addButton(self._radio_all, 0)
        group_layout.addWidget(self._radio_all)

        # Option 2: Seitenbereich
        range_layout = QHBoxLayout()
        self._radio_range = QRadioButton("Bestimmte Seiten extrahieren:")
        self._btn_group.addButton(self._radio_range, 1)
        range_layout.addWidget(self._radio_range)

        self._range_input = QLineEdit()
        self._range_input.setPlaceholderText(f"z.B. 1,3,5-7  (max. {self.page_count})")
        self._range_input.setEnabled(False)
        range_layout.addWidget(self._range_input)
        group_layout.addLayout(range_layout)

        hint = QLabel("Seiten kommagetrennt oder als Bereich (1-3) angeben.")
        hint.setStyleSheet("color: #666; font-size: 11px;")
        group_layout.addWidget(hint)

        layout.addWidget(group)

        # Radio-Buttons verdrahten
        self._radio_all.toggled.connect(lambda checked: self._range_input.setEnabled(not checked))

        # Zielordner-Info
        target_label = QLabel(f"Zielordner: <i>{self.pdf_path.parent}</i>")
        target_label.setWordWrap(True)
        target_label.setStyleSheet("color: #555; font-size: 11px;")
        layout.addWidget(target_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        ok_btn = QPushButton("Trennen")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_accept)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

    def _on_accept(self):
        """Validiert die Eingabe und schließt den Dialog bei Erfolg."""
        if self._radio_all.isChecked():
            self._pages = None  # alle Seiten
            self.accept()
            return

        # Seitenbereich parsen
        text = self._range_input.text().strip()
        if not text:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Eingabe fehlt", "Bitte Seitenzahlen eingeben.")
            return

        try:
            pages = self._parse_pages(text)
        except ValueError as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Ungültige Eingabe", str(e))
            return

        self._pages = pages
        self.accept()

    def _parse_pages(self, text: str) -> list[int]:
        """Parst eine Seiten-Spezifikation wie '1,3,5-7' in eine Seitenliste."""
        pages = []
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                bounds = part.split("-", 1)
                start = int(bounds[0].strip())
                end = int(bounds[1].strip())
                if start < 1 or end > self.page_count or start > end:
                    raise ValueError(
                        f"Ungültiger Bereich '{part}'. "
                        f"Seiten müssen zwischen 1 und {self.page_count} liegen."
                    )
                pages.extend(range(start, end + 1))
            else:
                page = int(part)
                if page < 1 or page > self.page_count:
                    raise ValueError(
                        f"Seite {page} liegt außerhalb des gültigen Bereichs "
                        f"(1–{self.page_count})."
                    )
                pages.append(page)

        if not pages:
            raise ValueError("Keine gültigen Seitenzahlen angegeben.")

        return sorted(set(pages))

    def get_pages(self) -> list[int] | None:
        """Gibt die ausgewählten Seiten zurück, oder None für alle Seiten."""
        return self._pages

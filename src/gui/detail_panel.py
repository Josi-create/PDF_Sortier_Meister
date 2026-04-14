"""
Detail-Panel für das 3-Spalten-Layout.

Zeigt Umbenennungsvorschläge, Metadaten und Vorschau für die ausgewählte PDF.
Der Benutzer klickt links ein Thumbnail an, sieht hier die Details,
und klickt rechts auf einen Zielordner zum Verschieben+Umbenennen.
"""

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QGroupBox,
    QPlainTextEdit,
    QScrollArea,
    QApplication,
)

from src.gui.rename_dialog import RenameSuggestion


class DetailPanel(QWidget):
    """Mittleres Panel: Zeigt Rename-Vorschläge + Metadaten für ausgewählte PDF."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_pdf: Optional[Path] = None
        self._suggestions: list[RenameSuggestion] = []
        self._metadata: dict = {}
        self._has_learned_overrides: bool = False

        self._setup_ui()

    def _setup_ui(self):
        """Erstellt die UI-Komponenten."""
        # Scroll-Bereich für den gesamten Inhalt
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        # Platzhalter wenn nichts ausgewählt
        self.placeholder = QLabel(
            "PDF auswählen\n\n"
            "Klicken Sie links auf ein PDF-Thumbnail,\n"
            "um hier die Details zu sehen.\n\n"
            "Dann klicken Sie rechts auf einen\n"
            "Zielordner zum Verschieben."
        )
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet("color: #888; padding: 30px; font-size: 12px;")
        layout.addWidget(self.placeholder)

        # === Detail-Bereich (zunächst versteckt) ===
        self.detail_container = QWidget()
        detail_layout = QVBoxLayout(self.detail_container)
        detail_layout.setSpacing(6)
        detail_layout.setContentsMargins(0, 0, 0, 0)

        # Header: Aktueller Dateiname
        self.header_label = QLabel()
        self.header_label.setStyleSheet(
            "font-size: 11px; color: #666; padding: 4px; "
            "background-color: #f5f5f5; border-radius: 3px;"
        )
        self.header_label.setWordWrap(True)
        detail_layout.addWidget(self.header_label)

        # Vorschläge
        suggestions_group = QGroupBox("Vorschläge (zum Auswählen klicken)")
        suggestions_layout = QVBoxLayout(suggestions_group)
        suggestions_layout.setSpacing(2)

        self.suggestions_list = QListWidget()
        self.suggestions_list.setMaximumHeight(120)
        self.suggestions_list.itemClicked.connect(self._on_suggestion_clicked)
        suggestions_layout.addWidget(self.suggestions_list)

        detail_layout.addWidget(suggestions_group)

        # Neuer Name
        name_group = QGroupBox("Neuer Dateiname")
        name_layout = QVBoxLayout(name_group)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Neuen Dateinamen eingeben...")
        self.name_input.textChanged.connect(self._update_preview)
        font = QFont()
        font.setPointSize(11)
        self.name_input.setFont(font)
        name_layout.addWidget(self.name_input)

        # Vorschau
        self.preview_label = QLabel()
        self.preview_label.setStyleSheet(
            "font-family: monospace; padding: 6px; background-color: #e8f5e9; "
            "border: 1px solid #a5d6a7; border-radius: 3px; font-size: 11px;"
        )
        self.preview_label.setWordWrap(True)
        name_layout.addWidget(self.preview_label)

        self.warning_label = QLabel()
        self.warning_label.setStyleSheet("color: #d32f2f; font-size: 10px;")
        self.warning_label.hide()
        name_layout.addWidget(self.warning_label)

        detail_layout.addWidget(name_group)

        # Metadaten
        self.metadata_group = QGroupBox("Metadaten (werden in PDF gespeichert)")
        metadata_layout = QVBoxLayout(self.metadata_group)
        metadata_layout.setSpacing(3)

        self._metadata_inputs = {}
        metadata_fields = [
            ("subject", "Kategorie"),
            ("korrespondent", "Korrespondent"),
            ("betrag", "Betrag"),
            ("waehrung", "Währung"),
            ("mwst_satz", "MwSt-Satz"),
            ("steuerjahr", "Steuerjahr"),
            ("description", "Zusammenfassung"),
        ]

        for field_key, field_label in metadata_fields:
            row = QHBoxLayout()
            label = QLabel(f"{field_label}:")
            label.setFixedWidth(100)
            label.setStyleSheet("color: #555; font-size: 10px;")
            if field_key == "description":
                label.setAlignment(Qt.AlignmentFlag.AlignTop)
            row.addWidget(label)

            if field_key == "description":
                input_field = QPlainTextEdit()
                input_field.setPlaceholderText(f"{field_label}...")
                input_field.setStyleSheet("font-size: 10px; padding: 2px;")
                input_field.setFixedHeight(45)
            else:
                input_field = QLineEdit()
                input_field.setPlaceholderText(f"{field_label}...")
                input_field.setStyleSheet("font-size: 10px; padding: 2px;")
            row.addWidget(input_field)

            self._metadata_inputs[field_key] = input_field
            metadata_layout.addLayout(row)

        # KI-Button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.llm_btn = QPushButton("KI-Metadaten generieren")
        self.llm_btn.setStyleSheet(
            "QPushButton { background-color: #7b1fa2; color: white; "
            "padding: 3px 10px; border: none; border-radius: 3px; font-size: 10px; }"
            "QPushButton:hover { background-color: #6a1b9a; }"
            "QPushButton:disabled { background-color: #bdbdbd; }"
        )
        self.llm_btn.clicked.connect(self._request_llm_metadata)
        btn_row.addWidget(self.llm_btn)
        metadata_layout.addLayout(btn_row)

        detail_layout.addWidget(self.metadata_group)

        # Hinweis
        self.hint_label = QLabel("Jetzt rechts auf einen Zielordner klicken")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setStyleSheet(
            "color: #1976d2; font-weight: bold; padding: 8px; "
            "background-color: #e3f2fd; border-radius: 4px; font-size: 11px;"
        )
        detail_layout.addWidget(self.hint_label)

        detail_layout.addStretch()

        self.detail_container.hide()
        layout.addWidget(self.detail_container)

        scroll.setWidget(container)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(scroll)

    # === Öffentliche Methoden ===

    def set_pdf(
        self,
        pdf_path: Path,
        suggestions: list[RenameSuggestion],
        extracted_text: str = "",
        keywords: list[str] = None,
        detected_date: str = None,
    ):
        """Befüllt das Panel mit Daten für eine ausgewählte PDF."""
        self._current_pdf = pdf_path
        self._suggestions = suggestions or []
        self._has_learned_overrides = False

        # Header
        self.header_label.setText(f"Original: {pdf_path.name}")

        # Vorschläge befüllen
        self._populate_suggestions()

        # Metadaten vorbefüllen
        self._metadata = {}

        # 1. Basis aus Analyse
        if keywords:
            self._metadata["subject"] = keywords[0].capitalize()
        if detected_date:
            try:
                year = detected_date[:4]
                if year.isdigit():
                    self._metadata["steuerjahr"] = year
            except Exception:
                pass

        # 2. LLM-Metadaten
        for s in self._suggestions:
            if s.metadata:
                self._metadata.update(s.metadata)
                break

        # 3. Gelernte Korrespondent-Zuordnungen
        korrespondent = self._metadata.get("korrespondent")
        if korrespondent:
            try:
                from src.utils.database import get_database
                learned = get_database().get_korrespondent_metadata(korrespondent)
                if learned:
                    self._metadata.update(learned)
                    self._has_learned_overrides = True
            except Exception:
                pass

        # Metadaten-Felder befüllen
        self._apply_metadata_to_fields()

        # GroupBox-Titel
        if self._has_learned_overrides:
            self.metadata_group.setTitle("Metadaten (gelernt + werden in PDF gespeichert)")
        else:
            self.metadata_group.setTitle("Metadaten (werden in PDF gespeichert)")

        # Ersten Vorschlag als Name setzen
        if self._suggestions:
            name = self._suggestions[0].name.replace('.pdf', '')
            self.name_input.setText(name)

        # UI umschalten
        self.placeholder.hide()
        self.detail_container.show()

    def clear(self):
        """Leert das Panel (kein PDF ausgewählt)."""
        self._current_pdf = None
        self._suggestions = []
        self._metadata = {}

        self.name_input.clear()
        self.suggestions_list.clear()
        self.preview_label.clear()
        self.warning_label.hide()
        for widget in self._metadata_inputs.values():
            if isinstance(widget, QPlainTextEdit):
                widget.clear()
            else:
                widget.clear()

        self.detail_container.hide()
        self.placeholder.show()

    def get_new_name(self) -> Optional[str]:
        """Gibt den aktuellen Dateinamen zurück (mit .pdf)."""
        text = self.name_input.text().strip()
        if not text:
            return None
        if not text.lower().endswith('.pdf'):
            text += '.pdf'
        return text

    def get_metadata(self) -> dict:
        """Gibt die aktuellen Metadaten zurück."""
        metadata = {}
        for field_key, input_field in self._metadata_inputs.items():
            if isinstance(input_field, QPlainTextEdit):
                value = input_field.toPlainText().strip()
            else:
                value = input_field.text().strip()
            if value:
                metadata[field_key] = value
        return metadata

    def get_current_pdf(self) -> Optional[Path]:
        """Gibt den Pfad der aktuell angezeigten PDF zurück."""
        return self._current_pdf

    # === Interne Methoden ===

    def _populate_suggestions(self):
        """Füllt die Vorschlagsliste."""
        self.suggestions_list.clear()

        if not self._suggestions:
            item = QListWidgetItem("Keine Vorschläge verfügbar")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.suggestions_list.addItem(item)
            return

        for suggestion in self._suggestions:
            confidence_pct = int(suggestion.confidence * 100)
            display_text = f"{suggestion.name}"
            if suggestion.reason:
                display_text += f"  [{suggestion.reason}]"

            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, suggestion.name)
            item.setToolTip(f"Konfidenz: {confidence_pct}%\n{suggestion.reason}")

            if confidence_pct >= 70:
                item.setBackground(Qt.GlobalColor.green)
                item.setForeground(Qt.GlobalColor.darkGreen)
            elif confidence_pct >= 40:
                item.setBackground(Qt.GlobalColor.yellow)

            self.suggestions_list.addItem(item)

    def _on_suggestion_clicked(self, item: QListWidgetItem):
        """Übernimmt Vorschlag in Eingabefeld + Metadaten."""
        name = item.data(Qt.ItemDataRole.UserRole)
        if name:
            self.name_input.setText(name.replace('.pdf', ''))

            # Metadaten des Vorschlags übernehmen
            idx = self.suggestions_list.row(item)
            if idx < len(self._suggestions) and self._suggestions[idx].metadata:
                for key, value in self._suggestions[idx].metadata.items():
                    widget = self._metadata_inputs.get(key)
                    if widget:
                        if isinstance(widget, QPlainTextEdit):
                            widget.setPlainText(str(value))
                        else:
                            widget.setText(str(value))

    def _apply_metadata_to_fields(self):
        """Setzt die Metadaten-Werte in die Eingabefelder."""
        for key, widget in self._metadata_inputs.items():
            value = self._metadata.get(key, "")
            if isinstance(widget, QPlainTextEdit):
                widget.setPlainText(str(value) if value else "")
            else:
                widget.setText(str(value) if value else "")

    def _update_preview(self, text: str):
        """Aktualisiert die Dateinamen-Vorschau."""
        if not text.strip():
            self.preview_label.setText("(Name eingeben)")
            self.preview_label.setStyleSheet(
                "font-family: monospace; padding: 6px; background-color: #fff3e0; "
                "border: 1px solid #ffcc80; border-radius: 3px; font-size: 11px;"
            )
            return

        preview_name = text.strip()
        if not preview_name.lower().endswith('.pdf'):
            preview_name += '.pdf'

        invalid_chars = '<>:"/\\|?*'
        found_invalid = [c for c in preview_name if c in invalid_chars]

        if found_invalid:
            self.warning_label.setText(f"Ungültige Zeichen: {' '.join(found_invalid)}")
            self.warning_label.show()
            self.preview_label.setStyleSheet(
                "font-family: monospace; padding: 6px; background-color: #ffebee; "
                "border: 1px solid #ef9a9a; border-radius: 3px; font-size: 11px;"
            )
        else:
            self.warning_label.hide()
            self.preview_label.setStyleSheet(
                "font-family: monospace; padding: 6px; background-color: #e8f5e9; "
                "border: 1px solid #a5d6a7; border-radius: 3px; font-size: 11px;"
            )

        self.preview_label.setText(preview_name)

    def _request_llm_metadata(self):
        """Ruft das LLM erneut auf um Metadaten zu extrahieren."""
        if not self._current_pdf:
            return

        try:
            from src.ml.hybrid_classifier import get_hybrid_classifier

            classifier = get_hybrid_classifier()
            if not classifier.is_llm_available():
                return

            self.llm_btn.setEnabled(False)
            self.llm_btn.setText("KI arbeitet...")
            QApplication.processEvents()

            detected_date = self._metadata.get("buchungsdatum")

            from datetime import datetime
            file_date = None
            try:
                file_mtime = self._current_pdf.stat().st_mtime
                file_date = datetime.fromtimestamp(file_mtime).strftime("%Y-%m-%d")
            except Exception:
                pass

            # Aktuellen extrahierten Text aus dem Cache holen
            from src.core.pdf_cache import get_pdf_cache
            cached = get_pdf_cache().get(self._current_pdf)
            extracted_text = cached.extracted_text if cached else ""
            keywords = cached.keywords if cached else []

            suggestions = classifier.suggest_filename(
                text=extracted_text,
                current_filename=self._current_pdf.name,
                keywords=keywords,
                detected_date=detected_date,
                use_llm=True,
                file_date=file_date,
            )

            for s in suggestions:
                if s.source == "llm" and s.metadata:
                    for key, value in s.metadata.items():
                        widget = self._metadata_inputs.get(key)
                        if widget:
                            if isinstance(widget, QPlainTextEdit):
                                widget.setPlainText(str(value))
                            else:
                                widget.setText(str(value))

                    # Gelernte Korrekturen anwenden
                    korr = s.metadata.get("korrespondent", "")
                    if korr:
                        try:
                            from src.utils.database import get_database
                            learned = get_database().get_korrespondent_metadata(korr)
                            if learned:
                                for lk, lv in learned.items():
                                    w = self._metadata_inputs.get(lk)
                                    if w:
                                        if isinstance(w, QPlainTextEdit):
                                            w.setPlainText(str(lv))
                                        else:
                                            w.setText(str(lv))
                        except Exception:
                            pass
                    break

        except Exception as e:
            print(f"LLM-Metadaten Fehler: {e}")
        finally:
            self.llm_btn.setEnabled(True)
            self.llm_btn.setText("KI-Metadaten generieren")

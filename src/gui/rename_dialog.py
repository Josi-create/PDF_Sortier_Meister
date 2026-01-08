"""
Verbesserter Umbenennungsdialog für PDF Sortier Meister

Features:
- Vorschau des neuen Namens
- Mehrere Namensvorschläge basierend auf PDF-Inhalt
- Lernen aus Benutzerentscheidungen
"""

from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QGroupBox,
    QFrame,
    QMessageBox,
)


@dataclass
class RenameSuggestion:
    """Ein Umbenennungsvorschlag."""
    name: str
    reason: str
    confidence: float  # 0.0 - 1.0


class RenameDialog(QDialog):
    """Dialog zum Umbenennen von PDF-Dateien mit intelligenten Vorschlägen."""

    # Signal wenn eine Umbenennung gelernt werden soll
    rename_learned = pyqtSignal(str, str, str, list)  # original, new, text, keywords

    def __init__(
        self,
        pdf_path: Path,
        suggestions: list[RenameSuggestion] = None,
        extracted_text: str = None,
        keywords: list[str] = None,
        parent=None
    ):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.suggestions = suggestions or []
        self.extracted_text = extracted_text or ""
        self.keywords = keywords or []
        self.new_name: Optional[str] = None

        self.setWindowTitle("PDF umbenennen")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        self.setup_ui()
        self.populate_suggestions()

    def setup_ui(self):
        """Initialisiert die UI-Komponenten."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # Originaldateiname
        original_group = QGroupBox("Aktueller Dateiname")
        original_layout = QVBoxLayout(original_group)

        self.original_label = QLabel(self.pdf_path.name)
        self.original_label.setStyleSheet(
            "font-family: monospace; padding: 8px; background-color: #f5f5f5; "
            "border-radius: 3px;"
        )
        self.original_label.setWordWrap(True)
        original_layout.addWidget(self.original_label)

        layout.addWidget(original_group)

        # Vorschläge
        suggestions_group = QGroupBox("Vorschläge (zum Auswählen klicken)")
        suggestions_layout = QVBoxLayout(suggestions_group)

        self.suggestions_list = QListWidget()
        self.suggestions_list.setMaximumHeight(150)
        self.suggestions_list.itemClicked.connect(self.on_suggestion_clicked)
        self.suggestions_list.itemDoubleClicked.connect(self.on_suggestion_double_clicked)
        suggestions_layout.addWidget(self.suggestions_list)

        layout.addWidget(suggestions_group)

        # Neuer Name Eingabe
        new_name_group = QGroupBox("Neuer Dateiname")
        new_name_layout = QVBoxLayout(new_name_group)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Neuen Dateinamen eingeben...")
        self.name_input.textChanged.connect(self.update_preview)
        font = QFont()
        font.setPointSize(11)
        self.name_input.setFont(font)
        new_name_layout.addWidget(self.name_input)

        # Hinweis zur .pdf Endung
        hint_label = QLabel("Die .pdf Endung wird automatisch hinzugefügt")
        hint_label.setStyleSheet("color: #666; font-size: 10px;")
        new_name_layout.addWidget(hint_label)

        layout.addWidget(new_name_group)

        # Vorschau
        preview_group = QGroupBox("Vorschau")
        preview_layout = QVBoxLayout(preview_group)

        self.preview_label = QLabel()
        self.preview_label.setStyleSheet(
            "font-family: monospace; padding: 10px; background-color: #e8f5e9; "
            "border: 1px solid #a5d6a7; border-radius: 3px; font-weight: bold;"
        )
        self.preview_label.setWordWrap(True)
        preview_layout.addWidget(self.preview_label)

        # Warnung bei ungültigen Zeichen
        self.warning_label = QLabel()
        self.warning_label.setStyleSheet("color: #d32f2f; font-size: 11px;")
        self.warning_label.hide()
        preview_layout.addWidget(self.warning_label)

        layout.addWidget(preview_group)

        # Erkannte Informationen
        if self.keywords:
            info_group = QGroupBox("Erkannte Informationen")
            info_layout = QVBoxLayout(info_group)

            keywords_text = ", ".join(self.keywords) if self.keywords else "Keine erkannt"
            keywords_label = QLabel(f"Schlüsselwörter: {keywords_text}")
            keywords_label.setStyleSheet("color: #666;")
            info_layout.addWidget(keywords_label)

            layout.addWidget(info_group)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)

        self.rename_button = QPushButton("Umbenennen")
        self.rename_button.setDefault(True)
        self.rename_button.clicked.connect(self.accept_rename)
        self.rename_button.setStyleSheet(
            "QPushButton { background-color: #1976d2; color: white; "
            "padding: 8px 20px; border: none; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1565c0; }"
            "QPushButton:disabled { background-color: #bdbdbd; }"
        )
        button_layout.addWidget(self.rename_button)

        layout.addLayout(button_layout)

        # Initial: Ersten Vorschlag in Input setzen
        if self.suggestions:
            self.name_input.setText(self.suggestions[0].name.replace('.pdf', ''))

    def populate_suggestions(self):
        """Füllt die Vorschlagsliste."""
        self.suggestions_list.clear()

        if not self.suggestions:
            item = QListWidgetItem("Keine Vorschläge verfügbar")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.suggestions_list.addItem(item)
            return

        for suggestion in self.suggestions:
            # Formatierung: Name (Grund - Konfidenz%)
            confidence_pct = int(suggestion.confidence * 100)
            display_text = f"{suggestion.name}"
            if suggestion.reason:
                display_text += f"  [{suggestion.reason}]"

            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, suggestion.name)
            item.setToolTip(f"Konfidenz: {confidence_pct}%\n{suggestion.reason}")

            # Farbcodierung nach Konfidenz
            if confidence_pct >= 70:
                item.setBackground(Qt.GlobalColor.green)
                item.setForeground(Qt.GlobalColor.darkGreen)
            elif confidence_pct >= 40:
                item.setBackground(Qt.GlobalColor.yellow)

            self.suggestions_list.addItem(item)

    def on_suggestion_clicked(self, item: QListWidgetItem):
        """Übernimmt einen Vorschlag in das Eingabefeld."""
        name = item.data(Qt.ItemDataRole.UserRole)
        if name:
            # .pdf Endung entfernen für die Eingabe
            name = name.replace('.pdf', '')
            self.name_input.setText(name)

    def on_suggestion_double_clicked(self, item: QListWidgetItem):
        """Doppelklick übernimmt und bestätigt sofort."""
        self.on_suggestion_clicked(item)
        self.accept_rename()

    def update_preview(self, text: str):
        """Aktualisiert die Vorschau."""
        if not text.strip():
            self.preview_label.setText("(Bitte Namen eingeben)")
            self.preview_label.setStyleSheet(
                "font-family: monospace; padding: 10px; background-color: #fff3e0; "
                "border: 1px solid #ffcc80; border-radius: 3px;"
            )
            self.rename_button.setEnabled(False)
            return

        # .pdf Endung hinzufügen wenn nicht vorhanden
        preview_name = text.strip()
        if not preview_name.lower().endswith('.pdf'):
            preview_name += '.pdf'

        # Ungültige Zeichen prüfen
        invalid_chars = '<>:"/\\|?*'
        found_invalid = [c for c in preview_name if c in invalid_chars]

        if found_invalid:
            self.warning_label.setText(
                f"Ungültige Zeichen gefunden: {' '.join(found_invalid)}"
            )
            self.warning_label.show()
            self.preview_label.setStyleSheet(
                "font-family: monospace; padding: 10px; background-color: #ffebee; "
                "border: 1px solid #ef9a9a; border-radius: 3px;"
            )
            self.rename_button.setEnabled(False)
        else:
            self.warning_label.hide()
            self.preview_label.setStyleSheet(
                "font-family: monospace; padding: 10px; background-color: #e8f5e9; "
                "border: 1px solid #a5d6a7; border-radius: 3px; font-weight: bold;"
            )
            self.rename_button.setEnabled(True)

        self.preview_label.setText(preview_name)

    def accept_rename(self):
        """Bestätigt die Umbenennung."""
        text = self.name_input.text().strip()

        if not text:
            QMessageBox.warning(
                self,
                "Fehler",
                "Bitte geben Sie einen Dateinamen ein."
            )
            return

        # .pdf Endung sicherstellen
        if not text.lower().endswith('.pdf'):
            text += '.pdf'

        # Ungültige Zeichen entfernen
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            text = text.replace(char, '')

        self.new_name = text
        self.accept()

    def get_new_name(self) -> Optional[str]:
        """Gibt den neuen Dateinamen zurück."""
        return self.new_name


def generate_rename_suggestions(
    pdf_path: Path,
    extracted_text: str = None,
    keywords: list[str] = None,
    dates: list = None,
    learned_patterns: list = None
) -> list[RenameSuggestion]:
    """
    Generiert Umbenennungsvorschläge für eine PDF.

    Args:
        pdf_path: Pfad zur PDF
        extracted_text: Bereits extrahierter Text
        keywords: Bereits extrahierte Schlüsselwörter
        dates: Bereits extrahierte Datumsangaben
        learned_patterns: Gelernte Muster aus der Datenbank

    Returns:
        Liste von RenameSuggestion Objekten
    """
    suggestions = []

    # 1. Vorschlag aus PDF-Analyzer
    try:
        from src.core.pdf_analyzer import PDFAnalyzer

        with PDFAnalyzer(pdf_path) as analyzer:
            if extracted_text is None:
                extracted_text = analyzer.extract_text()
            if keywords is None:
                keywords = analyzer.extract_keywords()
            if dates is None:
                dates = analyzer.extract_dates()

            # Standard-Vorschlag
            suggested = analyzer.suggest_filename()
            if suggested and suggested != pdf_path.name:
                suggestions.append(RenameSuggestion(
                    name=suggested,
                    reason="Automatisch erkannt",
                    confidence=0.6
                ))

    except Exception as e:
        print(f"Fehler bei PDF-Analyse für Vorschläge: {e}")

    # 2. Datum-basierte Vorschläge
    if dates:
        date_str = dates[0].strftime("%Y-%m-%d")

        # Nur Datum
        suggestions.append(RenameSuggestion(
            name=f"{date_str}.pdf",
            reason="Nur Datum",
            confidence=0.3
        ))

        # Datum + Kategorie
        if keywords:
            category = keywords[0].capitalize()
            suggestions.append(RenameSuggestion(
                name=f"{date_str} {category}.pdf",
                reason=f"Datum + Kategorie ({category})",
                confidence=0.5
            ))

    # 3. Kategorie-basierte Vorschläge
    if keywords:
        category = keywords[0].capitalize()

        # Nur Kategorie + Original-Dateinamen-Teil
        original_stem = pdf_path.stem
        # Extrahiere mögliche Nummer aus Original
        import re
        number_match = re.search(r'(\d{3,})', original_stem)
        if number_match:
            number = number_match.group(1)
            suggestions.append(RenameSuggestion(
                name=f"{category} Nr{number}.pdf",
                reason=f"Kategorie + Nummer",
                confidence=0.4
            ))

    # 4. Gelernte Muster anwenden
    if learned_patterns:
        for pattern in learned_patterns[:3]:  # Max 3 gelernte Vorschläge
            suggestions.append(RenameSuggestion(
                name=pattern.suggested_name,
                reason=f"Gelernt: ähnlich zu {pattern.original_name}",
                confidence=pattern.confidence
            ))

    # Duplikate entfernen (nach Name)
    seen_names = set()
    unique_suggestions = []
    for s in suggestions:
        if s.name.lower() not in seen_names:
            seen_names.add(s.name.lower())
            unique_suggestions.append(s)

    # Nach Konfidenz sortieren
    unique_suggestions.sort(key=lambda s: s.confidence, reverse=True)

    return unique_suggestions[:6]  # Max 6 Vorschläge

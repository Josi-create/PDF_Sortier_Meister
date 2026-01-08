"""
Einstellungsdialog für PDF Sortier Meister

Ermöglicht die Konfiguration von LLM-Providern und anderen Einstellungen.

MIT License - Copyright (c) 2026
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QPushButton,
    QGroupBox, QCheckBox, QMessageBox, QTabWidget,
    QWidget, QSpinBox, QDoubleSpinBox
)
from PyQt6.QtCore import Qt, pyqtSignal

from src.utils.config import get_config


class SettingsDialog(QDialog):
    """Dialog für Anwendungseinstellungen."""

    # Signal wenn Einstellungen geändert wurden
    settings_changed = pyqtSignal()

    def __init__(self, parent=None):
        """Initialisiert den Einstellungsdialog."""
        super().__init__(parent)
        self.config = get_config()
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        """Erstellt die Benutzeroberfläche."""
        self.setWindowTitle("Einstellungen")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        layout = QVBoxLayout(self)

        # Tab-Widget für verschiedene Kategorien
        tab_widget = QTabWidget()

        # LLM-Tab
        llm_tab = self._create_llm_tab()
        tab_widget.addTab(llm_tab, "KI-Assistent (LLM)")

        # Allgemeine Einstellungen Tab
        general_tab = self._create_general_tab()
        tab_widget.addTab(general_tab, "Allgemein")

        layout.addWidget(tab_widget)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.test_button = QPushButton("Verbindung testen")
        self.test_button.clicked.connect(self._test_connection)
        button_layout.addWidget(self.test_button)

        self.save_button = QPushButton("Speichern")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._save_settings)
        button_layout.addWidget(self.save_button)

        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)

    def _create_llm_tab(self) -> QWidget:
        """Erstellt den LLM-Einstellungs-Tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Provider-Auswahl
        provider_group = QGroupBox("LLM-Provider")
        provider_layout = QFormLayout(provider_group)

        self.provider_combo = QComboBox()
        self.provider_combo.addItems([
            "Keiner (nur lokale Klassifikation)",
            "Anthropic Claude",
            "OpenAI GPT",
            "Poe.com (viele Modelle)",
        ])
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_layout.addRow("Provider:", self.provider_combo)

        layout.addWidget(provider_group)

        # API-Konfiguration
        api_group = QGroupBox("API-Konfiguration")
        api_layout = QFormLayout(api_group)

        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("sk-... oder anthropic-...")
        api_layout.addRow("API-Key:", self.api_key_input)

        # Show/Hide Button für API-Key
        key_button_layout = QHBoxLayout()
        self.show_key_button = QPushButton("Anzeigen")
        self.show_key_button.setCheckable(True)
        self.show_key_button.toggled.connect(self._toggle_key_visibility)
        key_button_layout.addWidget(self.show_key_button)
        key_button_layout.addStretch()
        api_layout.addRow("", key_button_layout)

        # Modell-Auswahl
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        api_layout.addRow("Modell:", self.model_combo)

        layout.addWidget(api_group)

        # Erweiterte Einstellungen
        advanced_group = QGroupBox("Erweiterte Einstellungen")
        advanced_layout = QFormLayout(advanced_group)

        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(100, 2000)
        self.max_tokens_spin.setValue(500)
        self.max_tokens_spin.setSuffix(" Tokens")
        advanced_layout.addRow("Max. Tokens:", self.max_tokens_spin)

        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 1.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setValue(0.3)
        advanced_layout.addRow("Temperatur:", self.temperature_spin)

        self.auto_use_check = QCheckBox(
            "Automatisch bei niedriger lokaler Konfidenz verwenden"
        )
        advanced_layout.addRow("Auto-LLM:", self.auto_use_check)

        layout.addWidget(advanced_group)

        # Info-Label
        info_label = QLabel(
            "<i>Hinweis: Die LLM-Nutzung verursacht API-Kosten. "
            "Das lokale TF-IDF-System funktioniert auch ohne LLM.</i>"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: gray;")
        layout.addWidget(info_label)

        layout.addStretch()

        return tab

    def _create_general_tab(self) -> QWidget:
        """Erstellt den Tab für allgemeine Einstellungen."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Darstellung
        display_group = QGroupBox("Darstellung")
        display_layout = QFormLayout(display_group)

        self.thumbnail_size_spin = QSpinBox()
        self.thumbnail_size_spin.setRange(80, 300)
        self.thumbnail_size_spin.setValue(150)
        self.thumbnail_size_spin.setSuffix(" px")
        display_layout.addRow("Thumbnail-Größe:", self.thumbnail_size_spin)

        self.max_suggestions_spin = QSpinBox()
        self.max_suggestions_spin.setRange(1, 10)
        self.max_suggestions_spin.setValue(5)
        display_layout.addRow("Max. Vorschläge:", self.max_suggestions_spin)

        layout.addWidget(display_group)

        # Cache-Einstellungen
        cache_group = QGroupBox("PDF-Analyse-Cache")
        cache_layout = QVBoxLayout(cache_group)

        self.persist_cache_checkbox = QCheckBox("Cache über Programmende hinaus speichern")
        self.persist_cache_checkbox.setToolTip(
            "Wenn aktiviert, werden PDF-Analysen auf der Festplatte gespeichert.\n"
            "Beim nächsten Start sind bereits analysierte PDFs sofort verfügbar.\n"
            "Dies beschleunigt besonders große Ordner erheblich."
        )
        cache_layout.addWidget(self.persist_cache_checkbox)

        # Cache leeren Button
        cache_buttons_layout = QHBoxLayout()

        self.clear_cache_button = QPushButton("Cache leeren")
        self.clear_cache_button.setToolTip("Löscht alle gecachten PDF-Analysen")
        self.clear_cache_button.clicked.connect(self._clear_cache)
        cache_buttons_layout.addWidget(self.clear_cache_button)

        self.cache_stats_label = QLabel("")
        cache_buttons_layout.addWidget(self.cache_stats_label)
        cache_buttons_layout.addStretch()

        cache_layout.addLayout(cache_buttons_layout)

        layout.addWidget(cache_group)

        layout.addStretch()

        return tab

    def _clear_cache(self):
        """Löscht den PDF-Analyse-Cache."""
        try:
            from src.core.pdf_cache import get_pdf_cache

            reply = QMessageBox.question(
                self,
                "Cache leeren",
                "Möchten Sie den gesamten PDF-Analyse-Cache löschen?\n\n"
                "Alle PDFs müssen dann erneut analysiert werden.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                cache = get_pdf_cache()
                cache.clear()
                cache.clear_persistent_cache()
                self._update_cache_stats()
                QMessageBox.information(
                    self, "Cache geleert", "Der PDF-Analyse-Cache wurde erfolgreich geleert."
                )

        except Exception as e:
            QMessageBox.warning(self, "Fehler", f"Cache konnte nicht geleert werden:\n{e}")

    def _update_cache_stats(self):
        """Aktualisiert die Cache-Statistik-Anzeige."""
        try:
            from src.core.pdf_cache import get_pdf_cache
            cache = get_pdf_cache()
            stats = cache.get_stats()
            self.cache_stats_label.setText(f"({stats['cached_count']} PDFs im Cache)")
        except Exception:
            self.cache_stats_label.setText("")

    def _on_provider_changed(self, index: int):
        """Wird aufgerufen wenn der Provider geändert wird."""
        # Modelle je nach Provider aktualisieren
        self.model_combo.clear()

        if index == 0:  # Keiner
            self.api_key_input.setEnabled(False)
            self.model_combo.setEnabled(False)
            self.test_button.setEnabled(False)
        elif index == 1:  # Claude
            self.api_key_input.setEnabled(True)
            self.model_combo.setEnabled(True)
            self.test_button.setEnabled(True)
            self.model_combo.addItems([
                "haiku (schnell & günstig)",
                "sonnet (ausgewogen)",
                "opus (beste Qualität)",
            ])
            self.api_key_input.setPlaceholderText("sk-ant-...")
        elif index == 2:  # OpenAI
            self.api_key_input.setEnabled(True)
            self.model_combo.setEnabled(True)
            self.test_button.setEnabled(True)
            self.model_combo.addItems([
                "gpt-4o-mini (schnell & günstig)",
                "gpt-4o (ausgewogen)",
                "gpt-4-turbo (beste Qualität)",
            ])
            self.api_key_input.setPlaceholderText("sk-...")
        elif index == 3:  # Poe
            self.api_key_input.setEnabled(True)
            self.model_combo.setEnabled(True)
            self.test_button.setEnabled(True)
            self.model_combo.addItems([
                "GPT-4o-Mini (schnell & günstig)",
                "GPT-4o (OpenAI)",
                "GPT-5 (neuestes GPT)",
                "Claude-3.5-Sonnet (Anthropic)",
                "Claude-3-Haiku (schnell)",
                "Gemini-2-Flash (Google)",
                "Llama-3.1-405B (Meta)",
                "Mistral-Large (Mistral)",
            ])
            self.api_key_input.setPlaceholderText("Poe API-Key von poe.com/api_key")

    def _toggle_key_visibility(self, checked: bool):
        """Zeigt/versteckt den API-Key."""
        if checked:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_key_button.setText("Verbergen")
        else:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_key_button.setText("Anzeigen")

    def _load_settings(self):
        """Lädt die aktuellen Einstellungen."""
        # LLM-Einstellungen
        llm_config = self.config.get_llm_config()
        provider = llm_config.get("provider", "none")

        if provider == "claude":
            self.provider_combo.setCurrentIndex(1)
        elif provider == "openai":
            self.provider_combo.setCurrentIndex(2)
        elif provider == "poe":
            self.provider_combo.setCurrentIndex(3)
        else:
            self.provider_combo.setCurrentIndex(0)

        self.api_key_input.setText(llm_config.get("api_key", ""))

        model = llm_config.get("model", "")
        if model:
            # Versuche Modell in Combo zu finden
            for i in range(self.model_combo.count()):
                if model in self.model_combo.itemText(i).lower():
                    self.model_combo.setCurrentIndex(i)
                    break
            else:
                self.model_combo.setCurrentText(model)

        self.max_tokens_spin.setValue(llm_config.get("max_tokens", 500))
        self.temperature_spin.setValue(llm_config.get("temperature", 0.3))
        self.auto_use_check.setChecked(llm_config.get("auto_use", False))

        # Allgemeine Einstellungen
        self.thumbnail_size_spin.setValue(self.config.get("thumbnail_size", 150))
        self.max_suggestions_spin.setValue(self.config.get("max_suggestions", 5))

        # Cache-Einstellungen
        self.persist_cache_checkbox.setChecked(self.config.get("persist_pdf_cache", True))
        self._update_cache_stats()

    def _save_settings(self):
        """Speichert die Einstellungen."""
        # LLM-Einstellungen
        provider_index = self.provider_combo.currentIndex()
        if provider_index == 0:
            provider = "none"
        elif provider_index == 1:
            provider = "claude"
        elif provider_index == 2:
            provider = "openai"
        else:
            provider = "poe"

        # Modellname extrahieren (vor dem Klammerteil)
        model_text = self.model_combo.currentText()
        model = model_text.split(" ")[0] if model_text else ""

        llm_config = {
            "provider": provider,
            "api_key": self.api_key_input.text().strip(),
            "model": model,
            "max_tokens": self.max_tokens_spin.value(),
            "temperature": self.temperature_spin.value(),
            "auto_use": self.auto_use_check.isChecked(),
        }
        self.config.set("llm", llm_config)

        # Allgemeine Einstellungen
        self.config.set("thumbnail_size", self.thumbnail_size_spin.value())
        self.config.set("max_suggestions", self.max_suggestions_spin.value())

        # Cache-Einstellungen
        persist_cache = self.persist_cache_checkbox.isChecked()
        self.config.set("persist_pdf_cache", persist_cache)

        # Cache-Modul über Änderung informieren
        try:
            from src.core.pdf_cache import get_pdf_cache
            cache = get_pdf_cache()
            cache.set_persist_cache(persist_cache)
        except Exception:
            pass

        self.settings_changed.emit()
        self.accept()

    def _test_connection(self):
        """Testet die Verbindung zum LLM-Provider."""
        provider_index = self.provider_combo.currentIndex()
        api_key = self.api_key_input.text().strip()

        if not api_key:
            QMessageBox.warning(
                self, "Fehler",
                "Bitte geben Sie einen API-Key ein."
            )
            return

        # Modellname extrahieren
        model_text = self.model_combo.currentText()
        model = model_text.split(" ")[0] if model_text else ""

        self.test_button.setEnabled(False)
        self.test_button.setText("Teste...")

        try:
            if provider_index == 1:  # Claude
                self._test_claude(api_key, model)
            elif provider_index == 2:  # OpenAI
                self._test_openai(api_key, model)
            elif provider_index == 3:  # Poe
                self._test_poe(api_key, model)
        finally:
            self.test_button.setEnabled(True)
            self.test_button.setText("Verbindung testen")

    def _test_claude(self, api_key: str, model: str):
        """Testet die Claude API."""
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)

            # Kurzer Test-Request
            from src.ml.claude_provider import ClaudeProvider
            model_id = ClaudeProvider.MODELS.get(model, model)

            message = client.messages.create(
                model=model_id,
                max_tokens=10,
                messages=[
                    {"role": "user", "content": "Sage 'OK'"}
                ]
            )

            QMessageBox.information(
                self, "Erfolg",
                f"Verbindung zu Claude erfolgreich!\n"
                f"Modell: {model_id}\n"
                f"Antwort: {message.content[0].text}"
            )
        except ImportError:
            QMessageBox.critical(
                self, "Fehler",
                "Das 'anthropic' Paket ist nicht installiert.\n"
                "Installieren mit: pip install anthropic"
            )
        except anthropic.AuthenticationError:
            QMessageBox.critical(
                self, "Fehler",
                "Ungültiger API-Key. Bitte überprüfen Sie Ihren Key."
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Fehler",
                f"Verbindungsfehler: {str(e)}"
            )

    def _test_openai(self, api_key: str, model: str):
        """Testet die OpenAI API."""
        try:
            import openai
            client = openai.OpenAI(api_key=api_key)

            # Modell-ID ermitteln
            from src.ml.openai_provider import OpenAIProvider
            model_id = OpenAIProvider.MODELS.get(model, model)

            response = client.chat.completions.create(
                model=model_id,
                max_tokens=10,
                messages=[
                    {"role": "user", "content": "Sage 'OK'"}
                ]
            )

            QMessageBox.information(
                self, "Erfolg",
                f"Verbindung zu OpenAI erfolgreich!\n"
                f"Modell: {model_id}\n"
                f"Antwort: {response.choices[0].message.content}"
            )
        except ImportError:
            QMessageBox.critical(
                self, "Fehler",
                "Das 'openai' Paket ist nicht installiert.\n"
                "Installieren mit: pip install openai"
            )
        except openai.AuthenticationError:
            QMessageBox.critical(
                self, "Fehler",
                "Ungültiger API-Key. Bitte überprüfen Sie Ihren Key."
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Fehler",
                f"Verbindungsfehler: {str(e)}"
            )

    def _test_poe(self, api_key: str, model: str):
        """Testet die Poe API."""
        try:
            import openai
            client = openai.OpenAI(
                api_key=api_key,
                base_url="https://api.poe.com/v1",
            )

            response = client.chat.completions.create(
                model=model,
                max_tokens=20,  # Poe erfordert mindestens 16 Tokens
                messages=[
                    {"role": "user", "content": "Sage 'OK'"}
                ]
            )

            QMessageBox.information(
                self, "Erfolg",
                f"Verbindung zu Poe erfolgreich!\n"
                f"Modell: {model}\n"
                f"Antwort: {response.choices[0].message.content}"
            )
        except ImportError:
            QMessageBox.critical(
                self, "Fehler",
                "Das 'openai' Paket ist nicht installiert.\n"
                "Installieren mit: pip install openai"
            )
        except openai.AuthenticationError:
            QMessageBox.critical(
                self, "Fehler",
                "Ungültiger Poe API-Key.\n"
                "Holen Sie Ihren Key von: poe.com/api_key"
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Fehler",
                f"Verbindungsfehler: {str(e)}"
            )

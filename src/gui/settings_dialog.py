"""
Einstellungsdialog für PDF Sortier Meister

Ermöglicht die Konfiguration von LLM-Providern und anderen Einstellungen.

MIT License - Copyright (c) 2026
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QPushButton,
    QGroupBox, QCheckBox, QMessageBox, QTabWidget,
    QWidget, QSpinBox, QDoubleSpinBox, QRadioButton,
    QButtonGroup, QPlainTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal

import sys

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

        # Dateinamen-Muster Tab
        filename_tab = self._create_filename_pattern_tab()
        tab_widget.addTab(filename_tab, "Dateinamen-Muster")

        # Persönliche Daten Tab
        personal_tab = self._create_personal_tab()
        tab_widget.addTab(personal_tab, "Persönliche Daten")

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
            "Ollama (lokal, kein API-Key noetig)",
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

        # Server-URL (nur fuer Ollama relevant)
        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText("http://localhost:11434")
        self.base_url_input.setToolTip(
            "Nur fuer Ollama: URL des lokalen Ollama-Servers.\n"
            "Standard: http://localhost:11434"
        )
        api_layout.addRow("Server-URL:", self.base_url_input)

        # Modell-Auswahl mit Aktualisieren-Button
        model_row_layout = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        model_row_layout.addWidget(self.model_combo, 1)

        self.refresh_models_button = QPushButton("Modelle aktualisieren")
        self.refresh_models_button.setToolTip(
            "Ruft die aktuell verfügbaren Modelle vom API-Provider ab.\n"
            "Erfordert einen gültigen API-Key."
        )
        self.refresh_models_button.clicked.connect(self._refresh_models)
        model_row_layout.addWidget(self.refresh_models_button)

        api_layout.addRow("Modell:", model_row_layout)

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

        self.text_limit_spin = QSpinBox()
        self.text_limit_spin.setRange(500, 5000)
        self.text_limit_spin.setValue(1500)
        self.text_limit_spin.setSingleStep(500)
        self.text_limit_spin.setSuffix(" Zeichen")
        self.text_limit_spin.setToolTip(
            "Maximale Textlänge die an die LLM gesendet wird.\n"
            "Weniger = schneller + günstiger, aber weniger Kontext.\n"
            "Empfohlen: 1500 (meist ausreichend für Kopfzeile/Absender)"
        )
        advanced_layout.addRow("Text-Limit:", self.text_limit_spin)

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

    # Vordefinierte Muster - werden im Tab als Auswahl angeboten und genau so
    # an die LLM uebergeben (sie soll das Muster IMITIEREN, nicht woertlich
    # uebernehmen, siehe Prompt-Hinweis in llm_provider._build_filename_pattern_info).
    PATTERN_PRESETS = [
        ("YYYY-MM-DD_Rechnung_Kontakt_Betreff",
         "Datum_Dokumenttyp_Absender_Betreff (z.B. fuer Rechnungen)"),
        ("PROJEKTNUMMER_INITIALIEN/AKTENZEICHEN_YYYY-MM-DD_Betreff_Kontakt",
         "Projekt-/Aktenbezogen (Projekt zuerst, dann Datum)"),
    ]

    def _create_filename_pattern_tab(self) -> QWidget:
        """
        Erstellt den Tab fuer das benutzerdefinierte Dateinamen-Muster.

        Der Nutzer kann zwischen Standardverhalten, vordefinierten Mustern und
        einem Freitext-Template waehlen. Der gewaehlte Wert wird als Hinweis in
        den Filename-Prompt aller LLM-Provider eingeflochten.
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)

        info_label = QLabel(
            "Hier koennen Sie der KI ein Muster vorgeben, an dem sie sich beim "
            "Vorschlagen von Dateinamen orientieren soll. Die KI ersetzt die "
            "Platzhalter im Muster mit den konkreten Werten aus dem Dokument."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #555; padding: 5px;")
        layout.addWidget(info_label)

        # Auswahl-Gruppe: Standard | Preset 1 | Preset 2 | Freitext
        choice_group = QGroupBox("Muster waehlen")
        choice_layout = QVBoxLayout(choice_group)

        self.pattern_button_group = QButtonGroup(self)

        self.pattern_radio_default = QRadioButton(
            "Standard (KI entscheidet selbst, z.B. YYYY-MM-DD_Kategorie_Beschreibung)"
        )
        self.pattern_button_group.addButton(self.pattern_radio_default, 0)
        choice_layout.addWidget(self.pattern_radio_default)

        self.pattern_preset_radios = []
        for i, (pattern, description) in enumerate(self.PATTERN_PRESETS, start=1):
            radio = QRadioButton(f"{pattern}\n    ({description})")
            self.pattern_button_group.addButton(radio, i)
            choice_layout.addWidget(radio)
            self.pattern_preset_radios.append((radio, pattern))

        self.pattern_radio_custom = QRadioButton("Eigenes Muster (Freitext):")
        self.pattern_button_group.addButton(
            self.pattern_radio_custom, len(self.PATTERN_PRESETS) + 1
        )
        choice_layout.addWidget(self.pattern_radio_custom)

        self.pattern_custom_input = QPlainTextEdit()
        self.pattern_custom_input.setPlaceholderText(
            "z.B.  YYYY-MM-DD_Lieferant_Auftragsnummer_Kurzbeschreibung\n"
            "\n"
            "Sie koennen die Platzhalter frei waehlen. Schreiben Sie z.B.\n"
            "'Datum' oder 'YYYY-MM-DD' fuer das Datum, 'Kontakt' oder 'Absender'\n"
            "fuer den Korrespondenten, usw. Die KI interpretiert die\n"
            "Bezeichnungen selbst und fuellt sie aus dem Dokument."
        )
        self.pattern_custom_input.setMaximumHeight(120)
        choice_layout.addWidget(self.pattern_custom_input)

        layout.addWidget(choice_group)

        # UI-Logik: Freitextfeld nur bei "Eigenes Muster" aktiv
        self.pattern_button_group.idToggled.connect(self._on_pattern_choice_changed)

        # Hinweis
        hint_label = QLabel(
            "<i>Hinweis: Das Muster wird der KI als Vorlage gezeigt. Die "
            "allgemeinen Regeln (erlaubte Zeichen, Datum nicht erfinden, "
            "max. 80 Zeichen) bleiben bestehen.</i>"
        )
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet("color: gray;")
        layout.addWidget(hint_label)

        layout.addStretch()
        return tab

    def _on_pattern_choice_changed(self, button_id: int, checked: bool):
        """Aktiviert/deaktiviert das Freitextfeld je nach Auswahl."""
        if not checked:
            return
        is_custom = (button_id == len(self.PATTERN_PRESETS) + 1)
        self.pattern_custom_input.setEnabled(is_custom)

    def _create_personal_tab(self) -> QWidget:
        """Erstellt den Tab für persönliche Daten."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Erklärung
        info_label = QLabel(
            "Damit das System Sie nicht als Korrespondent erkennt, geben Sie hier\n"
            "Ihren Namen ein. Der Korrespondent ist immer die andere Partei\n"
            "(Firma, Behörde, Person) — nicht Sie selbst."
        )
        info_label.setStyleSheet("color: #555; font-size: 11px; padding: 5px;")
        layout.addWidget(info_label)

        # Benutzerinformationen
        user_group = QGroupBox("Ihre Daten")
        user_layout = QFormLayout(user_group)

        self.owner_name_input = QLineEdit()
        self.owner_name_input.setPlaceholderText("z.B. Johannes Härle-Wack")
        self.owner_name_input.setToolTip("Ihr vollständiger Name")
        user_layout.addRow("Name:", self.owner_name_input)

        self.owner_variants_input = QLineEdit()
        self.owner_variants_input.setPlaceholderText("z.B. J. Härle-Wack, Härle-Wack")
        self.owner_variants_input.setToolTip(
            "Weitere Schreibweisen Ihres Namens (kommagetrennt),\n"
            "die auf Dokumenten vorkommen können."
        )
        user_layout.addRow("Namensvarianten:", self.owner_variants_input)

        self.owner_company_input = QLineEdit()
        self.owner_company_input.setPlaceholderText("z.B. Härle-Wack GbR (optional)")
        self.owner_company_input.setToolTip("Ihre eigene Firma (falls vorhanden)")
        user_layout.addRow("Eigene Firma:", self.owner_company_input)

        self.owner_address_input = QLineEdit()
        self.owner_address_input.setPlaceholderText("z.B. Musterstraße 12, 12345 Berlin (optional)")
        self.owner_address_input.setToolTip("Ihre Adresse (hilft bei der Erkennung auf Briefen)")
        user_layout.addRow("Adresse:", self.owner_address_input)

        self.owner_emails_input = QLineEdit()
        self.owner_emails_input.setPlaceholderText(
            "z.B. ich@example.com, privat@example.com (kommagetrennt)"
        )
        self.owner_emails_input.setToolTip(
            "Ihre eigenen E-Mail-Adressen (kommagetrennt).\n"
            "Mehrere Adressen moeglich. Hilft der KI, Sie als Empfaenger\n"
            "und nicht als Korrespondent zu erkennen, wenn die Adresse\n"
            "auf einem Dokument steht."
        )
        user_layout.addRow("E-Mail-Adressen:", self.owner_emails_input)

        layout.addWidget(user_group)

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

        self.llm_precache_checkbox = QCheckBox("LLM-Vorschläge im Hintergrund vorladen (Pre-Caching)")
        self.llm_precache_checkbox.setToolTip(
            "Wenn aktiviert, werden LLM-Namensvorschläge bereits im Hintergrund\n"
            "abgerufen, bevor Sie den Umbenennen-Dialog öffnen.\n"
            "Dies beschleunigt den Dialog, verursacht aber mehr API-Aufrufe.\n"
            "Deaktivieren für Debugging oder um API-Kosten zu sparen."
        )
        cache_layout.addWidget(self.llm_precache_checkbox)

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

        # Windows-Explorer-Integration (nur unter Windows sinnvoll)
        if sys.platform == "win32":
            explorer_group = QGroupBox("Windows-Explorer-Integration")
            explorer_layout = QVBoxLayout(explorer_group)

            self.explorer_menu_checkbox = QCheckBox(
                "Im Rechtsklick-Menue des Explorers anzeigen "
                "(\"PDF Sortier Meister von hier oeffnen\")"
            )
            self.explorer_menu_checkbox.setToolTip(
                "Fuegt einen Eintrag zum Kontextmenue hinzu fuer:\n"
                "  - Ordner (Rechtsklick auf Ordner-Icon)\n"
                "  - Ordner-Hintergrund (Rechtsklick in den leeren Bereich)\n"
                "  - PDF-Dateien (Ordner wird gewechselt, PDF selektiert,\n"
                "    Umbenennungs-Dialog mit KI-Vorschlag oeffnet sich)\n"
                "Laeuft das Programm bereits, wird der Pfad an die offene\n"
                "Instanz uebergeben statt eine zweite zu starten."
            )
            explorer_layout.addWidget(self.explorer_menu_checkbox)

            self.explorer_info_label = QLabel("")
            self.explorer_info_label.setStyleSheet("color: gray;")
            self.explorer_info_label.setWordWrap(True)
            explorer_layout.addWidget(self.explorer_info_label)

            layout.addWidget(explorer_group)

        # Debug-Bereich
        debug_group = QGroupBox("Debug / Zurücksetzen")
        debug_layout = QVBoxLayout(debug_group)

        debug_info = QLabel(
            "<i>Achtung: Diese Aktionen können nicht rückgängig gemacht werden!</i>"
        )
        debug_info.setStyleSheet("color: #cc0000;")
        debug_layout.addWidget(debug_info)

        debug_buttons_layout = QHBoxLayout()

        self.clear_learning_button = QPushButton("🗑 Gelernte Ordnervorschläge löschen")
        self.clear_learning_button.setToolTip(
            "Löscht alle gelernten Zuordnungen (Sortierhistorie, Ordnerstatistiken).\n"
            "Das Programm startet danach quasi 'neu' ohne Lernfortschritt."
        )
        self.clear_learning_button.clicked.connect(self._clear_learned_data)
        debug_buttons_layout.addWidget(self.clear_learning_button)

        debug_buttons_layout.addStretch()
        debug_layout.addLayout(debug_buttons_layout)

        # Statistik-Label
        self.learning_stats_label = QLabel("")
        debug_layout.addWidget(self.learning_stats_label)
        self._update_learning_stats()

        layout.addWidget(debug_group)

        layout.addStretch()

        return tab

    def _clear_learned_data(self):
        """Löscht alle gelernten Ordnervorschläge aus der Datenbank."""
        try:
            from src.utils.database import get_database

            db = get_database()
            entry_count = db.get_entry_count()
            rename_count = db.get_rename_count()

            reply = QMessageBox.warning(
                self,
                "Gelernte Daten löschen",
                f"Möchten Sie wirklich ALLE gelernten Daten löschen?\n\n"
                f"• {entry_count} Sortierhistorie-Einträge\n"
                f"• {rename_count} Umbenennungs-Einträge\n"
                f"• Alle Ordnerstatistiken\n\n"
                f"Diese Aktion kann NICHT rückgängig gemacht werden!",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply != QMessageBox.StandardButton.Yes:
                return

            # Nochmal bestätigen
            confirm = QMessageBox.question(
                self,
                "Wirklich löschen?",
                "Sind Sie SICHER? Alle Lernfortschritte gehen verloren!",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if confirm != QMessageBox.StandardButton.Yes:
                return

            # Datenbank-Tabellen leeren
            session = db.get_session()
            try:
                from src.utils.database import SortingHistory, TargetFolder, RenameHistory

                session.query(SortingHistory).delete()
                session.query(TargetFolder).delete()
                session.query(RenameHistory).delete()
                session.commit()

                # Classifier-Modell auch löschen
                from src.ml.classifier import get_classifier
                classifier = get_classifier()
                if classifier.model_path.exists():
                    classifier.model_path.unlink()
                classifier._retrain()  # Leeres Modell erstellen

                self._update_learning_stats()

                QMessageBox.information(
                    self,
                    "Daten gelöscht",
                    "Alle gelernten Ordnervorschläge wurden gelöscht.\n"
                    "Das Programm startet jetzt ohne Lernfortschritt."
                )

            finally:
                session.close()

        except Exception as e:
            QMessageBox.critical(
                self,
                "Fehler",
                f"Fehler beim Löschen der Daten:\n{e}"
            )

    def _update_learning_stats(self):
        """Aktualisiert die Lernstatistik-Anzeige."""
        try:
            from src.utils.database import get_database
            db = get_database()
            entry_count = db.get_entry_count()
            rename_count = db.get_rename_count()
            self.learning_stats_label.setText(
                f"Aktuell: {entry_count} Sortierungen, {rename_count} Umbenennungen gelernt"
            )
        except Exception:
            self.learning_stats_label.setText("")

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
            llm_count = stats.get('llm_cached_count', 0)
            if llm_count > 0:
                self.cache_stats_label.setText(
                    f"({stats['cached_count']} PDFs, {llm_count} mit LLM-Vorschlägen)"
                )
            else:
                self.cache_stats_label.setText(f"({stats['cached_count']} PDFs im Cache)")
        except Exception:
            self.cache_stats_label.setText("")

    def _on_provider_changed(self, index: int):
        """Wird aufgerufen wenn der Provider geändert wird."""
        # Modelle je nach Provider aktualisieren
        self.model_combo.clear()

        # Server-URL ist nur fuer Ollama relevant - standardmaessig deaktivieren
        is_ollama = (index == 4)
        self.base_url_input.setEnabled(is_ollama)

        if index == 0:  # Keiner
            self.api_key_input.setEnabled(False)
            self.model_combo.setEnabled(False)
            self.test_button.setEnabled(False)
        elif index == 1:  # Claude
            self.api_key_input.setEnabled(True)
            self.model_combo.setEnabled(True)
            self.test_button.setEnabled(True)
            self.model_combo.addItems([
                "haiku-3.5 (günstig, älter)",
                "haiku-4.5 (schnell & günstig)",
                "sonnet-3.5 (günstig, älter)",
                "sonnet-4 (ausgewogen)",
                "sonnet-4.5 (beste Qualität)",
                "opus-4 (premium)",
            ])
            self.api_key_input.setPlaceholderText("sk-ant-...")
        elif index == 2:  # OpenAI
            self.api_key_input.setEnabled(True)
            self.model_combo.setEnabled(True)
            self.test_button.setEnabled(True)
            self.model_combo.addItems([
                "gpt-4o-mini (günstig, älter)",
                "gpt-4.1-nano (schnellstes)",
                "gpt-4.1-mini (schnell & günstig)",
                "gpt-4o (ausgewogen)",
                "gpt-4.1 (beste Qualität)",
                "o3-mini (Reasoning, günstig)",
                "o3 (Reasoning)",
                "o4-mini (Reasoning, neu)",
            ])
            self.api_key_input.setPlaceholderText("sk-...")
        elif index == 3:  # Poe
            self.api_key_input.setEnabled(True)
            self.model_combo.setEnabled(True)
            self.test_button.setEnabled(True)
            self.model_combo.addItems([
                "GPT-4o-Mini (schnell & günstig)",
                "GPT-4o (OpenAI)",
                "GPT-4.1-Mini (OpenAI, neu)",
                "GPT-4.1 (OpenAI, neu)",
                "o3-Mini (Reasoning)",
                "o4-Mini (Reasoning, neu)",
                "Claude-3.5-Haiku (schnell)",
                "Claude-3.5-Sonnet (Anthropic)",
                "Claude-Sonnet-4 (Anthropic, neu)",
                "Claude-Sonnet-4.5 (Anthropic, neuestes)",
                "Claude-Opus-4 (Anthropic, premium)",
                "Gemini-2-Flash (Google)",
                "Gemini-2.5-Flash (Google, neu)",
                "Gemini-2.5-Pro (Google, premium)",
                "Llama-3.1-405B (Meta)",
                "Mistral-Large (Mistral)",
            ])
            self.api_key_input.setPlaceholderText("Poe API-Key von poe.com/api_key")
        elif index == 4:  # Ollama (lokal)
            # Kein API-Key noetig, aber URL und Modell
            self.api_key_input.setEnabled(False)
            self.api_key_input.setPlaceholderText("Nicht noetig fuer Ollama")
            self.model_combo.setEnabled(True)
            self.test_button.setEnabled(True)
            # Vorinstallierte Vorschlaege - per "Modelle aktualisieren" werden
            # die tatsaechlich vorhandenen Modelle vom Server gelesen.
            self.model_combo.addItems([
                "llama3.1 (Meta, ausgewogen)",
                "llama3.2 (Meta, klein & schnell)",
                "qwen2.5 (Alibaba, gut bei strukturiertem Output)",
                "mistral (Mistral, klein)",
                "gemma3 (Google)",
                "phi3 (Microsoft, sehr klein)",
            ])

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
        elif provider == "ollama":
            self.provider_combo.setCurrentIndex(4)
        else:
            self.provider_combo.setCurrentIndex(0)

        self.api_key_input.setText(llm_config.get("api_key", ""))
        self.base_url_input.setText(llm_config.get("base_url", ""))

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
        self.text_limit_spin.setValue(llm_config.get("text_limit", 1500))

        # Allgemeine Einstellungen
        self.thumbnail_size_spin.setValue(self.config.get("thumbnail_size", 150))
        self.max_suggestions_spin.setValue(self.config.get("max_suggestions", 5))

        # Persönliche Daten
        self.owner_name_input.setText(self.config.get("owner_name", ""))
        self.owner_variants_input.setText(self.config.get("owner_name_variants", ""))
        self.owner_company_input.setText(self.config.get("owner_company", ""))
        self.owner_address_input.setText(self.config.get("owner_address", ""))
        self.owner_emails_input.setText(self.config.get("owner_emails", ""))

        # Dateinamen-Muster
        self._load_filename_pattern()

        # Cache-Einstellungen
        self.persist_cache_checkbox.setChecked(self.config.get("persist_pdf_cache", True))
        self.llm_precache_checkbox.setChecked(self.config.get("llm_precache_enabled", True))
        self._update_cache_stats()

        # Explorer-Integration: aktuellen Stand aus der Registry lesen.
        if sys.platform == "win32":
            try:
                from src.utils.explorer_integration import is_context_menu_registered
                registered = is_context_menu_registered()
            except Exception:
                registered = False
            self.explorer_menu_checkbox.setChecked(registered)
            self._explorer_initial_state = registered
            self.explorer_info_label.setText(
                "Aktuell aktiviert." if registered else
                "Aktuell nicht eingerichtet."
            )

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
        elif provider_index == 3:
            provider = "poe"
        else:
            provider = "ollama"

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
            "text_limit": self.text_limit_spin.value(),
            "base_url": self.base_url_input.text().strip(),
        }
        self.config.set("llm", llm_config)

        # Allgemeine Einstellungen
        self.config.set("thumbnail_size", self.thumbnail_size_spin.value())
        self.config.set("max_suggestions", self.max_suggestions_spin.value())

        # Cache-Einstellungen
        persist_cache = self.persist_cache_checkbox.isChecked()
        self.config.set("persist_pdf_cache", persist_cache)

        llm_precache = self.llm_precache_checkbox.isChecked()
        self.config.set("llm_precache_enabled", llm_precache)

        # Cache-Modul über Änderung informieren
        try:
            from src.core.pdf_cache import get_pdf_cache
            cache = get_pdf_cache()
            cache.set_persist_cache(persist_cache)
            cache.set_llm_precache_enabled(llm_precache)
        except Exception:
            pass

        # Persönliche Daten speichern
        self.config.set("owner_name", self.owner_name_input.text().strip())
        self.config.set("owner_name_variants", self.owner_variants_input.text().strip())
        self.config.set("owner_company", self.owner_company_input.text().strip())
        self.config.set("owner_address", self.owner_address_input.text().strip())
        self.config.set("owner_emails", self.owner_emails_input.text().strip())

        # Dateinamen-Muster speichern
        self.config.set("filename_pattern", self._collect_filename_pattern())

        # Explorer-Integration nur bei Aenderung anwenden.
        if sys.platform == "win32":
            self._apply_explorer_integration_change()

        self.settings_changed.emit()
        self.accept()

    def _apply_explorer_integration_change(self):
        """Setzt oder entfernt den Explorer-Kontextmenue-Eintrag."""
        desired = self.explorer_menu_checkbox.isChecked()
        current = getattr(self, "_explorer_initial_state", False)
        if desired == current:
            return

        try:
            from src.utils.explorer_integration import (
                register_context_menu,
                unregister_context_menu,
            )
            if desired:
                register_context_menu()
            else:
                unregister_context_menu()
            self._explorer_initial_state = desired
        except Exception as e:
            QMessageBox.warning(
                self,
                "Explorer-Integration",
                f"Die Aenderung konnte nicht angewendet werden:\n{e}"
            )

    def _load_filename_pattern(self):
        """Stellt die gespeicherte Pattern-Auswahl im Tab wieder her."""
        saved = self.config.get("filename_pattern", "").strip()

        if not saved:
            self.pattern_radio_default.setChecked(True)
            self.pattern_custom_input.setEnabled(False)
            return

        # Match gegen Presets
        for radio, pattern in self.pattern_preset_radios:
            if saved == pattern:
                radio.setChecked(True)
                self.pattern_custom_input.setEnabled(False)
                return

        # Sonst: Freitext
        self.pattern_radio_custom.setChecked(True)
        self.pattern_custom_input.setPlainText(saved)
        self.pattern_custom_input.setEnabled(True)

    def _collect_filename_pattern(self) -> str:
        """Ermittelt den zu speichernden Pattern-String aus der UI-Auswahl."""
        if self.pattern_radio_default.isChecked():
            return ""
        for radio, pattern in self.pattern_preset_radios:
            if radio.isChecked():
                return pattern
        if self.pattern_radio_custom.isChecked():
            return self.pattern_custom_input.toPlainText().strip()
        return ""

    def _test_connection(self):
        """Testet die Verbindung zum LLM-Provider."""
        provider_index = self.provider_combo.currentIndex()
        api_key = self.api_key_input.text().strip()

        # Ollama braucht keinen API-Key, aber eine URL.
        if provider_index == 4:
            base_url = self.base_url_input.text().strip() or "http://localhost:11434"
        elif not api_key:
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
            elif provider_index == 4:  # Ollama
                self._test_ollama(base_url, model)
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

    def _test_ollama(self, base_url: str, model: str):
        """Testet die Verbindung zu einem lokalen Ollama-Server."""
        try:
            from src.ml.ollama_provider import OllamaProvider
            from src.ml.llm_provider import LLMConfig

            provider = OllamaProvider(LLMConfig(
                api_key="",
                model=model or OllamaProvider.DEFAULT_MODEL,
                base_url=base_url,
            ))

            ok, msg = provider.ping()
            if not ok:
                QMessageBox.critical(
                    self, "Fehler",
                    f"Ollama-Server nicht erreichbar:\n{msg}\n\n"
                    f"Pruefen Sie ob Ollama laeuft (z.B. 'ollama serve')\n"
                    f"und die URL stimmt: {base_url}"
                )
                return

            available = provider.list_models()
            chosen = model or OllamaProvider.DEFAULT_MODEL
            extra = ""
            if available and chosen not in available:
                # Nicht zwingend ein Fehler - der Modellname kann ein Tag
                # enthalten (z.B. 'llama3.1:latest'). Wir geben einen Hinweis.
                extra = (
                    f"\n\nHinweis: Modell '{chosen}' steht nicht in der Liste "
                    f"der installierten Modelle. Verfuegbar:\n"
                    + "\n".join(f"  - {m}" for m in available[:10])
                    + f"\n\nInstallieren mit: ollama pull {chosen}"
                )

            QMessageBox.information(
                self, "Erfolg",
                f"Verbindung zu Ollama erfolgreich!\n"
                f"Server: {base_url}\n"
                f"Version: {msg}\n"
                f"Gewaehltes Modell: {chosen}"
                + extra
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Fehler",
                f"Verbindungsfehler: {str(e)}"
            )

    def _refresh_models(self):
        """Ruft die verfügbaren Modelle vom API-Provider ab."""
        provider_index = self.provider_combo.currentIndex()
        api_key = self.api_key_input.text().strip()

        if provider_index == 0:
            QMessageBox.information(
                self, "Hinweis",
                "Bitte wählen Sie zuerst einen LLM-Provider aus."
            )
            return

        # Ollama braucht keinen API-Key, alle anderen schon.
        if provider_index != 4 and not api_key:
            QMessageBox.warning(
                self, "Fehler",
                "Bitte geben Sie einen API-Key ein, um die Modelle abzurufen."
            )
            return

        # Aktuell gewähltes Modell merken
        current_model = self.model_combo.currentText().split(" ")[0]

        self.refresh_models_button.setEnabled(False)
        self.refresh_models_button.setText("Lade...")

        try:
            if provider_index == 1:  # Claude
                models = self._fetch_claude_models(api_key)
            elif provider_index == 2:  # OpenAI
                models = self._fetch_openai_models(api_key)
            elif provider_index == 3:  # Poe
                models = self._fetch_poe_models(api_key)
            elif provider_index == 4:  # Ollama (lokal)
                base_url = self.base_url_input.text().strip() or "http://localhost:11434"
                models = self._fetch_ollama_models(base_url)
            else:
                models = []

            if models:
                self.model_combo.clear()
                self.model_combo.addItems(models)

                # Vorheriges Modell wieder auswählen wenn möglich
                for i in range(self.model_combo.count()):
                    if self.model_combo.itemText(i).startswith(current_model):
                        self.model_combo.setCurrentIndex(i)
                        break

                QMessageBox.information(
                    self, "Erfolg",
                    f"{len(models)} Modelle gefunden und aktualisiert."
                )
        except Exception as e:
            QMessageBox.critical(
                self, "Fehler",
                f"Modelle konnten nicht abgerufen werden:\n{str(e)}"
            )
        finally:
            self.refresh_models_button.setEnabled(True)
            self.refresh_models_button.setText("Modelle aktualisieren")

    def _fetch_claude_models(self, api_key: str) -> list[str]:
        """Ruft verfügbare Claude-Modelle von der Anthropic API ab."""
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        models_response = client.models.list(limit=100)
        models = []
        for model in models_response.data:
            model_id = model.id
            if not model_id.startswith("claude"):
                continue
            display = model.display_name if hasattr(model, 'display_name') and model.display_name else model_id
            models.append(f"{model_id} ({display})")

        models.sort(reverse=True)
        return models

    def _fetch_openai_models(self, api_key: str) -> list[str]:
        """Ruft verfügbare OpenAI-Modelle von der API ab."""
        import openai
        client = openai.OpenAI(api_key=api_key)

        models_response = client.models.list()
        models = []
        chat_prefixes = ("gpt-4", "gpt-3.5", "o1", "o3", "o4", "chatgpt")
        for model in models_response.data:
            model_id = model.id
            if not any(model_id.startswith(p) for p in chat_prefixes):
                continue
            models.append(model_id)

        models.sort(reverse=True)
        return models

    def _fetch_poe_models(self, api_key: str) -> list[str]:
        """Ruft verfügbare Modelle von der Poe API ab."""
        import openai
        client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.poe.com/v1",
        )

        models_response = client.models.list()
        models = []
        for model in models_response.data:
            models.append(model.id)

        models.sort()
        return models

    def _fetch_ollama_models(self, base_url: str) -> list[str]:
        """Ruft die lokal installierten Modelle vom Ollama-Server ab."""
        from src.ml.ollama_provider import OllamaProvider
        from src.ml.llm_provider import LLMConfig

        provider = OllamaProvider(LLMConfig(
            api_key="",
            model="",
            base_url=base_url,
        ))
        models = provider.list_models()
        if not models:
            raise RuntimeError(
                f"Keine Modelle gefunden. Laeuft Ollama unter {base_url}?\n"
                "Modelle installieren mit: ollama pull llama3.1"
            )
        models.sort()
        return models

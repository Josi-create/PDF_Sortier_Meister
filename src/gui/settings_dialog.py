"""
Einstellungsdialog für PDF Sortier Meister

Ermöglicht die Konfiguration von LLM-Providern und anderen Einstellungen.

GPL-3.0-or-later - Copyright (c) 2026
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QPushButton,
    QGroupBox, QCheckBox, QMessageBox, QTabWidget,
    QWidget, QSpinBox, QDoubleSpinBox, QRadioButton,
    QButtonGroup, QPlainTextEdit, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal

import sys

from src.gui.original_wegraeumen import AKTIONEN, antwort_speichern, gespeicherte_antwort
from src.utils.config import get_config
from src.utils.pdf_open import OPEN_MODE_CUSTOM, OPEN_MODES, normalize_open_mode
from src.ml.llm_provider import is_cloud_provider
from src.rag.bezug import SCHNELLFRAGEN, schnellfragen_aus_text


class SettingsDialog(QDialog):
    """Dialog für Anwendungseinstellungen."""

    # Signal wenn Einstellungen geändert wurden
    settings_changed = pyqtSignal()

    # Provider-Combo: (provider_id, Anzeigetext) in Anzeige-Reihenfolge.
    # Ollama (lokal, kein Key) zuerst, "Ohne KI" ganz unten (Issue #67 -
    # KI ist ein Hauptfeature, nicht "optional"). Kein hartkodierter Index
    # mehr noetig - siehe _provider_id_at()/_index_for_provider().
    _LLM_PROVIDERS: list[tuple[str, str]] = [
        ("ollama", "Ollama (lokal auf diesem Rechner, empfohlen — kein API-Key noetig)"),
        ("ollama_cloud", "Ollama Cloud (Ollama-Modelle in der Cloud, API-Key)"),
        ("strata", "Strata (lokaler Modell-Server, OpenAI-kompatibel, eigener Key)"),
        ("lmstudio", "LM Studio (lokal auf diesem Rechner, kein API-Key noetig)"),
        ("openrouter", "OpenRouter (viele Modelle, ein API-Key)"),
        ("poe", "Poe.com (viele KI-Modelle, ein API-Key)"),
        ("claude", "Anthropic Claude"),
        ("openai", "OpenAI GPT"),
        ("none", "Ohne KI-Assistent (nur einfache lokale Stichwort-Zuordnung — stark eingeschraenkt)"),
    ]
    _LLM_PROVIDER_INDEX = {pid: i for i, (pid, _) in enumerate(_LLM_PROVIDERS)}
    # Provider-Combo des eigenen Chat-Modells (Issue #166/#167): dieselben
    # Anbieter ohne "Ohne KI" - abgeschaltet wird das eigene Modell ueber die
    # Checkbox davor, dann nimmt der Chat das Modell der Sortierung.
    _CHAT_PROVIDERS: list[tuple[str, str]] = [
        (pid, label) for pid, label in _LLM_PROVIDERS if pid != "none"
    ]
    _CHAT_PROVIDER_INDEX = {pid: i for i, (pid, _) in enumerate(_CHAT_PROVIDERS)}

    def __init__(self, parent=None, example_values_provider=None):
        """Initialisiert den Einstellungsdialog.

        Args:
            example_values_provider: optionaler Callable, der Platzhalter-Werte
                der gerade ausgewaehlten PDF liefert (fuer die Muster-Vorschau
                "Mit aktueller PDF"); None = Button ausgeblendet.
        """
        super().__init__(parent)
        self.config = get_config()
        self._example_values_provider = example_values_provider
        self._ki_preview_name = ""
        self._setup_ui()
        self._load_settings()

    def show_tab(self, title: str) -> bool:
        """Schaltet auf den Tab mit diesem Titel (z.B. "Dateinamen")."""
        for idx in range(self.tab_widget.count()):
            if self.tab_widget.tabText(idx) == title:
                self.tab_widget.setCurrentIndex(idx)
                return True
        return False

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

        # Persönliche Daten Tab (vor "Dateinamen": dort werden die Initialen
        # definiert, die das Dateinamen-Muster benutzt)
        personal_tab = self._create_personal_tab()
        tab_widget.addTab(personal_tab, "Persönliche Daten")

        # Dateinamen Tab
        filename_tab = self._create_filename_pattern_tab()
        tab_widget.addTab(filename_tab, "Dateinamen")

        # Name/Initialen wirken auf die Muster-Vorschau
        self.owner_name_input.textChanged.connect(self._on_owner_name_changed)
        self.owner_initials_input.textChanged.connect(self._update_filename_previews)

        # Allgemeine Einstellungen Tab
        general_tab = self._create_general_tab()
        tab_widget.addTab(general_tab, "Allgemein")

        # Dokumentensuche (Integration von PDFsuche, Phase 3)
        search_tab = self._create_search_tab()
        tab_widget.addTab(search_tab, "Suche")

        layout.addWidget(tab_widget)
        self.tab_widget = tab_widget

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.test_button = QPushButton("Verbindung testen")
        self.test_button.clicked.connect(self._test_connection)
        button_layout.addWidget(self.test_button)
        # "Verbindung testen" gehoert zum KI-Tab - auf den anderen ausblenden
        tab_widget.currentChanged.connect(
            lambda index: self.test_button.setVisible(index == 0)
        )
        self.test_button.setVisible(tab_widget.currentIndex() == 0)

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

        # API-Keys pro Provider (Puffer, bis "Speichern" gedrueckt wird)
        self._api_keys: dict[str, str] = {}
        self._key_provider = ""  # Provider, dessen Key gerade im Feld steht
        # Server-URLs pro lokalem Provider (Ollama, Strata), gleiches Prinzip
        self._base_urls: dict[str, str] = {}
        self._url_provider = ""

        self.provider_combo = QComboBox()
        self.provider_combo.addItems([label for _, label in self._LLM_PROVIDERS])
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_layout.addRow("Provider:", self.provider_combo)

        layout.addWidget(provider_group)

        # API-Konfiguration
        api_group = QGroupBox("API-Konfiguration")
        api_layout = QFormLayout(api_group)

        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("sk-... oder anthropic-...")
        self.api_key_label = QLabel("API-Key:")
        api_layout.addRow(self.api_key_label, self.api_key_input)

        # Show/Hide Button für API-Key
        key_button_layout = QHBoxLayout()
        self.show_key_button = QPushButton("Anzeigen")
        self.show_key_button.setCheckable(True)
        self.show_key_button.toggled.connect(self._toggle_key_visibility)
        key_button_layout.addWidget(self.show_key_button)
        key_button_layout.addStretch()
        api_layout.addRow("", key_button_layout)

        # Server-URL (nur fuer lokale Server: Ollama, Strata)
        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText("http://localhost:11434")
        self.base_url_input.setToolTip(
            "Nur fuer lokale Server (Ollama, Strata, LM Studio): URL des Servers.\n"
            "Leer = Standard-URL (siehe Platzhalter)."
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

        # Erkennungsstatus (nur bei LM Studio sichtbar)
        self.lmstudio_status_label = QLabel("")
        self.lmstudio_status_label.setWordWrap(True)
        self.lmstudio_status_label.setVisible(False)
        api_layout.addRow("", self.lmstudio_status_label)

        layout.addWidget(api_group)

        # Datenschutz: Einwilligung fuer Cloud-Provider
        consent_group = QGroupBox("Datenschutz")
        consent_layout = QVBoxLayout(consent_group)
        self.cloud_consent_check = QCheckBox(
            "Ich willige ein, dass Textauszüge meiner Dokumente an den\n"
            "gewählten Cloud-Anbieter übertragen werden."
        )
        self.cloud_consent_check.toggled.connect(self._update_consent_hint)
        consent_layout.addWidget(self.cloud_consent_check)
        self.consent_hint_label = QLabel("")
        self.consent_hint_label.setWordWrap(True)
        consent_layout.addWidget(self.consent_hint_label)
        layout.addWidget(consent_group)

        # Erweiterte Einstellungen
        advanced_group = QGroupBox("Erweiterte Einstellungen")
        advanced_layout = QFormLayout(advanced_group)

        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(100, 8000)
        self.max_tokens_spin.setValue(2000)
        self.max_tokens_spin.setToolTip(
            "Obergrenze fuer die Antwortlaenge. Reasoning-Modelle (z.B. GLM, "
            "DeepSeek-R1) verbrauchen davon zuerst ihr 'Nachdenken' - bei zu "
            "kleinem Wert kommt eine leere Antwort zurueck."
        )
        self.max_tokens_spin.setSuffix(" Tokens")
        advanced_layout.addRow("Max. Tokens:", self.max_tokens_spin)

        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 1.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setValue(0.3)
        advanced_layout.addRow("Temperatur:", self.temperature_spin)

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

        # Chat (Reiter „Chat“): eigenes Modell und Werkzeuge (Issue #166/#167)
        layout.addWidget(self._create_chat_group())

        layout.addStretch()

        # Mit der Chat-Gruppe wird der Reiter hoch; auf kleinen Bildschirmen
        # scrollt er, statt den Dialog zu sprengen (wie der Reiter „Suche“).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(tab)
        # Der Dialog soll sich weiter nach dem Inhalt richten (sonst liefert der
        # Scrollbereich einen festen, kleinen sizeHint und der Reiter bekommt
        # auf grossen Bildschirmen unnoetig Scrollbalken, Review-Befund)
        from PyQt6.QtWidgets import QAbstractScrollArea
        scroll.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        return scroll

    def _create_chat_group(self) -> QGroupBox:
        """Gruppe „Chat“ im KI-Reiter: eigenes Modell und Werkzeuge (Issue #166/#167).

        Das eigene Chat-Modell wird wie das Sortier-Modell eingestellt
        (Provider, Modell, API-Key, Server-URL, Verbindungstest), landet aber im
        ``"chat"``-Block (``Config.update_chat_config``). Leerer Key bzw. leere
        URL heisst: Wert des gleichen Anbieters aus der API-Konfiguration oben
        (``Config.get_chat_llm_config``). Die Cloud-Einwilligung gilt global.
        """
        group = QGroupBox("Chat (Reiter „Chat“)")
        layout = QVBoxLayout(group)

        # API-Key/Server-URL je Chat-Provider (Puffer bis "Speichern", wie oben)
        self._chat_api_keys: dict[str, str] = {}
        self._chat_key_provider = ""
        self._chat_base_urls: dict[str, str] = {}
        self._chat_url_provider = ""

        self.chat_own_model_check = QCheckBox("Eigenes Modell für den Chat verwenden")
        self.chat_own_model_check.setToolTip(
            "Aus: Der Chat nutzt das Modell der Sortierung (oben).\n"
            "An: Der Chat nutzt den hier gewählten Anbieter und das Modell - z.B. ein\n"
            "großes Modell mit Werkzeugunterstützung, während die Sortierung ein\n"
            "kleines lokales Modell behält."
        )
        self.chat_own_model_check.toggled.connect(self._on_chat_own_model_toggled)
        layout.addWidget(self.chat_own_model_check)

        form = QFormLayout()

        self.chat_provider_combo = QComboBox()
        self.chat_provider_combo.addItems([label for _, label in self._CHAT_PROVIDERS])
        self.chat_provider_combo.currentIndexChanged.connect(self._on_chat_provider_changed)
        form.addRow("Provider:", self.chat_provider_combo)

        model_row = QHBoxLayout()
        self.chat_model_combo = QComboBox()
        self.chat_model_combo.setEditable(True)
        model_row.addWidget(self.chat_model_combo, 1)
        self.chat_refresh_models_button = QPushButton("Modelle aktualisieren")
        self.chat_refresh_models_button.setToolTip(
            "Ruft die aktuell verfügbaren Modelle vom gewählten Anbieter ab."
        )
        self.chat_refresh_models_button.clicked.connect(self._refresh_chat_models)
        model_row.addWidget(self.chat_refresh_models_button)
        form.addRow("Modell:", model_row)

        self.chat_api_key_input = QLineEdit()
        self.chat_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.chat_api_key_label = QLabel("API-Key:")
        form.addRow(self.chat_api_key_label, self.chat_api_key_input)

        self.chat_base_url_input = QLineEdit()
        self.chat_base_url_input.setToolTip(
            "Nur für lokale Server (Ollama, Strata): URL des Servers.\n"
            "Leer = URL des gleichen Anbieters von oben bzw. Standard-URL."
        )
        form.addRow("Server-URL:", self.chat_base_url_input)

        test_row = QHBoxLayout()
        self.chat_test_button = QPushButton("Verbindung testen")
        self.chat_test_button.clicked.connect(self._test_chat_connection)
        test_row.addWidget(self.chat_test_button)
        test_row.addStretch()
        form.addRow("", test_row)

        layout.addLayout(form)

        self.chat_consent_hint_label = QLabel("")
        self.chat_consent_hint_label.setWordWrap(True)
        layout.addWidget(self.chat_consent_hint_label)
        # Einwilligung oben geaendert -> Hinweis hier nachziehen
        self.cloud_consent_check.toggled.connect(self._update_chat_consent_hint)

        self.chat_tools_check = QCheckBox(
            "Werkzeuge im Chat verwenden (Suche, Lesen, Ordnervorschlag, Korrespondent)"
        )
        self.chat_tools_check.setToolTip(
            "Das Modell darf selbst in der Dokumentensuche suchen, Dokumente lesen,\n"
            "Ordner vorschlagen und Korrespondenten nachschlagen - nur bei Anbietern\n"
            "und Modellen mit Werkzeugunterstützung, sonst antwortet es wie bisher."
        )
        layout.addWidget(self.chat_tools_check)

        steps_row = QHBoxLayout()
        steps_row.addWidget(QLabel("Höchstens"))
        self.chat_steps_spin = QSpinBox()
        self.chat_steps_spin.setRange(1, 12)
        self.chat_steps_spin.setValue(8)
        self.chat_steps_spin.setToolTip(
            "Obergrenze für die Modellaufrufe mit Werkzeugen je Frage.\n"
            "Mehr Schritte = gründlicher, aber langsamer (und bei Cloud-Anbietern teurer)."
        )
        steps_row.addWidget(self.chat_steps_spin)
        steps_row.addWidget(QLabel("Werkzeugschritte je Frage"))
        steps_row.addStretch()
        layout.addLayout(steps_row)

        self.chat_sql_check = QCheckBox(
            "SQL-Abfragen auf der Suchdatenbank erlauben (nur lesend)"
        )
        self.chat_sql_check.setToolTip(
            "Das Modell darf lesende SQL-Abfragen auf der Suchdatenbank stellen\n"
            "(z.B. Zählungen, Zeiträume). Kleine Modelle formulieren oft falsches SQL."
        )
        layout.addWidget(self.chat_sql_check)

        # Schrittzahl und SQL betreffen nur die Werkzeug-Schleife
        self.chat_tools_check.toggled.connect(self.chat_steps_spin.setEnabled)
        self.chat_tools_check.toggled.connect(self.chat_sql_check.setEnabled)

        # Eigene Schnellfragen (Phase 3, Issue #166): eine je Zeile
        fragen_kopf = QHBoxLayout()
        fragen_kopf.addWidget(QLabel("Schnellfragen im Chat (eine je Zeile):"))
        fragen_kopf.addStretch(1)
        self.chat_schnellfragen_standard_btn = QPushButton("Standard wiederherstellen")
        self.chat_schnellfragen_standard_btn.clicked.connect(
            lambda: self.chat_schnellfragen_edit.setPlainText("\n".join(SCHNELLFRAGEN))
        )
        fragen_kopf.addWidget(self.chat_schnellfragen_standard_btn)
        layout.addLayout(fragen_kopf)
        self.chat_schnellfragen_edit = QPlainTextEdit()
        self.chat_schnellfragen_edit.setPlaceholderText("\n".join(SCHNELLFRAGEN))
        self.chat_schnellfragen_edit.setToolTip(
            "Knöpfe über dem Eingabefeld des Chats, wenn eine PDF der Bezug ist.\n"
            "Leer = Standardfragen. Höchstens 12 Fragen."
        )
        self.chat_schnellfragen_edit.setFixedHeight(96)
        layout.addWidget(self.chat_schnellfragen_edit)

        self._on_chat_provider_changed(self.chat_provider_combo.currentIndex())
        self._update_chat_fields_enabled()
        return group

    # Beispiel-Zielordner fuer die Vorschau "Beim Verschieben"
    _PREVIEW_FOLDER = "069-03-05 Arbeitsamt"
    _PREVIEW_RELATIVE_PATH = "Behoerden/069-03-05 Arbeitsamt"
    _PREVIEW_DEFAULT_PATTERN = "{datum}_{kategorie}_{betreff}"

    def _create_filename_pattern_tab(self) -> QWidget:
        """Tab "Dateinamen": KI-Muster mit Live-Vorschau + Verhalten beim Verschieben.

        Eine Platzhalter-Syntax ({datum}, {kontakt} ...) fuer KI-Muster und
        Verschiebe-Vorlage; die Bedeutungen kommen aus
        src.core.filename_placeholders und landen genauso im KI-Prompt.
        """
        from PyQt6.QtWidgets import QComboBox, QGridLayout, QRadioButton, QSizePolicy, QToolButton
        from src.core.filename_placeholders import PLACEHOLDERS, legend_html
        from src.core.folder_naming import DEFAULT_TEMPLATE

        tab = QWidget()
        layout = QVBoxLayout(tab)

        intro = QLabel("Nach diesem Muster schlägt die KI Dateinamen vor.")
        intro.setStyleSheet("color: #555; padding: 2px 0 6px 0;")
        layout.addWidget(intro)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # Vorlage (Combo) fuellt das Muster-Feld; Tippen schaltet auf "Eigenes"
        self.pattern_preset_combo = QComboBox()
        self._pattern_presets: list[tuple[str, str | None]] = []
        self._rebuild_pattern_presets()
        self.pattern_preset_combo.activated.connect(self._on_pattern_preset_activated)
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        preset_row.addWidget(self.pattern_preset_combo, 1)
        # Eigenes Muster unter einem Namen merken -> erscheint in der Vorlagen-
        # Liste und als Muster-Vorschlag im Detail-Panel
        self.pattern_save_btn = QPushButton("Muster speichern…")
        self.pattern_save_btn.setToolTip(
            "Das Muster im Feld unter einem Namen in die Vorlagen-Liste aufnehmen."
        )
        self.pattern_save_btn.clicked.connect(self._save_custom_pattern)
        preset_row.addWidget(self.pattern_save_btn)
        self.pattern_delete_btn = QPushButton("Löschen")
        self.pattern_delete_btn.setToolTip("Das gewählte gespeicherte Muster aus der Liste entfernen.")
        self.pattern_delete_btn.clicked.connect(self._delete_custom_pattern)
        preset_row.addWidget(self.pattern_delete_btn)
        form.addRow("Vorlage:", preset_row)

        self.pattern_input = QLineEdit()
        self.pattern_input.setPlaceholderText("leer = KI entscheidet selbst")
        self.pattern_input.setStyleSheet("font-family: monospace;")
        self.pattern_input.setToolTip(
            "Platzhalter in geschweiften Klammern, dazwischen beliebige Trennzeichen.\n"
            "Klick auf einen Platzhalter unten fügt ihn an der Cursorposition ein."
        )
        self.pattern_input.textChanged.connect(self._on_pattern_text_changed)
        form.addRow("Muster:", self.pattern_input)

        # Platzhalter-Chips: Klick fuegt an der Cursorposition ein
        chips_widget = QWidget()
        chips = QGridLayout(chips_widget)
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setHorizontalSpacing(4)
        chips.setVerticalSpacing(4)
        self.pattern_chip_buttons = []
        per_row = 5
        for i, ph in enumerate(PLACEHOLDERS):
            btn = QPushButton("{" + ph.key + "}")
            btn.setToolTip(f"{ph.label}\nBeispiel: {ph.example}")
            btn.setStyleSheet(
                "QPushButton { padding: 1px 6px; font-family: monospace; font-size: 11px; }"
            )
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _checked=False, key=ph.key: self._insert_placeholder(key))
            chips.addWidget(btn, i // per_row, i % per_row)
            self.pattern_chip_buttons.append(btn)
        self.pattern_legend_toggle = QToolButton()
        self.pattern_legend_toggle.setText("Alle Platzhalter")
        self.pattern_legend_toggle.setCheckable(True)
        self.pattern_legend_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.pattern_legend_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.pattern_legend_toggle.setAutoRaise(True)
        self.pattern_legend_toggle.toggled.connect(self._toggle_pattern_legend)
        # Eigene Spalte rechts neben den Chips - nie in der Zelle eines Chips
        # (bei vollen Zeilen lag der Knopf sonst ueber dem letzten Chip)
        last_row = (len(PLACEHOLDERS) - 1) // per_row
        chips.addWidget(self.pattern_legend_toggle, last_row, per_row,
                        Qt.AlignmentFlag.AlignRight)
        chips.setColumnStretch(per_row, 1)

        # Trennzeichen + Zuruecknehmen: Muster ganz ohne Tastatur zusammenklicken
        sep_row = QHBoxLayout()
        sep_row.setSpacing(4)
        self.pattern_sep_buttons = []
        for label, sep, tip in (
            ("Leerzeichen", " ", "Leerzeichen einfuegen"),
            ("_", "_", "Unterstrich einfuegen"),
            ("-", "-", "Bindestrich einfuegen"),
        ):
            btn = QPushButton(label)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                "QPushButton { padding: 1px 8px; font-family: monospace; font-size: 11px; }"
            )
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _checked=False, s=sep: self._insert_separator(s))
            sep_row.addWidget(btn)
            self.pattern_sep_buttons.append(btn)
        sep_row.addStretch(1)
        self.pattern_undo_btn = QPushButton("⌫ Zurücknehmen")
        self.pattern_undo_btn.setToolTip(
            "Letzten Baustein vor dem Cursor entfernen (ganzer Platzhalter oder ein Trennzeichen)"
        )
        self.pattern_undo_btn.setStyleSheet("QPushButton { padding: 1px 8px; font-size: 11px; }")
        self.pattern_undo_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.pattern_undo_btn.clicked.connect(self._remove_last_pattern_token)
        sep_row.addWidget(self.pattern_undo_btn)
        chips.addLayout(sep_row, last_row + 1, 0, 1, per_row + 1)
        form.addRow("", chips_widget)

        self.pattern_legend_label = QLabel(legend_html())
        self.pattern_legend_label.setTextFormat(Qt.TextFormat.RichText)
        self.pattern_legend_label.setWordWrap(True)
        self.pattern_legend_label.setStyleSheet("font-size: 11px;")
        self.pattern_legend_label.hide()
        form.addRow("", self.pattern_legend_label)

        self.pattern_warning_label = QLabel()
        self.pattern_warning_label.setStyleSheet("color: #d32f2f; font-size: 11px;")
        self.pattern_warning_label.hide()
        form.addRow("", self.pattern_warning_label)

        # Live-Vorschau mit Beispieldokument (+ optional echte PDF)
        preview_widget = QWidget()
        preview_row = QHBoxLayout(preview_widget)
        preview_row.setContentsMargins(0, 0, 0, 0)
        # Read-only QLineEdit statt QLabel: lange Namen werden gescrollt statt
        # (wie bei QLabel+wordWrap im QFormLayout) vertikal abgeschnitten.
        self.pattern_preview_label = QLineEdit()
        self.pattern_preview_label.setReadOnly(True)
        self.pattern_preview_label.setStyleSheet(
            "font-family: monospace; padding: 4px; background-color: #e8f5e9; "
            "border: 1px solid #a5d6a7; border-radius: 3px; color: #1b5e20;"
        )
        preview_row.addWidget(self.pattern_preview_label, 1)
        self.pattern_try_button = QPushButton("Mit aktueller PDF")
        self.pattern_try_button.setToolTip(
            "Vorschau mit den KI-Metadaten der gerade ausgewählten PDF"
        )
        self.pattern_try_button.clicked.connect(self._preview_with_current_pdf)
        self.pattern_try_button.setVisible(self._example_values_provider is not None)
        preview_row.addWidget(self.pattern_try_button)
        form.addRow("Vorschau:", preview_widget)

        layout.addLayout(form)

        # ---- Beim Verschieben in einen Ordner (Issue #42) ----
        move_group = QGroupBox("Beim Verschieben in einen Ordner")
        move_layout = QVBoxLayout(move_group)

        self.folder_naming_keep_radio = QRadioButton("Dateinamen beibehalten")
        self.folder_naming_prefix_radio = QRadioButton(
            "Ordnernummer aus dem Zielordner voranstellen"
        )
        self.folder_naming_keep_radio.setChecked(True)
        move_layout.addWidget(self.folder_naming_keep_radio)
        move_layout.addWidget(self.folder_naming_prefix_radio)

        move_form = QFormLayout()
        move_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.folder_naming_template_input = QLineEdit()
        self.folder_naming_template_input.setPlaceholderText(DEFAULT_TEMPLATE)
        self.folder_naming_template_input.setStyleSheet("font-family: monospace;")
        self.folder_naming_template_input.setToolTip(
            "Platzhalter: {initialen}, {ordnernummern} (Nummernkette aus dem "
            "Zielordner-Namen, z.B. 069-03-05), {ordnerpfad} (Ordnernamen mit - "
            "verbunden), {datum} (JJJJMMTT), {datum_iso} (JJJJ-MM-TT), "
            "{text} (bisheriger Name ohne Datum)"
        )
        move_form.addRow("Vorlage:", self.folder_naming_template_input)

        self.folder_naming_preview_label = QLineEdit()
        self.folder_naming_preview_label.setReadOnly(True)
        self.folder_naming_preview_label.setStyleSheet(
            "font-family: monospace; padding: 4px; background-color: #f5f5f5; "
            "border: 1px solid #ddd; border-radius: 3px; color: #444;"
        )
        move_form.addRow("Ergebnis:", self.folder_naming_preview_label)
        move_layout.addLayout(move_form)

        move_hint = QLabel(
            f"Beispiel für den Zielordner „{self._PREVIEW_FOLDER}“. "
            "Ihre Initialen stellen Sie unter „Persönliche Daten“ ein."
        )
        move_hint.setWordWrap(True)
        move_hint.setStyleSheet("color: #777; font-size: 11px;")
        move_layout.addWidget(move_hint)

        layout.addWidget(move_group)
        layout.addStretch()

        self.folder_naming_prefix_radio.toggled.connect(self._on_folder_naming_mode_changed)
        self.folder_naming_template_input.textChanged.connect(self._update_filename_previews)
        self._on_folder_naming_mode_changed(False)
        self._update_filename_previews()
        return tab

    # -- Handler Dateinamen-Tab ------------------------------------------ #

    def _on_pattern_preset_activated(self, index: int):
        """Vorlage gewaehlt -> Muster-Feld befuellen ("Eigenes": Feld behalten)."""
        _name, pattern = self._pattern_presets[index]
        if pattern is None:
            self.pattern_input.setFocus()
            return
        self.pattern_input.setText(pattern)

    # -- Gespeicherte Muster ------------------------------------------------ #

    def _custom_patterns(self) -> list[tuple[str, str]]:
        from src.core.filename_placeholders import CUSTOM_PATTERNS_KEY, load_custom_patterns
        return load_custom_patterns(self.config.get(CUSTOM_PATTERNS_KEY, []))

    def _store_custom_patterns(self, patterns: list[tuple[str, str]]):
        from src.core.filename_placeholders import CUSTOM_PATTERNS_KEY
        self.config.set(CUSTOM_PATTERNS_KEY, [{"name": n, "pattern": p} for n, p in patterns])

    def _rebuild_pattern_presets(self):
        """Combo neu befuellen: eingebaute Vorlagen, gespeicherte Muster, "Eigenes"."""
        from src.core.filename_placeholders import all_presets
        self._pattern_presets = all_presets(self._custom_patterns())
        self.pattern_preset_combo.blockSignals(True)
        self.pattern_preset_combo.clear()
        for name, _pattern in self._pattern_presets:
            self.pattern_preset_combo.addItem(name)
        self.pattern_preset_combo.blockSignals(False)

    def _selected_custom_pattern(self) -> tuple[str, str] | None:
        """(Name, Muster), wenn die Combo gerade ein gespeichertes Muster zeigt."""
        from src.core.filename_placeholders import builtin_pattern_names
        idx = self.pattern_preset_combo.currentIndex()
        if not 0 <= idx < len(self._pattern_presets):
            return None
        name, pattern = self._pattern_presets[idx]
        if pattern is None or name in builtin_pattern_names():
            return None
        return name, pattern

    def _update_custom_pattern_buttons(self):
        from src.core.filename_placeholders import PRESETS
        text = self.pattern_input.text().strip()
        is_builtin = any(p == text for _n, p in PRESETS if p)
        self.pattern_save_btn.setEnabled(bool(text) and not is_builtin)
        self.pattern_delete_btn.setEnabled(self._selected_custom_pattern() is not None)

    def _save_custom_pattern(self):
        """"Muster speichern…": Namen erfragen, in die Config schreiben, Combo neu."""
        from PyQt6.QtWidgets import QInputDialog
        pattern = self.pattern_input.text().strip()
        if not pattern:
            return
        existing = self._custom_patterns()
        default_name = next((n for n, p in existing if p == pattern), "")
        name, ok = QInputDialog.getText(
            self, "Muster speichern", "Name für dieses Muster:", text=default_name
        )
        name = (name or "").strip()
        if not ok or not name:
            return
        from src.core.filename_placeholders import builtin_pattern_names
        if name in builtin_pattern_names():
            QMessageBox.warning(self, "Muster speichern",
                                f"„{name}“ ist eine eingebaute Vorlage - bitte einen anderen Namen wählen.")
            return
        # Gleicher Name oder gleiches Muster -> Eintrag ersetzen
        patterns = [(n, p) for n, p in existing if n.lower() != name.lower() and p != pattern]
        patterns.append((name, pattern))
        self._store_custom_patterns(patterns)
        self._rebuild_pattern_presets()
        self._sync_pattern_combo(pattern)

    def _delete_custom_pattern(self):
        selected = self._selected_custom_pattern()
        if selected is None:
            return
        name, _pattern = selected
        self._store_custom_patterns([(n, p) for n, p in self._custom_patterns() if n != name])
        self._rebuild_pattern_presets()
        self._sync_pattern_combo(self.pattern_input.text())

    def _on_pattern_text_changed(self, text: str):
        self._sync_pattern_combo(text)
        self._update_filename_previews()

    def _sync_pattern_combo(self, text: str):
        """Combo auf die passende Vorlage stellen, sonst auf "Eigenes"."""
        text = text.strip()
        index = len(self._pattern_presets) - 1
        for i, (_name, pattern) in enumerate(self._pattern_presets):
            if pattern is not None and pattern == text:
                index = i
                break
        self.pattern_preset_combo.blockSignals(True)
        self.pattern_preset_combo.setCurrentIndex(index)
        self.pattern_preset_combo.blockSignals(False)
        self._update_custom_pattern_buttons()

    _PATTERN_SEPARATORS = " _-"

    def _insert_placeholder(self, key: str):
        """Chip geklickt -> Platzhalter an der Cursorposition einfuegen.

        Steht davor bereits etwas, aber kein Trennzeichen, kommt automatisch
        ein "_" dazwischen - so laesst sich ein Muster nur mit Chips
        zusammenklicken. Wer "-" oder Leerzeichen will, klickt das vorher.
        """
        before = self.pattern_input.text()[: self.pattern_input.cursorPosition()]
        sep = "_" if before and before[-1] not in self._PATTERN_SEPARATORS else ""
        self.pattern_input.insert(sep + "{" + key + "}")
        self.pattern_input.setFocus()

    def _insert_separator(self, sep: str):
        """Trennzeichen-Knopf -> an der Cursorposition einfuegen."""
        self.pattern_input.insert(sep)
        self.pattern_input.setFocus()

    def _remove_last_pattern_token(self):
        """Baustein vor dem Cursor entfernen: ganzer {platzhalter} oder ein Zeichen.

        Ein Chip-Klick = Trennzeichen + Platzhalter, ein Klick auf
        "Zuruecknehmen" macht genau das wieder rueckgaengig.
        """
        text = self.pattern_input.text()
        pos = self.pattern_input.cursorPosition()
        before, after = text[:pos], text[pos:]
        if not before:
            return
        if before.endswith("}") and "{" in before:
            before = before[:before.rfind("{")]
            # das automatisch eingefuegte Trennzeichen gehoert zum Baustein
            if before and before[-1] in self._PATTERN_SEPARATORS:
                before = before[:-1]
        else:
            before = before[:-1]
        self.pattern_input.setText(before + after)
        self.pattern_input.setCursorPosition(len(before))
        self.pattern_input.setFocus()

    def _toggle_pattern_legend(self, checked: bool):
        self.pattern_legend_label.setVisible(checked)
        self.pattern_legend_toggle.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )

    def _on_owner_name_changed(self, text: str):
        """Abgeleitete Initialen als Platzhalter zeigen + Vorschau aktualisieren."""
        from src.ml.llm_provider import derive_initials
        derived = derive_initials(text)
        self.owner_initials_input.setPlaceholderText(
            f"{derived} (aus dem Namen)" if derived else "z.B. JW"
        )
        self._update_filename_previews()

    def _current_initials(self) -> str:
        """Initialen aus dem Feld, sonst aus dem Namen abgeleitet."""
        initials_input = getattr(self, "owner_initials_input", None)
        name_input = getattr(self, "owner_name_input", None)
        if initials_input is not None and initials_input.text().strip():
            return initials_input.text().strip().upper()
        if name_input is not None:
            from src.ml.llm_provider import derive_initials
            return derive_initials(name_input.text())
        return ""

    def _update_filename_previews(self, *_):
        """Live-Vorschau fuer KI-Muster und Verschiebe-Vorlage."""
        from src.core.filename_placeholders import render_example
        from src.utils.filename_sanitizer import find_problem_chars

        pattern = self.pattern_input.text().strip()

        problems = [c for c in find_problem_chars(pattern) if not c.isspace()]
        if problems:
            self.pattern_warning_label.setText(
                "Im Dateinamen nicht erlaubt: " + " ".join(problems) + " – wird durch _ ersetzt"
            )
            self.pattern_warning_label.show()
        else:
            self.pattern_warning_label.hide()

        initials = self._current_initials()
        values = {"initialen": initials} if initials else None
        if pattern:
            self._ki_preview_name = render_example(pattern, values)
            self.pattern_preview_label.setText(self._ki_preview_name or "(leer)")
        else:
            self._ki_preview_name = render_example(self._PREVIEW_DEFAULT_PATTERN, values)
            self.pattern_preview_label.setText(
                f"KI entscheidet selbst, z.B. {self._ki_preview_name}"
            )
        self._update_folder_naming_preview()

    def _update_folder_naming_preview(self):
        from datetime import date
        from pathlib import PurePath
        from src.core.folder_naming import DEFAULT_TEMPLATE, build_folder_based_name

        base = self._ki_preview_name or "Dokument.pdf"
        if not self.folder_naming_prefix_radio.isChecked():
            self.folder_naming_preview_label.setText(base)
            return
        template = self.folder_naming_template_input.text().strip() or DEFAULT_TEMPLATE
        name = build_folder_based_name(
            base,
            PurePath(self._PREVIEW_FOLDER),
            self._PREVIEW_RELATIVE_PATH,
            template=template,
            initials=self._current_initials(),
            fallback_date=date(2024, 3, 12),
        )
        self.folder_naming_preview_label.setText(name)

    def _on_folder_naming_mode_changed(self, _checked: bool):
        enabled = self.folder_naming_prefix_radio.isChecked()
        self.folder_naming_template_input.setEnabled(enabled)
        self._update_folder_naming_preview()

    def _preview_with_current_pdf(self):
        """Vorschau mit den KI-Metadaten der aktuell ausgewaehlten PDF."""
        from src.core.filename_placeholders import render_example

        values = None
        if self._example_values_provider is not None:
            try:
                values = self._example_values_provider()
            except Exception:
                values = None
        if not values:
            self.pattern_preview_label.setText(
                "Keine PDF ausgewählt oder noch keine KI-Metadaten vorhanden."
            )
            return
        pattern = self.pattern_input.text().strip() or self._PREVIEW_DEFAULT_PATTERN
        initials = self._current_initials()
        if initials:
            values = {**values, "initialen": initials}
        self.pattern_preview_label.setText(render_example(pattern, values) or "(leer)")

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

        self.owner_initials_input = QLineEdit()
        self.owner_initials_input.setPlaceholderText("z.B. JW")
        self.owner_initials_input.setMaximumWidth(80)
        self.owner_initials_input.setToolTip(
            "2-3 Großbuchstaben für den Platzhalter {initialen} in Dateinamen.\n"
            "Leer = aus dem Namen abgeleitet."
        )
        user_layout.addRow("Initialen:", self.owner_initials_input)

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

        tile_hint = QLabel(
            "Die Größe der Kacheln (Klein / Mittel / Groß) stellen Sie direkt "
            "über dem Scan-Bereich unter „Ansicht“ ein."
        )
        tile_hint.setStyleSheet("color: gray;")
        tile_hint.setWordWrap(True)
        display_layout.addRow(tile_hint)

        self.max_suggestions_spin = QSpinBox()
        self.max_suggestions_spin.setRange(1, 10)
        self.max_suggestions_spin.setValue(5)
        display_layout.addRow("Max. Vorschläge:", self.max_suggestions_spin)

        # Issue #116: auch Ordner vorschlagen, die es noch nicht gibt
        self.suggest_new_folders_check = QCheckBox("Neue Ordner vorschlagen")
        self.suggest_new_folders_check.setChecked(True)
        self.suggest_new_folders_check.setToolTip(
            "Fehlt der Ordner für das Jahr des Dokuments (z. B. „Steuer 2027/Medikamente“)\n"
            "oder nennt die KI einen passenden neuen Unterordner, erscheint er als\n"
            "Vorschlag „➕ neu:“. Angelegt wird er erst nach Ihrer Rückfrage."
        )
        display_layout.addRow(self.suggest_new_folders_check)

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

        # PDF oeffnen (Issues #74/#76)
        open_group = QGroupBox("PDF öffnen (Doppelklick auf ein Thumbnail)")
        open_layout = QFormLayout(open_group)

        self.pdf_open_mode_combo = QComboBox()
        for mode_id, label in OPEN_MODES:
            self.pdf_open_mode_combo.addItem(label, mode_id)
        self.pdf_open_mode_combo.setToolTip(
            "Integrierte Vorschau: eigenes Fenster in der App, öffnet sofort.\n"
            "Standardprogramm: was Windows/macOS für PDFs eingestellt hat\n"
            "(oft der Browser).\n"
            "Eigenes Programm: z. B. PDF-XChange Editor oder Acrobat."
        )
        self.pdf_open_mode_combo.currentIndexChanged.connect(self._update_pdf_open_command_enabled)
        open_layout.addRow("Öffnen mit:", self.pdf_open_mode_combo)

        command_row = QHBoxLayout()
        self.pdf_open_command_input = QLineEdit()
        self.pdf_open_command_input.setPlaceholderText(
            "Pfad zum Programm, z. B. C:\\Program Files\\Tracker Software\\PDF Editor\\PDFXEdit.exe"
        )
        command_row.addWidget(self.pdf_open_command_input, 1)
        self.pdf_open_command_browse = QPushButton("Durchsuchen…")
        self.pdf_open_command_browse.clicked.connect(self._browse_pdf_open_command)
        command_row.addWidget(self.pdf_open_command_browse)
        open_layout.addRow("Programm:", command_row)

        open_hint = QLabel(
            "Die kleine Vorschau unten im mittleren Bereich ist davon unabhängig "
            "und immer aktiv."
        )
        open_hint.setStyleSheet("color: gray;")
        open_hint.setWordWrap(True)
        open_layout.addRow(open_hint)

        layout.addWidget(open_group)

        # Original nach Umwandeln/Trennen (Issues #184, #187)
        original_group = QGroupBox("Original nach dem Umwandeln und Trennen")
        original_layout = QFormLayout(original_group)
        self.original_combos = {}
        for aktion, label in AKTIONEN.items():
            combo = QComboBox()
            combo.addItem("Jedes Mal fragen", None)
            combo.addItem("In den Papierkorb verschieben", True)
            combo.addItem("Behalten", False)
            combo.setToolTip("Mit Strg+Z holst du ein weggeräumtes Original zurück.")
            self.original_combos[aktion] = combo
            original_layout.addRow(f"{label}:", combo)
        layout.addWidget(original_group)

        # Update-Pruefung (Issue #73)
        update_group = QGroupBox("Updates")
        update_layout = QVBoxLayout(update_group)

        self.update_check_checkbox = QCheckBox("Beim Programmstart auf neue Versionen prüfen")
        self.update_check_checkbox.setToolTip(
            "Fragt kurz nach dem Start die Versionsnummer des neuesten Releases\n"
            "auf GitHub ab. Es werden keine Daten über Sie oder Ihre Dokumente\n"
            "gesendet. Manuell jederzeit über Hilfe > Nach Updates suchen."
        )
        update_layout.addWidget(self.update_check_checkbox)

        update_info = QLabel(
            "Es wird nur die Versionsnummer des neuesten Releases abgerufen; "
            "heruntergeladen und installiert wird nichts automatisch."
        )
        update_info.setStyleSheet("color: gray;")
        update_info.setWordWrap(True)
        update_layout.addWidget(update_info)

        layout.addWidget(update_group)

        # Backup-Erinnerung (Issue #14)
        backup_group = QGroupBox("Backup-Erinnerung")
        backup_layout = QHBoxLayout(backup_group)
        backup_layout.addWidget(QLabel("Alle"))
        self.backup_days_spin = QSpinBox()
        self.backup_days_spin.setRange(0, 365)
        self.backup_days_spin.setSuffix(" Tage")
        self.backup_days_spin.setToolTip(
            "Abstand, in dem gefragt wird, ob ein Backup gemacht wurde.\n"
            "0 = Erinnerung aus. Ein aktuelles Macrium-Reflect-Log ersetzt die Frage."
        )
        backup_layout.addWidget(self.backup_days_spin)
        backup_layout.addWidget(QLabel("nach einem Backup fragen (0 = aus)"))
        backup_layout.addStretch()
        layout.addWidget(backup_group)

        # Unterstuetzen-Hinweis (Issue #115)
        support_group = QGroupBox("Unterstützen")
        support_layout = QVBoxLayout(support_group)
        self.support_hint_disabled_checkbox = QCheckBox("Nicht mehr an das Unterstützen erinnern")
        self.support_hint_disabled_checkbox.setToolTip(
            "Blendet den gelegentlichen Hinweis aus. Über Hilfe > Unterstützen ...\n"
            "lässt sich der Dialog jederzeit öffnen."
        )
        support_layout.addWidget(self.support_hint_disabled_checkbox)
        layout.addWidget(support_group)

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

    # ------------------------------------------------------------------ Dokumentensuche (Registerkarte „Suche“)

    def _create_search_tab(self) -> QWidget:
        """Registerkarte „Suche“: alle Felder der ``SearchConfig`` (Dokumentensuche, ``src/search``).

        Die Felder liegen in einem Scrollbereich; geladen wird in
        ``_load_search_settings``, gespeichert in ``_save_search_settings``.
        """
        from PyQt6.QtWidgets import QListWidget, QMenu, QScrollArea, QTimeEdit, QToolButton

        inner = QWidget()
        layout = QVBoxLayout(inner)

        self.search_active_check = QCheckBox(
            "Dokumentensuche eingeschaltet (Volltextindex über die unten gewählten Ordner)"
        )
        self.search_active_check.setToolTip(
            "Durchsucht PDFs (mit Texterkennung), Office-Dateien, Markdown und Mails\n"
            "nach Stichwörtern. Der Index ist eine lokale Datenbank; Dateien werden\n"
            "nur gelesen, nie verändert."
        )
        layout.addWidget(self.search_active_check)
        search_hint = QLabel(
            "Alles bleibt auf diesem Rechner: Index und erkannter Text liegen in einer "
            "lokalen Datenbank, nichts wird gesendet. Ohne Einschalten wird nichts indiziert."
        )
        search_hint.setStyleSheet("color: gray;")
        search_hint.setWordWrap(True)
        layout.addWidget(search_hint)

        # Ordner und Laufwerke
        folders_group = QGroupBox("Ordner und Laufwerke")
        folders_layout = QVBoxLayout(folders_group)
        folders_layout.addWidget(QLabel("Vollständig durchsuchte Ordner oder Laufwerke:"))
        self.search_roots_list = QListWidget()
        self.search_roots_list.setMaximumHeight(90)
        folders_layout.addWidget(self.search_roots_list)
        roots_buttons = QHBoxLayout()
        self.search_roots_add = QPushButton("Ordner hinzufügen…")
        self.search_roots_add.clicked.connect(
            lambda: self._search_list_add_folder(self.search_roots_list, "Ordner oder Laufwerk hinzufügen")
        )
        roots_buttons.addWidget(self.search_roots_add)
        self.search_roots_suggest = QToolButton()
        self.search_roots_suggest.setText("Vorschläge")
        self.search_roots_suggest.setToolTip("Scan- und Zielordner, Laufwerke bzw. Benutzerordner und Volumes")
        self.search_roots_suggest.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.search_roots_suggest_menu = QMenu(self.search_roots_suggest)
        self.search_roots_suggest_menu.aboutToShow.connect(self._search_fill_suggestions)
        self.search_roots_suggest.setMenu(self.search_roots_suggest_menu)
        roots_buttons.addWidget(self.search_roots_suggest)
        self.search_roots_remove = QPushButton("Entfernen")
        self.search_roots_remove.clicked.connect(lambda: self._search_list_remove(self.search_roots_list))
        roots_buttons.addWidget(self.search_roots_remove)
        roots_buttons.addStretch()
        folders_layout.addLayout(roots_buttons)

        folders_layout.addWidget(QLabel(
            "Vorrang-Ordner (bei jedem Lauf zuerst; neue Scans im ersten Ordner werden sofort texterkannt):"
        ))
        self.search_priority_list = QListWidget()
        self.search_priority_list.setMaximumHeight(70)
        folders_layout.addWidget(self.search_priority_list)
        prio_buttons = QHBoxLayout()
        self.search_priority_add = QPushButton("Ordner hinzufügen…")
        self.search_priority_add.clicked.connect(
            lambda: self._search_list_add_folder(self.search_priority_list, "Vorrang-Ordner hinzufügen")
        )
        prio_buttons.addWidget(self.search_priority_add)
        self.search_priority_remove = QPushButton("Entfernen")
        self.search_priority_remove.clicked.connect(lambda: self._search_list_remove(self.search_priority_list))
        prio_buttons.addWidget(self.search_priority_remove)
        prio_buttons.addStretch()
        folders_layout.addLayout(prio_buttons)

        folders_layout.addWidget(QLabel("Ordnernamen, die überall übersprungen werden (einer je Zeile):"))
        self.search_exclude_names_edit = QPlainTextEdit()
        self.search_exclude_names_edit.setMaximumHeight(70)
        folders_layout.addWidget(self.search_exclude_names_edit)

        folders_layout.addWidget(QLabel("Vollständige Pfade, die übersprungen werden:"))
        self.search_exclude_paths_list = QListWidget()
        self.search_exclude_paths_list.setMaximumHeight(60)
        folders_layout.addWidget(self.search_exclude_paths_list)
        excl_buttons = QHBoxLayout()
        self.search_exclude_paths_add = QPushButton("Pfad hinzufügen…")
        self.search_exclude_paths_add.clicked.connect(
            lambda: self._search_list_add_folder(self.search_exclude_paths_list, "Auszuschließenden Ordner wählen")
        )
        excl_buttons.addWidget(self.search_exclude_paths_add)
        self.search_exclude_paths_remove = QPushButton("Entfernen")
        self.search_exclude_paths_remove.clicked.connect(
            lambda: self._search_list_remove(self.search_exclude_paths_list)
        )
        excl_buttons.addWidget(self.search_exclude_paths_remove)
        excl_buttons.addStretch()
        folders_layout.addLayout(excl_buttons)

        ext_row = QFormLayout()
        self.search_extensions_edit = QLineEdit()
        self.search_extensions_edit.setToolTip("Mit Leerzeichen getrennt, z. B.: .pdf .md .docx .xlsx .odt .doc .xls .eml .msg")
        ext_row.addRow("Dateiendungen:", self.search_extensions_edit)
        folders_layout.addLayout(ext_row)
        layout.addWidget(folders_group)

        # Mails
        mail_group = QGroupBox("Mails (Thunderbird-Postfächer)")
        mail_layout = QVBoxLayout(mail_group)
        self.search_mails_check = QCheckBox("Mails in den Index aufnehmen (jede Mail einzeln, Anhänge nur mit Namen)")
        mail_layout.addWidget(self.search_mails_check)
        self.search_thunderbird_label = QLabel("")
        self.search_thunderbird_label.setStyleSheet("color: gray;")
        self.search_thunderbird_label.setWordWrap(True)
        mail_layout.addWidget(self.search_thunderbird_label)
        mail_layout.addWidget(QLabel("Postfach-Ordner (leer = Postfächer des Thunderbird-Standardprofils):"))
        self.search_mail_folders_list = QListWidget()
        self.search_mail_folders_list.setMaximumHeight(60)
        mail_layout.addWidget(self.search_mail_folders_list)
        mail_buttons = QHBoxLayout()
        self.search_mail_folders_add = QPushButton("Ordner hinzufügen…")
        self.search_mail_folders_add.clicked.connect(
            lambda: self._search_list_add_folder(self.search_mail_folders_list, "Postfach-Ordner (Mail/, ImapMail/) wählen")
        )
        mail_buttons.addWidget(self.search_mail_folders_add)
        self.search_mail_folders_remove = QPushButton("Entfernen")
        self.search_mail_folders_remove.clicked.connect(
            lambda: self._search_list_remove(self.search_mail_folders_list)
        )
        mail_buttons.addWidget(self.search_mail_folders_remove)
        mail_buttons.addStretch()
        mail_layout.addLayout(mail_buttons)
        layout.addWidget(mail_group)

        # Texterkennung
        ocr_group = QGroupBox("Texterkennung (OCR) für gescannte PDFs")
        ocr_layout = QFormLayout(ocr_group)
        self.search_ocr_check = QCheckBox("Bildseiten ohne Text mit Tesseract erkennen")
        ocr_layout.addRow(self.search_ocr_check)
        self.search_ocr_languages_edit = QLineEdit()
        self.search_ocr_languages_edit.setToolTip("Tesseract-Sprachen, mit + verbunden, z. B. deu+eng")
        ocr_layout.addRow("Sprachen:", self.search_ocr_languages_edit)
        self.search_ocr_max_pages_spin = QSpinBox()
        self.search_ocr_max_pages_spin.setRange(0, 100000)
        self.search_ocr_max_pages_spin.setSpecialValueText("keine Grenze")
        self.search_ocr_max_pages_spin.setToolTip("PDFs mit mehr Bildseiten werden nicht automatisch texterkannt")
        ocr_layout.addRow("Höchstens Bildseiten je PDF:", self.search_ocr_max_pages_spin)
        self.search_ocr_status_label = QLabel("")
        self.search_ocr_status_label.setStyleSheet("color: gray;")
        self.search_ocr_status_label.setWordWrap(True)
        ocr_layout.addRow(self.search_ocr_status_label)
        layout.addWidget(ocr_group)

        # Cloud-Dateien und Grenzen
        limits_group = QGroupBox("Cloud-Dateien und Grenzen")
        limits_layout = QFormLayout(limits_group)
        self.search_cloud_check = QCheckBox(
            "Nur in der Cloud liegende Dateien (OneDrive, iCloud Drive) zum Lesen herunterladen"
        )
        self.search_cloud_check.setToolTip("Sonst werden solche Dateien nur mit ihrem Namen aufgenommen.")
        limits_layout.addRow(self.search_cloud_check)
        self.search_max_size_spin = QSpinBox()
        self.search_max_size_spin.setRange(1, 100000)
        self.search_max_size_spin.setSuffix(" MB")
        limits_layout.addRow("Größere Dateien nur mit Namen aufnehmen ab:", self.search_max_size_spin)
        layout.addWidget(limits_group)

        # Hintergrundindexierung
        bg_group = QGroupBox("Hintergrundindexierung")
        bg_layout = QFormLayout(bg_group)
        self.search_background_check = QCheckBox("Einmal täglich im Hintergrund indizieren, sobald der Rechner nicht "
                                                  "benutzt wird")
        bg_layout.addRow(self.search_background_check)
        self.search_background_time_edit = QTimeEdit()
        self.search_background_time_edit.setDisplayFormat("HH:mm")
        bg_layout.addRow("Frühestens ab:", self.search_background_time_edit)
        bg_hint = QLabel(
            "Der Lauf beginnt erst, wenn der Rechner 10 Minuten nicht benutzt wurde, und hält an, "
            "sobald Sie weiterarbeiten; im nächsten Leerlauf geht er weiter. War der Rechner zur "
            "eingestellten Zeit aus, wird der Lauf nach dem Einschalten nachgeholt – ebenfalls erst "
            "im Leerlauf, nicht direkt nach dem Start. Eingerichtet wird er beim Speichern über die "
            "Aufgabenplanung (Windows) bzw. einen LaunchAgent (macOS), Administratorrechte sind "
            "nicht nötig."
        )
        bg_hint.setStyleSheet("color: gray;")
        bg_hint.setWordWrap(True)
        bg_layout.addRow(bg_hint)
        layout.addWidget(bg_group)

        # Browser-Oberflaeche
        web_group = QGroupBox("Browser-Oberfläche (nur auf diesem Rechner erreichbar)")
        web_layout = QFormLayout(web_group)
        self.search_web_check = QCheckBox("Browser-Oberfläche der Suche einschalten")
        web_layout.addRow(self.search_web_check)
        self.search_web_login_check = QCheckBox("Bei der Anmeldung automatisch starten (nicht nötig)")
        self.search_web_login_check.setToolTip(
            "Legt eine Anmeldeaufgabe an. Manche Virenscanner, z. B. Microsoft Defender, melden das bei "
            "unsignierten Programmen als verdächtig und entfernen den Hintergrunddienst."
        )
        web_layout.addRow(self.search_web_login_check)
        self.search_web_port_spin = QSpinBox()
        self.search_web_port_spin.setRange(1024, 65535)
        web_layout.addRow("Port:", self.search_web_port_spin)
        web_hint = QLabel(
            "Geöffnet wird sie im Reiter „Suche“ mit „Im Browser öffnen“; dabei startet sie bei Bedarf "
            "von selbst. Beim automatischen Start läuft sie ab der Anmeldung im Hintergrund – das "
            "melden manche Virenscanner (z. B. Microsoft Defender) als verdächtig."
        )
        web_hint.setStyleSheet("color: gray;")
        web_hint.setWordWrap(True)
        web_layout.addRow(web_hint)
        layout.addWidget(web_group)

        # Leistung
        perf_group = QGroupBox("Leistung")
        perf_layout = QFormLayout(perf_group)
        self.search_processes_spin = QSpinBox()
        self.search_processes_spin.setRange(0, 64)
        self.search_processes_spin.setSpecialValueText("automatisch (halbe Kernzahl, höchstens 8)")
        perf_layout.addRow("Arbeitsprozesse:", self.search_processes_spin)
        layout.addWidget(perf_group)

        # Textebene (Phase 5b)
        text_group = QGroupBox("Gescannte PDFs verbessern (Textebene, Drehung, Schräglage)")
        text_layout = QFormLayout(text_group)
        self.search_textlayer_combo = QComboBox()
        for label, stufe in (
            ("Nur neue Scans im ersten Vorrang-Ordner (Standard)", "neue_scans"),
            ("Aus – keine PDF wird verändert", "aus"),
            ("Alle texterkannten PDFs (auch Altbestand, nur auf ausdrücklichen Wunsch)", "alle"),
        ):
            self.search_textlayer_combo.addItem(label, stufe)
        self._search_textlayer_previous = "aus"
        self.search_textlayer_combo.currentIndexChanged.connect(self._on_search_textlayer_changed)
        text_layout.addRow("Textebene schreiben:", self.search_textlayer_combo)
        self.search_textlayer_backup_days_spin = QSpinBox()
        self.search_textlayer_backup_days_spin.setRange(0, 3650)
        self.search_textlayer_backup_days_spin.setSuffix(" Tage")
        self.search_textlayer_backup_days_spin.setSpecialValueText("unbegrenzt")
        text_layout.addRow("Sicherungskopien aufbewahren:", self.search_textlayer_backup_days_spin)
        self.search_textlayer_protocol_button = QPushButton("Geänderte PDFs anzeigen / rückgängig machen…")
        self.search_textlayer_protocol_button.setToolTip(
            "Protokoll aller PDFs, die eine Textebene bekommen haben; einzelne Änderungen zurücknehmen"
        )
        self.search_textlayer_protocol_button.clicked.connect(self._open_textlayer_protocol)
        text_layout.addRow(self.search_textlayer_protocol_button)
        text_hint = QLabel(
            "Der erkannte Text wird als unsichtbare Textebene in die PDF gelegt, damit auch "
            "andere Programme (Explorer-Suche, Acrobat, PaperPort) ihn finden und man ihn "
            "markieren kann. Das Scanbild bleibt unverändert; vor jeder Änderung entsteht "
            "eine Sicherungskopie. Geschrieben wird beim nächsten Indexlauf, auch wenn die "
            "Datei inzwischen einsortiert ist. Signierte, verschlüsselte und PDF/A-Dateien "
            "sowie geöffnete Dateien bleiben unberührt."
        )
        text_hint.setStyleSheet("color: gray;")
        text_hint.setWordWrap(True)
        text_layout.addRow(text_hint)
        # Gedrehte Scans (Issue #151)
        self.search_autorotate_combo = QComboBox()
        for label, stufe in (
            ("Nur neue Scans im ersten Vorrang-Ordner (Standard)", "neue_scans"),
            ("Aus – Seiten bleiben, wie sie gescannt wurden", "aus"),
            ("Alle PDFs, deren Texterkennung eine gedrehte Seite findet", "alle"),
        ):
            self.search_autorotate_combo.addItem(label, stufe)
        self.search_autorotate_combo.setToolTip(
            "Liest die Texterkennung eine Seite erst gedreht richtig, wird die PDF so gespeichert"
        )
        text_layout.addRow("Gedrehte Seiten richtig herum speichern:", self.search_autorotate_combo)
        rotate_hint = QLabel(
            "Liest die Texterkennung eine Seite nicht, weil sie auf dem Kopf steht oder quer "
            "liegt, versucht sie die drei anderen Lagen und nimmt die beste. So herum wird die "
            "Seite gespeichert – mit Sicherungskopie, im Protokoll oben, rückgängig wie die "
            "Textebene. Nur die Drehangabe ändert sich, das Scanbild bleibt unverändert."
        )
        rotate_hint.setStyleSheet("color: gray;")
        rotate_hint.setWordWrap(True)
        text_layout.addRow(rotate_hint)
        # Schief gescannte Seiten (Issue #165)
        self.search_deskew_combo = QComboBox()
        for label, stufe in (
            ("Nur neue Scans im ersten Vorrang-Ordner (Standard)", "neue_scans"),
            ("Aus – Seiten bleiben, wie sie gescannt wurden", "aus"),
            ("Alle neu eingelesenen gescannten PDFs", "alle"),
        ):
            self.search_deskew_combo.addItem(label, stufe)
        self.search_deskew_combo.setToolTip(
            "Schief eingezogene Seiten werden um den kleinen Winkel gerade gedreht"
        )
        text_layout.addRow("Schief gescannte Seiten gerade ausrichten:", self.search_deskew_combo)
        deskew_hint = QLabel(
            "Beim Einlesen wird gemessen, ob die Zeilen eines Scans schräg stehen (ab 0,3°). Dann "
            "dreht PDFSM den Seiteninhalt um diesen Winkel gerade – mit Sicherungskopie, im Protokoll "
            "oben, rückgängig wie die Textebene. Das Scanbild wird dabei nicht neu berechnet, eine "
            "vorhandene Textebene dreht mit. Einzelne PDFs: Rechtsklick › Drehen › Gerade ausrichten."
        )
        deskew_hint.setStyleSheet("color: gray;")
        deskew_hint.setWordWrap(True)
        text_layout.addRow(deskew_hint)
        layout.addWidget(text_group)

        # Speicherort und Uebernahme
        storage_group = QGroupBox("Speicherort und Übernahme")
        storage_layout = QFormLayout(storage_group)
        db_row = QHBoxLayout()
        self.search_db_path_edit = QLineEdit()
        self.search_db_path_edit.setToolTip(
            "Leer = Standardort im Datenverzeichnis. Bei einer übernommenen PDFsuche\n"
            "zeigt der Wert auf deren bisherige Datenbank."
        )
        db_row.addWidget(self.search_db_path_edit, 1)
        self.search_db_browse = QPushButton("Durchsuchen…")
        self.search_db_browse.clicked.connect(self._browse_search_db)
        db_row.addWidget(self.search_db_browse)
        storage_layout.addRow("Datenbank:", db_row)
        self.search_migrate_button = QPushButton("Vorhandene PDFsuche übernehmen…")
        self.search_migrate_button.setToolTip(
            "Einstellungen und Datenbank des früheren, eigenständigen Programms PDFsuche übernehmen"
        )
        self.search_migrate_button.clicked.connect(self._open_search_migration)
        storage_layout.addRow(self.search_migrate_button)
        layout.addWidget(storage_group)

        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(inner)
        return scroll

    # Listen-Helfer der Registerkarte „Suche“

    def _search_list_add_folder(self, liste, titel: str) -> None:
        from PyQt6.QtWidgets import QFileDialog

        ordner = QFileDialog.getExistingDirectory(self, titel, "")
        if ordner:
            self._search_list_add(liste, ordner)

    @staticmethod
    def _search_list_add(liste, pfad: str) -> None:
        from src.search.konfig import norm_pfad

        pfad = norm_pfad(pfad)
        vorhanden = {liste.item(i).text().lower() for i in range(liste.count())}
        if pfad.lower() not in vorhanden:
            liste.addItem(pfad)

    @staticmethod
    def _search_list_remove(liste) -> None:
        for item in liste.selectedItems():
            liste.takeItem(liste.row(item))

    @staticmethod
    def _search_list_items(liste) -> list[str]:
        return [liste.item(i).text() for i in range(liste.count())]

    @staticmethod
    def _search_list_set(liste, werte) -> None:
        liste.clear()
        liste.addItems([str(w) for w in werte])

    def _search_fill_suggestions(self) -> None:
        """Menue „Vorschläge“: Scan-/Zielordner, dann Laufwerke bzw. Benutzerordner und Volumes."""
        from src.search import plattform
        from src.search.konfig import norm_pfad

        menu = self.search_roots_suggest_menu
        menu.clear()
        kandidaten = [str(self.config.get_scan_folder() or "")]
        kandidaten += [str(t) for t in self.config.get_target_folders()]
        try:
            kandidaten += plattform.wurzel_vorschlaege()
        except Exception:
            pass
        gesehen = set()
        for k in kandidaten:
            if not k.strip():
                continue
            p = norm_pfad(k)
            if p.lower() in gesehen:
                continue
            gesehen.add(p.lower())
            action = menu.addAction(p)
            action.triggered.connect(lambda _=False, pfad=p: self._search_list_add(self.search_roots_list, pfad))
        if menu.isEmpty():
            menu.addAction("Keine Vorschläge").setEnabled(False)

    def _browse_search_db(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        pfad, _ = QFileDialog.getSaveFileName(
            self, "Datenbank der Dokumentensuche", self.search_db_path_edit.text(),
            "SQLite-Datenbank (*.db);;Alle Dateien (*)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if pfad:
            self.search_db_path_edit.setText(pfad)

    def _open_search_migration(self) -> None:
        """„Vorhandene PDFsuche übernehmen…“: Dialog; danach die Registerkarte neu laden."""
        from src.gui.search_migration_dialog import SearchMigrationDialog

        dlg = SearchMigrationDialog(self, self.config)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._load_search_settings()

    def _load_search_settings(self) -> None:
        """Registerkarte „Suche“ aus ``Config.get_search_config()`` fuellen."""
        from PyQt6.QtCore import QTime

        from src.search import plattform
        from src.search.konfig import SearchConfig

        cfg = self.config.get_search_config()
        self.search_active_check.setChecked(cfg.aktiv)
        self._search_list_set(self.search_roots_list, cfg.wurzeln)
        self._search_list_set(self.search_priority_list, cfg.prioritaet)
        self.search_exclude_names_edit.setPlainText("\n".join(sorted(cfg.ordner_ausschliessen)))
        self._search_list_set(self.search_exclude_paths_list, sorted(cfg.pfade_ausschliessen))
        self.search_extensions_edit.setText(" ".join(sorted(cfg.endungen)))

        self.search_mails_check.setChecked(cfg.mails_aktiv)
        self._search_list_set(self.search_mail_folders_list, cfg.mail_ordner)
        try:
            profil = plattform.thunderbird_mail_ordner()
        except Exception:
            profil = []
        self.search_thunderbird_label.setText(
            "Thunderbird-Profil erkannt: " + ", ".join(profil) if profil
            else "Kein Thunderbird-Profil gefunden – Postfach-Ordner unten eintragen."
        )

        self.search_ocr_check.setChecked(cfg.ocr_aktiv)
        self.search_ocr_languages_edit.setText(cfg.ocr_sprachen)
        self.search_ocr_max_pages_spin.setValue(cfg.ocr_max_seiten)
        ocr = cfg.ocr_einstellungen()
        if ocr["tesseract"]:
            status = f"Tesseract gefunden: {ocr['tesseract']}"
            if ocr["grund"] and "Sprachdaten" in ocr["grund"]:
                status += f" – {ocr['grund']}"
        else:
            status = "Tesseract nicht gefunden – die Texterkennung bleibt aus, bis Tesseract installiert ist."
        self.search_ocr_status_label.setText(status)

        self.search_cloud_check.setChecked(cfg.cloud_herunterladen)
        self.search_max_size_spin.setValue(cfg.max_dateigroesse_mb)
        self.search_background_check.setChecked(cfg.hintergrund_aktiv)
        zeit = QTime.fromString(cfg.hintergrund_uhrzeit, "HH:mm")
        self.search_background_time_edit.setTime(zeit if zeit.isValid() else QTime(0, 0))
        self.search_web_check.setChecked(cfg.web_aktiv)
        self.search_web_login_check.setChecked(cfg.web_bei_anmeldung)
        self.search_web_port_spin.setValue(cfg.web_port)
        self.search_processes_spin.setValue(cfg.prozesse)
        self.search_textlayer_combo.blockSignals(True)
        self.search_textlayer_combo.setCurrentIndex(max(self.search_textlayer_combo.findData(cfg.textebene), 0))
        self.search_textlayer_combo.blockSignals(False)
        self._search_textlayer_previous = self.search_textlayer_combo.currentData() or "aus"
        self.search_textlayer_backup_days_spin.setValue(cfg.textebene_sicherung_tage)
        self.search_autorotate_combo.setCurrentIndex(max(self.search_autorotate_combo.findData(cfg.auto_drehen), 0))
        self.search_deskew_combo.setCurrentIndex(max(self.search_deskew_combo.findData(cfg.auto_gerade), 0))
        self.search_db_path_edit.setText(cfg.db_pfad)
        self.search_db_path_edit.setPlaceholderText(str(SearchConfig().db_datei))

    def _save_search_settings(self) -> None:
        """Registerkarte „Suche“ als ``SearchConfig`` in den Block ``"suche"`` schreiben."""
        from src.search.konfig import STANDARD_ENDUNGEN, SearchConfig

        alt = self.config.get_search_config()
        endungen = set(self.search_extensions_edit.text().split()) or set(STANDARD_ENDUNGEN)
        cfg = SearchConfig(
            aktiv=self.search_active_check.isChecked(),
            db_pfad=self.search_db_path_edit.text().strip(),
            wurzeln=self._search_list_items(self.search_roots_list),
            prioritaet=self._search_list_items(self.search_priority_list),
            endungen=endungen,
            ordner_ausschliessen={
                z.strip() for z in self.search_exclude_names_edit.toPlainText().splitlines() if z.strip()
            },
            pfade_ausschliessen=set(self._search_list_items(self.search_exclude_paths_list)),
            cloud_herunterladen=self.search_cloud_check.isChecked(),
            max_dateigroesse_mb=self.search_max_size_spin.value(),
            mails_aktiv=self.search_mails_check.isChecked(),
            mail_ordner=self._search_list_items(self.search_mail_folders_list),
            ocr_aktiv=self.search_ocr_check.isChecked(),
            ocr_tesseract=alt.ocr_tesseract,
            ocr_tessdata=alt.ocr_tessdata,
            ocr_sprachen=self.search_ocr_languages_edit.text().strip() or "deu+eng",
            ocr_dpi=alt.ocr_dpi,
            ocr_min_zeichen=alt.ocr_min_zeichen,
            ocr_max_seiten=self.search_ocr_max_pages_spin.value(),
            prozesse=self.search_processes_spin.value(),
            hintergrund_aktiv=self.search_background_check.isChecked(),
            hintergrund_uhrzeit=self.search_background_time_edit.time().toString("HH:mm"),
            web_aktiv=self.search_web_check.isChecked(),
            web_bei_anmeldung=self.search_web_login_check.isChecked(),
            web_host=alt.web_host,
            web_port=self.search_web_port_spin.value(),
            textebene=self.search_textlayer_combo.currentData() or "aus",
            textebene_sicherung_tage=self.search_textlayer_backup_days_spin.value(),
            textebene_sicherung_ordner=alt.textebene_sicherung_ordner,
            auto_drehen=self.search_autorotate_combo.currentData() or "aus",
            auto_gerade=self.search_deskew_combo.currentData() or "aus",
        )
        self.config.set_search_config(cfg)
        self._sync_search_schedule(alt, cfg)

    def _sync_search_schedule(self, alt, neu) -> None:
        """Aufgabenplanung bzw. LaunchAgent an Hintergrundindexierung und Web-Oberfläche anpassen.

        Ist etwas eingeschaltet, wird bei jedem Speichern abgeglichen (repariert
        auch eine gelöschte Aufgabe); sonst nur, wenn sich etwas geändert hat.
        """
        import subprocess

        from PyQt6.QtGui import QGuiApplication

        from src.search import zeitplan

        if zeitplan.merkmale(alt) == zeitplan.merkmale(neu) and not zeitplan.etwas_gewuenscht(neu):
            return
        fehler = ""
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            zeitplan.abgleichen(neu)
        except (zeitplan.ZeitplanFehler, OSError, subprocess.SubprocessError) as e:
            fehler = str(e)
        finally:
            QGuiApplication.restoreOverrideCursor()
        if fehler:
            QMessageBox.warning(
                self, "Hintergrundindexierung",
                "Die Einstellungen sind gespeichert, aber der Zeitplan ließ sich nicht anpassen:\n\n" + fehler)

    def _search_config_for_index(self):
        """Gespeicherte Suche-Einstellungen mit dem Datenbankpfad aus dem Formular (Schätzung, Protokoll)."""
        from dataclasses import replace

        cfg = self.config.get_search_config()
        return replace(cfg, db_pfad=self.search_db_path_edit.text().strip(),
                       prozesse=self.search_processes_spin.value(),
                       textebene_sicherung_tage=self.search_textlayer_backup_days_spin.value())

    def _on_search_textlayer_changed(self, _index: int) -> None:
        """Stufe „alle“ nur nach Rückfrage mit Schätzung (Dauer, OneDrive-Upload, Sicherungskopien)."""
        stufe = self.search_textlayer_combo.currentData() or "aus"
        if stufe == "alle" and self._search_textlayer_previous != "alle":
            if not self._confirm_textlayer_all():
                self.search_textlayer_combo.blockSignals(True)
                self.search_textlayer_combo.setCurrentIndex(
                    max(self.search_textlayer_combo.findData(self._search_textlayer_previous), 0))
                self.search_textlayer_combo.blockSignals(False)
                return
        self._search_textlayer_previous = stufe

    def _confirm_textlayer_all(self) -> bool:
        from PyQt6.QtGui import QGuiApplication

        from src.search import textebene
        from src.search.suchindex import Suchindex

        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            text = textebene.schaetzung_text(Suchindex(self._search_config_for_index()).textebene_schaetzung())
        except Exception as e:  # noqa: BLE001 - Schätzung ist eine Hilfe, kein Muss
            text = f"Der Aufwand lässt sich gerade nicht schätzen ({e})."
        finally:
            QGuiApplication.restoreOverrideCursor()
        antwort = QMessageBox.question(
            self, "Textebene auch für den Altbestand",
            text + "\n\nDie Stufe gilt ab dem nächsten Indexlauf; im Reiter „Suche“ lässt sich der Lauf "
            "jederzeit anhalten. Einschalten?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        return antwort == QMessageBox.StandardButton.Yes

    def _open_textlayer_protocol(self) -> None:
        from src.gui.textebene_dialog import TextebeneProtokollDialog

        TextebeneProtokollDialog(self._search_config_for_index(), self).exec()

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

    # Vorgegebene Default-Modelle pro Provider (Fallback wenn kein Cache existiert)
    _PROVIDER_DEFAULT_MODELS = {
        "claude": [
            "haiku-3.5 (günstig, älter)",
            "haiku-4.5 (schnell & günstig)",
            "sonnet-3.5 (günstig, älter)",
            "sonnet-4 (ausgewogen)",
            "sonnet-4.5 (beste Qualität)",
            "opus-4 (premium)",
        ],
        "openai": [
            "gpt-4o-mini (günstig, älter)",
            "gpt-4.1-nano (schnellstes)",
            "gpt-4.1-mini (schnell & günstig)",
            "gpt-4o (ausgewogen)",
            "gpt-4.1 (beste Qualität)",
            "o3-mini (Reasoning, günstig)",
            "o3 (Reasoning)",
            "o4-mini (Reasoning, neu)",
        ],
        "ollama": [
            "gpt-oss:20b (OpenAI, ab 16 GB Grafikspeicher, empfohlen)",
            "gemma4:12b (Google, ab 10 GB Grafikspeicher)",
            "gemma3:4b (Google, ab 4 GB Grafikspeicher)",
            "gemma4:26b (Google, ab 24 GB Grafikspeicher)",
            "gemma3:1b (Google, ohne Grafikkarte, langsam)",
            "llama3.1 (Meta, ausgewogen)",
            "qwen2.5 (Alibaba, gut bei strukturiertem Output)",
        ],
        "poe": [
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
        ],
        "openrouter": [
            "openai/gpt-4.1-nano (schnell & günstig)",
            "openai/gpt-4.1-mini (ausgewogen)",
            "openai/gpt-4o-mini (OpenAI, älter)",
            "anthropic/claude-3.5-haiku (Anthropic, schnell)",
            "anthropic/claude-sonnet-4 (Anthropic)",
            "google/gemini-2.5-flash (Google)",
            "meta-llama/llama-3.1-70b-instruct (Meta)",
            "mistralai/mistral-small (Mistral)",
        ],
        "ollama_cloud": [
            "gpt-oss:120b (OpenAI, gross, empfohlen)",
            "gpt-oss:20b (OpenAI, schnell)",
            "gemma4:31b (Google)",
            "deepseek-v4.1-flash (DeepSeek)",
            "kimi-k3 (Moonshot)",
            "glm-5.3 (Zhipu)",
            "minimax-m3 (MiniMax)",
            "mistral-large-4 (Mistral)",
        ],
    }

    _KEY_PROVIDER_LABELS = {
        "claude": "Anthropic Claude",
        "openai": "OpenAI",
        "poe": "Poe.com",
        "openrouter": "OpenRouter",
        "ollama_cloud": "Ollama Cloud",
        "strata": "Strata",
    }
    # Provider mit eigener Server-URL -> Standard-URL (Platzhalter)
    _URL_PROVIDER_DEFAULTS = {
        "ollama": "http://localhost:11434",
        "strata": "http://127.0.0.1:8080/v1",
        "lmstudio": "http://localhost:1234/v1",
    }
    _API_KEY_PLACEHOLDERS = {
        "strata": "sk-strata-... (in Strata unter Connect, Taste k)",
        "claude": "sk-ant-...",
        "openai": "sk-...",
        "poe": "Poe API-Key von poe.com/api_key",
        "ollama": "Nicht noetig fuer Ollama",
        "lmstudio": "Nicht noetig fuer LM Studio",
        "openrouter": "sk-or-... von openrouter.ai/keys",
        "ollama_cloud": "API-Key von ollama.com/settings/keys",
    }

    def _provider_id_at(self, index: int) -> str:
        """Liefert die Provider-ID fuer einen Combo-Index (leer wenn ungueltig)."""
        if 0 <= index < len(self._LLM_PROVIDERS):
            return self._LLM_PROVIDERS[index][0]
        return ""

    def _index_for_provider(self, provider_id: str) -> int:
        """Liefert den Combo-Index fuer eine Provider-ID (Fallback: "none")."""
        return self._LLM_PROVIDER_INDEX.get(provider_id, self._LLM_PROVIDER_INDEX["none"])

    def _stash_api_key(self):
        """Merkt sich den Feldinhalt fuer den Provider, dem er gehoert."""
        if self._key_provider:
            self._api_keys[self._key_provider] = self.api_key_input.text().strip()

    def _stash_base_url(self):
        """Merkt sich die Server-URL fuer den Provider, dem sie gehoert."""
        if self._url_provider:
            self._base_urls[self._url_provider] = self.base_url_input.text().strip()

    def _current_base_url(self, provider_id: str) -> str:
        """Server-URL aus dem Feld, leer -> Standard des Providers."""
        return (self.base_url_input.text().strip()
                or self._URL_PROVIDER_DEFAULTS.get(provider_id, ""))

    def _models_for_provider(self, provider_name: str) -> list[str]:
        """Liefert gecachte Modelle oder Defaults fuer einen Provider."""
        cached = self.config.get_cached_models(provider_name)
        if cached:
            return cached
        return self._PROVIDER_DEFAULT_MODELS.get(provider_name, [])

    def _on_provider_changed(self, index: int):
        """Wird aufgerufen wenn der Provider geändert wird."""
        # Key des bisherigen Providers sichern, Key des neuen laden
        self._stash_api_key()
        new_provider = self._provider_id_at(index)
        key_label = self._KEY_PROVIDER_LABELS.get(new_provider, "")
        self._key_provider = new_provider if key_label else ""
        self.api_key_input.setText(self._api_keys.get(self._key_provider, ""))
        self.api_key_label.setText(
            f"API-Key ({key_label}):" if key_label else "API-Key:"
        )
        self.cloud_consent_check.setEnabled(is_cloud_provider(new_provider))
        self._update_consent_hint()

        # Modelle je nach Provider aktualisieren
        self.model_combo.clear()

        # Server-URL nur fuer lokale Server (Ollama, Strata), je Provider gemerkt
        self._stash_base_url()
        default_url = self._URL_PROVIDER_DEFAULTS.get(new_provider, "")
        self._url_provider = new_provider if default_url else ""
        self.base_url_input.setText(self._base_urls.get(self._url_provider, ""))
        self.base_url_input.setPlaceholderText(default_url)
        self.base_url_input.setEnabled(bool(default_url))
        no_key = new_provider in ("ollama", "lmstudio")
        self.lmstudio_status_label.setVisible(new_provider == "lmstudio")

        if new_provider == "none":
            self.api_key_input.setEnabled(False)
            self.model_combo.setEnabled(False)
            self.test_button.setEnabled(False)
            return

        # Alle anderen Provider: API-/Modell-Felder freischalten
        # (nur Ollama und LM Studio kommen ohne Key aus).
        self.api_key_input.setEnabled(not no_key)
        self.model_combo.setEnabled(True)
        self.test_button.setEnabled(True)

        if new_provider == "lmstudio":
            self._detect_lmstudio()
        else:
            self.model_combo.addItems(self._models_for_provider(new_provider))
        self.api_key_input.setPlaceholderText(
            self._API_KEY_PLACEHOLDERS.get(new_provider, "")
        )

    _LMSTUDIO_START_HINT = (
        "LM Studio wurde nicht gefunden. LM Studio starten und den lokalen "
        "Server aktivieren (Developer > Start Server), dann "
        "„Modelle aktualisieren“ klicken."
    )
    _LMSTUDIO_KEIN_MODELL = (
        "LM Studio laeuft, bietet aber kein Modell an. In LM Studio "
        "ein Modell herunterladen bzw. laden."
    )

    def _detect_lmstudio(self) -> list[str] | None:
        """Kurzer Ping auf /v1/models: Modelle eintragen oder Start-Hinweis zeigen.

        Returns:
            Modellliste bei laufendem LM Studio, sonst None.
        """
        from src.ml.lmstudio_provider import detect_lm_studio

        models = detect_lm_studio(self._current_base_url("lmstudio"))
        current = self.model_combo.currentText().strip()
        self.model_combo.clear()
        if models is None:
            self.lmstudio_status_label.setText(self._LMSTUDIO_START_HINT)
            self.lmstudio_status_label.setStyleSheet("color: #c0392b;")
        else:
            self.model_combo.addItems(models)
            if models:
                text, color = f"LM Studio erkannt: {len(models)} Modell(e) verfuegbar.", "green"
            else:
                text, color = self._LMSTUDIO_KEIN_MODELL, "#b35c00"
            self.lmstudio_status_label.setText(text)
            self.lmstudio_status_label.setStyleSheet(f"color: {color};")
        if current:
            self.model_combo.setCurrentText(current)
        return models

    def _update_consent_hint(self):
        """Zeigt an, ob der Cloud-Provider ohne Einwilligung blockiert bleibt."""
        provider = self._provider_id_at(self.provider_combo.currentIndex())
        if not is_cloud_provider(provider):
            self.consent_hint_label.setText(
                "Nur für Cloud-Anbieter relevant (Ollama läuft lokal)."
            )
            self.consent_hint_label.setStyleSheet("color: gray;")
        elif self.cloud_consent_check.isChecked():
            self.consent_hint_label.setText("Einwilligung erteilt.")
            self.consent_hint_label.setStyleSheet("color: green;")
        else:
            self.consent_hint_label.setText(
                "Ohne Einwilligung bleibt der KI-Assistent deaktiviert "
                "(Statusleiste: \"LLM: Aus\")."
            )
            self.consent_hint_label.setStyleSheet("color: #c0392b;")

    # Chat-Gruppe (Issue #166/#167): eigenes Modell fuer den Chat

    def _chat_provider_id_at(self, index: int) -> str:
        """Provider-ID zum Index der Chat-Provider-Combo (leer wenn ungueltig)."""
        if 0 <= index < len(self._CHAT_PROVIDERS):
            return self._CHAT_PROVIDERS[index][0]
        return ""

    def _chat_index_for_provider(self, provider_id: str) -> int:
        """Combo-Index zur Provider-ID (Fallback: erster Eintrag, Ollama)."""
        return self._CHAT_PROVIDER_INDEX.get(provider_id, 0)

    def _stash_chat_api_key(self):
        """Merkt sich den Chat-Key fuer den Provider, dem er gehoert."""
        if self._chat_key_provider:
            self._chat_api_keys[self._chat_key_provider] = self.chat_api_key_input.text().strip()

    def _stash_chat_base_url(self):
        """Merkt sich die Chat-Server-URL fuer den Provider, dem sie gehoert."""
        if self._chat_url_provider:
            self._chat_base_urls[self._chat_url_provider] = self.chat_base_url_input.text().strip()

    def _main_api_key_for(self, provider_id: str) -> str:
        """API-Key des Anbieters aus der API-Konfiguration oben (Puffer inkl. Feld).

        Rueckfall fuer den Chat, wenn dort kein eigener Key steht - wie
        ``Config.get_chat_llm_config`` nach dem Speichern.
        """
        self._stash_api_key()
        return self._api_keys.get(provider_id, "")

    def _main_base_url_for(self, provider_id: str) -> str:
        """Server-URL des Anbieters von oben, leer -> Standard-URL des Providers."""
        self._stash_base_url()
        return (self._base_urls.get(provider_id, "")
                or self._URL_PROVIDER_DEFAULTS.get(provider_id, ""))

    def _on_chat_own_model_toggled(self, _checked: bool):
        """Checkbox „Eigenes Modell“: Felder frei-/abschalten, Hinweis nachziehen."""
        self._update_chat_fields_enabled()
        self._update_chat_consent_hint()

    def _on_chat_provider_changed(self, index: int):
        """Chat-Provider gewechselt: Key/URL je Provider, Modell-Liste, Hinweis."""
        self._stash_chat_api_key()
        self._stash_chat_base_url()
        provider = self._chat_provider_id_at(index)

        key_label = self._KEY_PROVIDER_LABELS.get(provider, "")
        self._chat_key_provider = provider if key_label else ""
        self.chat_api_key_input.setText(self._chat_api_keys.get(self._chat_key_provider, ""))
        self.chat_api_key_label.setText(
            f"API-Key ({key_label}):" if key_label else "API-Key:"
        )
        if key_label:
            self.chat_api_key_input.setPlaceholderText(
                "Leer = Key des gleichen Anbieters von oben"
            )
        else:
            self.chat_api_key_input.setPlaceholderText(
                self._API_KEY_PLACEHOLDERS.get(provider, "")
            )

        default_url = self._URL_PROVIDER_DEFAULTS.get(provider, "")
        self._chat_url_provider = provider if default_url else ""
        self.chat_base_url_input.setText(self._chat_base_urls.get(self._chat_url_provider, ""))
        self.chat_base_url_input.setPlaceholderText(
            f"Leer = wie oben bzw. {default_url}" if default_url else ""
        )

        self.chat_model_combo.clear()
        self.chat_model_combo.addItems(self._models_for_provider(provider))

        self._update_chat_fields_enabled()
        self._update_chat_consent_hint()

    def _update_chat_fields_enabled(self):
        """Felder des eigenen Chat-Modells nur bei gesetzter Checkbox bedienbar."""
        aktiv = self.chat_own_model_check.isChecked()
        provider = self._chat_provider_id_at(self.chat_provider_combo.currentIndex())
        self.chat_provider_combo.setEnabled(aktiv)
        self.chat_model_combo.setEnabled(aktiv)
        self.chat_refresh_models_button.setEnabled(aktiv)
        # Ollama und LM Studio (lokal) kommen ohne Key aus; URL nur fuer lokale Server
        self.chat_api_key_input.setEnabled(aktiv and provider not in ("ollama", "lmstudio"))
        self.chat_base_url_input.setEnabled(aktiv and provider in self._URL_PROVIDER_DEFAULTS)
        self.chat_test_button.setEnabled(aktiv)

    def _update_chat_consent_hint(self):
        """Hinweis: Die Cloud-Einwilligung von oben gilt auch fuer das Chat-Modell."""
        base = "Die Einwilligung für Cloud-Anbieter gilt auch hier."
        provider = self._chat_provider_id_at(self.chat_provider_combo.currentIndex())
        if (self.chat_own_model_check.isChecked()
                and is_cloud_provider(provider)
                and not self.cloud_consent_check.isChecked()):
            self.chat_consent_hint_label.setText(
                f"{base} Ohne Einwilligung (oben unter „Datenschutz“) bleibt das "
                f"Chat-Modell aus."
            )
            self.chat_consent_hint_label.setStyleSheet("color: #c0392b;")
        else:
            self.chat_consent_hint_label.setText(base)
            self.chat_consent_hint_label.setStyleSheet("color: gray;")

    def _test_chat_connection(self):
        """„Verbindung testen“ der Chat-Gruppe: dieselbe Testlogik mit den Chat-Werten.

        Leerer Key bzw. leere URL fallen wie beim Speichern auf die Werte des
        gleichen Anbieters aus der API-Konfiguration oben zurueck.
        """
        provider_id = self._chat_provider_id_at(self.chat_provider_combo.currentIndex())
        api_key = (self.chat_api_key_input.text().strip()
                   or self._main_api_key_for(provider_id))
        base_url = (self.chat_base_url_input.text().strip()
                    or self._main_base_url_for(provider_id))
        model_text = self.chat_model_combo.currentText()
        model = model_text.split(" ")[0] if model_text else ""
        self._run_connection_test(provider_id, api_key, model, base_url, self.chat_test_button)

    def _refresh_chat_models(self):
        """„Modelle aktualisieren“ der Chat-Gruppe (Liste wird je Anbieter gecacht)."""
        provider_id = self._chat_provider_id_at(self.chat_provider_combo.currentIndex())
        api_key = (self.chat_api_key_input.text().strip()
                   or self._main_api_key_for(provider_id))
        base_url = (self.chat_base_url_input.text().strip()
                    or self._main_base_url_for(provider_id))
        self._refresh_models_into(
            provider_id, api_key, base_url,
            self.chat_model_combo, self.chat_refresh_models_button,
        )

    @staticmethod
    def _select_model_in_combo(combo: QComboBox, model: str) -> None:
        """Waehlt das gespeicherte Modell in einer Modell-Combo (sonst als Freitext)."""
        if not model:
            return
        for i in range(combo.count()):
            if model in combo.itemText(i).lower():
                combo.setCurrentIndex(i)
                return
        combo.setCurrentText(model)

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

        self._key_provider = ""  # verhindert Stash eines leeren Felds
        self._api_keys = dict(llm_config.get("api_keys", {}))
        legacy_key = llm_config.get("api_key", "")
        if legacy_key and provider in self._KEY_PROVIDER_LABELS:
            self._api_keys.setdefault(provider, legacy_key)

        # Server-URLs je Provider; das alte Einzelfeld "base_url" gehoerte
        # dem aktiven lokalen Provider bzw. (vor Strata) immer Ollama.
        self._url_provider = ""
        self._base_urls = dict(llm_config.get("base_urls", {}))
        legacy_url = llm_config.get("base_url", "")
        if legacy_url:
            owner = provider if provider in self._URL_PROVIDER_DEFAULTS else "ollama"
            self._base_urls.setdefault(owner, legacy_url)

        self.provider_combo.setCurrentIndex(self._index_for_provider(provider))
        # Explizit aufrufen, falls sich der Index nicht geaendert hat (kein Signal)
        self._on_provider_changed(self.provider_combo.currentIndex())

        self._select_model_in_combo(self.model_combo, llm_config.get("model", ""))

        self.max_tokens_spin.setValue(llm_config.get("max_tokens", 2000))
        self.temperature_spin.setValue(llm_config.get("temperature", 0.3))
        self.text_limit_spin.setValue(llm_config.get("text_limit", 1500))
        self.cloud_consent_check.setChecked(llm_config.get("cloud_consent", False))

        # Chat (Issue #166/#167): eigenes Modell und Werkzeuge
        chat = self.config.get_chat_config()
        chat_provider = str(chat.provider or "").strip().lower()
        eigenes_modell = chat_provider in self._CHAT_PROVIDER_INDEX
        self._chat_key_provider = ""  # verhindert Stash eines leeren Felds
        self._chat_url_provider = ""
        self._chat_api_keys = (
            {chat_provider: str(chat.api_key)} if eigenes_modell and chat.api_key else {}
        )
        self._chat_base_urls = (
            {chat_provider: str(chat.base_url)} if eigenes_modell and chat.base_url else {}
        )
        self.chat_provider_combo.setCurrentIndex(
            self._chat_index_for_provider(chat_provider) if eigenes_modell else 0
        )
        # Explizit, falls sich der Index nicht geaendert hat (kein Signal)
        self._on_chat_provider_changed(self.chat_provider_combo.currentIndex())
        self._select_model_in_combo(self.chat_model_combo, str(chat.model or ""))
        self.chat_own_model_check.setChecked(eigenes_modell)
        self._update_chat_fields_enabled()
        self._update_chat_consent_hint()

        werkzeuge = bool(chat.werkzeuge_aktiv)
        self.chat_tools_check.setChecked(werkzeuge)
        try:
            schritte = int(chat.max_werkzeug_schritte)
        except (TypeError, ValueError):
            schritte = self.chat_steps_spin.value()
        self.chat_steps_spin.setValue(schritte)  # QSpinBox begrenzt auf 1-12
        self.chat_sql_check.setChecked(bool(chat.sql_erlaubt))
        self.chat_steps_spin.setEnabled(werkzeuge)
        self.chat_sql_check.setEnabled(werkzeuge)
        # Eigene Schnellfragen; leer = Standard (steht als Platzhalter im Feld)
        self.chat_schnellfragen_edit.setPlainText(
            "\n".join(schnellfragen_aus_text("\n".join(str(f) for f in (chat.schnellfragen or []))))
        )

        # Allgemeine Einstellungen
        self.max_suggestions_spin.setValue(self.config.get("max_suggestions", 5))
        self.suggest_new_folders_check.setChecked(bool(self.config.get("suggest_new_folders", True)))

        # Persönliche Daten
        self.owner_name_input.setText(self.config.get("owner_name", ""))
        self.owner_variants_input.setText(self.config.get("owner_name_variants", ""))
        self.owner_company_input.setText(self.config.get("owner_company", ""))
        self.owner_address_input.setText(self.config.get("owner_address", ""))
        self.owner_emails_input.setText(self.config.get("owner_emails", ""))
        self.owner_initials_input.setText(self.config.get("owner_initials", ""))
        self._on_owner_name_changed(self.owner_name_input.text())

        # Dateinamen-Muster (alte Grosswort-Schreibweise wird beim Anzeigen migriert)
        from src.core.filename_placeholders import migrate_legacy_pattern
        self.pattern_input.setText(
            migrate_legacy_pattern(self.config.get("filename_pattern", "") or "")
        )

        # Beim Verschieben (Issue #42)
        if self.config.get("folder_naming_enabled", False):
            self.folder_naming_prefix_radio.setChecked(True)
        else:
            self.folder_naming_keep_radio.setChecked(True)
        self.folder_naming_template_input.setText(
            self.config.get("folder_naming_template", "")
        )

        # Cache-Einstellungen
        self.persist_cache_checkbox.setChecked(self.config.get("persist_pdf_cache", True))
        self.llm_precache_checkbox.setChecked(self.config.get("llm_precache_enabled", True))
        self._update_cache_stats()

        # Original nach Umwandeln/Trennen (Issues #184, #187)
        for aktion, combo in self.original_combos.items():
            combo.setCurrentIndex(max(combo.findData(gespeicherte_antwort(self.config, aktion)), 0))

        # Update-Pruefung (Issue #73)
        self.update_check_checkbox.setChecked(self.config.get("update_check_enabled", True))

        # Backup-Erinnerung (Issue #14)
        self.backup_days_spin.setValue(int(self.config.get("backup_check_days", 7)))
        self.support_hint_disabled_checkbox.setChecked(
            bool(self.config.get("support_hint_disabled", False))
        )

        # PDF oeffnen (Issues #74/#76)
        mode = normalize_open_mode(self.config.get("pdf_open_mode"))
        self.pdf_open_mode_combo.setCurrentIndex(max(self.pdf_open_mode_combo.findData(mode), 0))
        self.pdf_open_command_input.setText(self.config.get("pdf_open_command", "") or "")
        self._update_pdf_open_command_enabled()

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

        # Dokumentensuche (Registerkarte „Suche“)
        self._load_search_settings()

    def _save_settings(self):
        """Speichert die Einstellungen."""
        # LLM-Einstellungen
        provider_index = self.provider_combo.currentIndex()
        provider = self._provider_id_at(provider_index) or "none"

        # Modellname extrahieren (vor dem Klammerteil)
        model_text = self.model_combo.currentText()
        model = model_text.split(" ")[0] if model_text else ""

        self._stash_api_key()
        api_keys = {k: v for k, v in self._api_keys.items() if v}
        self._stash_base_url()
        base_urls = {k: v for k, v in self._base_urls.items() if v}

        # Bestehende Werte (cloud_consent, cached_models, ...) erhalten,
        # nur die Dialog-Felder ueberschreiben.
        llm_config = {
            **self.config.get_llm_config(),
            "provider": provider,
            "api_key": api_keys.get(provider, ""),
            "api_keys": api_keys,
            "model": model,
            "max_tokens": self.max_tokens_spin.value(),
            "temperature": self.temperature_spin.value(),
            "text_limit": self.text_limit_spin.value(),
            "base_url": base_urls.get(provider, ""),
            "base_urls": base_urls,
            "cloud_consent": self.cloud_consent_check.isChecked(),
        }
        self.config.set("llm", llm_config)

        # Allgemeine Einstellungen
        self.config.set("max_suggestions", self.max_suggestions_spin.value())
        self.config.set("suggest_new_folders", self.suggest_new_folders_check.isChecked())

        # Cache-Einstellungen
        persist_cache = self.persist_cache_checkbox.isChecked()
        self.config.set("persist_pdf_cache", persist_cache)

        llm_precache = self.llm_precache_checkbox.isChecked()
        self.config.set("llm_precache_enabled", llm_precache)

        # Original nach Umwandeln/Trennen (Issues #184, #187)
        for aktion, combo in self.original_combos.items():
            antwort_speichern(self.config, aktion, combo.currentData())

        # Update-Pruefung (Issue #73)
        self.config.set("update_check_enabled", self.update_check_checkbox.isChecked())

        # Backup-Erinnerung (Issue #14)
        self.config.set("backup_check_days", self.backup_days_spin.value())
        self.config.set(
            "support_hint_disabled", self.support_hint_disabled_checkbox.isChecked()
        )

        # PDF oeffnen (Issues #74/#76)
        self.config.set("pdf_open_mode", self.pdf_open_mode_combo.currentData())
        self.config.set("pdf_open_command", self.pdf_open_command_input.text().strip())

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
        self.config.set("owner_initials", self.owner_initials_input.text().strip().upper())

        # Dateinamen-Muster speichern
        self.config.set("filename_pattern", self.pattern_input.text().strip())

        # Beim Verschieben speichern (Issue #42)
        self.config.set("folder_naming_enabled", self.folder_naming_prefix_radio.isChecked())
        template = self.folder_naming_template_input.text().strip()
        self.config.set(
            "folder_naming_template",
            template or self.config.DEFAULTS["folder_naming_template"],
        )

        # Explorer-Integration nur bei Aenderung anwenden.
        if sys.platform == "win32":
            self._apply_explorer_integration_change()

        # Dokumentensuche (Registerkarte „Suche“)
        self._save_search_settings()

        # Chat (Issue #166/#167): Checkbox aus -> nur provider "" (Modell der
        # Sortierung); Modell/Key/URL werden dann NICHT angefasst, damit ein
        # frueher gespeicherter Key nicht bei jedem Speichern verloren geht
        # (Review-Befund: der Dialog kennt bei abgeschalteter Checkbox keinen
        # Provider, zu dem er den Key puffern koennte).
        self._stash_chat_api_key()
        self._stash_chat_base_url()
        fragen = schnellfragen_aus_text(self.chat_schnellfragen_edit.toPlainText())
        chat_felder = dict(
            werkzeuge_aktiv=self.chat_tools_check.isChecked(),
            max_werkzeug_schritte=self.chat_steps_spin.value(),
            sql_erlaubt=self.chat_sql_check.isChecked(),
            # Standardfragen nicht festschreiben: leer, wenn sie dem Standard entsprechen
            schnellfragen=[] if fragen == list(SCHNELLFRAGEN) else fragen,
        )
        if self.chat_own_model_check.isChecked():
            chat_provider = self._chat_provider_id_at(self.chat_provider_combo.currentIndex())
            chat_model_text = self.chat_model_combo.currentText()
            chat_felder.update(
                provider=chat_provider,
                model=chat_model_text.split(" ")[0] if chat_model_text else "",
                api_key=self._chat_api_keys.get(chat_provider, ""),
                base_url=self._chat_base_urls.get(chat_provider, ""),
            )
        else:
            chat_felder["provider"] = ""
        self.config.update_chat_config(**chat_felder)

        self.settings_changed.emit()
        self.accept()

    def _update_pdf_open_command_enabled(self, *_):
        """Programm-Feld nur bei "Eigenes Programm" aktiv (Issue #76)."""
        is_custom = self.pdf_open_mode_combo.currentData() == OPEN_MODE_CUSTOM
        self.pdf_open_command_input.setEnabled(is_custom)
        self.pdf_open_command_browse.setEnabled(is_custom)

    def _browse_pdf_open_command(self):
        """Dateiauswahl fuer das eigene PDF-Programm."""
        from PyQt6.QtWidgets import QFileDialog

        if sys.platform == "win32":
            file_filter = "Programme (*.exe);;Alle Dateien (*)"
        elif sys.platform == "darwin":
            file_filter = "Programme (*.app);;Alle Dateien (*)"
        else:
            file_filter = "Alle Dateien (*)"
        path, _ = QFileDialog.getOpenFileName(
            self, "PDF-Programm auswählen", self.pdf_open_command_input.text(), file_filter
        )
        if path:
            self.pdf_open_command_input.setText(path)

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

    def _test_connection(self):
        """Testet die Verbindung zum LLM-Provider (Sortier-Modell)."""
        provider_id = self._provider_id_at(self.provider_combo.currentIndex())
        api_key = self.api_key_input.text().strip()
        base_url = self._current_base_url(provider_id)

        # Modellname extrahieren
        model_text = self.model_combo.currentText()
        model = model_text.split(" ")[0] if model_text else ""

        self._run_connection_test(provider_id, api_key, model, base_url, self.test_button)

    def _run_connection_test(self, provider_id: str, api_key: str, model: str,
                             base_url: str, button: QPushButton):
        """Verbindungstest fuer Sortier- und Chat-Modell (Issue #166/#167).

        ``button`` ist der ausloesende Knopf; er ist waehrend des Tests gesperrt.
        """
        # Ollama und LM Studio brauchen keinen API-Key, aber eine URL.
        if provider_id not in ("ollama", "lmstudio") and not api_key:
            QMessageBox.warning(
                self, "Fehler",
                "Bitte geben Sie einen API-Key ein."
            )
            return

        button.setEnabled(False)
        button.setText("Teste...")

        try:
            if provider_id == "claude":
                self._test_claude(api_key, model)
            elif provider_id == "openai":
                self._test_openai(api_key, model)
            elif provider_id == "poe":
                self._test_poe(api_key, model)
            elif provider_id == "ollama":
                self._test_ollama(base_url, model)
            elif provider_id == "openrouter":
                self._test_openrouter(api_key, model)
            elif provider_id == "ollama_cloud":
                self._test_ollama_cloud(api_key, model)
            elif provider_id == "strata":
                self._test_strata(api_key, model, base_url)
            elif provider_id == "lmstudio":
                self._test_lmstudio(model, base_url)
        finally:
            button.setEnabled(True)
            button.setText("Verbindung testen")

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
        """Testet die Poe API (OpenAI-kompatibel)."""
        try:
            import openai
            from src.ml.poe_provider import PoeProvider
            client = openai.OpenAI(
                api_key=api_key,
                base_url=PoeProvider.BASE_URL,
            )
            model_id = model or PoeProvider.DEFAULT_MODEL

            # Claude-Modelle via Poe aktivieren Thinking automatisch. max_tokens
            # muss deshalb hoch genug sein (>=2048), damit Poe's abgeleitetes
            # budget_tokens nach Abzug der Response-Reserve >= 1024 bleibt.
            max_tokens = 2048 if "claude" in model_id.lower() else 20

            response = client.chat.completions.create(
                model=model_id,
                max_tokens=max_tokens,
                messages=[
                    {"role": "user", "content": "Sage 'OK'"}
                ]
            )

            QMessageBox.information(
                self, "Erfolg",
                f"Verbindung zu Poe erfolgreich!\n"
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
                "Ungültiger Poe API-Key.\n"
                "Holen Sie Ihren Key von: poe.com/api_key"
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Fehler",
                f"Verbindungsfehler: {str(e)}"
            )

    def _test_ollama_cloud(self, api_key: str, model: str):
        """Testet Ollama Cloud (ollama.com) mit einem Mini-Request."""
        try:
            from src.ml.ollama_provider import OllamaCloudProvider
            from src.ml.llm_provider import LLMConfig

            provider = OllamaCloudProvider(LLMConfig(
                api_key=api_key,
                model=model or OllamaCloudProvider.DEFAULT_MODEL,
                max_tokens=5,
            ))
            answer, error = provider._do_chat("Antworte nur mit OK.", "Test")
            if error:
                QMessageBox.critical(
                    self, "Fehler",
                    f"Ollama Cloud antwortet nicht:\n{error}\n\n"
                    "Pruefen Sie den API-Key (ollama.com/settings/keys) "
                    "und den Modellnamen."
                )
                return
            QMessageBox.information(
                self, "Erfolg",
                f"Verbindung zu Ollama Cloud erfolgreich!\n"
                f"Modell: {model or OllamaCloudProvider.DEFAULT_MODEL}\n"
                f"Antwort: {answer.strip()[:60]}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Verbindungsfehler: {e}")

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

    def _test_openrouter(self, api_key: str, model: str):
        """Testet die OpenRouter API (OpenAI-kompatibel)."""
        try:
            import openai
            from src.ml.openrouter_provider import OpenRouterProvider
            client = openai.OpenAI(
                api_key=api_key,
                base_url=OpenRouterProvider.BASE_URL,
            )
            model_id = model or OpenRouterProvider.DEFAULT_MODEL

            response = client.chat.completions.create(
                model=model_id,
                max_tokens=10,
                messages=[
                    {"role": "user", "content": "Sage 'OK'"}
                ]
            )

            QMessageBox.information(
                self, "Erfolg",
                f"Verbindung zu OpenRouter erfolgreich!\n"
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
                "Ungültiger OpenRouter API-Key.\n"
                "Holen Sie Ihren Key von: openrouter.ai/keys"
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Fehler",
                f"Verbindungsfehler: {str(e)}"
            )

    def _test_strata(self, api_key: str, model: str, base_url: str):
        """Testet einen lokalen Strata-Server (OpenAI-kompatibel)."""
        try:
            import openai
            from src.ml.llm_provider import LLMConfig
            from src.ml.strata_provider import StrataProvider

            provider = StrataProvider(LLMConfig(
                api_key=api_key, model=model, base_url=base_url,
            ))
            if provider._client is None:
                raise RuntimeError("OpenAI-kompatibler Client nicht verfuegbar.")
            model_id = provider._get_model_id()
            if not model_id:
                raise RuntimeError(
                    f"Kein Modell gefunden. Laeuft Strata unter {provider.base_url}?"
                )
            response = provider._create_chat_completion(
                model=model_id,
                max_tokens=200,
                messages=[{"role": "user", "content": "Sage 'OK'"}],
            )
            QMessageBox.information(
                self, "Erfolg",
                f"Verbindung zu Strata erfolgreich!\n"
                f"Server: {provider.base_url}\n"
                f"Modell: {model_id}\n"
                f"Antwort: {response.choices[0].message.content}"
            )
        except ImportError:
            QMessageBox.critical(
                self, "Fehler",
                "Das 'openai' Paket ist nicht installiert.\n"
                "Installieren mit: pip install openai"
            )
        except Exception as e:
            if type(e).__name__ == "AuthenticationError":
                text = ("Ungueltiger Strata API-Key.\n"
                        "Den Key zeigt Strata unter Connect (Taste k).")
            elif type(e).__name__ == "APIConnectionError":
                text = (f"Keine Verbindung zu Strata unter {base_url}.\n"
                        "Laeuft der Strata-Server?")
            else:
                text = f"Verbindungsfehler: {str(e)}"
            QMessageBox.critical(self, "Fehler", text)

    def _test_lmstudio(self, model: str, base_url: str):
        """Testet ein lokales LM Studio (OpenAI-kompatibel, ohne Key).

        Prueft die uebergebene URL, damit der Test auch fuer ein eigenes
        Chat-Modell (Issue #166/#167) mit abweichender URL stimmt.
        """
        from src.ml.lmstudio_provider import detect_lm_studio

        if detect_lm_studio(base_url) is None:
            QMessageBox.warning(self, "LM Studio", self._LMSTUDIO_START_HINT)
            return
        try:
            from src.ml.llm_provider import LLMConfig
            from src.ml.lmstudio_provider import LMStudioProvider

            provider = LMStudioProvider(LLMConfig(
                api_key="", model=model, base_url=base_url,
            ))
            if provider._client is None:
                raise RuntimeError("OpenAI-kompatibler Client nicht verfuegbar.")
            model_id = provider._get_model_id()
            if not model_id:
                raise RuntimeError(
                    "LM Studio bietet kein Modell an. Bitte in LM Studio "
                    "ein Modell herunterladen bzw. laden."
                )
            response = provider._create_chat_completion(
                model=model_id,
                max_tokens=200,
                messages=[{"role": "user", "content": "Sage 'OK'"}],
            )
            QMessageBox.information(
                self, "Erfolg",
                f"Verbindung zu LM Studio erfolgreich!\n"
                f"Server: {provider.base_url}\n"
                f"Modell: {model_id}\n"
                f"Antwort: {response.choices[0].message.content}"
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Fehler", f"Verbindungsfehler: {str(e)}")

    def _refresh_models(self):
        """Ruft die verfügbaren Modelle vom API-Provider ab (Sortier-Modell)."""
        provider_id = self._provider_id_at(self.provider_combo.currentIndex())
        api_key = self.api_key_input.text().strip()
        if provider_id == "lmstudio":
            # Erkennungsstatus unter dem Provider aktualisieren (Issue #45)
            self._detect_lmstudio()
        self._refresh_models_into(
            provider_id, api_key, self._current_base_url(provider_id),
            self.model_combo, self.refresh_models_button,
        )

    def _fetch_models_for(self, provider_id: str, api_key: str, base_url: str) -> list[str]:
        """Modell-Liste eines Anbieters abrufen (wirft bei Fehlern; leer = unbekannter Anbieter)."""
        if provider_id == "claude":
            return self._fetch_claude_models(api_key)
        if provider_id == "openai":
            return self._fetch_openai_models(api_key)
        if provider_id == "poe":
            return self._fetch_poe_models(api_key)
        if provider_id == "ollama":
            return self._fetch_ollama_models(base_url)
        if provider_id == "strata":
            from src.ml.strata_provider import StrataProvider
            from src.ml.llm_provider import LLMConfig
            strata = StrataProvider(LLMConfig(
                api_key=api_key, model="", base_url=base_url,
            ))
            models = strata.list_models()
            if not models:
                raise RuntimeError(
                    f"Keine Modelle gefunden. Laeuft Strata unter "
                    f"{strata.base_url} und stimmt der API-Key?"
                )
            return models
        if provider_id == "lmstudio":
            from src.ml.lmstudio_provider import detect_lm_studio
            models = detect_lm_studio(base_url)
            if models is None:
                raise RuntimeError(self._LMSTUDIO_START_HINT)
            if not models:
                raise RuntimeError(self._LMSTUDIO_KEIN_MODELL)
            return models
        if provider_id == "openrouter":
            return self._fetch_openrouter_models(api_key)
        if provider_id == "ollama_cloud":
            from src.ml.ollama_provider import OllamaCloudProvider
            from src.ml.llm_provider import LLMConfig
            return OllamaCloudProvider(LLMConfig(api_key=api_key, model="")).list_models()
        return []

    def _refresh_models_into(self, provider_id: str, api_key: str, base_url: str,
                             combo: QComboBox, button: QPushButton):
        """„Modelle aktualisieren“ fuer Sortier- und Chat-Modell (Issue #166/#167).

        Fuellt ``combo`` mit der abgerufenen Liste, waehlt das bisherige Modell
        wieder aus und cacht die Liste je Anbieter in der Konfiguration.
        """
        if provider_id == "none" or not provider_id:
            QMessageBox.information(
                self, "Hinweis",
                "Bitte wählen Sie zuerst einen LLM-Provider aus."
            )
            return

        # Ollama und LM Studio brauchen keinen API-Key, alle anderen schon.
        if provider_id not in ("ollama", "lmstudio") and not api_key:
            QMessageBox.warning(
                self, "Fehler",
                "Bitte geben Sie einen API-Key ein, um die Modelle abzurufen."
            )
            return

        # Aktuell gewähltes Modell merken
        current_model = combo.currentText().split(" ")[0]

        button.setEnabled(False)
        button.setText("Lade...")

        try:
            models = self._fetch_models_for(provider_id, api_key, base_url)

            if models:
                combo.clear()
                combo.addItems(models)

                # Vorheriges Modell wieder auswählen wenn möglich
                for i in range(combo.count()):
                    if combo.itemText(i).startswith(current_model):
                        combo.setCurrentIndex(i)
                        break

                # Liste persistieren, damit sie nach Neustart erhalten bleibt
                self.config.set_cached_models(provider_id, models)

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
            button.setEnabled(True)
            button.setText("Modelle aktualisieren")

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
        from src.ml.poe_provider import PoeProvider
        client = openai.OpenAI(
            api_key=api_key,
            base_url=PoeProvider.BASE_URL,
        )

        models_response = client.models.list()
        models = [model.id for model in models_response.data]
        models.sort()
        return models

    def _fetch_openrouter_models(self, api_key: str) -> list[str]:
        """Ruft verfügbare Modelle von der OpenRouter API ab."""
        import openai
        from src.ml.openrouter_provider import OpenRouterProvider
        client = openai.OpenAI(
            api_key=api_key,
            base_url=OpenRouterProvider.BASE_URL,
        )

        models_response = client.models.list()
        models = [model.id for model in models_response.data]
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

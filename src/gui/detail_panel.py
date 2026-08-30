"""
Detail-Panel für das 3-Spalten-Layout.

Zeigt Umbenennungsvorschläge, Metadaten und Vorschau für die ausgewählte PDF.
Der Benutzer klickt links ein Thumbnail an, sieht hier die Details,
und klickt rechts auf einen Zielordner zum Verschieben+Umbenennen.
"""

from pathlib import Path
from typing import Optional

import logging
import time

from PyQt6.QtCore import Qt, QEvent, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QColor, QFont
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
    QCheckBox,
    QComboBox,
    QGridLayout,
    QSizePolicy,
    QSplitter,
)

logger = logging.getLogger(__name__)

from src.core.llm_activity import (
    KIND_SUGGEST,
    format_elapsed,
    format_estimate,
    get_llm_activity,
)
from src.gui.pdf_preview_widget import PdfPreviewWidget
from src.gui.rename_dialog import RenameSuggestion


class _PdfMetadataReader(QThread):
    """Liest XMP-Metadaten einer PDF im Hintergrund.

    Der Lesezugriff kann auf OneDrive ("Files On-Demand") mehrere Sekunden
    dauern, weil die Datei erst heruntergeladen wird - das darf den Klick
    nicht blockieren (Issue #28).
    """

    finished_meta = pyqtSignal(object, object)  # (pdf_path, PDFMetadata | None)

    def __init__(self, pdf_path: Path, parent=None):
        super().__init__(parent)
        self._pdf_path = pdf_path

    def run(self):
        try:
            from src.core.pdf_metadata import read_metadata
            meta = read_metadata(self._pdf_path)
        except Exception:
            meta = None
        self.finished_meta.emit(self._pdf_path, meta)


class _LLMMetadataWorker(QThread):
    """Ruft die KI fuer Dateiname + Metadaten im Hintergrund auf (Issue #68).

    Vorher lief der Aufruf im GUI-Thread und fror das Fenster fuer die Dauer
    der Anfrage ein - auf langsamen Rechnern oder bei haengender Cloud
    minutenlang, ohne dass man sah, ob noch etwas passiert.
    """

    # (pdf_path, suggestions, fehlertext)
    result_ready = pyqtSignal(Path, list, str)

    def __init__(self, classifier, pdf_path: Path, text: str, keywords: list,
                 detected_date, file_date, parent=None):
        super().__init__(parent)
        self._classifier = classifier
        self._pdf_path = pdf_path
        self._text = text
        self._keywords = keywords
        self._detected_date = detected_date
        self._file_date = file_date

    def run(self):
        activity = get_llm_activity()
        token = activity.begin(KIND_SUGGEST, self._pdf_path.name)
        ok = False
        try:
            suggestions = self._classifier.suggest_filename(
                text=self._text,
                current_filename=self._pdf_path.name,
                keywords=self._keywords,
                detected_date=self._detected_date,
                use_llm=True,
                file_date=self._file_date,
            )
            ok = True
        except Exception as e:  # noqa: BLE001 - Fehler an die GUI melden
            self.result_ready.emit(self._pdf_path, [], str(e))
            return
        finally:
            activity.end(token, success=ok)
        self.result_ready.emit(self._pdf_path, list(suggestions or []), "")


class _CategoryCombo(QComboBox):
    """Kategorie-Feld als editierbare Auswahl (Issue #110).

    Verhaelt sich nach aussen wie das QLineEdit, das hier vorher stand
    (``text``/``setText``/``clear``/``textChanged``), zeigt aber im Aufklapp-
    Menue die haeufigsten Kategorien der Sammlung.
    """

    textChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(6)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.lineEdit().textChanged.connect(self.textChanged)

    def text(self) -> str:
        return self.currentText()

    def setText(self, text: str) -> None:
        self.setEditText(text or "")

    def clear(self) -> None:  # nur den Text, nicht die Auswahlliste
        self.clearEditText()

    def setPlaceholderText(self, text: str) -> None:
        self.lineEdit().setPlaceholderText(text)

    def set_choices(self, choices: list[str]) -> None:
        current = self.currentText()
        self.blockSignals(True)
        self.lineEdit().blockSignals(True)
        super().clear()
        self.addItems(list(choices))
        self.setEditText(current)
        self.lineEdit().blockSignals(False)
        self.blockSignals(False)


class DetailPanel(QWidget):
    """Mittleres Panel: Zeigt Rename-Vorschläge + Metadaten für ausgewählte PDF."""

    # Signal: Benutzer möchte Metadaten in PDF speichern (ohne Verschieben)
    save_metadata_requested = pyqtSignal()
    # Signal: Benutzer möchte Dateiname UND Metadaten speichern (ohne Verschieben)
    rename_and_save_metadata_requested = pyqtSignal()
    # Signale rund ums Öffnen (Issues #74/#76) - das Hauptfenster entscheidet,
    # ob integrierte Vorschau oder externes Programm
    open_pdf_requested = pyqtSignal(Path)            # Suchergebnis doppelgeklickt
    open_pdf_external_requested = pyqtSignal(Path)   # "Extern öffnen" in der Vorschau
    enlarge_preview_requested = pyqtSignal(Path)     # große Vorschau gewünscht
    # "Muster bearbeiten" in der Vorschlags-Kopfzeile: Einstellungen > Dateinamen
    edit_pattern_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_pdf: Optional[Path] = None
        self._suggestions: list[RenameSuggestion] = []
        # Tatsaechlich angezeigte Liste (#99/#106): _suggestions + ein
        # Muster-Vorschlag je Vorlage, sortiert nach der gemerkten Rangfolge;
        # _displayed_kinds haelt parallel dazu die Art jeder Zeile
        self._displayed_suggestions: list[RenameSuggestion] = []
        self._displayed_kinds: list[str] = []
        self._detected_date: Optional[str] = None
        self._metadata: dict = {}
        self._has_learned_overrides: bool = False
        # Quelle der aktuell angezeigten Metadaten: "pdf", "llm", "user", None
        self._metadata_source: Optional[str] = None
        # Zuletzt automatisch (aus Vorschlag) gesetzter Dateiname - dient zur
        # Erkennung, ob der Nutzer den Namen selbst geaendert hat
        self._auto_name: str = ""
        # Snapshot der zuletzt gespeicherten Metadaten (entspricht PDF-Stand)
        self._saved_metadata_snapshot: dict = {}
        # Felder, die tatsaechlich aus dem PDF (XMP/Info) gelesen wurden - nur
        # diese gelten als "gespeichert"; Analyse-/KI-Werte daneben nicht
        self._pdf_field_keys: set = set()
        # Flag um textChanged-Signale während des programmatischen Füllens zu ignorieren
        self._loading_metadata: bool = False
        # KI-Aufruf "Metadaten neu generieren" laeuft im Hintergrund (Issue #68)
        self._llm_worker: Optional[_LLMMetadataWorker] = None
        self._llm_started: Optional[float] = None
        self._llm_timer = QTimer(self)
        self._llm_timer.setInterval(1000)
        self._llm_timer.timeout.connect(self._tick_llm_button)

        # Feste Größenpolitik: Panel ändert seine Größe nicht beim Befüllen
        from PyQt6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        self._setup_ui()

    def _setup_ui(self):
        """Erstellt die UI-Komponenten."""
        # Scroll-Bereich für den gesamten Inhalt
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        # AsNeeded statt AlwaysOff: Wenn die Felder nicht in die Spalte passen
        # (z.B. 125% Windows-Skalierung), wird sonst rechts abgeschnitten (Issue #50)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

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
        detail_layout.setSpacing(4)
        detail_layout.setContentsMargins(0, 0, 0, 0)

        # Header: Aktueller Dateiname
        self.header_label = QLabel()
        self.header_label.setStyleSheet(
            "font-size: 11px; color: #666; padding: 4px; "
            "background-color: #f5f5f5; border-radius: 3px;"
        )
        self.header_label.setWordWrap(True)
        detail_layout.addWidget(self.header_label)

        # Vorschläge - Kopfzeile mit Titel links, Schalter + Button rechts
        suggestions_group = QGroupBox()
        suggestions_layout = QVBoxLayout(suggestions_group)
        suggestions_layout.setSpacing(2)
        suggestions_layout.setContentsMargins(6, 4, 6, 6)

        head_row = QHBoxLayout()
        head_row.setSpacing(6)
        title = QLabel("<b>Vorschläge</b>")
        title.setToolTip("Zum Auswählen anklicken - der Name wandert ins Feld „Neuer Dateiname“.")
        head_row.addWidget(title)
        head_row.addStretch(1)
        # Schalter fuer "Dateiname aus Ordnerstruktur" (Issue #42) direkt am
        # Ort des Geschehens - gleiche Einstellung wie im Einstellungsdialog
        self.folder_naming_checkbox = QCheckBox("Ordnerstruktur im Namen")
        self.folder_naming_checkbox.setStyleSheet("font-size: 10px;")
        self.folder_naming_checkbox.setToolTip(
            "Beim Verschieben die Nummern/Namen des Zielordners in den Dateinamen\n"
            "aufnehmen (Vorlage unter Einstellungen > Dateinamen > Beim Verschieben).\n"
            "Wirkt sofort, auch fuer den naechsten Verschiebe-Vorgang."
        )
        self.folder_naming_checkbox.toggled.connect(self._on_folder_naming_toggled)
        head_row.addWidget(self.folder_naming_checkbox)
        self.edit_pattern_btn = QPushButton("Muster bearbeiten…")
        self.edit_pattern_btn.setFlat(True)
        self.edit_pattern_btn.setStyleSheet(
            "QPushButton { font-size: 10px; color: #1a5fb4; padding: 1px 4px; }"
            "QPushButton:hover { text-decoration: underline; }"
        )
        self.edit_pattern_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_pattern_btn.setToolTip("Öffnet Einstellungen > Dateinamen (Muster und Vorlagen)")
        self.edit_pattern_btn.clicked.connect(self.edit_pattern_requested)
        head_row.addWidget(self.edit_pattern_btn)
        suggestions_layout.addLayout(head_row)

        self.suggestions_list = QListWidget()
        self.suggestions_list.setFixedHeight(28)  # wird an die Anzahl angepasst
        self.suggestions_list.setToolTip(
            "Vorschlag anklicken, um Namen und Metadaten in die Felder unten zu übernehmen.\n"
            "Die zuletzt gewählte Art von Vorschlag steht beim nächsten Dokument ganz oben\n"
            "und wird automatisch als Dateiname vorgeschlagen."
        )
        self.suggestions_list.itemClicked.connect(self._on_suggestion_clicked)
        self.suggestions_list.installEventFilter(self)
        suggestions_layout.addWidget(self.suggestions_list)

        detail_layout.addWidget(suggestions_group)

        # Neuer Name
        name_group = QGroupBox("Neuer Dateiname")
        name_layout = QVBoxLayout(name_group)
        name_layout.setSpacing(3)
        name_layout.setContentsMargins(6, 4, 6, 6)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Neuen Dateinamen eingeben...")
        self.name_input.setToolTip(
            "Neuer Dateiname für die PDF - wird beim Klick auf einen Zielordner übernommen."
        )
        self.name_input.textChanged.connect(self._update_preview)
        font = QFont()
        font.setPointSize(11)
        self.name_input.setFont(font)
        name_layout.addWidget(self.name_input)

        # Vorschau
        self.preview_label = QLabel()
        self.preview_label.setStyleSheet(
            "font-family: monospace; padding: 3px 6px; background-color: #e8f5e9; "
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
        metadata_layout.setContentsMargins(6, 4, 6, 6)

        # Statusanzeige: Quelle der Metadaten
        self.metadata_status_label = QLabel("")
        self.metadata_status_label.setStyleSheet("font-size: 10px; padding: 2px 4px; border-radius: 3px;")
        self.metadata_status_label.hide()
        metadata_layout.addWidget(self.metadata_status_label)

        self._metadata_inputs = {}
        metadata_fields = [
            ("subject", "Kategorie"),
            ("korrespondent", "Korrespondent"),
            ("betrag_netto", "Betrag Netto"),
            ("betrag_brutto", "Betrag Brutto"),
            ("waehrung", "Währung"),
            ("mwst_satz", "MwSt-Satz"),
            ("iban", "IBAN"),
            ("steuerjahr", "Steuerjahr"),
            ("description", "Zusammenfassung"),
        ]
        # Kurze Erklärung je Feld (Issue #51) - hilft neuen Nutzern, die
        # Bedeutung der Metadaten-Felder ohne Nachfragen zu verstehen.
        field_tooltips = {
            "subject": "Kategorie des Dokuments (z.B. Rechnung, Vertrag).",
            "korrespondent": "Absender oder Firma des Dokuments.",
            "betrag_netto": "Rechnungsbetrag ohne MwSt.",
            "betrag_brutto": "Rechnungsbetrag inkl. MwSt.",
            "waehrung": "Währung des Betrags (z.B. EUR).",
            "mwst_satz": "Mehrwertsteuersatz in Prozent (z.B. 19).",
            "iban": "IBAN, falls im Dokument vorhanden.",
            "steuerjahr": "Steuerjahr, dem dieses Dokument zugeordnet wird.",
            "description": "Kurze Zusammenfassung des Dokumentinhalts.",
        }

        # Zweispaltig, damit unten mehr Platz fuer die PDF-Vorschau bleibt:
        # Kategorie|Korrespondent, Netto|Brutto, Waehrung|MwSt, IBAN|Steuerjahr;
        # die Zusammenfassung laeuft ueber die volle Breite.
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(3)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        for idx, (field_key, field_label) in enumerate(metadata_fields):
            label = QLabel(f"{field_label}:")
            label.setStyleSheet("color: #555; font-size: 10px;")

            if field_key == "description":
                input_field = QPlainTextEdit()
                input_field.setPlaceholderText(f"{field_label}...")
                input_field.setStyleSheet("font-size: 11px; padding: 2px;")
                input_field.setFixedHeight(58)  # drei Zeilen
                label.setAlignment(Qt.AlignmentFlag.AlignTop)
                row_idx = (idx + 1) // 2  # unter den Paaren
                grid.addWidget(label, row_idx, 0)
                grid.addWidget(input_field, row_idx, 1, 1, 3)
            else:
                if field_key == "subject":
                    input_field = _CategoryCombo()  # Aufklappliste (Issue #110)
                else:
                    input_field = QLineEdit()
                input_field.setPlaceholderText(f"{field_label}...")
                input_field.setStyleSheet("font-size: 10px; padding: 2px;")
                row_idx, col = divmod(idx, 2)
                grid.addWidget(label, row_idx, col * 2)
                grid.addWidget(input_field, row_idx, col * 2 + 1)

            tooltip = field_tooltips.get(field_key)
            if tooltip:
                input_field.setToolTip(tooltip)
            input_field.textChanged.connect(self._on_metadata_user_edit)
            self._metadata_inputs[field_key] = input_field

        metadata_layout.addLayout(grid)

        # Buttons: KI + Speichern
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.save_metadata_btn = QPushButton("Metadaten speichern")
        self.save_metadata_btn.setToolTip(
            "Metadaten in die PDF schreiben, ohne die Datei zu verschieben"
        )
        self.save_metadata_btn.setStyleSheet(
            "QPushButton { background-color: #1565c0; color: white; "
            "padding: 3px 10px; border: none; border-radius: 3px; font-size: 10px; }"
            "QPushButton:hover { background-color: #0d47a1; }"
            "QPushButton:disabled { background-color: #bdbdbd; color: #777; }"
        )
        self.save_metadata_btn.clicked.connect(self.save_metadata_requested)
        btn_row.addWidget(self.save_metadata_btn)

        self.rename_and_save_btn = QPushButton("Umbenennen + Metadaten speichern")
        self.rename_and_save_btn.setToolTip(
            "Dateinamen aktualisieren UND Metadaten in die PDF schreiben, ohne sie zu verschieben"
        )
        self.rename_and_save_btn.setStyleSheet(
            "QPushButton { background-color: #2e7d32; color: white; "
            "padding: 3px 10px; border: none; border-radius: 3px; font-size: 10px; }"
            "QPushButton:hover { background-color: #1b5e20; }"
            "QPushButton:disabled { background-color: #bdbdbd; color: #777; }"
        )
        self.rename_and_save_btn.clicked.connect(self.rename_and_save_metadata_requested)
        btn_row.addWidget(self.rename_and_save_btn)

        self.llm_btn = QPushButton("KI-Metadaten neu generieren")
        self.llm_btn.setToolTip(
            "Metadaten und Dateinamen per KI erneut aus dem PDF-Text vorschlagen lassen"
        )
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

        # Der Schalter "Nur verschieben" samt Hinweiszeile ist entfernt (Issue
        # #100): reines Verschieben geht per Drag & Drop oder Kontextmenue.
        detail_layout.addStretch()

        self.detail_container.hide()
        layout.addWidget(self.detail_container)

        # Suchergebnis-Bereich (Phase 17)
        self.search_container = QWidget()
        search_layout = QVBoxLayout(self.search_container)
        search_layout.setContentsMargins(0, 0, 0, 0)

        self.search_header = QLabel("Suchergebnisse")
        self.search_header.setStyleSheet(
            "font-size: 13px; font-weight: bold; padding: 6px; "
            "background-color: #e3f2fd; border-radius: 3px;"
        )
        search_layout.addWidget(self.search_header)

        self.search_results_list = QListWidget()
        self.search_results_list.setStyleSheet("font-size: 11px;")
        self.search_results_list.setToolTip("Doppelklick öffnet das Dokument im Standardprogramm.")
        self.search_results_list.itemDoubleClicked.connect(self._on_search_result_double_clicked)
        search_layout.addWidget(self.search_results_list)

        self.search_container.hide()
        layout.addWidget(self.search_container)

        scroll.setWidget(container)

        # PDF-Vorschau unten (Issue #74): vertikaler Splitter, oben die
        # Details, unten die Seitenansicht der ausgewählten PDF
        self.preview = PdfPreviewWidget(self, compact=True)
        self.preview.setToolTip(
            "Vorschau der ausgewählten PDF.\n"
            "Doppelklick auf die Seite oder „Groß“ öffnet die große Ansicht."
        )
        self.preview.enlarge_requested.connect(self.enlarge_preview_requested)
        self.preview.open_external_requested.connect(self.open_pdf_external_requested)
        # Markierten Text aus der Vorschau in ein Metadaten-Feld (Issue #109)
        self.preview.apply_text_requested.connect(self._on_preview_text_applied)

        self.splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.splitter.addWidget(scroll)
        self.splitter.addWidget(self.preview)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setCollapsible(0, False)
        self.splitter.setSizes([440, 400])

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(self.splitter)

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
        self._detected_date = detected_date
        self._has_learned_overrides = False

        # Header
        self.header_label.setText(f"Original: {pdf_path.name}")

        # Vorschau unten nachladen (Issue #74) - liest im Hintergrund
        self.preview.load_pdf(pdf_path)

        # Metadaten vorbefüllen
        self._metadata = {}

        # 1. Gespeicherte XMP-Metadaten werden im Hintergrund gelesen und danach
        #    nachgetragen (siehe _on_pdf_metadata_read). Bis dahin: Basis aus Analyse.
        self._saved_metadata_snapshot = {}
        self._pdf_field_keys = set()
        pdf_had_data = False
        self._start_metadata_reader(pdf_path)

        # 2. Nur wenn keine PDF-Metadaten vorhanden: Basis aus Analyse
        if not pdf_had_data:
            if keywords:
                self._metadata["subject"] = keywords[0].capitalize()
            if detected_date:
                try:
                    year = detected_date[:4]
                    if year.isdigit():
                        self._metadata["steuerjahr"] = year
                except Exception:
                    pass

            # LLM-Metadaten
            for s in self._suggestions:
                if s.metadata:
                    self._metadata.update(s.metadata)
                    break

            # Bekannter Korrespondent im Text (Issue #109): die vom Nutzer
            # gelernte Schreibweise schlaegt den KI-Vorschlag
            known = self._known_korrespondent(extracted_text)
            if known:
                self._metadata["korrespondent"] = known

            # Gelernte Korrespondent-Zuordnungen
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

            # Metadaten-Felder befüllen und Quelle setzen
            self._loading_metadata = True
            self._apply_metadata_to_fields()
            self._loading_metadata = False
            if any(self._metadata.values()):
                self._metadata_source = "llm"
            else:
                self._metadata_source = None

        # Vorschläge befüllen (nach den Metadaten: die Muster-Vorschlaege
        # rendern aus den Feldern)
        self._load_category_choices()
        self.refresh_settings()
        self._populate_suggestions()

        # GroupBox-Titel
        if self._has_learned_overrides:
            self.metadata_group.setTitle("Metadaten (gelernt + werden in PDF gespeichert)")
        else:
            self.metadata_group.setTitle("Metadaten (werden in PDF gespeichert)")

        self._refresh_save_btn()

        # Obersten Vorschlag (= zuletzt gewaehlte Art, Issue #106) als Name setzen
        self._auto_name = ""
        self.name_input.setText("")
        self._apply_top_suggestion()

        # UI umschalten
        self.placeholder.hide()
        self.search_container.hide()
        self.detail_container.show()

    def show_search_results(self, results: list[dict]):
        """Zeigt Suchergebnisse an."""
        self.placeholder.hide()
        self.detail_container.hide()
        self.search_container.show()

        self.search_header.setText(f"Suchergebnisse ({len(results)} Treffer)")
        self.search_results_list.clear()

        for r in results:
            filename = r.get("filename", "?")
            korrespondent = r.get("korrespondent", "")
            kategorie = r.get("kategorie", "")
            betrag = r.get("betrag", "")
            steuerjahr = r.get("steuerjahr", "")
            target = r.get("target_folder", "")
            snippet = r.get("text_snippet", "")
            # Phase 3 (Issue #25): pdf_id aus dem DB-Dict (32-stellige
            # Hex-UUID). Optional - nicht-gesetzte Werte werden
            # toleriert (alter Aufruf).
            pdf_id = r.get("pdf_id", "") or ""

            # Mehrzeilige Anzeige
            line1 = filename
            details = []
            if korrespondent:
                details.append(korrespondent)
            if kategorie:
                details.append(kategorie)
            if betrag:
                details.append(f"{betrag} EUR")
            if steuerjahr:
                details.append(f"SJ {steuerjahr}")
            line2 = " | ".join(details) if details else ""
            line3 = f"Ordner: {target}" if target else ""
            # Phase 3 (Issue #25): ID-Zeile mit gekuerzter pdf_id (falls
            # vorhanden). Vollstaendige UUID steht im toolTip.
            if pdf_id:
                short_id = pdf_id[:8] if len(pdf_id) >= 8 else pdf_id
                line4 = f"ID: {short_id}…"
            else:
                line4 = ""

            display = line1
            if line2:
                display += f"\n  {line2}"
            if line3:
                display += f"\n  {line3}"
            if line4:
                display += f"\n  {line4}"
            if snippet:
                # >>> und <<< aus FTS5-Snippet entfernen
                clean_snippet = snippet.replace(">>>", "[").replace("<<<", "]")
                display += f"\n  ...{clean_snippet}..."

            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, r.get("file_path", ""))
            # Phase 3 (Issue #25): toolTip enthaelt den vollstaendigen
            # Pfad UND die pdf_id (falls vorhanden). Damit der
            # Anwender die UUID per Hover einsehen / kopieren kann.
            tooltip = r.get("file_path", "")
            if pdf_id:
                tooltip = f"{tooltip}\npdf_id: {pdf_id}" if tooltip else f"pdf_id: {pdf_id}"
            item.setToolTip(tooltip)
            self.search_results_list.addItem(item)

    def _on_search_result_double_clicked(self, item: QListWidgetItem):
        """Öffnet ein Suchergebnis (integrierte Vorschau oder extern, je Einstellung)."""
        file_path = item.data(Qt.ItemDataRole.UserRole)
        if not file_path:
            return
        path = Path(file_path)
        if not path.exists():
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Datei nicht gefunden",
                f"Die Datei existiert nicht mehr:\n{file_path}"
            )
            return
        self.open_pdf_requested.emit(path)

    def clear(self):
        """Leert das Panel (kein PDF ausgewählt)."""
        self._current_pdf = None
        self._suggestions = []
        self._metadata = {}
        self._metadata_source = None
        self._saved_metadata_snapshot = {}
        self.preview.clear()

        self.name_input.clear()
        self.suggestions_list.clear()
        self.preview_label.clear()
        self.warning_label.hide()
        self.metadata_status_label.hide()
        for widget in self._metadata_inputs.values():
            if isinstance(widget, QPlainTextEdit):
                widget.clear()
            else:
                widget.clear()

        self.detail_container.hide()
        self.search_container.hide()
        self.placeholder.show()

    def get_new_name(self) -> Optional[str]:
        """Gibt den bereinigten Dateinamen zurück (mit .pdf) oder None."""
        from src.utils.filename_sanitizer import sanitize_filename
        return sanitize_filename(self.name_input.text()) or None

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

    def has_user_edits(self) -> bool:
        """True, wenn der Nutzer Dateiname oder Metadaten selbst geaendert hat.

        Wird genutzt, um das Panel nicht ueber Nutzereingaben hinweg zu
        aktualisieren, wenn spaeter KI-Vorschlaege aus dem Hintergrund eintreffen.
        """
        if self._metadata_source == "user":
            return True
        return self.name_input.text().strip() != self._auto_name

    def get_current_pdf(self) -> Optional[Path]:
        """Gibt den Pfad der aktuell angezeigten PDF zurück."""
        return self._current_pdf

    def _start_metadata_reader(self, pdf_path: Path):
        """Startet das Hintergrund-Lesen der XMP-Metadaten fuer pdf_path."""
        reader = _PdfMetadataReader(pdf_path, self)
        reader.finished_meta.connect(self._on_pdf_metadata_read)
        reader.finished.connect(reader.deleteLater)
        self._metadata_reader = reader
        reader.start()

    def _on_pdf_metadata_read(self, pdf_path: Path, pdf_meta):
        """Traegt gelesene PDF-Metadaten nach - nur, wenn die PDF noch ausgewaehlt ist."""
        if self._current_pdf != pdf_path:
            return
        if self._metadata_source == "user":
            return  # Nutzer hat inzwischen editiert - nicht ueberschreiben
        self._apply_pdf_metadata(pdf_meta)
        if self._saved_metadata_snapshot:
            self.metadata_group.setTitle("Metadaten (aus PDF gelesen, werden in PDF gespeichert)")
            self._populate_suggestions()  # Muster-Vorschlaege mit den PDF-Werten
            if not self.has_user_edits():
                self._apply_top_suggestion()

    def load_metadata_from_pdf(self, pdf_path: Path):
        """Liest XMP-Metadaten synchron aus der PDF und befüllt die Felder (Tests/Sonderfaelle)."""
        try:
            from src.core.pdf_metadata import read_metadata
            pdf_meta = read_metadata(pdf_path)
        except Exception:
            pdf_meta = None
        self._apply_pdf_metadata(pdf_meta)

    def _apply_pdf_metadata(self, pdf_meta):
        """Uebertraegt PDFMetadata in die Felder und setzt Quelle auf 'pdf'."""
        if pdf_meta is None or not pdf_meta.has_any_data():
            self._saved_metadata_snapshot = {}
            self._pdf_field_keys = set()
            return

        # Felder aus PDFMetadata in _metadata-Dict übertragen
        field_map = {
            "subject": pdf_meta.subject,
            "korrespondent": pdf_meta.korrespondent,
            "betrag_netto": pdf_meta.betrag_netto,
            "betrag_brutto": pdf_meta.betrag_brutto,
            "iban": pdf_meta.iban,
            "waehrung": pdf_meta.waehrung,
            "mwst_satz": pdf_meta.mwst_satz,
            "steuerjahr": pdf_meta.steuerjahr,
            "description": pdf_meta.description,
        }
        pdf_keys = set()
        for key, value in field_map.items():
            if value:
                self._metadata[key] = value
                pdf_keys.add(key)
        if not pdf_keys:
            # Nur Felder vorhanden, die das Panel nicht anzeigt (z.B. Titel)
            self._saved_metadata_snapshot = {}
            self._pdf_field_keys = set()
            return

        self._loading_metadata = True
        self._apply_metadata_to_fields()
        self._loading_metadata = False

        # Als "gespeichert" gilt nur, was wirklich im PDF steht. Werte aus
        # Analyse/KI, die daneben in den Feldern stehen, sind noch ungesichert.
        self._pdf_field_keys = pdf_keys
        current = self.get_metadata()
        self._saved_metadata_snapshot = {
            k: v for k, v in current.items() if k in pdf_keys
        }
        if set(current.keys()) <= pdf_keys:
            self._metadata_source = "pdf"
        else:
            self._metadata_source = "pdf_partial"
        self._refresh_save_btn()

    def mark_metadata_saved(self):
        """Markiert den aktuellen Zustand als gespeichert (nach erfolgreichem Schreiben)."""
        self._metadata_source = "pdf"
        self._saved_metadata_snapshot = self.get_metadata()
        self._pdf_field_keys = set(self._saved_metadata_snapshot.keys())
        self._refresh_save_btn()

    def _on_metadata_user_edit(self, *args):
        """Wird aufgerufen wenn der User ein Metadaten-Feld ändert."""
        if self._loading_metadata:
            return
        if self._metadata_source != "user":
            self._metadata_source = "user"
        self._refresh_save_btn()

    def _refresh_save_btn(self):
        """Aktualisiert Text und Status des Speichern-Buttons und des Status-Labels."""
        current = self.get_metadata()
        is_saved = (current == self._saved_metadata_snapshot) and bool(self._saved_metadata_snapshot)

        if is_saved:
            self.save_metadata_btn.setText("Metadaten gespeichert")
            self.save_metadata_btn.setEnabled(False)
        else:
            self.save_metadata_btn.setText("Metadaten speichern")
            self.save_metadata_btn.setEnabled(True)

        # rename_and_save_btn: ausgrauen, wenn nichts mehr zu tun ist
        # (Dateiname schon = Wunschname UND Metadaten bereits gespeichert)
        name_pending = False
        if self._current_pdf:
            desired = self.get_new_name()
            if desired and desired != self._current_pdf.name:
                name_pending = True
        if is_saved and not name_pending:
            self.rename_and_save_btn.setText("Bereits gespeichert")
            self.rename_and_save_btn.setEnabled(False)
        else:
            self.rename_and_save_btn.setText("Umbenennen + Metadaten speichern")
            self.rename_and_save_btn.setEnabled(True)

        # Status-Label
        source = self._metadata_source
        if source == "pdf":
            self.metadata_status_label.setText("Quelle: aus PDF gelesen")
            self.metadata_status_label.setStyleSheet(
                "font-size: 10px; padding: 2px 6px; border-radius: 3px; "
                "background-color: #e8f5e9; color: #2e7d32;"
            )
            self.metadata_status_label.show()
        elif source == "pdf_partial":
            self.metadata_status_label.setText(
                "Quelle: teils aus PDF gelesen, teils Vorschlag (noch nicht gespeichert)"
            )
            self.metadata_status_label.setStyleSheet(
                "font-size: 10px; padding: 2px 6px; border-radius: 3px; "
                "background-color: #fff8e1; color: #e65100;"
            )
            self.metadata_status_label.show()
        elif source == "llm":
            self.metadata_status_label.setText("Quelle: KI-Vorschlag (noch nicht gespeichert)")
            self.metadata_status_label.setStyleSheet(
                "font-size: 10px; padding: 2px 6px; border-radius: 3px; "
                "background-color: #f3e5f5; color: #6a1b9a;"
            )
            self.metadata_status_label.show()
        elif source == "user":
            self.metadata_status_label.setText("Quelle: editiert (noch nicht gespeichert)")
            self.metadata_status_label.setStyleSheet(
                "font-size: 10px; padding: 2px 6px; border-radius: 3px; "
                "background-color: #fff8e1; color: #e65100;"
            )
            self.metadata_status_label.show()
        else:
            self.metadata_status_label.hide()

    # === Interne Methoden ===

    def _populate_suggestions(self):
        """Fuellt die Vorschlagsliste: eine einheitliche, nach Art sortierte Liste.

        KI-Vorschlaege, ein Muster-Vorschlag je Vorlage (aus den Metadaten
        dieses Dokuments) und die einfachen Analyse-Vorschlaege stehen in der
        Rangfolge aus der Config (``suggestion_kind_order``, Issue #106): die
        zuletzt angeklickte Art zuoberst.
        """
        from src.core.suggestion_order import (
            KIND_DATE, KIND_LEARNED, kind_from_reason, sort_by_kind,
        )

        self.suggestions_list.clear()

        pairs: list[tuple[RenameSuggestion, str]] = []
        for s in self._suggestions:
            kind = kind_from_reason(s.reason)
            if kind in (KIND_DATE, KIND_LEARNED):
                # "Nur Datum" ist als Dateiname unbrauchbar; "Gelernt" (fremder
                # alter Dateiname) ebenso - die Historie fliesst stattdessen als
                # Beispiel in den KI-Prompt (src.core.rename_examples)
                continue
            pairs.append((s, kind))
        pattern_pairs = self._pattern_suggestions()
        pairs.extend(pattern_pairs)
        pairs = sort_by_kind(pairs, self._kind_order())

        # Doppelte Namen (z.B. KI folgt exakt dem Muster): hoeher gereihte Zeile gewinnt
        seen: set[str] = set()
        displayed: list[tuple[RenameSuggestion, str]] = []
        for s, kind in pairs:
            key = s.name.lower()
            if key in seen:
                continue
            seen.add(key)
            displayed.append((s, kind))
        self._displayed_suggestions = [s for s, _k in displayed]
        self._displayed_kinds = [k for _s, k in displayed]

        if not displayed:
            item = QListWidgetItem("Keine Vorschläge verfügbar")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.suggestions_list.addItem(item)
            self._fit_suggestions_height()
            return

        pattern_rows = {id(s) for s, _k in pattern_pairs}
        for suggestion, _kind in displayed:
            confidence_pct = int(suggestion.confidence * 100)
            display_text = f"{suggestion.name}"
            if suggestion.reason:
                display_text += f"  [{suggestion.reason}]"

            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, suggestion.name)

            if id(suggestion) in pattern_rows:
                item.setToolTip(
                    "Nach diesem Dateinamen-Muster aus den Metadaten dieses "
                    "Dokuments gebildet. Anklicken übernimmt den Namen."
                )
                item.setBackground(QColor(214, 234, 255))  # hellblau = Muster
                item.setForeground(QColor(20, 60, 120))
            else:
                item.setToolTip(f"Konfidenz: {confidence_pct}%\n{suggestion.reason}")
                if confidence_pct >= 70:
                    item.setBackground(Qt.GlobalColor.green)
                    item.setForeground(Qt.GlobalColor.darkGreen)
                elif confidence_pct >= 40:
                    item.setBackground(Qt.GlobalColor.yellow)

            self.suggestions_list.addItem(item)
        self._fit_suggestions_height()

    def _apply_top_suggestion(self):
        """Uebernimmt die oberste Zeile als (automatischen) Dateinamen."""
        if not self._displayed_suggestions:
            return
        name = self._displayed_suggestions[0].name.replace('.pdf', '')
        self.name_input.setText(name)
        self._auto_name = name

    # -- Metadaten-Hilfen (Issues #109/#110) ------------------------------- #

    def _load_category_choices(self):
        """Aufklappliste der Kategorie: haeufigste 10 der Sammlung + Standard."""
        from src.core.metadata_choices import category_choices

        top: list[str] = []
        try:
            from src.utils.database import get_database
            top = get_database().get_top_kategorien(10)
        except Exception:
            pass
        widget = self._metadata_inputs.get("subject")
        if isinstance(widget, _CategoryCombo):
            widget.set_choices(category_choices(top))

    def _known_korrespondent(self, text: str) -> Optional[str]:
        """Bekannter Korrespondent (Verwaltung), der im Dokumenttext vorkommt."""
        if not text:
            return None
        from src.core.korrespondent_match import find_known_korrespondent

        try:
            from src.utils.database import get_database
            entries = get_database().list_korrespondenten()
        except Exception:
            return None
        return find_known_korrespondent(text, entries)

    def _on_preview_text_applied(self, field_key: str, text: str):
        """Markierter Text aus der Vorschau -> Metadaten-Feld; Korrespondent wird gelernt."""
        from src.core.metadata_choices import normalize_for_field

        text = normalize_for_field(field_key, text)
        widget = self._metadata_inputs.get(field_key)
        if widget is None or not text:
            return
        if isinstance(widget, QPlainTextEdit):
            widget.setPlainText(text)
        else:
            widget.setText(text)
        widget.setFocus()
        if field_key == "korrespondent":
            self._learn_korrespondent(text)

    def _learn_korrespondent(self, name: str):
        """Nimmt den Namen in die Korrespondenten-Verwaltung auf (Issue #109).

        Bei spaeteren Dokumenten, in deren Text der Name vorkommt, wird er
        automatisch als Korrespondent gesetzt (siehe _known_korrespondent).
        """
        try:
            from src.utils.database import get_database
            get_database().add_or_update_korrespondent(name)
        except Exception as e:  # noqa: BLE001 - Lernen ist Komfort, kein Muss
            logger.debug(f"Korrespondent nicht gelernt: {e}")

    # -- Kopfzeile: Ordnerstruktur-Schalter --------------------------------- #

    def refresh_settings(self):
        """Gleicht die Kopfzeile an die Config an (nach Einstellungs-Aenderung)."""
        try:
            from src.utils.config import get_config
            enabled = bool(get_config().get("folder_naming_enabled", False))
        except Exception:
            enabled = False
        self.folder_naming_checkbox.blockSignals(True)
        self.folder_naming_checkbox.setChecked(enabled)
        self.folder_naming_checkbox.blockSignals(False)

    def _on_folder_naming_toggled(self, checked: bool):
        """Schalter in der Kopfzeile schreibt dieselbe Einstellung wie der Dialog."""
        try:
            from src.utils.config import get_config
            get_config().set("folder_naming_enabled", bool(checked))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Ordnerstruktur-Schalter nicht gespeichert: {e}")

    # -- Rangfolge der Vorschlaege (Issue #106) --------------------------- #

    def _config_pattern(self) -> str:
        """Dateinamen-Muster aus Einstellungen > Dateinamen (migriert)."""
        from src.core.filename_placeholders import migrate_legacy_pattern

        try:
            from src.utils.config import get_config
            return migrate_legacy_pattern(get_config().get("filename_pattern", "") or "")
        except Exception:
            return ""

    def _custom_patterns(self) -> list[tuple[str, str]]:
        """Vom Nutzer gespeicherte Muster (Einstellungen > Dateinamen)."""
        from src.core.filename_placeholders import CUSTOM_PATTERNS_KEY, load_custom_patterns

        try:
            from src.utils.config import get_config
            return load_custom_patterns(get_config().get(CUSTOM_PATTERNS_KEY, []))
        except Exception:
            return []

    def _kind_order(self) -> list[str]:
        """Gemerkte Rangfolge der Vorschlagsarten, um fehlende Arten ergaenzt."""
        from src.core.suggestion_order import CONFIG_KEY, effective_order

        saved = None
        try:
            from src.utils.config import get_config
            saved = get_config().get(CONFIG_KEY, None)
        except Exception:
            pass
        return effective_order(saved, self._config_pattern(), self._custom_patterns())

    def _remember_kind(self, kind: str):
        """Die angeklickte Art wird beim naechsten Dokument zuoberst gereiht."""
        from src.core.suggestion_order import CONFIG_KEY, KIND_OTHER, promote

        if not kind or kind == KIND_OTHER:
            return
        try:
            from src.utils.config import get_config
            get_config().set(CONFIG_KEY, promote(self._kind_order(), kind))
        except Exception as e:  # noqa: BLE001 - Rangfolge ist Komfort, kein Muss
            logger.debug(f"Vorschlags-Rangfolge nicht gespeichert: {e}")

    def _pattern_values(self) -> dict:
        """Platzhalter-Werte aus den aktuellen Feldern + Dokumentdatum."""
        from src.core.filename_placeholders import placeholder_values_from_metadata

        initials = ""
        try:
            from src.utils.config import get_config
            from src.ml.llm_provider import derive_initials
            config = get_config()
            initials = (config.get("owner_initials", "") or "").strip()
            if not initials:
                initials = derive_initials(config.get("owner_name", "") or "")
        except Exception:
            pass

        doc_date = self._detected_date
        if not doc_date:
            # Rueckfall: fuehrendes Datum eines KI-Vorschlags (YYYY-MM-DD)
            for s in self._suggestions:
                if s.reason == "KI-Vorschlag" and len(s.name) >= 10:
                    head = s.name[:10]
                    if head[4] == "-" and head[7] == "-" and head.replace("-", "").isdigit():
                        doc_date = head
                        break
        return placeholder_values_from_metadata(self.get_metadata(), doc_date, initials)

    def _pattern_suggestions(self) -> list[tuple[RenameSuggestion, str]]:
        """Ein Vorschlag je Vorlage (und eigenem Einstellungs-Muster), mit Art.

        Vorlagen, bei denen weniger als zwei Platzhalter einen Wert haben,
        fallen weg - „Rechnung.pdf“ oder ein blosses Datum sind als
        Dateiname unbrauchbar.
        """
        from src.core.filename_placeholders import pattern_choices, render_with_values
        from src.core.suggestion_order import pattern_kind

        if not self._current_pdf:
            return []
        values = self._pattern_values()
        result: list[tuple[RenameSuggestion, str]] = []
        for label, pattern in pattern_choices(self._config_pattern(), self._custom_patterns()):
            if not pattern:
                continue  # "Standard" = kein Muster
            name = render_with_values(pattern, values, min_values=2)
            if not name:
                continue
            short = label.split(" (")[0]
            result.append((
                RenameSuggestion(name=name, reason=f"Muster: {short}", confidence=0.75),
                pattern_kind(pattern),
            ))
        return result

    def _fit_suggestions_height(self):
        """Liste nur so hoch wie noetig (max. ~8 Zeilen) - spart Platz fuer die Vorschau.

        Ragen Zeilen ueber die Breite hinaus (lange Muster-Namen), blendet Qt
        einen horizontalen Scrollbalken ein - der wird mitgerechnet, sonst
        verdeckt er die letzte Zeile.
        """
        lst = self.suggestions_list
        count = max(1, lst.count())
        row_h = lst.sizeHintForRow(0)
        if row_h <= 0:
            row_h = 22
        frame = 2 * lst.frameWidth() + 4
        extra = 0
        if lst.count() and lst.viewport().width() > 0:
            fm = lst.fontMetrics()
            widest = max(fm.horizontalAdvance(lst.item(i).text()) for i in range(lst.count()))
            if widest + 8 > lst.viewport().width():
                extra = lst.horizontalScrollBar().sizeHint().height()
        lst.setFixedHeight(min(8, count) * row_h + frame + extra)

    def eventFilter(self, obj, event):
        # Breite der Liste aendert sich (Fenster/Splitter): Scrollbalken-Bedarf neu pruefen
        if obj is self.suggestions_list and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._fit_suggestions_height)
        return super().eventFilter(obj, event)

    def _on_suggestion_clicked(self, item: QListWidgetItem):
        """Übernimmt Vorschlag in Eingabefeld + Metadaten und merkt sich die Art."""
        name = item.data(Qt.ItemDataRole.UserRole)
        if name:
            self.name_input.setText(name.replace('.pdf', ''))

            idx = self.suggestions_list.row(item)
            if 0 <= idx < len(self._displayed_kinds):
                self._remember_kind(self._displayed_kinds[idx])

            # Metadaten des Vorschlags übernehmen
            shown = self._displayed_suggestions
            if idx < len(shown) and shown[idx].metadata:
                self._loading_metadata = True
                for key, value in shown[idx].metadata.items():
                    widget = self._metadata_inputs.get(key)
                    if widget:
                        if isinstance(widget, QPlainTextEdit):
                            widget.setPlainText(str(value))
                        else:
                            widget.setText(str(value))
                self._loading_metadata = False
                if self._metadata_source != "pdf":
                    self._metadata_source = "llm"
                self._refresh_save_btn()

    def _apply_metadata_to_fields(self):
        """Setzt die Metadaten-Werte in die Eingabefelder."""
        for key, widget in self._metadata_inputs.items():
            value = self._metadata.get(key, "")
            if isinstance(widget, QPlainTextEdit):
                widget.setPlainText(str(value) if value else "")
            else:
                widget.setText(str(value) if value else "")

    def _update_preview(self, text: str):
        """Aktualisiert die Dateinamen-Vorschau.

        Die Vorschau-Zeile erscheint nur, wenn der endgueltige Name vom
        Eingetippten abweicht (ersetzte Zeichen, E-Mail, ungueltig) - sonst
        stuende derselbe Name zweimal untereinander (Issue #101).
        """
        if not text.strip():
            self.preview_label.clear()
            self.preview_label.hide()
            self.warning_label.hide()
            self._refresh_save_btn()
            return

        from src.utils.filename_sanitizer import (
            contains_email, find_problem_chars, sanitize_filename,
        )

        preview_name = sanitize_filename(text)
        found_invalid = find_problem_chars(text)
        has_email = contains_email(text)

        if not preview_name:
            self.warning_label.setText("Name besteht nur aus ungültigen Zeichen")
            self.warning_label.show()
            self.preview_label.setStyleSheet(
                "font-family: monospace; padding: 6px; background-color: #ffebee; "
                "border: 1px solid #ef9a9a; border-radius: 3px; font-size: 11px;"
            )
            preview_name = "(ungültig)"
        elif found_invalid or has_email:
            hints = []
            if has_email:
                hints.append("E-Mail-Adresse → Name")
            if found_invalid:
                shown = ' '.join('␣' if c.isspace() else c for c in found_invalid)
                hints.append(f"{shown} → _")
            self.warning_label.setText("Wird ersetzt: " + ", ".join(hints))
            self.warning_label.show()
            self.preview_label.setStyleSheet(
                "font-family: monospace; padding: 6px; background-color: #fff8e1; "
                "border: 1px solid #ffe082; border-radius: 3px; font-size: 11px;"
            )
        else:
            self.warning_label.hide()
            self.preview_label.setStyleSheet(
                "font-family: monospace; padding: 6px; background-color: #e8f5e9; "
                "border: 1px solid #a5d6a7; border-radius: 3px; font-size: 11px;"
            )

        self._refresh_save_btn()

        self.preview_label.setText(preview_name)
        # Nur zeigen, wenn sich etwas aendert (".pdf" haengt ohnehin an)
        unchanged = preview_name == f"{text.strip()}.pdf" or preview_name == text.strip()
        self.preview_label.setVisible(not unchanged)

    LLM_BTN_TEXT = "KI-Metadaten neu generieren"

    def _request_llm_metadata(self):
        """Startet den KI-Aufruf fuer Metadaten im Hintergrund (Issue #68)."""
        if not self._current_pdf:
            return
        if self._llm_worker is not None and self._llm_worker.isRunning():
            return

        try:
            from src.ml.hybrid_classifier import get_hybrid_classifier

            classifier = get_hybrid_classifier()
            if not classifier.is_llm_available():
                return

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
        except Exception as e:
            print(f"LLM-Metadaten Fehler: {e}")
            return

        self.llm_btn.setEnabled(False)
        self._llm_started = time.monotonic()
        self._tick_llm_button()
        self._llm_timer.start()

        worker = _LLMMetadataWorker(
            classifier, self._current_pdf, extracted_text, keywords,
            detected_date, file_date, self,
        )
        worker.result_ready.connect(self._on_llm_metadata_ready)
        worker.finished.connect(worker.deleteLater)
        self._llm_worker = worker
        worker.start()

    def _show_llm_error(self, error: str):
        """Zeigt einen KI-Fehler im Status-Label des Metadaten-Bereichs an."""
        text = str(error).strip().splitlines()[0] if error else "KI-Fehler"
        if len(text) > 160:
            text = text[:157] + "…"
        self.metadata_status_label.setText(f"KI-Fehler: {text}")
        self.metadata_status_label.setToolTip(str(error))
        self.metadata_status_label.setStyleSheet(
            "font-size: 10px; padding: 2px 6px; border-radius: 3px; "
            "background-color: #ffebee; color: #b71c1c;"
        )
        self.metadata_status_label.show()

    def _tick_llm_button(self):
        """Button zeigt laufende Uhr + Schaetzung, solange die KI arbeitet."""
        if self._llm_started is None:
            return
        text = f"KI arbeitet… {format_elapsed(time.monotonic() - self._llm_started)}"
        estimate = format_estimate(get_llm_activity().estimate(KIND_SUGGEST))
        if estimate:
            text += f" ({estimate})"
        self.llm_btn.setText(text)

    def _on_llm_metadata_ready(self, pdf_path: Path, suggestions: list, error: str):
        """Traegt das KI-Ergebnis ein - nur, wenn die PDF noch ausgewaehlt ist."""
        self._llm_timer.stop()
        self._llm_started = None
        self._llm_worker = None
        self.llm_btn.setEnabled(True)
        self.llm_btn.setText(self.LLM_BTN_TEXT)

        if error:
            print(f"LLM-Metadaten Fehler: {error}")
            if pdf_path == self._current_pdf:
                self._show_llm_error(error)
            return
        if pdf_path != self._current_pdf:
            return

        try:
            for s in suggestions:
                if s.source == "llm" and s.metadata:
                    self.name_input.setText(s.filename.replace('.pdf', ''))
                    self._loading_metadata = True
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
                    self._loading_metadata = False
                    self._metadata_source = "llm"
                    self._refresh_save_btn()
                    break
            else:
                for s in suggestions:
                    if s.source == "llm":
                        self.name_input.setText(s.filename.replace('.pdf', ''))
                        break
                else:
                    # Kein KI-Vorschlag angekommen - Grund anzeigen (z.B. Token-Limit)
                    try:
                        from src.ml.hybrid_classifier import get_hybrid_classifier
                        reason = get_hybrid_classifier().last_llm_error
                    except Exception:
                        reason = None
                    self._show_llm_error(reason or "KI hat keinen Vorschlag geliefert.")

            from src.core.pdf_cache import get_pdf_cache, LLMSuggestion as CacheLLMSuggestion
            llm_cached = [
                CacheLLMSuggestion(filename=s.filename, confidence=s.confidence, source=s.source, metadata=s.metadata)
                for s in suggestions if s.source == "llm"
            ]
            if llm_cached:
                # Frische KI-Namen auch in der Liste zeigen; der Muster-Vorschlag
                # rendert mit den neuen Metadaten (Issue #99)
                fresh = [
                    RenameSuggestion(name=s.filename, reason="KI-Vorschlag",
                                     confidence=s.confidence, metadata=s.metadata)
                    for s in llm_cached
                ]
                self._suggestions = fresh + [
                    s for s in self._suggestions if s.reason != "KI-Vorschlag"
                ]
                self._populate_suggestions()
                get_pdf_cache().update_llm_suggestions(pdf_path, llm_cached)
        except Exception as e:
            print(f"LLM-Metadaten Fehler: {e}")

"""
Erststart-Wizard fuer PDF Sortier Meister

Fuehrt den Benutzer beim ersten Start durch:
  1. Begruessung
  2. Scan-Ordner waehlen (mit Default-Vorschlag)
  3. Zielordner waehlen (mit Default-Vorschlag)
  4. LLM-Provider waehlen (mit Hardware-Erkennung und Ollama-Status)
  5. API-Key eingeben bzw. Ollama einrichten (Modelle anzeigen/herunterladen)
  6. Dokumentensuche (optional: Ordner, Mails, Texterkennung, Hintergrund;
     Uebernahme einer vorhandenen PDFsuche)
  7. Abschluss

Der Wizard kann auch ueber das Extras-Menue erneut geoeffnet werden.
"""

import sys
import threading
from pathlib import Path

from PyQt6.QtWidgets import (
    QWizard, QWizardPage, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog,
    QRadioButton, QButtonGroup, QWidget, QCheckBox,
    QDialog, QComboBox, QProgressBar, QListWidget, QListWidgetItem,
)
from PyQt6.QtCore import Qt, QUrl, QThread, QStandardPaths, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont

from src.utils.config import get_config
from src.i18n import tr


# Seiten-IDs
PAGE_WELCOME = 0
PAGE_SCAN_FOLDER = 1
PAGE_TARGET_FOLDER = 2
PAGE_PROVIDER = 3
PAGE_API_KEY = 4
PAGE_SUCHE = 5
PAGE_DONE = 6

# Provider-Konstanten (Index -> interner Name). Reihenfolge = Empfehlungsrang:
# Ollama (lokal, kein Key) zuerst, dann Cloud-Anbieter, "Ohne KI" ganz unten
# (Issue #67 - KI ist ein Hauptfeature, nicht "optional").
# LM Studio (Issue #45) erscheint nur, wenn es bereits laeuft - die App
# bietet es nie zum Download an.
_PROVIDER_IDS = ["ollama", "lmstudio", "ollama_cloud", "openrouter", "poe", "claude", "openai", "none"]
_PROVIDER_LABELS = [
    tr("Ollama (lokal auf diesem Rechner, empfohlen — kein API-Key noetig)"),
    tr("LM Studio (laeuft bereits auf diesem Rechner — kein API-Key noetig)"),
    tr("Ollama Cloud (Ollama-Modelle in der Cloud, API-Key)"),
    tr("OpenRouter (viele KI-Modelle, ein API-Key)"),
    tr("Poe.com (viele KI-Modelle, ein API-Key)"),
    tr("Anthropic Claude"),
    tr("OpenAI GPT"),
    tr("Ohne KI-Assistent (nur einfache lokale Stichwort-Zuordnung — stark eingeschraenkt)"),
]
_PROVIDER_URLS = {
    "claude": "https://console.anthropic.com/settings/keys",
    "openai": "https://platform.openai.com/api-keys",
    "ollama": "https://ollama.com/download",
    "ollama_cloud": "https://ollama.com/settings/keys",
    "openrouter": "https://openrouter.ai/keys",
    "poe": "https://poe.com/api_key",
}
_PROVIDER_KEY_HINTS = {
    "claude": tr('Beginnt mit "sk-ant-..."'),
    "openai": tr('Beginnt mit "sk-..."'),
    "ollama": tr("Leer lassen fuer Standard (http://localhost:11434)"),
    "ollama_cloud": tr("Zu finden auf ollama.com/settings/keys"),
    "openrouter": tr('Beginnt mit "sk-or-..."'),
    "poe": tr("Zu finden auf poe.com/api_key"),
}

OLLAMA_LOCAL_URL = "http://localhost:11434"
OLLAMA_CLOUD_DEFAULT_MODEL = "gpt-oss:120b"
OLLAMA_FALLBACK_MODEL = "gemma3:4b"


def _documents_dir() -> Path:
    """Dokumente-Ordner des Benutzers (Windows: "Eigene Dokumente",
    macOS: ~/Documents). Fallback: Home-Verzeichnis, falls Qt nichts liefert
    (z. B. in seltenen Systemkonfigurationen)."""
    path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    return Path(path) if path else Path.home()


def default_scan_folder() -> Path:
    """Vorschlag fuer den Scan-Ordner (Issue #61), solange noch keiner
    konfiguriert ist."""
    return _documents_dir() / "Scans"


def default_target_folder() -> Path:
    """Vorschlag fuer den Zielordner (Issue #64), solange noch keiner
    konfiguriert ist."""
    return _documents_dir() / "PDF-Sammlung"


def detect_ollama_environment() -> dict:
    """
    Ermittelt Ollama-Installation, Serverstatus und Hardware-Empfehlung,
    ausserdem ein laufendes LM Studio ("lmstudio_models": Modellliste oder
    None, wenn es nicht antwortet).

    Laeuft in einem Hintergrund-Thread der Provider-Seite; in Tests wird
    die Funktion durch eine Attrappe ersetzt.
    """
    from src.ml.lmstudio_provider import detect_lm_studio
    from src.ml.ollama_launcher import find_ollama_executable, quick_ping
    from src.utils.hardware import detect_and_recommend

    exe = find_ollama_executable()
    running = quick_ping(OLLAMA_LOCAL_URL, timeout=0.5)
    return {
        "exe": exe,
        "installed": bool(exe) or running,
        "running": running,
        "recommendation": detect_and_recommend(),
        "lmstudio_models": detect_lm_studio(timeout=0.5),
    }


def probe_ollama_models() -> tuple[bool, str, list[str]]:
    """Startet Ollama bei Bedarf und liefert (ok, meldung, modelle)."""
    from src.ml.ollama_launcher import ensure_running, list_models

    ok, msg = ensure_running(OLLAMA_LOCAL_URL)
    if not ok:
        return False, msg, []
    return True, msg, list_models(OLLAMA_LOCAL_URL)


class _DetectThread(QThread):
    done = pyqtSignal(object)

    def run(self):
        try:
            result = detect_ollama_environment()
        except Exception as e:  # Erkennung darf den Wizard nie blockieren
            result = {"exe": None, "installed": False, "running": False,
                      "recommendation": None, "lmstudio_models": None, "error": str(e)}
        self.done.emit(result)


class _ModelsThread(QThread):
    done = pyqtSignal(bool, str, object)

    def run(self):
        try:
            ok, msg, models = probe_ollama_models()
        except Exception as e:
            ok, msg, models = False, str(e), []
        self.done.emit(ok, msg, models)


class _PullThread(QThread):
    progress = pyqtSignal(int, str)
    finished_pull = pyqtSignal(bool, str)

    def __init__(self, model: str, parent=None):
        super().__init__(parent)
        self._model = model
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        from src.ml.ollama_launcher import pull_model

        ok, msg = pull_model(
            OLLAMA_LOCAL_URL, self._model,
            progress_cb=lambda p, s: self.progress.emit(p, s),
            should_cancel=self._cancel.is_set,
        )
        self.finished_pull.emit(ok, msg)


class WelcomePage(QWizardPage):
    """Seite 1: Begruessung."""

    def __init__(self):
        super().__init__()
        self.setTitle(tr("Willkommen bei PDF Sortier Meister!"))
        self.setSubTitle(
            tr("Dieses kurze Setup dauert etwa 2 Minuten.\n"
            "Sie koennen jeden Schritt ueberspringen und spaeter aendern.")
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        text = QLabel(
            tr("<b>Was macht PDF Sortier Meister?</b><br><br>"
            "Das Programm schaut Ihre gescannten PDFs an und schlaegt Ihnen vor,\n"
            "in welchen Ordner jedes Dokument gehoert — zum Beispiel:\n"
            "<ul>"
            "<li>Rechnung &rarr; Ordner <i>Rechnungen/2024</i></li>"
            "<li>Kontoauszug &rarr; Ordner <i>Bank/Sparkasse</i></li>"
            "<li>Arztbrief &rarr; Ordner <i>Gesundheit</i></li>"
            "</ul>"
            "Sie bestimmen immer selbst, was wirklich passiert.\n"
            "Das Programm verschiebt nichts ohne Ihre Zustimmung.<br><br>"
            "<b>KI-Assistent (empfohlen):</b> Erst mit einer KI entfaltet das\n"
            "Programm sein volles Potential — die Vorschlaege werden deutlich\n"
            "besser. Am einfachsten geht das mit <b>Ollama</b>, das kostenlos\n"
            "lokal auf Ihrem PC laeuft (kein API-Key noetig, Ihre Dokumente\n"
            "bleiben auf diesem Rechner). Wer lieber einen Cloud-Anbieter nutzt\n"
            "(z. B. weil er ein Abo hat oder dem Anbieter vertraut), kann\n"
            "stattdessen einen API-Key hinterlegen. Im naechsten Schritt waehlen\n"
            "Sie aus — ganz ohne KI geht es zur Not auch, dann sortiert nur\n"
            "eine einfache Stichwort-Zuordnung.")
        )
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addStretch()


class ScanFolderPage(QWizardPage):
    """Seite 2: Scan-Ordner waehlen."""

    def __init__(self):
        super().__init__()
        self.setTitle(tr("Schritt 1: Scan-Ordner auswaehlen"))
        self.setSubTitle(
            tr("Hier landen Ihre unsortierten (gescannten) PDFs — hierhin\n"
            "speichert auch Ihr Scanner. Diesen Ordner wird das Programm\n"
            "beim Start anzeigen.")
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        info = QLabel(
            tr("Ein Vorschlag ist schon eingetragen. Sie koennen ihn uebernehmen\n"
            "oder einen anderen Ordner waehlen (z. B. ein Netzlaufwerk).")
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(tr("Noch kein Ordner ausgewaehlt ..."))
        self.path_edit.setReadOnly(True)
        path_layout.addWidget(self.path_edit, 1)

        browse_btn = QPushButton(tr("Ordner auswaehlen ..."))
        browse_btn.clicked.connect(self._browse)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)

        skip_info = QLabel(
            tr("<i>Sie koennen auch jetzt ueberspringen und den Ordner spaeter\n"
            "unter Extras → Einstellungen festlegen.</i>")
        )
        skip_info.setStyleSheet("color: gray;")
        layout.addWidget(skip_info)

        layout.addStretch()

        # Bestehenden Wert voreintragen; ohne bisherige Konfiguration einen
        # sinnvollen Default vorschlagen (Issue #61), den der Nutzer per
        # "Weiter" einfach uebernehmen kann.
        config = get_config()
        existing = config.get_scan_folder()
        if existing:
            self.path_edit.setText(str(existing))
        else:
            self.path_edit.setText(str(default_scan_folder()))

        # Wird erst wahr, wenn der Nutzer diese Seite tatsaechlich sieht
        # oder den Pfad manuell aendert - verhindert, dass ein reiner
        # Default-Vorschlag beim sofortigen "Spaeter" auf der
        # Begruessungsseite ungefragt gespeichert/angelegt wird (siehe
        # SetupWizard._on_finished).
        self._visited = False

    def initializePage(self):
        self._visited = True

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, tr("Scan-Ordner auswaehlen"), str(self.path_edit.text() or "")
        )
        if folder:
            self.path_edit.setText(folder)
            self._visited = True

    def get_folder(self) -> str:
        return self.path_edit.text().strip()

    def was_visited(self) -> bool:
        """True, wenn die Seite betreten wurde oder der Pfad manuell
        geaendert wurde (siehe SetupWizard._on_finished)."""
        return self._visited


class TargetFolderPage(QWizardPage):
    """Seite 3: Zielordner waehlen (Issue #64) - wohin sortierte PDFs wandern."""

    def __init__(self):
        super().__init__()
        self.setTitle(tr("Schritt 2: Zielordner auswaehlen"))
        self.setSubTitle(
            tr("Hierhin werden die sortierten PDFs verschoben — in Unterordner,\n"
            "die Sie selbst anlegen oder die Ihnen vorgeschlagen werden.")
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        info = QLabel(
            tr("Ein Vorschlag ist schon eingetragen. Sie koennen ihn uebernehmen\n"
            "oder einen anderen Ordner waehlen.")
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(tr("Noch kein Ordner ausgewaehlt ..."))
        self.path_edit.setReadOnly(True)
        path_layout.addWidget(self.path_edit, 1)

        browse_btn = QPushButton(tr("Ordner auswaehlen ..."))
        browse_btn.clicked.connect(self._browse)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)

        skip_info = QLabel(
            tr("<i>Sie koennen auch jetzt ueberspringen und den Ordner spaeter\n"
            "unter Extras → Einstellungen festlegen.</i>")
        )
        skip_info.setStyleSheet("color: gray;")
        layout.addWidget(skip_info)

        layout.addStretch()

        # Bestehenden Wert voreintragen; ohne bisherigen Zielordner einen
        # sinnvollen Default vorschlagen (Issue #64).
        config = get_config()
        existing = config.get_target_folders()
        if existing:
            self.path_edit.setText(str(existing[0]))
        else:
            self.path_edit.setText(str(default_target_folder()))

        # Siehe ScanFolderPage._visited: erst wahr nach tatsaechlichem
        # Besuch der Seite bzw. manueller Aenderung des Pfads.
        self._visited = False

    def initializePage(self):
        self._visited = True

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, tr("Zielordner auswaehlen"), str(self.path_edit.text() or "")
        )
        if folder:
            self.path_edit.setText(folder)
            self._visited = True

    def get_folder(self) -> str:
        return self.path_edit.text().strip()

    def was_visited(self) -> bool:
        """True, wenn die Seite betreten wurde oder der Pfad manuell
        geaendert wurde (siehe SetupWizard._on_finished)."""
        return self._visited


class ProviderPage(QWizardPage):
    """Seite 4: LLM-Provider waehlen - mit Ollama-Status und Hardware-Empfehlung."""

    def __init__(self):
        super().__init__()
        self.setTitle(tr("Schritt 3: KI-Assistent auswaehlen"))
        self.setSubTitle(
            tr("Ein KI-Assistent liefert deutlich bessere Vorschlaege — wir empfehlen\n"
            "Ollama (laeuft lokal, kostenlos). Ganz ohne KI geht es zur Not auch.")
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        self._button_group = QButtonGroup(self)
        self._radios: list[QRadioButton] = []

        for i, label in enumerate(_PROVIDER_LABELS):
            rb = QRadioButton(label)
            self._button_group.addButton(rb, i)
            self._radios.append(rb)
            layout.addWidget(rb)
            if _PROVIDER_IDS[i] == "ollama":
                # Vorauswahl: Ollama, bis die Hardware-Erkennung ggf. eine
                # andere Empfehlung liefert (siehe _on_detected) oder eine
                # bestehende Nutzer-Entscheidung geladen wird (siehe unten).
                rb.setChecked(True)
                # Statuszeile direkt unter dem Ollama-Eintrag
                self.ollama_status_label = QLabel(tr("    Pruefe Ollama-Installation ..."))
                self.ollama_status_label.setStyleSheet("color: gray;")
                layout.addWidget(self.ollama_status_label)
            elif _PROVIDER_IDS[i] == "lmstudio":
                # Nur sichtbar, wenn LM Studio laeuft (siehe _on_detected)
                rb.setVisible(False)
                self.lmstudio_status_label = QLabel()
                self.lmstudio_status_label.setVisible(False)
                layout.addWidget(self.lmstudio_status_label)

        self.hardware_label = QLabel(tr("Hardware wird geprueft ..."))
        self.hardware_label.setWordWrap(True)
        self.hardware_label.setStyleSheet("color: gray;")
        layout.addWidget(self.hardware_label)

        # Bestehenden Wert voreintragen. "none" im gespeicherten Config-Default
        # ist mehrdeutig: entweder wurde noch nie etwas eingerichtet (dann soll
        # Ollama vorausgewaehlt bleiben), oder der Nutzer hat den Wizard schon
        # einmal durchlaufen und sich bewusst gegen KI entschieden (dann muss
        # "none" erhalten bleiben). Ein bereits gesetzter Scan-Ordner ist das
        # Signal, dass es sich um einen erneuten Lauf handelt (main.py startet
        # den Wizard beim ersten Start nur, solange kein Scan-Ordner existiert).
        config = get_config()
        llm_cfg = config.get_llm_config()
        self._configured_provider = llm_cfg.get("provider", "none")
        self._had_explicit_choice = (
            self._configured_provider != "none" or bool(config.get_scan_folder())
        )
        if self._had_explicit_choice and self._configured_provider in _PROVIDER_IDS:
            idx = _PROVIDER_IDS.index(self._configured_provider)
            btn = self._button_group.button(idx)
            if btn:
                btn.setChecked(True)
                btn.setVisible(True)  # auch LM Studio, falls schon gewaehlt

        layout.addStretch()

        self._detection: dict | None = None
        self._thread: _DetectThread | None = None

    def initializePage(self):
        if self._detection is not None or self._thread is not None:
            return
        self._thread = _DetectThread(self)
        self._thread.done.connect(self._on_detected)
        self._thread.start()

    def _on_detected(self, result: dict):
        self._detection = result
        rec = result.get("recommendation")

        # Ollama-Status
        if result.get("running"):
            status, color = tr("✓ Ollama ist installiert und laeuft"), "green"
        elif result.get("installed"):
            status, color = tr("✓ Ollama ist installiert"), "green"
        else:
            status, color = tr("Ollama ist nicht installiert (Download im naechsten Schritt)"), "#b35c00"
        self.ollama_status_label.setText("    " + status)
        self.ollama_status_label.setStyleSheet(f"color: {color};")

        # LM Studio nur anbieten, wenn es laeuft (Empfehlung bleibt Ollama)
        lms_models = result.get("lmstudio_models")
        if lms_models is not None:
            self._radios[_PROVIDER_IDS.index("lmstudio")].setVisible(True)
            if lms_models:
                status, color = tr("✓ LM Studio laeuft ({anzahl} Modell(e))").format(anzahl=len(lms_models)), "green"
            else:
                status, color = tr("LM Studio laeuft, aber es ist kein Modell vorhanden"), "#b35c00"
            self.lmstudio_status_label.setText("    " + status)
            self.lmstudio_status_label.setStyleSheet(f"color: {color};")
            self.lmstudio_status_label.setVisible(True)

        # Hardware-Empfehlung
        recommended_id = None
        if rec is None:
            self.hardware_label.setText(tr("Hardware konnte nicht geprueft werden."))
        elif rec.local_ok:
            recommended_id = "ollama"
            self.hardware_label.setText(
                tr(
                    "<b>Empfehlung: Ollama lokal.</b> {reason} Ihre Dokumente bleiben dabei "
                    "auf diesem PC."
                ).format(reason=rec.reason)
            )
            self.hardware_label.setStyleSheet("color: #1a6b1a;")
        else:
            recommended_id = "ollama_cloud"
            self.hardware_label.setText(
                tr(
                    "<b>Ollama lokal nicht empfohlen.</b> {reason} Empfehlung: <b>Ollama "
                    "Cloud</b> — dieselben Modelle, nur ein API-Key noetig (Dokumentinhalte "
                    "werden dabei an ollama.com uebertragen)."
                ).format(reason=rec.reason)
            )
            self.hardware_label.setStyleSheet("color: #7a4a00;")

        self._recommended_id = recommended_id
        if recommended_id:
            idx = _PROVIDER_IDS.index(recommended_id)
            self._radios[idx].setText(tr("{0}  (empfohlen)").format(_PROVIDER_LABELS[idx]))
            # Nur vorauswaehlen, wenn noch keine bewusste Entscheidung
            # vorliegt - eine bestehende Wahl des Nutzers (auch "ohne KI")
            # wird nicht ueberschrieben.
            if not self._had_explicit_choice:
                self._radios[idx].setChecked(True)

    def get_detection(self) -> dict | None:
        return self._detection

    def get_recommendation(self):
        return (self._detection or {}).get("recommendation")

    def get_provider_index(self) -> int:
        return self._button_group.checkedId()

    def get_provider_id(self) -> str:
        idx = self.get_provider_index()
        return _PROVIDER_IDS[idx] if 0 <= idx < len(_PROVIDER_IDS) else "none"

    def nextId(self):
        # Kein LLM: API-Key-Seite ueberspringen, weiter zur Dokumentensuche
        if self.get_provider_id() == "none":
            return PAGE_SUCHE
        return PAGE_API_KEY


class ApiKeyPage(QWizardPage):
    """Seite 5: API-Key eingeben bzw. Ollama einrichten."""

    def __init__(self):
        super().__init__()
        self.setTitle(tr("Schritt 4: API-Key eingeben"))
        self._provider_id = "none"

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self._info_label = QLabel()
        self._info_label.setWordWrap(True)
        layout.addWidget(self._info_label)

        self._link_btn = QPushButton()
        self._link_btn.setFlat(True)
        self._link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._link_btn.setStyleSheet("color: #0066cc; text-align: left;")
        self._link_btn.clicked.connect(self._open_link)
        layout.addWidget(self._link_btn)

        key_layout = QHBoxLayout()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        key_layout.addWidget(self.key_edit, 1)

        self._show_btn = QPushButton(tr("Anzeigen"))
        self._show_btn.setCheckable(True)
        self._show_btn.toggled.connect(self._toggle_visibility)
        key_layout.addWidget(self._show_btn)
        layout.addLayout(key_layout)

        self._hint_label = QLabel()
        self._hint_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(self._hint_label)

        # --- Ollama-Bereich (nur bei lokalem Ollama sichtbar) ---------------
        self._ollama_box = QWidget()
        ollama_layout = QVBoxLayout(self._ollama_box)
        ollama_layout.setContentsMargins(0, 8, 0, 0)
        ollama_layout.setSpacing(6)

        self.ollama_warning_label = QLabel()
        self.ollama_warning_label.setWordWrap(True)
        self.ollama_warning_label.setStyleSheet("color: #7a4a00;")
        self.ollama_warning_label.setVisible(False)
        ollama_layout.addWidget(self.ollama_warning_label)

        models_row = QHBoxLayout()
        models_row.addWidget(QLabel(tr("Modell:")))
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        models_row.addWidget(self.model_combo, 1)
        self.refresh_btn = QPushButton(tr("Erneut pruefen"))
        self.refresh_btn.clicked.connect(self._start_probe)
        models_row.addWidget(self.refresh_btn)
        ollama_layout.addLayout(models_row)

        self.models_status_label = QLabel()
        self.models_status_label.setWordWrap(True)
        self.models_status_label.setStyleSheet("color: gray;")
        ollama_layout.addWidget(self.models_status_label)

        pull_row = QHBoxLayout()
        self.pull_btn = QPushButton()
        self.pull_btn.clicked.connect(self._start_pull)
        pull_row.addWidget(self.pull_btn, 1)
        self.cancel_pull_btn = QPushButton(tr("Abbrechen"))
        self.cancel_pull_btn.clicked.connect(self._cancel_pull)
        self.cancel_pull_btn.setVisible(False)
        pull_row.addWidget(self.cancel_pull_btn)
        ollama_layout.addLayout(pull_row)

        self.pull_progress = QProgressBar()
        self.pull_progress.setRange(0, 100)
        self.pull_progress.setVisible(False)
        ollama_layout.addWidget(self.pull_progress)

        layout.addWidget(self._ollama_box)
        self._ollama_box.setVisible(False)

        skip_info = QLabel(
            tr("<i>Ohne API-Key koennen Sie die App trotzdem nutzen.\n"
            "Klicken Sie einfach auf 'Weiter' ohne etwas einzugeben.\n"
            "Den Key koennen Sie spaeter unter Extras → Einstellungen eintragen.</i>")
        )
        skip_info.setWordWrap(True)
        skip_info.setStyleSheet("color: gray;")
        layout.addWidget(skip_info)

        layout.addStretch()

        self._models_thread: _ModelsThread | None = None
        self._pull_thread: _PullThread | None = None
        self._recommended_model = OLLAMA_FALLBACK_MODEL
        self._recommended_size_gb = 3.3
        self._ollama_installed = False

    # ------------------------------------------------------------------ #
    # Seite betreten                                                      #
    # ------------------------------------------------------------------ #

    def initializePage(self):
        """Wird aufgerufen wenn die Seite betreten wird."""
        wizard = self.wizard()
        provider_page = wizard.page(PAGE_PROVIDER)
        self._provider_id = provider_page.get_provider_id()
        detection = provider_page.get_detection() or {}
        recommendation = provider_page.get_recommendation()

        # Vorhandenen Wert aus Config laden (Key bei Cloud-Providern, URL bei Ollama)
        config = get_config()
        llm_cfg = config.get_llm_config()
        existing_value = ""
        if llm_cfg.get("provider") == self._provider_id:
            if self._provider_id == "ollama":
                existing_value = llm_cfg.get("base_url", "")
            elif self._provider_id == "lmstudio":
                existing_value = ""
            else:
                existing_value = llm_cfg.get("api_key", "")
        self.key_edit.setText(existing_value)

        provider_labels = {
            "claude": "Anthropic Claude",
            "openai": "OpenAI GPT",
            "ollama": "Ollama",
            "lmstudio": "LM Studio",
            "ollama_cloud": "Ollama Cloud",
            "openrouter": "OpenRouter",
            "poe": "Poe.com",
        }
        name = provider_labels.get(self._provider_id, self._provider_id)

        is_ollama = (self._provider_id == "ollama")
        is_lmstudio = (self._provider_id == "lmstudio")
        self._ollama_box.setVisible(is_ollama or is_lmstudio)
        # LM Studio: weder Key/URL-Feld noch Download - nur Modellwahl
        for widget in (self.key_edit, self._hint_label, self.refresh_btn, self.pull_btn):
            widget.setVisible(not is_lmstudio)

        if is_lmstudio:
            self.setTitle(tr("Schritt 4: LM Studio"))
            self.setSubTitle(
                tr("LM Studio laeuft auf Ihrem Rechner. Sie brauchen keinen API-Key,\n"
                "nur ein Modell - waehlen Sie es unten aus.")
            )
            self._show_btn.setVisible(False)
            self._setup_lmstudio_section(detection)
        elif is_ollama:
            self.setTitle(tr("Schritt 4: Ollama einrichten"))
            self.setSubTitle(
                tr("Ollama laeuft lokal auf Ihrem Rechner. Sie brauchen keinen API-Key,\n"
                "nur die Installation und ein Modell - beides erledigen Sie hier.")
            )
            self.key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._show_btn.setVisible(False)
            self._setup_ollama_section(detection, recommendation)
        else:
            self.setTitle(tr("Schritt 4: API-Key eingeben"))
            self.setSubTitle(
                tr(
                    "Geben Sie Ihren {name} API-Key ein.\nDen Key koennen Sie kostenlos "
                    "erstellen (ein Account genuegt)."
                ).format(name=name)
            )
            self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._show_btn.setVisible(True)
            self._show_btn.setChecked(False)

        url = _PROVIDER_URLS.get(self._provider_id, "")
        if url:
            link_text = (
                tr("  Hier klicken um Ollama herunterzuladen: {url}").format(url=url)
                if is_ollama
                else tr("  Hier klicken um API-Key zu erstellen: {url}").format(url=url)
            )
            self._link_btn.setText(link_text)
            self._link_btn.setVisible(True)
        else:
            self._link_btn.setVisible(False)

        hint = _PROVIDER_KEY_HINTS.get(self._provider_id, "")
        self._hint_label.setText(hint)
        self.key_edit.setPlaceholderText(
            hint if is_ollama else (hint or tr("API-Key hier einfuegen ..."))
        )

        info_texts = {
            "claude": (
                tr("1. Oeffnen Sie den Link unten (oder gehen Sie zu console.anthropic.com).\n"
                "2. Melden Sie sich an oder erstellen Sie ein kostenloses Konto.\n"
                "3. Klicken Sie auf 'API Keys' und dann 'Create Key'.\n"
                "4. Kopieren Sie den Key und fuegen Sie ihn unten ein.")
            ),
            "openai": (
                tr("1. Oeffnen Sie den Link unten (oder gehen Sie zu platform.openai.com).\n"
                "2. Melden Sie sich an oder erstellen Sie ein Konto.\n"
                "3. Klicken Sie auf 'API Keys' und dann 'Create new secret key'.\n"
                "4. Kopieren Sie den Key und fuegen Sie ihn unten ein.")
            ),
            "ollama": self._ollama_info_text(detection),
            "lmstudio": (
                tr("Der lokale Server von LM Studio muss beim Sortieren laufen\n"
                "(LM Studio starten, Developer > Start Server). Das Modell koennen Sie\n"
                "spaeter unter Extras -> Einstellungen aendern.")
            ),
            "ollama_cloud": (
                tr(
                    "Ollama Cloud fuehrt die Ollama-Modelle auf Servern von ollama.com aus "
                    "-\nideal fuer PCs ohne Grafikkarte. Dokumentinhalte werden dabei "
                    "uebertragen.\n1. Oeffnen Sie den Link unten und melden Sie sich bei "
                    "ollama.com an.\n2. Unter 'Keys' einen API-Key erstellen und kopieren.\n"
                    "3. Fuegen Sie ihn unten ein. Standardmodell: "
                    "{OLLAMA_CLOUD_DEFAULT_MODEL}\n   (aenderbar unter Extras -> "
                    "Einstellungen)."
                ).format(OLLAMA_CLOUD_DEFAULT_MODEL=OLLAMA_CLOUD_DEFAULT_MODEL)
            ),
            "poe": (
                tr("1. Oeffnen Sie den Link unten (oder gehen Sie zu poe.com).\n"
                "2. Melden Sie sich an oder erstellen Sie ein Konto.\n"
                "3. Gehen Sie zu poe.com/api_key und kopieren Sie Ihren Key.\n"
                "4. Fuegen Sie ihn unten ein. Modell waehlen Sie spaeter unter\n"
                "   Extras -> Einstellungen (z.B. GPT-4o-Mini).")
            ),
            "openrouter": (
                tr("1. Oeffnen Sie den Link unten (oder gehen Sie zu openrouter.ai).\n"
                "2. Melden Sie sich an oder erstellen Sie ein Konto.\n"
                "3. Unter 'Keys' einen neuen API-Key erstellen und kopieren.\n"
                "4. Fuegen Sie ihn unten ein. Modell waehlen Sie spaeter unter\n"
                "   Extras -> Einstellungen (z.B. openai/gpt-4.1-nano).")
            ),
        }
        self._info_label.setText(info_texts.get(self._provider_id, ""))

    # ------------------------------------------------------------------ #
    # Ollama-Bereich                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _ollama_info_text(detection: dict) -> str:
        if detection.get("installed"):
            return (
                tr("Ollama ist installiert. Unten sehen Sie die vorhandenen Modelle;\n"
                "falls noch keines da ist, laden Sie das empfohlene Modell mit einem Klick.\n"
                "Die Server-URL koennen Sie leer lassen (Standard: http://localhost:11434).")
            )
        return (
            tr("Ollama ist noch nicht installiert:\n"
            "1. Ueber den Link unten Ollama herunterladen und installieren (Standardeinstellungen).\n"
            "2. Danach hier auf 'Erneut pruefen' klicken.\n"
            "3. Das empfohlene Modell mit einem Klick herunterladen - fertig.")
        )

    def _setup_ollama_section(self, detection: dict, recommendation) -> None:
        self._ollama_installed = bool(detection.get("installed"))

        if recommendation is not None and recommendation.local_ok and recommendation.model:
            self._recommended_model = recommendation.model
            self._recommended_size_gb = recommendation.model_size_gb
        else:
            self._recommended_model = OLLAMA_FALLBACK_MODEL
            self._recommended_size_gb = 3.3

        if recommendation is not None and not recommendation.local_ok:
            self.ollama_warning_label.setText(
                tr(
                    "Hinweis: {reason} Sie koennen Ollama trotzdem lokal nutzen, muessen "
                    "aber mit langen Wartezeiten rechnen."
                ).format(reason=recommendation.reason)
            )
            self.ollama_warning_label.setVisible(True)
        else:
            self.ollama_warning_label.setVisible(False)

        self.pull_btn.setText(
            tr(
                "Empfohlenes Modell herunterladen: {recommended_model} (ca. "
                "{recommended_size_gb:.0f} GB)"
            ).format(recommended_model=self._recommended_model, recommended_size_gb=self._recommended_size_gb)
        )
        self.pull_progress.setVisible(False)
        self.cancel_pull_btn.setVisible(False)

        # Bereits konfiguriertes Modell vorbelegen
        configured_model = get_config().get_llm_config().get("model", "")
        self.model_combo.clear()
        if configured_model:
            self.model_combo.addItem(configured_model)

        if self._ollama_installed:
            self._start_probe()
        else:
            self.models_status_label.setText(
                tr("Ollama nicht gefunden - nach der Installation 'Erneut pruefen' klicken.")
            )
            self.pull_btn.setEnabled(False)

    def _setup_lmstudio_section(self, detection: dict) -> None:
        self.ollama_warning_label.setVisible(False)
        self.pull_progress.setVisible(False)
        self.cancel_pull_btn.setVisible(False)
        models = detection.get("lmstudio_models") or []
        configured_model = get_config().get_llm_config().get("model", "")
        self.model_combo.clear()
        self.model_combo.addItems(models)
        if configured_model in models:
            self.model_combo.setCurrentText(configured_model)
        if models:
            self.models_status_label.setText(tr("{anzahl} Modell(e) in LM Studio verfuegbar.").format(anzahl=len(models)))
        else:
            self.models_status_label.setText(
                tr("LM Studio bietet noch kein Modell an - bitte in LM Studio ein Modell "
                "herunterladen und laden.")
            )

    def _start_probe(self):
        if self._models_thread is not None and self._models_thread.isRunning():
            return
        self.refresh_btn.setEnabled(False)
        self.models_status_label.setText(tr("Ollama wird gestartet und Modelle werden gelesen ..."))
        self._models_thread = _ModelsThread(self)
        self._models_thread.done.connect(self._on_models_probed)
        self._models_thread.start()

    def _on_models_probed(self, ok: bool, msg: str, models: list):
        self.refresh_btn.setEnabled(True)
        if not ok:
            self._ollama_installed = False
            self.models_status_label.setText(tr("Ollama nicht erreichbar: {msg}").format(msg=msg))
            self.pull_btn.setEnabled(False)
            return

        self._ollama_installed = True
        self.pull_btn.setEnabled(True)
        self.pull_btn.setText(
            tr(
                "Empfohlenes Modell herunterladen: {recommended_model} (ca. "
                "{recommended_size_gb:.0f} GB)"
            ).format(recommended_model=self._recommended_model, recommended_size_gb=self._recommended_size_gb)
        )
        current = self.model_combo.currentText().strip()
        self.model_combo.clear()
        self.model_combo.addItems(models)
        if models:
            # Empfohlenes bzw. bereits gewaehltes Modell aktiv setzen
            preferred = next(
                (m for m in models if m.split(":")[0] == self._recommended_model.split(":")[0]
                 or m == current),
                models[0],
            )
            self.model_combo.setCurrentText(preferred)
            self.models_status_label.setText(
                tr(
                    "{anzahl} Modell(e) installiert. Empfehlung fuer Ihre Hardware: "
                    "{recommended_model}."
                ).format(anzahl=len(models), recommended_model=self._recommended_model)
            )
            if self._is_installed(self._recommended_model, models):
                self.pull_btn.setText(tr("{recommended_model} ist bereits installiert").format(recommended_model=self._recommended_model))
                self.pull_btn.setEnabled(False)
        else:
            self.model_combo.setCurrentText(current or self._recommended_model)
            self.models_status_label.setText(
                tr("Ollama laeuft, aber es ist noch kein Modell installiert - "
                "bitte unten herunterladen.")
            )

    @staticmethod
    def _is_installed(model: str, installed: list[str]) -> bool:
        """'gemma3:12b' gilt als installiert bei 'gemma3:12b' oder 'gemma3:12b-...'."""
        return any(m == model or m.startswith(model + "-") for m in installed)

    def _start_pull(self):
        if self._pull_thread is not None and self._pull_thread.isRunning():
            return
        self.pull_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.cancel_pull_btn.setVisible(True)
        self.pull_progress.setValue(0)
        self.pull_progress.setVisible(True)
        self.models_status_label.setText(tr("Lade {recommended_model} herunter ...").format(recommended_model=self._recommended_model))
        self._pull_thread = _PullThread(self._recommended_model, self)
        self._pull_thread.progress.connect(self._on_pull_progress)
        self._pull_thread.finished_pull.connect(self._on_pull_finished)
        self._pull_thread.start()

    def _cancel_pull(self):
        if self._pull_thread is not None:
            self._pull_thread.cancel()
            self.cancel_pull_btn.setEnabled(False)

    def _on_pull_progress(self, percent: int, status: str):
        self.pull_progress.setValue(percent)
        self.models_status_label.setText(f"{status} ({percent} %)")

    def _on_pull_finished(self, ok: bool, msg: str):
        self.pull_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self.cancel_pull_btn.setVisible(False)
        self.cancel_pull_btn.setEnabled(True)
        if ok:
            self.pull_progress.setValue(100)
            self.models_status_label.setText(f"{self._recommended_model}: {msg}")
            self._start_probe()
        else:
            self.pull_progress.setVisible(False)
            self.models_status_label.setText(tr("Download fehlgeschlagen: {msg}").format(msg=msg))

    def get_selected_model(self) -> str:
        """Gewaehltes Ollama-Modell (nur bei Provider 'ollama' relevant)."""
        return self.model_combo.currentText().strip()

    # ------------------------------------------------------------------ #
    # Allgemein                                                           #
    # ------------------------------------------------------------------ #

    def _open_link(self):
        url = _PROVIDER_URLS.get(self._provider_id, "")
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _toggle_visibility(self, checked: bool):
        if checked:
            self.key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._show_btn.setText(tr("Verbergen"))
        else:
            self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._show_btn.setText(tr("Anzeigen"))

    def get_api_key(self) -> str:
        return self.key_edit.text().strip()


class SearchPage(QWizardPage):
    """Seite 6: Dokumentensuche - Ordner, Mails, Texterkennung, Hintergrund (Suche-Integration, Phase 3).

    Nichts wird ungefragt indiziert (Entscheidung 3): Die Suche ist nur an,
    wenn der Nutzer sie hier oder in den Einstellungen einschaltet. Vorbelegt
    sind Scan- und Zielordner; Laufwerke bzw. Benutzerordner und Volumes stehen
    abwaehlbar darunter. Eine vorhandene PDFsuche laesst sich uebernehmen
    (``SearchMigrationDialog``); danach gelten deren Einstellungen.
    """

    def __init__(self):
        super().__init__()
        self.setTitle(tr("Schritt 5: Dokumentensuche (optional)"))
        self.setSubTitle(
            tr("Volltextsuche ueber Ihre Dokumente - auch in gescannten PDFs,\n"
            "Office-Dateien und Mails. Alles bleibt auf diesem Rechner.")
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self.enable_check = QCheckBox(tr("Dokumentensuche einschalten"))
        self.enable_check.toggled.connect(self._update_enabled)
        layout.addWidget(self.enable_check)

        self.folders_label = QLabel(tr("Diese Ordner und Laufwerke durchsuchen (Haken setzen):"))
        layout.addWidget(self.folders_label)
        self.folders_list = QListWidget()
        self.folders_list.setMaximumHeight(110)
        layout.addWidget(self.folders_list)
        folder_row = QHBoxLayout()
        self.add_folder_button = QPushButton(tr("Weiteren Ordner ..."))
        self.add_folder_button.clicked.connect(self._browse)
        folder_row.addWidget(self.add_folder_button)
        folder_row.addStretch()
        layout.addLayout(folder_row)

        self.mails_check = QCheckBox(tr("Mails aus Thunderbird aufnehmen"))
        layout.addWidget(self.mails_check)
        self.mails_label = QLabel("")
        self.mails_label.setStyleSheet("color: gray;")
        self.mails_label.setWordWrap(True)
        layout.addWidget(self.mails_label)

        self.ocr_check = QCheckBox(tr("Gescannte PDFs per Texterkennung (OCR) durchsuchbar machen"))
        layout.addWidget(self.ocr_check)
        self.ocr_label = QLabel("")
        self.ocr_label.setStyleSheet("color: gray;")
        self.ocr_label.setWordWrap(True)
        layout.addWidget(self.ocr_label)

        self.textlayer_check = QCheckBox(
            tr("Erkannten Text unsichtbar in neue Scans schreiben (Textebene, mit Sicherungskopie)")
        )
        self.textlayer_check.setToolTip(
            tr("Dann finden auch andere Programme den Text der Scans. Das Scanbild bleibt unveraendert; "
            "abschalten unter Einstellungen > Suche > Textebene.")
        )
        layout.addWidget(self.textlayer_check)

        self.background_check = QCheckBox(
            tr("Einmal taeglich im Hintergrund indizieren, sobald der Rechner nicht benutzt wird")
        )
        layout.addWidget(self.background_check)

        privacy = QLabel(
            tr("<b>Datenschutz:</b> Index und erkannter Text liegen in einer lokalen\n"
            "Datenbank, nichts verlaesst den Rechner. Dateien werden nur gelesen;\n"
            "einzige Ausnahme ist die Textebene fuer neue Scans (abschaltbar).\n"
            "Ohne Ihre Zustimmung wird nichts indiziert. Alles laesst sich spaeter\n"
            "unter <b>Extras &rarr; Einstellungen &rarr; Suche</b> aendern.")
        )
        privacy.setWordWrap(True)
        layout.addWidget(privacy)

        self.migrate_button = QPushButton(tr("Vorhandene PDFsuche uebernehmen ..."))
        self.migrate_button.setToolTip(
            tr("Einstellungen und Datenbank des frueheren, eigenstaendigen Programms\n"
            "PDFsuche uebernehmen. Die Datenbank bleibt an ihrem Ort.")
        )
        self.migrate_button.setVisible(False)
        self.migrate_button.clicked.connect(self._migrate)
        layout.addWidget(self.migrate_button)
        self.migrate_label = QLabel("")
        self.migrate_label.setStyleSheet("color: gray;")
        self.migrate_label.setWordWrap(True)
        self.migrate_label.setVisible(False)
        layout.addWidget(self.migrate_label)

        layout.addStretch()

        self._visited = False
        self._known: set[str] = set()
        self._scan_folder = ""
        self._mails_moeglich = False
        self._ocr_moeglich = False
        self._kandidaten: list[str] = []
        self._uebernommen = None
        self._update_enabled(False)

    def initializePage(self):
        from src.search import migration, plattform
        from src.utils.tesseract import find_tesseract

        self._visited = True
        config = get_config()
        cfg = config.get_search_config()
        # Scan- und Zielordner aus den Assistentenseiten, sonst aus der Konfiguration
        wizard = self.wizard()
        scan = wizard.page(PAGE_SCAN_FOLDER).get_folder() if wizard is not None else ""
        scan = scan or str(config.get_scan_folder() or "")
        ziele = [wizard.page(PAGE_TARGET_FOLDER).get_folder()] if wizard is not None else []
        ziele = [z for z in ziele if z] or [str(t) for t in config.get_target_folders()]
        self._scan_folder = scan
        # Nur beim ersten Betreten fuellen: ein "Zurueck"/"Weiter" soll manuell
        # hinzugefuegte Ordner nicht verwerfen.
        if self.folders_list.count() == 0:
            self._fill_folders(cfg, [scan, *ziele])
            self.enable_check.setChecked(cfg.aktiv)
            self.background_check.setChecked(cfg.hintergrund_aktiv if cfg.aktiv else True)

        try:
            profil = plattform.thunderbird_mail_ordner()
        except Exception:
            profil = []
        self._mails_moeglich = bool(profil)
        self.mails_check.setChecked(cfg.mails_aktiv and self._mails_moeglich)
        self.mails_label.setText(
            tr("Thunderbird-Profil gefunden: {0}").format(', '.join(profil)) if profil
            else tr("Kein Thunderbird-Profil gefunden - Mails lassen sich spaeter in den\n"
                 "Einstellungen einrichten (Postfach-Ordner angeben).")
        )

        tesseract = find_tesseract()
        self._ocr_moeglich = bool(tesseract)
        self.ocr_check.setChecked(self._ocr_moeglich and cfg.ocr_aktiv)
        self.textlayer_check.setChecked(cfg.textebene != "aus")
        self.ocr_label.setText(
            tr("Braucht Rechenzeit und laeuft mit niedriger Prioritaet; der erkannte\n"
            "Text landet nur im Index.") if tesseract
            else tr("Tesseract nicht gefunden - die Texterkennung laesst sich spaeter einrichten.")
        )

        try:
            self._kandidaten = migration.finde_pdfsuche()
        except Exception:
            self._kandidaten = []
        self.migrate_button.setVisible(bool(self._kandidaten) and self._uebernommen is None)
        self._update_enabled(self.enable_check.isChecked() and self._uebernommen is None)

    def _fill_folders(self, cfg, vorgaben: list[str]) -> None:
        from src.search import plattform

        self.folders_list.clear()
        self._known.clear()
        for p in vorgaben:
            if p:
                self._add_folder(p, True)
        if cfg.aktiv:
            for w in cfg.wurzeln:
                self._add_folder(w, True)
        try:
            vorschlaege = plattform.wurzel_vorschlaege()
        except Exception:
            vorschlaege = []
        for v in vorschlaege:
            self._add_folder(v, False)

    def _add_folder(self, pfad: str, checked: bool) -> None:
        from src.search.konfig import norm_pfad

        p = norm_pfad(pfad)
        if p.lower() in self._known:
            if checked:
                for i in range(self.folders_list.count()):
                    item = self.folders_list.item(i)
                    if item.text().lower() == p.lower():
                        item.setCheckState(Qt.CheckState.Checked)
            return
        self._known.add(p.lower())
        item = QListWidgetItem(p)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.folders_list.addItem(item)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Ordner oder Laufwerk fuer die Suche waehlen"), "")
        if folder:
            self._add_folder(folder, True)

    def _update_enabled(self, on: bool) -> None:
        for w in (self.folders_label, self.folders_list, self.add_folder_button, self.background_check):
            w.setEnabled(on)
        self.mails_check.setEnabled(on and self._mails_moeglich)
        self.ocr_check.setEnabled(on and self._ocr_moeglich)
        self.textlayer_check.setEnabled(on and self._ocr_moeglich)

    def selected_folders(self) -> list[str]:
        return [
            self.folders_list.item(i).text() for i in range(self.folders_list.count())
            if self.folders_list.item(i).checkState() == Qt.CheckState.Checked
        ]

    def was_visited(self) -> bool:
        return self._visited

    def get_search_config(self):
        """``SearchConfig`` aus den Angaben dieser Seite; None nach einer Uebernahme (der Dialog hat schon gespeichert)."""
        if self._uebernommen is not None:
            return None
        cfg = get_config().get_search_config()
        cfg.aktiv = self.enable_check.isChecked()
        cfg.wurzeln = self.selected_folders()
        if self._scan_folder:
            cfg.prioritaet = [self._scan_folder]
        cfg.mails_aktiv = self.mails_check.isChecked() and self._mails_moeglich
        if self._ocr_moeglich:
            cfg.ocr_aktiv = self.ocr_check.isChecked()
        cfg.hintergrund_aktiv = self.background_check.isChecked()
        if not self.textlayer_check.isChecked():
            cfg.textebene = "aus"
        elif cfg.textebene == "aus":
            cfg.textebene = "neue_scans"           # "alle" bleibt, wenn es schon eingestellt war
        cfg.__post_init__()
        return cfg

    def _migrate(self):
        from src.gui.search_migration_dialog import SearchMigrationDialog

        dlg = SearchMigrationDialog(self, get_config(), kandidaten=self._kandidaten or None)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.ergebnis is not None:
            self._uebernommen = dlg.ergebnis
            self.migrate_label.setText(
                tr(
                    "Uebernommen: {db_datei}\nDie Einstellungen der PDFsuche gelten; aendern "
                    "koennen Sie sie unter\nExtras -> Einstellungen -> Suche."
                ).format(db_datei=dlg.ergebnis.db_datei)
            )
            self.migrate_label.setVisible(True)
            self.migrate_button.setVisible(False)
            self.enable_check.setChecked(True)
            self.enable_check.setEnabled(False)
            self._update_enabled(False)


class DonePage(QWizardPage):
    """Seite 7: Abschluss."""

    def __init__(self):
        super().__init__()
        self.setTitle(tr("Alles bereit!"))
        self.setSubTitle(tr("Das Setup ist abgeschlossen. Sie koennen jetzt loslegen."))
        self.setFinalPage(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        text = QLabel(
            tr("<b>Was jetzt?</b><br><br>"
            "Legen Sie ein paar PDFs in Ihren Scan-Ordner und starten Sie\n"
            "die Sortierung mit einem Doppelklick auf ein Dokument.<br><br>"
            "<b>Einstellungen aendern:</b><br>"
            "Sie finden alle Optionen jederzeit unter\n"
            "<b>Extras &rarr; Einstellungen</b> in der Menuleiste.<br><br>"
            "<b>Assistenten erneut starten:</b><br>"
            "Unter <b>Extras &rarr; Einrichtungs-Assistent</b> koennen Sie\n"
            "diesen Assistenten jederzeit erneut oeffnen.")
        )
        text.setWordWrap(True)
        layout.addWidget(text)

        # Optional: Eintrag im Windows-Explorer-Kontextmenue (nur Windows).
        self.explorer_checkbox = None
        if sys.platform == "win32":
            self.explorer_checkbox = QCheckBox(
                tr("PDF Sortier Meister im Rechtsklick-Menue des Explorers "
                "anzeigen")
            )
            self.explorer_checkbox.setToolTip(
                tr("Fuegt einen Eintrag \"PDF Sortier Meister von hier oeffnen\"\n"
                "hinzu, wenn Sie einen Ordner oder dessen Hintergrund\n"
                "rechtsklicken. Aenderbar unter Extras -> Einstellungen.")
            )
            layout.addWidget(self.explorer_checkbox)

        layout.addStretch()

    def initializePage(self):
        """Setzt die Explorer-Checkbox als Empfehlung auf 'an'."""
        if self.explorer_checkbox is None:
            return
        # Default: aktiv. Bei einem zweiten Wizard-Lauf koennte man hier
        # den Registry-Stand spiegeln, aber die Empfehlung "an" ist
        # sowieso identisch zu beiden Faellen.
        self.explorer_checkbox.setChecked(True)

    def wants_context_menu(self) -> bool:
        if self.explorer_checkbox is None:
            return False
        return self.explorer_checkbox.isChecked()


class SetupWizard(QWizard):
    """
    Fuehrt den Benutzer durch die Erstkonfiguration.

    Trigger: In main.py aufrufen wenn config.get_scan_folder() leer ist.
    Erneuter Aufruf: ueber Extras -> Einrichtungs-Assistent.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("PDF Sortier Meister einrichten"))
        self.setMinimumSize(600, 520)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)

        # Kein "?" Hilfe-Button (verwirrt DAUs)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.WizardOption.HaveHelpButton, False)

        self._welcome_page = WelcomePage()
        self._scan_page = ScanFolderPage()
        self._target_page = TargetFolderPage()
        self._provider_page = ProviderPage()
        self._api_key_page = ApiKeyPage()
        self._search_page = SearchPage()
        self._done_page = DonePage()

        self.setPage(PAGE_WELCOME, self._welcome_page)
        self.setPage(PAGE_SCAN_FOLDER, self._scan_page)
        self.setPage(PAGE_TARGET_FOLDER, self._target_page)
        self.setPage(PAGE_PROVIDER, self._provider_page)
        self.setPage(PAGE_API_KEY, self._api_key_page)
        self.setPage(PAGE_SUCHE, self._search_page)
        self.setPage(PAGE_DONE, self._done_page)

        self.setStartId(PAGE_WELCOME)

        # Fertig-Button beschriften
        self.setButtonText(QWizard.WizardButton.FinishButton, tr("Fertig"))
        self.setButtonText(QWizard.WizardButton.NextButton, tr("Weiter >"))
        self.setButtonText(QWizard.WizardButton.BackButton, tr("< Zurueck"))
        self.setButtonText(QWizard.WizardButton.CancelButton, tr("Spaeter"))

        self.finished.connect(self._on_finished)

    def _on_finished(self, result: int):
        """Speichert die Einstellungen wenn der User auf 'Fertig' klickt."""
        # result == QDialog.DialogCode.Accepted (1) bei Fertig-Klick
        # result == QDialog.DialogCode.Rejected (0) bei Spaeter/Schliessen
        # Bei "Fertig" speichern wir immer, was eingetragen ist. Bei
        # "Spaeter"/Schliessen nur, wenn die jeweilige Ordner-Seite
        # tatsaechlich besucht wurde (oder der Pfad manuell geaendert
        # wurde) - sonst wuerde ein reiner Default-Vorschlag, den der
        # Nutzer nie gesehen hat (Sofort-Abbruch auf der Begruessungsseite),
        # ungefragt gespeichert und der Ordner auf der Platte angelegt.
        config = get_config()
        accepted = (result == QDialog.DialogCode.Accepted)

        # Scan-Ordner speichern und anlegen, falls er noch nicht existiert
        folder = self._scan_page.get_folder()
        if folder and (accepted or self._scan_page.was_visited()):
            config.set_scan_folder(folder)
            self._ensure_folder_exists(folder)

        # Zielordner anlegen (falls er fehlt) und als Zielordner registrieren
        # (Issue #64). config.add_target_folder() dedupliziert selbst.
        target_folder = self._target_page.get_folder()
        if target_folder and (accepted or self._target_page.was_visited()):
            self._ensure_folder_exists(target_folder)
            config.add_target_folder(target_folder)

        # Dokumentensuche: nur speichern, wenn die Seite gesehen wurde (sonst
        # bliebe "nichts indizieren" unausgesprochen). Nach einer Uebernahme
        # hat der Dialog bereits gespeichert (get_search_config() ist None).
        if self._search_page.was_visited():
            search_cfg = self._search_page.get_search_config()
            if search_cfg is not None:
                config.set_search_config(search_cfg)
                self._search_schedule_sync(search_cfg)

        # Provider und API-Key bzw. Server-URL speichern
        provider_id = self._provider_page.get_provider_id()
        config.set_llm_provider(provider_id)

        if provider_id == "ollama":
            # Bei Ollama steht im Eingabefeld die Server-URL, kein API-Key.
            # Leerer Eintrag heisst: Default-URL verwenden (wird im Provider
            # selbst auf http://localhost:11434 gesetzt).
            base_url = self._api_key_page.get_api_key()
            llm_cfg = config.get_llm_config()
            llm_cfg["base_url"] = base_url
            # API-Key auf leer setzen, damit kein Cloud-Key aus einem
            # vorherigen Setup haengenbleibt.
            llm_cfg["api_key"] = ""
            model = self._api_key_page.get_selected_model()
            if model:
                llm_cfg["model"] = model
            config.set("llm", llm_cfg)
        elif provider_id == "lmstudio":
            # Kein Key, Standard-URL (dort wurde LM Studio erkannt)
            llm_cfg = config.get_llm_config()
            llm_cfg["api_key"] = ""
            llm_cfg["base_url"] = ""
            llm_cfg["model"] = self._api_key_page.get_selected_model()
            config.set("llm", llm_cfg)
        elif provider_id != "none":
            api_key = self._api_key_page.get_api_key()
            if api_key:
                config.set_llm_api_key(api_key)
            if provider_id == "ollama_cloud":
                llm_cfg = config.get_llm_config()
                if not llm_cfg.get("model"):
                    llm_cfg["model"] = OLLAMA_CLOUD_DEFAULT_MODEL
                    config.set("llm", llm_cfg)

        # Explorer-Integration: nur bei "Fertig" (Accepted) anwenden,
        # nicht bei "Spaeter"/Schliessen - dort waere eine Registry-
        # Aenderung ueberraschend.
        if accepted and sys.platform == "win32":
            if self._done_page.wants_context_menu():
                try:
                    from src.utils.explorer_integration import register_context_menu
                    register_context_menu()
                except Exception:
                    # Bewusst still: ein fehlgeschlagener Registry-Eintrag
                    # darf den Wizard nicht zum Crash bringen. Der User
                    # kann es spaeter unter Einstellungen erneut versuchen.
                    pass

    def _search_schedule_sync(self, search_cfg) -> None:
        """Hintergrundindexierung gleich einrichten (Aufgabenplanung bzw. LaunchAgent), wenn eingeschaltet."""
        import subprocess

        from PyQt6.QtWidgets import QMessageBox

        from src.search import zeitplan

        if not zeitplan.etwas_gewuenscht(search_cfg):
            return
        try:
            zeitplan.abgleichen(search_cfg)
        except (zeitplan.ZeitplanFehler, OSError, subprocess.SubprocessError) as e:
            QMessageBox.warning(
                self, tr("Hintergrundindexierung"),
                tr(
                    "Die Dokumentensuche ist eingerichtet, aber der tägliche Lauf ließ sich "
                    "nicht planen:\n\n{e}\n\nUnter Einstellungen > Suche lässt er sich "
                    "erneut speichern."
                ).format(e=e))

    @staticmethod
    def _ensure_folder_exists(folder: str) -> None:
        """Legt den Ordner an, falls er noch fehlt (Issues #61, #64).

        Fehler (z. B. fehlende Rechte, ungueltiger Pfad) werden bewusst
        verschluckt - der Wizard darf dadurch nie abstuerzen. Der Nutzer
        kann den Ordner spaeter manuell anlegen oder unter Einstellungen
        einen anderen waehlen.
        """
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

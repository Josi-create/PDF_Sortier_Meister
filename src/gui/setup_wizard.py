"""
Erststart-Wizard fuer PDF Sortier Meister

Fuehrt den Benutzer beim ersten Start durch:
  1. Begruessung
  2. Scan-Ordner waehlen
  3. LLM-Provider waehlen (mit Hardware-Erkennung und Ollama-Status)
  4. API-Key eingeben bzw. Ollama einrichten (Modelle anzeigen/herunterladen)
  5. Abschluss

Der Wizard kann auch ueber das Extras-Menue erneut geoeffnet werden.
"""

import sys
import threading

from PyQt6.QtWidgets import (
    QWizard, QWizardPage, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog,
    QRadioButton, QButtonGroup, QWidget, QCheckBox,
    QDialog, QComboBox, QProgressBar,
)
from PyQt6.QtCore import Qt, QUrl, QThread, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont

from src.utils.config import get_config


# Seiten-IDs
PAGE_WELCOME = 0
PAGE_SCAN_FOLDER = 1
PAGE_PROVIDER = 2
PAGE_API_KEY = 3
PAGE_DONE = 4

# Provider-Konstanten (Index -> interner Name). Reihenfolge = Empfehlungsrang:
# Ollama (lokal, kein Key) zuerst, dann Cloud-Anbieter, "Ohne KI" ganz unten
# (Issue #67 - KI ist ein Hauptfeature, nicht "optional").
_PROVIDER_IDS = ["ollama", "ollama_cloud", "openrouter", "poe", "claude", "openai", "none"]
_PROVIDER_LABELS = [
    "Ollama (lokal auf diesem Rechner, empfohlen — kein API-Key noetig)",
    "Ollama Cloud (Ollama-Modelle in der Cloud, API-Key)",
    "OpenRouter (viele KI-Modelle, ein API-Key)",
    "Poe.com (viele KI-Modelle, ein API-Key)",
    "Anthropic Claude",
    "OpenAI GPT",
    "Ohne KI-Assistent (nur einfache lokale Stichwort-Zuordnung — stark eingeschraenkt)",
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
    "claude": 'Beginnt mit "sk-ant-..."',
    "openai": 'Beginnt mit "sk-..."',
    "ollama": "Leer lassen fuer Standard (http://localhost:11434)",
    "ollama_cloud": "Zu finden auf ollama.com/settings/keys",
    "openrouter": 'Beginnt mit "sk-or-..."',
    "poe": "Zu finden auf poe.com/api_key",
}

OLLAMA_LOCAL_URL = "http://localhost:11434"
OLLAMA_CLOUD_DEFAULT_MODEL = "gpt-oss:120b"
OLLAMA_FALLBACK_MODEL = "gemma3:4b"


def detect_ollama_environment() -> dict:
    """
    Ermittelt Ollama-Installation, Serverstatus und Hardware-Empfehlung.

    Laeuft in einem Hintergrund-Thread der Provider-Seite; in Tests wird
    die Funktion durch eine Attrappe ersetzt.
    """
    from src.ml.ollama_launcher import find_ollama_executable, quick_ping
    from src.utils.hardware import detect_and_recommend

    exe = find_ollama_executable()
    running = quick_ping(OLLAMA_LOCAL_URL, timeout=0.5)
    return {
        "exe": exe,
        "installed": bool(exe) or running,
        "running": running,
        "recommendation": detect_and_recommend(),
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
                      "recommendation": None, "error": str(e)}
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
        self.setTitle("Willkommen bei PDF Sortier Meister!")
        self.setSubTitle(
            "Dieses kurze Setup dauert etwa 2 Minuten.\n"
            "Sie koennen jeden Schritt ueberspringen und spaeter aendern."
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        text = QLabel(
            "<b>Was macht PDF Sortier Meister?</b><br><br>"
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
            "eine einfache Stichwort-Zuordnung."
        )
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addStretch()


class ScanFolderPage(QWizardPage):
    """Seite 2: Scan-Ordner waehlen."""

    def __init__(self):
        super().__init__()
        self.setTitle("Schritt 1: Scan-Ordner auswaehlen")
        self.setSubTitle(
            "In welchem Ordner liegen Ihre gescannten PDFs?\n"
            "Diesen Ordner wird das Programm beim Start anzeigen."
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        info = QLabel(
            "Waehlen Sie den Ordner, in den Ihr Scanner die PDFs speichert\n"
            "(z. B. <i>C:\\Users\\IhrName\\Scans</i> oder ein Netzlaufwerk)."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Noch kein Ordner ausgewaehlt ...")
        self.path_edit.setReadOnly(True)
        path_layout.addWidget(self.path_edit, 1)

        browse_btn = QPushButton("Ordner auswaehlen ...")
        browse_btn.clicked.connect(self._browse)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)

        skip_info = QLabel(
            "<i>Sie koennen auch jetzt ueberspringen und den Ordner spaeter\n"
            "unter Extras → Einstellungen festlegen.</i>"
        )
        skip_info.setStyleSheet("color: gray;")
        layout.addWidget(skip_info)

        layout.addStretch()

        # Bestehenden Wert voreintragen
        config = get_config()
        existing = config.get_scan_folder()
        if existing:
            self.path_edit.setText(str(existing))

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Scan-Ordner auswaehlen", str(self.path_edit.text() or "")
        )
        if folder:
            self.path_edit.setText(folder)

    def get_folder(self) -> str:
        return self.path_edit.text().strip()


class ProviderPage(QWizardPage):
    """Seite 3: LLM-Provider waehlen - mit Ollama-Status und Hardware-Empfehlung."""

    def __init__(self):
        super().__init__()
        self.setTitle("Schritt 2: KI-Assistent auswaehlen")
        self.setSubTitle(
            "Ein KI-Assistent liefert deutlich bessere Vorschlaege — wir empfehlen\n"
            "Ollama (laeuft lokal, kostenlos). Ganz ohne KI geht es zur Not auch."
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
                self.ollama_status_label = QLabel("    Pruefe Ollama-Installation ...")
                self.ollama_status_label.setStyleSheet("color: gray;")
                layout.addWidget(self.ollama_status_label)

        self.hardware_label = QLabel("Hardware wird geprueft ...")
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
            status, color = "✓ Ollama ist installiert und laeuft", "green"
        elif result.get("installed"):
            status, color = "✓ Ollama ist installiert", "green"
        else:
            status, color = "Ollama ist nicht installiert (Download im naechsten Schritt)", "#b35c00"
        self.ollama_status_label.setText("    " + status)
        self.ollama_status_label.setStyleSheet(f"color: {color};")

        # Hardware-Empfehlung
        recommended_id = None
        if rec is None:
            self.hardware_label.setText("Hardware konnte nicht geprueft werden.")
        elif rec.local_ok:
            recommended_id = "ollama"
            self.hardware_label.setText(
                f"<b>Empfehlung: Ollama lokal.</b> {rec.reason} "
                f"Ihre Dokumente bleiben dabei auf diesem PC."
            )
            self.hardware_label.setStyleSheet("color: #1a6b1a;")
        else:
            recommended_id = "ollama_cloud"
            self.hardware_label.setText(
                f"<b>Ollama lokal nicht empfohlen.</b> {rec.reason} "
                f"Empfehlung: <b>Ollama Cloud</b> — dieselben Modelle, nur ein API-Key noetig "
                f"(Dokumentinhalte werden dabei an ollama.com uebertragen)."
            )
            self.hardware_label.setStyleSheet("color: #7a4a00;")

        self._recommended_id = recommended_id
        if recommended_id:
            idx = _PROVIDER_IDS.index(recommended_id)
            self._radios[idx].setText(_PROVIDER_LABELS[idx] + "  (empfohlen)")
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
        # Kein LLM: direkt zur Fertig-Seite springen
        if self.get_provider_id() == "none":
            return PAGE_DONE
        return PAGE_API_KEY


class ApiKeyPage(QWizardPage):
    """Seite 4: API-Key eingeben bzw. Ollama einrichten."""

    def __init__(self):
        super().__init__()
        self.setTitle("Schritt 3: API-Key eingeben")
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

        self._show_btn = QPushButton("Anzeigen")
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
        models_row.addWidget(QLabel("Modell:"))
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        models_row.addWidget(self.model_combo, 1)
        self.refresh_btn = QPushButton("Erneut pruefen")
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
        self.cancel_pull_btn = QPushButton("Abbrechen")
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
            "<i>Ohne API-Key koennen Sie die App trotzdem nutzen.\n"
            "Klicken Sie einfach auf 'Weiter' ohne etwas einzugeben.\n"
            "Den Key koennen Sie spaeter unter Extras → Einstellungen eintragen.</i>"
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
            else:
                existing_value = llm_cfg.get("api_key", "")
        self.key_edit.setText(existing_value)

        provider_labels = {
            "claude": "Anthropic Claude",
            "openai": "OpenAI GPT",
            "ollama": "Ollama",
            "ollama_cloud": "Ollama Cloud",
            "openrouter": "OpenRouter",
            "poe": "Poe.com",
        }
        name = provider_labels.get(self._provider_id, self._provider_id)

        is_ollama = (self._provider_id == "ollama")
        self._ollama_box.setVisible(is_ollama)

        if is_ollama:
            self.setTitle("Schritt 3: Ollama einrichten")
            self.setSubTitle(
                "Ollama laeuft lokal auf Ihrem Rechner. Sie brauchen keinen API-Key,\n"
                "nur die Installation und ein Modell - beides erledigen Sie hier."
            )
            self.key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._show_btn.setVisible(False)
            self._setup_ollama_section(detection, recommendation)
        else:
            self.setTitle("Schritt 3: API-Key eingeben")
            self.setSubTitle(
                f"Geben Sie Ihren {name} API-Key ein.\n"
                "Den Key koennen Sie kostenlos erstellen (ein Account genuegt)."
            )
            self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._show_btn.setVisible(True)
            self._show_btn.setChecked(False)

        url = _PROVIDER_URLS.get(self._provider_id, "")
        if url:
            link_text = (
                f"  Hier klicken um Ollama herunterzuladen: {url}"
                if is_ollama
                else f"  Hier klicken um API-Key zu erstellen: {url}"
            )
            self._link_btn.setText(link_text)
            self._link_btn.setVisible(True)
        else:
            self._link_btn.setVisible(False)

        hint = _PROVIDER_KEY_HINTS.get(self._provider_id, "")
        self._hint_label.setText(hint)
        self.key_edit.setPlaceholderText(
            hint if is_ollama else (hint or "API-Key hier einfuegen ...")
        )

        info_texts = {
            "claude": (
                "1. Oeffnen Sie den Link unten (oder gehen Sie zu console.anthropic.com).\n"
                "2. Melden Sie sich an oder erstellen Sie ein kostenloses Konto.\n"
                "3. Klicken Sie auf 'API Keys' und dann 'Create Key'.\n"
                "4. Kopieren Sie den Key und fuegen Sie ihn unten ein."
            ),
            "openai": (
                "1. Oeffnen Sie den Link unten (oder gehen Sie zu platform.openai.com).\n"
                "2. Melden Sie sich an oder erstellen Sie ein Konto.\n"
                "3. Klicken Sie auf 'API Keys' und dann 'Create new secret key'.\n"
                "4. Kopieren Sie den Key und fuegen Sie ihn unten ein."
            ),
            "ollama": self._ollama_info_text(detection),
            "ollama_cloud": (
                "Ollama Cloud fuehrt die Ollama-Modelle auf Servern von ollama.com aus -\n"
                "ideal fuer PCs ohne Grafikkarte. Dokumentinhalte werden dabei uebertragen.\n"
                "1. Oeffnen Sie den Link unten und melden Sie sich bei ollama.com an.\n"
                "2. Unter 'Keys' einen API-Key erstellen und kopieren.\n"
                f"3. Fuegen Sie ihn unten ein. Standardmodell: {OLLAMA_CLOUD_DEFAULT_MODEL}\n"
                "   (aenderbar unter Extras -> Einstellungen)."
            ),
            "poe": (
                "1. Oeffnen Sie den Link unten (oder gehen Sie zu poe.com).\n"
                "2. Melden Sie sich an oder erstellen Sie ein Konto.\n"
                "3. Gehen Sie zu poe.com/api_key und kopieren Sie Ihren Key.\n"
                "4. Fuegen Sie ihn unten ein. Modell waehlen Sie spaeter unter\n"
                "   Extras -> Einstellungen (z.B. GPT-4o-Mini)."
            ),
            "openrouter": (
                "1. Oeffnen Sie den Link unten (oder gehen Sie zu openrouter.ai).\n"
                "2. Melden Sie sich an oder erstellen Sie ein Konto.\n"
                "3. Unter 'Keys' einen neuen API-Key erstellen und kopieren.\n"
                "4. Fuegen Sie ihn unten ein. Modell waehlen Sie spaeter unter\n"
                "   Extras -> Einstellungen (z.B. openai/gpt-4.1-nano)."
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
                "Ollama ist installiert. Unten sehen Sie die vorhandenen Modelle;\n"
                "falls noch keines da ist, laden Sie das empfohlene Modell mit einem Klick.\n"
                "Die Server-URL koennen Sie leer lassen (Standard: http://localhost:11434)."
            )
        return (
            "Ollama ist noch nicht installiert:\n"
            "1. Ueber den Link unten Ollama herunterladen und installieren (Standardeinstellungen).\n"
            "2. Danach hier auf 'Erneut pruefen' klicken.\n"
            "3. Das empfohlene Modell mit einem Klick herunterladen - fertig."
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
                f"Hinweis: {recommendation.reason} Sie koennen Ollama trotzdem lokal "
                f"nutzen, muessen aber mit langen Wartezeiten rechnen."
            )
            self.ollama_warning_label.setVisible(True)
        else:
            self.ollama_warning_label.setVisible(False)

        self.pull_btn.setText(
            f"Empfohlenes Modell herunterladen: {self._recommended_model} "
            f"(ca. {self._recommended_size_gb:.0f} GB)"
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
                "Ollama nicht gefunden - nach der Installation 'Erneut pruefen' klicken."
            )
            self.pull_btn.setEnabled(False)

    def _start_probe(self):
        if self._models_thread is not None and self._models_thread.isRunning():
            return
        self.refresh_btn.setEnabled(False)
        self.models_status_label.setText("Ollama wird gestartet und Modelle werden gelesen ...")
        self._models_thread = _ModelsThread(self)
        self._models_thread.done.connect(self._on_models_probed)
        self._models_thread.start()

    def _on_models_probed(self, ok: bool, msg: str, models: list):
        self.refresh_btn.setEnabled(True)
        if not ok:
            self._ollama_installed = False
            self.models_status_label.setText(f"Ollama nicht erreichbar: {msg}")
            self.pull_btn.setEnabled(False)
            return

        self._ollama_installed = True
        self.pull_btn.setEnabled(True)
        self.pull_btn.setText(
            f"Empfohlenes Modell herunterladen: {self._recommended_model} "
            f"(ca. {self._recommended_size_gb:.0f} GB)"
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
                f"{len(models)} Modell(e) installiert. Empfehlung fuer Ihre Hardware: "
                f"{self._recommended_model}."
            )
            if self._is_installed(self._recommended_model, models):
                self.pull_btn.setText(f"{self._recommended_model} ist bereits installiert")
                self.pull_btn.setEnabled(False)
        else:
            self.model_combo.setCurrentText(current or self._recommended_model)
            self.models_status_label.setText(
                "Ollama laeuft, aber es ist noch kein Modell installiert - "
                "bitte unten herunterladen."
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
        self.models_status_label.setText(f"Lade {self._recommended_model} herunter ...")
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
            self.models_status_label.setText(f"Download fehlgeschlagen: {msg}")

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
            self._show_btn.setText("Verbergen")
        else:
            self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._show_btn.setText("Anzeigen")

    def get_api_key(self) -> str:
        return self.key_edit.text().strip()


class DonePage(QWizardPage):
    """Seite 5: Abschluss."""

    def __init__(self):
        super().__init__()
        self.setTitle("Alles bereit!")
        self.setSubTitle("Das Setup ist abgeschlossen. Sie koennen jetzt loslegen.")
        self.setFinalPage(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        text = QLabel(
            "<b>Was jetzt?</b><br><br>"
            "Legen Sie ein paar PDFs in Ihren Scan-Ordner und starten Sie\n"
            "die Sortierung mit einem Doppelklick auf ein Dokument.<br><br>"
            "<b>Einstellungen aendern:</b><br>"
            "Sie finden alle Optionen jederzeit unter\n"
            "<b>Extras &rarr; Einstellungen</b> in der Menuleiste.<br><br>"
            "<b>Assistenten erneut starten:</b><br>"
            "Unter <b>Extras &rarr; Einrichtungs-Assistent</b> koennen Sie\n"
            "diesen Assistenten jederzeit erneut oeffnen."
        )
        text.setWordWrap(True)
        layout.addWidget(text)

        # Optional: Eintrag im Windows-Explorer-Kontextmenue (nur Windows).
        self.explorer_checkbox = None
        if sys.platform == "win32":
            self.explorer_checkbox = QCheckBox(
                "PDF Sortier Meister im Rechtsklick-Menue des Explorers "
                "anzeigen"
            )
            self.explorer_checkbox.setToolTip(
                "Fuegt einen Eintrag \"PDF Sortier Meister von hier oeffnen\"\n"
                "hinzu, wenn Sie einen Ordner oder dessen Hintergrund\n"
                "rechtsklicken. Aenderbar unter Extras -> Einstellungen."
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
        self.setWindowTitle("PDF Sortier Meister einrichten")
        self.setMinimumSize(600, 520)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)

        # Kein "?" Hilfe-Button (verwirrt DAUs)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.WizardOption.HaveHelpButton, False)

        self._welcome_page = WelcomePage()
        self._scan_page = ScanFolderPage()
        self._provider_page = ProviderPage()
        self._api_key_page = ApiKeyPage()
        self._done_page = DonePage()

        self.setPage(PAGE_WELCOME, self._welcome_page)
        self.setPage(PAGE_SCAN_FOLDER, self._scan_page)
        self.setPage(PAGE_PROVIDER, self._provider_page)
        self.setPage(PAGE_API_KEY, self._api_key_page)
        self.setPage(PAGE_DONE, self._done_page)

        self.setStartId(PAGE_WELCOME)

        # Fertig-Button beschriften
        self.setButtonText(QWizard.WizardButton.FinishButton, "Fertig")
        self.setButtonText(QWizard.WizardButton.NextButton, "Weiter >")
        self.setButtonText(QWizard.WizardButton.BackButton, "< Zurueck")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Spaeter")

        self.finished.connect(self._on_finished)

    def _on_finished(self, result: int):
        """Speichert die Einstellungen wenn der User auf 'Fertig' klickt."""
        # result == QDialog.DialogCode.Accepted (1) bei Fertig-Klick
        # result == QDialog.DialogCode.Rejected (0) bei Spaeter/Schliessen
        # Wir speichern in BEIDEN Faellen was bisher eingetragen wurde,
        # damit ein halbfertiges Setup nicht verloren geht.
        config = get_config()

        # Scan-Ordner speichern
        folder = self._scan_page.get_folder()
        if folder:
            config.set_scan_folder(folder)

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
        if result == QDialog.DialogCode.Accepted and sys.platform == "win32":
            if self._done_page.wants_context_menu():
                try:
                    from src.utils.explorer_integration import register_context_menu
                    register_context_menu()
                except Exception:
                    # Bewusst still: ein fehlgeschlagener Registry-Eintrag
                    # darf den Wizard nicht zum Crash bringen. Der User
                    # kann es spaeter unter Einstellungen erneut versuchen.
                    pass

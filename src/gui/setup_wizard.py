"""
Erststart-Wizard fuer PDF Sortier Meister

Fuehrt den Benutzer beim ersten Start durch:
  1. Begruessung
  2. Scan-Ordner waehlen
  3. LLM-Provider waehlen
  4. API-Key eingeben
  5. Abschluss

Der Wizard kann auch ueber das Extras-Menue erneut geoeffnet werden.
"""

from PyQt6.QtWidgets import (
    QWizard, QWizardPage, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog,
    QRadioButton, QButtonGroup, QWidget,
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont

from src.utils.config import get_config


# Seiten-IDs
PAGE_WELCOME = 0
PAGE_SCAN_FOLDER = 1
PAGE_PROVIDER = 2
PAGE_API_KEY = 3
PAGE_DONE = 4

# Provider-Konstanten (Index -> interner Name)
_PROVIDER_IDS = ["none", "claude", "openai", "poe"]
_PROVIDER_LABELS = [
    "Kein KI-Assistent (nur klassische Erkennung)",
    "Anthropic Claude (empfohlen)",
    "OpenAI GPT",
    "Poe.com (viele KI-Modelle, ein Account)",
]
_PROVIDER_URLS = {
    "claude": "https://console.anthropic.com/settings/keys",
    "openai": "https://platform.openai.com/api-keys",
    "poe":    "https://poe.com/api_key",
}
_PROVIDER_KEY_HINTS = {
    "claude": 'Beginnt mit "sk-ant-..."',
    "openai": 'Beginnt mit "sk-..."',
    "poe":    "Zu finden auf poe.com/api_key",
}


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
            "<b>Optionaler KI-Assistent:</b> Mit einem API-Key eines KI-Anbieters\n"
            "werden die Vorschlaege noch besser. Das ist aber kein Muss —\n"
            "die klassische Erkennung funktioniert auch ohne KI."
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
            "(z. B. <i>C:\\Users\\IhrName\\Scans</i> oder ein Netzlaufwerk)."
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
    """Seite 3: LLM-Provider waehlen."""

    def __init__(self):
        super().__init__()
        self.setTitle("Schritt 2: KI-Assistent auswaehlen")
        self.setSubTitle(
            "Moechten Sie einen KI-Assistenten nutzen?\n"
            "Das verbessert die Erkennungsqualitaet, ist aber nicht noetig."
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        self._button_group = QButtonGroup(self)

        for i, label in enumerate(_PROVIDER_LABELS):
            rb = QRadioButton(label)
            self._button_group.addButton(rb, i)
            layout.addWidget(rb)
            if i == 0:
                rb.setChecked(True)

        # Bestehenden Wert voreintragen
        config = get_config()
        llm_cfg = config.get_llm_config()
        provider = llm_cfg.get("provider", "none")
        if provider in _PROVIDER_IDS:
            idx = _PROVIDER_IDS.index(provider)
            btn = self._button_group.button(idx)
            if btn:
                btn.setChecked(True)

        layout.addStretch()

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
    """Seite 4: API-Key eingeben."""

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

        skip_info = QLabel(
            "<i>Ohne API-Key koennen Sie die App trotzdem nutzen.\n"
            "Klicken Sie einfach auf 'Weiter' ohne etwas einzugeben.\n"
            "Den Key koennen Sie spaeter unter Extras → Einstellungen eintragen.</i>"
        )
        skip_info.setWordWrap(True)
        skip_info.setStyleSheet("color: gray;")
        layout.addWidget(skip_info)

        layout.addStretch()

    def initializePage(self):
        """Wird aufgerufen wenn die Seite betreten wird."""
        # Provider-Auswahl aus Seite 3 lesen
        wizard = self.wizard()
        provider_page = wizard.page(PAGE_PROVIDER)
        self._provider_id = provider_page.get_provider_id()

        # Vorhandenen Key aus Config laden
        config = get_config()
        llm_cfg = config.get_llm_config()
        existing_key = ""
        if llm_cfg.get("provider") == self._provider_id:
            existing_key = llm_cfg.get("api_key", "")
        self.key_edit.setText(existing_key)

        # UI an Provider anpassen
        provider_labels = {
            "claude": "Anthropic Claude",
            "openai": "OpenAI GPT",
            "poe":    "Poe.com",
        }
        name = provider_labels.get(self._provider_id, self._provider_id)
        self.setSubTitle(
            f"Geben Sie Ihren {name} API-Key ein.\n"
            "Den Key koennen Sie kostenlos erstellen (ein Account genuegt)."
        )

        url = _PROVIDER_URLS.get(self._provider_id, "")
        if url:
            self._link_btn.setText(f"  Hier klicken um API-Key zu erstellen: {url}")
            self._link_btn.setVisible(True)
        else:
            self._link_btn.setVisible(False)

        hint = _PROVIDER_KEY_HINTS.get(self._provider_id, "")
        self._hint_label.setText(hint)
        self.key_edit.setPlaceholderText(hint or "API-Key hier einfuegen ...")

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
            "poe": (
                "1. Oeffnen Sie den Link unten (oder gehen Sie zu poe.com).\n"
                "2. Melden Sie sich an oder erstellen Sie ein Konto.\n"
                "3. Gehen Sie zu poe.com/api_key und kopieren Sie Ihren Key.\n"
                "4. Fuegen Sie ihn unten ein."
            ),
        }
        self._info_label.setText(info_texts.get(self._provider_id, ""))

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
        layout.addStretch()


class SetupWizard(QWizard):
    """
    Fuehrt den Benutzer durch die Erstkonfiguration.

    Trigger: In main.py aufrufen wenn config.get_scan_folder() leer ist.
    Erneuter Aufruf: ueber Extras -> Einrichtungs-Assistent.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PDF Sortier Meister einrichten")
        self.setMinimumSize(550, 420)
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

        # Provider und API-Key speichern
        provider_id = self._provider_page.get_provider_id()
        config.set_llm_provider(provider_id)

        if provider_id != "none":
            api_key = self._api_key_page.get_api_key()
            if api_key:
                config.set_llm_api_key(api_key)

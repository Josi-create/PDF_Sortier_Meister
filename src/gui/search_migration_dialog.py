"""Dialog „Vorhandene PDFsuche übernehmen“ (Dokumentensuche, Phase 3).

Prueft einen Projektordner des frueheren, eigenstaendigen Programms PDFsuche
(``src.search.migration.pruefen``) in einem Thread, zeigt die Vorschau und
uebernimmt Einstellungen und Datenbank (``migration.uebernehmen``). Die
Datenbank bleibt am bisherigen Ort; wahlweise wird sie in das Datenverzeichnis
kopiert (mit Fortschrittsanzeige und Pruefung der Kopie). Wird vom
Einrichtungsassistenten und von den Einstellungen (Registerkarte „Suche“)
geoeffnet.
"""

from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout,
)

from src.search import migration
from src.utils.config import get_config


class _PruefThread(QThread):
    fertig = pyqtSignal(object)

    def __init__(self, ordner: str, parent=None):
        super().__init__(parent)
        self.ordner = ordner

    def run(self):
        self.fertig.emit(migration.pruefen(self.ordner))


class _UebernahmeThread(QThread):
    fortschritt = pyqtSignal(int, int)
    fertig = pyqtSignal(bool, str)

    def __init__(self, uebernahme, config, kopieren: bool, parent=None):
        super().__init__(parent)
        self.uebernahme = uebernahme
        self.config = config
        self.kopieren = kopieren

    def run(self):
        try:
            konfig = migration.uebernehmen(
                self.uebernahme, self.config, kopieren=self.kopieren,
                fortschritt=lambda kopiert, gesamt: self.fortschritt.emit(kopiert, gesamt),
            )
            self.fertig.emit(True, str(konfig.db_datei))
        except Exception as e:  # noqa: BLE001 - jede Ursache landet als Text im Dialog
            self.fertig.emit(False, str(e))


class SearchMigrationDialog(QDialog):
    """Vorschau und Uebernahme einer vorhandenen PDFsuche.

    ``ergebnis`` ist nach ``accept()`` die gespeicherte ``SearchConfig``.
    ``kandidaten`` (Liste von Ordnern) ersetzt die automatische Suche
    (``migration.finde_pdfsuche``), z. B. in Tests.
    """

    def __init__(self, parent=None, config=None, kandidaten: list[str] | None = None):
        super().__init__(parent)
        self.config = config or get_config()
        self.uebernahme = None
        self.ergebnis = None
        self._thread: QThread | None = None
        self.setWindowTitle("Vorhandene PDFsuche übernehmen")
        self.setMinimumSize(640, 500)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Wenn Sie bisher das eigenständige Programm <b>PDFsuche</b> benutzt haben, "
            "übernimmt PDF Sortier Meister dessen Einstellungen (config.toml) und die "
            "Suchdatenbank. Die Datenbank bleibt an ihrem bisherigen Ort, es wird nichts "
            "gelöscht; den bisherigen Projektordner räumen Sie später selbst auf. "
            "Die Aufgaben der Aufgabenplanung werden hier nicht verändert."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        row.addWidget(QLabel("PDFsuche-Ordner:"))
        self.folder_combo = QComboBox()
        self.folder_combo.setEditable(True)
        self.folder_combo.setMinimumWidth(260)
        row.addWidget(self.folder_combo, 1)
        self.browse_button = QPushButton("Durchsuchen…")
        self.browse_button.clicked.connect(self._browse)
        row.addWidget(self.browse_button)
        self.check_button = QPushButton("Prüfen")
        self.check_button.clicked.connect(self._pruefen)
        row.addWidget(self.check_button)
        layout.addLayout(row)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("Noch nicht geprüft. Ordner wählen und auf „Prüfen“ klicken.")
        layout.addWidget(self.preview, 1)

        self.copy_check = QCheckBox(
            "Datenbank in das Datenverzeichnis von PDF Sortier Meister kopieren "
            "(sonst bleibt sie am bisherigen Ort; die Kopie wird geprüft)"
        )
        layout.addWidget(self.copy_check)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray;")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.take_button = QPushButton("Übernehmen")
        self.take_button.setEnabled(False)
        self.take_button.setDefault(True)
        self.take_button.clicked.connect(self._uebernehmen)
        buttons.addWidget(self.take_button)
        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

        if kandidaten is None:
            kandidaten = migration.finde_pdfsuche()
        for k in kandidaten:
            self.folder_combo.addItem(k)
        if kandidaten:
            self._pruefen()
        else:
            self.status_label.setText("Keine PDFsuche gefunden – bitte den Projektordner (mit config.toml) wählen.")

    # ------------------------------------------------------------------ Ablauf

    def ordner(self) -> str:
        return self.folder_combo.currentText().strip()

    def _browse(self):
        ordner = QFileDialog.getExistingDirectory(self, "Projektordner der PDFsuche wählen", self.ordner())
        if ordner:
            self.folder_combo.setEditText(ordner)
            self._pruefen()

    def _pruefen(self):
        ordner = self.ordner()
        if not ordner:
            self.status_label.setText("Bitte zuerst den Projektordner wählen.")
            return
        if self._thread is not None and self._thread.isRunning():
            return
        self.take_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self.status_label.setText("Prüfe … (bei großen Datenbanken dauert die Integritätsprüfung einige Minuten)")
        self._thread = _PruefThread(ordner, self)
        self._thread.fertig.connect(self._geprueft)
        self._thread.start()

    def _geprueft(self, uebernahme):
        self.uebernahme = uebernahme
        self.preview.setPlainText(uebernahme.zusammenfassung())
        self.check_button.setEnabled(True)
        self.take_button.setEnabled(uebernahme.moeglich)
        self.status_label.setText(
            "Bereit zur Übernahme." if uebernahme.moeglich else "Übernahme nicht möglich – siehe Hinweise oben."
        )

    def _uebernehmen(self):
        u = self.uebernahme
        if u is None or not u.moeglich:
            return
        if self._thread is not None and self._thread.isRunning():
            return
        kopieren = self.copy_check.isChecked()
        self.take_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.copy_check.setEnabled(False)
        if kopieren:
            self.progress.setRange(0, 0)
            self.progress.setVisible(True)
        self.status_label.setText("Übernehme …" + (" Datenbank wird kopiert." if kopieren else ""))
        self._thread = _UebernahmeThread(u, self.config, kopieren, self)
        self._thread.fortschritt.connect(self._fortschritt)
        self._thread.fertig.connect(self._uebernommen)
        self._thread.start()

    def _fortschritt(self, kopiert: int, gesamt: int):
        self.progress.setRange(0, max(gesamt, 1))
        self.progress.setValue(kopiert)

    def _uebernommen(self, ok: bool, text: str):
        self.cancel_button.setEnabled(True)
        self.check_button.setEnabled(True)
        self.copy_check.setEnabled(True)
        if ok:
            self.ergebnis = self.config.get_search_config()
            self.status_label.setText(f"Übernommen. Datenbank: {text}")
            self.accept()
            return
        self.progress.setVisible(False)
        self.take_button.setEnabled(True)
        self.status_label.setText(f"Fehler: {text}")

    def reject(self):
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait(60_000)
        super().reject()

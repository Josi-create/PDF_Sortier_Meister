"""Textfeld "Zeitraum" mit sofortiger Deutung (Issue #161).

Ersetzt die Kalender-Felder "von" / "bis": man tippt "2004-2006", "12/2024",
"Jan 2024" oder "ab 2020"; darunter steht klein und grau die Deutung, bei
unlesbarer Eingabe wird der Rand rot. ``geaendert`` kommt erst bei lesbarer
(oder leerer) Eingabe - nach kurzer Tipp-Pause, bei Enter und beim Verlassen
des Feldes sofort.
"""
from __future__ import annotations

from datetime import date
from typing import Callable

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QLabel, QLineEdit, QVBoxLayout, QWidget

from src.core import datum_eingabe as de

HINWEIS_STIL = "color: #888; font-size: 10px;"
FEHLER_HINWEIS_STIL = "color: #b71c1c; font-size: 10px;"
FEHLER_RAND_STIL = "QLineEdit { border: 1px solid #d32f2f; border-radius: 3px; padding: 1px 3px; }"

TOOLTIP = (
    "Zeitraum frei eintippen, leer = keine Grenze.\n"
    "Beispiele: 2024 · 12/2024 · Jan 2024 · Q2 2024 · 3.5.2024\n"
    "Bereiche: 2004-2006 · 12/2023-3/2024 · 2004 bis 2006\n"
    "Offen: ab 2020 · 2020- · bis 12/2023"
)


class ZeitraumFeld(QWidget):
    """QLineEdit + Hinweiszeile; ``grenzen()`` liefert ISO-Daten fuer die Suche."""

    geaendert = pyqtSignal()
    TIPP_PAUSE_MS = 600

    def __init__(self, parent: QWidget | None = None, heute: Callable[[], date] = date.today):
        super().__init__(parent)
        self._heute = heute
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Zeitraum, z. B. 2004-2006")
        self.edit.setClearButtonEnabled(True)
        self.edit.setToolTip(TOOLTIP)
        self.hinweis = QLabel("")
        self.hinweis.setStyleSheet(HINWEIS_STIL)
        self.hinweis.setVisible(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        lay.addWidget(self.edit)
        lay.addWidget(self.hinweis)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.TIPP_PAUSE_MS)
        self._timer.timeout.connect(self._melden)
        self.edit.textChanged.connect(self._text_geaendert)
        self.edit.returnPressed.connect(self._sofort)
        self.edit.editingFinished.connect(self._sofort)
        self._gemeldet: tuple[str, str] = ("", "")
        self._aktualisieren()

    # ------------------------------------------------------------------ Zugriff

    def text(self) -> str:
        return self.edit.text()

    def setText(self, text: str) -> None:  # noqa: N802 (Qt-Stil)
        self.edit.setText(text)

    def ergebnis(self):
        """``Zeitraum`` oder ``Fehler`` zum aktuellen Text."""
        return de.parse_zeitraum(self.edit.text(), self._heute())

    def grenzen(self) -> tuple[str, str]:
        """(von, bis) als JJJJ-MM-TT; "" = offen. Unlesbare Eingabe wirkt als keine Grenze."""
        erg = self.ergebnis()
        if isinstance(erg, de.Fehler):
            return "", ""
        return (erg.von.isoformat() if erg.von else "", erg.bis.isoformat() if erg.bis else "")

    def setGrenzen(self, von: str, bis: str) -> None:  # noqa: N802 (Qt-Stil)
        """Grenzen von aussen setzen (ISO) und als lesbaren Text anzeigen; ohne Signal."""
        self.edit.blockSignals(True)
        try:
            self.edit.setText(de.formatiere(date.fromisoformat(von) if von else None,
                                            date.fromisoformat(bis) if bis else None))
        finally:
            self.edit.blockSignals(False)
        self._gemeldet = self.grenzen()
        self._aktualisieren()

    def zuruecksetzen(self) -> None:
        """Feld leeren, ohne ``geaendert`` zu senden."""
        self._timer.stop()
        self.setGrenzen("", "")

    def hat_grenze(self) -> bool:
        return self.grenzen() != ("", "")

    # ------------------------------------------------------------------ intern

    def _aktualisieren(self) -> None:
        erg = self.ergebnis()
        fehler = isinstance(erg, de.Fehler)
        text = de.beschreibe(erg)
        self.hinweis.setText(text)
        self.hinweis.setVisible(bool(text))
        self.hinweis.setStyleSheet(FEHLER_HINWEIS_STIL if fehler else HINWEIS_STIL)
        self.edit.setStyleSheet(FEHLER_RAND_STIL if fehler else "")

    def _text_geaendert(self, _text: str) -> None:
        self._aktualisieren()
        if isinstance(self.ergebnis(), de.Fehler):
            self._timer.stop()
        else:
            self._timer.start()

    def _sofort(self) -> None:
        self._timer.stop()
        if not isinstance(self.ergebnis(), de.Fehler):
            self._melden()

    def _melden(self) -> None:
        grenzen = self.grenzen()
        if grenzen != self._gemeldet:
            self._gemeldet = grenzen
            self.geaendert.emit()

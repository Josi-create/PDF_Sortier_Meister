"""
Eingabefeld fuer Schlagwoerter (Issue #231).

Mehrere Eintraege, durch Komma getrennt; ein Schraegstrich trennt Ebenen
(``Steuer/Werbungskosten, Haus``). Beim Tippen erscheint eine Liste der schon
benutzten Schlagwoerter - sie bezieht sich nur auf den Eintrag unter der
Schreibmarke, nicht auf das ganze Feld.
"""

from __future__ import annotations

from PyQt6.QtCore import QStringListModel, Qt
from PyQt6.QtWidgets import QCompleter, QLineEdit

_TRENNER = ",;"


class SchlagwortFeld(QLineEdit):
    """QLineEdit mit Vorschlagsliste je kommagetrenntem Eintrag."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._modell = QStringListModel(self)
        self._completer = QCompleter(self._modell, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setWidget(self)
        self._completer.activated[str].connect(self.eintrag_einsetzen)
        self.textEdited.connect(self._vorschlagen)

    def set_choices(self, schlagwoerter) -> None:
        """Die schon benutzten Schlagwoerter fuer die Vorschlagsliste."""
        self._modell.setStringList(list(schlagwoerter or []))

    def choices(self) -> list[str]:
        return list(self._modell.stringList())

    def _abschnitt(self) -> tuple[int, int]:
        """Anfang und Ende des Eintrags unter der Schreibmarke."""
        text, pos = self.text(), self.cursorPosition()
        start = max(text.rfind(t, 0, pos) for t in _TRENNER) + 1
        enden = [i for i in (text.find(t, pos) for t in _TRENNER) if i >= 0]
        return start, min(enden) if enden else len(text)

    def aktueller_anfang(self) -> str:
        """Was im Eintrag unter der Schreibmarke bis zu ihr getippt ist."""
        start, _ende = self._abschnitt()
        return self.text()[start:self.cursorPosition()].strip()

    def _vorschlagen(self, _text: str = "") -> None:
        anfang = self.aktueller_anfang()
        if not anfang:
            self._completer.popup().hide()
            return
        self._completer.setCompletionPrefix(anfang)
        if self._completer.completionCount() > 0:
            self._completer.complete()
        else:
            self._completer.popup().hide()

    def eintrag_einsetzen(self, schlagwort: str) -> None:
        """Den Eintrag unter der Schreibmarke durch ``schlagwort`` ersetzen."""
        start, ende = self._abschnitt()
        text = self.text()
        davor = text[:start].rstrip()
        neu = (davor + " " if davor else "") + schlagwort
        self.setText(neu + text[ende:])
        self.setCursorPosition(len(neu))

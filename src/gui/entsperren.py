"""Hauptfenster-Teil "Passwortschutz entfernen…" (Issue #244).

:class:`EntsperrenMixin` fragt das Passwort ab, laesst ``src.core.pdf_entsperren``
eine ungeschuetzte Kopie neben das Original schreiben und fragt erst danach,
was mit dem Original geschieht (Regel "Original wegraeumen", eigener
Schluessel ``entsperren``).

Das Passwort bleibt in diesem Aufruf: Es wird nicht gespeichert, nicht
protokolliert, steht in keiner Meldung und geht an keine KI. Bei mehreren
markierten PDFs gilt es fuer alle; fuer die, bei denen es nicht passt, wird
noch einmal gefragt.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from src.core.pdf_entsperren import (
    EntsperrenNichtMoeglich,
    Entsperrt,
    FalschesPasswort,
    braucht_passwort,
    entsperren,
)
from src.gui import original_wegraeumen as ow
from src.i18n import tr
from src.search.meldungen import melden as index_melden

TITEL = tr("Passwortschutz entfernen")


def _namen(pfade: list[Path], maximal: int = 5) -> str:
    namen = [p.name for p in pfade[:maximal]]
    if len(pfade) > maximal:
        namen.append(f"… (+{len(pfade) - maximal})")
    return "\n".join(namen)


class PasswortDialog(QDialog):
    """Fragt das Passwort verdeckt ab. Das Feld wird nach dem Schliessen geleert."""

    def __init__(self, parent, pfade: list[Path], fehler: str = ""):
        super().__init__(parent)
        self.setWindowTitle(TITEL)
        layout = QVBoxLayout(self)

        if len(pfade) == 1:
            kopf = tr("Passwort für diese PDF:")
        else:
            kopf = tr("Passwort für diese {anzahl} PDFs (es wird bei allen versucht):").format(anzahl=len(pfade))
        layout.addWidget(QLabel(kopf))
        dateien = QLabel(_namen(pfade))
        dateien.setTextFormat(Qt.TextFormat.PlainText)
        dateien.setStyleSheet("font-weight: bold;")
        layout.addWidget(dateien)

        self.fehler_label = QLabel(fehler)
        self.fehler_label.setTextFormat(Qt.TextFormat.PlainText)
        self.fehler_label.setWordWrap(True)
        self.fehler_label.setStyleSheet("color: #b00020;")
        self.fehler_label.setVisible(bool(fehler))
        layout.addWidget(self.fehler_label)

        self.eingabe = QLineEdit()
        self.eingabe.setEchoMode(QLineEdit.EchoMode.Password)
        self.eingabe.setPlaceholderText(tr("Passwort"))
        layout.addWidget(self.eingabe)

        self.zeigen = QCheckBox(tr("Passwort anzeigen"))
        self.zeigen.toggled.connect(self._zeigen)
        layout.addWidget(self.zeigen)

        hinweis = QLabel(tr(
            "Es entsteht eine Kopie ohne Schutz neben dem Original; das Original bleibt unverändert.\n"
            "Das Passwort wird nicht gespeichert und nicht an die KI gegeben."
        ))
        hinweis.setWordWrap(True)
        hinweis.setStyleSheet("color: #555;")
        layout.addWidget(hinweis)

        self.knoepfe = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.knoepfe.accepted.connect(self.accept)
        self.knoepfe.rejected.connect(self.reject)
        layout.addWidget(self.knoepfe)
        self.ok = self.knoepfe.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText(tr("Kopie ohne Schutz erstellen"))
        self.ok.setEnabled(False)
        self.knoepfe.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Abbrechen"))
        self.eingabe.textChanged.connect(lambda text: self.ok.setEnabled(bool(text)))
        self.eingabe.setFocus()

    def _zeigen(self, an: bool):
        self.eingabe.setEchoMode(QLineEdit.EchoMode.Normal if an else QLineEdit.EchoMode.Password)

    def passwort(self) -> str:
        return self.eingabe.text()

    def leeren(self):
        """Eingabe aus dem Feld nehmen."""
        self.eingabe.setEchoMode(QLineEdit.EchoMode.Password)
        self.eingabe.clear()


def _passwort_fragen(parent, pfade: list[Path], fehler: str = "") -> Optional[str]:
    """Zeigt den Dialog; ``None`` = abgebrochen. Tests ersetzen diese Funktion."""
    dialog = PasswortDialog(parent, pfade, fehler)
    try:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.passwort() or None
    finally:
        dialog.leeren()
        dialog.deleteLater()


class EntsperrenMixin:
    """Mixin fuer ``MainWindow``; braucht ``statusbar``, ``config``, ``_aktion_ziele`` usw."""

    def on_pdf_entsperren(self, pdf_path: Path):
        """Kontextmenue "Passwortschutz entfernen…": Kopie(n) ohne Schutz neben dem Original."""
        ziele = [p for p in self._aktion_ziele(pdf_path) if p.exists()]
        offen = [p for p in ziele if braucht_passwort(p)]
        if not offen:
            self.statusbar.showMessage(tr("Kein Passwortschutz gefunden - nichts geändert."), 5000)
            return
        ohne_schutz = len(ziele) - len(offen)

        fertig: list[Entsperrt] = []
        fehler: list[str] = []
        hinweis = ""
        while offen:
            passwort = _passwort_fragen(self, offen, hinweis)
            if passwort is None:
                break  # Abbruch: was schon entsperrt ist, bleibt; sonst ist nichts geschehen
            falsch: list[Path] = []
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                for pfad in offen:
                    try:
                        fertig.append(entsperren(pfad, passwort))
                    except FalschesPasswort:
                        falsch.append(pfad)
                    except EntsperrenNichtMoeglich as e:
                        fehler.append(f"{pfad.name}: {e}")
                    except FileNotFoundError:
                        fehler.append(tr("{name}: Die Datei ist nicht mehr da.").format(name=pfad.name))
                    except Exception as e:  # noqa: BLE001 - je Datei melden, ohne Text der Ausnahme
                        fehler.append(tr("{name}: unerwarteter Fehler ({art}).").format(
                            name=pfad.name, art=type(e).__name__))
            finally:
                passwort = None  # nicht laenger halten als noetig
                QApplication.restoreOverrideCursor()
            if falsch and len(falsch) < len(offen):
                hinweis = tr("Bei diesen PDFs passt das Passwort nicht. Anderes Passwort?")
            else:
                hinweis = tr("Das Passwort passt nicht. Bitte noch einmal eingeben.")
            offen = falsch

        if fehler:
            QMessageBox.warning(self, TITEL, "\n".join(fehler))
        if not fertig:
            if not fehler:
                self.statusbar.showMessage(tr("Abgebrochen - nichts wurde geändert."), 5000)
            return
        self._nach_entsperren(fertig, uebrig=len(offen), ohne_schutz=ohne_schutz)

    def _nach_entsperren(self, fertig: list[Entsperrt], uebrig: int, ohne_schutz: int):
        for erg in fertig:
            index_melden("datei_aufnehmen", str(erg.kopie))
        self.original_nach_entsperren(fertig)
        self.neues_pdf_auswaehlen(fertig[0].kopie)
        if len(fertig) == 1:
            meldung = tr("Kopie ohne Passwortschutz erstellt: {name}").format(name=fertig[0].kopie.name)
        else:
            meldung = tr("{anzahl} Kopien ohne Passwortschutz erstellt").format(anzahl=len(fertig))
        if uebrig:
            meldung += tr(", {anzahl} PDF(s) bleiben geschützt").format(anzahl=uebrig)
        if ohne_schutz:
            meldung += tr(", {anzahl} PDF(s) hatten keinen Passwortschutz").format(anzahl=ohne_schutz)
        self.statusbar.showMessage(meldung, 8000)  # nach der Auswahl (sie meldet "Analysiere")

    def original_nach_entsperren(self, fertig: list[Entsperrt]) -> list[Path]:
        """Fragt (oder nutzt die gemerkte Antwort), ob die geschuetzten Originale in den Papierkorb sollen.

        Zur Wahl stehen nur Originale, deren Kopie da und lesbar ist. Signierte
        Originale bleiben immer liegen: Die Signatur gilt nur fuer das Original.
        """
        from src.core.bild_convert import pdf_lesbar

        signiert = [e for e in fertig if e.signiert]
        if signiert:
            QMessageBox.information(self, TITEL, tr(
                "Diese PDFs sind digital signiert. Die Signatur gilt nur für das geschützte Original, "
                "nicht für die Kopie - das Original bleibt deshalb liegen:\n{namen}"
            ).format(namen=_namen([e.original for e in signiert])))
        waehlbar = [e for e in fertig if not e.signiert and pdf_lesbar(e.kopie, e.seiten)]
        if not waehlbar:
            return []
        originale = [e.original for e in waehlbar]
        if len(waehlbar) == 1:
            text = tr(
                "'{name}' wurde ohne Passwortschutz als '{kopie}' gespeichert.\n\n"
                "Das geschützte Original in den Papierkorb verschieben?"
            ).format(name=originale[0].name, kopie=waehlbar[0].kopie.name)
        else:
            text = tr(
                "{anzahl} PDFs wurden ohne Passwortschutz als Kopie gespeichert.\n\n"
                "Die {anzahl} geschützten Originale in den Papierkorb verschieben?\n{namen}"
            ).format(anzahl=len(waehlbar), namen=_namen(originale, 3))
        beschreibung = tr("Geschütztes Original weggeräumt: {namen}").format(
            namen=", ".join(p.name for p in originale[:3]) + ("…" if len(originale) > 3 else ""))
        return ow.original_wegraeumen(self, originale, "entsperren", text, beschreibung)

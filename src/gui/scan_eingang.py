"""Nach „Jetzt scannen“ in den Scan-Ordner wechseln und den neuen Scan auswaehlen (Issue #339).

Das Programm kennt den Ordner, in dem das Scanprogramm neue Scans ablegt, aus der
Einstellung „Neue Scans landen in:“ (Einstellungen › Allgemein › Scannen). Ist sie
leer, fragt der Knopf „Jetzt scannen“ einmal danach.

Ablauf beim Klick auf „Jetzt scannen“ (vor dem Start des Scanprogramms, damit die
Frage nicht hinter dessen Fenster liegt):

1. Steht links schon der Scan-Ordner, passiert nichts.
2. Sonst Rueckfrage „In den Ordner … wechseln?“ mit dem Kaestchen „Künftig immer
   automatisch wechseln“; ist die Einstellung schon an, wird ohne Frage gewechselt.

Danach ist die Beobachtung „scharf“: Erscheint im Scan-Ordner eine neue Datei
(Ordner-Beobachtung, Issue #232), wird sie ausgewaehlt und die Liste dorthin
gerollt. Das geschieht einmal je Klick und nur, solange man im Scan-Ordner bleibt;
wer vorher in einen anderen Ordner wechselt oder mehrere Dateien markiert hat,
wird nicht aus seiner Arbeit gerissen.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QCheckBox, QFileDialog, QMessageBox

from src.i18n import tr

KONFIG_ORDNER = "scan_eingang_ordner"            # „Neue Scans landen in:“ ("" = nicht festgelegt)
KONFIG_AUTOMATISCH = "scan_eingang_automatisch"  # ohne Rueckfrage wechseln
KONFIG_GEFRAGT = "scan_eingang_gefragt"          # einmal nach dem Ordner gefragt

# So lange nach dem Klick wird auf einen neuen Scan gewartet (Sekunden).
WARTEZEIT = 30 * 60


def ordner_schluessel(ordner) -> str:
    """Vergleichbarer Schluessel eines Ordners (Gross-/Kleinschreibung unter Windows)."""
    return os.path.normcase(os.path.normpath(str(ordner)))


def gleicher_ordner(a, b) -> bool:
    if not a or not b:
        return False
    if ordner_schluessel(a) == ordner_schluessel(b):
        return True
    try:  # Junction/Verknuepfung (z. B. OneDrive): auf das Ziel aufgeloest vergleichen
        return ordner_schluessel(os.path.realpath(a)) == ordner_schluessel(os.path.realpath(b))
    except (OSError, ValueError):
        return False


# --- Dialoge (in Tests ersetzt, siehe tests/conftest.py) ---

def _ordner_dialog(fenster, start: str) -> str:
    """Fragt einmal, wohin das Scanprogramm speichert. Leer bei Abbruch."""
    return QFileDialog.getExistingDirectory(
        fenster, tr("Wo speichert Ihr Scanprogramm neue Scans?"), start
    )


def _wechsel_dialog(fenster, ordner: Path) -> tuple[bool, bool]:
    """Rueckfrage vor dem Wechsel: (wechseln?, kuenftig immer automatisch?)."""
    box = QMessageBox(fenster)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(tr("Jetzt scannen"))
    box.setText(
        tr("In den Ordner „{name}“ wechseln?\n\nDort erscheint der neue Scan und wird gleich ausgewählt.")
        .format(name=ordner.name or str(ordner))
    )
    box.setInformativeText(str(ordner))
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.Yes)
    kaestchen = QCheckBox(tr("Künftig immer automatisch wechseln"))
    box.setCheckBox(kaestchen)
    box.exec()
    ja = box.clickedButton() is box.button(QMessageBox.StandardButton.Yes)
    return ja, ja and kaestchen.isChecked()


# Ueber diese Namen aufgerufen; Tests ersetzen sie (die Dialoge selbst bleiben pruefbar)
ordner_erfragen = _ordner_dialog
wechsel_erfragen = _wechsel_dialog


class ScanEingang:
    """Merkt sich nach „Jetzt scannen“, dass ein neuer Scan erwartet wird (Hauptfenster ``fenster``)."""

    def __init__(self, fenster):
        self.fenster = fenster
        self._erwartet_in: Optional[Path] = None
        self._erwartet_bis = 0.0

    @property
    def config(self):
        return self.fenster.config

    def ordner(self) -> Optional[Path]:
        """Der eingestellte Scan-Ordner, falls es ihn gibt."""
        wert = (self.config.get(KONFIG_ORDNER, "") or "").strip()
        if wert and Path(wert).is_dir():
            return Path(wert)
        return None

    def _startordner_fuer_frage(self) -> str:
        """Erster Favorit (beim Einrichten mit dem damaligen Scan-Ordner vorbelegt, #114), sonst der gezeigte Ordner."""
        for favorit in self.config.get("favoriten", []) or []:
            pfad = (favorit or {}).get("pfad") if isinstance(favorit, dict) else None
            if pfad and Path(pfad).is_dir():
                return str(pfad)
        aktuell = self.fenster.file_manager.scan_folder
        return str(aktuell) if aktuell else ""

    def vor_dem_scannen(self) -> Optional[Path]:
        """Vor dem Start des Scanprogramms: Scan-Ordner klaeren und ggf. dorthin wechseln.

        Gibt den Scan-Ordner zurueck, wenn er danach links angezeigt wird, sonst None.
        """
        ziel = self.ordner()
        if ziel is None:
            eingetragen = (self.config.get(KONFIG_ORDNER, "") or "").strip()
            # Nur einmal fragen; ein eingetragener, aber verschwundener Ordner wird neu erfragt
            if not eingetragen and self.config.get(KONFIG_GEFRAGT, False):
                return None
            self.config.set(KONFIG_GEFRAGT, True)
            gewaehlt = ordner_erfragen(self.fenster, self._startordner_fuer_frage())
            if not gewaehlt:
                return None
            ziel = Path(gewaehlt)
            self.config.set(KONFIG_ORDNER, str(ziel))
        if gleicher_ordner(ziel, self.fenster.file_manager.scan_folder):
            return ziel
        if not self.config.get(KONFIG_AUTOMATISCH, False):
            wechseln, immer = wechsel_erfragen(self.fenster, ziel)
            if not wechseln:
                return None
            if immer:
                self.config.set(KONFIG_AUTOMATISCH, True)
        self.fenster._navigate_to_folder(ziel)
        return ziel

    # --- Warten auf den neuen Scan ---

    def erwarten(self, ordner: Path) -> None:
        """Der naechste neue Scan in ``ordner`` wird ausgewaehlt."""
        self._erwartet_in = Path(ordner)
        self._erwartet_bis = time.monotonic() + WARTEZEIT

    def vergessen(self) -> None:
        self._erwartet_in = None

    @property
    def wartet(self) -> bool:
        return self._erwartet_in is not None and time.monotonic() < self._erwartet_bis

    def ordner_gewechselt(self, ordner) -> None:
        """Wer den Scan-Ordner verlaesst, arbeitet an etwas anderem: nicht mehr warten."""
        if self._erwartet_in is not None and not gleicher_ordner(ordner, self._erwartet_in):
            self.vergessen()

    def neue_dateien(self, ordner: Path, pfade: list[Path], staende: Optional[dict] = None) -> None:
        """Von der Ordner-Beobachtung: ``pfade`` sind neu in ``ordner`` erschienen."""
        if not self.wartet or not pfade:
            return
        if not gleicher_ordner(ordner, self._erwartet_in):
            return
        fenster = self.fenster
        if fenster.selected_pdfs:  # Mehrfachauswahl: man arbeitet gerade an etwas anderem
            self.vergessen()
            return
        sichtbar = {w.pdf_path for w in fenster.pdf_widgets}
        kandidaten = [p for p in pfade if p in sichtbar]
        if not kandidaten:
            return
        staende = staende or {}
        # Der neueste Scan (Aenderungszeit aus der gelesenen Dateiliste, sonst der zuletzt gemeldete)
        neuester = max(
            enumerate(kandidaten),
            key=lambda ip: ((staende.get(ip[1].name) or (0.0,))[0], ip[0]),
        )[1]
        self.vergessen()
        fenster.on_pdf_clicked(neuester)
        fenster.zur_kachel_scrollen(neuester)

"""Doppelte Dateien eines Ordners aufraeumen (Issue #299).

Menue „Extras > Doppelte Dateien suchen …“ (geoeffneter Scan-Ordner) bzw.
Kontextmenue eines Ordners im Zielordner-Baum: Das Programm sucht im Ordner und
allen Unterordnern nach Dateien mit genau demselben Inhalt (Pruefsumme,
``src.core.duplikate``) und zeigt sie in Gruppen, je Datei mit Ordner und
Aenderungsdatum. Man markiert, welche in den Papierkorb sollen; nach einer
Rueckfrage gehen sie dorthin, alle in *einem* Eintrag des Rueckgaengig-Stapels
(Strg+Z im Hauptfenster holt sie zurueck).

Geloescht wird nie automatisch und nie endgueltig: Geht der Papierkorb nicht
(Netzlaufwerk), bleibt die Datei liegen. Von jeder Gruppe muss mindestens eine
Datei bleiben.

Gesucht wird in einem Hintergrund-Thread; die Oberflaeche holt nur Fortschritt
und Ergebnis ab (wie ``DoppelteImOrdner`` in ``src.gui.doppelte``).
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from src.core import duplikate
from src.core.file_manager import PapierkorbNichtVerfuegbar
from src.gui.pfad_aktionen import im_dateimanager_zeigen
from src.gui.search_view import groesse_text
from src.i18n import tr

logger = logging.getLogger(__name__)

PFAD_ROLLE = Qt.ItemDataRole.UserRole
NAMEN_MAX = 10  # so viele Namen nennt die Rueckfrage, der Rest als Zahl


def _datum(pfad: Path) -> str:
    try:
        return datetime.fromtimestamp(os.stat(pfad).st_mtime).strftime("%d.%m.%Y %H:%M")
    except (OSError, ValueError, OverflowError):
        return ""


def _ordner_text(pfad: Path, wurzel: Path) -> str:
    """Ordner der Datei relativ zum durchsuchten Ordner; „.“ wird zum Namen des Ordners selbst."""
    try:
        rel = pfad.parent.relative_to(wurzel)
    except ValueError:
        return str(pfad.parent)
    return wurzel.name if str(rel) == "." else str(Path(wurzel.name) / rel)


class DoppelteAufraeumenDialog(QDialog):
    """Liste der Gruppen gleicher Dateien unter ``ordner``; ``fenster`` ist das Hauptfenster."""

    ABHOL_MS = 100

    def __init__(self, fenster, ordner: Path):
        super().__init__(fenster)
        self.fenster = fenster
        self.ordner = Path(ordner)
        self._lauf: Optional[dict] = None
        self.gruppen: list[list[Path]] = []
        self.entfernt: list[Path] = []  # in diesem Dialog in den Papierkorb gelegt

        self.setWindowTitle(tr("Doppelte Dateien"))
        self.resize(820, 520)
        layout = QVBoxLayout(self)

        kopf = QLabel(tr("Dateien mit genau demselben Inhalt in „{ordner}“ und seinen Unterordnern.").format(
            ordner=str(self.ordner)))
        kopf.setWordWrap(True)
        layout.addWidget(kopf)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.fortschritt = QProgressBar()
        self.fortschritt.setRange(0, 0)
        self.fortschritt.setTextVisible(False)
        layout.addWidget(self.fortschritt)

        self.liste = QTreeWidget()
        self.liste.setHeaderLabels([tr("Datei"), tr("Ordner"), tr("Geändert")])
        self.liste.setRootIsDecorated(True)
        self.liste.setUniformRowHeights(True)
        kopfzeile = self.liste.header()
        kopfzeile.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        kopfzeile.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        kopfzeile.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        kopfzeile.resizeSection(1, 260)
        self.liste.itemChanged.connect(lambda *_: self._knoepfe_nachfuehren())
        self.liste.itemDoubleClicked.connect(self._doppelklick)
        layout.addWidget(self.liste, stretch=1)

        hinweis = QLabel(tr("Haken setzen bei den Dateien, die in den Papierkorb sollen. Von jeder Gruppe "
                            "bleibt mindestens eine Datei. Doppelklick zeigt die Datei im Dateimanager."))
        hinweis.setWordWrap(True)
        layout.addWidget(hinweis)

        knoepfe = QHBoxLayout()
        self.alle_ausser_aeltester = QPushButton(tr("Je Gruppe alle außer der ältesten markieren"))
        self.alle_ausser_aeltester.clicked.connect(self.alle_ausser_aeltester_markieren)
        knoepfe.addWidget(self.alle_ausser_aeltester)
        self.keine = QPushButton(tr("Keine markieren"))
        self.keine.clicked.connect(self.keine_markieren)
        knoepfe.addWidget(self.keine)
        knoepfe.addStretch(1)
        self.papierkorb_knopf = QPushButton(tr("In den Papierkorb …"))
        self.papierkorb_knopf.clicked.connect(self.markierte_in_papierkorb)
        knoepfe.addWidget(self.papierkorb_knopf)
        self.schliessen_knopf = QPushButton(tr("Schließen"))
        self.schliessen_knopf.clicked.connect(self.reject)
        knoepfe.addWidget(self.schliessen_knopf)
        layout.addLayout(knoepfe)

        self._abholen = QTimer(self)
        self._abholen.setInterval(self.ABHOL_MS)
        self._abholen.timeout.connect(self._ergebnis_holen)
        self._knoepfe_nachfuehren()
        self.suchen()

    # ------------------------------------------------------------------ Suche im Hintergrund

    def suchen(self):
        lauf = {"ordner": self.ordner, "abbrechen": False, "stand": (0, 0), "ergebnis": None}
        self._lauf = lauf
        self.liste.clear()
        self.status_label.setText(tr("Suche doppelte Dateien …"))
        self.fortschritt.setRange(0, 0)
        self.fortschritt.show()
        self._knoepfe_nachfuehren()
        threading.Thread(target=self._rechnen, args=(lauf,), name="doppelte-aufraeumen", daemon=True).start()
        self._abholen.start()

    @staticmethod
    def _rechnen(lauf: dict):
        """Im Hintergrund-Thread; fasst keine Qt-Objekte an (der Dialog kann schon zu sein)."""
        def stand(gelesen, gesamt):
            lauf["stand"] = (gelesen, gesamt)
        try:
            lauf["ergebnis"] = duplikate.doppelte_unter(
                lauf["ordner"], abbrechen=lambda: lauf["abbrechen"], fortschritt=stand)
        except Exception:  # noqa: BLE001 - leere Liste statt Absturz
            logger.exception("Doppelte Dateien aufraeumen: Suche fehlgeschlagen")
            lauf["ergebnis"] = []

    def sucht(self) -> bool:
        return self._lauf is not None

    def _ergebnis_holen(self):
        lauf = self._lauf
        if lauf is None:
            self._abholen.stop()
            return
        if lauf["ergebnis"] is None:
            gelesen, gesamt = lauf["stand"]
            if gesamt:
                self.fortschritt.setRange(0, gesamt)
                self.fortschritt.setValue(gelesen)
                self.status_label.setText(tr("Vergleiche Dateien gleicher Größe: {gelesen} von {gesamt} …").format(
                    gelesen=gelesen, gesamt=gesamt))
            return
        self._abholen.stop()
        self._lauf = None
        self.fortschritt.hide()
        self.anzeigen(lauf["ergebnis"])

    def _suche_beenden(self):
        if self._lauf is not None:
            self._lauf["abbrechen"] = True
            self._lauf = None
        self._abholen.stop()

    def done(self, r):
        self._suche_beenden()
        super().done(r)

    # ------------------------------------------------------------------ Liste

    def anzeigen(self, gruppen: list[list[Path]]):
        self.gruppen = [list(g) for g in gruppen]
        self.liste.blockSignals(True)
        self.liste.clear()
        for gruppe in self.gruppen:
            try:
                groesse = groesse_text(os.stat(gruppe[0]).st_size)
            except OSError:
                groesse = ""
            kopf = QTreeWidgetItem([tr("{anzahl} gleiche Dateien ({groesse})").format(
                anzahl=len(gruppe), groesse=groesse)])
            kopf.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.liste.addTopLevelItem(kopf)
            for pfad in gruppe:
                zeile = QTreeWidgetItem([pfad.name, _ordner_text(pfad, self.ordner), _datum(pfad)])
                zeile.setData(0, PFAD_ROLLE, str(pfad))
                zeile.setToolTip(0, str(pfad))
                zeile.setToolTip(1, str(pfad.parent))
                zeile.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                               | Qt.ItemFlag.ItemIsUserCheckable)
                zeile.setCheckState(0, Qt.CheckState.Unchecked)
                kopf.addChild(zeile)
            kopf.setExpanded(True)
        self.liste.blockSignals(False)
        if not self.gruppen:
            self.status_label.setText(tr("Keine doppelten Dateien gefunden."))
        elif len(self.gruppen) == 1:
            self.status_label.setText(tr("Eine Gruppe mit {dateien} gleichen Dateien gefunden.").format(
                dateien=len(self.gruppen[0])))
        else:
            self.status_label.setText(tr("{gruppen} Gruppen mit zusammen {dateien} gleichen Dateien gefunden.").format(
                gruppen=len(self.gruppen), dateien=sum(len(g) for g in self.gruppen)))
        self._knoepfe_nachfuehren()

    def _zeilen(self):
        """(Gruppen-Kopf, [Dateizeilen]) je Gruppe."""
        for i in range(self.liste.topLevelItemCount()):
            kopf = self.liste.topLevelItem(i)
            yield kopf, [kopf.child(j) for j in range(kopf.childCount())]

    def markierte(self) -> list[Path]:
        return [Path(z.data(0, PFAD_ROLLE)) for _, zeilen in self._zeilen() for z in zeilen
                if z.checkState(0) == Qt.CheckState.Checked]

    def _alle_setzen(self, wert):
        self.liste.blockSignals(True)
        for _, zeilen in self._zeilen():
            for nr, zeile in enumerate(zeilen):
                zeile.setCheckState(0, wert(nr))
        self.liste.blockSignals(False)
        self._knoepfe_nachfuehren()

    def alle_ausser_aeltester_markieren(self):
        """Die erste Datei jeder Gruppe ist die aelteste (``doppelte_unter``)."""
        self._alle_setzen(lambda nr: Qt.CheckState.Unchecked if nr == 0 else Qt.CheckState.Checked)

    def keine_markieren(self):
        self._alle_setzen(lambda nr: Qt.CheckState.Unchecked)

    def _knoepfe_nachfuehren(self):
        bereit = not self.sucht() and bool(self.gruppen)
        self.alle_ausser_aeltester.setEnabled(bereit)
        self.keine.setEnabled(bereit)
        anzahl = len(self.markierte()) if bereit else 0
        self.papierkorb_knopf.setEnabled(anzahl > 0)
        self.papierkorb_knopf.setText(
            tr("{anzahl} in den Papierkorb …").format(anzahl=anzahl) if anzahl else tr("In den Papierkorb …"))

    def _doppelklick(self, zeile: QTreeWidgetItem, _spalte: int):
        pfad = zeile.data(0, PFAD_ROLLE)
        if pfad:
            im_dateimanager_zeigen(pfad)

    # ------------------------------------------------------------------ Papierkorb

    def _rueckfrage(self, pfade: list[Path]) -> bool:
        """Tests ersetzen diese Methode."""
        namen = [p.name for p in pfade[:NAMEN_MAX]]
        if len(pfade) > NAMEN_MAX:
            namen.append(tr("… und {anzahl} weitere").format(anzahl=len(pfade) - NAMEN_MAX))
        if len(pfade) == 1:
            frage = tr("Diese Datei in den Papierkorb legen? Von ihrer Gruppe bleibt mindestens eine Datei.\n\n"
                       "{namen}\n\nMit Strg+Z im Hauptfenster holen Sie sie zurück.")
        else:
            frage = tr("{anzahl} Dateien in den Papierkorb legen? Von jeder Gruppe bleibt mindestens eine Datei.\n\n"
                       "{namen}\n\nMit Strg+Z im Hauptfenster holen Sie sie zurück.")
        antwort = QMessageBox.question(
            self, tr("Doppelte Dateien"),
            frage.format(anzahl=len(pfade), namen="\n".join(namen)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return antwort == QMessageBox.StandardButton.Yes

    def markierte_in_papierkorb(self):
        markiert = self.markierte()
        if not markiert:
            return
        # Von jeder Gruppe muss eine Datei bleiben - und zwar eine, die es noch gibt
        ganz: list[str] = []
        for kopf, zeilen in self._zeilen():
            bleiben = [Path(z.data(0, PFAD_ROLLE)) for z in zeilen if z.checkState(0) != Qt.CheckState.Checked]
            if not any(p.exists() for p in bleiben):
                ganz.append(zeilen[0].text(0) if zeilen else kopf.text(0))
        if ganz:
            QMessageBox.warning(
                self, tr("Doppelte Dateien"),
                tr("Von jeder Gruppe muss mindestens eine Datei bleiben. Bitte bei diesen Gruppen einen Haken "
                   "entfernen:\n\n{liste}").format(liste="\n".join(ganz[:NAMEN_MAX])))
            return
        if not self._rueckfrage(markiert):
            return

        eintraege: list[tuple[Path, Path]] = []
        entfernt: list[Path] = []
        fehler: list[str] = []
        for pfad in markiert:
            try:
                papierkorb = self.fenster.file_manager.delete_file(pfad)
            except PapierkorbNichtVerfuegbar:
                fehler.append(tr("{name}: Papierkorb nicht verfügbar").format(name=pfad.name))
                continue
            except Exception as ex:  # noqa: BLE001 - die uebrigen trotzdem
                fehler.append(f"{pfad.name}: {ex}")
                continue
            entfernt.append(pfad)
            if papierkorb is not None:
                eintraege.append((pfad, papierkorb))
            if self.fenster._pdf_widget_for(pfad) is not None:
                self.fenster.original_entfernt(pfad)  # Kachel im Scan-Bereich wegnehmen

        if eintraege:
            self.fenster._push_undo({
                "type": "wegraeumen",  # ein Strg+Z holt alle zurueck (original_wegraeumen.rueckgaengig)
                "eintraege": eintraege,
                "description": tr("Doppelte Dateien in den Papierkorb: {anzahl}").format(anzahl=len(eintraege)),
            })
        if entfernt:
            self.entfernt.extend(entfernt)
            if len(entfernt) == 1:
                meldung = tr("Doppelte Datei in den Papierkorb gelegt: {name} (Strg+Z holt sie zurück)").format(
                    name=entfernt[0].name)
            else:
                meldung = tr("{anzahl} doppelte Dateien in den Papierkorb gelegt (Strg+Z holt sie zurück)").format(
                    anzahl=len(entfernt))
            self.fenster.statusbar.showMessage(meldung, 8000)
            weg = {os.path.normcase(str(p)) for p in entfernt}
            rest = [[p for p in g if os.path.normcase(str(p)) not in weg] for g in self.gruppen]
            self.anzeigen([g for g in rest if len(g) > 1])
        if fehler:
            QMessageBox.warning(self, tr("Teilweise fehlgeschlagen"),
                                tr("Nicht in den Papierkorb gelegt (die Dateien bleiben, wo sie sind):\n{0}").format(
                                    "\n".join(fehler)))

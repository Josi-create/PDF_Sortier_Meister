"""Protokoll der Textebene: welche PDFs eine unsichtbare OCR-Textebene bekommen haben, mit Rueckgaengig (Phase 5b).

Liest das Protokoll ueber ``Suchindex.textebene_protokoll`` und nimmt eine
Aenderung mit ``Suchindex.textebene_rueckgaengig`` zurueck. Das Zurueckspielen
laeuft in einem eigenen Thread: Es schreibt eine Datei und wartet unter
Umstaenden auf das Schreibrecht der Datenbank, solange ein Indexlauf committet.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.search.suchindex import Suchindex
from src.search.textebene import MELDUNG_GEAENDERT
from src.utils.platform_paths import file_manager_name

SPALTEN = ("Geändert am", "Datei", "Seiten", "Gedreht", "Stand")


def stand_text(e: dict) -> str:
    """Kurzer Stand eines Protokolleintrags."""
    if e.get("status") == "rueckgaengig":
        return "rückgängig gemacht"
    if e.get("sicherung"):
        return "Sicherung vorhanden"
    return "Sicherung abgelaufen"


def gedreht_text(gedreht: str | None) -> str:
    """``"1:180,3:90"`` -> ``"S. 1: 180°, S. 3: 90°"`` (Issue #151); leer, wenn nichts gedreht wurde."""
    teile = []
    for teil in (gedreht or "").split(","):
        seite, _, grad = teil.partition(":")
        if seite.strip() and grad.strip():
            teile.append(f"S. {seite.strip()}: {grad.strip()}°")
    return ", ".join(teile)


class RueckgaengigThread(QThread):
    """``Suchindex.textebene_rueckgaengig`` im Hintergrund; ``fertig(ok, meldung)``."""

    fertig = pyqtSignal(bool, str)

    def __init__(self, index: Suchindex, eintrag_id: int, erzwingen: bool, parent=None):
        super().__init__(parent)
        self.index = index
        self.eintrag_id = eintrag_id
        self.erzwingen = erzwingen

    def run(self) -> None:
        try:
            ok, meldung = self.index.textebene_rueckgaengig(self.eintrag_id, erzwingen=self.erzwingen)
        except Exception as e:  # noqa: BLE001 - nie in die Oberflaeche werfen
            ok, meldung = False, f"Rückgängig machen fehlgeschlagen: {e}"
        self.fertig.emit(ok, meldung)


class TextebeneProtokollDialog(QDialog):
    """Liste der geaenderten Dateien mit „Rückgängig machen“ und „Im Explorer/Finder zeigen“."""

    rueckgaengig_fertig = pyqtSignal(bool, str)   # fuer Tests

    def __init__(self, konfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Textebene – geänderte PDFs")
        self.resize(820, 420)
        self.index = Suchindex(konfig)
        self.eintraege: list[dict] = []
        self._thread: RueckgaengigThread | None = None

        lay = QVBoxLayout(self)
        hinweis = QLabel(
            "Diese PDFs haben eine unsichtbare Textebene mit dem erkannten Text bekommen oder wurden richtig "
            "herum gedreht. Vor jeder Änderung entstand eine Sicherungskopie; solange sie aufbewahrt wird, "
            "lässt sich die Änderung zurücknehmen."
        )
        hinweis.setWordWrap(True)
        lay.addWidget(hinweis)

        self.tabelle = QTableWidget(0, len(SPALTEN))
        self.tabelle.setHorizontalHeaderLabels(SPALTEN)
        self.tabelle.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabelle.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabelle.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabelle.verticalHeader().setVisible(False)
        kopf = self.tabelle.horizontalHeader()
        kopf.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for spalte in (0, 2, 3, 4):
            kopf.setSectionResizeMode(spalte, QHeaderView.ResizeMode.ResizeToContents)
        self.tabelle.itemSelectionChanged.connect(self._auswahl_geaendert)
        lay.addWidget(self.tabelle, 1)

        self.leer_label = QLabel("Noch keine PDF hat eine Textebene bekommen oder wurde gedreht.")
        self.leer_label.setStyleSheet("color: gray;")
        lay.addWidget(self.leer_label)

        knoepfe = QHBoxLayout()
        self.rueckgaengig_button = QPushButton("Rückgängig machen")
        self.rueckgaengig_button.clicked.connect(self._rueckgaengig)
        knoepfe.addWidget(self.rueckgaengig_button)
        self.zeigen_button = QPushButton(f"Im {file_manager_name()} zeigen")
        self.zeigen_button.clicked.connect(self._zeigen)
        knoepfe.addWidget(self.zeigen_button)
        knoepfe.addStretch()
        schliessen = QPushButton("Schließen")
        schliessen.clicked.connect(self.accept)
        knoepfe.addWidget(schliessen)
        lay.addLayout(knoepfe)
        self.laden()

    # ------------------------------------------------------------------ Liste

    def laden(self) -> None:
        try:
            self.eintraege = self.index.textebene_protokoll()
        except Exception:  # noqa: BLE001 - Index fehlt oder ist gesperrt
            self.eintraege = []
        self.tabelle.setRowCount(len(self.eintraege))
        for zeile, e in enumerate(self.eintraege):
            pfad = e.get("aktueller_pfad") or e["pfad"]
            werte = ((e.get("am") or "").replace("T", " "), pfad, e.get("seiten") or "",
                     gedreht_text(e.get("gedreht")), stand_text(e))
            for spalte, wert in enumerate(werte):
                item = QTableWidgetItem(wert)
                item.setData(Qt.ItemDataRole.UserRole, e["id"])
                if spalte == 1:
                    item.setToolTip(pfad)
                self.tabelle.setItem(zeile, spalte, item)
        self.leer_label.setVisible(not self.eintraege)
        self._auswahl_geaendert()

    def ausgewaehlt(self) -> dict | None:
        zeilen = self.tabelle.selectionModel().selectedRows()
        if not zeilen:
            return None
        return self.eintraege[zeilen[0].row()]

    def _auswahl_geaendert(self) -> None:
        e = self.ausgewaehlt()
        laeuft = self._thread is not None and self._thread.isRunning()
        self.rueckgaengig_button.setEnabled(bool(e and e.get("status") == "geschrieben" and e.get("sicherung"))
                                            and not laeuft)
        self.zeigen_button.setEnabled(bool(e and os.path.exists(e.get("aktueller_pfad") or e["pfad"])))

    # ------------------------------------------------------------------ Aktionen

    def _zeigen(self) -> None:
        from src.search import plattform

        e = self.ausgewaehlt()
        if e:
            plattform.im_dateimanager_zeigen(e.get("aktueller_pfad") or e["pfad"])

    def _rueckgaengig(self, erzwingen: bool = False) -> None:
        e = self.ausgewaehlt()
        if e is None:
            return
        name = os.path.basename(e.get("aktueller_pfad") or e["pfad"])
        if not erzwingen and QMessageBox.question(
                self, "Rückgängig machen",
                f"Die Textebene aus „{name}“ entfernen und das Original wiederherstellen?\n\n"
                "Die Datei bekommt danach nicht mehr automatisch eine Textebene.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self._thread = RueckgaengigThread(self.index, e["id"], erzwingen, self)
        self._thread.fertig.connect(lambda ok, meldung, eid=e["id"]: self._fertig(eid, ok, meldung))
        self.rueckgaengig_button.setEnabled(False)
        self._thread.start()

    def _fertig(self, eintrag_id: int, ok: bool, meldung: str) -> None:
        self._thread = None
        if not ok and meldung == MELDUNG_GEAENDERT:
            if QMessageBox.question(
                    self, "Datei wurde seither geändert",
                    meldung + "\n\nTrotzdem das Original wiederherstellen? Die spätere Änderung geht dabei verloren.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                self._auswahl_setzen(eintrag_id)
                self._rueckgaengig(erzwingen=True)
                return
        elif ok:
            QMessageBox.information(self, "Rückgängig gemacht", meldung)
        else:
            QMessageBox.warning(self, "Rückgängig machen nicht möglich", meldung)
        self.laden()
        self._auswahl_setzen(eintrag_id)
        self.rueckgaengig_fertig.emit(ok, meldung)

    def _auswahl_setzen(self, eintrag_id: int) -> None:
        for zeile, e in enumerate(self.eintraege):
            if e["id"] == eintrag_id:
                self.tabelle.selectRow(zeile)
                return

    def done(self, r: int) -> None:  # noqa: D401 - Qt-API
        if self._thread is not None:
            self._thread.wait(30000)
        super().done(r)

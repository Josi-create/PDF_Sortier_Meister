"""Seiten einer PDF bearbeiten: loeschen, umsortieren, drehen (Issue #280).

Kontextmenue einer PDF-Kachel > "Seiten bearbeiten…": Das Fenster zeigt alle
Seiten als Miniaturen. Seiten lassen sich zum Loeschen vormerken (durchkreuzt,
ein zweiter Klick nimmt es zurueck), um 90 Grad drehen und per Ziehen oder mit
den Knoepfen "Nach vorn"/"Nach hinten" umsortieren. "Leere Seiten markieren"
merkt fast weisse Seiten zum Loeschen vor. Geschrieben wird erst mit
"Speichern" (``src.core.pdf_seiten``).

Vorher legt das Programm eine Sicherungskopie in den Programmdaten ab
(``seiten_sicherung``, 30 Tage); Strg+Z holt den alten Stand zurueck (Eintrag
``seiten`` auf dem Rueckgaengig-Stapel des Hauptfensters).

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QItemSelectionModel, QSize, Qt, QTimer
from PyQt6.QtGui import QDrag, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut, QTransform
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from src.core import pdf_seiten
from src.core.pdf_rotate import DrehenNichtMoeglich
from src.gui.farben import qfarbe, stil
from src.i18n import tr

logger = logging.getLogger(__name__)

BILD_BREITE = 150
BILD_HOEHE = 200
SICHERUNG_TAGE = 30

ROLLE_SEITE = Qt.ItemDataRole.UserRole          # bisherige Seitennummer (1-basiert)
ROLLE_GRAD = Qt.ItemDataRole.UserRole + 1       # zusaetzliche Drehung im Uhrzeigersinn
ROLLE_WEG = Qt.ItemDataRole.UserRole + 2        # zum Loeschen vorgemerkt
ROLLE_BILD = Qt.ItemDataRole.UserRole + 3       # QPixmap der Seite, wie sie in der Datei steht


class SeitenListe(QListWidget):
    """Miniaturen in Zeilen; Ziehen sortiert um (die Reihenfolge der Zeilen ist die der Seiten)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setMovement(QListView.Movement.Static)  # Plaetze folgen der Reihenfolge, kein freies Legen
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setWrapping(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setIconSize(QSize(BILD_BREITE, BILD_HOEHE))
        self.setGridSize(QSize(BILD_BREITE + 24, BILD_HOEHE + 40))
        self.setUniformItemSizes(True)
        self.setWordWrap(True)
        # setMovement(Static) schaltet das Ziehen ab - fuer das Umsortieren wieder ein
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def zeilen(self) -> list[int]:
        """Zeilen der ausgewaehlten Seiten, aufsteigend."""
        return sorted(self.row(item) for item in self.selectedItems())

    def zielzeile(self, punkt) -> int:
        """Zeile, vor der an ``punkt`` abgelegt wird (rechte Haelfte einer Seite: dahinter)."""
        item = self.itemAt(punkt)
        if item is None:
            return self.count()
        zeile = self.row(item)
        return zeile + 1 if punkt.x() > self.visualItemRect(item).center().x() else zeile

    def verschieben(self, zeilen: list[int], ziel: int) -> bool:
        """Legt die Seiten ``zeilen`` gemeinsam vor die Zeile ``ziel``. ``True``, wenn sich etwas aendert."""
        zeilen = sorted(set(zeilen))
        if not zeilen:
            return False
        ziel = max(0, min(ziel, self.count()))
        neu_ab = ziel - sum(1 for z in zeilen if z < ziel)
        if zeilen == list(range(neu_ab, neu_ab + len(zeilen))):
            return False
        items = [self.takeItem(z) for z in reversed(zeilen)][::-1]
        for versatz, item in enumerate(items):
            self.insertItem(neu_ab + versatz, item)
        self.clearSelection()
        self.setCurrentItem(items[0], QItemSelectionModel.SelectionFlag.NoUpdate)
        for item in items:
            item.setSelected(True)
        self.scrollToItem(items[0])
        return True

    # Ziehen und Ablegen laufen ganz ueber diese vier Methoden: Die Liste sortiert selbst um
    # (``verschieben``) und ueberlaesst Qt weder das Verschieben noch das Entfernen der Eintraege.

    def startDrag(self, supported_actions):  # noqa: N802 - Qt-API
        items = self.selectedItems()
        if not items:
            return
        drag = QDrag(self)
        drag.setMimeData(self.model().mimeData(self.selectedIndexes()))
        bild = (self.currentItem() if self.currentItem() in items else items[0]).icon().pixmap(
            BILD_BREITE // 2, BILD_HOEHE // 2)
        drag.setPixmap(bild)
        drag.setHotSpot(bild.rect().center())
        drag.exec(Qt.DropAction.MoveAction)

    def _eigenes_ziehen(self, event) -> bool:
        if event.source() is self:
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return True
        event.ignore()
        return False

    def dragEnterEvent(self, event):  # noqa: N802 - Qt-API
        self._eigenes_ziehen(event)

    def dragMoveEvent(self, event):  # noqa: N802 - Qt-API
        super().dragMoveEvent(event)  # rollt die Liste am Rand weiter
        self._eigenes_ziehen(event)

    def dropEvent(self, event):  # noqa: N802 - Qt-API
        if not self._eigenes_ziehen(event):
            return
        self.verschieben(self.zeilen(), self.zielzeile(event.position().toPoint()))


class SeitenBearbeitenDialog(QDialog):
    """Miniaturen aller Seiten; ``plan()`` liefert nach "Speichern", was bleibt."""

    def __init__(self, pdf_path: Path, parent=None):
        super().__init__(parent)
        self.pdf_path = Path(pdf_path)
        self._doc = None
        self._offen: list[int] = []  # Seiten, deren Miniatur noch fehlt

        self.setWindowTitle(tr("Seiten bearbeiten"))
        self.setModal(True)
        self.resize(900, 640)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        kopf = QLabel(tr(
            "<b>{name}</b><br>Seiten anklicken (mit Strg oder Umschalt mehrere), dann löschen oder "
            "drehen. Die Reihenfolge änderst du durch Ziehen oder mit „Nach vorn“ und „Nach hinten“. "
            "Geändert wird die Datei erst mit „Speichern“."
        ).format(name=self.pdf_path.name))
        kopf.setWordWrap(True)
        kopf.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(kopf)

        leiste = QHBoxLayout()
        self.btn_loeschen = QPushButton(tr("Löschen"))
        self.btn_loeschen.setToolTip(tr("Ausgewählte Seiten zum Löschen vormerken oder die Vormerkung aufheben (Entf)"))
        self.btn_loeschen.clicked.connect(self.loeschen_umschalten)
        self.btn_links = QPushButton(tr("90° nach links"))
        self.btn_links.clicked.connect(lambda: self.drehen(-90))
        self.btn_rechts = QPushButton(tr("90° nach rechts"))
        self.btn_rechts.clicked.connect(lambda: self.drehen(90))
        self.btn_vor = QPushButton(tr("Nach vorn"))
        self.btn_vor.setToolTip(tr("Ausgewählte Seiten um eine Stelle nach vorn schieben (Strg+Pfeil links)"))
        self.btn_vor.clicked.connect(lambda: self.schieben(-1))
        self.btn_zurueck = QPushButton(tr("Nach hinten"))
        self.btn_zurueck.setToolTip(tr("Ausgewählte Seiten um eine Stelle nach hinten schieben (Strg+Pfeil rechts)"))
        self.btn_zurueck.clicked.connect(lambda: self.schieben(1))
        self.btn_leere = QPushButton(tr("Leere Seiten markieren"))
        self.btn_leere.setToolTip(tr(
            "Sucht fast weiße Seiten (leere Rückseiten) und merkt sie zum Löschen vor. "
            "Gelöscht wird erst mit „Speichern“."))
        self.btn_leere.clicked.connect(self.leere_markieren)
        for knopf in (self.btn_loeschen, self.btn_links, self.btn_rechts, self.btn_vor, self.btn_zurueck):
            leiste.addWidget(knopf)
        leiste.addStretch(1)
        leiste.addWidget(self.btn_leere)
        layout.addLayout(leiste)

        self.liste = SeitenListe(self)
        self.liste.itemSelectionChanged.connect(self._stand_zeigen)
        self.liste.model().rowsInserted.connect(lambda *_: self._stand_zeigen())
        layout.addWidget(self.liste, 1)

        self.stand = QLabel("")
        stil(self.stand, "color: $grau_66;")
        layout.addWidget(self.stand)

        self.knoepfe = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.knoepfe.button(QDialogButtonBox.StandardButton.Save).setText(tr("Speichern"))
        self.knoepfe.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Abbrechen"))
        self.knoepfe.accepted.connect(self.accept)
        self.knoepfe.rejected.connect(self.reject)
        layout.addWidget(self.knoepfe)

        for taste, slot in (
            (QKeySequence(Qt.Key.Key_Delete), self.loeschen_umschalten),
            (QKeySequence("Ctrl+Left"), lambda: self.schieben(-1)),
            (QKeySequence("Ctrl+Right"), lambda: self.schieben(1)),
        ):
            kuerzel = QShortcut(taste, self.liste)
            kuerzel.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            kuerzel.activated.connect(slot)

        self._fuellen()
        self._stand_zeigen()

    # --- Seiten laden ---

    def _fuellen(self) -> None:
        import pymupdf

        try:
            self._doc = pymupdf.open(str(self.pdf_path))
            anzahl = self._doc.page_count
        except Exception as e:  # noqa: BLE001 - dann bleibt die Liste leer, Speichern aus
            logger.warning("Seiten bearbeiten: %s nicht lesbar (%s)", self.pdf_path.name, e)
            self._doc = None
            anzahl = 0
        self.seitenzahl = anzahl
        for nr in range(1, anzahl + 1):
            item = QListWidgetItem("")
            item.setData(ROLLE_SEITE, nr)
            item.setData(ROLLE_GRAD, 0)
            item.setData(ROLLE_WEG, False)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            self.liste.addItem(item)
            self._schmuecken(item)
        # Miniaturen nach und nach: das Fenster steht auch bei langen Scans sofort
        self._offen = list(range(1, anzahl + 1))
        self._lader = QTimer(self)
        self._lader.setInterval(0)
        self._lader.timeout.connect(self._naechste_laden)
        if self._offen:
            self._lader.start()

    def _item(self, seite: int) -> QListWidgetItem | None:
        for zeile in range(self.liste.count()):
            item = self.liste.item(zeile)
            if item.data(ROLLE_SEITE) == seite:
                return item
        return None

    def _naechste_laden(self) -> None:
        if not self._offen or self._doc is None:
            self._lader.stop()
            return
        seite = self._offen.pop(0)
        item = self._item(seite)
        if item is not None:
            bild = self._seitenbild(seite)
            if bild is not None:
                item.setData(ROLLE_BILD, bild)
                self._schmuecken(item)
        if not self._offen:
            self._lader.stop()

    def alle_laden(self) -> None:
        """Alle noch fehlenden Miniaturen sofort laden (Tests)."""
        while self._offen and self._doc is not None:
            self._naechste_laden()

    def _seitenbild(self, seite: int) -> QPixmap | None:
        try:
            import pymupdf

            page = self._doc[seite - 1]
            faktor = (BILD_HOEHE * 1.5) / max(page.rect.height, page.rect.width, 1)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(faktor, faktor), alpha=False)
            bild = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
            return QPixmap.fromImage(bild.copy())
        except Exception as e:  # noqa: BLE001 - ohne Bild bleibt der Platzhalter
            logger.debug("Seiten bearbeiten: Seite %s ohne Miniatur (%s)", seite, e)
            return None

    # --- Anzeige ---

    def gezeigt(self, item: QListWidgetItem) -> QPixmap:
        """Die Seite, wie sie nach dem Speichern liegt: gedreht und auf die Miniaturgroesse gebracht."""
        bild = item.data(ROLLE_BILD)
        if not isinstance(bild, QPixmap) or bild.isNull():
            bild = QPixmap(BILD_BREITE, BILD_HOEHE)  # Platzhalter, bis die Seite geladen ist
            bild.fill(qfarbe("weiss"))
            return bild
        grad = item.data(ROLLE_GRAD)
        if grad:
            bild = bild.transformed(QTransform().rotate(grad), Qt.TransformationMode.SmoothTransformation)
        return bild.scaled(BILD_BREITE, BILD_HOEHE, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)

    def _schmuecken(self, item: QListWidgetItem) -> None:
        """Miniatur (gedreht, durchkreuzt wenn vorgemerkt) und Beschriftung der Seite setzen."""
        seite, grad, weg = item.data(ROLLE_SEITE), item.data(ROLLE_GRAD), item.data(ROLLE_WEG)
        bild = self.gezeigt(item)
        # Alle Miniaturen auf gleich grosser Flaeche (Beschriftung auf einer Hoehe), mit Rand:
        # eine leere weisse Seite waere auf weissem Grund sonst nicht zu sehen
        flaeche = QPixmap(BILD_BREITE, BILD_HOEHE)
        flaeche.fill(Qt.GlobalColor.transparent)
        maler = QPainter(flaeche)
        maler.setRenderHint(QPainter.RenderHint.Antialiasing)
        blatt = bild.rect().translated((BILD_BREITE - bild.width()) // 2, (BILD_HOEHE - bild.height()) // 2)
        maler.drawPixmap(blatt.topLeft(), bild)
        if weg:
            schleier = qfarbe("weiss")
            schleier.setAlpha(170)
            maler.fillRect(blatt, schleier)
            maler.setPen(QPen(qfarbe("rot"), 5))
            r = blatt.adjusted(12, 12, -12, -12)
            maler.drawLine(r.topLeft(), r.bottomRight())
            maler.drawLine(r.topRight(), r.bottomLeft())
        maler.setPen(QPen(qfarbe("grau_aa"), 1))
        maler.drawRect(blatt.adjusted(0, 0, -1, -1))
        maler.end()
        item.setIcon(QIcon(flaeche))
        if weg:
            item.setText(tr("Seite {nr} – wird gelöscht").format(nr=seite))
        else:
            item.setText(tr("Seite {nr}").format(nr=seite))
        item.setToolTip(tr("Seite {nr} der bisherigen PDF").format(nr=seite))

    def _stand_zeigen(self) -> None:
        if not hasattr(self, "stand"):
            return
        plan = self.plan()
        weg = self.seitenzahl - len(plan)
        teile = [tr("{anzahl} Seite(n)").format(anzahl=self.seitenzahl)]
        if weg:
            teile.append(tr("{anzahl} werden gelöscht").format(anzahl=weg))
        if not plan and self.seitenzahl:
            teile.append(tr("mindestens eine Seite muss bleiben"))
        elif self.geaendert() and not weg:
            teile.append(tr("geändert"))
        self.stand.setText(" · ".join(teile))
        gewaehlt = bool(self.liste.selectedItems())
        for knopf in (self.btn_loeschen, self.btn_links, self.btn_rechts, self.btn_vor, self.btn_zurueck):
            knopf.setEnabled(gewaehlt)
        alle_weg = gewaehlt and all(item.data(ROLLE_WEG) for item in self.liste.selectedItems())
        self.btn_loeschen.setText(tr("Doch behalten") if alle_weg else tr("Löschen"))
        self.btn_leere.setEnabled(self.seitenzahl > 0)
        self.knoepfe.button(QDialogButtonBox.StandardButton.Save).setEnabled(bool(plan) and self.geaendert())

    # --- Aktionen ---

    def loeschen_umschalten(self) -> None:
        """Ausgewaehlte Seiten vormerken; sind schon alle vorgemerkt, die Vormerkung aufheben."""
        items = self.liste.selectedItems()
        if not items:
            return
        weg = not all(item.data(ROLLE_WEG) for item in items)
        for item in items:
            item.setData(ROLLE_WEG, weg)
            self._schmuecken(item)
        self._stand_zeigen()

    def drehen(self, grad: int) -> None:
        for item in self.liste.selectedItems():
            item.setData(ROLLE_GRAD, (item.data(ROLLE_GRAD) + grad) % 360)
            self._schmuecken(item)
        self._stand_zeigen()

    def schieben(self, schritt: int) -> None:
        """Ausgewaehlte Seiten gemeinsam um eine Stelle nach vorn (-1) oder hinten (+1)."""
        zeilen = self.liste.zeilen()
        if not zeilen:
            return
        ziel = zeilen[0] - 1 if schritt < 0 else zeilen[-1] + 2
        if ziel < 0 or ziel > self.liste.count():
            return
        self.liste.verschieben(zeilen, ziel)
        self._stand_zeigen()

    def leere_markieren(self) -> list[int]:
        """Fast weisse Seiten zum Loeschen vormerken und auswaehlen. Liefert ihre Nummern."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            leere = pdf_seiten.leere_seiten(self.pdf_path)
        except Exception as e:  # noqa: BLE001 - dann eben kein Vorschlag
            logger.warning("Leere Seiten in %s nicht bestimmt (%s)", self.pdf_path.name, e)
            leere = []
        finally:
            QApplication.restoreOverrideCursor()
        self.liste.clearSelection()
        for seite in leere:
            item = self._item(seite)
            if item is None:
                continue
            item.setData(ROLLE_WEG, True)
            self._schmuecken(item)
            item.setSelected(True)
        self._stand_zeigen()
        if leere:
            self.stand.setText(self.stand.text() + " · " + tr(
                "{anzahl} leere Seite(n) vorgemerkt – bitte ansehen, „Doch behalten“ nimmt eine wieder heraus"
            ).format(anzahl=len(leere)))
        else:
            self.stand.setText(self.stand.text() + " · " + tr("keine leere Seite gefunden"))
        return leere

    # --- Ergebnis ---

    def plan(self) -> list[tuple[int, int]]:
        """``(bisherige Seite, Drehung)`` der bleibenden Seiten in der neuen Reihenfolge."""
        plan = []
        for zeile in range(self.liste.count()):
            item = self.liste.item(zeile)
            if not item.data(ROLLE_WEG):
                plan.append((item.data(ROLLE_SEITE), item.data(ROLLE_GRAD)))
        return plan

    def geaendert(self) -> bool:
        return not pdf_seiten.unveraendert(self.plan(), self.seitenzahl)

    def done(self, r: int) -> None:  # noqa: D401 - Qt-API
        # Die Datei freigeben, bevor sie ersetzt wird (Windows sperrt geoeffnete Dateien)
        self._lader.stop()
        self._offen = []
        if self._doc is not None:
            try:
                self._doc.close()
            except Exception:  # noqa: BLE001
                pass
            self._doc = None
        super().done(r)


# --- Anbindung an das Hauptfenster ---

def sicherungs_ordner() -> Path:
    from src.utils.platform_paths import get_app_data_dir

    return get_app_data_dir() / "seiten_sicherung"


def _alte_sicherungen_entfernen(wurzel: Path) -> None:
    if not wurzel.is_dir():
        return
    grenze = time.time() - SICHERUNG_TAGE * 86400
    for eintrag in wurzel.iterdir():
        try:
            if eintrag.is_dir() and eintrag.stat().st_mtime < grenze:
                shutil.rmtree(eintrag)
        except OSError as e:
            logger.warning("Alte Seiten-Sicherung nicht entfernt: %s (%s)", eintrag, e)


def _dialog(main, pdf_path: Path) -> list[tuple[int, int]] | None:
    """Zeigt das Fenster; liefert den Plan oder ``None`` bei Abbruch. Tests ersetzen diese Funktion."""
    dialog = SeitenBearbeitenDialog(pdf_path, parent=main)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.plan()


def bearbeiten(main, pdf_path: Path) -> bool:
    """Kontextmenue "Seiten bearbeiten…": Fenster zeigen, speichern, Rueckgaengig-Eintrag anlegen."""
    pdf_path = Path(pdf_path)
    titel = tr("Seiten bearbeiten")
    from src.gui.nicht_lesbar import melden_falls_nicht_lesbar

    if melden_falls_nicht_lesbar(main, titel, [pdf_path]):  # Issue #414: sonst z. B. leeres Fenster
        return False
    try:
        anzahl = pdf_seiten.seitenzahl(pdf_path)
    except DrehenNichtMoeglich as e:
        QMessageBox.information(main, titel, f"{pdf_path.name}\n\n{e}")
        return False
    except Exception as e:  # noqa: BLE001
        QMessageBox.critical(main, tr("Fehler"), tr("PDF konnte nicht geöffnet werden:\n{e}").format(e=e))
        return False

    main._wait_for_metadata_writes([pdf_path])
    plan = _dialog(main, pdf_path)
    if not plan or pdf_seiten.unveraendert(plan, anzahl):
        return False

    main._wait_for_metadata_writes([pdf_path])  # waehrend das Fenster offen war, kann einer begonnen haben
    wurzel = sicherungs_ordner()
    sicherung = wurzel / datetime.now().strftime("%Y%m%d-%H%M%S-%f") / pdf_path.name
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        pdf_seiten.seiten_schreiben(pdf_path, plan, sicherung)
    except PermissionError:
        QApplication.restoreOverrideCursor()
        QMessageBox.warning(main, titel, tr("{name}: Die Datei ist geöffnet oder gesperrt.").format(name=pdf_path.name))
        return False
    except Exception as e:  # noqa: BLE001
        QApplication.restoreOverrideCursor()
        QMessageBox.critical(main, tr("Fehler"), tr("Seiten konnten nicht gespeichert werden:\n{e}").format(e=e))
        return False
    QApplication.restoreOverrideCursor()
    _alte_sicherungen_entfernen(wurzel)

    geloescht = anzahl - len(plan)
    if geloescht:
        was = tr("{name}: {geloescht} Seite(n) gelöscht").format(name=pdf_path.name, geloescht=geloescht)
    else:
        was = tr("{name}: Seiten geändert").format(name=pdf_path.name)
    main._push_undo({"type": "seiten", "path": pdf_path, "sicherung": sicherung, "description": was})
    main._pdf_inhalt_geaendert(pdf_path)
    main.statusbar.showMessage(tr("{desc} (Ctrl+Z macht es rückgängig)").format(desc=was), 6000)
    return True


def rueckgaengig(main, entry: dict) -> None:
    """Strg+Z: den Stand vor dem Bearbeiten aus der Sicherungskopie zurueckholen."""
    pdf_path, sicherung = Path(entry["path"]), Path(entry["sicherung"])
    if not pdf_path.exists():
        main._undo_stack.pop()
        main._update_undo_ui()
        main.statusbar.showMessage(
            tr("Rückgängig nicht möglich: {name} liegt nicht mehr am alten Ort.").format(name=pdf_path.name), 6000)
        return
    main._wait_for_metadata_writes([pdf_path])
    try:
        pdf_seiten.wiederherstellen(pdf_path, sicherung)
    except PermissionError:
        # Eintrag bleibt: die Sicherung ist noch da, ein neuer Versuch ist moeglich
        QMessageBox.warning(main, tr("Rückgängig machen"),
                            tr("{name}: Die Datei ist geöffnet oder gesperrt.").format(name=pdf_path.name))
        return
    except Exception as e:  # noqa: BLE001
        main._undo_stack.pop()
        main._update_undo_ui()
        QMessageBox.critical(main, tr("Fehler"), tr("Rückgängig fehlgeschlagen:\n{e}").format(e=e))
        return
    main._undo_stack.pop()
    main._update_undo_ui()
    main._pdf_inhalt_geaendert(pdf_path)
    main.statusbar.showMessage(tr("Rückgängig: {description}").format(description=entry["description"]), 5000)

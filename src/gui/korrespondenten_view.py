"""Reiter "Korrespondenten" in der linken Spalte (Issue #160).

Oben ein Suchfeld und die Liste aller Korrespondenten aus dem Suchindex
(gleichwertige Schreibweisen und gespeicherte Aliasse zusammengefasst,
haeufigste zuerst). Ein Klick zeigt darunter alle Dokumente dieses
Korrespondenten (Datum, Dateiname, Ablageort, Kategorie; neueste zuerst).
Ein Klick auf ein Dokument waehlt es wie ein PDF unter "PDFs" (Felder, Vorschau,
Ordnervorschlaege; ``dokumente_gewaehlt``), mit Strg/Umschalt auch mehrere. Sie lassen
sich verschieben, kopieren und auf einen Ordner ziehen. Ein Doppelklick oeffnet das
Dokument extern, das Kontextmenue bietet "Im Explorer anzeigen" und "Ordner links öffnen".

Keine Handpflege: Unsichere Schreibweisen ("Stadtwerke GÖ" / "Stadtwerke
Göttingen") gleicht die KI einmal je Sitzung im Hintergrund ab und speichert
das Ergebnis als Alias. "Aufräumen…" bewertet nur auffaellige Dokumente
neu (Korrespondent leer, der Nutzer selbst oder ein Formularverlag) und
schreibt das Ergebnis wie "Metadaten speichern" in PDF und Suchindex.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import QMimeData, QPoint, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDrag
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core import korrespondenten as kr

logger = logging.getLogger(__name__)

# Text, der je Dokument an die KI geht (der Provider kuerzt selbst auf sein Limit)
TEXT_ZEICHEN = 20000


def _datum(d: dict) -> str:
    """Buchungsdatum des Dokuments, sonst das Dateidatum (JJJJ-MM-TT)."""
    if d.get("buchungsdatum"):
        return str(d["buchungsdatum"])[:10]
    try:
        return datetime.fromtimestamp(float(d["datum"])).strftime("%Y-%m-%d")
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return ""


def _pdf_signiert(pfad: Path) -> bool:
    """Digital signiert? Dann bleibt die Datei unberuehrt (die Signatur waere sonst ungueltig)."""
    try:
        import pikepdf

        from src.core.pdf_rotate import _signiert

        with pikepdf.open(pfad) as pdf:
            return _signiert(pdf)
    except Exception:  # noqa: BLE001 - unlesbar: write_metadata meldet den Fehler selbst
        return False


class _KiAbgleich(QThread):
    """Fragt die KI, welche unsicheren Paare denselben Korrespondenten meinen."""

    fertig = pyqtSignal(list, str)  # [(a, b, gleich)], Fehlertext

    def __init__(self, provider, paare: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self._provider = provider
        self._paare = paare

    def run(self):
        try:
            antwort = self._provider.answer_with_context(
                kr.KI_SYSTEM_PROMPT, [], kr.ki_frage(self._paare), max_tokens=1500,
            )
        except Exception as e:  # noqa: BLE001 - Abgleich ist Komfort
            self.fertig.emit([], str(e))
            return
        self.fertig.emit(kr.ki_antwort_lesen(antwort or "", self._paare), "")


class _Aufraeumen(QThread):
    """Bewertet auffaellige Dokumente ueber den KI-Metadatenweg neu und schreibt den Korrespondenten in die PDF."""

    fortschritt = pyqtSignal(int, int, str)       # erledigt, gesamt, Dateiname
    geaendert = pyqtSignal(dict, str, bool)       # Dokument, neuer Korrespondent, in die PDF geschrieben
    fertig = pyqtSignal(dict)                     # Zaehler

    def __init__(self, hybrid, index, dokumente: list[dict], eintraege: list[dict], owner: list[str], parent=None):
        super().__init__(parent)
        self._hybrid = hybrid
        self._index = index
        self._dokumente = dokumente
        self._eintraege = eintraege
        self._owner = owner

    def run(self):
        n = len(self._dokumente)
        stand = {"gesamt": n, "geaendert": 0, "unveraendert": 0, "fehler": 0, "abgebrochen": False}
        for i, d in enumerate(self._dokumente):
            if self.isInterruptionRequested():
                stand["abgebrochen"] = True
                break
            self.fortschritt.emit(i, n, str(d.get("name") or ""))
            try:
                neu, geschrieben = self._bewerten(d)
            except Exception as e:  # noqa: BLE001 - je Dokument zaehlen, weitermachen
                logger.info(f"Korrespondent fuer {d.get('name')} nicht neu bewertet: {e}")
                stand["fehler"] += 1
                continue
            if neu:
                stand["geaendert"] += 1
                self.geaendert.emit(d, neu, geschrieben)
            else:
                stand["unveraendert"] += 1
        erledigt = stand["geaendert"] + stand["unveraendert"] + stand["fehler"]
        self.fortschritt.emit(erledigt, n, "")
        self.fertig.emit(stand)

    def _bewerten(self, d: dict) -> tuple[str, bool]:
        """Neuer Korrespondent (leer = keiner bzw. wieder auffaellig) und ob er in die PDF kam."""
        from src.core.llm_activity import KIND_SUGGEST, get_llm_activity
        from src.ml.hybrid_classifier import source_folder_hint

        pfad = Path(d.get("datei") or d.get("pfad") or "")
        text = self._index.volltext(int(d["id"]), TEXT_ZEICHEN) if d.get("id") is not None else ""
        if not (text or "").strip():
            return "", False
        activity = get_llm_activity()
        token = activity.begin(KIND_SUGGEST, pfad.name)
        ok = False
        try:
            vorschlaege = self._hybrid.suggest_filename(
                text=text, current_filename=pfad.name, use_llm=True, source_folder=source_folder_hint(pfad),
            )
            ok = True
        finally:
            activity.end(token, success=ok)
        roh = ""
        for s in vorschlaege or []:
            if getattr(s, "source", "") == "llm" and isinstance(getattr(s, "metadata", None), dict):
                roh = str(s.metadata.get("korrespondent") or "").strip()
                break
        else:
            fehler = getattr(self._hybrid, "last_llm_error", None)
            if fehler:
                raise RuntimeError(fehler)
        if not roh or kr.auffaelligkeit(roh, self._owner):
            return "", False
        neu = kr.kanonisch(roh, self._eintraege)
        if kr.schluessel(neu) == kr.schluessel(str(d.get("korrespondent") or "")):
            return "", False
        geschrieben = False
        if pfad.suffix.lower() == ".pdf" and pfad.is_file() and not _pdf_signiert(pfad):
            from src.core.pdf_metadata import PDFMetadata, write_metadata

            geschrieben = bool(write_metadata(pfad, PDFMetadata(korrespondent=neu)))
        return neu, geschrieben


def dokument_pfad(d: dict) -> Path:
    """Pfad der Datei eines Index-Eintrags (bei Mails aus einer mbox deren Datei)."""
    return Path(d.get("datei") or d.get("pfad") or "")


class _DokumentListe(QTreeWidget):
    """Dokumentliste: mehrere markierbar, Ziehen auf einen Ordner (Strg = kopieren)."""

    def mimeData(self, items):  # noqa: N802 - Qt-Signatur
        mime = QMimeData()
        pfade = []
        for item in items:
            d = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(d, dict):
                pfade.append(dokument_pfad(d))
        mime.setUrls([QUrl.fromLocalFile(str(p)) for p in pfade])
        mime.setText(str(pfade[0]) if len(pfade) == 1 else f"{len(pfade)} Dokumente")
        return mime

    def startDrag(self, supportedActions):  # noqa: N802 - Qt-Signatur
        items = self.selectedItems()
        if not items:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(items))
        drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction, Qt.DropAction.MoveAction)


class KorrespondentenView(QWidget):
    """Inhalt des Reiters "Korrespondenten".

    Signale:
        dokumente_gewaehlt(list): markierte Dokumente (Zeilen des Suchindex; leer = nichts markiert)
        dokument_oeffnen(Path): Doppelklick - extern oeffnen
        ordner_oeffnen(Path): Kontextmenue "Ordner links öffnen"
        einrichten_requested: Knopf im Hinweis (Einstellungen > Suche)
        aufraeumen_fertig(dict): Zaehler eines abgeschlossenen Aufraeumens (auch fuer Tests)
        abgleich_fertig(int): Anzahl der von der KI zusammengefuehrten Paare (auch fuer Tests)
    """

    dokumente_gewaehlt = pyqtSignal(list)
    dokument_oeffnen = pyqtSignal(Path)
    ordner_oeffnen = pyqtSignal(Path)
    einrichten_requested = pyqtSignal()
    aufraeumen_fertig = pyqtSignal(dict)
    abgleich_fertig = pyqtSignal(int)

    def __init__(self, db, config, hybrid=None, wurzeln: Callable[[], list] | None = None, parent=None):
        """``db``: :class:`~src.utils.database.Database` (Suchindex und Verwaltung), ``config``: Konfiguration,
        ``hybrid``: KI-Klassifikator (Abgleich, Aufraeumen), ``wurzeln``: liefert die Zielordner."""
        super().__init__(parent)
        self.db = db
        self.config = config
        self.hybrid = hybrid
        self._wurzeln = wurzeln or (lambda: [])
        self.gruppen: list[kr.Gruppe] = []
        self._eintrag_namen: set[str] = set()
        self._aktuelle: kr.Gruppe | None = None
        self._ki_versucht = False
        self._ki_thread: _KiAbgleich | None = None
        self._aufraeumen_thread: _Aufraeumen | None = None
        self._ui_bauen()

    # ------------------------------------------------------------------ Aufbau

    def _ui_bauen(self) -> None:
        aussen = QVBoxLayout(self)
        aussen.setContentsMargins(4, 4, 4, 4)
        aussen.setSpacing(4)

        self.hinweis = QFrame()
        self.hinweis.setObjectName("korrHinweis")
        self.hinweis.setStyleSheet("QFrame#korrHinweis { background: #fff8e1; border: 1px solid #f0d58c; "
                                   "border-radius: 6px; }")
        h = QVBoxLayout(self.hinweis)
        h.setContentsMargins(10, 8, 10, 8)
        text = QLabel("Die Korrespondenten kommen aus dem Suchindex. Richten Sie dazu die Dokumentensuche "
                      "ein – sie bleibt ganz auf diesem Rechner.")
        text.setWordWrap(True)
        h.addWidget(text)
        self.einrichten_button = QPushButton("Suche einrichten…")
        self.einrichten_button.setToolTip("Einstellungen > Suche öffnen")
        self.einrichten_button.clicked.connect(self.einrichten_requested)
        h.addWidget(self.einrichten_button, 0, Qt.AlignmentFlag.AlignLeft)
        aussen.addWidget(self.hinweis)

        self.inhalt = QWidget()
        lay = QVBoxLayout(self.inhalt)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        kopf = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Korrespondent suchen…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._filter_anwenden)
        kopf.addWidget(self.filter_edit, 1)
        self.aufraeumen_button = QToolButton()
        self.aufraeumen_button.setText("Aufräumen…")
        self.aufraeumen_button.setAutoRaise(True)
        self.aufraeumen_button.setToolTip(
            "Korrespondenten aufräumen: Dokumente in den Zielordnern ohne Korrespondent, mit Ihrem\n"
            "eigenen Namen oder einem Formularverlag (z. B. „Haus & Grund“) von der KI neu bewerten\n"
            "lassen. Vorher erscheint die Anzahl; abbrechen geht jederzeit."
        )
        self.aufraeumen_button.clicked.connect(self.aufraeumen)
        kopf.addWidget(self.aufraeumen_button)
        lay.addLayout(kopf)

        # Fortschritt des Aufraeumens (nur waehrend es laeuft)
        self.fortschritt_box = QWidget()
        f = QHBoxLayout(self.fortschritt_box)
        f.setContentsMargins(0, 0, 0, 0)
        self.fortschritt_bar = QProgressBar()
        self.fortschritt_bar.setTextVisible(True)
        self.fortschritt_bar.setFormat("%v / %m")
        f.addWidget(self.fortschritt_bar, 1)
        self.abbrechen_button = QPushButton("Abbrechen")
        self.abbrechen_button.clicked.connect(self.abbrechen)
        f.addWidget(self.abbrechen_button)
        self.fortschritt_box.hide()
        lay.addWidget(self.fortschritt_box)
        self.fortschritt_label = QLabel("")
        self.fortschritt_label.setStyleSheet("color: #666; font-size: 10px;")
        self.fortschritt_label.hide()
        lay.addWidget(self.fortschritt_label)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.liste = QListWidget()
        self.liste.setAlternatingRowColors(True)
        self.liste.currentItemChanged.connect(lambda neu, _alt: self._gruppe_gewaehlt(neu))
        self.splitter.addWidget(self.liste)

        unten = QWidget()
        u = QVBoxLayout(unten)
        u.setContentsMargins(0, 0, 0, 0)
        u.setSpacing(2)
        self.dokumente_label = QLabel("Korrespondent anklicken, um seine Dokumente zu sehen.")
        self.dokumente_label.setWordWrap(True)
        self.dokumente_label.setStyleSheet("font-weight: bold; padding: 2px;")
        u.addWidget(self.dokumente_label)
        self.dokumente = _DokumentListe()
        self.dokumente.setHeaderLabels(["Datum", "Dateiname", "Ablageort", "Kategorie"])
        self.dokumente.setRootIsDecorated(False)
        self.dokumente.setAlternatingRowColors(True)
        self.dokumente.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.dokumente.setDragEnabled(True)
        self.dokumente.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.dokumente.setToolTip(
            "Klick: Dokument wie unter „PDFs“ bearbeiten · Strg/Umschalt: mehrere markieren · "
            "auf einen Ordner ziehen (Strg: kopieren) · Doppelklick: öffnen · Rechtsklick: weitere Aktionen")
        self.dokumente.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.dokumente.customContextMenuRequested.connect(self._dokument_menue_zeigen)
        self.dokumente.itemSelectionChanged.connect(self._auswahl_geaendert)
        self.dokumente.itemDoubleClicked.connect(lambda item, _s: self._dokument_doppelklick(item))
        u.addWidget(self.dokumente, 1)
        self.splitter.addWidget(unten)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)
        lay.addWidget(self.splitter, 1)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #666; font-size: 10px;")
        lay.addWidget(self.status_label)
        aussen.addWidget(self.inhalt, 1)

    # ------------------------------------------------------------------ Zustand

    @property
    def index(self):
        return self.db.suchindex

    def suche_aktiv(self) -> bool:
        try:
            return bool(self.config.get_search_config().aktiv)
        except Exception:  # noqa: BLE001
            return False

    def _owner(self) -> list[str]:
        return kr.owner_namen(self.config)

    def _provider(self):
        h = self.hybrid
        try:
            return h.llm_provider if h is not None and h.is_llm_available() else None
        except Exception:  # noqa: BLE001
            return None

    def _meldung(self, text: str) -> None:
        self.status_label.setText(text)

    # ------------------------------------------------------------------ Liste

    def refresh(self, abgleich: bool = True) -> None:
        """Liste aus dem Suchindex neu laden; die Auswahl bleibt erhalten. Startet einmal je Sitzung
        den KI-Abgleich unsicherer Schreibweisen."""
        aktiv = self.suche_aktiv()
        self.hinweis.setVisible(not aktiv)
        self.inhalt.setVisible(aktiv)
        if not aktiv:
            self.gruppen = []
            self.liste.clear()
            self.dokumente.clear()
            return
        try:
            eintraege = self.db.list_korrespondenten()
        except Exception:  # noqa: BLE001
            eintraege = []
        self._eintrag_namen = {str(e.get("name") or "") for e in eintraege}
        self.gruppen = kr.gruppieren(self.index.werte_mit_anzahl("korrespondent"), eintraege)
        vorher = self._aktuelle.name if self._aktuelle else None
        owner = self._owner()
        self.liste.blockSignals(True)
        try:
            self.liste.clear()
            for i, g in enumerate(self.gruppen):
                item = QListWidgetItem(f"{g.name}  ({g.anzahl})")
                item.setData(Qt.ItemDataRole.UserRole, i)
                tipp = [g.name]
                if len(g.schreibweisen) > 1 or g.schreibweisen[:1] != [g.name]:
                    tipp.append("Schreibweisen: " + ", ".join(g.schreibweisen))
                grund = kr.auffaelligkeit(g.name, owner)
                if grund:
                    item.setForeground(QColor("#9e9e9e"))
                    tipp.append(f"Auffällig ({kr.GRUND_TEXT[grund]}) – „Aufräumen…“ bewertet diese "
                                "Dokumente neu.")
                item.setToolTip("\n".join(tipp))
                self.liste.addItem(item)
        finally:
            self.liste.blockSignals(False)
        self._filter_anwenden(self.filter_edit.text())
        if not self.gruppen:
            self._meldung("Noch keine Korrespondenten im Suchindex. Sie entstehen beim Sortieren und mit "
                          "„Metadaten speichern“.")
        elif not self._aufraeumen_thread:
            self._meldung(f"{len(self.gruppen)} Korrespondenten")
        if vorher:
            self.waehlen(vorher, neu_laden=False)
        else:
            self._dokumente_zeigen(None)
        if abgleich:
            self._ki_abgleich_starten()

    def _filter_anwenden(self, text: str) -> None:
        for row in range(self.liste.count()):
            item = self.liste.item(row)
            g = self.gruppen[item.data(Qt.ItemDataRole.UserRole)]
            item.setHidden(not kr.filter_passt(g, text))

    def _gruppe_von(self, item: QListWidgetItem | None) -> kr.Gruppe | None:
        if item is None:
            return None
        i = item.data(Qt.ItemDataRole.UserRole)
        return self.gruppen[i] if isinstance(i, int) and 0 <= i < len(self.gruppen) else None

    def _gruppe_gewaehlt(self, item: QListWidgetItem | None) -> None:
        self._dokumente_zeigen(self._gruppe_von(item))

    def waehlen(self, name: str, neu_laden: bool = True) -> bool:
        """Korrespondenten auswaehlen und seine Dokumente zeigen (Rechtsklick im Detailbereich).

        Liefert False, wenn es ihn im Index nicht gibt.
        """
        if neu_laden:
            self.refresh(abgleich=False)
        try:
            ziel = kr.kanonisch(name, self.db.list_korrespondenten())
        except Exception:  # noqa: BLE001
            ziel = name
        for row in range(self.liste.count()):
            item = self.liste.item(row)
            g = self._gruppe_von(item)
            if g is not None and (kr.passt_zu(g, name) or kr.passt_zu(g, ziel)):
                if item.isHidden():
                    self.filter_edit.clear()
                if self.liste.currentItem() is item:
                    self._dokumente_zeigen(g)
                else:
                    self.liste.setCurrentItem(item)  # zeigt die Dokumente (currentItemChanged)
                self.liste.scrollToItem(item)
                return True
        self.liste.setCurrentItem(None)
        self._dokumente_zeigen(None)
        if neu_laden:
            self._meldung(f"Keine Dokumente von „{name}“ im Suchindex.")
        return False

    # ------------------------------------------------------------------ Dokumente

    def _dokumente_zeigen(self, gruppe: kr.Gruppe | None) -> None:
        self._aktuelle = gruppe
        self.dokumente.blockSignals(True)  # Neuaufbau ist keine Auswahl des Nutzers
        try:
            self._dokumente_fuellen(gruppe)
        finally:
            self.dokumente.blockSignals(False)
        self.dokumente_gewaehlt.emit([])  # die Markierung ist mit der Liste verschwunden

    def _dokumente_fuellen(self, gruppe: kr.Gruppe | None) -> None:
        self.dokumente.clear()
        if gruppe is None:
            self.dokumente_label.setText("Korrespondent anklicken, um seine Dokumente zu sehen.")
            return
        try:
            doks = self.index.dokumente_mit_werten("korrespondent", gruppe.schreibweisen)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Dokumente nicht geladen: {e}")
            doks = []
        wurzeln = [str(w) for w in self._wurzeln() or []]
        for d in doks:
            item = QTreeWidgetItem([
                _datum(d), str(d.get("name") or ""),
                kr.relativer_ordner(str(d.get("ordner") or ""), wurzeln), str(d.get("kategorie") or ""),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, d)
            item.setToolTip(1, str(d.get("pfad") or ""))
            self.dokumente.addTopLevelItem(item)
        for spalte in range(self.dokumente.columnCount()):
            self.dokumente.resizeColumnToContents(spalte)
        self.dokumente_label.setText(f"Dokumente von „{gruppe.name}“ ({len(doks)})")

    def angezeigte_dokumente(self) -> list[dict]:
        return [self.dokumente.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                for i in range(self.dokumente.topLevelItemCount())]

    @staticmethod
    def _dok(item) -> dict | None:
        d = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        return d if isinstance(d, dict) else None

    def markierte_dokumente(self) -> list[dict]:
        """Die markierten Dokumente in Listenreihenfolge."""
        return [d for d in (self._dok(self.dokumente.topLevelItem(i))
                            for i in range(self.dokumente.topLevelItemCount())
                            if self.dokumente.topLevelItem(i).isSelected()) if d is not None]

    def auswahl_aufheben(self) -> None:
        """Markierung aufheben, ohne ``dokumente_gewaehlt`` zu senden (das Hauptfenster hat sie schon verworfen)."""
        self.dokumente.blockSignals(True)
        try:
            self.dokumente.clearSelection()
        finally:
            self.dokumente.blockSignals(False)

    def _auswahl_geaendert(self) -> None:
        self.dokumente_gewaehlt.emit(self.markierte_dokumente())

    def pfade_aktualisieren(self, paare) -> None:
        """Verschobene bzw. umbenannte Dateien (alt, neu) in der Liste nachziehen, ohne den Index abzuwarten.

        Der Suchindex erfaehrt von Verschieben und Umbenennen ueber eine Warteschlange; bis dahin
        zeigt die Liste sonst noch den alten Ablageort.
        """
        neu_von = {Path(alt): Path(neu) for alt, neu in paare}
        if not neu_von:
            return
        wurzeln = [str(w) for w in self._wurzeln() or []]
        for i in range(self.dokumente.topLevelItemCount()):
            item = self.dokumente.topLevelItem(i)
            d = self._dok(item)
            if d is None or dokument_pfad(d) not in neu_von:
                continue
            neu = neu_von[dokument_pfad(d)]
            d = {**d, "pfad": str(neu), "datei": str(neu), "name": neu.name, "ordner": str(neu.parent)}
            item.setData(0, Qt.ItemDataRole.UserRole, d)
            item.setText(1, neu.name)
            item.setText(2, kr.relativer_ordner(str(neu.parent), wurzeln))
            item.setToolTip(1, str(neu))

    def _dokument_doppelklick(self, item) -> None:
        d = self._dok(item)
        if d is None:
            return
        pfad = dokument_pfad(d)
        if not pfad.exists():
            self._meldung(f"Die Datei gibt es nicht mehr: {pfad}")
            return
        self.dokument_oeffnen.emit(pfad)

    def dokument_menue(self, d: dict) -> QMenu:
        """Kontextmenue eines Dokuments (ohne exec, auch fuer Tests)."""
        from src.gui.pfad_aktionen import im_dateimanager_zeigen, zeigen_text

        menue = QMenu(self)
        pfad = dokument_pfad(d)
        ordner = Path(d.get("ordner") or pfad.parent)
        zeigen = menue.addAction(zeigen_text())
        zeigen.setEnabled(pfad.exists())
        zeigen.triggered.connect(lambda: im_dateimanager_zeigen(pfad))
        links = menue.addAction("Ordner links öffnen")
        links.setEnabled(ordner.is_dir())
        links.triggered.connect(lambda: self.ordner_oeffnen.emit(ordner))
        return menue

    def _dokument_menue_zeigen(self, pos: QPoint) -> None:
        d = self._dok(self.dokumente.itemAt(pos))
        if d is None:
            return
        menue = self.dokument_menue(d)
        menue.exec(self.dokumente.viewport().mapToGlobal(pos))
        menue.deleteLater()

    # ------------------------------------------------------------------ KI-Abgleich (unsichere Faelle)

    def _abgleich_datei(self) -> Path:
        return Path(self.db.db_path).parent / "korrespondenten_abgleich.json"

    def _ki_abgleich_starten(self) -> None:
        """Einmal je Sitzung: unsichere Paare von der KI pruefen lassen (ohne Rueckfrage)."""
        if self._ki_versucht or self._ki_thread is not None:
            return
        provider = self._provider()
        if provider is None:
            return
        self._ki_versucht = True
        paare = kr.kandidaten_paare(self.gruppen, kr.geprueft_laden(self._abgleich_datei()))
        if not paare:
            return
        thread = _KiAbgleich(provider, paare, self)
        thread.fertig.connect(lambda ergebnis, fehler: self._ki_abgleich_fertig(paare, ergebnis, fehler))
        thread.finished.connect(thread.deleteLater)
        self._ki_thread = thread
        thread.start()

    def _ki_abgleich_fertig(self, paare: list, ergebnis: list, fehler: str) -> None:
        self._ki_thread = None
        if fehler or not ergebnis:
            if fehler:
                logger.info(f"KI-Abgleich der Korrespondenten nicht moeglich: {fehler}")
            self.abgleich_fertig.emit(0)
            return
        nach_name = {g.name: g for g in self.gruppen}
        geprueft = kr.geprueft_laden(self._abgleich_datei())
        zusammen = 0
        for a, b, gleich in ergebnis:
            geprueft.add(kr.paar_schluessel(a, b))
            if not gleich:
                continue
            ga, gb = nach_name.get(a), nach_name.get(b)
            if ga is None or gb is None:
                continue
            kanon, alias = self._kanonisch_von(ga, gb)
            try:
                self.db.korrespondent_alias_setzen(kanon.name, alias.name)
                zusammen += 1
            except Exception as e:  # noqa: BLE001
                logger.info(f"Alias {alias.name} -> {kanon.name} nicht gespeichert: {e}")
        kr.geprueft_speichern(self._abgleich_datei(), geprueft)
        if zusammen:
            self.refresh(abgleich=False)
        self.abgleich_fertig.emit(zusammen)

    def _kanonisch_von(self, a: kr.Gruppe, b: kr.Gruppe) -> tuple[kr.Gruppe, kr.Gruppe]:
        """(kanonisch, alias): die vom Nutzer uebernommene Schreibweise, sonst die haeufigere."""
        a_nutzer, b_nutzer = a.name in self._eintrag_namen, b.name in self._eintrag_namen
        if a_nutzer != b_nutzer:
            return (a, b) if a_nutzer else (b, a)
        return (a, b) if a.anzahl >= b.anzahl else (b, a)

    # ------------------------------------------------------------------ Aufraeumen

    def aufraeumen(self) -> None:
        """Auffaellige Dokumente zaehlen, bei Cloud-Anbietern nachfragen und im Hintergrund neu bewerten."""
        if self._aufraeumen_thread is not None or not self.suche_aktiv():
            return
        wurzeln = [str(w) for w in self._wurzeln() or []]
        if not wurzeln:
            self._meldung("Aufgeräumt wird in den Zielordnern – es ist noch keiner eingerichtet.")
            return
        owner = self._owner()
        doks = kr.auffaellige_dokumente(self.index.metadaten_liste("pdf"), wurzeln, owner)
        if not doks:
            self._meldung("Nichts aufzuräumen: Kein Dokument in den Zielordnern ist ohne Korrespondent, "
                          "trägt Ihren Namen oder einen Formularverlag.")
            return
        gruende = Counter(d["grund"] for d in doks)
        teile = ", ".join(f"{n} {kr.GRUND_TEXT[g]}" for g, n in gruende.most_common())
        if self._provider() is None:
            self._meldung(f"{len(doks)} Dokumente wären neu zu bewerten ({teile}) – dafür braucht es "
                          "einen KI-Anbieter (Einstellungen > KI-Assistent).")
            return
        from src.ml.llm_provider import is_cloud_provider

        anbieter = str((self.config.get("llm", {}) or {}).get("provider", ""))
        if is_cloud_provider(anbieter):
            try:
                name = self.hybrid.get_llm_provider_name() or anbieter
            except Exception:  # noqa: BLE001
                name = anbieter
            antwort = QMessageBox.question(
                self, "Korrespondenten aufräumen",
                f"{len(doks)} Dokumente werden neu bewertet ({teile}).\n\n"
                f"Dabei geht der Text jedes Dokuments an {name}. Das ist ein KI-Aufruf je Dokument "
                "und kann je nach Tarif Kosten verursachen.\n\nJetzt starten?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if antwort != QMessageBox.StandardButton.Yes:
                return
        try:
            eintraege = self.db.list_korrespondenten()
        except Exception:  # noqa: BLE001
            eintraege = []
        thread = _Aufraeumen(self.hybrid, self.index, doks, eintraege, owner, self)
        thread.fortschritt.connect(self._aufraeumen_fortschritt)
        thread.geaendert.connect(self._aufraeumen_geaendert)
        thread.fertig.connect(self._aufraeumen_ende)
        thread.finished.connect(thread.deleteLater)
        self._aufraeumen_thread = thread
        self.aufraeumen_button.setEnabled(False)
        self.abbrechen_button.setEnabled(True)
        self.fortschritt_bar.setRange(0, len(doks))
        self.fortschritt_bar.setValue(0)
        self.fortschritt_box.show()
        self.fortschritt_label.setText(f"{len(doks)} Dokumente: {teile}")
        self.fortschritt_label.show()
        self._meldung("Korrespondenten werden aufgeräumt …")
        thread.start()

    def abbrechen(self) -> None:
        """Aufraeumen nach dem laufenden Dokument beenden."""
        if self._aufraeumen_thread is not None:
            self._aufraeumen_thread.requestInterruption()
            self.abbrechen_button.setEnabled(False)
            self._meldung("Wird nach dem laufenden Dokument abgebrochen …")

    def _aufraeumen_fortschritt(self, erledigt: int, gesamt: int, name: str) -> None:
        self.fortschritt_bar.setRange(0, gesamt)
        self.fortschritt_bar.setValue(erledigt)
        if name:
            self.fortschritt_label.setText(f"Bewerte {name} …")

    def _aufraeumen_geaendert(self, d: dict, neu: str, geschrieben: bool) -> None:
        """Wie "Metadaten speichern": Datei neu lesen lassen, Korrespondent mit Vorrang in den Suchindex."""
        pfad = str(d.get("datei") or d.get("pfad") or "")
        try:
            if geschrieben:
                from src.search.meldungen import melden

                melden("datei_geaendert", pfad)
            self.db.set_document_metadata(pfad, {"korrespondent": neu}, sofort=False)
        except Exception as e:  # noqa: BLE001 - der Index ist Zusatz, nie Blocker
            logger.info(f"Suchindex: Korrespondent fuer {pfad} nicht gemeldet: {e}")

    def _aufraeumen_ende(self, stand: dict) -> None:
        self._aufraeumen_thread = None
        self.aufraeumen_button.setEnabled(True)
        self.fortschritt_box.hide()
        self.fortschritt_label.hide()
        text = (f"Aufräumen {'abgebrochen' if stand.get('abgebrochen') else 'fertig'}: "
                f"{stand.get('geaendert', 0)} geändert, {stand.get('unveraendert', 0)} unverändert")
        if stand.get("fehler"):
            text += f", {stand['fehler']} ohne KI-Antwort"
        self.refresh(abgleich=False)
        self._meldung(text + ".")
        self.aufraeumen_fertig.emit(stand)

    # ------------------------------------------------------------------ Beenden

    def shutdown(self, timeout_ms: int = 3000) -> None:
        """Hintergrundlaeufe beenden (beim Schliessen des Fensters)."""
        for t in (self._aufraeumen_thread, self._ki_thread):
            if t is not None and not sip.isdeleted(t):
                t.requestInterruption()
                t.wait(timeout_ms)

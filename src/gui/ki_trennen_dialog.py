"""KI-unterstütztes Trennen eines Scan-Stapels (Kontextmenü einer PDF-Kachel).

Die KI schlägt vor, welche Seiten zu welchem Dokument gehören und wie die
Dokumente heißen (``src.core.ki_trennen``); der Dialog zeigt den Vorschlag zum
Anpassen, erst danach wird getrennt. ``KiTrennenMixin`` hängt das ans Hauptfenster.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QEventLoop, QSize, Qt, QTimer
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.core import ki_trennen
from src.core.ki_trennen import Teil

logger = logging.getLogger(__name__)

BILD_HOEHE = 96
SPALTE_SEITEN, SPALTE_NAME = 0, 1


class KiTrennenDialog(QDialog):
    """Vorschau der erkannten Dokumente; Seiten und Namen sind änderbar."""

    def __init__(self, pdf_path: Path, seitenzahl: int, teile: list[Teil],
                 texte: Optional[list[str]] = None, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.seitenzahl = seitenzahl
        self._texte = texte or []
        self._ergebnis: list[Teil] = []
        self._bilder: dict[int, QIcon] = {}
        self._doc = None
        try:
            import fitz

            self._doc = fitz.open(str(pdf_path))
        except Exception:  # noqa: BLE001 - dann ohne Seitenbilder
            self._doc = None

        self.setWindowTitle("KI-unterstütztes Trennen")
        self.setModal(True)
        self.resize(760, 560)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        if len(teile) > 1:
            kopf = (f"<b>{pdf_path.name}</b> ({seitenzahl} Seiten)<br>"
                    f"Die KI hat {len(teile)} Dokumente erkannt. Jede Zeile wird ein eigenes PDF; "
                    "Seiten und Namen lassen sich ändern.")
        else:
            kopf = (f"<b>{pdf_path.name}</b> ({seitenzahl} Seiten)<br>"
                    "Die KI hält das für ein einziges Dokument. Mit „Dokument aufteilen …“ kannst du "
                    "es selbst zerlegen; jede Zeile wird ein eigenes PDF.")
        info = QLabel(kopf)
        info.setWordWrap(True)
        layout.addWidget(info)

        self.tabelle = QTableWidget(0, 2, self)
        self.tabelle.setHorizontalHeaderLabels(["Seiten", "Dateiname (ohne .pdf)"])
        self.tabelle.setIconSize(QSize(int(BILD_HOEHE * 0.72), BILD_HOEHE))
        self.tabelle.verticalHeader().setDefaultSectionSize(BILD_HOEHE + 10)
        self.tabelle.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabelle.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        kopfzeile = self.tabelle.horizontalHeader()
        kopfzeile.setSectionResizeMode(SPALTE_SEITEN, QHeaderView.ResizeMode.Interactive)
        kopfzeile.setSectionResizeMode(SPALTE_NAME, QHeaderView.ResizeMode.Stretch)
        self.tabelle.setColumnWidth(SPALTE_SEITEN, 190)
        layout.addWidget(self.tabelle, 1)

        for teil in teile:
            self._zeile_anfuegen(ki_trennen.seiten_als_text(teil.seiten), teil.name)
        self.tabelle.itemChanged.connect(self._geaendert)

        zeile = QHBoxLayout()
        self.teilen = QPushButton("Dokument aufteilen …")
        self.teilen.setToolTip("Im markierten Dokument stecken zwei Schriftstücke?\n"
                               "Hier angeben, auf welcher Seite das zweite beginnt.")
        self.teilen.clicked.connect(self._aufteilen)
        zeile.addWidget(self.teilen)
        self.zusammen = QPushButton("Mit dem Dokument davor zusammenlegen")
        self.zusammen.setToolTip("Das markierte Dokument ist gar kein eigenes Schriftstück?\n"
                                 "Seine Seiten kommen zum Dokument in der Zeile darüber\n"
                                 "(beim ersten Dokument: in der Zeile darunter).")
        self.zusammen.clicked.connect(self._entfernen)
        zeile.addWidget(self.zusammen)
        zeile.addStretch()
        layout.addLayout(zeile)
        self.tabelle.itemSelectionChanged.connect(self._knoepfe_stellen)

        self.stand = QLabel()
        self.stand.setWordWrap(True)
        layout.addWidget(self.stand)

        hinweis = QLabel("Seiten als Bereich (1-3) oder kommagetrennt (1-3, 7). "
                         f"Die neuen PDFs entstehen in: {pdf_path.parent}")
        hinweis.setWordWrap(True)
        hinweis.setEnabled(False)
        layout.addWidget(hinweis)

        knoepfe = QHBoxLayout()
        knoepfe.addStretch()
        abbrechen = QPushButton("Abbrechen")
        abbrechen.clicked.connect(self.reject)
        knoepfe.addWidget(abbrechen)
        self.ok = QPushButton("Trennen")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self._annehmen)
        knoepfe.addWidget(self.ok)
        layout.addLayout(knoepfe)

        self._stand_zeigen()
        self._knoepfe_stellen()

    # --- Tabelle --------------------------------------------------------------------

    def _zeile_anfuegen(self, seiten: str, name: str, nach: Optional[int] = None) -> int:
        zeile = self.tabelle.rowCount() if nach is None else nach + 1
        self.tabelle.blockSignals(True)
        try:
            self.tabelle.insertRow(zeile)
            self.tabelle.setItem(zeile, SPALTE_SEITEN, QTableWidgetItem(seiten))
            self.tabelle.setItem(zeile, SPALTE_NAME, QTableWidgetItem(name))
            self._zeile_schmuecken(zeile)
        finally:
            self.tabelle.blockSignals(False)
        return zeile

    def _seiten_der_zeile(self, zeile: int) -> list[int]:
        item = self.tabelle.item(zeile, SPALTE_SEITEN)
        return ki_trennen.seiten_parsen(item.text() if item else "", self.seitenzahl)

    def _zeile_schmuecken(self, zeile: int) -> None:
        """Bild der ersten Seite und Textanfang als Tooltip (Signale sind beim Aufrufer gesperrt)."""
        item = self.tabelle.item(zeile, SPALTE_SEITEN)
        if item is None:
            return
        try:
            erste = self._seiten_der_zeile(zeile)[0]
        except ValueError:
            item.setIcon(QIcon())
            item.setToolTip("")
            return
        item.setIcon(self._seitenbild(erste))
        anfang = " ".join((self._texte[erste - 1] if erste <= len(self._texte) else "").split())[:400]
        tipp = f"Seite {erste}: {anfang}" if anfang else f"Seite {erste} (kein Text)"
        item.setToolTip(tipp)
        name = self.tabelle.item(zeile, SPALTE_NAME)
        if name is not None:
            name.setToolTip(tipp)

    def _seitenbild(self, seite: int) -> QIcon:
        if seite in self._bilder:
            return self._bilder[seite]
        icon = QIcon()
        if self._doc is not None:
            try:
                import fitz

                page = self._doc[seite - 1]
                faktor = (BILD_HOEHE * 2) / max(page.rect.height, 1)
                pix = page.get_pixmap(matrix=fitz.Matrix(faktor, faktor), alpha=False)
                bild = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
                icon = QIcon(QPixmap.fromImage(bild.copy()))
            except Exception:  # noqa: BLE001 - Bild ist nur Beiwerk
                icon = QIcon()
        self._bilder[seite] = icon
        return icon

    def _geaendert(self, item: QTableWidgetItem) -> None:
        if item.column() == SPALTE_SEITEN:
            self.tabelle.blockSignals(True)
            try:
                self._zeile_schmuecken(item.row())
            finally:
                self.tabelle.blockSignals(False)
        self._stand_zeigen()
        self._knoepfe_stellen()

    def _knoepfe_stellen(self) -> None:
        """Knoepfe nur anbieten, wenn sie beim markierten Dokument etwas tun koennen."""
        zeile = self.tabelle.currentRow() if self.tabelle.selectedItems() else -1
        mehrseitig = False
        if zeile >= 0:
            try:
                mehrseitig = len(self._seiten_der_zeile(zeile)) > 1
            except ValueError:
                mehrseitig = False
        self.teilen.setEnabled(mehrseitig)
        self.zusammen.setEnabled(zeile >= 0 and self.tabelle.rowCount() > 1)
        if zeile == 0:
            self.zusammen.setText("Mit dem Dokument danach zusammenlegen")
        else:
            self.zusammen.setText("Mit dem Dokument davor zusammenlegen")

    def _frage_teilseite(self, seiten: list[int]) -> Optional[int]:
        """Fragt, auf welcher Seite das zweite Schriftstueck beginnt (Tests ersetzen das)."""
        seite, ok = QInputDialog.getInt(
            self, "Dokument aufteilen",
            f"Das Dokument hat die Seiten {ki_trennen.seiten_als_text(seiten)}.\n\n"
            "Auf welcher Seite beginnt das zweite Schriftstück?",
            seiten[1], seiten[1], seiten[-1])
        return seite if ok else None

    def _aufteilen(self) -> None:
        zeile = self.tabelle.currentRow()
        if zeile < 0:
            return
        try:
            seiten = self._seiten_der_zeile(zeile)
        except ValueError:
            return
        if len(seiten) < 2:
            return
        ab = self._frage_teilseite(seiten)
        if ab is None:
            return
        vorn = [s for s in seiten if s < ab]
        hinten = [s for s in seiten if s >= ab]
        if not vorn or not hinten:
            return
        name = self.tabelle.item(zeile, SPALTE_NAME).text().strip() or self.pdf_path.stem
        self.tabelle.blockSignals(True)
        try:
            self.tabelle.item(zeile, SPALTE_SEITEN).setText(ki_trennen.seiten_als_text(vorn))
            self._zeile_schmuecken(zeile)
        finally:
            self.tabelle.blockSignals(False)
        neu = self._zeile_anfuegen(ki_trennen.seiten_als_text(hinten), f"{name}_2", nach=zeile)
        self._stand_zeigen()
        # Der neue Name ist nur ein Platzhalter: gleich zum Ueberschreiben anbieten
        self.tabelle.setCurrentCell(neu, SPALTE_NAME)
        self.tabelle.editItem(self.tabelle.item(neu, SPALTE_NAME))

    def _entfernen(self) -> None:
        zeile = self.tabelle.currentRow()
        if zeile < 0 or self.tabelle.rowCount() <= 1:
            return
        # Seiten der Zeile zum Dokument davor (bzw. danach, wenn es die erste ist)
        ziel = zeile - 1 if zeile > 0 else 1
        try:
            seiten = sorted(set(self._seiten_der_zeile(zeile)) | set(self._seiten_der_zeile(ziel)))
        except ValueError:
            seiten = None
        self.tabelle.blockSignals(True)
        try:
            if seiten is not None:
                self.tabelle.item(ziel, SPALTE_SEITEN).setText(ki_trennen.seiten_als_text(seiten))
                self._zeile_schmuecken(ziel)
            self.tabelle.removeRow(zeile)
        finally:
            self.tabelle.blockSignals(False)
        self._stand_zeigen()
        self._knoepfe_stellen()

    # --- Prüfen und Ergebnis ----------------------------------------------------------

    def _lesen(self) -> tuple[list[Teil], list[str]]:
        """Zeilen als Teile und die Fehler (leere Liste = alles lesbar)."""
        teile: list[Teil] = []
        fehler: list[str] = []
        for zeile in range(self.tabelle.rowCount()):
            try:
                seiten = self._seiten_der_zeile(zeile)
            except ValueError as e:
                fehler.append(f"Zeile {zeile + 1}: {e}")
                continue
            item = self.tabelle.item(zeile, SPALTE_NAME)
            name = ki_trennen.name_bereinigen(item.text() if item else "")
            if not name:
                fehler.append(f"Zeile {zeile + 1}: Der Dateiname fehlt.")
                continue
            teile.append(Teil(seiten, name))
        return teile, fehler

    def _luecken(self, teile: list[Teil]) -> tuple[list[int], list[int]]:
        """(fehlende Seiten, mehrfach vergebene Seiten)."""
        gezaehlt: dict[int, int] = {}
        for teil in teile:
            for s in teil.seiten:
                gezaehlt[s] = gezaehlt.get(s, 0) + 1
        fehlend = [s for s in range(1, self.seitenzahl + 1) if s not in gezaehlt]
        doppelt = sorted(s for s, n in gezaehlt.items() if n > 1)
        return fehlend, doppelt

    def _stand_zeigen(self) -> None:
        teile, fehler = self._lesen()
        if fehler:
            self.stand.setText("⚠ " + fehler[0])
            return
        fehlend, doppelt = self._luecken(teile)
        meldungen = []
        if fehlend:
            meldungen.append(f"Seite(n) {ki_trennen.seiten_als_text(fehlend)} kommen in keinem Dokument vor")
        if doppelt:
            meldungen.append(f"Seite(n) {ki_trennen.seiten_als_text(doppelt)} sind mehrfach vergeben")
        if meldungen:
            self.stand.setText("⚠ " + "; ".join(meldungen) + ".")
        else:
            self.stand.setText(f"✓ Alle {self.seitenzahl} Seiten sind auf {len(teile)} Dokument(e) verteilt.")

    def _annehmen(self) -> None:
        # Laufende Eingabe in einer Zelle uebernehmen
        self.ok.setFocus()
        teile, fehler = self._lesen()
        if fehler:
            QMessageBox.warning(self, "Eingabe prüfen", "\n".join(fehler))
            return
        fehlend, doppelt = self._luecken(teile)
        if fehlend or doppelt:
            zeilen = []
            if fehlend:
                zeilen.append(f"Seite(n) {ki_trennen.seiten_als_text(fehlend)} kommen in keinem Dokument vor.")
            if doppelt:
                zeilen.append(f"Seite(n) {ki_trennen.seiten_als_text(doppelt)} sind mehrfach vergeben.")
            antwort = QMessageBox.question(
                self, "KI-unterstütztes Trennen", "\n".join(zeilen) + "\n\nTrotzdem so trennen?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if antwort != QMessageBox.StandardButton.Yes:
                return
        self._ergebnis = teile
        self.accept()

    def teile(self) -> list[Teil]:
        return self._ergebnis

    def done(self, code: int) -> None:
        if self._doc is not None:
            try:
                self._doc.close()
            except Exception:  # noqa: BLE001
                pass
            self._doc = None
        super().done(code)


class KiTrennenMixin:
    """Hauptfenster-Teil: Stapel-PDF von der KI in Dokumente zerlegen lassen."""

    def on_pdf_ki_split(self, pdf_path: Path):
        titel = "KI-unterstütztes Trennen"
        if pdf_path.suffix.lower() != ".pdf":
            QMessageBox.information(self, titel, "Das geht nur mit PDF-Dateien.")
            return
        try:
            import fitz

            with fitz.open(str(pdf_path)) as doc:
                seitenzahl = len(doc)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Fehler", f"PDF konnte nicht geöffnet werden:\n{e}")
            return
        if seitenzahl < 2:
            QMessageBox.information(
                self, titel, f"'{pdf_path.name}' hat nur eine Seite und kann nicht getrennt werden.")
            return

        hc = self.hybrid_classifier
        provider = getattr(hc, "llm_provider", None)
        try:
            mit_ki = provider is not None and bool(hc.is_llm_available())
        except Exception:  # noqa: BLE001
            mit_ki = False
        if not mit_ki:
            QMessageBox.information(
                self, titel,
                "Dafür ist eine KI nötig. Bitte in den Einstellungen einen KI-Anbieter einrichten "
                "oder das PDF mit „PDF trennen...“ von Hand trennen.")
            return

        ergebnis: dict = {"stand": "Der Text der Seiten wird gelesen …"}
        stopp = threading.Event()

        def gemeldet(fertig: int, gesamt: int) -> None:
            if gesamt > 1:
                ergebnis["stand"] = (f"Die KI sucht die Dokumentgrenzen in den {seitenzahl} Seiten …\n"
                                     f"Abschnitt {min(fertig + 1, gesamt)} von {gesamt}")
            else:
                ergebnis["stand"] = f"Die KI sucht die Dokumentgrenzen in den {seitenzahl} Seiten …"

        def arbeit():
            try:
                texte = ki_trennen.seiten_texte(pdf_path)
                ergebnis["texte"] = texte
                if not any(t.strip() for t in texte):
                    raise RuntimeError(
                        "In dem PDF wurde kein Text gefunden (auch nicht per Texterkennung). "
                        "Ohne Text kann die KI die Dokumente nicht unterscheiden.")
                ergebnis["teile"] = ki_trennen.vorschlagen(
                    provider, texte, pdf_path.stem, fortschritt=gemeldet, abbruch=stopp.is_set)
            except Exception as ex:  # noqa: BLE001 - als Meldung zeigen
                ergebnis["fehler"] = str(ex) or ex.__class__.__name__

        job = None
        try:
            from src.core.llm_activity import get_llm_activity

            aktivitaet = get_llm_activity()
            job = aktivitaet.begin("ki_trennen", pdf_path.name)
        except Exception:  # noqa: BLE001 - Anzeige ist Beiwerk
            aktivitaet = None

        thread = threading.Thread(target=arbeit, name="ki-trennen", daemon=True)
        thread.start()
        fortschritt = QProgressDialog(ergebnis["stand"], "Abbrechen", 0, 0, self)
        fortschritt.setWindowTitle(titel)
        fortschritt.setWindowModality(Qt.WindowModality.WindowModal)
        fortschritt.setMinimumDuration(0)
        schleife = QEventLoop()
        takt = QTimer()
        takt.setInterval(150)

        def tick():
            if fortschritt.labelText() != ergebnis["stand"]:
                fortschritt.setLabelText(ergebnis["stand"])
            if not thread.is_alive() or fortschritt.wasCanceled():
                schleife.quit()

        takt.timeout.connect(tick)
        fortschritt.canceled.connect(schleife.quit)
        takt.start()
        fortschritt.show()
        if thread.is_alive():
            schleife.exec()
        takt.stop()
        abgebrochen = fortschritt.wasCanceled() and thread.is_alive()
        if abgebrochen:
            stopp.set()  # noch nicht begonnene KI-Aufrufe entfallen
        fortschritt.close()
        fortschritt.deleteLater()
        if aktivitaet is not None and job is not None:
            try:
                aktivitaet.end(job, success="teile" in ergebnis and not abgebrochen)
            except Exception:  # noqa: BLE001
                pass
        if abgebrochen:
            self.statusbar.showMessage("KI-unterstütztes Trennen abgebrochen", 4000)
            return
        if "teile" not in ergebnis:
            QMessageBox.warning(self, titel, ergebnis.get("fehler") or "Die KI hat keine Aufteilung geliefert.")
            return

        dialog = KiTrennenDialog(pdf_path, seitenzahl, ergebnis["teile"], ergebnis.get("texte"), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        teile = dialog.teile()
        try:
            output_files = self.file_manager.split_pdf_teile(
                pdf_path, pdf_path.parent, [(t.seiten, t.name) for t in teile])
            n = len(output_files)
            self.statusbar.showMessage(f"PDF getrennt: {n} Dokument(e) erstellt", 4000)
            if self.original_nach_trennen(pdf_path, output_files):
                self.statusbar.showMessage(
                    f"PDF getrennt: {n} Dokument(e) erstellt, Original im Papierkorb (Strg+Z holt es zurück)",
                    6000)
            self.load_pdfs()
        except Exception as e:  # noqa: BLE001
            logger.exception("KI-Trennen fehlgeschlagen")
            QMessageBox.critical(self, "Fehler", f"PDF trennen fehlgeschlagen:\n{e}")

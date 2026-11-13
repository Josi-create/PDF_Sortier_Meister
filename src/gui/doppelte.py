"""Hinweis auf doppelte Dateien (Issue #245).

Zwei Anlaesse:

- **Im Scan-Bereich** (:class:`DoppelteImOrdner`): Liegt dieselbe Datei zweimal im
  geoeffneten Ordner - etwa ein Foto, das aus dem Messenger zweimal gespeichert
  wurde -, tragen beide Kacheln den Streifen „Doppelt: wie …“, und die
  Statusleiste meldet es einmal. Geprueft wird nach dem Laden des Ordners und
  immer dann, wenn die Ordner-Beobachtung (Issue #232) eine Datei bringt,
  auffrischt oder wegnimmt.
- **Beim Ablegen** (:class:`DoppelteMixin`): Liegt im Zielordner oder unter den
  Dokumenten des Suchindex schon eine Datei mit genau demselben Inhalt, fragt
  das Programm vor dem Verschieben nach: trotzdem ablegen, in den Papierkorb
  oder abbrechen.

Verglichen wird der Inhalt Byte fuer Byte (``src.core.duplikate``). Gelesen und
gerechnet wird nie im Thread der Oberflaeche: Die Arbeit laeuft in einem
Hintergrund-Thread, die Oberflaeche holt nur das Ergebnis ab.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QEventLoop, QObject, Qt, QTimer
from PyQt6.QtWidgets import QMessageBox, QProgressDialog

from src.core import duplikate
from src.core.file_manager import PapierkorbNichtVerfuegbar
from src.i18n import tr

logger = logging.getLogger(__name__)

# In Tests abgeschaltet (tests/conftest.py): Viele Tests legen mehrere Dateien mit
# demselben Inhalt an; sie sollen weder Hinweise noch Rueckfragen ausloesen. Die Tests
# dieses Hinweises stellen den Schalter wieder an.
AUTOMATISCH = True

HOECHSTENS_ZEILEN = 8  # so viele Dateien nennt die Rueckfrage, der Rest als Zahl


class DoppelteImOrdner(QObject):
    """Kennzeichnet inhaltsgleiche Dateien im Scan-Bereich eines Hauptfensters (``fenster``)."""

    VERZOEGERUNG_MS = 800  # mehrere Anstoesse kurz nacheinander ergeben eine Pruefung
    ABHOL_MS = 100         # so oft wird nach dem Ergebnis des Hintergrund-Threads gesehen
    MELDUNG_MS = 10000

    def __init__(self, fenster):
        super().__init__(fenster)
        self.fenster = fenster
        self._gestoppt = False
        self._lauf: Optional[dict] = None      # laufende Pruefung: Ordner, Pfade, Ergebnis
        self._nochmal = False                  # waehrend der Pruefung kam ein neuer Anstoss
        self._markiert: dict[Path, list[Path]] = {}   # Kachel -> die anderen Dateien gleichen Inhalts
        self._gemeldet: set[frozenset] = set()        # schon in der Statusleiste gemeldete Gruppen
        self._ordner: Optional[Path] = None           # ... dieses Ordners
        self._start = QTimer(self)
        self._start.setSingleShot(True)
        self._start.timeout.connect(self.pruefen)
        self._abholen = QTimer(self)
        self._abholen.setInterval(self.ABHOL_MS)
        self._abholen.timeout.connect(self._ergebnis_holen)

    def stoppen(self):
        """Beim Schliessen des Fensters."""
        self._gestoppt = True
        self._start.stop()
        self._abholen.stop()
        self._lauf = None

    def anstossen(self):
        """Demnaechst pruefen (ohne Dateizugriff; darf beliebig oft gerufen werden)."""
        if AUTOMATISCH and not self._gestoppt:
            self._start.start(self.VERZOEGERUNG_MS)

    def neu_geladen(self):
        """Der Scan-Bereich wurde neu aufgebaut: Die Kacheln sind neu und tragen noch keinen Hinweis."""
        self._markiert = {}
        self.anstossen()

    def datei_betroffen(self, pfad: Path):
        """Eine Kachel wurde entfernt oder umbenannt; neu pruefen, wenn sie einen Hinweis trug."""
        if pfad in self._markiert:
            self.anstossen()

    def pruefen(self):
        """Startet die Pruefung im Hintergrund; das Ergebnis kommt ueber :meth:`_ergebnis_holen`."""
        if self._gestoppt:
            return
        if self._lauf is not None:
            self._nochmal = True
            return
        fenster = self.fenster
        lauf = {
            "ordner": fenster.file_manager.scan_folder,
            "pfade": [w.pdf_path for w in fenster.pdf_widgets],
            "ergebnis": None,
        }
        self._lauf = lauf
        threading.Thread(target=self._rechnen, args=(lauf,), name="doppelte-im-ordner", daemon=True).start()
        self._abholen.start()

    @staticmethod
    def _rechnen(lauf: dict):
        """Im Hintergrund-Thread. Kein Qt-Signal: Der Thread darf ein schon geschlossenes
        Fenster ueberleben (grosse Datei, langsames Laufwerk), ohne es anzufassen."""
        try:
            lauf["ergebnis"] = duplikate.gleiche_im_ordner(lauf["pfade"])
        except Exception:  # noqa: BLE001 - ohne Hinweis weiter
            logger.exception("Doppelte Dateien: Pruefung fehlgeschlagen")
            lauf["ergebnis"] = []

    def _ergebnis_holen(self):
        lauf = self._lauf
        if lauf is None:
            self._abholen.stop()
            return
        if lauf["ergebnis"] is None:
            return  # rechnet noch
        self._abholen.stop()
        self._lauf = None
        if not self._gestoppt and lauf["ordner"] == self.fenster.file_manager.scan_folder:
            self.anzeigen(lauf["ergebnis"])
        if self._nochmal:
            self._nochmal = False
            self.anstossen()

    def anzeigen(self, gruppen: list[list[Path]]):
        """Hinweise auf den Kacheln nachfuehren; angefasst werden nur betroffene Kacheln."""
        fenster = self.fenster
        ordner = fenster.file_manager.scan_folder
        if ordner != self._ordner:
            self._ordner = ordner
            self._gemeldet = set()
        neu: dict[Path, list[Path]] = {}
        for gruppe in gruppen:
            for pfad in gruppe:
                neu[pfad] = [p for p in gruppe if p != pfad]
        if not neu and not self._markiert:
            return
        kacheln = {w.pdf_path: w for w in fenster.pdf_widgets}
        for pfad in self._markiert:
            widget = kacheln.get(pfad)
            if widget is not None and pfad not in neu:
                widget.set_kopie_hinweis("")
                fenster._kopie_hinweis_anwenden(widget)  # „kopiert nach …“ (Issue #179) wieder zeigen
        for pfad, andere in neu.items():
            widget = kacheln.get(pfad)
            if widget is None or self._markiert.get(pfad) == andere:
                continue
            text = tr("Doppelt: wie {name}").format(name=andere[0].name)
            if len(andere) > 1:
                text += f" (+{len(andere) - 1})"
            widget.set_kopie_hinweis(
                text,
                tr("Gleicher Inhalt wie:\n{liste}").format(liste="\n".join(p.name for p in andere)),
                tr("Doppelt"),
            )
        self._markiert = {p: a for p, a in neu.items() if p in kacheln}

        frisch = [g for g in gruppen if frozenset(g) not in self._gemeldet]
        self._gemeldet = {frozenset(g) for g in gruppen}
        if not frisch:
            return
        if len(frisch) == 1 and len(frisch[0]) == 2:
            text = tr("Gleicher Inhalt: „{a}“ und „{b}“").format(a=frisch[0][0].name, b=frisch[0][1].name)
        else:
            text = tr("{anzahl} Dateien in diesem Ordner sind doppelt vorhanden (gleicher Inhalt)").format(
                anzahl=sum(len(g) for g in frisch))
        fenster.statusbar.showMessage(text, self.MELDUNG_MS)


class DoppelteMixin:
    """Rueckfrage vor dem Ablegen, wenn es den Inhalt im Ziel oder im Archiv schon gibt (Hauptfenster)."""

    def _doppelte_suchen(self, dateien: list[Path], folder_path: Path) -> dict[Path, list[Path]]:
        """Je Datei die schon vorhandenen Dateien gleichen Inhalts; gerechnet wird im Hintergrund.

        Dauert es laenger (grosse Datei, langsames Laufwerk), erscheint eine
        Fortschrittsanzeige; „Nicht mehr warten“ legt ohne Hinweis ab.
        """
        suchindex = getattr(getattr(self, "db", None), "suchindex", None)
        index = getattr(suchindex, "gleiche_groesse", None)
        ergebnis: dict[Path, list[Path]] = {}

        def zaehlt(gefunden: Path, pfad: Path) -> bool:
            """Kein „liegt schon dort“ sind Dateien, die gerade selbst abgelegt werden (sonst nennte
            von zwei gleichen jede die andere, und beide gingen in den Papierkorb), und Dateien im
            Ordner der Datei selbst - die kennzeichnet schon der Scan-Bereich."""
            return not (duplikate.selbe_datei(gefunden.parent, pfad.parent)
                        or any(duplikate.selbe_datei(gefunden, d) for d in dateien))

        def arbeit():
            im_ziel = duplikate.ordner_nach_groesse(folder_path)  # einmal lesen, auch fuer viele Dateien
            for pfad in dateien:
                try:
                    gleiche = duplikate.gleiche_anderswo(pfad, im_ziel, index)
                except Exception:  # noqa: BLE001 - ohne Hinweis ablegen
                    logger.exception("Doppelte Dateien: Vergleich fehlgeschlagen")
                    continue
                gleiche = [g for g in gleiche if zaehlt(g, pfad)]
                if gleiche:
                    ergebnis[pfad] = gleiche

        thread = threading.Thread(target=arbeit, name="doppelte-vor-ablage", daemon=True)
        thread.start()
        thread.join(0.2)
        if not thread.is_alive():
            return ergebnis
        fortschritt = QProgressDialog(
            tr("Prüfe, ob es die Datei im Ziel oder im Archiv schon gibt …"), tr("Nicht mehr warten"), 0, 0, self)
        fortschritt.setWindowTitle(tr("Doppelte Dateien"))
        fortschritt.setWindowModality(Qt.WindowModality.WindowModal)
        fortschritt.setMinimumDuration(0)
        schleife = QEventLoop()
        takt = QTimer()
        takt.setInterval(100)
        takt.timeout.connect(lambda: (not thread.is_alive() or fortschritt.wasCanceled()) and schleife.quit())
        fortschritt.canceled.connect(schleife.quit)
        takt.start()
        if thread.is_alive():
            schleife.exec()
        takt.stop()
        abgebrochen = thread.is_alive()
        fortschritt.close()
        fortschritt.deleteLater()
        return {} if abgebrochen else dict(ergebnis)

    def _doppelte_vor_ablage(self, dateien: list[Path], folder_path: Path) -> list[Path]:
        """Vor dem Verschieben nach ``folder_path``: die Dateien, die weiter abgelegt werden sollen.

        Leere Liste: nichts ablegen (abgebrochen, oder alles lag schon dort und
        ging in den Papierkorb).
        """
        dateien = [Path(p) for p in dateien]
        if not AUTOMATISCH or not dateien:
            return dateien
        doppelt = self._doppelte_suchen(dateien, Path(folder_path))
        if not doppelt:
            return dateien

        wahl = self._doppelte_rueckfrage(dateien, doppelt)
        if wahl == "ablegen":
            return dateien
        if wahl != "papierkorb":
            return []
        geloescht = self._doppelte_in_papierkorb(doppelt, naechste_waehlen=len(dateien) == 1)
        return [p for p in dateien if p not in doppelt and p not in geloescht]

    def _doppelte_rueckfrage(self, dateien: list[Path], doppelt: dict[Path, list[Path]]) -> str:
        """„ablegen“, „papierkorb“ oder „abbrechen“."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("Datei schon vorhanden"))
        if len(dateien) == 1:
            pfad = dateien[0]
            orte = doppelt[pfad]
            text = tr("„{name}“ gibt es schon: Eine Datei mit genau demselben Inhalt liegt unter\n\n{ort}").format(
                name=pfad.name, ort="\n".join(str(o) for o in orte[:HOECHSTENS_ZEILEN]))
            if len(orte) > HOECHSTENS_ZEILEN:
                text += tr("\n… und an {anzahl} weiteren Orten").format(anzahl=len(orte) - HOECHSTENS_ZEILEN)
            erklaerung = tr("„In den Papierkorb“ legt die Datei, die Sie gerade ablegen wollten, in den "
                            "Papierkorb. Die schon vorhandene Datei bleibt, wo sie ist.")
        else:
            zeilen = [tr("„{name}“ liegt schon unter {ort}").format(name=p.name, ort=orte[0])
                      for p, orte in list(doppelt.items())[:HOECHSTENS_ZEILEN]]
            if len(doppelt) > HOECHSTENS_ZEILEN:
                zeilen.append(tr("… und {anzahl} weitere").format(anzahl=len(doppelt) - HOECHSTENS_ZEILEN))
            text = tr("{anzahl} von {gesamt} Dateien gibt es schon (genau derselbe Inhalt):\n\n{liste}").format(
                anzahl=len(doppelt), gesamt=len(dateien), liste="\n".join(zeilen))
            erklaerung = tr("„In den Papierkorb“ legt diese Dateien in den Papierkorb, statt sie ein zweites Mal "
                            "abzulegen; nur die übrigen werden abgelegt. Die schon vorhandenen Dateien "
                            "bleiben, wo sie sind.")
        box.setText(text)
        box.setInformativeText(erklaerung)
        ablegen = box.addButton(tr("Trotzdem ablegen"), QMessageBox.ButtonRole.AcceptRole)
        papierkorb = box.addButton(tr("In den Papierkorb"), QMessageBox.ButtonRole.DestructiveRole)
        abbrechen = box.addButton(tr("Abbrechen"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(abbrechen)
        box.setEscapeButton(abbrechen)
        box.exec()
        geklickt = box.clickedButton()
        if geklickt is ablegen:
            return "ablegen"
        if geklickt is papierkorb:
            return "papierkorb"
        return "abbrechen"

    def _doppelte_in_papierkorb(self, doppelt: dict[Path, list[Path]], naechste_waehlen: bool) -> list[Path]:
        """Legt die schon vorhandenen Dateien in den Papierkorb (mit Rueckgaengig) und nimmt ihre Kacheln weg.

        ``naechste_waehlen``: wie nach dem Ablegen einer einzelnen Datei die naechste auswaehlen;
        bei einem Stapel regelt das die Stapel-Ablage fuer die uebrigen Dateien.
        """
        geloescht: list[Path] = []
        fehler: list[str] = []
        for pfad, orte in doppelt.items():
            if not any(ort.exists() for ort in orte):
                # inzwischen verschwunden: dann waere die Datei im Papierkorb die einzige
                fehler.append(tr("{name}: die vorhandene Datei ist nicht mehr da").format(name=pfad.name))
                continue
            try:
                papierkorb = self.file_manager.delete_file(pfad)
            except PapierkorbNichtVerfuegbar:
                fehler.append(tr("{name}: Papierkorb nicht verfügbar").format(name=pfad.name))
                continue
            except Exception as ex:  # noqa: BLE001 - die uebrigen trotzdem
                fehler.append(f"{pfad.name}: {ex}")
                continue
            geloescht.append(pfad)
            if papierkorb is not None:
                self._push_undo({
                    "type": "delete",
                    "original": pfad,
                    "papierkorb": papierkorb,
                    "description": tr("Löschen: {name}").format(name=pfad.name),
                })
            if naechste_waehlen:
                self._remove_pdf_widget_and_select_next(pfad)
            else:
                self.remove_pdf_widget(pfad)
        if geloescht:
            if len(geloescht) == 1:
                text = tr("Schon vorhanden, in den Papierkorb gelegt: {name}").format(name=geloescht[0].name)
            else:
                text = tr("{anzahl} schon vorhandene Dateien in den Papierkorb gelegt").format(anzahl=len(geloescht))
            self.statusbar.showMessage(text, 5000)
        if fehler:
            QMessageBox.warning(self, tr("Teilweise fehlgeschlagen"),
                                tr("Nicht in den Papierkorb gelegt (die Dateien bleiben im Ordner):\n{0}").format(
                                    "\n".join(fehler)))
        return geloescht

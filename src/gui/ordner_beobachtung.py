"""Neue Dateien im Scan-Ordner erscheinen von selbst (Issue #232).

Solange das Hauptfenster offen ist, liest ein Hintergrund-Thread alle paar
Sekunden die Dateiliste des links geoeffneten Ordners (``src.core.ordner_beobachter``).
Die Oberflaeche bekommt nur das Ergebnis: Kacheln fuer fertig geschriebene neue
Dateien kommen einzeln dazu, Kacheln verschwundener Dateien gehen einzeln weg.
Die Ansicht wird dafuer nicht neu aufgebaut; Auswahl, Scrollposition und die
uebrigen Kacheln bleiben, wie sie sind.

Im Thread der Oberflaeche wird der Ordner nie gelesen (ein Netzlaufwerk, das
gerade nicht antwortet, haelt sonst das Fenster an). Viele neue Dateien auf
einmal werden in kleinen Portionen angelegt.

Abschaltbar: Einstellungen › Allgemein › „Scan-Ordner beobachten“
(Konfigurationswert ``scan_ordner_beobachten``, Standard an).
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtWidgets import QApplication

from src.core.office_convert import ist_office_datei
from src.core.ordner_beobachter import Abgleich, Aenderung, anzeige_endungen, ordner_lesen
from src.core.pdf_analyzer import thumbnail_vergessen
from src.i18n import tr

logger = logging.getLogger(__name__)

KONFIG_SCHLUESSEL = "scan_ordner_beobachten"

# In Tests abgeschaltet (tests/conftest.py): Dort laeuft kein Takt, die Tests der
# Beobachtung rufen die Schritte selbst auf.
AUTOMATISCH = True


class _Lauf:
    """Beobachtung eines Ordners; mit dem Wechsel des Ordners beginnt ein neuer Lauf."""

    def __init__(self, ordner: Path, abgleich: Abgleich, endungen: tuple[str, ...]):
        self.ordner = ordner
        self.abgleich = abgleich
        self.endungen = endungen
        self.liest = False       # ein Lesevorgang ist unterwegs
        self.naechstes = 0.0     # fruehester Zeitpunkt des naechsten Lesens (time.monotonic)
        # Vom Lese-Thread abgelegt, vom Takt abgeholt: (Aenderung oder None bei Lesefehler, Dauer in s).
        # Kein Qt-Signal aus dem fremden Thread - der Thread darf ein schon geschlossenes Fenster
        # ueberleben (Netzlaufwerk antwortet nicht), ohne es je anzufassen.
        self.ergebnis: Optional[tuple] = None


class OrdnerBeobachtung(QObject):
    """Haelt die Kacheln des Scan-Bereichs eines Hauptfensters (``fenster``) auf dem Stand des Ordners."""

    TAKT_MS = 250                 # so oft wird geprueft, ob etwas zu tun ist (ohne Dateizugriff)
    INTERVALL = 2.0               # Sekunden zwischen zwei Lesevorgaengen
    INTERVALL_WARTEND = 1.0       # ... solange eine Datei noch geschrieben wird
    RUHEZEIT = 2.0                # so lange muss eine neue Datei unveraendert sein
    HOECHSTWARTEZEIT = 30.0       # danach erscheint auch eine unvollstaendige Datei
    KACHELN_JE_PORTION = 8        # viele Dateien auf einmal: so viele Kacheln je Durchlauf der Ereignisschleife
    PORTION_MS = 15               # ... und hoechstens so lange
    BILDER_GLEICHZEITIG = 4       # so viele Kachelbilder duerfen zugleich laden, bevor weitere Kacheln entstehen
    DROSSEL_MS = 20               # Wartezeit, wenn diese Grenze erreicht ist

    def __init__(self, fenster):
        super().__init__(fenster)
        self.fenster = fenster
        self._lauf: Optional[_Lauf] = None
        self._gestoppt = False
        # Noch nicht in die Ansicht uebernommen (Dateinamen, in der Reihenfolge der Meldung)
        self._neu: dict[str, None] = {}
        self._weg: dict[str, None] = {}
        self._geaendert: dict[str, None] = {}
        self._angelegt: list[Path] = []   # in den laufenden Portionen angelegt (fuer Meldung und Analyse)
        self._entfernt: list[Path] = []   # in den laufenden Portionen entfernt
        self._auswahl_einzeln = False     # die ausgewaehlte Datei ist verschwunden
        self._auswahl_mehrfach = False    # eine Datei der Mehrfachauswahl ist verschwunden
        self._ladend: list = []           # Kacheln, deren Bild die Beobachtung gerade laden laesst
        self._liste: dict = {}            # zuletzt gelesene Dateiliste (Name -> Eintrag)

        self._portion_timer = QTimer(self)
        self._portion_timer.setSingleShot(True)
        self._portion_timer.timeout.connect(self._anwenden)
        self._takt = QTimer(self)
        self._takt.setInterval(self.TAKT_MS)
        self._takt.timeout.connect(self.takten)
        if AUTOMATISCH:
            self._takt.start()

    # --- Ablauf -----------------------------------------------------------

    def stoppen(self):
        """Beim Schliessen des Fensters: nichts mehr lesen, nichts mehr anwenden."""
        self._gestoppt = True
        self._takt.stop()
        self._portion_timer.stop()
        self._lauf = None
        self._vormerkungen_leeren()

    def eingeschaltet(self) -> bool:
        return bool(self.fenster.config.get(KONFIG_SCHLUESSEL, True))

    def _vormerkungen_leeren(self):
        self._neu.clear()
        self._weg.clear()
        self._geaendert.clear()
        self._angelegt = []
        self._entfernt = []
        self._auswahl_einzeln = self._auswahl_mehrfach = False
        self._liste = {}

    def lauf_sichern(self) -> Optional[_Lauf]:
        """Der Lauf zum aktuellen Scan-Ordner; None, wenn nicht beobachtet wird."""
        ordner = self.fenster.file_manager.scan_folder
        if self._gestoppt or ordner is None or not self.eingeschaltet():
            if self._lauf is not None:
                self._lauf = None
                self._vormerkungen_leeren()
            return None
        if self._lauf is None or self._lauf.ordner != ordner:
            # Ordner gewechselt: Die Kacheln zeigen schon seinen Inhalt (load_pdfs)
            self._vormerkungen_leeren()
            bekannte = [w.pdf_path.name for w in self.fenster.pdf_widgets]
            abgleich = Abgleich(
                ordner, bekannte, ruhezeit=self.RUHEZEIT, hoechstwartezeit=self.HOECHSTWARTEZEIT
            )
            self._lauf = _Lauf(Path(ordner), abgleich, anzeige_endungen())
        return self._lauf

    def takten(self):
        """Regelmaessig aus dem Takt: Gelesenes abholen, Vorgemerktes anwenden und bei Bedarf
        den Ordner im Hintergrund neu lesen. Der Takt selbst greift nie auf die Platte zu."""
        lauf = self.lauf_sichern()
        if lauf is None:
            return
        if lauf.ergebnis is not None:
            (aenderung, dauer), lauf.ergebnis = lauf.ergebnis, None
            self._uebernehmen(lauf, aenderung, dauer)
        else:
            self._anwenden()
        if lauf.liest or time.monotonic() < lauf.naechstes:
            return
        lauf.liest = True
        threading.Thread(target=self._lesen, args=(lauf,), name="ordner-beobachtung", daemon=True).start()

    @classmethod
    def _lesen(cls, lauf: _Lauf):
        """Im Hintergrund-Thread: Dateiliste lesen, vergleichen, Ergebnis fuer den Takt ablegen."""
        beginn = time.monotonic()
        aenderung = cls.lesen(lauf)
        lauf.ergebnis = (aenderung, time.monotonic() - beginn)

    @staticmethod
    def lesen(lauf: _Lauf) -> Optional[Aenderung]:
        """Ein Lesevorgang (ohne Oberflaeche); None, wenn der Ordner nicht lesbar ist."""
        try:
            liste = ordner_lesen(lauf.ordner, lauf.endungen)
            return lauf.abgleich.schritt(liste, time.monotonic())
        except OSError:
            return None  # Ordner weg oder Laufwerk getrennt: Kacheln bleiben stehen
        except Exception:  # noqa: BLE001 - der Takt soll weiterlaufen
            logger.exception("Ordner-Beobachtung: Lesen fehlgeschlagen")
            return None

    def _uebernehmen(self, lauf: _Lauf, aenderung: Optional[Aenderung], dauer: float):
        """Ergebnis eines Lesevorgangs (im Thread der Oberflaeche)."""
        lauf.liest = False
        wartend = aenderung is not None and aenderung.wartend > 0
        # Ein langsames Laufwerk wird seltener gelesen
        pause = self.INTERVALL_WARTEND if wartend else self.INTERVALL
        lauf.naechstes = time.monotonic() + max(pause, 10 * dauer)
        if self._gestoppt or lauf is not self._lauf or aenderung is None:
            return
        self._liste = aenderung.liste
        self.vormerken(aenderung)
        self._anwenden()

    def vormerken(self, aenderung: Aenderung):
        """Merkt eine Aenderung vor; angewendet wird sie, sobald kein Dialog offen ist."""
        for name in aenderung.weg:
            self._neu.pop(name, None)
            self._geaendert.pop(name, None)
            self._weg[name] = None
        for name in aenderung.neu:
            if name in self._weg:
                # ersetzt, bevor die Kachel entfernt war: sie bleibt und bekommt ein neues Bild
                del self._weg[name]
                self._geaendert[name] = None
            else:
                self._neu[name] = None
        for name in aenderung.geaendert:
            if name not in self._neu:
                self._geaendert[name] = None

    # --- Ansicht nachfuehren ------------------------------------------------

    def _anwenden(self):
        """Uebernimmt Vorgemerktes in die Ansicht, in kleinen Portionen.

        Je Aufruf hoechstens ``PORTION_MS`` Arbeit; der Rest folgt nach dem naechsten
        Durchlauf der Ereignisschleife, damit das Fenster auch bei mehreren hundert
        Dateien auf einmal bedienbar bleibt.
        """
        if not (self._neu or self._weg or self._geaendert or self._angelegt or self._entfernt):
            return
        fenster = self.fenster
        lauf = self._lauf
        if lauf is None or self._gestoppt:
            return
        if lauf.ordner != fenster.file_manager.scan_folder:
            self._vormerkungen_leeren()  # Ordner gewechselt; der naechste Takt beginnt neu
            return
        if self._nutzer_beschaeftigt():
            return  # der Takt versucht es wieder

        ende = time.monotonic() + self.PORTION_MS / 1000.0
        kacheln = {w.pdf_path: w for w in fenster.pdf_widgets}

        # 1) Verschwundene Dateien
        anzahl = 0
        while self._weg and anzahl < self.KACHELN_JE_PORTION and time.monotonic() < ende:
            name = next(iter(self._weg))
            del self._weg[name]
            pfad = lauf.ordner / name
            if kacheln.pop(pfad, None) is None:
                continue  # schon von einer eigenen Aktion (Verschieben, Loeschen) entfernt
            if pfad in fenster.selected_pdfs:
                self._auswahl_mehrfach = True
            elif fenster.selected_pdf == pfad:
                self._auswahl_einzeln = True
            fenster.remove_pdf_widget(pfad)
            self._entfernt.append(pfad)
            anzahl += 1
        if self._weg:
            self._portion_timer.start(0)
            return
        if self._entfernt:
            self._entfernen_abschliessen()
            fenster._doppelte_im_ordner.anstossen()  # Issue #245

        # 2) Geaenderte Dateien (z. B. hat der Scanner Seiten angehaengt): Bild und Analyse neu
        while self._geaendert and time.monotonic() < ende and not self._gedrosselt():
            name = next(iter(self._geaendert))
            del self._geaendert[name]
            self._auffrischen(lauf.ordner / name, kacheln)
            fenster._doppelte_im_ordner.anstossen()  # Issue #245: der Inhalt ist neu
        if self._geaendert:
            self._portion_timer.start(self.DROSSEL_MS if self._gedrosselt() else 0)
            return

        # 3) Neue Dateien
        if self._neu and fenster.pdf_scroll_area.isHidden():
            # Der Ordner war leer („Keine PDFs …“): einmal ganz aufbauen
            neue = [lauf.ordner / n for n in self._neu]
            self._neu.clear()
            fenster.load_pdfs()
            self._melden(neue)
            return
        anzahl = 0
        while (self._neu and anzahl < self.KACHELN_JE_PORTION and time.monotonic() < ende
               and not self._gedrosselt()):
            name = next(iter(self._neu))
            del self._neu[name]
            pfad = lauf.ordner / name
            if pfad in kacheln:
                # Die Kachel gibt es schon (F5 oder eine eigene Aktion war schneller)
                self._auffrischen(pfad, kacheln, nur_ohne_bild=True)
                continue
            kacheln[pfad] = self._kachel_anlegen(pfad)
            self._angelegt.append(pfad)
            anzahl += 1
        if self._neu:
            self._portion_timer.start(self.DROSSEL_MS if self._gedrosselt() else 0)
            return

        if self._angelegt:
            angelegt, self._angelegt = self._angelegt, []
            # Aenderungszeit und Groesse stehen schon in der gelesenen Dateiliste:
            # zum Einsortieren wird die Platte nicht noch einmal gefragt
            staende = {n: (e.mtime_ns / 1e9, e.groesse) for n, e in self._liste.items()}
            fenster._sortiere_kacheln(staende)
            self._zahlen_anzeigen()
            fenster.pdf_cache.pre_cache(angelegt)  # Analyse und KI-Vorschlag wie nach F5
            self._melden(angelegt)
            # Issue #245: Liegt eine der neuen Dateien schon einmal im Ordner?
            fenster._doppelte_im_ordner.anstossen()

    @staticmethod
    def _nutzer_beschaeftigt() -> bool:
        """Solange ein Dialog (Umbenennen, Fortschritt eines Stapels) oder ein Menue offen ist
        oder eine Maustaste gedrueckt wird (Ziehen einer Kachel), bleibt die Ansicht stehen."""
        return (
            QApplication.activeModalWidget() is not None
            or QApplication.activePopupWidget() is not None
            or QApplication.mouseButtons() != Qt.MouseButton.NoButton
        )

    def _gedrosselt(self) -> bool:
        """Laden gerade genug Kachelbilder? Jedes Bild rendert in einem eigenen Thread;
        bei hunderten gleichzeitig kaeme die Oberflaeche sekundenlang nicht mehr zum Zug."""
        ladend = []
        for widget in self._ladend:
            try:
                thread = getattr(widget, "_loader_thread", None)
                if thread is not None and thread.isRunning():
                    ladend.append(widget)
            except RuntimeError:
                continue  # Kachel bzw. Thread inzwischen geloescht
        self._ladend = ladend
        return len(ladend) >= self.BILDER_GLEICHZEITIG

    def _kachel_anlegen(self, pfad: Path):
        """Eine Kachel hinten anfuegen; sortiert wird einmal am Ende."""
        fenster = self.fenster
        thumbnail_vergessen(pfad)  # ein frueherer Scan gleichen Namens darf nicht sein altes Bild zeigen
        index = len(fenster.pdf_widgets)
        if ist_office_datei(pfad):
            fenster._add_office_widgets([pfad], index)
            widget = fenster.pdf_widgets[-1]
        else:
            widget = fenster._erzeuge_pdf_kachel(pfad)
            fenster.pdf_layout.addWidget(widget, index // fenster._grid_cols, index % fenster._grid_cols)
            fenster.pdf_widgets.append(widget)
        self._ladend.append(widget)
        return widget

    def _entfernen_abschliessen(self):
        fenster = self.fenster
        entfernt, self._entfernt = self._entfernt, []
        einzeln, self._auswahl_einzeln = self._auswahl_einzeln, False
        mehrfach, self._auswahl_mehrfach = self._auswahl_mehrfach, False
        if einzeln:
            fenster._clear_selection()  # Details und Vorschlaege der verschwundenen Datei leeren
        elif mehrfach:
            fenster._update_selection_status()
        self._zahlen_anzeigen()
        if len(entfernt) == 1:
            text = tr("Nicht mehr im Ordner: {name}").format(name=entfernt[0].name)
        else:
            text = tr("{anzahl} Dateien sind nicht mehr im Ordner").format(anzahl=len(entfernt))
        fenster.statusbar.showMessage(text, 5000)

    def _auffrischen(self, pfad: Path, kacheln: dict, nur_ohne_bild: bool = False):
        """Bild und Analyse einer vorhandenen Kachel neu (``nur_ohne_bild``: Bild nur, wenn keines da ist)."""
        widget = kacheln.get(pfad)
        if widget is None:
            return
        thread = getattr(widget, "_loader_thread", None)
        laedt = thread is not None and thread.isRunning()
        if not (nur_ohne_bild and (laedt or getattr(widget, "_original_pixmap", None) is not None)):
            thumbnail_vergessen(pfad)
            widget.load_thumbnail()
            self._ladend.append(widget)
        self.fenster.pdf_cache.pre_cache([pfad])

    def _zahlen_anzeigen(self):
        """Dateizahl ueber dem Scan-Bereich und in der Statusleiste (Texte wie in ``load_pdfs``)."""
        fenster = self.fenster
        count = len(fenster.pdf_widgets)
        text = (tr("{anzahl} Datei") if count == 1 else tr("{anzahl} Dateien")).format(anzahl=count)
        ordner = sum(1 for kachel in fenster.folder_tiles if not kachel.is_parent)
        if ordner:
            text += f" · {ordner} Ordner"
        fenster.pdf_folder_count_label.setText(text)
        pdfs = count - len(fenster.office_widgets)
        fenster.pdf_count_label.setText(tr("PDFs: {anzahl}").format(anzahl=pdfs))

    def _melden(self, neue: list[Path]):
        if len(neue) == 1:
            text = tr("Neu im Scan-Ordner: {name}").format(name=neue[0].name)
        else:
            text = tr("{anzahl} neue Dateien im Scan-Ordner").format(anzahl=len(neue))
        self.fenster.statusbar.showMessage(text, 5000)

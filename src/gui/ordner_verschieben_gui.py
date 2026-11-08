"""Ganzen Ordner verschieben oder kopieren: Bedienung im Hauptfenster (Issue #196).

Ablauf: Ein Einfachklick auf eine Ordnerzeile links markiert den Ordner (PDF-Auswahl und
Ordnermarkierung schliessen sich aus). Rechts erscheinen unter "Vorgeschlagene Ziele"
Elternordner fuer ihn (Inhalt und gleichnamige Ordner, automatisch; KI auf Knopfdruck),
der Baum hebt sie hervor. Ein Klick auf einen Vorschlag oder auf einen Ordner im Baum
verschiebt den markierten Ordner dorthin; Strg+Ziehen auf den Baum oder "Hierhin kopieren"
kopiert ihn. Die Logik steckt in ``src/core`` (``ordner_verschieben``, ``ordner_vorschlaege``,
``pfad_umzug``), hier ist nur die Anbindung an Fenster, Rueckgaengig und Lernen.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from PyQt6 import sip
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox, QProgressDialog, QPushButton

from src.core import ordner_verschieben, ordner_vorschlaege, pfad_umzug
from src.core.office_convert import ist_sortierbar
from src.gui.folder_widget import REGENBOGEN_SCHWELLE
from src.gui.hierhin_kopieren import AblageNamen
from src.gui.vorschlag_liste import VorschlagZeile

logger = logging.getLogger("pdf_sortier_meister.ordner")

STANDARD_PLATZHALTER = "Wählen Sie eine PDF aus für Vorschläge"
STANDARD_UEBERSCHRIFT = "Vorgeschlagene Ziele:"

# Laufende Hintergrundjobs: die Python-Referenz muss bis zum Ende erhalten bleiben,
# sonst loescht Qt einen laufenden QThread (Absturz).
_LAUFENDE: set = set()


class OrdnerJob(QThread):
    """Fuehrt ``funktion(fortschritt, abbruch)`` im Hintergrund aus."""

    fortschritt = pyqtSignal(int, int, str)
    fertig = pyqtSignal(object)
    fehler = pyqtSignal(str)

    def __init__(self, funktion: Callable):
        super().__init__()
        self._funktion = funktion
        self._abbruch = False
        _LAUFENDE.add(self)
        self.finished.connect(lambda: _LAUFENDE.discard(self))

    def abbrechen(self):
        self._abbruch = True

    def run(self):
        try:
            ergebnis = self._funktion(self.fortschritt.emit, lambda: self._abbruch)
        except ordner_verschieben.OrdnerFehler as e:
            self.fehler.emit(str(e))
            return
        except Exception as e:  # noqa: BLE001 - Meldung an den Nutzer, nie ein Absturz
            logger.exception("Ordner-Job fehlgeschlagen")
            self.fehler.emit(str(e) or e.__class__.__name__)
            return
        self.fertig.emit(ergebnis)


class OrdnerVorschlagZeile(VorschlagZeile):
    """Vorschlagszeile fuer einen Elternordner: Rechtsklick verschiebt oder kopiert den markierten Ordner."""

    ordner_hierhin = pyqtSignal(Path, bool)  # (Zielordner, kopieren)

    def _build_context_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("📁 Ordner hierhin verschieben").triggered.connect(
            lambda: self.ordner_hierhin.emit(self.folder_path, False)
        )
        menu.addAction("📁 Ordner hierhin kopieren").triggered.connect(
            lambda: self.ordner_hierhin.emit(self.folder_path, True)
        )
        menu.addSeparator()
        from src.gui.pfad_aktionen import PFAD_KOPIEREN_TEXT

        menu.addAction(PFAD_KOPIEREN_TEXT).triggered.connect(self._copy_path)
        return menu

    # PDFs werden hier nicht abgelegt: die Zeile steht fuer den markierten Ordner
    def dragEnterEvent(self, event):
        event.ignore()

    def dragMoveEvent(self, event):
        event.ignore()


class OrdnerVerschiebenMixin:
    """Markieren, Vorschlaege, Verschieben/Kopieren, Rueckgaengig und Lernen fuer ganze Ordner."""

    _markierter_ordner: Optional[Path] = None
    _ordner_generation = 0
    _ordner_vorschlaege: list = []
    _ordner_laeuft = False
    ordner_ki_btn = None  # baut das Hauptfenster mit ``ordner_ki_knopf_bauen``

    # --- Markierung ---------------------------------------------------------

    def ordner_ki_knopf_bauen(self) -> QPushButton:
        btn = QPushButton("🤖 KI fragen")
        btn.setToolTip(
            "Fragt die KI, unter welchen Ordner der markierte Ordner gehört.\n"
            "Gesendet werden der Ordnername, Dateinamen und Ordnernamen der Ablage."
        )
        btn.setStyleSheet("padding: 2px 8px;")
        btn.clicked.connect(self.on_ordner_ki_fragen)
        btn.hide()
        return btn

    def verbinde_ordner_markierung(self, zeile) -> None:
        """Einfachklick markiert, Rechtsklick-Untermenues und Zielauswahl der Ordnerzeile."""
        if zeile.is_parent:
            return
        zeile.clicked.connect(self.on_folder_tile_clicked)
        zeile.markieren_requested.connect(self.on_folder_tile_markieren)
        zeile.ziel_vorschlag_pruefer = self.ordner_ziel_vorschlaege_fuer
        zeile.ordner_ziel_gewaehlt.connect(self.ordner_uebertragen)
        zeile.ordner_ziel_waehlen.connect(self.on_ordner_ziel_waehlen)

    def on_folder_tile_clicked(self, folder_path: Path) -> None:
        """Einfachklick auf eine Ordnerzeile: markieren, nochmal klicken hebt auf."""
        folder_path = Path(folder_path)
        if self._markierter_ordner == folder_path:
            self._ordner_markierung_aufheben()
            self.statusbar.showMessage("Auswahl aufgehoben", 2000)
            return
        self._ordner_markieren(folder_path)

    def on_folder_tile_markieren(self, folder_path: Path) -> None:
        """Rechtsklick: Ordner markieren (damit die Vorschlaege fuers Menue bereit sind)."""
        if self._markierter_ordner != Path(folder_path):
            self._ordner_markieren(Path(folder_path))

    def _ordner_markieren(self, folder_path: Path) -> None:
        # PDF-Auswahl und Ordnermarkierung schliessen sich aus
        if self.selected_pdf or self.selected_pdfs:
            self._clear_selection()
        else:
            self.clear_suggestions()
        self._markierter_ordner = Path(folder_path)
        self._ordner_vorschlaege = []
        self._ordner_markierung_anzeigen()
        self.suggestions_label.setText(f"Vorgeschlagene Ziele für Ordner „{folder_path.name}“:")
        self.no_suggestions_label.setText("Vorschläge für den Ordner werden berechnet …")
        self.no_suggestions_label.show()
        if self.ordner_ki_btn is not None:
            self.ordner_ki_btn.setEnabled(True)
            self.ordner_ki_btn.setText("🤖 KI fragen")
            self.ordner_ki_btn.show()
        self.statusbar.showMessage(
            f"Ordner markiert: {folder_path.name} – Ziel rechts anklicken (Vorschlag oder Baum), "
            "Strg+Ziehen kopiert"
        )
        self._ordner_vorschlaege_starten(Path(folder_path))

    def _ordner_markierung_anzeigen(self) -> None:
        for kachel in getattr(self, "folder_tiles", []):
            kachel.markiert = (
                self._markierter_ordner is not None
                and not kachel.is_parent
                and Path(kachel.folder_path) == self._markierter_ordner
            )

    def _ordner_markierung_aufheben(self) -> None:
        """Hebt die Ordnermarkierung auf und stellt die Vorschlagsanzeige zurueck."""
        if self._markierter_ordner is None:
            return
        self._markierter_ordner = None
        self._ordner_generation += 1  # laufende Berechnungen verwerfen
        self._ordner_vorschlaege = []
        self._ordner_markierung_anzeigen()
        self.suggestions_label.setText(STANDARD_UEBERSCHRIFT)
        self.no_suggestions_label.setText(STANDARD_PLATZHALTER)
        if self.ordner_ki_btn is not None:
            self.ordner_ki_btn.hide()
        self.clear_suggestions()

    def _ordner_markierung_anwenden(self) -> None:
        """Nach dem Neuaufbau der Ordnerzeilen: Markierung behalten, wenn der Ordner noch da ist."""
        if self._markierter_ordner is None:
            return
        if any(
            not k.is_parent and Path(k.folder_path) == self._markierter_ordner
            for k in getattr(self, "folder_tiles", [])
        ):
            self._ordner_markierung_anzeigen()
        else:
            self._ordner_markierung_aufheben()

    # --- Vorschlaege ----------------------------------------------------------

    def _ordner_vorschlaege_starten(self, ordner: Path) -> None:
        """Berechnet die automatischen Vorschlaege (a: Inhalt, b: Namensvetter) im Hintergrund."""
        self._ordner_generation += 1
        gen = self._ordner_generation
        roots = list(self.config.get_target_folders())
        klassifikator, db, cache = self.classifier, self.db, self.pdf_cache

        def arbeit(_fortschritt, _abbruch):
            return ordner_vorschlaege.vorschlaege_fuer_ordner(
                ordner, roots, db=db, cache_get=cache.get,
                suggest_fn=lambda text, kw: klassifikator.suggest(text, kw, max_suggestions=1),
            )

        job = OrdnerJob(arbeit)
        job.fertig.connect(lambda erg, g=gen, o=ordner: self._ordner_vorschlaege_da(g, o, erg))
        job.fehler.connect(lambda msg, g=gen, o=ordner: self._ordner_vorschlaege_da(g, o, []))
        job.start()

    def _ordner_vorschlaege_da(self, gen: int, ordner: Path, vorschlaege: list) -> None:
        if sip.isdeleted(self):  # Fenster wurde waehrend der Berechnung geschlossen
            return
        if gen != self._ordner_generation or self._markierter_ordner != ordner:
            return  # inzwischen anderer Ordner oder aufgehoben
        self._ordner_vorschlaege = list(vorschlaege or [])
        self.display_folder_suggestions(self._ordner_vorschlaege)

    def display_folder_suggestions(self, suggestions: list) -> None:
        """Zeigt die Elternordner-Vorschlaege fuer den markierten Ordner (Issue #196)."""
        self.clear_suggestions()
        name = self._markierter_ordner.name if self._markierter_ordner else ""
        if not suggestions:
            self.no_suggestions_label.setText(
                "Keine Vorschläge für diesen Ordner. Ziel im Baum anklicken oder „KI fragen“."
            )
            self.no_suggestions_label.show()
            return
        self.no_suggestions_label.hide()
        first = True
        for s in suggestions:
            is_new = bool(getattr(s, "new_source", ""))
            zeile = OrdnerVorschlagZeile(s.folder_path)
            zeile.is_suggestion = True
            if is_new:
                zeile.set_neu(True)
            rel = (s.relative_path or s.folder_name).replace("\\", "/")
            eltern, _, kurz = rel.rpartition("/")
            kurz = kurz or s.folder_name
            zeile.set_anzeige(f"➕ neu: {kurz}" if is_new else kurz, eltern)
            tooltip = f"Ordner „{name}“ wird nach {rel}/{name} einsortiert.\n{s.reason}\n"
            tooltip += f"Konfidenz: {int(s.confidence * 100)}%\n"
            tooltip += (
                "Diesen Ordner gibt es noch nicht, er wird nach einer Rückfrage angelegt.\n"
                if is_new else ""
            )
            tooltip += "Anklicken verschiebt den markierten Ordner hierher (Rechtsklick: kopieren)."
            zeile.setToolTip(tooltip)
            zeile.count_label.setText(f"{int(s.confidence * 100)}%")
            farbe = "#1e6fd9" if is_new else "#28a745"
            zeile.count_label.setStyleSheet(
                f"font-size: 11px; color: {farbe}; font-weight: bold; background: transparent; border: none;"
            )
            zeile.clicked.connect(self.on_ordner_vorschlag_clicked)
            zeile.ordner_hierhin.connect(self.on_ordner_vorschlag_hierhin)
            if first and not is_new and s.confidence >= REGENBOGEN_SCHWELLE:
                zeile.set_regenbogen(True)
            first = first and is_new
            self.suggestions_layout.addWidget(zeile)
            self.suggestion_widgets.append(zeile)
        self.folder_tree.set_suggestion_folders([s.folder_path for s in suggestions if not s.new_source])

    def ordner_ziel_vorschlaege_fuer(self, ordner: Path) -> list:
        """Fuers Kontextmenue: [(Text, Zielordner)] der berechneten Vorschlaege (leer, solange sie fehlen)."""
        if self._markierter_ordner != Path(ordner):
            return []
        return [
            (f"{(s.relative_path or s.folder_name)} ({int(s.confidence * 100)} %)", Path(s.folder_path))
            for s in self._ordner_vorschlaege
        ]

    def on_ordner_vorschlag_clicked(self, ziel: Path) -> None:
        if self._markierter_ordner is not None:
            self.ordner_uebertragen(self._markierter_ordner, Path(ziel), False)

    def on_ordner_vorschlag_hierhin(self, ziel: Path, kopieren: bool) -> None:
        if self._markierter_ordner is not None:
            self.ordner_uebertragen(self._markierter_ordner, Path(ziel), kopieren)

    # --- KI auf Knopfdruck (c) --------------------------------------------------

    def on_ordner_ki_fragen(self) -> None:
        ordner = self._markierter_ordner
        if ordner is None:
            return
        hc = self.hybrid_classifier
        provider = getattr(hc, "llm_provider", None)
        if not hc.is_llm_available() or provider is None:
            QMessageBox.information(
                self, "KI nicht eingerichtet",
                "Für „KI fragen“ muss unter Einstellungen ein KI-Anbieter eingerichtet sein.",
            )
            return
        roots = list(self.config.get_target_folders())
        cache = self.pdf_cache
        gen = self._ordner_generation

        def arbeit(_fortschritt, _abbruch):
            return ordner_vorschlaege.ki_zielordner(provider, ordner, roots, cache_get=cache.get)

        if self.ordner_ki_btn is not None:
            self.ordner_ki_btn.setEnabled(False)
            self.ordner_ki_btn.setText("🤖 KI fragt …")
        self.statusbar.showMessage(f"KI überlegt, wohin „{ordner.name}“ gehört …")
        job = OrdnerJob(arbeit)
        job.fertig.connect(lambda s, g=gen, o=ordner: self._ordner_ki_da(g, o, s))
        job.fehler.connect(lambda msg, g=gen, o=ordner: self._ordner_ki_fehler(g, o, msg))
        job.start()

    def _ordner_ki_fertig_knopf(self) -> None:
        if self.ordner_ki_btn is not None:
            self.ordner_ki_btn.setEnabled(True)
            self.ordner_ki_btn.setText("🤖 KI fragen")

    def _ordner_ki_da(self, gen: int, ordner: Path, vorschlag) -> None:
        if sip.isdeleted(self):
            return
        if gen != self._ordner_generation or self._markierter_ordner != ordner:
            return
        self._ordner_ki_fertig_knopf()
        if vorschlag is None:
            self.statusbar.showMessage("Die KI konnte keinen passenden Elternordner nennen", 5000)
            return
        liste = list(self._ordner_vorschlaege)
        for s in liste:
            if Path(s.folder_path) == Path(vorschlag.folder_path):  # bestaetigt einen vorhandenen
                s.confidence = max(s.confidence, 0.9)
                if "KI bestätigt" not in s.reason:
                    s.reason += " + KI bestätigt"
                liste.insert(0, liste.pop(liste.index(s)))
                break
        else:
            liste.insert(0, vorschlag)
        self._ordner_vorschlaege = liste
        self.display_folder_suggestions(liste)
        self.statusbar.showMessage(f"KI-Vorschlag: {vorschlag.relative_path}", 5000)

    def _ordner_ki_fehler(self, gen: int, ordner: Path, meldung: str) -> None:
        if sip.isdeleted(self):
            return
        if gen != self._ordner_generation or self._markierter_ordner != ordner:
            return
        self._ordner_ki_fertig_knopf()
        QMessageBox.warning(self, "KI fragen", f"Die KI-Anfrage ist fehlgeschlagen:\n{meldung}")

    # --- Zielwahl per Dialog und per Ziehen ----------------------------------------

    def on_ordner_ziel_waehlen(self, ordner: Path, kopieren: bool) -> None:
        """Menue "Anderen Ordner wählen …": beliebigen Zielordner im Dateidialog waehlen."""
        ziele = self.config.get_target_folders()
        start = str(ziele[0]) if ziele else str(Path(ordner).parent)
        verb = "kopieren" if kopieren else "verschieben"
        gewaehlt = QFileDialog.getExistingDirectory(self, f"Zielordner zum {verb.capitalize()} wählen", start)
        if gewaehlt:
            self.ordner_uebertragen(Path(ordner), Path(gewaehlt), kopieren)

    def on_tree_ordner_dropped(self, ordner: Path, ziel: Path) -> None:
        # Nach dem Drop: Rueckfragen nicht mitten im Drag-and-Drop-Ereignis
        QTimer.singleShot(0, lambda: self.ordner_uebertragen(Path(ordner), Path(ziel), False))

    def on_tree_ordner_copy_dropped(self, ordner: Path, ziel: Path) -> None:
        QTimer.singleShot(0, lambda: self.ordner_uebertragen(Path(ordner), Path(ziel), True))

    # --- Verschieben und Kopieren ------------------------------------------------------

    def ordner_uebertragen(self, quelle: Path, ziel_eltern: Path, kopieren: bool = False) -> None:
        """Verschiebt bzw. kopiert ``quelle`` nach ``ziel_eltern/<Name>`` (nach Rueckfrage, im Hintergrund)."""
        quelle, ziel_eltern = Path(quelle), Path(ziel_eltern)
        if self._ordner_laeuft:
            self.statusbar.showMessage("Es läuft schon ein Ordner-Vorgang", 3000)
            return
        meldung = ordner_verschieben.pruefe(quelle, ziel_eltern)
        if meldung:
            QMessageBox.warning(self, "Ordner verschieben nicht möglich", meldung)
            return

        verb = "kopieren" if kopieren else "verschieben"
        rel = self.folder_tree.get_relative_path(ziel_eltern)
        dateien, unterordner = ordner_verschieben.inhalt_zaehlen(quelle)
        text = (
            f"Ordner „{quelle.name}“ ({dateien} {'Datei' if dateien == 1 else 'Dateien'}, "
            f"{unterordner} {'Unterordner' if unterordner == 1 else 'Unterordner'}) "
            f"nach „{rel}“ {verb}?"
        )
        if not ziel_eltern.exists():
            text += "\n\nDen Zielordner gibt es noch nicht, er wird angelegt."
        if ordner_verschieben.zusammenfuehren_noetig(quelle, ziel_eltern):
            text += (
                f"\n\n„{quelle.name}“ gibt es dort schon: Die Inhalte werden zusammengeführt. "
                "Gleiche Dateinamen bekommen „ (2)“ angehängt, byte-gleiche Dateien werden nicht doppelt abgelegt"
                + (" (die Quelldatei kommt in den Papierkorb)." if not kopieren else ".")
            )
        antwort = QMessageBox.question(
            self, f"Ordner {verb}", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if antwort != QMessageBox.StandardButton.Yes:
            return

        papierkorb = self.file_manager.delete_file

        def arbeit(fortschritt, abbruch):
            return ordner_verschieben.uebertrage(
                quelle, ziel_eltern, kopieren=kopieren, papierkorb=papierkorb,
                fortschritt=fortschritt, abbruch=abbruch,
            )

        titel = f"Ordner „{quelle.name}“ wird {'kopiert' if kopieren else 'verschoben'} …"
        self._ordner_job_starten(titel, arbeit, lambda erg: self._ordner_fertig(erg, rel))

    def _ordner_job_starten(self, titel: str, arbeit: Callable, fertig: Callable) -> None:
        """Startet den Job mit Fortschrittsdialog (erscheint erst nach einer halben Sekunde)."""
        self._ordner_laeuft = True
        dlg = QProgressDialog(titel, "Abbrechen", 0, 0, self)
        dlg.setWindowTitle("PDF Sortier Meister")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(500)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        job = OrdnerJob(arbeit)

        def fortschritt(i: int, n: int, name: str) -> None:
            dlg.setMaximum(max(n, 1))
            dlg.setValue(min(i, max(n, 1)))
            dlg.setLabelText(f"{titel}\n{name}")

        def beenden() -> None:
            self._ordner_laeuft = False
            try:
                dlg.canceled.disconnect()
            except TypeError:
                pass
            dlg.cancel()
            dlg.deleteLater()

        def ok(ergebnis) -> None:
            if sip.isdeleted(self):
                return
            beenden()
            fertig(ergebnis)

        def fehler(meldung: str) -> None:
            if sip.isdeleted(self):
                return
            beenden()
            QMessageBox.warning(self, "Ordner verschieben", meldung)

        job.fortschritt.connect(fortschritt)
        job.fertig.connect(ok)
        job.fehler.connect(fehler)
        dlg.canceled.connect(job.abbrechen)
        job.start()

    def _ordner_fertig(self, erg, rel: str) -> None:
        """Nach dem Uebertragen (GUI-Thread): Pfade nachziehen, lernen, Rueckgaengig, Ansicht."""
        name = erg.quelle.name
        if erg.fehler:
            QMessageBox.warning(
                self, "Teilweise fehlgeschlagen",
                "Einige Dateien konnten nicht übertragen werden (sie bleiben am alten Platz):\n"
                + "\n".join(erg.fehler[:15]) + ("\n…" if len(erg.fehler) > 15 else ""),
            )
        if not erg.etwas_getan:
            self.statusbar.showMessage("Es wurde nichts übertragen", 4000)
            return

        if not erg.kopiert:
            self._ordner_pfade_umziehen(
                erg.quelle, erg.ziel, [(a, n) for a, n in erg.dateien],
                nur_dateien=erg.quelle.exists(),
            )
            for quelldatei, _vorhanden, _ablage in erg.identisch:
                self.pdf_cache.clear_for_pdf(quelldatei)
        self._ordner_lernen(erg)
        self._invalidate_folder_caches()
        if not erg.kopiert:
            self.classifier._schedule_retrain()  # gelernte Ordnerpfade neu einlesen

        verb = "kopiert" if erg.kopiert else "verschoben"
        self._push_undo({
            "type": "ordner",
            "ergebnis": erg,
            "description": f"Ordner {name} {verb} → {rel}",
        })
        extra = f", {len(erg.identisch)} identische übersprungen" if erg.identisch else ""
        self.statusbar.showMessage(
            f"Ordner „{name}“ nach „{rel}“ {verb} ({len(erg.dateien)} Dateien{extra})", 6000
        )
        self.config.add_to_last_used(erg.ziel.parent)
        if not erg.kopiert:
            self._ordner_markierung_aufheben()
        self._ordner_ansicht_aktualisieren(erg)

    def _ordner_pfade_umziehen(
        self, alt: Path, neu: Path, paare: Optional[list], nur_dateien: bool = False,
        umbenannt: bool = False,
    ) -> dict:
        """Gemeinsamer Helfer fuer Verschieben, Rueckgaengig und Umbenennen: alle gespeicherten Pfade nachziehen.

        ``paare=None`` liest die Dateien aus dem neuen Ordner (Umbenennen, ``umbenannt=True``):
        dann meldet der Helfer sie auch dem Suchindex und laesst den Baum in Ruhe (er hat sich selbst umgeschrieben).
        """
        ergebnis = pfad_umzug.umziehen(
            alt, neu, self.config, self.db, self.pdf_cache, paare=paare, nur_dateien=nur_dateien,
            index_melden_paare=umbenannt,
        )
        for a, n in ergebnis["ziele"]:
            self.folder_manager.remove_folder(a)
            try:
                self.folder_manager.add_folder(n)
            except ValueError:  # Ordner gibt es (noch) nicht: nur die Config behaelt den Eintrag
                pass
        if ergebnis["favoriten"]:
            self.favoriten_leiste.aktualisieren()
        if ergebnis["ziele"] and not umbenannt:
            self.load_folders()
        return ergebnis

    def _ordner_lernen(self, erg) -> None:
        """Jede Datei zaehlt als einzeln einsortiert (gebuendelt; nur Dateien mit gecachtem Text)."""
        gelernt = 0
        for alt, neu in erg.dateien:
            if not ist_sortierbar(neu):
                continue
            ergebnis = self.pdf_cache.get(alt if erg.kopiert else neu)
            text = getattr(ergebnis, "extracted_text", None)
            if not text:
                continue
            namen = AblageNamen(
                new_name=None, name_changed=False, learned_name=None, folder_naming_applied=False,
                metadata={}, office_ext=None, dokument_id=self._dokument_id(Path(alt)),
            )
            ordner = Path(neu).parent
            self._aus_ablage_lernen(
                Path(alt), ordner, self.folder_tree.get_relative_path(ordner), Path(neu), namen,
                text, list(getattr(ergebnis, "keywords", None) or []),
            )
            gelernt += 1
        if gelernt:
            self.training_label.setText(f"Gelernt: {self.classifier.get_training_count()}")

    def _ordner_ansicht_aktualisieren(self, erg, rueckgaengig: bool = False) -> None:
        """Ordnerzeilen und Zielbaum nach einer Aenderung auffrischen."""
        baum = self.folder_tree
        if (
            not baum.has_folder(erg.ziel.parent)
            or baum.has_folder(erg.quelle)
            or (rueckgaengig and baum.has_folder(erg.ziel))
            or not baum.add_folder_incremental(erg.ziel)
        ):
            baum.refresh_tree()
        else:
            baum.refresh_counts({erg.ziel.parent, erg.ziel, erg.quelle.parent})
        self.load_pdfs()

    # --- Rueckgaengig ------------------------------------------------------------------

    def _undo_ordner(self, entry: dict) -> None:
        erg = entry["ergebnis"]
        if erg.kopiert:
            text = f"Die Kopie von „{erg.quelle.name}“ in den Papierkorb legen?"
        else:
            text = f"Ordner „{erg.quelle.name}“ zurück nach „{erg.quelle.parent}“ verschieben?"
        antwort = QMessageBox.question(
            self, "Rückgängig machen", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if antwort != QMessageBox.StandardButton.Yes:
            return
        if self._ordner_laeuft:
            self.statusbar.showMessage("Es läuft schon ein Ordner-Vorgang", 3000)
            return
        self._undo_stack.pop()
        self._update_undo_ui()
        papierkorb = self.file_manager.delete_file

        def arbeit(_fortschritt, _abbruch):
            return ordner_verschieben.rueckgaengig(erg, papierkorb)

        self._ordner_job_starten(
            f"Ordner „{erg.quelle.name}“ wird zurückgeholt …", arbeit,
            lambda probleme: self._undo_ordner_fertig(entry, probleme),
        )

    def _undo_ordner_fertig(self, entry: dict, probleme: list) -> None:
        erg = entry["ergebnis"]
        if probleme:
            QMessageBox.warning(self, "Rückgängig nicht ganz möglich", "\n".join(probleme[:15]))
        if not erg.kopiert:
            zurueck = [(n, a) for a, n in erg.dateien if Path(a).exists()]
            neu_angelegt = any(Path(p) == erg.ziel for p in erg.neue_ordner)
            # In einen schon vorhandenen Zielordner zurueckgeholt: nur die Dateien zaehlen,
            # sonst wuerden Pfade des bisherigen Inhalts mitwandern
            self._ordner_pfade_umziehen(
                erg.ziel, erg.quelle, zurueck,
                nur_dateien=not (neu_angelegt and not probleme),
            )
            self.classifier._schedule_retrain()
        self._invalidate_folder_caches()
        self.statusbar.showMessage(f"Rückgängig: {entry['description']}", 3000)
        self._ordner_ansicht_aktualisieren(erg, rueckgaengig=True)

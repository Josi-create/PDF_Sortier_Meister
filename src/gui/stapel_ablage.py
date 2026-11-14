"""
Stapel-Ablage (Issue #218)

Mehrere markierte Dateien verschieben oder am Platz umbenennen - jede mit dem
Namen und den Metadaten, die ihr das Detail-Panel vorbelegen wuerde. Bisher
galt der Name im Detail-Panel nur fuer die eine angezeigte Datei; die uebrigen
wurden unter ihrem alten Namen verschoben, und "Umbenennen + Metadaten
speichern" benannte nur die angezeigte Datei um.

- :class:`Namensrechner`: ein unsichtbares Detail-Panel ohne Vorschau, das die
  Vorbelegung einer Datei synchron ausrechnet. Es ist dieselbe Klasse wie das
  sichtbare Panel, damit Rangfolge der Vorschlagsarten, Muster, Korrespondent
  und gespeicherte PDF-Metadaten genau gleich wirken.
- Rueckfrage mit der Liste alt -> neu: :mod:`src.gui.stapel_rueckfrage`.
- :class:`StapelAblageMixin`: fehlende Analysen und KI-Vorschlaege abwarten,
  Namen bilden, verschieben bzw. umbenennen, Rueckgaengig.

GPL-3.0-or-later - Copyright (c) 2026
"""

import logging
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QEventLoop, Qt, QTimer
from PyQt6.QtWidgets import QMessageBox, QProgressDialog

from src.core import namen_unterscheiden
from src.core.office_convert import ist_office_datei
from src.core.pdf_cache import PDFAnalysisResult
from src.gui import stapel_rueckfrage
from src.gui.detail_panel import DetailPanel
from src.gui.hierhin_kopieren import AblageNamen
from src.gui.stapel_rueckfrage import UMBENENNEN
from src.i18n import tr

logger = logging.getLogger(__name__)


def erkanntes_datum(dates) -> Optional[str]:
    """Erstes erkanntes Datum als Text (JJJJ-MM-TT bei date-Objekten), sonst None."""
    if not dates:
        return None
    first = dates[0]
    return first.strftime("%Y-%m-%d") if hasattr(first, "strftime") else str(first)


class Namensrechner(DetailPanel):
    """Unsichtbares Detail-Panel: rechnet Name und Metadaten so aus, wie sie das sichtbare vorbelegt.

    Ohne Vorschau; die gespeicherten Metadaten der PDF liest es sofort statt im
    Hintergrund und wendet sie danach so an wie das sichtbare Panel, wenn sein
    Hintergrund-Leser fertig ist.
    """

    def _vorschau_laden(self, pdf_path: Path):
        pass

    def _start_metadata_reader(self, pdf_path: Path):
        pass  # liest berechne() selbst, und zwar sofort

    def berechne(
        self,
        pdf_path: Path,
        suggestions: list,
        extracted_text: str,
        keywords: Optional[list],
        detected_date: Optional[str],
    ) -> tuple[Optional[str], dict]:
        """(Dateiname mit .pdf oder None, Metadaten) fuer ``pdf_path``."""
        self.clear()
        self.set_pdf(
            pdf_path=pdf_path,
            suggestions=suggestions,
            extracted_text=extracted_text or "",
            keywords=keywords,
            detected_date=detected_date,
        )
        try:
            from src.core.pdf_metadata import read_metadata
            meta = read_metadata(pdf_path)
        except Exception:  # noqa: BLE001 - wie der Hintergrund-Leser: ohne Metadaten weiter
            meta = None
        self._on_pdf_metadata_read(pdf_path, meta)
        return self.get_new_name(), self.get_metadata()


@dataclass
class StapelEintrag:
    """Eine Datei des Stapels mit ihrem geplanten Namen und den Analyse-Daten zum Lernen."""

    pfad: Path
    namen: AblageNamen
    text: Optional[str]
    keywords: Optional[list]
    dates: Optional[list]


class StapelAblageMixin:
    """Verschieben und Umbenennen mehrerer Dateien fuer das Hauptfenster (Issue #218)."""

    # --- Vorbereitung: Analysen und KI-Vorschlaege ---------------------------

    def _stapel_vorbereiten(self, dateien: list[Path]) -> None:
        """Zieht fehlende Analysen und KI-Vorschlaege vor und wartet darauf.

        Mit Fortschrittsanzeige; "Nicht mehr warten" faehrt mit dem fort, was
        schon da ist (die Rueckfrage danach zeigt die Namen, Abbrechen geht dort).
        """
        cache = self.pdf_cache
        try:
            mit_ki = bool(self.hybrid_classifier.is_llm_available())
        except Exception:  # noqa: BLE001 - ohne KI geht es mit den uebrigen Vorschlaegen
            mit_ki = False
        analyse_offen: set[Path] = set()
        for pfad in dateien:
            if not pfad.exists():
                continue
            vorhanden = cache.get(pfad)
            if vorhanden is not None and (not mit_ki or vorhanden.llm_fetched):
                continue
            if vorhanden is None:
                analyse_offen.add(pfad)
            cache.vorziehen(pfad, mit_ki, analysiert=lambda _r, p=pfad: analyse_offen.discard(p))

        def offen() -> list[Path]:
            return [p for p in dateien if p in analyse_offen or (mit_ki and cache.ki_offen(p))]

        if not offen():
            return
        gesamt = len(dateien)
        fortschritt = QProgressDialog("", tr("Nicht mehr warten"), 0, gesamt, self)
        fortschritt.setWindowTitle(tr("Namensvorschläge"))
        fortschritt.setWindowModality(Qt.WindowModality.WindowModal)
        fortschritt.setMinimumDuration(0)
        fortschritt.setAutoClose(False)
        fortschritt.setAutoReset(False)
        schleife = QEventLoop()
        takt = QTimer()
        takt.setInterval(150)

        def pruefen():
            rest = offen()
            fortschritt.setValue(gesamt - len(rest))
            was = tr("Namensvorschläge der KI") if mit_ki else tr("Texterkennung")
            fortschritt.setLabelText(
                tr("Warte auf {was} …\n{fertig} von {gesamt} Dateien fertig").format(
                    was=was, fertig=gesamt - len(rest), gesamt=gesamt)
                + (tr("\n\nGerade: {name}").format(name=rest[0].name) if rest else "")
            )
            if not rest or fortschritt.wasCanceled():
                schleife.quit()

        takt.timeout.connect(pruefen)
        fortschritt.canceled.connect(schleife.quit)
        pruefen()
        takt.start()
        schleife.exec()
        takt.stop()
        fortschritt.close()
        fortschritt.deleteLater()

    # --- Namen bilden ---------------------------------------------------------

    def _stapel_rechner(self) -> Namensrechner:
        rechner = getattr(self, "_namensrechner", None)
        if rechner is None:
            rechner = Namensrechner(self)
            rechner.hide()  # ausdruecklich verborgen: erscheint nie mit dem Hauptfenster
            self._namensrechner = rechner
        return rechner

    def _stapel_eintraege(self, dateien: list[Path], folder_path: Optional[Path],
                          relative_path: str) -> list[StapelEintrag]:
        """Geplanter Name und Metadaten je Datei; fuer die angezeigte gilt das Detail-Panel."""
        eintraege: list[StapelEintrag] = []
        for pfad in dateien:
            result = self.pdf_cache.get(pfad) or PDFAnalysisResult(pdf_path=pfad)
            if self.detail_panel.get_current_pdf() == pfad and pfad == self.selected_pdf:
                text, keywords, dates = self.selected_pdf_text, self.selected_pdf_keywords, self.selected_pdf_dates
            else:
                text, keywords, dates = result.extracted_text, result.keywords, result.dates
            vorbelegung = None
            if self.detail_panel.get_current_pdf() != pfad:
                vorbelegung = self._stapel_rechner().berechne(
                    pfad, self._namens_vorschlaege(pfad, result), result.extracted_text,
                    result.keywords, erkanntes_datum(result.dates),
                )
            namen = self._ablage_namen(pfad, folder_path, relative_path,
                                       vorbelegung=vorbelegung, dates=result.dates)
            eintraege.append(StapelEintrag(pfad, namen, text, keywords, dates))
        self._stapel_vereinheitlichen(eintraege)
        self._stapel_unterscheiden(eintraege)
        return eintraege

    def _stapel_ki_anbieter(self):
        """Der KI-Anbieter, wenn die KI gerade nutzbar ist, sonst None."""
        hc = self.hybrid_classifier
        provider = getattr(hc, "llm_provider", None)
        try:
            return provider if provider is not None and hc.is_llm_available() else None
        except Exception:  # noqa: BLE001 - ohne KI bleiben die Namen
            return None

    def _stapel_ki_warten(self, arbeit, hinweis: str) -> None:
        """Laesst ``arbeit`` im Hintergrund laufen; dauert es, zeigt ein Fenster ``hinweis`` mit "Nicht mehr warten"."""
        thread = threading.Thread(target=arbeit, name="namen-unterscheiden", daemon=True)
        thread.start()
        thread.join(0.2)
        if not thread.is_alive():
            return
        fortschritt = QProgressDialog(hinweis, tr("Nicht mehr warten"), 0, 0, self)
        fortschritt.setWindowTitle(tr("Namensvorschläge"))
        fortschritt.setWindowModality(Qt.WindowModality.WindowModal)
        fortschritt.setMinimumDuration(0)
        schleife = QEventLoop()
        takt = QTimer()
        takt.setInterval(150)
        takt.timeout.connect(lambda: (not thread.is_alive() or fortschritt.wasCanceled()) and schleife.quit())
        fortschritt.canceled.connect(schleife.quit)
        takt.start()
        if thread.is_alive():
            schleife.exec()
        takt.stop()
        fortschritt.close()
        fortschritt.deleteLater()

    def _stapel_vereinheitlichen(self, eintraege: list[StapelEintrag]) -> None:
        """Gleichartige Namen im Stapel gleich aufbauen (Issue #256), sonst bleibt es dabei.

        Die KI benennt jede Datei fuer sich; von mehreren Monatsrechnungen bekommt
        dann eine den Monat in den Namen und die naechste nicht. Tragen im Stapel
        nur einige von sonst gleichen Namen einen Zusatz am Ende, fragt ein
        KI-Aufruf je Gruppe nach dem Zusatz fuer die uebrigen. Ohne KI, bei Fehlern
        oder "Nicht mehr warten" behalten die Dateien ihre Namen.
        """
        namen = [e.namen.new_name or e.pfad.name for e in eintraege]
        gruppen = namen_unterscheiden.uneinheitliche_gruppen(namen)
        provider = self._stapel_ki_anbieter() if gruppen else None
        if provider is None:
            return
        ergebnis: dict[int, list] = {}
        fehler: list[str] = []

        def arbeit():
            for nr, g in enumerate(gruppen):
                try:
                    ergebnis[nr] = namen_unterscheiden.ergaenzen(
                        provider, [(namen[i], zusatz) for i, zusatz in g.mit.items()],
                        [namen[i] for i in g.ohne], [eintraege[i].text or "" for i in g.ohne])
                except Exception as ex:  # noqa: BLE001 - die anderen Gruppen trotzdem
                    fehler.append(str(ex))

        anzahl = sum(len(g.ohne) + len(g.mit) for g in gruppen)
        self._stapel_ki_warten(arbeit, tr(
            "Die KI gleicht die Namen von {anzahl} gleichartigen Dokumenten an …").format(anzahl=anzahl))

        for nr, zusaetze in dict(ergebnis).items():
            for i, zusatz in zip(gruppen[nr].ohne, zusaetze):
                if not zusatz:
                    continue
                n = eintraege[i].namen
                eintraege[i].namen = replace(
                    n,
                    new_name=namen_unterscheiden.zusatz_einfuegen(namen[i], zusatz),
                    name_changed=True,
                    learned_name=(namen_unterscheiden.zusatz_einfuegen(n.learned_name, zusatz)
                                  if n.learned_name else n.learned_name),
                )
        if fehler:
            logger.info("Namen angleichen: %s", "; ".join(fehler))
            self.statusbar.showMessage(tr("Namen nicht angeglichen: {0}").format(fehler[0]), 6000)

    def _stapel_unterscheiden(self, eintraege: list[StapelEintrag]) -> None:
        """Gleiche Namen im Stapel per KI unterscheiden (Issue #221), sonst bleibt es dabei.

        Je Gruppe gleicher Namen ein KI-Aufruf im Hintergrund; das Wort kommt vor die
        Endung. Ohne KI, bei Fehlern oder "Nicht mehr warten" behalten die Dateien
        ihre Namen (beim Umbenennen haengt der Dateimanager dann " (1)" usw. an).
        """
        gruppen = namen_unterscheiden.doppelte_gruppen([e.namen.new_name for e in eintraege])
        if not gruppen:
            return
        provider = self._stapel_ki_anbieter()
        if provider is None:
            return
        auftraege = [(eintraege[g[0]].namen.new_name, [eintraege[i].text or "" for i in g], tuple(g))
                     for g in gruppen]
        ergebnis: dict[tuple, list[str]] = {}
        fehler: list[str] = []

        def arbeit():
            for name, texte, gruppe in auftraege:
                try:
                    ergebnis[gruppe] = namen_unterscheiden.unterscheiden(provider, name, texte)
                except Exception as ex:  # noqa: BLE001 - die anderen Gruppen trotzdem
                    fehler.append(str(ex))

        self._stapel_ki_warten(arbeit, tr(
            "Die KI sieht nach, was {anzahl} gleich benannte Dokumente unterscheidet …").format(
                anzahl=sum(len(g) for g in gruppen)))

        for gruppe, woerter in dict(ergebnis).items():
            for i, wort in zip(gruppe, woerter):
                n = eintraege[i].namen
                eintraege[i].namen = replace(
                    n,
                    new_name=namen_unterscheiden.wort_einfuegen(n.new_name, wort),
                    learned_name=(namen_unterscheiden.wort_einfuegen(n.learned_name, wort)
                                  if n.learned_name else n.learned_name),
                )
        if fehler:
            logger.info("Namen unterscheiden: %s", "; ".join(fehler))
            self.statusbar.showMessage(tr("Gleiche Namen nicht unterschieden: {0}").format(fehler[0]), 6000)

    def _stapel_rueckfrage(self, titel: str, frage: str, eintraege: list[StapelEintrag],
                           ja_text: str, ja_ohne_namen: str, nur_text: Optional[str]) -> Optional[str]:
        zeilen = [(e.pfad.name, e.namen.new_name if e.namen.name_changed else None) for e in eintraege]
        if namen_unterscheiden.doppelte_gruppen([neu for _alt, neu in zeilen]):
            frage += (tr("\n\nEinige Dateien bekämen denselben Namen; beim Umbenennen wird "
                      "„ (1)“, „ (2)“ … angehängt."))
        if any(neu for _alt, neu in zeilen):
            return stapel_rueckfrage.frage(self, titel, frage, zeilen, ja_text, nur_text)
        # Kein Name aendert sich: "Nur verschieben" waere dasselbe
        return stapel_rueckfrage.frage(self, titel, frage, zeilen, ja_ohne_namen, None)

    # --- Verschieben ----------------------------------------------------------

    def stapel_verschieben(self, dateien: list[Path], folder_path: Path,
                           auswahl_behalten: bool = False) -> None:
        """Verschiebt mehrere Dateien nach ``folder_path``, jede mit ihrem Namen und ihren Metadaten.

        ``auswahl_behalten`` (Vorschlag aus dem Chat): Auswahl und Ordnervorschlaege
        bleiben, solange die ausgewaehlte PDF nicht selbst verschoben wurde.
        """
        dateien = [Path(p) for p in dateien]
        folder_path = Path(folder_path)
        # Issue #245: Dateien, die es im Ziel oder im Archiv schon gibt, erst nachfragen
        dateien = self._doppelte_vor_ablage(dateien, folder_path)
        if not dateien:
            return
        relative_path = self.folder_tree.get_relative_path(folder_path)

        neu_anlegen = not folder_path.exists()  # vorgeschlagener neuer Ordner (Issue #116)

        self._stapel_vorbereiten(dateien)
        eintraege = self._stapel_eintraege(dateien, folder_path, relative_path)
        wahl = self._stapel_rueckfrage(
            tr("Mehrere Dateien verschieben") if len(dateien) > 1 else tr("Datei verschieben"),
            tr("{wer} nach '{relative_path}' verschieben?").format(
                wer=(tr("{anzahl} Dateien").format(anzahl=len(dateien)) if len(dateien) > 1
                     else f"'{dateien[0].name}'"),
                relative_path=relative_path)
            + (tr("\n\nDer Ordner '{relative_path}' wird dafür neu angelegt.").format(
                relative_path=relative_path) if neu_anlegen else ""),
            eintraege,
            ja_text=tr("Verschieben und umbenennen"),
            ja_ohne_namen=tr("Verschieben"),
            nur_text=tr("Nur verschieben"),
        )
        if wahl is None:
            return
        umbenennen = wahl == UMBENENNEN

        angelegt: list[Path] = []
        if neu_anlegen:
            from src.core import neuer_ordner
            try:
                angelegt = neuer_ordner.anlegen(folder_path)
            except OSError as ex:
                QMessageBox.critical(self, tr("Fehler"), tr("Ordner konnte nicht angelegt werden:\n{ex}").format(ex=ex))
                return
            self._invalidate_folder_caches()

        original_selected = self.selected_pdf
        paare: list[tuple[Path, Path]] = []
        fehler: list[str] = []
        umbenannt = 0
        for e in eintraege:
            namen = e.namen if umbenennen else AblageNamen(
                new_name=None, name_changed=False, learned_name=None, folder_naming_applied=False,
                metadata={}, office_ext=e.namen.office_ext, dokument_id=e.namen.dokument_id,
            )
            try:
                neu = self.file_manager.move_file(e.pfad, folder_path, new_name=namen.new_name)
            except Exception as ex:  # noqa: BLE001 - die uebrigen Dateien trotzdem verschieben
                fehler.append(f"{e.pfad.name}: {ex}")
                continue
            paare.append((e.pfad, neu))
            if namen.name_changed:
                umbenannt += 1
            self.pdf_cache.migrate_cache_entry(e.pfad, neu)
            meta = namen.metadata or {}
            try:
                self._aus_ablage_lernen(e.pfad, folder_path, relative_path, neu, namen,
                                        text=e.text, keywords=e.keywords, dates=e.dates)
                self.db.update_pdf_path(
                    old_path=str(e.pfad),
                    new_path=str(neu),
                    new_filename=neu.name,
                    extracted_text=e.text or "",
                    keywords=", ".join(e.keywords) if e.keywords else "",
                    korrespondent=meta.get("korrespondent", ""),
                    kategorie=meta.get("subject", ""),
                    steuerjahr=meta.get("steuerjahr", ""),
                    betrag=meta.get("betrag", ""),
                    zusammenfassung=meta.get("description", ""),
                    target_folder=relative_path,
                )
            except Exception as ex:  # noqa: BLE001 - Datei liegt schon richtig, Lernen ist Zugabe
                logger.warning(f"Stapel-Ablage: Nacharbeit fuer {neu.name}: {ex}")
            # Erst den Suchindex nachfuehren, dann den Hintergrund-Schreiber starten: beide
            # legen sonst gleichzeitig den Eintrag des neuen Pfads an (UNIQUE-Fehler)
            if meta and not namen.office_ext:
                self._write_pdf_metadata_async(neu, neu.name, e.keywords, meta)

        self.training_label.setText(tr("Gelernt: {0}").format(self.classifier.get_training_count()))
        if paare:
            info = tr(" ({umbenannt} umbenannt)").format(umbenannt=umbenannt) if umbenannt else ""
            self.statusbar.showMessage(tr("{anzahl} Dateien nach '{relative_path}' verschoben{info}").format(anzahl=len(paare), relative_path=relative_path, info=info), 4000)
            desc = (f"{paare[0][0].name} → {relative_path}" if len(paare) == 1
                    else tr("{anzahl} Dateien → {relative_path}").format(anzahl=len(paare), relative_path=relative_path))
            eintrag = {"type": "move", "moves": paare, "description": desc}
            if angelegt:
                eintrag["created_dirs"] = list(angelegt)  # Rueckgaengig raeumt ihn leer wieder weg
            self._push_undo(eintrag)
        elif angelegt:  # nichts verschoben: den neuen Ordner nicht leer liegen lassen
            from src.core import neuer_ordner
            neuer_ordner.leere_wegraeumen(angelegt)
            self._invalidate_folder_caches()
        if fehler:
            QMessageBox.warning(
                self, tr("Teilweise fehlgeschlagen"),
                tr("Einige Dateien konnten nicht verschoben werden:\n{0}").format('\n'.join(fehler)),
            )

        # Verschobene Kacheln entfernen und die naechste PDF auswaehlen (Issue #75)
        selected_removed_index = None
        for alt, _neu in paare:
            index = self.remove_pdf_widget(alt)
            if alt == original_selected:
                selected_removed_index = index
        verschoben = {alt for alt, _neu in paare}
        auswahl_bleibt = auswahl_behalten and original_selected not in verschoben
        auto_selected = False
        if auswahl_bleibt:
            self.selected_pdfs = [p for p in self.selected_pdfs if p not in verschoben]
        elif selected_removed_index is not None and self.pdf_widgets and not self._korr_aktiv:
            self.selected_pdfs = []
            next_index = min(selected_removed_index, len(self.pdf_widgets) - 1)
            self.on_pdf_clicked(self.pdf_widgets[next_index].pdf_path)
            auto_selected = True
        else:
            self.selected_pdfs = []
            self.selected_pdf = None
            self.selected_pdf_text = None
            self.selected_pdf_keywords = None

        if paare:
            self.config.add_to_last_used(folder_path)
        self._refresh_after_move(folder_path, *{p.parent for p in dateien})
        if not auto_selected and not auswahl_bleibt:
            self.clear_suggestions()
        if self._korr_aktiv:
            self._korr_auswahl_leeren()  # Dokumente aus dem Reiter "Korrespondenten" sind abgelegt
        if paare:
            self._auto_collect_korrespondenten()

    # --- Umbenennen am Platz --------------------------------------------------

    def stapel_umbenennen_speichern(self, dateien: list[Path]) -> None:
        """"Umbenennen + Metadaten speichern" fuer alle markierten PDFs."""
        dateien = [Path(p) for p in dateien]
        pdfs = [p for p in dateien if not ist_office_datei(p)]
        anders = len(dateien) - len(pdfs)
        if not pdfs:
            self.statusbar.showMessage(
                tr("Metadaten lassen sich nur in PDFs speichern - erst in PDF umwandeln"), 4000)
            return

        self._stapel_vorbereiten(pdfs)
        eintraege = self._stapel_eintraege(pdfs, None, "")
        frage = tr("{anzahl} PDFs umbenennen und Metadaten speichern?").format(anzahl=len(pdfs))
        if anders:
            frage += tr("\n{anders} weitere Datei(en) sind keine PDF und bleiben unverändert.").format(anders=anders)
        wahl = self._stapel_rueckfrage(
            tr("Mehrere PDFs umbenennen"), frage, eintraege,
            ja_text=tr("Umbenennen und speichern"), ja_ohne_namen=tr("Metadaten speichern"), nur_text=None,
        )
        if wahl is None:
            return

        panel_pdf = self.detail_panel.get_current_pdf()
        paare: list[tuple[Path, Path]] = []
        fehler: list[str] = []
        gespeichert = 0
        for e in eintraege:
            try:
                neu = e.pfad
                if e.namen.name_changed:
                    neu = self.file_manager.rename_file(e.pfad, e.namen.new_name)
                    paare.append((e.pfad, neu))
                    self.pdf_cache.migrate_cache_entry(e.pfad, neu)
                    self._update_pdf_widget_path(e.pfad, neu)
                    if e.keywords:  # Umbenennung lernen (wie bei einer einzelnen PDF)
                        self.db.add_rename_entry(
                            original_filename=e.pfad.name,
                            new_filename=neu.name,
                            extracted_text=e.text,
                            keywords=e.keywords,
                            detected_date=None,
                        )
                meta = e.namen.metadata or {}
                if meta:
                    self._write_pdf_metadata(neu, neu.name, e.keywords, meta)
                    if meta.get("korrespondent"):
                        self.db.learn_korrespondent_metadata(meta["korrespondent"], meta)
                if e.pfad == panel_pdf:
                    self.detail_panel._current_pdf = neu
                    self.detail_panel.header_label.setText(tr("Original: {name}").format(name=neu.name))
                    self.detail_panel.mark_metadata_saved()
                gespeichert += 1
            except Exception as ex:  # noqa: BLE001 - die uebrigen trotzdem
                fehler.append(f"{e.pfad.name}: {ex}")

        if paare:
            desc = (f"{paare[0][0].name} → {paare[0][1].name}" if len(paare) == 1
                    else tr("{anzahl} PDFs umbenannt").format(anzahl=len(paare)))
            self._push_undo({"type": "renames", "moves": paare, "description": desc})
        if gespeichert:
            self.statusbar.showMessage(
                tr("{gespeichert} PDFs gespeichert, {anzahl} umbenannt").format(gespeichert=gespeichert, anzahl=len(paare)), 4000)
        if fehler:
            QMessageBox.warning(
                self, tr("Teilweise fehlgeschlagen"),
                tr("Einige PDFs konnten nicht umbenannt/gespeichert werden:\n{0}").format('\n'.join(fehler)),
            )

    def _undo_renames(self, entry: dict) -> None:
        """Macht die Umbenennungen eines Stapels in einem Schritt rueckgaengig."""
        paare = entry["moves"]
        self._wait_for_metadata_writes([neu for _alt, neu in paare])
        fehlend = [neu for _alt, neu in paare if not neu.exists()]
        if fehlend:
            QMessageBox.warning(
                self, tr("Rückgängig nicht möglich"),
                tr(
                    "Folgende Dateien wurden nicht mehr gefunden:\n"
                    "{0}\n\nMöglicherweise wurden sie inzwischen umbenannt, verschoben oder "
                    "gelöscht."
                ).format('\n'.join((p.name for p in fehlend))),
            )
            self._undo_stack.pop()
            self._update_undo_ui()
            return
        antwort = QMessageBox.question(
            self, tr("Rückgängig machen"),
            tr("{anzahl} Umbenennungen rückgängig machen?").format(anzahl=len(paare)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if antwort != QMessageBox.StandardButton.Yes:
            return

        zurueck: list[tuple[Path, Path]] = []
        fehler: list[str] = []
        for alt, neu in paare:
            try:
                if alt.exists():
                    raise FileExistsError(tr("'{name}' gibt es schon").format(name=alt.name))
                wieder = self.file_manager.rename_file(neu, alt.name)
                self.pdf_cache.migrate_cache_entry(neu, wieder)
                self._update_pdf_widget_path(neu, wieder)
                if self.detail_panel.get_current_pdf() == neu:
                    self.detail_panel._current_pdf = wieder
                    self.detail_panel.header_label.setText(tr("Original: {name}").format(name=wieder.name))
                zurueck.append((neu, wieder))
            except Exception as ex:  # noqa: BLE001
                fehler.append(f"{neu.name}: {ex}")

        self._undo_stack.pop()
        self._update_undo_ui()
        self.korrespondenten_view.pfade_aktualisieren(zurueck)
        if fehler:
            QMessageBox.warning(
                self, tr("Teilweise fehlgeschlagen"),
                tr("{anzahl} von {anzahl2} Umbenennungen rückgängig gemacht.\n\nFehler:\n{0}").format('\n'.join(fehler), anzahl=len(zurueck), anzahl2=len(paare)),
            )
        else:
            self.statusbar.showMessage(tr("Rückgängig: {anzahl} Umbenennungen").format(anzahl=len(zurueck)), 3000)

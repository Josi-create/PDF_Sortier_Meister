"""Hauptfenster-Teil fuer Bilder und das Wegraeumen von Originalen (Issues #184, #187).

:class:`BildAktionenMixin` haelt, getrennt von ``main_window.py``: "In PDF
umwandeln" und "Zu einem PDF zusammenfuegen" fuer Bilder, die Frage "Original
in den Papierkorb?" nach Umwandeln und Trennen (siehe ``original_wegraeumen``)
und das Entfernen der Kachel eines weggeraeumten Originals.

GPL-3.0-or-later - Copyright (c) 2026
"""

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from src.core.bild_convert import ist_bild_datei, pdf_lesbar
from src.core.entzerren import TONWERT_STANDARD, TONWERTE, Entzerrung
from src.gui import original_wegraeumen as ow
from src.gui.bild_convert_worker import BildConvertWorker, BilderEinzelnWorker, EntzerrErkennungWorker
from src.gui.entzerren_dialog import EntzerrenDialog
from src.search.meldungen import melden as index_melden
from src.i18n import tr


def _seiten_summe(pdfs: list[Path]) -> int:
    """Seiten aller PDFs zusammen; nicht lesbare zaehlen als sehr viele (dann wird nichts weggeraeumt)."""
    import pymupdf

    summe = 0
    for pdf in pdfs:
        try:
            with pymupdf.open(str(pdf)) as doc:
                summe += doc.page_count
        except Exception:  # noqa: BLE001
            return 10**9
    return summe


def _namen(pfade: list[Path], maximal: int = 3) -> str:
    namen = [p.name for p in pfade[:maximal]]
    if len(pfade) > maximal:
        namen.append(f"… (+{len(pfade) - maximal})")
    return ", ".join(namen)


class BildAktionenMixin:
    """Mixin fuer ``MainWindow``; braucht ``statusbar``, ``config``, ``file_manager``, ``pdf_widgets`` usw."""

    _bild_worker: Optional[BildConvertWorker] = None
    _erkennung_worker: Optional[EntzerrErkennungWorker] = None  # Blatt suchen (Issue #205)

    # --- Bilder -> PDF -----------------------------------------------------------

    def on_bild_convert(self, pfad: Path):
        """Kontextmenue "In PDF umwandeln" eines Bildes."""
        self._bilder_umwandeln([pfad])

    def on_bilder_zusammenfuegen(self, pfad: Path):
        """Kontextmenue "Zu einem PDF zusammenfügen": die markierten Bilder, in Ansichtsreihenfolge."""
        markiert = [p for p in self.selected_pdfs if ist_bild_datei(p)]
        if pfad not in markiert:
            markiert = [pfad]
        reihenfolge = {w.pdf_path: i for i, w in enumerate(self.pdf_widgets)}
        markiert.sort(key=lambda p: reihenfolge.get(p, len(reihenfolge)))
        self._bilder_umwandeln(markiert)

    def _bild_beschaeftigt(self) -> bool:
        return (self._bild_worker is not None or self._erkennung_worker is not None
                or self._office_worker is not None)

    # --- Entzerren (Issue #205) ----------------------------------------------------

    def on_bild_entzerren(self, pfad: Path, art: str, modus: str):
        """Kontextmenue "... und automatisch/von Hand entzerren".

        ``art``: ``einzeln`` (je Bild ein PDF) oder ``zusammen`` (ein PDF aus allen markierten Bildern);
        ``modus``: ``auto`` oder ``hand``.
        """
        markiert = [p for p in self.selected_pdfs if ist_bild_datei(p)]
        if pfad not in markiert:
            markiert = [pfad]
        reihenfolge = {w.pdf_path: i for i, w in enumerate(self.pdf_widgets)}
        markiert.sort(key=lambda p: reihenfolge.get(p, len(reihenfolge)))
        self.bilder_entzerren(markiert, art, modus)

    def bilder_entzerren(self, pfade: list[Path], art: str, modus: str):
        """Sucht im Hintergrund das Blatt je Foto; danach Dialog (von Hand / unsichere) oder direkt umwandeln."""
        if self._bild_beschaeftigt():
            self.statusbar.showMessage(tr("Eine Umwandlung läuft noch - bitte warten."), 4000)
            return
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        text = pfade[0].name if len(pfade) == 1 else tr("{anzahl} Bildern").format(anzahl=len(pfade))
        self.statusbar.showMessage(tr("Suche das Blatt in {text}…").format(text=text))
        worker = EntzerrErkennungWorker(pfade, self)
        worker.fertig.connect(lambda ergebnisse: self._on_erkennung_fertig(ergebnisse, art, modus))
        self._erkennung_worker = worker
        worker.start()

    def _tonwerte_standard(self) -> str:
        wert = self.config.get("bild_tonwerte", TONWERT_STANDARD)
        return wert if wert in TONWERTE else TONWERT_STANDARD

    def _on_erkennung_fertig(self, ergebnisse: list, art: str, modus: str):
        self._erkennung_worker = None
        QApplication.restoreOverrideCursor()
        tonwerte = self._tonwerte_standard()
        lesbar = [(p, erk) for p, erk, fehler in ergebnisse if erk is not None]
        fehler = [f"{p.name}: {text}" for p, erk, text in ergebnisse if erk is None]
        if fehler:
            QMessageBox.warning(self, tr("Entzerren"), "\n".join(fehler))
        if not lesbar:
            self.statusbar.showMessage(tr("Entzerren: kein Bild lesbar."), 6000)
            return
        vorgaben = {p: erk.ecken for p, erk in lesbar}
        unsicher = {p for p, erk in lesbar if not erk.sicher}
        auftraege = {p: Entzerrung(list(erk.ecken), tonwerte) for p, erk in lesbar}
        # Von Hand: alle im Fenster; automatisch: nur die Bilder, bei denen die Erkennung unsicher war
        im_fenster = [p for p, _ in lesbar if modus == "hand" or p in unsicher]
        if im_fenster:
            dialog = EntzerrenDialog(im_fenster, vorgaben, tonwerte, self, unsicher=unsicher)
            if dialog.exec() != EntzerrenDialog.DialogCode.Accepted:
                self.statusbar.showMessage(tr("Entzerren abgebrochen - nichts wurde geändert."), 5000)
                return
            auftraege.update(dialog.ergebnis())
            tonwerte = dialog.tonwerte()  # die Wahl im Fenster gilt fuer alle Bilder dieses Auftrags
            for auftrag in auftraege.values():
                auftrag.tonwerte = tonwerte
        pfade = [p for p, _ in lesbar if p in auftraege]
        if art == "zusammen" or len(pfade) == 1:
            self._bilder_umwandeln(pfade, entzerrung=auftraege)
        else:
            self.bilder_einzeln_umwandeln(pfade, entzerrung=auftraege)

    def bilder_einzeln_umwandeln(self, pfade: list[Path], entzerrung: Optional[dict] = None):
        """Mehrfachauswahl "Einzeln in PDFs umwandeln": jedes Bild ein eigenes PDF (Live-Test 08.11.2026)."""
        if self._bild_beschaeftigt():
            self.statusbar.showMessage(tr("Eine Umwandlung läuft noch - bitte warten."), 4000)
            return
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        self.statusbar.showMessage(tr("Wandle {anzahl} Bilder einzeln in PDFs um (mit Texterkennung)…").format(anzahl=len(pfade)))
        worker = BilderEinzelnWorker(pfade, self, entzerrung)
        worker.fortschritt.connect(lambda i, n, p: self.statusbar.showMessage(
            tr("Wandle in PDF um ({i}/{n}, mit Texterkennung): {name}…").format(i=i, n=n, name=p.name)))
        worker.fertig.connect(self._on_bilder_einzeln_converted)
        self._bild_worker = worker
        worker.start()

    def _on_bilder_einzeln_converted(self, ergebnisse: list):
        self._bild_worker = None
        QApplication.restoreOverrideCursor()
        fehler, hinweise, erzeugt, lesbar = [], [], [], []
        for quelle, erg, fehlertext in ergebnisse:
            if erg is None:
                fehler.append(f"{quelle.name}: {fehlertext}")
                continue
            erzeugt.append(erg.pdf)
            index_melden("datei_aufnehmen", str(erg.pdf))
            if erg.ocr_hinweis:
                hinweise.append(erg.ocr_hinweis)
            if pdf_lesbar(erg.pdf, erg.seiten):
                lesbar.append((quelle, erg.pdf))
        if lesbar:
            # Eine Frage fuer alle Originale, nicht eine je Bild
            self.original_nach_umwandeln([q for q, _ in lesbar], [p for _, p in lesbar])
        if erzeugt:
            self.neues_pdf_auswaehlen(erzeugt[0])
            meldung = tr("{anzahl} PDF(s) erstellt").format(anzahl=len(erzeugt))
            if hinweise:
                meldung += f" - {hinweise[0]}"  # z. B. "ohne Texterkennung", gilt fuer alle
            self.statusbar.showMessage(meldung, 10000 if hinweise else 6000)  # nach der Auswahl
        if fehler:
            QMessageBox.warning(self, tr("In PDF umwandeln"), "\n".join(fehler))

    def _bilder_umwandeln(self, pfade: list[Path], entzerrung: Optional[dict] = None):
        if self._bild_beschaeftigt():
            self.statusbar.showMessage(tr("Eine Umwandlung läuft noch - bitte warten."), 4000)
            return
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        text = pfade[0].name if len(pfade) == 1 else tr("{anzahl} Bilder").format(anzahl=len(pfade))
        self.statusbar.showMessage(tr("Wandle in PDF um (mit Texterkennung): {text}…").format(text=text))
        worker = BildConvertWorker(pfade, self, entzerrung)
        worker.fertig.connect(self._on_bild_converted)
        self._bild_worker = worker
        worker.start()

    def _on_bild_converted(self, quellen: list, erg, fehlertext):
        self._bild_worker = None
        QApplication.restoreOverrideCursor()
        if erg is None:
            QMessageBox.warning(self, tr("In PDF umwandeln"), f"{_namen(quellen)}: {fehlertext}")
            return
        index_melden("datei_aufnehmen", str(erg.pdf))
        meldung = tr("PDF erstellt ({seiten} Seite(n)").format(seiten=erg.seiten)
        meldung += tr(", durchsuchbar)") if erg.ocr_seiten else ")"
        meldung += f": {erg.pdf.name}"
        if erg.ocr_hinweis:
            meldung += f" - {erg.ocr_hinweis}"
        # Nur wenn die PDF wirklich da und lesbar ist, wird das Original zur Wahl gestellt
        if pdf_lesbar(erg.pdf, erg.seiten):
            self.original_nach_umwandeln(quellen, erg.pdf)
        self.neues_pdf_auswaehlen(erg.pdf)
        self.statusbar.showMessage(meldung, 10000 if erg.ocr_hinweis else 6000)  # nach der Auswahl (sie meldet "Analysiere")

    # --- Original wegraeumen -------------------------------------------------------

    def original_nach_umwandeln(self, quellen: list[Path], pdf) -> list[Path]:
        """Fragt (oder nutzt die gemerkte Antwort), ob die umgewandelten Originale in den Papierkorb sollen.

        ``pdf``: das erzeugte PDF oder die Liste der erzeugten PDFs (eine Frage fuer alle).
        """
        pdfs = list(pdf) if isinstance(pdf, (list, tuple)) else [pdf]
        if len(pdfs) == 1:
            text = (tr(
                "Das PDF '{name}' wurde erstellt.\n\nOriginal in den Papierkorb "
                "verschieben?\n{0}"
            ).format(_namen(quellen), name=pdfs[0].name))
        else:
            text = (tr(
                "{anzahl} PDFs wurden erstellt.\n\nDie {anzahl2} Originale in den Papierkorb "
                "verschieben?\n{0}"
            ).format(_namen(quellen), anzahl=len(pdfs), anzahl2=len(quellen)))
        beschreibung = tr("Original weggeräumt: {0}").format(_namen(quellen))
        return ow.original_wegraeumen(self, quellen, "umwandeln", text, beschreibung)

    def original_nach_trennen(self, original: Path, teile: list[Path]) -> list[Path]:
        """Wie ``original_nach_umwandeln``, nach dem Trennen eines PDFs."""
        if not teile or not all(pdf_lesbar(t) for t in teile):
            return []  # nur nach erfolgreichem Trennen
        text = (tr(
            "'{name}' wurde in {anzahl} Datei(en) getrennt.\n\n"
            "Original in den Papierkorb verschieben?"
        ).format(name=original.name, anzahl=len(teile)))
        return ow.original_wegraeumen(self, [original], "trennen", text,
                                      tr("Original nach dem Trennen weggeräumt: {name}").format(name=original.name))

    def originale_nach_zusammenfuegen(self, quellen: list[Path], ziel: Path) -> list[Path]:
        """Wie ``original_nach_trennen``: die Einzel-PDFs nach dem Zusammenfügen wegräumen."""
        quellen = [q for q in quellen if q != ziel]
        if not quellen or not pdf_lesbar(ziel, _seiten_summe(quellen)):
            return []  # nur wenn das zusammengefügte PDF wirklich alle Seiten hat
        text = (tr(
            "{anzahl} PDFs wurden zu '{name}' zusammengefügt.\n\n"
            "Die {anzahl} einzelnen PDFs in den Papierkorb verschieben?\n"
            "{0}"
        ).format(_namen(quellen), anzahl=len(quellen), name=ziel.name))
        return ow.original_wegraeumen(self, quellen, "zusammenfuegen", text,
                                      tr("Einzel-PDFs nach dem Zusammenfügen weggeräumt: {0}").format(_namen(quellen)))

    def original_entfernt(self, pfad: Path):
        """Kachel, Analyse und Detailansicht eines weggeraeumten Originals aufraeumen."""
        war_ausgewaehlt = self.selected_pdf == pfad
        self.remove_pdf_widget(pfad)
        self.pdf_cache.clear_for_pdf(pfad)
        if war_ausgewaehlt:
            self.detail_panel.clear()

    def neues_pdf_auswaehlen(self, pdf: Path):
        """Kacheln neu laden und das neue PDF wie angeklickt auswaehlen."""
        self.load_pdfs()
        widget = self._pdf_widget_for(pdf)
        if widget is not None:
            self.on_pdf_clicked(pdf)
            self.zur_kachel_scrollen(pdf)


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
from src.gui import original_wegraeumen as ow
from src.gui.bild_convert_worker import BildConvertWorker
from src.search.meldungen import melden as index_melden


def _namen(pfade: list[Path], maximal: int = 3) -> str:
    namen = [p.name for p in pfade[:maximal]]
    if len(pfade) > maximal:
        namen.append(f"… (+{len(pfade) - maximal})")
    return ", ".join(namen)


class BildAktionenMixin:
    """Mixin fuer ``MainWindow``; braucht ``statusbar``, ``config``, ``file_manager``, ``pdf_widgets`` usw."""

    _bild_worker: Optional[BildConvertWorker] = None

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

    def _bilder_umwandeln(self, pfade: list[Path]):
        if (self._bild_worker is not None) or self._office_worker is not None:
            self.statusbar.showMessage("Eine Umwandlung läuft noch - bitte warten.", 4000)
            return
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        text = pfade[0].name if len(pfade) == 1 else f"{len(pfade)} Bilder"
        self.statusbar.showMessage(f"Wandle in PDF um (mit Texterkennung): {text}…")
        worker = BildConvertWorker(pfade, self)
        worker.fertig.connect(self._on_bild_converted)
        self._bild_worker = worker
        worker.start()

    def _on_bild_converted(self, quellen: list, erg, fehlertext):
        self._bild_worker = None
        QApplication.restoreOverrideCursor()
        if erg is None:
            QMessageBox.warning(self, "In PDF umwandeln", f"{_namen(quellen)}: {fehlertext}")
            return
        index_melden("datei_aufnehmen", str(erg.pdf))
        meldung = f"PDF erstellt ({erg.seiten} Seite(n)"
        meldung += ", durchsuchbar)" if erg.ocr_seiten else ")"
        meldung += f": {erg.pdf.name}"
        if erg.ocr_hinweis:
            meldung += f" - {erg.ocr_hinweis}"
        # Nur wenn die PDF wirklich da und lesbar ist, wird das Original zur Wahl gestellt
        if pdf_lesbar(erg.pdf, erg.seiten):
            self.original_nach_umwandeln(quellen, erg.pdf)
        self.neues_pdf_auswaehlen(erg.pdf)
        self.statusbar.showMessage(meldung, 10000 if erg.ocr_hinweis else 6000)  # nach der Auswahl (sie meldet "Analysiere")

    # --- Original wegraeumen -------------------------------------------------------

    def original_nach_umwandeln(self, quellen: list[Path], pdf: Path) -> list[Path]:
        """Fragt (oder nutzt die gemerkte Antwort), ob die umgewandelten Originale in den Papierkorb sollen."""
        text = (f"Das PDF '{pdf.name}' wurde erstellt.\n\n"
                f"Original in den Papierkorb verschieben?\n{_namen(quellen)}")
        beschreibung = f"Original weggeräumt: {_namen(quellen)}"
        return ow.original_wegraeumen(self, quellen, "umwandeln", text, beschreibung)

    def original_nach_trennen(self, original: Path, teile: list[Path]) -> list[Path]:
        """Wie ``original_nach_umwandeln``, nach dem Trennen eines PDFs."""
        if not teile or not all(pdf_lesbar(t) for t in teile):
            return []  # nur nach erfolgreichem Trennen
        text = (f"'{original.name}' wurde in {len(teile)} Datei(en) getrennt.\n\n"
                "Original in den Papierkorb verschieben?")
        return ow.original_wegraeumen(self, [original], "trennen", text,
                                      f"Original nach dem Trennen weggeräumt: {original.name}")

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
            self.pdf_scroll_area.ensureWidgetVisible(widget)


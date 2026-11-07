"""
Schwer lesbare Scans: andere Erkennung anbieten (Issue #47)

Zwei Wege fuer PDFs, deren Text trotz Drehen schlecht erkannt ist (Handschrift,
Fraktur, andere Sprache; die Kachel traegt dann ein Warndreieck):

* "OCR wiederholen mit ..." - Tesseract mit anderen Sprachen, im Hintergrund;
  uebernommen wird nur ein besseres Ergebnis.
* "Handschrift mit KI entziffern" - Seitenbilder an das eingestellte
  KI-Modell, falls es Bilder versteht; das Ergebnis zeigt ein Dialog, und erst
  auf Knopfdruck wird es als Text gespeichert.

Dieses Modul haelt die Abfolge zusammen, damit das Hauptfenster nur
Signale weiterreicht.

GPL-3.0-or-later - Copyright (c) 2026
"""

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

# Modulweit importieren (Lazy-Imports in Threads aendern sys.modules, siehe conftest.patch_singletons)
from src.core import handschrift_ki
from src.core.pdf_analyzer import ocr_schlecht
from src.gui.ocr_neu_worker import OcrWiederholenWorker
from src.ml.llm_provider import is_cloud_provider
from src.utils.tesseract import sprachname

KI_TAB = "KI-Assistent (LLM)"   # Titel der Einstellungsseite (SettingsDialog.show_tab)


class HandschriftWorker(QThread):
    """Schickt die Seiten einer PDF als Bilder an das KI-Modell (Hintergrund)."""

    fortschritt = pyqtSignal(int, int)   # (Seite, Anzahl)
    fertig = pyqtSignal(dict)            # Ergebnis von handschrift_ki.entziffern

    def __init__(self, pdf_path: Path, provider, parent=None):
        super().__init__(parent)
        self.pdf_path = Path(pdf_path)
        self.provider = provider

    def run(self):
        try:
            erg = handschrift_ki.entziffern(
                self.pdf_path, self.provider,
                abbrechen=self.isInterruptionRequested, fortschritt=self.fortschritt.emit)
        except Exception as e:  # noqa: BLE001 - melden, nie den Thread verlieren
            erg = {"texte": {}, "seiten": 0, "gesamt": 0, "gekuerzt": False, "fehler": str(e)}
        self.fertig.emit(erg)


def zeige_vision_hilfe(parent, grund: str) -> bool:
    """Hilfedialog, wenn kein Bilder lesender KI-Anbieter eingestellt ist.

    Liefert True, wenn der Nutzer "Einstellungen öffnen" gewaehlt hat.
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle("Handschrift mit KI entziffern")
    box.setText("Dafür ist ein KI-Modell mit Bilderkennung nötig.")
    box.setInformativeText(f"{grund}\n\n{handschrift_ki.HILFE_TEXT}")
    knopf = box.addButton("Einstellungen öffnen", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Schließen", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is knopf


class HandschriftErgebnisDialog(QDialog):
    """Zeigt den entzifferten Text (kopierbar); "Als Text übernehmen" speichert ihn wie OCR-Text."""

    def __init__(self, texte: dict, hinweis: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Handschrift entziffert")
        self.resize(640, 520)
        self.uebernehmen = False
        layout = QVBoxLayout(self)
        if hinweis:
            label = QLabel(hinweis)
            label.setWordWrap(True)
            layout.addWidget(label)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)   # markier- und kopierbar
        self.text_edit.setPlainText(handschrift_ki.gesamttext(texte))
        layout.addWidget(self.text_edit)
        self.buttons = QDialogButtonBox()
        self.kopieren_button = self.buttons.addButton("Alles kopieren", QDialogButtonBox.ButtonRole.ActionRole)
        self.uebernehmen_button = self.buttons.addButton("Als Text übernehmen", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton("Schließen", QDialogButtonBox.ButtonRole.RejectRole)
        self.uebernehmen_button.setToolTip("Speichert den Text wie erkannten OCR-Text (Suche, Analyse)")
        self.kopieren_button.clicked.connect(self._kopieren)
        self.buttons.accepted.connect(self._uebernehmen)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _kopieren(self):
        QApplication.clipboard().setText(self.text_edit.toPlainText())

    def _uebernehmen(self):
        self.uebernehmen = True
        self.accept()


class OcrSchwerLesbar(QObject):
    """Ablauf der beiden Wege fuer ein Hauptfenster (``fenster``)."""

    def __init__(self, fenster):
        super().__init__(fenster)
        self.fenster = fenster
        self._worker: Optional[QThread] = None
        self._pdf: Optional[Path] = None

    @property
    def laeuft(self) -> bool:
        return self._worker is not None

    def abbrechen(self):
        """Beim Beenden des Programms: vor der naechsten Seite aufhoeren."""
        if self._worker is not None:
            self._worker.requestInterruption()

    def _beschaeftigt(self) -> bool:
        if self._worker is not None:
            self.fenster.statusbar.showMessage("Eine Erkennung läuft noch - bitte warten.", 4000)
            return True
        return False

    def _start(self, worker: QThread, pdf_path: Path, text: str):
        self._pdf = pdf_path
        self._worker = worker
        widget = self.fenster._pdf_widget_for(pdf_path)
        if widget is not None:
            widget.analyzing = True
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        self.fenster.statusbar.showMessage(text)
        worker.start()

    def _ende(self):
        widget = self.fenster._pdf_widget_for(self._pdf) if self._pdf is not None else None
        if widget is not None:
            widget.analyzing = False
        QApplication.restoreOverrideCursor()
        self._worker = None

    def _text_neu_laden(self, pdf_path: Path):
        """Analyse verwerfen; ist die PDF ausgewaehlt, Vorschlaege neu holen."""
        fenster = self.fenster
        fenster.pdf_cache.clear_for_pdf(pdf_path)
        if fenster.selected_pdf is not None and not fenster.selected_pdfs and fenster.selected_pdf == pdf_path:
            fenster.update_suggestions_for_pdf(pdf_path)

    # --- OCR wiederholen mit ... --------------------------------------------

    def sprache_wiederholen(self, pdf_path: Path, sprachen: str):
        """Kontextmenue "OCR wiederholen mit ...": Hintergrund-Lauf mit den gewaehlten Tesseract-Sprachen."""
        if self._beschaeftigt():
            return
        worker = OcrWiederholenWorker(pdf_path, sprachen, self.fenster)
        worker.fertig.connect(lambda ergebnisse, s=sprachen: self._sprache_fertig(ergebnisse, s))
        self._start(worker, pdf_path, f"OCR wiederholen mit {sprachname(sprachen)}: {pdf_path.name}…")

    def _sprache_fertig(self, ergebnisse: list, sprachen: str):
        self._ende()
        titel = "OCR wiederholen"
        for path, erg in ergebnisse:
            name = sprachname(sprachen)
            if erg.get("fehler"):
                QMessageBox.warning(self.fenster, titel, f"{path.name}: {erg['fehler']}")
            elif not erg.get("index"):
                QMessageBox.information(
                    self.fenster, titel,
                    "Der Text wird im Suchindex gespeichert, und der ist nicht eingerichtet. "
                    "Richten Sie die Suche in den Einstellungen ein.")
            elif erg.get("besser"):
                self._text_neu_laden(path)
                widget = self.fenster._pdf_widget_for(path)
                if widget is not None:
                    widget.ocr_schlecht = ocr_schlecht(erg.get("nachher"))
                QMessageBox.information(
                    self.fenster, titel,
                    f"Mit „{name}“ wurde der Text besser erkannt{_vergleich(erg)} "
                    f"und ersetzt den bisherigen ({erg.get('seiten', 0)} Seite(n)).")
                self.fenster.statusbar.showMessage(f"OCR wiederholt mit {name}: Text ersetzt", 6000)
            else:
                QMessageBox.information(
                    self.fenster, titel,
                    f"Mit „{name}“ wurde der Text nicht besser erkannt{_vergleich(erg)}. "
                    "Der bisherige Text bleibt.")
                self.fenster.statusbar.showMessage(f"OCR wiederholt mit {name}: nicht besser, Text bleibt", 6000)

    # --- Handschrift mit KI entziffern --------------------------------------

    def handschrift(self, pdf_path: Path):
        """Kontextmenue "Handschrift mit KI entziffern (Bilderkennung)"."""
        fenster = self.fenster
        provider, grund = handschrift_ki.vision_bereit(fenster.hybrid_classifier)
        if provider is None:
            if zeige_vision_hilfe(fenster, grund):
                fenster._open_settings_dialog(tab=KI_TAB)
            return
        if self._beschaeftigt():
            return
        try:
            gesamt = _seitenzahl(pdf_path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(fenster, "Handschrift mit KI entziffern", f"Die PDF lässt sich nicht lesen: {e}")
            return
        n = min(gesamt, handschrift_ki.MAX_SEITEN)
        hinweis = ""
        if gesamt > n:
            hinweis = f"Die PDF hat {gesamt} Seiten; gelesen werden nur die ersten {n}.\n\n"
        cloud = is_cloud_provider(fenster.config.get("llm", {}).get("provider", "none"))
        if cloud:
            wer = fenster.hybrid_classifier.get_llm_provider_name()
            antwort = QMessageBox.question(
                fenster, "Seitenbilder hochladen?",
                f"{hinweis}Die Bilder von {n} Seite(n) werden an {wer} hochgeladen. "
                "Dabei können Kosten entstehen.\n\nFortfahren?")
            if antwort != QMessageBox.StandardButton.Yes:
                return
        elif hinweis:
            QMessageBox.information(fenster, "Handschrift mit KI entziffern", hinweis.strip())
        worker = HandschriftWorker(pdf_path, provider, fenster)
        worker.fortschritt.connect(
            lambda nr, anzahl: fenster.statusbar.showMessage(f"Handschrift entziffern: Seite {nr}/{anzahl}…"))
        worker.fertig.connect(lambda erg, p=pdf_path: self._handschrift_fertig(p, erg))
        self._start(worker, pdf_path, f"Handschrift entziffern: {pdf_path.name}…")

    def _handschrift_fertig(self, pdf_path: Path, erg: dict):
        self._ende()
        fenster = self.fenster
        titel = "Handschrift mit KI entziffern"
        texte = erg.get("texte") or {}
        if erg.get("fehler") and not texte:
            QMessageBox.warning(fenster, titel, f"Die KI konnte die Seiten nicht lesen:\n\n{erg['fehler']}")
            return
        if not texte:
            QMessageBox.information(fenster, titel, "Die KI hat keinen Text erkannt.")
            return
        hinweis = f"{pdf_path.name}: {len(texte)} Seite(n) entziffert."
        if erg.get("gekuerzt"):
            hinweis += f" Die PDF hat {erg['gesamt']} Seiten, gelesen wurden nur die ersten {handschrift_ki.MAX_SEITEN}."
        if erg.get("fehler"):
            hinweis += f"\nAbgebrochen: {erg['fehler']}"
        dialog = HandschriftErgebnisDialog(texte, hinweis, fenster)
        dialog.exec()
        if dialog.uebernehmen:
            self._uebernehmen(pdf_path, texte)

    def _uebernehmen(self, pdf_path: Path, texte: dict):
        """Entzifferten Text als OCR-Text speichern; vorhandenen Text nur nach Rueckfrage ersetzen."""
        fenster = self.fenster
        titel = "Als Text übernehmen"
        if handschrift_ki.vorhandener_text(pdf_path, texte.keys()):
            antwort = QMessageBox.question(
                fenster, titel,
                "Für diese Seiten ist schon Text gespeichert. Er wird durch den entzifferten Text ersetzt.\n\n"
                "Ersetzen?")
            if antwort != QMessageBox.StandardButton.Yes:
                return
        erg = handschrift_ki.text_uebernehmen(pdf_path, texte)
        if erg.get("fehler"):
            QMessageBox.warning(fenster, titel, erg["fehler"])
        elif not erg.get("index"):
            QMessageBox.information(
                fenster, titel,
                "Der Text wird im Suchindex gespeichert, und der ist nicht eingerichtet. "
                "Richten Sie die Suche in den Einstellungen ein.")
        else:
            self._text_neu_laden(pdf_path)
            widget = fenster._pdf_widget_for(pdf_path)
            if widget is not None:
                widget.ocr_schlecht = False
            fenster.statusbar.showMessage(f"Entzifferter Text gespeichert ({erg.get('seiten', 0)} Seite(n))", 6000)


def _prozent(wert) -> str:
    return f"{round(100 * wert[1] / wert[0])} %" if wert and wert[0] else "unbekannt"


def _vergleich(erg: dict) -> str:
    """" (sicher erkannte Zeichen: 80 % statt 35 %)" für die Meldung; leer ohne Messwerte."""
    if not erg.get("nachher"):
        return ""
    return f" (sicher erkannte Zeichen: {_prozent(erg['nachher'])} statt {_prozent(erg.get('vorher'))})"


def _seitenzahl(pdf_path: Path) -> int:
    import pymupdf
    doc = pymupdf.open(str(pdf_path))
    try:
        return doc.page_count
    finally:
        doc.close()

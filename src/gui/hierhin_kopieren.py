"""
"Hierhin kopieren" (Issue #179)

Eine Datei wird in einen Ordner KOPIERT statt verschoben: Rechtsklick auf einen
Ordner (Vorschlags- und Zielordner-Kachel, Ordnerzeile, Baum, Favorit) oder
Strg (macOS: Wahltaste) beim Ziehen. Das Original im Eingangsordner bleibt
unveraendert, die Kopie bekommt Namen und Metadaten wie beim Verschieben.

Dieses Modul enthaelt die Hilfen fuer die Ordner-Widgets (Menueeintrag, Drop-Aktion)
und den :class:`HierhinKopierenMixin` fuer das Hauptfenster. Der Mixin haelt auch
den gemeinsamen Kern fuer Verschieben und Kopieren (Namensbildung und Lernen),
damit beide Wege dieselben Lernvorgaenge nutzen.

GPL-3.0-or-later - Copyright (c) 2026
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMenu, QMessageBox

from src.core.folder_naming import DEFAULT_TEMPLATE, build_folder_based_name, coerce_date
from src.core.office_convert import endung_tauschen, ist_office_datei

NICHTS_AUSGEWAEHLT_TIP = "In der PDF-Ansicht ist keine Datei ausgewählt"

# Mime-Typ beim Ziehen einer Ordnerzeile (Issue #196); bewusst ohne URLs, damit andere
# Programme den Ordner nicht selbst verschieben
ORDNER_MIME = "application/x-pdfsm-ordner"


def ordner_aus_mime(mime) -> Optional[Path]:
    """Der gezogene Ordner (Issue #196) oder None, wenn es keine Ordnerzeile ist."""
    if mime is None or not mime.hasFormat(ORDNER_MIME):
        return None
    text = bytes(mime.data(ORDNER_MIME)).decode("utf-8", "replace")
    return Path(text) if text else None


def _aktions_text(dateien: list[Path], symbol: str, verb: str) -> str:
    if len(dateien) == 1 and Path(dateien[0]).is_dir():  # markierter Ordner (Issue #196)
        return f"📁 Ordner hierhin {verb}"
    if len(dateien) > 1:
        return f"{symbol} {len(dateien)} Dateien hierhin {verb}"
    if len(dateien) == 1 and ist_office_datei(dateien[0]):
        return f"{symbol} Datei hierhin {verb}"
    return f"{symbol} PDF hierhin {verb}"


def kopier_text(dateien: list[Path]) -> str:
    """Text des Menueeintrags passend zur Auswahl."""
    return _aktions_text(dateien, "📄", "kopieren")


def verschieben_text(dateien: list[Path]) -> str:
    """Text des Eintrags "Hierhin verschieben" (Issue #183)."""
    return _aktions_text(dateien, "➡", "verschieben")


def _auswahl_eintrag(menu, auswahl, anfordern, text_fn):
    dateien = list(auswahl() or []) if auswahl else []
    aktion = menu.addAction(text_fn(dateien))
    aktion.setEnabled(bool(dateien))
    if not dateien:
        aktion.setToolTip(NICHTS_AUSGEWAEHLT_TIP)
    aktion.triggered.connect(lambda: anfordern())
    return aktion


def kopier_eintrag(menu: QMenu, auswahl: Optional[Callable[[], list]], anfordern: Callable[[], None]):
    """Haengt den Eintrag "Hierhin kopieren" an ``menu``; aktiv nur bei ausgewaehlter Datei.

    ``auswahl`` liefert die aktuell ausgewaehlten Dateien (das Hauptfenster setzt
    sie), ``anfordern`` wird beim Anklicken aufgerufen.
    """
    return _auswahl_eintrag(menu, auswahl, anfordern, kopier_text)


def verschieben_eintrag(menu: QMenu, auswahl: Optional[Callable[[], list]], anfordern: Callable[[], None]):
    """Haengt den Eintrag "Hierhin verschieben" an ``menu`` (Issue #183), sonst wie ``kopier_eintrag``."""
    return _auswahl_eintrag(menu, auswahl, anfordern, verschieben_text)


def ist_kopier_drop(event) -> bool:
    """True, wenn beim Ziehen kopiert werden soll (Strg; auf macOS Wahltaste).

    Bewusst nur die Modifikatortaste, nicht die vorgeschlagene Aktion: Ziehen
    aus anderen Programmen schlaegt je nach Laufwerk selbst "Kopieren" vor,
    das soll das gewohnte Verschieben nicht veraendern.
    """
    taste = (
        Qt.KeyboardModifier.AltModifier if sys.platform == "darwin"
        else Qt.KeyboardModifier.ControlModifier
    )
    modifiers = getattr(event, "modifiers", None)
    return bool(modifiers and modifiers() & taste)


def drop_aktion_setzen(event) -> bool:
    """Nimmt ein Drag-Ereignis an: mit Strg als Kopieraktion (Cursor), sonst unveraendert.

    Gibt zurueck, ob kopiert wird.
    """
    kopieren = ist_kopier_drop(event)
    if kopieren:
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
    else:
        event.acceptProposedAction()
    return kopieren


@dataclass
class AblageNamen:
    """Name, Metadaten und Lern-Kennung einer Ablage (Verschieben oder Kopieren)."""

    new_name: Optional[str]  # None = Originalname behalten
    name_changed: bool
    learned_name: Optional[str]
    folder_naming_applied: bool
    metadata: dict
    office_ext: Optional[str]
    dokument_id: tuple = field(default_factory=tuple)  # (Pfad, mtime) des Originals


class HierhinKopierenMixin:
    """Kopieren ins Ziel und der gemeinsame Kern (Namen, Lernen) fuer Verschieben und Kopieren."""

    # --- gemeinsamer Kern (auch von _move_rename_and_learn genutzt) ----------

    def _ablage_namen(
        self,
        pdf_path: Path,
        folder_path: Optional[Path],
        relative_path: str,
        vorbelegung: Optional[tuple[Optional[str], dict]] = None,
        dates: Optional[list] = None,
    ) -> AblageNamen:
        """Name und Metadaten aus dem Detail-Panel (und ggf. Ordner-Namensschema, Issue #42).

        ``vorbelegung`` (Stapel-Ablage, Issue #218): (Name, Metadaten), die das Panel
        dieser Datei vorbelegen wuerde, mit ``dates`` = erkannte Daten dieser Datei.
        Gilt nur, wenn das Panel gerade eine andere Datei zeigt - was dort steht (auch
        von Hand geaendert), hat Vorrang. Ohne ``folder_path`` (Umbenennen am Platz)
        bleibt das Ordner-Namensschema aus.
        """
        from src.gui.main_window import _iso_to_date

        # Namen und Metadaten nur aus dem Panel, wenn es DIESE Datei zeigt (Reiterwechsel, noch
        # laufende Analyse): sonst gingen die Felder eines anderen Dokuments an die falsche Datei
        if self.detail_panel.get_current_pdf() == pdf_path:
            new_name = self.detail_panel.get_new_name()
            metadata = self.detail_panel.get_metadata()
            dates = self.selected_pdf_dates
        elif vorbelegung is not None:
            new_name, metadata = vorbelegung[0], dict(vorbelegung[1] or {})
        else:
            new_name, metadata = None, {}
            dates = self.selected_pdf_dates
        # .docx/.xlsx behalten beim Umbenennen ihre Endung (der Name kommt mit ".pdf")
        office_ext = pdf_path.suffix.lower() if ist_office_datei(pdf_path) else None
        if office_ext and new_name:
            new_name = endung_tauschen(new_name, office_ext)

        # Der vom Nutzer gewaehlte/korrigierte Name ist das, was die KI
        # kuenftig liefern soll - nur er geht als Beispiel in die Historie.
        # Das Ordner-Praefix (#42) kommt beim Ablegen dazu und wuerde
        # die KI sonst dazu verleiten, selbst Ordnernummern zu erfinden.
        learned_name = new_name
        folder_naming_applied = False

        # Dateiname aus Ordnerstruktur aufbauen (Issue #42, Opt-in)
        if folder_path is not None and self.config.get("folder_naming_enabled", False):
            folder_naming_applied = True
            # Datum aus dem Feld "Datum" des Detail-Panels (Issue #132),
            # sonst das erkannte Datum der Analyse
            fallback_date = _iso_to_date(metadata.get("buchungsdatum") if metadata else None)
            if fallback_date is None and dates:
                fallback_date = coerce_date(dates[0])
            basis_name = new_name or pdf_path.name
            if office_ext:
                basis_name = basis_name[: -len(office_ext)] if basis_name.lower().endswith(office_ext) else basis_name
            new_name = build_folder_based_name(
                basis_name,
                folder_path,
                relative_path,
                template=self.config.get("folder_naming_template", "") or DEFAULT_TEMPLATE,
                initials=self.config.get("owner_initials", ""),
                fallback_date=fallback_date,
            )
            if office_ext:
                new_name = endung_tauschen(new_name, office_ext)

        name_changed = bool(new_name and new_name != pdf_path.name)
        dokument_id = self._dokument_id(pdf_path)
        return AblageNamen(
            new_name=new_name if name_changed else None,
            name_changed=name_changed,
            learned_name=learned_name,
            folder_naming_applied=folder_naming_applied,
            metadata=metadata,
            office_ext=office_ext,
            dokument_id=dokument_id,
        )

    def _aus_ablage_lernen(
        self,
        pdf_path: Path,
        folder_path: Path,
        relative_path: str,
        new_path: Path,
        namen: AblageNamen,
        text: Optional[str],
        keywords: Optional[list],
        dates: Optional[list] = None,
    ) -> None:
        """Lernt aus einer Ablage: Klassifikator, Umbenennung, Korrespondent.

        Gilt fuer Verschieben und Kopieren gleichermassen. Derselbe Lernvorgang
        (gleiches Dokument, gleicher Zielordner) wird je Sitzung nur einmal
        gezaehlt: Kopieren und spaeteres Verschieben in denselben Ordner zaehlt
        also nicht doppelt, ein Verschieben in einen anderen Ordner lernt
        dagegen wie gewohnt (das Dokument gehoert dann auch dorthin).
        """
        gelernt = self.__dict__.setdefault("_gelernte_ablagen", set())
        metadata = namen.metadata

        def neu(schluessel: tuple) -> bool:
            if schluessel in gelernt:
                return False
            gelernt.add(schluessel)
            return True

        # Korrespondent-Zuordnung lernen
        if metadata and metadata.get("korrespondent"):
            if neu(("korrespondent", namen.dokument_id, metadata["korrespondent"])):
                self.db.learn_korrespondent_metadata(metadata["korrespondent"], metadata)

        # Aus der Entscheidung lernen
        if text and neu(("sortierung", namen.dokument_id, str(folder_path))):
            self.classifier.learn(
                pdf_path=pdf_path,
                target_folder=folder_path,
                extracted_text=text,
                keywords=keywords,
                relative_path=relative_path,
            )

        # Umbenennung lernen (falls Name geaendert)
        if namen.name_changed:
            # Vom Nutzer bestaetigtes/korrigiertes Datum (Issue #132) vor dem erkannten
            detected_date = metadata.get("buchungsdatum") if metadata else None
            if not detected_date and dates:
                try:
                    d = dates[0]
                    detected_date = d.strftime("%Y-%m-%d") if hasattr(d, 'strftime') else str(d)
                except Exception:
                    pass
            history_name = (
                namen.learned_name
                if namen.folder_naming_applied and namen.learned_name
                else new_path.name
            )
            # Schluessel mit dem gewuenschten Namen: ein "(1)" bei Namenskonflikt ist kein neuer Lernvorgang
            if history_name != pdf_path.name and neu(("umbenennung", namen.dokument_id, namen.new_name)):
                self.db.add_rename_entry(
                    original_filename=pdf_path.name,
                    new_filename=history_name,
                    extracted_text=text,
                    keywords=keywords,
                    detected_date=detected_date,
                    target_folder=str(folder_path),
                )

    # --- Auswahl und Anbindung der Ordner-Widgets -----------------------------

    def kopier_auswahl(self) -> list[Path]:
        """Die Dateien, auf die "Hierhin kopieren" wirkt: die aktuelle Auswahl der PDF-Ansicht.

        Ist links ein Ordner markiert (Issue #196), ist es dieser Ordner.
        """
        if getattr(self, "_markierter_ordner", None) is not None:
            return [self._markierter_ordner]
        if len(self.selected_pdfs) > 1:
            return list(self.selected_pdfs)
        if self.selected_pdf:
            return [self.selected_pdf]
        return list(self.selected_pdfs)

    def verbinde_hierhin_kopieren(self, widget) -> None:
        """Verdrahtet ein Ordner-Widget (Menueeintrag und Strg-Drop) mit dem Hauptfenster."""
        widget.auswahl_pruefer = self.kopier_auswahl
        widget.copy_here_requested.connect(self.on_copy_here_requested)
        signal = getattr(widget, "pdf_copy_dropped", None)
        if signal is not None:
            signal.connect(self.on_pdfs_copy_dropped_on_folder)

    def verbinde_ordnerzeile(self, zeile) -> None:
        """Zusatzeintraege der Ordnerzeilen links (Issue #183): verschieben, im Baum zeigen, Zielordner."""
        zeile.move_here_requested.connect(self.on_tree_folder_selected)  # wie Klick auf einen Vorschlag
        zeile.show_in_tree_requested.connect(self.on_show_in_tree_requested)
        zeile.target_toggle_requested.connect(self.on_target_toggle_requested)
        zeile.ziel_pruefer = lambda p: Path(p) in self.config.get_target_folders()

    def on_show_in_tree_requested(self, folder_path: Path) -> None:
        """"Rechts im Baum zeigen": aufklappen, markieren, hinscrollen (ohne zu verschieben)."""
        if not self.folder_tree.reveal_folder(Path(folder_path)):
            self.statusbar.showMessage(
                f"'{Path(folder_path).name}' liegt außerhalb der Zielordner rechts", 4000
            )

    def on_target_toggle_requested(self, folder_path: Path) -> None:
        """"Als Zielordner merken" bzw. "Aus Zielliste entfernen" (wie die bestehenden Wege)."""
        folder_path = Path(folder_path)
        if folder_path in self.config.get_target_folders():
            self.on_folder_remove(folder_path)
            return
        self.config.add_target_folder(folder_path)
        self.folder_manager.add_folder(folder_path)
        self.load_folders()
        self.statusbar.showMessage(f"Zielordner hinzugefügt: {folder_path.name}", 3000)

    def on_copy_here_requested(self, folder_path: Path) -> None:
        """Menue "Hierhin kopieren": kopiert die aktuelle Auswahl in den Ordner."""
        if getattr(self, "_markierter_ordner", None) is not None:
            self.ordner_uebertragen(self._markierter_ordner, Path(folder_path), kopieren=True)  # Issue #196
            return
        dateien = self.kopier_auswahl()
        if not dateien:
            self.statusbar.showMessage("Zum Kopieren zuerst eine Datei auswählen", 3000)
            return
        self._kopiere_dateien(dateien, Path(folder_path))

    def on_pdfs_copy_dropped_on_folder(self, dateien: list, folder_path: Path) -> None:
        """Strg+Drop auf einen Ordner: kopiert genau die gezogenen Dateien."""
        self._kopiere_dateien([Path(d) for d in dateien], Path(folder_path))

    # --- Kopieren -------------------------------------------------------------

    def _kopiere_dateien(self, dateien: list[Path], folder_path: Path) -> list[Path]:
        """Kopiert ``dateien`` nach ``folder_path``; das Original wird nie veraendert.

        Eine einzelne, ausgewaehlte Datei bekommt Namen und Metadaten aus dem
        Detail-Panel (wie beim Verschieben). Mehrere Dateien werden unter ihrem
        Namen kopiert. Gelernt wird in beiden Faellen.
        """
        relative_path = self.folder_tree.get_relative_path(folder_path)
        mit_panel = len(dateien) == 1 and dateien[0] == self.selected_pdf

        # Neuer Ordner (Issue #116): wie beim Verschieben nach Rueckfrage anlegen
        angelegt: list[Path] = []
        if not folder_path.exists():
            from src.core import neuer_ordner

            wer = f"{len(dateien)} Dateien" if len(dateien) > 1 else "Datei"
            antwort = QMessageBox.question(
                self, "Neuen Ordner anlegen",
                f"Ordner '{relative_path}' anlegen und {wer} dorthin kopieren?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if antwort != QMessageBox.StandardButton.Yes:
                return []
            try:
                angelegt = neuer_ordner.anlegen(folder_path)
            except OSError as e:
                QMessageBox.critical(self, "Fehler", f"Ordner konnte nicht angelegt werden:\n{e}")
                return []
            self._invalidate_folder_caches()

        kopien: list[tuple[Path, Path]] = []
        fehler: list[str] = []

        for pdf_path in dateien:
            try:
                if mit_panel:
                    neu_pfad = self._kopiere_mit_panel(pdf_path, folder_path, relative_path)
                else:
                    neu_pfad = self._kopiere_schlicht(pdf_path, folder_path, relative_path)
                kopien.append((pdf_path, neu_pfad))
            except Exception as e:
                fehler.append(f"{pdf_path.name}: {e}")

        if fehler:
            QMessageBox.warning(
                self,
                "Kopieren fehlgeschlagen" if not kopien else "Teilweise fehlgeschlagen",
                "Einige Dateien konnten nicht kopiert werden:\n" + "\n".join(fehler),
            )
        if not kopien:
            if angelegt:  # nichts kopiert: den neuen Ordner nicht leer liegen lassen
                from src.core import neuer_ordner

                neuer_ordner.leere_wegraeumen(angelegt)
                self._invalidate_folder_caches()
            return []

        self.training_label.setText(f"Gelernt: {self.classifier.get_training_count()}")
        suffix = f" ({len(kopien)} Dateien)" if len(kopien) > 1 else ""
        self.statusbar.showMessage(f"Kopiert nach '{relative_path}'{suffix}", 3000)

        for original, _kopie in kopien:
            self._kopie_hinweis_merken(original, folder_path)
        self.config.add_to_last_used(folder_path)
        self._refresh_after_move(folder_path)
        self._auto_collect_korrespondenten()
        return [k for _o, k in kopien]

    def _kopiere_mit_panel(self, pdf_path: Path, folder_path: Path, relative_path: str) -> Path:
        """Kopie der ausgewaehlten Datei mit Namen und Metadaten aus dem Detail-Panel."""
        namen = self._ablage_namen(pdf_path, folder_path, relative_path)
        new_path = self.file_manager.copy_file(pdf_path, folder_path, new_name=namen.new_name)

        metadata = namen.metadata
        # Erst die Kopie aufnehmen, dann den Hintergrund-Schreiber starten: beide legen
        # sonst gleichzeitig den Eintrag der Kopie in ``pdfs`` an (UNIQUE-Fehler)
        self._kopie_indexieren(
            new_path, relative_path, self.selected_pdf_text, self.selected_pdf_keywords, metadata
        )
        # Metadaten gehen nur in die KOPIE (das Original bleibt unveraendert);
        # in .docx/.xlsx schreiben wir keine PDF-Metadaten
        if metadata and not namen.office_ext:
            self._write_pdf_metadata_async(new_path, new_path.name, self.selected_pdf_keywords, metadata)

        self._aus_ablage_lernen(
            pdf_path, folder_path, relative_path, new_path, namen,
            text=self.selected_pdf_text,
            keywords=self.selected_pdf_keywords,
            dates=self.selected_pdf_dates,
        )
        return new_path

    def _kopiere_schlicht(self, pdf_path: Path, folder_path: Path, relative_path: str) -> Path:
        """Kopie unter dem Originalnamen; gelernt wird aus dem Analyse-Cache, falls vorhanden."""
        new_path = self.file_manager.copy_file(pdf_path, folder_path)
        cached = self.pdf_cache.get(pdf_path)
        text = cached.extracted_text if cached else None
        keywords = cached.keywords if cached else None
        namen = AblageNamen(
            new_name=None, name_changed=False, learned_name=None, folder_naming_applied=False,
            metadata={}, office_ext=None, dokument_id=self._dokument_id(pdf_path),
        )
        self._aus_ablage_lernen(pdf_path, folder_path, relative_path, new_path, namen, text, keywords)
        self._kopie_indexieren(new_path, relative_path, text, keywords, {})
        return new_path

    @staticmethod
    def _dokument_id(pdf_path: Path) -> tuple:
        try:
            return (str(pdf_path), pdf_path.stat().st_mtime_ns)
        except OSError:
            return (str(pdf_path), None)

    def _kopie_indexieren(self, new_path: Path, relative_path: str, text, keywords, metadata) -> None:
        """Nimmt die Kopie als eigenes Dokument auf (der Eintrag des Originals bleibt)."""
        metadata = metadata or {}
        self.db.kopie_aufnehmen(
            new_path=str(new_path),
            filename=new_path.name,
            extracted_text=text or "",
            keywords=", ".join(keywords) if keywords else "",
            korrespondent=metadata.get("korrespondent", ""),
            kategorie=metadata.get("subject", ""),
            steuerjahr=metadata.get("steuerjahr", ""),
            betrag=metadata.get("betrag", ""),
            zusammenfassung=metadata.get("description", ""),
        )

    # --- Hinweis "kopiert nach ..." auf der Kachel (nur im Speicher) -----------

    def _kopie_hinweis_merken(self, original: Path, folder_path: Path) -> None:
        ordner = self.__dict__.setdefault("_kopie_hinweise", {}).setdefault(Path(original), [])
        if folder_path not in ordner:
            ordner.append(folder_path)
        for widget in self.pdf_widgets:
            if widget.pdf_path == original:
                self._kopie_hinweis_anwenden(widget)

    def _kopie_hinweis_anwenden(self, widget) -> None:
        """Zeigt den Hinweis auf einer (neu erzeugten) Kachel, falls sie kopiert wurde."""
        ordner = self.__dict__.get("_kopie_hinweise", {}).get(Path(widget.pdf_path))
        if not ordner:
            return
        text = f"📄 kopiert nach {ordner[-1].name or str(ordner[-1])}"
        if len(ordner) > 1:
            text += f" (+{len(ordner) - 1})"
        kurz = f"📄 → {ordner[-1].name or str(ordner[-1])}"
        widget.set_kopie_hinweis(text, "\n".join(f"Kopiert nach {p}" for p in ordner), kurz)

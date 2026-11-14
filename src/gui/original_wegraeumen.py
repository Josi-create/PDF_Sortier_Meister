"""Original nach dem Umwandeln oder Trennen in den Papierkorb (Issues #184, #187).

Nach einer erfolgreichen Umwandlung (Word/Excel/Bild -> PDF) oder dem Trennen
eines PDFs fragt ein Dialog, ob das Original in den Papierkorb soll. Mit dem
Haekchen "Nicht mehr fragen" merkt sich das Programm die Antwort je Aktion in
der Config (``original_wegraeumen``: ``{"umwandeln": true|false|null,
"trennen": ...}``; ``null`` = fragen). Eingestellt wird das unter
Einstellungen > Allgemein.

Geloescht wird ueber den vorhandenen Papierkorb-Weg (Issue #124,
``FileManager.delete_file``); nie endgueltig. Alle Originale einer Aktion
stehen in *einem* Eintrag des Rueckgaengig-Stapels (Typ ``wegraeumen``), ein
Strg+Z holt alle zurueck.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QCheckBox, QMessageBox

from src.core.file_manager import PapierkorbNichtVerfuegbar
from src.search.meldungen import melden as index_melden
from src.i18n import tr

CONFIG_SCHLUESSEL = "original_wegraeumen"
AKTIONEN = {
    "umwandeln": tr("Nach dem Umwandeln in PDF"),
    "trennen": tr("Nach dem Trennen eines PDFs"),
    "zusammenfuegen": tr("Nach dem Zusammenfügen von PDFs"),
    "entsperren": tr("Nach dem Entfernen des Passwortschutzes"),  # Issue #244
}
HINWEIS = tr("Mit Strg+Z holst du es zurück.")


def gespeicherte_antwort(config, aktion: str) -> Optional[bool]:
    """True = Papierkorb, False = behalten, None = fragen."""
    werte = config.get(CONFIG_SCHLUESSEL) or {}
    wert = werte.get(aktion) if isinstance(werte, dict) else None
    return wert if isinstance(wert, bool) else None


def antwort_speichern(config, aktion: str, wert: Optional[bool]) -> None:
    werte = config.get(CONFIG_SCHLUESSEL)
    werte = dict(werte) if isinstance(werte, dict) else {}
    werte[aktion] = wert
    config.set(CONFIG_SCHLUESSEL, werte)


class OriginalFragenDialog(QMessageBox):
    """"Original in den Papierkorb verschieben?" - Standardknopf Ja, Haekchen "Nicht mehr fragen"."""

    def __init__(self, parent, text: str):
        super().__init__(parent)
        self.setWindowTitle(tr("Original wegräumen"))
        self.setIcon(QMessageBox.Icon.Question)
        self.setText(text)
        self.setInformativeText(HINWEIS)
        self.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        self.setDefaultButton(QMessageBox.StandardButton.Yes)
        self.nicht_mehr_fragen = QCheckBox(tr("Nicht mehr fragen"))
        self.setCheckBox(self.nicht_mehr_fragen)


def _frage(parent, text: str) -> tuple[bool, bool]:
    """Zeigt den Dialog: ``(Ja?, Nicht mehr fragen?)``. Tests ersetzen diese Funktion."""
    dialog = OriginalFragenDialog(parent, text)
    ja = dialog.exec() == QMessageBox.StandardButton.Yes
    return ja, dialog.nicht_mehr_fragen.isChecked()


def soll_wegraeumen(parent, config, aktion: str, text: str) -> bool:
    """Gespeicherte Antwort oder Dialog; merkt die Antwort bei gesetztem Haekchen."""
    gespeichert = gespeicherte_antwort(config, aktion)
    if gespeichert is not None:
        return gespeichert
    ja, merken = _frage(parent, text)
    if merken:
        antwort_speichern(config, aktion, ja)
    return ja


def original_wegraeumen(mw, pfade: list[Path], aktion: str, text: str, beschreibung: str) -> list[Path]:
    """Fragt (falls noetig) und verschiebt die Originale in den Papierkorb; Rueckgabe: wirklich entfernte.

    ``mw``: das Hauptfenster (``config``, ``file_manager``, ``statusbar``, Undo-Stapel).
    Ohne verfuegbaren Papierkorb bleiben die Originale liegen (nie endgueltig loeschen).
    """
    pfade = [Path(p) for p in pfade if Path(p).exists()]
    if not pfade or not soll_wegraeumen(mw, mw.config, aktion, text):
        return []
    eintraege: list[tuple[Path, Path]] = []
    fehler: list[str] = []
    for pfad in pfade:
        try:
            papierkorb = mw.file_manager.delete_file(pfad)
        except PapierkorbNichtVerfuegbar:
            fehler.append(tr("{name}: Papierkorb nicht verfügbar - das Original bleibt liegen.").format(name=pfad.name))
            continue
        except Exception as e:  # noqa: BLE001 - je Datei melden
            fehler.append(f"{pfad.name}: {e}")
            continue
        if papierkorb is not None:
            eintraege.append((pfad, papierkorb))
        mw.original_entfernt(pfad)
    entfernt = [o for o, _ in eintraege]
    if eintraege:
        mw._push_undo({"type": "wegraeumen", "eintraege": eintraege, "description": beschreibung})
    if fehler:
        QMessageBox.warning(mw, tr("Original wegräumen"), "\n".join(fehler))
    return entfernt


def rueckgaengig(mw, entry: dict) -> None:
    """Holt alle Originale eines ``wegraeumen``-Eintrags aus dem Papierkorb zurueck."""
    mw._undo_stack.pop()
    mw._update_undo_ui()
    probleme: list[str] = []
    geholt = 0
    for original, papierkorb in entry["eintraege"]:
        original, papierkorb = Path(original), Path(papierkorb)
        if not papierkorb.exists():
            probleme.append(tr("'{name}' ist nicht mehr im Papierkorb.").format(name=original.name))
            continue
        if original.exists():
            probleme.append(tr("Am ursprünglichen Ort existiert bereits eine Datei '{name}'.").format(name=original.name))
            continue
        try:
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(papierkorb), str(original))
        except Exception as e:  # noqa: BLE001
            probleme.append(f"{original.name}: {e}")
            continue
        index_melden("datei_aufnehmen", str(original))
        geholt += 1
    if probleme:
        QMessageBox.warning(mw, tr("Rückgängig nicht (ganz) möglich"), "\n".join(probleme))
    if geholt:
        mw.statusbar.showMessage(tr("Rückgängig: {description}").format(description=entry['description']), 3000)
        mw.refresh_view()

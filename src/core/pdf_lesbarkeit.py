"""Ist eine Datei als PDF lesbar? Und wenn nicht: warum, in Worten fuer Anwender (Issue #414).

Eine Pruefung fuer Kachel, Trennen, Stapeln, Zusammenfuegen, Seiten bearbeiten und Ablegen:
leer, keine PDF, beschaedigt, passwortgeschuetzt oder gar nicht zu lesen. Repariert nichts.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.i18n import tr

LEER = "leer"
KEINE_PDF = "keine_pdf"
BESCHAEDIGT = "beschaedigt"
GESCHUETZT = "geschuetzt"
NICHT_LESBAR = "nicht_lesbar"  # Datei fehlt, gesperrt, keine Rechte

# So weit vorn muss "%PDF" stehen (PDF-Leser dulden etwas Muell davor)
_KOPF_BYTES = 1024


@dataclass(frozen=True)
class Lesefehler:
    """Warum eine Datei nicht als PDF gelesen werden kann."""

    art: str
    technisch: str = ""  # Text der Bibliothek bzw. des Systems (fuer Tooltip und Fehlersuche)

    @property
    def kurz(self) -> str:
        """Ein bis zwei Woerter fuer die Kachel."""
        return {
            LEER: tr("Leere Datei"),
            KEINE_PDF: tr("Keine PDF"),
            BESCHAEDIGT: tr("Beschädigt"),
            GESCHUETZT: tr("Passwortgeschützt"),
        }.get(self.art, tr("Nicht lesbar"))

    def grund(self) -> str:
        """Ein Halbsatz ohne Dateinamen, z. B. fuer die Statusleiste."""
        return {
            LEER: tr("die Datei ist leer"),
            KEINE_PDF: tr("die Datei ist keine PDF"),
            BESCHAEDIGT: tr("die Datei ist beschädigt"),
            GESCHUETZT: tr("die Datei ist passwortgeschützt"),
        }.get(self.art, tr("die Datei lässt sich nicht lesen"))

    def satz(self, name: str) -> str:
        """Ganzer Satz mit Dateinamen und dem, was man tun kann."""
        if self.art == LEER:
            return tr("„{name}“ ist leer (0 Byte). Vielleicht wird sie gerade noch geschrieben "
                      "oder der Scan ist fehlgeschlagen.").format(name=name)
        if self.art == KEINE_PDF:
            return tr("„{name}“ ist keine PDF, auch wenn der Name auf .pdf endet.").format(name=name)
        if self.art == BESCHAEDIGT:
            return tr("„{name}“ ist beschädigt und lässt sich nicht als PDF lesen.").format(name=name)
        if self.art == GESCHUETZT:
            return tr("„{name}“ ist passwortgeschützt. Rechtsklick auf die Kachel, "
                      "„Passwortschutz entfernen…“ legt eine Kopie ohne Schutz an.").format(name=name)
        return tr("„{name}“ lässt sich nicht lesen ({technisch}).").format(name=name, technisch=self.technisch)


def pruefen(pfad: Path | str) -> Optional[Lesefehler]:
    """None, wenn die Datei eine lesbare PDF ist; sonst der Grund.

    Oeffnet die Datei und laedt die erste Seite (ohne sie zu zeichnen). Liegt die Datei nur in
    der Cloud (OneDrive), wird sie dabei heruntergeladen - wie bei jeder Bearbeitung.
    """
    pfad = Path(pfad)
    try:
        if pfad.stat().st_size == 0:
            return Lesefehler(LEER)
        with open(pfad, "rb") as f:
            kopf = f.read(_KOPF_BYTES)
    except OSError as e:
        return Lesefehler(NICHT_LESBAR, e.strerror or str(e))
    if b"%PDF" not in kopf:
        return Lesefehler(KEINE_PDF)

    import pymupdf

    try:
        with pymupdf.open(str(pfad)) as doc:
            if doc.needs_pass:
                return Lesefehler(GESCHUETZT)
            if doc.page_count < 1:
                return Lesefehler(BESCHAEDIGT, tr("keine Seiten gefunden"))
            doc.load_page(0)
    except Exception as e:  # noqa: BLE001 - jede Art von Lesefehler der Bibliothek
        return Lesefehler(BESCHAEDIGT, str(e))
    return None

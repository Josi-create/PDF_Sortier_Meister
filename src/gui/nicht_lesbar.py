"""Vor dem Trennen, Stapeln, Zusammenfuegen oder Seiten bearbeiten: sind alle PDFs lesbar? (Issue #414)

Statt eines Fehlerfensters mit englischem Bibliothekstext nach dem Versuch kommt vorher ein Satz,
was mit der Datei los ist, und dass nichts veraendert wurde.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PyQt6.QtWidgets import QMessageBox

from src.core.pdf_lesbarkeit import pruefen
from src.i18n import tr


def melden_falls_nicht_lesbar(parent, titel: str, pfade: Iterable[Path]) -> bool:
    """Prueft die PDFs; ist eine nicht lesbar, erklaert ein Hinweisfenster warum.

    Liefert True, wenn etwas nicht lesbar war (dann soll der Aufrufer abbrechen).
    """
    saetze = []
    for pfad in pfade:
        fehler = pruefen(pfad)
        if fehler is not None:
            saetze.append(fehler.satz(Path(pfad).name))
    if not saetze:
        return False
    QMessageBox.warning(parent, titel, "\n\n".join(saetze) + "\n\n" + tr("Es wurde nichts verändert."))
    return True

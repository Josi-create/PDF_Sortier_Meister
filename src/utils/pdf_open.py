"""
PDF ausserhalb der App oeffnen (Issue #76).

Der Nutzer waehlt in den Einstellungen, was ein Doppelklick auf eine PDF
tut: integrierte Vorschau (Default), Standardprogramm des Systems oder ein
selbst gewaehltes Programm (z.B. PDF-XChange, Acrobat, Browser). Diese
Datei enthaelt nur die Nicht-Qt-Logik fuer die beiden externen Varianten.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from src.utils.platform_paths import open_with_default_app

OPEN_MODE_INTEGRATED = "integrated"
OPEN_MODE_SYSTEM = "system"
OPEN_MODE_CUSTOM = "custom"

# (id, Beschriftung) - Reihenfolge = Reihenfolge in den Einstellungen
OPEN_MODES: list[tuple[str, str]] = [
    (OPEN_MODE_INTEGRATED, "Integrierte Vorschau (schnell, empfohlen)"),
    (OPEN_MODE_SYSTEM, "Standardprogramm des Systems (z. B. Browser oder Acrobat)"),
    (OPEN_MODE_CUSTOM, "Eigenes Programm (z. B. PDF-XChange)"),
]


def normalize_open_mode(mode: str | None) -> str:
    """Unbekannte Werte aus alten Configs auf den Default abbilden."""
    if mode in (OPEN_MODE_INTEGRATED, OPEN_MODE_SYSTEM, OPEN_MODE_CUSTOM):
        return mode
    return OPEN_MODE_INTEGRATED


def build_custom_command(command: str, pdf_path: Path) -> list[str]:
    """Kommandozeile fuer ein eigenes Programm.

    Unter macOS wird ein ``.app``-Bundle ueber ``open -a`` gestartet, sonst
    wird die ausfuehrbare Datei direkt mit dem PDF-Pfad aufgerufen.
    """
    if sys.platform == "darwin" and command.lower().endswith(".app"):
        return ["open", "-a", command, str(pdf_path)]
    return [command, str(pdf_path)]


def open_pdf_externally(pdf_path: Path | str, mode: str = OPEN_MODE_SYSTEM,
                        command: str = "") -> tuple[bool, str]:
    """Oeffnet eine PDF ausserhalb der App.

    Args:
        pdf_path: Pfad zur PDF
        mode: OPEN_MODE_SYSTEM oder OPEN_MODE_CUSTOM (OPEN_MODE_INTEGRATED
              wird wie SYSTEM behandelt - die integrierte Vorschau ist Qt-Sache)
        command: Pfad zum eigenen Programm (nur bei OPEN_MODE_CUSTOM)

    Returns:
        (ok, hinweis) - ``hinweis`` ist leer, wenn alles wie gewuenscht lief,
        sonst eine deutsche Meldung (z.B. Fallback auf das Standardprogramm).
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return False, f"Datei nicht gefunden: {pdf_path}"

    mode = normalize_open_mode(mode)
    if mode == OPEN_MODE_CUSTOM:
        command = (command or "").strip()
        if not command:
            note = "Kein eigenes Programm eingetragen - Standardprogramm verwendet."
        elif not Path(command).exists():
            note = f"Programm nicht gefunden ({command}) - Standardprogramm verwendet."
        else:
            try:
                subprocess.Popen(build_custom_command(command, pdf_path))
                return True, ""
            except OSError as e:
                note = f"Programm konnte nicht gestartet werden ({e}) - Standardprogramm verwendet."
        try:
            open_with_default_app(pdf_path)
        except OSError as e:
            return False, f"{note} Auch das schlug fehl: {e}"
        return True, note

    try:
        open_with_default_app(pdf_path)
    except OSError as e:
        return False, f"Standardprogramm konnte nicht gestartet werden: {e}"
    return True, ""

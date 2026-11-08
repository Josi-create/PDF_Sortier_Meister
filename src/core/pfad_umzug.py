"""Gespeicherte Pfade nachziehen, wenn ein Ordner verschoben oder umbenannt wurde (Issue #196). Qt-frei.

Betroffen ist alles, was einen Ordnerpfad merkt:

* Konfiguration: Zielordner-Liste, "zuletzt verwendet", Favoriten;
* Datenbank: gelernte Zuordnungen des Klassifikators (Sortierhistorie), Zielordner-
  Statistik, Umbenennungshistorie und die ``pdfs``-Tabelle (je Datei);
* Analyse-Cache (Text, Stichwoerter, KI-Vorschlaege je Datei);
* Suchindex: ``datei_verschoben`` je Datei (behaelt Text, OCR und Metadaten).
  Einen Umzug fuer einen ganzen Ordner auf einmal kennt der Index nicht; die
  Meldungen je Datei laufen aber in einer Warteschlange im Hintergrund und
  kosten den Oberflaechen-Thread nichts. Wer den Ordner ausserhalb des Programms
  verschiebt, wird weiterhin vom Watcher bzw. Neuscan nachgezogen.

``umziehen`` kennt die Datei-Paare entweder vom Aufrufer (Verschieben: die
tatsaechlichen Zielnamen, auch mit " (2)") oder liest sie aus dem neuen Ordner
(Umbenennen: die Namen bleiben gleich).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional

from src.search.meldungen import melden as index_melden


def ersetzen(pfad: str | Path, alt: Path | str, neu: Path | str) -> Optional[str]:
    """``pfad`` mit ``neu`` statt ``alt`` als Anfang; None, wenn er nicht unter ``alt`` liegt."""
    p, a, n = str(pfad), str(alt), str(neu)
    if p == a:
        return n
    if p.startswith(a + os.sep):
        return n + p[len(a):]
    return None


def _liste_umziehen(werte: Iterable[str], alt, neu) -> tuple[list[str], list[tuple[str, str]]]:
    """Ersetzt Pfade in einer Liste (Reihenfolge bleibt, Doppelte fallen weg)."""
    ergebnis: list[str] = []
    geaendert: list[tuple[str, str]] = []
    for w in werte:
        neuer = ersetzen(w, alt, neu)
        if neuer is not None:
            geaendert.append((w, neuer))
        wert = neuer if neuer is not None else w
        if wert not in ergebnis:
            ergebnis.append(wert)
    return ergebnis, geaendert


def dateipaare(alt: Path | str, neu: Path | str) -> list[tuple[Path, Path]]:
    """Alle Dateien unter dem NEUEN Ordner als (frueherer Pfad, jetziger Pfad)."""
    alt, neu = Path(alt), Path(neu)
    paare = []
    for wurzel, _dirs, files in os.walk(neu):
        rel = Path(wurzel).relative_to(neu)
        for name in files:
            paare.append((alt / rel / name, Path(wurzel) / name))
    return paare


def umziehen(
    alt: Path | str,
    neu: Path | str,
    config,
    db=None,
    pdf_cache=None,
    paare: Optional[list] = None,
    index_melden_paare: bool = False,
    nur_dateien: bool = False,
) -> dict:
    """Zieht alle gespeicherten Pfade von ``alt`` nach ``neu`` um.

    ``paare``: ``[(alt, neu)]`` je Datei; ``None`` = aus dem neuen Ordner ablesen
    (Umbenennen). ``index_melden_paare`` meldet die Paare zusaetzlich dem
    Suchindex (das Verschieben macht das schon beim Uebertragen). ``nur_dateien``
    laesst Config und die Ordnerpfade in der Datenbank aus (Ordner nur teilweise
    verschoben oder in einen schon vorhandenen Ordner zurueck): dann zaehlen nur
    die Datei-Paare.

    Liefert ``{"ziele": [(alt, neu)], "favoriten": int, "dateien": int}``;
    ``ziele`` sind die geaenderten Zielordner der Config (fuer den FolderManager).
    """
    alt, neu = Path(alt), Path(neu)
    if paare is None:
        paare = dateipaare(alt, neu)

    # Konfiguration
    ziele_geaendert: list = []
    fav_geaendert = 0
    if not nur_dateien:
        ziele_alt = [str(p) for p in config.get_target_folders()]
        ziele_neu, ziele_geaendert = _liste_umziehen(ziele_alt, alt, neu)
        if ziele_geaendert:
            config.set("target_folders", ziele_neu)
        zuletzt = list(config.get("last_used_folders", []) or [])
        zuletzt_neu, zuletzt_geaendert = _liste_umziehen(zuletzt, alt, neu)
        if zuletzt_geaendert:
            config.set("last_used_folders", zuletzt_neu)
        favoriten = list(config.get("favoriten", []) or [])
        for eintrag in favoriten:
            if isinstance(eintrag, dict) and eintrag.get("pfad"):
                neuer = ersetzen(eintrag["pfad"], alt, neu)
                if neuer is not None:
                    eintrag["pfad"] = neuer
                    fav_geaendert += 1
        if fav_geaendert:
            config.set("favoriten", favoriten)

    # Datenbank und Analyse-Cache
    if db is not None:
        if not nur_dateien:
            db.pfade_umziehen(str(alt), str(neu), root_folders=config.get_target_folders())
        db.dateipfade_umziehen(paare)
    if pdf_cache is not None:
        pdf_cache.pfade_umziehen(paare)
    if index_melden_paare:
        for a, n in paare:
            index_melden("datei_verschoben", str(a), str(n))

    return {
        "ziele": [(Path(a), Path(n)) for a, n in ziele_geaendert],
        "favoriten": fav_geaendert,
        "dateien": len(paare),
    }

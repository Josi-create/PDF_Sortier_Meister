"""Ganzen Ordner verschieben oder kopieren (Issue #196). Qt-frei.

Ein Ordner wandert samt Unterordnern und ALLEN Dateien (nicht nur PDFs) unter
einen neuen Elternordner: "Versicherungen" auf "Steuer 2025" ergibt
"Steuer 2025/Versicherungen". Gibt es das Ziel schon, wird zusammengefuehrt:

* gleicher Dateiname, anderer Inhalt: die neue Datei bekommt " (2)" (bzw. die
  naechste freie Nummer) angehaengt;
* gleicher Dateiname, byte-gleicher Inhalt: beim Verschieben wandert die
  Quelldatei in den Papierkorb (``papierkorb``, rueckgaengig machbar), beim
  Kopieren wird sie uebersprungen;
* leer gewordene Quellordner werden beim Verschieben entfernt.

Jede Datei wird einzeln uebertragen (``FileManager._move_with_retry``: Wiederholung
bei Windows-Dateisperre, ueber Laufwerksgrenzen Kopieren plus Loeschen) und dem
Suchindex gemeldet. Das Ergebnis haelt alle Paare fuer ``rueckgaengig``.
"""
from __future__ import annotations

import filecmp
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from src.core.file_manager import FileManager
from src.core.neuer_ordner import leere_wegraeumen
from src.search.meldungen import melden as index_melden

Fortschritt = Callable[[int, int, str], None]


class OrdnerFehler(ValueError):
    """Der Ordner darf nicht dorthin (Meldung ist fuer den Nutzer gedacht)."""


@dataclass
class OrdnerErgebnis:
    """Was beim Uebertragen eines Ordners passiert ist (Grundlage fuer Rueckgaengig)."""

    quelle: Path
    ziel: Path  # der Ordner selbst, z. B. "Steuer 2025/Versicherungen"
    kopiert: bool = False
    dateien: list = field(default_factory=list)  # [(alt, neu)] verschoben bzw. neu kopiert
    identisch: list = field(default_factory=list)  # [(quelldatei, vorhandene, papierkorb|None)]
    neue_ordner: list = field(default_factory=list)  # im Ziel neu angelegt, aussen zuerst
    entfernte_quellordner: list = field(default_factory=list)  # beim Verschieben weggeraeumt
    fehler: list = field(default_factory=list)
    abgebrochen: bool = False

    @property
    def anzahl(self) -> int:
        return len(self.dateien) + len(self.identisch)

    @property
    def etwas_getan(self) -> bool:
        return bool(self.dateien or self.identisch or self.neue_ordner or self.entfernte_quellordner)


def ziel_ordner(quelle: Path | str, ziel_eltern: Path | str) -> Path:
    return Path(ziel_eltern) / Path(quelle).name


def pruefe(quelle: Path | str, ziel_eltern: Path | str) -> Optional[str]:
    """Meldung, warum der Ordner nicht dorthin darf; None, wenn es geht.

    Gesperrt: nicht in sich selbst oder einen eigenen Unterordner, nicht dorthin,
    wo er schon liegt, und nur Ordner (keine Dateien).
    """
    quelle, ziel_eltern = Path(quelle), Path(ziel_eltern)
    if not quelle.is_dir():
        return f"'{quelle.name}' ist kein Ordner."
    if ziel_eltern.exists() and not ziel_eltern.is_dir():
        return f"'{ziel_eltern.name}' ist kein Ordner."
    q = _norm(quelle)
    z = _norm(ziel_eltern)
    if z == q or z.startswith(q + os.sep):
        return "Ein Ordner kann nicht in sich selbst oder einen eigenen Unterordner verschoben werden."
    if _norm(quelle.parent) == z:
        return f"'{quelle.name}' liegt schon in '{ziel_eltern.name}'."
    return None


def _norm(p: Path) -> str:
    return os.path.normcase(os.path.abspath(str(p))).rstrip("\\/")


def freier_name(ziel: Path) -> Path:
    """Zielname mit " (2)", " (3)" ... bis er frei ist (die Nummer beginnt bei 2)."""
    n = 2
    while True:
        kandidat = ziel.with_name(f"{ziel.stem} ({n}){ziel.suffix}")
        if not kandidat.exists():
            return kandidat
        n += 1


def inhalt_zaehlen(quelle: Path) -> tuple[int, int]:
    """(Dateien, Unterordner) unter ``quelle`` rekursiv."""
    dateien = ordner = 0
    for _wurzel, dirs, files in os.walk(quelle):
        ordner += len(dirs)
        dateien += len(files)
    return dateien, ordner


def zusammenfuehren_noetig(quelle: Path | str, ziel_eltern: Path | str) -> bool:
    """True, wenn es den Zielordner (gleichen Namens) schon gibt."""
    return ziel_ordner(quelle, ziel_eltern).exists()


def uebertrage(
    quelle: Path | str,
    ziel_eltern: Path | str,
    kopieren: bool = False,
    papierkorb: Optional[Callable[[Path], Optional[Path]]] = None,
    fortschritt: Optional[Fortschritt] = None,
    abbruch: Optional[Callable[[], bool]] = None,
) -> OrdnerErgebnis:
    """Verschiebt bzw. kopiert ``quelle`` nach ``ziel_eltern/<Name>``.

    ``papierkorb`` legt eine Datei in den Papierkorb und liefert deren Pfad dort
    (``FileManager.delete_file``); ohne ihn wird eine identische Quelldatei beim
    Verschieben endgueltig entfernt - das Hauptfenster uebergibt ihn immer.
    Wirft :class:`OrdnerFehler` bei gesperrtem Ziel; einzelne Dateifehler landen
    in ``fehler`` (die Datei bleibt dann an ihrem Platz).
    """
    quelle, ziel_eltern = Path(quelle), Path(ziel_eltern)
    meldung = pruefe(quelle, ziel_eltern)
    if meldung:
        raise OrdnerFehler(meldung)

    ziel = ziel_ordner(quelle, ziel_eltern)
    erg = OrdnerErgebnis(quelle=quelle, ziel=ziel, kopiert=kopieren)
    gesamt = inhalt_zaehlen(quelle)[0]
    erledigt = 0

    def ordner_anlegen(pfad: Path) -> None:
        fehlend = []
        p = pfad
        while not p.exists():
            fehlend.append(p)
            if p.parent == p:
                break
            p = p.parent
        pfad.mkdir(parents=True, exist_ok=True)
        erg.neue_ordner.extend(reversed(fehlend))

    ordner_anlegen(ziel)
    quell_ordner: list[Path] = []

    for wurzel, dirs, files in os.walk(quelle):
        # Verknuepfungen auf Ordner wie Dateien behandeln (os.walk folgt ihnen nicht)
        for d in list(dirs):
            if os.path.islink(os.path.join(wurzel, d)):
                dirs.remove(d)
                files.append(d)
        wurzel = Path(wurzel)
        rel = wurzel.relative_to(quelle)
        zielverz = ziel / rel
        quell_ordner.append(wurzel)
        try:
            ordner_anlegen(zielverz)
        except OSError as e:
            erg.fehler.append(f"{zielverz}: {e}")
            dirs.clear()
            continue
        for name in sorted(files):
            if abbruch is not None and abbruch():
                erg.abgebrochen = True
                break
            src = wurzel / name
            dst = zielverz / name
            erledigt += 1
            if fortschritt:
                fortschritt(erledigt, gesamt, name)
            try:
                _datei_uebertragen(src, dst, kopieren, papierkorb, erg)
            except Exception as e:  # noqa: BLE001 - eine Datei darf den Rest nicht stoppen
                erg.fehler.append(f"{src.name}: {e}")
        if erg.abgebrochen:
            break

    if not kopieren:
        # Leer gewordene Quellordner entfernen, innen zuerst
        for p in sorted(quell_ordner, key=lambda x: len(x.parts), reverse=True):
            try:
                if p.is_dir() and not any(p.iterdir()):
                    p.rmdir()
                    erg.entfernte_quellordner.append(p)
            except OSError:
                continue
    return erg


def _datei_uebertragen(src: Path, dst: Path, kopieren: bool, papierkorb, erg: OrdnerErgebnis) -> None:
    if os.path.lexists(dst):
        if (not src.is_symlink() and not dst.is_symlink() and dst.is_file()
                and filecmp.cmp(str(src), str(dst), shallow=False)):
            if kopieren:
                erg.identisch.append((src, dst, None))
                return
            ablage = papierkorb(src) if papierkorb is not None else _loeschen(src)
            erg.identisch.append((src, dst, ablage))
            return
        dst = freier_name(dst)
    if kopieren:
        shutil.copy2(str(src), str(dst))
        index_melden("datei_aufnehmen", str(dst))
    else:
        FileManager._move_with_retry(src, dst)
        index_melden("datei_verschoben", str(src), str(dst))
    erg.dateien.append((src, dst))


def _loeschen(src: Path) -> None:
    src.unlink()
    index_melden("datei_geloescht", str(src))
    return None


def rueckgaengig(
    erg: OrdnerErgebnis,
    papierkorb: Callable[[Path], Optional[Path]],
) -> list[str]:
    """Macht :func:`uebertrage` rueckgaengig; liefert die Probleme (leer = alles gut).

    Verschieben: jede Datei zurueck an ihren Platz, identische Quelldateien aus dem
    Papierkorb holen, weggeraeumte Quellordner wieder anlegen, neu angelegte
    Zielordner entfernen (wenn leer). Kopieren: die Kopien in den Papierkorb,
    neu angelegte Ordner entfernen (wenn leer). Vorhandene Dateien im Ziel bleiben unberuehrt.
    """
    probleme: list[str] = []
    if erg.kopiert:
        for _alt, neu in reversed(erg.dateien):
            try:
                if Path(neu).exists():
                    papierkorb(Path(neu))
            except Exception as e:  # noqa: BLE001
                probleme.append(f"{Path(neu).name}: {e}")
        leere_wegraeumen(erg.neue_ordner)
        return probleme

    for ordner in sorted(erg.entfernte_quellordner, key=lambda x: len(x.parts)):
        try:
            Path(ordner).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            probleme.append(f"{ordner}: {e}")
    for alt, neu in reversed(erg.dateien):
        alt, neu = Path(alt), Path(neu)
        if not os.path.lexists(neu):
            probleme.append(f"'{neu.name}' wurde am Zielort nicht mehr gefunden.")
            continue
        if os.path.lexists(alt):
            probleme.append(f"Am ursprünglichen Ort existiert schon '{alt.name}'.")
            continue
        try:
            alt.parent.mkdir(parents=True, exist_ok=True)
            FileManager._move_with_retry(neu, alt)
            index_melden("datei_verschoben", str(neu), str(alt))
        except Exception as e:  # noqa: BLE001
            probleme.append(f"{neu.name}: {e}")
    for quelldatei, _vorhandene, ablage in erg.identisch:
        if ablage is None:
            continue
        quelldatei, ablage = Path(quelldatei), Path(ablage)
        if not ablage.exists():
            probleme.append(f"'{quelldatei.name}' ist nicht mehr im Papierkorb.")
            continue
        if os.path.lexists(quelldatei):
            probleme.append(f"Am ursprünglichen Ort existiert schon '{quelldatei.name}'.")
            continue
        try:
            quelldatei.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(ablage), str(quelldatei))
            index_melden("datei_aufnehmen", str(quelldatei))
        except Exception as e:  # noqa: BLE001
            probleme.append(f"{quelldatei.name}: {e}")
    leere_wegraeumen(erg.neue_ordner)
    return probleme

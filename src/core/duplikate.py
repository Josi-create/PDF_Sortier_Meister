"""Doppelte Dateien erkennen (Issue #245) - Qt-frei.

Zwei Dateien gelten als doppelt, wenn ihr Inhalt Byte fuer Byte gleich ist
(gleiche Pruefsumme). Ein Foto und das daraus erzeugte PDF, ein zweiter Scan
desselben Blatts oder eine PDF, in die inzwischen Metadaten oder eine
Textebene geschrieben wurden, sind verschiedene Dateien und werden nicht
gemeldet.

Gerechnet wird sparsam: Nur Dateien gleicher Groesse koennen gleich sein, also
wird eine Pruefsumme erst gebildet, wenn es eine zweite Datei derselben Groesse
gibt. Einmal gebildete Pruefsummen merkt sich :class:`Pruefsummen`, solange
Groesse und Aenderungszeit der Datei gleich bleiben. Fuer Dokumente im
Suchindex schreibt der Indexlauf die Pruefsumme mit (``dokumente.pruefsumme``,
``src/search/db.py``); sie gilt nur, solange die Datei seitdem unveraendert ist.

Keine Funktion dieses Moduls gehoert in den Thread der Oberflaeche: Alle lesen
von der Platte. Dateien, die nur als Platzhalter in der Cloud liegen
(OneDrive „nur online“), werden nie geoeffnet - das wuerde sie herunterladen.
"""

from __future__ import annotations

import hashlib
import os
import stat as stat_modul
import threading
from pathlib import Path
from typing import Callable, Iterable, Optional

from src.search.plattform import nur_cloud, verknuepfung

_BLOCK = 1 << 20  # 1 MB je Lesevorgang


def pruefsumme(pfad: Path | str) -> str:
    """BLAKE2b (16 Byte, hex) ueber den Inhalt der Datei.

    Raises:
        OSError: Datei fehlt oder ist nicht lesbar.
    """
    h = hashlib.blake2b(digest_size=16)
    with open(pfad, "rb") as f:
        while True:
            block = f.read(_BLOCK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def stand_text(groesse: int, mtime_ns: int) -> str:
    """Stand einer Datei, zu dem eine gespeicherte Pruefsumme gehoert (``dokumente.pruefsumme_stand``)."""
    return f"{groesse}:{mtime_ns}"


def _vergleichbar(st: os.stat_result) -> bool:
    """Regulaere, nicht leere Datei, die sich lesen laesst, ohne sie herunterzuladen."""
    return stat_modul.S_ISREG(st.st_mode) and st.st_size > 0 and not nur_cloud(st)


class Pruefsummen:
    """Zwischenspeicher: Pfad -> Pruefsumme, gueltig fuer genau eine Groesse und Aenderungszeit.

    Aus mehreren Threads benutzbar. Er lebt nur im Arbeitsspeicher; nach einem
    Neustart werden die wenigen Dateien gleicher Groesse neu gelesen.
    """

    GRENZE = 50_000  # so viele Eintraege hoechstens (rund 10 MB), danach wird neu begonnen

    def __init__(self) -> None:
        self._sperre = threading.Lock()
        self._werte: dict[str, tuple[int, int, str]] = {}
        self.gerechnet = 0  # so oft wurde eine Datei wirklich gelesen (Tests, Messung)

    def summe(self, pfad: Path | str, st: Optional[os.stat_result] = None) -> Optional[str]:
        """Pruefsumme der Datei; None, wenn sie fehlt, leer, nicht lesbar oder nur online ist
        oder sich waehrend des Lesens geaendert hat."""
        try:
            if st is None:
                st = os.stat(pfad)
            if not _vergleichbar(st):
                return None
            key = os.path.normcase(str(pfad))
            with self._sperre:
                alt = self._werte.get(key)
            if alt is not None and alt[0] == st.st_size and alt[1] == st.st_mtime_ns:
                return alt[2]
            wert = pruefsumme(pfad)
            danach = os.stat(pfad)
        except OSError:
            return None
        if (danach.st_size, danach.st_mtime_ns) != (st.st_size, st.st_mtime_ns):
            return None  # wird gerade geschrieben
        with self._sperre:
            self.gerechnet += 1
            if len(self._werte) >= self.GRENZE:
                self._werte.clear()
            self._werte[key] = (st.st_size, st.st_mtime_ns, wert)
        return wert


# Ein gemeinsamer Zwischenspeicher fuer das Programm
_summen = Pruefsummen()


def summen() -> Pruefsummen:
    return _summen


def selbe_datei(a: Path | str, b: Path | str) -> bool:
    """Dieselbe Datei bzw. derselbe Ordner - auch ueber zwei Schreibweisen des Pfads (Junction, #220)."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(str(a)) == os.path.normcase(str(b))


def gleiche_im_ordner(pfade: Iterable[Path | str],
                      speicher: Optional[Pruefsummen] = None,
                      abbrechen: Optional[Callable[[], bool]] = None,
                      fortschritt: Optional[Callable[[int, int], None]] = None) -> list[list[Path]]:
    """Gruppen inhaltsgleicher Dateien unter ``pfade`` (je Gruppe mindestens zwei, Reihenfolge wie uebergeben).

    Gelesen werden nur Dateien, die ihre Groesse mit einer anderen teilen.
    ``abbrechen()`` wird vor jeder zu lesenden Datei gefragt (True: sofort mit dem
    bisherigen Ergebnis zurueck), ``fortschritt(gelesen, zu_lesen)`` danach gemeldet.
    """
    speicher = speicher or _summen
    nach_groesse: dict[int, list[tuple[Path, os.stat_result]]] = {}
    for p in pfade:
        try:
            st = os.stat(p)
        except OSError:
            continue
        if _vergleichbar(st):
            nach_groesse.setdefault(st.st_size, []).append((Path(p), st))
    zu_lesen = sum(len(g) for g in nach_groesse.values() if len(g) > 1)
    gelesen = 0
    gruppen: list[list[Path]] = []
    for gleich_gross in nach_groesse.values():
        if len(gleich_gross) < 2:
            continue
        nach_summe: dict[str, list[Path]] = {}
        for p, st in gleich_gross:
            if abbrechen is not None and abbrechen():
                return gruppen
            wert = speicher.summe(p, st)
            gelesen += 1
            if fortschritt is not None:
                fortschritt(gelesen, zu_lesen)
            if wert:
                nach_summe.setdefault(wert, []).append(p)
        gruppen.extend(g for g in nach_summe.values() if len(g) > 1)
    return gruppen


def dateien_unter(ordner: Path | str, abbrechen: Optional[Callable[[], bool]] = None) -> list[Path]:
    """Alle Dateien in ``ordner`` und seinen Unterordnern (Issue #299).

    Nicht betreten werden versteckte Ordner (Name beginnt mit „.“ oder „$“, etwa
    ``$RECYCLE.BIN``) sowie Junctions und Symlinks - sonst kaeme eine Datei ueber
    zwei Wege doppelt vor, oder die Suche liefe im Kreis. Nicht lesbare Ordner
    werden uebersprungen. Bei ``abbrechen()`` endet die Suche mit dem bisher Gefundenen.
    """
    dateien: list[Path] = []
    offen = [str(ordner)]
    while offen:
        if abbrechen is not None and abbrechen():
            break
        aktuell = offen.pop()
        try:
            with os.scandir(aktuell) as eintraege:
                for e in eintraege:
                    try:
                        st = e.stat(follow_symlinks=False)
                        if verknuepfung(st) or stat_modul.S_ISLNK(st.st_mode):
                            continue
                        if stat_modul.S_ISDIR(st.st_mode):
                            if not e.name.startswith((".", "$")):
                                offen.append(e.path)
                        elif stat_modul.S_ISREG(st.st_mode):
                            dateien.append(Path(e.path))
                    except OSError:
                        continue
        except OSError:
            continue
    return dateien


def doppelte_unter(ordner: Path | str, speicher: Optional[Pruefsummen] = None,
                   abbrechen: Optional[Callable[[], bool]] = None,
                   fortschritt: Optional[Callable[[int, int], None]] = None) -> list[list[Path]]:
    """Gruppen inhaltsgleicher Dateien in ``ordner`` samt Unterordnern (Issue #299).

    Je Gruppe die aelteste Datei (Aenderungszeit) zuerst; die Gruppen nach dem
    Pfad ihrer ersten Datei. Dateien nur in der Cloud (OneDrive „nur online“)
    werden nicht gelesen und fehlen deshalb.
    """
    pfade = dateien_unter(ordner, abbrechen)
    gruppen = gleiche_im_ordner(pfade, speicher, abbrechen, fortschritt)

    def alter(p: Path):
        try:
            return (os.stat(p).st_mtime_ns, str(p).lower())
        except OSError:
            return (0, str(p).lower())

    gruppen = [sorted(g, key=alter) for g in gruppen]
    gruppen.sort(key=lambda g: str(g[0]).lower())
    return gruppen


def ordner_nach_groesse(ordner: Path | str) -> dict[int, list[Path]]:
    """Dateien eines Ordners nach Groesse; leer, wenn es ihn (noch) nicht gibt oder er nicht erreichbar ist."""
    dateien: dict[int, list[Path]] = {}
    try:
        with os.scandir(ordner) as eintraege:
            for e in eintraege:
                try:
                    if e.is_file():
                        dateien.setdefault(e.stat().st_size, []).append(Path(e.path))
                except OSError:
                    continue
    except OSError:
        pass
    return dateien


def gleiche_anderswo(quelle: Path | str, zielordner: Optional[Path | str | dict] = None,
                     index_kandidaten: Optional[Callable[[int], list[dict]]] = None,
                     speicher: Optional[Pruefsummen] = None) -> list[Path]:
    """Dateien mit demselben Inhalt wie ``quelle``: im Zielordner und unter den Dokumenten des Suchindex.

    ``zielordner`` ist ein Ordner oder - wenn mehrere Dateien in denselben Ordner
    sollen - dessen einmal gelesener Inhalt aus :func:`ordner_nach_groesse`.
    ``index_kandidaten(groesse)`` liefert die Dokumente dieser Groesse als
    ``{"pfad", "pruefsumme", "pruefsumme_stand"}`` (``Suchindex.gleiche_groesse``).
    Eine dort gespeicherte Pruefsumme zaehlt nur, wenn die Datei noch den Stand
    hat, zu dem sie gebildet wurde; sonst wird die Datei gelesen. So werden auch
    Dokumente erkannt, die inzwischen nur noch online liegen.
    ``quelle`` selbst ist nie dabei.
    """
    speicher = speicher or _summen
    try:
        st = os.stat(quelle)
    except OSError:
        return []
    if not _vergleichbar(st):
        return []
    groesse = st.st_size

    kandidaten: dict[str, tuple[Path, Optional[dict]]] = {}
    if zielordner is not None:
        im_ziel = zielordner if isinstance(zielordner, dict) else ordner_nach_groesse(zielordner)
        for pfad in im_ziel.get(groesse, []):
            kandidaten[os.path.normcase(str(pfad))] = (pfad, None)
    if index_kandidaten is not None:
        try:
            zeilen = index_kandidaten(groesse)
        except Exception:  # noqa: BLE001 - ohne Suchindex bleibt der Vergleich im Zielordner
            zeilen = []
        for zeile in zeilen:
            pfad = zeile.get("pfad")
            if pfad:
                key = os.path.normcase(str(pfad))
                vorher = kandidaten.get(key)
                kandidaten[key] = (vorher[0] if vorher else Path(pfad), zeile)
    if not kandidaten:
        return []

    eigene = speicher.summe(quelle, st)
    if eigene is None:
        return []
    treffer: list[Path] = []
    for pfad, zeile in kandidaten.values():
        try:
            kst = os.stat(pfad)
        except OSError:
            continue  # im Index, aber nicht mehr auf der Platte
        if not stat_modul.S_ISREG(kst.st_mode) or kst.st_size != groesse or selbe_datei(pfad, quelle):
            continue
        if (zeile and zeile.get("pruefsumme")
                and zeile.get("pruefsumme_stand") == stand_text(kst.st_size, kst.st_mtime_ns)):
            wert = zeile["pruefsumme"]
        else:
            wert = speicher.summe(pfad, kst)
        if wert == eigene and not any(selbe_datei(pfad, t) for t in treffer):
            treffer.append(pfad)
    return treffer

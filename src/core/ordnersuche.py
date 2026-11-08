"""
Ordnersuche (Issue #159)

Sucht Ordner anhand ihres Namens unterhalb gegebener Wurzelordner. Ohne
Qt-Abhaengigkeit, damit sie im Hintergrund-Thread und in Tests laeuft.

- Gross-/Kleinschreibung egal, der Text wird als Teil des Namens gesucht
  ("Zeugn" findet "Arbeitszeugnisse"); ``*`` und ``?`` sind Platzhalter.
- Breitensuche (flache Treffer zuerst), begrenzt auf ``MAX_TIEFE`` Ebenen
  und ``MAX_TREFFER`` Treffer.
- Es werden nur Verzeichniseintraege gelesen (os.scandir), nie Dateiinhalte;
  OneDrive-Platzhalter werden dadurch nicht heruntergeladen.
- Uebersprungen werden versteckte und System-Ordner, Symlinks und Junctions
  (Schleifen) sowie Ordner, die schon ueber eine andere Wurzel besucht wurden.

GPL-3.0-or-later - Copyright (c) 2026
"""

import os
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

MAX_TIEFE = 8
MAX_TREFFER = 50

_ATTR_VERSTECKT_SYSTEM = 0x2 | 0x4  # FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM


@dataclass(frozen=True)
class Treffer:
    """Ein gefundener Ordner samt der Wurzel, unter der er gefunden wurde."""

    pfad: Path
    wurzel: Path

    @property
    def name(self) -> str:
        return self.pfad.name or str(self.pfad)

    @property
    def relativ(self) -> str:
        """Pfad des Elternordners ab dem Namen der Wurzel (z.B. "Ziel/Anton")."""
        if self.pfad == self.wurzel:
            return ""
        try:
            return self.pfad.parent.relative_to(self.wurzel.parent).as_posix()
        except ValueError:
            return str(self.pfad.parent)


def muster_zu_regex(text: str) -> Optional["re.Pattern[str]"]:
    """Baut aus dem Suchtext ein Teilstring-Muster; leerer Text -> None."""
    text = text.strip()
    if not text:
        return None
    teile = []
    for zeichen in text:
        if zeichen == "*":
            teile.append(".*")
        elif zeichen == "?":
            teile.append(".")
        else:
            teile.append(re.escape(zeichen))
    return re.compile("".join(teile), re.IGNORECASE | re.DOTALL)


def _ist_ausgeschlossen(eintrag: "os.DirEntry[str]") -> bool:
    """Versteckt, System, Symlink oder Junction -> nicht betreten."""
    if eintrag.name.startswith("."):
        return True
    try:
        if eintrag.is_symlink():
            return True
        ist_junction = getattr(eintrag, "is_junction", None)
        if ist_junction is not None and ist_junction():
            return True
        attribute = getattr(eintrag.stat(follow_symlinks=False), "st_file_attributes", 0)
        return bool(attribute & _ATTR_VERSTECKT_SYSTEM)
    except OSError:
        return True


def suche_ordner(
    wurzeln: Iterable[Path],
    text: str,
    max_tiefe: int = MAX_TIEFE,
    max_treffer: int = MAX_TREFFER,
    abgebrochen: Optional[Callable[[], bool]] = None,
) -> list[Treffer]:
    """Liefert bis zu ``max_treffer`` Ordner, deren Name zum Suchtext passt.

    Die Wurzeln selbst liegen auf Tiefe 0 und koennen auch Treffer sein;
    unterhalb werden ``max_tiefe`` Ebenen durchsucht. ``abgebrochen`` wird
    regelmaessig abgefragt (neue Eingabe im Suchfeld).
    """
    muster = muster_zu_regex(text)
    if muster is None:
        return []
    treffer: list[Treffer] = []
    besucht: set[str] = set()
    schlange: deque[tuple[Path, Path, int]] = deque()
    for wurzel in wurzeln:
        wurzel = Path(wurzel)
        schluessel = os.path.normcase(str(wurzel))
        if schluessel in besucht or not wurzel.is_dir():
            continue
        besucht.add(schluessel)
        schlange.append((wurzel, wurzel, 0))

    while schlange:
        if abgebrochen is not None and abgebrochen():
            return treffer
        ordner, wurzel, tiefe = schlange.popleft()
        if muster.search(ordner.name or str(ordner)):
            treffer.append(Treffer(ordner, wurzel))
            if len(treffer) >= max_treffer:
                return treffer
        if tiefe >= max_tiefe:
            continue
        kinder = []
        try:
            with os.scandir(ordner) as it:
                for eintrag in it:
                    if abgebrochen is not None and abgebrochen():
                        return treffer
                    try:
                        if not eintrag.is_dir(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    if _ist_ausgeschlossen(eintrag):
                        continue
                    kinder.append(Path(eintrag.path))
        except OSError:
            continue
        for kind in sorted(kinder, key=lambda p: p.name.casefold()):
            schluessel = os.path.normcase(str(kind))
            if schluessel in besucht:
                continue
            besucht.add(schluessel)
            schlange.append((kind, wurzel, tiefe + 1))
    return treffer

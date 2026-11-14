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
- Namen werden in Unicode-NFC verglichen: macOS liefert Umlaute teils
  zerlegt (NFD), getippt wird NFC - "Börse" fand "Börse" sonst nicht.

Fuer das Suchfeld gibt es zusaetzlich einen Ordner-Index (``OrdnerIndex``,
``suche_im_index``): Auf OneDrive unter macOS dauert das Listen eines Ordners
rund 0,1 s, ein grosser Baum also Minuten. Der Index liest jede Wurzel einmal
im Hintergrund ein; jede Eingabe filtert danach nur noch im Speicher, und
waehrend des Einlesens gibt es schon die bisherigen Treffer.

GPL-3.0-or-later - Copyright (c) 2026
"""

import os
import re
import threading
import time
import unicodedata
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


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def muster_zu_regex(text: str) -> Optional["re.Pattern[str]"]:
    """Baut aus dem Suchtext ein Teilstring-Muster; leerer Text -> None."""
    text = _nfc(text.strip())
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


def _unterordner(ordner: Path, abgebrochen: Optional[Callable[[], bool]] = None) -> Optional[list[Path]]:
    """Sichtbare Unterordner, nach Namen sortiert; None bei Abbruch, [] bei Lesefehler."""
    kinder = []
    try:
        with os.scandir(ordner) as it:
            for eintrag in it:
                if abgebrochen is not None and abgebrochen():
                    return None
                try:
                    if not eintrag.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                if _ist_ausgeschlossen(eintrag):
                    continue
                kinder.append(Path(eintrag.path))
    except OSError:
        return []
    return sorted(kinder, key=lambda p: p.name.casefold())


def anzeigename(pfad: Path) -> str:
    """Ordnername fuer die Anzeige; ein Laufwerk hat keinen Namen und heisst wie sein Pfad ("I:\\")."""
    pfad = Path(pfad)
    return pfad.name or str(pfad)


@dataclass(frozen=True)
class PfadEingabe:
    """Ergebnis einer getippten Pfadangabe (Issue #258).

    ``ordner`` ist der Ordner, den die Eingabe genau bezeichnet (None, solange
    der letzte Teil erst angefangen ist), ``kinder`` sind seine Unterordner
    bzw. die zum angefangenen Teil passenden Ordner.
    """

    ordner: Optional[Path]
    kinder: list[Path]


_NUR_LAUFWERK = re.compile(r"[A-Za-z]:")


def pfad_eingabe(text: str, max_treffer: int = MAX_TREFFER) -> Optional[PfadEingabe]:
    """Deutet den Suchtext als Pfad (Laufwerk oder vollstaendiger Pfad).

    None: kein Pfad, es gilt die Namenssuche. Gelesen wird nur ein Ordner,
    direkt und ohne Index - der Pfad muss kein Zielordner sein. Netzwerkpfade
    (zwei Schraegstriche am Anfang) bleiben aussen vor: sie koennen beim
    Tippen sekundenlang blockieren.
    """
    text = text.strip().strip('"').strip()
    if not text:
        return None
    if os.name == "nt" and _NUR_LAUFWERK.fullmatch(text):
        text += os.sep
    if text.startswith("~"):
        text = os.path.expanduser(text)
    if not os.path.isabs(text) or text.startswith(("\\\\", "//")):
        return None
    pfad = Path(text)
    if len(pfad.drive) == 2 and pfad.drive[0].islower():  # "i:" -> "I:"
        pfad = Path(pfad.drive.upper() + str(pfad)[2:])
    try:
        if pfad.is_dir():
            return PfadEingabe(pfad, (_unterordner(pfad) or [])[:max_treffer])
        if text.endswith(("/", os.sep)) or not pfad.parent.is_dir():
            return PfadEingabe(None, [])
    except OSError:
        return PfadEingabe(None, [])
    anfang = _nfc(pfad.name).casefold()
    kinder = [k for k in _unterordner(pfad.parent) or [] if _nfc(k.name).casefold().startswith(anfang)]
    return PfadEingabe(None, kinder[:max_treffer])


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
        if muster.search(_nfc(ordner.name or str(ordner))):
            treffer.append(Treffer(ordner, wurzel))
            if len(treffer) >= max_treffer:
                return treffer
        if tiefe >= max_tiefe:
            continue
        kinder = _unterordner(ordner, abgebrochen)
        if kinder is None:  # abgebrochen
            return treffer
        for kind in kinder:
            schluessel = os.path.normcase(str(kind))
            if schluessel in besucht:
                continue
            besucht.add(schluessel)
            schlange.append((kind, wurzel, tiefe + 1))
    return treffer


# --------------------------------------------------------------- Ordner-Index
class OrdnerIndex:
    """Alle Ordner unter einer Wurzel, einmal eingelesen und dann im Speicher.

    Das Einlesen laeuft in einem eigenen Hintergrund-Thread, unabhaengig von
    der einzelnen Suche (neue Eingaben brechen es nicht ab). Beim ersten
    Einlesen sind die bisher gefundenen Ordner sofort durchsuchbar; wird der
    Index spaeter erneuert, bleibt die alte Liste bis zum Ende gueltig.
    """

    VERALTET_NACH_S = 60 * 60  # danach beim naechsten Zugriff neu einlesen (OneDrive: Minuten)

    def __init__(self, wurzel: Path, max_tiefe: int = MAX_TIEFE):
        self.wurzel = Path(wurzel)
        self.max_tiefe = max_tiefe
        self._lock = threading.Lock()
        # (Pfad, Tiefe, NFC-Name) in Breitensuche-Reihenfolge
        self._eintraege: list[tuple[Path, int, str]] = []
        self._fertig = False
        self._veraltet = True
        self._stand = 0.0
        self._thread: Optional[threading.Thread] = None

    # -- Zustand
    def sicherstellen(self) -> None:
        """Startet das Einlesen, wenn noetig (noch nie, veraltet, zu alt)."""
        with self._lock:
            if self._fertig and time.monotonic() - self._stand > self.VERALTET_NACH_S:
                self._veraltet = True
            if not self._veraltet or self._thread is not None:
                return
            self._veraltet = False
            self._thread = threading.Thread(
                target=self._einlesen, name=f"Ordnerindex {self.wurzel.name}", daemon=True
            )
            self._thread.start()

    def als_veraltet_markieren(self) -> None:
        """Beim naechsten Zugriff neu einlesen (laeuft gerade eins: danach nochmal)."""
        with self._lock:
            self._veraltet = True

    def schnappschuss(self) -> tuple[list[tuple[Path, int, str]], bool]:
        with self._lock:
            return list(self._eintraege), self._fertig

    # -- Aenderungen aus der App sofort nachziehen (Einlesen dauert auf OneDrive Minuten)
    def ordner_neu(self, pfad: Path) -> None:
        pfad = Path(pfad)
        try:
            tiefe = len(pfad.relative_to(self.wurzel).parts)
        except ValueError:
            return
        if tiefe > self.max_tiefe:
            return
        with self._lock:
            if all(p != pfad for p, _t, _n in self._eintraege):
                self._eintraege.append((pfad, tiefe, _nfc(pfad.name)))

    def ordner_umbenannt(self, alt: Path, neu: Path) -> None:
        alt, neu = Path(alt), Path(neu)
        with self._lock:
            umgeschrieben = []
            for p, t, n in self._eintraege:
                if p == alt or alt in p.parents:
                    p = neu / p.relative_to(alt)
                    try:
                        t = len(p.relative_to(self.wurzel).parts)
                    except ValueError:
                        continue  # aus dieser Wurzel heraus verschoben
                    n = _nfc(p.name)
                umgeschrieben.append((p, t, n))
            self._eintraege = umgeschrieben
        self.ordner_neu(neu)  # ggf. in diese Wurzel hinein verschoben

    # -- Hintergrund
    def _einlesen(self) -> None:
        with self._lock:
            erstes_mal = not self._fertig
            liste: list[tuple[Path, int, str]] = []
            if erstes_mal:
                self._eintraege = liste  # Teilergebnisse sofort durchsuchbar
        schlange: deque[tuple[Path, int]] = deque()
        if self.wurzel.is_dir():
            schlange.append((self.wurzel, 0))
            with self._lock:
                liste.append((self.wurzel, 0, _nfc(self.wurzel.name or str(self.wurzel))))
        while schlange:
            ordner, tiefe = schlange.popleft()
            if tiefe >= self.max_tiefe:
                continue
            kinder = _unterordner(ordner) or []
            # gleich beim Auflisten des Elternordners durchsuchbar machen
            with self._lock:
                liste.extend((k, tiefe + 1, _nfc(k.name)) for k in kinder)
            schlange.extend((k, tiefe + 1) for k in kinder)
        with self._lock:
            self._eintraege = liste
            self._fertig = True
            self._stand = time.monotonic()
            self._thread = None
            nochmal = self._veraltet
        if nochmal:
            self.sicherstellen()


_INDIZES: dict[str, OrdnerIndex] = {}
_INDIZES_LOCK = threading.Lock()


def _schluessel(pfad: Path) -> str:
    return os.path.normcase(str(Path(pfad)))


def index_fuer(wurzel: Path) -> OrdnerIndex:
    """Gemeinsamer Index je Wurzel (Baum rechts und Pfadzeile links teilen ihn)."""
    with _INDIZES_LOCK:
        schluessel = _schluessel(wurzel)
        index = _INDIZES.get(schluessel)
        if index is None:
            index = _INDIZES[schluessel] = OrdnerIndex(Path(wurzel))
        return index


def _alle_indizes() -> list[OrdnerIndex]:
    with _INDIZES_LOCK:
        return list(_INDIZES.values())


def indizes_veraltet() -> None:
    """Alle Indizes beim naechsten Zugriff neu einlesen (z.B. Baum aktualisiert)."""
    for index in _alle_indizes():
        index.als_veraltet_markieren()


def index_ordner_neu(pfad: Path) -> None:
    """In der App angelegten Ordner sofort findbar machen."""
    for index in _alle_indizes():
        index.ordner_neu(pfad)


def index_ordner_umbenannt(alt: Path, neu: Path) -> None:
    """In der App umbenannten/verschobenen Ordner sofort unter neuem Pfad finden."""
    for index in _alle_indizes():
        index.ordner_umbenannt(alt, neu)


def indizes_vorwaermen(wurzeln: Iterable[Path]) -> None:
    """Einlesen schon starten (z.B. sobald das Suchfeld den Fokus bekommt)."""
    for wurzel in wurzeln:
        index_fuer(wurzel).sicherstellen()


def suche_im_index(
    wurzeln: Iterable[Path], text: str, max_treffer: int = MAX_TREFFER
) -> tuple[list[Treffer], bool, int]:
    """Sucht im Ordner-Index; startet das Einlesen bei Bedarf.

    Returns:
        (Treffer, vollstaendig, gelesene Ordner). ``vollstaendig`` ist False,
        solange eine Wurzel zum ersten Mal eingelesen wird - dann erneut fragen.
    """
    muster = muster_zu_regex(text)
    eindeutig: list[Path] = []
    for wurzel in wurzeln:
        wurzel = Path(wurzel)
        if wurzel.is_dir() and all(_schluessel(w) != _schluessel(wurzel) for w in eindeutig):
            eindeutig.append(wurzel)
    kandidaten = []
    vollstaendig = True
    gelesen = 0
    for nr, wurzel in enumerate(eindeutig):
        index = index_fuer(wurzel)
        index.sicherstellen()
        eintraege, fertig = index.schnappschuss()
        vollstaendig = vollstaendig and fertig
        gelesen += len(eintraege)
        if muster is None:
            continue
        for pos, (pfad, tiefe, name) in enumerate(eintraege):
            if muster.search(name):
                kandidaten.append((tiefe, nr, pos, pfad, wurzel))
    # flache Treffer zuerst; ueber mehrere Wurzeln gefundene Ordner nur einmal
    kandidaten.sort(key=lambda k: k[:3])
    treffer: list[Treffer] = []
    gesehen: set[str] = set()
    for _t, _n, _p, pfad, wurzel in kandidaten:
        schluessel = _schluessel(pfad)
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        treffer.append(Treffer(pfad, wurzel))
        if len(treffer) >= max_treffer:
            break
    return treffer, vollstaendig, gelesen

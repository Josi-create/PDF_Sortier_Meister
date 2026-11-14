"""Scan-Ordner beobachten (Issue #232) - Qt-frei.

Solange das Programm offen ist, wird der links geoeffnete Ordner alle paar
Sekunden gelesen (``ordner_lesen``) und mit dem letzten Stand verglichen
(``Abgleich``). Bewusst kein ``QFileSystemWatcher`` und kein ``watchdog``: Beide
halten unter Windows einen offenen Zugriff auf den Ordner, dann laesst er sich
(oder ein Ordner darueber) im Explorer nicht mehr umbenennen oder verschieben,
und auf Netzlaufwerken kommen ihre Meldungen nicht zuverlaessig an. Das Lesen
der Dateiliste kostet bei einigen hundert Dateien rund eine Millisekunde und
laeuft nie im Thread der Oberflaeche.

Eine neue Datei wird erst gemeldet, wenn sie fertig geschrieben ist (Scanner
und OneDrive schreiben in Etappen):

- Groesse und Aenderungszeit sind ``ruhezeit`` Sekunden lang gleich geblieben.
  Gemessen wird an der Datei selbst, nicht am Verzeichniseintrag: den bringt
  Windows erst auf den Stand, wenn das schreibende Programm die Datei schliesst.
- Die Datei laesst sich oeffnen und ist nicht leer.
- PDF, JPEG und PNG tragen ihre Endmarke (``%%EOF``, ``FF D9``, ``IEND``).

Bleibt eine Datei ``hoechstwartezeit`` Sekunden unveraendert, ohne diese
Pruefung zu bestehen (beschaedigtes PDF, gesperrte Datei), wird sie trotzdem
gemeldet - F5 wuerde sie auch zeigen. Dateien, die nur als Platzhalter in der
Cloud liegen (OneDrive „nur online“), werden nicht geoeffnet; das Lesen wuerde
sie herunterladen.
"""

from __future__ import annotations

import os
import stat as stat_modul
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

# Windows: Datei liegt nur in der Cloud (OFFLINE, RECALL_ON_OPEN, RECALL_ON_DATA_ACCESS)
_NUR_ONLINE = 0x1000 | 0x40000 | 0x400000

# Endmarke je Endung: (Marke, so viele Bytes vom Dateiende werden durchsucht)
_ENDMARKEN = {
    ".pdf": (b"%%EOF", 1024),
    ".jpg": (b"\xff\xd9", 64),
    ".jpeg": (b"\xff\xd9", 64),
    ".png": (b"IEND", 16),
}


@dataclass(frozen=True)
class Eintrag:
    """Stand einer Datei: daran ist zu erkennen, ob sie sich geaendert hat."""

    groesse: int
    mtime_ns: int
    nur_online: bool = field(default=False, compare=False)  # zaehlt nicht als Aenderung


@dataclass
class Aenderung:
    """Ergebnis eines Abgleichs (Dateinamen ohne Ordner)."""

    neu: list[str] = field(default_factory=list)        # dazugekommen und fertig geschrieben
    weg: list[str] = field(default_factory=list)        # nicht mehr im Ordner
    geaendert: list[str] = field(default_factory=list)  # Inhalt geaendert und wieder zur Ruhe gekommen
    wartend: int = 0                                    # noch nicht fertig geschrieben
    liste: dict[str, Eintrag] = field(default_factory=dict)  # alle Dateien des Ordners, wie gelesen

    def __bool__(self) -> bool:
        return bool(self.neu or self.weg or self.geaendert)


def _eintrag(st: os.stat_result) -> Eintrag:
    attribute = getattr(st, "st_file_attributes", 0)
    return Eintrag(st.st_size, st.st_mtime_ns, bool(attribute & _NUR_ONLINE))


def anzeige_endungen() -> tuple[str, ...]:
    """Endungen der Dateien, die im Scan-Bereich eine Kachel bekommen."""
    from src.core.office_convert import sortierbare_endungen

    return (".pdf",) + tuple(sortierbare_endungen())


def ordner_lesen(ordner: Path | str, endungen: Iterable[str]) -> dict[str, Eintrag]:
    """Dateien des Ordners mit einer der Endungen (wie ``FileManager.get_pdf_files``/``get_office_files``).

    Raises:
        OSError: Ordner nicht lesbar (geloescht, Netzlaufwerk getrennt). Der Aufrufer
            darf das nicht als „alle Dateien sind weg“ deuten.
    """
    endungen = tuple(e.lower() for e in endungen)
    dateien: dict[str, Eintrag] = {}
    with os.scandir(ordner) as eintraege:
        for e in eintraege:
            name = e.name
            endung = os.path.splitext(name)[1].lower()
            if endung not in endungen:
                continue
            if endung != ".pdf" and name.startswith("~$"):
                continue  # Sperrdatei von Word
            try:
                if not e.is_file():
                    continue
                dateien[name] = _eintrag(e.stat())
            except OSError:
                continue  # zwischen Auflisten und Lesen verschwunden
    return dateien


def datei_stand(pfad: Path | str) -> Optional[Eintrag]:
    """Stand der Datei selbst (nicht des Verzeichniseintrags); None, wenn es sie nicht mehr gibt."""
    try:
        st = os.stat(pfad)
    except OSError:
        return None
    if not stat_modul.S_ISREG(st.st_mode):
        return None
    return _eintrag(st)


def datei_fertig(pfad: Path | str, stand: Eintrag) -> bool:
    """Ist die Datei vollstaendig geschrieben? (leer, gesperrt oder ohne Endmarke: nein)"""
    if stand.nur_online:
        return True  # nicht oeffnen: das wuerde die Datei aus der Cloud laden
    if stand.groesse <= 0:
        return False
    marke = _ENDMARKEN.get(os.path.splitext(str(pfad))[1].lower())
    try:
        with open(pfad, "rb") as datei:
            if marke is None:
                datei.read(1)
                return True
            zeichen, laenge = marke
            datei.seek(max(0, stand.groesse - laenge))
            return zeichen in datei.read(laenge)
    except OSError:
        return False  # das schreibende Programm haelt die Datei gesperrt


@dataclass
class _Wartend:
    stand: Optional[Eintrag]  # Stand der Datei selbst bei der letzten Pruefung
    seit: float               # seit wann dieser Stand unveraendert ist
    bekannt: bool             # True: die Datei hat schon eine Kachel (Aenderung), False: neu


class Abgleich:
    """Vergleicht die Dateiliste eines Ordners von Lesen zu Lesen.

    Laeuft im Hintergrund-Thread der Beobachtung, immer nur ein ``schritt`` zur Zeit.
    """

    def __init__(
        self,
        ordner: Path | str,
        bekannte: Iterable[str] = (),
        ruhezeit: float = 2.0,
        hoechstwartezeit: float = 30.0,
        stand: Callable[[Path], Optional[Eintrag]] = datei_stand,
        fertig: Callable[[Path, Eintrag], bool] = datei_fertig,
    ):
        """
        Args:
            ordner: der beobachtete Ordner
            bekannte: Namen der Dateien, die schon als Kachel angezeigt werden
            ruhezeit: so lange muss eine Datei unveraendert sein, bevor sie gemeldet wird
            hoechstwartezeit: nach so langer Ruhe wird auch eine unvollstaendige Datei gemeldet
            stand, fertig: Zugriff auf die Datei (in Tests ersetzt)
        """
        self.ordner = Path(ordner)
        self.ruhezeit = ruhezeit
        self.hoechstwartezeit = hoechstwartezeit
        self._stand = stand
        self._fertig = fertig
        # Gemeldete Dateien mit dem Verzeichniseintrag beim Melden (None: noch nicht gelesen)
        self._gezeigt: dict[str, Optional[Eintrag]] = {name: None for name in bekannte}
        self._wartend: dict[str, _Wartend] = {}

    def schritt(self, liste: dict[str, Eintrag], jetzt: float) -> Aenderung:
        """Nimmt eine frisch gelesene Dateiliste und meldet, was sich seit dem letzten Mal getan hat."""
        aenderung = Aenderung(liste=liste)

        for name in [n for n in self._gezeigt if n not in liste]:
            del self._gezeigt[name]
            aenderung.weg.append(name)
        for name in [n for n in self._wartend if n not in liste]:
            del self._wartend[name]

        for name, eintrag in liste.items():
            wartend = self._wartend.get(name)
            if wartend is None:
                if name in self._gezeigt:
                    alt = self._gezeigt[name]
                    if alt is None or alt == eintrag:
                        self._gezeigt[name] = eintrag
                        continue
                # Neu oder geaendert: ab jetzt an der Datei selbst messen
                wartend = self._wartend[name] = _Wartend(None, jetzt, name in self._gezeigt)

            pfad = self.ordner / name
            stand = self._stand(pfad)
            if stand is None:
                continue  # gerade verschwunden; das naechste Lesen raeumt auf
            if stand != wartend.stand:
                wartend.stand = stand
                wartend.seit = jetzt
                continue
            ruhe = jetzt - wartend.seit
            if ruhe < self.ruhezeit:
                continue
            if ruhe < self.hoechstwartezeit and not self._fertig(pfad, stand):
                continue
            del self._wartend[name]
            self._gezeigt[name] = eintrag
            (aenderung.geaendert if wartend.bekannt else aenderung.neu).append(name)

        aenderung.wartend = len(self._wartend)
        return aenderung

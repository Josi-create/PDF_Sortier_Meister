"""Geordnete Warteschlange fuer die Schreibmeldungen der Oberflaeche an den Suchindex (Qt-frei).

Umbenennen, Verschieben, Loeschen, Inhaltsaenderungen und PDFSM-Metadaten
(``docs/SUCHE_ARCHITEKTUR.md``, Abschnitt 4.3) laufen nie im GUI-Thread: Der
Lauf committet alle paar Sekunden, eine Meldung wartet auf das Schreibrecht
also unter Umstaenden einige Sekunden. Ein einzelner Hintergrund-Thread
arbeitet die Meldungen in Reihenfolge ab (erst verschieben, dann umbenennen),
Fehler landen im Protokoll und werfen nie in die Oberflaeche.

Die Quelle des ``Suchindex`` ist austauschbar (``konfigurieren``): im Programm
die Konfiguration des Nutzers (nur bei eingeschalteter Suche), in Tests ein
Index unter ``tmp_path`` oder gar keiner (dann sind alle Meldungen wirkungslos).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable

log = logging.getLogger("pdf_sortier_meister.suche")

METHODEN = ("datei_verschoben", "datei_geloescht", "datei_geaendert", "datei_aufnehmen", "ocr_eintragen",
            "metadaten_setzen", "metadaten_ersetzen")


def standard_quelle():
    """Suchindex aus der Nutzerkonfiguration; None, wenn die Suche nicht eingeschaltet ist."""
    from src.search.suchindex import Suchindex
    from src.utils.config import get_config

    konfig = get_config().get_search_config()
    return Suchindex(konfig) if konfig.aktiv else None


class IndexMeldungen:
    """Warteschlange mit einem Arbeits-Thread; ``melden`` kehrt sofort zurueck."""

    def __init__(self, quelle: Callable[[], object] | None = standard_quelle) -> None:
        self._quelle = quelle
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.fehler = 0
        self.erledigt = 0

    def konfigurieren(self, quelle: Callable[[], object] | None) -> None:
        """Quelle des Suchindex setzen; None schaltet alle Meldungen ab."""
        self._quelle = quelle

    def aktiv(self) -> bool:
        return self._quelle is not None

    def melden(self, methode: str, *args, index=None, **kwargs) -> bool:
        """Meldung einreihen; ``index`` uebergeht die Quelle. False, wenn Meldungen abgeschaltet sind."""
        if methode not in METHODEN:
            raise ValueError(f"Unbekannte Meldung: {methode}")
        if index is None and self._quelle is None:
            return False
        self._queue.put((methode, args, kwargs, index))
        self._thread_sichern()
        return True

    def warten(self, timeout: float = 10.0) -> bool:
        """Auf die Abarbeitung aller eingereihten Meldungen warten (Tests, Beenden)."""
        ende = time.monotonic() + timeout
        with self._queue.all_tasks_done:
            while self._queue.unfinished_tasks:
                rest = ende - time.monotonic()
                if rest <= 0:
                    return False
                self._queue.all_tasks_done.wait(rest)
        return True

    def _thread_sichern(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._lauf, name="suche-meldungen", daemon=True)
                self._thread.start()

    def _lauf(self) -> None:
        while True:
            methode, args, kwargs, index = self._queue.get()
            try:
                idx = index if index is not None else (self._quelle() if self._quelle else None)
                if idx is not None:
                    getattr(idx, methode)(*args, **kwargs)
                    self.erledigt += 1
            except Exception:  # noqa: BLE001 - Meldungen duerfen die Oberflaeche nie stoeren
                self.fehler += 1
                log.warning("Indexmeldung %s%r fehlgeschlagen", methode, args, exc_info=True)
            finally:
                self._queue.task_done()


meldungen = IndexMeldungen()


def melden(methode: str, *args, **kwargs) -> bool:
    """Kurzform fuer ``meldungen.melden`` (FileManager, Hauptfenster, Datenbank)."""
    return meldungen.melden(methode, *args, **kwargs)

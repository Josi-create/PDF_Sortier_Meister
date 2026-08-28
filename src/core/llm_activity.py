"""
Aktivitaetsanzeige fuer KI-Aufrufe (Issue #68).

Beta-Feedback: Auf langsamen Rechnern oder bei haengender Cloud-Verbindung
muss sichtbar sein, dass der Computer arbeitet - eine Sanduhr reicht nicht.
Gewuenscht: eine vorwaerts laufende Uhr ("KI denkt seit 0:42") und, wenn
moeglich, eine Schaetzung aus frueheren Anfragen mit demselben Setting.

Zwei Bausteine:

* ``LLMTimingStore`` merkt sich die Dauer abgeschlossener Aufrufe je
  Schluessel ``provider|modell|art`` (die letzten 20) in einer JSON-Datei im
  Datenverzeichnis und liefert daraus den Median als Schaetzung.
* ``LLMActivity`` ist der prozessweite Zaehler laufender Aufrufe. Worker
  melden ``begin()``/``end()``; die GUI haengt sich an ``changed`` und tickt
  waehrenddessen einmal pro Sekunde ihre Anzeige.

Aufrufe kommen aus Worker-Threads - alle Zugriffe sind per Lock geschuetzt,
das Signal wird von Qt in den GUI-Thread gequeued.
"""
from __future__ import annotations

import json
import logging
import statistics
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger("pdf_sortier_meister.llm_activity")

MAX_SAMPLES = 20
MIN_SAMPLES_FOR_ESTIMATE = 2
TIMING_FILENAME = "llm_timing.json"

# Arten von Aufrufen (Teil des Schluessels, weil ein Chat mit Kontext
# deutlich laenger dauert als ein Namensvorschlag)
KIND_SUGGEST = "suggest"
KIND_CHAT = "chat"


def format_elapsed(seconds: float) -> str:
    """0:07, 0:42, 1:05, 12:30 - Minuten:Sekunden, vorwaerts zaehlend."""
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}"


def format_estimate(seconds: float | None) -> str:
    """'ca. 30 s' bzw. 'ca. 1:30 min'; leer, wenn keine Schaetzung vorliegt."""
    if seconds is None or seconds <= 0:
        return ""
    if seconds < 60:
        return f"ca. {max(1, int(round(seconds)))} s"
    return f"ca. {format_elapsed(seconds)} min"


def timing_key(provider: str, model: str, kind: str) -> str:
    return f"{provider or 'none'}|{model or '-'}|{kind}"


def current_timing_key(kind: str) -> str:
    """Schluessel fuer das aktuell konfigurierte Provider/Modell-Setting."""
    try:
        from src.utils.config import get_config

        llm = get_config().get_llm_config()
        return timing_key(llm.get("provider", "none"), llm.get("model", ""), kind)
    except Exception:  # noqa: BLE001 - Anzeige darf nie am Config-Zugriff scheitern
        return timing_key("none", "", kind)


class LLMTimingStore:
    """Dauern abgeschlossener Aufrufe je Setting, persistent als JSON."""

    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path else None
        self._lock = threading.Lock()
        self._data: dict[str, list[float]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path or not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = {
                    str(k): [float(x) for x in v][-MAX_SAMPLES:]
                    for k, v in raw.items()
                    if isinstance(v, list)
                }
        except (OSError, ValueError) as e:
            logger.warning("KI-Zeitstatistik konnte nicht gelesen werden: %s", e)

    def _save(self) -> None:
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data), encoding="utf-8")
        except OSError as e:
            logger.warning("KI-Zeitstatistik konnte nicht gespeichert werden: %s", e)

    def record(self, key: str, seconds: float) -> None:
        if seconds <= 0:
            return
        with self._lock:
            samples = self._data.setdefault(key, [])
            samples.append(round(float(seconds), 3))
            del samples[:-MAX_SAMPLES]
            self._save()

    def samples(self, key: str) -> list[float]:
        with self._lock:
            return list(self._data.get(key, []))

    def estimate(self, key: str) -> float | None:
        """Median der letzten Dauern - robust gegen einzelne Ausreisser."""
        samples = self.samples(key)
        if len(samples) < MIN_SAMPLES_FOR_ESTIMATE:
            return None
        return float(statistics.median(samples))


@dataclass
class LLMJob:
    token: int
    kind: str
    label: str
    key: str
    # perf_counter statt monotonic: Letzteres hat unter Windows nur ~16 ms
    # Aufloesung, sehr kurze Aufrufe kaemen als 0 s in die Statistik.
    started: float = field(default_factory=time.perf_counter)

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.started


class LLMActivity(QObject):
    """Prozessweiter Zaehler laufender KI-Aufrufe.

    Signals:
        changed(): ein Aufruf hat begonnen oder geendet (auch aus Worker-Threads)
    """

    changed = pyqtSignal()

    def __init__(self, store: LLMTimingStore | None = None, parent=None):
        super().__init__(parent)
        self._store = store or LLMTimingStore()
        self._lock = threading.Lock()
        self._jobs: dict[int, LLMJob] = {}
        self._next_token = 1

    @property
    def store(self) -> LLMTimingStore:
        return self._store

    def begin(self, kind: str, label: str = "", key: str | None = None) -> int:
        """Meldet einen startenden Aufruf; Rueckgabe ist das Token fuer ``end``."""
        job_key = key or current_timing_key(kind)
        with self._lock:
            token = self._next_token
            self._next_token += 1
            self._jobs[token] = LLMJob(token=token, kind=kind, label=label, key=job_key)
        self.changed.emit()
        return token

    def end(self, token: int, success: bool = True) -> float | None:
        """Beendet einen Aufruf; erfolgreiche Dauern fliessen in die Schaetzung."""
        with self._lock:
            job = self._jobs.pop(token, None)
        if job is None:
            return None
        elapsed = job.elapsed
        if success:
            self._store.record(job.key, elapsed)
        self.changed.emit()
        return elapsed

    def jobs(self) -> list[LLMJob]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.started)

    def is_busy(self) -> bool:
        with self._lock:
            return bool(self._jobs)

    def estimate(self, kind: str, key: str | None = None) -> float | None:
        return self._store.estimate(key or current_timing_key(kind))

    def describe(self, kind: str | None = None) -> str:
        """Kurztext fuer die Statusleiste, z.B. 'seit 0:42 · ca. 30 s'.

        Bei mehreren laufenden Aufrufen zaehlt der aelteste.
        """
        jobs = [j for j in self.jobs() if kind is None or j.kind == kind]
        if not jobs:
            return ""
        job = jobs[0]
        text = f"seit {format_elapsed(job.elapsed)}"
        estimate = format_estimate(self._store.estimate(job.key))
        if estimate:
            text += f" · {estimate}"
        return text


_activity: LLMActivity | None = None
_activity_lock = threading.Lock()


def _default_store() -> LLMTimingStore:
    try:
        from src.utils.platform_paths import get_app_data_dir

        return LLMTimingStore(get_app_data_dir() / TIMING_FILENAME)
    except Exception as e:  # noqa: BLE001 - dann eben ohne Persistenz
        logger.warning("KI-Zeitstatistik ohne Datei (Datenverzeichnis nicht erreichbar): %s", e)
        return LLMTimingStore(None)


def get_llm_activity() -> LLMActivity:
    """Prozessweite Instanz (lazy)."""
    global _activity
    with _activity_lock:
        if _activity is None:
            _activity = LLMActivity(_default_store())
        return _activity


def reset_llm_activity(store: LLMTimingStore | None = None) -> LLMActivity:
    """Fuer Tests: neue Instanz mit eigenem (z.B. temporaerem) Store."""
    global _activity
    with _activity_lock:
        _activity = LLMActivity(store or LLMTimingStore(None))
        return _activity

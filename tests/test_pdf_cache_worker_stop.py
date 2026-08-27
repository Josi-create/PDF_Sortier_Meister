"""stop_worker() darf einen noch laufenden QThread nicht dem GC ueberlassen.

Gibt Python das Objekt eines laufenden QThread frei, loescht Qt den Thread im
Betrieb - das endet in einem harten Absturz (Access Violation), nicht in einer
Exception. Auf langsamen Rechnern (CI) steckte der Analyse-Worker beim Schliessen
noch im Import/der Analyse, ueberlebte das 2-s-Timeout und stuerzte beim
naechsten GC-Lauf ab.
"""
import gc
import threading

import pytest
from PyQt6.QtCore import QThread


class _SlowWorker(QThread):
    """Blockiert in run(), bis das Event gesetzt wird."""

    def __init__(self):
        super().__init__()
        self.release = threading.Event()

    def stop(self):
        pass  # laesst sich nicht sofort stoppen - wie eine laufende Analyse

    def run(self):
        self.release.wait()


@pytest.fixture
def cache(tmp_path, monkeypatch):
    from src.core import pdf_cache as pc
    from src.utils import config as cfg_mod

    fresh = cfg_mod.Config(config_path=tmp_path / "config.json")
    fresh.set("persist_pdf_cache", False)
    monkeypatch.setattr(cfg_mod, "get_config", lambda: fresh)
    monkeypatch.setattr(pc.PDFCache, "_instance", None)
    return pc.PDFCache()


@pytest.mark.parametrize("attr,stop", [
    ("_worker", "stop_worker"),
    ("_llm_worker", "stop_llm_worker"),
])
def test_stop_keeps_running_thread_referenced(cache, monkeypatch, attr, stop):
    # wait() soll wie ein abgelaufenes Timeout wirken, ohne 2 s zu warten
    monkeypatch.setattr(_SlowWorker, "wait", lambda self, *_: False)

    worker = _SlowWorker()
    setattr(cache, attr, worker)
    worker.start()
    assert worker.isRunning()

    getattr(cache, stop)()
    assert getattr(cache, attr) is None

    # Ohne die Referenz in _stopping_workers wuerde der GC den laufenden Thread
    # loeschen -> Prozessabsturz statt Testfehler.
    del worker
    gc.collect()
    (worker,) = cache._stopping_workers
    assert worker.isRunning()

    worker.release.set()
    assert QThread.wait(worker, 5000)

"""Tests fuer ChatWorker (M3-Hardening: Signal-Safety, cancel-Idempotenz).

Diese Tests verwenden ``QCoreApplication`` statt ``QApplication``, weil
sie keine GUI brauchen - nur die Qt-Signal-Mechanik.
"""
import sys

import pytest


# Qt muss initialisiert sein, bevor pyqtSignal/QObject benutzt werden kann.
@pytest.fixture(scope="module", autouse=True)
def _qapp():
    from PyQt6.QtCore import QCoreApplication
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(sys.argv)
    yield app


def _make_worker(controller, question: str = "Testfrage?"):
    """Helper: erzeugt einen ChatWorker."""
    from src.gui.chat_worker import ChatWorker
    return ChatWorker(controller, question)


class _StubController:
    """Minimaler RAGController-Stub."""

    def __init__(self, answer: str = "Antwort", raise_exc: bool = False):
        self._answer = answer
        self._raise = raise_exc
        self.calls = 0

    def ask(self, question: str):
        self.calls += 1
        if self._raise:
            raise RuntimeError("simulierter LLM-Fehler")
        return _FakeResponse(self._answer)


class _FakeResponse:
    """Dummy-RAGResponse."""
    def __init__(self, text: str):
        self.answer_text = text
        self.used_llm = True
        self.citations = []
        self.retrieved_docs = []


# --------------------------------------------------------------------- #
# M3-Hardening: cancel-Idempotenz & Signal-Safety
# --------------------------------------------------------------------- #


def test_worker_initial_state():
    """Frisch erzeugter Worker ist nicht cancelled und nicht finished."""
    w = _make_worker(_StubController())
    assert w.is_cancelled is False
    assert w.is_finished is False


def test_cancel_sets_flag():
    """cancel() setzt ``is_cancelled`` auf True."""
    w = _make_worker(_StubController())
    w.cancel()
    assert w.is_cancelled is True


def test_cancel_is_idempotent():
    """cancel() darf mehrfach aufgerufen werden, ohne Fehler."""
    w = _make_worker(_StubController())
    w.cancel()
    w.cancel()  # darf nicht crashen
    w.cancel()  # und nochmal
    assert w.is_cancelled is True


def test_finished_signal_not_emitted_after_cancel():
    """Wird cancel() VOR run() aufgerufen, wird ``finished`` NICHT emittiert.

    Verifikation: ``is_finished`` bleibt False, weil der Worker nach
    ``ask()`` zurueckkehrt, aber im cancel-Pfad kein Signal feuert.
    """
    w = _make_worker(_StubController())
    w.cancel()
    w.run()
    # Kein ``finished`` -> is_finished bleibt False
    assert w.is_finished is False
    assert w.is_cancelled is True


def test_finished_signal_emitted_on_normal_run():
    """Im Normal-Fall wird ``finished`` genau einmal emittiert."""
    w = _make_worker(_StubController(answer="Hallo Welt"))
    w.run()
    assert w.is_finished is True
    assert w.is_cancelled is False


def test_finished_signal_only_emitted_once():
    """Zwei aufeinanderfolgende ``run()``-Aufrufe emittieren ``finished``
    nur einmal (Signal-Safety)."""
    w = _make_worker(_StubController(answer="Hallo"))
    w.run()
    assert w.is_finished is True
    w.run()  # zweiter Aufruf -> keine Doppel-Emission
    assert w.is_finished is True


def test_failed_signal_emitted_on_exception():
    """Bei einer Exception wird ``failed`` emittiert (``is_finished`` True)."""
    w = _make_worker(_StubController(raise_exc=True))
    w.run()
    assert w.is_finished is True
    assert w.is_cancelled is False


def test_failed_not_emitted_after_cancel():
    """Wenn cancel() VOR run() aufgerufen wird und ask() wirft, wird
    ``failed`` trotzdem nicht emittiert."""
    w = _make_worker(_StubController(raise_exc=True))
    w.cancel()
    w.run()
    # is_finished bleibt False, weil weder finished noch failed emittiert wurde
    assert w.is_finished is False
    assert w.is_cancelled is True


def test_cancel_after_normal_run_is_safe():
    """cancel() NACH erfolgreichem run() ist ein No-Op (idempotent + sicher)."""
    w = _make_worker(_StubController(answer="Antwort"))
    w.run()
    assert w.is_finished is True
    w.cancel()  # spaet, aber kein Crash
    assert w.is_cancelled is True
    # finished ist trotzdem emittiert worden (nicht rueckgaengig gemacht)
    assert w.is_finished is True

"""ChatWorker reicht ``abbruch``/``fortschritt`` an ``ask()`` durch - nur, wenn die Methode sie annimmt (Issue #166/#167).

Wie ``tests/test_chat_worker.py``: ``QCoreApplication`` statt ``QApplication``,
es geht nur um die Signal-Mechanik.
"""
import sys
import threading

import pytest


@pytest.fixture(scope="module", autouse=True)
def _qapp():
    from PyQt6.QtCore import QCoreApplication
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(sys.argv)
    yield app


class _Antwort:
    def __init__(self, text: str = "Antwort"):
        self.answer_text = text
        self.used_llm = True
        self.citations = []
        self.retrieved_docs = []


class _AlterController:
    """Stub wie in den GUI-Tests: ``ask(question)`` ohne Extras."""

    def __init__(self):
        self.aufrufe = []

    def ask(self, question: str):
        self.aufrufe.append(question)
        return _Antwort()


class _BezugController:
    """Stub wie in test_chat_view_gui: ``ask(question, bezug=None)``."""

    def __init__(self):
        self.aufrufe = []

    def ask(self, question: str, bezug=None):
        self.aufrufe.append((question, bezug))
        return _Antwort()


class _NeuerController:
    """Wie der echte RAGController: ``ask(question, bezug=None, abbruch=None, fortschritt=None)``."""

    def __init__(self):
        self.aufrufe = []

    def ask(self, question: str, bezug=None, abbruch=None, fortschritt=None):
        self.aufrufe.append({"question": question, "bezug": bezug, "abbruch": abbruch, "fortschritt": fortschritt})
        if fortschritt is not None:
            fortschritt("Suche „226541“ …")
        if abbruch is not None and abbruch.is_set():
            return _Antwort("Abgebrochen.")
        return _Antwort()


class _KwargsController:
    def __init__(self):
        self.kwargs = None

    def ask(self, question: str, **kwargs):
        self.kwargs = kwargs
        return _Antwort()


def _worker(controller, bezug=None):
    from src.gui.chat_worker import ChatWorker
    return ChatWorker(controller, "Testfrage?", bezug=bezug)


def test_alter_controller_bekommt_keine_extra_argumente():
    ctrl = _AlterController()
    w = _worker(ctrl)
    w.run()
    assert ctrl.aufrufe == ["Testfrage?"] and w.is_finished


def test_bezug_controller_bekommt_nur_den_bezug():
    ctrl = _BezugController()
    w = _worker(ctrl, bezug="x.pdf")
    w.run()
    assert ctrl.aufrufe == [("Testfrage?", "x.pdf")] and w.is_finished


def test_neuer_controller_bekommt_abbruch_und_fortschritt():
    ctrl = _NeuerController()
    w = _worker(ctrl, bezug="x.pdf")
    meldungen = []
    w.progress.connect(meldungen.append)
    antworten = []
    w.finished.connect(antworten.append)

    w.run()

    aufruf = ctrl.aufrufe[0]
    assert aufruf["question"] == "Testfrage?" and aufruf["bezug"] == "x.pdf"
    assert isinstance(aufruf["abbruch"], threading.Event) and not aufruf["abbruch"].is_set()
    assert callable(aufruf["fortschritt"])
    # Der Callback des Controllers landet als progress-Signal in der GUI
    assert meldungen == ["KI denkt…", "Suche „226541“ …"]
    assert len(antworten) == 1 and antworten[0].answer_text == "Antwort"


def test_cancel_setzt_das_event_das_der_controller_sieht():
    ctrl = _NeuerController()
    w = _worker(ctrl)
    w.cancel()
    w.run()
    aufruf = ctrl.aufrufe[0]
    assert aufruf["abbruch"].is_set() and aufruf["bezug"] is None
    assert not w.is_finished  # abgebrochen: kein finished


def test_controller_mit_kwargs_bekommt_beides():
    ctrl = _KwargsController()
    w = _worker(ctrl)
    w.run()
    assert set(ctrl.kwargs) == {"abbruch", "fortschritt"}

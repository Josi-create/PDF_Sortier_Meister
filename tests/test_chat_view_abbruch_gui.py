"""ChatView (Issue #166/#167): Abbrechen, waehrend der Worker noch im Modellaufruf steckt, darf nicht abstuerzen.

Vorher: _teardown_thread rief deleteLater auf dem noch laufenden QThread
("QThread: Destroyed while thread is still running", qFatal). Jetzt bleibt
der Thread referenziert und wird nach seinem Ende freigegeben.
"""
from __future__ import annotations

import threading

from src.gui.chat_view import ChatView
from src.rag.rag_controller import RAGResponse
from src.utils.config import ChatConfig


class _StubLLM:
    llm_provider = None

    def is_llm_available(self) -> bool:
        return False


class _LangsamerController:
    """ask() blockiert wie ein laufender Modellaufruf, der das Abbruch-Event erst spaeter sieht."""

    def __init__(self):
        self.gestartet = threading.Event()
        self.freigabe = threading.Event()
        self.fertig = threading.Event()
        self.chat_session = None

    def reset(self) -> None:
        pass

    def ask(self, question, bezug=None, abbruch=None, fortschritt=None):
        self.gestartet.set()
        self.freigabe.wait(10)  # ignoriert ``abbruch`` absichtlich: mitten im HTTP-Aufruf
        self.fertig.set()
        return RAGResponse(answer_text="Abgebrochen.", used_llm=False)


def test_abbrechen_waehrend_laufendem_aufruf_gibt_thread_spaeter_frei(qtbot):
    view = ChatView(db=None, hybrid_classifier=_StubLLM(), chat_config=ChatConfig())
    qtbot.addWidget(view)
    controller = _LangsamerController()
    view._controller = controller

    view.input_edit.setPlainText("Lange Frage")
    view._on_send()
    assert controller.gestartet.wait(5)
    thread = view._chat_thread
    assert thread is not None and thread.isRunning()

    view._cancel_current()  # wartet hoechstens 2 s, der Aufruf laeuft weiter

    assert view._chat_thread is None and view._chat_worker is None
    assert view._alte_threads and view._alte_threads[0][0] is thread
    assert thread.isRunning()
    controller.freigabe.set()  # der Modellaufruf kommt zurueck
    assert controller.fertig.wait(5)
    qtbot.waitUntil(lambda: not view._alte_threads, timeout=5000)
    from PyQt6 import sip

    qtbot.waitUntil(lambda: sip.isdeleted(thread), timeout=5000)  # erst nach dem Ende freigegeben
    # Kein Ergebnis gerendert, Eingabe wieder frei
    assert view.input_edit.isEnabled()
    assert view.history_layout.count() == 2  # Nutzer-Bubble + Stretch

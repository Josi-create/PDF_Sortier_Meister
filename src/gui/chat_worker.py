"""
ChatWorker fuer das RAG-Chat-Feature (Phase 19 / M2).

Fuehrt den synchronen (und potentiell langsamen, 5-30s) Aufruf von
``RAGController.ask()`` in einem eigenen Thread aus, damit die GUI
nicht einfriert. Der Worker ist ein ``QObject`` und wird per
``moveToThread`` in einen ``QThread`` verschoben (Architektur-Vorgabe
R3: striktes QObject-move-to-thread-Pattern, kein QThread-Subclassing).

GPL-3.0-or-later - Copyright (c) 2026
"""

import threading

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from src.core.llm_activity import KIND_CHAT, get_llm_activity


class ChatWorker(QObject):
    """Asynchroner LLM-/Retrieval-Aufruf ohne UI-Freeze.

    Signale:
        started: Direkt vor dem ``ask()``-Aufruf.
        progress: Optionaler Status-Text (z.B. "LLM antwortet...").
        finished: Bei Erfolg, emittiert die ``RAGResponse``.
        failed: Bei Exception, emittiert den Fehlertext (str).

    Verwendung::

        thread = QThread()
        worker = ChatWorker(controller, frage)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(...)
        thread.start()
    """

    started = pyqtSignal()
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)  # emittiert RAGResponse
    failed = pyqtSignal(str)

    def __init__(self, controller, question: str) -> None:
        """
        Args:
            controller: Eine :class:`~src.rag.rag_controller.RAGController`.
            question: Die Nutzerfrage.
        """
        super().__init__()
        self.controller = controller
        self.question = question
        self._cancel_event = threading.Event()
        self._cancelled = False
        # Signal-Safety (M3-Hardening): ``finished`` und ``failed`` duerfen
        # jeweils nur EINMAL emittiert werden, damit nach ``cancel()`` kein
        # Zombie-Ergebnis mehr an die GUI geht.
        self._finished_emitted = False
        self._failed_emitted = False

    @pyqtSlot()
    def run(self) -> None:
        """Fuehrt den blockierenden ``ask()``-Aufruf aus.

        Da ``ask()`` ein einziger blockierender Aufruf ist, kann er
        nicht mitten drin abgebrochen werden. ``cancel()`` verhindert
        daher nur, dass ``finished`` nach Rueckkehr noch ausgewertet
        wird (das ``_cancelled``-Flag wird geprueft).
        """
        # Doppel-Start verhindern (z.B. wenn ``started`` zweimal emittiert wird)
        if self._finished_emitted or self._failed_emitted:
            return
        self.started.emit()
        try:
            self.progress.emit("KI denkt…")
            # Aktivitaetsanzeige (Issue #68)
            activity = get_llm_activity()
            token = activity.begin(KIND_CHAT, self.question[:40])
            ok = False
            try:
                response = self.controller.ask(self.question)
                ok = True
            finally:
                activity.end(token, success=ok)
        except Exception as exc:  # noqa: BLE001 - Fehler an GUI melden
            if not self._cancelled and not self._failed_emitted:
                self._failed_emitted = True
                self.failed.emit(str(exc))
            return

        if self._cancelled:
            # Abgebrochen: Ergebnis verwerfen, kein finished emittieren.
            return
        if self._finished_emitted:
            # Doppelt-Emit verhindern (Race mit cancel() waehrend emit)
            return
        self._finished_emitted = True
        self.finished.emit(response)

    def cancel(self) -> None:
        """Markiert den Worker als abgebrochen.

        Setzt ein ``threading.Event`` und ein ``_cancelled``-Flag. Nach
        Rueckkehr aus ``ask()`` wird ``finished`` dann nicht mehr
        emittiert. ``cancel()`` ist idempotent: ein zweiter Aufruf
        waehrend des Cancel-Vorgangs hat keine negativen Auswirkungen.
        """
        if self._cancelled:
            return  # idempotent
        self._cancelled = True
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        """True, wenn der Worker abgebrochen wurde."""
        return self._cancelled

    @property
    def is_finished(self) -> bool:
        """True, wenn ``finished`` oder ``failed`` bereits emittiert wurde.

        Nuetzlich fuer die GUI, um nach ``cancel()`` keine
        Zombie-Slots mehr zu triggern.
        """
        return self._finished_emitted or self._failed_emitted

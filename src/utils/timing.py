"""
Stoppuhr fuer mehrstufige Ablaeufe (Issue #28).

    timer = StepTimer("Verschieben")
    ...; timer.step("move")
    ...; timer.step("metadata")
    timer.done()   # -> INFO-Log: "Verschieben 812 ms: move 120 | metadata 450 | ..."

Loggt nur, wenn die Gesamtdauer ueber ``threshold_ms`` liegt, damit das Log
im Normalfall ruhig bleibt.

GPL-3.0-or-later - Copyright (c) 2026
"""

import logging
import time

logger = logging.getLogger("pdf_sortier_meister.timing")


class StepTimer:
    def __init__(self, label: str, threshold_ms: float = 100.0):
        self.label = label
        self.threshold_ms = threshold_ms
        self._t0 = time.perf_counter()
        self._last = self._t0
        self.steps: list[tuple[str, float]] = []

    def step(self, name: str) -> float:
        now = time.perf_counter()
        ms = (now - self._last) * 1000.0
        self._last = now
        self.steps.append((name, ms))
        return ms

    @property
    def total_ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000.0

    def summary(self) -> str:
        parts = " | ".join(f"{n} {ms:.0f}" for n, ms in self.steps)
        return f"{self.label} {self.total_ms:.0f} ms: {parts}"

    def done(self) -> str:
        text = self.summary()
        if self.total_ms >= self.threshold_ms:
            logger.info(text)
        else:
            logger.debug(text)
        return text

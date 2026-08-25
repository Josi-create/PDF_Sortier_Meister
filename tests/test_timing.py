"""StepTimer (Issue #28 Stoppuhren)."""
import logging


def test_step_timer_collects_steps_and_logs_above_threshold(caplog):
    from src.utils.timing import StepTimer
    t = StepTimer("Test", threshold_ms=0)
    t.step("a"); t.step("b")
    with caplog.at_level(logging.INFO, logger="pdf_sortier_meister.timing"):
        text = t.done()
    assert text.startswith("Test ") and "a " in text and "| b " in text
    assert any("Test " in r.message for r in caplog.records)


def test_step_timer_quiet_below_threshold(caplog):
    from src.utils.timing import StepTimer
    t = StepTimer("Leise", threshold_ms=10_000)
    t.step("x")
    with caplog.at_level(logging.INFO, logger="pdf_sortier_meister.timing"):
        t.done()
    assert not [r for r in caplog.records if r.levelno >= logging.INFO]

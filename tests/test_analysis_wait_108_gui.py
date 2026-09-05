"""Issue #108, Teil 2: Erst-Klick auf eine noch nicht analysierte PDF.

- Analyse-Worker analysiert dieselbe PDF nicht mehrfach (Pre-Cache + Klick).
- Waehrend der Erst-Analyse: Wartezeiger, Kachel "Analysiere…", Statusmeldung.
- Der Wartezustand endet mit dem Ergebnis, auch wenn der Nutzer inzwischen
  eine andere PDF gewaehlt hat; ein neuer Klick oder Abwaehlen beendet ihn.
- Der asynchrone Pfad loggt eine eigene "Klick nach Analyse"-Zeile.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from src.core.pdf_cache import PDFAnalysisResult, PDFAnalysisWorker

from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401


# --- Worker-Dedupe (ohne Thread-Start) --------------------------------------

def test_worker_dedupes_same_pdf(tmp_path):
    w = PDFAnalysisWorker()
    pdf = tmp_path / "a.pdf"
    w.add_background(pdf)
    w.add_background(pdf)          # exakte Kopie: verworfen
    assert w._queue.qsize() == 1
    w.add_task(pdf, priority=5)    # dringender: ueberholt, alte Kopie wird stale
    assert w._queue.qsize() == 2
    assert w.queued_count() == 1
    assert w._dequeue(timeout=0.01) == pdf
    assert w._dequeue(timeout=0.01) is None   # stale Kopie uebersprungen
    assert w.queued_count() == 0


def test_worker_urgent_overtakes_background_and_skips_stale_copy(tmp_path):
    w = PDFAnalysisWorker()
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    w.add_background(a)
    w.add_background(b)
    w.add_urgent(b)          # Nutzer hat b geklickt: ueberholt a
    assert w.queued_count() == 2
    assert w._dequeue(timeout=0.01) == b
    assert w._dequeue(timeout=0.01) == a
    assert w._dequeue(timeout=0.01) is None   # die veraltete Hintergrund-Kopie von b
    assert w.queued_count() == 0


def test_worker_dequeue_after_analysis_allows_reanalysis(tmp_path):
    w = PDFAnalysisWorker()
    pdf = tmp_path / "a.pdf"
    w.add_urgent(pdf)
    assert w._dequeue(timeout=0.01) == pdf
    w.add_urgent(pdf)        # z.B. Datei geaendert -> darf wieder rein
    assert w._dequeue(timeout=0.01) == pdf


# --- GUI: Wartezustand -------------------------------------------------------

def _fake_pdf(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return p


@pytest.fixture
def window_with_pending_analysis(main_window, fresh_singletons, monkeypatch):  # noqa: F811
    """Zwei PDFs im Scan-Ordner; request_analysis liefert nichts sofort, sondern
    merkt sich den Callback (wie der Worker bei einer Scan-PDF)."""
    from src.gui import pdf_thumbnail as th
    monkeypatch.setattr(th.ThumbnailLoaderThread, "start", lambda self: None)

    scan = fresh_singletons["tmp_path"] / "Scan"
    a = _fake_pdf(scan, "a.pdf")
    b = _fake_pdf(scan, "b.pdf")
    main_window._navigate_to_folder(scan)
    assert {w.pdf_path for w in main_window.pdf_widgets} == {a, b}

    pending = {}
    monkeypatch.setattr(
        main_window.pdf_cache, "request_analysis",
        lambda pdf_path, callback=None, urgent=False: pending.__setitem__(pdf_path, callback),
    )
    monkeypatch.setattr(main_window.pdf_cache, "get", lambda pdf_path: None)
    monkeypatch.setattr(main_window.classifier, "is_model_ready", lambda: True)
    yield main_window, a, b, pending
    main_window._end_analysis_wait()
    while QApplication.overrideCursor() is not None:
        QApplication.restoreOverrideCursor()


def test_first_click_shows_wait_state(window_with_pending_analysis):
    win, a, b, pending = window_with_pending_analysis
    win.on_pdf_clicked(a)

    assert win._analysis_wait_pdf == a
    assert QApplication.overrideCursor() is not None
    assert win._pdf_widget_for(a).analyzing
    assert win._pdf_widget_for(a).name_label.text() == "Analysiere…"
    assert "Texterkennung" in win.statusbar.currentMessage()
    assert a in pending


def test_result_ends_wait_state_and_logs_async_click(window_with_pending_analysis, caplog, monkeypatch):
    win, a, b, pending = window_with_pending_analysis
    win.on_pdf_clicked(a)
    monkeypatch.setattr(win, "display_suggestions", lambda s: None)

    with caplog.at_level(logging.DEBUG, logger="pdf_sortier_meister.timing"):
        pending[a](PDFAnalysisResult(pdf_path=a, extracted_text="Rechnung", keywords=["rechnung"]))

    assert win._analysis_wait_pdf is None
    assert QApplication.overrideCursor() is None
    assert not win._pdf_widget_for(a).analyzing
    assert win._pdf_widget_for(a).name_label.text() == "a"
    assert any(r.message.startswith("Klick nach Analyse") for r in caplog.records)


def test_result_for_deselected_pdf_still_resets_wait_state(window_with_pending_analysis):
    """Reset VOR dem selected_pdf-Guard: Ergebnis kommt, Nutzer hat aber
    inzwischen abgewaehlt -> Wartezeiger darf nicht haengen bleiben."""
    win, a, b, pending = window_with_pending_analysis
    win.on_pdf_clicked(a)
    win.selected_pdf = None          # ohne _clear_selection, bewusst "roh"

    pending[a](PDFAnalysisResult(pdf_path=a))

    assert win._analysis_wait_pdf is None
    assert QApplication.overrideCursor() is None
    assert not win._pdf_widget_for(a).analyzing


def test_new_click_moves_wait_state_to_new_pdf(window_with_pending_analysis):
    win, a, b, pending = window_with_pending_analysis
    win.on_pdf_clicked(a)
    win.on_pdf_clicked(b)

    assert win._analysis_wait_pdf == b
    assert not win._pdf_widget_for(a).analyzing
    assert win._pdf_widget_for(b).analyzing
    # genau EIN Override-Cursor, nicht gestapelt
    QApplication.restoreOverrideCursor()
    assert QApplication.overrideCursor() is None
    win._analysis_wait_pdf = None


def test_clear_selection_ends_wait_state(window_with_pending_analysis):
    win, a, b, pending = window_with_pending_analysis
    win.on_pdf_clicked(a)
    win._clear_selection()

    assert win._analysis_wait_pdf is None
    assert QApplication.overrideCursor() is None
    assert not win._pdf_widget_for(a).analyzing


def test_stale_result_for_other_pdf_does_not_end_wait(window_with_pending_analysis):
    win, a, b, pending = window_with_pending_analysis
    win.on_pdf_clicked(a)
    win.on_pdf_clicked(b)
    pending[a](PDFAnalysisResult(pdf_path=a))   # verspaetetes Ergebnis fuer a

    assert win._analysis_wait_pdf == b
    assert QApplication.overrideCursor() is not None

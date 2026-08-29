"""„KI-Fehler“ in der Statusleiste setzt sich zurueck, wenn der Fehler behoben ist."""
from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401 - Fixtures


def _pdf(tmp_path, name):
    p = tmp_path / name
    p.write_bytes(b"%PDF-1.4")
    return p


def test_error_stays_while_run_continues(main_window, tmp_path, monkeypatch):
    a, b = _pdf(tmp_path, "a.pdf"), _pdf(tmp_path, "b.pdf")
    monkeypatch.setattr(main_window.pdf_cache, "llm_pending_count", lambda: 3)
    main_window._on_llm_suggestions_failed(a, "Kein gültiges JSON")
    assert "KI-Fehler" in main_window.cache_status_label.text()
    main_window._on_llm_suggestions_ready(b)
    assert "KI-Fehler" in main_window.cache_status_label.text()


def test_error_clears_when_run_finishes_without_new_errors(main_window, tmp_path, monkeypatch):
    a, b = _pdf(tmp_path, "a.pdf"), _pdf(tmp_path, "b.pdf")
    monkeypatch.setattr(main_window.pdf_cache, "llm_pending_count", lambda: 0)
    main_window._on_llm_suggestions_failed(a, "Kein gültiges JSON")
    main_window._on_llm_suggestions_ready(b)
    assert main_window._last_llm_error is None
    assert "KI-Fehler" not in main_window.cache_status_label.text()


def test_error_clears_when_failed_pdf_succeeds(main_window, tmp_path, monkeypatch):
    a = _pdf(tmp_path, "a.pdf")
    monkeypatch.setattr(main_window.pdf_cache, "llm_pending_count", lambda: 5)
    main_window._on_llm_suggestions_failed(a, "leere Antwort")
    main_window._on_llm_suggestions_ready(a)
    assert main_window._last_llm_error is None


def test_error_stays_when_failure_is_last_in_run(main_window, tmp_path, monkeypatch):
    a, b = _pdf(tmp_path, "a.pdf"), _pdf(tmp_path, "b.pdf")
    monkeypatch.setattr(main_window.pdf_cache, "llm_pending_count", lambda: 0)
    main_window._on_llm_suggestions_ready(b)
    main_window._on_llm_suggestions_failed(a, "leere Antwort")
    assert main_window._last_llm_error is not None
    assert "KI-Fehler" in main_window.cache_status_label.text()

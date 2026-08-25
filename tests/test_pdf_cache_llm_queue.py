"""Tests fuer die LLM-Queue-Verwaltung in src/core/pdf_cache.py"""
from pathlib import Path

import pytest


class _FakeLLMWorker:
    def __init__(self):
        self.tasks = []

    def add_task(self, pdf_path, analysis_result, priority=10):
        self.tasks.append(pdf_path)

    def isRunning(self):
        return True


class _FakeAnalysisWorker:
    def __init__(self):
        self.tasks = []

    def add_background(self, pdf_path):
        self.tasks.append(pdf_path)

    def isRunning(self):
        return True


@pytest.fixture
def cache(tmp_path, monkeypatch):
    from src.core import pdf_cache as pc
    from src.utils import config as cfg_mod

    fresh = cfg_mod.Config(config_path=tmp_path / "config.json")
    fresh.set("persist_pdf_cache", False)  # keine SQLite-DB anfassen
    # PDFCache importiert get_config lokal -> im config-Modul patchen
    monkeypatch.setattr(cfg_mod, "get_config", lambda: fresh)
    # PDFCache ist ein Singleton (__new__) -> frische Instanz erzwingen
    monkeypatch.setattr(pc.PDFCache, "_instance", None)
    c = pc.PDFCache()
    assert c._persist_cache is False
    c._worker = _FakeAnalysisWorker()
    c._llm_worker = _FakeLLMWorker()
    c._llm_precache_enabled = True
    monkeypatch.setattr(c, "_save_to_db", lambda result: None)
    return c


def _cached(cache, pdf: Path):
    from src.core.pdf_cache import PDFAnalysisResult
    pdf.write_bytes(b"%PDF-1.4")
    r = PDFAnalysisResult(pdf_path=pdf, extracted_text="x", file_modified=pdf.stat().st_mtime)
    cache._cache[pdf] = r
    return r


def test_pre_cache_returns_queue_counts(cache, tmp_path):
    new_pdf = tmp_path / "neu.pdf"
    new_pdf.write_bytes(b"%PDF-1.4")
    done_pdf = tmp_path / "analysiert.pdf"
    _cached(cache, done_pdf)

    analysis_n, llm_n = cache.pre_cache([new_pdf, done_pdf])
    assert (analysis_n, llm_n) == (1, 1)
    assert cache._worker.tasks == [new_pdf]
    assert cache._llm_worker.tasks == [done_pdf]


def test_llm_queue_dedupes_until_result_or_skip(cache, tmp_path):
    pdf = tmp_path / "a.pdf"
    _cached(cache, pdf)

    assert cache.pre_cache([pdf]) == (0, 1)
    assert cache.pre_cache([pdf]) == (0, 0)  # bereits eingereiht
    assert cache._llm_worker.tasks == [pdf]

    # Worker hat uebersprungen (LLM war aus) -> darf erneut eingereiht werden
    cache._on_llm_suggestions_skipped(pdf)
    assert cache.pre_cache([pdf]) == (0, 1)

    # Erfolg -> llm_fetched, nichts mehr einzureihen
    cache._on_llm_suggestions_complete(pdf, [])
    assert cache.pre_cache([pdf]) == (0, 0)
    assert cache._cache[pdf].llm_fetched is True


def test_llm_error_emits_signal_and_frees_queue(cache, tmp_path, qtbot):
    pdf = tmp_path / "b.pdf"
    _cached(cache, pdf)
    cache.pre_cache([pdf])

    with qtbot.waitSignal(cache.llm_suggestions_failed, timeout=1000) as blocker:
        cache._on_llm_suggestions_error(pdf, "HTTP 402: Guthaben aufgebraucht")
    assert blocker.args == [pdf, "HTTP 402: Guthaben aufgebraucht"]
    assert cache.pre_cache([pdf]) == (0, 1)  # erneut einreihbar

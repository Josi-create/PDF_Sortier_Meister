"""KI-Vorschlag nach einer Aenderung am Inhalt einer PDF (Zusammenfuehren, Drehen).

Befund vom 13.11.2026: Zwei frisch umgewandelte einseitige PDFs wurden zusammengefuehrt,
das zweiseitige Ergebnis bekam keinen KI-Vorschlag. Die Ziel-PDF stand noch mit ihrer alten
Analyse (eine Seite) in der Vorabfrage des Ordners; die neue Analyse wurde deshalb nicht
eingereiht, und die KI haette spaeter - hinter allen anderen PDFs - mit dem alten Text gefragt.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.core import llm_activity as la
from src.core.pdf_cache import LLMSuggestion, LLMSuggestionWorker, PDFAnalysisResult


@pytest.fixture
def cache(tmp_path, monkeypatch, qtbot):
    """PDFCache mit echtem, aber nicht gestartetem KI-Worker (die Tests spielen ihn selbst)."""
    from src.core import pdf_cache as pc
    from src.utils import config as cfg_mod

    fresh = cfg_mod.Config(config_path=tmp_path / "config.json")
    fresh.set("persist_pdf_cache", False)  # keine SQLite-DB anfassen
    monkeypatch.setattr(cfg_mod, "get_config", lambda: fresh)
    monkeypatch.setattr(pc.PDFCache, "_instance", None)
    c = pc.PDFCache()
    assert c._persist_cache is False
    c._llm_worker = LLMSuggestionWorker()
    c._llm_precache_enabled = True
    monkeypatch.setattr(c, "start_llm_worker", lambda: None)
    return c


def _analyse(pdf: Path, text: str) -> PDFAnalysisResult:
    return PDFAnalysisResult(pdf_path=pdf, extracted_text=text, file_modified=pdf.stat().st_mtime)


def _ki(name: str) -> list[LLMSuggestion]:
    return [LLMSuggestion(filename=name, confidence=0.9, source="llm", metadata={"korrespondent": "X"})]


def _wartend(worker: LLMSuggestionWorker) -> dict[Path, tuple[int, str]]:
    """Was der Worker als Naechstes fragen wuerde: {pdf: (Prioritaet, Text der Analyse)}."""
    return {p: (prio, worker._analysen[p].extracted_text) for p, prio in worker._queued.items()}


def _aufruf_beginnt(worker: LLMSuggestionWorker, pdf: Path) -> None:
    """Der Worker nimmt die PDF aus der Warteschlange und fragt die KI (wie in ``run``)."""
    with worker._lock:
        del worker._queued[pdf]
        worker._current_analyse = worker._analysen.pop(pdf)
        worker._current_pdf = pdf


def _aufruf_endet(worker: LLMSuggestionWorker) -> None:
    with worker._lock:
        worker._current_pdf = None
        worker._current_analyse = None


@pytest.fixture
def pdf(tmp_path) -> Path:
    p = tmp_path / "foto.pdf"
    p.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return p


def test_wartende_anfrage_bekommt_die_neue_analyse(cache, pdf):
    """Die PDF wartet noch in der Vorabfrage, ihr Inhalt aendert sich: gefragt wird mit dem neuen Text."""
    cache._on_analysis_complete(pdf, _analyse(pdf, "eine Seite"))
    assert _wartend(cache._llm_worker) == {pdf: (10, "eine Seite")}

    cache.clear_for_pdf(pdf)  # zusammengefuehrt
    cache._on_analysis_complete(pdf, _analyse(pdf, "zwei Seiten"))

    assert _wartend(cache._llm_worker) == {pdf: (10, "zwei Seiten")}
    assert cache.ki_offen(pdf)


def test_vorziehen_nach_aenderung_reiht_dringend_mit_neuem_text_ein(cache, pdf, monkeypatch):
    """So ruft das Hauptfenster nach dem Zusammenfuehren: Analyse dringend, KI gleich danach vorneweg."""
    andere = pdf.with_name("anderes.pdf")
    andere.write_bytes(b"%PDF-1.4\n%%EOF\n")
    cache._on_analysis_complete(andere, _analyse(andere, "wartet auch"))
    cache._on_analysis_complete(pdf, _analyse(pdf, "eine Seite"))
    cache.clear_for_pdf(pdf)
    angefragt = []
    monkeypatch.setattr(cache, "start_worker", lambda: None)

    class _Analyse:
        def add_urgent(self, p):
            angefragt.append(p)

    cache._worker = _Analyse()

    cache.vorziehen(pdf, mit_ki=True)
    assert angefragt == [pdf]
    cache._on_analysis_complete(pdf, _analyse(pdf, "zwei Seiten"))

    assert _wartend(cache._llm_worker) == {andere: (10, "wartet auch"), pdf: (1, "zwei Seiten")}


def test_antwort_zum_alten_inhalt_wird_verworfen_und_neu_gefragt(cache, pdf):
    """Die KI arbeitet gerade an der PDF, als ihr Inhalt sich aendert."""
    worker = cache._llm_worker
    cache._on_analysis_complete(pdf, _analyse(pdf, "eine Seite"))
    _aufruf_beginnt(worker, pdf)
    cache.clear_for_pdf(pdf)
    cache._on_analysis_complete(pdf, _analyse(pdf, "zwei Seiten"))
    assert _wartend(worker) == {}  # der laufende Aufruf wird erst abgewartet
    fertig = []
    cache.llm_suggestions_ready.connect(fertig.append)

    cache._on_llm_suggestions_complete(pdf, _ki("alt.pdf"))  # Antwort zum alten Inhalt
    _aufruf_endet(worker)

    assert fertig == [] and not cache.has_llm_suggestions(pdf)
    assert _wartend(worker) == {pdf: (1, "zwei Seiten")}  # neu gefragt, vorneweg
    assert cache.ki_offen(pdf)

    _aufruf_beginnt(worker, pdf)
    cache._on_llm_suggestions_complete(pdf, _ki("neu.pdf"))
    _aufruf_endet(worker)
    assert fertig == [pdf]
    assert [s.filename for s in cache.get_llm_suggestions(pdf)] == ["neu.pdf"]
    assert not cache.ki_offen(pdf)


def test_antwort_vor_der_neuen_analyse_bleibt_nicht_haengen(cache, pdf):
    """Die alte Antwort trifft ein, bevor die neue Analyse fertig ist: nichts wird gespeichert,
    die neue Analyse reiht danach ganz normal ein."""
    worker = cache._llm_worker
    cache._on_analysis_complete(pdf, _analyse(pdf, "eine Seite"))
    _aufruf_beginnt(worker, pdf)
    cache.clear_for_pdf(pdf)

    cache._on_llm_suggestions_complete(pdf, _ki("alt.pdf"))
    _aufruf_endet(worker)
    assert not cache.ki_offen(pdf)
    cache._on_analysis_complete(pdf, _analyse(pdf, "zwei Seiten"))

    assert not cache.has_llm_suggestions(pdf)
    assert _wartend(worker) == {pdf: (10, "zwei Seiten")}


def test_fehler_zum_alten_inhalt_zaehlt_nicht_als_ki_fehler(cache, pdf):
    worker = cache._llm_worker
    cache._on_analysis_complete(pdf, _analyse(pdf, "eine Seite"))
    _aufruf_beginnt(worker, pdf)
    cache.clear_for_pdf(pdf)
    cache._on_analysis_complete(pdf, _analyse(pdf, "zwei Seiten"))
    fehler = []
    cache.llm_suggestions_failed.connect(lambda p, e: fehler.append(p))

    cache._on_llm_suggestions_error(pdf, "Zeitüberschreitung")
    _aufruf_endet(worker)

    assert fehler == [] and pdf not in cache._llm_failed
    assert _wartend(worker) == {pdf: (1, "zwei Seiten")}


def test_unveraenderte_pdf_in_arbeit_wird_nicht_doppelt_gefragt(cache, pdf):
    """Ohne Aenderung am Inhalt bleibt es bei einem Aufruf (kein zweites Einreihen, kein Verwerfen)."""
    worker = cache._llm_worker
    cache._on_analysis_complete(pdf, _analyse(pdf, "eine Seite"))
    _aufruf_beginnt(worker, pdf)

    cache.pre_cache([pdf])        # Ordner neu geladen
    cache.vorziehen(pdf, True)    # und dringend verlangt
    assert _wartend(worker) == {}
    cache._on_llm_suggestions_complete(pdf, _ki("a.pdf"))
    _aufruf_endet(worker)

    assert _wartend(worker) == {}
    assert [s.filename for s in cache.get_llm_suggestions(pdf)] == ["a.pdf"]


def test_worker_fragt_mit_der_nachgereichten_analyse(qtbot, pdf):
    """Der echte Worker-Lauf nimmt fuer eine wartende PDF die juengste Analyse."""
    la.reset_llm_activity(la.LLMTimingStore(None))  # keine Zeitmessung in den Daten des Nutzers
    texte = []

    class _Klassifikator:
        last_llm_error = None

        def is_llm_available(self):
            return True

        def suggest_filename(self, text, current_filename, **kw):
            texte.append(text)
            from src.ml.hybrid_classifier import HybridFilename
            return [HybridFilename(filename="neu.pdf", reason="KI", confidence=0.9, source="llm")]

    worker = LLMSuggestionWorker()
    worker._hybrid_classifier = _Klassifikator()
    worker.add_task(pdf, _analyse(pdf, "eine Seite"), priority=10)
    assert worker.analyse_nachreichen(pdf, _analyse(pdf, "zwei Seiten")) is False  # wartet nur

    try:
        with qtbot.waitSignal(worker.suggestions_complete, timeout=5000):
            worker.start()
    finally:
        worker.stop()
        worker.wait(3000)
        la.reset_llm_activity()

    assert texte == ["zwei Seiten"]
    assert worker._analysen == {} and worker._current_analyse is None

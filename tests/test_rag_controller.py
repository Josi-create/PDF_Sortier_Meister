"""Tests fuer RAGController.ask() - Offline-Fallback (M3-Hardening)."""
import pytest

from src.rag.rag_controller import RAGController, RAGResponse
from src.utils.config import ChatConfig


# --------------------------------------------------------------------- #
# Mock-Hilfsobjekte (kein anthropic/openai-Import noetig)
# --------------------------------------------------------------------- #


class _FakeLLM:
    """Minimaler LLM-Provider-Stub, der ``is_available()`` und
    ``answer_with_context()`` kontrolliert."""

    def __init__(self, available: bool = True, answer: str = "LLM-Antwort"):
        self._available = available
        self._answer = answer
        self.calls = 0

    def is_available(self) -> bool:
        return self._available

    def answer_with_context(self, **kwargs) -> str:
        self.calls += 1
        return self._answer


def _make_db_with_docs(tmp_path):
    """DB mit drei indexierten Dokumenten."""
    from src.utils.database import Database
    db = Database(db_path=str(tmp_path / "rag_offline.db"))
    db.index_document(
        file_path="/docs/telekom.pdf",
        filename="2024-01-15_Telekom.pdf",
        extracted_text="Telekom Rechnung 49.95 EUR fuer Internet.",
        keywords="internet,rechnung",
        korrespondent="Telekom",
        kategorie="Rechnung",
        steuerjahr="2024",
        betrag="49.95",
    )
    db.index_document(
        file_path="/docs/stadtwerke.pdf",
        filename="2023-12-04_Stadtwerke.pdf",
        extracted_text="Stadtwerke Stromrechnung 142.30 EUR.",
        keywords="strom,energie",
        korrespondent="Stadtwerke",
        kategorie="Rechnung",
        steuerjahr="2023",
        betrag="142.30",
    )
    db.index_document(
        file_path="/docs/gez.pdf",
        filename="2023-03-01_GEZ.pdf",
        extracted_text="GEZ Rundfunkbeitrag 52.50 EUR.",
        keywords="gez,rundfunk",
        korrespondent="GEZ",
        kategorie="Bescheid",
        steuerjahr="2023",
        betrag="52.50",
    )
    return db


def _empty_db(tmp_path):
    """DB ohne indexierte Dokumente."""
    from src.utils.database import Database
    return Database(db_path=str(tmp_path / "rag_empty.db"))


# --------------------------------------------------------------------- #
# M3-Hardening: Offline-Fallback
# --------------------------------------------------------------------- #


def test_ask_empty_db_returns_no_indexed_message(tmp_path):
    """DB leer (keine indexierten Dokumente) -> 'Keine Dokumente indiziert.'."""
    db = _empty_db(tmp_path)
    ctrl = RAGController(db, llm_provider=_FakeLLM(), chat_config=ChatConfig())
    resp = ctrl.ask("Was steht in den Dokumenten?")
    assert isinstance(resp, RAGResponse)
    assert resp.used_llm is False
    assert resp.answer_text == "Keine Dokumente indiziert."
    assert resp.citations == []
    assert resp.retrieved_docs == []


def test_ask_empty_db_without_llm_same_message(tmp_path):
    """DB leer UND kein LLM -> trotzdem 'Keine Dokumente indiziert.' (nicht 'Keine passenden')."""
    db = _empty_db(tmp_path)
    ctrl = RAGController(db, llm_provider=None, chat_config=ChatConfig())
    resp = ctrl.ask("Was steht in den Dokumenten?")
    assert resp.answer_text == "Keine Dokumente indiziert."
    assert resp.citations == []
    assert resp.retrieved_docs == []
    assert resp.used_llm is False


def test_ask_offline_no_sources_returns_no_matches(tmp_path):
    """LLM=None, DB hat Docs, aber Query liefert nichts -> 'Keine passenden Dokumente gefunden.'."""
    db = _make_db_with_docs(tmp_path)
    ctrl = RAGController(db, llm_provider=None, chat_config=ChatConfig())
    # Eine Query, die garantiert nichts findet (kein Stopword, kein Match im Index)
    resp = ctrl.ask("xyzzy_unsinniges_wort_12345")
    assert resp.used_llm is False
    assert resp.answer_text == "Keine passenden Dokumente gefunden."
    assert resp.citations == []
    assert resp.retrieved_docs == []


def test_ask_offline_llm_unavailable_no_sources(tmp_path):
    """LLM nicht verfuegbar (is_available()=False), DB hat Docs, keine Treffer
    -> 'Keine passenden Dokumente gefunden.'."""
    db = _make_db_with_docs(tmp_path)
    fake_llm = _FakeLLM(available=False)
    ctrl = RAGController(db, llm_provider=fake_llm, chat_config=ChatConfig())
    resp = ctrl.ask("xyzzy_unsinniges_wort_12345")
    assert resp.used_llm is False
    assert resp.answer_text == "Keine passenden Dokumente gefunden."
    assert resp.citations == []
    assert resp.retrieved_docs == []
    # LLM darf nicht aufgerufen worden sein
    assert fake_llm.calls == 0


def test_ask_offline_with_sources_keeps_current_behavior(tmp_path):
    """LLM=None, DB hat Docs, Query liefert Treffer -> leerer answer_text + docs."""
    db = _make_db_with_docs(tmp_path)
    ctrl = RAGController(db, llm_provider=None, chat_config=ChatConfig())
    resp = ctrl.ask("Telekom Rechnung")
    assert resp.used_llm is False
    # Aktuelles Verhalten: leerer answer_text, damit GUI die Treffer-Liste zeigt
    assert resp.answer_text == ""
    assert resp.citations == []
    assert len(resp.retrieved_docs) > 0


def test_ask_llm_available_calls_llm(tmp_path):
    """LLM verfuegbar + DB hat Docs -> LLM wird aufgerufen, used_llm=True."""
    db = _make_db_with_docs(tmp_path)
    fake_llm = _FakeLLM(available=True, answer="Die Antwort lautet 49,95 EUR [1].")
    ctrl = RAGController(db, llm_provider=fake_llm, chat_config=ChatConfig())
    resp = ctrl.ask("Was kostet die Telekom-Rechnung?")
    assert resp.used_llm is True
    assert fake_llm.calls == 1
    # Antwort wurde durch den CitationParser gejagt -> kein "[" ohne gueltige Quelle
    assert resp.answer_text  # nicht leer


def test_ask_empty_question_returns_specific_message(tmp_path):
    """Leere Frage -> 'Bitte stelle eine konkrete Frage.' (bestehendes Verhalten)."""
    db = _make_db_with_docs(tmp_path)
    ctrl = RAGController(db, llm_provider=None, chat_config=ChatConfig())
    resp = ctrl.ask("")
    assert resp.answer_text == "Bitte stelle eine konkrete Frage."
    assert resp.citations == []
    assert resp.retrieved_docs == []


def test_ask_none_question_does_not_crash(tmp_path):
    """Defensiv: question=None darf nicht crashen."""
    db = _make_db_with_docs(tmp_path)
    ctrl = RAGController(db, llm_provider=None, chat_config=ChatConfig())
    resp = ctrl.ask(None)
    assert resp.answer_text == "Bitte stelle eine konkrete Frage."


def test_ask_cache_returns_same_response(tmp_path):
    """Cache-Check: zweiter Aufruf mit gleicher Frage gibt dasselbe Resultat."""
    db = _make_db_with_docs(tmp_path)
    fake_llm = _FakeLLM(available=True, answer="Antwort [1].")
    ctrl = RAGController(db, llm_provider=fake_llm, chat_config=ChatConfig())
    r1 = ctrl.ask("Telekom Rechnung 2024")
    r2 = ctrl.ask("Telekom Rechnung 2024")
    # Aus dem Cache -> gleiche Antwort, aber LLM nur einmal aufgerufen
    assert r1.answer_text == r2.answer_text
    assert fake_llm.calls == 1


def test_ask_llm_provider_with_no_is_available_method(tmp_path):
    """Defensiv: LLM-Provider ohne is_available() -> wird wie nicht-verfuegbar behandelt."""
    class _BadLLM:
        def answer_with_context(self, **kwargs):
            return "sollte nie aufgerufen werden"

    db = _make_db_with_docs(tmp_path)
    ctrl = RAGController(db, llm_provider=_BadLLM(), chat_config=ChatConfig())
    resp = ctrl.ask("Telekom Rechnung")
    # Da is_available() fehlt, faellt der Controller auf Offline zurueck
    assert resp.used_llm is False
    # Entweder leer (mit Quellen) oder Standardtext (ohne)
    assert resp.answer_text in ("", "Keine passenden Dokumente gefunden.")


def test_ask_db_without_get_search_index_count(tmp_path):
    """Defensiv: DB ohne get_search_index_count() -> normaler Flow laeuft weiter."""
    class _BareDB:
        def search_documents(self, *args, **kwargs):
            return []

    ctrl = RAGController(_BareDB(), llm_provider=None, chat_config=ChatConfig())
    resp = ctrl.ask("irgendwas")
    # Kein Count-Methode -> _has_indexed_documents() returnt True ->
    # Retrieval laeuft, findet nichts -> "Keine passenden Dokumente gefunden."
    assert resp.answer_text == "Keine passenden Dokumente gefunden."
    assert resp.retrieved_docs == []

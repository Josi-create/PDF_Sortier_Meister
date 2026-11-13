"""Tests fuer RAGController.ask() - Offline-Fallback (M3-Hardening)."""
from pathlib import Path

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


# --------------------------------------------------------------------- #
# Issue #148: Chat mit Bezugsdokument
# --------------------------------------------------------------------- #


class _SpyLLM(_FakeLLM):
    """Merkt sich die Kontext-Dokumente des letzten Aufrufs."""

    def __init__(self, answer: str = "Siehe [1]."):
        super().__init__(available=True, answer=answer)
        self.context_docs = []
        self.question = ""

    def answer_with_context(self, **kwargs) -> str:
        self.context_docs = kwargs.get("context_docs") or []
        self.question = kwargs.get("user_question", "")
        return super().answer_with_context(**kwargs)


def _bezug(pfad, **kwargs):
    from src.rag.bezug import Bezug
    return Bezug(pfad=Path(pfad), **kwargs)


def test_bezug_steht_als_dokument_1_im_kontext(tmp_path):
    from src.rag.prompts import build_context_block

    db = _make_db_with_docs(tmp_path)
    llm = _SpyLLM()
    ctrl = RAGController(db, llm, ChatConfig())
    bezug = _bezug(
        tmp_path / "Scan_0815.pdf",
        text="Stromabrechnung fuer die Wohnung Lindenstrasse 5, Zaehler 4711",
        metadaten={"korrespondent": "Stadtwerke", "kategorie": "Rechnung", "steuerjahr": "2023"},
    )

    response = ctrl.ask("Zu welcher Wohnung gehört dieses Dokument?", bezug=bezug)

    erster = llm.context_docs[0]
    assert erster["index"] == 1 and erster["bezug"] is True
    assert erster["filename"] == "Scan_0815.pdf"
    assert "Lindenstrasse 5" in erster["text_snippet"]
    assert erster["korrespondent"] == "Stadtwerke"
    # Suchtreffer folgen ab [D2], das Bezugsdokument zitierbar als [1]
    assert [d["index"] for d in llm.context_docs] == list(range(1, len(llm.context_docs) + 1))
    assert len(llm.context_docs) >= 2
    assert response.retrieved_docs[0].file_path == str(bezug.pfad)
    assert response.citations and response.citations[0].index == 1

    block = build_context_block(llm.context_docs)
    assert block.index("BEZUGSDOKUMENT") < block.index("[D1]") < block.index("WEITERE DOKUMENTE") < block.index("[D2]")


def test_bezug_aus_dem_index_mit_metadaten_und_ohne_dublette(tmp_path):
    from tests import helfer_suche as h

    db = _make_db_with_docs(tmp_path)
    pdf = h.pdf_mit_text(tmp_path / "Abschlag.pdf", ["Stadtwerke Abschlag Strom Wohnung Gartenweg 2"])
    db.index_document(file_path=str(pdf), filename=pdf.name, korrespondent="Stadtwerke",
                      kategorie="Rechnung", steuerjahr="2024", betrag="61.00")
    llm = _SpyLLM()
    ctrl = RAGController(db, llm, ChatConfig())

    ctrl.ask("Zeig mir ähnliche Rechnungen", bezug=pdf)

    erster = llm.context_docs[0]
    assert erster["bezug"] is True and erster["korrespondent"] == "Stadtwerke"
    assert erster["steuerjahr"] == "2024" and erster["betrag"] == "61.00"
    assert "Gartenweg 2" in erster["text_snippet"]
    pfade = [d["file_path"] for d in llm.context_docs]
    assert pfade.count(str(pdf)) == 1  # Bezug nicht noch einmal als Suchtreffer
    # Angereicherte Suche: die andere Stadtwerke-Rechnung ist dabei
    assert any(Path(p).name == "stadtwerke.pdf" for p in pfade)


def test_suche_wird_um_metadaten_des_bezugs_ergaenzt(tmp_path, monkeypatch):
    db = _make_db_with_docs(tmp_path)
    ctrl = RAGController(db, _SpyLLM(), ChatConfig())
    aufrufe = []
    echt = ctrl.retrieval.retrieve

    def spy(question, k=None, zusatz="", **mehr):
        aufrufe.append((question, zusatz, mehr))
        return echt(question, k=k, zusatz=zusatz, **mehr)

    monkeypatch.setattr(ctrl.retrieval, "retrieve", spy)
    ctrl.ask("Zeig mir ähnliche Rechnungen", bezug=_bezug(
        tmp_path / "x.pdf", metadaten={"korrespondent": "Telekom", "kategorie": "Rechnung", "steuerjahr": "2024"}))

    frage, zusatz, mehr = aufrufe[-1]
    assert frage == "Zeig mir ähnliche Rechnungen"
    assert "Telekom" in zusatz and "Rechnung" in zusatz and "2024" in zusatz
    # Fragen zu einem Bezugsdokument laufen ohne Bedeutungssuche (Issue #230)
    assert mehr == {"bedeutung": False}


def test_ordnerfrage_bekommt_vorschlag_der_sortierlogik(tmp_path):
    from src.rag.prompts import build_context_block

    db = _make_db_with_docs(tmp_path)
    llm = _SpyLLM()
    ctrl = RAGController(db, llm, ChatConfig())
    bezug = _bezug(tmp_path / "Scan.pdf", text="Stromrechnung",
                   sortier_vorschlaege=["Ablage/Energie (90 %, KI: ähnliche Dokumente liegen dort)"])

    ctrl.ask("In welchen Ordner gehört dieses PDF?", bezug=bezug)
    block = build_context_block(llm.context_docs)
    assert "VORSCHLAG DER SORTIERLOGIK: Ablage/Energie (90 %, KI: ähnliche Dokumente liegen dort)" in block
    assert block.index("VORSCHLAG DER SORTIERLOGIK") < block.index("--- text ---")

    # Andere Fragen bekommen die Zeile nicht
    ctrl.ask("Zeig mir ähnliche Rechnungen", bezug=bezug)
    assert "VORSCHLAG DER SORTIERLOGIK" not in build_context_block(llm.context_docs)


def test_ordnerfrage_ohne_vorschlag_sagt_keiner(tmp_path):
    db = _make_db_with_docs(tmp_path)
    llm = _SpyLLM()
    RAGController(db, llm, ChatConfig()).ask(
        "Gibt es schon einen Ordner mit ähnlichen Dokumenten?", bezug=_bezug(tmp_path / "Scan.pdf"))
    assert llm.context_docs[0]["hinweise"] == ["VORSCHLAG DER SORTIERLOGIK: keiner"]


def test_suchtreffer_haben_mit_bezug_einen_ablageort(tmp_path):
    from src.rag.bezug import ablageort

    db = _make_db_with_docs(tmp_path)
    llm = _SpyLLM()
    ctrl = RAGController(db, llm, ChatConfig())
    ctrl.ask("Zeig mir ähnliche Rechnungen", bezug=_bezug(
        tmp_path / "Eingang" / "Scan.pdf", metadaten={"korrespondent": "Telekom"}))
    assert llm.context_docs[0]["ordner"] == "Eingang"
    assert all(d.get("ordner") for d in llm.context_docs[1:])

    wurzel = tmp_path / "Ablage"
    assert ablageort(wurzel / "Steuer 2024" / "Energie" / "a.pdf", [wurzel]) == "Ablage/Steuer 2024/Energie"
    assert ablageort(tmp_path / "Scan" / "a.pdf", [wurzel]) == "Scan"


def test_ohne_bezug_bleibt_der_kontext_wie_bisher(tmp_path):
    db = _make_db_with_docs(tmp_path)
    llm = _SpyLLM()
    RAGController(db, llm, ChatConfig()).ask("Telekom Rechnung")
    assert llm.context_docs
    for d in llm.context_docs:
        assert "bezug" not in d and "ordner" not in d and "hinweise" not in d


def test_cache_key_unterscheidet_mit_und_ohne_bezug(tmp_path):
    db = _make_db_with_docs(tmp_path)
    llm = _SpyLLM()
    ctrl = RAGController(db, llm, ChatConfig())
    a, b = _bezug(tmp_path / "a.pdf"), _bezug(tmp_path / "b.pdf")

    keys = {ctrl._cache_key("Frage"), ctrl._cache_key("Frage", a), ctrl._cache_key("Frage", b)}
    assert len(keys) == 3
    assert ctrl._cache_key("Frage", a) == ctrl._cache_key("Frage", _bezug(tmp_path / "a.pdf"))

    frage = "Zeig mir ähnliche Rechnungen"
    ctrl.ask(frage)
    ctrl.ask(frage, bezug=a)
    ctrl.ask(frage, bezug=b)
    assert llm.calls == 3
    ctrl.ask(frage, bezug=_bezug(tmp_path / "a.pdf"))  # gleicher Bezug -> Cache
    assert llm.calls == 3


def test_bezug_auch_als_pfad(tmp_path):
    db = _make_db_with_docs(tmp_path)
    llm = _SpyLLM()
    RAGController(db, llm, ChatConfig()).ask("Was steht drin?", bezug=str(tmp_path / "x.pdf"))
    assert llm.context_docs[0]["filename"] == "x.pdf"
    assert llm.context_docs[0]["text_snippet"] == "(Kein Text erkannt.)"


def test_bezug_bei_leerem_index_fragt_trotzdem_die_ki(tmp_path):
    llm = _SpyLLM()
    response = RAGController(_empty_db(tmp_path), llm, ChatConfig()).ask(
        "Zu welcher Wohnung gehört dieses Dokument?", bezug=_bezug(tmp_path / "Scan.pdf", text="Wohnung 3"))
    assert llm.calls == 1 and response.used_llm
    assert [d["index"] for d in llm.context_docs] == [1]


def test_offline_mit_bezug_zeigt_treffer_ohne_bezug_und_hinweis(tmp_path):
    db = _make_db_with_docs(tmp_path)
    ctrl = RAGController(db, None, ChatConfig())
    bezug = _bezug(tmp_path / "Scan.pdf", metadaten={"korrespondent": "Stadtwerke"},
                   sortier_vorschlaege=["Ablage/Energie (80 %)"])

    response = ctrl.ask("In welchen Ordner gehört dieses PDF?", bezug=bezug)

    assert not response.used_llm
    assert response.hinweis == "Vorschlag der Sortierlogik: Ablage/Energie (80 %)"
    assert response.retrieved_docs, "Stadtwerke-Treffer erwartet"
    assert all(d.file_path != str(bezug.pfad) for d in response.retrieved_docs)
    assert [d.index for d in response.retrieved_docs] == list(range(1, len(response.retrieved_docs) + 1))

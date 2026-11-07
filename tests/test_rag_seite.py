"""Zitate mit Seite (Phase 5): search_documents -> RetrievedDoc.seite -> Citation.seite -> Vorschau auf der Seite."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.gui.chat_view import ChatView
from src.rag.citation import CitationParser
from src.rag.retrieval import RetrievalService, RetrievedDoc
from src.utils.config import ChatConfig
from src.utils.database import Database
from tests import helfer_suche as h


class _StubLLM:
    llm_provider = None

    def is_llm_available(self):
        return False


def test_search_documents_liefert_seite_und_zitate_tragen_sie(tmp_path):
    db = Database(tmp_path / "t.db")
    pdf = h.pdf_mit_text(tmp_path / "strom.pdf", ["Erste Seite ohne Treffer", "Zweite Seite mit Stromrechnung 142,30"])
    db.index_document(str(pdf), "strom.pdf", korrespondent="Stadtwerke", kategorie="Rechnung", steuerjahr="2023")
    raw = db.search_documents("Stromrechnung")
    assert len(raw) == 1 and raw[0]["seite"] == 2 and raw[0]["dok_id"] and raw[0]["typ"] == "pdf"
    assert "Stromrechnung" in raw[0]["extracted_text"] and ">>>Stromrechnung<<<" in raw[0]["text_snippet"]

    docs = RetrievalService(db, ChatConfig()).retrieve("Stromrechnung")
    assert docs and docs[0].seite == 2 and docs[0].dok_id == raw[0]["dok_id"]
    _cleaned, valid, _dropped = CitationParser().parse("Die Rechnung [1] ist da.", docs)
    assert valid and valid[0].seite == 2 and valid[0].file_path == str(pdf)
    # Dict-Aufrufer ohne Seite bleiben moeglich
    _c, valid2, _d = CitationParser().parse("[1]", [{"index": 1, "filename": "x.pdf", "file_path": "/x.pdf"}])
    assert valid2[0].seite == 0


def test_chat_quelle_oeffnet_auf_der_seite(qtbot, tmp_path):
    view = ChatView(db=None, hybrid_classifier=_StubLLM(), chat_config=ChatConfig())
    qtbot.addWidget(view)
    pfad = str(tmp_path / "a.pdf")
    view._populate_sources([
        RetrievedDoc(index=1, file_path=pfad, filename="a.pdf", text_snippet="", rank=1, seite=3),
        RetrievedDoc(index=2, file_path=pfad, filename="a.pdf", text_snippet="", rank=2),
    ])
    assert "(S. 3)" in view.sources_list.item(0).text() and "(S." not in view.sources_list.item(1).text()
    with qtbot.waitSignal(view.open_pdf_page_requested, timeout=1000) as blocker:
        view.sources_list.itemClicked.emit(view.sources_list.item(0))
    assert blocker.args == [pfad, 3]
    with qtbot.waitSignal(view.open_pdf_requested, timeout=1000) as blocker:
        view.sources_list.itemClicked.emit(view.sources_list.item(1))
    assert blocker.args == [pfad]
    # Zitat-Link mit Seite
    with qtbot.waitSignal(view.open_pdf_page_requested, timeout=1000) as blocker:
        view._on_citation_link("1", {"1": {"file_path": pfad, "pdf_id": "", "seite": 3}})
    assert blocker.args == [pfad, 3]


def test_vorschaufenster_springt_auf_die_seite(qtbot, tmp_path):
    from src.gui.pdf_preview_window import PdfPreviewWindow

    pdf = h.pdf_mit_text(tmp_path / "drei.pdf", ["eins", "zwei", "drei"])
    win = PdfPreviewWindow()
    qtbot.addWidget(win)
    with qtbot.waitSignal(win.preview.document_loaded, timeout=10000):
        win.show_pdf(pdf, seite=3)
    qtbot.waitUntil(lambda: win.preview.current_page() == 2, timeout=3000)
    assert win._pending_seite is None
    win.preview.shutdown()
    win.close()


@pytest.mark.parametrize("seite", [0, None])
def test_vorschaufenster_ohne_seite_bleibt_vorn(qtbot, tmp_path, seite):
    from src.gui.pdf_preview_window import PdfPreviewWindow

    pdf = h.pdf_mit_text(tmp_path / "zwei.pdf", ["eins", "zwei"])
    win = PdfPreviewWindow()
    qtbot.addWidget(win)
    with qtbot.waitSignal(win.preview.document_loaded, timeout=10000):
        win.show_pdf(Path(pdf), seite)
    assert win.preview.current_page() == 0
    win.preview.shutdown()
    win.close()

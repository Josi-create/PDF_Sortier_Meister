"""Tests fuer Phase 3 (Issue #25) - pdf_id-Propagation.

Prueft, dass ``pdf_id`` rueckwaertskompatibel durch die gesamte
RAG-Pipeline und in die GUI durchgereicht wird:

* ``RetrievedDoc`` traegt nach ``retrieve()`` die ``pdf_id`` aus der DB.
* Alte Aufrufer (DB ohne ``pdf_id``-Feld) crashen nicht.
* ``CitationParser`` uebernimmt ``pdf_id`` aus ``retrieved_docs``.
* Alte Aufrufer (kein ``pdf_id``-Feld) ergeben ``Citation.pdf_id == ""``.
* DetailPanel zeigt ``pdf_id`` in toolTip und als ID-Zeile.
* Smoke-Test: ``search_documents() -> show_search_results()`` macht
  ``pdf_id`` sichtbar.

MIT License - Copyright (c) 2026
"""
from __future__ import annotations

import uuid

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem

from src.rag.citation import Citation, CitationParser
from src.rag.retrieval import RetrievedDoc, RetrievalService


# --------------------------------------------------------------------- #
# Hilfsfunktionen / Fixtures
# --------------------------------------------------------------------- #


def _make_db_with_pdf_ids(tmp_path, with_pdf_id: bool = True):
    """Erzeugt eine Test-DB mit seed-Dokumenten.

    Args:
        tmp_path: pytest tmp_path
        with_pdf_id: Wenn True, wird die DB normal mit ``pdf_id``
            indiziert (Phase-2-Verhalten). Wenn False, werden Dicts
            ohne ``pdf_id`` simuliert (Phase-1-Rueckwaerts-Pfad).
    """
    from src.utils.database import Database
    db = Database(db_path=str(tmp_path / "pdfid_test.db"))
    db.index_document(
        file_path="/docs/a.pdf",
        filename="2024-01-15_A.pdf",
        extracted_text="A alpha bravo charlie",
        keywords="alpha",
        korrespondent="A GmbH",
        kategorie="Rechnung",
        steuerjahr="2024",
        betrag="10.00",
    )
    db.index_document(
        file_path="/docs/b.pdf",
        filename="2024-02-20_B.pdf",
        extracted_text="B alpha delta echo",
        keywords="alpha",
        korrespondent="B AG",
        kategorie="Vertrag",
        steuerjahr="2024",
        betrag="20.00",
    )
    return db


def _patch_search_documents(db, drop_pdf_id: bool):
    """Patcht ``db.search_documents``, damit die Dicts kein ``pdf_id``
    enthalten (Simulation eines alten DB-Stands).
    """
    if not drop_pdf_id:
        return
    original = db.search_documents

    def _stripped(query, *args, **kwargs):
        rows = original(query, *args, **kwargs) or []
        return [{k: v for k, v in r.items() if k != "pdf_id"} for r in rows]

    db.search_documents = _stripped


# --------------------------------------------------------------------- #
# 1) RetrievedDoc.pdf_id nach retrieve() korrekt gesetzt
# --------------------------------------------------------------------- #


def test_retrieveddoc_has_pdf_id_field():
    """Dataclass-Feld ist da (Rueckwaertskompatibilitaet)."""
    doc = RetrievedDoc(
        index=1, file_path="/x.pdf", filename="x.pdf", text_snippet="",
        rank=1,
    )
    # Default: leerer String (kein Breaking Change)
    assert doc.pdf_id == ""


def test_retrieveddoc_pdf_id_propagation(tmp_path):
    """retrieve() setzt pdf_id aus dem DB-Result."""
    db = _make_db_with_pdf_ids(tmp_path)
    rs = RetrievalService(db=db)
    docs = rs.retrieve("alpha", k=5)
    assert len(docs) >= 1
    # Jedes RetrievedDoc MUSS eine nicht-leere 32-Zeichen-Hex-pdf_id haben
    for d in docs:
        assert isinstance(d.pdf_id, str)
        assert len(d.pdf_id) == 32
        # Pruefe dass es eine gueltige UUID ist
        uuid.UUID(hex=d.pdf_id)


def test_retrieveddoc_without_pdf_id_does_not_crash(tmp_path):
    """Alter Aufruf (DB ohne pdf_id-Feld) crasht nicht und liefert ''."""
    db = _make_db_with_pdf_ids(tmp_path)
    _patch_search_documents(db, drop_pdf_id=True)
    rs = RetrievalService(db=db)
    docs = rs.retrieve("alpha", k=5)
    # Mindestens ein Treffer (sonst waere der Test trivial)
    assert len(docs) >= 1
    # pdf_id ist leerer String (Default), kein Crash
    for d in docs:
        assert d.pdf_id == ""


def test_retrieveddoc_manual_construction_with_pdf_id():
    """Manuelle Konstruktion mit pdf_id funktioniert."""
    pid = uuid.uuid4().hex
    doc = RetrievedDoc(
        index=1, file_path="/x.pdf", filename="x.pdf", text_snippet="t",
        rank=1, pdf_id=pid,
    )
    assert doc.pdf_id == pid


def test_retrieveddoc_manual_construction_without_pdf_id():
    """Manuelle Konstruktion ohne pdf_id nutzt Default ''."""
    doc = RetrievedDoc(
        index=1, file_path="/x.pdf", filename="x.pdf", text_snippet="t",
        rank=1,
    )
    assert doc.pdf_id == ""


# --------------------------------------------------------------------- #
# 2) Citation.pdf_id aus retrieved_docs uebernommen
# --------------------------------------------------------------------- #


def test_citation_dataclass_has_pdf_id_field():
    """Citation-Dataclass hat ein pdf_id-Feld mit Default ''."""
    c = Citation(index=1, filename="a.pdf", file_path="/a.pdf", valid=True)
    assert c.pdf_id == ""


def test_citation_parser_propagates_pdf_id_from_dicts():
    """Parser uebernimmt pdf_id aus Dict-Format retrieved_docs."""
    pid = uuid.uuid4().hex
    p = CitationParser()
    docs = [
        {"index": 1, "filename": "a.pdf", "file_path": "/a.pdf",
         "pdf_id": pid},
    ]
    cleaned, valid, dropped = p.parse("Laut [1] ist alles klar.", docs)
    assert len(valid) == 1
    assert valid[0].pdf_id == pid


def test_citation_parser_propagates_pdf_id_from_retrieveddoc():
    """Parser uebernimmt pdf_id aus RetrievedDoc-Instanzen."""
    pid = uuid.uuid4().hex
    p = CitationParser()
    docs = [
        RetrievedDoc(
            index=1, file_path="/a.pdf", filename="a.pdf", text_snippet="",
            rank=1, pdf_id=pid,
        ),
    ]
    cleaned, valid, dropped = p.parse("Laut [1] ist alles klar.", docs)
    assert len(valid) == 1
    assert valid[0].pdf_id == pid


def test_citation_parser_empty_pdf_id_when_missing_in_dicts():
    """Parser setzt Citation.pdf_id == '' wenn retrieved_docs kein
    pdf_id-Feld haben (alter Aufruf, Phase-1-Backwards-Compat)."""
    p = CitationParser()
    docs = [
        {"index": 1, "filename": "a.pdf", "file_path": "/a.pdf"},
    ]
    cleaned, valid, dropped = p.parse("Laut [1] ist alles klar.", docs)
    assert len(valid) == 1
    assert valid[0].pdf_id == ""


def test_citation_parser_empty_pdf_id_when_missing_in_retrieveddoc():
    """Parser setzt Citation.pdf_id == '' bei RetrievedDoc ohne pdf_id."""
    p = CitationParser()
    docs = [
        RetrievedDoc(
            index=1, file_path="/a.pdf", filename="a.pdf", text_snippet="",
            rank=1,  # kein pdf_id -> Default ""
        ),
    ]
    cleaned, valid, dropped = p.parse("Laut [1] ist alles klar.", docs)
    assert len(valid) == 1
    assert valid[0].pdf_id == ""


def test_citation_parser_dropped_citation_has_empty_pdf_id():
    """Dropped-Citations haben immer pdf_id == '' (Whitelist-Miss)."""
    p = CitationParser()
    docs = [{"index": 1, "filename": "a.pdf", "file_path": "/a.pdf",
             "pdf_id": "abc123"}]
    cleaned, valid, dropped = p.parse("Laut [99] stimmt etwas.", docs)
    assert valid == []
    assert len(dropped) == 1
    assert dropped[0].pdf_id == ""


# --------------------------------------------------------------------- #
# 3) DetailPanel: pdf_id sichtbar / in toolTip
# --------------------------------------------------------------------- #


def _make_detail_panel(qtbot):
    """Erzeugt ein frisches DetailPanel (headless via qtbot)."""
    from src.gui.detail_panel import DetailPanel
    panel = DetailPanel()
    qtbot.addWidget(panel)
    return panel


def test_detail_panel_shows_pdf_id_in_tooltip(qtbot, tmp_path):
    """DetailPanel setzt toolTip mit 'pdf_id: <uuid>'."""
    panel = _make_detail_panel(qtbot)
    pid = uuid.uuid4().hex
    results = [
        {
            "filename": "test.pdf",
            "file_path": "/docs/test.pdf",
            "pdf_id": pid,
            "text_snippet": "hello world",
        },
    ]
    panel.show_search_results(results)
    # Hole das erste Item
    assert panel.search_results_list.count() == 1
    item = panel.search_results_list.item(0)
    assert isinstance(item, QListWidgetItem)
    # toolTip enthaelt die pdf_id
    tip = item.toolTip()
    assert pid in tip
    assert "pdf_id:" in tip


def test_detail_panel_shows_short_pdf_id_in_label(qtbot, tmp_path):
    """DetailPanel zeigt eine 'ID: <8 Zeichen>...'-Zeile im Display."""
    panel = _make_detail_panel(qtbot)
    pid = uuid.uuid4().hex
    results = [
        {
            "filename": "test.pdf",
            "file_path": "/docs/test.pdf",
            "pdf_id": pid,
            "text_snippet": "",
        },
    ]
    panel.show_search_results(results)
    item = panel.search_results_list.item(0)
    text = item.text()
    # "ID: " + 8 Zeichen + "…" muss vorkommen
    assert "ID: " in text
    short = pid[:8]
    assert short in text


def test_detail_panel_without_pdf_id_shows_no_id_line(qtbot, tmp_path):
    """Ohne pdf_id im Result wird KEINE 'ID:'-Zeile gerendert."""
    panel = _make_detail_panel(qtbot)
    results = [
        {
            "filename": "test.pdf",
            "file_path": "/docs/test.pdf",
            "text_snippet": "snip",
            # kein pdf_id
        },
    ]
    panel.show_search_results(results)
    item = panel.search_results_list.item(0)
    text = item.text()
    # Keine ID-Zeile
    assert "ID: " not in text
    # toolTip enthaelt NUR den Pfad
    assert item.toolTip() == "/docs/test.pdf"


def test_detail_panel_empty_pdf_id_treated_as_missing(qtbot, tmp_path):
    """Leerer pdf_id-String wird wie 'fehlend' behandelt."""
    panel = _make_detail_panel(qtbot)
    results = [
        {
            "filename": "test.pdf",
            "file_path": "/docs/test.pdf",
            "pdf_id": "",
            "text_snippet": "snip",
        },
    ]
    panel.show_search_results(results)
    item = panel.search_results_list.item(0)
    text = item.text()
    assert "ID: " not in text
    # toolTip enthaelt KEIN 'pdf_id:'-Label
    assert "pdf_id:" not in item.toolTip()


# --------------------------------------------------------------------- #
# 4) Smoke-Test: search_documents -> show_search_results
# --------------------------------------------------------------------- #


def test_smoke_search_documents_to_detail_panel(qtbot, tmp_path):
    """End-to-End: DB.search_documents -> DetailPanel zeigt pdf_id."""
    db = _make_db_with_pdf_ids(tmp_path)
    # Suche via search_documents
    raw = db.search_documents("alpha", limit=10)
    assert len(raw) >= 2
    # Jeder Treffer hat eine pdf_id (32-stellig)
    for r in raw:
        assert "pdf_id" in r
        assert len(r["pdf_id"]) == 32

    # In das DetailPanel einspeisen
    panel = _make_detail_panel(qtbot)
    panel.show_search_results(raw)
    # Fuer jeden DB-Treffer gibt es ein QListWidgetItem mit pdf_id
    # im toolTip.
    assert panel.search_results_list.count() == len(raw)
    for i, r in enumerate(raw):
        item = panel.search_results_list.item(i)
        assert r["pdf_id"] in item.toolTip()

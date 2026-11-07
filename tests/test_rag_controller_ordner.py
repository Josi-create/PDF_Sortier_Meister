"""RAGController (Phase 3, Issue #166/#167): Zielordner der zitierten Belege in der Antwort."""
from __future__ import annotations

from pathlib import Path

from src.rag.bezug import Bezug
from src.rag.rag_controller import RAGController
from src.utils.config import ChatConfig
from src.utils.database import Database
from tests import helfer_suche as h
from tests.test_rag_controller import _SpyLLM

BEZUG_TEXT = "Gasliefervertrag mit der Vertragsnummer G22504020299 und Gaszaehlernummer 226541."


def _sammlung(tmp_path):
    db = Database(tmp_path / "t.db")
    ablage = tmp_path / "Ablage"
    energie = ablage / "Energie"
    energie.mkdir(parents=True)
    for name, text in (("Abrechnung.pdf", "Vertragsnummer G22504020299 Abnahmestelle Kellermannstr. 3"),
                       ("Stammdaten.pdf", "Zaehlernummer 226541 Kellermannstr. 3")):
        pdf = h.pdf_mit_text(energie / name, [text])
        db.index_document(str(pdf), name)
    scan = tmp_path / "Scan"
    scan.mkdir()
    return db, ablage, scan


def test_antwort_traegt_den_ordner_der_zitierten_belege(tmp_path):
    db, ablage, scan = _sammlung(tmp_path)
    llm = _SpyLLM(answer="Es gehört zur Kellermannstr. 3 [2], siehe auch [3].")
    bezug = Bezug(pfad=scan / "Neu.pdf", text=BEZUG_TEXT, scan_ordner=scan, wurzeln=[ablage])
    response = RAGController(db, llm, ChatConfig()).ask("Zu welcher Wohnung gehört dieses Dokument?", bezug=bezug)
    assert response.used_llm and [c.index for c in response.citations] == [2, 3]
    assert Path(response.ordner_vorschlag) == ablage / "Energie"
    assert response.ordner_anzeige == "Ablage/Energie"
    assert response.ordner_begruendung == "belegt durch [2], [3]"


def test_kein_ordner_ohne_bezug_ohne_zitate_oder_nur_bezug_zitiert(tmp_path):
    db, ablage, scan = _sammlung(tmp_path)
    ctrl = RAGController(db, _SpyLLM(answer="Siehe [1]."), ChatConfig())
    bezug = Bezug(pfad=scan / "Neu.pdf", text=BEZUG_TEXT, scan_ordner=scan, wurzeln=[ablage])
    # Nur das Bezugsdokument zitiert -> kein Zielordner
    response = ctrl.ask("Was steht drin?", bezug=bezug)
    assert response.ordner_vorschlag == "" and response.ordner_anzeige == ""
    # Ohne Bezug keine Verschiebe-Empfehlung
    response = RAGController(db, _SpyLLM(answer="Antwort [1]."), ChatConfig()).ask("Kellermannstr")
    assert response.ordner_vorschlag == ""
    # Ohne Zitate nichts
    response = RAGController(db, _SpyLLM(answer="Keine Ahnung."), ChatConfig()).ask("Wohnung?", bezug=bezug)
    assert response.ordner_vorschlag == ""

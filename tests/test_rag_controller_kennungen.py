"""RAGController mit Bezugsdokument seit Issue #166/#167: Kennungen verknuepfen Dokumente, Scan-Eingang."""
from pathlib import Path

from src.rag.bezug import Bezug
from src.rag.prompts import SCAN_EINGANG_HINWEIS, build_context_block
from src.rag.rag_controller import RAGController
from src.utils.config import ChatConfig
from src.utils.database import Database
from tests import helfer_suche as h
from tests.test_rag_controller import _SpyLLM

BEZUG_TEXT = (
    "Preisanpassung zum 03.05.2026 fuer Ihren Gasliefervertrag mit der Vertragsnummer G22504020299 "
    "und den Gaszaehler mit der Gaszaehlernummer 226541."
)


def _db_mit_sammlung(tmp_path):
    db = Database(tmp_path / "t.db")
    texte = {
        "Verbrauchsabrechnung.pdf": "Vertragsnummer G22504020299 Kundennummer G27301A1686 "
                                    "Abnahmestelle Kellermannstr. 3, 48149 Muenster",
        "Stammdaten.pdf": "Zaehlernummer 226541 Netzbetreiber Stadtnetze Muenster Kellermannstr. 3",
        "Telekom.pdf": "Telekom Rechnung Internet 49,95 EUR fuer die Wohnung Musterweg 1",
    }
    for name, text in texte.items():
        pdf = h.pdf_mit_text(tmp_path / name, [text])
        db.index_document(str(pdf), name)
    return db


def test_kennungen_des_bezugs_holen_verknuepfte_dokumente_zuerst(tmp_path):
    db = _db_mit_sammlung(tmp_path)
    llm = _SpyLLM()
    bezug = Bezug(pfad=tmp_path / "Scan.pdf", text=BEZUG_TEXT)

    RAGController(db, llm, ChatConfig()).ask("Zu welcher Wohnung / welchem Objekt gehört dieses Dokument?", bezug=bezug)

    docs = llm.context_docs
    assert docs[0]["bezug"] is True
    assert docs[0]["kennungen"] == ["G22504020299 (Vertragsnummer)", "226541 (Zählernummer)"]
    assert [d["filename"] for d in docs[1:3]] == ["Verbrauchsabrechnung.pdf", "Stammdaten.pdf"]
    assert docs[1]["gemeinsame_kennungen"] == ["G22504020299 (Vertragsnummer)"]
    assert docs[2]["gemeinsame_kennungen"] == ["226541 (Zählernummer)"]
    assert "Kellermannstr" in docs[1]["text_snippet"]
    assert [d["index"] for d in docs] == list(range(1, len(docs) + 1))
    # Die Telekom-Rechnung kommt nur ueber die Frage ("Wohnung") und ohne Kennung
    telekom = [d for d in docs if d["filename"] == "Telekom.pdf"]
    assert telekom and "gemeinsame_kennungen" not in telekom[0]

    block = build_context_block(docs)
    assert "kennungen in diesem Dokument: G22504020299 (Vertragsnummer), 226541 (Zählernummer)" in block
    assert "gemeinsame Kennungen mit dem Bezugsdokument: G22504020299 (Vertragsnummer)" in block
    assert block.index("[D1]") < block.index("kennungen in diesem Dokument") < block.index("[D2]")


def test_kennungs_treffer_lassen_platz_fuer_treffer_zur_frage(tmp_path):
    db = _db_mit_sammlung(tmp_path)
    llm = _SpyLLM()
    bezug = Bezug(pfad=tmp_path / "Scan.pdf", text=BEZUG_TEXT)

    RAGController(db, llm, ChatConfig(max_context_docs=3)).ask("Welche Wohnung?", bezug=bezug)

    docs = llm.context_docs
    # Bezug + 1 Kennungs-Treffer (hoechstens k - 2) + der Treffer zur Frage ("Wohnung" -> Telekom)
    assert [d["filename"] for d in docs] == ["Scan.pdf", "Verbrauchsabrechnung.pdf", "Telekom.pdf"]
    assert [bool(d.get("gemeinsame_kennungen")) for d in docs] == [False, True, False]


def test_bezug_aus_dem_index_liefert_kennungen_aus_dem_volltext(tmp_path):
    db = _db_mit_sammlung(tmp_path)
    scan = h.pdf_mit_text(tmp_path / "G22504020299.pdf", [BEZUG_TEXT])
    db.index_document(str(scan), scan.name)
    llm = _SpyLLM()

    RAGController(db, llm, ChatConfig()).ask("Zu welcher Wohnung gehört dieses Dokument?", bezug=scan)

    docs = llm.context_docs
    assert docs[0]["kennungen"][0] == "G22504020299 (Vertragsnummer)"
    pfade = [d["file_path"] for d in docs]
    assert pfade.count(str(scan)) == 1  # der Bezug ist kein eigener Kennungs-Treffer
    assert docs[1]["filename"] == "Verbrauchsabrechnung.pdf"


def test_ohne_kennungen_keine_kennungssuche(tmp_path, monkeypatch):
    db = _db_mit_sammlung(tmp_path)
    llm = _SpyLLM()
    ctrl = RAGController(db, llm, ChatConfig())
    aufrufe = []
    monkeypatch.setattr(ctrl.retrieval, "retrieve_kennungen",
                        lambda *a, **kw: aufrufe.append((a, kw)) or [])

    ctrl.ask("Zeig mir ähnliche Rechnungen", bezug=Bezug(pfad=tmp_path / "x.pdf", text="Nur Text ohne Nummern"))

    assert aufrufe == []
    assert "kennungen" not in llm.context_docs[0]


def test_bezug_im_scan_eingang_hat_keinen_ablageort_aber_den_hinweis(tmp_path):
    db = _db_mit_sammlung(tmp_path)
    llm = _SpyLLM()
    scan = tmp_path / "Scan"
    bezug = Bezug(pfad=scan / "Neu.pdf", text="Stromrechnung", scan_ordner=scan,
                  sortier_vorschlaege=["Ablage/Energie (80 %)"], wurzeln=[tmp_path / "Ablage"])

    RAGController(db, llm, ChatConfig()).ask("In welchen Ordner gehört dieses PDF?", bezug=bezug)

    erster = llm.context_docs[0]
    assert "ordner" not in erster
    assert erster["hinweise"] == [SCAN_EINGANG_HINWEIS, "VORSCHLAG DER SORTIERLOGIK: Ablage/Energie (80 %)"]
    block = build_context_block(llm.context_docs)
    assert "LIEGT NOCH UNSORTIERT IM SCAN-EINGANG" in block
    assert block.index("SCAN-EINGANG") < block.index("VORSCHLAG DER SORTIERLOGIK") < block.index("--- text ---")

    # Ausserhalb des Scan-Ordners wie bisher: Ablageort, kein Hinweis
    bezug2 = Bezug(pfad=tmp_path / "Ablage" / "Energie" / "Alt.pdf", text="Stromrechnung", scan_ordner=scan,
                   wurzeln=[tmp_path / "Ablage"])
    RAGController(db, llm, ChatConfig()).ask("Zeig mir ähnliche Rechnungen", bezug=bezug2)
    assert llm.context_docs[0]["ordner"] == "Ablage/Energie"
    assert "hinweise" not in llm.context_docs[0]


def test_offline_mit_bezug_zeigt_kennungs_treffer(tmp_path):
    db = _db_mit_sammlung(tmp_path)
    response = RAGController(db, None, ChatConfig()).ask("Welche Wohnung?", bezug=Bezug(pfad=tmp_path / "Scan.pdf", text=BEZUG_TEXT))
    assert not response.used_llm
    assert response.retrieved_docs[0].filename == "Verbrauchsabrechnung.pdf"
    assert response.retrieved_docs[0].extra["gemeinsame_kennungen"] == ["G22504020299 (Vertragsnummer)"]
    assert Path(response.retrieved_docs[0].file_path).exists()

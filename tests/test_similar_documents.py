"""Aehnliche, bereits einsortierte Dokumente als Kontext fuer die KI
(src/core/similar_documents.py) - inkl. Jahres-Regel: ein Zwilling in
"Steuer 2024" macht aus einer Rechnung von 2026 keinen 2024er-Beleg."""
from pathlib import Path

import pytest

from src.core import similar_documents as sd
from src.ml.classifier import Suggestion


@pytest.fixture
def roots(tmp_path):
    ziel = tmp_path / "Ablage"
    for sub in ("Steuer 2024/Energie", "Steuer 2026/Energie", "Versicherung"):
        (ziel / sub).mkdir(parents=True)
    return [ziel]


class _FakeDb:
    def __init__(self, history=(), index=()):
        self._history = list(history)
        self._index = list(index)

    def get_history_brief(self, limit=20000):
        return self._history[:limit]

    def get_indexed_documents_brief(self, limit=20000):
        return self._index[:limit]


TEXT = ("Stadtwerke Musterstadt GmbH\nRechnung Nr. 4711\nDatum: 31.01.2026\n"
        "Stromabrechnung Januar 2026 fuer Kim Muster\nGesamtbetrag 84,20 EUR")


# --- Ordnerpfade ---------------------------------------------------------------

def test_relative_und_aufloesen(roots):
    ziel = roots[0]
    assert sd.relative_folder(ziel / "Steuer 2024" / "Energie", roots) == "Ablage/Steuer 2024/Energie"
    assert sd.relative_folder(ziel, roots) == "Ablage"
    assert sd.relative_folder(ziel.parent / "woanders", roots) == ""
    assert sd.resolve_relative_folder("Ablage/Steuer 2026/Energie", roots) == ziel / "Steuer 2026" / "Energie"
    assert sd.resolve_relative_folder("ablage\\Steuer 2026\\Energie", roots) == ziel / "Steuer 2026" / "Energie"
    assert sd.resolve_relative_folder("Ablage/Steuer 2025/Energie", roots) is None
    assert sd.resolve_relative_folder("Fremd/x", roots) is None
    # alte Historie: Pfad ohne Zielordner-Namen, mit Backslash
    assert sd.resolve_relative_folder("Steuer 2026\\Energie", roots) == ziel / "Steuer 2026" / "Energie"
    assert sd.year_adjusted_folder("Steuer 2024\\Energie", 2026, roots) == "Ablage/Steuer 2026/Energie"


def test_jahr_nur_plausibel():
    assert sd._year_of("Rechnung-Nr-2034-17.pdf", "2025-01-01") == 2025
    assert sd._year_of("1999", "2034") is None
    assert sd._year_of("Steuer 2024/Medikamente") == 2024


def test_ablageort_bevorzugt_absoluten_zielordner(roots):
    ziel = roots[0]
    db = _FakeDb(history=[{
        "new_filename": "2024-01-30_Stadtwerke_Stromabrechnung.pdf", "original_filename": "s.pdf",
        "keywords": "", "korrespondent": "", "steuerjahr": "2024", "detected_date": None,
        "target_relative_path": "Steuer\\Steuer 2024",  # alte, abweichende Schreibweise
        "target_folder": str(ziel / "Steuer 2024" / "Energie"),
    }])
    found = sd.find_similar_documents(TEXT, [], roots, db=db)
    assert found[0].folder == "Ablage/Steuer 2024/Energie"


def test_nur_stichwoerter_reichen_nicht(roots):
    db = _FakeDb(history=[{
        "new_filename": "2025-03-03_HUK_Police.pdf", "original_filename": "p.pdf",
        "keywords": "rechnung,datum,strom", "korrespondent": "", "steuerjahr": "2025",
        "detected_date": None, "target_relative_path": "Ablage/Versicherung", "target_folder": "",
    }])
    assert sd.find_similar_documents(TEXT, ["rechnung", "datum", "strom"], roots, db=db) == []


def test_jahres_variante(roots):
    assert sd.year_adjusted_folder("Ablage/Steuer 2024/Energie", 2026, roots) == "Ablage/Steuer 2026/Energie"
    assert sd.year_adjusted_folder("Ablage/Steuer 2024/Energie", 2025, roots) is None  # Ordner fehlt
    assert sd.year_adjusted_folder("Ablage/Steuer 2024/Energie", 2024, roots) is None  # gleiches Jahr
    assert sd.year_adjusted_folder("Ablage/Versicherung", 2026, roots) is None  # kein Jahr im Pfad
    assert sd.year_adjusted_folder("Ablage/Steuer 2024/Energie", None, roots) is None


def test_document_year():
    assert sd.document_year("2026-01-31") == 2026
    assert sd.document_year(None, "2025-12-01") == 2025
    assert sd.document_year("", "") is None


# --- Aehnlichkeit --------------------------------------------------------------

def test_findet_aehnliche_aus_historie_und_index(roots):
    ziel = roots[0]
    db = _FakeDb(
        history=[
            {"new_filename": "2024-01-30_Stadtwerke_Stromabrechnung.pdf", "original_filename": "scan1.pdf",
             "keywords": "rechnung,strom", "korrespondent": "Stadtwerke Musterstadt",
             "steuerjahr": "2024", "detected_date": "2024-01-30",
             "target_relative_path": "Ablage/Steuer 2024/Energie", "target_folder": str(ziel / "Steuer 2024" / "Energie")},
            {"new_filename": None, "original_filename": "2023-05-02_HUK_Police.pdf",
             "keywords": "versicherung", "korrespondent": "HUK", "steuerjahr": None, "detected_date": None,
             "target_relative_path": None, "target_folder": str(ziel / "Versicherung")},
            {"new_filename": "irgendwo.pdf", "original_filename": "x.pdf", "keywords": "rechnung,strom",
             "korrespondent": "", "steuerjahr": None, "detected_date": None,
             "target_relative_path": None, "target_folder": "C:/ausserhalb"},  # kein Ablageort -> raus
        ],
        index=[
            {"filename": "2024-07-15_Stadtwerke_Abschlag.pdf",
             "file_path": str(ziel / "Steuer 2024" / "Energie" / "2024-07-15_Stadtwerke_Abschlag.pdf"),
             "keywords": "strom", "korrespondent": "", "steuerjahr": "", "target_folder": ""},
            {"filename": "2021-02-02_Kim_Zeugnis.pdf",  # nur ein Vorname gemeinsam -> zu schwach
             "file_path": str(ziel / "Versicherung" / "2021-02-02_Kim_Zeugnis.pdf"),
             "keywords": "", "korrespondent": "", "steuerjahr": "", "target_folder": ""},
        ],
    )
    found = sd.find_similar_documents(TEXT, ["rechnung", "strom"], roots, db=db)
    names = [d.filename for d in found]
    assert names[0] == "2024-01-30_Stadtwerke_Stromabrechnung.pdf"
    assert "2024-07-15_Stadtwerke_Abschlag.pdf" in names
    assert "2023-05-02_HUK_Police.pdf" not in names  # nichts gemeinsam
    assert "irgendwo.pdf" not in names
    assert "2021-02-02_Kim_Zeugnis.pdf" not in names
    best = found[0]
    assert best.folder == "Ablage/Steuer 2024/Energie" and best.year == 2024
    index_doc = next(d for d in found if d.filename.endswith("Abschlag.pdf"))
    assert index_doc.folder == "Ablage/Steuer 2024/Energie" and index_doc.year == 2024


def test_leer_ohne_treffer_oder_bei_db_fehler(roots):
    assert sd.find_similar_documents(TEXT, [], roots, db=_FakeDb()) == []

    class _Kaputt:
        def get_history_brief(self, limit=0): raise RuntimeError("db weg")
        def get_indexed_documents_brief(self, limit=0): raise RuntimeError("db weg")

    assert sd.find_similar_documents(TEXT, ["rechnung"], roots, db=_Kaputt()) == []


# --- Prompt --------------------------------------------------------------------

def test_prompt_abschnitt_mit_jahresregel(roots):
    similar = [sd.SimilarDocument("2024-01-30_Stadtwerke_Stromabrechnung.pdf", "Ablage/Steuer 2024/Energie", 2024, 5)]
    info = sd.describe_similar_for_prompt(similar, 2026, roots)
    assert '"2024-01-30_Stadtwerke_Stromabrechnung.pdf" (Dokument von 2024) liegt in "Ablage/Steuer 2024/Energie"' in info
    assert 'für ein Dokument von 2026 entspricht das "Ablage/Steuer 2026/Energie"' in info
    assert "Ordner mit Jahreszahl gelten nur für Dokumente dieses Jahres" in info
    assert "stammt laut Texterkennung aus 2026" in info
    assert '"zielordner"' in info
    assert sd.describe_similar_for_prompt([], 2026, roots) == ""


def test_filename_prompt_enthaelt_abschnitt_und_zielordner_feld():
    from src.ml.llm_provider import LLMConfig, LLMProvider

    class _Stub(LLMProvider):
        def _initialize_client(self): pass
        def classify_document(self, *a, **k): pass
        def suggest_filename(self, *a, **k): pass
        def is_available(self): return True
        def answer_with_context(self, *a, **k): return ""

    p = _Stub(LLMConfig(api_key="x", model="m"))
    ohne = p._build_filename_prompt("Text", "scan.pdf")
    assert "zielordner" not in ohne
    mit = p._build_filename_prompt("Text", "scan.pdf", similar_info="\nÄHNLICHE DOKUMENTE: Beispiel")
    assert "ÄHNLICHE DOKUMENTE: Beispiel" in mit
    assert '"zielordner": "Ablageort wie in den Beispielen, Jahr an dieses Dokument angepasst, oder UNBEKANNT"' in mit


# --- KI-Antwort -> Ordnervorschlag ---------------------------------------------

def test_zielordner_aus_ki_antwort_mit_jahreskorrektur(roots):
    ziel = roots[0]
    # KI nennt den Ordner des Beispiels (2024), das Dokument ist von 2026
    s = sd.folder_suggestion_from_metadata({"zielordner": "Ablage/Steuer 2024/Energie"}, roots, 2026)
    assert s.folder_path == ziel / "Steuer 2026" / "Energie"
    assert s.relative_path == "Ablage/Steuer 2026/Energie"
    assert "KI" in s.reason and s.confidence == 0.85
    # ohne Jahr: Ordner wie genannt
    s = sd.folder_suggestion_from_metadata({"zielordner": "Ablage/Steuer 2024/Energie"}, roots, None)
    assert s.folder_path == ziel / "Steuer 2024" / "Energie"
    # unbekannt / fehlend / erfunden
    assert sd.folder_suggestion_from_metadata({"zielordner": "Ablage/Gibt es nicht"}, roots, 2026) is None
    assert sd.folder_suggestion_from_metadata({"korrespondent": "x"}, roots, 2026) is None
    assert sd.folder_suggestion_from_metadata(None, roots, 2026) is None


def test_merge_setzt_ki_ordner_nach_vorn_oder_bestaetigt(roots):
    ziel = roots[0]
    a = Suggestion(ziel / "Versicherung", "Versicherung", 0.6, "Ähnlicher Inhalt", "Ablage/Versicherung")
    b = Suggestion(ziel / "Steuer 2026" / "Energie", "Energie", 0.5, "Jahr 2026", "Ablage/Steuer 2026/Energie")
    ki = Suggestion(ziel / "Steuer 2026" / "Energie", "Energie", 0.85, "KI: ähnliche Dokumente liegen dort",
                    "Ablage/Steuer 2026/Energie")

    merged = sd.merge_folder_suggestion([a, b], ki)
    assert [s.folder_name for s in merged] == ["Energie", "Versicherung"]
    assert merged[0].confidence == 0.9 and merged[0].reason == "Jahr 2026 + KI bestätigt"

    ki2 = Suggestion(ziel / "Steuer 2024" / "Energie", "Energie", 0.85, "KI: ähnliche Dokumente liegen dort",
                     "Ablage/Steuer 2024/Energie")
    merged = sd.merge_folder_suggestion([a], ki2)
    assert merged[0] is ki2 and merged[1] is a
    assert sd.merge_folder_suggestion([a], None) == [a]


# --- Einbindung im Hybrid-Klassifikator ----------------------------------------

def test_hybrid_reicht_abschnitt_an_provider(monkeypatch, roots):
    from src.ml import hybrid_classifier as hc_mod
    from src.ml.llm_provider import LLMResponse

    captured = {}

    class _Provider:
        def suggest_filename(self, **kw):
            captured.update(kw)
            return LLMResponse(success=True, filename_suggestion="2026-01-31_Stadtwerke.pdf",
                               confidence=0.9, metadata={"zielordner": "Ablage/Steuer 2026/Energie"})

    class _Cfg:
        def get_target_folders(self): return roots

    db = _FakeDb(history=[{
        "new_filename": "2024-01-30_Stadtwerke_Stromabrechnung.pdf", "original_filename": "s.pdf",
        "keywords": "rechnung,strom", "korrespondent": "Stadtwerke", "steuerjahr": "2024",
        "detected_date": None, "target_relative_path": "Ablage/Steuer 2024/Energie", "target_folder": ""}])
    monkeypatch.setattr(hc_mod, "get_config", lambda: _Cfg())
    monkeypatch.setattr(hc_mod, "get_database", lambda: db)

    hc = hc_mod.HybridClassifier.__new__(hc_mod.HybridClassifier)
    hc.llm_provider = _Provider()
    hc.llm_enabled = True
    hc.total_tokens_used = 0
    monkeypatch.setattr(hc, "_rename_examples", lambda text, keywords: [])

    result = hc._get_llm_filename_suggestion(TEXT, "scan.pdf", ["rechnung", "strom"], "2026-01-31", None)
    assert result.metadata["zielordner"] == "Ablage/Steuer 2026/Energie"
    info = captured["similar_info"]
    assert '"2024-01-30_Stadtwerke_Stromabrechnung.pdf" (Dokument von 2024) liegt in "Ablage/Steuer 2024/Energie"' in info
    assert 'entspricht das "Ablage/Steuer 2026/Energie"' in info


def test_datenbank_liefert_kurzlisten(tmp_path):
    from src.utils.database import Database
    db = Database(db_path=str(tmp_path / "t.db"))
    db.add_sorting_entry(
        original_filename="scan.pdf", original_path=str(tmp_path / "scan.pdf"),
        target_folder=str(tmp_path / "Ablage" / "Steuer 2024" / "Energie"), target_folder_name="Energie",
        extracted_text="Stadtwerke Rechnung", keywords=["rechnung", "strom"], detected_date="2024-01-30",
        new_filename="2024-01-30_Stadtwerke.pdf", target_relative_path="Ablage/Steuer 2024/Energie",
    )
    db.index_document(
        file_path=str(tmp_path / "Ablage" / "Versicherung" / "police.pdf"), filename="police.pdf",
        extracted_text="HUK Police", keywords="versicherung", korrespondent="HUK", steuerjahr="2023",
    )
    hist = db.get_history_brief()
    assert hist[0]["new_filename"] == "2024-01-30_Stadtwerke.pdf"
    assert hist[0]["target_relative_path"] == "Ablage/Steuer 2024/Energie"
    assert hist[0]["keywords"] == "rechnung,strom"
    idx = db.get_indexed_documents_brief()
    assert idx[0]["filename"] == "police.pdf" and idx[0]["korrespondent"] == "HUK"
    assert idx[0]["file_path"].endswith("police.pdf")

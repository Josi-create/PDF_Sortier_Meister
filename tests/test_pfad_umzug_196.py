"""Issue #196: gespeicherte Pfade ziehen mit, wenn ein Ordner verschoben wird."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core import pfad_umzug
from src.utils.config import Config
from src.utils.database import Database


@pytest.fixture
def db(tmp_path):
    return Database(db_path=tmp_path / "t.db")


@pytest.fixture
def config(tmp_path):
    return Config(config_path=tmp_path / "config.json")


class FakeCache:
    def __init__(self):
        self.gesehen = []

    def pfade_umziehen(self, paare):
        self.gesehen = list(paare)
        return len(self.gesehen)


def test_ersetzen_nur_echte_praefixe(tmp_path):
    alt = tmp_path / "Ordner"
    neu = tmp_path / "Neu" / "Ordner"
    assert pfad_umzug.ersetzen(alt, alt, neu) == str(neu)
    assert pfad_umzug.ersetzen(alt / "Sub" / "a.pdf", alt, neu) == str(neu / "Sub" / "a.pdf")
    assert pfad_umzug.ersetzen(tmp_path / "Ordner 2", alt, neu) is None  # nur ein aehnlicher Name
    assert pfad_umzug.ersetzen(tmp_path / "Anderer", alt, neu) is None


def test_config_zielordner_zuletzt_und_favoriten_ziehen_um(tmp_path, config):
    alt = tmp_path / "Versicherungen"
    neu = tmp_path / "Steuer 2025" / "Versicherungen"
    andere = tmp_path / "Privat"
    config.set("target_folders", [str(andere), str(alt), str(alt / "Kfz")])
    config.set("last_used_folders", [str(alt / "Kfz"), str(andere)])
    config.set("favoriten", [{"pfad": str(alt), "name": "Vers"}, {"pfad": str(andere), "name": ""}])

    ergebnis = pfad_umzug.umziehen(alt, neu, config, paare=[])

    assert [str(p) for p in config.get_target_folders()] == [str(andere), str(neu), str(neu / "Kfz")]  # Reihenfolge bleibt
    assert config.get("last_used_folders") == [str(neu / "Kfz"), str(andere)]
    assert config.get("favoriten") == [{"pfad": str(neu), "name": "Vers"}, {"pfad": str(andere), "name": ""}]
    assert ergebnis["favoriten"] == 1
    assert ergebnis["ziele"] == [(alt, neu), (alt / "Kfz", neu / "Kfz")]


def test_zusammenfuehren_in_vorhandenen_zielordner_entdoppelt_die_liste(tmp_path, config):
    alt = tmp_path / "Ordner"
    neu = tmp_path / "Z" / "Ordner"
    config.set("target_folders", [str(alt), str(neu)])
    pfad_umzug.umziehen(alt, neu, config, paare=[])
    assert config.get_target_folders() == [neu]


def test_datenbank_gelernte_zuordnungen_ziehen_um(tmp_path, config, db):
    alt = tmp_path / "Eingang" / "Versicherungen"
    neu = tmp_path / "Ablage" / "Steuer 2025" / "Versicherungen"
    root = tmp_path / "Ablage"
    config.set("target_folders", [str(root)])
    kfz = alt / "Kfz"
    db.add_sorting_entry("a.pdf", "x/a.pdf", str(alt), "Versicherungen", extracted_text="text",
                         target_relative_path="Eingang/Versicherungen")
    db.add_sorting_entry("b.pdf", "x/b.pdf", str(kfz), "Kfz", extracted_text="text")
    db.add_sorting_entry("c.pdf", "x/c.pdf", str(tmp_path / "Eingang" / "Versicherungen 2"), "Versicherungen 2")
    db.add_rename_entry("a.pdf", "A.pdf", "t", [], None, str(alt))

    pfad_umzug.umziehen(alt, neu, config, db=db, paare=[])

    ziele = {e.original_filename: (e.target_folder, e.target_folder_name, e.target_relative_path)
             for e in db.get_all_sorting_entries()}
    assert ziele["a.pdf"][:2] == (str(neu), "Versicherungen")
    assert ziele["a.pdf"][2] == "Ablage/Steuer 2025/Versicherungen"  # relativ zum Zielordner neu gebildet
    assert ziele["b.pdf"][0] == str(neu / "Kfz")
    assert ziele["c.pdf"][0] == str(tmp_path / "Eingang" / "Versicherungen 2")  # aehnlicher Name: unberuehrt
    stats = {r.path: r for r in db.get_folder_stats()}
    assert str(neu) in stats and str(alt) not in stats
    assert stats[str(neu)].name == "Versicherungen" and stats[str(neu)].parent_path == str(neu.parent)
    assert str(neu / "Kfz") in stats
    sess = db.get_session()
    try:
        from src.utils.database import RenameHistory
        assert sess.query(RenameHistory).one().target_folder == str(neu)
    finally:
        sess.close()


def test_zielordner_statistik_wird_beim_zusammenfuehren_addiert(tmp_path, config, db):
    alt = tmp_path / "A" / "Ordner"
    neu = tmp_path / "Z" / "Ordner"
    db.add_sorting_entry("a.pdf", "a", str(alt), "Ordner")
    db.add_sorting_entry("b.pdf", "b", str(alt), "Ordner")
    db.add_sorting_entry("c.pdf", "c", str(neu), "Ordner")
    pfad_umzug.umziehen(alt, neu, config, db=db, paare=[])
    stats = db.get_folder_stats()
    assert [(r.path, r.usage_count) for r in stats] == [(str(neu), 3)]


def test_pdfs_tabelle_zieht_je_datei_um_auch_mit_neuem_namen(tmp_path, config, db):
    alt = tmp_path / "A" / "Ordner"
    neu = tmp_path / "Z" / "Ordner"
    id1 = db.get_or_create_pdf_id(str(alt / "a.pdf"), "a.pdf")
    id2 = db.get_or_create_pdf_id(str(alt / "b.pdf"), "b.pdf")
    paare = [(alt / "a.pdf", neu / "a.pdf"), (alt / "b.pdf", neu / "b (2).pdf")]

    pfad_umzug.umziehen(alt, neu, config, db=db, paare=paare)

    con = sqlite3.connect(str(db.db_path))
    try:
        zeilen = dict(con.execute("SELECT pdf_id, file_path FROM pdfs").fetchall())
        namen = dict(con.execute("SELECT pdf_id, filename FROM pdfs").fetchall())
    finally:
        con.close()
    assert zeilen[id1] == str(neu / "a.pdf")
    assert zeilen[id2] == str(neu / "b (2).pdf") and namen[id2] == "b (2).pdf"


def test_nur_dateien_laesst_config_und_ordnerpfade_in_ruhe(tmp_path, config, db):
    alt = tmp_path / "Ordner"
    neu = tmp_path / "Z" / "Ordner"
    config.set("target_folders", [str(alt)])
    db.add_sorting_entry("a.pdf", "a", str(alt), "Ordner")
    cache = FakeCache()
    pfad_umzug.umziehen(alt, neu, config, db=db, pdf_cache=cache,
                        paare=[(alt / "a.pdf", neu / "a.pdf")], nur_dateien=True)
    assert config.get_target_folders() == [alt]
    assert db.get_all_sorting_entries()[0].target_folder == str(alt)
    assert cache.gesehen == [(alt / "a.pdf", neu / "a.pdf")]


def test_dateipaare_aus_dem_neuen_ordner(tmp_path):
    alt = tmp_path / "Alt"
    neu = tmp_path / "Neu"
    (neu / "Sub").mkdir(parents=True)
    (neu / "a.pdf").write_bytes(b"x")
    (neu / "Sub" / "b.pdf").write_bytes(b"x")
    assert sorted(pfad_umzug.dateipaare(alt, neu)) == sorted([
        (alt / "a.pdf", neu / "a.pdf"), (alt / "Sub" / "b.pdf", neu / "Sub" / "b.pdf")])


def test_index_meldungen_nur_auf_wunsch(tmp_path, config, monkeypatch):
    gemeldet = []
    monkeypatch.setattr(pfad_umzug, "index_melden", lambda *a: gemeldet.append(a))
    alt, neu = tmp_path / "A", tmp_path / "B"
    paare = [(alt / "a.pdf", neu / "a.pdf")]
    pfad_umzug.umziehen(alt, neu, config, paare=paare)
    assert gemeldet == []
    pfad_umzug.umziehen(alt, neu, config, paare=paare, index_melden_paare=True)
    assert gemeldet == [("datei_verschoben", str(alt / "a.pdf"), str(neu / "a.pdf"))]


def test_pdf_cache_zieht_eintraege_um(monkeypatch, tmp_path):
    """Direkt am PDFCache (persistent in tmp): Text und KI-Vorschlaege bleiben, der gespeicherte Eintrag zieht um."""
    from src.core import pdf_cache as pc
    from src.core.pdf_cache import LLMSuggestion, PDFAnalysisResult

    cache = pc.PDFCache.__new__(pc.PDFCache)
    cache._cache = {}
    cache._lock = __import__("threading").Lock()
    cache._db_auftraege = __import__("queue").Queue()  # Schreibauftraege aus dem GUI-Thread (hier keine)
    cache._persist_cache = True
    cache._db_path = tmp_path / "cache.db"
    con = sqlite3.connect(str(cache._db_path))
    con.execute("""CREATE TABLE pdf_cache (pdf_path TEXT PRIMARY KEY, extracted_text TEXT, keywords TEXT,
        dates TEXT, analyzed_at TEXT, file_modified REAL, llm_suggestions TEXT, llm_fetched INTEGER DEFAULT 0,
        ocr_alle INTEGER, ocr_gut INTEGER)""")
    con.commit()
    con.close()

    alt, neu = tmp_path / "A" / "a.pdf", tmp_path / "B" / "a (2).pdf"
    eintrag = PDFAnalysisResult(pdf_path=alt, extracted_text="Text", keywords=["k"],
                                llm_suggestions=[LLMSuggestion(filename="n.pdf")], llm_fetched=True)
    cache._cache[alt] = eintrag
    cache._save_to_db(eintrag)

    assert cache.pfade_umziehen([(alt, neu), (tmp_path / "nix.pdf", tmp_path / "nix2.pdf")]) == 1

    assert alt not in cache._cache and cache._cache[neu].extracted_text == "Text"
    assert cache._cache[neu].pdf_path == neu and cache._cache[neu].llm_fetched
    con = sqlite3.connect(str(cache._db_path))
    try:
        assert [r[0] for r in con.execute("SELECT pdf_path FROM pdf_cache")] == [str(neu)]
    finally:
        con.close()

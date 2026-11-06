"""Dokumentensuche: Uebernahme einer vorhandenen PDFsuche (finden, pruefen, uebernehmen, kopieren).

Alles synthetisch in tmp_path: ein Projektordner mit config.toml und einer
kleinen Datenbank (``helfer_suche.pdfsuche_projekt``). Weder die echte
``~/.claude.json`` noch die Aufgabenplanung werden angefasst.
"""

import json

import pytest

import helfer_suche as h
from src.search import db, indexer, migration
from src.search.konfig import norm_pfad
from src.utils.config import Config

AUFGABE_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Actions Context="Author">
    <Exec>
      <Command>{cmd}</Command>
      <Arguments>index --hintergrund</Arguments>
      <WorkingDirectory>{wd}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""


@pytest.fixture
def projekt(tmp_path):
    return h.pdfsuche_projekt(tmp_path)


@pytest.fixture
def app_data(tmp_path, monkeypatch):
    """Datenverzeichnis unter tmp_path - nie das echte %APPDATA% (Kopie der Datenbank, Standard-db_pfad)."""
    ordner = tmp_path / "AppData"
    monkeypatch.setattr(migration, "get_app_data_dir", lambda create=True: ordner)
    monkeypatch.setattr("src.search.konfig.get_app_data_dir", lambda create=True: ordner)
    return ordner


# --------------------------------------------------------------------------- Finden

def test_finde_ueber_mcp_eintrag_und_aufgabe(tmp_path, projekt, monkeypatch):
    claude_json = tmp_path / "claude.json"
    claude_json.write_text(json.dumps({"mcpServers": {"pdfsuche": {
        "type": "stdio", "command": str(projekt / ".venv" / "Scripts" / "pdfsuche-mcp.exe"), "args": []}}}),
        encoding="utf-8")
    monkeypatch.setattr(migration, "_aus_aufgabe", lambda: None)
    assert migration.finde_pdfsuche(claude_json) == [norm_pfad(str(projekt))]
    # Aufgabe nennt denselben Ordner: keine Dublette
    monkeypatch.setattr(migration, "_aus_aufgabe", lambda: str(projekt))
    assert migration.finde_pdfsuche(claude_json) == [norm_pfad(str(projekt))]
    # Ordner ohne config.toml, fehlende claude.json, Fehler in einer Quelle: alles "nicht gefunden"
    monkeypatch.setattr(migration, "_aus_aufgabe", lambda: str(tmp_path / "nix"))
    assert migration.finde_pdfsuche(tmp_path / "fehlt.json") == []

    def kaputt():
        raise OSError("schtasks fehlt")

    monkeypatch.setattr(migration, "_aus_aufgabe", kaputt)
    assert migration.finde_pdfsuche(claude_json) == [norm_pfad(str(projekt))]


def test_arbeitsverzeichnis_aus_aufgaben_xml(projekt):
    assert migration.arbeitsverzeichnis_aus_aufgabe(AUFGABE_XML.format(cmd="x.exe", wd=str(projekt))) == str(projekt)
    # Ohne WorkingDirectory: Projektordner aus dem Kommando (…/.venv/Scripts/pdfsuche.exe)
    exe = projekt / ".venv" / "Scripts" / "pdfsuche.exe"
    assert migration.arbeitsverzeichnis_aus_aufgabe(AUFGABE_XML.format(cmd=str(exe), wd="")) == str(projekt)
    assert migration.arbeitsverzeichnis_aus_aufgabe("kein xml") is None
    # schtasks schreibt UTF-16 mit BOM
    roh = AUFGABE_XML.format(cmd="x", wd=str(projekt)).encode("utf-16")
    assert migration.arbeitsverzeichnis_aus_aufgabe(migration._dekodiere(roh)) == str(projekt)


# --------------------------------------------------------------------------- Pruefen

def test_pruefen_liefert_vorschau(projekt):
    u = migration.pruefen(projekt)
    assert u.moeglich and u.db_vorhanden and u.laeuft is False and u.fehler == []
    assert u.db_pfad == norm_pfad(str(projekt / "data" / "pdfsuche.db"))
    assert u.schema_version == "1" and u.integritaet == "ok"
    assert u.zaehler["dokumente"] == 2 and u.zaehler["pro_typ"] == {"md": 1, "pdf": 1}
    assert u.konfig.aktiv is True and u.konfig.ocr_aktiv is False and u.konfig.web_port == 18425
    text = u.zusammenfassung()
    assert "Dokumente: 2" in text and "Schema-Version: 1" in text and "Fehler" not in text


def test_pruefen_fehler_ohne_config_db_oder_mit_kaputter_toml(tmp_path, projekt):
    u = migration.pruefen(tmp_path)
    assert not u.moeglich and "config.toml" in u.fehler[0] and "Fehler:" in u.zusammenfassung()
    (projekt / "config.toml").write_text('[datenbank]\npfad = "data/fehlt.db"\n', encoding="utf-8")
    u = migration.pruefen(projekt)
    assert not u.moeglich and "nicht gefunden" in u.fehler[0] and u.konfig is not None
    (projekt / "config.toml").write_text("kaputt = [", encoding="utf-8")
    assert "nicht lesbar" in migration.pruefen(projekt).fehler[0]


def test_pruefen_bei_aktivem_lauf_und_kaputter_db(projekt):
    u0 = migration.pruefen(projekt)
    assert indexer.sperre_holen(u0.konfig)
    try:
        u = migration.pruefen(projekt)
        assert u.laeuft and not u.moeglich and "aktiv" in u.fehler[0]
    finally:
        indexer.sperre_freigeben()
    (projekt / "data" / "pdfsuche.db").write_bytes(b"kein sqlite " * 100)
    u = migration.pruefen(projekt)
    assert not u.moeglich and "nicht lesbar" in u.fehler[0]


# --------------------------------------------------------------------------- Uebernehmen

def test_uebernehmen_laesst_datenbank_am_ort(tmp_path, projekt, app_data):
    cfg = Config(config_path=tmp_path / "config.json")
    u = migration.pruefen(projekt)
    k = migration.uebernehmen(u, cfg)
    assert k.aktiv and k.db_datei == projekt / "data" / "pdfsuche.db"
    s = Config(config_path=tmp_path / "config.json").get_search_config()
    assert s.aktiv is True and s.db_pfad == k.db_pfad and s.wurzeln == k.wurzeln and s.prioritaet == k.prioritaet
    con = db.verbinde(k.db_datei, nur_lesen=True)
    try:
        assert db.lies_meta(con, "migriert_von") == norm_pfad(str(projekt))
        assert db.lies_meta(con, "migriert_am")
        assert db.lies_meta(con, "schema_version") == "1"
    finally:
        con.close()
    with pytest.raises(ValueError):
        migration.uebernehmen(migration.pruefen(tmp_path), cfg)
    assert not (app_data / "suche").exists()


def test_uebernehmen_mit_kopie_prueft_die_kopie(tmp_path, projekt, app_data):
    cfg = Config(config_path=tmp_path / "config.json")
    fortschritt = []
    k = migration.uebernehmen(migration.pruefen(projekt), cfg, kopieren=True,
                              fortschritt=lambda a, b: fortschritt.append((a, b)))
    ziel = app_data / "suche" / "suche.db"
    assert k.db_pfad == "" and k.db_datei == ziel and ziel.is_file()
    assert fortschritt and fortschritt[-1][0] == fortschritt[-1][1] > 0
    assert (projekt / "data" / "pdfsuche.db").is_file() and not ziel.with_name("suche.db.teil").exists()
    con = db.verbinde(ziel, nur_lesen=True)
    try:
        assert db.status(con)["dokumente"] == 2 and db.lies_meta(con, "migriert_von") == norm_pfad(str(projekt))
    finally:
        con.close()
    # Die Quelle bleibt unangetastet (kein meta-Eintrag), das Ziel wird nicht ueberschrieben
    con = db.verbinde(projekt / "data" / "pdfsuche.db", nur_lesen=True)
    try:
        assert db.lies_meta(con, "migriert_von") is None
    finally:
        con.close()
    with pytest.raises(FileExistsError):
        migration.kopiere_db(projekt / "data" / "pdfsuche.db", ziel)

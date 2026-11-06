"""Dokumentensuche: Konsolenprogramm pdfsm-dienst, Textausgabe (ausgabe.py) und MCP-Werkzeuge."""

import asyncio
import json

import pytest

import helfer_suche as h
from src.search import Indexer, Suchindex, ausgabe, dienst, mcp_server


@pytest.fixture
def toml(tmp_path):
    ordner = tmp_path / "Ablage"
    ordner.mkdir()
    (ordner / "Rechnung.md").write_text("# Rechnung\nBetrag 49,99 Euro von Telekom", encoding="utf-8")
    h.pdf_mit_text(ordner / "Brief.pdf", ["Seite eins Brief", "Seite zwei Frist"])
    p = tmp_path / "config.toml"
    p.write_text(
        "[datenbank]\npfad = \"" + (tmp_path / "suche.db").as_posix() + "\"\n"
        "[suche]\nwurzeln = [\"" + ordner.as_posix() + "\"]\n[ocr]\naktiv = false\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def indiziert(toml):
    from src.search import konfig as konfig_modul
    konfig = konfig_modul.lade(str(toml))
    assert Indexer(konfig, synchron=True).lauf() == 0
    return konfig


def test_status_ohne_datenbank(toml, capsys):
    assert dienst.main(["--config", str(toml), "status"]) == 0
    out = capsys.readouterr().out
    assert "noch nicht vorhanden" in out


def test_suche_lesen_status(indiziert, toml, capsys):
    assert dienst.main(["--config", str(toml), "suche", "Telekom", "--typ", "md"]) == 0
    out = capsys.readouterr().out
    assert "1 Dokumente für „Telekom“" in out and "«Telekom»" in out and "Rechnung.md" in out

    assert dienst.main(["--config", str(toml), "suche", "Frist", "--json"]) == 0
    erg = json.loads(capsys.readouterr().out)
    assert erg["gesamt"] == 1 and erg["treffer"][0]["stellen"][0]["seite"] == 2
    dok_id = erg["treffer"][0]["id"]

    assert dienst.main(["--config", str(toml), "lesen", str(dok_id), "--seiten", "2"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Brief.pdf") and "--- Seite 2 ---" in out and "Seite eins" not in out

    assert dienst.main(["--config", str(toml), "lesen", "999"]) == 0
    assert "nicht gefunden" in capsys.readouterr().out

    assert dienst.main(["--config", str(toml), "status"]) == 0
    out = capsys.readouterr().out
    assert "Dokumente: 2" in out and "Letzter Lauf" in out and "fertig" in out


def test_keine_treffer_und_kuerzung(indiziert, capsys):
    idx = Suchindex(indiziert)
    assert ausgabe.ergebnisse(idx.suche("gibtesnicht"), "gibtesnicht").startswith("Keine Treffer")
    dok_id = idx.suche("Brief")["treffer"][0]["id"]
    text = ausgabe.dokument_text(idx, dok_id, max_zeichen=40)
    assert len(text) > 40 and "gekürzt" in text


def test_version_und_hilfe(capsys):
    with pytest.raises(SystemExit) as e:
        dienst.main(["--version"])
    assert e.value.code == 0
    assert capsys.readouterr().out.startswith("pdfsm-dienst ")
    assert dienst.version() != "0.0.0"


def test_index_befehl_startet_indexer(toml, monkeypatch):
    aufrufe = {}

    class FakeIndexer:
        def __init__(self, konfig, hintergrund=False, max_minuten=0, nur_leerlauf=False):
            aufrufe["init"] = (konfig.wurzeln, hintergrund, max_minuten, nur_leerlauf)

        def lauf(self, **kw):
            aufrufe["lauf"] = kw
            return 0

    monkeypatch.setattr("src.search.indexer.Indexer", FakeIndexer)
    monkeypatch.setattr("src.search.indexer.logging_einrichten", lambda konfig, konsole=True: aufrufe.setdefault("log", konsole))
    assert dienst.main(["--config", str(toml), "index", "--hintergrund", "--nur-prioritaet", "--ohne-mail",
                        "--max-minuten", "5", "--nur-leerlauf"]) == 0
    assert aufrufe["init"][1:] == (True, 5.0, True) and aufrufe["log"] is False
    assert aufrufe["lauf"] == {"nur_prioritaet": True, "ohne_ocr": False, "ohne_mail": True, "nur_pfad": None}


def test_mcp_werkzeuge(indiziert):
    pytest.importorskip("mcp")
    server = mcp_server.erstelle_server(indiziert)
    namen = {t.name for t in asyncio.run(server.list_tools())}
    assert namen == {"suche", "dokument_lesen", "index_status"}
    assert str(indiziert.wurzeln[0]) in mcp_server.beschreibung(indiziert)

    idx = Suchindex(indiziert)
    text = mcp_server.werkzeug_suche(idx, "Telekom", anzahl=500)
    assert "Rechnung.md" in text and "«Telekom»" in text
    dok_id = idx.suche("Frist")["treffer"][0]["id"]
    assert "Seite zwei Frist" in mcp_server.werkzeug_dokument_lesen(idx, dok_id, "2")
    assert "Dokumente: 2" in mcp_server.werkzeug_index_status(idx)


def test_migration_befehl(indiziert, tmp_path, capsys, monkeypatch):
    """pdfsm-dienst migration: Vorschau ohne --ja, Uebernahme mit --ja in die angegebene config.json."""
    from src.search.konfig import norm_pfad
    from src.utils.config import Config

    cfg_pfad = tmp_path / "pdfsm" / "config.json"
    # tmp_path ist hier der "Projektordner": config.toml liegt dort, die DB daneben
    assert dienst.main(["--config", str(cfg_pfad), "migration", "--von", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Dokumente: 2" in out and "--ja" in out
    assert Config(config_path=cfg_pfad).get_search_config().aktiv is False
    assert dienst.main(["--config", str(cfg_pfad), "migration", "--von", str(tmp_path), "--ja"]) == 0
    assert "bernommen" in capsys.readouterr().out
    s = Config(config_path=cfg_pfad).get_search_config()
    assert s.aktiv is True and s.db_pfad == norm_pfad(str(tmp_path / "suche.db"))
    # Ohne Fund und ohne --von: Hinweis, Rueckgabe 1
    monkeypatch.setattr("src.search.migration.finde_pdfsuche", lambda: [])
    assert dienst.main(["--config", str(cfg_pfad), "migration"]) == 1
    assert "--von" in capsys.readouterr().out

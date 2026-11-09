"""MCP-Server auf dem Stand des Chat-Werkzeugkastens (Baustein 1, docs/CHAT_MCP_PLAN.md).

Werkzeugfunktionen gegen einen kleinen Index mit Hauptdatenbank (Historie,
Korrespondenten), Werkzeugliste mit Annotationen und Aufruf ueber das
MCP-Protokoll. Muster: tests/test_suche_dienst.py.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import helfer_suche as h
import pytest

from src.search import Indexer, Suchindex, dienst, mcp_server
from src.search.mcp_server import Umgebung
from src.search.pdfsm_daten import PdfsmDaten
from src.utils.database import Database

NEU_TEXT = ["Stadtwerke Musterstadt Jahresabrechnung Strom 2025",
            "Zaehlernummer 226541 Kundennummer 4711 Abschlag 120,00 EUR"]


@pytest.fixture
def welt(tmp_path):
    """Scan-Eingang, Zielordner ``Ablage`` mit einsortierten Dokumenten, Index und Hauptdatenbank."""
    scan = tmp_path / "Scan"
    scan.mkdir()
    ablage = tmp_path / "Ablage"
    energie_24 = ablage / "Steuer 2024" / "Energie"
    energie_24.mkdir(parents=True)
    (ablage / "Steuer 2025" / "Energie").mkdir(parents=True)
    telekom = ablage / "Telekom"
    telekom.mkdir()

    h.pdf_mit_text(energie_24 / "Stadtwerke_Jahresabrechnung_Strom_2024.pdf",
                   ["Stadtwerke Musterstadt Jahresabrechnung Strom 2024 Zaehlernummer 226541"])
    h.pdf_mit_text(telekom / "Telekom_Rechnung.pdf", ["Telekom Rechnung Internet 49,95 EUR"])
    h.xlsx(telekom / "Kosten.xlsx", {"Blatt": [["Rechnung", "Telekom", 49.95]]})
    h.pdf_mit_text(scan / "Neu.pdf", NEU_TEXT)
    os.utime(scan / "Neu.pdf", (1_750_000_000, 1_750_000_000))

    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(scan), str(ablage)], prioritaet=[str(scan)])
    assert Indexer(konfig, synchron=True).lauf() == 0

    db = Database(tmp_path / "history.db", suchindex=Suchindex(konfig))
    db.add_sorting_entry("scan_7.pdf", str(scan / "scan_7.pdf"), str(energie_24), "Energie",
                         new_filename="Stadtwerke_Jahresabrechnung_Strom_2024.pdf",
                         metadata={"korrespondent": "Stadtwerke Musterstadt", "steuerjahr": "2024"})
    db.add_or_update_korrespondent("Stadtwerke Musterstadt", aliases=["SWM"], kategorie="Energie")
    db.learn_korrespondent_metadata("Stadtwerke Musterstadt", {"mwst_satz": "19"})

    umgebung = Umgebung(db_pfad=tmp_path / "history.db", zielordner=[ablage], scan_ordner=scan)
    idx = Suchindex(konfig)
    return {"konfig": konfig, "umgebung": umgebung, "idx": idx, "daten": PdfsmDaten(idx, umgebung.db_pfad),
            "scan": scan, "ablage": ablage}


def _id(idx: Suchindex, name: str) -> int:
    d = next(t for t in idx.suche("", typ="pdf,office", anzahl=50)["treffer"] if t["name"] == name)
    return int(d["id"])


def _werkzeuge(server) -> dict:
    return {t.name: t for t in asyncio.run(server.list_tools())}


# --------------------------------------------------------------------------- Werkzeugliste

def test_werkzeugliste_annotationen_und_sql_schalter(welt):
    pytest.importorskip("mcp")
    ohne = _werkzeuge(mcp_server.erstelle_server(welt["konfig"], welt["umgebung"]))
    assert set(ohne) == {"suche", "dokument_lesen", "index_status", "ordner_vorschlag", "korrespondent_info"}
    for w in ohne.values():
        assert w.annotations is not None and w.annotations.read_only_hint is True, w.name
        assert w.annotations.destructive_hint is not True
        assert w.description == w.description.strip() and w.description.splitlines()[0] == w.description.splitlines()[0].strip()
    assert set(ohne["ordner_vorschlag"].input_schema["properties"]) == {"dok_id"}
    assert set(ohne["korrespondent_info"].input_schema["properties"]) == {"name"}
    assert "'excel'" in ohne["suche"].description

    mit_sql = Umgebung(**{**welt["umgebung"].__dict__, "sql_erlaubt": True, "sql_zeitlimit_s": 7})
    mit = _werkzeuge(mcp_server.erstelle_server(welt["konfig"], mit_sql))
    assert set(mit) == set(ohne) | {"sql_abfrage"}
    sql = mit["sql_abfrage"]
    assert sql.annotations.read_only_hint is True
    assert set(sql.input_schema["properties"]) == {"sql"} and sql.input_schema["required"] == ["sql"]
    for stichwort in ("dokumente", "seiten_fts", "v_dokument_text", "7 s", "dok_id = <dokumente.id>"):
        assert stichwort in sql.description


def test_ohne_umgebung_wie_bisher_ohne_sql(welt):
    pytest.importorskip("mcp")
    namen = set(_werkzeuge(mcp_server.erstelle_server(welt["konfig"])))
    assert "sql_abfrage" not in namen and "ordner_vorschlag" in namen


def test_annotationen_fallback_fuer_alte_mcp_version():
    """Kennt ``server.tool()`` den Parameter ``annotations`` nicht, wird ohne registriert."""
    aufrufe = []

    class AlterServer:
        def tool(self, description=None):
            aufrufe.append(description)
            return lambda f: f

    @mcp_server._werkzeug(AlterServer(), annotationen=object())
    def probe() -> str:
        """Beschreibung."""
        return "ok"

    assert probe() == "ok" and aufrufe == ["Beschreibung."]


def test_beschreibung_nennt_neue_werkzeuge(welt):
    text = mcp_server.beschreibung(welt["konfig"], welt["umgebung"])
    for teil in ("'suche'", "'dokument_lesen'", "'ordner_vorschlag'", "'korrespondent_info'",
                 str(welt["scan"]), str(welt["ablage"]), "lesen nur"):
        assert teil in text, teil
    assert "sql_abfrage" not in text
    mit_sql = Umgebung(**{**welt["umgebung"].__dict__, "sql_erlaubt": True})
    assert "'sql_abfrage'" in mcp_server.beschreibung(welt["konfig"], mit_sql)
    # Ohne Umgebung (alte config.toml) wie bisher
    assert "'ordner_vorschlag'" in mcp_server.beschreibung(welt["konfig"])


# --------------------------------------------------------------------------- suche

def test_suche_versteht_typ_aliase(welt):
    idx = welt["idx"]
    nur_office = mcp_server.werkzeug_suche(idx, "Rechnung", typ="Excel")
    assert "Kosten.xlsx" in nur_office and "Telekom_Rechnung.pdf" not in nur_office
    beide = mcp_server.werkzeug_suche(idx, "Rechnung", typ="pdf, tabelle")
    assert "Kosten.xlsx" in beide and "Telekom_Rechnung.pdf" in beide
    assert mcp_server.werkzeug_suche(idx, "Rechnung", typ="video").startswith("Fehler: Unbekannter typ „video“")
    assert mcp_server.werkzeug_suche(idx, "Rechnung", von="2025-02-30").startswith("Fehler: Argument „von“")
    assert mcp_server.werkzeug_suche(idx, "Rechnung", sortierung="zufall").startswith("Fehler: Unbekannte sortierung")
    # Nur Filter ohne Suchbegriff bleibt moeglich
    assert "Kosten.xlsx" in mcp_server.werkzeug_suche(idx, "", typ="excel")


# --------------------------------------------------------------------------- ordner_vorschlag

def test_ordner_vorschlag_fuer_dokument_im_scan_eingang(welt):
    idx = welt["idx"]
    dok_id = _id(idx, "Neu.pdf")
    text = mcp_server.werkzeug_ordner_vorschlag(idx, welt["daten"], welt["umgebung"], dok_id)
    zeilen = text.splitlines()
    assert zeilen[0] == f"Ordnervorschlag für [{dok_id}] Neu.pdf"
    assert zeilen[1] == f"Pfad: {welt['scan'] / 'Neu.pdf'}"
    assert "Lage: liegt noch unsortiert im Scan-Eingang" in text
    assert f"Zielordner: Ablage ({welt['ablage']})" in text
    energie_24 = welt["ablage"] / "Steuer 2024" / "Energie"
    assert (f"- Stadtwerke_Jahresabrechnung_Strom_2024.pdf – Ordner: Ablage/Steuer 2024/Energie ({energie_24}) "
            "– Jahr: 2024") in text
    assert "eigenen Jahres" in text
    assert "Neu.pdf –" not in text  # das Dokument selbst ist nicht aehnlich


def test_ordner_vorschlag_fuer_einsortiertes_und_unbekanntes_dokument(welt):
    idx = welt["idx"]
    dok_id = _id(idx, "Telekom_Rechnung.pdf")
    text = mcp_server.werkzeug_ordner_vorschlag(idx, welt["daten"], welt["umgebung"], dok_id)
    assert f"Lage: bereits einsortiert, aktueller Ablageort: Ablage/Telekom ({welt['ablage'] / 'Telekom'})" in text
    assert "Ähnliche, bereits einsortierte Dokumente: keine gefunden." in text

    assert mcp_server.werkzeug_ordner_vorschlag(idx, welt["daten"], welt["umgebung"], 999999) == \
        "Dokument 999999 nicht gefunden."
    assert mcp_server.werkzeug_ordner_vorschlag(idx, welt["daten"], welt["umgebung"], "D3").startswith("Fehler:")
    # Ohne Zielordner und ohne Hauptdatenbank: trotzdem eine Antwort
    leer = mcp_server.werkzeug_ordner_vorschlag(idx, PdfsmDaten(idx, None), Umgebung(), _id(idx, "Neu.pdf"))
    assert "Zielordner: keine eingerichtet" in leer and "Lage: weder im Scan-Eingang" in leer


# --------------------------------------------------------------------------- korrespondent_info, sql_abfrage

def test_korrespondent_info(welt):
    daten = welt["daten"]
    text = mcp_server.werkzeug_korrespondent_info(daten, "swm")
    assert text.splitlines()[:3] == ["Korrespondent: Stadtwerke Musterstadt", "Aliase (andere Schreibweisen): SWM",
                                     "Kategorie: Energie"]
    assert "MwSt-Satz: 19" in text
    assert mcp_server.werkzeug_korrespondent_info(daten, "Nix GmbH") == "Kein Korrespondent „Nix GmbH“ bekannt."
    assert mcp_server.werkzeug_korrespondent_info(daten, " ") == "Fehler: Argument „name“ fehlt."


def test_sql_abfrage(welt):
    idx = welt["idx"]
    text = mcp_server.werkzeug_sql_abfrage(idx, "SELECT name FROM dokumente WHERE typ = 'office'")
    assert text.splitlines() == ["name", "Kosten.xlsx", "1 Zeile(n)"]
    vorher = Path(idx.db_datei).read_bytes()
    assert mcp_server.werkzeug_sql_abfrage(idx, "DELETE FROM dokumente").startswith("Fehler: Nur lesende Abfragen")
    assert mcp_server.werkzeug_sql_abfrage(idx, "SELECT 1; DROP TABLE dokumente").startswith("Fehler: Nur eine")
    assert Path(idx.db_datei).read_bytes() == vorher
    zeit = mcp_server.werkzeug_sql_abfrage(
        idx, "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT count(*) FROM c", 0.2)
    assert zeit.startswith("Fehler: Zeitlimit von 0.2 s")


# --------------------------------------------------------------------------- ueber das MCP-Protokoll

def _text(ergebnis) -> str:
    return "\n".join(getattr(c, "text", "") for c in ergebnis.content)


def test_aufruf_ueber_das_protokoll(welt):
    pytest.importorskip("mcp")
    umgebung = Umgebung(**{**welt["umgebung"].__dict__, "sql_erlaubt": True})
    server = mcp_server.erstelle_server(welt["konfig"], umgebung)
    treffer = _text(asyncio.run(server.call_tool("suche", {"abfrage": "Zaehlernummer", "typ": "pdfs"})))
    assert "Neu.pdf" in treffer
    dok_id = _id(welt["idx"], "Neu.pdf")
    assert f"[{dok_id}]" in treffer
    vorschlag = _text(asyncio.run(server.call_tool("ordner_vorschlag", {"dok_id": dok_id})))
    assert "Ablage/Steuer 2024/Energie" in vorschlag
    assert "Stadtwerke Musterstadt" in _text(asyncio.run(server.call_tool("korrespondent_info", {"name": "SWM"})))
    assert _text(asyncio.run(server.call_tool("sql_abfrage", {"sql": "SELECT count(*) FROM dokumente"}))) \
        .splitlines()[1] == "4"


# --------------------------------------------------------------------------- Umgebung aus der Konfiguration

def test_lade_umgebung_aus_config_json(tmp_path):
    ablage = tmp_path / "Ablage"
    p = tmp_path / "daten" / "config.json"
    p.parent.mkdir()
    p.write_text(json.dumps({"scan_folder": str(tmp_path / "Scan"), "target_folders": [str(ablage), ""],
                             "chat": {"sql_erlaubt": True}}), encoding="utf-8")
    u = mcp_server.lade_umgebung(str(p))
    assert u.db_pfad == tmp_path / "daten" / "history.db"
    assert u.zielordner == [ablage] and u.scan_ordner == tmp_path / "Scan" and u.sql_erlaubt is True

    p.write_text(json.dumps({}), encoding="utf-8")
    u = mcp_server.lade_umgebung(str(p))
    assert u.zielordner == [] and u.scan_ordner is None and u.sql_erlaubt is False

    # Alte PDFsuche-Konfiguration: keine Hauptdatenbank, keine Zielordner
    assert mcp_server.lade_umgebung(str(tmp_path / "config.toml")) == Umgebung()


def test_dienst_reicht_config_an_den_server(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"suche": {"aktiv": True, "db_pfad": str(tmp_path / "suche.db")}}), encoding="utf-8")
    aufrufe = []
    monkeypatch.setattr(mcp_server, "main", lambda konfig=None, config_pfad=None: aufrufe.append(config_pfad) or 0)
    assert dienst.main(["--config", str(p), "mcp"]) == 0
    assert aufrufe == [str(p)]

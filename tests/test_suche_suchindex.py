"""Dokumentensuche: Fassade Suchindex (Lesen ohne/mit Datenbank, Schreibmeldungen, Dienstaufruf)."""

import sys
from pathlib import Path

import helfer_suche as h
from src.search import Indexer, Suchindex


def test_ohne_datenbank_leere_antworten(tmp_path):
    idx = Suchindex(h.konfig_fuer(tmp_path))
    assert idx.vorhanden() is False
    assert idx.suche("x") == {"treffer": [], "gesamt": 0, "mehr": False, "abfrage": "x", "dauer_ms": 0}
    assert idx.suche("  ")["gesamt"] == 0
    assert idx.dokument(1) is None and idx.seiten_text(1) == [] and idx.volltext(1) == ""
    assert idx.text_fuer_datei(str(tmp_path / "x.pdf")) is None
    st = idx.status()
    assert st["vorhanden"] is False and st["dokumente"] == 0 and st["laeuft"] is False
    assert idx.datei_verschoben("a", "b") is False and idx.datei_geloescht("a") is False


def test_lesen_nach_lauf(tmp_path):
    ordner = tmp_path / "Ablage"
    ordner.mkdir()
    (ordner / "Rechnung.md").write_text("Rechnung von Telekom", encoding="utf-8")
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ordner)])
    assert Indexer(konfig, synchron=True).lauf() == 0
    idx = Suchindex(konfig)
    assert idx.vorhanden() is True
    erg = idx.suche("Telekom", typ="md")
    assert erg["gesamt"] == 1
    dok_id = erg["treffer"][0]["id"]
    assert idx.dokument(dok_id)["name"] == "Rechnung.md"
    assert idx.dokument_nach_pfad(str(ordner / "Rechnung.md"))["id"] == dok_id
    assert idx.seiten_text(dok_id, hervorheben="Telekom")[0]["treffer"] is True
    assert idx.volltext(dok_id) == "Rechnung von Telekom"
    assert idx.text_fuer_datei(str(ordner / "Rechnung.md"))["aktuell"] is True
    st = idx.status()
    assert st["vorhanden"] is True and st["dokumente"] == 1 and st["db_groesse"] > 0 and st["laeuft"] is False


def test_datei_verschoben_und_geloescht(tmp_path):
    ordner = tmp_path / "Ablage"
    (ordner / "Neu").mkdir(parents=True)
    (ordner / "Rechnung.md").write_text("Rechnung von Telekom", encoding="utf-8")
    (ordner / "Alt.md").write_text("alter Inhalt", encoding="utf-8")
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ordner)])
    Indexer(konfig, synchron=True).lauf()
    idx = Suchindex(konfig)
    dok_id = idx.dokument_nach_pfad(str(ordner / "Rechnung.md"))["id"]

    neu = ordner / "Neu" / "Rechnung 2024.md"
    assert idx.datei_verschoben(str(ordner / "Rechnung.md"), str(neu)) is True
    d = idx.dokument(dok_id)
    assert d["pfad"] == str(neu) and d["datei"] == str(neu) and d["name"] == "Rechnung 2024.md"
    assert d["ordner"] == str(ordner / "Neu")
    assert idx.volltext(dok_id) == "Rechnung von Telekom"
    assert idx.suche("Rechnung 2024", nur_namen=True)["gesamt"] == 1
    assert idx.datei_verschoben(str(ordner / "Rechnung.md"), str(neu)) is False   # alter Pfad unbekannt
    assert idx.datei_verschoben(str(neu), str(neu)) is False

    # Ziel existierte schon (ueberschrieben): der alte Zieleintrag weicht
    alt_id = idx.dokument_nach_pfad(str(ordner / "Alt.md"))["id"]
    assert idx.datei_verschoben(str(neu), str(ordner / "Alt.md")) is True
    assert idx.dokument(alt_id) is None and idx.dokument(dok_id)["pfad"] == str(ordner / "Alt.md")

    assert idx.datei_geloescht(str(ordner / "Alt.md")) is True
    assert idx.dokument(dok_id) is None and idx.status()["dokumente"] == 0
    assert idx.datei_geloescht(str(ordner / "Alt.md")) is False


def test_dienst_kommando_entwicklung_und_gebaut(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert Suchindex.dienst_kommando() == [sys.executable, "-m", "src.search.dienst"]
    # Gebaut: Dienst-EXE liegt neben dem Programm. Die simulierten Programmpfade
    # liegen unter tmp_path, damit der Test auf Windows und macOS gleich rechnet
    # (ein Windows-Pfad mit Backslashes hat unter POSIX keinen Ordnerteil).
    programm = tmp_path / "Programme"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(programm / "PDF_Sortier_Meister.exe"))
    monkeypatch.setattr(sys, "platform", "win32")
    assert Suchindex.dienst_kommando() == [str(programm / "pdfsm-dienstw.exe")]
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "executable", str(programm / "PDF_Sortier_Meister"))
    assert Suchindex.dienst_kommando() == [str(programm / "pdfsm-dienst")]


def test_lauf_starten_ruft_dienst(tmp_path, monkeypatch):
    konfig = h.konfig_fuer(tmp_path)
    aufrufe = []

    class FakePopen:
        def __init__(self, args, **kw):
            aufrufe.append((args, kw))

    monkeypatch.setattr("src.search.suchindex.subprocess.Popen", FakePopen)
    idx = Suchindex(konfig)
    assert idx.lauf_starten(nur_prioritaet=True, pfad=str(tmp_path), konfig_pfad="x.toml") is not None
    args, kw = aufrufe[0]
    assert args[:3] == [sys.executable, "-m", "src.search.dienst"]
    assert args[3:] == ["--config", "x.toml", "index", "--hintergrund", "--nur-prioritaet", "--pfad", str(tmp_path)]
    assert kw["stdout"] is not None
    # laeuft schon: kein zweiter Start
    monkeypatch.setattr(idx, "laeuft_gerade", lambda: True)
    assert idx.lauf_starten() is None and len(aufrufe) == 1

"""Datenquelle der Chat-Werkzeuge (Baustein 1): Database und PdfsmDaten liefern dasselbe.

``PdfsmDaten`` (Dienst, sqlite3, schreibgeschuetzt) muss sich gegen dieselbe
Datenbank genauso verhalten wie ``Database`` (Oberflaeche, SQLAlchemy), damit
MCP-Server und Chat dieselben Antworten geben.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime

import pytest

from src.rag.daten import ChatDaten
from src.search.pdfsm_daten import PdfsmDaten, aliase_lesen
from src.utils.database import Database
from tests import helfer_suche as h


@pytest.fixture
def beide(tmp_path):
    """Database mit Index, Historie und Korrespondenten; PdfsmDaten auf denselben Dateien."""
    db = Database(tmp_path / "history.db")
    ablage = tmp_path / "Ablage"
    (ablage / "Energie").mkdir(parents=True)
    (ablage / "Telekom").mkdir(parents=True)

    rechnung = h.pdf_mit_text(ablage / "Energie" / "Stadtwerke_Rechnung_2024.pdf",
                              ["Stadtwerke Musterstadt Rechnung Strom 2024 Zaehlernummer 226541"])
    os.utime(rechnung, (1_600_000_000, 1_600_000_000))
    db.index_document(str(rechnung), rechnung.name, korrespondent="Stadtwerke Musterstadt",
                      kategorie="Rechnung", steuerjahr="2024", betrag="480.00")
    telekom = h.pdf_mit_text(ablage / "Telekom" / "Telekom_Rechnung.pdf", ["Telekom Rechnung Internet 49,95 EUR"])
    db.index_document(str(telekom), telekom.name, korrespondent="Telekom", kategorie="Rechnung",
                      steuerjahr="2024", betrag="49.95")
    # Im Index ohne pdf_id, aber mit Eintrag in der Tabelle pdfs: beide holen die pdf_id von dort
    notiz = ablage / "Notiz.md"
    notiz.write_text("# Notiz\nZaehlernummer 226541 abgelesen", encoding="utf-8")
    assert db.suchindex.datei_aufnehmen(str(notiz), erzwingen=True)
    db.get_or_create_pdf_id(str(notiz), notiz.name)

    db.add_sorting_entry("scan_001.pdf", "C:/Scan/scan_001.pdf", str(ablage / "Energie"), "Energie",
                         keywords=["strom", "rechnung"], detected_date="12.03.2024",
                         new_filename="Stadtwerke_Rechnung_2024.pdf", target_relative_path="Ablage/Energie",
                         metadata={"korrespondent": "Stadtwerke Musterstadt", "steuerjahr": "2024"})
    db.add_sorting_entry("scan_002.pdf", "C:/Scan/scan_002.pdf", str(ablage / "Telekom"), "Telekom",
                         new_filename="Telekom_Rechnung.pdf")

    db.add_or_update_korrespondent("Stadtwerke Musterstadt", aliases=["SWM", "Stadtwerke MS"], kategorie="Energie",
                                   notizen="Strom und Gas")
    db.add_or_update_korrespondent("Telekom", aliases=["T-Mobile"])
    db.add_or_update_korrespondent("ista GmbH")
    db.learn_korrespondent_metadata("Stadtwerke Musterstadt",
                                    {"subject": "Energie", "mwst_satz": "19", "waehrung": "EUR"})
    db.learn_korrespondent_metadata("ista", {"subject": "Hausverwaltung", "steuerlich_absetzbar": "ja"})
    # Aeltere Datenbank mit unbereinigter Kategorie: beide bereinigen beim Lesen
    with sqlite3.connect(db.db_path) as con:
        con.execute("INSERT INTO korrespondent_metadata (korrespondent, kategorie, usage_count) "
                    "VALUES ('Haus & Grund e.V.', '{''Sonstiges''}', 1)")

    return db, PdfsmDaten(db.suchindex, db.db_path)


def test_beide_erfuellen_das_protokoll(beide):
    db, daten = beide
    assert isinstance(db, ChatDaten)
    assert isinstance(daten, ChatDaten)


def test_suche_gleich(beide):
    db, daten = beide
    faelle = [
        dict(query="226541"),
        dict(query="Rechnung", ordner="Telekom"),
        dict(query="", korrespondent="Stadtwerke Musterstadt"),
        dict(query="", steuerjahr="2024", sortierung="alt"),
        dict(query="Stadtwerke OR Telekom", typ="pdf", sortierung="neu", limit=1),
        dict(query="gibtsnicht"),
        dict(query=""),
    ]
    for argumente in faelle:
        erwartet = db.search_documents(**argumente)
        assert daten.search_documents(**argumente) == erwartet, argumente
    notiz = next(r for r in daten.search_documents(query="abgelesen"))
    assert notiz["pdf_id"] and notiz["pdf_id"] == db.get_pdf_by_path(notiz["file_path"])["pdf_id"]


def test_indizierte_dokumente_und_historie_gleich(beide):
    db, daten = beide
    assert daten.get_indexed_documents_brief() == db.get_indexed_documents_brief()
    assert len(daten.get_indexed_documents_brief()) == 2  # nur PDFs
    historie = daten.get_history_brief()
    assert historie == db.get_history_brief()
    assert [z["new_filename"] for z in historie] == ["Telekom_Rechnung.pdf", "Stadtwerke_Rechnung_2024.pdf"]
    assert historie[1]["keywords"] == "strom,rechnung" and historie[1]["korrespondent"] == "Stadtwerke Musterstadt"
    assert daten.get_history_brief(limit=1) == db.get_history_brief(limit=1)


def test_korrespondenten_gleich(beide):
    db, daten = beide
    liste = daten.list_korrespondenten()
    assert liste == db.list_korrespondenten()
    assert isinstance(liste[0]["created_at"], datetime)
    stadtwerke = daten.get_korrespondent("Stadtwerke Musterstadt")
    assert stadtwerke == db.get_korrespondent("Stadtwerke Musterstadt")
    assert stadtwerke["aliases"] == ["SWM", "Stadtwerke MS"]
    for name in ("Telekom", " Telekom ", "telekom", "", "   ", "Nix"):
        assert daten.get_korrespondent(name) == db.get_korrespondent(name), name


def test_gelernte_metadaten_gleich(beide):
    db, daten = beide
    namen = [
        "Stadtwerke Musterstadt",  # genau
        "SWM",                     # Alias -> kanonischer Name
        "stadtwerke  musterstadt.",  # gleichwertige Schreibweise
        "ista GmbH",               # Teiltreffer ("ista" steckt im Namen)
        "Haus und Grund",          # gleichwertige Schreibweise; Kategorie "{'Sonstiges'}" wird bereinigt
        "Telekom",                 # Verwaltung ja, gelernt nein
        "Unbekannt AG", "", "  ",
    ]
    for name in namen:
        assert daten.get_korrespondent_metadata(name) == db.get_korrespondent_metadata(name), name
    assert daten.get_korrespondent_metadata("SWM") == {"subject": "Energie", "waehrung": "EUR", "mwst_satz": "19"}
    assert daten.get_korrespondent_metadata("ista GmbH") == {"subject": "Hausverwaltung", "steuerlich_absetzbar": "ja"}
    assert daten.get_korrespondent_metadata("Haus und Grund") == {"subject": "Sonstiges"}
    assert daten.get_korrespondent_metadata("Telekom") is None


def test_fehlende_datenbank_liefert_leere_ergebnisse(tmp_path, beide):
    db, _ = beide
    for daten in (PdfsmDaten(db.suchindex, tmp_path / "gibtsnicht.db"), PdfsmDaten(db.suchindex, None)):
        assert daten.get_history_brief() == []
        assert daten.list_korrespondenten() == []
        assert daten.get_korrespondent("Telekom") is None
        assert daten.get_korrespondent_metadata("Telekom") is None
        # Die Suche laeuft weiter (Index ist da), nur ohne pdf_id aus der Hauptdatenbank
        assert [r["filename"] for r in daten.search_documents(query="abgelesen")] == ["Notiz.md"]
        assert daten.search_documents(query="abgelesen")[0]["pdf_id"] == ""

    ohne_index = PdfsmDaten(None, db.db_path)
    assert ohne_index.search_documents(query="Telekom") == []
    assert ohne_index.get_indexed_documents_brief() == []
    assert ohne_index.get_history_brief()  # Hauptdatenbank trotzdem lesbar


def test_fehlende_tabellen_liefern_leere_ergebnisse(tmp_path):
    pfad = tmp_path / "alt.db"
    con = sqlite3.connect(pfad)
    con.execute("CREATE TABLE sonstwas (x)")
    con.commit()
    con.close()
    daten = PdfsmDaten(None, pfad)
    assert daten.get_history_brief() == []
    assert daten.list_korrespondenten() == []
    assert daten.get_korrespondent("x") is None
    assert daten.get_korrespondent_metadata("x") is None


def test_pdfsm_daten_schreibt_nie(beide):
    """Nur-Lese-Verbindung: ein Schreibversuch scheitert, die Datei bleibt unveraendert."""
    db, daten = beide
    vorher = db.db_path.read_bytes()
    assert daten._abfrage("DELETE FROM sorting_history") == []
    assert db.db_path.read_bytes() == vorher
    assert len(db.get_history_brief()) == 2


def test_aliase_lesen():
    assert aliase_lesen(None) == [] and aliase_lesen("") == []
    assert aliase_lesen('["a", "b"]') == ["a", "b"]
    assert aliase_lesen('"einzeln"') == ["einzeln"]
    assert aliase_lesen("a, b,") == ["a", "b"]  # kein JSON: Komma-Liste
    assert aliase_lesen(["x", 1]) == ["x", "1"]
    assert Database._deserialize_aliases('["a"]') == ["a"]

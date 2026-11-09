"""Kernlogik der Werkzeuge fuer Chat und MCP (Baustein 1, src/rag/werkzeug_kern.py).

Ohne Datenbank und ohne Suchindex: die Datenquelle ist eine kleine Attrappe,
die SQL-Tests laufen gegen eine eigene SQLite-Datei.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from src.rag import werkzeug_kern as kern
from src.rag.werkzeug_kern import (
    SQL_MAX_ZEILEN,
    Dokument,
    KorrespondentInfo,
    SqlErgebnis,
    WerkzeugFehler,
)


class Daten:
    """Attrappe einer Datenquelle (:class:`src.rag.daten.ChatDaten`), nur was der Kern liest."""

    suchindex = None

    def __init__(self, historie=(), index=(), korrespondenten=(), gelernt=None, kaputt=False):
        self.historie = list(historie)
        self.index = list(index)
        self.korrespondenten = list(korrespondenten)
        self.gelernt = gelernt or {}
        self.kaputt = kaputt

    def _pruefen(self):
        if self.kaputt:
            raise RuntimeError("Platte weg")

    def search_documents(self, query, limit=50, **kw):
        self._pruefen()
        return []

    def get_history_brief(self, limit=20000):
        self._pruefen()
        return self.historie[:limit]

    def get_indexed_documents_brief(self, limit=20000):
        self._pruefen()
        return self.index[:limit]

    def get_korrespondent(self, name):
        self._pruefen()
        return next((k for k in self.korrespondenten if k["name"] == (name or "").strip()), None)

    def get_korrespondent_metadata(self, korrespondent):
        self._pruefen()
        return self.gelernt.get(korrespondent)

    def list_korrespondenten(self):
        self._pruefen()
        return list(self.korrespondenten)


# --------------------------------------------------------------------------- such_argumente

def test_such_argumente_typ_aliase_und_standardwerte():
    args = kern.such_argumente({"abfrage": "  Zaehlerstand  ", "typ": "Excel, e-mail,xlsx"})
    assert args == {"abfrage": "Zaehlerstand", "typ": "office,mail", "sortierung": "relevanz",
                    "anzahl": kern.SUCHE_ANZAHL_STANDARD}
    for alias, typ in (("word", "office"), ("odt", "office"), ("tabellen", "office"), ("emails", "mail"),
                       ("markdown", "md"), ("pdfs", "pdf"), ("PDF", "pdf"), ("pdf,office", "pdf,office")):
        assert kern.such_argumente({"abfrage": "x", "typ": alias})["typ"] == typ, alias


def test_such_argumente_filter_datum_anzahl_und_kennung():
    args = kern.such_argumente({"abfrage": "Strom", "von": "01.03.2024", "bis": "2024", "ordner": "Steuer 2024",
                                "korrespondent": "Telekom", "kategorie": "", "sortierung": "NEU", "anzahl": "500"})
    assert args["von"] == "2024-03-01" and args["bis"] == "2024-01-01"
    assert args["sortierung"] == "neu" and args["anzahl"] == kern.SUCHE_ANZAHL_MAX
    assert "kategorie" not in args
    assert kern.such_filter(args) == {"ordner": "Steuer 2024", "von": "2024-03-01", "bis": "2024-01-01",
                                      "korrespondent": "Telekom"}
    assert kern.such_kennung(args) == ("„Strom“ (sortierung=neu, ordner=Steuer 2024, von=2024-03-01, "
                                       "bis=2024-01-01, korrespondent=Telekom)")
    assert kern.such_kennung(kern.such_argumente({"abfrage": "x"})) == "„x“"
    # Eigene Grenzen (MCP: Standard 20, hoechstens 200)
    mcp = kern.such_argumente({"abfrage": "x", "anzahl": 500}, anzahl_standard=20, anzahl_max=200)
    assert mcp["anzahl"] == 200
    assert kern.such_argumente({"abfrage": "x"}, anzahl_standard=20, anzahl_max=200)["anzahl"] == 20
    assert kern.such_argumente({"abfrage": "x", "anzahl": 0})["anzahl"] == 1


@pytest.mark.parametrize("argumente, meldung", [
    ({}, "Argument „abfrage“ fehlt"),
    ({"abfrage": "   "}, "Argument „abfrage“ fehlt"),
    ({"abfrage": "x", "typ": "video"}, "Unbekannter typ „video“"),
    ({"abfrage": "x", "sortierung": "zufall"}, "Unbekannte sortierung „zufall“"),
    ({"abfrage": "x", "anzahl": "viele"}, "muss eine ganze Zahl sein"),
    ({"abfrage": "x", "von": "2025-02-30"}, "„von“ muss ein gültiges Datum"),
    ({"abfrage": "x", "bis": "gestern"}, "„bis“ muss ein gültiges Datum"),
])
def test_such_argumente_fehler(argumente, meldung):
    with pytest.raises(WerkzeugFehler, match=meldung):
        kern.such_argumente(argumente)


def test_liegt_in(tmp_path):
    scan = tmp_path / "Scan"
    (scan / "Unter").mkdir(parents=True)
    assert kern.liegt_in(scan / "a.pdf", scan)
    assert kern.liegt_in(scan / "Unter" / "a.pdf", scan)
    assert kern.liegt_in(scan, scan)
    assert not kern.liegt_in(tmp_path / "a.pdf", scan)
    assert not kern.liegt_in(scan / ".." / "a.pdf", scan)
    assert not kern.liegt_in("", scan) and not kern.liegt_in(scan / "a.pdf", None)


# --------------------------------------------------------------------------- ordner_vorschlag

TEXT = "Stadtwerke Musterstadt Jahresabrechnung Strom 2025 Zaehlernummer 226541 Abschlag"


@pytest.fixture
def ablage(tmp_path):
    ablage = tmp_path / "Ablage"
    (ablage / "Steuer 2024" / "Energie").mkdir(parents=True)
    (ablage / "Steuer 2025" / "Energie").mkdir(parents=True)
    (tmp_path / "Scan").mkdir()
    return ablage


def test_ordner_vorschlag_mit_aehnlichen_dokumenten(ablage, tmp_path):
    daten = Daten(
        historie=[{"new_filename": "Stadtwerke_Jahresabrechnung_Strom_2024.pdf", "original_filename": "scan.pdf",
                   "keywords": "", "korrespondent": "Stadtwerke Musterstadt", "steuerjahr": "2024",
                   "detected_date": "", "target_relative_path": "",
                   "target_folder": str(ablage / "Steuer 2024" / "Energie")}],
        index=[{"file_path": str(ablage / "Steuer 2025" / "Energie" / "Stadtwerke_Abschlag_2025.pdf"),
                "filename": "Stadtwerke_Abschlag_2025.pdf", "keywords": "", "korrespondent": "Stadtwerke Musterstadt",
                "steuerjahr": "2025", "target_folder": ""},
               # das Dokument selbst zaehlt nicht als aehnlich
               {"file_path": str(tmp_path / "Scan" / "Neu.pdf"), "filename": "Neu.pdf", "keywords": "",
                "korrespondent": "Stadtwerke Musterstadt", "steuerjahr": "", "target_folder": ""}],
    )
    doc = Dokument(str(tmp_path / "Scan" / "Neu.pdf"), "Neu.pdf", TEXT)
    v = kern.ordner_vorschlag(doc, daten, [ablage], tmp_path / "Scan")
    assert v.pfad == doc.pfad and v.name == "Neu.pdf"
    assert v.wurzeln == [ablage]
    assert v.sortier_vorschlaege is None  # liegen nur in der Oberflaeche vor
    assert [(s.filename, s.folder, s.year) for s in v.aehnliche] == [
        ("Stadtwerke_Jahresabrechnung_Strom_2024.pdf", "Ablage/Steuer 2024/Energie", 2024),
        ("Stadtwerke_Abschlag_2025.pdf", "Ablage/Steuer 2025/Energie", 2025),
    ]
    assert v.im_scan_eingang and v.ablageort == ""

    # Mit Vorschlaegen der Sortierlogik und Vorgabe "nicht im Scan-Eingang"
    v = kern.ordner_vorschlag(doc, daten, [ablage], tmp_path / "Scan", ["Ablage/Steuer 2025/Energie (90 %)", ""],
                              im_scan_eingang=False, limit=1)
    assert v.sortier_vorschlaege == ["Ablage/Steuer 2025/Energie (90 %)"]
    assert len(v.aehnliche) == 1
    assert not v.im_scan_eingang and v.ablageort == "Scan"  # ausserhalb der Zielordner: nur der Ordnername


def test_ordner_vorschlag_ohne_aehnliche_dokumente(ablage, tmp_path):
    abgelegt = Dokument(str(ablage / "Steuer 2024" / "Energie" / "Brief.pdf"), "Brief.pdf",
                        "Ein Text ohne bekannte Namen")
    v = kern.ordner_vorschlag(abgelegt, Daten(), [ablage], tmp_path / "Scan", [])
    assert v.aehnliche == [] and v.sortier_vorschlaege == []
    assert not v.im_scan_eingang and v.ablageort == "Ablage/Steuer 2024/Energie"

    # Ohne Text, ohne Datenquelle oder mit kaputter Datenquelle: keine aehnlichen Dokumente, kein Fehler
    ohne_text = Dokument(abgelegt.pfad, abgelegt.name, "  ")
    assert kern.ordner_vorschlag(ohne_text, Daten(), [ablage]).aehnliche == []
    assert kern.ordner_vorschlag(Dokument(abgelegt.pfad, abgelegt.name, TEXT), None, [ablage]).aehnliche == []
    kaputt = kern.ordner_vorschlag(Dokument(abgelegt.pfad, abgelegt.name, TEXT), Daten(kaputt=True), [ablage])
    assert kaputt.aehnliche == [] and kaputt.ablageort == "Ablage/Steuer 2024/Energie"
    # Ohne Zielordner und ohne Scan-Eingang
    v = kern.ordner_vorschlag(abgelegt, Daten(), [], None)
    assert v.wurzeln == [] and not v.im_scan_eingang and v.ablageort == "Energie"


# --------------------------------------------------------------------------- korrespondent_info

KORRESPONDENTEN = [
    {"name": "Stadtwerke Musterstadt", "aliases": ["SWM"], "kategorie": "Energie", "notizen": "Strom",
     "usage_count": 7},
    {"name": "Stadtwerke Nachbarort", "aliases": [], "kategorie": None, "notizen": None, "usage_count": 1},
    {"name": "Telekom", "aliases": ["T-Mobile"], "kategorie": None, "notizen": None, "usage_count": 3},
]


def test_korrespondent_info_genau_alias_teil_und_gelernt():
    daten = Daten(korrespondenten=KORRESPONDENTEN,
                  gelernt={"Stadtwerke Musterstadt": {"mwst_satz": "19", "waehrung": "EUR"},
                           "ista": {"subject": "Hausverwaltung", "steuerlich_absetzbar": "ja"}})
    info = kern.korrespondent_info(" Stadtwerke Musterstadt ", daten)
    assert info == KorrespondentInfo("Stadtwerke Musterstadt", "Stadtwerke Musterstadt", KORRESPONDENTEN[0],
                                     {"mwst_satz": "19", "waehrung": "EUR"}, [])
    assert kern.korrespondent_text(info).splitlines() == [
        "Korrespondent: Stadtwerke Musterstadt", "Aliase (andere Schreibweisen): SWM", "Kategorie: Energie",
        "Notizen: Strom", "MwSt-Satz: 19", "Währung: EUR", "Verwendet: 7-mal",
    ]
    # Alias genau (Gross-/Kleinschreibung egal) vor Teiltreffern
    assert kern.korrespondent_info("t-mobile", daten).name == "Telekom"
    # Teil des Namens: erster Treffer, die anderen als "weitere"
    info = kern.korrespondent_info("stadtwerke", daten)
    assert info.name == "Stadtwerke Musterstadt" and info.weitere == ["Stadtwerke Nachbarort"]
    assert kern.korrespondent_text(info).endswith("Weitere passende Korrespondenten: Stadtwerke Nachbarort")
    # Nur gelernt, ohne Eintrag der Verwaltung
    info = kern.korrespondent_info("ista", daten)
    assert info.bekannt and info.eintrag is None
    assert kern.korrespondent_text(info).splitlines() == [
        "Korrespondent: ista", "Kategorie (gelernt): Hausverwaltung", "Steuerlich absetzbar: ja"]


def test_korrespondent_info_unbekannt_fehlend_und_kaputt():
    unbekannt = kern.korrespondent_info("Nix GmbH", Daten(korrespondenten=KORRESPONDENTEN))
    assert not unbekannt.bekannt
    assert kern.korrespondent_text(unbekannt) == "Kein Korrespondent „Nix GmbH“ bekannt."
    assert not kern.korrespondent_info("Telekom", None).bekannt
    assert not kern.korrespondent_info("Telekom", Daten(korrespondenten=KORRESPONDENTEN, kaputt=True)).bekannt
    with pytest.raises(WerkzeugFehler, match="Argument „name“ fehlt"):
        kern.korrespondent_info("  ", Daten())


# --------------------------------------------------------------------------- SQL

@pytest.fixture
def sql_db(tmp_path) -> Path:
    pfad = tmp_path / "suche.db"
    con = sqlite3.connect(pfad)
    con.execute("CREATE TABLE dokumente (id INTEGER PRIMARY KEY, name TEXT, betrag REAL)")
    con.executemany("INSERT INTO dokumente (name, betrag) VALUES (?, ?)",
                    [("a.pdf", 10.5), ("b.pdf", None), ("c.pdf", 2.0)])
    con.commit()
    con.close()
    return pfad


@pytest.mark.parametrize("sql, meldung", [
    ("", "Leere SQL-Anweisung"),
    (" ; ", "Leere SQL-Anweisung"),
    ("INSERT INTO dokumente (name) VALUES ('x')", "muss mit SELECT oder WITH beginnen"),
    ("PRAGMA table_info(dokumente)", "muss mit SELECT oder WITH beginnen"),
    ("SELECT 1; DELETE FROM dokumente", "Nur eine einzelne Anweisung"),
    ("WITH x AS (SELECT 1) DELETE FROM dokumente", "Schlüsselwort DELETE"),
    ("SELECT * FROM dokumente WHERE 1 = 1 ATTACH DATABASE 'x' AS y", "Schlüsselwort ATTACH"),
    ("SELECT 1 UNION SELECT 2 PRAGMA journal_mode", "Schlüsselwort PRAGMA"),
    ("WITH t AS (SELECT 1) REPLACE INTO dokumente (name) VALUES ('x')", "Schlüsselwort REPLACE"),
    ("SELECT 'offen", "Unvollständige Anweisung"),
    ("SELECT 1 -- '\n; DROP TABLE dokumente", "Nur eine einzelne Anweisung"),
])
def test_sql_pruefen_lehnt_ab(sql, meldung):
    with pytest.raises(WerkzeugFehler, match=meldung):
        kern.sql_pruefen(sql)


def test_sql_pruefen_laesst_lesendes_durch():
    assert kern.sql_pruefen("  SELECT 1;  ") == "SELECT 1"
    assert kern.sql_pruefen("SELECT replace(name, 'a', 'b') FROM dokumente")
    assert kern.sql_pruefen("SELECT count(*) FROM dokumente WHERE name = 'DROP; DELETE' -- UPDATE")
    assert kern.sql_pruefen("with t as (select 1) select * from t")


def test_sql_abfrage_zeilen_kappung_und_tabelle(sql_db):
    erg = kern.sql_abfrage(sql_db, "SELECT name, betrag FROM dokumente ORDER BY id")
    assert erg == SqlErgebnis(["name", "betrag"], [("a.pdf", 10.5), ("b.pdf", None), ("c.pdf", 2.0)], False)
    assert kern.sql_tabelle(erg) == "name | betrag\na.pdf | 10.5\nb.pdf | NULL\nc.pdf | 2.0\n3 Zeile(n)"

    viele = kern.sql_abfrage(sql_db, "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 500) "
                                     "SELECT x FROM c")
    assert viele.gekappt and len(viele.zeilen) == SQL_MAX_ZEILEN
    assert kern.sql_tabelle(viele).splitlines()[-1].startswith(f"{SQL_MAX_ZEILEN} Zeile(n) - gekappt")
    assert kern.sql_tabelle(SqlErgebnis([], [], False)) == "0 Zeile(n)"


def test_sql_abfrage_prueft_selbst_und_bleibt_lesend(sql_db):
    vorher = sql_db.read_bytes()
    with pytest.raises(WerkzeugFehler, match="muss mit SELECT oder WITH beginnen"):
        kern.sql_abfrage(sql_db, "DELETE FROM dokumente")
    # Ohne Pruefung scheitert der Schreibversuch an der Nur-Lese-Verbindung
    with pytest.raises(WerkzeugFehler, match="^SQLite:"):
        kern.sql_abfrage(sql_db, "DELETE FROM dokumente", geprueft=True)
    assert sql_db.read_bytes() == vorher
    with pytest.raises(WerkzeugFehler, match="SQLite: no such table: gibtsnicht"):
        kern.sql_abfrage(sql_db, "SELECT * FROM gibtsnicht")


def test_sql_abfrage_ohne_datenbank(tmp_path):
    for pfad in (None, "", tmp_path / "fehlt.db"):
        with pytest.raises(WerkzeugFehler, match="Suchdatenbank noch nicht vorhanden"):
            kern.sql_abfrage(pfad, "SELECT 1")


@pytest.mark.parametrize("handler_schritte", [kern.SQL_HANDLER_SCHRITTE, 10**9])
def test_sql_abfrage_zeitlimit(sql_db, handler_schritte):
    """Zeitlimit greift ueber den Fortschritts-Handler und - falls der nie anschlaegt - ueber den Timer."""
    start = time.monotonic()
    with pytest.raises(WerkzeugFehler, match="Zeitlimit von 0.2 s überschritten"):
        kern.sql_abfrage(sql_db, "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT count(*) FROM c",
                         0.2, handler_schritte=handler_schritte)
    assert time.monotonic() - start < 5
    assert kern.sql_abfrage(sql_db, "SELECT 1").zeilen == [(1,)]


def test_sql_beschreibung():
    text = kern.sql_beschreibung(7, "Lies mit dokument_lesen(dok_id).")
    assert "7 s" in text and f"höchstens {SQL_MAX_ZEILEN} Zeilen" in text
    for stichwort in ("dokumente", "seiten_fts", "metadaten_fts", "v_dokument_text"):
        assert stichwort in text
    assert text.endswith("Lies mit dokument_lesen(dok_id).")

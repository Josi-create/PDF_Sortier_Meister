"""Werkzeugkasten des Chats (Issue #166/#167, Phase 2): Nummern, Suche, Lesen, Ordnervorschlag, Korrespondent, SQL.

Echte ``Database`` mit Suchindex unter ``tmp_path``, synthetische PDFs aus
``tests/helfer_suche.py``; keine Netz- und keine GUI-Abhaengigkeiten.
"""
from __future__ import annotations

import os
import time

import pytest

from src.ml.llm_provider import WerkzeugAufruf
from src.rag.bezug import Bezug
from src.rag.retrieval import RetrievedDoc
from src.rag.werkzeuge import (
    SQL_MAX_ZEILEN,
    SUCHE_MAX_ZEICHEN,
    Schritt,
    Werkzeugkasten,
)
from src.utils.config import ChatConfig
from src.utils.database import Database
from tests import helfer_suche as h

BEZUG_TEXT = (
    "Preisanpassung zum 03.05.2026 fuer Ihren Gasliefervertrag mit der Vertragsnummer G22504020299. "
    "Zaehlernummer 226541. Stadtwerke Musterstadt Jahresabrechnung Strom und Gas."
)

JAHRESABRECHNUNG = "Stadtwerke_Jahresabrechnung_Strom_2024.pdf"
STAMMDATEN = "Stadtwerke_Stammdaten.pdf"
TELEKOM = "Telekom_Rechnung_Internet.pdf"


@pytest.fixture
def sammlung(tmp_path):
    """Datenbank mit drei indexierten PDFs unter ``Ablage`` und einem nicht indexierten Bezug im Scan-Eingang."""
    db = Database(tmp_path / "t.db")
    ablage = tmp_path / "Ablage"
    energie = ablage / "Energie"
    telekom = ablage / "Telekom"
    energie.mkdir(parents=True)
    telekom.mkdir(parents=True)

    dateien = [
        (energie / JAHRESABRECHNUNG, [
            "Stadtwerke Musterstadt Jahresabrechnung Strom Vertragsnummer G22504020299 Kundennummer 4711",
            "Seite zwei: Zaehlernummer 226541 Abnahmestelle Kellermannstr. 3, 48149 Muenster",
            "Seite drei: Gesamtbetrag 480,00 EUR faellig am 15.04.2024",
        ], {"korrespondent": "Stadtwerke Musterstadt", "kategorie": "Rechnung", "steuerjahr": "2024",
            "betrag": "480.00"}, 1_600_000_000),
        (energie / STAMMDATEN, [
            "Stadtwerke Musterstadt Stammdatenblatt Zaehlernummer 226541 Netzbetreiber Stadtnetze Muenster",
        ], {"korrespondent": "Stadtwerke Musterstadt"}, 1_700_000_000),
        (telekom / TELEKOM, [
            "Telekom Rechnung Internet 49,95 EUR Kundennummer 99887 Wohnung Musterweg 1",
        ], {"korrespondent": "Telekom", "kategorie": "Rechnung", "steuerjahr": "2024", "betrag": "49.95"},
         1_650_000_000),
    ]
    for pfad, texte, meta, mtime in dateien:
        h.pdf_mit_text(pfad, texte)
        os.utime(pfad, (mtime, mtime))
        db.index_document(str(pfad), pfad.name, **meta)

    scan = tmp_path / "Scan"
    scan.mkdir()
    bezug = Bezug(pfad=scan / "Neu.pdf", text=BEZUG_TEXT, scan_ordner=scan, wurzeln=[ablage],
                  sortier_vorschlaege=["Ablage/Energie (80 %)", "Ablage/Telekom (10 %)"])
    return db, bezug


def _bezug_doc(bezug: Bezug) -> RetrievedDoc:
    return RetrievedDoc(index=1, file_path=str(bezug.pfad), filename=bezug.pfad.name, text_snippet=bezug.text,
                        rank=0, extra={"bezug": True})


def _kasten(sammlung, **kw) -> Werkzeugkasten:
    db, bezug = sammlung
    kasten = Werkzeugkasten(db, ChatConfig(), bezug=bezug, **kw)
    kasten.registriere(_bezug_doc(bezug))
    return kasten


def _aufruf(kasten: Werkzeugkasten, werkzeug: str, **argumente) -> str:
    return kasten.ausfuehren(WerkzeugAufruf(werkzeug, argumente))


def _dok_id(db: Database, name: str) -> int:
    treffer = db.search_documents(query="", korrespondent="Telekom" if "Telekom" in name else "Stadtwerke Musterstadt")
    return next(int(r["dok_id"]) for r in treffer if r["filename"] == name)


# --------------------------------------------------------------------------- Registrierung

def test_registriere_vergibt_nummern_dedupe_und_status(tmp_path):
    kasten = Werkzeugkasten(None, ChatConfig())
    a = kasten.registriere(RetrievedDoc(index=7, file_path="C:/Ablage/a.pdf", filename="a.pdf", text_snippet="", rank=1))
    b = kasten.registriere(RetrievedDoc(index=9, file_path="C:/Ablage/b.pdf", filename="b.pdf", text_snippet="", rank=2,
                                        dok_id=42, extra={"status": "gelesen"}))
    assert (a.index, b.index) == (1, 2)
    assert a.extra["status"] == "gefunden" and b.extra["status"] == "gelesen"

    # Gleicher Pfad (andere Schreibweise) -> dasselbe Dokument, kein neuer Eintrag; dok_id wird nachgetragen
    nochmal = kasten.registriere(RetrievedDoc(index=3, file_path="c:\\ablage\\A.PDF", filename="a.pdf",
                                              text_snippet="", rank=0, dok_id=11))
    assert nochmal is a and a.dok_id == 11
    # Gleiche Index-Id -> dasselbe Dokument
    assert kasten.registriere(RetrievedDoc(index=0, file_path="/anderswo/b.pdf", filename="b.pdf",
                                           text_snippet="", rank=0, dok_id=42)) is b
    assert [d.index for d in kasten.dokumente()] == [1, 2]
    assert kasten.nummer(42) == 2 and kasten.nummer(11) == 1 and kasten.nummer(999) is None

    kasten.markiere(1, "gelesen")
    kasten.markiere(1, "gefunden")  # nie zurueck
    assert a.extra["status"] == "gelesen"
    kasten.markiere(1, "zitiert")
    kasten.markiere(1, "gelesen")
    assert a.extra["status"] == "zitiert"
    kasten.markiere(2, "unsinn")
    kasten.markiere(99, "gelesen")  # unbekannte Nummer: still
    assert b.extra["status"] == "gelesen"


def test_definitionen_mit_und_ohne_sql(sammlung):
    db, bezug = sammlung
    ohne = Werkzeugkasten(db, ChatConfig(), bezug=bezug)
    assert [w.name for w in ohne.definitionen()] == ["suche", "dokument_lesen", "ordner_vorschlag", "korrespondent_info",
                                                    "vorschlag_verschieben", "vorschlag_umbenennen",
                                                    "vorschlag_metadaten"]
    mit = Werkzeugkasten(db, ChatConfig(), bezug=bezug, sql_erlaubt=True, sql_zeitlimit_s=7)
    namen = [w.name for w in mit.definitionen()]
    assert namen[-1] == "sql_abfrage"
    sql = mit.definitionen()[-1]
    assert sql.parameter["required"] == ["sql"]
    for stichwort in ("dokumente", "seiten", "v_dokument_text", "seiten_fts", "metadaten_fts", "id:", "7 s"):
        assert stichwort in sql.beschreibung
    suche = mit.definitionen()[0]
    assert suche.parameter["required"] == ["abfrage"]
    assert set(suche.parameter["properties"]) == {"abfrage", "typ", "ordner", "von", "bis", "steuerjahr", "kategorie",
                                                   "korrespondent", "sortierung", "anzahl"}
    assert "ODER" in suche.beschreibung and "*" in suche.beschreibung


# --------------------------------------------------------------------------- suche

def test_suche_registriert_treffer_und_formatiert(sammlung):
    kasten = _kasten(sammlung)
    text = _aufruf(kasten, "suche", abfrage="226541")

    assert text.startswith("2 Treffer für „226541“:")
    zeilen = text.splitlines()[1:]
    assert len(zeilen) == 2
    jahres = next(z for z in zeilen if JAHRESABRECHNUNG in z)
    assert jahres.startswith("[D") and "(PDF, " in jahres and ", S. 2)" in jahres
    assert " - Ordner: " in jahres and "Energie" in jahres
    assert "Korrespondent: Stadtwerke Musterstadt" in jahres and "Steuerjahr: 2024" in jahres
    assert "Fundstellen: " in jahres and ">>>226541<<<" in jahres

    docs = kasten.dokumente()
    assert [d.index for d in docs] == [1, 2, 3]
    assert docs[0].extra["bezug"] is True
    assert {d.filename for d in docs[1:]} == {JAHRESABRECHNUNG, STAMMDATEN}
    assert all(d.dok_id for d in docs[1:]) and all(d.extra["status"] == "gefunden" for d in docs[1:])
    # Auszug wie in Phase 1: Fundstellen + Trefferseite
    assert "Kellermannstr" in next(d for d in docs if d.filename == JAHRESABRECHNUNG).text_snippet

    schritt = kasten.protokoll[-1]
    assert schritt.werkzeug == "suche" and schritt.argumente == {"abfrage": "226541"}
    assert schritt.zusammenfassung == "Suche „226541“: 2 Treffer (D2, D3)" and schritt.dokumente == [2, 3]
    assert schritt.fehler == ""

    # Dieselben Dokumente noch einmal: gleiche Nummern, keine neuen Eintraege
    _aufruf(kasten, "suche", abfrage="Zaehlernummer")
    assert [d.index for d in kasten.dokumente()] == [1, 2, 3]
    assert kasten.protokoll[-1].dokumente == [2, 3] or sorted(kasten.protokoll[-1].dokumente) == [2, 3]


def test_suche_mit_filtern_und_deutschen_operatoren(sammlung):
    kasten = _kasten(sammlung)
    text = _aufruf(kasten, "suche", abfrage="Telekom ODER Stammdatenblatt", sortierung="neu", anzahl=5)
    assert text.startswith("2 Treffer für „Telekom ODER Stammdatenblatt“ (sortierung=neu):")
    zeilen = text.splitlines()[1:]
    assert STAMMDATEN in zeilen[0] and TELEKOM in zeilen[1]  # neueste zuerst

    text = _aufruf(kasten, "suche", abfrage="Rechnung", typ="pdf", ordner="Telekom", steuerjahr="2024")
    assert text.startswith("1 Treffer für „Rechnung“ (typ=pdf, ordner=Telekom, steuerjahr=2024):")
    assert TELEKOM in text
    assert kasten.protokoll[-1].zusammenfassung.startswith("Suche „Rechnung“ (typ=pdf, ordner=Telekom, steuerjahr=2024): 1 Treffer (D")


def test_suche_datumsfilter(sammlung):
    kasten = _kasten(sammlung)
    # mtimes: Jahresabrechnung 1_600_000_000 (Sept. 2020), Telekom 1_650_000_000 (Apr. 2022), Stammdaten 1_700_000_000 (Nov. 2023)
    text = _aufruf(kasten, "suche", abfrage="Stadtwerke", von="2023-01-01")
    assert text.startswith("1 Treffer") and STAMMDATEN in text
    text = _aufruf(kasten, "suche", abfrage="Stadtwerke", bis="2021-12-31")
    assert text.startswith("1 Treffer") and JAHRESABRECHNUNG in text
    assert _aufruf(kasten, "suche", abfrage="Stadtwerke", von="gestern").startswith("Fehler: Argument „von“")


def test_suche_ohne_treffer_typfilter_und_fehler(sammlung):
    kasten = _kasten(sammlung)
    text = _aufruf(kasten, "suche", abfrage="226541", typ="office")
    assert text.startswith("Keine Treffer für „226541“ (typ=office).")
    assert "*" in text and "ODER" in text and "weniger Wörter" in text
    assert kasten.protokoll[-1].zusammenfassung == "Suche „226541“ (typ=office): keine Treffer"
    assert kasten.protokoll[-1].dokumente == [] and kasten.protokoll[-1].fehler == ""
    assert len(kasten.dokumente()) == 1

    # "xlsx" ist seit der Review ein Alias fuer office; ein wirklich unbekannter Typ meldet den Fehler
    assert _aufruf(kasten, "suche", abfrage="x", typ="bild").startswith("Fehler: Unbekannter typ „bild“")
    assert _aufruf(kasten, "suche", abfrage="x", sortierung="zufall").startswith("Fehler: Unbekannte sortierung")
    assert _aufruf(kasten, "suche").startswith("Fehler: Argument „abfrage“ fehlt")
    assert _aufruf(kasten, "suche", abfrage="x", anzahl="viele").startswith("Fehler: Argument „anzahl“")
    assert all(s.fehler for s in kasten.protokoll[-4:])


def test_suche_kappt_lange_ausgabe(sammlung, monkeypatch):
    db, bezug = sammlung
    kasten = _kasten(sammlung)

    def viele(query, limit=50, **filters):
        return [{"file_path": f"/x/{i}.pdf", "filename": f"{i}.pdf", "text_snippet": f"{i} " + "x" * 400,
                 "typ": "pdf", "seite": 1, "datum": 0, "dok_id": 0} for i in range(limit)]

    monkeypatch.setattr(db, "search_documents", viele)
    text = _aufruf(kasten, "suche", abfrage="x", anzahl=99)
    assert len(text) <= SUCHE_MAX_ZEICHEN + 100
    assert "weitere Treffer weggelassen" in text
    assert text.startswith("20 Treffer")  # anzahl auf 20 gekappt
    gezeigt = kasten.protokoll[-1].dokumente
    assert 0 < len(gezeigt) < 20
    # Nur gezeigte Treffer sind registriert (Bezug + gezeigte)
    assert len(kasten.dokumente()) == 1 + len(gezeigt)


def test_suche_ohne_suchindex(tmp_path):
    class _OhneIndex:
        suchindex = None

    kasten = Werkzeugkasten(_OhneIndex(), ChatConfig())
    assert _aufruf(kasten, "suche", abfrage="x") == "Fehler: Suchindex nicht verfügbar."
    assert _aufruf(kasten, "dokument_lesen", dokument="id:5") == "Fehler: Suchindex nicht verfügbar."


# --------------------------------------------------------------------------- dokument_lesen

def test_dokument_lesen_nummer_und_seitenbereich(sammlung):
    kasten = _kasten(sammlung)
    _aufruf(kasten, "suche", abfrage="226541")
    nummer = next(d.index for d in kasten.dokumente() if d.filename == JAHRESABRECHNUNG)

    text = _aufruf(kasten, "dokument_lesen", dokument=f"D{nummer}")
    assert text.startswith(f"[D{nummer}]\n# {JAHRESABRECHNUNG}")
    assert "--- Seite 1 ---" in text and "--- Seite 3 ---" in text and "Gesamtbetrag 480,00" in text
    assert kasten.dokumente()[nummer - 1].extra["status"] == "gelesen"
    assert kasten.protokoll[-1].zusammenfassung.startswith(f"D{nummer} gelesen, ")
    assert kasten.protokoll[-1].dokumente == [nummer]

    text = _aufruf(kasten, "dokument_lesen", dokument=nummer, seiten="2-3")
    assert "--- Seite 2 ---" in text and "--- Seite 3 ---" in text and "--- Seite 1 ---" not in text
    assert "(Seiten 2-3)" in kasten.protokoll[-1].zusammenfassung

    text = _aufruf(kasten, "dokument_lesen", dokument=f"[D{nummer}]", seiten="2", max_zeichen=120)
    assert "Zaehlernummer 226541" in text or "gekürzt" in text
    assert "[… gekürzt" in text

    assert _aufruf(kasten, "dokument_lesen", dokument=f"D{nummer}", seiten="b-c").startswith("Fehler: Argument „seiten“")


def test_dokument_lesen_per_index_id(sammlung):
    db, bezug = sammlung
    kasten = _kasten(sammlung)
    dok_id = _dok_id(db, TELEKOM)
    assert kasten.nummer(dok_id) is None

    text = _aufruf(kasten, "dokument_lesen", dokument=f"id:{dok_id}")
    assert text.startswith("[D2]\n# " + TELEKOM) and "Kundennummer 99887" in text
    doc = kasten.dokumente()[1]
    assert doc.dok_id == dok_id and doc.korrespondent == "Telekom" and doc.betrag == "49.95"
    assert doc.extra["status"] == "gelesen" and kasten.nummer(dok_id) == 2

    # Noch einmal per Id oder Suche: dieselbe Nummer
    assert _aufruf(kasten, "dokument_lesen", dokument=f"id: {dok_id}").startswith("[D2]")
    _aufruf(kasten, "suche", abfrage="Telekom")
    assert [d.index for d in kasten.dokumente()] == [1, 2]


def test_dokument_lesen_unbekannt(sammlung):
    kasten = _kasten(sammlung)
    assert _aufruf(kasten, "dokument_lesen", dokument="D7") == "Fehler: Unbekanntes Dokument D7 - bekannt sind D1 bis D1."
    assert _aufruf(kasten, "dokument_lesen", dokument="id:999999") == "Fehler: Kein Dokument mit der Index-Id 999999."
    assert _aufruf(kasten, "dokument_lesen", dokument="Telekom.pdf").startswith("Fehler: Unverständliche Dokumentangabe")
    assert _aufruf(kasten, "dokument_lesen").startswith("Fehler: Argument „dokument“ fehlt")
    assert [s.fehler != "" for s in kasten.protokoll] == [True] * 4
    assert kasten.protokoll[0].zusammenfassung.startswith("dokument_lesen: Fehler - Unbekanntes Dokument D7")


def test_dokument_lesen_bezug_ohne_index_nimmt_text_aus_dem_chat(sammlung):
    kasten = _kasten(sammlung)
    text = _aufruf(kasten, "dokument_lesen", dokument="D1", seiten="2")
    assert text.startswith("[D1]\n# Neu.pdf")
    assert "noch nicht im Suchindex" in text and "keine Seitenauswahl" in text
    assert "G22504020299" in text
    assert kasten.dokumente()[0].extra["status"] == "gelesen"

    # Volltext aus dem Kontext hat Vorrang vor dem Auszug
    kasten.dokumente()[0].extra["volltext"] = "VOLLER TEXT"
    assert "VOLLER TEXT" in _aufruf(kasten, "dokument_lesen", dokument=1)


def test_dokument_lesen_bezug_der_inzwischen_im_index_ist(sammlung):
    db, bezug = sammlung
    kasten = _kasten(sammlung)
    h.pdf_mit_text(bezug.pfad, ["Seite eins des Bezugs", "Seite zwei des Bezugs"])
    db.index_document(str(bezug.pfad), bezug.pfad.name)

    text = _aufruf(kasten, "dokument_lesen", dokument="D1", seiten="2")
    assert "--- Seite 2 ---" in text and "Seite zwei des Bezugs" in text and "Seite eins" not in text
    assert kasten.dokumente()[0].dok_id > 0


# --------------------------------------------------------------------------- ordner_vorschlag

def test_ordner_vorschlag_fuer_den_bezug(sammlung):
    kasten = _kasten(sammlung)
    text = _aufruf(kasten, "ordner_vorschlag")
    zeilen = text.splitlines()
    assert zeilen[0] == "Ordnervorschlag für [D1] Neu.pdf:"
    assert "Zielordner: Ablage" in text
    assert "Vorschläge der Sortierlogik (bester zuerst): Ablage/Energie (80 %); Ablage/Telekom (10 %)" in text
    assert "Ähnliche, bereits einsortierte Dokumente" in text
    assert f"- {JAHRESABRECHNUNG} - Ordner: Ablage/Energie - Jahr: 2024" in text
    assert f"- {STAMMDATEN} - Ordner: Ablage/Energie" in text
    assert TELEKOM not in text
    assert "eigenen Jahres" in text
    assert "Das Bezugsdokument liegt noch unsortiert im Scan-Eingang" in text
    assert kasten.protokoll[-1].zusammenfassung == "Ordnervorschlag für D1: 2 Vorschläge, 2 ähnliche Dokumente"
    assert kasten.protokoll[-1].dokumente == [1]


def test_ordner_vorschlag_fuer_ein_anderes_dokument(sammlung):
    kasten = _kasten(sammlung)
    _aufruf(kasten, "suche", abfrage="Stammdatenblatt")
    nummer = next(d.index for d in kasten.dokumente() if d.filename == STAMMDATEN)
    text = _aufruf(kasten, "ordner_vorschlag", dokument=f"D{nummer}")
    assert text.startswith(f"Ordnervorschlag für [D{nummer}] {STAMMDATEN}:")
    assert "Vorschläge der Sortierlogik: keiner (liegen nur für das Bezugsdokument vor)" in text
    assert f"- {JAHRESABRECHNUNG} - Ordner: Ablage/Energie" in text  # Volltext aus dem Index
    assert f"- {STAMMDATEN}" not in text  # das Dokument selbst nicht
    assert "Das Dokument liegt nicht im Scan-Eingang; aktueller Ablageort: Ablage/Energie" in text
    assert _aufruf(kasten, "ordner_vorschlag", dokument="D9").startswith("Fehler: Unbekanntes Dokument D9")


def test_ordner_vorschlag_ohne_bezug_und_ohne_vorschlaege(sammlung):
    db, bezug = sammlung
    kasten = Werkzeugkasten(db, ChatConfig(), wurzeln=[bezug.wurzeln[0]], scan_ordner=bezug.scan_ordner)
    assert _aufruf(kasten, "ordner_vorschlag").startswith("Fehler: Kein Bezugsdokument im Chat")
    doc = kasten.registriere(RetrievedDoc(index=0, file_path=str(bezug.pfad), filename="Neu.pdf",
                                          text_snippet="Nur Text ohne Namen bekannter Dokumente", rank=0))
    text = _aufruf(kasten, "ordner_vorschlag", dokument=doc.index)
    assert "Vorschläge der Sortierlogik: keiner" in text
    assert "Ähnliche, bereits einsortierte Dokumente: keine gefunden." in text
    assert "liegt noch unsortiert im Scan-Eingang" in text  # scan_ordner des Kastens, ohne Bezug


# --------------------------------------------------------------------------- korrespondent_info

def test_korrespondent_info(sammlung):
    db, bezug = sammlung
    db.add_or_update_korrespondent("Stadtwerke Musterstadt", aliases=["SWM", "Stadtwerke MS"], kategorie="Energie",
                                   notizen="Strom und Gas der Wohnung")
    db.learn_korrespondent_metadata("Stadtwerke Musterstadt",
                                    {"mwst_satz": "19", "waehrung": "EUR", "steuerlich_absetzbar": "ja"})
    db.add_or_update_korrespondent("Telekom", aliases=["T-Mobile"])
    kasten = _kasten(sammlung)

    text = _aufruf(kasten, "korrespondent_info", name="Stadtwerke Musterstadt")
    assert text.splitlines() == [
        "Korrespondent: Stadtwerke Musterstadt",
        "Aliase (andere Schreibweisen): SWM, Stadtwerke MS",
        "Kategorie: Energie",
        "Notizen: Strom und Gas der Wohnung",
        "MwSt-Satz: 19",
        "Steuerlich absetzbar: ja",
        "Währung: EUR",
        "Verwendet: 0-mal",
    ]
    assert kasten.protokoll[-1].zusammenfassung == "Korrespondent „Stadtwerke Musterstadt“: Stadtwerke Musterstadt"

    # Alias (Gross-/Kleinschreibung egal) und Teil des Namens
    assert _aufruf(kasten, "korrespondent_info", name="swm").startswith("Korrespondent: Stadtwerke Musterstadt")
    assert _aufruf(kasten, "korrespondent_info", name="musterstadt").startswith("Korrespondent: Stadtwerke Musterstadt")
    text = _aufruf(kasten, "korrespondent_info", name="t-mobile")
    assert text.startswith("Korrespondent: Telekom") and "Aliase (andere Schreibweisen): T-Mobile" in text
    assert "Kategorie: unbekannt" in text

    assert _aufruf(kasten, "korrespondent_info", name="Nix GmbH") == "Kein Korrespondent „Nix GmbH“ bekannt."
    assert kasten.protokoll[-1].zusammenfassung == "Korrespondent „Nix GmbH“: unbekannt"
    assert _aufruf(kasten, "korrespondent_info").startswith("Fehler: Argument „name“ fehlt")


# --------------------------------------------------------------------------- sql_abfrage

def test_sql_select_und_with_liefern_zeilen(sammlung):
    kasten = _kasten(sammlung, sql_erlaubt=True)
    text = _aufruf(kasten, "sql_abfrage", sql="SELECT name, korrespondent, betrag FROM dokumente ORDER BY name;")
    zeilen = text.splitlines()
    assert zeilen[0] == "name | korrespondent | betrag"
    assert zeilen[1] == f"{JAHRESABRECHNUNG} | Stadtwerke Musterstadt | 480.0"
    assert zeilen[2] == f"{STAMMDATEN} | Stadtwerke Musterstadt | NULL"
    assert zeilen[3] == f"{TELEKOM} | Telekom | 49.95"
    assert zeilen[4] == "3 Zeile(n)"
    assert kasten.protokoll[-1].zusammenfassung == "SQL: 3 Zeilen" and kasten.protokoll[-1].dokumente == []

    text = _aufruf(kasten, "sql_abfrage",
                   sql="WITH t AS (SELECT count(*) AS n, sum(betrag) AS s FROM dokumente) SELECT n, s FROM t")
    assert text.splitlines() == ["n | s", "3 | 529.95", "1 Zeile(n)"]

    # replace() als Funktion ist erlaubt, FTS-Abfragen auch
    text = _aufruf(kasten, "sql_abfrage",
                   sql="SELECT replace(name, '_', ' ') FROM dokumente WHERE name LIKE 'Telekom%'")
    assert "Telekom Rechnung Internet.pdf" in text
    text = _aufruf(kasten, "sql_abfrage", sql="SELECT d.id, s.seite FROM seiten_fts JOIN seiten s ON s.id = seiten_fts.rowid "
                                             "JOIN dokumente d ON d.id = s.dok_id WHERE seiten_fts MATCH '226541' ORDER BY s.seite")
    assert text.endswith("2 Zeile(n)")

    # Ein Dokument aus dem Ergebnis laesst sich per id lesen
    dok_id = int(text.splitlines()[1].split(" | ")[0])
    assert _aufruf(kasten, "dokument_lesen", dokument=f"id:{dok_id}").startswith("[D2]\n# ")


def test_sql_lehnt_schreibende_und_mehrfache_anweisungen_ab(sammlung):
    db, bezug = sammlung
    kasten = _kasten(sammlung, sql_erlaubt=True)
    faelle = {
        "INSERT INTO dokumente (pfad, name) VALUES ('x', 'y')": "muss mit SELECT oder WITH beginnen",
        "PRAGMA table_info(dokumente)": "muss mit SELECT oder WITH beginnen",
        "DROP TABLE dokumente": "muss mit SELECT oder WITH beginnen",
        "DELETE FROM dokumente": "muss mit SELECT oder WITH beginnen",
        "SELECT 1; DELETE FROM dokumente": "Nur eine einzelne Anweisung",
        "SELECT 1; SELECT 2;": "Nur eine einzelne Anweisung",
        "WITH x AS (SELECT 1) DELETE FROM dokumente": "Schlüsselwort DELETE",
        "SELECT * FROM dokumente WHERE 1 = 1 ATTACH DATABASE 'x' AS y": "Schlüsselwort ATTACH",
        "SELECT 1 UNION SELECT 2 PRAGMA journal_mode": "Schlüsselwort PRAGMA",
        "REPLACE INTO dokumente (pfad) VALUES ('x')": "muss mit SELECT oder WITH beginnen",
        "SELECT 'unvollstaendig": "Unvollständige Anweisung",
        "": "Argument „sql“ fehlt",
    }
    for sql, erwartet in faelle.items():
        text = _aufruf(kasten, "sql_abfrage", sql=sql)
        assert text.startswith("Fehler: ") and erwartet in text, (sql, text)
    # Schluesselwoerter in Literalen stoeren nicht
    text = _aufruf(kasten, "sql_abfrage", sql="SELECT count(*) FROM dokumente WHERE name = 'DROP; DELETE' -- UPDATE")
    assert text.splitlines() == ["count(*)", "0", "1 Zeile(n)"]
    # Nichts wurde veraendert
    assert "3 | " in _aufruf(kasten, "sql_abfrage", sql="SELECT count(*), 1 FROM dokumente")


def test_sql_fehler_des_sqlite_als_text(sammlung, monkeypatch):
    kasten = _kasten(sammlung, sql_erlaubt=True)
    text = _aufruf(kasten, "sql_abfrage", sql="SELECT nix FROM gibtsnicht")
    assert text.startswith("Fehler: SQLite: no such table: gibtsnicht")
    assert kasten.protokoll[-1].fehler.startswith("SQLite:")
    # Schreibversuch, der die Pruefung umginge, scheitert an der Nur-Lese-Verbindung (query_only)
    monkeypatch.setattr(Werkzeugkasten, "_sql_pruefen", staticmethod(lambda sql: sql))
    text = _aufruf(kasten, "sql_abfrage", sql="DELETE FROM dokumente")
    assert text.startswith("Fehler: SQLite:")
    monkeypatch.undo()
    assert _aufruf(kasten, "sql_abfrage", sql="SELECT count(*) FROM dokumente").splitlines()[1] == "3"


def test_sql_zeilenkappung_und_zellenformat(sammlung):
    kasten = _kasten(sammlung, sql_erlaubt=True)
    text = _aufruf(kasten, "sql_abfrage", sql="WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 500) "
                                             "SELECT x, 'a' || x FROM c")
    zeilen = text.splitlines()
    assert zeilen[0] == "x | 'a' || x" and zeilen[1] == "1 | a1"
    assert len(zeilen) == SQL_MAX_ZEILEN + 2
    assert zeilen[-1].startswith(f"{SQL_MAX_ZEILEN} Zeile(n) - gekappt bei {SQL_MAX_ZEILEN}")
    assert kasten.protokoll[-1].zusammenfassung == f"SQL: {SQL_MAX_ZEILEN} Zeilen (gekappt)"

    text = _aufruf(kasten, "sql_abfrage", sql="SELECT NULL, x'00ff', 'a' || char(10) || 'b', 1.5")
    assert text.splitlines()[1] == "NULL | <2 Bytes> | a b | 1.5"


def test_sql_zeitlimit(sammlung):
    kasten = _kasten(sammlung, sql_erlaubt=True, sql_zeitlimit_s=0.2)
    start = time.monotonic()
    text = _aufruf(kasten, "sql_abfrage",
                   sql="WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT count(*) FROM c")
    assert time.monotonic() - start < 5
    assert text.startswith("Fehler: Zeitlimit von 0.2 s überschritten")
    assert kasten.protokoll[-1].fehler.startswith("Zeitlimit")
    # Danach geht es normal weiter
    assert _aufruf(kasten, "sql_abfrage", sql="SELECT 1").splitlines()[1] == "1"


def test_sql_nicht_freigegeben(sammlung):
    kasten = _kasten(sammlung)
    assert "sql_abfrage" not in [w.name for w in kasten.definitionen()]
    text = _aufruf(kasten, "sql_abfrage", sql="SELECT 1")
    assert text == "Fehler: SQL-Abfragen sind in den Einstellungen nicht freigegeben."
    assert kasten.protokoll[-1] == Schritt("sql_abfrage", {"sql": "SELECT 1"},
                                           "sql_abfrage: Fehler - SQL-Abfragen sind in den Einstellungen nicht freigegeben.",
                                           [], fehler="SQL-Abfragen sind in den Einstellungen nicht freigegeben.")


# --------------------------------------------------------------------------- ausfuehren allgemein

def test_ausfuehren_unbekanntes_werkzeug_und_argumente_als_json(sammlung):
    kasten = _kasten(sammlung)
    text = kasten.ausfuehren(WerkzeugAufruf("zaubern", {"a": 1}, id="x1"))
    assert text == ("Fehler: Unbekanntes Werkzeug „zaubern“. Verfügbar: suche, dokument_lesen, ordner_vorschlag, "
                    "korrespondent_info, vorschlag_verschieben, vorschlag_umbenennen, vorschlag_metadaten.")
    assert kasten.protokoll[-1].werkzeug == "zaubern" and kasten.protokoll[-1].argumente == {"a": 1}

    # Argumente als JSON-Text (manche Provider liefern sie so) und kaputte Argumente
    assert kasten.ausfuehren(WerkzeugAufruf("suche", '{"abfrage": "Telekom"}')).startswith("1 Treffer für „Telekom“")
    assert kasten.ausfuehren(WerkzeugAufruf("suche", "kein json")).startswith("Fehler: Argument „abfrage“ fehlt")
    assert kasten.ausfuehren(WerkzeugAufruf("suche", None)).startswith("Fehler: Argument „abfrage“ fehlt")


def test_ausfuehren_wirft_nie(sammlung, monkeypatch):
    db, bezug = sammlung
    kasten = _kasten(sammlung)

    def kaputt(*a, **kw):
        raise RuntimeError("Platte weg")

    monkeypatch.setattr(db, "search_documents", kaputt)
    assert _aufruf(kasten, "suche", abfrage="x") == "Fehler: Suche fehlgeschlagen: Platte weg"
    monkeypatch.setattr(db, "get_korrespondent", kaputt)
    monkeypatch.setattr(db, "list_korrespondenten", kaputt)
    monkeypatch.setattr(db, "get_korrespondent_metadata", kaputt)
    assert _aufruf(kasten, "korrespondent_info", name="x") == "Kein Korrespondent „x“ bekannt."
    monkeypatch.setattr(db.suchindex, "dokument", kaputt)
    assert _aufruf(kasten, "dokument_lesen", dokument="id:1") == "Fehler: Suchindex nicht lesbar: Platte weg"
    assert all(isinstance(s, Schritt) for s in kasten.protokoll) and len(kasten.protokoll) == 3


# --------------------------------------------------------------------------- Database.search_documents

def test_search_documents_nimmt_ordner_datum_und_sortierung_an(sammlung):
    db, bezug = sammlung
    assert [r["filename"] for r in db.search_documents(query="Rechnung", ordner="Telekom")] == [TELEKOM]
    assert [r["filename"] for r in db.search_documents(query="", ordner="Energie")] and all(
        "Energie" in r["file_path"] for r in db.search_documents(query="", ordner="Energie"))

    neu = [r["filename"] for r in db.search_documents(query="Stadtwerke OR Telekom", sortierung="neu")]
    assert neu == [STAMMDATEN, TELEKOM, JAHRESABRECHNUNG]
    alt = [r["filename"] for r in db.search_documents(query="Stadtwerke OR Telekom", sortierung="alt")]
    assert alt == list(reversed(neu))

    assert [r["filename"] for r in db.search_documents(query="", von="2022-01-01", bis="2022-12-31")] == [TELEKOM]
    # Bestehende Aufrufer ohne die neuen Parameter: unveraendert
    assert len(db.search_documents(query="Stadtwerke")) == 2
    assert db.search_documents(query="", sortierung="neu") == []  # sortierung allein ist kein Filter

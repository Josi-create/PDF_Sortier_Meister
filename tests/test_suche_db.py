"""Dokumentensuche: Datenbank, Suche (Operatoren, Umlaute, Fallback, Filter), Seiten, Status."""

import os

import pytest

from src.search import db


@pytest.fixture
def con(tmp_path):
    c = db.verbinde(tmp_path / "suche.db")
    db.init(c)
    yield c
    c.close()


def _dok(pfad, typ="pdf", fmt="pdf", datum=0.0, ordner="Ablage", **extra):
    return {"pfad": pfad, "datei": pfad, "name": pfad.replace("\\", "/").rsplit("/", 1)[-1], "ordner": ordner,
            "typ": typ, "format": fmt, "groesse": 1, "mtime_ns": 1, "datum": datum, "seiten": 1,
            "textstatus": "text", **extra}


@pytest.fixture
def gefuellt(con):
    db.speichere(con, _dok("/ablage/Rechnung Telekom.pdf", datum=1.7e9, ordner="/ablage/Steuer"),
                 [(1, "text", "Rechnung über 49,99 Euro"), (2, "text", "Kündigung der Frist")])
    db.speichere(con, _dok("/ablage/Notiz.md", typ="md", fmt="md", datum=1.6e9),
                 [(1, "text", "Müller schreibt über Bäume")])
    db.speichere(con, _dok("/ablage/Tabelle.xlsx", typ="office", fmt="xlsx", datum=1.65e9),
                 [(1, "text", "Tabellenblatt: Umsatz\nRechnung 12"), (2, "text", "Tabellenblatt: Kosten\nMiete")])
    con.commit()
    return con


def test_schema_version(con):
    assert db.lies_meta(con, "schema_version") == str(db.SCHEMA_VERSION)
    assert db.status(con)["schema_version"] == "1"


def test_speichere_ersetzt_bei_gleichem_pfad(con):
    a = db.speichere(con, _dok("/x/a.pdf"), [(1, "text", "alt")])
    b = db.speichere(con, _dok("/x/a.pdf"), [(1, "text", "neu"), (2, "text", "zwei")])
    assert a == b
    assert [r[0] for r in con.execute("SELECT text FROM seiten WHERE dok_id = ? ORDER BY seite", (a,))] == ["neu", "zwei"]
    # Pfad ist ohne Ruecksicht auf Gross-/Kleinschreibung eindeutig
    assert db.speichere(con, _dok("/X/A.PDF"), []) == a


def test_loesche_entfernt_seiten_und_fts(gefuellt):
    con = gefuellt
    assert db.suche(con, "Rechnung")["gesamt"] >= 1
    ids = [r[0] for r in con.execute("SELECT id FROM dokumente")]
    db.loesche(con, ids)
    con.commit()
    assert con.execute("SELECT count(*) FROM seiten").fetchone()[0] == 0
    assert db.suche(con, "Rechnung")["gesamt"] == 0


def test_suche_findet_text_und_markiert_fundstelle(gefuellt):
    erg = db.suche(gefuellt, "Euro")
    assert erg["gesamt"] == 1
    t = erg["treffer"][0]
    assert t["name"] == "Rechnung Telekom.pdf" and t["stellen"][0]["seite"] == 1
    assert "\x02Euro\x03" in t["stellen"][0]["text"]
    assert erg["dauer_ms"] >= 0 and erg["mehr"] is False


def test_umlaute_und_akzente_spielen_keine_rolle(gefuellt):
    assert db.suche(gefuellt, "Muller")["gesamt"] == 1
    assert db.suche(gefuellt, "müller")["gesamt"] == 1
    assert db.suche(gefuellt, "Baume")["gesamt"] == 1


def test_operatoren_deutsch_und_englisch(gefuellt):
    assert db.suche(gefuellt, "Rechnung UND Euro")["gesamt"] == 1
    assert db.suche(gefuellt, "Rechnung AND Euro")["gesamt"] == 1
    assert db.suche(gefuellt, "Rechnung ODER Bäume")["gesamt"] == 3
    assert db.suche(gefuellt, '"Kündigung der Frist"')["gesamt"] == 1
    assert db.suche(gefuellt, '"Frist der Kündigung"')["gesamt"] == 0
    assert db.suche(gefuellt, "Kündig*")["gesamt"] == 1
    assert db.suche(gefuellt, "NEAR(Rechnung Euro, 5)")["gesamt"] == 1
    assert db.suche(gefuellt, "NAHE(Rechnung Euro, 5)")["gesamt"] == 1


def test_nicht_schliesst_seiten_aus_namenstreffer_bleibt(gefuellt):
    erg = db.suche(gefuellt, "Rechnung NICHT Euro")
    # Seite 1 der PDF faellt weg (enthaelt Euro); die Tabelle trifft, und die PDF
    # bleibt ueber ihren Dateinamen "Rechnung Telekom.pdf" ohne Fundstelle im Text.
    namen = {t["name"]: t for t in erg["treffer"]}
    assert "Tabelle.xlsx" in namen
    assert namen["Rechnung Telekom.pdf"]["im_namen"] is True and namen["Rechnung Telekom.pdf"]["stellen"] == []


def test_syntaxfehler_faellt_auf_wortsuche_zurueck(gefuellt):
    erg = db.suche(gefuellt, "Rechnung (")
    assert erg["gesamt"] == 2 and erg["abfrage"] == '"Rechnung"'
    assert db.suche(gefuellt, '"')["gesamt"] == 0


def test_filter_typ_ordner_datum(gefuellt):
    assert {t["typ"] for t in db.suche(gefuellt, "Rechnung", typ="office")["treffer"]} == {"office"}
    assert db.suche(gefuellt, "Rechnung", typ="pdf,office")["gesamt"] == 2
    assert db.suche(gefuellt, "Rechnung", ordner="Steuer")["gesamt"] == 1
    # Datum: PDF 2023-11, Tabelle 2022-04, Notiz 2020-09
    assert db.suche(gefuellt, "Rechnung ODER Bäume", von="2022-01-01")["gesamt"] == 2
    assert db.suche(gefuellt, "Rechnung ODER Bäume", bis="31.12.2021")["gesamt"] == 1
    assert db.suche(gefuellt, "Rechnung ODER Bäume", von="2020", bis="2022-12-31")["gesamt"] == 2
    assert db.suche(gefuellt, "Rechnung ODER Bäume", von="2023")["gesamt"] == 1
    with pytest.raises(ValueError):
        db.suche(gefuellt, "Rechnung", von="irgendwann")


def test_sortierung_und_blaettern(gefuellt):
    neu = [t["name"] for t in db.suche(gefuellt, "Rechnung ODER Bäume", sortierung="neu")["treffer"]]
    assert neu == ["Rechnung Telekom.pdf", "Tabelle.xlsx", "Notiz.md"]
    alt = [t["name"] for t in db.suche(gefuellt, "Rechnung ODER Bäume", sortierung="alt")["treffer"]]
    assert alt == list(reversed(neu))
    seite2 = db.suche(gefuellt, "Rechnung ODER Bäume", sortierung="neu", anzahl=2, start=2)
    assert seite2["gesamt"] == 3 and [t["name"] for t in seite2["treffer"]] == ["Notiz.md"]


def test_namenstreffer_und_nur_namen(gefuellt):
    erg = db.suche(gefuellt, "Telekom")
    assert erg["gesamt"] == 1 and erg["treffer"][0]["im_namen"] is True
    assert db.suche(gefuellt, "Euro", nur_namen=True)["gesamt"] == 0
    assert db.suche(gefuellt, "Notiz", nur_namen=True)["gesamt"] == 1


def test_max_stellen_und_treffer_seiten(con):
    db.speichere(con, _dok("/x/lang.pdf"), [(i, "text", f"Seite {i} Stichwort") for i in range(1, 6)])
    con.commit()
    t = db.suche(con, "Stichwort", max_stellen=2)["treffer"][0]
    assert len(t["stellen"]) == 2 and t["treffer_seiten"] == 5


def test_seiten_text_mit_hervorhebung_und_bereich(gefuellt):
    dok_id = db.dokument_nach_pfad(gefuellt, "/ablage/Rechnung Telekom.pdf")["id"]
    seiten = db.seiten_text(gefuellt, dok_id, hervorheben="Frist")
    assert [s["seite"] for s in seiten] == [1, 2]
    assert seiten[1].get("treffer") is True and "\x02Frist\x03" in seiten[1]["text"]
    assert "treffer" not in seiten[0]
    assert [s["seite"] for s in db.seiten_text(gefuellt, dok_id, von=2, bis=2)] == [2]
    # fehlerhafte Hervorhebung stoert die Ausgabe nicht
    assert len(db.seiten_text(gefuellt, dok_id, hervorheben="Frist (")) == 2


def test_dokument_volltext_und_textstand(gefuellt, tmp_path):
    datei = tmp_path / "echt.pdf"
    datei.write_bytes(b"%PDF-1.4 inhalt")
    st = os.stat(datei)
    db.speichere(gefuellt, _dok(str(datei), groesse=st.st_size, mtime_ns=st.st_mtime_ns),
                 [(1, "text", "Eins"), (2, "ohne_text", ""), (3, "text", "Drei")])
    gefuellt.commit()
    d = db.dokument_nach_pfad(gefuellt, str(datei))
    assert db.dokument(gefuellt, d["id"])["pfad"] == str(datei)
    assert db.volltext(gefuellt, d["id"]) == "Eins\f\fDrei"

    stand = db.text_fuer_datei(gefuellt, str(datei))
    assert stand["aktuell"] is True and stand["ocr_offen"] == [2] and stand["text"] == "Eins\f\fDrei"
    datei.write_bytes(b"%PDF-1.4 inhalt geaendert")
    assert db.text_fuer_datei(gefuellt, str(datei))["aktuell"] is False
    assert db.text_fuer_datei(gefuellt, str(tmp_path / "unbekannt.pdf")) is None
    assert db.dokument(gefuellt, 999999) is None


def test_status_zaehlt(gefuellt):
    db.speichere(gefuellt, _dok("/x/scan.pdf", textstatus="ocr_ausstehend"),
                 [(1, "ohne_text", ""), (2, "text", "x")])
    gefuellt.execute("INSERT INTO laeufe (beginn, status, phase, statistik) VALUES ('2024-01-01T00:00:00', 'fertig', 'Ende', '{\"gelesen\": 4}')")
    gefuellt.commit()
    st = db.status(gefuellt)
    assert st["dokumente"] == 4 and st["pro_typ"] == {"pdf": 2, "md": 1, "office": 1}
    assert st["pro_status"] == {"text": 3, "ocr_ausstehend": 1}
    assert st["seiten"] == 7 and st["ocr_ausstehend_seiten"] == 1
    assert st["laeufe"][0]["statistik"] == {"gelesen": 4}


def test_nur_lesen_verbindung(tmp_path, gefuellt):
    ro = db.verbinde(tmp_path / "suche.db", nur_lesen=True)
    try:
        assert db.suche(ro, "Euro")["gesamt"] == 1
        with pytest.raises(Exception):
            ro.execute("DELETE FROM dokumente")
    finally:
        ro.close()

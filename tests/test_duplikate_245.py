"""Issue #245: doppelte Dateien am Inhalt erkennen (Kern ohne Qt, Pruefsumme im Suchindex).

Alle Dateien entstehen im Test unter tmp_path.
"""
from __future__ import annotations

import os
import sqlite3

import helfer_suche as h
from src.core import duplikate
from src.core.duplikate import Pruefsummen, gleiche_anderswo, gleiche_im_ordner, pruefsumme, stand_text
from src.search import db
from src.search.indexer import Indexer
from src.search.suchindex import Suchindex


def _datei(pfad, inhalt: bytes):
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(inhalt)
    return pfad


def _stand(pfad) -> str:
    st = os.stat(pfad)
    return stand_text(st.st_size, st.st_mtime_ns)


# --------------------------------------------------------------------------- Pruefsumme, Zwischenspeicher

def test_pruefsumme_haengt_nur_am_inhalt(tmp_path):
    a = _datei(tmp_path / "Foto.jpg", b"gleicher Inhalt")
    b = _datei(tmp_path / "Unterordner mit Ümlaut" / "Foto (1).jpg", b"gleicher Inhalt")
    c = _datei(tmp_path / "anders.jpg", b"gleicher Inhal!")
    assert pruefsumme(a) == pruefsumme(b) != pruefsumme(c)
    assert len(pruefsumme(a)) == 32


def test_zwischenspeicher_liest_eine_unveraenderte_datei_nur_einmal(tmp_path):
    a = _datei(tmp_path / "a.pdf", b"x" * 1000)
    speicher = Pruefsummen()
    erste = speicher.summe(a)
    assert speicher.summe(a) == erste and speicher.gerechnet == 1

    a.write_bytes(b"y" * 1000)
    os.utime(a, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    assert speicher.summe(a) != erste and speicher.gerechnet == 2


def test_zwischenspeicher_kennt_keine_fehlenden_leeren_und_nur_online_dateien(tmp_path, monkeypatch):
    speicher = Pruefsummen()
    assert speicher.summe(tmp_path / "fehlt.pdf") is None
    assert speicher.summe(_datei(tmp_path / "leer.pdf", b"")) is None
    assert speicher.summe(tmp_path) is None  # ein Ordner

    online = _datei(tmp_path / "online.pdf", b"liegt in der Cloud")
    monkeypatch.setattr(duplikate, "nur_cloud", lambda st: True)
    monkeypatch.setattr(duplikate, "pruefsumme", lambda p: (_ for _ in ()).throw(AssertionError("geoeffnet")))
    assert speicher.summe(online) is None
    assert speicher.gerechnet == 0


# --------------------------------------------------------------------------- im selben Ordner

def test_gleiche_im_ordner_findet_gruppen_und_liest_nur_gleich_grosse(tmp_path):
    a = _datei(tmp_path / "IMG-WA0001.jpg", b"Bild eins" * 50)
    b = _datei(tmp_path / "IMG-WA0001 (1).jpg", b"Bild eins" * 50)
    c = _datei(tmp_path / "Größe gleich.jpg", b"Bild zwei" * 50)      # gleich gross, anderer Inhalt
    for i in range(20):
        _datei(tmp_path / f"einzeln_{i}.pdf", b"z" * (2000 + i))      # jede Groesse nur einmal
    _datei(tmp_path / "leer1.txt", b"")
    _datei(tmp_path / "leer2.txt", b"")
    pfade = sorted(tmp_path.iterdir())

    speicher = Pruefsummen()
    gruppen = gleiche_im_ordner(pfade + [tmp_path / "gibt es nicht.pdf"], speicher)

    assert [sorted(g) for g in gruppen] == [sorted([a, b])]
    assert c not in gruppen[0]
    assert speicher.gerechnet == 3  # nur die drei gleich grossen, nicht die 20 anderen
    gleiche_im_ordner(pfade, speicher)
    assert speicher.gerechnet == 3  # beim zweiten Mal nichts neu gelesen


def test_gleiche_im_ordner_drei_gleiche_sind_eine_gruppe(tmp_path):
    pfade = [_datei(tmp_path / f"Scan_{i}.pdf", b"%PDF gleich") for i in range(3)]
    assert gleiche_im_ordner(pfade, Pruefsummen()) == [pfade]


# --------------------------------------------------------------------------- im Ziel und im Suchindex

def test_gleiche_anderswo_im_zielordner(tmp_path):
    quelle = _datei(tmp_path / "Scan" / "Foto.jpg", b"Urlaubsfoto" * 30)
    ziel = tmp_path / "Ablage" / "Fotos"
    gleich = _datei(ziel / "Foto vom Juni.jpg", b"Urlaubsfoto" * 30)
    _datei(ziel / "anderes.jpg", b"Urlaubsfot0" * 30)   # gleich gross, anderer Inhalt
    _datei(ziel / "klein.jpg", b"x")
    (ziel / "Unterordner.jpg").mkdir()

    assert gleiche_anderswo(quelle, ziel, speicher=Pruefsummen()) == [gleich]


def test_gleiche_anderswo_ohne_treffer_liest_die_quelle_nicht(tmp_path):
    quelle = _datei(tmp_path / "Scan" / "a.pdf", b"a" * 500)
    ziel = tmp_path / "Ziel"
    _datei(ziel / "b.pdf", b"b" * 501)
    speicher = Pruefsummen()
    assert gleiche_anderswo(quelle, ziel, speicher=speicher) == []
    assert gleiche_anderswo(quelle, tmp_path / "neuer Ordner, noch nicht da", speicher=speicher) == []
    assert gleiche_anderswo(tmp_path / "fehlt.pdf", ziel, speicher=speicher) == []
    assert speicher.gerechnet == 0


def test_gleiche_anderswo_nennt_die_quelle_selbst_nicht(tmp_path):
    quelle = _datei(tmp_path / "Scan" / "a.pdf", b"a" * 500)
    index = lambda groesse: [{"pfad": str(quelle), "pruefsumme": None, "pruefsumme_stand": None}]  # noqa: E731
    assert gleiche_anderswo(quelle, quelle.parent, index, Pruefsummen()) == []


def test_gespeicherte_pruefsumme_aus_dem_index_gilt_nur_zum_selben_stand(tmp_path):
    quelle = _datei(tmp_path / "Scan" / "a.pdf", b"a" * 500)
    archiv = _datei(tmp_path / "Archiv" / "2025" / "Beleg.pdf", b"b" * 500)  # gleich gross, anderer Inhalt
    summe = pruefsumme(quelle)

    # Stand passt: die gespeicherte Pruefsumme zaehlt, die Datei wird nicht gelesen
    speicher = Pruefsummen()
    index = lambda g: [{"pfad": str(archiv), "pruefsumme": summe, "pruefsumme_stand": _stand(archiv)}]  # noqa: E731
    assert gleiche_anderswo(quelle, None, index, speicher) == [archiv]
    assert speicher.gerechnet == 1  # nur die Quelle

    # Stand veraltet (Datei seit dem Indexlauf geaendert): es zaehlt der Inhalt von jetzt
    veraltet = lambda g: [{"pfad": str(archiv), "pruefsumme": summe, "pruefsumme_stand": "500:1"}]  # noqa: E731
    assert gleiche_anderswo(quelle, None, veraltet, Pruefsummen()) == []

    # ohne gespeicherte Pruefsumme (Archiv von frueher) wird die Datei gelesen
    archiv.write_bytes(b"a" * 500)
    ohne = lambda g: [{"pfad": str(archiv), "pruefsumme": None, "pruefsumme_stand": None},  # noqa: E731
                      {"pfad": str(tmp_path / "Archiv" / "geloescht.pdf"), "pruefsumme": summe,
                       "pruefsumme_stand": "500:1"}]
    assert gleiche_anderswo(quelle, None, ohne, Pruefsummen()) == [archiv]


def test_nur_online_dokument_wird_ueber_den_index_erkannt_ohne_es_zu_oeffnen(tmp_path, monkeypatch):
    quelle = _datei(tmp_path / "Scan" / "a.pdf", b"a" * 500)
    online = _datei(tmp_path / "OneDrive" / "Beleg.pdf", b"a" * 500)
    echte = duplikate.pruefsumme
    geoeffnet = []

    def lesen(pfad):
        geoeffnet.append(str(pfad))
        return echte(pfad)

    monkeypatch.setattr(duplikate, "pruefsumme", lesen)
    monkeypatch.setattr(duplikate, "nur_cloud", lambda st: st.st_ino == os.stat(online).st_ino)

    mit = lambda g: [{"pfad": str(online), "pruefsumme": echte(quelle), "pruefsumme_stand": _stand(online)}]  # noqa: E731
    assert gleiche_anderswo(quelle, None, mit, Pruefsummen()) == [online]
    ohne = lambda g: [{"pfad": str(online), "pruefsumme": None, "pruefsumme_stand": None}]  # noqa: E731
    assert gleiche_anderswo(quelle, online.parent, ohne, Pruefsummen()) == []
    assert str(online) not in geoeffnet


def test_fehler_im_index_laesst_den_vergleich_im_zielordner(tmp_path):
    quelle = _datei(tmp_path / "Scan" / "a.pdf", b"a" * 500)
    gleich = _datei(tmp_path / "Ziel" / "schon da.pdf", b"a" * 500)

    def kaputt(groesse):
        raise sqlite3.OperationalError("database is locked")

    assert gleiche_anderswo(quelle, gleich.parent, kaputt, Pruefsummen()) == [gleich]


def test_zielordner_und_index_nennen_dieselbe_datei_nur_einmal(tmp_path):
    quelle = _datei(tmp_path / "Scan" / "a.pdf", b"a" * 500)
    gleich = _datei(tmp_path / "Ziel" / "schon da.pdf", b"a" * 500)
    index = lambda g: [{"pfad": str(gleich).upper() if os.name == "nt" else str(gleich),  # noqa: E731
                        "pruefsumme": None, "pruefsumme_stand": None}]
    assert gleiche_anderswo(quelle, gleich.parent, index, Pruefsummen()) == [gleich]


# --------------------------------------------------------------------------- Suchindex

def test_indexlauf_schreibt_die_pruefsumme_mit(tmp_path):
    ablage = tmp_path / "Ablage"
    brief = h.pdf_mit_text(_datei(ablage / "Brief.pdf", b"").parent / "Brief.pdf", ["Sehr geehrte Frau Beispiel"])
    notiz = _datei(ablage / "Notiz.md", "Müller und die Bäume".encode("utf-8"))
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    assert Indexer(konfig, synchron=True).lauf() == 0

    index = Suchindex(konfig)
    zeilen = index.gleiche_groesse(brief.stat().st_size)
    assert [(z["pfad"].lower(), z["pruefsumme"], z["pruefsumme_stand"]) for z in zeilen] == [
        (str(brief).lower(), pruefsumme(brief), _stand(brief))]
    assert index.gleiche_groesse(notiz.stat().st_size)[0]["pruefsumme"] == pruefsumme(notiz)
    assert index.gleiche_groesse(123456789) == []

    # Eine Kopie im Scan-Ordner wird ueber den Index gefunden, ohne das Archiv zu lesen
    kopie = _datei(tmp_path / "Scan" / "Brief (1).pdf", brief.read_bytes())
    speicher = Pruefsummen()
    assert [str(p).lower() for p in gleiche_anderswo(kopie, None, index.gleiche_groesse, speicher)] == [
        str(brief).lower()]
    assert speicher.gerechnet == 1


def test_alte_datenbank_bekommt_die_spalten_und_bleibt_bis_dahin_lesbar(tmp_path):
    pfad = tmp_path / "suche.db"
    con = db.verbinde(pfad)
    con.executescript(db.SCHEMA)  # Stand vor Issue #245: ohne die Spalten
    con.execute(
        "INSERT INTO dokumente (pfad, datei, name, ordner, typ, format, groesse, mtime_ns, textstatus, indiziert_am) "
        "VALUES (?, ?, 'Alt.pdf', ?, 'pdf', 'pdf', 4711, 1, 'text', '2026-01-01')",
        ("C:\\Ablage\\Alt.pdf", "C:\\Ablage\\Alt.pdf", "C:\\Ablage"))
    con.commit()
    assert "pruefsumme" not in db._spalten(con, "dokumente")
    assert db.gleiche_groesse(con, 4711) == [
        {"pfad": "C:\\Ablage\\Alt.pdf", "pruefsumme": None, "pruefsumme_stand": None}]

    assert db.ergaenze_schema(con) is True
    assert set(db.PRUEFSUMME_SPALTEN) <= db._spalten(con, "dokumente")
    assert db.schema_stand(con) == 2
    assert db.ergaenze_schema(con) is False  # idempotent
    db.pruefsumme_setzen(con, 1, "ab" * 16, 4711, 99)
    assert db.gleiche_groesse(con, 4711)[0] == {
        "pfad": "C:\\Ablage\\Alt.pdf", "pruefsumme": "ab" * 16, "pruefsumme_stand": "4711:99"}
    con.close()


def test_suchindex_ohne_datenbank(tmp_path):
    assert Suchindex(h.konfig_fuer(tmp_path)).gleiche_groesse(100) == []

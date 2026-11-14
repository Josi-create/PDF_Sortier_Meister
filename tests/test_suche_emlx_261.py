"""Dokumentensuche: Apple Mail (``.emlx``, Issue #261) - Datei lesen, Lauf ueber den
Postfach-Ordner, Aufraeumen, Mail als ``.eml`` herausgeben, Erkennung des Mail-Ordners."""

import sys
from pathlib import Path

import helfer_suche as h
from src.search import db, extract, plattform
from src.search.indexer import Indexer
from src.search.suchindex import Suchindex

APPLE_MAIL_ORDNER_ECHT = plattform.apple_mail_ordner   # conftest schaltet die Erkennung fuer alle Tests ab

PLIST = (b'<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
         b"<key>flags</key><integer>8590195713</integer></dict></plist>\n")


def emlx(pfad: Path, roh: bytes) -> Path:
    """Apple-Mail-Datei: Laengenzeile, Mail, Eigenschaftsliste."""
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(str(len(roh)).encode() + b"\n" + roh + PLIST)
    return pfad


def _postfach(tmp_path: Path) -> Path:
    return tmp_path / "Mail" / "V10" / "KONTO-1" / "INBOX.mbox" / "ABC" / "Data" / "Messages"


def _lauf(konfig, **kw):
    ix = Indexer(konfig, synchron=True)
    assert ix.lauf(**kw) == 0
    return ix.stat


def _namen(konfig) -> list[str]:
    con = db.verbinde(konfig.db_datei, nur_lesen=True)
    try:
        return sorted(r[0] for r in con.execute("SELECT name FROM dokumente"))
    finally:
        con.close()


def test_emlx_roh_schneidet_laenge_und_eigenschaftsliste_ab():
    roh = h.mail_roh("Zählerstand", text="Grüße aus Musterstadt")
    assert extract.emlx_roh(str(len(roh)).encode() + b"\n" + roh + PLIST) == roh
    assert extract.emlx_roh(str(len(roh)).encode() + b"   \r\n" + roh + PLIST) == roh
    # ohne Laengenzeile: der ganze Inhalt ist die Mail
    assert extract.emlx_roh(roh) == roh
    assert extract.emlx_roh(b"") == b""


def test_emlx_text(tmp_path):
    p = emlx(tmp_path / "12.emlx", h.mail_roh("Zählerstand", text="Grüße aus Musterstadt", anhang="Ablesung.pdf"))
    erg = extract.emlx_text(str(p))
    assert erg["status"] == "text" and erg["betreff"] == "Zählerstand" and erg["anhaenge"] == "Ablesung.pdf"
    assert "Grüße aus Musterstadt" in erg["text"] and "plist" not in erg["text"] and "flags" not in erg["text"]
    assert erg["datum_iso"].startswith("2024-01-10T10:00:00")
    leer = tmp_path / "leer.emlx"
    leer.write_bytes(b"0\n" + PLIST)
    assert extract.emlx_text(str(leer))["status"] == "leer"
    assert extract.emlx_text(str(tmp_path / "fehlt.emlx"))["status"] == "fehler"


def test_lauf_liest_apple_mail_ordner_und_raeumt_auf(tmp_path):
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    (ablage / "Notiz.md").write_text("Ablage", encoding="utf-8")
    post = _postfach(tmp_path)
    eins = emlx(post / "1.emlx", h.mail_roh("Erste Mail", text="Inhalt Apfelbaum"))
    emlx(post / "2.partial.emlx", h.mail_roh("Zweite Mail", text="Inhalt Birnbaum"))
    # Anhaenge und andere Dateien im Mail-Ordner gehoeren nicht in den Index
    (post.parent / "Attachments").mkdir()
    (post.parent / "Attachments" / "Anhang.md").write_text("nicht aufnehmen", encoding="utf-8")
    # .emlx steht NICHT bei den Endungen: der Mail-Ordner wird trotzdem gelesen
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], mails_aktiv=True, mail_ordner=[str(tmp_path / "Mail")],
                           endungen={".md"})
    _lauf(konfig)
    assert _namen(konfig) == ["1.emlx", "2.partial.emlx", "Notiz.md"]
    con = db.verbinde(konfig.db_datei, nur_lesen=True)
    try:
        erg = db.suche(con, "Apfelbaum", typ="mail")
        assert erg["gesamt"] == 1
        t = erg["treffer"][0]
        assert t["format"] == "emlx" and t["mail_betreff"] == "Erste Mail" and t["datei"] == str(eins)
        # Datum der Mail (10.01.2024, 10:00 +0100), nicht das der Datei
        assert t["datum"] == 1704877200
    finally:
        con.close()
    # zweiter Lauf: nichts geht verloren (Mail-Ordner liegt ausserhalb der Wurzeln), nichts wird neu gelesen
    stat = _lauf(konfig)
    assert stat["entfernt"] == 0 and stat["neu"] == 0 and len(_namen(konfig)) == 3
    # geloeschte Mail verschwindet
    eins.unlink()
    assert _lauf(konfig)["entfernt"] == 1
    assert _namen(konfig) == ["2.partial.emlx", "Notiz.md"]
    # ohne Mails (--ohne-mail) bleibt der Bestand, mit abgeschalteten Mails wird er entfernt
    assert _lauf(konfig, ohne_mail=True)["entfernt"] == 0
    aus = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], mails_aktiv=False, mail_ordner=[str(tmp_path / "Mail")],
                        endungen={".md"})
    assert _lauf(aus)["entfernt"] == 1 and _namen(aus) == ["Notiz.md"]


def test_emlx_in_durchsuchtem_ordner_ohne_mail_phase(tmp_path):
    ablage = tmp_path / "Ablage"
    emlx(ablage / "kopie.emlx", h.mail_roh("Kopierte Mail", text="Inhalt Kirschbaum"))
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    assert ".emlx" in konfig.endungen
    _lauf(konfig)
    assert _namen(konfig) == ["kopie.emlx"]


def test_unlesbarer_mail_ordner_laesst_bestand_stehen(tmp_path, monkeypatch):
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    post = _postfach(tmp_path)
    emlx(post / "1.emlx", h.mail_roh("Erste Mail"))
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], mails_aktiv=True, mail_ordner=[str(tmp_path / "Mail")])
    _lauf(konfig)
    assert _namen(konfig) == ["1.emlx"]
    # Mac ohne Festplattenvollzugriff: der Ordner ist da, laesst sich aber nicht lesen
    monkeypatch.setattr(plattform, "ordner_lesbar", lambda pfad: False)
    assert _lauf(konfig)["entfernt"] == 0 and _namen(konfig) == ["1.emlx"]


def test_mail_als_eml_wandelt_emlx_um(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path / "temp"))
    (tmp_path / "temp").mkdir()
    post = _postfach(tmp_path)
    roh = h.mail_roh("Frist: Antwort/Rückfrage", text="Inhalt Pflaumenbaum")
    quelle = emlx(post / "7.emlx", roh)
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(tmp_path / "Ablage")], mails_aktiv=True,
                           mail_ordner=[str(tmp_path / "Mail")])
    (tmp_path / "Ablage").mkdir()
    _lauf(konfig)
    index = Suchindex(konfig)
    treffer = index.suche("Pflaumenbaum")["treffer"][0]
    eml = index.mail_als_eml(treffer)
    assert eml.suffix == ".eml" and eml.read_bytes() == roh and eml != quelle
    assert "Frist" in eml.name and "7.emlx" not in eml.name
    assert quelle.read_bytes().endswith(PLIST)          # die Datei von Apple Mail bleibt unberuehrt


def test_apple_mail_ordner_nur_auf_dem_mac(tmp_path, monkeypatch):
    monkeypatch.setattr(plattform, "apple_mail_ordner", APPLE_MAIL_ORDNER_ECHT)
    monkeypatch.setattr(plattform, "_home", lambda: tmp_path)
    monkeypatch.setattr(plattform, "thunderbird_mail_ordner", lambda profiles_ini=None: [])
    mail = tmp_path / "Library" / "Mail"
    mail.mkdir(parents=True)
    monkeypatch.setattr(sys, "platform", "win32")
    assert plattform.apple_mail_ordner() == []
    assert plattform.mail_quellen_hinweis()[0] is False
    monkeypatch.setattr(sys, "platform", "darwin")
    assert plattform.apple_mail_ordner() == [str(mail)]
    gefunden, text = plattform.mail_quellen_hinweis()
    assert gefunden and "Apple Mail erkannt" in text and "gesperrt" not in text
    assert h.konfig_fuer(tmp_path, mails_aktiv=True).mail_ordner_effektiv() == [str(mail)]
    # ohne Festplattenvollzugriff: Hinweis, was zu tun ist
    monkeypatch.setattr(plattform, "ordner_lesbar", lambda pfad: False)
    gefunden, text = plattform.mail_quellen_hinweis()
    assert gefunden and "Festplattenvollzugriff" in text
    mail.rmdir()
    assert plattform.apple_mail_ordner() == []
    assert "Apple Mail" in plattform.mail_quellen_hinweis()[1]

"""Issue #327: PDF-Anhaenge einer Mail aus der Suche in den Scan-Ordner legen.

Geprueft: Herausloesen der PDF-Anhaenge (Bilder bleiben weg) fuer mbox, ``.eml``,
``.emlx`` und ``.msg``; Ablage ohne Ueberschreiben (" (2)"), Dateinamen ohne
Pfadteile; Menueeintrag nur bei Mails mit PDF-Anhang; Meldung in der Suche.
Alle Mails und Namen sind erfunden.
"""
from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

import pytest

from src.search import extract
from src.search.indexer import Indexer
from src.search.suchindex import Suchindex, anhaenge_ablegen, anhang_dateiname
from tests import helfer_suche as h

PDF_A = b"%PDF-1.4\nRechnung A\n%%EOF\n"
PDF_B = b"%PDF-1.4\nBescheid B\n%%EOF\n"


def _mail(betreff: str, anhaenge: list[tuple[str, str, bytes]]) -> bytes:
    m = EmailMessage()
    m["Subject"] = betreff
    m["From"] = "Max Mustermann <max@example.invalid>"
    m["To"] = "erika@example.invalid"
    m["Date"] = "Wed, 10 Jan 2024 10:00:00 +0100"
    m.set_content("Im Anhang die Unterlagen.")
    for name, mime, daten in anhaenge:
        haupt, unter = mime.split("/")
        m.add_attachment(daten, maintype=haupt, subtype=unter, filename=name)
    return m.as_bytes()


ZWEI_PDF_UND_BILD = [("Rechnung.pdf", "application/pdf", PDF_A),
                     ("Foto.jpg", "image/jpeg", b"\xff\xd8\xff\xe0bild"),
                     ("Bescheid Ä.PDF", "application/pdf", PDF_B)]


# --------------------------------------------------------------------------- Herausloesen

def test_pdf_anhaenge_aus_bytes_nur_pdfs_unveraendert():
    anh = extract.pdf_anhaenge_aus_bytes(_mail("Unterlagen", ZWEI_PDF_UND_BILD))
    assert anh == [("Rechnung.pdf", PDF_A), ("Bescheid Ä.PDF", PDF_B)]
    assert extract.pdf_anhaenge_aus_bytes(_mail("Ohne", [])) == []


def test_mail_pdf_anhaenge_eml_emlx_msg(tmp_path):
    roh = _mail("Unterlagen", ZWEI_PDF_UND_BILD)
    eml = tmp_path / "a.eml"
    eml.write_bytes(roh)
    emlx = tmp_path / "1.emlx"
    emlx.write_bytes(str(len(roh)).encode() + b"\n" + roh + b"<?xml version=\"1.0\"?><plist/>")
    msg_text = tmp_path / "b.msg"           # als Text gespeicherte Mail mit Endung .msg
    msg_text.write_bytes(roh)
    index = Suchindex(h.konfig_fuer(tmp_path))
    for pfad, fmt in ((eml, "eml"), (emlx, "emlx"), (msg_text, "msg")):
        anh = index.mail_pdf_anhaenge({"typ": "mail", "format": fmt, "datei": str(pfad)})
        assert [d for _n, d in anh] == [PDF_A, PDF_B], fmt


def test_msg_outlook_container(tmp_path, monkeypatch):
    pfad = tmp_path / "c.msg"
    pfad.write_bytes(extract.OLE_MAGIC + b"\0" * 64)

    class Anhang:
        def __init__(self, name, daten, mimetype=None):
            self.name, self.data, self.mimetype = name, daten, mimetype

        def getFilename(self):
            return self.name

    class Nachricht:
        attachments = [Anhang("Rechnung.pdf", PDF_A), Anhang("Logo.png", b"\x89PNG"),
                       Anhang("ohne_endung", PDF_B, "application/pdf"), Anhang("Weitergeleitet.pdf", object())]
        geschlossen = False

        def close(self):
            Nachricht.geschlossen = True

    import extract_msg
    monkeypatch.setattr(extract_msg, "openMsg", lambda p: Nachricht())
    assert extract.msg_pdf_anhaenge(str(pfad)) == [("Rechnung.pdf", PDF_A), ("ohne_endung", PDF_B)]
    assert Nachricht.geschlossen


# --------------------------------------------------------------------------- Ablegen

@pytest.mark.parametrize("name,erwartet", [
    ("Rechnung.pdf", "Rechnung.pdf"),
    ("Bescheid Ä.PDF", "Bescheid Ä.pdf"),
    ("..\\..\\boese/pfad.pdf", "_.._boese_pfad.pdf"),
    ("ohne_endung", "ohne_endung.pdf"),
    ("", "Anhang.pdf"),
    ("CON.pdf", "Anhang CON.pdf"),
])
def test_anhang_dateiname(name, erwartet):
    assert anhang_dateiname(name) == erwartet


def test_ablegen_ueberschreibt_nie(tmp_path):
    scan = tmp_path / "Scan Ordner Ü"
    scan.mkdir()
    (scan / "Rechnung.pdf").write_bytes(b"alt")
    abgelegt = anhaenge_ablegen([("Rechnung.pdf", PDF_A), ("Rechnung.pdf", PDF_B)], scan)
    assert [p.name for p in abgelegt] == ["Rechnung (2).pdf", "Rechnung (3).pdf"]
    assert (scan / "Rechnung.pdf").read_bytes() == b"alt"
    assert abgelegt[0].read_bytes() == PDF_A and abgelegt[1].read_bytes() == PDF_B
    assert not list(scan.glob("*.part"))


# --------------------------------------------------------------------------- Oberflaeche

@pytest.fixture
def view(qtbot, tmp_path, fresh_config):
    from src.gui.search_view import SearchView

    konto = tmp_path / "Mail" / "pop.example.invalid"
    konto.mkdir(parents=True)
    h.mbox(konto / "Inbox", [_mail("Unterlagen Steuer", ZWEI_PDF_UND_BILD),
                             _mail("Nur Text ohne Anlage", []),
                             _mail("Nur ein Urlaubsbild", [("Foto.jpg", "image/jpeg", b"\xff\xd8")])])
    konfig = h.konfig_fuer(tmp_path, wurzeln=[], prioritaet=[], mails_aktiv=True,
                           mail_ordner=[str(tmp_path / "Mail")])
    assert Indexer(konfig, synchron=True).lauf() == 0
    fresh_config.set_search_config(konfig)
    v = SearchView(fresh_config)
    qtbot.addWidget(v)
    yield v
    v.shutdown()


def _mails(qtbot, view, text):
    view.search_edit.setText(text)
    with qtbot.waitSignal(view.suche_fertig, timeout=15000):
        view._suche_starten()
    return [k.dok for k in view.karten() if k.dok["typ"] == "mail"]


EINTRAG = "PDF-Anhänge in den Scan-Ordner legen"


def test_menue_und_ablage_in_den_scan_ordner(qtbot, view, tmp_path, fresh_config):
    (mail,) = _mails(qtbot, view, "Steuer")
    assert EINTRAG in [a.text() for a in view._aktionen_menue(mail).actions()]
    for text in ("Anlage", "Urlaubsbild"):
        (ohne,) = _mails(qtbot, view, text)
        assert EINTRAG not in [a.text() for a in view._aktionen_menue(ohne).actions()], text

    # Ohne Scan-Ordner: Hinweis, nichts geschrieben
    view._anhaenge_in_scan_ordner(mail)
    assert "Kein Scan-Ordner" in view.meldung_label.text()

    scan = tmp_path / "Frisch gescannt"
    scan.mkdir()
    (scan / "Rechnung.pdf").write_bytes(b"schon da")
    fresh_config.set_scan_folder(scan)
    mbox_vorher = (tmp_path / "Mail" / "pop.example.invalid" / "Inbox").read_bytes()

    aktion = next(a for a in view._aktionen_menue(mail).actions() if a.text() == EINTRAG)
    aktion.trigger()
    assert view.meldung_label.text() == "2 Anhänge in den Scan-Ordner gelegt"
    assert sorted(p.name for p in scan.iterdir()) == ["Bescheid Ä.pdf", "Rechnung (2).pdf", "Rechnung.pdf"]
    assert (scan / "Rechnung (2).pdf").read_bytes() == PDF_A
    assert (scan / "Rechnung.pdf").read_bytes() == b"schon da"
    assert (tmp_path / "Mail" / "pop.example.invalid" / "Inbox").read_bytes() == mbox_vorher


def test_meldung_bei_einem_anhang_und_bei_fehler(qtbot, view, tmp_path, fresh_config, monkeypatch):
    scan = tmp_path / "Scan"
    scan.mkdir()
    fresh_config.set_scan_folder(scan)
    d = {"typ": "mail", "format": "eml", "datei": str(tmp_path / "x.eml"), "mail_anhaenge": "Rechnung.pdf"}
    Path(d["datei"]).write_bytes(_mail("Eine Rechnung", ZWEI_PDF_UND_BILD[:1]))
    view._anhaenge_in_scan_ordner(d)
    assert view.meldung_label.text() == "1 Anhang in den Scan-Ordner gelegt: Rechnung.pdf"

    Path(d["datei"]).unlink()
    view._anhaenge_in_scan_ordner(d)
    assert view.meldung_label.text().startswith("Die Anhänge konnten nicht abgelegt werden")

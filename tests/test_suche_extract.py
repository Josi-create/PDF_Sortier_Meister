"""Dokumentensuche: Textgewinnung (PDF, OCR mit Tesseract-Attrappe, Markdown, eml, msg)."""

import subprocess
import sys
import types

import helfer_suche as h
from src.search import extract


def test_pdf_textebene_und_metadaten(tmp_path):
    p = h.pdf_mit_text(tmp_path / "a.pdf", ["Erste Seite Text", "Zweite Seite"], titel="Titel", autor="Autor")
    erg = extract.pdf_text(str(p), min_zeichen=5)
    assert erg["status"] == "text" and erg["anzahl"] == 2 and erg["ohne_text"] == []
    assert [s[0] for s in erg["seiten"]] == [1, 2] and "Erste Seite Text" in erg["seiten"][0][2]
    assert erg["titel"] == "Titel" and erg["autor"] == "Autor"


def test_pdf_bildseite_wartet_auf_ocr(tmp_path):
    p = h.pdf_mit_bild(tmp_path / "scan.pdf", seiten=2, text_seiten=["Deckblatt mit Text"])
    erg = extract.pdf_text(str(p), min_zeichen=5)
    assert erg["status"] == "ocr_ausstehend" and erg["ohne_text"] == [2, 3]
    assert [s[1] for s in erg["seiten"]] == ["text", "ohne_text", "ohne_text"]


def test_pdf_verschluesselt_und_fehler(tmp_path):
    p = h.pdf_verschluesselt(tmp_path / "geheim.pdf")
    assert extract.pdf_text(str(p), 5)["status"] == "verschluesselt"
    kaputt = tmp_path / "kaputt.pdf"
    kaputt.write_bytes(b"kein pdf")
    erg = extract.pdf_text(str(kaputt), 5)
    assert erg["status"] == "fehler" and erg["fehler"].startswith("Öffnen")
    assert extract.pdf_text(str(tmp_path / "fehlt.pdf"), 5)["status"] == "fehler"


def test_pdf_ocr_mit_tesseract_attrappe(tmp_path, monkeypatch):
    p = h.pdf_mit_bild(tmp_path / "scan.pdf", seiten=2)
    aufrufe = []

    def fake_run(args, **kw):
        aufrufe.append((args, kw))
        assert args[1:3] == ["stdin", "stdout"] and kw["input"][:8] == b"\x89PNG\r\n\x1a\n"
        assert kw["env"]["TESSDATA_PREFIX"] == "/tess/data"
        if "--psm" not in args:
            raise AssertionError("psm fehlt")
        return subprocess.CompletedProcess(args, 0, stdout=f"Erkannt {len(aufrufe)}".encode(), stderr=b"")

    monkeypatch.setattr(extract.subprocess, "run", fake_run)
    cfg = {"tesseract": "tesseract-fake", "tessdata": "/tess/data", "sprachen": "deu+eng", "dpi": 300}
    erg = extract.pdf_ocr(str(p), [1, 2, 7], cfg)
    assert erg["texte"] == {1: "Erkannt 1", 2: "Erkannt 2"} and erg["fehler"] is None
    assert len(aufrufe) == 2 and aufrufe[0][0][0] == "tesseract-fake" and "deu+eng" in aufrufe[0][0]


def test_pdf_ocr_fehler_je_seite(tmp_path, monkeypatch):
    p = h.pdf_mit_bild(tmp_path / "scan.pdf", seiten=1)
    monkeypatch.setattr(extract.subprocess, "run",
                        lambda args, **kw: subprocess.CompletedProcess(args, 1, stdout=b"", stderr=b"kaputt"))
    erg = extract.pdf_ocr(str(p), [1], {"tesseract": "t", "tessdata": None, "sprachen": "deu", "dpi": 300})
    assert erg["texte"] == {1: None} and "kaputt" in erg["fehler"]


def test_markdown(tmp_path):
    p = tmp_path / "notiz.md"
    p.write_bytes("﻿# Überschrift\n\nText mit Umlauten äöü".encode("utf-8"))
    erg = extract.md_text(str(p))
    assert erg["status"] == "text" and erg["titel"] == "Überschrift" and erg["text"].startswith("# Überschrift")
    cp = tmp_path / "alt.md"
    cp.write_bytes("Grüße".encode("cp1252"))
    assert extract.md_text(str(cp))["text"] == "Grüße"
    leer = tmp_path / "leer.md"
    leer.write_bytes(b"  \n")
    assert extract.md_text(str(leer))["status"] == "leer"
    assert extract.md_text(str(tmp_path / "fehlt.md"))["status"] == "fehler"


def test_eml_text_html_und_anhang(tmp_path):
    p = tmp_path / "mail.eml"
    p.write_bytes(h.mail_roh("Betreff äöü", text="Hallo <b>Welt</b>", html=True))
    erg = extract.eml_text(str(p))
    assert erg["status"] == "text" and erg["betreff"] == "Betreff äöü"
    assert erg["von"] == "absender@example.invalid" and erg["datum_iso"].startswith("2024-01-10T10:00:00")
    assert "Hallo Welt" in erg["text"] and "alert" not in erg["text"] and "<b>" not in erg["text"]
    assert erg["text"].startswith("Betreff: Betreff äöü\nVon: absender@example.invalid")

    p2 = tmp_path / "anhang.eml"
    p2.write_bytes(h.mail_roh("Mit Anhang", text="siehe Anlage", anhang="Rechnung.pdf"))
    erg = extract.eml_text(str(p2))
    assert erg["anhaenge"] == "Rechnung.pdf" and "siehe Anlage" in erg["text"] and "Anhänge: Rechnung.pdf" in erg["text"]
    assert extract.eml_text(str(tmp_path / "fehlt.eml"))["status"] == "fehler"


def test_mbox_stapel_zerlegt_mehrere_mails():
    stapel = [(0, 10, h.mail_roh("A")), (10, 10, h.mail_roh("B"))]
    erg = extract.mbox_stapel(stapel)
    assert [(off, m["betreff"]) for off, _, m in erg] == [(0, "A"), (10, "B")]


def test_msg_text_mit_extract_msg_attrappe(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    class FakeMsg:
        subject, sender, to, cc = "Outlook-Betreff", "chef@example.invalid", "ich@example.invalid", ""
        body, htmlBody = "", b"<p>HTML-Inhalt</p>"
        date = datetime(2024, 2, 1, 9, 30, tzinfo=timezone.utc)

        class _Anhang:
            def getFilename(self):
                return "Vertrag.docx"

        attachments = [_Anhang()]

        def close(self):
            pass

    fake = types.SimpleNamespace(openMsg=lambda pfad: FakeMsg())
    monkeypatch.setitem(sys.modules, "extract_msg", fake)
    p = tmp_path / "x.msg"
    p.write_bytes(extract.OLE_MAGIC + b"\0" * 1024)   # Outlook-Container: nur der Kopf zaehlt
    erg = extract.msg_text(str(p))
    assert erg["status"] == "text" and erg["betreff"] == "Outlook-Betreff" and erg["anhaenge"] == "Vertrag.docx"
    assert "HTML-Inhalt" in erg["text"] and erg["datum_iso"] == "2024-02-01T09:30:00+00:00"

    monkeypatch.setitem(sys.modules, "extract_msg",
                        types.SimpleNamespace(openMsg=lambda pfad: (_ for _ in ()).throw(ValueError("nicht OLE"))))
    erg = extract.msg_text(str(p))
    assert erg["status"] == "fehler" and erg["fehler"] == "ValueError: nicht OLE"


def test_msg_erkennt_format_am_inhalt(tmp_path):
    # Als Text gespeicherte Mail mit Endung .msg -> wie .eml
    p = tmp_path / "text.msg"
    p.write_bytes(h.mail_roh("Als Text gespeichert", text="Inhalt"))
    erg = extract.msg_text(str(p))
    assert erg["status"] == "text" and erg["betreff"] == "Als Text gespeichert" and "Inhalt" in erg["text"]
    # Tcl-Nachrichtenkatalog (msgcat) heisst auch .msg, ist aber keine Mail: leer, kein Fehler
    p2 = tmp_path / "de.msg"
    p2.write_bytes(b"# German messages for Tk\nnamespace eval ::tk {\n    ::msgcat::mcset de \"Open\" \"\\u00d6ffnen\"\n}\n")
    erg = extract.msg_text(str(p2))
    assert erg["status"] == "leer" and "kein Outlook-Format" in erg["fehler"] and erg["text"] == ""
    # leere Datei: leer ohne Fehlertext
    p3 = tmp_path / "leer.msg"
    p3.write_bytes(b"")
    erg = extract.msg_text(str(p3))
    assert erg["status"] == "leer" and erg["fehler"] is None
    assert extract.eml_text(str(p3))["status"] == "leer"
    # fehlende Datei: Fehler ohne den Pfad im Text
    erg = extract.msg_text(str(tmp_path / "fehlt.msg"))
    assert erg["status"] == "fehler" and erg["fehler"].startswith("FileNotFoundError") and str(tmp_path) not in erg["fehler"]
    assert extract.mail_format(b"\r\n\r\n") == "leer"
    assert extract.mail_format(b"From - Wed Jan 10 10:00:00 2024\nSubject: x\n") == "rfc822"
    assert extract.mail_format(b"Received: from a\nSubject: x\n") == "rfc822"
    assert extract.mail_format(b"Subject ohne Doppelpunkt\n") == "unbekannt"


def test_fehlertext_kurz_und_ohne_pfad():
    pfad = r"C:\Ablage\Rechnung 2024.pdf"
    t = extract.fehlertext(RuntimeError(f"cannot open {pfad}: bad header\n   details"), pfad)
    assert t == "RuntimeError: cannot open <Datei>: bad header details"
    t = extract.fehlertext(OSError(f"no such file: '{pfad.replace(chr(92), chr(92) * 2)}'"), pfad)
    assert t == "OSError: no such file: '<Datei>'"
    assert extract.fehlertext(ValueError()) == "ValueError"
    assert len(extract.fehlertext(OSError("x" * 1000))) == extract.MAX_FEHLERTEXT
    assert extract.fehlertext("Zeitüberschreitung") == "Zeitüberschreitung"


def test_popen_kwargs_nur_unter_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert extract._popen_kwargs() == {}
    monkeypatch.setattr(sys, "platform", "win32")
    assert extract._popen_kwargs() == {"creationflags": 0x08000000}

"""Dokumentensuche: Office-Extraktion (docx, xlsx, odt, doc, xls, RTF/HTML als .doc, verschluesselt)."""

import pytest

import helfer_suche as h
from src.search import office


def test_docx_mit_kopf_fuss_und_metadaten(tmp_path):
    p = h.docx(tmp_path / "brief.docx", ["Sehr geehrte Damen und Herren,", "Rechnung Nr. 4711"],
               kopf="Kopfzeile GmbH", fuss="Seite 1", titel="Brief", autor="Erika Beispiel")
    erg = office.office_text(str(p), "docx")
    assert erg["status"] == "text" and erg["fehler"] is None
    assert len(erg["seiten"]) == 1
    text = erg["seiten"][0][2]
    assert "Rechnung Nr. 4711" in text and "Kopfzeile GmbH" in text and "Seite 1" in text
    assert erg["titel"] == "Brief" and erg["autor"] == "Erika Beispiel"


def test_docx_leer(tmp_path):
    p = h.docx(tmp_path / "leer.docx", [""])
    assert office.office_text(str(p), "docx")["status"] == "leer"


def test_xlsx_blaetter_shared_inline_zahlen(tmp_path):
    p = h.xlsx(tmp_path / "mappe.xlsx", {
        "Umsatz": [["Posten", "Betrag"], ["Miete", 15880.219999999], ["inline:Nebenkosten", 42], [True, 7]],
        "Kosten": [["Strom", 99.5]],
    })
    erg = office.office_text(str(p), "xlsx")
    assert erg["status"] == "text"
    assert len(erg["seiten"]) == 2
    blatt1 = erg["seiten"][0][2]
    assert blatt1.startswith("Tabellenblatt: Umsatz")
    assert "Posten\tBetrag" in blatt1 and "Miete\t15880.22" in blatt1 and "Nebenkosten\t42" in blatt1
    assert "WAHR\t7" in blatt1
    assert erg["seiten"][1][2].startswith("Tabellenblatt: Kosten") and "Strom\t99.5" in erg["seiten"][1][2]


def test_odt(tmp_path):
    p = h.odt(tmp_path / "text.odt", ["Erster Absatz", "Zweiter Absatz"], titel="Notiz")
    erg = office.office_text(str(p), "odt")
    assert erg["status"] == "text" and erg["titel"] == "Notiz"
    assert erg["seiten"][0][2] == "Erster Absatz\nZweiter Absatz"


def test_doc_word97_piece_table_8bit_und_unicode(tmp_path):
    p = h.doc_word97(tmp_path / "alt.doc", "Grüße aus dem Büro\rZweiter Absatz")
    erg = office.office_text(str(p), "doc")
    assert erg["status"] == "text", erg
    assert erg["seiten"][0][2] == "Grüße aus dem Büro\nZweiter Absatz"

    p2 = h.doc_word97(tmp_path / "uni.doc", "Ünïcödé Text – Euro €", unicode=True)
    assert office.office_text(str(p2), "doc")["seiten"][0][2] == "Ünïcödé Text – Euro €"


def test_doc_verschluesselt(tmp_path):
    p = h.doc_word97(tmp_path / "geheim.doc", "Geheim", verschluesselt=True)
    erg = office.office_text(str(p), "doc")
    assert erg["status"] == "verschluesselt" and erg["seiten"] == []


def test_docx_xlsx_verschluesselt_ist_ole_container(tmp_path):
    p = tmp_path / "geheim.docx"
    p.write_bytes(h.ole_container({"EncryptedPackage": b"\x00" * 16}))
    assert office.office_text(str(p), "docx")["status"] == "verschluesselt"
    p2 = tmp_path / "geheim.xlsx"
    p2.write_bytes(h.ole_container({"EncryptedPackage": b"\x00" * 16}))
    assert office.office_text(str(p2), "xlsx")["status"] == "verschluesselt"


def test_falsche_endung_doc(tmp_path):
    # RTF mit Endung .doc
    rtf = tmp_path / "rtf.doc"
    rtf.write_bytes(b"{\\rtf1\\ansi{\\fonttbl{\\f0 Arial;}}\\f0 Hallo \\'fcber RTF\\par Zweite Zeile}")
    erg = office.office_text(str(rtf), "doc")
    assert erg["status"] == "text" and "Hallo über RTF" in erg["seiten"][0][2] and "Zweite Zeile" in erg["seiten"][0][2]
    assert "Arial" not in erg["seiten"][0][2]
    # HTML mit Endung .doc
    htm = tmp_path / "html.doc"
    htm.write_bytes(b"<html><head><style>p{}</style></head><body><p>Hallo HTML</p></body></html>")
    erg = office.office_text(str(htm), "doc")
    assert erg["status"] == "text" and "Hallo HTML" in erg["seiten"][0][2] and "<p>" not in erg["seiten"][0][2]
    # umbenannte docx mit Endung .doc
    docx = h.docx(tmp_path / "neu.doc", ["Moderne Datei"])
    erg = office.office_text(str(docx), "doc")
    assert erg["status"] == "text" and "Moderne Datei" in erg["seiten"][0][2]


def test_xls_mit_datum_und_zahlen(tmp_path):
    xlwt = pytest.importorskip("xlwt")
    from datetime import datetime

    wb = xlwt.Workbook()
    ws = wb.add_sheet("Belege")
    ws.write(0, 0, "Rechnung")
    ws.write(0, 1, 42.5)
    stil = xlwt.XFStyle()
    stil.num_format_str = "DD.MM.YYYY"
    ws.write(1, 0, datetime(2024, 3, 12), stil)
    ws.write(1, 1, True)
    p = tmp_path / "alt.xls"
    wb.save(str(p))
    erg = office.office_text(str(p), "xls")
    assert erg["status"] == "text"
    text = erg["seiten"][0][2]
    assert text.startswith("Tabellenblatt: Belege")
    assert "Rechnung\t42.5" in text and "12.03.2024\tWAHR" in text


def test_beschaedigte_datei_liefert_fehler(tmp_path):
    p = tmp_path / "kaputt.docx"
    p.write_bytes(b"PK\x03\x04 kein zip")
    erg = office.office_text(str(p), "docx")
    assert erg["status"] == "fehler" and erg["fehler"]

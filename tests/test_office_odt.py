"""Tests fuer .odt (OpenDocument-Text), das wie .docx behandelt wird - synthetische Dateien, kein Office noetig."""
from __future__ import annotations

import os
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from src.core import office_convert as oc
from src.core import office_vorschau as ov

NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:number="urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0" '
    'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/"'
)

DATUMSSTIL = (
    '<number:date-style style:name="N77">'
    '<number:day-of-week number:style="long"/><number:text>, </number:text>'
    '<number:day/><number:text>. </number:text><number:month number:textual="true" number:style="long"/>'
    '<number:text> </number:text><number:year number:style="long"/></number:date-style>'
)
ZEITSTIL = (
    '<number:time-style style:name="N80"><number:hours number:style="long"/>'
    '<number:text>:</number:text><number:minutes number:style="long"/></number:time-style>'
)
MANIFEST = (
    '<?xml version="1.0"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
    'manifest:version="1.2">'
    '<manifest:file-entry manifest:full-path="/" manifest:version="1.2" '
    'manifest:media-type="application/vnd.oasis.opendocument.text"/>'
    + "".join(
        f'<manifest:file-entry manifest:full-path="{n}" manifest:media-type="text/xml"/>'
        for n in ("content.xml", "styles.xml", "meta.xml")
    )
    + "</manifest:manifest>"
)
DT = datetime(2015, 5, 8, 20, 46)  # Freitag


def meta(inhalt: str) -> str:
    return f'<?xml version="1.0"?><office:document-meta {NS} office:version="1.2"><office:meta>{inhalt}</office:meta></office:document-meta>'


def content(absatz: str, stile: str = DATUMSSTIL + ZEITSTIL) -> str:
    return (
        f'<?xml version="1.0"?><office:document-content {NS} office:version="1.2">'
        f"<office:automatic-styles>{stile}</office:automatic-styles>"
        f"<office:body><office:text><text:p>{absatz}</text:p></office:text></office:body></office:document-content>"
    )


def odt_bauen(pfad: Path, content_xml: str, meta_inhalt: str | None = None, styles_xml: str | None = None) -> Path:
    """So packt LibreOffice: mimetype zuerst und unkomprimiert."""
    with zipfile.ZipFile(pfad, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        z.writestr("content.xml", content_xml)
        z.writestr("styles.xml", styles_xml or f'<?xml version="1.0"?><office:document-styles {NS} office:version="1.2"/>')
        if meta_inhalt is not None:
            z.writestr("meta.xml", meta(meta_inhalt))
        z.writestr("META-INF/manifest.xml", MANIFEST)
    return pfad


def teil(pfad: Path, name: str = "content.xml") -> str:
    with zipfile.ZipFile(pfad) as z:
        return z.read(name).decode("utf-8")


# --- Endungen ---------------------------------------------------------------------

def test_odt_ist_office_und_sortierbar():
    assert oc.ist_office_datei("a/B.ODT") and oc.ist_sortierbar(Path("x.odt"))
    assert ".odt" in oc.sortierbare_endungen()
    assert not oc.ist_office_datei("x.ods")


def test_endung_tauschen_odt():
    assert oc.endung_tauschen("Brief.pdf", ".odt") == "Brief.odt"
    assert oc.endung_tauschen("Brief.odt", ".odt") == "Brief.odt"


def test_umwandler_verfuegbar_kennt_odt(monkeypatch):
    monkeypatch.setattr(oc, "word_com_verfuegbar", lambda: True)
    monkeypatch.setattr(oc, "excel_com_verfuegbar", lambda: False)
    monkeypatch.setattr(oc, "finde_libreoffice", lambda: None)
    assert oc.umwandler_verfuegbar(".odt") and not oc.umwandler_verfuegbar(".xlsx")


def test_filemanager_behaelt_odt_endung_und_ignoriert_lockdatei(tmp_path):
    from src.core.file_manager import FileManager

    scan = tmp_path / "scan"
    ziel = tmp_path / "ziel"
    scan.mkdir()
    ziel.mkdir()
    (scan / "a.odt").write_bytes(b"PK")
    (scan / ".~lock.a.odt#").write_bytes(b"lock")  # LibreOffice-Sperrdatei
    fm = FileManager(scan)
    assert [p.name for p in fm.get_office_files()] == ["a.odt"]
    assert fm.move_file(scan / "a.odt", ziel, new_name="Neu.pdf").name == "Neu.odt"
    assert fm.rename_file(ziel / "Neu.odt", "Anders").name == "Anders.odt"


# --- Datum aus meta.xml -----------------------------------------------------------

def test_druckdatum_reihenfolge(tmp_path):
    d = odt_bauen(
        tmp_path / "a.odt", content(""),
        "<meta:creation-date>2010-01-01T08:00:00</meta:creation-date>"
        "<dc:date>2012-02-02T09:00:00</dc:date>"
        "<meta:print-date>2015-05-08T20:46:00</meta:print-date>",
    )
    assert oc.druckdatum(d) == (DT, "lastPrinted")
    d = odt_bauen(
        tmp_path / "b.odt", content(""),
        "<meta:creation-date>2010-01-01T08:00:00</meta:creation-date><dc:date>2012-02-02T09:00:00.123456</dc:date>",
    )
    assert oc.druckdatum(d) == (datetime(2012, 2, 2, 9), "modified")
    d = odt_bauen(tmp_path / "c.odt", content(""), "<meta:creation-date>2010-01-01T08:00:00</meta:creation-date>")
    assert oc.druckdatum(d) == (datetime(2010, 1, 1, 8), "created")


def test_druckdatum_ohne_meta_nimmt_dateizeit(tmp_path):
    d = odt_bauen(tmp_path / "a.odt", content(""), None)
    dt, quelle = oc.druckdatum(d)
    assert quelle == "Dateizeit" and dt == datetime.fromtimestamp(d.stat().st_mtime)


def test_druckdatum_leeres_printdate_wird_uebersprungen(tmp_path):
    d = odt_bauen(tmp_path / "a.odt", content(""), "<meta:print-date></meta:print-date><dc:date>2012-02-02T09:00:00</dc:date>")
    assert oc.druckdatum(d)[1] == "modified"


# --- Felder ersetzen --------------------------------------------------------------

def test_felder_ersetzt_mit_formatstil():
    xml = content(
        '<text:date style:data-style-name="N77" text:date-value="2026-11-08">08.11.2026</text:date> | '
        '<text:print-date style:data-style-name="N77">x</text:print-date> | '
        '<text:time style:data-style-name="N80" text:time-value="12:00:00">12:00</text:time> | '
        '<text:print-time style:data-style-name="N80"/>'
    )
    stile = oc._odf_stile([xml])
    neu, n = oc.odt_datumsfelder_ersetzen(xml, DT, stile)
    assert n == 4
    assert neu.count("Freitag, 8. Mai 2015") == 2 and neu.count("20:46") == 2
    assert "<text:date" not in neu and "<text:print" not in neu and "<text:time" not in neu


def test_felder_ohne_stil_bekommen_standardformat():
    neu, n = oc.odt_datumsfelder_ersetzen(
        '<text:p><text:date text:date-value="2026-01-01">x</text:date> <text:time/></text:p>', DT, {})
    assert n == 2 and "08.05.2015 20:46:00" in neu


def test_fixierte_felder_und_andere_bleiben():
    xml = (
        '<text:p><text:date text:fixed="true" text:date-value="2001-01-01">01.01.2001</text:date>'
        '<text:page-number>1</text:page-number><text:modification-date>x</text:modification-date>'
        '<text:date-adjust/></text:p>'
    )
    neu, n = oc.odt_datumsfelder_ersetzen(xml, DT, {})
    assert n == 0 and neu == xml


def test_stil_mit_12_stunden_und_kurzen_namen():
    stil = (
        '<number:time-style style:name="T"><number:hours/><number:text>:</number:text>'
        '<number:minutes number:style="long"/><number:text> </number:text><number:am-pm/></number:time-style>'
        '<number:date-style style:name="D"><number:day number:style="long"/><number:text>.</number:text>'
        '<number:month number:style="long"/><number:text>.</number:text><number:year/></number:date-style>'
    )
    stile = oc._odf_stile([content("", stil)])
    assert oc.formatiere_datum(DT, stile["T"]) == "8:46 PM"
    assert oc.formatiere_datum(DT, stile["D"]) == "08.05.15"


def test_sonderzeichen_im_ergebnis_werden_escaped():
    stil = '<number:date-style style:name="D"><number:text>A&amp;B </number:text><number:year number:style="long"/></number:date-style>'
    xml = content('<text:date style:data-style-name="D"/>', stil)
    neu, n = oc.odt_datumsfelder_ersetzen(xml, DT, oc._odf_stile([xml]))
    assert n == 1 and "A&amp;B 2015" in neu


# --- Ganze Datei ------------------------------------------------------------------

def test_odt_mit_festem_datum_kopie_zip_regeln_original_unveraendert(tmp_path):
    felder = '<text:date style:data-style-name="N77">08.11.2026</text:date>'
    kopf = (
        f'<?xml version="1.0"?><office:document-styles {NS} office:version="1.2"><office:automatic-styles>{ZEITSTIL}</office:automatic-styles>'
        '<office:master-styles><style:master-page><style:header><text:p>'
        '<text:time style:data-style-name="N80">12:00</text:time></text:p></style:header>'
        "</style:master-page></office:master-styles></office:document-styles>"
    )
    quelle = odt_bauen(
        tmp_path / "brief.odt", content(felder), "<meta:print-date>2015-05-08T20:46:00</meta:print-date>", kopf
    )
    vorher = quelle.read_bytes()
    ziel = tmp_path / "kopie.odt"

    assert oc.hat_datumsfelder(quelle)
    dt, quelle_name, n = oc.odt_mit_festem_datum(quelle, ziel)

    assert (dt, quelle_name, n) == (DT, "lastPrinted", 2)
    assert "Freitag, 8. Mai 2015" in teil(ziel) and "08.11.2026" not in teil(ziel)
    assert "20:46" in teil(ziel, "styles.xml")
    assert quelle.read_bytes() == vorher
    with zipfile.ZipFile(ziel) as z:
        assert z.testzip() is None
        erster = z.infolist()[0]
        assert erster.filename == "mimetype" and erster.compress_type == zipfile.ZIP_STORED
        assert {"meta.xml", "META-INF/manifest.xml"} <= set(z.namelist())


def test_mimetype_kommt_zuerst_auch_wenn_quelle_anders_sortiert(tmp_path):
    q = tmp_path / "a.odt"
    with zipfile.ZipFile(q, "w") as z:
        z.writestr("content.xml", content('<text:date/>'))
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
    ziel = tmp_path / "b.odt"
    oc.odt_mit_festem_datum(q, ziel)
    with zipfile.ZipFile(ziel) as z:
        assert z.infolist()[0].filename == "mimetype" and z.infolist()[0].compress_type == zipfile.ZIP_STORED


def test_hat_datumsfelder_odt(tmp_path):
    assert not oc.hat_datumsfelder(odt_bauen(tmp_path / "a.odt", content("Text")))
    assert not oc.hat_datumsfelder(odt_bauen(tmp_path / "b.odt", content('<text:date text:fixed="true"/>')))
    assert oc.hat_datumsfelder(odt_bauen(tmp_path / "c.odt", content("<text:print-date/>")))
    kaputt = tmp_path / "k.odt"
    kaputt.write_bytes(b"kein zip")
    assert not oc.hat_datumsfelder(kaputt)


def test_zu_grosser_teil_wird_ausgelassen(tmp_path, monkeypatch):
    d = odt_bauen(tmp_path / "a.odt", content("<text:date/>"))
    monkeypatch.setattr(oc, "MAX_TEIL", 10)
    assert not oc.hat_datumsfelder(d)


# --- umwandeln() --------------------------------------------------------------------

def test_umwandeln_odt_mit_libreoffice_nutzt_kopie_mit_festem_datum(tmp_path, monkeypatch):
    d = odt_bauen(
        tmp_path / "a.odt", content('<text:date style:data-style-name="N77">1999</text:date>'),
        "<meta:print-date>2015-05-08T20:46:00</meta:print-date>",
    )
    gesehen = {}

    def falsches_lo(soffice, quelle, pdf, pdfa):
        gesehen["quelle"] = quelle
        gesehen["xml"] = teil(quelle)
        pdf.write_bytes(b"%PDF-1.7 test")

    monkeypatch.setattr(oc, "word_com_verfuegbar", lambda: False)
    monkeypatch.setattr(oc, "finde_libreoffice", lambda: "soffice")
    monkeypatch.setattr(oc, "_mit_libreoffice", falsches_lo)

    erg = oc.umwandeln(d, pdfa=True)

    assert erg.werkzeug == "LibreOffice" and erg.pdfa and erg.pdf == tmp_path / "a.pdf"
    assert gesehen["quelle"] != d and "2015" in gesehen["xml"] and "1999" not in gesehen["xml"]
    assert erg.ersetzte_felder == 1 and erg.datum == DT and erg.datum_quelle == "lastPrinted" and not erg.hinweise
    assert d.exists()


def test_umwandeln_odt_mit_word_attrappe_und_hinweis_ohne_druckdatum(tmp_path, monkeypatch):
    d = odt_bauen(tmp_path / "a.odt", content("<text:print-date/>"), "<dc:date>2020-01-01T10:00:00</dc:date>")
    gesehen = {}

    def falsches_word(kopie, pdf, pdfa):
        gesehen["kopie"] = kopie
        pdf.write_bytes(b"%PDF")

    monkeypatch.setattr(oc, "word_com_verfuegbar", lambda: True)
    monkeypatch.setattr(oc, "finde_libreoffice", lambda: None)
    monkeypatch.setattr(oc, "_mit_word", falsches_word)
    erg = oc.umwandeln(d)
    assert erg.werkzeug == "Word" and gesehen["kopie"].suffix == ".odt"
    assert erg.datum_quelle == "modified" and any("Druckdatum" in h for h in erg.hinweise)


# --- Analyse und Vorschau -------------------------------------------------------------

def test_analyse_stellt_druckdatum_voran(tmp_path):
    from src.core.office_analyse import analysiere

    d = odt_bauen(
        tmp_path / "Brief.odt", content("Rechnung vom 03.03.2019 <text:print-date>x</text:print-date>"),
        "<meta:print-date>2015-05-08T20:46:00</meta:print-date>",
    )
    text, _kw, daten = analysiere(d)
    assert "Rechnung" in text
    assert daten[0].date() == DT.date()


def test_erste_zeilen_und_eingebettetes_bild(tmp_path):
    d = odt_bauen(tmp_path / "a.odt", content("Sehr geehrte Frau Meier"))
    assert "Sehr geehrte Frau Meier" in ov.erste_zeilen(d)[0]
    assert ov.eingebettetes_bild(d) is None
    with zipfile.ZipFile(d, "a") as z:
        z.writestr("Thumbnails/thumbnail.png", b"PNGDATA")
    assert ov.eingebettetes_bild(d) == b"PNGDATA"


def test_vorschau_pdf_fuer_odt_ruft_umwandeln(tmp_path, monkeypatch):
    d = odt_bauen(tmp_path / "a.odt", content("x"))
    aufrufe = []

    def falsch(quelle, ziel=None, pdfa=False):
        aufrufe.append(Path(quelle).name)
        Path(ziel).write_bytes(b"%PDF")
        return oc.UmwandlungsErgebnis(pdf=Path(ziel), werkzeug="Word")

    monkeypatch.setattr(ov, "umwandeln", falsch)
    cache = tmp_path / "cache"
    assert ov.vorschau_pdf(d, cache).exists() and aufrufe == ["a.odt"]


def test_echte_umwandlung_mit_word_wenn_vorhanden(tmp_path):
    """Echtes Word, nur auf Wunsch: PDFSM_WORD_TEST=1 (Windows mit Word). Arbeitet nur in tmp_path."""
    if not os.environ.get("PDFSM_WORD_TEST") or not oc.word_com_verfuegbar():
        pytest.skip("echter Word-Test nur mit PDFSM_WORD_TEST=1 und installiertem Word")
    import pymupdf

    d = odt_bauen(
        tmp_path / "Brief.odt",
        content('Briefdatum: <text:date style:data-style-name="N77">x</text:date>'),
        "<meta:print-date>2015-05-08T20:46:00</meta:print-date>",
    )
    erg = oc.umwandeln(d)
    with pymupdf.open(erg.pdf) as pdf:
        text = "".join(seite.get_text() for seite in pdf)
    assert "8. Mai 2015" in text

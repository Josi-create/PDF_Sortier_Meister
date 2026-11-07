"""Tests fuer src/core/office_convert.py (Issue #9) - synthetische .docx, kein Word noetig."""
from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from src.core import office_convert as oc

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

CORE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
    'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    "{inhalt}</cp:coreProperties>"
)


def komplexes_feld(instr: str, ergebnis: str) -> str:
    """So schreibt Word ein Feld: begin / instrText / separate / Ergebnis / end."""
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve">{instr}</w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        f'<w:r><w:rPr><w:b/></w:rPr><w:t>{ergebnis}</w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )


def body(inner: str) -> str:
    return f'<?xml version="1.0"?><w:document {W_NS}><w:body><w:p>{inner}</w:p></w:body></w:document>'


def docx_bauen(pfad: Path, document: str, core_inhalt: str | None, header: str | None = None) -> Path:
    with zipfile.ZipFile(pfad, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", document)
        if header is not None:
            z.writestr("word/header1.xml", header)
        if core_inhalt is not None:
            z.writestr("docProps/core.xml", CORE.format(inhalt=core_inhalt))
    return pfad


def teil(pfad: Path, name: str = "word/document.xml") -> str:
    with zipfile.ZipFile(pfad) as z:
        return z.read(name).decode("utf-8")


# --- Datumsbild -----------------------------------------------------------------

DT = datetime(2015, 5, 8, 20, 46)  # Freitag


@pytest.mark.parametrize(
    "bild, erwartet",
    [
        ("dddd, d. MMMM yyyy", "Freitag, 8. Mai 2015"),
        ("dd.MM.yyyy", "08.05.2015"),
        ("d.M.yy", "8.5.15"),
        ("ddd, dd. MMM yyyy", "Fr, 08. Mai 2015"),
        ("HH:mm", "20:46"),
        ("h:mm am/pm", "8:46 pm"),
        ("'Datum:' dd.MM.yyyy", "Datum: 08.05.2015"),
        ("d. MMMM yyyy", "8. Mai 2015"),
    ],
)
def test_formatiere_datum(bild, erwartet):
    assert oc.formatiere_datum(DT, bild) == erwartet


def test_formatiere_datum_maerz_mit_umlaut():
    assert oc.formatiere_datum(datetime(2020, 3, 1), "MMMM") == "März"


# --- Datum aus den Eigenschaften ------------------------------------------------

def test_druckdatum_nimmt_lastprinted(tmp_path):
    d = docx_bauen(
        tmp_path / "a.docx", body(""),
        "<cp:lastPrinted>2015-05-08T20:46:00Z</cp:lastPrinted>"
        '<dcterms:modified xsi:type="dcterms:W3CDTF">2020-01-01T10:00:00Z</dcterms:modified>',
    )
    assert oc.druckdatum(d) == (datetime(2015, 5, 8, 20, 46), "lastPrinted")


def test_druckdatum_ersatz_modified_und_created(tmp_path):
    d = docx_bauen(
        tmp_path / "a.docx", body(""),
        '<dcterms:created xsi:type="dcterms:W3CDTF">2019-02-03T08:00:00Z</dcterms:created>'
        '<dcterms:modified xsi:type="dcterms:W3CDTF">2020-01-01T10:00:00Z</dcterms:modified>',
    )
    assert oc.druckdatum(d) == (datetime(2020, 1, 1, 10, 0), "modified")
    d2 = docx_bauen(
        tmp_path / "b.docx", body(""),
        '<dcterms:created xsi:type="dcterms:W3CDTF">2019-02-03T08:00:00Z</dcterms:created>',
    )
    assert oc.druckdatum(d2) == (datetime(2019, 2, 3, 8, 0), "created")


def test_druckdatum_ignoriert_nulldatum_und_faellt_auf_dateizeit(tmp_path):
    d = docx_bauen(
        tmp_path / "a.docx", body(""),
        "<cp:lastPrinted>0001-01-01T00:00:00Z</cp:lastPrinted>",
    )
    dt, quelle = oc.druckdatum(d)
    assert quelle == "Dateizeit"
    assert dt.year >= 2000


def test_druckdatum_ohne_core_xml(tmp_path):
    d = docx_bauen(tmp_path / "a.docx", body(""), None)
    assert oc.druckdatum(d)[1] == "Dateizeit"


# --- Felder ersetzen --------------------------------------------------------------

@pytest.mark.parametrize("feld", ["PRINTDATE", "DATE", "TIME"])
def test_komplexes_feld_wird_fester_text(feld):
    xml = body(
        komplexes_feld(f' {feld}  \\@ "dddd, d. MMMM yyyy" ', "Donnerstag, 18. Juni 2020")
    )
    neu, n = oc.datumsfelder_ersetzen(xml, DT)
    assert n == 1
    assert "Freitag, 8. Mai 2015" in neu
    assert "Juni 2020" not in neu
    assert "fldChar" not in neu and "instrText" not in neu
    assert "<w:b/>" in neu  # Zeichenformat des Ergebnisses bleibt


def test_fldsimple_wird_fester_text_und_unescaped_anfuehrungszeichen():
    xml = body(
        '<w:fldSimple w:instr=" DATE  \\@ &quot;dd.MM.yyyy&quot; ">'
        "<w:r><w:rPr><w:noProof/></w:rPr><w:t>27.09.2010</w:t></w:r></w:fldSimple>"
    )
    neu, n = oc.datumsfelder_ersetzen(xml, DT)
    assert n == 1
    assert "08.05.2015" in neu and "27.09.2010" not in neu
    assert "fldSimple" not in neu
    assert "<w:noProof/>" in neu


def test_feld_ohne_bildschalter_nimmt_standardformat():
    neu, n = oc.datumsfelder_ersetzen(body(komplexes_feld(" PRINTDATE ", "00.00.0000")), DT)
    assert n == 1 and "08.05.2015" in neu


def test_feld_ohne_ergebnis_text():
    xml = body(
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText> PRINTDATE \\@ "yyyy" </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )
    neu, n = oc.datumsfelder_ersetzen(xml, DT)
    assert n == 1
    assert "<w:t xml:space=\"preserve\">2015</w:t>" in neu
    assert "fldChar" not in neu


def test_andere_felder_bleiben_unveraendert():
    xml = body(
        komplexes_feld(" PAGE ", "2")
        + komplexes_feld(' SAVEDATE \\@ "yyyy" ', "2001")
        + komplexes_feld(' HYPERLINK "https://x.de" ', "x.de")
        + komplexes_feld(" DATEIGROESSE ", "7")  # beginnt mit DATE, ist aber ein anderes Feld
        + '<w:fldSimple w:instr=" SEQ Abbildung \\* ARABIC "><w:r><w:t>1</w:t></w:r></w:fldSimple>'
    )
    neu, n = oc.datumsfelder_ersetzen(xml, DT)
    assert n == 0
    assert neu == xml


def test_mehrere_felder_gemischt_und_text_drumherum():
    xml = body(
        "<w:r><w:t>Ort, den </w:t></w:r>"
        + komplexes_feld(' PRINTDATE \\@ "dd.MM.yyyy" ', "01.01.2000")
        + komplexes_feld(" PAGE ", "3")
        + komplexes_feld(' TIME \\@ "HH:mm" ', "12:00")
    )
    neu, n = oc.datumsfelder_ersetzen(xml, DT)
    assert n == 2
    assert "Ort, den " in neu
    assert "08.05.2015" in neu and "20:46" in neu
    assert " PAGE " in neu  # PAGE-Feld bleibt


def test_ergebnis_ueber_mehrere_laeufe_wird_zusammengefasst():
    # Word zerlegt das Ergebnis manchmal in mehrere Laeufe
    xml = body(
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText> TIME \\@ "d. MMMM yyyy" </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        "<w:r><w:t>18. </w:t></w:r><w:r><w:t>Juni 2020</w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )
    neu, n = oc.datumsfelder_ersetzen(xml, DT)
    assert n == 1
    assert "8. Mai 2015" in neu and "Juni" not in neu and "18." not in neu


def test_instrtext_in_mehreren_teilen():
    xml = body(
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        "<w:r><w:instrText> PRINT</w:instrText></w:r><w:r><w:instrText>DATE \\@ \"yyyy\" </w:instrText></w:r>"
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1999</w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )
    neu, n = oc.datumsfelder_ersetzen(xml, DT)
    assert n == 1 and "2015" in neu and "1999" not in neu and "instrText" not in neu


def test_sonderzeichen_im_datumsbild_werden_escaped():
    neu, n = oc.datumsfelder_ersetzen(body(komplexes_feld(" DATE \\@ \"'A&amp;B' yyyy\" ", "x")), DT)
    assert n == 1 and "A&amp;B 2015" in neu


# --- Ganze Datei -------------------------------------------------------------------

def test_docx_mit_festem_datum_schreibt_kopie_und_laesst_original(tmp_path):
    kopf = body(komplexes_feld(' TIME \\@ "dddd, d. MMMM yyyy" ', "Donnerstag, 18. Juni 2020"))
    doc = body(komplexes_feld(' PRINTDATE \\@ "dd.MM.yyyy" ', "19.05.2015"))
    quelle = docx_bauen(
        tmp_path / "brief.docx", doc,
        "<cp:lastPrinted>2015-05-08T20:46:00Z</cp:lastPrinted>", header=kopf,
    )
    vorher = quelle.read_bytes()
    ziel = tmp_path / "kopie.docx"

    dt, quelle_name, n = oc.docx_mit_festem_datum(quelle, ziel)

    assert (dt, quelle_name, n) == (datetime(2015, 5, 8, 20, 46), "lastPrinted", 2)
    assert "08.05.2015" in teil(ziel)
    assert "Freitag, 8. Mai 2015" in teil(ziel, "word/header1.xml")
    assert quelle.read_bytes() == vorher  # Original unberuehrt
    with zipfile.ZipFile(ziel) as z:  # uebrige Teile mitgenommen
        assert z.testzip() is None
        assert {"[Content_Types].xml", "docProps/core.xml"} <= set(z.namelist())


def test_ist_office_datei():
    assert oc.ist_office_datei("a/B.DOCX") and oc.ist_office_datei(Path("x.xlsx"))
    assert not oc.ist_office_datei("x.pdf") and not oc.ist_office_datei("x.doc")


# --- umwandeln(): Fehlerfaelle ohne echtes Office -----------------------------------

def test_umwandeln_ohne_umwandler_meldet_klar(tmp_path, monkeypatch):
    d = docx_bauen(tmp_path / "a.docx", body(""), None)
    monkeypatch.setattr(oc, "word_com_verfuegbar", lambda: False)
    monkeypatch.setattr(oc, "excel_com_verfuegbar", lambda: False)
    monkeypatch.setattr(oc, "finde_libreoffice", lambda: None)
    with pytest.raises(oc.KeinUmwandlerGefunden, match="Word"):
        oc.umwandeln(d)
    assert not (tmp_path / "a.pdf").exists()


def test_umwandeln_word_da_aber_pywin32_fehlt(tmp_path, monkeypatch):
    """Live-Befund: Word installiert, aber dem Python fehlt pywin32 -> klarer Hinweis."""
    d = docx_bauen(tmp_path / "a.docx", body(""), None)
    monkeypatch.setattr(oc, "word_com_verfuegbar", lambda: False)
    monkeypatch.setattr(oc, "finde_libreoffice", lambda: None)
    monkeypatch.setattr(oc, "_com_klasse_registriert", lambda prog_id: True)
    monkeypatch.setattr(oc, "pywin32_verfuegbar", lambda: False)
    with pytest.raises(oc.KeinUmwandlerGefunden, match="pywin32"):
        oc.umwandeln(d)


def test_umwandeln_lehnt_falschen_dateityp_ab(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x")
    with pytest.raises(oc.UmwandlungFehler):
        oc.umwandeln(p)


def test_umwandeln_mit_libreoffice_rueckfall_und_ueberschreibt_nichts(tmp_path, monkeypatch):
    d = docx_bauen(
        tmp_path / "a.docx", body(komplexes_feld(' PRINTDATE \\@ "yyyy" ', "1999")),
        "<cp:lastPrinted>2015-05-08T20:46:00Z</cp:lastPrinted>",
    )
    (tmp_path / "a.pdf").write_bytes(b"vorhanden")
    gesehen = {}

    def falsches_lo(soffice, quelle, pdf, pdfa):
        gesehen["quelle"] = quelle
        gesehen["xml"] = teil(quelle)  # die Kopie mit festem Datum, nicht das Original
        pdf.write_bytes(b"%PDF-1.7 test")

    monkeypatch.setattr(oc, "word_com_verfuegbar", lambda: False)
    monkeypatch.setattr(oc, "finde_libreoffice", lambda: "soffice")
    monkeypatch.setattr(oc, "_mit_libreoffice", falsches_lo)

    erg = oc.umwandeln(d, pdfa=True)

    assert erg.werkzeug == "LibreOffice" and erg.pdfa
    assert erg.pdf == tmp_path / "a (1).pdf"
    assert erg.pdf.read_bytes().startswith(b"%PDF")
    assert (tmp_path / "a.pdf").read_bytes() == b"vorhanden"
    assert gesehen["quelle"] != d and "2015" in gesehen["xml"] and "1999" not in gesehen["xml"]
    assert erg.ersetzte_felder == 1 and erg.datum_quelle == "lastPrinted" and not erg.hinweise


def test_umwandeln_hinweis_wenn_kein_druckdatum(tmp_path, monkeypatch):
    d = docx_bauen(
        tmp_path / "a.docx", body(komplexes_feld(" PRINTDATE ", "x")),
        '<dcterms:modified xsi:type="dcterms:W3CDTF">2020-01-01T10:00:00Z</dcterms:modified>',
    )
    monkeypatch.setattr(oc, "word_com_verfuegbar", lambda: False)
    monkeypatch.setattr(oc, "finde_libreoffice", lambda: "soffice")
    monkeypatch.setattr(oc, "_mit_libreoffice", lambda s, q, pdf, a: pdf.write_bytes(b"%PDF"))
    erg = oc.umwandeln(d)
    assert erg.datum_quelle == "modified"
    assert any("Druckdatum" in h for h in erg.hinweise)


def test_word_fehler_faellt_auf_libreoffice_zurueck(tmp_path, monkeypatch):
    d = docx_bauen(tmp_path / "a.docx", body(""), None)

    def kaputt(*a, **k):
        raise RuntimeError("COM kaputt")

    monkeypatch.setattr(oc, "word_com_verfuegbar", lambda: True)
    monkeypatch.setattr(oc, "_mit_word", kaputt)
    monkeypatch.setattr(oc, "finde_libreoffice", lambda: "soffice")
    monkeypatch.setattr(oc, "_mit_libreoffice", lambda s, q, pdf, a: pdf.write_bytes(b"%PDF"))
    erg = oc.umwandeln(d)
    assert erg.werkzeug == "LibreOffice"
    assert any("COM kaputt" in h for h in erg.hinweise)


def test_xlsx_pdfa_bevorzugt_libreoffice_vor_excel(tmp_path, monkeypatch):
    x = tmp_path / "t.xlsx"
    x.write_bytes(b"PK")
    monkeypatch.setattr(oc, "excel_com_verfuegbar", lambda: True)
    monkeypatch.setattr(oc, "finde_libreoffice", lambda: "soffice")
    monkeypatch.setattr(oc, "_mit_excel", lambda *a: pytest.fail("Excel darf bei PDF/A nicht laufen"))
    monkeypatch.setattr(oc, "_mit_libreoffice", lambda s, q, pdf, a: pdf.write_bytes(b"%PDF"))
    erg = oc.umwandeln(x, pdfa=True)
    assert erg.werkzeug == "LibreOffice" and erg.pdfa

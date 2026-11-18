"""Issue #383: Streifen „Doppelt“ und „Doppelte Dateien suchen …“ erkennen auch abgelegte Fassungen.

Zwei abgelegte Fassungen derselben Rechnung sind nicht Byte fuer Byte gleich (jede traegt
eigene Metadaten). Gleich sind sie trotzdem, wenn sie denselben Vermerk des Originals
tragen (#307), wenn der Vermerk der einen zum heutigen Inhalt der anderen passt, oder -
fuer Scans, die vor v0.31 ohne Vermerk abgelegt wurden - wenn die Scanbilder gleich sind.

Alle Dateien entstehen im Test unter tmp_path; Namen sind erfunden.
"""

from __future__ import annotations

import shutil

import pikepdf
import pymupdf

import helfer_suche as h
from src.core.duplikate import PdfMerkmale, Pruefsummen, doppelte_unter, gleiche_im_ordner, original_aus_pdf
from src.core.pdf_metadata import PDFMetadata, write_metadata
from src.core.pdf_rotate import rotate_pdf


def _gruppen(pfade, merkmale=None):
    return [sorted(p.name for p in g) for g in gleiche_im_ordner(pfade, Pruefsummen(), merkmale=merkmale)]


def _alt_abgelegt(pfad, titel: str):
    """Wie vor v0.31 abgelegt: Metadaten geschrieben, aber kein Vermerk des Originals."""
    with pikepdf.open(pfad, allow_overwriting_input=True) as pdf:
        pdf.docinfo["/Title"] = titel
        with pdf.open_metadata() as meta:
            meta["dc:title"] = titel
        pdf.save()
    assert original_aus_pdf(pfad) is None


def test_zwei_abgelegte_fassungen_mit_vermerk_sind_doppelt(tmp_path):
    original = h.pdf_mit_text(tmp_path / "Scan.pdf", ["Rechnung Nr. 4711 an Max Mustermann"])
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    a = ablage / "2026-11-01 Rechnung Beispiel GmbH.pdf"
    b = ablage / "Rechnung 4711.pdf"
    shutil.copyfile(original, a)
    shutil.copyfile(original, b)
    assert write_metadata(a, PDFMetadata(korrespondent="Beispiel GmbH"))
    assert write_metadata(b, PDFMetadata(korrespondent="Beispiel GmbH", steuerjahr="2026", title="Rechnung"))
    assert a.read_bytes() != b.read_bytes()

    assert _gruppen([a, b]) == [sorted([a.name, b.name])]
    # „Doppelte Dateien suchen …“ geht ueber denselben Vergleich
    assert [sorted(p.name for p in g) for g in doppelte_unter(ablage, Pruefsummen())] == [sorted([a.name, b.name])]


def test_vermerk_passt_zum_original_im_selben_ordner(tmp_path):
    original = h.pdf_mit_text(tmp_path / "Rechnung.pdf", ["Rechnung Nr. 4711"])
    abgelegt = tmp_path / "2026-11-01 Rechnung.pdf"
    shutil.copyfile(original, abgelegt)
    assert write_metadata(abgelegt, PDFMetadata(korrespondent="Beispiel GmbH"))
    assert original.stat().st_size != abgelegt.stat().st_size

    anders = h.pdf_mit_text(tmp_path / "Brief.pdf", ["Sehr geehrter Herr Mustermann"])
    assert _gruppen([original, abgelegt, anders]) == [sorted([original.name, abgelegt.name])]


def test_verschiedene_originale_mit_vermerk_sind_nicht_doppelt(tmp_path):
    a = h.pdf_mit_text(tmp_path / "Rechnung Oktober.pdf", ["Rechnung Oktober"])
    b = h.pdf_mit_text(tmp_path / "Rechnung November.pdf", ["Rechnung November"])
    assert write_metadata(a, PDFMetadata(korrespondent="Beispiel GmbH"))
    assert write_metadata(b, PDFMetadata(korrespondent="Beispiel GmbH"))
    assert _gruppen([a, b]) == []


def test_alter_scan_ohne_vermerk_und_neue_fassung_mit_vermerk(tmp_path):
    """Der Fall aus dem Live-Test: die aeltere Datei wurde vor v0.31 abgelegt."""
    scan = h.scan_pdf(tmp_path / "Scan.pdf", ["Rechnung Nr. 4711", "Betrag 12,34 EUR"])
    alt = tmp_path / "Rechnung Müller alt.pdf"
    neu = tmp_path / "Rechnung neu.pdf"
    shutil.copyfile(scan, alt)
    shutil.copyfile(scan, neu)
    _alt_abgelegt(alt, "Rechnung")
    assert write_metadata(neu, PDFMetadata(korrespondent="Beispiel GmbH"))
    scan.unlink()

    assert _gruppen([alt, neu]) == [sorted([alt.name, neu.name])]


def test_scan_ohne_vermerk_gegen_das_original_und_gedreht(tmp_path):
    scan = h.scan_pdf(tmp_path / "Scan.pdf", ["Rechnung Nr. 4711"])
    alt = tmp_path / "Rechnung Müller alt.pdf"
    shutil.copyfile(scan, alt)
    _alt_abgelegt(alt, "Rechnung")
    gedreht = tmp_path / "Rechnung gedreht.pdf"
    shutil.copyfile(scan, gedreht)
    rotate_pdf(gedreht, 90)

    assert _gruppen([scan, alt, gedreht]) == [sorted([scan.name, alt.name, gedreht.name])]


def test_andere_scans_gleicher_form_sind_nicht_doppelt(tmp_path):
    a = h.scan_pdf(tmp_path / "Rechnung Oktober.pdf", ["Rechnung Oktober", "Betrag 12,34 EUR"])
    b = h.scan_pdf(tmp_path / "Rechnung November.pdf", ["Rechnung November", "Betrag 12,34 EUR"])
    _alt_abgelegt(a, "Rechnung")
    _alt_abgelegt(b, "Rechnung")
    assert _gruppen([a, b]) == []


def test_gleiches_logo_auf_verschiedenen_rechnungen_ist_nicht_doppelt(tmp_path):
    """Kein Scan: Das Bild bedeckt nur einen kleinen Teil der Seite, der Text unterscheidet sich."""
    a = h.pdf_mit_bild(tmp_path / "Rechnung Oktober.pdf")
    b = h.pdf_mit_bild(tmp_path / "Rechnung November.pdf")
    for pfad, monat in ((a, "Oktober"), (b, "November")):
        doc = pymupdf.open(pfad)
        doc[0].insert_text((72, 400), f"Rechnung {monat}", fontsize=11)
        doc.save(pfad, incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
        doc.close()
    assert a.read_bytes() != b.read_bytes()
    assert _gruppen([a, b]) == []


def test_bilder_werden_nur_bei_passender_form_verglichen_und_gemerkt(tmp_path):
    scan = h.scan_pdf(tmp_path / "Scan.pdf", ["Rechnung Nr. 4711"])
    zwei_seiten = h.scan_pdf(tmp_path / "Zwei Seiten.pdf", ["Rechnung Nr. 4711"], seiten=2)
    alt = tmp_path / "Rechnung Müller alt.pdf"
    shutil.copyfile(scan, alt)
    _alt_abgelegt(alt, "Rechnung")

    merkmale = PdfMerkmale()
    assert _gruppen([scan, alt, zwei_seiten], merkmale) == [sorted([scan.name, alt.name])]
    # je PDF einmal oeffnen; Bilder und Ansicht nur fuer die zwei mit gleicher Form
    assert merkmale.geoeffnet == 3 + 2 + 2
    assert _gruppen([scan, alt, zwei_seiten], merkmale) == [sorted([scan.name, alt.name])]
    assert merkmale.geoeffnet == 7  # zweiter Lauf ganz aus dem Zwischenspeicher


def test_gleiches_seitenbild_mit_anderem_sichtbarem_text_ist_nicht_doppelt(tmp_path):
    """Briefbogen als ganzseitiges Bild, darauf zwei verschiedene Rechnungen."""
    a = h.scan_pdf(tmp_path / "Rechnung Oktober.pdf", ["Beispiel GmbH, Musterstrasse 1"])
    b = tmp_path / "Rechnung November.pdf"
    shutil.copyfile(a, b)
    for pfad, monat in ((a, "Oktober"), (b, "November")):
        doc = pymupdf.open(pfad)
        doc[0].insert_text((72, 400), f"Rechnung {monat} 2026", fontsize=14)
        doc.save(pfad, incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
        doc.close()
    assert _gruppen([a, b]) == []


def test_kaputte_pdf_stoert_nicht(tmp_path):
    kaputt = tmp_path / "kaputt.pdf"
    kaputt.write_bytes(b"%PDF-1.4 kein echtes PDF")
    a = h.pdf_mit_text(tmp_path / "a.pdf", ["Brief"])
    b = tmp_path / "b.pdf"
    shutil.copyfile(a, b)
    assert _gruppen([kaputt, a, b]) == [["a.pdf", "b.pdf"]]

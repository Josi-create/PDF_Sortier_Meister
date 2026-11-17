"""Issue #307: Doppelte auch erkennen, wenn die abgelegte PDF schon veraendert wurde.

Vor dem ersten Schreiben merkt sich das Programm Groesse und Pruefsumme des
Originals in der PDF; der Indexlauf liest sie, der Vergleich zaehlt sie mit.
"""

from __future__ import annotations

import shutil

import pymupdf

import helfer_suche as h
from src.core import duplikate
from src.core.duplikate import (Pruefsummen, gleiche_anderswo, original_aus_pdf, original_eintragen_pymupdf,
                                original_lesen, pruefsumme)
from src.core.pdf_metadata import PDFMetadata, write_metadata
from src.core.pdf_rotate import rotate_pdf
from src.search.indexer import Indexer
from src.search.suchindex import Suchindex


def _original(pfad) -> tuple[int, str]:
    return pfad.stat().st_size, pruefsumme(pfad)


def test_original_lesen_nimmt_nur_gueltige_eintraege():
    summe = "ab" * 16
    assert original_lesen(f"4711:{summe}") == (4711, summe)
    assert original_lesen(f" 4711:{summe.upper()} ") == (4711, summe)
    for kaputt in (None, "", "4711", f"x:{summe}", f"0:{summe}", "4711:abc", f"4711:{'zz' * 16}"):
        assert original_lesen(kaputt) is None


def test_metadaten_schreiben_merkt_das_original_nur_beim_ersten_mal(tmp_path):
    pdf = h.pdf_mit_text(tmp_path / "Rechnung.pdf", ["Rechnung Max Mustermann"])
    vorher = _original(pdf)
    assert original_aus_pdf(pdf) is None

    assert write_metadata(pdf, PDFMetadata(korrespondent="Beispiel GmbH"))
    assert _original(pdf) != vorher  # die Datei hat sich geaendert
    assert original_aus_pdf(pdf) == vorher

    assert write_metadata(pdf, PDFMetadata(steuerjahr="2026"))
    assert original_aus_pdf(pdf) == vorher  # bleibt das erste Original


def test_drehen_merkt_das_original(tmp_path):
    pdf = h.pdf_mit_text(tmp_path / "Brief.pdf", ["Sehr geehrte Frau Beispiel"])
    vorher = _original(pdf)
    rotate_pdf(pdf, 90)
    assert original_aus_pdf(pdf) == vorher


def test_textebene_merkt_das_original_mit_pymupdf(tmp_path):
    pdf = h.pdf_mit_text(tmp_path / "Scan.pdf", ["Seite eins"])
    vorher = _original(pdf)
    kopie = tmp_path / "Scan-neu.pdf"
    doc = pymupdf.open(pdf)
    original_eintragen_pymupdf(doc, pdf)
    doc.save(kopie)
    doc.close()
    assert original_aus_pdf(kopie) == vorher

    # Ein vorhandener Eintrag bleibt
    doc = pymupdf.open(kopie)
    original_eintragen_pymupdf(doc, kopie)
    doc.save(tmp_path / "Scan-zweimal.pdf")
    doc.close()
    assert original_aus_pdf(tmp_path / "Scan-zweimal.pdf") == vorher


def test_zweites_exemplar_wird_ueber_das_original_im_index_erkannt(tmp_path):
    (tmp_path / "Download").mkdir()
    original = h.pdf_mit_text(tmp_path / "Download" / "Rechnung.pdf", ["Rechnung Max Mustermann"])
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    abgelegt = ablage / "2026-11-01 Rechnung Beispiel GmbH.pdf"
    shutil.copyfile(original, abgelegt)
    assert write_metadata(abgelegt, PDFMetadata(korrespondent="Beispiel GmbH"))
    assert pruefsumme(abgelegt) != pruefsumme(original)

    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    assert Indexer(konfig, synchron=True).lauf() == 0
    index = Suchindex(konfig)

    zweites = tmp_path / "Scan" / "Rechnung (1).pdf"
    zweites.parent.mkdir()
    shutil.copyfile(original, zweites)
    treffer = gleiche_anderswo(zweites, ablage, index.gleiche_groesse, Pruefsummen())
    assert [str(p).lower() for p in treffer] == [str(abgelegt).lower()]

    # Eine andere PDF gleicher Groesse ist kein Treffer
    anders = tmp_path / "Scan" / "Anders.pdf"
    daten = bytearray(original.read_bytes())
    daten[-2] = ord("X") if daten[-2] != ord("X") else ord("Y")
    anders.write_bytes(bytes(daten))
    assert gleiche_anderswo(anders, None, index.gleiche_groesse, Pruefsummen()) == []


def test_original_zeile_zaehlt_nicht_fuer_fehlende_datei_oder_die_quelle_selbst(tmp_path):
    quelle = tmp_path / "Neu.pdf"
    quelle.write_bytes(b"%PDF-1.4 Inhalt")
    summe = pruefsumme(quelle)
    weg = tmp_path / "Weg.pdf"
    zeilen = [{"pfad": str(weg), "pruefsumme": summe, "original": True},
              {"pfad": str(quelle), "pruefsumme": summe, "original": True}]
    assert gleiche_anderswo(quelle, None, lambda _g: zeilen, Pruefsummen()) == []

    da = tmp_path / "Abgelegt.pdf"
    da.write_bytes(b"%PDF-1.4 Inhalt, inzwischen mit Metadaten")
    zeilen.append({"pfad": str(da), "pruefsumme": summe, "original": True})
    zeilen.append({"pfad": str(da), "pruefsumme": summe, "original": True})  # doppelt im Index
    assert gleiche_anderswo(quelle, None, lambda _g: zeilen, Pruefsummen()) == [da]


def test_indexlauf_leert_das_original_ohne_eintrag(tmp_path):
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    brief = h.pdf_mit_text(ablage / "Brief.pdf", ["Sehr geehrte Frau Beispiel"])
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    assert Indexer(konfig, synchron=True).lauf() == 0
    zeilen = Suchindex(konfig).gleiche_groesse(brief.stat().st_size)
    assert [z for z in zeilen if z.get("original")] == []
    assert duplikate.ORIGINAL_SCHLUESSEL == "PSMOriginal"

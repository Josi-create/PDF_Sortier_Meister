"""Textebene mit echtem Tesseract (Phase 5b); uebersprungen, wenn Tesseract oder die Sprachdaten deu+eng fehlen.

Synthetischer Scan (Text gerendert, nur das Bild in der PDF), ein
Tesseract-Aufruf liefert Text und Text-PDF, ``datei_schreiben`` legt sie
darauf. Geprueft: ``get_text()`` findet die Woerter, die Bild-Streams sind
bytegleich, Seitengroesse und Drehung unveraendert, und die Woerter liegen
dort, wo sie im Bild stehen (auch auf einer gedrehten Seite).
"""

from __future__ import annotations

import os

import pymupdf
import pytest

from src.search import extract, textebene
from src.utils.tesseract import fehlende_sprachen, find_tesseract, tessdata_dir
from tests import helfer_suche as h

TESSERACT = find_tesseract()
TESSDATA = tessdata_dir(TESSERACT) if TESSERACT else None

pytestmark = pytest.mark.skipif(not TESSERACT or bool(fehlende_sprachen(TESSDATA, "deu+eng")),
                                reason="Tesseract mit deu+eng ist nicht installiert")

ZEILEN = ["Rechnung Nummer 4711", "Gesamtbetrag 123,45 Euro"]


def _erwartet(wort: str) -> pymupdf.Rect:
    """Wo das Wort auf der angezeigten Seite steht (wie ``helfer_suche.scan_pdf`` es zeichnet)."""
    d = pymupdf.open()
    q = d.new_page(width=595, height=842)
    for i, zeile in enumerate(ZEILEN):
        q.insert_text((72, 100 + 36 * i), zeile, fontsize=20)
    return q.search_for(wort)[0]


@pytest.mark.parametrize("drehung", [0, 90])
def test_echte_textebene_findbar_deckungsgleich_bild_unveraendert(tmp_path, drehung):
    scan = h.scan_pdf(tmp_path / "scan.pdf", ZEILEN, drehung=drehung, dpi=200)
    with pymupdf.open(scan) as d:
        bilder = {x: d.xref_stream_raw(x) for x, *_ in d[0].get_images(full=True)}
        vorher = (d[0].rect, d[0].mediabox, d[0].rotation)
    cfg = {"tesseract": TESSERACT, "tessdata": TESSDATA, "sprachen": "deu+eng", "dpi": 300, "textebene": True}
    ocr = extract.pdf_ocr(str(scan), [1], cfg)
    assert ocr["fehler"] is None and "4711" in ocr["texte"][1]
    st = os.stat(scan)
    res = textebene.datei_schreiben({
        "pfad": str(scan), "groesse": st.st_size, "mtime_ns": st.st_mtime_ns,
        "seiten": {1: {"hash": None, "ebene": ocr["ebenen"][1]}}, "ocr": None,
        "sicherung_ordner": str(tmp_path / "sicherung"), "min_zeichen": 25,
    })
    assert res["status"] == "geschrieben", res

    with pymupdf.open(scan) as d:
        s = d[0]
        text = s.get_text()
        for wort in ("Rechnung", "4711", "Gesamtbetrag"):
            assert wort in text
        assert {x: d.xref_stream_raw(x) for x in bilder} == bilder
        assert (s.rect, s.mediabox, s.rotation) == vorher
        assert extract.hat_ocr_textebene(s)
        for wort in ("4711", "Gesamtbetrag"):
            angezeigt = s.search_for(wort)[0] * s.rotation_matrix
            soll = _erwartet(wort)
            assert abs(angezeigt.x0 - soll.x0) < 8 and abs(angezeigt.y0 - soll.y0) < 8, (wort, angezeigt, soll)

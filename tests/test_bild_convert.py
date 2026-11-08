"""Issue #184: Bilder in PDF umwandeln (Kern, ohne Qt-Fenster).

Tesseract laeuft nie: ``ocr_einstellungen`` und ``ocr_seite`` werden ersetzt
(conftest setzt ``ocr_einstellungen`` ohnehin auf "kein Tesseract").
"""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from src.core import bild_convert as bc
from src.core.bild_convert import BildFehler, bilder_in_pdf


def _bild(pfad: Path, groesse=(200, 100), farbe="red", modus="RGB", **kw) -> Path:
    Image.new(modus, groesse, farbe).save(pfad, **kw)
    return pfad


def _text_pdf(text: str) -> bytes:
    """Wie die Text-PDF von Tesseract: eine Seite mit (hier sichtbarem) Text."""
    doc = pymupdf.open()
    doc.new_page(width=100, height=100).insert_text((10, 50), text)
    return doc.tobytes()


def test_endungen_und_sortierbar(tmp_path, monkeypatch):
    from src.core.office_convert import ist_office_datei, ist_sortierbar

    monkeypatch.setattr(bc, "heif_verfuegbar", lambda: False)
    for name in ("a.jpg", "a.JPEG", "a.png", "a.tif", "a.TIFF", "a.bmp", "a.gif", "a.webp"):
        assert bc.ist_bild_datei(name) and ist_sortierbar(name) and ist_office_datei(name), name
    for name in ("a.heic", "a.HEIF", "a.doc", "a.txt", "a"):
        assert not bc.ist_bild_datei(name) and not ist_sortierbar(name), name
    assert ist_sortierbar("a.pdf") and ist_sortierbar("a.docx")
    monkeypatch.setattr(bc, "heif_verfuegbar", lambda: True)  # mit pillow-heif
    assert bc.ist_bild_datei("a.heic") and bc.ist_bild_datei("a.HEIF")


def test_heic_ohne_paket_wird_ignoriert(tmp_path, monkeypatch):
    from src.core.file_manager import FileManager

    monkeypatch.setattr(bc, "heif_verfuegbar", lambda: False)
    (tmp_path / "foto.heic").write_bytes(b"x")
    _bild(tmp_path / "foto.jpg")
    assert [p.name for p in FileManager(tmp_path).get_office_files()] == ["foto.jpg"]


@pytest.mark.parametrize("name,kw", [("a.jpg", {}), ("a.png", {}), ("a.bmp", {}), ("a.gif", {}), ("a.webp", {})])
def test_umwandeln_einzelformate(tmp_path, name, kw):
    quelle = _bild(tmp_path / name)
    erg = bilder_in_pdf([quelle])
    assert erg.pdf == tmp_path / (Path(name).stem + ".pdf") and erg.seiten == 1
    assert quelle.exists()  # Original bleibt
    assert bc.pdf_lesbar(erg.pdf, 1)
    assert not list(tmp_path.glob("*.part"))


def test_png_mit_transparenz(tmp_path):
    quelle = _bild(tmp_path / "t.png", modus="RGBA", farbe=(255, 0, 0, 0))
    assert bilder_in_pdf([quelle]).seiten == 1


def test_mehrseitiges_tiff(tmp_path):
    seiten = [Image.new("RGB", (60, 40 + 10 * i), c) for i, c in enumerate(("red", "blue", "green"))]
    quelle = tmp_path / "m.tif"
    seiten[0].save(quelle, save_all=True, append_images=seiten[1:])
    erg = bilder_in_pdf([quelle])
    assert erg.seiten == 3 and bc.pdf_lesbar(erg.pdf, 3)


def test_exif_ausrichtung_wird_beachtet(tmp_path):
    bild = Image.new("RGB", (200, 100), "red")
    exif = bild.getexif()
    exif[274] = 6  # Handyfoto: 90 Grad im Uhrzeigersinn drehen -> hochkant
    bild.save(tmp_path / "foto.jpg", exif=exif)
    erg = bilder_in_pdf([tmp_path / "foto.jpg"])
    with pymupdf.open(erg.pdf) as doc:
        assert doc[0].rect.height > doc[0].rect.width


def test_exif_ausrichtung_bei_webp_ueber_pillow(tmp_path):
    bild = Image.new("RGB", (200, 100), "red")
    exif = bild.getexif()
    exif[274] = 6
    bild.save(tmp_path / "foto.webp", exif=exif)
    erg = bilder_in_pdf([tmp_path / "foto.webp"])
    with pymupdf.open(erg.pdf) as doc:
        assert doc[0].rect.height > doc[0].rect.width


def test_mehrere_bilder_zu_einem_pdf_in_reihenfolge(tmp_path):
    vorn = _bild(tmp_path / "scan_vorn.jpg", (100, 50))      # quer
    hinten = _bild(tmp_path / "scan_hinten.png", (50, 100))  # hoch
    mitte = _bild(tmp_path / "scan_mitte.bmp", (80, 80))     # quadratisch
    erg = bilder_in_pdf([vorn, hinten, mitte])
    assert erg.pdf == tmp_path / "scan_vorn.pdf"  # Name vom ersten Bild
    with pymupdf.open(erg.pdf) as doc:
        assert doc.page_count == 3
        formen = [(p.rect.width > p.rect.height) - (p.rect.width < p.rect.height) for p in doc]
    assert formen == [1, -1, 0]
    assert vorn.exists() and hinten.exists() and mitte.exists()


def test_vorhandenes_ziel_wird_nicht_ueberschrieben(tmp_path):
    quelle = _bild(tmp_path / "a.jpg")
    (tmp_path / "a.pdf").write_bytes(b"alt")
    erg = bilder_in_pdf([quelle])
    assert erg.pdf == tmp_path / "a (1).pdf" and (tmp_path / "a.pdf").read_bytes() == b"alt"


def test_ocr_wird_aufgerufen_und_textebene_aufgelegt(tmp_path, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(bc, "ocr_einstellungen", lambda: {"tesseract": "t", "sprachen": "deu"})

    def ocr(seite, cfg):
        aufrufe.append(cfg["sprachen"])
        return "Rechnung", _text_pdf("Rechnung")

    monkeypatch.setattr(bc, "ocr_seite", ocr)
    erg = bilder_in_pdf([_bild(tmp_path / "a.jpg"), _bild(tmp_path / "b.jpg")])
    assert aufrufe == ["deu", "deu"] and erg.ocr_seiten == 2 and erg.ocr_hinweis is None
    with pymupdf.open(erg.pdf) as doc:
        assert all("Rechnung" in p.get_text() for p in doc)


def test_ohne_ocr_wird_trotzdem_umgewandelt_mit_hinweis(tmp_path):
    erg = bilder_in_pdf([_bild(tmp_path / "a.jpg")])  # conftest: kein Tesseract
    assert erg.ocr_seiten == 0 and "Tesseract" in erg.ocr_hinweis
    assert bc.pdf_lesbar(erg.pdf)


def test_ocr_false_ruft_keine_texterkennung(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "ocr_einstellungen", lambda: pytest.fail("OCR gestartet"))
    erg = bilder_in_pdf([_bild(tmp_path / "a.jpg")], ocr=False)
    assert erg.ocr_hinweis is None


def test_ocr_fehler_je_seite_bricht_nicht_ab(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "ocr_einstellungen", lambda: {"tesseract": "t", "sprachen": "deu"})

    def kaputt(seite, cfg):
        raise RuntimeError("tesseract abgestuerzt")

    monkeypatch.setattr(bc, "ocr_seite", kaputt)
    erg = bilder_in_pdf([_bild(tmp_path / "a.jpg")])
    assert bc.pdf_lesbar(erg.pdf) and "fehlgeschlagen" in erg.ocr_hinweis


def test_kaputtes_bild_liefert_fehler_und_laesst_nichts_liegen(tmp_path):
    kaputt = tmp_path / "x.jpg"
    kaputt.write_bytes(b"das ist kein bild")
    with pytest.raises(BildFehler):
        bilder_in_pdf([kaputt])
    assert [p.name for p in tmp_path.iterdir()] == ["x.jpg"]


def test_falscher_typ_und_fehlende_datei(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    with pytest.raises(BildFehler, match="nicht unterstützt"):
        bilder_in_pdf([tmp_path / "a.txt"])
    with pytest.raises(BildFehler, match="nicht gefunden"):
        bilder_in_pdf([tmp_path / "fehlt.jpg"])
    with pytest.raises(BildFehler):
        bilder_in_pdf([])


def test_pdf_lesbar(tmp_path):
    assert not bc.pdf_lesbar(tmp_path / "fehlt.pdf")
    (tmp_path / "kaputt.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    assert not bc.pdf_lesbar(tmp_path / "kaputt.pdf")
    erg = bilder_in_pdf([_bild(tmp_path / "a.jpg")])
    assert bc.pdf_lesbar(erg.pdf) and not bc.pdf_lesbar(erg.pdf, 2)


def test_vorschau_pdf_fuer_bilder_ohne_ocr(tmp_path, monkeypatch):
    from src.core import office_vorschau

    monkeypatch.setattr(bc, "ocr_einstellungen", lambda: pytest.fail("Vorschau braucht keine OCR"))
    pdf = office_vorschau.vorschau_pdf(_bild(tmp_path / "a.jpg"), tmp_path / "cache")
    assert pdf.parent == tmp_path / "cache" and bc.pdf_lesbar(pdf)


def test_analyse_von_bildern_ohne_text(tmp_path):
    from src.core.office_analyse import analysiere

    text, keywords, daten = analysiere(_bild(tmp_path / "a.jpg"))
    assert text == ""

"""Issue #252: Bilder drehen - JPEG ueber die EXIF-Ausrichtung (Bilddaten unveraendert), PNG/BMP verlustfrei."""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageOps
from PIL.PngImagePlugin import PngInfo

from src.core.bild_drehen import (
    _NACH_DREHUNG,
    BildDrehenNichtMoeglich,
    bild_drehen,
    ist_drehbares_bild,
)
from src.core.pdf_rotate import DrehenNichtMoeglich, gegenrichtung

T = Image.Transpose
IM_UHRZEIGERSINN = {90: T.ROTATE_270, 180: T.ROTATE_180, -90: T.ROTATE_90, 270: T.ROTATE_90}
LAGE = {1: None, 2: T.FLIP_LEFT_RIGHT, 3: T.ROTATE_180, 4: T.FLIP_TOP_BOTTOM,
        5: T.TRANSPOSE, 6: T.ROTATE_270, 7: T.TRANSVERSE, 8: T.ROTATE_90}


def _muster(modus="RGB", groesse=(48, 32)) -> Image.Image:
    """Unsymmetrisches Bild: jede Drehung und Spiegelung ergibt andere Pixel."""
    bild = Image.new("RGB", groesse, "white")
    for x in range(groesse[0]):
        for y in range(groesse[1]):
            bild.putpixel((x, y), (x * 5 % 256, y * 7 % 256, (x + 2 * y) % 256))
    for x in range(8):
        for y in range(8):
            bild.putpixel((x, y), (255, 0, 0))  # Marke oben links
    return bild if modus == "RGB" else bild.convert(modus)


def _jpeg(pfad: Path, orientation: int | None = None, mit_marke: bool = False) -> Path:
    exif = Image.Exif()
    if mit_marke:
        exif[0x010F] = "Mustermann Kamera"  # Make
    if orientation is not None:
        exif[0x0112] = orientation
    optionen = {"exif": exif} if len(exif) else {}
    _muster().save(pfad, "JPEG", quality=85, **optionen)
    return pfad


def _angezeigt(pfad: Path) -> Image.Image:
    with Image.open(pfad) as bild:
        return ImageOps.exif_transpose(bild).copy()


def _gleich(a: Image.Image, b: Image.Image) -> bool:
    return a.size == b.size and a.mode == b.mode and a.tobytes() == b.tobytes()


def _bilddaten(pfad: Path) -> bytes:
    """Alles ab den Tabellen/Bilddaten (hinter den APPn-Abschnitten)."""
    daten = pfad.read_bytes()
    pos = 2
    while daten[pos] == 0xFF and 0xE0 <= daten[pos + 1] <= 0xEF:
        pos += 2 + int.from_bytes(daten[pos + 2:pos + 4], "big")
    return daten[pos:]


def test_tabelle_stimmt_mit_pillow_ueberein():
    roh = _muster("L", (16, 12))

    def zeigen(lage):
        return roh if LAGE[lage] is None else roh.transpose(LAGE[lage])

    for grad, tabelle in _NACH_DREHUNG.items():
        for alt, neu in tabelle.items():
            assert _gleich(zeigen(alt).transpose(IM_UHRZEIGERSINN[grad]), zeigen(neu)), (grad, alt, neu)


@pytest.mark.parametrize("grad", [90, -90, 180, 270])
def test_jpeg_ohne_exif_bilddaten_bleiben_gleich(tmp_path, grad):
    pfad = _jpeg(tmp_path / "Foto Größe.jpg")  # Umlaute im Namen
    vorher_daten, vorher_bild = _bilddaten(pfad), _angezeigt(pfad)

    assert bild_drehen(pfad, grad) == pfad

    assert _bilddaten(pfad) == vorher_daten  # keine Neukodierung
    assert _gleich(_angezeigt(pfad), vorher_bild.transpose(IM_UHRZEIGERSINN[grad]))
    assert pfad.read_bytes()[2:4] == b"\xff\xe0"  # JFIF-Kopf bleibt vorn
    assert [p.name for p in tmp_path.iterdir()] == [pfad.name]  # keine Hilfsdatei bleibt liegen


@pytest.mark.parametrize("lage", range(1, 9))
@pytest.mark.parametrize("grad", [90, -90, 180])
def test_jpeg_mit_exif_aendert_nur_den_eintrag(tmp_path, lage, grad):
    pfad = _jpeg(tmp_path / "foto.jpeg", orientation=lage, mit_marke=True)
    vorher = pfad.read_bytes()
    vorher_bild = _angezeigt(pfad)

    bild_drehen(pfad, grad)

    nachher = pfad.read_bytes()
    assert len(nachher) == len(vorher)
    assert sum(1 for a, b in zip(vorher, nachher) if a != b) == 1  # ein Byte des Orientation-Werts
    assert _gleich(_angezeigt(pfad), vorher_bild.transpose(IM_UHRZEIGERSINN[grad]))
    with Image.open(pfad) as bild:
        assert bild.getexif()[0x010F] == "Mustermann Kamera"

    bild_drehen(pfad, gegenrichtung(grad))  # Rueckgaengig: wieder Byte fuer Byte das Original
    assert pfad.read_bytes() == vorher


def test_jpeg_exif_ohne_orientation_behaelt_die_angaben(tmp_path):
    pfad = _jpeg(tmp_path / "foto.jpg", mit_marke=True)
    vorher_daten, vorher_bild = _bilddaten(pfad), _angezeigt(pfad)

    bild_drehen(pfad, 90)

    with Image.open(pfad) as bild:
        exif = bild.getexif()
        assert exif[0x0112] == 6 and exif[0x010F] == "Mustermann Kamera"
    assert _bilddaten(pfad) == vorher_daten
    assert _gleich(_angezeigt(pfad), vorher_bild.transpose(T.ROTATE_270))
    assert pfad.read_bytes().count(b"Exif\x00\x00") == 1  # ersetzt, nicht verdoppelt


def test_jpeg_viermal_rechts_und_hin_und_zurueck(tmp_path):
    pfad = _jpeg(tmp_path / "foto.jpg")
    original = _angezeigt(pfad)
    bild_drehen(pfad, 90)
    einmal = pfad.read_bytes()
    for _ in range(3):
        bild_drehen(pfad, 90)
    assert _gleich(_angezeigt(pfad), original)
    bild_drehen(pfad, 90)
    assert pfad.read_bytes() == einmal
    bild_drehen(pfad, -90)
    assert _gleich(_angezeigt(pfad), original)


def test_gedrehtes_jpeg_wird_auch_als_pdf_gedreht_umgewandelt(tmp_path):
    """Die Umwandlung in PDF (pymupdf) beachtet die eingetragene Ausrichtung - mit und ohne JFIF-Kopf."""
    import pymupdf

    from src.core.bild_convert import _pdf_bytes

    for name, lage in (("ohne.jpg", None), ("mit.jpg", 1)):
        pfad = _jpeg(tmp_path / name, orientation=lage)
        bild_drehen(pfad, 90)
        with pymupdf.open("pdf", _pdf_bytes(pfad)) as doc:
            assert doc[0].rect.height > doc[0].rect.width, name  # 48x32 quer -> hochkant


@pytest.mark.parametrize("modus", ["RGB", "RGBA", "L", "P", "1"])
@pytest.mark.parametrize("grad", [90, -90, 180])
def test_png_verlustfrei_mit_angaben(tmp_path, modus, grad):
    bild = _muster(modus)
    if modus == "RGBA":
        bild.putalpha(Image.linear_gradient("L").resize(bild.size))
    info = PngInfo()
    info.add_text("Title", "Beispiel von Max Mustermann")
    pfad = tmp_path / "Maß.png"
    bild.save(pfad, "PNG", pnginfo=info, dpi=(300, 300))

    bild_drehen(pfad, grad)

    with Image.open(pfad) as neu:
        assert neu.format == "PNG" and neu.mode == modus
        assert neu.text["Title"] == "Beispiel von Max Mustermann"
        assert round(neu.info["dpi"][0]) == 300
        assert _gleich(neu.convert("RGBA"), bild.transpose(IM_UHRZEIGERSINN[grad]).convert("RGBA"))

    bild_drehen(pfad, gegenrichtung(grad))
    with Image.open(pfad) as zurueck:
        assert _gleich(zurueck.convert("RGBA"), bild.convert("RGBA"))


def test_png_palette_mit_transparenz_bleibt_transparent(tmp_path):
    bild = _muster("P")
    pfad = tmp_path / "p.png"
    bild.save(pfad, "PNG", transparency=0)
    with Image.open(pfad) as vorher:
        erwartet = vorher.convert("RGBA").transpose(T.ROTATE_270)

    bild_drehen(pfad, 90)

    with Image.open(pfad) as neu:
        assert neu.mode == "P" and neu.info.get("transparency") == 0
        assert _gleich(neu.convert("RGBA"), erwartet)


def test_bmp_verlustfrei(tmp_path):
    bild = _muster()
    pfad = tmp_path / "scan.bmp"
    bild.save(pfad, "BMP")
    bild_drehen(pfad, -90)
    with Image.open(pfad) as neu:
        assert neu.format == "BMP" and _gleich(neu.convert("RGB"), bild.transpose(T.ROTATE_90))


@pytest.mark.parametrize("name", ["seiten.tif", "bild.webp", "bild.gif", "foto.heic", "a.pdf"])
def test_andere_formate_werden_nicht_angefasst(tmp_path, name):
    pfad = tmp_path / name
    pfad.write_bytes(b"irgendwas")
    assert not ist_drehbares_bild(pfad)
    with pytest.raises(BildDrehenNichtMoeglich):
        bild_drehen(pfad, 90)
    assert pfad.read_bytes() == b"irgendwas"


@pytest.mark.parametrize("name", ["kaputt.jpg", "kaputt.png"])
def test_unlesbare_datei_bleibt_unveraendert(tmp_path, name):
    pfad = tmp_path / name
    pfad.write_bytes(b"kein Bild")
    with pytest.raises(DrehenNichtMoeglich):
        bild_drehen(pfad, 90)
    assert pfad.read_bytes() == b"kein Bild"
    assert [p.name for p in tmp_path.iterdir()] == [name]


def test_png_inhalt_mit_jpg_endung_wird_abgelehnt(tmp_path):
    puffer = io.BytesIO()
    _muster().save(puffer, "PNG")
    pfad = tmp_path / "falsch.jpg"
    pfad.write_bytes(puffer.getvalue())
    with pytest.raises(BildDrehenNichtMoeglich):
        bild_drehen(pfad, 90)
    assert pfad.read_bytes() == puffer.getvalue()


def test_winkel_und_fehlende_datei(tmp_path):
    pfad = _jpeg(tmp_path / "foto.jpg")
    with pytest.raises(ValueError):
        bild_drehen(pfad, 45)
    with pytest.raises(FileNotFoundError):
        bild_drehen(tmp_path / "weg.jpg", 90)
    assert ist_drehbares_bild("X.JPG") and ist_drehbares_bild("x.PNG") and ist_drehbares_bild("x.bmp")


def test_jpeg_exif_in_motorola_reihenfolge(tmp_path):
    """EXIF mit Byte-Reihenfolge MM (viele Kameras) - der Eintrag wird genauso an Ort und Stelle geaendert."""
    exif = Image.Exif()
    exif.endian = ">"
    exif[0x0112] = 6
    pfad = tmp_path / "foto.jpg"
    _muster().save(pfad, "JPEG", exif=exif)
    vorher = pfad.read_bytes()
    assert b"Exif\x00\x00MM" in vorher

    bild_drehen(pfad, 90)

    nachher = pfad.read_bytes()
    assert len(nachher) == len(vorher) and sum(1 for a, b in zip(vorher, nachher) if a != b) == 1
    with Image.open(pfad) as bild:
        assert bild.getexif()[0x0112] == 3

"""Issue #205: Fotografierte Dokumente entzerren (Kernlogik, Qt-frei).

Die Fotos sind synthetisch (``tests/helfer_entzerren.py``): ein weisses Blatt mit Text, Stempel und
Logo, perspektivisch auf dunklen, hellen oder gemusterten Untergrund gelegt, mit und ohne Schatten.
"""
from __future__ import annotations

import math

import numpy as np
import pymupdf
import pytest
from PIL import Image

from src.core import entzerren as ez
from src.core.bild_convert import bilder_in_pdf
from tests.helfer_entzerren import blatt, ecken_abstand, foto, kamera_ecken, untergrund

GROESSE = (1200, 900)
DIAGONALE = math.hypot(*GROESSE)
SCHRAEG = kamera_ecken(35, 20, 5, z=450)      # kraeftig gekippt
LEICHT = kamera_ecken(12, -8, 3, z=520)       # leichte Schraeglage


def _luminanz(bild) -> np.ndarray:
    return np.asarray(bild.convert("L"), dtype=np.float32)


# --- Ecken finden ---------------------------------------------------------------------

@pytest.mark.parametrize("art", ["dunkel", "hell", "muster"])
@pytest.mark.parametrize("verlauf", [0.0, 0.4])
@pytest.mark.parametrize("ecken", [SCHRAEG, LEICHT], ids=["schraeg", "leicht"])
def test_ecken_auf_wenige_prozent_genau_und_sicher(art, verlauf, ecken):
    erk = ez.blatt_finden(foto(ecken, GROESSE, art=art, verlauf=verlauf))
    assert erk.sicher, (erk.methode, erk.konfidenz, erk.gruende)
    assert ecken_abstand(erk.ecken, ecken) < 0.02 * DIAGONALE


def test_ecken_reihenfolge_und_methode():
    erk = ez.blatt_finden(foto(SCHRAEG, GROESSE, art="dunkel"))
    (a, b, c, d) = erk.ecken
    assert a[0] < b[0] and d[0] < c[0] and a[1] < d[1] and b[1] < c[1]  # oben links, oben rechts, unten rechts, unten links
    assert erk.methode in ("helligkeit", "kanten")
    # Helles Blatt auf hellem Tisch: nur der Kantenweg sieht es
    assert ez.blatt_finden(foto(SCHRAEG, GROESSE, art="hell")).methode == "kanten"


def test_grosses_foto_wird_zum_suchen_verkleinert():
    gross = foto([(x * 3, y * 3) for x, y in SCHRAEG], (3600, 2700), art="dunkel", verlauf=0.3)
    erk = ez.blatt_finden(gross)
    assert erk.sicher and ecken_abstand(erk.ecken, [(x * 3, y * 3) for x, y in SCHRAEG]) < 0.02 * DIAGONALE * 3
    assert erk.dauer < 5


@pytest.mark.parametrize("name", ["rauschen", "einfarbig", "verlauf", "untergrund"])
def test_ohne_blatt_ist_die_konfidenz_niedrig(name):
    rng = np.random.default_rng(1)
    bilder = {
        "rauschen": Image.fromarray(rng.integers(0, 255, (900, 1200, 3), dtype=np.uint8)),
        "einfarbig": Image.new("RGB", GROESSE, (120, 120, 120)),
        "verlauf": Image.fromarray(np.tile(np.linspace(0, 255, 1200), (900, 1))[:, :, None].repeat(3, 2).astype(np.uint8)),
        "untergrund": untergrund(GROESSE, "muster"),
    }
    erk = ez.blatt_finden(bilder[name])
    assert not erk.sicher and erk.konfidenz < ez.KONFIDENZ_SICHER
    assert len(erk.ecken) == 4  # immer ein Vorschlag fuer den Dialog


def test_standard_ecken_liegen_eingerueckt():
    ecken = ez.standard_ecken(1000, 500)
    assert ecken[0] == (50.0, 25.0) and ecken[2] == (950.0, 475.0)


# --- Seitenverhaeltnis und Format -----------------------------------------------------------

@pytest.mark.parametrize("kippung", [(0, 0, 0), (30, 0, 3), (35, 20, 5), (45, -25, -10), (20, 15, 25)])
def test_seitenverhaeltnis_aus_der_perspektive(kippung):
    ecken = kamera_ecken(*kippung, z=450)
    assert ez.seitenverhaeltnis(ecken, GROESSE) == pytest.approx(210 / 297, rel=0.03)


def test_a4_rastet_ein_hoch_und_quer():
    b, h, name = ez.seitenformat(0.72)  # knapp 2 % neben A4
    assert (name, round(b), round(h)) == ("A4", 210, 297)
    b, h, name = ez.seitenformat(1 / 0.70)  # quer
    assert (name, round(b), round(h)) == ("A4", 297, 210)


def test_letter_rastet_ein_und_zu_weit_weg_bleibt_frei():
    b, h, name = ez.seitenformat(215.9 / 279.4)
    assert name == "Letter" and round(b, 1) == 215.9
    b, h, name = ez.seitenformat(0.55)  # zwischen allem: bleibt wie gemessen
    assert name == "frei" and b / h == pytest.approx(0.55, rel=1e-6)


def test_kassenbon_behaelt_sein_verhaeltnis():
    bon = kamera_ecken(10, 5, 0, z=450, mm=(80.0, 250.0))
    verh = ez.seitenverhaeltnis(bon, GROESSE)
    b, h, name = ez.seitenformat(verh)
    assert name == "frei" and b / h == pytest.approx(80 / 250, rel=0.04)
    assert b <= 210 + 1e-6 and h <= 297 + 1e-6


def test_entzerrte_seite_hat_a4_format_und_vernuenftige_aufloesung(monkeypatch):
    monkeypatch.setattr(ez, "ZIEL_DPI", 150)  # das synthetische Foto hat nur ca. 175 dpi am Blatt
    gross = foto([(x * 3, y * 3) for x, y in SCHRAEG], (3600, 2700), art="muster", verlauf=0.3)
    erk = ez.blatt_finden(gross)
    bild, (b_pt, h_pt), name = ez.entzerrte_seite(gross, erk.ecken, "farbe")
    assert name == "A4" and (round(b_pt), round(h_pt)) == (595, 842)
    assert bild.size[0] == round(210 / 25.4 * 150)  # genug Quellpixel: volle Zielaufloesung
    assert bild.size[0] / bild.size[1] == pytest.approx(210 / 297, rel=0.01)


def test_kleine_quelle_wird_nicht_hochgerechnet():
    klein = foto(SCHRAEG, GROESSE, art="dunkel")  # Blatt nur ca. 750 px breit
    bild, _pt, _n = ez.entzerrte_seite(klein, SCHRAEG)
    assert bild.size[0] < round(210 / 25.4 * ez.ZIEL_DPI)
    assert bild.size[0] >= round(210 / 25.4 * ez.MIN_DPI)


def test_vorschau_begrenzt_die_groesse():
    bild, _pt, _n = ez.entzerrte_seite(foto(SCHRAEG, GROESSE), SCHRAEG, "farbe", max_pixel=300)
    assert max(bild.size) <= 300


def test_entzerrtes_blatt_gleicht_dem_original():
    """Das Blatt wird wirklich gerade: Die Textzeilen stehen waagerecht (Zeilenprofil scharf)."""
    foto_ = foto(SCHRAEG, GROESSE, art="dunkel")
    bild, _pt, _n = ez.entzerrte_seite(foto_, ez.blatt_finden(foto_).ecken, "grau")
    lum = _luminanz(bild)
    h, b = lum.shape
    innen = lum[int(h * 0.06):int(h * 0.94), int(b * 0.06):int(b * 0.94)]  # ohne Randsaum
    profil = (innen < 128).sum(axis=1)
    # Waagerechte Zeilen: fast leere und volle Zeilen wechseln hart
    assert profil.max() > 0.2 * innen.shape[1] and (profil < 0.01 * innen.shape[1]).mean() > 0.3


# --- Tonwerte -------------------------------------------------------------------------------

def _entzerrt(tonwerte, verlauf=0.45):
    f = foto(SCHRAEG, GROESSE, art="muster", verlauf=verlauf)
    return ez.entzerrte_seite(f, ez.blatt_finden(f).ecken, tonwerte)[0]


def test_farbe_papier_weiss_schrift_dunkel_stempel_bleibt_farbig():
    bild = _entzerrt("farbe")
    assert bild.mode == "RGB"
    rgb = np.asarray(bild, dtype=np.float32)
    lum = _luminanz(bild)
    h, b = lum.shape
    # Beleuchtung ausgeglichen: auch in der schattigen Ecke ist das Papier weiss
    for ys, xs in ((slice(0, h // 8), slice(0, b // 8)), (slice(-h // 8, None), slice(-b // 8, None))):
        assert np.percentile(lum[ys, xs], 70) > 240
    assert np.percentile(lum, 1) < 60  # Schrift kraeftig
    assert ((rgb[:, :, 0] - rgb[:, :, 1] > 90)).sum() > 200  # roter Stempel
    assert ((rgb[:, :, 2] - rgb[:, :, 0] > 90)).sum() > 200  # blaues Logo


def test_graustufen_und_schwarzweiss():
    grau = _entzerrt("grau")
    assert grau.mode == "L" and np.percentile(np.asarray(grau), 70) > 240
    sw = _entzerrt("sw")
    assert sw.mode == "1"
    werte = np.unique(np.asarray(sw.convert("L")))
    assert set(werte) <= {0, 255} and len(werte) == 2
    weiss = (np.asarray(sw.convert("L")) == 255).mean()
    assert 0.6 < weiss < 0.95  # viel Papier, etwas Schrift


def test_unbekannte_tonwerte_fallen_auf_farbe_zurueck():
    assert ez.tonwerte_anwenden(Image.new("RGB", (40, 40), "white"), "quatsch").mode == "RGB"


# --- PDF -----------------------------------------------------------------------------------

def test_bilder_in_pdf_mit_entzerrung(tmp_path):
    pfad = tmp_path / "foto.jpg"
    foto(SCHRAEG, GROESSE, art="dunkel", verlauf=0.3).save(pfad, quality=95)
    erk = ez.blatt_finden(ez.bild_laden(pfad))
    erg = bilder_in_pdf([pfad], entzerrung={pfad: ez.Entzerrung(erk.ecken, "sw")})
    with pymupdf.open(erg.pdf) as doc:
        assert doc.page_count == 1
        assert (round(doc[0].rect.width), round(doc[0].rect.height)) == (595, 842)
        assert doc.get_page_images(0)[0][4] == 1  # Schwarzweiss: 1 Bit je Pixel
    assert pfad.exists()  # das Foto bleibt


def test_bilder_in_pdf_mischt_entzerrte_und_normale_bilder(tmp_path):
    a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
    foto(SCHRAEG, GROESSE).save(a)
    Image.new("RGB", (200, 100), "red").save(b)
    auftrag = {a: ez.Entzerrung(ez.blatt_finden(ez.bild_laden(a)).ecken, "farbe")}
    erg = bilder_in_pdf([a, b], tmp_path / "zwei.pdf", entzerrung=auftrag)
    with pymupdf.open(erg.pdf) as doc:
        assert doc.page_count == 2
        assert round(doc[0].rect.height) == 842 and round(doc[1].rect.width) != 595


def test_exif_wird_beim_laden_beachtet(tmp_path):
    bild = Image.new("RGB", (200, 100), "red")
    exif = bild.getexif()
    exif[274] = 6  # 90 Grad
    pfad = tmp_path / "x.jpg"
    bild.save(pfad, exif=exif)
    assert ez.bild_laden(pfad).size == (100, 200)


# --- HEIC ----------------------------------------------------------------------------------

def test_heic_foto_wird_gelesen_und_entzerrt(tmp_path):
    pillow_heif = pytest.importorskip("pillow_heif")
    from src.core.bild_convert import heif_verfuegbar, ist_bild_datei

    pfad = tmp_path / "foto.heic"
    pillow_heif.from_pillow(foto(SCHRAEG, GROESSE, art="dunkel")).save(pfad, quality=90)
    assert heif_verfuegbar() and ist_bild_datei(pfad)
    bild = ez.bild_laden(pfad)
    assert bild.size == GROESSE
    erk = ez.blatt_finden(bild)
    assert erk.sicher and ecken_abstand(erk.ecken, SCHRAEG) < 0.02 * DIAGONALE
    erg = bilder_in_pdf([pfad], entzerrung={pfad: ez.Entzerrung(erk.ecken, "farbe")})
    with pymupdf.open(erg.pdf) as doc:
        assert (round(doc[0].rect.width), round(doc[0].rect.height)) == (595, 842)
    # ohne Entzerren geht HEIC ebenfalls
    assert bilder_in_pdf([pfad], tmp_path / "roh.pdf").seiten == 1


def test_blatt_hat_erwartetes_verhaeltnis():
    b = blatt()
    assert b.size[0] / b.size[1] == pytest.approx(210 / 297, rel=0.01)

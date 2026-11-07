"""Issue #165: schief gescannte Seiten messen und gerade ausrichten (src/search/gerade.py, pdf_rotate)."""
import math
from pathlib import Path

import pymupdf
import pytest

from src.core.pdf_rotate import DrehenNichtMoeglich, ausrichtung_zuruecknehmen, gerade_ausrichten
from src.search import extract, gerade
from tests import helfer_suche as h

TOLERANZ = 0.15     # Grad; die Messung trifft synthetische Scans auf wenige Hundertstel


def _messen(pfad: Path, nr: int = 1):
    return h.schraeglage_der_datei(pfad, nr)


# --------------------------------------------------------------------------- Messen

@pytest.mark.parametrize("winkel", [-6.0, -1.5, 0.8, 2.5, 9.0])
def test_misst_den_winkel(tmp_path, winkel):
    scan = h.scan_schief(tmp_path / "s.pdf", winkel)
    assert _messen(scan) == pytest.approx(winkel, abs=TOLERANZ)


@pytest.mark.parametrize("inhalt", [90, 180, 270])
def test_misst_auch_quer_und_kopfstehend(tmp_path, inhalt):
    """Die Schraeglage haengt nicht davon ab, ob die Seite quer liegt oder auf dem Kopf steht (Issue #151)."""
    scan = h.scan_schief(tmp_path / "s.pdf", 2.0, inhalt_drehung=inhalt)
    assert _messen(scan) == pytest.approx(2.0, abs=TOLERANZ)


def test_gerade_seite_lohnt_nicht(tmp_path):
    scan = h.scan_schief(tmp_path / "s.pdf", 0)
    w = _messen(scan)
    assert w is not None and abs(w) < gerade.MIN_WINKEL and not gerade.lohnt(w)


def test_ohne_zeilenmuster_kein_winkel():
    import numpy as np

    assert gerade.schraeglage(np.full((800, 600), 255, dtype=np.uint8)) is None        # leer
    rng = np.random.default_rng(3)
    foto = rng.integers(0, 256, (800, 600)).astype(np.uint8)
    assert gerade.schraeglage(foto) is None                                             # Rauschen, Foto
    assert gerade.schraeglage(np.zeros((800, 600), dtype=np.uint8)) is None             # schwarz
    wenig = np.full((800, 600), 255, dtype=np.uint8)
    wenig[400:404, 100:120] = 0                                                         # ein Strich
    assert gerade.schraeglage(wenig) is None


def test_lohnt():
    assert not gerade.lohnt(None) and not gerade.lohnt(0.2) and not gerade.lohnt(-0.29)
    assert gerade.lohnt(0.3) and gerade.lohnt(-4.5) and not gerade.lohnt(10.0)


def test_ist_scan(tmp_path):
    with pymupdf.open(str(h.scan_schief(tmp_path / "s.pdf", 1))) as doc:
        assert gerade.ist_scan(doc[0])
    with pymupdf.open(str(h.pdf_mit_text(tmp_path / "t.pdf", ["Nur Text"]))) as doc:
        assert not gerade.ist_scan(doc[0])


# --------------------------------------------------------------------------- Ausrichten (Dokument)

def _streams(doc, seite) -> dict:
    xrefs = {x for x in seite.get_contents()} | {b[0] for b in seite.get_images()}
    return {x: doc.xref_stream_raw(x) for x in xrefs}


@pytest.mark.parametrize("drehung", [0, 90, 180, 270])
def test_ausrichten_stellt_die_seite_gerade(tmp_path, drehung):
    """Auch mit Seitendrehung (/Rotate) dreht die Ausrichtung so, wie die Seite angezeigt wird."""
    doc = pymupdf.open(str(h.scan_schief(tmp_path / "s.pdf", 3.0)))
    seite = doc[0]
    seite.set_rotation(drehung)
    vorher = _streams(doc, seite)
    w = gerade.seite_messen(seite)
    gerade.ausrichten(doc, seite, w)
    assert gerade.ist_ausgerichtet(doc, seite) and gerade.ausrichtung(doc, seite) == pytest.approx(w, abs=0.005)
    neu = pymupdf.open("pdf", doc.tobytes())
    rest = gerade.seite_messen(neu[0])
    assert rest is not None and abs(rest) < gerade.MIN_WINKEL
    # Scanbild und bisheriger Inhalt bytegleich, nur zwei kleine Streams dazu
    assert all(neu.xref_stream_raw(x) == daten for x, daten in vorher.items())
    assert len(neu[0].get_contents()) == len(seite.get_contents())
    assert len(gerade.eigene_streams(neu, neu[0])) == 2


def test_ausrichten_dreht_um_die_seitenmitte(tmp_path):
    """Der Schwerpunkt der Schrift bleibt, wo er war (nur gedreht, nicht verschoben)."""
    import numpy as np

    def schwerpunkt(seite):
        pix = seite.get_pixmap(dpi=50, colorspace=pymupdf.csGRAY)
        a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
        ys, xs = np.nonzero(a < 128)
        return xs.mean() / pix.width, ys.mean() / pix.height

    doc = pymupdf.open(str(h.scan_schief(tmp_path / "s.pdf", 4.0)))
    vorher = schwerpunkt(doc[0])
    gerade.ausrichten(doc, doc[0], 4.0)
    nachher = schwerpunkt(doc[0])
    assert nachher == pytest.approx(vorher, abs=0.03)


def test_textebene_dreht_mit(tmp_path):
    """Eine unsichtbare Textebene (Scanprogramm) dreht mit dem Bild: Zeilen laufen danach schraeg."""
    doc = pymupdf.open(str(h.scan_schief(tmp_path / "s.pdf", 0, textebene=True)))
    gerade.ausrichten(doc, doc[0], 5.0)
    zeilen = [z for b in doc[0].get_text("dict")["blocks"] for z in b.get("lines", [])]
    assert zeilen and "Stadtwerke" in doc[0].get_text()
    cos, sin = zeilen[0]["dir"]
    # gegen den Uhrzeigersinn gedreht: im Seitenkoordinatensystem (y nach unten) zeigt die Zeile nach oben
    assert sin == pytest.approx(-math.sin(math.radians(5.0)), abs=0.01) and cos > 0.99


def test_ausrichtung_entfernen(tmp_path):
    doc = pymupdf.open(str(h.scan_schief(tmp_path / "s.pdf", 2.0)))
    vorher = list(doc[0].get_contents())
    assert not gerade.ausrichtung_entfernen(doc, doc[0])
    gerade.ausrichten(doc, doc[0], 2.0)
    assert gerade.ausrichtung_entfernen(doc, doc[0])
    assert list(doc[0].get_contents()) == vorher and gerade.ausrichtung(doc, doc[0]) == 0
    # Kam danach etwas dazu (z. B. eine Textebene), bleibt die Ausrichtung
    gerade.ausrichten(doc, doc[0], 2.0)
    doc[0].insert_text((50, 50), "Nachtrag")
    assert not gerade.ausrichtung_entfernen(doc, doc[0]) and gerade.ausrichtung(doc, doc[0]) == 2.0


def test_bild_hash_bleibt_beim_ausrichten(tmp_path):
    """Das Ausrichten aendert das Bild nicht: gleicher Hash (Vormerkung, OCR-Cache), auch ohne Bild-XObject."""
    doc = pymupdf.open(str(h.scan_schief(tmp_path / "s.pdf", 2.0)))
    vorher = extract._bild_hash(doc, doc[0])
    gerade.ausrichten(doc, doc[0], 2.0)
    assert extract._bild_hash(doc, doc[0]) == vorher
    # Seite ohne Bild-XObject: der Hash kommt aus den Inhalts-Streams (Inline-Bilder), ohne die eigenen
    vektor = pymupdf.open()
    s = vektor.new_page()
    s.draw_rect(pymupdf.Rect(50, 50, 300, 300), fill=(0, 0, 0))
    s.insert_text((60, 400), "Inline", overlay=True)
    vorher = extract._bild_hash(vektor, s)
    assert vorher == extract._bild_hash(vektor, s)
    gerade.ausrichten(vektor, s, 1.5)
    assert extract._bild_hash(vektor, s) == vorher


def test_pdf_text_misst_nur_mit_gerade(tmp_path):
    scan = h.scan_schief(tmp_path / "s.pdf", 2.0, textebene=True)
    ohne = extract.pdf_text(str(scan), 25)
    assert ohne["schraeglagen"] == {} and ohne["bild_hashes"] == {}
    mit = extract.pdf_text(str(scan), 25, gerade=True)
    assert mit["schraeglagen"][1] == pytest.approx(2.0, abs=TOLERANZ)
    assert mit["bild_hashes"][1] and mit["seiten"][0][1] == "text"     # Textseite, trotzdem gemessen


# --------------------------------------------------------------------------- Rechtsklick (Datei)

def test_gerade_ausrichten_datei(tmp_path):
    scan = h.scan_schief(tmp_path / "s.pdf", -2.5, seiten=2)
    original = scan.read_bytes()
    winkel = gerade_ausrichten(scan)
    assert set(winkel) == {1, 2} and winkel[1] == pytest.approx(-2.5, abs=TOLERANZ)
    neu = scan.read_bytes()
    assert neu.startswith(original) and len(neu) > len(original)   # inkrementell: Original bleibt vorn
    assert abs(_messen(scan, 1)) < gerade.MIN_WINKEL and abs(_messen(scan, 2)) < gerade.MIN_WINKEL
    assert not list(tmp_path.glob("~$*"))                          # keine temporaeren Reste
    # Ein zweites Mal: nichts mehr schief, Datei unberuehrt
    assert gerade_ausrichten(scan) == {} and scan.read_bytes() == neu


def test_gerade_ausrichten_nur_bestimmte_seiten(tmp_path):
    scan = h.scan_schief(tmp_path / "s.pdf", 3.0, seiten=2)
    assert set(gerade_ausrichten(scan, seiten=[2])) == {2}
    assert h.ausrichtung_der_datei(scan, 1) == 0 and h.ausrichtung_der_datei(scan, 2) != 0
    with pytest.raises(ValueError):
        gerade_ausrichten(scan, seiten=[3])


def test_gerade_pdf_bleibt_unberuehrt(tmp_path):
    scan = h.scan_schief(tmp_path / "s.pdf", 0)
    text = h.pdf_mit_text(tmp_path / "t.pdf", ["Nur Text"])
    vorher = scan.read_bytes(), text.read_bytes()
    assert gerade_ausrichten(scan) == {} and gerade_ausrichten(text) == {}
    assert (scan.read_bytes(), text.read_bytes()) == vorher


def test_zuruecknehmen(tmp_path):
    scan = h.scan_schief(tmp_path / "s.pdf", 2.0, seiten=2)
    winkel = gerade_ausrichten(scan)
    assert ausrichtung_zuruecknehmen(scan, winkel) == [1, 2]
    assert h.ausrichtung_der_datei(scan, 1) == 0 and _messen(scan) == pytest.approx(2.0, abs=TOLERANZ)
    # nichts mehr zurueckzunehmen: Datei bleibt
    vorher = scan.read_bytes()
    assert ausrichtung_zuruecknehmen(scan, [1, 2]) == [] and scan.read_bytes() == vorher


def test_signierte_und_verschluesselte_pdf_werden_nicht_ausgerichtet(tmp_path):
    import pikepdf

    signiert = h.scan_schief(tmp_path / "sig.pdf", 2.0)
    with pikepdf.open(str(signiert), allow_overwriting_input=True) as pdf:
        pdf.Root.AcroForm = pdf.make_indirect(pikepdf.Dictionary(Fields=pikepdf.Array(), SigFlags=3))
        pdf.save(str(signiert))
    vorher = signiert.read_bytes()
    with pytest.raises(DrehenNichtMoeglich, match="signiert"):
        gerade_ausrichten(signiert)
    assert signiert.read_bytes() == vorher

    verschl = tmp_path / "geheim.pdf"
    with pikepdf.open(str(h.scan_schief(tmp_path / "v.pdf", 2.0))) as pdf:
        pdf.save(str(verschl), encryption=pikepdf.Encryption(owner="o", user="", R=4))
    with pytest.raises(DrehenNichtMoeglich, match="verschlüsselt"):
        gerade_ausrichten(verschl)

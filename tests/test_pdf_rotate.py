"""Issue #150: PDF verlustfrei drehen (src/core/pdf_rotate.py, Qt-frei)."""
from __future__ import annotations

import pikepdf
import pymupdf
import pytest

from src.core import pdf_rotate
from src.core.pdf_rotate import DrehenNichtMoeglich, drehung, gegenrichtung, rotate_pdf, tmp_pfad
from tests import helfer_suche as h


def _bild_streams(pfad) -> list[bytes]:
    erg = []
    with pikepdf.open(str(pfad)) as pdf:
        for page in pdf.pages:
            xobjekte = page.obj.get("/Resources", pikepdf.Dictionary()).get("/XObject", pikepdf.Dictionary())
            for _name, obj in xobjekte.items():
                if obj.get("/Subtype") == "/Image":
                    erg.append(bytes(obj.read_raw_bytes()))
    assert erg  # die Scan-Seiten haben Bilder
    return erg


def _xmp_und_info(pfad) -> tuple[str, dict]:
    with pikepdf.open(str(pfad)) as pdf:
        xmp = str(pdf.Root.Metadata.read_bytes(), "utf-8") if "/Metadata" in pdf.Root else ""
        info = {str(k): str(v) for k, v in pdf.docinfo.items()}
    return xmp, info


@pytest.fixture
def scan(tmp_path):
    pfad = h.pdf_mit_bild(tmp_path / "scan.pdf", seiten=2, text_seiten=["Deckblatt"])
    # Metadaten wie PDFSM sie schreibt: Info-Dict und XMP
    with pikepdf.open(str(pfad), allow_overwriting_input=True) as pdf:
        pdf.docinfo["/Korrespondent"] = "Stadtwerke Musterstadt"
        pdf.docinfo["/Steuerjahr"] = "2024"
        with pdf.open_metadata() as meta:
            meta["dc:title"] = "Rechnung Strom"
        pdf.save(str(pfad))
    return pfad


def test_drehen_setzt_rotate_je_seite(scan):
    assert drehung(scan) == [0, 0, 0]
    rotate_pdf(scan, 90)
    assert drehung(scan) == [90, 90, 90]
    rotate_pdf(scan, 180)
    assert drehung(scan) == [270, 270, 270]
    rotate_pdf(scan, -90)
    assert drehung(scan) == [180, 180, 180]


def test_viermal_90_grad_ist_der_ausgangszustand(scan):
    for _ in range(4):
        rotate_pdf(scan, 90)
    assert drehung(scan) == [0, 0, 0]


def test_gegenrichtung_hebt_auf(scan):
    for grad in (90, -90, 180, 270):
        rotate_pdf(scan, grad)
        rotate_pdf(scan, gegenrichtung(grad))
        assert drehung(scan) == [0, 0, 0]


def test_nur_bestimmte_seiten(scan):
    rotate_pdf(scan, 90, seiten=[2])
    assert drehung(scan) == [0, 90, 0]
    with pytest.raises(ValueError):
        rotate_pdf(scan, 90, seiten=[7])


def test_bilddaten_und_metadaten_bleiben(scan):
    bilder = _bild_streams(scan)
    xmp, info = _xmp_und_info(scan)
    rotate_pdf(scan, 90)
    assert _bild_streams(scan) == bilder
    xmp2, info2 = _xmp_und_info(scan)
    assert info2["/Korrespondent"] == "Stadtwerke Musterstadt" and info2["/Steuerjahr"] == "2024"
    assert "Rechnung Strom" in xmp2
    assert info2 == info


def test_textebene_bleibt_lesbar(tmp_path):
    pfad = h.pdf_mit_text(tmp_path / "text.pdf", ["Rechnung Nummer 4711"])
    rotate_pdf(pfad, 180)
    with pymupdf.open(str(pfad)) as doc:
        assert "Rechnung Nummer 4711" in doc[0].get_text()
        assert doc[0].rotation == 180


def test_temp_datei_ist_weg(scan):
    rotate_pdf(scan, 90)
    assert not tmp_pfad(scan).exists()
    assert sorted(p.name for p in scan.parent.iterdir()) == ["scan.pdf"]


def test_temp_datei_weg_auch_bei_fehler(scan, monkeypatch):
    def kaputt(ziel, ersatz):
        raise OSError(5, "kaputt")

    monkeypatch.setattr("src.search.plattform.datei_ersetzen", kaputt)
    with pytest.raises(OSError):
        rotate_pdf(scan, 90)
    assert not tmp_pfad(scan).exists()
    assert drehung(scan) == [0, 0, 0]  # Original unveraendert


def test_wiederholt_bei_kurzer_sperre(scan, monkeypatch):
    from src.search import plattform
    echt = plattform.datei_ersetzen
    versuche = []

    def gesperrt_dann_frei(ziel, ersatz):
        versuche.append(1)
        if len(versuche) < 3:
            raise PermissionError(13, "gesperrt")
        echt(ziel, ersatz)

    monkeypatch.setattr(pdf_rotate, "RETRY_DELAYS", (0, 0, 0, 0, 0))
    monkeypatch.setattr("src.search.plattform.datei_ersetzen", gesperrt_dann_frei)
    rotate_pdf(scan, 90)
    assert len(versuche) == 3
    assert drehung(scan) == [90, 90, 90]


def test_dauerhaft_gesperrt_meldet_permissionerror(scan, monkeypatch):
    def gesperrt(ziel, ersatz):
        raise PermissionError(13, "gesperrt")

    monkeypatch.setattr(pdf_rotate, "RETRY_DELAYS", (0, 0))
    monkeypatch.setattr("src.search.plattform.datei_ersetzen", gesperrt)
    with pytest.raises(PermissionError):
        rotate_pdf(scan, 90)
    assert not tmp_pfad(scan).exists()


def test_geerbte_drehung(tmp_path):
    pfad = h.pdf_mit_text(tmp_path / "geerbt.pdf", ["A", "B"])
    with pikepdf.open(str(pfad), allow_overwriting_input=True) as pdf:
        pdf.Root.Pages.Rotate = 90
        for page in pdf.pages:
            if "/Rotate" in page.obj:
                del page.obj["/Rotate"]
        pdf.save(str(pfad))
    assert drehung(pfad) == [90, 90]
    rotate_pdf(pfad, 90)
    assert drehung(pfad) == [180, 180]


def test_unzulaessiger_winkel(scan):
    with pytest.raises(ValueError):
        rotate_pdf(scan, 45)


def test_verschluesselt_wird_nicht_gedreht(tmp_path):
    pfad = h.pdf_verschluesselt(tmp_path / "geheim.pdf")
    vorher = pfad.read_bytes()
    with pytest.raises(DrehenNichtMoeglich):
        rotate_pdf(pfad, 90)
    assert pfad.read_bytes() == vorher


def test_signiert_wird_nicht_gedreht(tmp_path):
    pfad = h.pdf_mit_text(tmp_path / "signiert.pdf", ["Bescheid"])
    with pikepdf.open(str(pfad), allow_overwriting_input=True) as pdf:
        pdf.Root.AcroForm = pdf.make_indirect(pikepdf.Dictionary(Fields=pikepdf.Array(), SigFlags=3))
        pdf.save(str(pfad))
    vorher = pfad.read_bytes()
    with pytest.raises(DrehenNichtMoeglich):
        rotate_pdf(pfad, 90)
    assert pfad.read_bytes() == vorher


def test_fehlende_datei(tmp_path):
    with pytest.raises(FileNotFoundError):
        rotate_pdf(tmp_path / "gibtsnicht.pdf", 90)

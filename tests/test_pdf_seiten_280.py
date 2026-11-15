"""Issue #280: einzelne Seiten einer PDF loeschen, umsortieren, drehen; leere Seiten finden."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pikepdf
import pymupdf
import pytest

from src.core import pdf_seiten
from src.core.pdf_rotate import DrehenNichtMoeglich


def _pdf(pfad: Path, seiten: int, marke: str = "Blatt") -> Path:
    doc = pymupdf.open()
    try:
        for i in range(seiten):
            doc.new_page().insert_text((72, 100), f"{marke} {i + 1}", fontsize=30)
        doc.save(str(pfad))
    finally:
        doc.close()
    return pfad


def _stand(pfad: Path) -> list[tuple[str, int]]:
    with pymupdf.open(str(pfad)) as doc:
        return [(seite.get_text().strip(), seite.rotation) for seite in doc]


def _scan(pfad: Path, bilder: list[np.ndarray]) -> Path:
    """PDF aus Graustufenbildern (je Seite ein Scan, A4)."""
    doc = pymupdf.open()
    try:
        for bild in bilder:
            hoehe, breite = bild.shape
            pix = pymupdf.Pixmap(pymupdf.csGRAY, breite, hoehe, bild.astype(np.uint8).tobytes(), False)
            doc.new_page(width=595, height=842).insert_image(pymupdf.Rect(0, 0, 595, 842), pixmap=pix)
        doc.save(str(pfad))
    finally:
        doc.close()
    return pfad


def _papier(seed: int = 1) -> np.ndarray:
    """Leeres Blatt wie gescannt: fast weiss, leichtes Rauschen."""
    rng = np.random.default_rng(seed)
    return np.clip(rng.normal(243, 4, size=(1170, 827)), 0, 255)


def test_loeschen_umsortieren_drehen_in_einem_schritt(tmp_path):
    pfad = _pdf(tmp_path / "Mäppchen Größe.pdf", 5)  # Umlaute im Namen
    sicherung = tmp_path / "Sicherung" / "x" / pfad.name
    vorher = pfad.read_bytes()

    pdf_seiten.seiten_schreiben(pfad, [(5, 90), (1, 0), (3, 270)], sicherung)

    assert _stand(pfad) == [("Blatt 5", 90), ("Blatt 1", 0), ("Blatt 3", 270)]
    assert sicherung.read_bytes() == vorher
    assert not list(tmp_path.glob("~$*"))  # keine temporaere Datei bleibt liegen


def test_drehung_kommt_zur_vorhandenen_dazu(tmp_path):
    pfad = _pdf(tmp_path / "a.pdf", 2)
    with pikepdf.open(str(pfad), allow_overwriting_input=True) as pdf:
        pdf.pages[0].rotate(90, relative=True)
        pdf.save(str(pfad))

    pdf_seiten.seiten_schreiben(pfad, [(1, 270), (2, 180)], tmp_path / "s" / "a.pdf")

    assert _stand(pfad) == [("Blatt 1", 0), ("Blatt 2", 180)]


def test_inhalt_geloeschter_seiten_steht_nicht_mehr_in_der_datei(tmp_path):
    pfad = tmp_path / "a.pdf"
    doc = pymupdf.open()
    for text in ("Deckblatt", "GEHEIMZAHL-4711", "Schluss"):
        doc.new_page().insert_text((72, 100), text, fontsize=20)
    doc.set_toc([[1, "Anfang", 1], [1, "Mitte", 2], [1, "Ende", 3]])
    doc.save(str(pfad))
    doc.close()

    def texte_in_der_datei() -> bytes:
        """Alle Datenstroeme der Datei, auch solche, die keine Seite mehr benutzt."""
        with pikepdf.open(str(pfad)) as pdf:
            return b"".join(obj.read_bytes() for obj in pdf.objects if isinstance(obj, pikepdf.Stream))

    geheim = b"GEHEIMZAHL-4711".hex().encode()  # so steht der Text im Datenstrom der Seite
    assert geheim in texte_in_der_datei()

    pdf_seiten.seiten_schreiben(pfad, [(1, 0), (3, 0)], tmp_path / "s" / "a.pdf")

    with pymupdf.open(str(pfad)) as doc:
        assert doc.page_count == 2
        assert "GEHEIMZAHL" not in "".join(seite.get_text() for seite in doc)
        assert [(titel, seite) for _, titel, seite in doc.get_toc()] == [("Anfang", 1), ("Ende", 2)]
    roh = texte_in_der_datei()
    assert geheim not in roh
    assert b"Deckblatt".hex().encode() in roh


def test_link_auf_geloeschte_seite_haelt_ihren_inhalt_nicht_in_der_datei(tmp_path):
    pfad = tmp_path / "a.pdf"
    doc = pymupdf.open()
    for text in ("Deckblatt", "GEHEIMZAHL-4711"):
        doc.new_page().insert_text((72, 100), text, fontsize=20)
    doc[0].insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(72, 200, 200, 220), "page": 1,
                        "to": pymupdf.Point(0, 0)})
    doc.save(str(pfad))
    doc.close()

    pdf_seiten.seiten_schreiben(pfad, [(1, 0)], tmp_path / "s" / "a.pdf")

    with pikepdf.open(str(pfad)) as pdf:
        assert len(pdf.pages) == 1
        roh = b"".join(obj.read_bytes() for obj in pdf.objects if isinstance(obj, pikepdf.Stream))
    assert b"GEHEIMZAHL-4711".hex().encode() not in roh
    assert b"Deckblatt".hex().encode() in roh


def test_metadaten_bleiben_erhalten(tmp_path):
    pfad = _pdf(tmp_path / "a.pdf", 3)
    with pikepdf.open(str(pfad), allow_overwriting_input=True) as pdf:
        with pdf.open_metadata() as meta:
            meta["dc:title"] = "Rechnung Mustermann"
        pdf.docinfo["/Author"] = "Max Mustermann"
        pdf.save(str(pfad))

    pdf_seiten.seiten_schreiben(pfad, [(3, 0), (1, 0)], tmp_path / "s" / "a.pdf")

    with pikepdf.open(str(pfad)) as pdf:
        assert str(pdf.docinfo["/Author"]) == "Max Mustermann"
        with pdf.open_metadata() as meta:
            assert meta["dc:title"] == "Rechnung Mustermann"


def test_wiederherstellen_bringt_den_alten_stand_zurueck(tmp_path):
    pfad = _pdf(tmp_path / "a.pdf", 4)
    sicherung = tmp_path / "s" / "a.pdf"
    vorher = pfad.read_bytes()
    pdf_seiten.seiten_schreiben(pfad, [(2, 0)], sicherung)
    assert len(_stand(pfad)) == 1

    pdf_seiten.wiederherstellen(pfad, sicherung)

    assert pfad.read_bytes() == vorher
    assert sicherung.exists()


def test_wiederherstellen_ohne_sicherung_meldet_es(tmp_path):
    pfad = _pdf(tmp_path / "a.pdf", 2)
    with pytest.raises(FileNotFoundError):
        pdf_seiten.wiederherstellen(pfad, tmp_path / "fehlt.pdf")


@pytest.mark.parametrize("plan", [[], [(1, 0), (1, 0)], [(4, 0)], [(0, 0)], [(1, 45)]])
def test_unzulaessiger_plan_laesst_die_datei_unberuehrt(tmp_path, plan):
    pfad = _pdf(tmp_path / "a.pdf", 3)
    vorher = pfad.read_bytes()
    sicherung = tmp_path / "s" / "a.pdf"

    with pytest.raises(ValueError):
        pdf_seiten.seiten_schreiben(pfad, plan, sicherung)

    assert pfad.read_bytes() == vorher
    assert not sicherung.exists()
    assert not list(tmp_path.glob("~$*"))


def test_signierte_pdf_bleibt_unberuehrt(tmp_path):
    pfad = _pdf(tmp_path / "a.pdf", 2)
    with pikepdf.open(str(pfad), allow_overwriting_input=True) as pdf:
        pdf.Root.AcroForm = pdf.make_indirect(pikepdf.Dictionary(Fields=pikepdf.Array(), SigFlags=3))
        pdf.save(str(pfad))
    vorher = pfad.read_bytes()

    with pytest.raises(DrehenNichtMoeglich):
        pdf_seiten.seitenzahl(pfad)
    with pytest.raises(DrehenNichtMoeglich):
        pdf_seiten.seiten_schreiben(pfad, [(2, 0)], tmp_path / "s" / "a.pdf")
    assert pfad.read_bytes() == vorher


def test_verschluesselte_pdf_bleibt_unberuehrt(tmp_path):
    pfad = _pdf(tmp_path / "a.pdf", 2)
    with pikepdf.open(str(pfad), allow_overwriting_input=True) as pdf:
        pdf.save(str(pfad), encryption=pikepdf.Encryption(owner="besitzer", user=""))
    vorher = pfad.read_bytes()

    with pytest.raises(DrehenNichtMoeglich):
        pdf_seiten.seiten_schreiben(pfad, [(2, 0)], tmp_path / "s" / "a.pdf")
    assert pfad.read_bytes() == vorher


def test_fehlende_datei(tmp_path):
    with pytest.raises(FileNotFoundError):
        pdf_seiten.seiten_schreiben(tmp_path / "fehlt.pdf", [(1, 0)], tmp_path / "s" / "a.pdf")


def test_unveraendert():
    assert pdf_seiten.unveraendert([(1, 0), (2, 360)], 2)
    assert not pdf_seiten.unveraendert([(1, 0)], 2)
    assert not pdf_seiten.unveraendert([(2, 0), (1, 0)], 2)
    assert not pdf_seiten.unveraendert([(1, 0), (2, 90)], 2)


def test_leere_seiten_bei_textpdf(tmp_path):
    pfad = tmp_path / "a.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "Sehr geehrter Herr Mustermann,", fontsize=12)
    doc.new_page()
    seite = doc.new_page()
    for zeile in range(30):
        seite.insert_text((72, 100 + zeile * 20), "Lorem ipsum dolor sit amet, consetetur sadipscing elitr", fontsize=11)
    doc.new_page()
    doc.save(str(pfad))
    doc.close()

    assert pdf_seiten.leere_seiten(pfad) == [2, 4]


def test_leere_seiten_bei_scans(tmp_path):
    """Rauschen, durchscheinende Schrift, Lochung und Randschatten machen eine Rueckseite nicht voll."""
    text = _papier(1)
    for zeile in range(150, 1000, 40):  # Textzeilen: dunkle Striche
        text[zeile:zeile + 6, 120:700:3] = 40
    durchschein = _papier(2)
    for zeile in range(150, 1000, 40):  # Vorderseite scheint hellgrau durch
        durchschein[zeile:zeile + 6, 120:700:3] = 205
    gelocht = _papier(3)
    for mitte in (430, 740):  # Lochung links am Rand, schwarz
        gelocht[mitte - 12:mitte + 12, 22:46] = 10
    gelocht[:, :8] = 60  # Schatten der Blattkante
    eine_zeile = _papier(4)
    eine_zeile[300:306, 120:500:3] = 40  # eine einzige Zeile Text

    pfad = _scan(tmp_path / "scan.pdf", [text, _papier(5), durchschein, gelocht, eine_zeile])

    assert pdf_seiten.leere_seiten(pfad) == [2, 3, 4]

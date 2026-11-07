"""PDFAnalyzer holt seinen Text aus dem Suchindex und erkennt nie doppelt (Phase 5).

Aktueller Eintrag -> Text aus dem Index, ohne die PDF zu lesen; unbekannte
Datei unter einer Wurzel -> lesen und aufnehmen; ausserhalb -> nur lesen;
Bildseiten -> OCR mit der gemeinsamen Funktion, Ergebnis geht in Index und
Cache, ein zweiter Analyzer und der naechste Lauf rufen Tesseract nicht mehr.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

from src.core.pdf_analyzer import PDFAnalyzer
from src.search import extract
from src.search.indexer import Indexer
from src.search.suchindex import Suchindex
from tests import helfer_suche as h


@pytest.fixture
def umgebung(tmp_path, monkeypatch):
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], ocr_aktiv=True, ocr_tesseract="tesseract-fake")
    idx = Suchindex(konfig)
    monkeypatch.setattr("src.core.pdf_analyzer.suchindex_fuer_analyse", lambda: idx)
    monkeypatch.setattr("src.core.pdf_analyzer._search_konfig", lambda: konfig)
    return ablage, konfig, idx


def test_text_aus_dem_index_ohne_die_pdf_zu_lesen(umgebung, monkeypatch):
    ablage, konfig, idx = umgebung
    pdf = h.pdf_mit_text(ablage / "a.pdf", ["Rechnung Nummer eins", "Seite zwei"])
    assert Indexer(konfig, synchron=True).lauf() == 0

    def verboten(*a, **k):
        raise AssertionError("Die PDF darf nicht gelesen werden, der Index ist aktuell")

    monkeypatch.setattr(extract, "pdf_text", verboten)
    with PDFAnalyzer(pdf) as a:
        text = a.extract_text()
    assert "Rechnung Nummer eins" in text and "Seite zwei" in text and not a.ocr_used


def test_unbekannte_datei_wird_gelesen_und_unter_der_wurzel_aufgenommen(umgebung, tmp_path):
    ablage, konfig, idx = umgebung
    pdf = h.pdf_mit_text(ablage / "neu.pdf", ["Vertrag Text"])
    with PDFAnalyzer(pdf) as a:
        assert "Vertrag Text" in a.extract_text(use_ocr=False)
    d = idx.dokument_nach_pfad(str(pdf))
    assert d is not None and d["textstatus"] == "text"
    assert idx.text_fuer_datei(str(pdf))["aktuell"]

    fremd = h.pdf_mit_text(tmp_path / "fremd.pdf", ["Fremder Text"])
    with PDFAnalyzer(fremd) as a:
        assert "Fremder Text" in a.extract_text(use_ocr=False)
    assert idx.dokument_nach_pfad(str(fremd)) is None


def test_ohne_eingerichtete_suche_wie_bisher(tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.pdf_analyzer.suchindex_fuer_analyse", lambda: None)
    pdf = h.pdf_mit_text(tmp_path / "a.pdf", ["Nur lesen"])
    with PDFAnalyzer(pdf) as a:
        assert "Nur lesen" in a.extract_text(use_ocr=False)


def test_keine_doppelte_ocr(umgebung, monkeypatch):
    ablage, konfig, idx = umgebung
    scan = h.pdf_mit_bild(ablage / "scan.pdf", seiten=1, text_seiten=["Deckblatt"])
    aufrufe = []

    def fake_run(args, **kw):
        aufrufe.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=b"Erkannter Scantext", stderr=b"")

    monkeypatch.setattr(extract.subprocess, "run", fake_run)

    with PDFAnalyzer(scan) as a:
        text = a.extract_text()
    assert "Deckblatt" in text and "Erkannter Scantext" in text and a.ocr_used
    assert len(aufrufe) == 1 and "deu+eng" in aufrufe[0]
    d = idx.dokument_nach_pfad(str(scan))
    assert d["textstatus"] == "ocr" and d["ocr_seiten"] == 1

    # Zweiter Analyzer: alles aus dem Index
    with PDFAnalyzer(scan) as a:
        assert "Erkannter Scantext" in a.extract_text() and not a.ocr_used
    assert len(aufrufe) == 1

    # Indexlauf: nichts mehr zu erkennen
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert len(aufrufe) == 1

    # Kopie ohne Meldung (z. B. aus dem Explorer): OCR-Text aus dem Cache nach Bildinhalt
    shutil.copy2(scan, ablage / "kopie.pdf")
    with PDFAnalyzer(ablage / "kopie.pdf") as a:
        assert "Erkannter Scantext" in a.extract_text() and not a.ocr_used
    assert len(aufrufe) == 1
    assert idx.dokument_nach_pfad(str(ablage / "kopie.pdf"))["textstatus"] == "ocr"


def test_ocr_hoechstens_fuenf_seiten_interaktiv(umgebung, monkeypatch):
    ablage, konfig, idx = umgebung
    scan = h.pdf_mit_bild(ablage / "lang.pdf", seiten=7)
    aufrufe = []
    monkeypatch.setattr(extract.subprocess, "run", lambda args, **kw: aufrufe.append(args) or
                        subprocess.CompletedProcess(args, 0, stdout=b"Text", stderr=b""))
    with PDFAnalyzer(scan) as a:
        a.extract_text()
    assert len(aufrufe) == PDFAnalyzer.OCR_MAX_SEITEN
    d = idx.dokument_nach_pfad(str(scan))
    # Die restlichen Seiten (gleiches Bild) hat der Cache gefuellt, der Lauf haette sonst 2 Seiten offen
    assert d["ocr_seiten"] == 7 and d["textstatus"] == "ocr"


# --- Issue #150: Drehen und "OCR neu durchführen" ------------------------------


def test_nach_drehen_neue_ocr_statt_altem_cache_text(umgebung, monkeypatch):
    from src.core.pdf_rotate import rotate_pdf

    ablage, konfig, idx = umgebung
    scan = h.pdf_mit_bild(ablage / "kopfueber.pdf", seiten=1)
    antwort = {"text": b"Kopfueber Kauderwelsch"}
    aufrufe = []

    def fake_run(args, **kw):
        aufrufe.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=antwort["text"], stderr=b"")

    monkeypatch.setattr(extract.subprocess, "run", fake_run)
    with PDFAnalyzer(scan) as a:
        assert "Kauderwelsch" in a.extract_text()
    assert len(aufrufe) == 1

    rotate_pdf(scan, 180)
    antwort["text"] = b"Rechnung richtig herum"
    with PDFAnalyzer(scan) as a:
        text = a.extract_text()
    assert "Rechnung richtig herum" in text and "Kauderwelsch" not in text and a.ocr_used
    assert len(aufrufe) == 2

    # Zurueckgedreht: der alte Cache-Eintrag passt wieder, keine dritte OCR
    rotate_pdf(scan, 180)
    with PDFAnalyzer(scan) as a:
        assert "Kauderwelsch" in a.extract_text() and not a.ocr_used
    assert len(aufrufe) == 2


def test_ocr_neu_ersetzt_text_und_cache(umgebung, monkeypatch):
    from src.core.pdf_analyzer import ocr_neu_durchfuehren

    ablage, konfig, idx = umgebung
    scan = h.pdf_mit_bild(ablage / "scan.pdf", seiten=2, text_seiten=["Deckblatt"])
    antwort = {"text": b"Alter Text"}
    aufrufe = []
    monkeypatch.setattr(extract.subprocess, "run", lambda args, **kw: aufrufe.append(args) or
                        subprocess.CompletedProcess(args, 0, stdout=antwort["text"], stderr=b""))
    with PDFAnalyzer(scan) as a:
        assert "Alter Text" in a.extract_text()
    vorher = len(aufrufe)

    antwort["text"] = b"Neu erkannt"
    erg = ocr_neu_durchfuehren(scan)
    assert erg == {"index": True, "seiten": 2, "fehler": None}
    assert len(aufrufe) == vorher + 2  # beide Bildseiten, am Cache vorbei

    with PDFAnalyzer(scan) as a:
        text = a.extract_text()
    assert "Neu erkannt" in text and "Alter Text" not in text and not a.ocr_used
    # Auch der Cache ist ersetzt: eine Kopie bekommt den neuen Text
    shutil.copy2(scan, ablage / "kopie.pdf")
    with PDFAnalyzer(ablage / "kopie.pdf") as a:
        assert "Neu erkannt" in a.extract_text() and not a.ocr_used


def test_ocr_neu_nimmt_datei_ausserhalb_der_wurzeln_auf(umgebung, tmp_path, monkeypatch):
    from src.core.pdf_analyzer import ocr_neu_durchfuehren

    ablage, konfig, idx = umgebung
    fremd = h.pdf_mit_bild(tmp_path / "fremd.pdf", seiten=1)
    monkeypatch.setattr(extract.subprocess, "run", lambda args, **kw:
                        subprocess.CompletedProcess(args, 0, stdout=b"Fremd erkannt", stderr=b""))
    erg = ocr_neu_durchfuehren(fremd)
    assert erg["index"] and erg["seiten"] == 1
    assert idx.dokument_nach_pfad(str(fremd))["textstatus"] == "ocr"


def test_ocr_neu_abbrechen_vor_der_naechsten_seite(umgebung, monkeypatch):
    from src.core.pdf_analyzer import ocr_neu_durchfuehren

    ablage, konfig, idx = umgebung
    scan = h.pdf_mit_bild(ablage / "lang.pdf", seiten=3)
    aufrufe = []
    monkeypatch.setattr(extract.subprocess, "run", lambda args, **kw: aufrufe.append(args) or
                        subprocess.CompletedProcess(args, 0, stdout=b"Text", stderr=b""))
    erg = ocr_neu_durchfuehren(scan, abbrechen=lambda: len(aufrufe) >= 1)
    assert len(aufrufe) == 1 and erg["seiten"] == 1


def test_ocr_neu_ohne_suche_tut_nichts(tmp_path, monkeypatch):
    from src.core.pdf_analyzer import ocr_neu_durchfuehren

    monkeypatch.setattr("src.core.pdf_analyzer.suchindex_fuer_analyse", lambda: None)

    def verboten(*a, **k):
        raise AssertionError("ohne Suchindex keine OCR hier - die naechste Analyse erkennt neu")

    monkeypatch.setattr(extract.subprocess, "run", verboten)
    scan = h.pdf_mit_bild(tmp_path / "scan.pdf", seiten=1)
    assert ocr_neu_durchfuehren(scan) == {"index": False, "seiten": 0, "fehler": None}

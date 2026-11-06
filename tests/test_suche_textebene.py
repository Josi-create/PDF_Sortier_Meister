"""Unsichtbare OCR-Textebene in gescannten PDFs (Phase 5b, ``src/search/textebene.py``).

Alle Dateien entstehen synthetisch in ``tmp_path``; Tesseract ist durch
``helfer_suche.fake_tesseract`` ersetzt (der Test mit echtem Tesseract steht in
``test_suche_textebene_tesseract.py``). Geprueft wird: deckungsgleiche
Ueberlagerung bei Drehung und CropBox, sicheres Schreiben (Original bytegleich
vorn, Sicherungskopie, keine Reste), was nie angefasst wird, Abbruch und
Verschieben waehrend des Schreibens, die Stufen, das Zusammenspiel mit dem
Sortieren in PDFSM in beiden Reihenfolgen, Rueckgaengig, Aufbewahrung und Anhalten.
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime, timedelta

import pymupdf
import pytest

from src.search import db, extract, plattform, textebene
from src.search.indexer import Indexer, anhalten_datei
from src.search.suchindex import Suchindex
from tests import helfer_suche as h

TEXT = "Rechnung Nummer 4711 Gesamtbetrag"


@pytest.fixture
def ocr(monkeypatch):
    return h.fake_tesseract(monkeypatch, TEXT)


def _konfig(tmp_path, stufe="neue_scans", **kw):
    ablage = tmp_path / "Ablage"
    for ordner in ("1A", "Archiv", "Steuer"):
        (ablage / ordner).mkdir(parents=True, exist_ok=True)
    kw.setdefault("wurzeln", [str(ablage)])
    kw.setdefault("prioritaet", [str(ablage / "1A")])
    return h.konfig_fuer(tmp_path, ocr_aktiv=True, ocr_tesseract="tesseract-fake", textebene=stufe, **kw), ablage


def _auftrag(pfad, ebene: bytes | None, sicherung, ocr_cfg=None) -> dict:
    st = os.stat(pfad)
    return {"pfad": str(pfad), "groesse": st.st_size, "mtime_ns": st.st_mtime_ns,
            "seiten": {1: {"hash": None, "ebene": ebene}}, "ocr": ocr_cfg, "sicherung_ordner": str(sicherung),
            "min_zeichen": 25}


def _ebene_fuer(pfad) -> bytes:
    with pymupdf.open(pfad) as d:
        r = d[0].rect
    return h.text_pdf(r.width, r.height, TEXT)


def _reste(ordner) -> list[str]:
    return [n for n in os.listdir(ordner) if n.endswith(textebene.TMP_ENDUNG) or n.endswith(".neu")]


def _ocr_schriften(pfad, seite=0) -> int:
    with pymupdf.open(pfad) as d:
        return sum(1 for f in d[seite].get_fonts() if extract.OCR_SCHRIFT in f[3])


def _dok(konfig, pfad):
    con = db.verbinde(konfig.db_datei)
    try:
        r = con.execute("SELECT * FROM dokumente WHERE pfad = ?", (str(pfad),)).fetchone()
        return dict(r) if r else None
    finally:
        con.close()


# --------------------------------------------------------------------------- Geometrie

def _dunkel(pix) -> tuple | None:
    xs, ys = [], []
    s = pix.samples
    for y in range(pix.height):
        for x in range(pix.width):
            if s[y * pix.stride + x] < 100:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


@pytest.mark.parametrize("cropbox", [None, (50, 80, 350, 500)])
@pytest.mark.parametrize("drehung", [0, 90, 180, 270])
def test_ueberlagerung_deckungsgleich_bei_drehung_und_cropbox(drehung, cropbox):
    """Die Text-PDF hat die angezeigte Seitengroesse; ihr Quadrat oben links muss angezeigt oben links liegen."""
    doc = pymupdf.open()
    seite = doc.new_page(width=400, height=600)
    if cropbox:
        seite.set_cropbox(pymupdf.Rect(*cropbox))
    seite.set_rotation(drehung)
    angezeigt = seite.rect
    textebene.ebene_auflegen(seite, h.text_pdf(angezeigt.width, angezeigt.height, "OBENLINKS", sichtbar=True))
    neu = pymupdf.open("pdf", doc.tobytes())
    s = neu[0]
    assert s.rotation == drehung and s.rect == angezeigt
    assert _dunkel(s.get_pixmap(dpi=36, colorspace=pymupdf.csGRAY))[:2] == (5, 5)
    assert s.get_text().strip() == "OBENLINKS"


# --------------------------------------------------------------------------- Sicher schreiben

def test_schreiben_haelt_original_bytegleich_und_sichert(tmp_path):
    scan = h.scan_pdf(tmp_path / "scan.pdf", ["Rechnung Nummer 4711"])
    vorher = scan.read_bytes()
    with pymupdf.open(scan) as d:
        bilder = {x: d.xref_stream_raw(x) for x, *_ in d[0].get_images(full=True)}
        rect, mediabox = d[0].rect, d[0].mediabox
    res = textebene.datei_schreiben(_auftrag(scan, _ebene_fuer(scan), tmp_path / "sicherung"))

    assert res["status"] == "geschrieben" and res["seiten"] == [1]
    nachher = scan.read_bytes()
    assert nachher.startswith(vorher) and len(nachher) > len(vorher)   # inkrementell: Original vorn unveraendert
    with pymupdf.open(scan) as d:
        assert TEXT in d[0].get_text() and d.page_count == 1
        assert d[0].rect == rect and d[0].mediabox == mediabox
        assert {x: d.xref_stream_raw(x) for x in bilder} == bilder
        assert not d.is_repaired
    assert (res["groesse"], res["mtime_ns"]) == (os.stat(scan).st_size, os.stat(scan).st_mtime_ns)
    assert open(res["sicherung"], "rb").read() == vorher
    assert _reste(tmp_path) == []
    # Die Seite liest sich jetzt als Text: keine OCR und keine zweite Textebene mehr
    gelesen = extract.pdf_text(str(scan), 25)
    assert gelesen["status"] == "text" and not gelesen["ohne_text"]
    zweites = textebene.datei_schreiben(_auftrag(scan, _ebene_fuer(scan), tmp_path / "sicherung"))
    assert zweites["status"] == "vorhanden" and scan.read_bytes() == nachher and _ocr_schriften(scan) == 1


def _signiert(pfad):
    with pymupdf.open(pfad) as d:
        d.xref_set_key(d.pdf_catalog(), "AcroForm", "<< /Fields [] /SigFlags 3 >>")
        d.saveIncr()


def _verschluesselt(pfad):
    tmp = str(pfad) + ".x"
    with pymupdf.open(pfad) as d:
        d.save(tmp, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="eigentuemer", user_pw="")
    os.replace(tmp, pfad)


def _pdfa(pfad):
    with pymupdf.open(pfad) as d:
        d.set_xml_metadata('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
                           'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="" '
                           'xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/"><pdfaid:part>2</pdfaid:part>'
                           '</rdf:Description></rdf:RDF></x:xmpmeta>')
        d.saveIncr()


@pytest.mark.parametrize("fall, grund", [
    ("signiert", "signiert"), ("verschluesselt", "verschluesselt"), ("pdfa", "pdfa"),
    ("schreibgeschuetzt", "schreibgeschuetzt"), ("cloud", "nur_cloud"), ("gesperrt", "gesperrt"),
    ("geaendert", "geaendert"),
])
def test_wird_nie_angefasst(tmp_path, monkeypatch, fall, grund):
    scan = h.scan_pdf(tmp_path / "scan.pdf", ["Vertrag"])
    {"signiert": _signiert, "verschluesselt": _verschluesselt, "pdfa": _pdfa}.get(fall, lambda p: None)(scan)
    a = _auftrag(scan, _ebene_fuer(scan), tmp_path / "sicherung")
    if fall == "schreibgeschuetzt":
        os.chmod(scan, 0o444)
    elif fall == "cloud":
        monkeypatch.setattr(plattform, "nur_cloud", lambda st: True)
    elif fall == "gesperrt":
        monkeypatch.setattr(plattform, "gesperrt", lambda pfad: True)
    elif fall == "geaendert":
        a["mtime_ns"] -= 5_000_000_000            # Stand der OCR: aelter als die Datei
    vorher = scan.read_bytes()
    try:
        res = textebene.datei_schreiben(a)
    finally:
        os.chmod(scan, 0o644)
    assert (res["status"], res["grund"]) == ("uebersprungen", grund)
    assert scan.read_bytes() == vorher
    assert not (tmp_path / "sicherung").exists() or not os.listdir(tmp_path / "sicherung")
    assert _reste(tmp_path) == []


@pytest.mark.skipif(sys.platform != "win32", reason="nur Windows sperrt geoeffnete Dateien")
def test_geoeffnete_datei_bleibt_unveraendert(tmp_path):
    scan = h.scan_pdf(tmp_path / "scan.pdf", ["Kontoauszug"])
    vorher = scan.read_bytes()
    with open(scan, "rb"):                       # wie ein Betrachter, der die Datei offen haelt
        res = textebene.datei_schreiben(_auftrag(scan, _ebene_fuer(scan), tmp_path / "sicherung"))
    assert (res["status"], res["grund"]) == ("uebersprungen", "gesperrt")
    assert scan.read_bytes() == vorher and _reste(tmp_path) == [] and not os.listdir(tmp_path / "sicherung")


@pytest.mark.parametrize("stelle", ["pruefen", "ersetzen", "abbruch"])
def test_abbruch_mitten_im_schreiben_laesst_das_original_intakt(tmp_path, monkeypatch, stelle):
    scan = h.scan_pdf(tmp_path / "scan.pdf", ["Mahnung"])
    vorher = scan.read_bytes()
    if stelle == "pruefen":
        def pruefen(*a):
            raise textebene.PruefungFehlgeschlagen("Bild-Stream verändert")
        monkeypatch.setattr(textebene, "pruefen", pruefen)
    elif stelle == "ersetzen":
        def ersetzen(ziel, ersatz):
            raise OSError(5, "Datenträgerfehler")
        monkeypatch.setattr(plattform, "datei_ersetzen", ersetzen)
    else:
        echt = textebene._schreiben_tmp

        def abbrechen(pfad, tmp, ebenen):
            echt(pfad, tmp, ebenen)
            raise KeyboardInterrupt          # Prozess wird mitten im Schreiben beendet
        monkeypatch.setattr(textebene, "_schreiben_tmp", abbrechen)
    a = _auftrag(scan, _ebene_fuer(scan), tmp_path / "sicherung")
    if stelle == "abbruch":
        with pytest.raises(KeyboardInterrupt):
            textebene.datei_schreiben(a)
    else:
        res = textebene.datei_schreiben(a)
        assert res["status"] == "fehler" and res["fehler"]
    assert scan.read_bytes() == vorher
    assert _reste(tmp_path) == []
    assert not (tmp_path / "sicherung").exists() or not os.listdir(tmp_path / "sicherung")


def test_verschoben_waehrend_des_schreibens_keine_zweite_datei(tmp_path, monkeypatch):
    scan = h.scan_pdf(tmp_path / "scan.pdf", ["Bescheid"])
    vorher = scan.read_bytes()
    ziel = tmp_path / "sortiert"
    ziel.mkdir()
    echt = plattform.datei_ersetzen

    def ersetzen(pfad, ersatz):
        shutil.move(pfad, ziel / "Bescheid 2026.pdf")      # PDFSM sortiert genau jetzt
        echt(pfad, ersatz)
    monkeypatch.setattr(plattform, "datei_ersetzen", ersetzen)
    res = textebene.datei_schreiben(_auftrag(scan, _ebene_fuer(scan), tmp_path / "sicherung"))
    assert (res["status"], res["grund"]) == ("uebersprungen", "fehlt")
    assert not scan.exists()                                 # am alten Ort entsteht nichts
    assert (ziel / "Bescheid 2026.pdf").read_bytes() == vorher
    assert _reste(tmp_path) == [] and not os.listdir(tmp_path / "sicherung")


def test_ocr_liefert_textebene_im_selben_aufruf(tmp_path, ocr):
    scan = h.scan_pdf(tmp_path / "scan.pdf", ["Lieferschein"], seiten=2)
    cfg = {"tesseract": "tesseract-fake", "tessdata": None, "sprachen": "deu+eng", "dpi": 300, "textebene": True}
    res = extract.pdf_ocr(str(scan), [1, 2], cfg)
    assert len(ocr) == 2 and all("tessedit_create_pdf=1" in a and "textonly_pdf=1" in a for a in ocr)
    assert res["texte"] == {1: TEXT, 2: TEXT} and set(res["ebenen"]) == {1, 2}
    assert textebene.ebene_hat_text(res["ebenen"][1])
    ohne = extract.pdf_ocr(str(scan), [1], dict(cfg, textebene=False))
    assert ohne["ebenen"] == {} and ocr[-1][2] == "stdout"


# --------------------------------------------------------------------------- Indexlauf und Stufen

def test_neue_scans_im_ersten_vorrang_ordner_genau_einmal(tmp_path, ocr):
    konfig, ablage = _konfig(tmp_path)
    neu = h.scan_pdf(ablage / "1A" / "neu.pdf", ["Neuer Scan"], seiten=2)
    alt = h.scan_pdf(ablage / "Archiv" / "alt.pdf", ["Alter Scan"])
    alt_vorher = alt.read_bytes()
    assert Indexer(konfig, synchron=True).lauf() == 0

    d = _dok(konfig, neu)
    assert d["textebene_am"] and d["textebene_grund"] is None
    st = os.stat(neu)
    assert (d["groesse"], d["mtime_ns"]) == (st.st_size, st.st_mtime_ns)   # sofort nachgezogen
    assert _ocr_schriften(neu, 0) == 1 and _ocr_schriften(neu, 1) == 1
    assert _dok(konfig, alt)["textebene_am"] is None and alt.read_bytes() == alt_vorher
    idx = Suchindex(konfig)
    eintraege = idx.textebene_protokoll()
    assert [(e["pfad"], e["seiten"], e["status"]) for e in eintraege] == [(str(neu), "1,2", "geschrieben")]
    assert os.path.isfile(eintraege[0]["sicherung"])
    assert idx.status()["textebene"]["geschrieben"] == 1
    assert idx.suche("Gesamtbetrag")["gesamt"] == 2

    # Naechster Lauf: unveraendert, nichts doppelt
    bytes_neu, aufrufe = neu.read_bytes(), len(ocr)
    indexer = Indexer(konfig, synchron=True)
    assert indexer.lauf() == 0
    assert indexer.stat["unveraendert"] == 2 and indexer.stat["gelesen"] == 0
    assert neu.read_bytes() == bytes_neu and len(ocr) == aufrufe and len(idx.textebene_protokoll()) == 1


def test_stufe_aus_schreibt_und_speichert_nichts(tmp_path, ocr):
    konfig, ablage = _konfig(tmp_path, stufe="aus")
    neu = h.scan_pdf(ablage / "1A" / "neu.pdf", ["Neuer Scan"])
    vorher = neu.read_bytes()
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert neu.read_bytes() == vorher and all(a[2] == "stdout" for a in ocr)
    con = db.verbinde(konfig.db_datei)
    assert con.execute("SELECT count(*) FROM ocr_cache WHERE ebene IS NOT NULL").fetchone()[0] == 0
    con.close()


def test_altbestand_nur_mit_stufe_alle_und_schaetzung(tmp_path, ocr):
    konfig, ablage = _konfig(tmp_path, stufe="aus")
    a = h.scan_pdf(ablage / "Archiv" / "a.pdf", ["Altbestand eins"], seiten=2)
    b = h.scan_pdf(ablage / "Steuer" / "b.pdf", ["Altbestand zwei"])
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert len(ocr) == 3

    # "neue_scans" laesst den Altbestand in Ruhe
    konfig.textebene = "neue_scans"
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert _ocr_schriften(a) == 0 and len(ocr) == 3

    konfig.textebene = "alle"
    s = Suchindex(konfig).textebene_schaetzung()
    assert (s["dateien"], s["seiten"]) == (2, 3) and s["sekunden"] > 0 and s["bytes"] > 0
    con = db.verbinde(konfig.db_datei)
    od = textebene.schaetzung(con, konfig, onedrive=[str(ablage / "Steuer")])
    con.close()
    assert od["onedrive_dateien"] == 1 and od["onedrive_bytes"] >= os.path.getsize(b)
    assert "OneDrive" in textebene.schaetzung_text(od) and "3 Seiten" in textebene.schaetzung_text(od)

    assert Indexer(konfig, synchron=True).lauf() == 0
    assert len(ocr) == 6                         # Tesseract liest die drei Seiten noch einmal (Positionen)
    assert _ocr_schriften(a, 0) == _ocr_schriften(a, 1) == _ocr_schriften(b) == 1
    assert Suchindex(konfig).textebene_schaetzung()["dateien"] == 0


def test_dauerhafte_gruende_werden_nicht_wiederholt(tmp_path, ocr):
    konfig, ablage = _konfig(tmp_path)
    scan = h.scan_pdf(ablage / "1A" / "signiert.pdf", ["Signiert"])
    _signiert(scan)
    vorher = scan.read_bytes()
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert _dok(konfig, scan)["textebene_grund"] == "signiert" and scan.read_bytes() == vorher
    assert Suchindex(konfig).status()["textebene"]["gruende"] == {"signiert": 1}
    indexer = Indexer(konfig, synchron=True)
    assert indexer.lauf() == 0 and indexer.stat["textebene_dateien"] == 0


def test_gesperrt_wird_beim_naechsten_lauf_nachgeholt(tmp_path, ocr, monkeypatch):
    konfig, ablage = _konfig(tmp_path)
    scan = h.scan_pdf(ablage / "1A" / "offen.pdf", ["In PaperPort geöffnet"])
    monkeypatch.setattr(plattform, "gesperrt", lambda pfad: True)
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert _dok(konfig, scan)["textebene_grund"] == "gesperrt" and _ocr_schriften(scan) == 0
    monkeypatch.setattr(plattform, "gesperrt", lambda pfad: False)
    assert Indexer(konfig, synchron=True).lauf() == 0
    d = _dok(konfig, scan)
    assert d["textebene_am"] and d["textebene_grund"] is None and _ocr_schriften(scan) == 1


# --------------------------------------------------------------------------- Zusammenspiel mit PDFSM

def _sortieren(idx, pfad, ziel_ordner, neuer_name):
    """Wie PDFSM beim Sortieren: Metadaten in die PDF (pikepdf), dann umbenennen und verschieben, mit Meldungen."""
    from src.core.file_manager import FileManager
    from src.core.pdf_metadata import PDFMetadata, write_metadata
    from src.search.meldungen import meldungen

    meldungen.konfigurieren(lambda: idx)          # FileManager meldet an diesen Index (conftest stellt zurueck)
    assert write_metadata(pfad, PDFMetadata(korrespondent="Stadtwerke", steuerjahr="2026", subject="Rechnung"))
    meldungen.melden("datei_geaendert", str(pfad))
    fm = FileManager()
    umbenannt = fm.rename_file(pfad, neuer_name)
    verschoben = fm.move_file(umbenannt, ziel_ordner)
    assert meldungen.warten(20) and meldungen.fehler == 0
    return verschoben


def _korrespondent(pfad) -> str | None:
    import pikepdf

    with pikepdf.open(pfad) as pdf:
        wert = pdf.docinfo.get("/Korrespondent")
        return str(wert) if wert is not None else None


def test_erst_sortieren_dann_textebene(tmp_path, ocr, monkeypatch):
    """Der Analyzer erkennt den neuen Scan, PDFSM sortiert, der naechste Lauf schreibt am neuen Ort - einmal."""
    from src.core.pdf_analyzer import PDFAnalyzer
    from src.search.meldungen import meldungen

    konfig, ablage = _konfig(tmp_path)
    idx = Suchindex(konfig)
    monkeypatch.setattr("src.core.pdf_analyzer.suchindex_fuer_analyse", lambda: idx)
    monkeypatch.setattr("src.core.pdf_analyzer._search_konfig", lambda: konfig)
    scan = h.scan_pdf(ablage / "1A" / "scan_001.pdf", ["Stromrechnung"], seiten=2)

    with PDFAnalyzer(scan) as a:
        assert TEXT in a.extract_text() and a.ocr_used
    assert len(ocr) == 2 and all("textonly_pdf=1" in x for x in ocr)
    assert _ocr_schriften(scan) == 0                       # die Oberflaeche schreibt nie selbst

    ziel = _sortieren(idx, scan, ablage / "Steuer", "Stadtwerke Rechnung.pdf")
    assert not scan.exists() and _korrespondent(ziel) == "Stadtwerke"

    assert Indexer(konfig, synchron=True).lauf() == 0
    assert len(ocr) == 2                                   # keine zweite OCR
    assert _ocr_schriften(ziel, 0) == _ocr_schriften(ziel, 1) == 1
    assert _korrespondent(ziel) == "Stadtwerke"            # Metadaten bleiben
    assert [e["pfad"] for e in idx.textebene_protokoll()] == [str(ziel)]
    assert not list((ablage / "1A").iterdir())             # am alten Ort entsteht nichts

    # Weiter verschieben und neu einlesen: kein zweites Schreiben
    from src.core.file_manager import FileManager
    weiter = FileManager().move_file(ziel, ablage / "Archiv")
    assert meldungen.warten(20)
    bytes_vorher = weiter.read_bytes()
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert weiter.read_bytes() == bytes_vorher and len(idx.textebene_protokoll()) == 1
    assert idx.textebene_protokoll()[0]["aktueller_pfad"] == str(weiter)


def test_erst_textebene_dann_sortieren(tmp_path, ocr):
    """Der Lauf war schneller: die Datei hat ihre Textebene schon, Sortieren und Metadaten erhalten sie."""
    konfig, ablage = _konfig(tmp_path)
    idx = Suchindex(konfig)
    scan = h.scan_pdf(ablage / "1A" / "scan_002.pdf", ["Versicherung"])
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert _ocr_schriften(scan) == 1 and len(idx.textebene_protokoll()) == 1

    ziel = _sortieren(idx, scan, ablage / "Steuer", "Versicherung 2026.pdf")
    assert _ocr_schriften(ziel) == 1 and TEXT in pymupdf.open(ziel)[0].get_text()
    assert _korrespondent(ziel) == "Stadtwerke"
    assert idx.dokument_nach_pfad(str(ziel))["textebene_am"]

    # Die Meldung „geaendert“ kam erst nach dem Umbenennen an (Warteschlange); der naechste Lauf liest
    # die Datei neu: die Seite ist jetzt Text, keine OCR, kein zweites Schreiben
    bytes_vorher, aufrufe = ziel.read_bytes(), len(ocr)
    assert Indexer(konfig, synchron=True).lauf() == 0
    d = idx.dokument_nach_pfad(str(ziel))
    assert d["textebene_am"] and d["textstatus"] == "text" and d["korrespondent"] == "Stadtwerke"
    assert ziel.read_bytes() == bytes_vorher and len(ocr) == aufrufe and len(idx.textebene_protokoll()) == 1


def test_verlorene_textebene_wird_neu_geschrieben(tmp_path, ocr):
    konfig, ablage = _konfig(tmp_path)
    scan = h.scan_pdf(ablage / "1A" / "scan.pdf", ["Kaufvertrag"])
    assert Indexer(konfig, synchron=True).lauf() == 0
    sicherung = Suchindex(konfig).textebene_protokoll()[0]["sicherung"]
    shutil.copyfile(sicherung, scan)              # ein anderes Programm legt die alte Fassung zurueck
    assert _ocr_schriften(scan) == 0
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert _ocr_schriften(scan) == 1 and len(Suchindex(konfig).textebene_protokoll()) == 2
    assert len(ocr) == 1                          # Text-PDF kam aus dem Cache


def test_verschiebung_ohne_meldung_wird_nach_dem_schreiben_erkannt(tmp_path, ocr):
    """Groesse und Aenderungszeit stehen nach dem Schreiben im Index: die Signatur findet die Datei wieder."""
    konfig, ablage = _konfig(tmp_path, stufe="alle")
    scan = h.scan_pdf(ablage / "Archiv" / "scan.pdf", ["Mietvertrag"])
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert _ocr_schriften(scan) == 1
    ziel = ablage / "Steuer" / "scan.pdf"
    shutil.move(scan, ziel)                       # im Explorer verschoben, ohne PDFSM
    indexer = Indexer(konfig, synchron=True)
    assert indexer.lauf() == 0
    assert indexer.stat["verschoben"] == 1 and indexer.stat["gelesen"] == 0
    assert _dok(konfig, ziel)["textebene_am"] and len(Suchindex(konfig).textebene_protokoll()) == 1


# --------------------------------------------------------------------------- Rueckgaengig, Aufbewahrung

def test_rueckgaengig(tmp_path, ocr):
    konfig, ablage = _konfig(tmp_path)
    scan = h.scan_pdf(ablage / "1A" / "scan.pdf", ["Darlehen"])
    vorher_bytes, vorher_mtime = scan.read_bytes(), os.stat(scan).st_mtime_ns
    assert Indexer(konfig, synchron=True).lauf() == 0
    idx = Suchindex(konfig)
    eintrag = idx.textebene_protokoll()[0]

    ok, meldung = idx.textebene_rueckgaengig(eintrag["id"])
    assert ok, meldung
    assert scan.read_bytes() == vorher_bytes and os.stat(scan).st_mtime_ns == vorher_mtime
    assert not os.path.exists(eintrag["sicherung"]) and _reste(scan.parent) == []
    e = idx.textebene_protokoll()[0]
    assert e["status"] == "rueckgaengig" and e["rueckgaengig_am"] and e["sicherung"] is None
    d = _dok(konfig, scan)
    assert d["textebene_am"] is None and d["textebene_grund"] == "rueckgaengig"
    assert d["textstatus"] == "ocr" and idx.suche("Gesamtbetrag")["gesamt"] == 1   # Text bleibt im Index

    assert idx.textebene_rueckgaengig(eintrag["id"]) == (False, "Diese Änderung wurde schon rückgängig gemacht.")
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert scan.read_bytes() == vorher_bytes        # wird nicht wieder geschrieben


def test_rueckgaengig_nach_spaeterer_aenderung_nur_erzwungen(tmp_path, ocr):
    konfig, ablage = _konfig(tmp_path)
    scan = h.scan_pdf(ablage / "1A" / "scan.pdf", ["Police"])
    assert Indexer(konfig, synchron=True).lauf() == 0
    with pymupdf.open(scan) as d:
        d.set_metadata({"title": "Später geändert"})
        d.saveIncr()
    idx = Suchindex(konfig)
    eintrag = idx.textebene_protokoll()[0]
    ok, meldung = idx.textebene_rueckgaengig(eintrag["id"])
    assert not ok and "geändert" in meldung and _ocr_schriften(scan) == 1
    ok, meldung = idx.textebene_rueckgaengig(eintrag["id"], erzwingen=True)
    assert ok and _ocr_schriften(scan) == 0


def test_sicherungen_und_text_pdfs_laufen_ab(tmp_path, ocr):
    konfig, ablage = _konfig(tmp_path, textebene_sicherung_tage=30)
    h.scan_pdf(ablage / "1A" / "scan.pdf", ["Abrechnung"])
    assert Indexer(konfig, synchron=True).lauf() == 0
    sicherung = Suchindex(konfig).textebene_protokoll()[0]["sicherung"]
    ordner = konfig.sicherung_ordner
    verwaist_alt = ordner / "20200101-120000_deadbeef_alt.pdf"
    verwaist_neu = ordner / f"{datetime.now():%Y%m%d-%H%M%S}_deadbeef_neu.pdf"
    fremd = ordner / "notiz.txt"
    for f in (verwaist_alt, verwaist_neu, fremd):
        f.write_bytes(b"x")
    con = db.verbinde(konfig.db_datei)
    try:
        weg = textebene.aufraeumen(con, konfig)
        assert weg == {"sicherungen": 1, "ebenen": 0} and not verwaist_alt.exists() and verwaist_neu.exists()

        konfig.textebene_sicherung_tage = 30
        weg = textebene.aufraeumen(con, konfig, jetzt=datetime.now() + timedelta(days=31))
        assert weg["sicherungen"] == 2 and not os.path.exists(sicherung) and fremd.exists()
        assert con.execute("SELECT sicherung FROM textebene_protokoll").fetchone()[0] is None
        assert weg["ebenen"] == 0                     # Text-PDFs bleiben laenger (verlorene Textebene neu schreiben)
        weg = textebene.aufraeumen(con, konfig,
                                   jetzt=datetime.now() + timedelta(days=textebene.EBENE_AUFBEWAHREN_TAGE + 1))
        assert weg["ebenen"] == 1
        con.commit()
    finally:
        con.close()
    ok, meldung = Suchindex(konfig).textebene_rueckgaengig(1)
    assert not ok and "Sicherungskopie" in meldung


def test_sicherungen_unbegrenzt(tmp_path, ocr):
    konfig, ablage = _konfig(tmp_path, textebene_sicherung_tage=0)
    h.scan_pdf(ablage / "1A" / "scan.pdf", ["Grundbuch"])
    assert Indexer(konfig, synchron=True).lauf() == 0
    sicherung = Suchindex(konfig).textebene_protokoll()[0]["sicherung"]
    alt = konfig.sicherung_ordner / "20200101-120000_deadbeef_alt.pdf"
    alt.write_bytes(b"x")
    con = db.verbinde(konfig.db_datei)
    try:
        weg = textebene.aufraeumen(con, konfig, jetzt=datetime.now() + timedelta(days=400))
    finally:
        con.close()
    assert weg["sicherungen"] == 0 and os.path.exists(sicherung) and alt.exists()


# --------------------------------------------------------------------------- Anhalten, Schema, Lesen

def test_anhalten_und_fortsetzen(tmp_path, ocr, monkeypatch):
    konfig, ablage = _konfig(tmp_path, stufe="aus")
    for i in range(4):
        h.scan_pdf(ablage / "Archiv" / f"alt{i}.pdf", [f"Altbestand {i}"])
    assert Indexer(konfig, synchron=True).lauf() == 0
    konfig.textebene = "alle"
    monkeypatch.setattr("src.search.indexer.ANHALTEN_PRUEFEN_S", 0)
    echt = textebene.datei_schreiben

    def schreiben_und_anhalten(a):
        erg = echt(a)
        anhalten_datei(konfig).touch()            # der Nutzer klickt „Anhalten“
        return erg
    monkeypatch.setattr(textebene, "datei_schreiben", schreiben_und_anhalten)
    indexer = Indexer(konfig, synchron=True)
    assert indexer.lauf() == 1                    # angehalten
    assert indexer.stat["textebene_geschrieben"] == 1 and not anhalten_datei(konfig).exists()
    monkeypatch.setattr(textebene, "datei_schreiben", echt)
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert len(Suchindex(konfig).textebene_protokoll()) == 4
    assert Suchindex(konfig).lauf_anhalten() is False          # ohne laufenden Lauf


def test_schema_v2_bekommt_die_spalten_der_textebene(tmp_path):
    con = db.verbinde(tmp_path / "suche.db")
    db.init(con)
    # Stand von Version 2 vor Phase 5b nachbauen
    con.execute("DROP INDEX ix_ocr_cache_ebene")
    for spalte in ("textebene_am", "textebene_grund"):
        con.execute(f"ALTER TABLE dokumente DROP COLUMN {spalte}")
    for spalte in ("ebene", "ebene_am"):
        con.execute(f"ALTER TABLE ocr_cache DROP COLUMN {spalte}")
    con.execute("DROP TABLE textebene_protokoll")
    con.commit()
    assert db.schema_stand(con) == 1
    assert db.ergaenze_schema(con) is True
    assert db.schema_stand(con) == 2 and db.ergaenze_schema(con) is False
    assert {"textebene_am", "textebene_grund"} <= db._spalten(con, "dokumente")
    assert {"ebene", "ebene_am"} <= db._spalten(con, "ocr_cache")
    con.close()


def test_seite_mit_ocr_textebene_gilt_als_text(tmp_path):
    scan = h.scan_pdf(tmp_path / "kurz.pdf", ["x"])
    with pymupdf.open(scan) as d:
        r = d[0].rect
        textebene.ebene_auflegen(d[0], h.text_pdf(r.width, r.height, "S. 2"))   # weniger als min_zeichen
        d.saveIncr()
    gelesen = extract.pdf_text(str(scan), 25)
    assert gelesen["status"] == "text" and gelesen["ohne_text"] == []


# --------------------------------------------------------------------------- Kommandozeile

def test_dienst_textebene(tmp_path, ocr, monkeypatch, capsys):
    import json

    from src.search import dienst
    from src.search import indexer as indexer_modul

    monkeypatch.setattr(indexer_modul, "logging_einrichten", lambda konfig, konsole=True: None)
    echt = indexer_modul.Indexer         # Arbeitsprozesse kennen den Tesseract-Ersatz nicht: synchron
    monkeypatch.setattr(indexer_modul, "Indexer", lambda *a, **kw: echt(*a, synchron=True, **kw))
    konfig, ablage = _konfig(tmp_path, stufe="aus")
    scan = h.scan_pdf(ablage / "Archiv" / "alt.pdf", ["Altbestand"])
    vorher = scan.read_bytes()
    assert Indexer(konfig, synchron=True).lauf() == 0
    cfg = tmp_path / "config.json"
    konfig.textebene = "alle"
    konfig.prozesse = 1
    cfg.write_text(json.dumps({"suche": konfig.als_dict()}), encoding="utf-8")
    argv = ["--config", str(cfg), "textebene"]

    assert dienst.main(argv + ["schaetzen"]) == 0
    out = capsys.readouterr().out
    assert "Stufe in den Einstellungen: alle" in out and "1 texterkannte PDFs mit 1 Seiten" in out
    assert dienst.main(argv + ["protokoll"]) == 0
    assert "Noch keine Datei" in capsys.readouterr().out

    assert dienst.main(argv + ["schreiben"]) == 0
    assert _ocr_schriften(scan) == 1
    assert dienst.main(argv + ["protokoll"]) == 0
    out = capsys.readouterr().out
    assert "[1]" in out and "Seiten 1" in out and "Sicherung vorhanden" in out and str(scan) in out
    assert dienst.main(["--config", str(cfg), "status"]) == 0
    assert "Textebene in PDFs (alle): 1 geschrieben" in capsys.readouterr().out

    assert dienst.main(argv + ["rueckgaengig", "1"]) == 0
    assert "wiederhergestellt" in capsys.readouterr().out and scan.read_bytes() == vorher
    assert dienst.main(argv + ["rueckgaengig", "1"]) == 1
    assert "schon rückgängig" in capsys.readouterr().out

    konfig.textebene = "aus"
    cfg.write_text(json.dumps({"suche": konfig.als_dict()}), encoding="utf-8")
    assert dienst.main(argv + ["schreiben"]) == 1
    assert "ausgeschaltet" in capsys.readouterr().out

"""Gedrehte Scans erkennen und richtig herum speichern (Issue #151, ``extract.seite_erkennen``, ``textebene``).

Alle Dateien entstehen synthetisch in ``tmp_path``. Tesseract ist durch
``helfer_suche.fake_tesseract_lage`` ersetzt, das wie das mitgelieferte
Tesseract ohne ``osd`` antwortet: aufrecht sicher und waagerecht, quer
richtig, aber senkrecht, kopfstehend Buchstabensalat mit niedriger Konfidenz
(der Test mit echtem Tesseract steht am Ende und wird ohne Tesseract
uebersprungen). Geprueft wird: Bewertung der TSV, Wahl der Lage, dass die
Datei beim Erkennen unveraendert bleibt, Drehen im Indexlauf je nach Stufe
(mit und ohne Textebene, eine Sicherungskopie, ein Protokolleintrag),
Vormerkung bei der OCR auch nach dem Wegsortieren, Rueckgaengig, deckungsgleiche
Textebene auf ungedrehter Datei, Einstellungen und Protokollanzeige.
"""

from __future__ import annotations

import os
import shutil

import pymupdf
import pytest

from src.search import db, extract, textebene
from src.search.indexer import Indexer
from src.search.konfig import SearchConfig
from src.search.suchindex import Suchindex
from src.utils.tesseract import fehlende_sprachen, find_tesseract, tessdata_dir
from tests import helfer_suche as h


@pytest.fixture
def lagen(monkeypatch):
    return h.fake_tesseract_lage(monkeypatch)


def _cfg(**kw) -> dict:
    cfg = {"tesseract": "tesseract-fake", "tessdata": None, "sprachen": "deu+eng", "dpi": 72, "min_zeichen": 25,
           "lage_pruefen": True}
    cfg.update(kw)
    return cfg


def _konfig(tmp_path, textebene_stufe="aus", drehen="neue_scans"):
    ablage = tmp_path / "Ablage"
    for ordner in ("1A", "Archiv"):
        (ablage / ordner).mkdir(parents=True, exist_ok=True)
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], prioritaet=[str(ablage / "1A")], ocr_aktiv=True,
                           ocr_tesseract="tesseract-fake", ocr_dpi=72, textebene=textebene_stufe, auto_drehen=drehen)
    return konfig, ablage


def _con(konfig):
    return db.verbinde(konfig.db_datei)


def _drehung(pfad, seite=0) -> int:
    with pymupdf.open(pfad) as d:
        return d[seite].rotation


def _protokoll(konfig) -> list[dict]:
    return Suchindex(konfig).textebene_protokoll()


def _treffer(konfig, wort) -> list[str]:
    return [t["name"] for t in Suchindex(konfig).suche(wort)["treffer"]]


def _wort_angezeigt(seite, wort) -> pymupdf.Rect:
    """Wo ein Wort der Textebene auf der angezeigten Seite steht."""
    for w in seite.get_text("words"):
        if w[4] == wort:
            return pymupdf.Rect(w[:4]) * seite.rotation_matrix
    raise AssertionError(f"{wort} nicht gefunden")


# --------------------------------------------------------------------------- Bewertung der TSV

def test_lesbarkeit_zaehlt_nur_sichere_waagerechte_woerter():
    gut = h._lage_tsv(["Rechnung", "4711", "x", "Euro"], 95, senkrecht=False)
    assert extract.lesbarkeit(gut) == (16, 16)              # "x" ist Rauschen
    assert extract.lesbarkeit(h._lage_tsv(["Rechnung", "4711"], 95, senkrecht=True)) == (12, 0)
    assert extract.lesbarkeit(h._lage_tsv(["USNBIUSA", "JON}"], 30, senkrecht=False)) == (11, 0)
    assert extract.lesbarkeit(None) is None
    assert extract.lesbarkeit(h._lage_tsv([], 0, senkrecht=False)) == (0, 0)


def test_liegt_falsch_erst_bei_genug_schrift():
    assert extract.liegt_falsch((50, 0), 25) and extract.liegt_falsch((50, 24), 25)
    assert not extract.liegt_falsch((50, 25), 25)           # die Haelfte sicher: liegt richtig
    assert not extract.liegt_falsch((10, 0), 25)            # zu wenig Schrift (leere Rueckseite, Stempel)
    assert not extract.liegt_falsch(None, 25)


# --------------------------------------------------------------------------- Lage waehlen

@pytest.mark.parametrize("inhalt, erwartet, gesehen", [
    (180, 180, ["kopf", "quer", "aufrecht", "quer"]),
    (90, 270, ["quer", "kopf", "quer", "aufrecht"]),
    (270, 90, ["quer", "aufrecht", "quer", "kopf"]),
])
def test_falsch_liegende_seite_wird_in_allen_lagen_gelesen(tmp_path, lagen, inhalt, erwartet, gesehen):
    scan = h.scan_mit_lage(tmp_path / "scan.pdf", inhalt)
    vorher = scan.read_bytes()
    erg = extract.pdf_ocr(str(scan), [1], _cfg())
    assert erg["fehler"] is None and erg["drehungen"] == {1: erwartet}
    assert erg["texte"][1] == h.LAGE_TEXT and lagen == gesehen
    assert scan.read_bytes() == vorher                      # gedreht wird nur die Seite im Speicher


def test_aufrechte_und_leere_seiten_kosten_keinen_weiteren_aufruf(tmp_path, lagen):
    scan = h.scan_mit_lage(tmp_path / "scan.pdf", 0)
    erg = extract.pdf_ocr(str(scan), [1], _cfg())
    assert erg["drehungen"] == {} and erg["texte"][1] == h.LAGE_TEXT and lagen == ["aufrecht"]
    leer = tmp_path / "leer.pdf"
    with pymupdf.open() as d:
        seite = d.new_page()
        weiss = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 60, 80), 0)
        weiss.clear_with(255)
        seite.insert_image(seite.rect, pixmap=weiss)
        d.save(str(leer))
    lagen.clear()
    erg = extract.pdf_ocr(str(leer), [1], _cfg())
    assert erg["drehungen"] == {} and lagen == ["leer"]


def test_ohne_lage_pruefen_ein_aufruf_wie_bisher(tmp_path, lagen):
    scan = h.scan_mit_lage(tmp_path / "scan.pdf", 180)
    erg = extract.pdf_ocr(str(scan), [1], _cfg(lage_pruefen=False))
    assert erg["drehungen"] == {} and erg["texte"][1] == h.LAGE_SALAT and lagen == ["kopf"]


def test_keine_lage_deutlich_besser_dann_bleibt_es_wie_angezeigt(tmp_path, monkeypatch):
    """Salat in allen Lagen (z. B. Handschrift): keine Drehung, der erste Text bleibt."""
    h.fake_tesseract_lage(monkeypatch)
    monkeypatch.setattr(h, "bild_lage", lambda png: "kopf")
    scan = h.scan_mit_lage(tmp_path / "scan.pdf", 0)
    erg = extract.pdf_ocr(str(scan), [1], _cfg())
    assert erg["drehungen"] == {} and erg["texte"][1] == h.LAGE_SALAT


def test_textebene_kommt_aus_der_besten_lage(tmp_path, lagen):
    scan = h.scan_mit_lage(tmp_path / "scan.pdf", 90)
    erg = extract.pdf_ocr(str(scan), [1], _cfg(textebene=True))
    assert erg["drehungen"] == {1: 270}
    with pymupdf.open("pdf", erg["ebenen"][1]) as d, pymupdf.open(scan) as s:
        # gelesen in der Lage +270: Breite und Hoehe der Text-PDF sind vertauscht
        assert round(d[0].rect.width) == round(s[0].rect.height) and "Rechnung" in d[0].get_text()


# --------------------------------------------------------------------------- Textebene auf ungedrehter Datei

@pytest.mark.parametrize("drehung", [0, 90])
@pytest.mark.parametrize("zusatz", [90, 180, 270])
def test_textebene_aus_gedrehter_lage_liegt_deckungsgleich(drehung, zusatz):
    """Die Text-PDF entstand in der Lage ``drehung + zusatz``; so angezeigt muss ihr Quadrat oben links liegen."""
    doc = pymupdf.open()
    seite = doc.new_page(width=400, height=600)
    seite.set_rotation(drehung)
    lage = (drehung + zusatz) % 360
    seite.set_rotation(lage)
    angezeigt = seite.rect
    seite.set_rotation(drehung)
    textebene.ebene_auflegen(seite, h.text_pdf(angezeigt.width, angezeigt.height, "OBENLINKS", sichtbar=True), lage)
    neu = pymupdf.open("pdf", doc.tobytes())
    s = neu[0]
    assert s.rotation == drehung                            # die Datei bleibt ungedreht ...
    s.set_rotation(lage)                                    # ... in der Lage der OCR liegt alles oben links
    pix = s.get_pixmap(dpi=36, colorspace=pymupdf.csGRAY)
    dunkel = [(x, y) for y in range(pix.height) for x in range(pix.width) if pix.samples[y * pix.stride + x] < 100]
    assert (min(x for x, _ in dunkel), min(y for _, y in dunkel)) == (5, 5)
    assert s.get_text().strip() == "OBENLINKS"


def test_pruefen_verlangt_genau_die_vorgesehene_drehung(tmp_path):
    scan = h.scan_mit_lage(tmp_path / "scan.pdf", 0, seiten=2)
    kopie = tmp_path / "kopie.pdf"
    shutil.copyfile(scan, kopie)
    with pymupdf.open(kopie) as d:
        d[0].set_rotation(180)
        d.saveIncr()
    textebene.pruefen(str(scan), str(kopie), {}, {1: 180})
    with pytest.raises(textebene.PruefungFehlgeschlagen):
        textebene.pruefen(str(scan), str(kopie), {}, {1: 90})
    with pytest.raises(textebene.PruefungFehlgeschlagen):
        textebene.pruefen(str(scan), str(kopie), {})        # ohne Vorgabe darf sich nichts drehen


# --------------------------------------------------------------------------- Indexlauf

def test_kopfstehender_neuer_scan_wird_gedreht(tmp_path, lagen):
    konfig, ablage = _konfig(tmp_path)
    scan = h.scan_mit_lage(ablage / "1A" / "kopf.pdf", 180)
    vorher = scan.read_bytes()
    indexer = Indexer(konfig, synchron=True)
    assert indexer.lauf() == 0
    assert _drehung(scan) == 180 and indexer.stat["gedreht_seiten"] == 1
    assert lagen == ["kopf", "quer", "aufrecht", "quer"]
    assert _treffer(konfig, "Gesamtbetrag") == ["kopf.pdf"]

    (eintrag,) = _protokoll(konfig)
    assert eintrag["gedreht"] == "1:180" and eintrag["seiten"] == "" and eintrag["status"] == "geschrieben"
    with open(eintrag["sicherung"], "rb") as f:
        assert f.read() == vorher
    con = _con(konfig)
    try:
        d = con.execute("SELECT * FROM dokumente WHERE name = 'kopf.pdf'").fetchone()
        assert d["textebene_am"] is None and d["groesse"] == os.path.getsize(scan)
        h_neu = con.execute("SELECT bild_hash FROM seiten WHERE dok_id = ?", (d["id"],)).fetchone()[0]
        with pymupdf.open(scan) as pdf:
            assert h_neu == extract._bild_hash(pdf, pdf[0])
        neu = con.execute("SELECT text, drehung, drehen FROM ocr_cache WHERE bild_hash = ?", (h_neu,)).fetchone()
        assert neu["text"] == h.LAGE_TEXT and neu["drehung"] is None and not neu["drehen"]
        alt = con.execute("SELECT drehung, drehen FROM ocr_cache WHERE bild_hash != ?", (h_neu,)).fetchone()
        assert alt["drehung"] == 180 and alt["drehen"] == 0
    finally:
        con.close()

    # Der naechste Lauf hat nichts mehr zu tun
    lagen.clear()
    nachher = scan.read_bytes()
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert scan.read_bytes() == nachher and lagen == [] and len(_protokoll(konfig)) == 1


def test_drehen_und_textebene_in_einem_schritt(tmp_path, lagen):
    konfig, ablage = _konfig(tmp_path, textebene_stufe="neue_scans")
    scan = h.scan_mit_lage(ablage / "1A" / "quer.pdf", 90)
    assert Indexer(konfig, synchron=True).lauf() == 0
    (eintrag,) = _protokoll(konfig)
    assert eintrag["gedreht"] == "1:270" and eintrag["seiten"] == "1"
    with pymupdf.open(scan) as d:
        s = d[0]
        assert s.rotation == 270 and extract.hat_ocr_textebene(s) and "Rechnung" in s.get_text()
        # Die Textebene liegt angezeigt oben (die Attrappe schreibt den Text bei y = 40)
        assert _wort_angezeigt(s, "Rechnung").y0 < 60
    con = _con(konfig)
    try:
        assert con.execute("SELECT textebene_am FROM dokumente").fetchone()[0] is not None
    finally:
        con.close()


def test_stufe_aus_dreht_nicht_textebene_trotzdem_deckungsgleich(tmp_path, lagen):
    konfig, ablage = _konfig(tmp_path, textebene_stufe="neue_scans", drehen="aus")
    scan = h.scan_mit_lage(ablage / "1A" / "kopf.pdf", 180)
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert _treffer(konfig, "Gesamtbetrag") == ["kopf.pdf"]
    (eintrag,) = _protokoll(konfig)
    assert eintrag["gedreht"] is None and eintrag["seiten"] == "1"
    with pymupdf.open(scan) as d:
        s = d[0]
        assert s.rotation == 0 and extract.hat_ocr_textebene(s)
        # Gelesen wurde kopfstehend: der Text steht im Scanbild unten (angezeigt), dort liegt auch die Textebene
        assert _wort_angezeigt(s, "Rechnung").y0 > s.rect.height - 60
    con = _con(konfig)
    try:
        assert tuple(con.execute("SELECT drehung, drehen FROM ocr_cache").fetchone()) == (180, 0)
    finally:
        con.close()


@pytest.mark.parametrize("stufe, gedreht", [("neue_scans", 0), ("alle", 180)])
def test_ausserhalb_des_scan_ordners_nur_mit_stufe_alle(tmp_path, lagen, stufe, gedreht):
    konfig, ablage = _konfig(tmp_path, drehen=stufe)
    scan = h.scan_mit_lage(ablage / "Archiv" / "alt.pdf", 180)
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert _drehung(scan) == gedreht
    assert _treffer(konfig, "Gesamtbetrag") == ["alt.pdf"]   # Text in jedem Fall


def test_vormerkung_der_analyse_gilt_auch_nach_dem_wegsortieren(tmp_path, lagen):
    """PDFSM erkennt den Scan im Scan-Ordner (Analyse), der Nutzer sortiert ihn weg, der Lauf dreht ihn dort."""
    konfig, ablage = _konfig(tmp_path)
    scan = h.scan_mit_lage(ablage / "1A" / "kopf.pdf", 180)
    assert Indexer(konfig, synchron=True).lauf(ohne_ocr=True) == 0
    erg = extract.pdf_ocr(str(scan), [1], konfig.ocr_einstellungen())
    assert erg["drehungen"] == {1: 180}
    assert Suchindex(konfig).ocr_eintragen(str(scan), erg["texte"], drehungen=erg["drehungen"]) == 1
    ziel = ablage / "Archiv" / "Stadtwerke 2024.pdf"
    shutil.move(scan, ziel)
    lagen.clear()
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert _drehung(ziel) == 180 and lagen == []            # Text kam aus dem Cache, keine neue OCR
    assert _protokoll(konfig)[0]["gedreht"] == "1:180"


@pytest.mark.parametrize("stufe, gedreht", [("neue_scans", 180), ("aus", 0)])
def test_ocr_neu_merkt_die_drehung_auch_ausserhalb_des_scan_ordners_vor(tmp_path, lagen, monkeypatch, stufe,
                                                                         gedreht):
    """"OCR neu" ist ausdruecklich verlangt: gedreht wird, wo die Datei liegt (ausser die Stufe ist aus)."""
    from src.core import pdf_analyzer

    konfig, ablage = _konfig(tmp_path, drehen=stufe)
    scan = h.scan_mit_lage(ablage / "Archiv" / "alt.pdf", 180)
    assert Indexer(konfig, synchron=True).lauf(ohne_ocr=True) == 0
    monkeypatch.setattr(pdf_analyzer, "suchindex_fuer_analyse", lambda: Suchindex(konfig))
    monkeypatch.setattr(pdf_analyzer, "ocr_einstellungen_fuer_analyse", lambda: konfig.ocr_einstellungen())
    erg = pdf_analyzer.ocr_neu_durchfuehren(scan)
    assert erg["seiten"] == 1 and erg["gedreht"] == 1 and _treffer(konfig, "Gesamtbetrag") == ["alt.pdf"]
    assert Indexer(konfig, synchron=True).lauf(ohne_ocr=True) == 0
    assert _drehung(scan) == gedreht


def test_rueckgaengig_und_kein_erneutes_drehen(tmp_path, lagen):
    konfig, ablage = _konfig(tmp_path)
    scan = h.scan_mit_lage(ablage / "1A" / "kopf.pdf", 180)
    vorher = scan.read_bytes()
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert _drehung(scan) == 180
    ok, meldung = Suchindex(konfig).textebene_rueckgaengig(_protokoll(konfig)[0]["id"])
    assert ok, meldung
    assert scan.read_bytes() == vorher
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert scan.read_bytes() == vorher and len(_protokoll(konfig)) == 1


def test_signierte_pdf_wird_nicht_gedreht(tmp_path, lagen, monkeypatch):
    konfig, ablage = _konfig(tmp_path)
    scan = h.scan_mit_lage(ablage / "1A" / "signiert.pdf", 180)
    vorher = scan.read_bytes()
    monkeypatch.setattr(textebene, "dokument_grund", lambda doc: "signiert")
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert scan.read_bytes() == vorher and _protokoll(konfig) == []
    con = _con(konfig)
    try:
        assert con.execute("SELECT textebene_grund FROM dokumente").fetchone()[0] == "signiert"
    finally:
        con.close()


# --------------------------------------------------------------------------- Einstellungen, Schema, Anzeige

def test_einstellung_auto_drehen():
    assert SearchConfig().auto_drehen == "neue_scans"
    assert SearchConfig(auto_drehen="quatsch").auto_drehen == "aus"
    k = SearchConfig(prioritaet=["C:/Scans"], auto_drehen="neue_scans")
    assert k.drehen_vormerken("C:/Scans/neu.pdf") and not k.drehen_vormerken("C:/Ablage/neu.pdf")
    assert SearchConfig(auto_drehen="alle").drehen_vormerken("C:/Ablage/neu.pdf")
    assert not SearchConfig(prioritaet=["C:/Scans"], auto_drehen="aus").drehen_vormerken("C:/Scans/neu.pdf")
    assert SearchConfig.aus_dict(SearchConfig(auto_drehen="alle").als_dict()).auto_drehen == "alle"
    assert SearchConfig().ocr_einstellungen()["lage_pruefen"] is True


def test_schema_bekommt_die_spalten_fuer_das_drehen(tmp_path):
    con = db.verbinde(tmp_path / "suche.db")
    db.init(con)
    con.execute("DROP INDEX ix_ocr_cache_drehen")           # Stand vor Issue #151 nachbauen
    for spalte in ("drehung", "drehen"):
        con.execute(f"ALTER TABLE ocr_cache DROP COLUMN {spalte}")
    con.execute("ALTER TABLE textebene_protokoll DROP COLUMN gedreht")
    con.commit()
    assert db.schema_stand(con) == 1
    assert db.ergaenze_schema(con) is True and db.schema_stand(con) == 2
    assert {"drehung", "drehen"} <= db._spalten(con, "ocr_cache")
    assert "gedreht" in db._spalten(con, "textebene_protokoll")
    # Die Kandidaten fuer das Schreiben kommen ueber die Teilindizes, nicht ueber den ganzen Cache
    plan = " ".join(str(tuple(r)) for r in con.execute(
        "EXPLAIN QUERY PLAN SELECT bild_hash FROM ocr_cache c WHERE c.drehen = 1 AND c.drehung % 360 != 0"))
    assert "ix_ocr_cache_drehen" in plan
    con.close()


def test_protokoll_zeigt_gedrehte_seiten():
    from src.gui.textebene_dialog import gedreht_text

    assert gedreht_text("1:180,3:90") == "S. 1: 180°, S. 3: 90°"
    assert gedreht_text(None) == "" and gedreht_text("") == ""
    assert textebene.drehungen_text({3: 90, 1: 180}) == "1:180,3:90"


def test_einstellungsdialog_speichert_die_stufe(qtbot, monkeypatch, tmp_path):
    from src.utils import config as cfg_mod
    from src.utils.config import Config

    monkeypatch.setattr("src.utils.tesseract.find_tesseract", lambda: None)
    cfg = Config.__new__(Config)
    cfg.config_path = tmp_path / "config.json"
    cfg._config = {}
    cfg.load()
    monkeypatch.setattr(cfg_mod, "get_config", lambda: cfg)
    monkeypatch.setattr("src.gui.settings_dialog.get_config", lambda: cfg, raising=False)
    from src.gui.settings_dialog import SettingsDialog

    dlg = SettingsDialog()
    qtbot.addWidget(dlg)
    assert dlg.search_autorotate_combo.currentData() == "neue_scans"
    dlg.search_autorotate_combo.setCurrentIndex(dlg.search_autorotate_combo.findData("aus"))
    dlg._save_settings()
    assert cfg.get_search_config().auto_drehen == "aus"
    dlg2 = SettingsDialog()
    qtbot.addWidget(dlg2)
    assert dlg2.search_autorotate_combo.currentData() == "aus"


# --------------------------------------------------------------------------- Echtes Tesseract

TESSERACT = find_tesseract()
TESSDATA = tessdata_dir(TESSERACT) if TESSERACT else None


@pytest.mark.skipif(not TESSERACT or bool(fehlende_sprachen(TESSDATA, "deu+eng")),
                    reason="Tesseract mit deu+eng ist nicht installiert")
@pytest.mark.parametrize("inhalt, erwartet", [(180, 180), (90, 270)])
def test_echtes_tesseract_findet_die_richtige_lage(tmp_path, inhalt, erwartet):
    zeilen = ["Stadtwerke Musterstadt GmbH", "Rechnung Nummer 2024-1187", "Gesamtbetrag 1.181,20 Euro",
              "Bitte ueberweisen Sie den Betrag", "Vielen Dank fuer Ihr Vertrauen"]
    scan = h.scan_mit_lage(tmp_path / "scan.pdf", inhalt, dpi=150, zeilen=zeilen)
    cfg = {"tesseract": TESSERACT, "tessdata": TESSDATA, "sprachen": "deu+eng", "dpi": 200, "min_zeichen": 25,
           "lage_pruefen": True}
    erg = extract.pdf_ocr(str(scan), [1], cfg)
    assert erg["fehler"] is None and erg["drehungen"] == {1: erwartet}
    assert "Gesamtbetrag" in erg["texte"][1] and "Rechnung" in erg["texte"][1]


@pytest.mark.skipif(not TESSERACT or bool(fehlende_sprachen(TESSDATA, "deu+eng")),
                    reason="Tesseract mit deu+eng ist nicht installiert")
@pytest.mark.parametrize("inhalt", [90, 180])
def test_echt_gedreht_und_textebene_liegt_auf_den_woertern(tmp_path, inhalt):
    zeilen = ["Stadtwerke Musterstadt GmbH", "Rechnung Nummer 2024-1187", "Gesamtbetrag 1.181,20 Euro"]
    scan = h.scan_mit_lage(tmp_path / "scan.pdf", inhalt, dpi=150, zeilen=zeilen)
    cfg = {"tesseract": TESSERACT, "tessdata": TESSDATA, "sprachen": "deu+eng", "dpi": 200, "min_zeichen": 25,
           "lage_pruefen": True, "textebene": True}
    erg = extract.pdf_ocr(str(scan), [1], cfg)
    grad = erg["drehungen"][1]
    st = os.stat(scan)
    res = textebene.datei_schreiben({
        "pfad": str(scan), "groesse": st.st_size, "mtime_ns": st.st_mtime_ns,
        "seiten": {1: {"hash": None, "ebene": erg["ebenen"][1], "drehung": grad}},
        "drehen": {1: {"hash": None, "grad": grad}}, "ocr": None,
        "sicherung_ordner": str(tmp_path / "sicherung"), "min_zeichen": 25,
    })
    assert res["status"] == "geschrieben" and res["gedreht"] == {1: grad} and res["seiten"] == [1], res
    # So zeichnet scan_mit_lage den Text auf die aufrechte Seite
    with pymupdf.open() as q:
        vorlage = q.new_page(width=595, height=842)
        for i, zeile in enumerate(zeilen):
            vorlage.insert_text((72, 220 + 30 * i), zeile, fontsize=18)
        soll = {w: vorlage.search_for(w)[0] for w in ("Musterstadt", "Gesamtbetrag")}
    with pymupdf.open(scan) as d:
        s = d[0]
        assert s.rotation == grad and extract.hat_ocr_textebene(s)
        for wort, r in soll.items():
            ist = _wort_angezeigt(s, wort)
            assert abs(ist.x0 - r.x0) < 8 and abs(ist.y0 - r.y0) < 8, (wort, ist, r)

"""Schief gescannte Seiten im Indexlauf gerade ausrichten (Issue #165, ``extract``, ``db``, ``textebene``).

Alle Dateien entstehen synthetisch in ``tmp_path`` (``helfer_suche.scan_schief``).
Geprueft wird: Messen beim Einlesen nur, wo die Stufe gilt (auch bei Scans mit
Textebene des Scanprogramms), Ausrichten im Schreibschritt mit Sicherungskopie
und Protokoll, Vormerkung auch nach dem Wegsortieren, kein zweites Ausrichten
(naechster Lauf, Rueckgaengig, von Hand schon ausgerichtet), Drehen, Textebene
und Ausrichten in einem Schritt, Schema, Status und Protokollanzeige.
"""

from __future__ import annotations

import shutil

import pymupdf
import pytest

from src.search import db, extract, gerade, textebene
from src.search.indexer import Indexer
from src.search.konfig import SearchConfig
from src.search.suchindex import Suchindex
from tests import helfer_suche as h

TOLERANZ = 0.15


def _konfig(tmp_path, stufe="neue_scans", **kw):
    ablage = tmp_path / "Ablage"
    for ordner in ("1A", "Archiv"):
        (ablage / ordner).mkdir(parents=True, exist_ok=True)
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], prioritaet=[str(ablage / "1A")], auto_gerade=stufe,
                           **kw)
    return konfig, ablage


def _protokoll(konfig) -> list[dict]:
    return Suchindex(konfig).textebene_protokoll()


def _schraeglagen(konfig) -> list[tuple]:
    con = db.verbinde(konfig.db_datei)
    try:
        return [tuple(r) for r in con.execute("SELECT round(winkel, 1), gerade FROM schraeglage ORDER BY winkel")]
    finally:
        con.close()


def _ist_gerade(pfad, seite: int = 1) -> bool:
    rest = h.schraeglage_der_datei(pfad, seite)
    return rest is not None and abs(rest) < gerade.MIN_WINKEL


def test_schiefer_neuer_scan_wird_gerade_ausgerichtet(tmp_path):
    konfig, ablage = _konfig(tmp_path)
    scan = h.scan_schief(ablage / "1A" / "schief.pdf", 2.5)
    vorher = scan.read_bytes()
    indexer = Indexer(konfig, synchron=True)
    assert indexer.lauf() == 0
    assert indexer.stat["schief_erkannt"] == 1 and indexer.stat["gerade_seiten"] == 1
    assert h.ausrichtung_der_datei(scan) == pytest.approx(2.5, abs=TOLERANZ) and _ist_gerade(scan)
    assert scan.read_bytes().startswith(vorher)                # inkrementell, Scanbild unveraendert

    (eintrag,) = _protokoll(konfig)
    assert eintrag["gerade"].startswith("1:2.") and eintrag["gedreht"] is None and eintrag["seiten"] == ""
    with open(eintrag["sicherung"], "rb") as f:
        assert f.read() == vorher
    assert _schraeglagen(konfig) == [(2.5, 0)]                 # erledigt

    # Der naechste Lauf hat nichts mehr zu tun
    nachher = scan.read_bytes()
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert scan.read_bytes() == nachher and len(_protokoll(konfig)) == 1


def test_scan_mit_textebene_des_scanprogramms_wird_auch_ausgerichtet(tmp_path):
    """VueScan schreibt eine eigene Textebene: die Seite gilt als Text, gemessen und ausgerichtet wird trotzdem."""
    konfig, ablage = _konfig(tmp_path)
    scan = h.scan_schief(ablage / "1A" / "vuescan.pdf", -1.8, textebene=True)
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert h.ausrichtung_der_datei(scan) == pytest.approx(-1.8, abs=TOLERANZ)
    with pymupdf.open(scan) as d:
        assert "Stadtwerke" in d[0].get_text()                 # die Textebene ist noch da (und dreht mit)
    assert [t["name"] for t in Suchindex(konfig).suche("Stadtwerke")["treffer"]] == ["vuescan.pdf"]


def test_mehrere_seiten_nur_die_schiefen(tmp_path):
    konfig, ablage = _konfig(tmp_path)
    scan = ablage / "1A" / "zwei.pdf"
    doc = pymupdf.open()
    for winkel in (0, 3.0):
        with pymupdf.open(h.scan_schief(tmp_path / f"t{winkel}.pdf", winkel)) as einzeln:
            doc.insert_pdf(einzeln)
    doc.save(str(scan))
    doc.close()
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert h.ausrichtung_der_datei(scan, 1) == 0 and h.ausrichtung_der_datei(scan, 2) == pytest.approx(3.0, abs=0.2)
    assert _protokoll(konfig)[0]["gerade"].startswith("2:")


@pytest.mark.parametrize("stufe, ordner, erwartet", [
    ("aus", "1A", False), ("neue_scans", "Archiv", False), ("alle", "Archiv", True)])
def test_gemessen_wird_nur_wo_die_stufe_gilt(tmp_path, stufe, ordner, erwartet):
    konfig, ablage = _konfig(tmp_path, stufe=stufe)
    scan = h.scan_schief(ablage / ordner / "schief.pdf", 2.0)
    vorher = scan.read_bytes()
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert (scan.read_bytes() != vorher) is erwartet
    assert bool(_schraeglagen(konfig)) is erwartet


def test_vormerkung_beim_einlesen_gilt_auch_nach_dem_wegsortieren(tmp_path):
    """PDFSM liest den Scan im Scan-Ordner (Analyse), der Nutzer sortiert ihn weg, der Lauf richtet ihn dort aus."""
    konfig, ablage = _konfig(tmp_path)
    scan = h.scan_schief(ablage / "1A" / "neu.pdf", 2.0)
    assert Suchindex(konfig).datei_aufnehmen(str(scan)) is not None   # wie PDF-Analyzer und Meldungen der Oberflaeche
    assert _schraeglagen(konfig) == [(2.0, 1)]
    ziel = ablage / "Archiv" / "Stadtwerke 2025.pdf"
    shutil.move(scan, ziel)
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert _ist_gerade(ziel) and _protokoll(konfig)[0]["pfad"] == str(ziel)


@pytest.mark.parametrize("ordner, vorgemerkt", [("1A", [(2.0, 1)]), ("Archiv", [])])
def test_analyse_in_pdfsm_misst_neue_scans(tmp_path, monkeypatch, ordner, vorgemerkt):
    """Liest PDFSM den Scan zuerst (Analyse), misst schon die Analyse; der Indexlauf liest ihn nicht neu ein."""
    from src.core import pdf_analyzer

    konfig, ablage = _konfig(tmp_path)
    scan = h.scan_schief(ablage / ordner / "neu.pdf", 2.0, textebene=True)
    monkeypatch.setattr(pdf_analyzer, "suchindex_fuer_analyse", lambda: Suchindex(konfig))
    with pdf_analyzer.PDFAnalyzer(scan) as a:
        assert "Stadtwerke" in a.extract_text()
    assert _schraeglagen(konfig) == vorgemerkt


def test_rueckgaengig_und_kein_erneutes_ausrichten(tmp_path):
    konfig, ablage = _konfig(tmp_path)
    scan = h.scan_schief(ablage / "1A" / "schief.pdf", 2.0)
    vorher = scan.read_bytes()
    assert Indexer(konfig, synchron=True).lauf() == 0
    ok, meldung = Suchindex(konfig).textebene_rueckgaengig(_protokoll(konfig)[0]["id"])
    assert ok, meldung
    assert scan.read_bytes() == vorher
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert scan.read_bytes() == vorher and len(_protokoll(konfig)) == 1
    # Auch eine Kopie desselben Scans wird nicht ausgerichtet (die Vormerkung haengt am Bild)
    kopie = shutil.copy(scan, ablage / "1A" / "kopie.pdf")
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert h.ausrichtung_der_datei(kopie) == 0


def test_von_hand_ausgerichtet_wird_nicht_doppelt_gedreht(tmp_path):
    from src.core.pdf_rotate import gerade_ausrichten

    konfig, ablage = _konfig(tmp_path)
    scan = h.scan_schief(ablage / "1A" / "schief.pdf", 3.0)
    assert Suchindex(konfig).datei_aufnehmen(str(scan)) is not None   # vorgemerkt ...
    assert gerade_ausrichten(scan)                                     # ... dann von Hand ausgerichtet
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert h.ausrichtung_der_datei(scan) == pytest.approx(3.0, abs=TOLERANZ) and _ist_gerade(scan)
    assert _protokoll(konfig) == [] and _schraeglagen(konfig) == [(3.0, 0)]


def test_textebene_aus_dem_cache_nach_ausrichten_von_hand_wird_neu_erkannt(tmp_path, monkeypatch):
    """Die Analyse hat die Textebene erzeugt, dann wurde die Seite von Hand ausgerichtet: neu erkennen,
    sonst laege die Textebene aus der schiefen Seite um den Winkel verdreht auf der geraden."""
    from src.core.pdf_rotate import gerade_ausrichten

    lagen = h.fake_tesseract_lage(monkeypatch)
    konfig, ablage = _konfig(tmp_path, stufe="aus", ocr_aktiv=True, ocr_tesseract="tesseract-fake", ocr_dpi=72,
                             textebene="neue_scans")
    scan = h.scan_schief(ablage / "1A" / "s.pdf", 2.0, quadrat=True)
    assert Indexer(konfig, synchron=True).lauf(ohne_ocr=True) == 0
    erg = extract.pdf_ocr(str(scan), [1], dict(konfig.ocr_einstellungen(), textebene=True))
    assert Suchindex(konfig).ocr_eintragen(str(scan), erg["texte"], ebenen=erg["ebenen"]) == 1
    assert gerade_ausrichten(scan)
    lagen.clear()
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert lagen                                               # neu erkannt, nicht aus dem Cache
    assert _protokoll(konfig)[0]["seiten"] == "1"
    with pymupdf.open(scan) as d:
        assert extract.hat_ocr_textebene(d[0]) and gerade.ist_ausgerichtet(d, d[0])


def test_drehen_textebene_und_ausrichten_in_einem_schritt(tmp_path, monkeypatch):
    """Kopfstehend und schief (Issue #151 + #165): eine Aenderung, eine Sicherung, ein Protokolleintrag."""
    lagen = h.fake_tesseract_lage(monkeypatch)
    konfig, ablage = _konfig(tmp_path, ocr_aktiv=True, ocr_tesseract="tesseract-fake", ocr_dpi=72,
                             textebene="neue_scans", auto_drehen="neue_scans")
    scan = h.scan_schief(ablage / "1A" / "kopf.pdf", 2.0, inhalt_drehung=180, quadrat=True)
    with pymupdf.open(scan) as d:      # ohne die Textebene des Scanprogramms: Tesseract muss lesen
        assert not d[0].get_text().strip()
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert "kopf" in lagen
    (eintrag,) = _protokoll(konfig)
    assert eintrag["gedreht"] == "1:180" and eintrag["seiten"] == "1" and eintrag["gerade"].startswith("1:")
    with pymupdf.open(scan) as d:
        s = d[0]
        assert s.rotation == 180 and extract.hat_ocr_textebene(s)
        assert h.bild_lage(s.get_pixmap(dpi=40, colorspace=pymupdf.csGRAY).tobytes("png")) == "aufrecht"
    assert _ist_gerade(scan)


def test_pdfa_wird_nicht_automatisch_ausgerichtet(tmp_path, monkeypatch):
    konfig, ablage = _konfig(tmp_path)
    scan = h.scan_schief(ablage / "1A" / "archiv.pdf", 2.0)
    vorher = scan.read_bytes()
    monkeypatch.setattr(textebene, "dokument_grund", lambda doc: "pdfa")
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert scan.read_bytes() == vorher and _protokoll(konfig) == []
    con = db.verbinde(konfig.db_datei)
    try:
        assert con.execute("SELECT textebene_grund FROM dokumente").fetchone()[0] == "pdfa"
    finally:
        con.close()


def test_geaenderte_seite_wird_nicht_mit_altem_winkel_ausgerichtet(tmp_path):
    """Passt das Bild nicht mehr zum gemessenen Hash, schreibt der Lauf nichts (``geaendert``)."""
    konfig, ablage = _konfig(tmp_path)
    scan = h.scan_schief(ablage / "1A" / "schief.pdf", 2.0)
    con = db.verbinde(konfig.db_datei)
    db.init(con)
    res = extract.pdf_text(str(scan), 25, gerade=True)
    res["bild_hashes"][1] = "0" * 32                                    # anderes Bild vorgetaeuscht
    from src.search.indexer import dokument_speichern
    import os
    st = os.stat(scan)
    basis = {"pfad": str(scan), "datei": str(scan), "name": scan.name, "ordner": str(scan.parent), "typ": "pdf",
             "format": "pdf", "groesse": st.st_size, "mtime_ns": st.st_mtime_ns, "datum": st.st_mtime, "prioritaet": 0}
    dok_id, _d, _z = dokument_speichern(con, basis, "pdf", res)
    con.commit()
    d = con.execute("SELECT * FROM dokumente WHERE id = ?", (dok_id,)).fetchone()
    a = textebene.auftrag(con, d, konfig, None)
    con.close()
    assert a["gerade"][1]["hash"] == "0" * 32
    vorher = scan.read_bytes()
    erg = textebene.datei_schreiben(a)
    assert (erg["status"], erg["grund"]) == ("uebersprungen", "geaendert") and scan.read_bytes() == vorher


def test_pruefen_verlangt_genau_den_vorgesehenen_winkel(tmp_path):
    scan = h.scan_schief(tmp_path / "s.pdf", 2.0)
    tmp = tmp_path / "neu.pdf"
    textebene._schreiben_tmp(str(scan), str(tmp), {}, {}, {1: 2.0})
    textebene.pruefen(str(scan), str(tmp), {}, {}, {1: 2.0})
    with pytest.raises(textebene.PruefungFehlgeschlagen, match="Ausrichtung"):
        textebene.pruefen(str(scan), str(tmp), {}, {}, {1: 1.0})
    with pytest.raises(textebene.PruefungFehlgeschlagen, match="Ausrichtung"):
        textebene.pruefen(str(scan), str(tmp), {}, {}, {})


# --------------------------------------------------------------------------- Einstellungen, Schema, Anzeige

def test_einstellung_auto_gerade(tmp_path):
    assert SearchConfig().auto_gerade == "neue_scans"
    assert SearchConfig(auto_gerade="quatsch").auto_gerade == "aus"
    k = SearchConfig(prioritaet=[str(tmp_path / "1A")], auto_gerade="neue_scans")
    assert k.gerade_vormerken(str(tmp_path / "1A" / "a.pdf"))
    assert not k.gerade_vormerken(str(tmp_path / "Archiv" / "a.pdf"))
    assert SearchConfig(auto_gerade="alle").gerade_vormerken(str(tmp_path / "x.pdf"))


def test_schema_bekommt_tabelle_und_spalte(tmp_path):
    con = db.verbinde(tmp_path / "suche.db")
    db.init(con)
    con.execute("DROP TABLE schraeglage")                   # Stand vor Issue #165 nachbauen
    con.execute("ALTER TABLE textebene_protokoll DROP COLUMN gerade")
    con.commit()
    assert db.schema_stand(con) == 1
    assert db.ergaenze_schema(con) is True and db.schema_stand(con) == 2
    assert {"bild_hash", "winkel", "gerade"} <= db._spalten(con, "schraeglage")
    assert "gerade" in db._spalten(con, "textebene_protokoll")
    plan = " ".join(str(tuple(r)) for r in con.execute(
        "EXPLAIN QUERY PLAN SELECT bild_hash FROM schraeglage g WHERE g.gerade = 1"))
    assert "ix_schraeglage_gerade" in plan
    con.close()


def test_protokoll_und_status_zeigen_die_ausrichtung(tmp_path):
    from src.gui.textebene_dialog import gedreht_text
    from src.search import ausgabe

    assert textebene.gerade_text({2: -1.754, 1: 0.8}) == "1:0.80,2:-1.75"
    assert gedreht_text(None, "2:-1.75") == "S. 2: 1,8° gerade"
    assert gedreht_text("1:180", "1:0.80") == "S. 1: 180°, S. 1: 0,8° gerade"

    konfig, ablage = _konfig(tmp_path)
    h.scan_schief(ablage / "1A" / "schief.pdf", 2.0)
    assert Indexer(konfig, synchron=True).lauf() == 0
    idx = Suchindex(konfig)
    assert "Schiefe Scans gerade ausgerichtet (neue_scans): 1 PDFs" in ausgabe.status_text(idx)


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
    assert dlg.search_deskew_combo.currentData() == "neue_scans"
    dlg.search_deskew_combo.setCurrentIndex(dlg.search_deskew_combo.findData("aus"))
    dlg._save_settings()
    assert cfg.get_search_config().auto_gerade == "aus"
    dlg2 = SettingsDialog()
    qtbot.addWidget(dlg2)
    assert dlg2.search_deskew_combo.currentData() == "aus"

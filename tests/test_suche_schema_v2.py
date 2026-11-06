"""Schema-Version 2 der Dokumentensuche (Phase 5 der PDFsuche-Integration).

Additive Ergaenzung einer Version-1-Datenbank in-place (Erkennung an der
Struktur, idempotent), Metadaten aus der PDF (Quelle ``pdf``) mit Vorrang fuer
Werte von PDFSM (``pdfsm``), Metadatenfilter und Treffer in den Metadaten,
Aufraeumregel fuer PDFSM-verwaltete Dokumente, OCR-Cache nach Bildinhalt
(Tesseract-Attrappe zaehlt Aufrufe ueber Umbenennen, XMP-Schreiben, Stapeln
und Kopieren) und das Auffuellen des Caches fuer den Altbestand.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

from src.core.file_manager import FileManager
from src.core.pdf_metadata import PDFMetadata, write_metadata
from src.search import db, extract
from src.search.indexer import Indexer
from src.search.suchindex import Suchindex
from tests import helfer_suche as h


def _v1_db(pfad) -> int:
    """Datenbank im Stand von PDFsuche (Version 1) mit einem OCR-Dokument anlegen."""
    con = db.verbinde(pfad)
    con.executescript(db.SCHEMA)
    con.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', '1')")
    cur = con.execute(
        "INSERT INTO dokumente (pfad, datei, name, ordner, typ, format, groesse, mtime_ns, datum, seiten, "
        "textstatus, ocr_seiten, prioritaet, indiziert_am) VALUES (?, ?, ?, ?, 'pdf', 'pdf', 10, 1, 1.0, 1, "
        "'ocr', 1, 9, '2026-01-01T00:00:00')",
        (os.path.join("alt", "a.pdf"), os.path.join("alt", "a.pdf"), "a.pdf", "alt"))
    dok_id = cur.lastrowid
    con.execute("INSERT INTO seiten (dok_id, seite, quelle, text) VALUES (?, 1, 'ocr', 'Alter OCR-Text')", (dok_id,))
    con.commit()
    con.close()
    return dok_id


def _statistik(konfig) -> dict:
    con = db.verbinde(konfig.db_datei, nur_lesen=True)
    try:
        return json.loads(con.execute("SELECT statistik FROM laeufe ORDER BY id DESC LIMIT 1").fetchone()[0])
    finally:
        con.close()


def _tesseract_attrappe(monkeypatch) -> list:
    aufrufe = []

    def fake_run(args, **kw):
        aufrufe.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=b"Erkannter Scantext", stderr=b"")

    monkeypatch.setattr(extract.subprocess, "run", fake_run)
    return aufrufe


# --------------------------------------------------------------------------- Schema

def test_version_1_wird_additiv_ergaenzt_und_an_der_struktur_erkannt(tmp_path):
    pfad = tmp_path / "suche.db"
    dok_id = _v1_db(pfad)
    con = db.verbinde(pfad)
    try:
        assert db.schema_stand(con) == 1
        assert db.ergaenze_schema(con) is True
        assert db.schema_stand(con) == 2 and db.lies_meta(con, "schema_version") == "2"
        spalten = {r[1] for r in con.execute("PRAGMA table_info(dokumente)")}
        assert set(db.V2_SPALTEN) <= spalten
        # Daten unversehrt, Volltext weiter auffindbar
        assert db.volltext(con, dok_id) == "Alter OCR-Text"
        assert db.suche(con, "OCR-Text")["gesamt"] == 1
        # Das alte PDFsuche setzt die Version zurueck: die Struktur zaehlt, erneut ergaenzen ist harmlos
        db.setze_meta(con, "schema_version", "1")
        con.commit()
        assert db.schema_stand(con) == 2
        assert db.ergaenze_schema(con) is True and db.lies_meta(con, "schema_version") == "2"
        assert db.ergaenze_schema(con) is False

        # Metadaten setzen: Filter, Werte und Treffer in den Metadaten (metadaten_fts)
        assert db.metadaten_setzen(con, dok_id, {"korrespondent": "Telekom", "kategorie": "Rechnung",
                                                 "steuerjahr": "2024", "betrag": "59,99 EUR"})
        con.commit()
        erg = db.suche(con, "Telekom")
        assert erg["gesamt"] == 1 and erg["treffer"][0]["im_metadaten"] and erg["treffer"][0]["betrag"] == 59.99
        assert db.suche(con, "", steuerjahr="2024")["gesamt"] == 1
        assert db.suche(con, "", steuerjahr="2023")["gesamt"] == 0
        assert db.suche(con, "", betrag_von=50, betrag_bis=60)["gesamt"] == 1
        assert db.suche(con, "", betrag_von=60)["gesamt"] == 0
        assert db.suche(con, "OCR-Text", kategorie="Rechnung")["gesamt"] == 1
        assert db.werte(con, "steuerjahr", absteigend=True) == ["2024"]
        assert db.top_werte(con, "kategorie") == ["Rechnung"]
        # Nur pdf_id nachtragen beansprucht keinen Vorrang
        db.metadaten_setzen(con, dok_id, {}, pdf_id="abc", quelle="pdfsm")
        r = con.execute("SELECT pdf_id, metadaten_quelle FROM dokumente WHERE id = ?", (dok_id,)).fetchone()
        assert r[0] == "abc" and r[1] == "pdfsm"
        assert db.metadaten_ersetzen(con, "korrespondent", "Telekom", "Telekom AG") == 1
        assert db.suche(con, "", korrespondent="Telekom AG")["gesamt"] == 1
    finally:
        con.close()


def test_neue_datenbank_entsteht_mit_version_2(tmp_path):
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(tmp_path / "leer")])
    (tmp_path / "leer").mkdir()
    assert Indexer(konfig, synchron=True).lauf() == 0
    con = db.verbinde(konfig.db_datei, nur_lesen=True)
    try:
        assert db.schema_stand(con) == 2 and db.status(con)["schema_version"] == "2"
    finally:
        con.close()


# --------------------------------------------------------------------------- Metadaten aus der PDF, Vorrang

def test_metadaten_aus_der_pdf_und_vorrang_von_pdfsm(tmp_path):
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    pdf = h.pdf_mit_text(ablage / "rechnung.pdf", ["Rechnung Telekom 59,99 Euro"])
    assert write_metadata(pdf, PDFMetadata(
        subject="Rechnung", description="Telefonrechnung Januar", keywords="telefon, rechnung",
        korrespondent="Telekom", buchungsdatum="2024-01-15", steuerjahr="2024", betrag_brutto="59.99",
    ))
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    assert Indexer(konfig, synchron=True).lauf() == 0
    idx = Suchindex(konfig)
    d = idx.dokument_nach_pfad(str(pdf))
    assert d["metadaten_quelle"] == "pdf"
    assert d["korrespondent"] == "Telekom" and d["kategorie"] == "Rechnung" and d["steuerjahr"] == "2024"
    assert d["betrag"] == 59.99 and d["buchungsdatum"] == "2024-01-15"
    assert d["zusammenfassung"] == "Telefonrechnung Januar" and d["schlagwoerter"] == "telefon, rechnung"
    assert idx.suche("Telefonrechnung")["gesamt"] == 1          # Treffer in den Metadaten
    assert idx.suche("", kategorie="Rechnung")["gesamt"] == 1    # reine Filterabfrage

    # PDFSM setzt einen anderen Korrespondenten (z. B. nach einem Merge): Vorrang vor der Datei
    assert idx.metadaten_setzen(str(pdf), {"korrespondent": "Deutsche Telekom"}, pdf_id="abc")
    assert write_metadata(pdf, PDFMetadata(korrespondent="Telekom", steuerjahr="2025"))
    assert Indexer(konfig, synchron=True).lauf() == 0
    d = idx.dokument_nach_pfad(str(pdf))
    assert d["metadaten_quelle"] == "pdfsm" and d["pdf_id"] == "abc"
    assert d["korrespondent"] == "Deutsche Telekom" and d["steuerjahr"] == "2024"
    assert d["textstatus"] == "text"   # die Datei wurde neu gelesen (Groesse/mtime geaendert)
    assert idx.metadaten_ersetzen("korrespondent", "Deutsche Telekom", "Telekom AG") == 1
    assert idx.werte("korrespondent") == ["Telekom AG"]
    assert idx.suche("", korrespondent="Telekom AG")["treffer"][0]["name"] == "rechnung.pdf"


def test_aufraeumen_behaelt_pdfsm_verwaltete_dokumente(tmp_path):
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    woanders = tmp_path / "Woanders"
    woanders.mkdir()
    h.pdf_mit_text(ablage / "a.pdf", ["Im Zielordner"])
    fremd = h.pdf_mit_text(woanders / "b.pdf", ["Von PDFSM sortiert, ausserhalb der Wurzeln"])
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    idx = Suchindex(konfig)
    assert idx.metadaten_setzen(str(fremd), {"kategorie": "Vertrag"}, pdf_id="f1")
    assert idx.dokument_nach_pfad(str(fremd))["textstatus"] == "text"   # sofort gelesen
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert idx.dokument_nach_pfad(str(fremd))["kategorie"] == "Vertrag"   # bleibt trotz Aufraeumen ausserhalb
    fremd.unlink()
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert idx.dokument_nach_pfad(str(fremd)) is None   # Datei weg -> Eintrag weg


# --------------------------------------------------------------------------- OCR-Cache nach Bildinhalt

def test_ocr_cache_ueberlebt_umbenennen_xmp_stapeln_und_kopieren(tmp_path, monkeypatch):
    scans = tmp_path / "Scans"
    scans.mkdir()
    scan = h.pdf_mit_bild(scans / "scan.pdf", seiten=2)
    aufrufe = _tesseract_attrappe(monkeypatch)
    konfig = h.konfig_fuer(tmp_path, prioritaet=[str(scans)], ocr_aktiv=True, ocr_tesseract="tesseract-fake")
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert len(aufrufe) == 2
    idx = Suchindex(konfig)
    con = db.verbinde(konfig.db_datei, nur_lesen=True)
    try:
        assert con.execute("SELECT count(*) FROM ocr_cache").fetchone()[0] >= 1
        assert con.execute("SELECT count(*) FROM seiten WHERE bild_hash IS NOT NULL").fetchone()[0] == 2
    finally:
        con.close()

    # 1) Umbenannt ohne Meldung an den Index: Signatur passt noch (Groesse, mtime) -> uebernommen
    umbenannt = scans / "umbenannt.pdf"
    os.rename(scan, umbenannt)
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert len(aufrufe) == 2 and _statistik(konfig)["verschoben"] == 1

    # 2) XMP-Metadaten geschrieben (Datei neu geschrieben): Text aus dem Cache, kein Tesseract
    assert write_metadata(umbenannt, PDFMetadata(korrespondent="Scanner GmbH", steuerjahr="2024"))
    assert Indexer(konfig, synchron=True).lauf() == 0
    stat = _statistik(konfig)
    assert len(aufrufe) == 2 and stat["ocr_cache"] == 2 and stat.get("ocr_seiten", 0) == 0
    d = idx.dokument_nach_pfad(str(umbenannt))
    assert d["textstatus"] == "ocr" and d["ocr_seiten"] == 2 and d["korrespondent"] == "Scanner GmbH"
    assert idx.suche("Scantext")["gesamt"] == 1

    # 3) Gestapelt (Ziel neu geschrieben, Quelle aufgegangen) und 4) kopiert: alles aus dem Cache
    anlage = h.pdf_mit_bild(scans / "anlage.pdf", seiten=1)
    FileManager().stack_pdfs(umbenannt, [anlage], tmp_path / "sicherung")
    shutil.copy2(umbenannt, scans / "kopie.pdf")
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert len(aufrufe) == 2
    d = idx.dokument_nach_pfad(str(umbenannt))
    assert d["seiten"] == 3 and d["textstatus"] == "ocr" and d["ocr_seiten"] == 3
    assert idx.dokument_nach_pfad(str(scans / "kopie.pdf"))["textstatus"] == "ocr"
    assert idx.dokument_nach_pfad(str(anlage)) is None

    # 5) Meldung der Oberflaeche: datei_geaendert liest sofort, OCR aus dem Cache
    assert write_metadata(umbenannt, PDFMetadata(subject="Scan"))
    assert idx.datei_geaendert(str(umbenannt)) is not None
    d = idx.dokument_nach_pfad(str(umbenannt))
    assert d["textstatus"] == "ocr" and d["ocr_seiten"] == 3 and len(aufrufe) == 2


def test_ocr_eintragen_der_oberflaeche_fuellt_cache_und_status(tmp_path, monkeypatch):
    scans = tmp_path / "Scans"
    scans.mkdir()
    scan = h.pdf_mit_bild(scans / "scan.pdf", seiten=2, text_seiten=["Deckblatt"])
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(scans)], ocr_aktiv=True, ocr_tesseract="tesseract-fake")
    aufrufe = _tesseract_attrappe(monkeypatch)
    assert Indexer(konfig, synchron=True).lauf(ohne_ocr=True) == 0
    idx = Suchindex(konfig)
    assert idx.dokument_nach_pfad(str(scan))["textstatus"] == "ocr_ausstehend"
    # Die Oberflaeche hat Seite 2 selbst erkannt; Seite 3 zeigt dasselbe Bild und kommt aus dem Cache
    assert idx.ocr_eintragen(str(scan), {2: "Text der Oberflaeche"}) == 1
    d = idx.dokument_nach_pfad(str(scan))
    assert d["textstatus"] == "ocr" and d["ocr_seiten"] == 2
    stand = idx.text_fuer_datei(str(scan))
    assert stand["ocr_offen"] == [] and "Text der Oberflaeche" in stand["text"]
    assert stand["seiten"][2][2] == "Text der Oberflaeche"
    # Der Lauf hat nichts mehr zu erkennen, Tesseract wird nie gerufen
    assert Indexer(konfig, synchron=True).lauf() == 0
    d = idx.dokument_nach_pfad(str(scan))
    assert d["textstatus"] == "ocr" and d["ocr_seiten"] == 2 and len(aufrufe) == 0


def test_ocr_cache_wird_fuer_den_altbestand_ergaenzt(tmp_path, monkeypatch):
    scans = tmp_path / "Scans"
    scans.mkdir()
    scan = h.pdf_mit_bild(scans / "scan.pdf", seiten=1)
    aufrufe = _tesseract_attrappe(monkeypatch)
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(scans)], ocr_aktiv=True, ocr_tesseract="tesseract-fake")
    assert Indexer(konfig, synchron=True).lauf() == 0 and len(aufrufe) == 1
    # Altbestand nachstellen: OCR-Seite ohne Hash, leerer Cache
    con = db.verbinde(konfig.db_datei)
    con.execute("UPDATE seiten SET bild_hash = NULL")
    con.execute("DELETE FROM ocr_cache")
    con.commit()
    con.close()
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert _statistik(konfig)["ocr_cache_ergaenzt"] == 1
    con = db.verbinde(konfig.db_datei, nur_lesen=True)
    try:
        assert con.execute("SELECT count(*) FROM ocr_cache").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM seiten WHERE bild_hash IS NULL").fetchone()[0] == 0
    finally:
        con.close()
    # Eine Kopie des alten Scans braucht jetzt kein Tesseract mehr
    shutil.copy2(scan, scans / "kopie.pdf")
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert len(aufrufe) == 1 and Suchindex(konfig).dokument_nach_pfad(str(scans / "kopie.pdf"))["textstatus"] == "ocr"

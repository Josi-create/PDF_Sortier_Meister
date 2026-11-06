"""Dokumentensuche: Indexierungslauf in tmp_path (neu, geaendert, unveraendert, verschoben, kopiert,
geloescht, Cloud-Platzhalter, OCR mit Tesseract-Attrappe, Mails, Sperre, Zeitlimit, Absturz)."""

import os
import shutil
import subprocess
import time

import pytest

import helfer_suche as h
from src.search import db, extract, indexer, mbox
from src.search.indexer import Auftrag, Indexer


@pytest.fixture
def ablage(tmp_path):
    ordner = tmp_path / "Ablage"
    (ordner / "Unterordner").mkdir(parents=True)
    (ordner / "Rechnung.md").write_text("# Rechnung\nBetrag 49,99 Euro von Telekom", encoding="utf-8")
    (ordner / "Unterordner" / "Notiz.md").write_text("Müller und die Bäume", encoding="utf-8")
    h.pdf_mit_text(ordner / "Brief.pdf", ["Sehr geehrte Frau Beispiel"])
    h.docx(ordner / "Vertrag.docx", ["Mietvertrag über Wohnung"])
    return ordner


def _lauf(konfig, **kw):
    ix = Indexer(konfig, synchron=True)
    assert ix.lauf(**kw) == 0
    return ix.stat


def _lesen(konfig):
    con = db.verbinde(konfig.db_datei, nur_lesen=True)
    try:
        yield con
    finally:
        con.close()


def _con(konfig):
    return db.verbinde(konfig.db_datei, nur_lesen=True)


def test_neu_dann_unveraendert(tmp_path, ablage):
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    stat = _lauf(konfig)
    assert stat["neu"] == 4 and stat["gelesen"] == 4 and stat["fehler"] == 0
    con = _con(konfig)
    try:
        assert db.suche(con, "Telekom")["gesamt"] == 1
        assert db.suche(con, "Mietvertrag")["treffer"][0]["typ"] == "office"
        assert db.suche(con, "Muller")["treffer"][0]["name"] == "Notiz.md"
        lauf = db.status(con)["laeufe"][0]
        assert lauf["status"] == "fertig" and lauf["statistik"]["gelesen"] == 4
    finally:
        con.close()
    stat2 = _lauf(konfig)
    assert stat2["unveraendert"] == 4 and stat2["gelesen"] == 0


def test_geaendert_wird_neu_gelesen(tmp_path, ablage):
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    _lauf(konfig)
    datei = ablage / "Rechnung.md"
    datei.write_text("# Rechnung\nJetzt mit Mahnung", encoding="utf-8")
    t = time.time() + 10
    os.utime(datei, (t, t))
    stat = _lauf(konfig)
    assert stat["geaendert"] == 1 and stat["unveraendert"] == 3
    con = _con(konfig)
    try:
        assert db.suche(con, "Mahnung")["gesamt"] == 1 and db.suche(con, "Telekom")["gesamt"] == 0
        assert con.execute("SELECT count(*) FROM dokumente").fetchone()[0] == 4
    finally:
        con.close()


def test_verschoben_behaelt_text_und_ocr(tmp_path, ablage):
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    _lauf(konfig)
    # OCR-Ergebnis simulieren, das beim Neulesen verloren ginge
    con = db.verbinde(konfig.db_datei)
    alt_id = con.execute("SELECT id FROM dokumente WHERE name = 'Brief.pdf'").fetchone()[0]
    con.execute("UPDATE seiten SET text = 'OCRTEXT', quelle = 'ocr' WHERE dok_id = ?", (alt_id,))
    con.execute("UPDATE dokumente SET textstatus = 'ocr', ocr_seiten = 1 WHERE id = ?", (alt_id,))
    con.commit()
    con.close()

    shutil.move(str(ablage / "Brief.pdf"), str(ablage / "Unterordner" / "Brief.pdf"))
    stat = _lauf(konfig)
    assert stat["verschoben"] == 1 and stat["gelesen"] == 0 and stat["entfernt"] == 0
    con = _con(konfig)
    try:
        d = db.dokument(con, alt_id)
        assert d["pfad"] == str(ablage / "Unterordner" / "Brief.pdf") and d["textstatus"] == "ocr"
        assert db.volltext(con, alt_id) == "OCRTEXT"
        assert con.execute("SELECT count(*) FROM dokumente").fetchone()[0] == 4
    finally:
        con.close()


def test_kopiert_uebernimmt_text(tmp_path, ablage):
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    _lauf(konfig)
    shutil.copy2(str(ablage / "Brief.pdf"), str(ablage / "Unterordner" / "Brief.pdf"))
    stat = _lauf(konfig)
    assert stat["kopie"] == 1 and stat["gelesen"] == 0
    con = _con(konfig)
    try:
        assert con.execute("SELECT count(*) FROM dokumente WHERE name = 'Brief.pdf'").fetchone()[0] == 2
        assert db.suche(con, "Beispiel")["gesamt"] == 2
    finally:
        con.close()


def test_geloescht_nur_bei_vollstaendigem_durchlauf(tmp_path, ablage):
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    _lauf(konfig)
    (ablage / "Rechnung.md").unlink()
    stat = _lauf(konfig)
    assert stat["entfernt"] == 1
    con = _con(konfig)
    try:
        assert con.execute("SELECT count(*) FROM dokumente").fetchone()[0] == 3
    finally:
        con.close()
    # Wurzel nicht erreichbar: nichts wird entfernt
    shutil.rmtree(ablage)
    stat = _lauf(konfig)
    assert stat["entfernt"] == 0
    con = _con(konfig)
    try:
        assert con.execute("SELECT count(*) FROM dokumente").fetchone()[0] == 3
    finally:
        con.close()


def test_nur_pfad_und_ausschluesse(tmp_path, ablage):
    (ablage / "node_modules").mkdir()
    (ablage / "node_modules" / "paket.md").write_text("ignorieren", encoding="utf-8")
    (ablage / "~$Vertrag.docx").write_bytes(b"sperrdatei")
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(tmp_path / "woanders")],
                           pfade_ausschliessen=[str(ablage / "Unterordner")])
    stat = _lauf(konfig, nur_pfad=str(ablage))
    assert stat["gelesen"] == 3 and stat["neu"] == 3
    con = _con(konfig)
    try:
        namen = {r[0] for r in con.execute("SELECT name FROM dokumente")}
        assert namen == {"Rechnung.md", "Brief.pdf", "Vertrag.docx"}
    finally:
        con.close()


def test_cloud_platzhalter_nur_mit_namen(tmp_path, ablage, monkeypatch):
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    monkeypatch.setattr(indexer, "_nur_cloud", lambda st: True)
    stat = _lauf(konfig)
    assert stat["cloud"] == 4 and stat["gelesen"] == 0
    con = _con(konfig)
    try:
        assert {r[0] for r in con.execute("SELECT textstatus FROM dokumente")} == {"cloud"}
        assert db.suche(con, "Telekom")["gesamt"] == 0
        assert db.suche(con, "Rechnung")["treffer"][0]["im_namen"] is True
    finally:
        con.close()
    # Herunterladen erlaubt: jetzt wird gelesen, auch wenn Groesse/mtime gleich sind
    konfig.cloud_herunterladen = True
    stat = _lauf(konfig)
    assert stat["gelesen"] == 4


def test_zu_grosse_dateien_nur_mit_namen(tmp_path, ablage):
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], max_dateigroesse_mb=0)
    stat = _lauf(konfig)
    assert stat["zu_gross"] == 4


def test_ocr_im_vorrangordner_mit_tesseract_attrappe(tmp_path, monkeypatch):
    scans = tmp_path / "Scans"
    scans.mkdir()
    h.pdf_mit_bild(scans / "scan.pdf", seiten=2, text_seiten=["Deckblatt"])
    aufrufe = []

    def fake_run(args, **kw):
        aufrufe.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=b"Erkannter Scantext", stderr=b"")

    monkeypatch.setattr(extract.subprocess, "run", fake_run)
    konfig = h.konfig_fuer(tmp_path, prioritaet=[str(scans)], ocr_aktiv=True, ocr_tesseract="tesseract-fake")
    stat = _lauf(konfig)
    assert stat["ocr_vorgemerkt"] == 1 and stat["ocr_seiten"] == 2 and len(aufrufe) == 2
    con = _con(konfig)
    try:
        d = db.dokument_nach_pfad(con, str(scans / "scan.pdf"))
        assert d["textstatus"] == "ocr" and d["ocr_seiten"] == 2 and d["prioritaet"] == 0
        assert [r[0] for r in con.execute("SELECT quelle FROM seiten WHERE dok_id = ? ORDER BY seite", (d["id"],))] == ["text", "ocr", "ocr"]
        assert db.suche(con, "Scantext")["treffer"][0]["stellen"][0]["seite"] == 2
    finally:
        con.close()
    # Zweiter Lauf: nichts zu erkennen, Tesseract wird nicht erneut aufgerufen
    stat = _lauf(konfig)
    assert stat["unveraendert"] == 1 and len(aufrufe) == 2


def test_ocr_ohne_tesseract_bleibt_ausstehend(tmp_path, monkeypatch):
    scans = tmp_path / "Scans"
    scans.mkdir()
    h.pdf_mit_bild(scans / "scan.pdf")
    monkeypatch.setattr("src.utils.tesseract.find_tesseract", lambda: None)
    monkeypatch.setattr("src.utils.tesseract.shutil.which", lambda name: None)
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(scans)], ocr_aktiv=True, ocr_tesseract="")
    assert konfig.ocr_einstellungen()["aktiv"] is False
    _lauf(konfig)
    con = _con(konfig)
    try:
        assert db.dokument_nach_pfad(con, str(scans / "scan.pdf"))["textstatus"] == "ocr_ausstehend"
    finally:
        con.close()


def test_ocr_fehler_markiert_seiten(tmp_path, monkeypatch):
    scans = tmp_path / "Scans"
    scans.mkdir()
    h.pdf_mit_bild(scans / "scan.pdf", seiten=2)
    monkeypatch.setattr(extract.subprocess, "run",
                        lambda args, **kw: subprocess.CompletedProcess(args, 1, stdout=b"", stderr=b"Fehler"))
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(scans)], ocr_aktiv=True, ocr_tesseract="tesseract-fake")
    _lauf(konfig)
    con = _con(konfig)
    try:
        d = db.dokument_nach_pfad(con, str(scans / "scan.pdf"))
        assert d["textstatus"] == "ocr_teilweise" and "Fehler" in d["fehler"]
        assert {r[0] for r in con.execute("SELECT quelle FROM seiten WHERE dok_id = ?", (d["id"],))} == {"ocr_fehler"}
    finally:
        con.close()


def test_mails_neu_und_nur_angehaengte(tmp_path):
    konto = tmp_path / "Mail" / "pop.example.invalid"
    konto.mkdir(parents=True)
    p = h.mbox(konto / "Inbox", [h.mail_roh("Erste Mail", text="Inhalt eins", mozilla_status="0000"),
                                 h.mail_roh("Geloescht", text="weg", mozilla_status="0008")])
    konfig = h.konfig_fuer(tmp_path, mails_aktiv=True, mail_ordner=[str(tmp_path / "Mail")])
    stat = _lauf(konfig)
    assert stat["mails"] == 1
    con = _con(konfig)
    try:
        erg = db.suche(con, "eins", typ="mail")
        assert erg["gesamt"] == 1 and erg["treffer"][0]["ordner"] == "Thunderbird/pop.example.invalid/Inbox"
        assert erg["treffer"][0]["mail_betreff"] == "Erste Mail" and erg["treffer"][0]["format"] == "mbox"
        assert db.suche(con, "weg")["gesamt"] == 0
    finally:
        con.close()
    # unveraenderte mbox wird uebersprungen
    assert _lauf(konfig)["mails"] == 0
    # angehaengte Mail: nur sie wird gelesen
    with open(p, "ab") as f:
        f.write(b"From - Thu Jan 11 10:00:00 2024\n" + h.mail_roh("Zweite Mail", text="Inhalt zwei", mozilla_status="0000") + b"\n")
    stat = _lauf(konfig)
    assert stat["mails"] == 1
    con = _con(konfig)
    try:
        assert con.execute("SELECT count(*) FROM dokumente WHERE format = 'mbox'").fetchone()[0] == 2
    finally:
        con.close()
    # Postfach verschwindet: Mails werden entfernt
    p.unlink()
    (konto / "Inbox.msf").unlink()
    stat = _lauf(konfig)
    assert stat["entfernt"] == 2


def test_sperre_verhindert_zweiten_lauf(tmp_path, ablage):
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    assert indexer.laeuft_gerade(konfig) is False
    assert indexer.sperre_holen(konfig) is True
    try:
        assert indexer.laeuft_gerade(konfig) is True
        assert Indexer(konfig, synchron=True).lauf() == 2
    finally:
        indexer.sperre_freigeben()
    assert indexer.laeuft_gerade(konfig) is False
    assert Indexer(konfig, synchron=True).lauf() == 0


def test_zeitlimit_bricht_lauf_ab(tmp_path, ablage):
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    ix = Indexer(konfig, synchron=True, max_minuten=0.0001)
    time.sleep(0.02)
    assert ix.lauf() == 1
    con = _con(konfig)
    try:
        assert db.status(con)["laeufe"][0]["status"] == "abgebrochen"
    finally:
        con.close()


def test_fehlerhafte_datei_landet_mit_status_fehler(tmp_path, ablage):
    (ablage / "kaputt.pdf").write_bytes(b"kein pdf")
    (ablage / "leer.pdf").write_bytes(b"")
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    stat = _lauf(konfig)
    assert stat["fehler"] == 1 and stat["leer"] == 1
    con = _con(konfig)
    try:
        d = db.dokument_nach_pfad(con, str(ablage / "kaputt.pdf"))
        assert d["textstatus"] == "fehler"
        # kurzer Fehlertext ohne den Pfad (der steht schon in der Zeile)
        assert d["fehler"] and str(ablage) not in d["fehler"] and "\n" not in d["fehler"]
        assert db.dokument_nach_pfad(con, str(ablage / "leer.pdf"))["textstatus"] == "leer"
    finally:
        con.close()


def test_leere_dateien_sind_leer_statt_fehler(tmp_path, ablage):
    namen = ["leer.pdf", "leer.docx", "leer.md", "leer.eml", "leer.msg"]
    for name in namen:
        (ablage / name).write_bytes(b"")
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    stat = _lauf(konfig)
    assert stat["leer"] == len(namen) and stat["fehler"] == 0
    con = _con(konfig)
    try:
        rows = con.execute("SELECT textstatus, fehler FROM dokumente WHERE name LIKE 'leer.%'").fetchall()
        assert len(rows) == len(namen)
        assert all(r["textstatus"] == "leer" and r["fehler"] is None for r in rows)
    finally:
        con.close()


def test_msg_fremdformat_wird_leer(tmp_path, ablage):
    (ablage / "de.msg").write_bytes(b"# Tcl message catalog\n::msgcat::mcset de \"Open\" \"Oeffnen\"\n")
    (ablage / "text.msg").write_bytes(h.mail_roh("Textmail", text="als msg gespeichert"))
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    stat = _lauf(konfig)
    assert stat["fehler"] == 0
    con = _con(konfig)
    try:
        d = db.dokument_nach_pfad(con, str(ablage / "de.msg"))
        assert d["textstatus"] == "leer" and "kein Outlook-Format" in d["fehler"]
        assert db.suche(con, "gespeichert", typ="mail")["treffer"][0]["mail_betreff"] == "Textmail"
    finally:
        con.close()


def test_aufraeumen_ausserhalb_der_wurzeln(tmp_path, ablage):
    andere = tmp_path / "Andere"
    andere.mkdir()
    (andere / "Notiz.md").write_text("woanders", encoding="utf-8")
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    assert _lauf(konfig)["gelesen"] == 4
    # Konfiguration zeigt jetzt nur noch auf den anderen Ordner
    konfig2 = h.konfig_fuer(tmp_path, wurzeln=[str(andere)])
    stat = _lauf(konfig2, nur_prioritaet=True)       # kein vollstaendiger Lauf: nichts entfernen
    assert stat["entfernt"] == 0
    stat = _lauf(konfig2)
    assert stat["gelesen"] == 1 and stat["entfernt"] == 4
    con = _con(konfig2)
    try:
        assert [r[0] for r in con.execute("SELECT name FROM dokumente")] == ["Notiz.md"]
    finally:
        con.close()
    # ohne konfigurierte Ordner wird nichts geloescht
    assert _lauf(h.konfig_fuer(tmp_path, wurzeln=[]))["entfernt"] == 0


def test_mbox_zwischenstand_bei_abbruch(tmp_path, monkeypatch):
    konto = tmp_path / "Mail" / "pop.example.invalid"
    konto.mkdir(parents=True)
    mails = [h.mail_roh(f"Mail {i}", text=f"Inhalt {i}", mozilla_status="0000") for i in range(1, 8)]
    p = h.mbox(konto / "Inbox", mails)
    konfig = h.konfig_fuer(tmp_path, mails_aktiv=True, mail_ordner=[str(tmp_path / "Mail")])
    monkeypatch.setattr(indexer, "MBOX_STAPEL_MAILS", 1)      # jede Mail ein Stapel
    monkeypatch.setattr(Indexer, "MBOX_STAND_INTERVALL_S", 0)  # jeden Zwischenstand sichern

    # Abbruch, sobald drei Mails gespeichert sind (Zeitlimit-Pruefung beim Einreichen)
    schalter = {"aktiv": True}
    original = Indexer._zeit_pruefen

    def pruefen(self):
        if schalter["aktiv"] and self.stat["mails"] >= 3:
            raise indexer.Abbruch("Test-Abbruch")
        original(self)

    monkeypatch.setattr(Indexer, "_zeit_pruefen", pruefen)
    ix = Indexer(konfig, synchron=True)
    assert ix.lauf() == 1 and ix.stat["mails"] == 3
    offsets = [off for off, _, _ in mbox.mails(str(p))]
    con = _con(konfig)
    try:
        stand = con.execute("SELECT groesse FROM mbox_stand").fetchone()[0]
        assert stand == offsets[3]                     # bis vor die vierte Mail gelesen
        assert con.execute("SELECT count(*) FROM dokumente WHERE format = 'mbox'").fetchone()[0] == 3
    finally:
        con.close()

    # Naechster Lauf setzt beim Zwischenstand fort: nur die restlichen vier Mails, keine Doppelten
    schalter["aktiv"] = False
    stat = _lauf(konfig)
    assert stat["mails"] == 4
    con = _con(konfig)
    try:
        assert con.execute("SELECT count(*) FROM dokumente WHERE format = 'mbox'").fetchone()[0] == 7
        assert con.execute("SELECT groesse FROM mbox_stand").fetchone()[0] == p.stat().st_size
        assert db.suche(con, "Inhalt 7", typ="mail")["gesamt"] == 1
    finally:
        con.close()


# --------------------------------------------------------------------------- echte Arbeitsprozesse

def _basis(pfad):
    st = os.stat(pfad)
    return {"pfad": str(pfad), "datei": str(pfad), "name": pfad.name, "ordner": str(pfad.parent), "typ": "md",
            "format": "md", "groesse": st.st_size, "mtime_ns": st.st_mtime_ns, "datum": st.st_mtime, "prioritaet": 9}


def test_absturz_eines_arbeitsprozesses_wird_der_datei_zugeschrieben(tmp_path):
    pfad = tmp_path / "boese.md"
    pfad.write_text("x", encoding="utf-8")
    konfig = h.konfig_fuer(tmp_path)
    ix = Indexer(konfig)
    try:
        ix._einreichen(Auftrag("datei", h.absturz, (str(pfad),), {"pfad": str(pfad), "basis": _basis(pfad)}, zeitlimit=60))
        ix._abarbeiten()
        ix.con.commit()
        status, fehler = ix.con.execute("SELECT textstatus, fehler FROM dokumente").fetchone()
        assert status == "fehler" and "Absturz" in fehler
    finally:
        ix._pool_beenden()
        ix.con.close()


def test_zeitueberschreitung_beendet_arbeitsprozesse_unter_python_311(tmp_path):
    pfad = tmp_path / "langsam.md"
    pfad.write_text("x", encoding="utf-8")
    konfig = h.konfig_fuer(tmp_path)
    ix = Indexer(konfig)
    try:
        ix._einreichen(Auftrag("datei", h.haengt, (str(pfad),), {"pfad": str(pfad), "basis": _basis(pfad)}, zeitlimit=1))
        prozesse = list(ix.pool._processes.values())
        assert prozesse
        ix._abarbeiten()
        ix.con.commit()
        status, fehler = ix.con.execute("SELECT textstatus, fehler FROM dokumente").fetchone()
        assert status == "fehler" and fehler == "Zeitüberschreitung"
        assert ix.pool is None
        for p in prozesse:
            p.join(5)
            assert not p.is_alive()
    finally:
        ix._pool_beenden()
        ix.con.close()

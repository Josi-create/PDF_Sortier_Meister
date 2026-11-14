"""Issue #244: Passwortschutz einer PDF entfernen (src/core/pdf_entsperren.py, Qt-frei).

Alle PDFs entstehen im Test (erfundener Inhalt, erfundene Passwoerter).
"""
from __future__ import annotations

import hashlib
import os

import pikepdf
import pymupdf
import pytest

from src.core import pdf_entsperren as pe
from src.core.pdf_entsperren import EntsperrenNichtMoeglich, FalschesPasswort, braucht_passwort, entsperren

BENUTZER = "geheim-1975"
BESITZER = "besitzer-xyz"
VERFAHREN = {
    "aes256": pymupdf.PDF_ENCRYPT_AES_256,
    "aes128": pymupdf.PDF_ENCRYPT_AES_128,
    "rc4-128": pymupdf.PDF_ENCRYPT_RC4_128,
    "rc4-40": pymupdf.PDF_ENCRYPT_RC4_40,
}


def geschuetzte_pdf(pfad, benutzer=BENUTZER, besitzer=BESITZER, verfahren=pymupdf.PDF_ENCRYPT_AES_256, seiten=2):
    """PDF mit Text und Metadaten; ``benutzer=""`` ergibt eine PDF, die nur Rechte einschraenkt."""
    doc = pymupdf.open()
    for nr in range(seiten):
        doc.new_page().insert_text((72, 72), f"Kontoauszug Musterbank Seite {nr + 1}")
    doc.set_metadata({"title": "Kontoauszug", "author": "Musterbank", "keywords": "Bank/Konto"})
    doc.save(str(pfad), encryption=verfahren, user_pw=benutzer, owner_pw=besitzer)
    doc.close()
    return pfad


def _sha(pfad) -> str:
    return hashlib.sha256(pfad.read_bytes()).hexdigest()


def _ordner(pfad) -> list[str]:
    return sorted(p.name for p in pfad.iterdir())


# --- Erkennen ---------------------------------------------------------------------------

def test_braucht_passwort_nur_bei_oeffnen_passwort(tmp_path):
    offen = tmp_path / "offen.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(offen))
    doc.close()
    assert braucht_passwort(geschuetzte_pdf(tmp_path / "zu.pdf")) is True
    assert braucht_passwort(offen) is False
    # nur Besitzerpasswort (Drucken/Kopieren eingeschraenkt): laesst sich ohne Passwort oeffnen
    assert braucht_passwort(geschuetzte_pdf(tmp_path / "rechte.pdf", benutzer="")) is False


def test_braucht_passwort_bei_kaputter_oder_fehlender_datei(tmp_path):
    kaputt = tmp_path / "kaputt.pdf"
    kaputt.write_bytes(b"kein pdf")
    assert braucht_passwort(kaputt) is False
    assert braucht_passwort(tmp_path / "fehlt.pdf") is False
    text = tmp_path / "notiz.txt"
    text.write_text("Hallo", encoding="utf-8")
    assert braucht_passwort(text) is False


# --- Entsperren -------------------------------------------------------------------------

@pytest.mark.parametrize("verfahren", sorted(VERFAHREN))
def test_benutzerpasswort_erzeugt_ungeschuetzte_kopie(tmp_path, verfahren):
    original = geschuetzte_pdf(tmp_path / "Auszug.pdf", verfahren=VERFAHREN[verfahren])
    vorher = _sha(original)
    erg = entsperren(original, BENUTZER)

    assert erg.kopie == tmp_path / "Auszug (entsperrt).pdf" and erg.original == original
    assert erg.seiten == 2 and erg.signiert is False
    assert _sha(original) == vorher and braucht_passwort(original)  # das Original ist unberuehrt
    assert _ordner(tmp_path) == ["Auszug (entsperrt).pdf", "Auszug.pdf"]  # keine temporaere Datei bleibt
    with pymupdf.open(str(erg.kopie)) as doc:
        assert not doc.needs_pass and not doc.is_encrypted and doc.metadata["encryption"] is None
        assert doc.page_count == 2 and "Musterbank Seite 2" in doc[1].get_text()
        assert doc.metadata["title"] == "Kontoauszug" and doc.metadata["keywords"] == "Bank/Konto"
    with pikepdf.open(str(erg.kopie)) as pdf:  # ohne Passwort
        assert not pdf.is_encrypted


def test_besitzerpasswort_oeffnet_ebenfalls(tmp_path):
    original = geschuetzte_pdf(tmp_path / "Auszug.pdf")
    erg = entsperren(original, BESITZER)
    assert not braucht_passwort(erg.kopie)
    with pymupdf.open(str(erg.kopie)) as doc:
        assert doc.page_count == 2 and not doc.is_encrypted


@pytest.mark.parametrize("falsch", ["falsch", "", BENUTZER.upper(), BENUTZER + " "])
def test_falsches_passwort_aendert_nichts(tmp_path, falsch):
    original = geschuetzte_pdf(tmp_path / "Auszug.pdf")
    vorher = _sha(original)
    with pytest.raises(FalschesPasswort) as fehler:
        entsperren(original, falsch)
    assert _ordner(tmp_path) == ["Auszug.pdf"] and _sha(original) == vorher
    if falsch:
        assert falsch not in str(fehler.value)


@pytest.mark.parametrize("verfahren", sorted(VERFAHREN))
@pytest.mark.parametrize("passwort", ["Mäuschen", "pässwört€", "ä1"])
def test_passwort_mit_umlauten(tmp_path, verfahren, passwort):
    """Aeltere PDFs legen Umlaute nicht als UTF-8 ab; dasselbe Passwort muss trotzdem passen."""
    original = geschuetzte_pdf(tmp_path / "Auszug.pdf", benutzer=passwort, verfahren=VERFAHREN[verfahren])
    erg = entsperren(original, passwort)
    assert not braucht_passwort(erg.kopie)
    with pytest.raises(FalschesPasswort):
        entsperren(original, passwort.replace("ä", "a"))


def test_mit_pikepdf_verschluesselte_pdf(tmp_path):
    """Zweiter Erzeuger (qpdf), damit nicht nur das Format eines Programms geprueft ist."""
    offen = tmp_path / "offen.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Lohnabrechnung Max Mustermann")
    doc.save(str(offen))
    doc.close()
    for name, r in (("r6.pdf", 6), ("r4.pdf", 4), ("r3.pdf", 3)):
        ziel = tmp_path / name
        with pikepdf.open(str(offen)) as pdf:
            pdf.save(str(ziel), encryption=pikepdf.Encryption(user="Straße9", owner="chef", R=r, aes=r >= 4, metadata=r >= 4))
        assert braucht_passwort(ziel)
        erg = entsperren(ziel, "Straße9")
        with pymupdf.open(str(erg.kopie)) as doc:
            assert not doc.is_encrypted and "Max Mustermann" in doc[0].get_text()


def test_zweiter_weg_wenn_pikepdf_das_passwort_ablehnt(tmp_path, monkeypatch):
    """PyMuPDF nimmt das Passwort an, pikepdf (hier: kuenstlich) nicht - die Kopie entsteht trotzdem."""
    original = geschuetzte_pdf(tmp_path / "Auszug.pdf")
    vorher = _sha(original)
    monkeypatch.setattr(pe, "_kandidaten", lambda passwort: ["passt-bei-pikepdf-nicht"])
    erg = entsperren(original, BENUTZER)
    assert erg.kopie.name == "Auszug (entsperrt).pdf" and erg.seiten == 2 and erg.signiert is False
    assert _sha(original) == vorher and _ordner(tmp_path) == ["Auszug (entsperrt).pdf", "Auszug.pdf"]
    with pymupdf.open(str(erg.kopie)) as doc:
        assert not doc.needs_pass and not doc.is_encrypted and "Musterbank Seite 1" in doc[0].get_text()
        assert doc.metadata["keywords"] == "Bank/Konto"
    with pytest.raises(FalschesPasswort):
        entsperren(original, "falsch")
    assert _ordner(tmp_path) == ["Auszug (entsperrt).pdf", "Auszug.pdf"]


def test_ohne_oeffnen_passwort_wird_nichts_geschrieben(tmp_path):
    rechte = geschuetzte_pdf(tmp_path / "rechte.pdf", benutzer="")
    with pytest.raises(EntsperrenNichtMoeglich, match="kein Passwort"):
        entsperren(rechte, BESITZER)
    assert _ordner(tmp_path) == ["rechte.pdf"]


def test_fehlende_datei(tmp_path):
    with pytest.raises(FileNotFoundError):
        entsperren(tmp_path / "fehlt.pdf", "x")


def test_vorhandene_kopie_wird_nie_ueberschrieben(tmp_path):
    original = geschuetzte_pdf(tmp_path / "Auszug.pdf")
    belegt = tmp_path / "Auszug (entsperrt).pdf"
    belegt.write_bytes(b"schon da")
    erste = entsperren(original, BENUTZER)
    zweite = entsperren(original, BENUTZER)
    assert erste.kopie.name == "Auszug (entsperrt) (2).pdf" and zweite.kopie.name == "Auszug (entsperrt) (3).pdf"
    assert belegt.read_bytes() == b"schon da"


def test_verschieben_ersetzt_nie(tmp_path):
    tmp = tmp_path / "neu.tmp"
    tmp.write_bytes(b"neu")
    ziel = tmp_path / "ziel.pdf"
    ziel.write_bytes(b"alt")
    with pytest.raises(FileExistsError):
        pe._verschieben_ohne_ersetzen(tmp, ziel)
    assert ziel.read_bytes() == b"alt" and tmp.read_bytes() == b"neu"
    frei = tmp_path / "frei.pdf"
    pe._verschieben_ohne_ersetzen(tmp, frei)
    assert frei.read_bytes() == b"neu" and not tmp.exists()


@pytest.mark.skipif(os.name != "nt", reason="Dateisperren durch Virenscanner/OneDrive gibt es so nur unter Windows")
def test_verschieben_wartet_bei_kurz_gesperrter_datei(tmp_path, monkeypatch):
    tmp = tmp_path / "neu.tmp"
    tmp.write_bytes(b"neu")
    monkeypatch.setattr(pe, "RETRY_DELAYS", (0, 0))
    echt = os.rename
    versuche = []

    def gesperrt(quelle, ziel):
        versuche.append(1)
        if len(versuche) < 3:
            raise PermissionError(13, "gesperrt")
        return echt(quelle, ziel)

    monkeypatch.setattr(os, "rename", gesperrt)
    frei = tmp_path / "frei.pdf"
    pe._verschieben_ohne_ersetzen(tmp, frei)
    assert frei.read_bytes() == b"neu" and not tmp.exists() and len(versuche) == 3
    # bleibt sie gesperrt, wird der Fehler gemeldet statt endlos gewartet
    tmp.write_bytes(b"neu")
    versuche.clear()
    monkeypatch.setattr(os, "rename", lambda q, z: (_ for _ in ()).throw(PermissionError(13, "gesperrt")))
    with pytest.raises(PermissionError):
        pe._verschieben_ohne_ersetzen(tmp, tmp_path / "nie.pdf")


def test_verknuepfen_ohne_ersetzen_auch_ohne_harte_links(tmp_path, monkeypatch):
    """Der Weg fuer macOS/Linux (laeuft auch unter Windows): mit hartem Link und ohne."""
    ziel = tmp_path / "ziel.pdf"
    for ohne_link in (False, True):
        if ohne_link:
            def kein_link(quelle, ziel_):
                raise OSError(95, "Operation not supported")
            monkeypatch.setattr(os, "link", kein_link)
        tmp = tmp_path / "neu.tmp"
        tmp.write_bytes(b"neu")
        ziel.unlink(missing_ok=True)
        pe._verknuepfen_ohne_ersetzen(tmp, ziel)
        assert ziel.read_bytes() == b"neu" and not tmp.exists()
        tmp.write_bytes(b"zweite")
        with pytest.raises(FileExistsError):
            pe._verknuepfen_ohne_ersetzen(tmp, ziel)
        assert ziel.read_bytes() == b"neu"
        tmp.unlink()


def test_umlaute_und_leerzeichen_im_pfad(tmp_path):
    ordner = tmp_path / "Bücher & Belege (März)"
    ordner.mkdir()
    original = geschuetzte_pdf(ordner / "Größe Übersicht ß.pdf")
    erg = entsperren(original, BENUTZER)
    assert erg.kopie.name == "Größe Übersicht ß (entsperrt).pdf" and not braucht_passwort(erg.kopie)


def test_pruefung_schlaegt_fehl_dann_bleibt_nur_das_original(tmp_path, monkeypatch):
    """Ist die geschriebene Datei nicht in Ordnung, entsteht keine Kopie und keine temporaere Datei bleibt."""
    original = geschuetzte_pdf(tmp_path / "Auszug.pdf")
    vorher = _sha(original)

    def kaputt(datei, seiten):
        raise EntsperrenNichtMoeglich("Die Kopie hat nicht alle Seiten des Originals.")

    monkeypatch.setattr(pe, "_pruefen", kaputt)
    with pytest.raises(EntsperrenNichtMoeglich, match="nicht alle Seiten"):
        entsperren(original, BENUTZER)
    assert _ordner(tmp_path) == ["Auszug.pdf"] and _sha(original) == vorher


def test_pruefen_erkennt_geschuetzte_und_unvollstaendige_datei(tmp_path):
    zu = geschuetzte_pdf(tmp_path / "zu.pdf")
    with pytest.raises(EntsperrenNichtMoeglich, match="noch geschützt"):
        pe._pruefen(zu, 2)
    rechte = geschuetzte_pdf(tmp_path / "rechte.pdf", benutzer="")
    with pytest.raises(EntsperrenNichtMoeglich, match="noch geschützt"):
        pe._pruefen(rechte, 2)
    offen = tmp_path / "offen.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(offen))
    doc.close()
    pe._pruefen(offen, 1)
    with pytest.raises(EntsperrenNichtMoeglich, match="nicht alle Seiten"):
        pe._pruefen(offen, 2)


def test_schreibfehler_nennt_das_passwort_nicht(tmp_path, monkeypatch):
    """Auch wenn eine Bibliothek das Passwort in ihrer Meldung nennt: bei uns steht es nicht."""
    original = geschuetzte_pdf(tmp_path / "Auszug.pdf")

    def schreiben(self, *args, **kwargs):
        raise RuntimeError(f"Platte voll (Passwort {BENUTZER})")

    monkeypatch.setattr(pikepdf.Pdf, "save", schreiben)
    with pytest.raises(EntsperrenNichtMoeglich) as fehler:
        entsperren(original, BENUTZER)
    assert BENUTZER not in str(fehler.value) and "Platte voll" in str(fehler.value)
    assert fehler.value.__cause__ is None and fehler.value.__suppress_context__  # kein Traceback mit dem Original
    assert _ordner(tmp_path) == ["Auszug.pdf"]


def test_ordner_nicht_beschreibbar(tmp_path, monkeypatch):
    original = geschuetzte_pdf(tmp_path / "Auszug.pdf")
    tmp = pe.tmp_pfad(original)
    echtes_open = open

    def gesperrt(datei, modus="r", *args, **kwargs):
        if str(datei) == str(tmp) and "w" in modus:
            raise PermissionError(13, "Zugriff verweigert")
        return echtes_open(datei, modus, *args, **kwargs)

    monkeypatch.setattr("builtins.open", gesperrt)
    with pytest.raises(EntsperrenNichtMoeglich, match="kann nicht geschrieben werden"):
        entsperren(original, BENUTZER)
    assert _ordner(tmp_path) == ["Auszug.pdf"]


def test_temporaere_datei_liegt_im_selben_ordner_und_ist_keine_pdf(tmp_path):
    tmp = pe.tmp_pfad(tmp_path / "Auszug.pdf")
    assert tmp.parent == tmp_path and tmp.name.startswith("~$") and tmp.suffix == ".tmp"
    assert pe.tmp_pfad(tmp_path / "Auszug2.pdf") != tmp


def test_signierte_pdf_wird_gemeldet(tmp_path):
    offen = tmp_path / "offen.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(offen))
    doc.close()
    zu = tmp_path / "signiert.pdf"
    with pikepdf.open(str(offen)) as pdf:
        pdf.Root.AcroForm = pikepdf.Dictionary(SigFlags=3, Fields=pikepdf.Array())
        pdf.save(str(zu), encryption=pikepdf.Encryption(user=BENUTZER, owner=BESITZER, R=6))
    erg = entsperren(zu, BENUTZER)
    assert erg.signiert is True and erg.kopie.exists()


def test_passwort_steht_nicht_in_der_kopie(tmp_path):
    original = geschuetzte_pdf(tmp_path / "Auszug.pdf")
    erg = entsperren(original, BENUTZER)
    inhalt = erg.kopie.read_bytes()
    assert BENUTZER.encode() not in inhalt and BESITZER.encode() not in inhalt

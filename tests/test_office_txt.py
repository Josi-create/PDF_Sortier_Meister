"""Tests fuer .txt (Issue #227): PDFSM wandelt selbst um, ohne Word oder LibreOffice.

Synthetische Dateien unter tmp_path. Suchindex: der Lauf nimmt .txt nicht von sich
aus auf, wohl aber eine vom Nutzer einsortierte Datei, und haelt sie dann aktuell.
"""
from __future__ import annotations

import pymupdf
import pytest

from src.core import office_convert as oc
from src.core import office_vorschau as ov
from src.search import office
from src.search.indexer import Indexer
from src.search.suchindex import Suchindex
from tests import helfer_suche as h


def _pdf_text(pfad) -> list[str]:
    with pymupdf.open(str(pfad)) as doc:
        return [seite.get_text() for seite in doc]


@pytest.fixture
def kein_office(monkeypatch):
    """Kein Word, kein LibreOffice: .txt muss trotzdem gehen."""
    monkeypatch.setattr(oc, "word_com_verfuegbar", lambda: False)
    monkeypatch.setattr(oc, "excel_com_verfuegbar", lambda: False)
    monkeypatch.setattr(oc, "mac_office_verfuegbar", lambda art: False)
    monkeypatch.setattr(oc, "finde_libreoffice", lambda: None)


# --------------------------------------------------------------------------- Kodierung

@pytest.mark.parametrize("roh", [
    "Grüße aus Köln – 5 €".encode("utf-8"),
    b"\xef\xbb\xbf" + "Grüße aus Köln – 5 €".encode("utf-8"),
    "Grüße aus Köln – 5 €".encode("cp1252"),
    "Grüße aus Köln – 5 €".encode("utf-16"),  # mit BOM, wie der Windows-Editor "Unicode" speichert
    b"\xfe\xff" + "Grüße aus Köln – 5 €".encode("utf-16-be"),
])
def test_kodierung_wird_erkannt(roh):
    assert office.txt_dekodieren(roh) == "Grüße aus Köln – 5 €"


def test_kodierung_unbelegte_bytes_werfen_nicht():
    assert office.txt_dekodieren(b"a\x81\xfcb") == "a\x81üb"


def test_office_text_liest_txt(tmp_path):
    p = tmp_path / "Notiz.txt"
    p.write_bytes("Zählerstand März\r\n\r\n4711 kWh\r\n".encode("cp1252"))
    erg = office.office_text(str(p), "txt")
    assert erg["status"] == "text" and erg["fehler"] is None
    assert erg["seiten"] == [(1, "text", "Zählerstand März\r\n\r\n4711 kWh")]
    leer = tmp_path / "leer.txt"
    leer.write_bytes(b" \n")
    assert office.office_text(str(leer), "txt")["status"] == "leer"


# --------------------------------------------------------------------------- Endungen

def test_txt_ist_sortierbar_und_behaelt_endung():
    assert oc.ist_office_datei("Notiz.TXT") and oc.ist_sortierbar("a/Notiz.txt")
    assert ".txt" in oc.sortierbare_endungen()
    assert oc.endung_tauschen("2026-05-12_Notiz", ".txt") == "2026-05-12_Notiz.txt"
    assert oc.umwandler_verfuegbar(".txt")


# --------------------------------------------------------------------------- Zeilen

def test_zeilen_umbruch_tabs_und_steuerzeichen():
    lang = "wort " * 30  # 150 Zeichen
    zeilen = oc.txt_zeilen(f"Titel\r\n\tEingerückt\r{lang}\n\nEnde\x00\x07\n\n\n")
    assert zeilen[0] == "Titel" and zeilen[1] == " " * 8 + "Eingerückt"
    assert all(len(z) <= oc.TXT_SPALTEN for z in zeilen)
    assert " ".join(zeilen[2:4]).split() == ["wort"] * 30
    assert zeilen[-2:] == ["", "Ende"]  # Leerzeile bleibt, Leerzeilen am Ende fallen weg


def test_zeilen_ohne_leerzeichen_werden_hart_umbrochen():
    assert oc.txt_zeilen("x" * 200) == ["x" * 80, "x" * 80, "x" * 40]


# --------------------------------------------------------------------------- Umwandeln

def test_umwandeln_ohne_office(tmp_path, kein_office):
    quelle = tmp_path / "Zählerstand Müller.txt"
    inhalt = "Zählerstand am 12.05.2026\n\nStrom: 4711 kWh – Abschlag 85 €\n„Bitte prüfen“\n"
    quelle.write_bytes(inhalt.encode("cp1252"))
    erg = oc.umwandeln(quelle)
    assert erg.pdf == tmp_path / "Zählerstand Müller.pdf" and erg.pdf.exists()
    assert erg.werkzeug == "PDF Sortier Meister" and not erg.pdfa and not erg.hinweise
    assert quelle.read_bytes() == inhalt.encode("cp1252")  # Original unveraendert
    seiten = _pdf_text(erg.pdf)
    assert len(seiten) == 1
    for teil in ("Zählerstand am 12.05.2026", "4711 kWh – Abschlag 85 €", "„Bitte prüfen“"):
        assert teil in seiten[0]
    with pymupdf.open(str(erg.pdf)) as doc:
        assert tuple(round(v) for v in doc[0].rect[2:]) == oc.TXT_SEITE  # A4


def test_umwandeln_mehrere_seiten_und_rand(tmp_path, kein_office):
    quelle = tmp_path / "lang.txt"
    quelle.write_text("\n".join(f"Zeile {i}" for i in range(1, 131)), encoding="utf-8")
    erg = oc.umwandeln(quelle)
    seiten = _pdf_text(erg.pdf)
    assert len(seiten) == 3  # 60 Zeilen je Seite
    assert seiten[0].split("\n")[0] == "Zeile 1" and "Zeile 60" in seiten[0] and "Zeile 61" not in seiten[0]
    assert seiten[2].strip().split("\n")[-1] == "Zeile 130"
    with pymupdf.open(str(erg.pdf)) as doc:
        for seite in doc:
            for block in seite.get_text("blocks"):
                assert block[0] >= oc.TXT_RAND - 1 and block[3] <= oc.TXT_SEITE[1] - oc.TXT_RAND + 1


def test_umwandeln_breite_zeile_bleibt_im_satzspiegel(tmp_path, kein_office):
    quelle = tmp_path / "breit.txt"
    quelle.write_text("M" * 80, encoding="utf-8")
    with pymupdf.open(str(oc.umwandeln(quelle).pdf)) as doc:
        rechts = max(b[2] for b in doc[0].get_text("blocks"))
    assert rechts <= oc.TXT_SEITE[0] - oc.TXT_RAND + 1


def test_umwandeln_unbekannte_zeichen_werden_fragezeichen(tmp_path, kein_office):
    quelle = tmp_path / "bunt.txt"
    quelle.write_text("Привет, αβγ und 日本 😀", encoding="utf-8")
    text = _pdf_text(oc.umwandeln(quelle).pdf)[0]
    assert "Привет, αβγ und ?? ?" in text and "\x00" not in text


def test_umwandeln_ueberschreibt_nichts_und_pdfa_gibt_hinweis(tmp_path, kein_office):
    quelle = tmp_path / "Notiz.txt"
    quelle.write_text("Inhalt", encoding="utf-8")
    (tmp_path / "Notiz.pdf").write_bytes(b"alt")
    erg = oc.umwandeln(quelle, pdfa=True)
    assert erg.pdf.name == "Notiz (1).pdf" and (tmp_path / "Notiz.pdf").read_bytes() == b"alt"
    assert not erg.pdfa and len(erg.hinweise) == 1 and "PDF/A" in erg.hinweise[0]


def test_umwandeln_leer_und_zu_gross(tmp_path, kein_office, monkeypatch):
    leer = tmp_path / "leer.txt"
    leer.write_bytes(b"\r\n \r\n")
    with pytest.raises(oc.UmwandlungFehler, match="leer"):
        oc.umwandeln(leer)
    gross = tmp_path / "protokoll.txt"
    gross.write_text("x" * 200, encoding="utf-8")
    monkeypatch.setattr(oc, "TXT_MAX_BYTES", 100)
    with pytest.raises(oc.UmwandlungFehler, match="zu groß"):
        oc.umwandeln(gross)
    assert not list(tmp_path.glob("*.pdf"))


# --------------------------------------------------------------------------- Vorschau und Analyse

def test_vorschau_erste_zeilen_und_pdf(tmp_path, kein_office):
    quelle = tmp_path / "Notiz.txt"
    quelle.write_text("Erste Zeile\n\nZweite Zeile\n", encoding="utf-8")
    assert ov.erste_zeilen(quelle) == ["Erste Zeile", "Zweite Zeile"]
    assert ov.eingebettetes_bild(quelle) is None
    pdf = ov.vorschau_pdf(quelle, cache_dir=tmp_path / "cache")
    assert pdf.parent == tmp_path / "cache" and "Erste Zeile" in _pdf_text(pdf)[0]
    assert not (tmp_path / "Notiz.pdf").exists()  # Vorschau legt nichts neben das Original


def test_analyse_liest_text_und_datum(tmp_path):
    from src.core.office_analyse import analysiere

    quelle = tmp_path / "Notiz.txt"
    quelle.write_bytes("Stromrechnung der Stadtwerke vom 12.05.2026\nZählerstand 4711".encode("cp1252"))
    text, _keywords, daten = analysiere(quelle)
    assert "Zählerstand 4711" in text
    assert any((d.year, d.month, d.day) == (2026, 5, 12) for d in daten)


# --------------------------------------------------------------------------- Suchindex

def test_lauf_nimmt_txt_nicht_von_sich_aus_auf(tmp_path):
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    (ablage / "LICENSE.txt").write_text("Lizenztext Sonderwort", encoding="utf-8")
    h.pdf_mit_text(ablage / "a.pdf", ["Mietvertrag"])
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    assert Indexer(konfig, synchron=True).lauf() == 0
    idx = Suchindex(konfig)
    assert idx.dokument_nach_pfad(str(ablage / "LICENSE.txt")) is None
    assert idx.suche("Sonderwort")["gesamt"] == 0 and idx.suche("Mietvertrag")["gesamt"] == 1
    # ... und auch nicht ueber eine Meldung der Oberflaeche (z. B. Original aus dem Papierkorb zurueck)
    assert idx.datei_aufnehmen(str(ablage / "LICENSE.txt")) is None
    assert idx.datei_geaendert(str(ablage / "LICENSE.txt")) is None


def test_einsortierte_txt_ist_suchbar_und_bleibt_es(tmp_path):
    from src.utils.database import Database

    scan = tmp_path / "Scan"
    scan.mkdir()
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    quelle = scan / "Notiz.txt"
    quelle.write_bytes("Zählerstand Sonderwort".encode("cp1252"))
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    idx = Suchindex(konfig)
    datenbank = Database(db_path=str(tmp_path / "pdfsm.db"), suchindex=idx)

    ziel = ablage / "2026-05-12_Notiz.txt"
    quelle.rename(ziel)  # der Nutzer verschiebt; das Hauptfenster meldet es so:
    assert datenbank.update_pdf_path(str(quelle), str(ziel), new_filename=ziel.name)

    d = idx.dokument_nach_pfad(str(ziel))
    assert d["typ"] == "office" and d["format"] == "txt" and d["textstatus"] == "text"
    assert idx.suche("Sonderwort")["gesamt"] == 1 and idx.suche("Zählerstand")["gesamt"] == 1

    # Der naechste Lauf laesst den Eintrag stehen ...
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert idx.suche("Sonderwort")["gesamt"] == 1
    # ... liest eine geaenderte Datei neu ...
    ziel.write_text("Jetzt steht hier Neuwort und mehr", encoding="utf-8")
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert idx.suche("Neuwort")["gesamt"] == 1 and idx.suche("Sonderwort")["gesamt"] == 0
    # ... und raeumt sie weg, wenn sie geloescht wurde
    ziel.unlink()
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert idx.dokument_nach_pfad(str(ziel)) is None


def test_txt_in_den_einstellungen_nimmt_alle_auf(tmp_path):
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    (ablage / "Notiz.txt").write_text("Sonderwort", encoding="utf-8")
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    konfig.endungen.add(".txt")
    assert Indexer(konfig, synchron=True).lauf() == 0
    assert Suchindex(konfig).suche("Sonderwort")["gesamt"] == 1

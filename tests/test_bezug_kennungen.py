"""Kennungen aus dem Bezugsdokument (Issue #166/#167): Erkennung, Ausschluesse, Suchphrase."""
from pathlib import Path

from src.rag.bezug import Bezug, Kennung, kennungen_aus_text, kennungs_abfrage

TEXT = (
    "Zum 03.05.2026 werden einzelne Preisbestandteile Ihres Gasliefervertrags mit der "
    "Vertragsnummer G22504020299 angepasst. Kundennummer: G27301A1686. Die Konditionen gelten "
    "für den Gaszähler mit der Gaszählernummer 226541. Rechnungs-Nr. R26-3117753 vom 24.07.2026, "
    "Mandatsreferenz 1708867, Marktlokations ID: 50941885277, Zähler-Nr.: 226541, "
    "Betrag 172,00 € per Lastschrift von IBAN DE05 5706 9144 1205 6190 05. "
    "Verbrauch 11792 kWh/Jahr, Zählerstand 33.683,003 am 01.05.2025. "
    "Johannes Wack, Kellermannstr. 3, 48149 Münster, Tel. 0251 123456, Fax: 0251 654321. "
    "immergrün energie GmbH, Amtsgericht Köln unter HRB 102538, USt-IdNr. DE212755674, "
    "Gläubiger-ID DE34ZZZ00000117309, Steuernummer 215/5812/3405, BIC GENODED1KAI"
)


def test_benannte_kennungen_in_reihenfolge_ohne_doppelte():
    assert kennungen_aus_text(TEXT) == [
        Kennung("G22504020299", "Vertragsnummer"),
        Kennung("G27301A1686", "Kundennummer"),
        Kennung("226541", "Zählernummer"),
        Kennung("R26-3117753", "Rechnungsnummer"),
        Kennung("1708867", "Referenz"),
        Kennung("50941885277", "Marktlokation"),
        Kennung("DE05 5706 9144 1205 6190 05", "IBAN"),
    ]


def test_daten_betraege_mengen_telefon_plz_und_absenderangaben_sind_keine_kennungen():
    werte = {k.wert for k in kennungen_aus_text(TEXT)}
    for falsch in ("2026", "03.05.2026", "172", "11792", "33.683,003", "683", "48149", "123456", "654321", "0251",
                   "102538", "DE212755674", "DE34ZZZ00000117309", "215/5812/3405", "GENODED1KAI"):
        assert falsch not in werte


def test_benannt_und_allgemein():
    assert Kennung("G1", "Vertragsnummer").benannt
    assert Kennung("226541", "Zählernummer").benannt
    assert not Kennung("DE05570691441205619005", "IBAN").benannt
    assert not Kennung("3000083421").benannt


def test_unbenannte_kennungen_mit_mindestens_fuenf_ziffern():
    k = kennungen_aus_text("Ihre Buchung 20536 vom 12.03.2024, Transaktion 3000083421, Seite 1 von 2, "
                           "Zaehlernummer 190000074262, Datum 2026-07-24, Jahr 2024/2025")
    assert k[0] == Kennung("190000074262", "Zählernummer")  # ae statt ä im Stamm reicht
    assert [x.wert for x in k[1:]] == ["20536", "3000083421"]
    assert all(x.art == "Kennung" for x in k[1:])


def test_schreibweisen_der_beschriftung():
    k = kennungen_aus_text("Kunden-Nr 4711-08 / Vertragsnr.: V123456 / Versicherungsscheinnummer 99887766 / "
                           "Steuernummer 123/456/78901 / Aktenzeichen 4 C 1234/26 / MeLo DE0004676743400001")
    arten = {x.art: x.wert for x in k}
    assert arten["Kundennummer"] == "4711-08"
    assert arten["Vertragsnummer"] == "V123456"
    assert arten["Versicherungsnummer"] == "99887766"
    assert arten["Messlokation"] == "DE0004676743400001"
    # Die Steuernummer steht auf jedem Schreiben des Absenders und verbindet nichts Einzelnes
    assert "123/456/78901" not in {x.wert for x in k}


def test_leerer_text_und_hoechstzahl():
    assert kennungen_aus_text("") == []
    assert kennungen_aus_text("   ") == []
    assert len(kennungen_aus_text(TEXT, max_anzahl=2)) == 2


def test_kennungs_abfrage_ist_exakte_phrase():
    assert kennungs_abfrage("G22504020299") == '"G22504020299"'
    assert kennungs_abfrage("R26-3117753") == '"R26 3117753"'
    assert kennungs_abfrage("123/456/78901") == '"123 456 78901"'
    assert kennungs_abfrage("DE05 5706 9144 1205 6190 05") == '"DE05 5706 9144 1205 6190 05" OR "DE05570691441205619005"'
    assert kennungs_abfrage("") == ""


def test_str_der_kennung_fuer_den_prompt():
    assert str(Kennung("226541", "Zählernummer")) == "226541 (Zählernummer)"


def test_bezug_im_scan_ordner(tmp_path):
    scan = tmp_path / "Scan"
    assert Bezug(pfad=scan / "a.pdf", scan_ordner=scan).im_scan_ordner()
    assert Bezug(pfad=scan / "Unterordner" / "a.pdf", scan_ordner=str(scan)).im_scan_ordner()
    assert not Bezug(pfad=tmp_path / "Ablage" / "a.pdf", scan_ordner=scan).im_scan_ordner()
    assert not Bezug(pfad=scan / "a.pdf").im_scan_ordner()
    assert isinstance(Bezug(pfad=scan / "a.pdf", scan_ordner=str(scan)).scan_ordner, Path)

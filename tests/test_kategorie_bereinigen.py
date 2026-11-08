"""Kategorie (subject) ist genau ein Wert - Befunde aus dem Live-Test vom 2026-11-08.

- Die KI schrieb die Auswahlliste aus dem Prompt-Beispiel ab
  ("Rechnung/Vertrag/Steuer/Versicherung/Bank/Gehalt/Arzt/Energie/Sonstiges",
  auch gekuerzt); sie landete in der PDF und wurde fuer den Korrespondenten gelernt.
- Aeltere PDFs tragen die Textform eines XMP-Bags ("{'Sonstiges'}") in dc:subject,
  die beim Lesen und erneuten Schreiben uebernommen wurde.
"""
from __future__ import annotations

import pytest

from src.core.metadata_choices import clean_category
from src.ml.llm_provider import normalize_llm_metadata


@pytest.mark.parametrize("wert, erwartet", [
    ("Rechnung", "Rechnung"),
    ("  Versicherung ", "Versicherung"),
    ("Nebenkostenabrechnung", "Nebenkostenabrechnung"),  # eigene Kategorie bleibt
    ("Recht/Vertrag", "Recht/Vertrag"),  # nur eine Standardkategorie: keine Auswahlliste
    ("Rechnung/Vertrag/Steuer/Versicherung/Bank/Gehalt/Arzt/Energie/Sonstiges", ""),
    ("Rechnung/Vertrag/Steuer/Bank", ""),
    ("genau EINE von: Rechnung, Vertrag, Steuer, Versicherung, Bank, Gehalt, Arzt, Energie, Sonstiges", ""),
    ("Rechnung oder Vertrag", ""),
    ("{'Sonstiges'}", "Sonstiges"),
    ("['Rechnung']", "Rechnung"),
    ("('Bank',)", "Bank"),
    ({"Sonstiges"}, "Sonstiges"),
    (["Rechnung"], "Rechnung"),
    ({"acme", "Steuer", "2024"}, "Steuer"),  # Standardkategorie gewinnt
    ({"acme", "zeta"}, "acme"),
    ({"x": "Rechnung"}, ""),
    ("UNBEKANNT", ""),
    ("null", ""),
    ("", ""),
    (None, ""),
])
def test_clean_category(wert, erwartet):
    assert clean_category(wert) == erwartet


def test_ki_metadaten_ohne_abgeschriebene_auswahlliste():
    md = normalize_llm_metadata({
        "category": "Rechnung/Vertrag/Steuer/Versicherung/Bank/Gehalt/Arzt/Energie/Sonstiges",
        "korrespondent": "Jester GmbH & Co KG",
    })
    assert md == {"korrespondent": "Jester GmbH & Co KG"}


def test_ki_metadaten_kategorie_alias_springt_ein_wenn_subject_kaputt():
    md = normalize_llm_metadata({"subject": "Rechnung/Vertrag", "kategorie": "Rechnung"})
    assert md["subject"] == "Rechnung"


def test_prompt_beispiel_ist_keine_schraegstrich_liste():
    import inspect

    from src.ml import llm_provider

    quelle = inspect.getsource(llm_provider)
    assert "Rechnung/Vertrag/Steuer" not in quelle


def test_dateiname_platzhalter_ohne_auswahlliste():
    from src.core.filename_placeholders import placeholder_values_from_metadata

    werte = placeholder_values_from_metadata({"subject": "{'Rechnung'}"})
    assert werte["kategorie"] == "Rechnung"
    werte = placeholder_values_from_metadata({"subject": "Rechnung/Vertrag/Steuer/Bank"})
    assert "kategorie" not in werte


# --------------------------------------------------------------------------- PDF

pikepdf = pytest.importorskip("pikepdf")


def _pdf(tmp_path, subject, name="brief.pdf"):
    path = tmp_path / name
    pdf = pikepdf.new()
    pdf.add_blank_page()
    with pdf.open_metadata() as meta:
        meta["dc:title"] = "Brief"
        meta["dc:subject"] = subject
    pdf.save(path)
    return path


@pytest.mark.parametrize("subject", ["{'Sonstiges'}", {"Sonstiges"}])
def test_pdf_lesen_liefert_eine_kategorie(tmp_path, subject):
    from src.core.pdf_metadata import read_metadata

    assert read_metadata(_pdf(tmp_path, subject)).subject == "Sonstiges"


def test_pdf_schreiben_ohne_auswahlliste(tmp_path):
    from src.core.pdf_metadata import PDFMetadata, read_metadata, write_metadata

    path = _pdf(tmp_path, "Rechnung")
    liste = "Rechnung/Vertrag/Steuer/Versicherung/Bank/Gehalt/Arzt/Energie/Sonstiges"
    assert write_metadata(path, PDFMetadata(subject=liste, korrespondent="Jester"))
    meta = read_metadata(path)
    assert meta.subject == "Rechnung"  # alter Wert bleibt, die Liste wird nicht geschrieben
    assert meta.korrespondent == "Jester"


@pytest.mark.parametrize("endung", [".docx", ".xlsx", ".odt", ".jpg"])
def test_kein_pdf_kein_metadaten_lesen(tmp_path, capsys, endung):
    """Word/Excel/Bilder: kein pikepdf-Versuch, keine Fehlermeldung in der Konsole."""
    from src.core.pdf_metadata import PDFMetadata, read_metadata, write_metadata

    datei = tmp_path / f"Brief{endung}"
    datei.write_bytes(b"PK\x03\x04 kein pdf")
    assert read_metadata(datei) is None
    assert write_metadata(datei, PDFMetadata(korrespondent="Jester")) is False
    assert datei.read_bytes() == b"PK\x03\x04 kein pdf"
    assert "Fehler" not in capsys.readouterr().out


def test_pdf_endung_gross_wird_gelesen(tmp_path):
    from src.core.pdf_metadata import read_metadata

    assert read_metadata(_pdf(tmp_path, "Bank", name="AUSZUG.PDF")).subject == "Bank"


# --------------------------------------------------------------------------- Datenbank

@pytest.fixture
def db(tmp_path):
    from src.utils.database import Database
    return Database(db_path=str(tmp_path / "history.db"))


def test_lernen_ohne_auswahlliste(db):
    liste = "Rechnung/Vertrag/Steuer/Versicherung/Bank/Gehalt/Arzt/Energie/Sonstiges"
    db.learn_korrespondent_metadata("Jester GmbH", {"subject": liste, "waehrung": "EUR"})
    assert db.get_korrespondent_metadata("Jester GmbH") == {"waehrung": "EUR"}
    db.learn_korrespondent_metadata("Jester GmbH", {"subject": "Rechnung"})
    db.learn_korrespondent_metadata("Jester GmbH", {"subject": liste})
    assert db.get_korrespondent_metadata("Jester GmbH")["subject"] == "Rechnung"


@pytest.mark.parametrize("gespeichert, erwartet", [
    ("{'Rechnung'}", {"subject": "Rechnung"}),
    ("Rechnung/Vertrag/Steuer/Bank/Gehalt/Arzt/Energie/Sonstiges", {}),
])
def test_alte_kaputte_gelernte_kategorie(db, gespeichert, erwartet):
    """Schon gespeicherte kaputte Werte wirken nicht mehr und heilen beim naechsten Lernen."""
    from src.utils.database import KorrespondentMetadata

    session = db.get_session()
    session.add(KorrespondentMetadata(korrespondent="MVG", kategorie=gespeichert))
    session.commit()
    session.close()

    assert (db.get_korrespondent_metadata("MVG") or {}) == erwartet
    db.learn_korrespondent_metadata("MVG", {"waehrung": "EUR"})
    session = db.get_session()
    try:
        zeile = session.query(KorrespondentMetadata).filter_by(korrespondent="MVG").one()
        assert zeile.kategorie == (erwartet.get("subject") or None)
    finally:
        session.close()

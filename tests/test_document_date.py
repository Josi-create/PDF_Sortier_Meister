"""Issue #132: Dokumentdatum finden, auswaehlen und Nutzereingaben parsen.

Vorher galt "das juengste Datum im Text ist das Dokumentdatum" - eine Frist
oder ein Eingangsstempel machte aus einem Brief von 2004 ein Dokument von
2006, und das Steuerjahr folgte.
"""
from datetime import datetime

import pytest

from src.core.document_date import (
    find_dates,
    is_iso_date,
    ordered_dates,
    parse_user_date,
    pick_document_date,
)


# --- find_dates -----------------------------------------------------------

def test_find_dates_liefert_alle_formate_in_lesereihenfolge():
    text = "Stand 2004-03-12, Brief vom 15.03.2004, Frist 1. April 2004, alt 31/12/99"
    values = [f.value for f in find_dates(text)]
    assert values == [
        datetime(2004, 3, 12), datetime(2004, 3, 15), datetime(2004, 4, 1), datetime(1999, 12, 31),
    ]


def test_find_dates_ignoriert_unmoegliche_und_zu_alte_daten():
    assert find_dates("31.02.2004 und 12.13.2004 und 01.01.1234 und 1.2.1985") == []


def test_find_dates_nicht_mitten_in_ziffernfolgen():
    # Telefonnummern / Aktenzeichen sollen keine Daten liefern
    assert find_dates("Az. 4711.03.2004567") == []


# --- pick_document_date ---------------------------------------------------

def test_erstes_datum_schlaegt_juengeres_datum():
    text = "Muenchen, 12.03.2004\n\nSehr geehrte Damen und Herren,\nbitte antworten Sie bis 30.06.2006."
    assert pick_document_date(text) == datetime(2004, 3, 12)


def test_beschriftetes_datum_schlaegt_frueheres_datum():
    text = "Ihr Schreiben vom 02.01.2004\nRechnungsdatum: 20.02.2004\nLieferung bis 15.03.2004"
    assert pick_document_date(text) == datetime(2004, 2, 20)


def test_ort_komma_den_gilt_als_briefdatum():
    text = "Vertrag Nr. 7 gueltig ab 01.01.2003\nBerlin, den 5. Maerz 2004\nMit freundlichen Gruessen"
    assert pick_document_date(text) == datetime(2004, 3, 5)


@pytest.mark.parametrize("label", ["geboren am", "geb.", "gueltig bis", "faellig am", "Frist:", "Eingang", "bis zum"])
def test_negative_beschriftung_zaehlt_nur_als_notnagel(label):
    text = f"{label} 01.02.2005 ... Rechnung ... 15.03.2004"
    assert pick_document_date(text) == datetime(2004, 3, 15)


def test_negativ_beschriftetes_datum_bleibt_wenn_es_das_einzige_ist():
    assert pick_document_date("Frist: 01.02.2005") == datetime(2005, 2, 1)


def test_kein_datum():
    assert pick_document_date("Kein Datum hier") is None
    assert ordered_dates("") == []


def test_ordered_dates_dokumentdatum_zuerst_dann_absteigend_ohne_doppelte():
    text = "12.03.2004 ... bis 30.06.2006 ... 12.03.2004 ... 01.01.2005"
    assert ordered_dates(text) == [
        datetime(2004, 3, 12), datetime(2006, 6, 30), datetime(2005, 1, 1),
    ]


# --- parse_user_date / is_iso_date ------------------------------------------

@pytest.mark.parametrize("text, iso", [
    ("12.03.2004", "2004-03-12"),
    ("12.3.04", "2004-03-12"),
    ("1.1.99", "1999-01-01"),
    ("2004-03-12", "2004-03-12"),
    ("2004-03-12 00:00:00", "2004-03-12"),
    ("12. März 2004", "2004-03-12"),
    ("12 Maerz 2004", "2004-03-12"),
    ("3. Jan. 2025", "2025-01-03"),
    ("Muenchen, den 12.03.2004", "2004-03-12"),
    ("01.03.2004 bis 31.03.2004", "2004-03-01"),
    ("15.08.1975", "1975-08-15"),  # Nutzereingaben duerfen vor 1990 liegen
])
def test_parse_user_date(text, iso):
    assert parse_user_date(text) == iso


@pytest.mark.parametrize("text", ["", "   ", "Rechnung Nr. 12", "31.02.2004", "12.03", None])
def test_parse_user_date_unlesbar(text):
    assert parse_user_date(text) is None


def test_is_iso_date():
    assert is_iso_date("2004-03-12")
    assert not is_iso_date("2004-02-30")
    assert not is_iso_date("12.03.2004")
    assert not is_iso_date("2004-03-12 00:00:00")
    assert not is_iso_date("")

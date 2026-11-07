"""Issue #161: intelligente Datumseingabe (Parser ohne Qt, festes ``heute``)."""
from datetime import date

import pytest

from src.core.datum_eingabe import (
    Fehler,
    Zeitraum,
    beschreibe,
    formatiere,
    parse_tag,
    parse_zeitraum,
)

HEUTE = date(2026, 11, 8)




def D(s):
    return date.fromisoformat(s)


def Z(von, bis):
    return Zeitraum(D(von) if von else None, D(bis) if bis else None)


@pytest.mark.parametrize("text,erwartet", [
    # Jahr
    ("2004", Z("2004-01-01", "2004-12-31")),
    ("  2004  ", Z("2004-01-01", "2004-12-31")),
    # Monat
    ("12/2024", Z("2024-12-01", "2024-12-31")),
    ("12.2024", Z("2024-12-01", "2024-12-31")),
    ("12-2024", Z("2024-12-01", "2024-12-31")),
    ("1/2024", Z("2024-01-01", "2024-01-31")),
    ("Dez 2024", Z("2024-12-01", "2024-12-31")),
    ("Dezember 2024", Z("2024-12-01", "2024-12-31")),
    ("dez. 24", Z("2024-12-01", "2024-12-31")),
    ("DEZ.2024", Z("2024-12-01", "2024-12-31")),
    ("Jan 24", Z("2024-01-01", "2024-01-31")),
    ("January 2024", Z("2024-01-01", "2024-01-31")),
    ("Oct 2023", Z("2023-10-01", "2023-10-31")),
    ("Mrz 2024", Z("2024-03-01", "2024-03-31")),
    ("Mär 2024", Z("2024-03-01", "2024-03-31")),
    ("März 2024", Z("2024-03-01", "2024-03-31")),
    ("Maerz 2024", Z("2024-03-01", "2024-03-31")),
    ("Mai 2024", Z("2024-05-01", "2024-05-31")),
    ("May 2024", Z("2024-05-01", "2024-05-31")),
    # Monatsenden
    ("2/2023", Z("2023-02-01", "2023-02-28")),
    ("2/2024", Z("2024-02-01", "2024-02-29")),
    ("Feb 1900", Z("1900-02-01", "1900-02-28")),
    ("04/2024", Z("2024-04-01", "2024-04-30")),
    # Tag
    ("3.5.2024", Z("2024-05-03", "2024-05-03")),
    ("03.05.24", Z("2024-05-03", "2024-05-03")),
    ("2024-05-03", Z("2024-05-03", "2024-05-03")),
    ("3. Mai 2024", Z("2024-05-03", "2024-05-03")),
    ("3 Mai 2024", Z("2024-05-03", "2024-05-03")),
    ("29.2.2024", Z("2024-02-29", "2024-02-29")),
    ("3.5.", Z("2026-05-03", "2026-05-03")),
    # Quartal
    ("Q2 2024", Z("2024-04-01", "2024-06-30")),
    ("q1/2024", Z("2024-01-01", "2024-03-31")),
    ("Q4 24", Z("2024-10-01", "2024-12-31")),
    ("2. Quartal 2024", Z("2024-04-01", "2024-06-30")),
    ("3.Quartal 2023", Z("2023-07-01", "2023-09-30")),
    # Bereiche
    ("2004-2006", Z("2004-01-01", "2006-12-31")),
    ("2004 - 2006", Z("2004-01-01", "2006-12-31")),
    ("2004 – 2006", Z("2004-01-01", "2006-12-31")),
    ("2004 — 2006", Z("2004-01-01", "2006-12-31")),
    ("2004 bis 2006", Z("2004-01-01", "2006-12-31")),
    ("2004 BIS 2006", Z("2004-01-01", "2006-12-31")),
    ("12/2023-3/2024", Z("2023-12-01", "2024-03-31")),
    ("12/2023 - 3/2024", Z("2023-12-01", "2024-03-31")),
    ("12-2023 - 3-2024", Z("2023-12-01", "2024-03-31")),
    ("12-2023-3-2024", Z("2023-12-01", "2024-03-31")),
    ("Jan 2024 - Mär 2024", Z("2024-01-01", "2024-03-31")),
    ("Jan 2024 – Feb 2024", Z("2024-01-01", "2024-02-29")),
    ("1.1.2024-15.2.2024", Z("2024-01-01", "2024-02-15")),
    ("2024-01-01 - 2024-02-15", Z("2024-01-01", "2024-02-15")),
    ("2024-01-01 bis 2024-02-15", Z("2024-01-01", "2024-02-15")),
    ("Q1 2024 - Q2 2024", Z("2024-01-01", "2024-06-30")),
    ("2023 - 3/2024", Z("2023-01-01", "2024-03-31")),
    # vertauscht
    ("2006-2004", Z("2004-01-01", "2006-12-31")),
    ("2006 bis 2004", Z("2004-01-01", "2006-12-31")),
    ("3/2024 - 12/2023", Z("2023-12-01", "2024-03-31")),
    # offen
    ("ab 2020", Z("2020-01-01", None)),
    ("seit 2020", Z("2020-01-01", None)),
    ("ab 12/2023", Z("2023-12-01", None)),
    ("Ab Mai 2021", Z("2021-05-01", None)),
    ("2020-", Z("2020-01-01", None)),
    ("2020 -", Z("2020-01-01", None)),
    ("2020 –", Z("2020-01-01", None)),
    ("1.1.2024-", Z("2024-01-01", None)),
    ("bis 12/2023", Z(None, "2023-12-31")),
    ("bis 2023", Z(None, "2023-12-31")),
    ("bis 3.5.2024", Z(None, "2024-05-03")),
    ("-2023", Z(None, "2023-12-31")),
    ("- 2023", Z(None, "2023-12-31")),
    ("ab 2020 bis 2022", Z("2020-01-01", "2022-12-31")),
    # leer
    ("", Z(None, None)),
    ("   ", Z(None, None)),
])
def test_parse_zeitraum(text, erwartet):
    assert parse_zeitraum(text, HEUTE) == erwartet


@pytest.mark.parametrize("text,jahr", [
    ("24", None),
    ("1/00", 2000), ("1/24", 2024), ("1/27", 2027), ("1/28", 1928), ("1/98", 1998), ("1/99", 1999),
])
def test_zweistellige_jahre(text, jahr):
    ergebnis = parse_zeitraum(text, HEUTE)
    if jahr is None:
        assert isinstance(ergebnis, Fehler)
    else:
        assert ergebnis.von == date(jahr, 1, 1)


def test_zweistellige_jahre_folgen_dem_heutigen_jahr():
    assert parse_zeitraum("1/30", date(2029, 1, 1)).von.year == 2030
    assert parse_zeitraum("1/30", date(2026, 1, 1)).von.year == 1930


@pytest.mark.parametrize("text", [
    "abc", "13/2024", "0/2024", "31.2.2024", "30.2.24", "2024-13-01", "99999", "1800", "2200",
    "2004-2006-2008", "bis", "ab", "ab abc", "bis abc", "2004 bis", "bis bis 2004", "2004 bis 2005 bis 2006",
    "Q5 2024", "5. Quartal 2024", "Foo 2024", "-", "--", "2004-abc", "3.5", "2004-06", "3.13.", "32.1.",
])
def test_parse_zeitraum_unlesbar(text):
    ergebnis = parse_zeitraum(text, HEUTE)
    assert isinstance(ergebnis, Fehler)
    assert beschreibe(ergebnis) == "nicht erkannt – z. B. 2024, 12/2024, Jan 2024, 2004-2006"


def test_heute_standard_ist_das_aktuelle_datum():
    assert parse_zeitraum("3.5.").von == date(date.today().year, 5, 3)


@pytest.mark.parametrize("text,erwartet", [
    ("3.5.24", "2024-05-03"),
    ("03.05.2024", "2024-05-03"),
    ("3. Mai 2024", "2024-05-03"),
    ("3 mai 2024", "2024-05-03"),
    ("2024-05-03", "2024-05-03"),
    ("29.2.2024", "2024-02-29"),
    ("3.5.", "2026-05-03"),
    ("  1/2/24 ", "2024-02-01"),
])
def test_parse_tag(text, erwartet):
    assert parse_tag(text, HEUTE) == D(erwartet)


@pytest.mark.parametrize("text", ["2024", "12/2024", "Mai 2024", "Q2 2024", "2004-2006", "ab 2020", "abc", "", "31.4.2024"])
def test_parse_tag_ungueltig(text):
    assert isinstance(parse_tag(text, HEUTE), Fehler)


def test_parse_tag_hinweise_unterscheiden_ungenau_und_unlesbar():
    assert "ganzen Tag" in beschreibe(parse_tag("2024", HEUTE))
    assert "nicht erkannt" in beschreibe(parse_tag("abc", HEUTE))


@pytest.mark.parametrize("text,hinweis", [
    ("2004-2006", "= 01.01.2004 – 31.12.2006"),
    ("ab 2020", "= ab 01.01.2020"),
    ("bis 12/2023", "= bis 31.12.2023"),
    ("2024", "= 01.01.2024 – 31.12.2024"),
    ("3.5.2024", "= 03.05.2024"),
    ("", ""),
])
def test_beschreibe(text, hinweis):
    assert beschreibe(parse_zeitraum(text, HEUTE)) == hinweis


def test_beschreibe_tag():
    assert beschreibe(date(2024, 5, 3)) == "= 03.05.2024"


@pytest.mark.parametrize("von,bis", [
    ("2024-01-01", "2024-03-31"), ("2020-01-01", None), (None, "2023-12-31"), ("2024-05-03", "2024-05-03"), (None, None),
])
def test_formatiere_ist_wieder_lesbar(von, bis):
    erwartet = Z(von, bis)
    assert parse_zeitraum(formatiere(erwartet.von, erwartet.bis), HEUTE) == erwartet or (
        # eine Einzelangabe ist ihr voller Zeitraum - hier ein einzelner Tag
        erwartet.von == erwartet.bis
    )

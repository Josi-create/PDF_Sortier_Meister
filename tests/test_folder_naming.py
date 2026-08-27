"""Issue #42: Dateiname aus der Ordnerstruktur aufbauen."""
from datetime import date, datetime
from pathlib import PurePath

from src.core.folder_naming import (
    DEFAULT_TEMPLATE,
    build_folder_based_name,
    coerce_date,
    extract_folder_numbers,
    split_leading_date,
)


# --- extract_folder_numbers -----------------------------------------------

def test_extract_folder_numbers_chain():
    assert extract_folder_numbers("JK 069-03-05-Auftrag") == "069-03-05"
    assert extract_folder_numbers("JK 069-Umbau Kellermannstrasse") == "069"


def test_extract_folder_numbers_without_numbers():
    assert extract_folder_numbers("Steuer Unterlagen") == ""


# --- split_leading_date ---------------------------------------------------

def test_split_leading_date_iso():
    d, text = split_leading_date("2026-05-12_Rechnung Elektro Meier")
    assert d == date(2026, 5, 12)
    assert text == "Rechnung Elektro Meier"


def test_split_leading_date_compact():
    d, text = split_leading_date("20260512-Rechnung")
    assert d == date(2026, 5, 12)
    assert text == "Rechnung"


def test_split_leading_date_none():
    d, text = split_leading_date("Rechnung Elektro Meier")
    assert d is None
    assert text == "Rechnung Elektro Meier"


def test_split_leading_date_invalid_date_kept_as_text():
    d, text = split_leading_date("2026-13-99_Rechnung")
    assert d is None
    assert text == "2026-13-99_Rechnung"


# --- coerce_date ----------------------------------------------------------

def test_coerce_date():
    assert coerce_date(datetime(2026, 5, 12, 8, 30)) == date(2026, 5, 12)
    assert coerce_date(date(2026, 5, 12)) == date(2026, 5, 12)
    assert coerce_date("2026-05-12") is None
    assert coerce_date(None) is None


# --- build_folder_based_name ----------------------------------------------

def test_issue_example_format():
    """Das Beispiel aus Issue #42: JK 069-03-05-09-20260512-Rechnung."""
    name = build_folder_based_name(
        "2026-05-12_Rechnung.pdf",
        PurePath("C:/Ablage/JK 069-Umbau/JK 069-03-05-09-Auftrag"),
        "JK 069-Umbau/JK 069-03-05-09-Auftrag",
        template=DEFAULT_TEMPLATE,
        initials="JK",
    )
    assert name == "JK 069-03-05-09-20260512-Rechnung.pdf"


def test_fallback_date_used_when_name_has_none():
    name = build_folder_based_name(
        "Rechnung.pdf",
        PurePath("JK 069-01-Firmen"),
        "JK 069-01-Firmen",
        initials="JK",
        fallback_date=date(2026, 5, 12),
    )
    assert name == "JK 069-01-20260512-Rechnung.pdf"


def test_missing_date_collapses_separators():
    name = build_folder_based_name(
        "Rechnung.pdf",
        PurePath("JK 069-01-Firmen"),
        "JK 069-01-Firmen",
        initials="JK",
    )
    assert name == "JK 069-01-Rechnung.pdf"


def test_folder_without_numbers_collapses_separators():
    name = build_folder_based_name(
        "2026-05-12_Rechnung.pdf",
        PurePath("Steuer/Banken"),
        "Steuer/Banken",
        initials="JK",
    )
    assert name == "JK-20260512-Rechnung.pdf"


def test_ordnerpfad_placeholder():
    name = build_folder_based_name(
        "2026-05-12_Rechnung.pdf",
        PurePath("Steuer 2026/Banken"),
        "Steuer 2026/Banken",
        template="{initialen}-{datum_iso}-{ordnerpfad}-{text}",
        initials="JK",
    )
    assert name == "JK-2026-05-12-Steuer 2026-Banken-Rechnung.pdf"


def test_forbidden_characters_removed():
    name = build_folder_based_name(
        "2026-05-12_Rechnung: Meier?.pdf",
        PurePath("JK 069-01-Firmen"),
        "JK 069-01-Firmen",
        initials="JK",
    )
    assert name == "JK 069-01-20260512-Rechnung Meier.pdf"


def test_broken_template_keeps_original_name():
    name = build_folder_based_name(
        "2026-05-12_Rechnung.pdf",
        PurePath("JK 069-01-Firmen"),
        "JK 069-01-Firmen",
        template="{unbekannt}-{text}",
        initials="JK",
    )
    assert name == "2026-05-12_Rechnung.pdf"


def test_name_without_pdf_extension():
    name = build_folder_based_name(
        "2026-05-12_Rechnung",
        PurePath("JK 069-01-Firmen"),
        "JK 069-01-Firmen",
        initials="JK",
    )
    assert name == "JK 069-01-20260512-Rechnung.pdf"

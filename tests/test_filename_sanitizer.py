"""Tests fuer src/utils/filename_sanitizer.py (kein Qt noetig)."""
import pytest

from src.utils.filename_sanitizer import (
    find_problem_chars,
    sanitize_filename,
    strip_pdf_extension,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Klammeraffe und Punkte (E-Mail im Namen)
        (
            "Haerle-Wack_2013-04-23_Arbeitsuchendmeldung_kathrin.haerle@web.de.pdf",
            "Haerle-Wack_2013-04-23_Arbeitsuchendmeldung_Kathrin_Haerle.pdf",
        ),
        # Punkt als Doppel-Endung / Versionsnummer
        ("Rechnung.v1.2.pdf", "Rechnung_v1_2.pdf"),
        ("Rechnung.PDF", "Rechnung.pdf"),
        # Windows-verbotene Zeichen
        ('Angebot<1>:"x"/y\\z|?*.pdf', "Angebot_1_x_y_z.pdf"),
        # Umlaute, Akzente, Leerzeichen
        ("Überweisung Müller Straße.pdf", "Ueberweisung Mueller Strasse.pdf"),
        ("Résumé café.pdf", "Resume cafe.pdf"),
        # Mehrfach-Unterstriche, Raender, Unterstrich um Bindestrich
        ("__Foo___Bar__.pdf", "Foo_Bar.pdf"),
        ("Foo _ - _ Bar.pdf", "Foo-Bar.pdf"),
        # Endung wird angehaengt, Whitespace am Rand ignoriert
        ("  Vertrag 2024  ", "Vertrag 2024.pdf"),
        # Leerzeichen bleiben (Bestandssysteme wie "JK 069-01-01-20260512-Rechnung")
        ("JK 069-01-01-20260512-Rechnung", "JK 069-01-01-20260512-Rechnung.pdf"),
        ("JK  2026-05-12 - Rechnung _ Telekom", "JK 2026-05-12-Rechnung_Telekom.pdf"),
        ("Tab\tund\nUmbruch", "Tab_und_Umbruch.pdf"),
        # Reservierte Windows-Namen
        ("CON.pdf", "CON_.pdf"),
        ("nul", "nul_.pdf"),
        # Abschliessender Punkt/Leerzeichen (auf Windows verboten)
        ("Scan 001. .pdf", "Scan 001.pdf"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_sanitize_is_idempotent():
    raw = "kathrin.haerle@web.de / Überweisung.pdf"
    once = sanitize_filename(raw)
    assert sanitize_filename(once) == once


def test_sanitize_without_pdf_suffix():
    assert sanitize_filename("a.b@c.pdf", ensure_pdf=False) == "a_b_c"


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Person aus Lokalteil
        ("Meldung_kathrin.haerle@web.de.pdf", "Meldung_Kathrin_Haerle.pdf"),
        ("Meldung_max-mustermann@example.com", "Meldung_Max_Mustermann.pdf"),
        ("Meldung_m.mueller2024@gmx.de", "Meldung_M_Mueller.pdf"),
        ("Meldung_hans+tag@web.de", "Meldung_Hans.pdf"),
        # Generischer Lokalteil -> Organisation aus Domain
        ("Rechnung_info@huk-coburg.de", "Rechnung_Huk-Coburg.pdf"),
        ("Rechnung_kontakt@mail.stadtwerke-muenster.de", "Rechnung_Stadtwerke-Muenster.pdf"),
        # Generisch + Freemailer -> nichts Brauchbares, Adresse entfaellt
        ("Rechnung_info@web.de", "Rechnung.pdf"),
        ("info@gmail.com", ""),
        # Zwei Adressen
        ("a.b@x.de_und_c.d@y.org", "A_B_und_C_D.pdf"),
    ],
)
def test_email_addresses_become_names(raw, expected):
    assert sanitize_filename(raw) == expected


def test_contains_email():
    from src.utils.filename_sanitizer import contains_email
    assert contains_email("x_kathrin.haerle@web.de")
    assert not contains_email("x_kathrin_haerle")
    assert not contains_email("a@b")


@pytest.mark.parametrize("raw", ["", "   ", ".pdf", "@@..", "___.pdf"])
def test_sanitize_empty_or_only_invalid_returns_empty(raw):
    assert sanitize_filename(raw) == ""


def test_strip_pdf_extension():
    assert strip_pdf_extension("Rechnung.pdf") == "Rechnung"
    assert strip_pdf_extension("Rechnung.PDF") == "Rechnung"
    assert strip_pdf_extension("kathrin.pdfx") == "kathrin.pdfx"
    assert strip_pdf_extension("kathrin.pdf.pdf") == "kathrin.pdf"


def test_find_problem_chars_ignores_pdf_suffix_and_dedupes():
    assert find_problem_chars("Rechnung_2024.pdf") == []
    assert find_problem_chars("a.b.c@d e?.pdf") == [".", "@", "?"]
    assert find_problem_chars("Tab\there") == ["\t"]


def test_umlauts_are_not_reported_as_problem():
    # Umlaute werden ersetzt, aber nicht als "Problemzeichen" gemeldet
    assert find_problem_chars("Überweisung.pdf") == []
    assert sanitize_filename("Überweisung.pdf") == "Ueberweisung.pdf"

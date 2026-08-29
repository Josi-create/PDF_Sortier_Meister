"""Tests fuer src/core/filename_placeholders.py (kein Qt)."""
import pytest

from src.core.filename_placeholders import (
    PRESETS,
    describe_for_prompt,
    find_placeholders,
    legend_html,
    migrate_legacy_pattern,
    render_example,
)


def test_find_placeholders_order_and_dedupe():
    assert find_placeholders("{datum}_{kontakt}_{Datum}_{lieferant}") == [
        "datum", "kontakt", "lieferant",
    ]
    assert find_placeholders("Freitext ohne Klammern") == []
    assert find_placeholders("") == []


@pytest.mark.parametrize(
    "legacy, expected",
    [
        # Alte Presets 1:1
        ("YYYY-MM-DD_Rechnung_Kontakt_Betreff", "{datum}_{kategorie}_{kontakt}_{betreff}"),
        (
            "PROJEKTNUMMER_INITIALIEN/AKTENZEICHEN_YYYY-MM-DD_Betreff_Kontakt",
            "{initialen}_{aktenzeichen}_{datum}_{betreff}_{kontakt}",
        ),
        # Freitext mit Grosswoertern
        (
            "YYYY-MM-DD_Lieferant_Auftragsnummer_Kurzbeschreibung",
            "{datum}_{kontakt}_{aktenzeichen}_{betreff}",
        ),
        ("Datum_Absender_Betreff", "{datum}_{kontakt}_{betreff}"),
        ("Initialen/Aktenzeichen_YYYY", "{initialen}_{aktenzeichen}_{jahr}"),
        # Literale Woerter bleiben
        ("YYYY-MM-DD_Rechnung_Kontakt", "{datum}_Rechnung_{kontakt}"),
        # Schon neue Syntax: unveraendert
        ("{datum}_{kontakt}", "{datum}_{kontakt}"),
        ("", ""),
    ],
)
def test_migrate_legacy_pattern(legacy, expected):
    assert migrate_legacy_pattern(legacy) == expected


def test_render_example_with_defaults():
    assert (
        render_example("{datum}_{kategorie}_{kontakt}_{betreff}")
        == "2024-03-12_Behoerde_Agentur-fuer-Arbeit_Arbeitsuchendmeldung.pdf"
    )


def test_render_example_unknown_placeholder_and_values():
    assert render_example("{lieferant}_{datum}") == "Lieferant_2024-03-12.pdf"
    out = render_example(
        "{initialen}_{datum}_{kontakt}",
        {"initialen": "JHW", "kontakt": "Stadtwerke Münster", "datum": ""},
    )
    # leerer Wert -> Beispielwert; Leerzeichen im Wert -> "-"
    assert out == "JHW_2024-03-12_Stadtwerke-Muenster.pdf"


def test_render_example_sanitizes():
    assert render_example("{kontakt}/{datum}") == "Agentur-fuer-Arbeit_2024-03-12.pdf"


def test_describe_for_prompt_lists_placeholders_and_example():
    text = describe_for_prompt("{initialen}_{datum}_{kontakt}_{lieferant}", initials="JW")
    assert "BENUTZERDEFINIERTES DATEINAMEN-MUSTER" in text
    assert "    {initialen}_{datum}_{kontakt}_{lieferant}" in text
    assert "- {initialen}:" in text and "Verwende genau: JW" in text
    assert "- {kontakt}:" in text and "nie eine E-Mail-Adresse" in text
    assert '- {lieferant}: frei nach der Bezeichnung "lieferant"' in text
    assert "Beispiel-Ergebnis: JW_2024-03-12_Agentur-fuer-Arbeit_Lieferant.pdf" in text


def test_describe_for_prompt_free_text_fallback():
    text = describe_for_prompt("Rechnung Telekom Monat")
    assert "Strukturvorlage" in text
    assert "Platzhalter:" not in text
    assert describe_for_prompt("") == ""


def test_presets_render_cleanly():
    for _name, pattern in PRESETS:
        if pattern:
            rendered = render_example(pattern)
            assert rendered.endswith(".pdf")
            assert "{" not in rendered


def test_legend_html_mentions_every_placeholder():
    html = legend_html()
    for key in ("datum", "kontakt", "betreff", "initialen", "aktenzeichen"):
        assert "{" + key + "}" in html


def test_render_example_keeps_pattern_spaces_and_derives_compact_date():
    # Sven-Schema: Leerzeichen nach den Initialen, Datum als JJJJMMTT
    assert render_example("{initialen} {datum_kompakt}-{betreff}", {"initialen": "JK"}) == (
        "JK 20240312-Arbeitsuchendmeldung.pdf"
    )
    out = render_example("{initialen} {datum_kompakt}-{jahr}", {"initialen": "JK", "datum": "2026-05-12"})
    assert out == "JK 20260512-2026.pdf"


def test_prompt_example_shows_space_from_pattern():
    text = describe_for_prompt("{initialen} {datum}-{betreff}", initials="JK")
    assert "Beispiel-Ergebnis: JK 2024-03-12-Arbeitsuchendmeldung.pdf" in text

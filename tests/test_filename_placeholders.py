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


# --------------------------------------------------------------------- #
# Issue #99: Rendern mit echten Werten + Metadaten-Zuordnung + Auswahlliste
# --------------------------------------------------------------------- #

from src.core.filename_placeholders import (  # noqa: E402
    PATTERN_CHOICE_SETTINGS,
    pattern_choices,
    placeholder_values_from_metadata,
    render_with_values,
)


def test_render_with_values_uses_only_real_values():
    name = render_with_values(
        "{datum}_{kategorie}_{kontakt}_{betreff}",
        {"datum": "2024-01-31", "kategorie": "Rechnung", "kontakt": "Testfirma GmbH",
         "betreff": "Beratung im Maerz"},
    )
    assert name == "2024-01-31_Rechnung_Testfirma-GmbH_Beratung-im-Maerz.pdf"


@pytest.mark.parametrize(
    "pattern, values, expected",
    [
        # Fehlender Wert am Ende: Trennzeichen davor faellt weg
        ("{datum}_{kontakt}_{betreff}", {"datum": "2024-01-31", "kontakt": "Firma"},
         "2024-01-31_Firma.pdf"),
        # Fehlender Wert in der Mitte
        ("{datum}_{kategorie}_{kontakt}", {"datum": "2024-01-31", "kontakt": "Firma"},
         "2024-01-31_Firma.pdf"),
        # Fehlender Wert am Anfang: Trennzeichen danach faellt weg
        ("{initialen} {datum}-{betreff}", {"datum": "2024-01-31", "betreff": "Miete"},
         "2024-01-31-Miete.pdf"),
        # Abgeleitete Datumsformen
        ("{jahr}_{datum_kompakt}", {"datum": "2024-01-31"}, "2024_20240131.pdf"),
        # Unbekannter Platzhalter ohne Wert wird NICHT als Bezeichnung eingesetzt
        ("{datum}_{lieferant}", {"datum": "2024-01-31"}, "2024-01-31.pdf"),
    ],
)
def test_render_with_values_drops_missing_placeholders(pattern, values, expected):
    assert render_with_values(pattern, values) == expected


def test_render_with_values_without_any_value_is_empty():
    assert render_with_values("{datum}_{kontakt}", {}) == ""
    assert render_with_values("{datum}_{kontakt}", None) == ""
    assert render_with_values("{datum}_{kontakt}", {"betreff": "x"}) == ""
    assert render_with_values("", {"datum": "2024-01-31"}) == ""


def test_placeholder_values_from_metadata_maps_canonical_keys():
    values = placeholder_values_from_metadata(
        {
            "korrespondent": "Testfirma GmbH",
            "subject": "Rechnung",
            "description": "Rechnung fuer Beratung im Maerz 2024 inkl. Fahrtkosten",
            "betrag_brutto": "123,45",
            "waehrung": "EUR",
            "steuerjahr": "2024",
        },
        doc_date="2024-01-31",
        initials="JW",
    )
    assert values == {
        "datum": "2024-01-31",
        "jahr": "2024",
        "kontakt": "Testfirma GmbH",
        "kategorie": "Rechnung",
        "betreff": "Rechnung fuer Beratung im",
        "betrag": "123,45 EUR",
        "initialen": "JW",
    }


def test_placeholder_values_from_metadata_accepts_legacy_keys_and_empty():
    assert placeholder_values_from_metadata(None) == {}
    values = placeholder_values_from_metadata({"beschreibung": "Mietvertrag Wohnung", "category": "Vertrag"})
    assert values == {"betreff": "Mietvertrag Wohnung", "kategorie": "Vertrag"}


def test_pattern_choices_presets_and_custom_settings_pattern():
    choices = pattern_choices("")
    assert choices[0] == PRESETS[0]
    assert all(pattern is not None for _n, pattern in choices)
    assert [p for _n, p in choices[1:]] == [p for _n, p in PRESETS[1:] if p]

    # Muster aus den Einstellungen, das keiner Vorlage entspricht -> eigener Eintrag
    custom = pattern_choices("{datum}_{lieferant}")
    assert custom[1] == (PATTERN_CHOICE_SETTINGS, "{datum}_{lieferant}")
    # Vorlagen-Muster in den Einstellungen -> kein Doppel-Eintrag
    assert pattern_choices("{datum}_{kategorie}_{kontakt}_{betreff}") == choices
    # Altes Grosswort-Muster wird zuerst migriert
    assert pattern_choices("YYYY-MM-DD_Rechnung_Kontakt_Betreff") == choices


def test_custom_patterns_load_and_join_choices():
    from src.core.filename_placeholders import PRESET_CUSTOM, all_presets, load_custom_patterns

    raw = [
        {"name": "Mieter", "pattern": "{jahr}_{kontakt}_Miete"},
        {"name": "mieter", "pattern": "doppelt"},          # Name doppelt -> weg
        {"name": "", "pattern": "{datum}"},                 # ohne Name -> weg
        {"name": "Leer", "pattern": ""},                    # ohne Muster -> weg
        "kaputt",
    ]
    custom = load_custom_patterns(raw)
    assert custom == [("Mieter", "{jahr}_{kontakt}_Miete")]

    presets = all_presets(custom)
    assert presets[0] == PRESETS[0]
    assert ("Mieter", "{jahr}_{kontakt}_Miete") in presets
    assert presets[-1] == (PRESET_CUSTOM, None)

    choices = pattern_choices("", custom)
    assert choices[-1] == ("Mieter", "{jahr}_{kontakt}_Miete")
    # Gespeichertes Muster = Einstellungs-Muster: kein Extra-Eintrag "Eigenes Muster"
    assert PATTERN_CHOICE_SETTINGS not in [n for n, _p in pattern_choices("{jahr}_{kontakt}_Miete", custom)]
    # Gespeichertes Muster gleich einer eingebauten Vorlage: nur einmal
    dup = [("Kopie", PRESETS[1][1])]
    assert [p for _n, p in pattern_choices("", dup)].count(PRESETS[1][1]) == 1


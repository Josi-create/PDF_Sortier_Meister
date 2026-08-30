"""Issues #109/#110: Korrespondenten im Text wiederfinden, Kategorie-Auswahl."""
from src.core.korrespondent_match import find_known_korrespondent
from src.core.metadata_choices import DEFAULT_CATEGORIES, category_choices

TEXT = (
    "Commerzbank AG - Depotauszug per 31.12.2024\n"
    "Kunde: Johannes Wack\nIhre Ansprechpartnerin: Frau Müller, Stadtwerke-Kundencenter"
)


def test_known_name_is_found_case_insensitive_as_whole_phrase():
    entries = [{"name": "Stadtwerke München", "aliases": ["SWM"]},
               {"name": "commerzbank", "aliases": []}]
    assert find_known_korrespondent(TEXT, entries) == "commerzbank"
    # "Stadtwerke" allein ist kein Alias, "Stadtwerke-Kundencenter" kein Wortgrenzen-Treffer
    assert find_known_korrespondent("Stadtwerke-Kundencenter", entries) is None
    assert find_known_korrespondent("SWM Rechnung", entries) == "Stadtwerke München"


def test_longest_match_wins_then_list_order():
    entries = [{"name": "Bank", "aliases": []},                      # zu kurz/generisch, aber 4 Zeichen
               {"name": "Commerzbank AG", "aliases": []},
               {"name": "Commerzbank", "aliases": []}]
    assert find_known_korrespondent(TEXT, entries) == "Commerzbank AG"
    # Gleich lange Treffer: der zuerst gelistete (nach Haeufigkeit) gewinnt
    entries = [{"name": "Wack", "aliases": []}, {"name": "Frau", "aliases": []}]
    assert find_known_korrespondent(TEXT, entries) == "Wack"


def test_no_text_or_short_names_give_none():
    assert find_known_korrespondent("", [{"name": "Commerzbank"}]) is None
    assert find_known_korrespondent(TEXT, [{"name": "AG"}, {"name": ""}]) is None
    assert find_known_korrespondent(TEXT, []) is None


def test_category_choices_merge_db_and_defaults():
    assert category_choices([]) == list(DEFAULT_CATEGORIES)[:10]
    choices = category_choices(["Rechnung", "Mietvertrag", "rechnung", "", "Notar"])
    assert choices[:3] == ["Rechnung", "Mietvertrag", "Notar"]
    assert "Vertrag" in choices and len(choices) == 10
    assert choices.count("Rechnung") == 1
    assert category_choices(["A", "B"], limit=3) == ["A", "B", "Rechnung"]

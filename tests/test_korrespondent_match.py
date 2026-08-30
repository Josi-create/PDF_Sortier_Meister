"""Issues #109/#110: Korrespondenten im Text wiederfinden, Kategorie-Auswahl."""
from src.core.korrespondent_match import find_known_korrespondent
from src.core.metadata_choices import DEFAULT_CATEGORIES, category_choices, normalize_for_field, remember_category

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


def test_category_choices_recent_first_then_db_then_defaults():
    assert category_choices([], []) == list(DEFAULT_CATEGORIES)[:10]
    choices = category_choices(["Liste", "Rechnung"], ["Rechnung", "Mietvertrag", "rechnung", "", "Notar"])
    assert choices[:4] == ["Liste", "Rechnung", "Mietvertrag", "Notar"]
    assert "Vertrag" in choices and len(choices) == 10
    assert choices.count("Rechnung") == 1
    assert category_choices(["A"], ["B"], limit=3) == ["A", "B", "Rechnung"]


def test_category_choices_drop_long_index_junk_but_keep_recent():
    junk = "Nebenkosten Schmutzwassergebühr"
    assert junk not in category_choices([], [junk, "Steuer"])
    assert "Drei Wort Kategorie" not in category_choices([], ["Drei Wort Kategorie"])
    # Was der Nutzer selbst verwendet hat, bleibt - egal wie lang
    assert category_choices([junk], [])[0] == junk


def test_remember_category_is_mru_and_capped():
    recent = remember_category(["Rechnung", "Vertrag"], "Liste")
    assert recent == ["Liste", "Rechnung", "Vertrag"]
    assert remember_category(recent, "vertrag") == ["vertrag", "Liste", "Rechnung"]
    assert remember_category(recent, "  ") == recent
    many = remember_category([f"K{i}" for i in range(20)], "Neu")
    assert len(many) == 15 and many[0] == "Neu"


def test_normalize_for_field_cleans_amounts_iban_year():
    assert normalize_for_field("iban", "DE89 3704 0044 0532 0130 00") == "DE89370400440532013000"
    assert normalize_for_field("betrag_brutto", "Gesamt: 1.234,56 €") == "Gesamt: 1.234,56"
    assert normalize_for_field("betrag_netto", "EUR 99,00") == "99,00"
    assert normalize_for_field("mwst_satz", "19 %") == "19"
    assert normalize_for_field("steuerjahr", "Abrechnung 2024/2025") == "2024"
    assert normalize_for_field("steuerjahr", "kein Jahr") == "kein Jahr"
    assert normalize_for_field("waehrung", "€") == "EUR"
    assert normalize_for_field("korrespondent", "  Commerzbank 	 AG ") == "Commerzbank AG"


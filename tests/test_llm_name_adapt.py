"""Issue #113: KI-Dateinamen an geaenderte Metadaten anpassen (ohne Qt)."""
from src.core.llm_name_adapt import adapt_llm_filename, replace_token


def test_replace_whole_token_only():
    assert replace_token("2026-03-15_Rechnung_Muster.pdf", "Rechnung", "Mahnung") == "2026-03-15_Mahnung_Muster.pdf"
    assert replace_token("2026-03-15_Rechnungen_Muster.pdf", "Rechnung", "Mahnung") == "2026-03-15_Rechnungen_Muster.pdf"


def test_replace_is_case_insensitive_and_handles_multiword_values():
    assert replace_token("Sonstiges_Muster-GmbH.pdf", "muster gmbh", "Beispiel AG") == "Sonstiges_Beispiel_AG.pdf"
    assert replace_token("JK 2026-03-15-Muster GmbH.pdf", "Muster GmbH", "Beispiel AG") == "JK 2026-03-15-Beispiel AG.pdf"


def test_adapt_replaces_old_category_and_fallback_tokens():
    assert adapt_llm_filename(
        "2026-03-15_Sonstiges_Noten.pdf", {"subject": "Sonstiges"}, {"subject": "Klaviernoten"}
    ) == "2026-03-15_Klaviernoten_Noten.pdf"
    # KI lieferte keine Kategorie (normalize_llm_metadata verwirft "Unbekannt")
    assert adapt_llm_filename(
        "2026-03-15_Unbekannt_Bach.pdf", {}, {"subject": "Klaviernoten"}
    ) == "2026-03-15_Klaviernoten_Bach.pdf"


def test_adapt_replaces_korrespondent_and_leaves_rest():
    assert adapt_llm_filename(
        "2026-03-15_Rechnung_Testfirma-GmbH.pdf",
        {"subject": "Rechnung", "korrespondent": "Testfirma GmbH"},
        {"subject": "Rechnung", "korrespondent": "Beispiel AG"},
    ) == "2026-03-15_Rechnung_Beispiel_AG.pdf"


def test_adapt_without_changes_or_fields_is_identity():
    name = "2026-03-15_Rechnung_Testfirma.pdf"
    assert adapt_llm_filename(name, {"subject": "Rechnung"}, {"subject": "Rechnung"}) == name
    assert adapt_llm_filename(name, {"subject": "Rechnung"}, {}) == name
    assert adapt_llm_filename("", {}, {"subject": "X"}) == ""

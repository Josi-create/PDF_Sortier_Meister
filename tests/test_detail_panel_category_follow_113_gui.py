"""Issue #113: Eine Metadaten-Eingabe zieht den Dateinamen-Vorschlag sofort nach.

Solange der Name aus der Liste stammt (oberste Zeile, Klick, KI-Ergebnis),
folgt er der Eingabe in Kategorie/Korrespondent. Ein getippter Name bleibt.
"""
from PyQt6.QtTest import QTest

from src.gui.rename_dialog import RenameSuggestion

from tests.test_llm_metadata_extraction import provider  # noqa: F401 - Fixture

from tests.test_detail_panel_pattern_suggestions_gui import (  # noqa: F401
    RECHNUNGEN, _ki_suggestion, _panel, _reasons, _rows, _select,
)


def _ki_sonstiges():
    return RenameSuggestion(
        name="2024-01-31_Sonstiges_Noten.pdf", reason="KI-Vorschlag", confidence=0.9,
        metadata={"subject": "Sonstiges", "korrespondent": "Musikverlag"},
    )


def test_category_edit_updates_ki_row_and_name(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, [_ki_sonstiges()])
    assert panel.name_input.text() == "2024-01-31_Sonstiges_Noten"
    assert panel._name_from_list

    cat = panel._metadata_inputs["subject"]
    cat.setText("")
    QTest.keyClicks(cat, "Klaviernoten")

    assert _rows(panel)[0].startswith("2024-01-31_Klaviernoten_Noten.pdf")
    assert panel.name_input.text() == "2024-01-31_Klaviernoten_Noten"
    assert not panel.has_user_edits() or panel._metadata_source == "user"
    assert panel._auto_name == "2024-01-31_Klaviernoten_Noten"


def test_pattern_row_follows_korrespondent_edit(qtbot, monkeypatch, tmp_path):
    panel, cfg = _panel(qtbot, monkeypatch, tmp_path, filename_pattern=RECHNUNGEN)
    _select(panel, tmp_path, [])            # nur Muster-Zeilen
    assert _reasons(panel)[0].startswith("Muster")
    assert panel.name_input.text() == "2024-01-31_Rechnung"

    korr = panel._metadata_inputs["korrespondent"]
    QTest.keyClicks(korr, "Beispiel AG")

    assert panel.name_input.text() == "2024-01-31_Rechnung_Beispiel-AG"


def test_typed_name_is_not_overwritten(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, [_ki_sonstiges()])

    panel.name_input.clear()
    QTest.keyClicks(panel.name_input, "Mein eigener Name")
    assert not panel._name_from_list

    QTest.keyClicks(panel._metadata_inputs["subject"], "X")

    assert panel.name_input.text() == "Mein eigener Name"
    # Liste rendert trotzdem neu
    assert "SonstigesX" in _rows(panel)[0] or "X" in _rows(panel)[0]


def test_clicked_row_stays_coupled_to_its_kind(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path, filename_pattern=RECHNUNGEN)
    _select(panel, tmp_path, [_ki_suggestion()])
    reasons = _reasons(panel)
    idx = reasons.index("Muster: Rechnungen & Belege")
    panel._on_suggestion_clicked(panel.suggestions_list.item(idx))
    assert panel.name_input.text().startswith("2024-01-31_Rechnung_Testfirma-GmbH")
    assert panel._name_from_list

    korr = panel._metadata_inputs["korrespondent"]
    korr.setText("")
    QTest.keyClicks(korr, "Neue Firma")

    # Folgt der MUSTER-Zeile, nicht der KI-Zeile
    assert panel.name_input.text().startswith("2024-01-31_Rechnung_Neue-Firma")


def test_clear_resets_coupling(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, [_ki_sonstiges()])
    panel.clear()
    assert not panel._name_from_list and panel._name_kind is None
    # Kein Absturz bei Feld-Aenderung ohne PDF
    panel._on_metadata_user_edit("x")
    assert panel.name_input.text() == ""


def test_prompt_contains_rule_against_meaningless_names(provider):  # noqa: F811
    prompt = provider._build_filename_prompt(text="text", current_filename="scan.pdf")
    assert "Sonstiges" in prompt and "nie im Dateinamen" in prompt

"""Vorschlagsliste: letzte Zeile "Aktuellen Namen behalten" (manchmal besser als die KI)."""
from src.core.suggestion_order import CONFIG_KEY

from tests.test_llm_metadata_extraction import provider  # noqa: F401 - Fixture
from tests.test_detail_panel_pattern_suggestions_gui import (  # noqa: F401
    _ki_suggestion, _panel, _rows, _select,
)

BEHALTEN = "scan.pdf  [Aktuellen Namen behalten]"


def test_letzte_zeile_behaelt_den_namen(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, [_ki_suggestion()])
    rows = _rows(panel)
    assert rows[-1] == BEHALTEN
    assert panel.name_input.text() != "scan"  # oben steht weiter der KI-Vorschlag

    lst = panel.suggestions_list
    lst.itemClicked.emit(lst.item(lst.count() - 1))
    assert panel.name_input.text() == "scan"
    assert panel.get_new_name() == "scan.pdf"


def test_behalten_wird_nicht_nach_oben_gereiht(qtbot, monkeypatch, tmp_path):
    panel, cfg = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, [_ki_suggestion()])
    vorher = cfg.get(CONFIG_KEY, None)
    lst = panel.suggestions_list
    lst.itemClicked.emit(lst.item(lst.count() - 1))
    assert cfg.get(CONFIG_KEY, None) == vorher
    # naechstes Dokument: wieder der KI-Vorschlag oben und im Feld
    _select(panel, tmp_path, [_ki_suggestion()])
    assert _rows(panel)[0].startswith(_ki_suggestion().name)
    assert _rows(panel)[-1] == BEHALTEN


def test_bleibt_beim_aendern_der_metadaten(qtbot, monkeypatch, tmp_path):
    from PyQt6.QtTest import QTest
    panel, _ = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, [_ki_suggestion()])
    lst = panel.suggestions_list
    lst.itemClicked.emit(lst.item(lst.count() - 1))
    QTest.keyClicks(panel._metadata_inputs["subject"], "Steuer")
    assert panel.name_input.text() == "scan"


def test_office_datei_behaelt_namen_ohne_endung(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path)
    docx = tmp_path / "Brief an Bank.docx"
    docx.write_bytes(b"PK")
    panel.set_pdf(pdf_path=docx, suggestions=[_ki_suggestion()], extracted_text="x",
                  keywords=[], detected_date="2024-01-31")
    assert _rows(panel)[-1] == "Brief an Bank.pdf  [Aktuellen Namen behalten]"
    lst = panel.suggestions_list
    lst.itemClicked.emit(lst.item(lst.count() - 1))
    assert panel.name_input.text() == "Brief an Bank"

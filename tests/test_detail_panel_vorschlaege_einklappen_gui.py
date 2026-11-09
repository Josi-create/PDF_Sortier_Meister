"""Issue #146: Vorschlaege unter "Neuer Dateiname" einklappen.

Standard ist eingeklappt: nur Namensfeld, Vorschau und Warnung. Der Pfeil
"Vorschläge (n)" klappt Schalter-Zeile und Liste auf; der Zustand steht in
der Config und gilt fuer alle folgenden Dokumente. Der oberste Vorschlag
wird in beiden Zustaenden als Dateiname gesetzt.
"""
from src.gui.rename_dialog import RenameSuggestion
from tests.test_detail_panel_pattern_suggestions_gui import (
    _analysis_suggestions,
    _ki_suggestion,
    _panel,
    _reasons,
    _select,
)


def _sichtbar(widget) -> bool:
    """Sichtbar relativ zum Panel (das Panel selbst ist im Test nicht gezeigt)."""
    return widget.isVisibleTo(widget.window())


def test_standard_ist_eingeklappt(qtbot, monkeypatch, tmp_path):
    panel, cfg = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, [_ki_suggestion()] + _analysis_suggestions())

    assert not panel.suggestions_expanded
    assert not _sichtbar(panel.suggestions_list)
    assert not _sichtbar(panel.folder_naming_checkbox)
    assert not _sichtbar(panel.edit_pattern_btn)
    assert _sichtbar(panel.name_input)
    # Oberster Vorschlag ist trotzdem der Dateiname
    assert panel.name_input.text() == "2024-01-31_Rechnung_Testfirma"


def test_pfeil_klappt_auf_und_zu_und_schreibt_config(qtbot, monkeypatch, tmp_path):
    from PyQt6.QtCore import Qt
    panel, cfg = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, [_ki_suggestion()] + _analysis_suggestions())

    panel.suggestions_toggle.click()
    assert panel.suggestions_expanded
    assert panel.suggestions_toggle.arrowType() == Qt.ArrowType.DownArrow
    assert _sichtbar(panel.suggestions_list)
    assert _sichtbar(panel.folder_naming_checkbox)
    assert _sichtbar(panel.edit_pattern_btn)
    assert cfg.get("suggestions_expanded") is True
    assert (tmp_path / "config.json").exists()

    panel.suggestions_toggle.click()
    assert not panel.suggestions_expanded
    assert panel.suggestions_toggle.arrowType() == Qt.ArrowType.RightArrow
    assert not _sichtbar(panel.suggestions_list)
    assert cfg.get("suggestions_expanded") is False


def test_zustand_aus_config_beim_start(qtbot, monkeypatch, tmp_path):
    panel, _cfg = _panel(qtbot, monkeypatch, tmp_path, suggestions_expanded=True)
    assert panel.suggestions_expanded
    _select(panel, tmp_path, [_ki_suggestion()])
    assert _sichtbar(panel.suggestions_list)


def test_zustand_bleibt_ueber_dokumente(qtbot, monkeypatch, tmp_path):
    panel, _cfg = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, [_ki_suggestion()])
    panel.suggestions_toggle.click()
    panel.clear()
    _select(panel, tmp_path, _analysis_suggestions())
    assert panel.suggestions_expanded
    assert _sichtbar(panel.suggestions_list)


def test_zaehler_stimmt(qtbot, monkeypatch, tmp_path):
    panel, _cfg = _panel(qtbot, monkeypatch, tmp_path)
    assert panel.suggestions_toggle.text() == "Vorschläge (0)"

    _select(panel, tmp_path, [_ki_suggestion()] + _analysis_suggestions())
    n = len(_reasons(panel))
    assert panel.suggestions_list.count() == n + 1 > 2  # + "Aktuellen Namen behalten"
    assert panel.suggestions_toggle.text() == f"Vorschläge ({n})"

    panel.clear()
    assert panel.suggestions_toggle.text() == "Vorschläge (0)"


def test_zaehler_waechst_wenn_ki_vorschlag_eintrifft(qtbot, monkeypatch, tmp_path):
    panel, _cfg = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, _analysis_suggestions())
    vorher = panel.suggestions_list.count()
    assert not panel.suggestions_expanded

    # Neuladen mit KI-Vorschlag (wie _refresh_detail_panel_after_llm im Hauptfenster)
    _select(panel, tmp_path, [_ki_suggestion()] + _analysis_suggestions())
    # KI-Zeile plus Muster-Zeilen aus den KI-Metadaten
    nachher = panel.suggestions_list.count()
    assert nachher > vorher
    assert panel.suggestions_toggle.text() == f"Vorschläge ({nachher - 1})"  # ohne "behalten"
    assert not panel.suggestions_expanded  # bleibt eingeklappt


def test_ohne_vorschlaege_zaehler_null(qtbot, monkeypatch, tmp_path):
    panel, _cfg = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, [RenameSuggestion("2024-01-31.pdf", "Nur Datum", 0.3)], detected_date=None)
    assert panel.suggestions_toggle.text() == "Vorschläge (0)"


def test_klick_auf_vorschlag_im_aufgeklappten_zustand(qtbot, monkeypatch, tmp_path):
    panel, _cfg = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, [_ki_suggestion()] + _analysis_suggestions())
    panel.suggestions_toggle.click()

    idx = _reasons(panel).index("Automatisch erkannt")
    item = panel.suggestions_list.item(idx)
    panel.suggestions_list.itemClicked.emit(item)
    assert panel.name_input.text() == "Dokument"

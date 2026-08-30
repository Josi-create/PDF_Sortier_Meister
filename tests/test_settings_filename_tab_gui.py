"""Einstellungen > Dateinamen (Widgets liegen auf einem Tab, daher isHidden()
statt isVisibleTo()): Vorlage-Combo, Muster-Feld, Chips, Live-Vorschau,
Verschiebe-Modus; Initialen unter "Persoenliche Daten"."""
from PyQt6.QtTest import QTest


def _dialog(qtbot, monkeypatch, tmp_path, provider=None, **config_values):
    from src.utils import config as cfg_mod
    from src.utils.config import Config
    cfg = Config.__new__(Config)
    cfg.config_path = tmp_path / "config.json"
    cfg._config = {}
    cfg.load()
    for key, value in config_values.items():
        cfg.set(key, value, auto_save=False)
    monkeypatch.setattr(cfg_mod, "get_config", lambda: cfg)
    monkeypatch.setattr("src.gui.settings_dialog.get_config", lambda: cfg, raising=False)
    from src.gui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(example_values_provider=provider)
    qtbot.addWidget(dlg)
    return dlg, cfg


def test_default_state_is_standard_with_example_preview(qtbot, monkeypatch, tmp_path):
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    assert dlg.pattern_preset_combo.currentIndex() == 0
    assert dlg.pattern_input.text() == ""
    assert dlg.pattern_preview_label.text().startswith("KI entscheidet selbst")
    assert dlg.pattern_warning_label.isHidden()
    assert dlg.folder_naming_keep_radio.isChecked()
    assert not dlg.folder_naming_template_input.isEnabled()


def test_preset_fills_pattern_and_preview(qtbot, monkeypatch, tmp_path):
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    dlg.pattern_preset_combo.setCurrentIndex(1)
    dlg.pattern_preset_combo.activated.emit(1)
    assert dlg.pattern_input.text() == "{datum}_{kategorie}_{kontakt}_{betreff}"
    assert dlg.pattern_preview_label.text() == (
        "2024-03-12_Behoerde_Agentur-fuer-Arbeit_Arbeitsuchendmeldung.pdf"
    )
    assert dlg.pattern_preset_combo.currentIndex() == 1


def test_typing_switches_combo_to_custom(qtbot, monkeypatch, tmp_path):
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    QTest.keyClicks(dlg.pattern_input, "{datum}_{lieferant}")
    assert dlg.pattern_preset_combo.currentText() == "Eigenes Muster"
    assert dlg.pattern_preview_label.text() == "2024-03-12_Lieferant.pdf"


def test_chip_inserts_placeholder_at_cursor(qtbot, monkeypatch, tmp_path):
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    dlg.pattern_input.setText("{datum}_")
    dlg.pattern_input.setCursorPosition(len("{datum}_"))
    kontakt_chip = next(b for b in dlg.pattern_chip_buttons if b.text() == "{kontakt}")
    kontakt_chip.click()
    assert dlg.pattern_input.text() == "{datum}_{kontakt}"


def test_forbidden_chars_show_warning_but_preview_is_clean(qtbot, monkeypatch, tmp_path):
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    dlg.pattern_input.setText("{initialen}/{datum}.{kontakt}")
    assert not dlg.pattern_warning_label.isHidden()
    assert "/" in dlg.pattern_warning_label.text()
    assert "/" not in dlg.pattern_preview_label.text()


def test_initials_from_personal_tab_feed_preview(qtbot, monkeypatch, tmp_path):
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    dlg.pattern_input.setText("{initialen}_{datum}")
    dlg.owner_name_input.setText("Dr. med. Johannes Härle-Wack")
    assert dlg.owner_initials_input.placeholderText().startswith("JHW")
    assert dlg.pattern_preview_label.text() == "JHW_2024-03-12.pdf"
    dlg.owner_initials_input.setText("jw")
    assert dlg.pattern_preview_label.text() == "JW_2024-03-12.pdf"


def test_folder_naming_mode_enables_template_and_preview(qtbot, monkeypatch, tmp_path):
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    dlg.owner_initials_input.setText("JW")
    dlg.pattern_input.setText("{datum}_{betreff}")
    dlg.folder_naming_prefix_radio.setChecked(True)
    assert dlg.folder_naming_template_input.isEnabled()
    # Default-Vorlage "{initialen} {ordnernummern}-{datum}-{text}"
    assert dlg.folder_naming_preview_label.text() == "JW 069-03-05-20240312-Arbeitsuchendmeldung.pdf"
    dlg.folder_naming_keep_radio.setChecked(True)
    assert dlg.folder_naming_preview_label.text() == "2024-03-12_Arbeitsuchendmeldung.pdf"


def test_legacy_pattern_is_shown_in_new_syntax(qtbot, monkeypatch, tmp_path):
    dlg, _ = _dialog(
        qtbot, monkeypatch, tmp_path,
        filename_pattern="YYYY-MM-DD_Rechnung_Kontakt_Betreff",
    )
    assert dlg.pattern_input.text() == "{datum}_{kategorie}_{kontakt}_{betreff}"
    assert dlg.pattern_preset_combo.currentText() == "Rechnungen & Belege"


def test_save_writes_new_keys(qtbot, monkeypatch, tmp_path):
    dlg, cfg = _dialog(qtbot, monkeypatch, tmp_path)
    dlg.owner_initials_input.setText("jhw")
    dlg.pattern_input.setText("{initialen}_{datum}")
    dlg.folder_naming_prefix_radio.setChecked(True)
    dlg.folder_naming_template_input.setText("{ordnernummern}-{text}")
    dlg._save_settings()
    assert cfg.get("owner_initials") == "JHW"
    assert cfg.get("filename_pattern") == "{initialen}_{datum}"
    assert cfg.get("folder_naming_enabled") is True
    assert cfg.get("folder_naming_template") == "{ordnernummern}-{text}"
    assert "folder_naming_initials" not in cfg._config


def test_try_button_hidden_without_provider(qtbot, monkeypatch, tmp_path):
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    assert dlg.pattern_try_button.isHidden()


def test_try_button_renders_real_values(qtbot, monkeypatch, tmp_path):
    values = {"datum": "2013-04-23", "kontakt": "Agentur für Arbeit", "betreff": "Arbeitsuchendmeldung"}
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path, provider=lambda: values)
    assert not dlg.pattern_try_button.isHidden()
    dlg.owner_initials_input.setText("JW")
    dlg.pattern_input.setText("{initialen}_{datum}_{betreff}_{kontakt}")
    dlg.pattern_try_button.click()
    assert dlg.pattern_preview_label.text() == (
        "JW_2013-04-23_Arbeitsuchendmeldung_Agentur-fuer-Arbeit.pdf"
    )


def test_try_button_without_pdf_shows_hint(qtbot, monkeypatch, tmp_path):
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path, provider=lambda: None)
    dlg.pattern_try_button.click()
    assert "Keine PDF" in dlg.pattern_preview_label.text()


def test_connection_test_button_only_on_llm_tab(qtbot, monkeypatch, tmp_path):
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    assert dlg.test_button.isVisibleTo(dlg)
    dlg.tab_widget.setCurrentIndex(2)
    assert not dlg.test_button.isVisibleTo(dlg)
    dlg.tab_widget.setCurrentIndex(0)
    assert dlg.test_button.isVisibleTo(dlg)


def test_show_tab_selects_dateinamen(qtbot, monkeypatch, tmp_path):
    dialog, _ = _dialog(qtbot, monkeypatch, tmp_path)
    assert dialog.show_tab("Dateinamen")
    assert dialog.tab_widget.tabText(dialog.tab_widget.currentIndex()) == "Dateinamen"
    assert not dialog.show_tab("Gibt es nicht")


def test_legend_toggle_does_not_share_a_cell_with_a_chip(qtbot, monkeypatch, tmp_path):
    """Bei vollen Chip-Zeilen lag "Alle Platzhalter" ueber dem letzten Chip."""
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    grid = dlg.pattern_legend_toggle.parentWidget().layout()
    cells = {}
    for i in range(grid.count()):
        item = grid.itemAt(i)
        row, col, _rs, _cs = grid.getItemPosition(i)
        cells.setdefault((row, col), []).append(item.widget())
    toggle_cells = [c for c, ws in cells.items() if dlg.pattern_legend_toggle in ws]
    assert toggle_cells and len(cells[toggle_cells[0]]) == 1
    assert all(len(ws) == 1 for ws in cells.values())


def test_separator_buttons_insert_at_cursor(qtbot, monkeypatch, tmp_path):
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    dlg.pattern_input.setText("{datum}")
    dlg.pattern_input.setCursorPosition(len("{datum}"))
    by_text = {b.text(): b for b in dlg.pattern_sep_buttons}
    by_text["_"].click()
    by_text["-"].click()
    by_text["Leerzeichen"].click()
    assert dlg.pattern_input.text() == "{datum}_- "


def test_chip_click_auto_inserts_underscore_between_placeholders(qtbot, monkeypatch, tmp_path):
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    chip = {b.text(): b for b in dlg.pattern_chip_buttons}
    chip["{datum}"].click()
    assert dlg.pattern_input.text() == "{datum}"          # am Anfang kein Trenner
    chip["{kontakt}"].click()
    assert dlg.pattern_input.text() == "{datum}_{kontakt}"  # automatisch "_"
    sep = {b.text(): b for b in dlg.pattern_sep_buttons}
    sep["-"].click()
    chip["{betreff}"].click()
    assert dlg.pattern_input.text() == "{datum}_{kontakt}-{betreff}"  # eigener Trenner bleibt


def test_undo_button_removes_placeholder_with_its_separator(qtbot, monkeypatch, tmp_path):
    """Ein Klick zurueck je Chip-Klick - auch nach Doppelklick auf {jahr}."""
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    chip = {b.text(): b for b in dlg.pattern_chip_buttons}
    chip["{datum}"].click()
    chip["{jahr}"].click()
    chip["{jahr}"].click()
    assert dlg.pattern_input.text() == "{datum}_{jahr}_{jahr}"
    dlg.pattern_undo_btn.click()
    assert dlg.pattern_input.text() == "{datum}_{jahr}"
    dlg.pattern_undo_btn.click()
    assert dlg.pattern_input.text() == "{datum}"
    # Getippter Text ohne Trenner: nur der Platzhalter geht weg
    dlg.pattern_input.setText("Akte{datum}")
    dlg.pattern_input.setCursorPosition(len("Akte{datum}"))
    dlg.pattern_undo_btn.click()
    assert dlg.pattern_input.text() == "Akte"
    dlg.pattern_undo_btn.click()  # einzelnes Zeichen
    assert dlg.pattern_input.text() == "Akt"
    # Leeres Feld: nichts passiert
    dlg.pattern_input.setText("")
    dlg.pattern_undo_btn.click()
    assert dlg.pattern_input.text() == ""


def test_undo_button_respects_cursor_position(qtbot, monkeypatch, tmp_path):
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    dlg.pattern_input.setText("{datum}_{kontakt}_{betreff}")
    dlg.pattern_input.setCursorPosition(len("{datum}_{kontakt}"))
    dlg.pattern_undo_btn.click()
    assert dlg.pattern_input.text() == "{datum}_{betreff}"
    assert dlg.pattern_input.cursorPosition() == len("{datum}")


def test_save_custom_pattern_adds_it_to_combo_and_config(qtbot, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QInputDialog
    dlg, cfg = _dialog(qtbot, monkeypatch, tmp_path)
    # Eingebaute Vorlage: Speichern gesperrt
    dlg.pattern_input.setText("{datum}_{kategorie}_{kontakt}_{betreff}")
    assert not dlg.pattern_save_btn.isEnabled()
    dlg.pattern_input.setText("{jahr}_{kontakt}_Miete")
    assert dlg.pattern_save_btn.isEnabled()
    assert not dlg.pattern_delete_btn.isEnabled()

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Mieter", True)))
    dlg.pattern_save_btn.click()

    names = [dlg.pattern_preset_combo.itemText(i) for i in range(dlg.pattern_preset_combo.count())]
    assert "Mieter" in names
    assert names[-1] == "Eigenes Muster"
    assert dlg.pattern_preset_combo.currentText() == "Mieter"
    assert cfg.get("custom_patterns") == [{"name": "Mieter", "pattern": "{jahr}_{kontakt}_Miete"}]
    assert dlg.pattern_delete_btn.isEnabled()

    # Vorlage aus der Combo waehlen fuellt das Feld
    dlg.pattern_input.setText("")
    idx = names.index("Mieter")
    dlg.pattern_preset_combo.setCurrentIndex(idx)
    dlg.pattern_preset_combo.activated.emit(idx)
    assert dlg.pattern_input.text() == "{jahr}_{kontakt}_Miete"

    # Loeschen entfernt es wieder, Feldinhalt bleibt
    dlg.pattern_delete_btn.click()
    names = [dlg.pattern_preset_combo.itemText(i) for i in range(dlg.pattern_preset_combo.count())]
    assert "Mieter" not in names
    assert cfg.get("custom_patterns") == []
    assert dlg.pattern_input.text() == "{jahr}_{kontakt}_Miete"
    assert dlg.pattern_preset_combo.currentText() == "Eigenes Muster"


def test_save_custom_pattern_cancel_and_builtin_name(qtbot, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QInputDialog, QMessageBox
    dlg, cfg = _dialog(qtbot, monkeypatch, tmp_path)
    dlg.pattern_input.setText("{jahr}_{kontakt}")
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))
    dlg.pattern_save_btn.click()
    assert cfg.get("custom_patterns", []) == []

    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a)))
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("Rechnungen & Belege", True)))
    dlg.pattern_save_btn.click()
    assert warned and cfg.get("custom_patterns", []) == []


def test_saved_pattern_is_preselected_when_config_matches(qtbot, monkeypatch, tmp_path):
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path,
                     filename_pattern="{jahr}_{kontakt}_Miete",
                     custom_patterns=[{"name": "Mieter", "pattern": "{jahr}_{kontakt}_Miete"}])
    assert dlg.pattern_preset_combo.currentText() == "Mieter"
    assert dlg.pattern_delete_btn.isEnabled()


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


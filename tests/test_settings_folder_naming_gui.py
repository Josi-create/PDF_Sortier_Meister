"""Einstellungen > Dateinamen-Muster: Initialen/Vorlage sind immer editierbar.

Vorher waren die Felder bis zum Setzen des Hakens ausgegraut. Auf Retina-Macs
war das Kaestchen kaum sichtbar - die Felder wirkten "nicht anklickbar".
"""
from PyQt6.QtTest import QTest


def _dialog(qtbot, monkeypatch, tmp_path):
    from src.utils import config as cfg_mod
    from src.utils.config import Config
    cfg = Config.__new__(Config)
    cfg.config_path = tmp_path / "config.json"
    cfg._config = {}
    cfg.load()
    monkeypatch.setattr(cfg_mod, "get_config", lambda: cfg)
    monkeypatch.setattr("src.gui.settings_dialog.get_config", lambda: cfg, raising=False)
    from src.gui.settings_dialog import SettingsDialog
    dlg = SettingsDialog()
    qtbot.addWidget(dlg)
    return dlg


def test_fields_editable_without_checkbox(qtbot, monkeypatch, tmp_path):
    dlg = _dialog(qtbot, monkeypatch, tmp_path)
    assert not dlg.folder_naming_check.isChecked()
    assert dlg.folder_naming_initials_input.isEnabled()
    assert dlg.folder_naming_template_input.isEnabled()


def test_typing_initials_enables_feature(qtbot, monkeypatch, tmp_path):
    dlg = _dialog(qtbot, monkeypatch, tmp_path)
    QTest.keyClicks(dlg.folder_naming_initials_input, "JK")
    assert dlg.folder_naming_initials_input.text() == "JK"
    assert dlg.folder_naming_check.isChecked()


def test_programmatic_fill_does_not_enable_feature(qtbot, monkeypatch, tmp_path):
    dlg = _dialog(qtbot, monkeypatch, tmp_path)
    dlg.folder_naming_initials_input.setText("JK")  # z.B. beim Laden der Config
    assert not dlg.folder_naming_check.isChecked()

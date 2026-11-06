"""Einstellungen > Suche (Dokumentensuche, Phase 3 der PDFsuche-Integration):
Laden aus dem Block "suche", Speichern als SearchConfig, Thunderbird-/Tesseract-
Hinweise, Vorschlaege-Menue, Uebernahme-Dialog. Plattformabfragen (Profil,
Laufwerke, Tesseract) sind gepatcht, damit der Test nicht vom Rechner abhaengt."""
import pytest
from PyQt6.QtCore import QTime
from PyQt6.QtWidgets import QDialog

from src.search.konfig import norm_pfad


@pytest.fixture(autouse=True)
def plattform_neutral(monkeypatch, tmp_path):
    monkeypatch.setattr("src.search.plattform.thunderbird_mail_ordner",
                        lambda profiles_ini=None: [str(tmp_path / "Profil" / "Mail")])
    monkeypatch.setattr("src.search.plattform.wurzel_vorschlaege", lambda: [str(tmp_path / "Laufwerk")])
    monkeypatch.setattr("src.utils.tesseract.find_tesseract", lambda: None)


def _dialog(qtbot, monkeypatch, tmp_path, **config_values):
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
    dlg = SettingsDialog()
    qtbot.addWidget(dlg)
    return dlg, cfg


def _items(liste):
    return [liste.item(i).text() for i in range(liste.count())]


def test_tab_laedt_standardwerte_aus_scan_und_zielordner(qtbot, monkeypatch, tmp_path):
    scan, ziel = tmp_path / "Scans", tmp_path / "Ablage"
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path, scan_folder=str(scan), target_folders=[str(ziel)])
    assert dlg.show_tab("Suche")
    assert not dlg.search_active_check.isChecked()
    assert _items(dlg.search_roots_list) == [norm_pfad(str(scan)), norm_pfad(str(ziel))]
    assert _items(dlg.search_priority_list) == [norm_pfad(str(scan))]
    assert "Thunderbird-Profil erkannt" in dlg.search_thunderbird_label.text()
    assert "nicht gefunden" in dlg.search_ocr_status_label.text()
    assert dlg.search_web_port_spin.value() == 18425 and dlg.search_textlayer_combo.currentData() == "aus"
    assert dlg.search_background_time_edit.time() == QTime(3, 0) and dlg.search_processes_spin.value() == 0
    assert ".pdf" in dlg.search_extensions_edit.text() and "appdata" in dlg.search_exclude_names_edit.toPlainText()
    assert dlg.search_db_path_edit.text() == "" and dlg.search_db_path_edit.placeholderText().endswith("suche.db")


def test_speichern_schreibt_searchconfig_und_laedt_sie_wieder(qtbot, monkeypatch, tmp_path):
    scan = tmp_path / "Scans"
    dlg, cfg = _dialog(qtbot, monkeypatch, tmp_path, scan_folder=str(scan))
    dlg.search_active_check.setChecked(True)
    dlg._search_list_add(dlg.search_roots_list, str(tmp_path / "Mehr"))
    dlg._search_list_add(dlg.search_roots_list, str(tmp_path / "MEHR"))   # Dublette (Gross/Klein) bleibt draussen
    dlg.search_mails_check.setChecked(True)
    dlg.search_ocr_check.setChecked(False)
    dlg.search_ocr_languages_edit.setText("deu")
    dlg.search_ocr_max_pages_spin.setValue(50)
    dlg.search_extensions_edit.setText("pdf .docx")
    dlg.search_exclude_names_edit.setPlainText("node_modules\n.git\n\n")
    dlg._search_list_add(dlg.search_exclude_paths_list, str(tmp_path / "Tmp"))
    dlg.search_cloud_check.setChecked(True)
    dlg.search_max_size_spin.setValue(250)
    dlg.search_web_check.setChecked(True)
    dlg.search_web_login_check.setChecked(True)
    dlg.search_web_port_spin.setValue(18500)
    dlg.search_textlayer_combo.setCurrentIndex(dlg.search_textlayer_combo.findData("neue_scans"))
    dlg.search_textlayer_backup_days_spin.setValue(14)
    dlg.search_background_check.setChecked(True)
    dlg.search_background_time_edit.setTime(QTime(4, 30))
    dlg.search_processes_spin.setValue(3)
    dlg.search_db_path_edit.setText(str(tmp_path / "db" / "suche.db"))
    dlg._save_settings()

    s = cfg.get_search_config()
    assert s.aktiv is True and s.wurzeln == [norm_pfad(str(scan)), norm_pfad(str(tmp_path / "Mehr"))]
    assert s.prioritaet == [norm_pfad(str(scan))] and s.endungen == {".pdf", ".docx"}
    assert s.ordner_ausschliessen == {"node_modules", ".git"}
    assert s.pfade_ausschliessen == {norm_pfad(str(tmp_path / "Tmp")).lower()}
    assert s.mails_aktiv and s.mail_ordner == []
    assert s.mail_ordner_effektiv() == [norm_pfad(str(tmp_path / "Profil" / "Mail"))]
    assert s.ocr_aktiv is False and s.ocr_sprachen == "deu" and s.ocr_max_seiten == 50
    assert s.cloud_herunterladen and s.max_dateigroesse_mb == 250
    assert s.web_aktiv and s.web_bei_anmeldung and s.web_port == 18500
    assert s.textebene == "neue_scans" and s.textebene_sicherung_tage == 14
    assert s.hintergrund_aktiv and s.hintergrund_uhrzeit == "04:30" and s.prozesse == 3
    assert s.db_pfad == norm_pfad(str(tmp_path / "db" / "suche.db"))

    # Neu geoeffnet (liest config.json): die Werte kommen zurueck
    dlg2, _ = _dialog(qtbot, monkeypatch, tmp_path)
    assert dlg2.search_active_check.isChecked() and dlg2.search_web_port_spin.value() == 18500
    assert dlg2.search_textlayer_combo.currentData() == "neue_scans"
    assert _items(dlg2.search_roots_list) == s.wurzeln and dlg2.search_background_time_edit.time() == QTime(4, 30)


def test_vorschlaege_menue_und_uebernahme_dialog(qtbot, monkeypatch, tmp_path):
    scan = tmp_path / "Scans"
    dlg, cfg = _dialog(qtbot, monkeypatch, tmp_path, scan_folder=str(scan))
    dlg.search_roots_list.clear()
    dlg._search_fill_suggestions()
    texte = [a.text() for a in dlg.search_roots_suggest_menu.actions()]
    assert texte == [norm_pfad(str(scan)), norm_pfad(str(tmp_path / "Laufwerk"))]
    dlg.search_roots_suggest_menu.actions()[1].trigger()
    assert _items(dlg.search_roots_list) == [norm_pfad(str(tmp_path / "Laufwerk"))]

    class FakeDialog:
        def __init__(self, parent, config):
            self.config = config

        def exec(self):
            from src.search.konfig import SearchConfig
            self.config.set_search_config(SearchConfig(
                aktiv=True, db_pfad=str(tmp_path / "alt" / "x.db"), wurzeln=[str(tmp_path)], mails_aktiv=True))
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr("src.gui.search_migration_dialog.SearchMigrationDialog", FakeDialog)
    dlg.search_migrate_button.click()
    assert dlg.search_active_check.isChecked() and dlg.search_mails_check.isChecked()
    assert dlg.search_db_path_edit.text() == norm_pfad(str(tmp_path / "alt" / "x.db"))
    assert _items(dlg.search_roots_list) == [norm_pfad(str(tmp_path))]

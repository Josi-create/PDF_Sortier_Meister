"""GUI-Tests: Dialog „Vorhandene PDFsuche übernehmen“ (Prüfung im Thread, Übernahme, Fehlerfall).

Die Config liegt in tmp_path und wird dem Dialog direkt uebergeben; die
automatische Suche nach einer PDFsuche (Aufgabenplanung, ~/.claude.json) wird
durch ``kandidaten`` ersetzt, damit der Test nicht vom Rechner abhaengt.
"""

import helfer_suche as h
from src.gui.search_migration_dialog import SearchMigrationDialog
from src.search.konfig import norm_pfad
from src.utils.config import Config


def test_dialog_prueft_kandidaten_und_uebernimmt(qtbot, tmp_path):
    projekt = h.pdfsuche_projekt(tmp_path)
    cfg_pfad = tmp_path / "pdfsm" / "config.json"
    dlg = SearchMigrationDialog(config=Config(config_path=cfg_pfad), kandidaten=[str(projekt)])
    qtbot.addWidget(dlg)
    assert dlg.folder_combo.currentText() == str(projekt)
    qtbot.waitUntil(lambda: dlg.take_button.isEnabled(), timeout=15000)
    assert "Dokumente: 2" in dlg.preview.toPlainText() and "Bereit" in dlg.status_label.text()

    with qtbot.waitSignal(dlg.accepted, timeout=15000):
        dlg.take_button.click()
    assert dlg.ergebnis is not None and dlg.ergebnis.aktiv is True
    gespeichert = Config(config_path=cfg_pfad).get_search_config()
    assert gespeichert.db_pfad == norm_pfad(str(projekt / "data" / "pdfsuche.db")) == dlg.ergebnis.db_pfad
    assert not dlg.progress.isVisible()


def test_dialog_ohne_kandidaten_und_mit_fehler(qtbot, tmp_path):
    dlg = SearchMigrationDialog(config=Config(config_path=tmp_path / "config.json"), kandidaten=[])
    qtbot.addWidget(dlg)
    assert not dlg.take_button.isEnabled() and dlg.preview.toPlainText() == ""
    assert "Keine PDFsuche gefunden" in dlg.status_label.text()

    dlg.folder_combo.setEditText(str(tmp_path / "leer"))
    dlg.check_button.click()
    qtbot.waitUntil(lambda: dlg.uebernahme is not None, timeout=15000)
    assert not dlg.take_button.isEnabled() and "config.toml" in dlg.preview.toPlainText()
    assert "nicht möglich" in dlg.status_label.text()
    # Die Config wurde nicht angefasst
    assert Config(config_path=tmp_path / "config.json").get_search_config().aktiv is False

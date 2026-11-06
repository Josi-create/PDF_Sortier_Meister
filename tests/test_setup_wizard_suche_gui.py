"""GUI-Tests: Seite „Dokumentensuche“ im Einrichtungs-Assistenten (Phase 3 der PDFsuche-Integration).

Laufwerke, Thunderbird-Profil, Tesseract, Ollama-Erkennung und PDFsuche-Funde
sind gepatcht, damit der Test nicht vom Rechner abhaengt; der Dokumente-Ordner
liegt unter tmp_path (wie in den Ordner-Tests).
"""
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog

from src.gui import setup_wizard as wiz
from src.gui.setup_wizard import PAGE_DONE, PAGE_PROVIDER, PAGE_SUCHE, SetupWizard, _PROVIDER_IDS
from src.search.konfig import norm_pfad
from src.utils.hardware import GpuInfo, OllamaRecommendation


@pytest.fixture(autouse=True)
def plattform_neutral(monkeypatch, tmp_path):
    monkeypatch.setattr(wiz.QStandardPaths, "writableLocation", lambda loc: str(tmp_path / "Documents"))
    monkeypatch.setattr("src.search.plattform.wurzel_vorschlaege", lambda: [str(tmp_path / "Laufwerk")])
    monkeypatch.setattr("src.search.plattform.thunderbird_mail_ordner", lambda profiles_ini=None: [])
    monkeypatch.setattr("src.utils.tesseract.find_tesseract", lambda: None)
    monkeypatch.setattr("src.search.migration.finde_pdfsuche", lambda claude_json=None: [])
    gpu = GpuInfo("Intel(R) UHD Graphics 770", 0, False, "intel")
    rec = OllamaRecommendation(False, None, 0.0, "Nur integrierte Grafik erkannt.", gpu)
    monkeypatch.setattr(wiz, "detect_ollama_environment",
                        lambda: {"exe": None, "installed": False, "running": False, "recommendation": rec})


def _zur_suchseite(qtbot):
    w = SetupWizard()
    qtbot.addWidget(w)
    w.show()
    w.next()  # Welcome -> Scan
    w.next()  # Scan -> Zielordner
    w.next()  # Zielordner -> KI-Assistent (startet die Erkennung)
    provider = w.page(PAGE_PROVIDER)
    qtbot.waitUntil(lambda: provider.get_detection() is not None, timeout=5000)
    provider._radios[_PROVIDER_IDS.index("none")].setChecked(True)
    w.next()  # ohne KI direkt zur Dokumentensuche
    assert w.currentId() == PAGE_SUCHE
    return w, w.page(PAGE_SUCHE)


def _texte(page):
    return [page.folders_list.item(i).text() for i in range(page.folders_list.count())]


def test_seite_vorbelegt_mit_scan_und_zielordner(qtbot, fresh_config, tmp_path):
    w, page = _zur_suchseite(qtbot)
    docs = tmp_path / "Documents"
    assert page.was_visited() and not page.enable_check.isChecked()
    texte = _texte(page)
    assert texte == [norm_pfad(str(docs / "Scans")), norm_pfad(str(docs / "PDF-Sammlung")),
                     norm_pfad(str(tmp_path / "Laufwerk"))]
    assert page.selected_folders() == texte[:2]
    assert not page.folders_list.isEnabled() and not page.mails_check.isEnabled() and not page.ocr_check.isEnabled()
    assert "Kein Thunderbird-Profil" in page.mails_label.text() and "nicht gefunden" in page.ocr_label.text()
    assert page.migrate_button.isHidden()
    page.enable_check.setChecked(True)
    assert page.folders_list.isEnabled() and page.background_check.isEnabled()
    assert not page.mails_check.isEnabled() and not page.ocr_check.isEnabled()   # kein Profil, kein Tesseract


def test_fertig_speichert_suchkonfiguration(qtbot, fresh_config, tmp_path):
    w, page = _zur_suchseite(qtbot)
    page.enable_check.setChecked(True)
    page.folders_list.item(2).setCheckState(Qt.CheckState.Checked)      # Laufwerk dazu
    page.folders_list.item(1).setCheckState(Qt.CheckState.Unchecked)    # Zielordner weg
    page.background_check.setChecked(False)
    w.next()
    assert w.currentId() == PAGE_DONE
    w.accept()
    s = fresh_config.get_search_config()
    docs = tmp_path / "Documents"
    assert s.aktiv is True
    assert s.wurzeln == [norm_pfad(str(docs / "Scans")), norm_pfad(str(tmp_path / "Laufwerk"))]
    assert s.prioritaet == [norm_pfad(str(docs / "Scans"))]
    assert s.mails_aktiv is False and s.hintergrund_aktiv is False and s.ocr_aktiv is True


def test_spaeter_ohne_besuch_laesst_block_unberuehrt(qtbot, fresh_config):
    w = SetupWizard()
    qtbot.addWidget(w)
    w.show()
    w.reject()
    assert fresh_config.get("suche", {}) == {}


def test_ausgeschaltet_wird_ausdruecklich_gespeichert(qtbot, fresh_config):
    w, page = _zur_suchseite(qtbot)
    w.next()
    w.accept()
    block = fresh_config.get("suche", {})
    assert block.get("aktiv") is False and block.get("wurzeln")


def test_uebernahme_sperrt_seite_und_speichert_nicht_doppelt(qtbot, fresh_config, tmp_path, monkeypatch):
    monkeypatch.setattr("src.search.migration.finde_pdfsuche", lambda claude_json=None: [str(tmp_path / "PDFsuche")])

    class FakeDialog:
        def __init__(self, parent, config, kandidaten=None):
            self.config = config
            self.kandidaten = kandidaten
            self.ergebnis = None

        def exec(self):
            from src.search.konfig import SearchConfig
            k = SearchConfig(aktiv=True, db_pfad=str(tmp_path / "alt" / "x.db"), wurzeln=[str(tmp_path)])
            self.config.set_search_config(k)
            self.ergebnis = k
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr("src.gui.search_migration_dialog.SearchMigrationDialog", FakeDialog)
    w, page = _zur_suchseite(qtbot)
    assert not page.migrate_button.isHidden()
    page.migrate_button.click()
    assert page.enable_check.isChecked() and not page.enable_check.isEnabled()
    assert not page.migrate_label.isHidden() and page.migrate_button.isHidden()
    assert page.get_search_config() is None
    w.next()
    w.accept()
    s = fresh_config.get_search_config()
    assert s.db_pfad == norm_pfad(str(tmp_path / "alt" / "x.db")) and s.wurzeln == [norm_pfad(str(tmp_path))]


def test_fertig_mit_hintergrund_richtet_den_zeitplan_ein(qtbot, fresh_config, zeitplan_speicher):
    w, page = _zur_suchseite(qtbot)
    page.enable_check.setChecked(True)
    assert page.background_check.isChecked()             # Vorschlag: täglich im Hintergrund
    w.next()
    w.accept()
    index = zeitplan_speicher.eintraege["index"]
    assert index.uhrzeit == "00:00" and index.argumente[-2:] == ("index", "--hintergrund")


def test_fertig_ohne_hintergrund_plant_nichts(qtbot, fresh_config, zeitplan_speicher):
    w, page = _zur_suchseite(qtbot)
    page.enable_check.setChecked(True)
    page.background_check.setChecked(False)
    w.next()
    w.accept()
    assert zeitplan_speicher.eintraege == {}


def test_textebene_im_assistenten_vorausgewaehlt_und_abwaehlbar(qtbot, fresh_config):
    """Opt-out: die Textebene fuer neue Scans ist vorausgewaehlt und laesst sich abwaehlen."""
    w, page = _zur_suchseite(qtbot)
    page.enable_check.setChecked(True)
    assert page.textlayer_check.isChecked()
    assert page.get_search_config().textebene == "neue_scans"
    page.textlayer_check.setChecked(False)
    assert page.get_search_config().textebene == "aus"

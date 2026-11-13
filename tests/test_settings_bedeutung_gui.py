"""Einstellungen > Suche > Bedeutungssuche für den Chat (Issue #230): Schalter (Standard aus),
Einschalten nur mit laufendem Ollama, Modell laden, Stand aus dem Index, Speichern."""
import pytest
from PyQt6.QtWidgets import QMessageBox

from src.search import bedeutung, db
from src.search.konfig import SearchConfig


@pytest.fixture(autouse=True)
def plattform_neutral(monkeypatch, tmp_path):
    monkeypatch.setattr("src.search.plattform.thunderbird_mail_ordner", lambda profiles_ini=None: [])
    monkeypatch.setattr("src.search.plattform.wurzel_vorschlaege", lambda: [])
    monkeypatch.setattr("src.utils.tesseract.find_tesseract", lambda: None)


@pytest.fixture
def meldungen(monkeypatch):
    liste = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, titel, text, *a, **k: liste.append(text))
    return liste


def _ollama(monkeypatch, vorhanden):
    """``bedeutung.modell_vorhanden`` liefert der Reihe nach die Werte aus ``vorhanden``."""
    werte = list(vorhanden)
    aufrufe = []

    def modell_vorhanden(url, modell, zeitlimit=3.0):
        aufrufe.append((url, modell))
        return werte.pop(0) if len(werte) > 1 else werte[0]

    monkeypatch.setattr(bedeutung, "modell_vorhanden", modell_vorhanden)
    return aufrufe


def _dialog(qtbot, fresh_config, tmp_path, **suche):
    fresh_config.set("suche", {"db_pfad": str(tmp_path / "suche" / "suche.db"), **suche}, auto_save=False)
    from src.gui.settings_dialog import SettingsDialog

    dlg = SettingsDialog()
    qtbot.addWidget(dlg)
    assert dlg.show_tab("Suche")
    return dlg


def test_standard_ist_aus_und_fragt_ollama_nicht(qtbot, fresh_config, tmp_path, monkeypatch):
    aufrufe = _ollama(monkeypatch, [True])
    dlg = _dialog(qtbot, fresh_config, tmp_path)
    assert not dlg.search_meaning_check.isChecked()
    assert dlg.search_meaning_status_label.text() == "" and dlg.search_meaning_model_button.isEnabled()
    assert aufrufe == []
    dlg._save_settings()
    assert fresh_config.get_search_config().bedeutung_aktiv is False


def test_einschalten_ohne_ollama_geht_nicht(qtbot, fresh_config, tmp_path, monkeypatch, meldungen):
    _ollama(monkeypatch, [None])
    dlg = _dialog(qtbot, fresh_config, tmp_path)
    dlg.search_meaning_check.click()
    assert not dlg.search_meaning_check.isChecked()
    assert len(meldungen) == 1 and "Ollama läuft nicht" in meldungen[0]
    assert "Ollama läuft nicht" in dlg.search_meaning_status_label.text()


def test_einschalten_ohne_modell_bietet_den_download_an(qtbot, fresh_config, tmp_path, monkeypatch, meldungen):
    aufrufe = _ollama(monkeypatch, [False, True])
    geladen = []
    monkeypatch.setattr("src.ml.ollama_launcher.pull_model",
                        lambda url, modell, *a, **k: geladen.append((url, modell)) or (True, "ok"))
    dlg = _dialog(qtbot, fresh_config, tmp_path)
    dlg.search_meaning_check.click()
    assert dlg.search_meaning_check.isChecked() and meldungen == []
    assert "fehlt noch" in dlg.search_meaning_status_label.text() and dlg.search_meaning_model_button.isEnabled()

    dlg.search_meaning_model_button.click()
    qtbot.waitUntil(lambda: "ist bereit" in dlg.search_meaning_status_label.text(), timeout=5000)
    assert geladen == [("http://localhost:11434", "embeddinggemma")]
    assert not dlg.search_meaning_model_button.isEnabled()
    assert "beim nächsten Indexlauf" in dlg.search_meaning_status_label.text()
    assert aufrufe == [("", "embeddinggemma")] * 2

    dlg._save_settings()
    assert fresh_config.get_search_config().bedeutung_aktiv is True


def test_download_fehler_wird_gemeldet(qtbot, fresh_config, tmp_path, monkeypatch, meldungen):
    _ollama(monkeypatch, [False])
    monkeypatch.setattr("src.ml.ollama_launcher.pull_model", lambda url, modell, *a, **k: (False, "kein Netz"))
    dlg = _dialog(qtbot, fresh_config, tmp_path)
    dlg.search_meaning_check.click()
    dlg.search_meaning_model_button.click()
    qtbot.waitUntil(lambda: bool(meldungen), timeout=5000)
    assert "kein Netz" in meldungen[0] and dlg.search_meaning_model_button.isEnabled()


def test_stand_aus_dem_index_und_eigene_werte_bleiben_beim_speichern(qtbot, fresh_config, tmp_path, monkeypatch):
    aufrufe = _ollama(monkeypatch, [True])
    konfig = SearchConfig(db_pfad=str(tmp_path / "suche" / "suche.db"))
    con = db.verbinde(konfig.db_datei)
    db.init(con)
    pfad = "/ablage/Scan.pdf"
    db.speichere(con, {"pfad": pfad, "datei": pfad, "name": "Scan.pdf", "ordner": "/ablage", "typ": "pdf",
                       "format": "pdf", "groesse": 1, "mtime_ns": 1, "datum": 1.7e9, "seiten": 2,
                       "textstatus": "text"}, [(1, "text", "Seite eins mit Text"), (2, "text", "Seite zwei")])
    bedeutung.schema(con)
    seite = con.execute("SELECT id FROM seiten ORDER BY id LIMIT 1").fetchone()[0]
    con.execute("INSERT INTO seiten_vektor VALUES (?, 'bge-m3', ?)", (seite, bytes(256)))
    con.commit()
    con.close()

    dlg = _dialog(qtbot, fresh_config, tmp_path, bedeutung_aktiv=True, bedeutung_modell="bge-m3",
                  bedeutung_url="http://rechner:11434")
    assert dlg.search_meaning_check.isChecked()
    assert dlg.search_meaning_status_label.text() == "1 von 2 Seiten vorbereitet"
    assert aufrufe == []            # beim Oeffnen keine Netzabfrage

    dlg.search_meaning_check.click()    # aus
    dlg.search_meaning_check.click()    # wieder an: fragt den eingestellten Server nach dem eingestellten Modell
    assert aufrufe == [("http://rechner:11434", "bge-m3")]
    assert dlg.search_meaning_status_label.text() == "Modell bge-m3 ist bereit. 1 von 2 Seiten vorbereitet"
    dlg._save_settings()
    s = fresh_config.get_search_config()
    assert (s.bedeutung_aktiv, s.bedeutung_modell, s.bedeutung_url) == (True, "bge-m3", "http://rechner:11434")

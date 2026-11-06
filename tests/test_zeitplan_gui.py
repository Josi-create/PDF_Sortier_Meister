"""Oberflaeche des Hintergrunddienstes (Phase 6): Einstellungen richten den Zeitplan ein,
der Reiter „Suche“ oeffnet die Browser-Oberflaeche.

Das Betriebssystem ist durch ``zeitplan.Speicher`` ersetzt (``tests/conftest.py``):
Kein Test legt eine echte Aufgabe an. Browser und Prozessstart sind gepatcht.
"""
from __future__ import annotations

from PyQt6.QtCore import QTime
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMessageBox

from src.gui.search_view import SearchView
from src.search import zeitplan
from src.search.suchindex import Suchindex
from src.utils.config import Config
from tests import helfer_suche as h
from tests.test_settings_search_tab_gui import (  # noqa: F401 (autouse-Fixture)
    _dialog,
    plattform_neutral,
)


def _suche(tmp_path, **kw):
    return h.konfig_fuer(tmp_path, wurzeln=[str(tmp_path)], **kw).als_dict()


def test_speichern_richtet_den_zeitplan_ein_und_entfernt_ihn(qtbot, monkeypatch, tmp_path, zeitplan_speicher):
    dlg, cfg = _dialog(qtbot, monkeypatch, tmp_path, suche=_suche(tmp_path))
    dlg.search_background_check.setChecked(True)
    dlg.search_background_time_edit.setTime(QTime(4, 45))
    dlg.search_web_check.setChecked(True)
    dlg.search_web_login_check.setChecked(True)
    dlg._save_settings()
    index, web = zeitplan_speicher.eintraege["index"], zeitplan_speicher.eintraege["web"]
    assert index.uhrzeit == "04:45" and index.argumente[-2:] == ("index", "--hintergrund")
    assert web.uhrzeit is None and web.argumente[-2:] == ("web", "--nicht-oeffnen")
    assert zeitplan_speicher.gestartet == ["web"]

    dlg2, _ = _dialog(qtbot, monkeypatch, tmp_path)
    assert dlg2.search_background_check.isChecked() and dlg2.search_web_login_check.isChecked()
    dlg2.search_background_check.setChecked(False)
    dlg2.search_web_login_check.setChecked(False)
    dlg2._save_settings()
    assert zeitplan_speicher.eintraege == {}


def test_ohne_hintergrund_wird_nichts_abgefragt(qtbot, monkeypatch, tmp_path, zeitplan_speicher):
    abfragen = []
    monkeypatch.setattr(zeitplan_speicher, "abfragen", lambda art: abfragen.append(art))
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path, suche=_suche(tmp_path))
    dlg._save_settings()
    assert abfragen == []          # nichts eingeschaltet und nichts geaendert: kein schtasks-Aufruf


def test_fehler_beim_einrichten_wird_gemeldet(qtbot, monkeypatch, tmp_path, zeitplan_speicher):
    def scheitern(e):
        raise zeitplan.ZeitplanFehler("Aufgabe ließ sich nicht einrichten: Zugriff verweigert")

    monkeypatch.setattr(zeitplan_speicher, "einrichten", scheitern)
    warnungen = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda p, titel, text, *a: warnungen.append(text)))
    dlg, cfg = _dialog(qtbot, monkeypatch, tmp_path, suche=_suche(tmp_path))
    dlg.search_background_check.setChecked(True)
    dlg._save_settings()
    assert len(warnungen) == 1 and "Zugriff verweigert" in warnungen[0]
    assert cfg.get_search_config().hintergrund_aktiv          # die Einstellung selbst ist gespeichert


def _view(qtbot, tmp_path, **kw):
    cfg = Config(config_path=tmp_path / "config.json")
    cfg.set_search_config(h.konfig_fuer(tmp_path, wurzeln=[str(tmp_path)], **kw))
    v = SearchView(cfg)
    qtbot.addWidget(v)
    return v


def test_im_browser_oeffnen(qtbot, monkeypatch, tmp_path):
    ohne = _view(qtbot, tmp_path)
    assert not ohne.web_button.isVisibleTo(ohne)
    ohne.shutdown()

    v = _view(qtbot, tmp_path, web_aktiv=True, web_port=18555)
    try:
        assert v.web_button.isVisibleTo(v)
        geoeffnet, gestartet = [], []
        monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: geoeffnet.append(url.toString())))
        monkeypatch.setattr(Suchindex, "web_starten", lambda self, **kw: gestartet.append(kw))
        monkeypatch.setattr("src.gui.search_view.WEB_PRUEFEN_MS", 0)

        monkeypatch.setattr(Suchindex, "web_erreichbar", lambda self, timeout=0.5: True)
        v.web_button.click()
        assert geoeffnet == ["http://127.0.0.1:18555/"] and gestartet == []

        monkeypatch.setattr(Suchindex, "web_erreichbar", lambda self, timeout=0.5: False)
        v.web_button.click()
        assert gestartet == [{"oeffnen": True}] and "wird gestartet" in v.status_label.text()
        qtbot.waitUntil(lambda: v.meldung_label.isVisibleTo(v), timeout=3000)
        assert "Port 18555" in v.meldung_label.text()      # antwortet nicht: Hinweis auf belegten Port
    finally:
        v.shutdown()

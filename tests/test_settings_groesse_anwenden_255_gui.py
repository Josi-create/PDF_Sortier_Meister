"""GUI-Tests: Groesse des Einstellungsfensters und Knopf „Anwenden“ (Issue #255).

* Das Fenster oeffnet so gross, dass kein Reiter waagerecht rollen muss
  (begrenzt auf 90 % des Bildschirms), auch mit langen gespeicherten Modellnamen.
* Eine von Hand geaenderte Groesse wird gemerkt und beim naechsten Oeffnen benutzt.
* „Anwenden“ speichert und laesst das Fenster offen, „Speichern“ schliesst weiter.

Alle Tests laufen gegen eine Konfiguration in ``tmp_path`` (``patch_singletons``).
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QScrollArea

from src.gui.settings_dialog import SettingsDialog

LANGES_MODELL = "erfundener-anbieter/ein-sehr-langer-modellname-zum-testen-der-fensterbreite-v12:latest"


@pytest.fixture(autouse=True)
def kein_netz(monkeypatch):
    def _verboten(*args, **kwargs):
        raise AssertionError("Netzaufruf im Test")
    monkeypatch.setattr("urllib.request.urlopen", _verboten)


@pytest.fixture
def fresh_config(monkeypatch, tmp_path):
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod
    from src.ml import classifier as cl_mod
    from src.ml import hybrid_classifier as hc_mod
    from src.core import pdf_cache as pc_mod

    from tests.conftest import patch_singletons

    fresh = cfg_mod.Config(config_path=tmp_path / "config.json")
    fresh.set("persist_pdf_cache", False)
    monkeypatch.setattr(pc_mod.PDFCache, "_instance", None)
    patch_singletons(monkeypatch, {
        "get_config": lambda: fresh,
        "get_database": lambda: db_mod.Database(db_path=str(tmp_path / "t.db")),
        "get_classifier": cl_mod.PDFClassifier,
        "get_hybrid_classifier": hc_mod.HybridClassifier,
        "get_pdf_cache": pc_mod.PDFCache,
    })
    return fresh


@pytest.fixture(autouse=True)
def keine_mcp_pruefung(monkeypatch):
    """Der Reiter „Suche“ prueft sonst Claude Code/Desktop auf dem echten Rechner."""
    monkeypatch.setattr(SettingsDialog, "_mcp_status_pruefen", lambda self: None)


def _dialog(qtbot):
    d = SettingsDialog()
    qtbot.addWidget(d)
    return d


def _scroll_seiten(d):
    seiten = [d.tab_widget.widget(i) for i in range(d.tab_widget.count())]
    return [s for s in seiten if isinstance(s, QScrollArea)]


def test_inhaltsgroesse_laesst_keinen_reiter_rollen(qtbot, fresh_config):
    """Bei der berechneten Breite rollt kein Reiter waagerecht.

    Die Hoehe wird nicht geprueft: der Reiter „Suche“ ist hoeher als jeder
    Bildschirm, und das Fenstersystem begrenzt die Fensterhoehe.
    """
    fresh_config.set_cached_models("ollama", [LANGES_MODELL])
    fresh_config.set("llm", {**fresh_config.get_llm_config(), "provider": "ollama", "model": LANGES_MODELL})
    d = _dialog(qtbot)
    assert len(_scroll_seiten(d)) >= 3  # KI-Assistent, Allgemein, Suche

    # Der Testbildschirm ist kleiner als der Inhalt; die Begrenzung auf den
    # Bildschirm prueft ein eigener Test.
    d.resize(d._content_size())
    d.show()
    qtbot.waitExposed(d)
    for i in range(d.tab_widget.count()):
        d.tab_widget.setCurrentIndex(i)
        qtbot.wait(20)
        seite = d.tab_widget.widget(i)
        titel = d.tab_widget.tabText(i)
        if isinstance(seite, QScrollArea):
            assert seite.horizontalScrollBar().maximum() == 0, titel
        else:
            assert seite.width() >= seite.minimumSizeHint().width(), titel


def test_inhaltsgroesse_beruecksichtigt_lange_modellnamen(qtbot, fresh_config):
    """Die Groesse wird nach dem Laden bestimmt: lange Modellnamen zaehlen mit."""
    ohne = _dialog(qtbot)._content_size().width()
    fresh_config.set_cached_models("ollama", [LANGES_MODELL * 3])
    fresh_config.set("llm", {**fresh_config.get_llm_config(), "provider": "ollama"})
    d = _dialog(qtbot)
    ki_inhalt = d.tab_widget.widget(0).widget()
    assert d._content_size().width() >= ki_inhalt.minimumSizeHint().width()
    assert d._content_size().width() >= ohne


def test_startgroesse_passt_auf_den_bildschirm(qtbot, fresh_config):
    d = _dialog(qtbot)
    verfuegbar = d.screen().availableGeometry().size()
    wunsch = d._content_size()
    assert d.width() == max(min(wunsch.width(), int(verfuegbar.width() * 0.9)), d.minimumWidth())
    assert d.height() == max(min(wunsch.height(), int(verfuegbar.height() * 0.9)), d.minimumHeight())


def test_gemerkte_groesse_wird_benutzt(qtbot, fresh_config):
    fresh_config.set("settings_dialog_size", [640, 520])
    d = _dialog(qtbot)
    assert d.size() == QSize(640, 520)


@pytest.mark.parametrize("kaputt", [[], [640], ["a", "b"], [0, -5], [True, True], "640x520", None])
def test_unbrauchbare_gemerkte_groesse_wird_ignoriert(qtbot, fresh_config, kaputt):
    erwartet = _dialog(qtbot).size()
    fresh_config.set("settings_dialog_size", kaputt)
    assert _dialog(qtbot).size() == erwartet


def test_gemerkte_groesse_nie_groesser_als_der_bildschirm(qtbot, fresh_config):
    fresh_config.set("settings_dialog_size", [99999, 99999])
    d = _dialog(qtbot)
    verfuegbar = d.screen().availableGeometry().size()
    assert d.width() <= verfuegbar.width()
    assert d.height() <= verfuegbar.height()


@pytest.mark.parametrize("schliessen", ["reject", "accept"])
def test_geaenderte_groesse_wird_beim_schliessen_gemerkt(qtbot, fresh_config, schliessen):
    d = _dialog(qtbot)
    d.resize(610, 470)
    getattr(d, schliessen)()
    assert fresh_config.get("settings_dialog_size") == [610, 470]
    assert _dialog(qtbot).size() == QSize(610, 470)


def test_unveraenderte_groesse_wird_nicht_gespeichert(qtbot, fresh_config):
    d = _dialog(qtbot)
    d.reject()
    assert fresh_config.get("settings_dialog_size") == []


def test_anwenden_speichert_und_laesst_das_fenster_offen(qtbot, fresh_config, monkeypatch):
    geschlossen = []
    monkeypatch.setattr(SettingsDialog, "done", lambda self, r: geschlossen.append(r))
    d = _dialog(qtbot)
    signale = []
    d.settings_changed.connect(lambda: signale.append(1))
    assert d.apply_button.text() == "Anwenden"

    d.max_suggestions_spin.setValue(7)
    d.apply_button.click()
    assert fresh_config.get("max_suggestions") == 7
    assert signale == [1]
    assert geschlossen == []

    # Ein zweites Mal anwenden und danach speichern funktioniert weiter
    d.max_suggestions_spin.setValue(3)
    d.apply_button.click()
    assert fresh_config.get("max_suggestions") == 3
    assert signale == [1, 1]
    assert geschlossen == []


def test_speichern_schliesst_weiterhin(qtbot, fresh_config, monkeypatch):
    geschlossen = []
    monkeypatch.setattr(SettingsDialog, "done", lambda self, r: geschlossen.append(r))
    d = _dialog(qtbot)
    signale = []
    d.settings_changed.connect(lambda: signale.append(1))
    d.max_suggestions_spin.setValue(4)
    d.save_button.click()
    assert fresh_config.get("max_suggestions") == 4
    assert signale == [1]
    assert geschlossen == [SettingsDialog.DialogCode.Accepted]


def test_abbrechen_nach_anwenden_behaelt_das_angewendete(qtbot, fresh_config):
    d = _dialog(qtbot)
    d.max_suggestions_spin.setValue(6)
    d.apply_button.click()
    d.max_suggestions_spin.setValue(2)
    d.cancel_button.click()
    assert fresh_config.get("max_suggestions") == 6

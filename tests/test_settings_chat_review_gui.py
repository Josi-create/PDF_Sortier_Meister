"""Einstellungen „Chat“ (Issue #166/#167): Befunde der Review - Key/URL bleiben, Scrollbereich passt sich an."""
from __future__ import annotations

from PyQt6.QtWidgets import QAbstractScrollArea, QScrollArea

from tests.test_settings_chat_gui import _dialog, fresh_config  # noqa: F401 - Fixture wird importiert


def test_speichern_mit_abgeschalteter_checkbox_laesst_key_und_url_stehen(qtbot, fresh_config):
    """Nach dem ersten Abschalten steht provider ""; weitere Speichervorgaenge duerfen Key/URL nicht loeschen."""
    fresh_config.set("chat", {
        "provider": "", "model": "sonnet-4", "api_key": "sk-ant-chat", "base_url": "http://x:1",
        "werkzeuge_aktiv": False, "max_werkzeug_schritte": 3,
    })
    d = _dialog(qtbot)
    assert not d.chat_own_model_check.isChecked()
    d._save_settings()
    chat = fresh_config.get("chat")
    assert chat["provider"] == ""
    assert chat["model"] == "sonnet-4" and chat["api_key"] == "sk-ant-chat" and chat["base_url"] == "http://x:1"
    # Die uebrigen Chat-Felder werden weiterhin aus dem Dialog geschrieben
    assert chat["werkzeuge_aktiv"] is False and chat["max_werkzeug_schritte"] == 3


def test_ki_reiter_scrollbereich_richtet_sich_nach_dem_inhalt(qtbot, fresh_config):
    d = _dialog(qtbot)
    scroll = d.tab_widget.widget(0)
    assert isinstance(scroll, QScrollArea)
    assert scroll.sizeAdjustPolicy() == QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents
    # Der Dialog ist mindestens so breit wie der Inhalt des KI-Reiters verlangt -
    # hoechstens aber so breit, wie Qt eine QScrollArea vorschlaegt
    # (QScrollArea::sizeHint ist auf 36 x Schrifthoehe begrenzt). Unter
    # QT_QPA_PLATFORM=offscreen sind die Schriften breiter, dann greift die Grenze.
    inhalt = scroll.widget().minimumSizeHint().width()
    qt_grenze = 36 * max(10, scroll.fontMetrics().height())
    assert d.sizeHint().width() >= min(inhalt, qt_grenze) - 40

"""Tests fuer main._apply_wizard_result (Issue #65).

Nach dem Erststart-Wizard muss der LLM-Provider im Hauptfenster neu
initialisiert werden, sonst zeigt die Statusleiste "LLM: Aus", obwohl der
Wizard z.B. Ollama erfolgreich eingerichtet hat. Ursache: der
HybridClassifier des Hauptfensters wird VOR dem Wizard mit Provider "none"
gebaut und ohne einen expliziten Re-Init-Aufruf nie aktualisiert.

Nutzt ein Fake-Fenster (MagicMock) statt eines echten MainWindow, damit der
Test schnell und ohne Qt-Widget-Erzeugung laeuft. Da src.main beim Import
src.gui.main_window mitzieht, laeuft der Test trotzdem ueber die
qtbot-Fixture (pytest-qt), damit eine QApplication existiert.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from src.main import _apply_wizard_result


def test_apply_wizard_result_reinits_llm_with_scan_folder(qtbot, fresh_config):
    """Wizard hat einen Scan-Ordner gesetzt: initial_load() UND
    _on_settings_changed() (re-init LLM-Provider, Status, Pre-Caching)
    muessen aufgerufen werden."""
    fresh_config.set_scan_folder("C:/irgendein/ordner")
    window = MagicMock()

    _apply_wizard_result(window, fresh_config)

    window.initial_load.assert_called_once()
    window._on_settings_changed.assert_called_once()


def test_apply_wizard_result_reinits_llm_without_scan_folder(qtbot, fresh_config):
    """Wizard wurde ohne Scan-Ordner beendet (z.B. abgebrochen):
    initial_load() ist sinnlos und wird uebersprungen, aber der
    LLM-Status muss trotzdem aktualisiert werden."""
    window = MagicMock()

    _apply_wizard_result(window, fresh_config)

    window.initial_load.assert_not_called()
    window._on_settings_changed.assert_called_once()


def test_apply_wizard_result_calls_settings_changed_after_initial_load(qtbot, fresh_config):
    """Reihenfolge ist wichtig: initial_load() zuerst (laedt die PDFs),
    danach _on_settings_changed() (re-init LLM + Pre-Caching), damit das
    Pre-Caching die bereits geladenen PDFs sieht."""
    fresh_config.set_scan_folder("C:/irgendein/ordner")
    calls = []
    window = MagicMock()
    window.initial_load.side_effect = lambda: calls.append("initial_load")
    window._on_settings_changed.side_effect = lambda: calls.append("settings_changed")

    _apply_wizard_result(window, fresh_config)

    assert calls == ["initial_load", "settings_changed"]

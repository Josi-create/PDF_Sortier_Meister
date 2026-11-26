"""Statusleiste: KI-Warnung und Text daneben oeffnen dasselbe Fenster; X schliesst es (Issue #430).

Headless MainWindow mit frischen Singletons (wie tests/test_main_window_chat_gui.py);
``QMessageBox.exec`` ist ersetzt, damit kein Fenster wartet.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox

from tests.test_main_window_chat_gui import fenster, fresh_singletons  # noqa: F401 - Fixtures


def _abfangen(monkeypatch):
    from src.gui import main_window as mw_mod

    gezeigt = []

    def exec_attrappe(box):
        escape = box.escapeButton()
        gezeigt.append({
            # macOS zeigt keinen Fenstertitel an einer QMessageBox (windowTitle() bleibt
            # leer) - darum am Inhalt erkennen
            "hintergrund_analyse": "KI-Vorabfrage im Hintergrund" in box.text(),
            "escape": box.standardButton(escape) if escape is not None else None,
        })
        return 0

    monkeypatch.setattr(mw_mod.QMessageBox, "exec", exec_attrappe)
    return gezeigt


def test_warnzeichen_und_text_daneben_oeffnen_hintergrund_analyse(fenster, monkeypatch):  # noqa: F811
    gezeigt = _abfangen(monkeypatch)
    win = fenster()
    geoeffnet = []
    monkeypatch.setattr(win, "open_settings", lambda *a: geoeffnet.append(1))

    win.llm_status_label.doubleClicked.emit()
    win.cache_status_label.doubleClicked.emit()

    assert [g["hintergrund_analyse"] for g in gezeigt] == [True, True]
    assert geoeffnet == []  # die Einstellungen nur noch ueber den Knopf im Fenster
    assert "Hintergrund-Analyse" in win.llm_status_label.toolTip()


def test_x_und_esc_schliessen_das_fenster_wie_ok(fenster, monkeypatch):  # noqa: F811
    gezeigt = _abfangen(monkeypatch)
    win = fenster()
    win._show_precache_details()
    assert gezeigt[-1]["escape"] == QMessageBox.StandardButton.Ok

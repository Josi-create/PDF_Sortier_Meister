"""GUI-Tests fuer den Unterstuetzen-Dialog (Issue #115). Kein echter Browser."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from PyQt6.QtWidgets import QLabel

from src.core import support
from src.gui import support_dialog as sd


@pytest.fixture
def urls(monkeypatch):
    geoeffnet = []
    monkeypatch.setattr(sd.QDesktopServices, "openUrl", lambda url: geoeffnet.append(url.toString()))
    return geoeffnet


@pytest.fixture
def dialog(qtbot, fresh_config, urls):
    dlg = sd.SupportDialog(fresh_config)
    qtbot.addWidget(dlg)
    return dlg


def _texte(dlg):
    return " ".join(label.text() for label in dlg.findChildren(QLabel))


def test_knoepfe_zeigen_betrag_aber_keine_pause(dialog):
    texte = [b.text() for b in dialog.tier_buttons.values()]
    assert "Ein Kaffee – 3 €" in texte
    assert "Ein neuer Porsche – 999 €" in texte
    assert len(texte) == len(support.TIERS)
    alles = " ".join(texte) + _texte(dialog)
    for wort in ("Monat", "Jahr", "Pause"):
        assert wort not in alles


def test_hinweis_freiwillig_ohne_freischaltung(dialog):
    text = _texte(dialog)
    assert "keine Gegenleistung" in text
    assert "keine Freischaltung" in text
    assert "Betrag" in text


def test_jede_stufe_oeffnet_den_zahlungslink(dialog, urls):
    for button in dialog.tier_buttons.values():
        button.click()
    assert urls == [support.DONATE_URL] * len(support.TIERS)


def test_leerer_link_deaktiviert_knoepfe(qtbot, fresh_config, urls, monkeypatch):
    monkeypatch.setattr(support, "DONATE_URL", "")
    dlg = sd.SupportDialog(fresh_config)
    qtbot.addWidget(dlg)
    assert not any(b.isEnabled() for b in dlg.tier_buttons.values())
    dlg.tier_buttons["kaffee"].click()
    assert urls == []


def test_spaeter_erinnern_schliesst_ohne_speichern(dialog, fresh_config):
    dialog.show()
    dialog.later_button.click()
    assert not dialog.isVisible()
    assert fresh_config.get("support_since", "") == ""


def test_selbstauskunft_speichert_und_schliesst(dialog, fresh_config):
    dialog.tier_combo.setCurrentIndex(dialog.tier_combo.findData("kaffee"))
    dialog.confirm_button.click()
    assert fresh_config.get("support_tier") == "kaffee"
    assert fresh_config.get("support_until") == (date.today() + timedelta(days=182)).isoformat()
    assert dialog.result() == dialog.DialogCode.Accepted


def test_impressum_link_nur_wenn_gesetzt(qtbot, fresh_config, monkeypatch):
    dlg = sd.SupportDialog(fresh_config)
    qtbot.addWidget(dlg)
    assert "Impressum" not in _texte(dlg)
    monkeypatch.setattr(support, "IMPRESSUM_URL", "https://example.org/impressum")
    dlg2 = sd.SupportDialog(fresh_config)
    qtbot.addWidget(dlg2)
    assert "Impressum" in _texte(dlg2)


def test_menue_und_show_support_hint(qtbot, fresh_config, monkeypatch, tmp_path):
    """Hilfe-Menue-Eintrag existiert; automatische Anzeige nur ab 50 Dokumenten."""
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QMenu

    from src.core import pdf_cache as pc_mod
    from src.ml import classifier as cl_mod
    from src.ml import hybrid_classifier as hc_mod
    from src.utils import database as db_mod
    from tests.conftest import patch_singletons

    fresh_config.set("persist_pdf_cache", False)
    monkeypatch.setattr(pc_mod.PDFCache, "_instance", None)
    db = db_mod.Database(db_path=str(tmp_path / "s.db"))
    patch_singletons(monkeypatch, {
        "get_config": lambda: fresh_config,
        "get_database": lambda: db,
        "get_classifier": cl_mod.PDFClassifier,
        "get_hybrid_classifier": hc_mod.HybridClassifier,
        "get_pdf_cache": pc_mod.PDFCache,
    })
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    from src.gui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.QMainWindow, "showMaximized", lambda self: None)
    monkeypatch.setattr(mw_mod.QMainWindow, "show", lambda self: None)
    win = mw_mod.MainWindow()
    qtbot.addWidget(win)

    gezeigt = []
    monkeypatch.setattr(sd.SupportDialog, "exec", lambda self: gezeigt.append(1))

    aktionen = [a.text() for m in win.menuBar().findChildren(QMenu) for a in m.actions()]
    assert "Unterstützen ..." in aktionen

    assert win.show_support_hint() is False  # 0 Dokumente
    assert gezeigt == []
    monkeypatch.setattr(db, "get_entry_count", lambda: 50)
    assert win.show_support_hint() is True
    assert gezeigt == [1]
    assert fresh_config.get("support_hint_last_shown") == date.today().isoformat()
    assert win.show_support_hint() is False  # erst in 30 Tagen wieder
    assert win.show_support_hint(force=True) is True
    win.close()


def test_einstellungen_nicht_mehr_erinnern_round_trip(qtbot, fresh_config):
    from src.gui.settings_dialog import SettingsDialog

    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    assert not dialog.support_hint_disabled_checkbox.isChecked()
    dialog.support_hint_disabled_checkbox.setChecked(True)
    dialog._save_settings()
    assert fresh_config.get("support_hint_disabled") is True

    dialog2 = SettingsDialog()
    qtbot.addWidget(dialog2)
    assert dialog2.support_hint_disabled_checkbox.isChecked()

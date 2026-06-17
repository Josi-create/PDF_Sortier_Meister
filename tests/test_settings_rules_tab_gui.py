"""GUI-Tests fuer den SettingsDialog-Tab 'Automatisierungs-Regeln' (Phase 21).

Testet nur den neuen Tab:
* Tab ist vorhanden und hat den richtigen Titel
* rules_list ist initialisiert
* Buttons sind vorhanden
* _refresh_rules_list befuellt die Liste aus der DB
* Toggle enabled aendert die Anzeige
"""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QTabWidget, QListWidget, QPushButton, QDialog

from src.gui.settings_dialog import SettingsDialog


# --------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------- #


@pytest.fixture
def fresh_singletons(monkeypatch, tmp_path):
    """Setzt Module-Singletons auf tmp-Pfade (wie bei MainWindow-Tests)."""
    db_path = tmp_path / "rules_tab.db"
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod
    from src.ml import classifier as cl_mod
    from src.ml import hybrid_classifier as hc_mod
    from src.core import pdf_cache as pc_mod

    fresh_config = cfg_mod.Config(config_path=tmp_path / "config.json")
    monkeypatch.setattr(cfg_mod, "get_config", lambda: fresh_config)
    monkeypatch.setattr(db_mod, "get_database",
                        lambda: db_mod.Database(db_path=str(db_path)))
    monkeypatch.setattr(cl_mod, "get_classifier", cl_mod.PDFClassifier)
    monkeypatch.setattr(hc_mod, "get_hybrid_classifier",
                        hc_mod.HybridClassifier)
    monkeypatch.setattr(pc_mod, "get_pdf_cache", pc_mod.PDFCache)
    return {"config": fresh_config, "tmp_path": tmp_path}


@pytest.fixture
def settings_dialog(qtbot, fresh_singletons):
    """Eine frische SettingsDialog-Instanz."""
    d = SettingsDialog()
    qtbot.addWidget(d)
    return d


# --------------------------------------------------------------------- #
# 1) Tab ist da
# --------------------------------------------------------------------- #


def test_settings_dialog_has_rules_tab(settings_dialog):
    """Es gibt einen Tab 'Automatisierungs-Regeln'."""
    # Finde QTabWidget
    tabs = settings_dialog.findChildren(QTabWidget)
    assert len(tabs) >= 1
    tab_widget = tabs[0]
    titles = [tab_widget.tabText(i) for i in range(tab_widget.count())]
    assert "Automatisierungs-Regeln" in titles, \
        f"Tabs: {titles}"


def test_settings_dialog_has_rules_list_widget(settings_dialog):
    """Der Regeln-Tab enthaelt eine QListWidget 'rules_list'."""
    assert hasattr(settings_dialog, "rules_list")
    assert isinstance(settings_dialog.rules_list, QListWidget)


def test_rules_list_is_empty_initially(settings_dialog):
    """Bei leerer DB ist die Liste leer."""
    assert settings_dialog.rules_list.count() == 0


# --------------------------------------------------------------------- #
# 2) Buttons sind da
# --------------------------------------------------------------------- #


def test_rules_tab_has_required_buttons(settings_dialog):
    """Die erwarteten Buttons sind vorhanden."""
    expected = ["+ Neu", "Bearbeiten", "Loeschen", "hoeher", "tiefer",
                "Aktivieren/Deaktivieren"]
    btn_texts = [b.text() for b in settings_dialog.findChildren(QPushButton)]
    for expected_text in expected:
        assert expected_text in btn_texts, \
            f"Button '{expected_text}' fehlt. Vorhanden: {btn_texts}"


# --------------------------------------------------------------------- #
# 3) refresh befuellt die Liste
# --------------------------------------------------------------------- #


def test_refresh_rules_list_shows_added_rules(settings_dialog, fresh_singletons):
    """Nach add_rule + refresh erscheint die Regel in der Liste."""
    from src.utils.database import get_database
    db = get_database()
    db.add_rule(
        name="Test-Regel",
        priority=50,
        enabled=True,
        conditions=[{"type": "korrespondent", "operator": "equals",
                     "value": "Telekom"}],
        actions=[{"type": "target_folder",
                  "template": "Rechnungen/{jahr}"}],
    )
    settings_dialog._refresh_rules_list()
    assert settings_dialog.rules_list.count() == 1
    text = settings_dialog.rules_list.item(0).text()
    assert "Test-Regel" in text
    assert "AN" in text  # enabled


def test_refresh_shows_disabled_status(settings_dialog, fresh_singletons):
    """Disabled-Regeln werden mit 'AUS' markiert."""
    from src.utils.database import get_database
    db = get_database()
    db.add_rule(name="Disabled", enabled=False)
    settings_dialog._refresh_rules_list()
    text = settings_dialog.rules_list.item(0).text()
    assert "AUS" in text


def test_refresh_sortiert_by_priority(settings_dialog, fresh_singletons):
    """Hoechste Prioritaet zuerst."""
    from src.utils.database import get_database
    db = get_database()
    db.add_rule(name="Niedrig", priority=10)
    db.add_rule(name="Hoch", priority=100)
    db.add_rule(name="Mittel", priority=50)
    settings_dialog._refresh_rules_list()
    texts = [settings_dialog.rules_list.item(i).text()
             for i in range(settings_dialog.rules_list.count())]
    # In list_rules ist die Reihenfolge priority DESC
    # Format ist "[AN] P{priority:>3}  {name}", z.B. "P100", "P 50", "P 10"
    assert "Hoch" in texts[0]
    assert "Mittel" in texts[1]
    assert "Niedrig" in texts[2]


# --------------------------------------------------------------------- #
# 4) Toggle-Button aendert enabled-Status
# --------------------------------------------------------------------- #


def test_rule_toggle_changes_enabled(settings_dialog, fresh_singletons):
    """Klick auf Toggle aendert enabled-Status in der DB."""
    from src.utils.database import get_database
    db = get_database()
    rule = db.add_rule(name="ToggleTest", enabled=True)
    settings_dialog._refresh_rules_list()
    settings_dialog.rules_list.setCurrentRow(0)
    settings_dialog._on_rule_toggle()
    # Erneut laden, Status ist jetzt AUS
    settings_dialog._refresh_rules_list()
    text = settings_dialog.rules_list.item(0).text()
    assert "AUS" in text
    # DB-Status
    r = db.get_rule(rule["id"])
    assert r["enabled"] is False


# --------------------------------------------------------------------- #
# 5) Reihenfolge (up/down)
# --------------------------------------------------------------------- #


def test_rule_up_swaps_order(settings_dialog, fresh_singletons):
    """'hoeher'-Button verschiebt eine Regel nach oben (niedrigere Zeile)."""
    from src.utils.database import get_database
    db = get_database()
    db.add_rule(name="A", priority=10)
    db.add_rule(name="B", priority=20)
    settings_dialog._refresh_rules_list()
    # Initial: B (prio 20) oben, A (prio 10) unten
    assert "B" in settings_dialog.rules_list.item(0).text()
    # A (Zeile 1) nach oben
    settings_dialog.rules_list.setCurrentRow(1)
    settings_dialog._on_rule_up()
    # Jetzt sollte A oben sein
    assert "A" in settings_dialog.rules_list.item(0).text()


def test_rule_down_swaps_order(settings_dialog, fresh_singletons):
    """'tiefer'-Button verschiebt eine Regel nach unten (hoehere Zeile).

    list_rules ist sortiert nach priority DESC. Initial:
        Position 0: Y (priority 20)
        Position 1: X (priority 10)

    Nach _on_rule_down auf Position 0 (Y) wird Y nach unten getauscht:
        Position 0: X (priority bleibt 10)
        Position 1: Y (priority bleibt 20)
    """
    from src.utils.database import get_database
    db = get_database()
    db.add_rule(name="X", priority=10)
    db.add_rule(name="Y", priority=20)
    settings_dialog._refresh_rules_list()
    assert "Y" in settings_dialog.rules_list.item(0).text()
    assert "X" in settings_dialog.rules_list.item(1).text()
    settings_dialog.rules_list.setCurrentRow(0)
    settings_dialog._on_rule_down()
    assert "X" in settings_dialog.rules_list.item(0).text()
    assert "Y" in settings_dialog.rules_list.item(1).text()


# --------------------------------------------------------------------- #
# 6) selected_rule Hilfsmethode
# --------------------------------------------------------------------- #


def test_selected_rule_returns_dict(settings_dialog, fresh_singletons):
    """_selected_rule returnt das volle Regel-Dict."""
    from src.utils.database import get_database
    db = get_database()
    rule = db.add_rule(name="Selected")
    settings_dialog._refresh_rules_list()
    settings_dialog.rules_list.setCurrentRow(0)
    sel = settings_dialog._selected_rule()
    assert sel is not None
    assert sel["name"] == "Selected"
    assert sel["id"] == rule["id"]


def test_selected_rule_returns_none_when_nothing_selected(settings_dialog):
    """Ohne Selektion returnt _selected_rule None."""
    assert settings_dialog._selected_rule() is None

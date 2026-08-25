"""GUI-Tests fuer den RuleEditDialog (Phase 21 / Issue #22)."""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QDialog, QLineEdit, QListWidget

from src.gui.rule_edit_dialog import RuleEditDialog


@pytest.fixture
def dialog(qtbot):
    d = RuleEditDialog()
    qtbot.addWidget(d)
    return d


# --------------------------------------------------------------------- #
# 1) Konstruktion
# --------------------------------------------------------------------- #


def test_dialog_instantiates_with_no_initial_data(qtbot):
    """Default-Dialog hat leere Felder und leere Bedingungen/Aktionen."""
    d = RuleEditDialog()
    qtbot.addWidget(d)
    assert d.name_edit.text() == ""
    assert d.cond_list.count() == 0
    assert d.act_list.count() == 0


def test_dialog_instantiates_with_initial_data(qtbot):
    """Mit initial_data werden Felder befuellt und Bedingungen/Aktionen geladen."""
    d = RuleEditDialog(
        initial_data={
            "name": "Finanzamt-Steuer",
            "priority": 100,
            "enabled": False,
            "conditions": [
                {"type": "korrespondent", "operator": "equals", "value": "Finanzamt"},
            ],
            "actions": [
                {"type": "target_folder", "template": "Steuern/{steuerjahr}"},
            ],
        }
    )
    qtbot.addWidget(d)
    assert d.name_edit.text() == "Finanzamt-Steuer"
    assert d.priority_spin.value() == 100
    assert d.enabled_check.isChecked() is False
    assert d.cond_list.count() == 1
    assert d.act_list.count() == 1


def test_dialog_has_required_widgets(qtbot):
    """Die wichtigsten Widgets sind im Dialog vorhanden."""
    d = RuleEditDialog()
    qtbot.addWidget(d)
    assert isinstance(d.name_edit, QLineEdit)
    assert isinstance(d.priority_spin, type(d.priority_spin))  # QSpinBox
    assert isinstance(d.enabled_check, type(d.enabled_check))   # QCheckBox
    assert isinstance(d.cond_list, QListWidget)
    assert isinstance(d.act_list, QListWidget)


# --------------------------------------------------------------------- #
# 2) Interne Helfer (append_condition/append_action)
# --------------------------------------------------------------------- #


def test_append_condition_adds_to_list(qtbot):
    """_append_condition fuegt Eintrag korrekt in die Liste ein."""
    d = RuleEditDialog()
    qtbot.addWidget(d)
    cond = {"type": "kategorie", "operator": "equals", "value": "Rechnung"}
    d._append_condition(cond)
    assert d.cond_list.count() == 1
    text = d.cond_list.item(0).text()
    assert "kategorie" in text
    assert "equals" in text


def test_append_action_adds_target_folder(qtbot):
    """target_folder-Aktion wird mit 'template' angezeigt."""
    d = RuleEditDialog()
    qtbot.addWidget(d)
    action = {"type": "target_folder", "template": "Steuern/{steuerjahr}"}
    d._append_action(action)
    assert d.act_list.count() == 1
    text = d.act_list.item(0).text()
    assert "target_folder" in text
    assert "Steuern" in text


def test_append_action_adds_metadata_field(qtbot):
    """metadata_field-Aktion wird mit Feld=Wert angezeigt."""
    d = RuleEditDialog()
    qtbot.addWidget(d)
    action = {"type": "metadata_field", "field": "steuerjahr", "value": "auto"}
    d._append_action(action)
    assert d.act_list.count() == 1
    text = d.act_list.item(0).text()
    assert "metadata_field" in text
    assert "steuerjahr" in text


# --------------------------------------------------------------------- #
# 3) get_data() (Accept-Pfad)
# --------------------------------------------------------------------- #


def test_get_data_returns_none_before_accept(qtbot):
    """Vor Accept returnt get_data() None."""
    d = RuleEditDialog()
    qtbot.addWidget(d)
    assert d.result() != QDialog.DialogCode.Accepted
    assert d.get_data() is None


def test_get_data_returns_dict_after_accept_with_name(qtbot):
    """Nach Accept mit Name liefert get_data() ein vollstaendiges Dict."""
    d = RuleEditDialog()
    qtbot.addWidget(d)
    d.name_edit.setText("Test-Regel")
    d.priority_spin.setValue(50)
    d.enabled_check.setChecked(False)
    d._append_condition({"type": "korrespondent", "operator": "equals",
                          "value": "Telekom"})
    d._append_action({"type": "target_folder", "template": "Rechnungen/{jahr}"})
    d.accept()
    data = d.get_data()
    assert data is not None
    assert data["name"] == "Test-Regel"
    assert data["priority"] == 50
    assert data["enabled"] is False
    assert len(data["conditions"]) == 1
    assert len(data["actions"]) == 1


def test_get_data_collects_multiple_conditions(qtbot):
    """Mehrere Bedingungen werden in der Reihenfolge gesammelt."""
    d = RuleEditDialog()
    qtbot.addWidget(d)
    d.name_edit.setText("Multi")
    d._append_condition({"type": "korrespondent", "operator": "equals",
                          "value": "Telekom"})
    d._append_condition({"type": "betrag", "operator": "gt", "value": 100})
    d.accept()
    data = d.get_data()
    assert data["conditions"][0]["type"] == "korrespondent"
    assert data["conditions"][1]["type"] == "betrag"


# --------------------------------------------------------------------- #
# 4) Cancel-Pfad
# --------------------------------------------------------------------- #


def test_dialog_rejects_with_cancel(qtbot):
    """Cancel setzt result=Rejected und get_data() returnt None."""
    d = RuleEditDialog()
    qtbot.addWidget(d)
    d.name_edit.setText("WirdNichtGespeichert")
    d.reject()
    assert d.result() == QDialog.DialogCode.Rejected
    assert d.get_data() is None


def test_dialog_remove_handlers_do_not_crash_on_empty(qtbot):
    """Remove-Buttons auf leerer Liste crashen nicht (silent no-op)."""
    d = RuleEditDialog()
    qtbot.addWidget(d)
    d._remove_condition()
    d._remove_action()
    assert d.cond_list.count() == 0
    assert d.act_list.count() == 0

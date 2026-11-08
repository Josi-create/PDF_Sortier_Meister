"""#125: Das Regel-Feature ist entfernt, die Tabelle ``automation_rules`` bleibt.

Bestehende Datenbanken mit gespeicherten Regeln muessen weiter ohne Migration
oeffnen und ihre Zeilen behalten.
"""
import sqlite3

from src.utils.database import Database


def test_bestehende_db_mit_regeln_oeffnet_und_behaelt_zeilen(tmp_path):
    db_path = tmp_path / "history.db"
    first = Database(db_path=db_path)
    first.engine.dispose()

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO automation_rules (name, priority, enabled, conditions_json,"
        " actions_json) VALUES ('alt', 5, 1, '[]', '[]')"
    )
    conn.commit()
    conn.close()

    second = Database(db_path=db_path)
    second.engine.dispose()

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT name FROM automation_rules").fetchall()
    conn.close()
    assert rows == [("alt",)]


def test_module_importierbar_ohne_regel_code():
    import src.gui.main_window  # noqa: F401
    import src.gui.settings_dialog  # noqa: F401

    assert not hasattr(src.gui.main_window.MainWindow, "_check_automation_rules")
    assert not hasattr(src.gui.settings_dialog.SettingsDialog, "_create_rules_tab")

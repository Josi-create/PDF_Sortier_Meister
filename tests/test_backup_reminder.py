"""Issue #14: Backup-Erinnerung - Faelligkeitslogik und Hauptfenster."""
import os
import time
from datetime import datetime, timedelta

from PyQt6.QtWidgets import QMessageBox

from src.core.backup_reminder import is_question_due, macrium_last_backup, parse_date
from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401 - Fixtures

NOW = datetime(2026, 11, 7, 12, 0)


def test_due_when_never_confirmed():
    assert is_question_due(7, None, now=NOW)


def test_not_due_within_interval():
    assert not is_question_due(7, NOW - timedelta(days=3), now=NOW)


def test_due_after_interval():
    assert is_question_due(7, NOW - timedelta(days=7), now=NOW)


def test_zero_days_disables():
    assert not is_question_due(0, None, now=NOW)
    assert not is_question_due(0, NOW - timedelta(days=100), now=NOW)


def test_invalid_days_disables():
    assert not is_question_due("abc", None, now=NOW)
    assert not is_question_due(-3, None, now=NOW)


def test_not_due_while_pending():
    assert not is_question_due(7, None, pending=True, now=NOW)


def test_recent_macrium_log_skips_question():
    assert not is_question_due(7, None, macrium_last=NOW - timedelta(days=2), now=NOW)


def test_old_macrium_log_still_asks():
    assert is_question_due(7, None, macrium_last=NOW - timedelta(days=20), now=NOW)


def test_parse_date():
    assert parse_date("2026-11-07T12:00:00") == NOW
    assert parse_date("") is None
    assert parse_date("kaputt") is None
    assert parse_date(None) is None


def test_macrium_missing_dir_returns_none(tmp_path):
    assert macrium_last_backup(tmp_path / "gibt-es-nicht") is None


def test_macrium_empty_dir_returns_none(tmp_path):
    assert macrium_last_backup(tmp_path) is None


def test_macrium_uses_newest_html_log(tmp_path):
    alt = tmp_path / "a.html"
    neu = tmp_path / "b.html"
    andere = tmp_path / "c.vsslog"
    for p in (alt, neu, andere):
        p.write_text("x")
    t_alt = time.time() - 10 * 86400
    t_neu = time.time() - 2 * 86400
    os.utime(alt, (t_alt, t_alt))
    os.utime(neu, (t_neu, t_neu))
    os.utime(andere, (time.time(), time.time()))  # zaehlt nicht
    assert abs(macrium_last_backup(tmp_path).timestamp() - t_neu) < 2


# --- Hauptfenster -------------------------------------------------------- #

def _ask(monkeypatch, answer):
    calls = []

    def fake(*a, **k):
        calls.append(a)
        return answer

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake))
    return calls


def _no_macrium(monkeypatch):
    from src.gui import main_window as mw
    monkeypatch.setattr(mw, "macrium_last_backup", lambda: None)


def test_answer_yes_stores_date_and_hides_label(main_window, monkeypatch):
    _no_macrium(monkeypatch)
    _ask(monkeypatch, QMessageBox.StandardButton.Yes)
    main_window.check_backup_reminder()
    cfg = main_window.config
    assert parse_date(cfg.get("backup_last_confirmed")) is not None
    assert cfg.get("backup_pending") is False
    assert main_window.backup_status_label.isHidden()


def test_answer_no_shows_label_and_pending(main_window, monkeypatch):
    _no_macrium(monkeypatch)
    _ask(monkeypatch, QMessageBox.StandardButton.No)
    main_window.check_backup_reminder()
    assert main_window.config.get("backup_pending") is True
    assert not main_window.backup_status_label.isHidden()
    assert main_window.config.get("backup_last_confirmed") == ""


def test_pending_does_not_ask_again(main_window, monkeypatch):
    _no_macrium(monkeypatch)
    main_window.config.set("backup_pending", True)
    calls = _ask(monkeypatch, QMessageBox.StandardButton.No)
    main_window.check_backup_reminder()
    assert calls == []


def test_confirm_via_label_clears_pending(main_window, monkeypatch):
    _no_macrium(monkeypatch)
    _ask(monkeypatch, QMessageBox.StandardButton.No)
    main_window.check_backup_reminder()
    main_window.backup_status_label.clicked.emit()
    assert main_window.config.get("backup_pending") is False
    assert main_window.backup_status_label.isHidden()
    assert parse_date(main_window.config.get("backup_last_confirmed")) is not None


def test_zero_days_never_asks(main_window, monkeypatch):
    _no_macrium(monkeypatch)
    main_window.config.set("backup_check_days", 0)
    calls = _ask(monkeypatch, QMessageBox.StandardButton.No)
    main_window.check_backup_reminder()
    assert calls == []


def test_recent_confirmation_does_not_ask(main_window, monkeypatch):
    _no_macrium(monkeypatch)
    main_window.config.set("backup_last_confirmed", datetime.now().isoformat())
    calls = _ask(monkeypatch, QMessageBox.StandardButton.No)
    main_window.check_backup_reminder()
    assert calls == []

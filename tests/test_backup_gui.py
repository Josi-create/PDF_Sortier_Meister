"""Issue #98: Extras > Daten sichern / wiederherstellen im Hauptfenster."""
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401 - Fixtures


def _menu_texts(win):
    extras = next(m for m in win.menuBar().findChildren(type(win.menuBar().actions()[0].menu()))
                  if m.title() == "Extras")
    return [a.text() for a in extras.actions() if a.text()]


def test_extras_menu_has_backup_actions(main_window):
    texts = _menu_texts(main_window)
    assert "Daten sichern (ZIP)..." in texts
    assert "Daten aus Sicherung wiederherstellen..." in texts


def test_backup_writes_zip(main_window, fresh_singletons, monkeypatch, tmp_path):
    from src.utils.backup import inspect_backup
    target = tmp_path / "sicherung.zip"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a[2])))

    main_window.backup_app_data()

    assert target.exists()
    info = inspect_backup(target)
    assert "config.json" in info.entries
    assert shown and "gesichert" in shown[0]


def test_backup_cancelled_writes_nothing(main_window, monkeypatch, tmp_path):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    main_window.backup_app_data()
    assert not list(tmp_path.glob("*.zip"))


def test_restore_stages_backup_and_closes(main_window, fresh_singletons, monkeypatch, tmp_path):
    from src.utils.backup import PENDING_DIR, create_backup
    data_dir = fresh_singletons["config"].data_dir
    zip_path = tmp_path / "b.zip"
    create_backup(data_dir, zip_path)

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(zip_path), "")))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    closed = []
    monkeypatch.setattr(type(main_window), "close", lambda self: closed.append(True))

    main_window.restore_app_data()

    assert (Path(data_dir) / PENDING_DIR / "config.json").exists()
    assert closed == [True]


def test_restore_declined_does_nothing(main_window, fresh_singletons, monkeypatch, tmp_path):
    from src.utils.backup import PENDING_DIR, create_backup
    data_dir = fresh_singletons["config"].data_dir
    zip_path = tmp_path / "b.zip"
    create_backup(data_dir, zip_path)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(zip_path), "")))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    main_window.restore_app_data()
    assert not (Path(data_dir) / PENDING_DIR).exists()


def test_restore_rejects_foreign_zip(main_window, monkeypatch, tmp_path):
    import zipfile
    foreign = tmp_path / "foreign.zip"
    with zipfile.ZipFile(foreign, "w") as zf:
        zf.writestr("readme.txt", "x")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(foreign), "")))
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: errors.append(a[1])))
    main_window.restore_app_data()
    assert errors == ["Keine gültige Sicherung"]

"""GUI-Tests: Default-Ordnervorschlaege und Zielordner-Schritt im
Einrichtungs-Assistenten (Issues #61, #64).

QStandardPaths.DocumentsLocation wird in jedem Test auf einen Ordner unter
tmp_path umgebogen - die Default-Vorschlaege duerfen NIE auf echte
Nutzerordner (%USERPROFILE%\\Documents) zeigen, weder beim Anzeigen noch beim
tatsaechlichen Anlegen der Ordner auf der Platte.
"""
from __future__ import annotations

from src.gui import setup_wizard as wiz
from src.gui.setup_wizard import (
    SetupWizard,
    PAGE_SCAN_FOLDER,
    PAGE_TARGET_FOLDER,
)


def _patch_documents_dir(monkeypatch, docs_dir):
    """Biegt den von Qt gemeldeten Dokumente-Ordner auf ``docs_dir`` um."""
    monkeypatch.setattr(
        wiz.QStandardPaths, "writableLocation", lambda loc: str(docs_dir)
    )


def test_scan_folder_page_prefills_default_suggestion(qtbot, fresh_config, monkeypatch, tmp_path):
    """Ohne konfigurierten Scan-Ordner schlaegt die Seite <Dokumente>/Scans vor."""
    docs = tmp_path / "Documents"
    _patch_documents_dir(monkeypatch, docs)

    w = SetupWizard()
    qtbot.addWidget(w)
    page = w.page(PAGE_SCAN_FOLDER)

    assert page.get_folder() == str(docs / "Scans")


def test_target_folder_page_prefills_default_suggestion(qtbot, fresh_config, monkeypatch, tmp_path):
    """Ohne konfigurierten Zielordner schlaegt die Seite <Dokumente>/PDF-Sammlung vor."""
    docs = tmp_path / "Documents"
    _patch_documents_dir(monkeypatch, docs)

    w = SetupWizard()
    qtbot.addWidget(w)
    page = w.page(PAGE_TARGET_FOLDER)

    assert page.get_folder() == str(docs / "PDF-Sammlung")


def test_existing_scan_folder_is_not_overridden_by_default(qtbot, fresh_config, monkeypatch, tmp_path):
    docs = tmp_path / "Documents"
    _patch_documents_dir(monkeypatch, docs)
    existing = tmp_path / "MeineScans"
    fresh_config.set_scan_folder(existing)

    w = SetupWizard()
    qtbot.addWidget(w)
    page = w.page(PAGE_SCAN_FOLDER)

    assert page.get_folder() == str(existing)


def test_existing_target_folder_is_not_overridden_by_default(qtbot, fresh_config, monkeypatch, tmp_path):
    docs = tmp_path / "Documents"
    _patch_documents_dir(monkeypatch, docs)
    existing = tmp_path / "MeineAblage"
    fresh_config.add_target_folder(existing)

    w = SetupWizard()
    qtbot.addWidget(w)
    page = w.page(PAGE_TARGET_FOLDER)

    assert page.get_folder() == str(existing)


def test_finish_creates_both_folders_and_registers_target(qtbot, fresh_config, monkeypatch, tmp_path):
    """'Fertig' legt Scan- und Zielordner an (falls sie fehlen) und
    registriert den Zielordner in der Config (Issues #61, #64)."""
    docs = tmp_path / "Documents"
    _patch_documents_dir(monkeypatch, docs)
    scan_folder = docs / "Scans"
    target_folder = docs / "PDF-Sammlung"

    w = SetupWizard()
    qtbot.addWidget(w)
    assert not scan_folder.exists()
    assert not target_folder.exists()

    w.accept()

    assert scan_folder.is_dir()
    assert target_folder.is_dir()
    assert fresh_config.get_scan_folder() == scan_folder
    assert target_folder in fresh_config.get_target_folders()


def test_cancel_still_creates_folders_like_scan_folder_behavior(qtbot, fresh_config, monkeypatch, tmp_path):
    """'Spaeter'/Schliessen uebernimmt - wie schon beim Scan-Ordner ueblich -
    was aktuell in den Feldern steht, damit kein halbfertiges Setup verloren
    geht; das gilt jetzt auch fuer den neuen Zielordner-Schritt."""
    docs = tmp_path / "Documents"
    _patch_documents_dir(monkeypatch, docs)
    scan_folder = docs / "Scans"
    target_folder = docs / "PDF-Sammlung"

    w = SetupWizard()
    qtbot.addWidget(w)

    w.reject()

    assert scan_folder.is_dir()
    assert target_folder.is_dir()
    assert fresh_config.get_scan_folder() == scan_folder
    assert target_folder in fresh_config.get_target_folders()


def test_target_folder_not_registered_twice(qtbot, fresh_config, monkeypatch, tmp_path):
    """Ist der vorgeschlagene Zielordner schon registriert, darf er beim
    Abschluss nicht doppelt in der Liste landen."""
    docs = tmp_path / "Documents"
    _patch_documents_dir(monkeypatch, docs)
    target_folder = docs / "PDF-Sammlung"
    fresh_config.add_target_folder(target_folder)

    w = SetupWizard()
    qtbot.addWidget(w)
    w.accept()

    assert fresh_config.get_target_folders().count(target_folder) == 1


def test_user_can_pick_different_target_folder(qtbot, fresh_config, monkeypatch, tmp_path):
    """Waehlt der Nutzer ueber 'Ordner auswaehlen' einen anderen Ordner,
    wird dieser (nicht der Default) angelegt und registriert."""
    docs = tmp_path / "Documents"
    _patch_documents_dir(monkeypatch, docs)
    chosen = tmp_path / "Kundendaten" / "Abgelegt"

    w = SetupWizard()
    qtbot.addWidget(w)
    target_page = w.page(PAGE_TARGET_FOLDER)
    target_page.path_edit.setText(str(chosen))

    w.accept()

    default_target = docs / "PDF-Sammlung"
    assert chosen.is_dir()
    assert not default_target.exists()
    assert chosen in fresh_config.get_target_folders()

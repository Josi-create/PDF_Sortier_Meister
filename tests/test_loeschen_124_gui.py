"""Issue #124: Loeschen per Papierkorb mit Rueckgaengig (Ctrl+Z)."""
import shutil

import pytest

from tests import helfer_suche as h
from tests.test_file_manager import _fake_papierkorb
from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401 - Fixtures
from tests.test_pdf_drehen_150_gui import beobachtet  # noqa: F401 - Fixture


@pytest.fixture
def ordner(fresh_singletons, monkeypatch):  # noqa: F811
    from src.gui import main_window as mw_mod
    ordner = fresh_singletons["tmp_path"] / "Scan"
    ordner.mkdir()
    h.scan_schief(ordner / "a.pdf", 0)
    h.scan_schief(ordner / "b.pdf", 0)
    monkeypatch.setattr(mw_mod.QMessageBox, "question", lambda *a, **k: mw_mod.QMessageBox.StandardButton.Yes)
    return ordner


def test_loeschen_und_rueckgaengig(main_window, ordner, beobachtet, monkeypatch):  # noqa: F811
    _fake_papierkorb(monkeypatch, ordner.parent / "trash")
    main_window._navigate_to_folder(ordner)
    a = ordner / "a.pdf"

    main_window.on_pdf_delete(a)

    assert not a.exists()
    assert all(w.pdf_path != a for w in main_window.pdf_widgets)
    eintrag = main_window._undo_stack[-1]
    assert eintrag["type"] == "delete" and "Löschen: a.pdf" in main_window.undo_action.text()

    main_window.undo_last_action()
    assert a.exists() and not main_window._undo_stack
    assert any(w.pdf_path == a for w in main_window.pdf_widgets)


def test_rueckgaengig_meldet_fehlende_datei_im_papierkorb(main_window, ordner, beobachtet, monkeypatch):  # noqa: F811
    _fake_papierkorb(monkeypatch, ordner.parent / "trash")
    main_window._navigate_to_folder(ordner)
    a = ordner / "a.pdf"
    main_window.on_pdf_delete(a)
    main_window._undo_stack[-1]["papierkorb"].unlink()

    main_window.undo_last_action()

    assert not a.exists() and "nicht mehr im Papierkorb" in beobachtet["warnung"][-1]


def test_rueckgaengig_meldet_belegtes_ziel(main_window, ordner, beobachtet, monkeypatch):  # noqa: F811
    _fake_papierkorb(monkeypatch, ordner.parent / "trash")
    main_window._navigate_to_folder(ordner)
    a = ordner / "a.pdf"
    main_window.on_pdf_delete(a)
    shutil.copy(ordner / "b.pdf", a)

    main_window.undo_last_action()

    assert "existiert bereits" in beobachtet["warnung"][-1]
    assert main_window._undo_stack == []


def test_ohne_papierkorb_fragt_und_loescht_endgueltig_ohne_undo(main_window, ordner, beobachtet, monkeypatch):  # noqa: F811
    from src.gui import main_window as mw_mod
    _fake_papierkorb(monkeypatch, ordner.parent / "trash", ok=False)
    fragen = []
    ja = mw_mod.QMessageBox.StandardButton.Yes
    monkeypatch.setattr(mw_mod.QMessageBox, "question", lambda *a, **k: fragen.append(a[2]) or ja)
    main_window._navigate_to_folder(ordner)
    a = ordner / "a.pdf"

    main_window.on_pdf_delete(a)

    assert not a.exists() and not main_window._undo_stack
    assert len(fragen) == 2 and "Papierkorb nicht verfügbar – endgültig löschen?" in fragen[1]

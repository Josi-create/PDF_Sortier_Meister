"""Nebenbefunde aus der Planungsrunde 09/2026 (Fahrplan v0.24).

Vier kleine Fehler rund ums Verschieben, jeder mit eigenem Test:

1. ``on_pdf_move`` benutzte ein undefiniertes ``folder_path`` und zeigte nach
   erfolgreichem "Verschieben nach..." einen Fehlerdialog (NameError).
2. Drop auf eine gruene Vorschlagskachel war ein stilles No-op, weil
   ``pdf_dropped`` in ``display_suggestions`` nie verbunden wurde.
3. "Aus Zielliste entfernen" auf Vorschlagskacheln war toter Code.
4. Root-Ordner entfernen scannte den Zielbaum zweimal.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6 import sip

from src.gui.folder_tree_widget import FolderTreeWidget
from src.gui.folder_widget import FolderWidget
from src.ml.classifier import Suggestion

from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401


def _pdf(folder: Path, name: str = "scan.pdf") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return p


# 1) "Verschieben nach..." ---------------------------------------------------


def test_on_pdf_move_moves_without_error_dialog(main_window, fresh_singletons, monkeypatch):  # noqa: F811
    from src.gui import main_window as mw_mod

    tmp = fresh_singletons["tmp_path"]
    pdf = _pdf(tmp / "Scan")
    target = tmp / "Ziel" / "Ablage"
    target.mkdir(parents=True)

    monkeypatch.setattr(
        mw_mod.QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(target))
    )

    def boom(*args, **kwargs):  # pragma: no cover - nur bei Regression
        raise AssertionError(f"Fehlerdialog nach erfolgreichem Verschieben: {args[2:]}")

    monkeypatch.setattr(mw_mod.QMessageBox, "critical", staticmethod(boom))

    main_window.on_pdf_move(pdf)

    assert not pdf.exists()
    assert (target / "scan.pdf").exists()


# 2) Drop auf Vorschlagskachel ----------------------------------------------


def test_drop_on_suggestion_tile_is_wired(main_window, fresh_singletons, monkeypatch):  # noqa: F811
    tmp = fresh_singletons["tmp_path"]
    target = tmp / "Ziel" / "Rechnungen"
    target.mkdir(parents=True)
    pdf = _pdf(tmp / "Scan")

    received = []
    monkeypatch.setattr(
        main_window, "on_pdf_dropped_on_folder", lambda p, f: received.append((p, f))
    )

    main_window.display_suggestions(
        [Suggestion(folder_path=target, folder_name="Rechnungen", confidence=0.8, reason="Test")]
    )
    tile = main_window.suggestion_widgets[0]
    assert tile.is_suggestion

    tile.pdf_dropped.emit(pdf, target)

    assert received == [(pdf, target)]


# 3) Kontextmenue auf Kacheln ----------------------------------------------


def test_suggestion_tile_has_no_remove_entry(qtbot, tmp_path):
    w = FolderWidget(tmp_path, 0)
    qtbot.addWidget(w)
    w.is_suggestion = True

    texts = [a.text() for a in w._build_context_menu().actions() if not a.isSeparator()]

    assert texts and "Aus Zielliste entfernen" not in texts


def test_target_tile_keeps_remove_entry(qtbot, tmp_path):
    w = FolderWidget(tmp_path, 0)
    qtbot.addWidget(w)

    texts = [a.text() for a in w._build_context_menu().actions() if not a.isSeparator()]

    assert "Aus Zielliste entfernen" in texts


# 4) Root entfernen: ein Scan statt zwei ------------------------------------


def test_remove_root_scans_tree_once(main_window, fresh_singletons, monkeypatch):  # noqa: F811
    tmp = fresh_singletons["tmp_path"]
    root_a = tmp / "Ziel A"
    root_b = tmp / "Ziel B"
    root_a.mkdir()
    root_b.mkdir()
    cfg = fresh_singletons["config"]
    cfg.add_target_folder(root_a)
    cfg.add_target_folder(root_b)
    main_window.folder_manager.add_folder(root_a)
    main_window.folder_manager.add_folder(root_b)

    tree: FolderTreeWidget = main_window.folder_tree
    tree.async_scan = False
    main_window.load_folders()
    assert tree.has_folder(root_a) and tree.has_folder(root_b)

    scans = []
    original = tree.refresh_tree
    monkeypatch.setattr(tree, "refresh_tree", lambda: (scans.append(1), original())[1])

    # Wie ueber das Kontextmenue "Aus Zielliste entfernen"
    tree._remove_folder(root_a)

    assert len(scans) == 1
    assert not tree.has_folder(root_a) and tree.has_folder(root_b)
    assert root_a not in main_window.folder_manager.target_folders

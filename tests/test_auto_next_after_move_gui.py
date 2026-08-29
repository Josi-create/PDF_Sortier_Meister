"""GUI-Tests fuer Issue #75: Nach dem Wegsortieren automatisch die naechste
PDF auswaehlen.

Deckt die drei Verschiebe-Pfade ab, die ``remove_pdf_widget`` aufrufen:
``move_pdf_to_folder_and_learn`` (Einzelauswahl, Klick auf Vorschlag/Ordner),
``move_multiple_pdfs_to_folder`` (Mehrfachauswahl) sowie den Fall, dass die
verschobene PDF gar nicht die ausgewaehlte war (keine Auto-Auswahl).

Fixtures folgen dem Muster aus ``tests/test_main_window_gui.py``: Singletons
werden auf tmp-Pfade umgebogen, damit nie gegen die echte Nutzer-Config in
%APPDATA% getestet wird.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6 import sip
from PyQt6.QtWidgets import QMessageBox


# --------------------------------------------------------------------- #
# Fixtures: Singletons monkeypatchen (identisch zu test_main_window_gui.py)
# --------------------------------------------------------------------- #


@pytest.fixture
def fresh_singletons(monkeypatch, tmp_path):
    """Setzt die Module-Singletons auf tmp-Pfade und leere Defaults."""
    db_path = tmp_path / "auto_next_smoke.db"
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod
    from src.ml import classifier as cl_mod
    from src.ml import hybrid_classifier as hc_mod
    from src.core import pdf_cache as pc_mod

    from tests.conftest import patch_singletons
    fresh_config = cfg_mod.Config(config_path=tmp_path / "config.json")
    fresh_config.set("persist_pdf_cache", False)
    monkeypatch.setattr(pc_mod.PDFCache, "_instance", None)
    patch_singletons(monkeypatch, {
        "get_config": lambda: fresh_config,
        "get_database": lambda: db_mod.Database(db_path=str(db_path)),
        "get_classifier": cl_mod.PDFClassifier,
        "get_hybrid_classifier": hc_mod.HybridClassifier,
        "get_pdf_cache": pc_mod.PDFCache,
    })

    return {"config": fresh_config, "tmp_path": tmp_path}


@pytest.fixture
def main_window(qtbot, fresh_singletons, monkeypatch):
    """Eine frische MainWindow-Instanz, headless."""
    from PyQt6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)

    from src.gui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.QMainWindow, "showMaximized", lambda self: None)
    monkeypatch.setattr(mw_mod.QMainWindow, "show", lambda self: None)

    # Keine Thumbnail-Threads: die halten die PDF unter Windows kurz offen,
    # und ein Verschieben waehrenddessen scheitert (PermissionError) - auf
    # langsamen CI-Runnern schlug so der erste Test der Sitzung fehl.
    from src.gui import pdf_thumbnail as th_mod
    monkeypatch.setattr(th_mod.ThumbnailLoaderThread, "start", lambda self: None)

    # Modale Dialoge duerfen den Test nie blockieren: Verschieben immer
    # bestaetigen, Fehler-/Warn-Dialoge nur protokollieren.
    monkeypatch.setattr(
        mw_mod.QMessageBox, "question",
        lambda *a, **k: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(mw_mod.QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(mw_mod.QMessageBox, "warning", lambda *a, **k: None)

    win = mw_mod.MainWindow()
    # Modell als "sofort bereit" behandeln: sonst haengt der Klick-Pfad in
    # _wait_for_model_then_apply an einem Hintergrund-Timer, der beim
    # Schliessen des Fensters nicht garantiert den Override-Cursor
    # zuruecksetzt (siehe closeEvent) und so Folge-Tests verunreinigt.
    monkeypatch.setattr(win.classifier, "is_model_ready", lambda: True)

    yield win

    win.close()
    sip.delete(win)


def _make_scan_folder(tmp_path: Path, names: list[str]) -> Path:
    """Legt einen Scan-Ordner mit minimalen PDF-Dateien an."""
    scan = tmp_path / "Scan"
    scan.mkdir()
    for name in names:
        (scan / name).write_bytes(b"%PDF-1.4\n%%EOF\n")
    return scan


def _prime_cache(main_window, paths: list[Path]) -> None:
    """Legt fuer jede PDF ein leeres Analyse-Ergebnis synchron in den Cache.

    Ohne das wuerde ``update_suggestions_for_pdf`` bei jedem Klick einen
    Hintergrund-Analyse-Worker anstossen (``request_analysis``) - fuer diese
    Tests irrelevant und eine Quelle fuer Nebenlaeufigkeit/Testverunreinigung.
    """
    from src.core.pdf_cache import PDFAnalysisResult

    for path in paths:
        main_window.pdf_cache._cache[path] = PDFAnalysisResult(
            pdf_path=path,
            file_modified=path.stat().st_mtime,
        )


# --------------------------------------------------------------------- #
# Einzelauswahl: move_pdf_to_folder_and_learn
# --------------------------------------------------------------------- #


def test_move_selects_next_pdf_in_same_grid_slot(main_window, fresh_singletons):
    """Wird die ausgewaehlte PDF aus der Mitte weggeraeumt, ruckt die naechste
    an dieselbe Rasterposition und wird automatisch ausgewaehlt."""
    scan = _make_scan_folder(fresh_singletons["tmp_path"], ["a.pdf", "b.pdf", "c.pdf"])
    ziel = fresh_singletons["tmp_path"] / "Ziel"
    ziel.mkdir()
    main_window._navigate_to_folder(scan)
    assert len(main_window.pdf_widgets) == 3
    _prime_cache(main_window, [w.pdf_path for w in main_window.pdf_widgets])

    middle_path = main_window.pdf_widgets[1].pdf_path
    remaining_path = main_window.pdf_widgets[2].pdf_path

    main_window.on_pdf_clicked(middle_path)
    assert main_window.selected_pdf == middle_path

    main_window.move_pdf_to_folder_and_learn(middle_path, ziel)

    assert len(main_window.pdf_widgets) == 2
    assert main_window.selected_pdf == remaining_path
    selected_widgets = [w for w in main_window.pdf_widgets if w.selected]
    assert [w.pdf_path for w in selected_widgets] == [remaining_path]


def test_move_last_pdf_selects_new_last_pdf(main_window, fresh_singletons):
    """War die zuletzt im Raster stehende PDF ausgewaehlt, wird nach dem
    Verschieben die neue letzte PDF ausgewaehlt."""
    scan = _make_scan_folder(fresh_singletons["tmp_path"], ["a.pdf", "b.pdf", "c.pdf"])
    ziel = fresh_singletons["tmp_path"] / "Ziel"
    ziel.mkdir()
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [w.pdf_path for w in main_window.pdf_widgets])

    last_path = main_window.pdf_widgets[-1].pdf_path
    new_last_path = main_window.pdf_widgets[-2].pdf_path

    main_window.on_pdf_clicked(last_path)
    main_window.move_pdf_to_folder_and_learn(last_path, ziel)

    assert len(main_window.pdf_widgets) == 2
    assert main_window.selected_pdf == new_last_path


def test_move_last_remaining_pdf_clears_selection(main_window, fresh_singletons):
    """Wird die einzige verbliebene PDF verschoben, bleibt die Auswahl leer
    (kein Absturz, keine Phantom-Auswahl)."""
    scan = _make_scan_folder(fresh_singletons["tmp_path"], ["a.pdf"])
    ziel = fresh_singletons["tmp_path"] / "Ziel"
    ziel.mkdir()
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [w.pdf_path for w in main_window.pdf_widgets])

    only_path = main_window.pdf_widgets[0].pdf_path
    main_window.on_pdf_clicked(only_path)

    main_window.move_pdf_to_folder_and_learn(only_path, ziel)

    assert main_window.pdf_widgets == []
    assert main_window.selected_pdf is None


def test_move_non_selected_pdf_does_not_change_selection(main_window, fresh_singletons):
    """Wird eine andere als die ausgewaehlte PDF verschoben (z.B. per
    Kontextmenue), bleibt die aktuelle Auswahl unangetastet."""
    scan = _make_scan_folder(fresh_singletons["tmp_path"], ["a.pdf", "b.pdf", "c.pdf"])
    ziel = fresh_singletons["tmp_path"] / "Ziel"
    ziel.mkdir()
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [w.pdf_path for w in main_window.pdf_widgets])

    selected_path = main_window.pdf_widgets[0].pdf_path
    other_path = main_window.pdf_widgets[2].pdf_path

    main_window.on_pdf_clicked(selected_path)
    assert main_window.selected_pdf == selected_path

    main_window.move_pdf_to_folder_and_learn(other_path, ziel)

    assert len(main_window.pdf_widgets) == 2
    assert main_window.selected_pdf == selected_path


# --------------------------------------------------------------------- #
# Mehrfachauswahl: move_multiple_pdfs_to_folder
# --------------------------------------------------------------------- #


def test_move_multiple_selects_next_after_batch(main_window, fresh_singletons):
    """Bei Mehrfachauswahl reicht es, nach dem letzten entfernten Widget die
    naechste PDF auszuwaehlen (Issue #75)."""
    scan = _make_scan_folder(
        fresh_singletons["tmp_path"], ["a.pdf", "b.pdf", "c.pdf", "d.pdf"]
    )
    ziel = fresh_singletons["tmp_path"] / "Ziel"
    ziel.mkdir()
    main_window._navigate_to_folder(scan)
    assert len(main_window.pdf_widgets) == 4
    _prime_cache(main_window, [w.pdf_path for w in main_window.pdf_widgets])

    paths = [w.pdf_path for w in main_window.pdf_widgets]
    # a, b als Mehrfachauswahl markieren; b ist die "aktive" (zuletzt
    # angeklickte) PDF fuer Vorschlaege - siehe _update_selection_status.
    main_window.on_pdf_clicked(paths[0])
    main_window.on_pdf_ctrl_clicked(paths[1])
    assert main_window.selected_pdf == paths[1]
    assert set(main_window.selected_pdfs) == {paths[0], paths[1]}

    main_window.move_multiple_pdfs_to_folder([paths[0], paths[1]], ziel)

    assert len(main_window.pdf_widgets) == 2
    assert main_window.selected_pdfs == []
    # a und b werden entfernt; c und d ruecken nach - c steht jetzt an der
    # Position, an der zuletzt b (die aktive Auswahl) stand.
    assert main_window.selected_pdf == paths[2]


def test_move_multiple_without_prior_selection_clears_as_before(main_window, fresh_singletons):
    """War keine Einzelauswahl aktiv, bleibt das bisherige Verhalten (Auswahl
    leer, Vorschlaege geleert) erhalten."""
    scan = _make_scan_folder(fresh_singletons["tmp_path"], ["a.pdf", "b.pdf"])
    ziel = fresh_singletons["tmp_path"] / "Ziel"
    ziel.mkdir()
    main_window._navigate_to_folder(scan)
    paths = [w.pdf_path for w in main_window.pdf_widgets]

    assert main_window.selected_pdf is None
    main_window.move_multiple_pdfs_to_folder(list(paths), ziel)

    assert main_window.pdf_widgets == []
    assert main_window.selected_pdf is None
    assert main_window.selected_pdfs == []

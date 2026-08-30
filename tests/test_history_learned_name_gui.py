"""Ordnerstruktur-Namen (#42): In die Historie (= KI-Beispiele) geht der vom
Nutzer gewaehlte Name, nicht der Name mit Ordner-Praefix."""
from pathlib import Path

from tests.test_auto_next_after_move_gui import (  # noqa: F401 - Fixtures
    _make_scan_folder,
    _prime_cache,
    fresh_singletons,
    main_window,
)


def _history_names(main_window) -> list[str]:
    from src.utils.database import RenameHistory
    session = main_window.db.get_session()
    try:
        return [e.new_filename for e in session.query(RenameHistory).all()]
    finally:
        session.close()


def test_history_keeps_user_name_without_folder_prefix(main_window, fresh_singletons):
    tmp: Path = fresh_singletons["tmp_path"]
    scan = _make_scan_folder(tmp, ["scan_001.pdf"])
    ziel = tmp / "JK 069-03 Rohbau"
    ziel.mkdir()
    main_window.config.set("folder_naming_enabled", True, auto_save=False)
    main_window.config.set("owner_initials", "JK", auto_save=False)

    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [w.pdf_path for w in main_window.pdf_widgets])
    pdf = main_window.pdf_widgets[0].pdf_path
    main_window.on_pdf_clicked(pdf)
    main_window.selected_pdf_keywords = ["rechnung"]
    main_window.detail_panel.name_input.setText("2026-05-12_Rechnung_Elektro-Mueller")

    main_window._move_rename_and_learn(pdf, ziel)

    moved = list(ziel.glob("*.pdf"))
    assert len(moved) == 1
    assert moved[0].name.startswith("JK 069-03-")          # Praefix auf der Datei ...
    assert _history_names(main_window) == ["2026-05-12_Rechnung_Elektro-Mueller.pdf"]  # ... nicht im Beispiel


def test_history_without_folder_naming_stores_final_name(main_window, fresh_singletons):
    tmp: Path = fresh_singletons["tmp_path"]
    scan = _make_scan_folder(tmp, ["scan_002.pdf"])
    ziel = tmp / "Ziel"
    ziel.mkdir()
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [w.pdf_path for w in main_window.pdf_widgets])
    pdf = main_window.pdf_widgets[0].pdf_path
    main_window.on_pdf_clicked(pdf)
    main_window.selected_pdf_keywords = ["rechnung"]
    main_window.detail_panel.name_input.setText("2026-05-12_Rechnung_Elektro-Mueller")

    main_window._move_rename_and_learn(pdf, ziel)

    assert (ziel / "2026-05-12_Rechnung_Elektro-Mueller.pdf").exists()
    assert _history_names(main_window) == ["2026-05-12_Rechnung_Elektro-Mueller.pdf"]

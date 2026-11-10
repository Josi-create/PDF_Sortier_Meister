"""Nach "PDFs zusammenfügen": die Einzel-PDFs auf Wunsch in den Papierkorb (v0.26.2)."""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from PyQt6.QtWidgets import QInputDialog

from src.gui import original_wegraeumen as ow
from tests.test_bild_gui import cursor_aufraeumen, scan  # noqa: F401 - Fixtures
from tests.test_office_gui import _prime_cache_on_load, fresh_singletons, main_window  # noqa: F401 - Fixtures


def _pdf(pfad: Path, seiten: int) -> Path:
    doc = pymupdf.open()
    for i in range(seiten):
        doc.new_page().insert_text((50, 100), f"{pfad.stem} Seite {i + 1}")
    doc.save(str(pfad))
    doc.close()
    return pfad


def _seitenzahl(pfad: Path) -> int:
    with pymupdf.open(str(pfad)) as doc:
        return doc.page_count


@pytest.fixture
def zwei(main_window, scan, monkeypatch):  # noqa: F811
    a = _pdf(scan / "a.pdf", 2)
    b = _pdf(scan / "b.pdf", 3)
    main_window._navigate_to_folder(scan)
    main_window.selected_pdfs = [a, b]
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *x, **k: ("gesamt.pdf", True)))
    return a, b


def _fragen(monkeypatch, antwort):
    gestellt = []
    monkeypatch.setattr(ow, "_frage", lambda parent, text: gestellt.append(text) or antwort)
    return gestellt


def test_einzel_pdfs_gehen_in_den_papierkorb_und_strg_z_holt_sie_zurueck(main_window, scan, zwei, monkeypatch):  # noqa: F811
    a, b = zwei
    gestellt = _fragen(monkeypatch, (True, False))

    main_window.on_pdf_merge()

    assert _seitenzahl(scan / "gesamt.pdf") == 5
    assert len(gestellt) == 1 and "gesamt.pdf" in gestellt[0] and "a.pdf" in gestellt[0]
    assert not a.exists() and not b.exists()
    assert main_window._undo_stack[-1]["type"] == "wegraeumen"
    assert "Papierkorb" in main_window.statusbar.currentMessage()
    assert {w.pdf_path.name for w in main_window.pdf_widgets} == {"gesamt.pdf"}

    main_window.undo_last_action()
    assert a.exists() and b.exists() and (scan / "gesamt.pdf").exists()


def test_einzel_pdfs_bleiben_auf_wunsch(main_window, scan, zwei, monkeypatch):  # noqa: F811
    a, b = zwei
    _fragen(monkeypatch, (False, False))
    main_window.on_pdf_merge()
    assert a.exists() and b.exists() and (scan / "gesamt.pdf").exists()


def test_nicht_mehr_fragen_merkt_die_antwort(main_window, scan, zwei, monkeypatch):  # noqa: F811
    a, b = zwei
    _fragen(monkeypatch, (True, True))
    main_window.on_pdf_merge()
    assert main_window.config.get("original_wegraeumen")["zusammenfuegen"] is True
    assert not a.exists() and not b.exists()


def test_unvollstaendiges_ergebnis_raeumt_nichts_weg(main_window, scan, zwei, monkeypatch):  # noqa: F811
    a, b = zwei
    # Das "zusammengefügte" PDF hat zu wenige Seiten: Einzel-PDFs muessen bleiben
    monkeypatch.setattr(main_window.file_manager, "merge_pdfs",
                        lambda pdfs, ordner, name: _pdf(ordner / name, 2))
    monkeypatch.setattr(ow, "_frage", lambda *x: pytest.fail("Frage trotz unvollständigem Ergebnis"))
    main_window.on_pdf_merge()
    assert a.exists() and b.exists()


def test_fehler_beim_zusammenfuegen_raeumt_nichts_weg(main_window, scan, zwei, monkeypatch):  # noqa: F811
    from PyQt6.QtWidgets import QMessageBox

    a, b = zwei
    monkeypatch.setattr(main_window.file_manager, "merge_pdfs",
                        lambda *x, **k: (_ for _ in ()).throw(ValueError("kaputt")))
    monkeypatch.setattr(ow, "_frage", lambda *x: pytest.fail("Frage trotz Fehler"))
    gezeigt = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda p, t, text, *x, **k: gezeigt.append(text)))
    main_window.on_pdf_merge()
    assert a.exists() and b.exists() and "kaputt" in gezeigt[0]

"""Live-Test 08.11.2026: Mehrere markierte JPGs (oder docx) per Rechtsklick
"In PDF umwandeln" - vorher entstand nur ein PDF (das angeklickte Bild).

Jetzt wird jede markierte Datei ein eigenes PDF, die Frage nach den Originalen kommt
einmal fuer alle, ein Strg+Z holt alle Originale zurueck. Fixtures aus tests/test_bild_gui.py.
"""
from __future__ import annotations

import pymupdf

from tests.test_bild_gui import (  # noqa: F401 - Fixtures
    _bild,
    _fragen,
    _pdf,
    cursor_aufraeumen,
    fresh_singletons,
    main_window,
    scan,
)


def _menue_texte(widget) -> list[str]:
    return [a.text() for a in widget._build_context_menu().actions() if not a.isSeparator()]


def _kachel(mw, pfad):
    return next(w for w in mw.office_widgets if w.pdf_path == pfad)


def test_menue_bei_mehreren_bildern_einzeln_und_zusammen(main_window, scan):  # noqa: F811
    a, b, c = (_bild(scan / n) for n in ("a.jpg", "b.jpg", "c.jpg"))
    main_window._navigate_to_folder(scan)
    main_window.selected_pdfs = [a, b, c]
    texte = _menue_texte(_kachel(main_window, b))
    assert "Einzeln in PDFs umwandeln (3 Bilder)" in texte
    assert "Zu einem PDF zusammenfügen (3 Bilder)" in texte
    assert "In PDF umwandeln" not in texte  # waere mehrdeutig: nur das angeklickte?

    # Rechtsklick auf ein nicht markiertes Bild: nur dieses
    main_window.selected_pdfs = [a, b]
    assert "In PDF umwandeln" in _menue_texte(_kachel(main_window, c))


def test_mehrere_bilder_werden_je_ein_pdf(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    bilder = [_bild(scan / n) for n in ("a.jpg", "b.jpg", "c.png")]
    main_window._navigate_to_folder(scan)
    gestellt = _fragen(monkeypatch, (True, False))
    main_window.selected_pdfs = list(reversed(bilder))  # Auswahlreihenfolge egal

    aktion = next(a for a in _kachel(main_window, bilder[1])._build_context_menu().actions()
                  if a.text().startswith("Einzeln in PDFs umwandeln"))
    aktion.trigger()
    qtbot.waitUntil(lambda: main_window._bild_worker is None, timeout=15000)

    for bild in bilder:
        pdf = bild.with_suffix(".pdf")
        assert pdf.exists() and not bild.exists()
        with pymupdf.open(pdf) as doc:
            assert doc.page_count == 1
    assert len(gestellt) == 1 and "3 PDFs wurden erstellt" in gestellt[0]  # eine Frage fuer alle
    assert main_window.selected_pdf == scan / "a.pdf"  # das erste in Ansichtsreihenfolge
    assert len([e for e in main_window._undo_stack if e["type"] == "wegraeumen"]) == 1

    main_window.undo_last_action()  # ein Strg+Z holt alle Originale zurueck
    assert all(b.exists() for b in bilder)


def test_ein_fehler_haelt_die_anderen_nicht_auf(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    from PyQt6.QtWidgets import QMessageBox

    gut, kaputt = _bild(scan / "a.jpg"), scan / "b.jpg"
    kaputt.write_bytes(b"kein Bild")
    main_window._navigate_to_folder(scan)
    gestellt = _fragen(monkeypatch, (True, False))
    warnungen = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnungen.append(a[2]))

    main_window.on_mehrere_umwandeln([gut, kaputt], False)
    qtbot.waitUntil(lambda: main_window._bild_worker is None, timeout=15000)

    assert (scan / "a.pdf").exists() and not gut.exists()
    assert kaputt.exists() and not (scan / "b.pdf").exists()  # das kaputte bleibt liegen
    assert len(gestellt) == 1 and "'a.pdf'" in gestellt[0]  # nur das gelungene zur Wahl
    assert len(warnungen) == 1 and "b.jpg" in warnungen[0]


def test_mehrere_docx_je_ein_pdf_und_eine_frage(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    from src.core.office_convert import UmwandlungsErgebnis
    from src.gui import office_convert_worker as worker_mod

    dateien = []
    for name in ("Brief.docx", "Liste.xlsx"):
        (scan / name).write_bytes(b"PK")
        dateien.append(scan / name)
    main_window._navigate_to_folder(scan)
    aufrufe = []

    def umwandeln(pfad, pdfa=False):
        aufrufe.append((pfad.name, pdfa))
        return UmwandlungsErgebnis(pdf=_pdf(pfad.with_suffix(".pdf")), werkzeug="Word", pdfa=pdfa)

    monkeypatch.setattr(worker_mod, "umwandeln", umwandeln)
    gestellt = _fragen(monkeypatch, (True, False))
    main_window.selected_pdfs = list(dateien)
    texte = _menue_texte(_kachel(main_window, dateien[0]))
    assert "In PDF umwandeln (2 Dateien)" in texte and "In PDF/A umwandeln (2 Dateien)" in texte

    aktion = next(a for a in _kachel(main_window, dateien[0])._build_context_menu().actions()
                  if a.text() == "In PDF/A umwandeln (2 Dateien)")
    aktion.trigger()
    qtbot.waitUntil(lambda: main_window._office_worker is None, timeout=5000)

    assert sorted(aufrufe) == [("Brief.docx", True), ("Liste.xlsx", True)]
    assert (scan / "Brief.pdf").exists() and (scan / "Liste.pdf").exists()
    assert len(gestellt) == 1 and "2 PDFs wurden erstellt" in gestellt[0]
    assert not any(d.exists() for d in dateien)
    main_window.undo_last_action()
    assert all(d.exists() for d in dateien)

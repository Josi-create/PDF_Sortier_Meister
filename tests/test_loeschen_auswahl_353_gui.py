"""Issue #353: "Löschen" im Rechtsklick-Menue einer markierten Kachel erfasst die ganze Auswahl.

Vorher fragte das Menue bei zwei markierten Kacheln nur nach der angeklickten ("diese PDF"),
erst Entf loeschte beide. Fixtures wie in tests/test_entf_papierkorb_272_gui.py.
"""
from __future__ import annotations

from tests.test_alle_markieren_gui import _ordner
from tests.test_entf_papierkorb_272_gui import _geladen, _namen, fragen  # noqa: F401
from tests.test_office_gui import (  # noqa: F401 - Fixtures
    _prime_cache_on_load,
    fresh_singletons,
    main_window,
)


def _loeschen_aktion(kachel):
    menue = kachel._build_context_menu()
    return next(a for a in menue.actions() if a.text().startswith("Löschen"))


def test_rechtsklick_loeschen_bei_zwei_markierten_loescht_beide(main_window, fresh_singletons, fragen, monkeypatch):  # noqa: F811
    scan = _ordner(fresh_singletons)
    _geladen(main_window, monkeypatch, scan)
    weg = [scan / "dok_0.pdf", scan / "dok_2.pdf"]
    main_window.on_pdf_clicked(weg[0])
    main_window.on_pdf_ctrl_clicked(weg[1])

    aktion = _loeschen_aktion(main_window._pdf_widget_for(weg[1]))
    assert aktion.text() == "Löschen (2 Dateien)"
    aktion.trigger()

    assert len(fragen) == 1 and "2 Dateien in den Papierkorb" in fragen[0]
    assert not any(p.exists() for p in weg)
    assert _namen(main_window) == ["Brief.docx", "dok_1.pdf", "dok_3.pdf"]
    assert len(main_window._undo_stack) == 1 and main_window._undo_stack[-1]["type"] == "wegraeumen"


def test_rechtsklick_loeschen_auf_office_kachel_in_der_auswahl(main_window, fresh_singletons, fragen, monkeypatch):  # noqa: F811
    scan = _ordner(fresh_singletons)
    _geladen(main_window, monkeypatch, scan)
    weg = [scan / "dok_1.pdf", scan / "Brief.docx"]
    main_window.on_pdf_clicked(weg[0])
    main_window.on_pdf_ctrl_clicked(weg[1])

    aktion = _loeschen_aktion(main_window._pdf_widget_for(weg[1]))
    assert aktion.text() == "Löschen (2 Dateien)"
    aktion.trigger()

    assert len(fragen) == 1 and "2 Dateien in den Papierkorb" in fragen[0]
    assert not any(p.exists() for p in weg)


def test_rechtsklick_auf_kachel_ausserhalb_der_auswahl_loescht_nur_diese(main_window, fresh_singletons, fragen, monkeypatch):  # noqa: F811
    scan = _ordner(fresh_singletons)
    _geladen(main_window, monkeypatch, scan)
    main_window.on_pdf_clicked(scan / "dok_0.pdf")
    main_window.on_pdf_ctrl_clicked(scan / "dok_1.pdf")
    andere = scan / "dok_3.pdf"

    aktion = _loeschen_aktion(main_window._pdf_widget_for(andere))
    assert aktion.text() == "Löschen"
    aktion.trigger()

    assert len(fragen) == 1 and "diese PDF in den Papierkorb" in fragen[0] and "dok_3.pdf" in fragen[0]
    assert not andere.exists()
    assert (scan / "dok_0.pdf").exists() and (scan / "dok_1.pdf").exists()


def test_klick_und_strg_klick_aus_dem_textfeld_dann_ein_entf_loescht_beide(qtbot, main_window, fresh_singletons, fragen, monkeypatch):  # noqa: F811
    """Nachstellversuch zur Taste: der Fokus stand vorher in einem Textfeld der Details."""
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtWidgets import QApplication, QLineEdit

    from tests.test_alle_markieren_gui import _sichtbar

    scan = _ordner(fresh_singletons)
    _sichtbar(qtbot, main_window, monkeypatch, scan)
    a, b = scan / "dok_0.pdf", scan / "dok_2.pdf"

    def kachel(p):
        return main_window._pdf_widget_for(p)

    qtbot.waitUntil(lambda: kachel(b) is not None and kachel(b).isVisible() and kachel(b).width() > 20, timeout=3000)
    feld = next(f for f in main_window.findChildren(QLineEdit) if f.isVisible() and f.isEnabled())
    feld.setFocus()
    qtbot.waitUntil(lambda: QApplication.focusWidget() is feld, timeout=2000)

    qtbot.mouseClick(kachel(a), Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    qtbot.mouseClick(kachel(b), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, pos=QPoint(10, 10))
    assert sorted(main_window.selected_pdfs) == [a, b]
    assert QApplication.focusWidget() is main_window.pdf_scroll_area

    qtbot.keyClick(QApplication.focusWidget(), Qt.Key.Key_Delete)

    assert len(fragen) == 1 and "2 Dateien in den Papierkorb" in fragen[0]
    assert not a.exists() and not b.exists()


def test_rechtsklick_loeschen_einzeln_markiert_bleibt_wie_bisher(main_window, fresh_singletons, fragen, monkeypatch):  # noqa: F811
    scan = _ordner(fresh_singletons)
    _geladen(main_window, monkeypatch, scan)
    ziel = scan / "dok_2.pdf"
    main_window.on_pdf_clicked(ziel)

    aktion = _loeschen_aktion(main_window._pdf_widget_for(ziel))
    assert aktion.text() == "Löschen"
    aktion.trigger()

    assert len(fragen) == 1 and "diese PDF in den Papierkorb" in fragen[0]
    assert not ziel.exists() and main_window._undo_stack[-1]["type"] == "delete"

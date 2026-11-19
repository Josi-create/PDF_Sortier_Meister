"""Live-Test 08.11.2026: Strg+A nach einem Klick in die Kachelansicht "PDFs" markiert alle Kacheln.

In Textfeldern bleibt Strg+A "Text markieren". Fixtures wie in tests/test_office_gui.py
(nie die echte Konfiguration).
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QApplication, QLineEdit, QWidget

from tests.test_office_gui import (  # noqa: F401 - Fixtures
    _prime_cache_on_load,
    fresh_singletons,
    main_window,
)


def _ordner(fresh_singletons, anzahl=4):
    scan = fresh_singletons["tmp_path"] / "Viele"
    scan.mkdir()
    for i in range(anzahl):
        (scan / f"dok_{i}.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (scan / "Brief.docx").write_bytes(b"PK")
    return scan


def _sichtbar(qtbot, mw, monkeypatch, scan):
    mw.resize(1100, 700)
    QWidget.setVisible(mw, True)  # show() ist in der Fixture stillgelegt
    qtbot.waitExposed(mw)
    mw.activateWindow()
    _prime_cache_on_load(mw, monkeypatch)
    monkeypatch.setattr(mw, "update_suggestions_for_pdf", lambda p: None)
    mw._navigate_to_folder(scan)
    qtbot.waitUntil(lambda: len(mw.pdf_widgets) == 5, timeout=3000)


def test_klick_in_die_kacheln_dann_strg_a_markiert_alle(qtbot, main_window, fresh_singletons, monkeypatch):
    scan = _ordner(fresh_singletons)
    _sichtbar(qtbot, main_window, monkeypatch, scan)
    def kachel():  # jedes Mal frisch: ein Neuladen ersetzt die Kacheln
        return main_window._pdf_widget_for(scan / "dok_2.pdf")

    qtbot.waitUntil(lambda: kachel() is not None and kachel().isVisible() and kachel().width() > 20,
                    timeout=3000)  # Layout steht
    qtbot.mouseClick(kachel(), Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert main_window.selected_pdf == scan / "dok_2.pdf"
    qtbot.waitUntil(lambda: main_window.pdf_scroll_area.isAncestorOf(QApplication.focusWidget())
                    or QApplication.focusWidget() is main_window.pdf_scroll_area, timeout=2000)

    qtbot.keyClick(QApplication.focusWidget(), Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)

    alle = {w.pdf_path for w in main_window.pdf_widgets}
    assert set(main_window.selected_pdfs) == alle and len(alle) == 5  # auch die docx-Kachel
    assert all(w.selected for w in main_window.pdf_widgets)
    assert main_window.selected_pdf == scan / "dok_2.pdf"  # die aktive bleibt die aktive


def test_strg_a_im_textfeld_markiert_text_nicht_kacheln(qtbot, main_window, fresh_singletons, monkeypatch):
    scan = _ordner(fresh_singletons)
    _sichtbar(qtbot, main_window, monkeypatch, scan)
    felder = [f for f in main_window.findChildren(QLineEdit)
              if f.isVisible() and f.isEnabled() and not f.isReadOnly()]
    feld = felder[0]
    feld.setText("Hallo Welt")
    feld.setFocus()
    qtbot.waitUntil(lambda: QApplication.focusWidget() is feld, timeout=2000)

    qtbot.keyClick(feld, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)

    assert feld.selectedText() == "Hallo Welt"
    assert main_window.selected_pdfs == [] and not any(w.selected for w in main_window.pdf_widgets)


def test_menue_eintrag_und_einzelne_kachel(qtbot, main_window, fresh_singletons, monkeypatch):
    scan = fresh_singletons["tmp_path"] / "Einer"
    scan.mkdir()
    (scan / "nur.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    _prime_cache_on_load(main_window, monkeypatch)
    monkeypatch.setattr(main_window, "update_suggestions_for_pdf", lambda p: None)
    main_window._navigate_to_folder(scan)
    aktion = main_window.select_all_action
    assert aktion.text() == "Alle markieren" and aktion.shortcut().toString() == "Ctrl+A"

    aktion.trigger()
    assert main_window.selected_pdf == scan / "nur.pdf" and main_window.selected_pdfs == []
    aktion.trigger()  # nochmal: bleibt markiert (kein Umschalten wie beim Klick)
    assert main_window.selected_pdf == scan / "nur.pdf"


def test_strg_a_wirkt_auch_wenn_der_fokus_woanders_liegt(qtbot, main_window, fresh_singletons, monkeypatch):
    """Live-Test 09.11.2026: vorher zuletzt in den Zielordner-Baum geklickt -> Strg+A tat nichts.

    Ohne aktives Fenster loest Qt keine Tastenkuerzel aus; deshalb wird hier geprueft, dass der Baum
    Strg+A nicht mehr fuer sich beansprucht (ShortcutOverride) und das Kuerzel dann alle Kacheln markiert.
    """
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QKeyEvent

    scan = _ordner(fresh_singletons)
    _sichtbar(qtbot, main_window, monkeypatch, scan)
    baum = main_window.folder_tree.tree
    baum.setFocus()
    qtbot.waitUntil(lambda: QApplication.focusWidget() is baum, timeout=2000)

    anfrage = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier, "a")
    QApplication.sendEvent(baum, anfrage)
    assert not anfrage.isAccepted()  # das Fenster-Kuerzel darf greifen

    main_window.select_all_action.trigger()
    assert len(main_window.selected_pdfs) == 5 and all(w.selected for w in main_window.pdf_widgets)

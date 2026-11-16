"""Issue #272: Die Taste Entf legt die markierte(n) Kachel(n) in den Papierkorb.

Gleiche Rueckfrage und gleiches Rueckgaengig wie "Löschen" im Kontextmenue; das Kuerzel
gilt nur, solange der Fokus in der Kachelansicht liegt. Fixtures wie in
tests/test_alle_markieren_gui.py (nie die echte Konfiguration, nie der echte Papierkorb).
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QLineEdit

from tests.test_alle_markieren_gui import _ordner, _sichtbar
from tests.test_file_manager import _fake_papierkorb
from tests.test_office_gui import (  # noqa: F401 - Fixtures
    _prime_cache_on_load,
    fresh_singletons,
    main_window,
)


@pytest.fixture
def fragen(main_window, monkeypatch):  # noqa: F811
    """Rueckfragen mitschreiben; ``fragen.antwort`` bestimmt, was der Nutzer klickt."""
    from src.core import file_manager as fm
    from src.gui import main_window as mw_mod
    from src.gui import original_wegraeumen

    class Fragen(list):
        antwort = mw_mod.QMessageBox.StandardButton.Yes

    log = Fragen()
    monkeypatch.setattr(mw_mod.QMessageBox, "question", lambda *a, **k: log.append(a[2]) or log.antwort)
    monkeypatch.setattr(mw_mod.QMessageBox, "critical", lambda *a, **k: log.append(a[2]))
    for modul in (fm, mw_mod, original_wegraeumen):
        monkeypatch.setattr(modul, "index_melden", lambda *a, **k: None)
    return log


def _geladen(main_window, monkeypatch, scan):  # noqa: F811
    _prime_cache_on_load(main_window, monkeypatch)
    monkeypatch.setattr(main_window, "update_suggestions_for_pdf", lambda p: None)
    main_window._navigate_to_folder(scan)


def _namen(main_window):  # noqa: F811
    return sorted(w.pdf_path.name for w in main_window.pdf_widgets)


def test_menue_eintrag_mit_entf_nur_in_der_kachelansicht(main_window):  # noqa: F811
    aktion = main_window.papierkorb_action
    assert aktion.text() == "In den Papierkorb"
    assert "Del" in [k.toString() for k in aktion.shortcuts()]
    assert aktion.shortcutContext() == Qt.ShortcutContext.WidgetWithChildrenShortcut
    assert aktion in main_window.pdf_scroll_area.actions()


def test_klick_auf_kachel_dann_entf_loescht_mit_rueckfrage(qtbot, main_window, fresh_singletons, fragen, monkeypatch):  # noqa: F811
    scan = _ordner(fresh_singletons)
    _sichtbar(qtbot, main_window, monkeypatch, scan)
    ziel = scan / "dok_2.pdf"

    def kachel():
        return main_window._pdf_widget_for(ziel)

    qtbot.waitUntil(lambda: kachel() is not None and kachel().isVisible() and kachel().width() > 20, timeout=3000)
    qtbot.mouseClick(kachel(), Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    qtbot.waitUntil(lambda: main_window.pdf_scroll_area.isAncestorOf(QApplication.focusWidget())
                    or QApplication.focusWidget() is main_window.pdf_scroll_area, timeout=2000)

    qtbot.keyClick(QApplication.focusWidget(), Qt.Key.Key_Delete)

    assert not ziel.exists() and "dok_2.pdf" not in _namen(main_window)
    assert len(fragen) == 1 and "diese PDF in den Papierkorb" in fragen[0] and "dok_2.pdf" in fragen[0]
    assert main_window._undo_stack[-1]["type"] == "delete"

    main_window.undo_last_action()  # Strg+Z
    assert ziel.exists() and "dok_2.pdf" in _namen(main_window)


def test_mehrere_markiert_eine_rueckfrage_ein_rueckgaengig(main_window, fresh_singletons, fragen, monkeypatch):  # noqa: F811
    scan = _ordner(fresh_singletons)
    _geladen(main_window, monkeypatch, scan)
    weg = [scan / "dok_0.pdf", scan / "dok_3.pdf", scan / "Brief.docx"]
    main_window.on_pdf_clicked(weg[0])
    main_window.on_pdf_ctrl_clicked(weg[1])
    main_window.on_pdf_ctrl_clicked(weg[2])
    assert sorted(main_window.selected_pdfs) == sorted(weg)

    main_window.papierkorb_action.trigger()

    assert len(fragen) == 1 and "3 Dateien in den Papierkorb" in fragen[0]
    assert all(p.name in fragen[0] for p in weg)
    assert not any(p.exists() for p in weg)
    assert _namen(main_window) == ["dok_1.pdf", "dok_2.pdf"]
    assert main_window.selected_pdf is None and main_window.selected_pdfs == []
    assert len(main_window._undo_stack) == 1
    assert "Löschen: 3 Dateien" in main_window.undo_action.text()

    main_window.undo_last_action()  # ein Strg+Z holt alle drei zurueck
    assert all(p.exists() for p in weg) and len(_namen(main_window)) == 5
    assert main_window._undo_stack == []


def test_nein_in_der_rueckfrage_laesst_alles_liegen(main_window, fresh_singletons, fragen, monkeypatch):  # noqa: F811
    from src.gui import main_window as mw_mod
    scan = _ordner(fresh_singletons)
    _geladen(main_window, monkeypatch, scan)
    fragen.antwort = mw_mod.QMessageBox.StandardButton.No
    main_window.alle_markieren()

    main_window.auswahl_loeschen()

    assert len(fragen) == 1 and len(_namen(main_window)) == 5
    assert len(list(scan.iterdir())) == 5 and main_window._undo_stack == []
    assert len(main_window.selected_pdfs) == 5  # die Markierung bleibt


def test_ohne_markierung_keine_rueckfrage(main_window, fresh_singletons, fragen, monkeypatch):  # noqa: F811
    scan = _ordner(fresh_singletons)
    _geladen(main_window, monkeypatch, scan)

    main_window.auswahl_loeschen()

    assert fragen == [] and len(list(scan.iterdir())) == 5


def test_einzelne_office_datei_geht_den_weg_des_kontextmenues(main_window, fresh_singletons, fragen, monkeypatch):  # noqa: F811
    scan = _ordner(fresh_singletons)
    _geladen(main_window, monkeypatch, scan)
    brief = scan / "Brief.docx"
    main_window.on_pdf_clicked(brief)

    main_window.auswahl_loeschen()

    assert not brief.exists() and "diese Datei in den Papierkorb" in fragen[0]
    assert main_window._undo_stack[-1]["type"] == "delete"


def test_entf_im_textfeld_loescht_zeichen_nicht_die_datei(qtbot, main_window, fresh_singletons, fragen, monkeypatch):  # noqa: F811
    scan = _ordner(fresh_singletons)
    _sichtbar(qtbot, main_window, monkeypatch, scan)
    main_window.on_pdf_clicked(scan / "dok_1.pdf")
    feld = next(f for f in main_window.findChildren(QLineEdit)
                if f.isVisible() and f.isEnabled() and not f.isReadOnly())
    feld.setText("Hallo")
    feld.setFocus()
    qtbot.waitUntil(lambda: QApplication.focusWidget() is feld, timeout=2000)
    feld.setCursorPosition(0)

    qtbot.keyClick(feld, Qt.Key.Key_Delete)

    assert feld.text() == "allo"
    assert fragen == [] and (scan / "dok_1.pdf").exists()


def test_entf_im_ordnerbaum_loescht_keine_kachel(qtbot, main_window, fresh_singletons, fragen, monkeypatch):  # noqa: F811
    scan = _ordner(fresh_singletons)
    _sichtbar(qtbot, main_window, monkeypatch, scan)
    main_window.on_pdf_clicked(scan / "dok_1.pdf")
    baum = main_window.folder_tree.tree
    baum.setFocus()
    qtbot.waitUntil(lambda: QApplication.focusWidget() is baum, timeout=2000)

    qtbot.keyClick(baum, Qt.Key.Key_Delete)
    QApplication.sendEvent(baum, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier))

    assert fragen == [] and (scan / "dok_1.pdf").exists()


def test_ohne_papierkorb_zweite_rueckfrage_dann_endgueltig_ohne_undo(main_window, fresh_singletons, fragen, monkeypatch):  # noqa: F811
    scan = _ordner(fresh_singletons)
    _geladen(main_window, monkeypatch, scan)
    _fake_papierkorb(monkeypatch, scan.parent / "trash", ok=False)
    main_window.on_pdf_clicked(scan / "dok_0.pdf")
    main_window.on_pdf_ctrl_clicked(scan / "dok_1.pdf")

    main_window.auswahl_loeschen()

    assert len(fragen) == 2 and "2 Datei(en) endgültig löschen?" in fragen[1]
    assert not (scan / "dok_0.pdf").exists() and not (scan / "dok_1.pdf").exists()
    assert main_window._undo_stack == [] and len(_namen(main_window)) == 3


def test_ohne_papierkorb_und_nein_bleiben_die_dateien(main_window, fresh_singletons, fragen, monkeypatch):  # noqa: F811
    from src.gui import main_window as mw_mod
    scan = _ordner(fresh_singletons)
    _geladen(main_window, monkeypatch, scan)
    _fake_papierkorb(monkeypatch, scan.parent / "trash", ok=False)
    ja, nein = mw_mod.QMessageBox.StandardButton.Yes, mw_mod.QMessageBox.StandardButton.No
    antworten = [ja, nein]
    monkeypatch.setattr(mw_mod.QMessageBox, "question", lambda *a, **k: fragen.append(a[2]) or antworten.pop(0))
    main_window.on_pdf_clicked(scan / "dok_0.pdf")
    main_window.on_pdf_ctrl_clicked(scan / "dok_1.pdf")

    main_window.auswahl_loeschen()

    assert len(fragen) == 2 and (scan / "dok_0.pdf").exists() and (scan / "dok_1.pdf").exists()
    assert len(_namen(main_window)) == 5 and main_window._undo_stack == []

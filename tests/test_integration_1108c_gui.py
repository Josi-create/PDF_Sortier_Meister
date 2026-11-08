"""Zusammenspiel #196 (Ordner verschieben) mit den Live-Test-Korrekturen vom 08.11.2026:
Ordner-Vorschlaege nutzen die Pfadanzeige auf zwei Zeilen, Strg+A hebt eine
Ordnermarkierung auf. Szene und Helfer aus tests/test_ordner_verschieben_196_gui.py.
"""
from __future__ import annotations

from tests.test_ordner_verschieben_196_gui import (  # noqa: F401 - Fixtures
    _markieren,
    _vorschlaege_da,
    dialoge,
    fresh_singletons,
    main_window,
    szene,
)


def test_ordner_vorschlaege_zeigen_vollen_pfad_ziel_fett(qtbot, szene):
    win = szene.win
    _markieren(qtbot, szene)
    _vorschlaege_da(qtbot, win)
    zeile = next(w for w in win.suggestion_widgets if w.folder_path == szene.ziel)
    assert zeile._pfad_voll == str(szene.ablage)  # absoluter Elternpfad, nicht relativ
    assert zeile._name_voll == "Steuer 2025" and zeile._praefix == ""
    assert "<b>" in zeile.name_label.text() and "Steuer 2025</b>" in zeile.name_label.text()


def test_neuer_jahresordner_hat_das_praefix_statt_neu_im_namen(qtbot, szene):
    win = szene.win
    (szene.ablage / "Steuer 2025").rmdir()
    win.load_folders()
    _markieren(qtbot, szene)
    _vorschlaege_da(qtbot, win)
    neu = next(w for w in win.suggestion_widgets if w.neu)
    assert neu._praefix == "➕ neu: " and neu._name_voll == "Steuer 2025"


def test_strg_a_hebt_die_ordnermarkierung_auf(qtbot, szene):
    win = szene.win
    kachel = _markieren(qtbot, szene)
    assert win._markierter_ordner == szene.vers

    win.alle_markieren()

    assert win._markierter_ordner is None and not kachel.markiert
    assert win.selected_pdf == szene.scan / "lose.pdf"  # nur eine Kachel im Scan-Ordner

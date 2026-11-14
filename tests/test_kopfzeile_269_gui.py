"""Kopfzeile ueber den Kacheln (Issue #269).

Der Ordnername steht ausgeschrieben da; "Ansicht:" und "Sortieren:" entfallen, die
beiden Auswahlfelder stehen ganz rechts, darueber sehr klein die Anzahl. Die Zeile
ist nicht hoeher als vorher.

Offscreen misst eine andere Schrift als Windows: Die Tests vergleichen deshalb
Breiten mit den Massen des Labels selbst statt mit festen Pixelwerten.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QWidget

from src.gui.ordner_titel import OrdnerTitel
from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401


def _zeige(win, scan, breite: int = 1500):
    win.resize(breite, 720)
    QWidget.show(win)  # MainWindow.show() ist in der Fixture ersetzt
    win._navigate_to_folder(scan)
    win.centralWidget().layout().activate()
    return win


def _ordner(tmp_path, name: str):
    scan = tmp_path / name
    (scan / "Belege").mkdir(parents=True)
    return scan


# --------------------------------------------------------------------- #
# OrdnerTitel allein
# --------------------------------------------------------------------- #


def _titel(qtbot, breite_fuer: str) -> OrdnerTitel:
    titel = OrdnerTitel()
    qtbot.addWidget(titel)
    titel.setze_ordner("PDFs in: Steuer 2026", "Steuer 2026")
    titel.resize(titel.fontMetrics().horizontalAdvance(breite_fuer) + 2, 30)
    return titel


def test_titel_zeigt_ganzen_text_wenn_platz_ist(qtbot):
    titel = _titel(qtbot, "PDFs in: Steuer 2026")
    assert titel.angezeigter_text() == "PDFs in: Steuer 2026"


def test_titel_zeigt_bei_platzmangel_nur_den_ordnernamen(qtbot):
    titel = _titel(qtbot, "Steuer 2026")
    assert titel.angezeigter_text() == "Steuer 2026"
    assert titel.text() == "PDFs in: Steuer 2026"


def test_titel_zeigt_von_zu_langem_namen_den_rechten_teil(qtbot):
    titel = _titel(qtbot, "uer 2026")
    gemalt = titel.angezeigter_text()
    assert gemalt.startswith("…")
    assert gemalt.endswith("2026")
    assert "PDFs" not in gemalt


def test_titel_mindestbreite_waechst_nicht_mit_dem_namen(qtbot):
    titel = OrdnerTitel()
    qtbot.addWidget(titel)
    lang = "Sehr langer Ordnername " * 6
    titel.setze_ordner("PDFs in: " + lang, lang)
    assert titel.minimumSizeHint().width() <= OrdnerTitel.VORRANG_BREITE


def test_titel_set_text_vergisst_alten_ordnernamen(qtbot):
    titel = _titel(qtbot, "uer 2026")
    titel.setText("Neue PDFs im Scan-Ordner")
    assert "2026" not in titel.angezeigter_text()


# --------------------------------------------------------------------- #
# Kopfzeile im Hauptfenster
# --------------------------------------------------------------------- #


def test_beschriftungen_entfallen(main_window, tmp_path):
    win = _zeige(main_window, _ordner(tmp_path, "Steuer 2026"))
    kopf = win.pdf_header.parentWidget()
    texte = {label.text() for label in kopf.findChildren(QLabel)}
    assert "Ansicht:" not in texte
    assert "Sortieren:" not in texte
    # fuer Bildschirmleser bleiben die Felder benannt
    assert win.tile_view_combo.accessibleName()
    assert win.sort_combo.accessibleName()


def test_ordnername_ausgeschrieben(main_window, tmp_path):
    win = _zeige(main_window, _ordner(tmp_path, "Steuer 2026"))
    assert win.pdf_header.text() == "PDFs in: Steuer 2026"
    assert win.pdf_header.angezeigter_text().endswith("Steuer 2026")
    assert "…" not in win.pdf_header.angezeigter_text()


def test_ordnername_mit_umlauten(main_window, tmp_path):
    win = _zeige(main_window, _ordner(tmp_path, "Bürgerbüro Übersicht"))
    assert win.pdf_header.text() == "PDFs in: Bürgerbüro Übersicht"
    assert win.pdf_header.toolTip().endswith("Bürgerbüro Übersicht")


def test_auswahlfelder_ganz_rechts_anzahl_darueber(main_window, tmp_path):
    win = _zeige(main_window, _ordner(tmp_path, "Steuer 2026"))
    titel, zahl = win.pdf_header.geometry(), win.pdf_folder_count_label.geometry()
    ansicht, sortieren = win.tile_view_combo.geometry(), win.sort_combo.geometry()
    assert win.pdf_folder_count_label.text() == "0 Dateien · 1 Ordner"
    # Reihenfolge von links: Titel, Ansicht, Sortieren - Sortieren schliesst rechts ab
    assert titel.right() < ansicht.left() < sortieren.left()
    assert sortieren.right() == zahl.right()
    assert sortieren.right() == max(
        w.geometry().right() for w in (win.pdf_header, win.pdf_folder_count_label,
                                       win.tile_view_combo, win.sort_combo)
    )
    # die Anzahl steht ueber den Auswahlfeldern und ist kleiner geschrieben
    assert zahl.bottom() < ansicht.top()
    assert zahl.bottom() < sortieren.top()
    assert win.pdf_folder_count_label.font().pixelSize() < win.sort_combo.fontInfo().pixelSize()


def test_zeile_nicht_hoeher_als_die_ueberschrift(main_window, tmp_path):
    """Vorher bestimmte die Ueberschrift die Hoehe; der rechte Block darf nicht hoeher sein."""
    win = _zeige(main_window, _ordner(tmp_path, "Steuer 2026"))
    oben = win.pdf_folder_count_label.geometry().top()
    unten = win.sort_combo.geometry().bottom()
    assert unten - oben + 1 <= max(win.pdf_header.sizeHint().height(),
                                   win.navigate_back_btn.height())
    assert win.pdf_header.geometry().top() <= oben
    assert unten <= win.pdf_header.geometry().bottom()


def test_langer_ordnername_zeigt_rechten_teil(main_window, tmp_path):
    name = "Sehr langer Ordnername fuer Belege und Rechnungen und noch viel mehr 2026"
    win = _zeige(main_window, _ordner(tmp_path, name), breite=1024)
    gemalt = win.pdf_header.angezeigter_text()
    # wie viel vom Namen passt, haengt von der Schrift ab (offscreen breiter)
    assert gemalt.startswith("…") and len(gemalt) > 1
    assert name.endswith(gemalt[1:])
    assert win.pdf_header.toolTip().endswith(name)
    # die Auswahlfelder bleiben in der Spalte
    kopf = win.pdf_header.parentWidget()
    assert win.sort_combo.geometry().right() <= kopf.width()

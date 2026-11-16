"""Lupen-Knopf an der Pfadzeile: einfarbig in der Textfarbe des Farbschemas (Issue #295)."""
from __future__ import annotations

from PyQt6.QtGui import QColor

from src.gui import farben
from src.gui.lupe import lupen_pixmap
from tests.test_farben_238_gui import schema_zurueck  # noqa: F401 - Fixture
from tests.test_main_window_gui import fresh_singletons, main_window, _scan_tree  # noqa: F401 - Fixtures


def _deckende_farben(pixmap) -> set[tuple[int, int, int]]:
    """RGB-Werte aller voll deckenden Punkte (Kantenglaettung bleibt aussen vor)."""
    bild = pixmap.toImage()
    werte = set()
    for x in range(bild.width()):
        for y in range(bild.height()):
            c = bild.pixelColor(x, y)
            if c.alpha() == 255:
                werte.add((c.red(), c.green(), c.blue()))
    return werte


def _knopf_farben(fenster) -> set[tuple[int, int, int]]:
    knopf = fenster.breadcrumb_suche_btn
    return _deckende_farben(knopf.icon().pixmap(knopf.iconSize()))


def test_lupe_hat_genau_eine_farbe_und_durchsichtigen_grund(qapp):
    pix = lupen_pixmap(QColor("#123456"), 16)
    assert _deckende_farben(pix) == {(0x12, 0x34, 0x56)}
    bild = pix.toImage()
    assert bild.pixelColor(15, 0).alpha() == 0  # Ecke oben rechts bleibt frei
    assert bild.pixelColor(0, 15).alpha() == 0  # Ecke unten links bleibt frei


def test_knopf_zeigt_lupe_statt_emoji_und_folgt_dem_schema(main_window, qapp, schema_zurueck):  # noqa: F811
    knopf = main_window.breadcrumb_suche_btn
    assert knopf.text() == ""
    assert not knopf.icon().isNull()
    hell = farben.qfarbe("schwarz")
    assert _knopf_farben(main_window) == {(hell.red(), hell.green(), hell.blue())}
    assert hell.lightness() < 80  # dunkle Lupe auf hellem Grund

    farben.anwenden(farben.DUNKEL, qapp)

    dunkel = farben.qfarbe("schwarz")
    assert dunkel.lightness() > 180  # helle Lupe auf dunklem Grund
    assert _knopf_farben(main_window) == {(dunkel.red(), dunkel.green(), dunkel.blue())}

    farben.anwenden(farben.HELL, qapp)

    assert _knopf_farben(main_window) == {(hell.red(), hell.green(), hell.blue())}

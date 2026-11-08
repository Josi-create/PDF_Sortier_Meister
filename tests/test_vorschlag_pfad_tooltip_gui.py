"""Live-Test 08.11.2026: Vorschlagszeilen zeigen den vollen Pfad (von links gekuerzt),
Tooltips sind nicht mehr schwarz.

Schwarz waren sie, weil ein Stylesheet ohne Selektor ("background: transparent") auch
fuer die Tooltips aller Kinder gilt - ein transparenter Tooltip wird unter Windows schwarz.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QToolTip

from src.gui.vorschlag_liste import AUSLASSUNG, VorschlagListe, VorschlagZeile, pfad_kuerzen
from tests.test_vorschlag_liste_gui import _aufbau


def _laenge(text: str) -> int:
    return len(text)  # 1 Zeichen = 1 "Pixel": unabhaengig von den Schriften der Testumgebung


# --- pfad_kuerzen -----------------------------------------------------------

def test_passt_bleibt_unveraendert():
    pfad = "C:\\A\\B\\Ziel"
    assert pfad_kuerzen(pfad, _laenge, 100) == pfad
    assert pfad_kuerzen("", _laenge, 0) == ""


@pytest.mark.parametrize("breite,erwartet", [
    (len("…\\OrdnerB\\OrdnerC\\OrdnerE"), "…\\OrdnerB\\OrdnerC\\OrdnerE"),
    (len("…\\OrdnerC\\OrdnerE") + 3, "…\\OrdnerC\\OrdnerE"),
    (len("…\\OrdnerE"), "…\\OrdnerE"),
])
def test_faellt_von_links_in_ganzen_ordnern_weg(breite, erwartet):
    pfad = "C:\\OrdnerA\\OrdnerB\\OrdnerC\\OrdnerE"
    assert pfad_kuerzen(pfad, _laenge, breite) == erwartet


def test_schraegstriche_bleiben_schraegstriche():
    assert pfad_kuerzen("/home/ich/Ablage/Steuer 2025", _laenge, 20) == "…/Ablage/Steuer 2025"


def test_zu_schmal_fuer_den_letzten_ordner_zeigt_dessen_ende():
    text = pfad_kuerzen("C:\\A\\Versicherungen", _laenge, 6)
    assert text.startswith(AUSLASSUNG) and "Versicherungen".endswith(text[1:]) and len(text) <= 6
    assert pfad_kuerzen("C:\\A\\Versicherungen", _laenge, 0) == AUSLASSUNG


# --- Vorschlagszeile im Hauptfenster-Ablauf ----------------------------------

def test_zeile_zeigt_vollen_elternpfad_rechts_mit_vorrang(qtbot, tmp_path):
    rel = "Ablage/" + "/".join(["Sehr langer Unterordner"] * 4) + "/Steuer 2025/Ziel"
    host, liste, fake = _aufbau(qtbot, tmp_path, 1, 260, rels=[rel])
    z = fake.suggestion_widgets[0]
    eltern = (tmp_path / Path(rel)).parent
    assert z._pfad_voll == str(eltern)  # absoluter Pfad samt Laufwerk
    text = z.path_label.text()
    assert text.startswith(AUSLASSUNG) and text.endswith("Steuer 2025")  # Ordner direkt darueber sichtbar
    assert str(tmp_path / Path(rel)) in z.toolTip()

    # Breit genug: ganzer Pfad (ein Vorschlag bekommt nur eine von drei Spalten)
    host.resize(30000, 400)
    qtbot.waitUntil(lambda: z.path_label.text() == str(eltern), timeout=2000)


def test_neuer_ordner_zeigt_ebenfalls_den_vollen_elternpfad(qtbot, tmp_path):
    from src.core import neuer_ordner
    from src.gui.main_window import MainWindow

    host, liste, fake = _aufbau(qtbot, tmp_path, 0, 400)
    s = SimpleNamespace(folder_path=tmp_path / "Steuer 2026" / "Versicherungen", folder_name="Versicherungen",
                        relative_path="Steuer 2026/Versicherungen", reason="x", confidence=0.9,
                        new_source=neuer_ordner.QUELLE_JAHR)
    MainWindow.display_suggestions(fake, [s])
    z = fake.suggestion_widgets[0]
    assert z._pfad_voll == str(tmp_path / "Steuer 2026")
    assert z._name_voll == "➕ neu: Versicherungen"


# --- Tooltips ----------------------------------------------------------------

def _tooltip_hell(qtbot, widget) -> bool:
    QToolTip.showText(widget.mapToGlobal(QPoint(4, 4)), widget.toolTip() or "Tipp", widget)
    try:
        tips = []
        qtbot.waitUntil(lambda: tips.extend(
            w for w in QApplication.topLevelWidgets()
            if w.metaObject().className() == "QTipLabel" and w.isVisible()) or bool(tips), timeout=2000)
        bild = tips[0].grab().toImage()
        farbe = bild.pixelColor(bild.width() - 3, bild.height() // 2)  # rechter Rand: kein Text
        return farbe.alpha() == 255 and farbe.lightness() > 150
    finally:
        QToolTip.hideText()


def test_tooltip_der_vorschlagszeile_ist_nicht_transparent(qtbot, tmp_path):
    liste = VorschlagListe()
    qtbot.addWidget(liste)
    zeile = VorschlagZeile(tmp_path / "Ziel")
    zeile.is_suggestion = True
    liste.spalten.addWidget(zeile)
    liste.resize(400, 60)
    liste.show()
    qtbot.waitExposed(liste)
    assert _tooltip_hell(qtbot, zeile)


def test_tooltip_des_typ_etiketts_ist_hell(qtbot, tmp_path, monkeypatch):
    from src.gui.office_thumbnail import OfficeThumbnailWidget

    monkeypatch.setattr(OfficeThumbnailWidget, "load_thumbnail", lambda self: None)
    kachel = OfficeThumbnailWidget(tmp_path / "Brief.docx")
    qtbot.addWidget(kachel)
    kachel.show()
    qtbot.waitExposed(kachel)
    assert _tooltip_hell(qtbot, kachel.typ_label)  # vorher blau mit 9-px-Schrift

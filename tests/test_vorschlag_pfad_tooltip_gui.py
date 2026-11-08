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

from src.gui.vorschlag_liste import (
    AUSLASSUNG,
    VorschlagListe,
    VorschlagZeile,
    pfad_kuerzen,
    zeilen_aufteilen,
)
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


# --- zeilen_aufteilen: unten Ende + fettes Ziel, oben der Anfang --------------

def _halb(text: str) -> int:
    return len(text) // 2  # obere Zeile: kleinere Schrift


def _teilen(breite, eltern="E:\\Users\\johan_000\\OneDrive\\1PaperPort14", name="Kinder", praefix="",
            messen_oben=_halb):
    return zeilen_aufteilen(eltern, name, breite, messen_oben, _laenge, _laenge, praefix)


def test_beispiel_des_users():
    # unten passt "\1PaperPort14" + "\Kinder" (20 Zeichen), mehr nicht
    assert _teilen(20) == ("E:\\Users\\johan_000\\OneDrive\\", "\\1PaperPort14", "\\Kinder")


def test_unten_wird_von_rechts_gefuellt_oben_bekommt_den_rest():
    oben, unten, fett = _teilen(29)
    assert (oben, unten, fett) == ("E:\\Users\\johan_000\\", "\\OneDrive\\1PaperPort14", "\\Kinder")
    assert oben + unten[1:] + fett == "E:\\Users\\johan_000\\OneDrive\\1PaperPort14\\Kinder"


def test_passt_alles_unten_bleibt_oben_leer():
    assert _teilen(200) == ("", "E:\\Users\\johan_000\\OneDrive\\1PaperPort14", "\\Kinder")
    assert _teilen(0) == ("", "E:\\Users\\johan_000\\OneDrive\\1PaperPort14", "\\Kinder")  # Geometrie unbekannt


def test_oben_zu_lang_faellt_links_in_ganzen_ordnern_weg():
    eltern = "E:\\Users\\johan_000\\Sehr langer Ordnername\\Noch einer\\OneDrive\\1PaperPort14"
    oben, unten, fett = _teilen(len("\\OneDrive\\1PaperPort14\\Kinder"), eltern, messen_oben=_laenge)
    assert unten == "\\OneDrive\\1PaperPort14" and fett == "\\Kinder"
    assert oben == "…\\Noch einer\\"  # der Ordner direkt ueber der unteren Zeile bleibt


def test_nur_das_ziel_passt_unten():
    oben, unten, fett = _teilen(len("\\Kinder") + 2)
    assert unten == "" and fett == "\\Kinder"
    assert oben == "…\\1PaperPort14\\"


def test_ziel_zu_lang_wird_rechts_gekuerzt():
    oben, unten, fett = _teilen(5)
    assert fett.endswith(AUSLASSUNG) and len(fett) <= 5 and fett.startswith("\\Ki")
    assert unten == "" and oben.endswith("\\")


def test_praefix_fuer_neue_ordner_und_unix_pfade():
    oben, unten, fett = zeilen_aufteilen("/home/ich/Steuer 2026", "Versicherungen", 200,
                                         _laenge, _laenge, _laenge, "➕ neu: ")
    assert (oben, unten, fett) == ("", "➕ neu: /home/ich/Steuer 2026", "/Versicherungen")
    oben, unten, fett = zeilen_aufteilen("/home/ich/Steuer 2026", "Versicherungen",
                                         len("➕ neu: /Steuer 2026/Versicherungen"),
                                         _laenge, _laenge, _laenge, "➕ neu: ")
    assert (oben, unten, fett) == ("/home/ich/", "➕ neu: /Steuer 2026", "/Versicherungen")


# --- Vorschlagszeile im Hauptfenster-Ablauf ----------------------------------

def test_zeile_zeigt_vollen_pfad_auf_zwei_zeilen(qtbot, tmp_path):
    rel = "Ablage/" + "/".join(["Sehr langer Unterordner"] * 4) + "/Steuer 2025/Ziel"
    host, liste, fake = _aufbau(qtbot, tmp_path, 1, 260, rels=[rel])
    z = fake.suggestion_widgets[0]
    eltern = (tmp_path / Path(rel)).parent
    assert z._pfad_voll == str(eltern)  # absoluter Pfad samt Laufwerk
    oben, unten, fett = z._zeilen
    assert fett == "\\Ziel" and "<b>\\Ziel</b>" in z.name_label.text()  # Ziel fett, unten
    assert oben.endswith("\\") and z.path_label.text() == oben and z.path_label.isVisibleTo(z)
    assert str(tmp_path / Path(rel)) in z.toolTip()

    # Breit genug: alles unten, obere Zeile weg (ein Vorschlag bekommt eine von drei Spalten)
    host.resize(30000, 400)
    qtbot.waitUntil(lambda: z._zeilen == ("", str(eltern), "\\Ziel"), timeout=2000)
    assert not z.path_label.isVisibleTo(z)


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
    assert z._name_voll == "Versicherungen" and z._praefix == "➕ neu: "
    assert "➕ neu: " in z.name_label.text() and "<b>\\Versicherungen</b>" in z.name_label.text()


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

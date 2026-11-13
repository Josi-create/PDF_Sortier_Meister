"""Farbschema Hell / Dunkel / wie das System (Issue #238): Palette, Schalter, Umfaerben im Betrieb."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QLabel

from src.gui import farben

GUI = Path(farben.__file__).resolve().parent


@pytest.fixture
def schema_zurueck(qapp):
    """Nach dem Test gilt wieder Hell mit der Palette von vorher (wie in allen anderen Tests)."""
    palette, stylesheet = qapp.palette(), qapp.styleSheet()
    yield
    farben._dunkel, farben._wahl, farben._app_stil = False, farben.HELL, None
    try:
        qapp.styleHints().unsetColorScheme()
    except AttributeError:
        pass
    qapp.setPalette(palette)
    qapp.setStyleSheet(stylesheet)


@pytest.fixture
def fresh_config(monkeypatch, tmp_path):
    from src.core import pdf_cache as pc_mod
    from src.ml import classifier as cl_mod
    from src.ml import hybrid_classifier as hc_mod
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod
    from tests.conftest import patch_singletons

    fresh = cfg_mod.Config(config_path=tmp_path / "config.json")
    fresh.set("persist_pdf_cache", False)
    monkeypatch.setattr(pc_mod.PDFCache, "_instance", None)
    patch_singletons(monkeypatch, {
        "get_config": lambda: fresh,
        "get_database": lambda: db_mod.Database(db_path=str(tmp_path / "t.db")),
        "get_classifier": cl_mod.PDFClassifier,
        "get_hybrid_classifier": hc_mod.HybridClassifier,
        "get_pdf_cache": pc_mod.PDFCache,
    })
    return fresh


# --- Palette ------------------------------------------------------------------

def test_jede_farbe_hat_gueltige_werte_fuer_hell_und_dunkel():
    for name, werte in farben.FARBEN.items():
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name), name
        assert len(werte) == 2, name
        for wert in werte:
            if wert.startswith("rgba("):
                continue
            assert QColor(wert).isValid(), f"{name}: {wert}"


def test_ohne_einrichten_gilt_hell_mit_den_bisherigen_werten():
    assert not farben.ist_dunkel()
    assert farben.farbe("gelb_flaeche") == "#fff3cd"
    assert farben.css("color: $grau_66; border: 1px solid $gelb_rand;") == "color: #666; border: 1px solid #daa520;"
    assert farben.css("font-size: 11px;") == "font-size: 11px;"


def test_unbekannter_name_bleibt_im_text_stehen_farbe_meldet_ihn():
    assert farben.css("Ordner $gibt_es_nicht, color: $rot;") == "Ordner $gibt_es_nicht, color: #d32f2f;"
    assert farben.farbe("$rot") == farben.farbe("rot") == "#d32f2f"
    with pytest.raises(KeyError):
        farben.farbe("gibt_es_nicht")


def test_gespeicherter_wert_wird_geprueft():
    assert farben.schema("dunkel") == farben.DUNKEL
    assert farben.schema(" Hell ") == farben.HELL
    for unbekannt in (None, "", "light", 3):
        assert farben.schema(unbekannt) == farben.SYSTEM


def test_dunkle_schrift_ist_auf_dunklem_grund_lesbar():
    """Jeder dunkle Wert hebt sich vom dunklen Fenstergrund oder von der dunklen Eingabeflaeche ab."""
    def helligkeit(wert: str) -> float:
        c = QColor(wert)
        kanal = [(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
                 for v in (c.redF(), c.greenF(), c.blueF())]
        return 0.2126 * kanal[0] + 0.7152 * kanal[1] + 0.0722 * kanal[2]

    grund = helligkeit(farben._PALETTE_DUNKEL["Window"])
    for name, (_hell, dunkel) in farben.FARBEN.items():
        if "text" in name or name in ("grau_20", "grau_22", "grau_33", "grau_44", "grau_55", "grau_66", "grau_77", "grau_88"):
            kontrast = (helligkeit(dunkel) + 0.05) / (grund + 0.05)
            assert kontrast >= 4.5, f"{name}: {dunkel} hat nur Kontrast {kontrast:.1f}"


# --- Umschalten -----------------------------------------------------------------

def test_dunkel_setzt_palette_und_faerbt_gemerkte_stylesheets_um(qtbot, qapp, schema_zurueck):
    label = QLabel("x")
    qtbot.addWidget(label)
    farben.stil(label, "color: $grau_66; background-color: $gelb_flaeche;")
    ohne = QLabel("y")
    qtbot.addWidget(ohne)
    farben.stil(ohne, "font-weight: bold;")
    assert label.styleSheet() == "color: #666; background-color: #fff3cd;"
    gemeldet = []
    farben.melder.geaendert.connect(lambda: gemeldet.append(farben.ist_dunkel()))

    farben.anwenden(farben.DUNKEL, qapp)

    assert farben.ist_dunkel() and gemeldet == [True]
    assert label.styleSheet() == "color: #b4b4b4; background-color: #4a3d14;"
    assert ohne.styleSheet() == "font-weight: bold;"
    fenster = qapp.palette().color(QPalette.ColorRole.Window)
    assert fenster.lightness() < 80 and qapp.palette().color(QPalette.ColorRole.WindowText).lightness() > 180
    aus = qapp.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText)
    assert aus != qapp.palette().color(QPalette.ColorRole.ButtonText)  # deaktivierte Knoepfe sind erkennbar

    farben.anwenden(farben.HELL, qapp)

    assert not farben.ist_dunkel() and gemeldet == [True, False]
    assert label.styleSheet() == "color: #666; background-color: #fff3cd;"
    assert qapp.palette().color(QPalette.ColorRole.Window) == QColor(240, 240, 240)
    assert qapp.palette().color(QPalette.ColorRole.Text) == QColor(0, 0, 0)


def test_spaeteres_stylesheet_ohne_farbe_wird_nicht_wieder_ueberschrieben(qtbot, qapp, schema_zurueck):
    label = QLabel("x")
    qtbot.addWidget(label)
    farben.stil(label, "color: $rot;")
    farben.stil(label, "")
    direkt = QLabel("y")
    qtbot.addWidget(direkt)
    farben.stil(direkt, "color: $rot;")
    direkt.setStyleSheet("font-style: italic;")  # ohne stil() ueberschrieben
    farben.anwenden(farben.DUNKEL, qapp)
    assert label.styleSheet() == ""
    assert direkt.styleSheet() == "font-style: italic;"


def test_system_folgt_dem_betriebssystem_auch_im_betrieb(qapp, schema_zurueck, monkeypatch):
    system = {"dunkel": False}
    monkeypatch.setattr(farben, "_system_dunkel", lambda app: system["dunkel"])
    farben.anwenden(farben.SYSTEM, qapp)
    assert not farben.ist_dunkel()

    system["dunkel"] = True
    farben._system_geaendert(Qt.ColorScheme.Dark)
    assert farben.ist_dunkel()

    system["dunkel"] = False
    farben._system_geaendert(Qt.ColorScheme.Light)
    assert not farben.ist_dunkel()


def test_feste_wahl_ignoriert_den_wechsel_des_systems(qapp, schema_zurueck, monkeypatch):
    farben.anwenden(farben.HELL, qapp)
    monkeypatch.setattr(farben, "_system_dunkel", lambda app: True)
    farben._system_geaendert(Qt.ColorScheme.Dark)
    assert not farben.ist_dunkel()


def test_einrichten_liest_die_einstellung_und_faerbt_das_anwendungs_stylesheet(qapp, schema_zurueck, fresh_config):
    assert fresh_config.get(farben.KONFIG_SCHLUESSEL) == farben.SYSTEM  # Standard
    fresh_config.set(farben.KONFIG_SCHLUESSEL, farben.DUNKEL)
    farben.einrichten(qapp, fresh_config, lambda: "QCheckBox::indicator { background-color: $weiss; }")
    assert farben.ist_dunkel()
    assert qapp.styleSheet() == "QCheckBox::indicator { background-color: #262626; }"
    farben.anwenden(farben.HELL, qapp)
    assert qapp.styleSheet() == "QCheckBox::indicator { background-color: white; }"


# --- Einstellungen --------------------------------------------------------------

def test_schalter_in_den_einstellungen_speichert_und_gilt_sofort(qtbot, qapp, schema_zurueck, fresh_config):
    from src.gui.settings_dialog import SettingsDialog

    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    combo = dialog.farbschema_combo
    assert [combo.itemData(i) for i in range(combo.count())] == [farben.SYSTEM, farben.HELL, farben.DUNKEL]
    assert combo.currentData() == farben.SYSTEM

    combo.setCurrentIndex(combo.findData(farben.DUNKEL))
    dialog._save_settings()

    assert fresh_config.get(farben.KONFIG_SCHLUESSEL) == farben.DUNKEL
    assert farben.ist_dunkel()

    zweiter = SettingsDialog()
    qtbot.addWidget(zweiter)
    assert zweiter.farbschema_combo.currentData() == farben.DUNKEL


# --- Quelltext ------------------------------------------------------------------

def test_alle_farbnamen_im_quelltext_gibt_es():
    """Jedes ``$name`` in einem GUI-Modul steht in farben.FARBEN (sonst KeyError erst zur Laufzeit)."""
    unbekannt = []
    for pfad in sorted(GUI.glob("*.py")):
        if pfad.name == "farben.py":
            continue
        for nr, zeile in enumerate(pfad.read_text(encoding="utf-8").splitlines(), 1):
            for name in re.findall(r"\$([a-z][a-z0-9_]*)", zeile):
                if name not in farben.FARBEN:
                    unbekannt.append(f"{pfad.name}:{nr}: ${name}")
    assert not unbekannt, "\n".join(unbekannt)


def test_stylesheet_mit_farbnamen_laeuft_ueber_stil():
    """``setStyleSheet("... $name ...")`` braechte den Namen unersetzt ins Stylesheet."""
    falsch = []
    for pfad in sorted(GUI.glob("*.py")):
        text = pfad.read_text(encoding="utf-8")
        for m in re.finditer(r"\.setStyleSheet\(", text):
            # bis zur schliessenden Klammer derselben Anweisung (Stylesheets enthalten keine Klammer-Reste)
            tiefe, i = 0, m.end() - 1
            while i < len(text):
                tiefe += text[i] == "("
                tiefe -= text[i] == ")"
                if tiefe == 0:
                    break
                i += 1
            if "$" in text[m.end():i]:
                falsch.append(f"{pfad.name}:{text.count(chr(10), 0, m.start()) + 1}")
    assert not falsch, "stil(widget, ...) statt setStyleSheet verwenden: " + ", ".join(falsch)

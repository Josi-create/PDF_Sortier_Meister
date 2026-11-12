"""Übersetzung der Oberfläche (Issue #118): Sprachwahl, Umschalten, Vollständigkeit."""
import ast
import json
import re
import string
from pathlib import Path

import pytest

from src import i18n

SRC = Path(i18n.__file__).resolve().parent.parent


@pytest.fixture
def sprache():
    """Stellt die Sprache nach dem Test wieder auf Deutsch (wie tests/conftest.py)."""
    yield i18n.set_language
    i18n.set_language("de")


def markierte_texte() -> dict[str, list[str]]:
    """Alle Texte in ``tr("...")``-Aufrufen unter src: Schlüssel wie im Katalog -> Fundstellen."""
    texte: dict[str, list[str]] = {}
    for pfad in sorted(SRC.rglob("*.py")):
        tree = ast.parse(pfad.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "tr"):
                continue
            ort = f"{pfad.relative_to(SRC.parent).as_posix()}:{node.lineno}"
            assert node.args and isinstance(node.args[0], ast.Constant) and isinstance(
                node.args[0].value, str
            ), f"{ort}: tr() braucht ein Zeichenkettenliteral, sonst ist der Text nicht übersetzbar"
            kontext = None
            if len(node.args) > 1:
                kontext = ast.literal_eval(node.args[1])
            for kw in node.keywords:
                if kw.arg == "kontext":
                    kontext = ast.literal_eval(kw.value)
            schluessel = f"{kontext}\x04{node.args[0].value}" if kontext else node.args[0].value
            texte.setdefault(schluessel, []).append(ort)
    for pfad in sorted(SRC.rglob("static/*.html")):
        for text in i18n.texte_in_html(pfad.read_text(encoding="utf-8")):
            texte.setdefault(text, []).append(pfad.relative_to(SRC.parent).as_posix())
    return texte


# --- Sprachwahl ---------------------------------------------------------------

@pytest.mark.parametrize("einstellung, system, erwartet", [
    ("auto", "de", "de"),
    ("auto", "de_AT", "de"),
    ("auto", "de-CH", "de"),
    ("auto", "en", "en"),
    ("auto", "en_US.UTF-8", "en"),
    ("auto", "fr", "en"),          # alles außer Deutsch wird Englisch
    ("auto", "", "en"),            # Systemsprache unbekannt
    ("", "de", "de"),
    (None, "ja", "en"),
    ("de", "en", "de"),            # ausdrückliche Wahl geht vor
    ("en", "de", "en"),
    ("EN", "de", "en"),
    ("xx", "de", "en"),            # unbekanntes Kürzel: Englisch
])
def test_sprachwahl_nach_einstellung_und_system(einstellung, system, erwartet):
    assert i18n.resolve_language(einstellung, system) == erwartet


def test_standard_der_einstellung_ist_automatisch(tmp_path):
    from src.utils.config import Config

    assert Config(config_path=tmp_path / "config.json").get("language") == "auto"


def test_alte_konfiguration_mit_de_bleibt_deutsch(tmp_path):
    """Bis 0.26 stand "language": "de" in jeder config.json; diese Nutzer bleiben bei Deutsch."""
    from src.utils.config import Config

    datei = tmp_path / "config.json"
    datei.write_text(json.dumps({"language": "de"}), encoding="utf-8")
    assert Config(config_path=datei).get("language") == "de"
    assert i18n.resolve_language("de", "en") == "de"


def test_systemsprache_windows(monkeypatch):
    import ctypes

    if not hasattr(ctypes, "windll"):
        pytest.skip("nur Windows")
    monkeypatch.setattr(i18n.sys, "platform", "win32")

    class Kernel:
        @staticmethod
        def GetUserDefaultUILanguage():  # noqa: N802
            return 0x0C07  # Deutsch (Österreich)

    monkeypatch.setattr(ctypes.windll, "kernel32", Kernel, raising=False)
    assert i18n.system_language() == "de"


def test_systemsprache_aus_umgebung(monkeypatch):
    monkeypatch.setattr(i18n.sys, "platform", "linux")
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    assert i18n.system_language() == ""
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert i18n.system_language() == "de"
    monkeypatch.setenv("LC_ALL", "C")              # "C" sagt nichts über die Sprache
    assert i18n.system_language() == "de"
    monkeypatch.setenv("LANGUAGE", "fr:en")
    assert i18n.system_language() == "fr"


def test_erster_aufruf_liest_einstellung_aus_config_json(monkeypatch, tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"language": "en"}), encoding="utf-8")
    monkeypatch.setattr("src.utils.platform_paths.get_app_data_dir", lambda create=True: tmp_path)
    assert i18n.configured_language() == "en"
    monkeypatch.delenv(i18n.ENV_VAR)
    monkeypatch.setattr(i18n, "_language", None)
    try:
        assert i18n.current_language() == "en"
    finally:
        i18n.set_language("de")


def test_einstellung_ohne_oder_mit_defekter_datei_ist_automatisch(monkeypatch, tmp_path):
    monkeypatch.setattr("src.utils.platform_paths.get_app_data_dir", lambda create=True: tmp_path)
    assert i18n.configured_language() == "auto"
    (tmp_path / "config.json").write_text("{kaputt", encoding="utf-8")
    assert i18n.configured_language() == "auto"


def test_umgebungsvariable_geht_vor(monkeypatch, tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"language": "de"}), encoding="utf-8")
    monkeypatch.setattr("src.utils.platform_paths.get_app_data_dir", lambda create=True: tmp_path)
    monkeypatch.setenv(i18n.ENV_VAR, "en")
    monkeypatch.setattr(i18n, "_language", None)
    try:
        assert i18n.current_language() == "en"
    finally:
        i18n.set_language("de")


def test_tests_laufen_deutsch():
    assert i18n.current_language() == "de"


# --- Umschalten -----------------------------------------------------------------

def test_deutsch_gibt_den_text_unveraendert_zurueck(sprache):
    sprache("de")
    text = "Ein Text, den es in keiner Übersetzung gibt: {zahl} „ä“"
    assert i18n.tr(text) is text


def test_umschalten_auf_englisch_und_zurueck(sprache):
    sprache("en")
    assert i18n.current_language() == "en"
    assert i18n.tr("Sprache:") == "Language:"
    assert i18n.tr("Kein Eintrag für diesen Text 4711") == "Kein Eintrag für diesen Text 4711"
    sprache("de")
    assert i18n.tr("Sprache:") == "Sprache:"


def test_weitere_sprache_braucht_nur_eine_datei(monkeypatch, tmp_path, sprache):
    (tmp_path / "fr.po").write_text(
        'msgid ""\nmsgstr ""\n"Language: fr\\n"\n"X-Language-Name: Français\\n"\n\n'
        'msgid "PDF Sortier Meister"\nmsgstr "Maître du tri"\n\n'
        'msgid "Sprache:"\nmsgstr "Langue :"\n\n'
        'msgctxt "Menü"\nmsgid "Datei"\nmsgstr "Fichier"\n\n'
        'msgid "Datei"\nmsgstr "fichier"\n\n'
        'msgid ""\n"Zeile 1\\n"\n"mit \\"Anführung\\" {n}"\nmsgstr ""\n"Ligne 1\\n"\n"avec {n}"\n\n'
        'msgid "Über PDF Sortier Meister"\nmsgstr "À propos de PDF Sortier Meister"\n\n'
        'msgid "Ohne Übersetzung"\nmsgstr ""\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(i18n, "LOCALE_DIR", tmp_path)
    assert i18n.available_languages() == [("de", "Deutsch"), ("fr", "Français")]
    assert i18n.resolve_language("fr", "de") == "fr"
    sprache("fr")
    assert i18n.tr("Sprache:") == "Langue :"
    assert i18n.tr("Datei", "Menü") == "Fichier"
    assert i18n.tr("Datei") == "fichier"
    assert i18n.tr("Datei", "anderer Kontext") == "fichier"
    assert i18n.tr('Zeile 1\nmit "Anführung" {n}') == "Ligne 1\navec {n}"
    assert i18n.tr("Ohne Übersetzung") == "Ohne Übersetzung"
    # Der Programmname steht je Sprache an einer Stelle und wird überall eingesetzt
    assert i18n.app_name() == "Maître du tri"
    assert i18n.tr("Über PDF Sortier Meister") == "À propos de Maître du tri"


def test_fehlende_sprachdatei_faellt_auf_deutsch_zurueck(monkeypatch, tmp_path, sprache):
    monkeypatch.setattr(i18n, "LOCALE_DIR", tmp_path)
    sprache("en")
    assert i18n.current_language() == "de"
    assert i18n.tr("Sprache:") == "Sprache:"


def test_po_literal_und_lesen_passen_zusammen(tmp_path):
    text = 'Pfad C:\\Ordner\t"Name"\nzweite Zeile {x} 100 %'
    datei = tmp_path / "xx.po"
    datei.write_text(
        f"msgid {i18n.po_literal(text)}\nmsgstr {i18n.po_literal(text.upper())}\n", encoding="utf-8"
    )
    assert i18n.read_po(datei)[0] == {text: text.upper()}


# --- Einstellungen ----------------------------------------------------------------

def test_einstellungen_zeigen_und_speichern_die_sprache(qtbot, fresh_config):
    from src.gui.settings_dialog import SettingsDialog

    dlg = SettingsDialog()
    qtbot.addWidget(dlg)
    combo = dlg.language_combo
    assert [combo.itemData(i) for i in range(combo.count())][:3] == ["auto", "de", "en"]
    assert combo.currentData() == "auto"
    combo.setCurrentIndex(combo.findData("en"))
    dlg._save_settings()
    assert fresh_config.get("language") == "en"

    dlg2 = SettingsDialog()
    qtbot.addWidget(dlg2)
    assert dlg2.language_combo.currentData() == "en"


# --- Vollständigkeit --------------------------------------------------------------

def test_programm_liefert_die_uebersetzungsdateien_mit():
    spec = (SRC.parent / "pdf_sortier_meister.spec").read_text(encoding="utf-8")
    assert spec.count('"src/i18n/locale"') == 2, "Oberfläche und pdfsm-dienst brauchen die .po-Dateien"
    assert (i18n.LOCALE_DIR / "en.po").is_file()


def test_jeder_markierte_text_hat_eine_englische_uebersetzung():
    katalog, kopf = i18n.read_po(i18n.LOCALE_DIR / "en.po")
    assert kopf.get("X-Language-Name") == "English"
    fehlend = {text: orte[0] for text, orte in markierte_texte().items() if text not in katalog}
    assert not fehlend, (
        f"{len(fehlend)} Texte ohne englische Übersetzung in src/i18n/locale/en.po "
        "(python tools/i18n_werkzeug.py offen): "
        + "; ".join(f"{ort}: {text[:50]!r}" for text, ort in list(fehlend.items())[:15])
    )


def _felder(text: str) -> list[str]:
    return sorted(feld for _, feld, _, _ in string.Formatter().parse(text) if feld is not None)


def test_uebersetzungen_behalten_platzhalter_und_tastenkuerzel():
    katalog, _ = i18n.read_po(i18n.LOCALE_DIR / "en.po")
    maengel = []
    for deutsch, englisch in katalog.items():
        deutsch = deutsch.split("\x04")[-1]
        try:
            if _felder(deutsch) != _felder(englisch):
                maengel.append(f"Platzhalter: {deutsch[:60]!r}")
        except ValueError:
            # Kein Formattext (einzelne Klammer): dann muss er gleich viele Klammern behalten
            if deutsch.count("{") != englisch.count("{"):
                maengel.append(f"Klammern: {deutsch[:60]!r}")
        if sorted(re.findall(r"%[sd]", deutsch)) != sorted(re.findall(r"%[sd]", englisch)):
            maengel.append(f"%-Platzhalter: {deutsch[:60]!r}")
        kuerzel = re.compile(r"&(?![&#]|amp;|nbsp;|lt;|gt;|quot;)\w")
        if bool(kuerzel.search(deutsch)) != bool(kuerzel.search(englisch)):
            maengel.append(f"Tastenkürzel (&): {deutsch[:60]!r}")
    assert not maengel, "\n".join(maengel)


# --- Englische Oberfläche ---------------------------------------------------------

def test_einstellungsdialog_auf_englisch(qtbot, fresh_config, sprache):
    from src.gui.settings_dialog import SettingsDialog

    sprache("en")
    dlg = SettingsDialog()
    qtbot.addWidget(dlg)
    titel = [dlg.tab_widget.tabText(i) for i in range(dlg.tab_widget.count())]
    assert titel == ["AI assistant (LLM)", "Personal data", "File names", "General", "Search"]
    # Reiter werden über ihren Titel angesprungen; der Aufrufer übersetzt mit
    assert dlg.show_tab(i18n.tr("Suche"))
    assert dlg.windowTitle() == "Settings"


@pytest.mark.parametrize("kuerzel, reiter", [("de", "Allgemein"), ("en", "General")])
def test_sprachwahl_steht_zuoberst_im_reiter_allgemein(qtbot, fresh_config, sprache, kuerzel, reiter):
    """Issue #235: die Sprachwahl ist in beiden Sprachen auf den ersten Blick zu finden."""
    from PyQt6.QtWidgets import QGroupBox

    from src.gui.settings_dialog import SettingsDialog

    sprache(kuerzel)
    dlg = SettingsDialog()
    qtbot.addWidget(dlg)
    assert dlg.show_tab(reiter)
    gruppen = dlg.tab_widget.currentWidget().findChildren(QGroupBox)
    assert gruppen[0].title() == "Sprache / Language"
    assert gruppen[0].isAncestorOf(dlg.language_combo)


def test_begruendung_wird_erst_bei_der_anzeige_uebersetzt(sprache):
    """Die Begründung bleibt intern deutsch (kind_from_reason liest sie), nur die Anzeige wechselt."""
    from src.core.suggestion_order import KIND_KI, KIND_LEARNED, kind_from_reason, reason_display

    assert reason_display("KI-Vorschlag") == "KI-Vorschlag"
    assert reason_display("Muster: Rechnungen & Belege") == "Muster: Rechnungen & Belege"
    sprache("en")
    assert reason_display("KI-Vorschlag") == "AI suggestion"
    assert reason_display("Gelernt: ähnlich zu brief.pdf") == "Learned: similar to brief.pdf"
    assert reason_display("Muster: Rechnungen & Belege") == "Pattern: Rechnungen & Belege"
    assert reason_display("etwas anderes") == "etwas anderes"
    assert kind_from_reason("KI-Vorschlag") == KIND_KI
    assert kind_from_reason("Gelernt: ähnlich zu brief.pdf") == KIND_LEARNED


def test_keine_lokale_variable_verdeckt_tr():
    """Eine lokale Variable ``tr`` würde in derselben Funktion jeden ``tr("...")``-Aufruf brechen."""
    funde = []
    for pfad in sorted(SRC.rglob("*.py")):
        tree = ast.parse(pfad.read_text(encoding="utf-8"))
        for funktion in ast.walk(tree):
            if not isinstance(funktion, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            knoten = list(ast.walk(funktion))
            zuweisung = any(isinstance(k, ast.Name) and k.id == "tr" and isinstance(k.ctx, ast.Store)
                            for k in knoten)
            aufruf = any(isinstance(k, ast.Call) and isinstance(k.func, ast.Name) and k.func.id == "tr"
                         for k in knoten)
            if zuweisung and aufruf:
                funde.append(f"{pfad.relative_to(SRC.parent).as_posix()}:{funktion.lineno} {funktion.name}")
    assert not funde, funde


def test_browser_oberflaeche_bekommt_die_texte_aus_derselben_po_datei(sprache):
    from src.search import web

    roh = (web.STATIC / "index.html").read_text(encoding="utf-8")
    texte = i18n.texte_in_html(roh)
    assert "Suchen" in texte and "Weitere Treffer laden" in texte and "z. B. Steuer" in texte
    assert '"sprache": "de"' in web.startseite()
    sprache("en")
    seite = web.startseite()
    assert '"sprache": "en"' in seite
    assert '"Weitere Treffer laden": "Load more results"' in seite
    assert "/*I18N*/" not in seite
    # Schlüsselwörter der Suchsyntax bleiben in jeder Sprache gleich
    assert "Mietvertrag ODER Pachtvertrag" in seite and "Rechnung NICHT Mahnung" in seite

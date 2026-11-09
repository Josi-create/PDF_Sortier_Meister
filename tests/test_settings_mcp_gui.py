"""Einstellungen › Suche › „KI-Assistenten (MCP)“ (Baustein 3, docs/CHAT_MCP_PLAN.md).

Die Logik (``src/search/mcp_einrichtung.py``) ist gepatcht bzw. arbeitet auf einer
Konfigurationsdatei in ``tmp_path``; Rueckfragen werden beantwortet, Meldungen gemerkt.
Kein Test startet das echte ``claude`` oder beruehrt die echte Claude-Desktop-Konfiguration.
"""
import json

import pytest
from PyQt6.QtWidgets import QApplication, QGroupBox, QMessageBox

from src.search import mcp_einrichtung as me

GEBAUT = me.DienstAufruf(r"C:\Programme\PDF Sortier Meister\pdfsm-dienst.exe", ("mcp",))


@pytest.fixture(autouse=True)
def umgebung(monkeypatch, tmp_path):
    """Plattformabfragen des Reiters neutral, Dienst „gebaut“, Rueckfragen und Meldungen abgefangen."""
    monkeypatch.setattr("src.search.plattform.thunderbird_mail_ordner", lambda profiles_ini=None: [])
    monkeypatch.setattr("src.search.plattform.wurzel_vorschlaege", lambda: [])
    monkeypatch.setattr("src.utils.tesseract.find_tesseract", lambda: None)
    monkeypatch.setattr(me, "dienst_aufruf", lambda: GEBAUT)
    zustand = {"fragen": [], "antwort": QMessageBox.StandardButton.Yes, "meldungen": []}

    def frage(parent, titel, text, *args, **kwargs):
        zustand["fragen"].append(text)
        return zustand["antwort"]

    def meldung(art):
        def _m(parent, titel, text, *args, **kwargs):
            zustand["meldungen"].append((art, text))
            return QMessageBox.StandardButton.Ok
        return _m

    monkeypatch.setattr(QMessageBox, "question", frage)
    monkeypatch.setattr(QMessageBox, "information", meldung("info"))
    monkeypatch.setattr(QMessageBox, "warning", meldung("warnung"))
    return zustand


def _dialog(qtbot, monkeypatch, tmp_path, **config_values):
    from src.utils import config as cfg_mod
    from src.utils.config import Config

    cfg = Config.__new__(Config)
    cfg.config_path = tmp_path / "config.json"
    cfg._config = {}
    cfg.load()
    for key, value in config_values.items():
        cfg.set(key, value, auto_save=False)
    monkeypatch.setattr(cfg_mod, "get_config", lambda: cfg)
    monkeypatch.setattr("src.gui.settings_dialog.get_config", lambda: cfg, raising=False)
    from src.gui.settings_dialog import SettingsDialog

    dlg = SettingsDialog()
    qtbot.addWidget(dlg)
    return dlg, cfg


def _code_status(monkeypatch, zustand, text="", aufrufe=None):
    def status(aufruf=None):
        if aufrufe is not None:
            aufrufe.append("status")
        return me.Status(zustand, text or zustand)
    monkeypatch.setattr(me, "claude_code_status", status)


def test_gruppe_im_reiter_suche_mit_dienst_und_werkzeugen(qtbot, monkeypatch, tmp_path):
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    titel = [g.title() for g in dlg.findChildren(QGroupBox)]
    assert "KI-Assistenten (MCP)" in titel
    assert dlg.mcp_dienst_edit.text() == GEBAUT.programm and dlg.mcp_dienst_edit.isReadOnly()
    assert dlg.mcp_tools_label.text() == ", ".join(me.werkzeug_namen(False))
    assert "fragt vor jeder Aktion" in dlg.mcp_hint_label.text()
    dlg.mcp_dienst_copy_button.click()
    assert QApplication.clipboard().text() == GEBAUT.programm


def test_sql_schalter_ist_derselbe_wie_im_chat(qtbot, monkeypatch, tmp_path):
    dlg, cfg = _dialog(qtbot, monkeypatch, tmp_path)
    assert not dlg.mcp_sql_check.isChecked() and not dlg.chat_sql_check.isChecked()
    dlg.mcp_sql_check.setChecked(True)
    assert dlg.chat_sql_check.isChecked() and "sql_abfrage" in dlg.mcp_tools_label.text()
    dlg.chat_sql_check.setChecked(False)
    assert not dlg.mcp_sql_check.isChecked() and "sql_abfrage" not in dlg.mcp_tools_label.text()
    # bleibt bedienbar, auch wenn die Werkzeuge im Chat aus sind
    dlg.chat_tools_check.setChecked(False)
    assert dlg.mcp_sql_check.isEnabled()
    dlg.mcp_sql_check.setChecked(True)
    dlg._save_settings()
    assert cfg.get_chat_config().sql_erlaubt is True
    assert "Chat" in dlg.mcp_sql_check.toolTip()


def test_sql_schalter_laedt_gespeicherten_wert(qtbot, monkeypatch, tmp_path):
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path, chat={"sql_erlaubt": True})
    assert dlg.mcp_sql_check.isChecked() and "sql_abfrage" in dlg.mcp_tools_label.text()


def test_status_erst_im_reiter_suche_und_im_hintergrund(qtbot, monkeypatch, tmp_path):
    aufrufe = []
    _code_status(monkeypatch, me.INSTALLIERT, "installiert, „pdfsuche“ noch nicht eingerichtet", aufrufe)
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    assert aufrufe == []                                   # beim Oeffnen noch nicht
    assert dlg.show_tab("Suche")
    qtbot.waitUntil(lambda: "noch nicht eingerichtet" in dlg.mcp_code_status_label.text(), timeout=3000)
    assert dlg.mcp_code_button.isEnabled() and dlg.mcp_code_button.text() == "Einrichten"
    assert "nicht gefunden" in dlg.mcp_desktop_status_label.text()   # conftest: kein Claude Desktop
    assert not dlg.mcp_desktop_write_button.isEnabled() and dlg.mcp_desktop_copy_button.isEnabled()
    dlg.show_tab("Allgemein")
    dlg.show_tab("Suche")
    assert aufrufe == ["status"]                           # nur einmal


def test_claude_code_nicht_gefunden_sperrt_einrichten(qtbot, monkeypatch, tmp_path):
    _code_status(monkeypatch, me.NICHT_GEFUNDEN, "nicht gefunden")
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    dlg.show_tab("Suche")
    qtbot.waitUntil(lambda: "nicht gefunden" in dlg.mcp_code_status_label.text(), timeout=3000)
    assert not dlg.mcp_code_button.isEnabled()


def test_claude_code_einrichten_mit_rueckfrage(qtbot, monkeypatch, tmp_path, umgebung):
    _code_status(monkeypatch, me.INSTALLIERT)
    aufrufe = []

    def einrichten(ersetzen=False, aufruf=None):
        aufrufe.append(ersetzen)
        _code_status(monkeypatch, me.EINGERICHTET, "eingerichtet")
        return "Claude Code: „pdfsuche“ ist eingerichtet."

    monkeypatch.setattr(me, "claude_code_einrichten", einrichten)
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    dlg.show_tab("Suche")
    qtbot.waitUntil(lambda: dlg.mcp_code_button.isEnabled(), timeout=3000)

    umgebung["antwort"] = QMessageBox.StandardButton.No
    dlg.mcp_code_button.click()
    assert aufrufe == [] and GEBAUT.programm in umgebung["fragen"][0]   # Befehl steht in der Rueckfrage

    umgebung["antwort"] = QMessageBox.StandardButton.Yes
    dlg.mcp_code_button.click()
    qtbot.waitUntil(lambda: bool(umgebung["meldungen"]), timeout=3000)
    assert aufrufe == [False]
    assert umgebung["meldungen"] == [("info", "Claude Code: „pdfsuche“ ist eingerichtet.")]
    qtbot.waitUntil(lambda: dlg.mcp_code_status_label.text().endswith("eingerichtet"), timeout=3000)
    assert dlg.mcp_code_button.text() == "Neu einrichten"


def test_claude_code_neu_einrichten_ersetzt_und_zeigt_fehler(qtbot, monkeypatch, tmp_path, umgebung):
    _code_status(monkeypatch, me.ANDERER_PFAD, r"eingerichtet, startet aber D:\alt.exe")
    aufrufe = []

    def einrichten(ersetzen=False, aufruf=None):
        aufrufe.append(ersetzen)
        return "Fehler: Claude Code hat „pdfsuche“ nicht eingerichtet."

    monkeypatch.setattr(me, "claude_code_einrichten", einrichten)
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    dlg.show_tab("Suche")
    qtbot.waitUntil(lambda: dlg.mcp_code_button.text() == "Neu einrichten", timeout=3000)
    dlg.mcp_code_button.click()
    qtbot.waitUntil(lambda: bool(umgebung["meldungen"]), timeout=3000)
    assert aufrufe == [True] and "ersetzt" in umgebung["fragen"][0]
    assert umgebung["meldungen"][0][0] == "warnung"


def test_desktop_eintrag_kopieren_ist_gueltiges_json(qtbot, monkeypatch, tmp_path):
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    dlg.mcp_desktop_copy_button.click()
    daten = json.loads(QApplication.clipboard().text())
    assert daten == {"mcpServers": {"pdfsuche": {"command": GEBAUT.programm, "args": ["mcp"]}}}


def test_desktop_in_konfiguration_eintragen(qtbot, monkeypatch, tmp_path, umgebung):
    _code_status(monkeypatch, me.NICHT_GEFUNDEN)
    datei = tmp_path / "Claude" / me.KONFIG_NAME
    datei.parent.mkdir()
    datei.write_text(json.dumps({"preferences": {"x": 1}}), encoding="utf-8")
    monkeypatch.setattr(me, "claude_desktop_konfig", lambda *a, **k: datei)
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    dlg.show_tab("Suche")
    assert "noch nicht eingetragen" in dlg.mcp_desktop_status_label.text()
    assert dlg.mcp_desktop_write_button.isEnabled()

    umgebung["antwort"] = QMessageBox.StandardButton.No
    dlg.mcp_desktop_write_button.click()
    assert str(datei) in umgebung["fragen"][0] and "pdfsuche" not in datei.read_text(encoding="utf-8")

    umgebung["antwort"] = QMessageBox.StandardButton.Yes
    dlg.mcp_desktop_write_button.click()
    daten = json.loads(datei.read_text(encoding="utf-8"))
    assert daten["preferences"] == {"x": 1}
    assert daten["mcpServers"]["pdfsuche"] == {"command": GEBAUT.programm, "args": ["mcp"]}
    art, text = umgebung["meldungen"][-1]
    assert art == "info" and "neu starten" in text
    assert dlg.mcp_desktop_status_label.text().endswith("eingerichtet")


def test_desktop_defekte_konfiguration(qtbot, monkeypatch, tmp_path):
    _code_status(monkeypatch, me.NICHT_GEFUNDEN)
    datei = tmp_path / me.KONFIG_NAME
    datei.write_text("{ kaputt", encoding="utf-8")
    monkeypatch.setattr(me, "claude_desktop_konfig", lambda *a, **k: datei)
    dlg, _ = _dialog(qtbot, monkeypatch, tmp_path)
    dlg.show_tab("Suche")
    assert "nicht lesbar" in dlg.mcp_desktop_status_label.text()
    assert not dlg.mcp_desktop_write_button.isEnabled()

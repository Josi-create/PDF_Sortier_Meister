"""Einrichtung des MCP-Servers in Claude Code und Claude Desktop (Baustein 3, docs/CHAT_MCP_PLAN.md).

Qt-frei. ``shutil.which``, ``subprocess.run``, ``sys.frozen`` und die Orte der
Konfiguration sind gepatcht bzw. zeigen in ``tmp_path``; kein Test startet das echte
``claude`` oder liest die echte ``claude_desktop_config.json``.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import helfer_suche as h
import pytest

from src.search import mcp_einrichtung as me

# tests/conftest.py ersetzt beide fuer alle Tests; hier werden sie gezielt gebraucht
ECHTES_CLAUDE_PROGRAMM = me.claude_programm
ECHTE_DESKTOP_KONFIG = me.claude_desktop_konfig

GEBAUT = me.DienstAufruf(r"C:\Programme\PDFSM\pdfsm-dienst.exe", ("mcp",))
JETZT = datetime(2026, 11, 9, 14, 30, 5)


@pytest.fixture
def claude(monkeypatch, tmp_path):
    """``claude`` im Suchpfad; ``subprocess.run`` antwortet aus ``antworten`` und merkt die Aufrufe."""
    programm = str(tmp_path / "bin" / "claude.cmd")
    monkeypatch.setattr(me, "claude_programm", ECHTES_CLAUDE_PROGRAMM)
    monkeypatch.setattr(me.shutil, "which", lambda name: programm if name == "claude" else None)
    zustand = {"aufrufe": [], "antworten": {}, "kwargs": []}

    def run(args, **kwargs):
        zustand["aufrufe"].append(list(args))
        zustand["kwargs"].append(kwargs)
        antwort = zustand["antworten"].get(tuple(args[1:3]), (0, "", ""))
        if isinstance(antwort, BaseException):
            raise antwort
        rc, out, err = antwort
        return subprocess.CompletedProcess(args, rc, out, err)

    monkeypatch.setattr(me.subprocess, "run", run)
    zustand["programm"] = programm
    return zustand


def _get_ausgabe(command: str, args: str = "mcp", status: str = "✔ Connected") -> str:
    return (f"pdfsuche:\n  Scope: User config (available in all your projects)\n  Status: {status}\n"
            f"  Type: stdio\n  Command: {command}\n  Args: {args}\n  Environment:\n\n"
            "To remove this server, run: claude mcp remove pdfsuche -s user\n")


# --------------------------------------------------------------------------- Dienstpfad


def test_dienst_gebaut_liegt_neben_dem_programm(monkeypatch, tmp_path):
    exe = tmp_path / "PDFSM" / ("PDF_Sortier_Meister.exe" if sys.platform == "win32" else "PDF_Sortier_Meister")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    aufruf = me.dienst_aufruf()
    name = "pdfsm-dienst.exe" if sys.platform == "win32" else "pdfsm-dienst"
    assert aufruf == me.DienstAufruf(str(exe.with_name(name)), ("mcp",), {}, True)
    assert me.dienst_pfad() == exe.with_name(name)


def test_dienst_in_entwicklung_ueber_einstiegsskript_mit_pythonpath(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    aufruf = me.dienst_aufruf()
    wurzel = Path(__file__).resolve().parents[1]
    assert aufruf.programm == sys.executable and not aufruf.gebaut
    assert aufruf.argumente == (str(wurzel / "packaging" / "pdfsm_dienst.py"), "mcp")
    assert aufruf.umgebung == {"PYTHONPATH": str(wurzel)}
    assert Path(aufruf.argumente[0]).is_file()
    pfad = me.dienst_pfad()
    assert isinstance(pfad, str) and "pdfsm_dienst.py" in pfad and pfad.endswith("mcp")


def test_befehlszeile_setzt_pfade_mit_leerzeichen_in_anfuehrungszeichen():
    aufruf = me.DienstAufruf(str(Path("/Programme/PDF Sortier Meister/pdfsm-dienst")), ("mcp",))
    zeile = aufruf.befehlszeile()
    assert zeile.endswith(" mcp") and ('"' in zeile or "'" in zeile)


def test_werkzeugliste_stimmt_mit_dem_server_ueberein(tmp_path):
    pytest.importorskip("mcp")
    from src.search import mcp_server
    from src.search.mcp_server import Umgebung

    konfig = h.konfig_fuer(tmp_path)
    for sql in (False, True):
        server = mcp_server.erstelle_server(konfig, Umgebung(sql_erlaubt=sql))
        namen = [t.name for t in asyncio.run(server.list_tools())]
        assert sorted(namen) == sorted(me.werkzeug_namen(sql))
    assert "sql_abfrage" not in me.werkzeug_namen(False)


# --------------------------------------------------------------------------- Claude Code


def test_claude_code_befehl_als_argumentliste():
    assert me.claude_code_befehl(GEBAUT) == ["claude", "mcp", "add", "pdfsuche", "--scope", "user", "--",
                                             GEBAUT.programm, "mcp"]
    entwicklung = me.DienstAufruf("python", ("pdfsm_dienst.py", "mcp"), {"PYTHONPATH": "/src"}, False)
    assert me.claude_code_befehl(entwicklung, "/bin/claude") == [
        "/bin/claude", "mcp", "add", "pdfsuche", "--scope", "user", "-e", "PYTHONPATH=/src", "--",
        "python", "pdfsm_dienst.py", "mcp"]


def test_claude_code_nicht_gefunden(monkeypatch):
    monkeypatch.setattr(me, "claude_programm", ECHTES_CLAUDE_PROGRAMM)
    monkeypatch.setattr(me.shutil, "which", lambda name: None)
    assert me.claude_code_status(GEBAUT).zustand == me.NICHT_GEFUNDEN
    assert me.claude_code_einrichten(aufruf=GEBAUT).startswith("Fehler")


def test_claude_code_installiert_ohne_eintrag(claude):
    claude["antworten"][("mcp", "get")] = (1, "", 'No MCP server named "pdfsuche".')
    status = me.claude_code_status(GEBAUT)
    assert status.zustand == me.INSTALLIERT
    assert claude["aufrufe"] == [[claude["programm"], "mcp", "get", "pdfsuche"]]
    # ohne Konsolenfenster und ohne Eingabe (sonst wartete claude ewig)
    assert claude["kwargs"][0]["stdin"] is subprocess.DEVNULL and claude["kwargs"][0]["timeout"] > 0


def test_claude_code_eingerichtet_und_anderer_pfad(claude):
    claude["antworten"][("mcp", "get")] = (0, _get_ausgabe(GEBAUT.programm.lower()), "")
    assert me.claude_code_status(GEBAUT).zustand == me.EINGERICHTET
    claude["antworten"][("mcp", "get")] = (0, _get_ausgabe(r"D:\Alt\pdfsm-dienst.exe"), "")
    status = me.claude_code_status(GEBAUT)
    assert status.zustand == me.ANDERER_PFAD and r"D:\Alt\pdfsm-dienst.exe" in status.text
    claude["antworten"][("mcp", "get")] = (0, _get_ausgabe(GEBAUT.programm, status="✘ Failed to connect"), "")
    status = me.claude_code_status(GEBAUT)
    assert status.zustand == me.EINGERICHTET and "Failed to connect" in status.text


def test_claude_code_status_haengt_oder_startet_nicht(claude):
    claude["antworten"][("mcp", "get")] = subprocess.TimeoutExpired("claude", 60)
    assert me.claude_code_status(GEBAUT).zustand == me.FEHLER
    claude["antworten"][("mcp", "get")] = OSError("Zugriff verweigert")
    status = me.claude_code_status(GEBAUT)
    assert status.zustand == me.FEHLER and "Zugriff verweigert" in status.text


def test_claude_code_einrichten(claude):
    text = me.claude_code_einrichten(aufruf=GEBAUT)
    assert not text.startswith("Fehler") and "eingerichtet" in text
    assert claude["aufrufe"] == [me.claude_code_befehl(GEBAUT, claude["programm"])]


def test_claude_code_ersetzen_entfernt_vorher(claude):
    me.claude_code_einrichten(ersetzen=True, aufruf=GEBAUT)
    assert claude["aufrufe"][0] == [claude["programm"], "mcp", "remove", "pdfsuche", "-s", "user"]
    assert claude["aufrufe"][1][1:3] == ["mcp", "add"]


def test_claude_code_einrichten_fehlertext(claude):
    claude["antworten"][("mcp", "add")] = (1, "", "MCP server pdfsuche already exists in user config")
    text = me.claude_code_einrichten(aufruf=GEBAUT)
    assert text.startswith("Fehler") and "already exists" in text
    claude["antworten"][("mcp", "add")] = subprocess.TimeoutExpired("claude", 60)
    assert me.claude_code_einrichten(aufruf=GEBAUT).startswith("Fehler")


# --------------------------------------------------------------------------- Claude Desktop: Orte


def test_konfigurationsorte_macos(tmp_path):
    assert me.claude_desktop_kandidaten("darwin", {}, tmp_path) == [
        tmp_path / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"]
    assert me.claude_desktop_kandidaten("linux", {}, tmp_path) == []


def test_konfigurationsorte_windows_store_und_klassisch(tmp_path):
    lokal, roaming = tmp_path / "Local", tmp_path / "Roaming"
    neu = lokal / "Claude-Data" / "claude_pzs8sxrjxfjjc"
    neu.mkdir(parents=True)
    alt = lokal / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude"
    alt.mkdir(parents=True)
    env = {"LOCALAPPDATA": str(lokal), "APPDATA": str(roaming)}
    name = "claude_desktop_config.json"
    assert me.claude_desktop_kandidaten("win32", env, tmp_path) == [
        neu / name, alt / name, roaming / "Claude" / name]
    # Store-Fassung, deren Daten umgezogen sind: Paketordner nur noch mit Markierung
    (alt / ".user-data-left.claude_pzs8sxrjxfjjc").write_text("")
    assert alt / name not in me.claude_desktop_kandidaten("win32", env, tmp_path)


def test_konfiguration_finden(monkeypatch, tmp_path):
    monkeypatch.setattr(me, "claude_desktop_konfig", ECHTE_DESKTOP_KONFIG)
    lokal, roaming = tmp_path / "Local", tmp_path / "Roaming"
    env = {"LOCALAPPDATA": str(lokal), "APPDATA": str(roaming)}
    assert me.claude_desktop_konfig("win32", env, tmp_path) is None            # nicht installiert
    (roaming / "Claude").mkdir(parents=True)
    assert me.claude_desktop_konfig("win32", env, tmp_path) == roaming / "Claude" / me.KONFIG_NAME
    neu = lokal / "Claude-Data" / "claude_x"
    neu.mkdir(parents=True)
    assert me.claude_desktop_konfig("win32", env, tmp_path) == neu / me.KONFIG_NAME   # Ordner, vorn
    (roaming / "Claude" / me.KONFIG_NAME).write_text("{}")
    assert me.claude_desktop_konfig("win32", env, tmp_path) == roaming / "Claude" / me.KONFIG_NAME  # Datei siegt


# --------------------------------------------------------------------------- Claude Desktop: Status


def test_desktop_status(tmp_path):
    datei = tmp_path / "Claude" / me.KONFIG_NAME
    assert me.claude_desktop_status(None, GEBAUT).zustand == me.NICHT_GEFUNDEN   # conftest: nicht gefunden
    assert me.claude_desktop_status(datei, GEBAUT).zustand == me.INSTALLIERT     # Datei fehlt noch
    datei.parent.mkdir()
    datei.write_text(json.dumps({"mcpServers": {"andere": {"command": "x"}}}), encoding="utf-8")
    status = me.claude_desktop_status(datei, GEBAUT)
    assert status.zustand == me.INSTALLIERT and status.pfad == datei
    datei.write_text(json.dumps({"mcpServers": {"pdfsuche": me.claude_desktop_eintrag(GEBAUT)}}), encoding="utf-8")
    assert me.claude_desktop_status(datei, GEBAUT).zustand == me.EINGERICHTET
    datei.write_text(json.dumps({"mcpServers": {"pdfsuche": {"command": "D:/alt.exe", "args": ["mcp"]}}}))
    status = me.claude_desktop_status(datei, GEBAUT)
    assert status.zustand == me.ANDERER_PFAD and "D:/alt.exe" in status.text
    datei.write_text("{ kaputt", encoding="utf-8")
    status = me.claude_desktop_status(datei, GEBAUT)
    assert status.zustand == me.FEHLER and "kein gültiges JSON" in status.text


def test_desktop_eintrag_und_json_zum_kopieren():
    assert me.claude_desktop_eintrag(GEBAUT) == {"command": GEBAUT.programm, "args": ["mcp"]}
    entwicklung = me.DienstAufruf("python", ("pdfsm_dienst.py", "mcp"), {"PYTHONPATH": "/src"}, False)
    assert me.claude_desktop_eintrag(entwicklung)["env"] == {"PYTHONPATH": "/src"}
    daten = json.loads(me.claude_desktop_eintrag_json(GEBAUT))
    assert daten == {"mcpServers": {"pdfsuche": {"command": GEBAUT.programm, "args": ["mcp"]}}}


# --------------------------------------------------------------------------- Claude Desktop: Eintragen


def test_eintragen_in_neue_datei(tmp_path):
    datei = tmp_path / "Claude" / me.KONFIG_NAME
    text = me.claude_desktop_eintragen(datei, GEBAUT, JETZT)
    assert not text.startswith("Fehler") and "neu starten" in text
    assert json.loads(datei.read_text(encoding="utf-8")) == {
        "mcpServers": {"pdfsuche": {"command": GEBAUT.programm, "args": ["mcp"]}}}
    assert list(datei.parent.glob("*.bak-*")) == []   # nichts zu sichern


def test_eintragen_in_leere_datei(tmp_path):
    datei = tmp_path / me.KONFIG_NAME
    datei.write_text("", encoding="utf-8")
    me.claude_desktop_eintragen(datei, GEBAUT, JETZT)
    assert json.loads(datei.read_text(encoding="utf-8"))["mcpServers"]["pdfsuche"]["args"] == ["mcp"]


def test_eintragen_behaelt_andere_server_und_einstellungen_und_sichert(tmp_path):
    datei = tmp_path / me.KONFIG_NAME
    vorher = {"coworkUserFilesPath": "C:\\Users\\x\\Claude", "preferences": {"sidebarMode": "chat", "ä": "ö"},
              "mcpServers": {"andere": {"command": "node", "args": ["server.js"], "env": {"TOKEN": "geheim"}},
                             "pdfsuche": {"command": "D:\\alt\\pdfsm-dienst.exe", "args": ["mcp"]}}}
    roh = json.dumps(vorher, indent=2, ensure_ascii=False)
    datei.write_text(roh, encoding="utf-8")
    text = me.claude_desktop_eintragen(datei, GEBAUT, JETZT)
    nachher = json.loads(datei.read_text(encoding="utf-8"))
    assert nachher["mcpServers"]["pdfsuche"] == {"command": GEBAUT.programm, "args": ["mcp"]}
    assert nachher["mcpServers"]["andere"] == vorher["mcpServers"]["andere"]
    assert {k: v for k, v in nachher.items() if k != "mcpServers"} == {
        k: v for k, v in vorher.items() if k != "mcpServers"}
    sicherung = tmp_path / f"{me.KONFIG_NAME}.bak-20261109-143005"
    assert sicherung.read_text(encoding="utf-8") == roh and sicherung.name in text
    # zweite Sicherung in derselben Sekunde ueberschreibt die erste nicht
    datei.write_text(roh, encoding="utf-8")
    me.claude_desktop_eintragen(datei, GEBAUT, JETZT)
    assert sicherung.read_text(encoding="utf-8") == roh
    assert (tmp_path / f"{me.KONFIG_NAME}.bak-20261109-143005-1").is_file()
    assert not list(tmp_path.glob("*.neu"))


def test_eintragen_mit_bom_und_ohne_mcpservers(tmp_path):
    datei = tmp_path / me.KONFIG_NAME
    datei.write_bytes(b"\xef\xbb\xbf" + json.dumps({"preferences": {}}).encode("utf-8"))
    me.claude_desktop_eintragen(datei, GEBAUT, JETZT)
    daten = json.loads(datei.read_text(encoding="utf-8"))
    assert daten["preferences"] == {} and "pdfsuche" in daten["mcpServers"]


def test_bereits_eingetragen_schreibt_nichts(tmp_path):
    datei = tmp_path / me.KONFIG_NAME
    me.claude_desktop_eintragen(datei, GEBAUT, JETZT)
    vorher = datei.stat().st_mtime_ns
    text = me.claude_desktop_eintragen(datei, GEBAUT, JETZT)
    assert "bereits" in text and datei.stat().st_mtime_ns == vorher
    assert list(tmp_path.glob("*.bak-*")) == []


@pytest.mark.parametrize("inhalt", ["{ kaputt", "[1, 2]", '{"mcpServers": []}'])
def test_defekte_konfiguration_bleibt_unberuehrt(tmp_path, inhalt):
    datei = tmp_path / me.KONFIG_NAME
    datei.write_text(inhalt, encoding="utf-8")
    text = me.claude_desktop_eintragen(datei, GEBAUT, JETZT)
    assert text.startswith("Fehler") and "Nichts geändert" in text
    assert datei.read_text(encoding="utf-8") == inhalt
    assert list(tmp_path.glob("*.bak-*")) == []


def test_schreibfehler_wird_fehlertext(monkeypatch, tmp_path):
    datei = tmp_path / me.KONFIG_NAME

    def verweigert(*args, **kwargs):
        raise PermissionError("Zugriff verweigert")

    monkeypatch.setattr(me.os, "replace", verweigert)
    text = me.claude_desktop_eintragen(datei, GEBAUT, JETZT)
    assert text.startswith("Fehler") and "Zugriff verweigert" in text
    assert not datei.exists() and not list(tmp_path.glob("*.neu"))   # keine halbe Datei zurueck


def test_conftest_sperrt_echte_clients():
    """Ohne eigenes Patchen sieht kein Test das echte Claude Code oder Claude Desktop."""
    assert me.claude_programm() is None and me.claude_desktop_konfig() is None
    assert me.claude_code_status().zustand == me.NICHT_GEFUNDEN
    assert me.claude_desktop_status().zustand == me.NICHT_GEFUNDEN


def test_laedt_ohne_qt():
    """Qt-frei wie src/search: die Einstellungen nutzen das Modul, der Dienst koennte es auch."""
    code = ("import sys; import src.search.mcp_einrichtung; "
            "geladen = sorted(m for m in sys.modules if m.startswith(('PyQt6', 'sqlalchemy', 'src.gui'))); "
            "assert not geladen, geladen; print('ok')")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(Path(__file__).resolve().parents[1]),
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "ok"

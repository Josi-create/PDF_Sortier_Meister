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
    claude["antworten"][("mcp", "get")] = (0, _get_ausgabe(GEBAUT.programm), "")
    assert me.claude_code_status(GEBAUT).zustand == me.EINGERICHTET
    if sys.platform == "win32":   # nur Windows ignoriert Gross-/Kleinschreibung in Pfaden
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


# --------------------------------------------------------------------------- Hermes Agent (#417)

ECHTES_HERMES_PROGRAMM = me.hermes_programm


@pytest.fixture
def hermes(monkeypatch, tmp_path):
    """Ein nachgebautes ``hermes``: ``config path``, ``config get`` und ``mcp add`` wie Hermes Agent
    v0.22 (hermes_cli/mcp_config.py): Rueckfrage zum Ueberschreiben (Vorgabe nein), Probe, Frage
    „Enable all tools?“ (Vorgabe ja), danach „Saved 'name' to …“. Die Datei ``config.yaml`` gehoert
    Hermes; der Nachbau aendert sie nur ueber ``server`` und haengt eine Zeile an."""
    programm = str(tmp_path / "bin" / "hermes.exe")
    konfig = tmp_path / "hermes" / "config.yaml"
    konfig.parent.mkdir()
    konfig.write_text("# Kommentar des Nutzers\nmcp_servers:\n  andere:\n    command: x\n", encoding="utf-8")
    monkeypatch.setattr(me, "hermes_programm", ECHTES_HERMES_PROGRAMM)
    monkeypatch.setattr(me.shutil, "which", lambda name: programm if name == "hermes" else None)
    zustand = {"aufrufe": [], "eingaben": [], "server": {"andere": {"command": "x"}}, "probe_ok": True,
               "konfig": konfig, "programm": programm, "antworten": {}}

    def run(args, **kwargs):
        args = list(args)
        zustand["aufrufe"].append(args)
        zustand["eingaben"].append(kwargs.get("input"))
        if tuple(args[1:3]) in zustand["antworten"]:
            antwort = zustand["antworten"][tuple(args[1:3])]
            if isinstance(antwort, BaseException):
                raise antwort
            return subprocess.CompletedProcess(args, *antwort)
        if args[1:3] == ["config", "path"]:
            return subprocess.CompletedProcess(args, 0, f"{konfig}\n", "")
        if args[1:3] == ["config", "get"]:
            name = args[3].split(".", 1)[1]
            if name not in zustand["server"]:
                return subprocess.CompletedProcess(args, 1, f"Config key not set: {args[3]}\n", "")
            return subprocess.CompletedProcess(args, 0, json.dumps(zustand["server"][name]) + "\n", "")
        assert args[1:3] == ["mcp", "add"]
        antworten = iter((kwargs.get("input") or "").splitlines())
        name = args[3]
        eintrag = {"command": args[args.index("--command") + 1]}
        if "--args" in args:
            eintrag["args"] = args[args.index("--args") + 1:]
        if "--env" in args:
            eintrag["env"] = dict(a.split("=", 1) for a in args[args.index("--env") + 1:args.index("--args")])
        if name in zustand["server"] and next(antworten, "").strip().lower() not in ("y", "yes"):
            return subprocess.CompletedProcess(args, 0, "  Cancelled.\n", "")
        if not zustand["probe_ok"]:
            if next(antworten, "").strip().lower() in ("y", "yes"):
                zustand["server"][name] = {**eintrag, "enabled": False}
            return subprocess.CompletedProcess(args, 0, "  Failed to connect: boom\n", "")
        if next(antworten, "").strip().lower() in ("n", "no"):
            return subprocess.CompletedProcess(args, 0, "  Cancelled - server not saved.\n", "")
        zustand["server"][name] = {**eintrag, "enabled": True}
        with konfig.open("a", encoding="utf-8") as f:
            f.write(f"  {name}:\n    command: {eintrag['command']}\n")
        return subprocess.CompletedProcess(args, 0, f"  Saved '{name}' to {konfig.parent}/config.yaml\n", "")

    monkeypatch.setattr(me.subprocess, "run", run)
    return zustand


def test_hermes_befehl_als_argumentliste():
    assert me.hermes_befehl(GEBAUT) == ["hermes", "mcp", "add", "pdfsuche", "--command", GEBAUT.programm,
                                        "--args", "mcp"]
    entwicklung = me.DienstAufruf("python", ("pdfsm_dienst.py", "mcp"), {"PYTHONPATH": "/src"}, False)
    assert me.hermes_befehl(entwicklung, "/bin/hermes") == [
        "/bin/hermes", "mcp", "add", "pdfsuche", "--command", "python", "--env", "PYTHONPATH=/src",
        "--args", "pdfsm_dienst.py", "mcp"]


def test_hermes_orte_ausserhalb_des_suchpfads(tmp_path):
    assert me.hermes_kandidaten("win32", {"LOCALAPPDATA": str(tmp_path / "Lokal")}, tmp_path) == [
        tmp_path / "Lokal" / "hermes" / "bin" / "hermes.exe"]
    assert me.hermes_kandidaten("darwin", {}, tmp_path) == [tmp_path / ".local" / "bin" / "hermes"]


def test_hermes_nicht_gefunden_sperrt(monkeypatch, tmp_path):
    monkeypatch.setattr(me, "hermes_programm", ECHTES_HERMES_PROGRAMM)
    monkeypatch.setattr(me.shutil, "which", lambda name: None)
    monkeypatch.setattr(me, "hermes_kandidaten", lambda: [tmp_path / "fehlt" / "hermes.exe"])
    assert me.hermes_status(GEBAUT).zustand == me.NICHT_GEFUNDEN
    assert me.hermes_einrichten(aufruf=GEBAUT).startswith("Fehler")


def test_hermes_ausserhalb_des_suchpfads_gefunden(monkeypatch, tmp_path):
    exe = tmp_path / "hermes" / "bin" / "hermes.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setattr(me, "hermes_programm", ECHTES_HERMES_PROGRAMM)
    monkeypatch.setattr(me.shutil, "which", lambda name: None)
    monkeypatch.setattr(me, "hermes_kandidaten", lambda: [exe])
    assert me.hermes_programm() == str(exe)


def test_hermes_status(hermes):
    status = me.hermes_status(GEBAUT)
    assert status.zustand == me.INSTALLIERT
    assert hermes["aufrufe"] == [[hermes["programm"], "config", "get", "mcp_servers.pdfsuche", "--json"]]
    assert hermes["eingaben"] == [None]          # liest nichts von stdin
    hermes["server"]["pdfsuche"] = {"command": GEBAUT.programm, "args": ["mcp"], "enabled": True}
    assert me.hermes_status(GEBAUT).zustand == me.EINGERICHTET
    hermes["server"]["pdfsuche"] = {"command": r"D:\Alt\pdfsm-dienst.exe", "args": ["mcp"]}
    status = me.hermes_status(GEBAUT)
    assert status.zustand == me.ANDERER_PFAD and r"D:\Alt" in status.text
    hermes["server"]["pdfsuche"] = {"command": GEBAUT.programm, "args": ["mcp"], "enabled": False}
    status = me.hermes_status(GEBAUT)
    assert status.zustand == me.ANDERER_PFAD and "ausgeschaltet" in status.text


def test_hermes_status_mit_hinweiszeile_vor_dem_json(hermes):
    eintrag = {"command": GEBAUT.programm, "args": ["mcp"], "enabled": True}
    hermes["antworten"][("config", "get")] = (0, "Hinweis: irgendwas\n" + json.dumps(eintrag), "")
    assert me.hermes_status(GEBAUT).zustand == me.EINGERICHTET


def test_hermes_status_fehler(hermes):
    hermes["antworten"][("config", "get")] = (1, "", "config.yaml is not valid YAML")
    status = me.hermes_status(GEBAUT)
    assert status.zustand == me.FEHLER and "not valid YAML" in status.text
    hermes["antworten"][("config", "get")] = subprocess.TimeoutExpired("hermes", 120)
    assert me.hermes_status(GEBAUT).zustand == me.FEHLER


def test_hermes_einrichten_sichert_und_traegt_ein(hermes):
    vorher = hermes["konfig"].read_text(encoding="utf-8")
    text = me.hermes_einrichten(aufruf=GEBAUT, jetzt=JETZT)
    assert not text.startswith("Fehler") and "/reload-mcp" in text
    assert hermes["server"]["pdfsuche"] == {"command": GEBAUT.programm, "args": ["mcp"], "enabled": True}
    assert hermes["server"]["andere"] == {"command": "x"}                     # anderer Server unveraendert
    sicherung = hermes["konfig"].with_name("config.yaml.bak-20261109-143005")
    assert sicherung.read_text(encoding="utf-8") == vorher and sicherung.name in text
    add = [a for a in hermes["aufrufe"] if a[1:3] == ["mcp", "add"]]
    assert add == [me.hermes_befehl(GEBAUT, hermes["programm"])]
    eingabe = hermes["eingaben"][hermes["aufrufe"].index(add[0])]
    assert eingabe == me.HERMES_EINGABE_NEU                                    # nur Vorgaben (Enter)


def test_hermes_zweiter_klick_traegt_nichts_doppelt_ein(hermes):
    me.hermes_einrichten(aufruf=GEBAUT, jetzt=JETZT)
    text = me.hermes_einrichten(ersetzen=True, aufruf=GEBAUT, jetzt=JETZT)
    assert not text.startswith("Fehler")
    assert list(hermes["server"]) == ["andere", "pdfsuche"]
    assert me.HERMES_EINGABE_ERSETZEN in hermes["eingaben"]                   # „Overwrite?“ mit ja


def test_hermes_einrichten_ohne_ersetzen_bei_vorhandenem_eintrag_ist_fehler(hermes):
    hermes["server"]["pdfsuche"] = {"command": r"D:\Alt\pdfsm-dienst.exe", "args": ["mcp"]}
    text = me.hermes_einrichten(aufruf=GEBAUT, jetzt=JETZT)                   # Hermes fragt, Vorgabe nein
    assert text.startswith("Fehler") and "Cancelled" in text
    assert hermes["server"]["pdfsuche"]["command"] == r"D:\Alt\pdfsm-dienst.exe"


def test_hermes_probe_scheitert_speichert_nichts(hermes):
    hermes["probe_ok"] = False
    text = me.hermes_einrichten(aufruf=GEBAUT, jetzt=JETZT)
    assert text.startswith("Fehler") and "Failed to connect" in text
    assert "pdfsuche" not in hermes["server"]
    # beim Ersetzen bleibt der alte (passende) Eintrag, gemeldet wird trotzdem der Fehler
    hermes["server"]["pdfsuche"] = {"command": GEBAUT.programm, "args": ["mcp"], "enabled": True}
    assert me.hermes_einrichten(ersetzen=True, aufruf=GEBAUT, jetzt=JETZT).startswith("Fehler")


def test_hermes_ohne_konfigurationsdatei_kein_eintrag(hermes):
    hermes["antworten"][("config", "path")] = (1, "", "kaputt")
    text = me.hermes_einrichten(aufruf=GEBAUT, jetzt=JETZT)
    assert text.startswith("Fehler") and "Nichts geändert" in text
    assert not any(a[1:3] == ["mcp", "add"] for a in hermes["aufrufe"])


def test_hermes_neue_konfiguration_ohne_sicherung(hermes):
    hermes["konfig"].unlink()
    text = me.hermes_einrichten(aufruf=GEBAUT, jetzt=JETZT)
    assert not text.startswith("Fehler") and "Sicherungskopie" not in text


def test_conftest_sperrt_echtes_hermes():
    assert me.hermes_programm() is None
    assert me.hermes_status().zustand == me.NICHT_GEFUNDEN

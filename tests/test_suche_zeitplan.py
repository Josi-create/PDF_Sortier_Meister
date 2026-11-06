"""Zeitplan der Hintergrundindexierung und der Web-Oberflaeche (Phase 6, ``src/search/zeitplan.py``).

Das Betriebssystem ist ersetzt: Die Aufgabenplanung bekommt ein Imitat von
``schtasks``, das die XML-Definition speichert und wie Windows in der
OEM-Codepage zurueckgibt; die LaunchAgents schreiben nach ``tmp_path`` und
``launchctl`` ist ein Imitat. ``tests/conftest.py`` sperrt ausserdem jeden
echten Aufruf, damit kein Test eine Aufgabe auf dem Rechner anlegt. Dazu der
Unterbefehl ``pdfsm-dienst zeitplan`` und die Helfer fuer die Browser-Oberflaeche.
"""
from __future__ import annotations

import json
import plistlib
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from src.search import dienst, zeitplan
from src.search import suchindex as suchindex_modul
from src.search.suchindex import Suchindex
from src.utils.config import Config
from tests import helfer_suche as h

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
DIENST_WIN = ["C:\\Programme\\PDF Sortier Meister\\pdfsm-dienstw.exe"]
DIENST_MAC = ["/Applications/PDF Sortier Meister.app/Contents/MacOS/pdfsm-dienst"]


def _konfig(tmp_path, **kw):
    kw.setdefault("hintergrund_aktiv", True)
    return h.konfig_fuer(tmp_path, wurzeln=[str(tmp_path)], **kw)


def _ok(args, stdout=b""):
    return subprocess.CompletedProcess(args, 0, stdout, b"")


class SchtasksImitat:
    """Verhaelt sich wie ``schtasks`` fuer /Create /XML, /Query /XML, /Delete, /Run und /End."""

    def __init__(self):
        self.aufgaben: dict[str, str] = {}
        self.aufrufe: list[list[str]] = []
        self.fehler: str | None = None

    def befehle(self, befehl: str) -> list[str]:
        return [a[a.index("/TN") + 1] for a in self.aufrufe if a[0] == "schtasks" and a[1] == befehl]

    def __call__(self, args):
        self.aufrufe.append(list(args))
        if args[0] != "schtasks":
            return _ok(args)
        befehl, name = args[1], args[args.index("/TN") + 1]
        if befehl == "/Create":
            if self.fehler:
                return subprocess.CompletedProcess(args, 1, b"", self.fehler.encode("cp850"))
            self.aufgaben[name] = Path(args[args.index("/XML") + 1]).read_text(encoding="utf-16")
        elif befehl == "/Query":
            if name not in self.aufgaben:
                return subprocess.CompletedProcess(args, 1, b"", "FEHLER: Datei nicht gefunden.".encode("cp850"))
            return _ok(args, self.aufgaben[name].encode("cp850", "replace"))   # wie Windows: OEM-Codepage
        elif befehl == "/Delete":
            self.aufgaben.pop(name, None)
        return _ok(args)


def _xml(text: str) -> ET.Element:
    return ET.fromstring(text.split("?>", 1)[1])


def _wert(wurzel, pfad: str) -> str:
    return wurzel.find(pfad, NS).text


# --------------------------------------------------------------------------- Was die Einstellungen verlangen

def test_gewuenscht_folgt_den_einstellungen(tmp_path):
    assert zeitplan.gewuenscht(_konfig(tmp_path, hintergrund_aktiv=False), DIENST_WIN) == {"index": None, "web": None}
    assert zeitplan.gewuenscht(_konfig(tmp_path, aktiv=False, web_aktiv=True, web_bei_anmeldung=True),
                               DIENST_WIN) == {"index": None, "web": None}

    soll = zeitplan.gewuenscht(_konfig(tmp_path, hintergrund_uhrzeit="04:30"), DIENST_WIN, arbeitsordner="C:\\P")
    assert soll["web"] is None
    assert soll["index"] == zeitplan.Eintrag("index", DIENST_WIN[0], ("index", "--hintergrund"), "04:30", "C:\\P")
    mac = zeitplan.gewuenscht(_konfig(tmp_path), DIENST_MAC, leerlauf_selbst=True)["index"]
    assert mac.argumente == ("index", "--hintergrund", "--nur-leerlauf")

    # Web nur mit „einschalten“ UND „bei Anmeldung“; eine andere config.json geht als --config mit
    assert zeitplan.gewuenscht(_konfig(tmp_path, web_aktiv=True), DIENST_WIN)["web"] is None
    soll = zeitplan.gewuenscht(_konfig(tmp_path, hintergrund_aktiv=False, web_aktiv=True, web_bei_anmeldung=True),
                               ["python.exe", "-m", "src.search.dienst"], konfig_pfad="C:\\x\\config.json")
    assert soll["index"] is None
    assert soll["web"].argumente == ("-m", "src.search.dienst", "--config", "C:\\x\\config.json", "web",
                                     "--nicht-oeffnen")
    assert soll["web"].uhrzeit is None


def test_merkmale_und_etwas_gewuenscht(tmp_path):
    aus = _konfig(tmp_path, hintergrund_aktiv=False)
    assert not zeitplan.etwas_gewuenscht(aus)
    assert zeitplan.etwas_gewuenscht(_konfig(tmp_path))
    assert zeitplan.merkmale(aus) != zeitplan.merkmale(_konfig(tmp_path))
    assert zeitplan.merkmale(_konfig(tmp_path)) != zeitplan.merkmale(_konfig(tmp_path, hintergrund_uhrzeit="05:00"))


# --------------------------------------------------------------------------- Windows: Aufgabenplanung

def test_aufgabenplanung_wie_die_frueheren_aufgaben(tmp_path):
    imitat = SchtasksImitat()
    b = zeitplan.Aufgabenplanung(ausfuehren=imitat, benutzer="RECHNER\\nutzer")
    konfig = _konfig(tmp_path, hintergrund_uhrzeit="04:30", web_aktiv=True, web_bei_anmeldung=True)
    assert zeitplan.abgleichen(konfig, DIENST_WIN, b=b) == [
        "eingerichtet: \\PDF Sortier Meister\\Indexierung", "eingerichtet: \\PDF Sortier Meister\\Web-Oberflaeche"]

    index = _xml(imitat.aufgaben["\\PDF Sortier Meister\\Indexierung"])
    assert _wert(index, "t:Triggers/t:CalendarTrigger/t:StartBoundary").endswith("T04:30:00")
    assert _wert(index, "t:Triggers/t:CalendarTrigger/t:ScheduleByDay/t:DaysInterval") == "1"
    einst = "t:Settings/"
    assert _wert(index, einst + "t:RunOnlyIfIdle") == "true"
    assert _wert(index, einst + "t:IdleSettings/t:Duration") == "PT10M"
    assert _wert(index, einst + "t:IdleSettings/t:StopOnIdleEnd") == "true"     # Abbruch bei Aktivitaet
    assert _wert(index, einst + "t:IdleSettings/t:RestartOnIdle") == "true"     # Fortsetzung bei Leerlauf
    assert _wert(index, einst + "t:ExecutionTimeLimit") == "PT20H"
    assert _wert(index, einst + "t:MultipleInstancesPolicy") == "IgnoreNew"
    assert _wert(index, einst + "t:StartWhenAvailable") == "true"
    assert _wert(index, einst + "t:DisallowStartIfOnBatteries") == "false"
    assert _wert(index, einst + "t:Priority") == "7"
    assert _wert(index, "t:Principals/t:Principal/t:RunLevel") == "LeastPrivilege"   # ohne Adminrechte
    assert _wert(index, "t:Principals/t:Principal/t:LogonType") == "InteractiveToken"
    assert _wert(index, "t:Actions/t:Exec/t:Command") == DIENST_WIN[0]
    assert _wert(index, "t:Actions/t:Exec/t:Arguments") == "index --hintergrund"

    web = _xml(imitat.aufgaben["\\PDF Sortier Meister\\Web-Oberflaeche"])
    assert _wert(web, "t:Triggers/t:LogonTrigger/t:UserId") == "RECHNER\\nutzer"
    assert _wert(web, einst + "t:RunOnlyIfIdle") == "false"
    assert _wert(web, einst + "t:ExecutionTimeLimit") == "PT0S"
    assert _wert(web, "t:Actions/t:Exec/t:Arguments") == "web --nicht-oeffnen"
    assert imitat.befehle("/Run") == ["\\PDF Sortier Meister\\Web-Oberflaeche"]   # sofort, nicht erst bei Anmeldung

    # Unveraendert: nur abfragen, nichts neu anlegen
    imitat.aufrufe.clear()
    assert zeitplan.abgleichen(konfig, DIENST_WIN, b=b) == []
    assert imitat.befehle("/Create") == []

    z = zeitplan.zustand(b)
    assert z["index"]["uhrzeit"] == "04:30" and z["web"]["anmeldung"] and z["index"]["aktiviert"]
    text = zeitplan.zustand_text(z)
    assert "täglich um 04:30" in text and "bei der Anmeldung" in text and "Aufgabenplanung" in text


def test_aufgabenplanung_aendern_und_entfernen(tmp_path):
    imitat = SchtasksImitat()
    b = zeitplan.Aufgabenplanung(ausfuehren=imitat, benutzer="RECHNER\\nutzer")
    konfig = _konfig(tmp_path, web_aktiv=True, web_bei_anmeldung=True)
    zeitplan.abgleichen(konfig, DIENST_WIN, b=b)

    imitat.aufrufe.clear()
    konfig.hintergrund_uhrzeit = "22:15"
    zeitplan.abgleichen(konfig, DIENST_WIN, b=b)
    assert imitat.befehle("/Create") == ["\\PDF Sortier Meister\\Indexierung"]
    assert "T22:15:00" in imitat.aufgaben["\\PDF Sortier Meister\\Indexierung"]

    # In der Aufgabenplanung deaktiviert oder das Programm verschoben: wird neu eingerichtet
    name = "\\PDF Sortier Meister\\Indexierung"
    imitat.aufgaben[name] = imitat.aufgaben[name].replace("<Enabled>true</Enabled>\n    <Hidden>",
                                                          "<Enabled>false</Enabled>\n    <Hidden>")
    assert zeitplan.zustand(b)["index"]["aktiviert"] is False
    imitat.aufrufe.clear()
    zeitplan.abgleichen(konfig, DIENST_WIN, b=b)
    assert imitat.befehle("/Create") == [name]
    imitat.aufrufe.clear()
    neu = ["D:\\Neu\\pdfsm-dienstw.exe"]                       # Programm verschoben
    zeitplan.abgleichen(konfig, neu, b=b)
    assert sorted(imitat.befehle("/Create")) == sorted(imitat.aufgaben)

    # Web aus: laufende Oberflaeche beenden, Aufgabe loeschen; alles aus: Ordner aufraeumen
    imitat.aufrufe.clear()
    konfig.web_bei_anmeldung = False
    assert zeitplan.abgleichen(konfig, neu, b=b) == ["entfernt: \\PDF Sortier Meister\\Web-Oberflaeche"]
    assert imitat.befehle("/End") == imitat.befehle("/Delete") == ["\\PDF Sortier Meister\\Web-Oberflaeche"]
    assert not any(a[0] == "powershell" for a in imitat.aufrufe)
    konfig.hintergrund_aktiv = False
    zeitplan.abgleichen(konfig, neu, b=b)
    assert imitat.aufgaben == {} and imitat.aufrufe[-1][0] == "powershell"
    assert "DeleteFolder('PDF Sortier Meister',0)" in imitat.aufrufe[-1][-1]


def test_aufgabenplanung_fehler_wird_gemeldet(tmp_path):
    imitat = SchtasksImitat()
    imitat.fehler = "FEHLER: Zugriff verweigert."
    b = zeitplan.Aufgabenplanung(ausfuehren=imitat, benutzer="RECHNER\\nutzer")
    with pytest.raises(zeitplan.ZeitplanFehler, match="Zugriff verweigert"):
        zeitplan.abgleichen(_konfig(tmp_path), DIENST_WIN, b=b)


def test_aufgabe_xml_maskiert_sonderzeichen():
    e = zeitplan.Eintrag("index", "C:\\A & B\\pdfsm-dienstw.exe", ("--config", "C:\\A & B\\c<1>.json", "index"),
                         "03:00", "C:\\A & B")
    text = zeitplan.aufgabe_xml(e, "R\\n", "Beschreibung mit <Zeichen> & Umlauten: täglich")
    wurzel = _xml(text)
    assert _wert(wurzel, "t:Actions/t:Exec/t:Command") == "C:\\A & B\\pdfsm-dienstw.exe"
    assert _wert(wurzel, "t:Actions/t:Exec/t:Arguments") == '--config "C:\\A & B\\c<1>.json" index'
    gelesen = zeitplan._xml_lesen(text)
    assert gelesen["argumente"] == '--config "C:\\A & B\\c<1>.json" index' and gelesen["uhrzeit"] == "03:00"


# --------------------------------------------------------------------------- macOS: LaunchAgents

class LaunchctlImitat:
    def __init__(self, ordner: Path, bootstrap_rc: int = 0):
        self.ordner = ordner
        self.aufrufe: list[list[str]] = []
        self.bootstrap_rc = bootstrap_rc
        self.geladen: set[str] = set()

    def __call__(self, args):
        self.aufrufe.append(list(args))
        befehl = args[1]
        if befehl == "bootstrap":
            if self.bootstrap_rc:
                return subprocess.CompletedProcess(args, self.bootstrap_rc, b"", b"Bootstrap failed: 5")
            self.geladen.add(Path(args[3]).stem)
        elif befehl == "bootout":
            self.geladen.discard(args[2].rsplit("/", 1)[1])
        elif befehl == "print":
            return subprocess.CompletedProcess(args, 0 if args[2].rsplit("/", 1)[1] in self.geladen else 113, b"",
                                               b"")
        return _ok(args)


def test_launchagents(tmp_path):
    ordner = tmp_path / "LaunchAgents"
    imitat = LaunchctlImitat(ordner)
    b = zeitplan.LaunchAgents(ordner=ordner, ausfuehren=imitat, uid=501)
    konfig = _konfig(tmp_path, hintergrund_uhrzeit="03:15", web_aktiv=True, web_bei_anmeldung=True)
    zeitplan.abgleichen(konfig, DIENST_MAC, b=b)

    with open(ordner / "de.josi-create.pdf-sortier-meister.suche.plist", "rb") as f:
        index = plistlib.load(f)
    assert index["ProgramArguments"] == [*DIENST_MAC, "index", "--hintergrund", "--nur-leerlauf"]
    assert index["StartCalendarInterval"] == {"Hour": 3, "Minute": 15}
    assert index["ProcessType"] == "Background" and index["LowPriorityIO"] is True
    with open(ordner / "de.josi-create.pdf-sortier-meister.web.plist", "rb") as f:
        web = plistlib.load(f)
    assert web["RunAtLoad"] is True and web["ProgramArguments"][-2:] == ["web", "--nicht-oeffnen"]
    assert ["launchctl", "bootstrap", "gui/501", str(ordner / "de.josi-create.pdf-sortier-meister.suche.plist")] \
        in imitat.aufrufe

    imitat.aufrufe.clear()
    assert zeitplan.abgleichen(konfig, DIENST_MAC, b=b) == []
    assert not any(a[1] == "bootstrap" for a in imitat.aufrufe)
    assert "täglich um 03:15" in zeitplan.zustand_text(zeitplan.zustand(b))

    assert zeitplan.entfernen(b) == ["entfernt: de.josi-create.pdf-sortier-meister.suche",
                                     "entfernt: de.josi-create.pdf-sortier-meister.web"]
    assert list(ordner.iterdir()) == [] and imitat.geladen == set()


def test_launchagent_fehler_wird_gemeldet(tmp_path):
    b = zeitplan.LaunchAgents(ordner=tmp_path, ausfuehren=LaunchctlImitat(tmp_path, bootstrap_rc=5), uid=501)
    with pytest.raises(zeitplan.ZeitplanFehler, match="Bootstrap failed"):
        zeitplan.abgleichen(_konfig(tmp_path), DIENST_MAC, b=b)


def test_nicht_unterstuetzt_und_tests_erreichen_das_system_nie(tmp_path, monkeypatch):
    monkeypatch.setattr(zeitplan, "_backend_fuer_tests", None)
    monkeypatch.setattr(sys, "platform", "linux")
    assert zeitplan.backend() is None
    assert zeitplan.abgleichen(_konfig(tmp_path, hintergrund_aktiv=False), DIENST_WIN) == []
    with pytest.raises(zeitplan.ZeitplanFehler, match="nicht unterstützt"):
        zeitplan.abgleichen(_konfig(tmp_path), DIENST_WIN)
    assert "nicht unterstützt" in zeitplan.zustand_text(zeitplan.zustand())
    with pytest.raises(AssertionError, match="Betriebssystem"):
        zeitplan.Aufgabenplanung().abfragen("index")          # conftest sperrt echte Aufrufe


# --------------------------------------------------------------------------- Kommandozeile

def test_dienst_zeitplan(tmp_path, zeitplan_speicher, capsys):
    cfg = Config(config_path=tmp_path / "config.json")
    cfg.set_search_config(_konfig(tmp_path, web_aktiv=True, web_bei_anmeldung=True))
    pfad = str(tmp_path / "config.json")

    assert dienst.main(["--config", pfad, "zeitplan", "--status"]) == 0
    assert "Hintergrundindexierung: nicht eingerichtet" in capsys.readouterr().out
    assert dienst.main(["--config", pfad, "zeitplan", "--einrichten"]) == 0
    aus = capsys.readouterr().out
    assert "eingerichtet: \\PDF Sortier Meister\\Indexierung" in aus and "täglich um 03:00" in aus
    index = zeitplan_speicher.eintraege["index"]
    assert index.argumente[-4:] == ("--config", pfad, "index", "--hintergrund")
    assert zeitplan_speicher.gestartet == ["web"]
    assert dienst.main(["--config", pfad, "zeitplan", "--einrichten"]) == 0
    assert "Bereits wie eingestellt." in capsys.readouterr().out

    # --entfernen liest keine Konfiguration (Deinstallation, auch wenn config.json kaputt ist)
    (tmp_path / "config.json").write_text("{kaputt", encoding="utf-8")
    assert dienst.main(["--config", pfad, "zeitplan", "--entfernen"]) == 0
    assert zeitplan_speicher.eintraege == {}
    assert dienst.main(["zeitplan", "--entfernen"]) == 0
    assert "Nichts eingerichtet." in capsys.readouterr().out


def test_dienst_zeitplan_fehler(tmp_path, zeitplan_speicher, monkeypatch, capsys):
    cfg = Config(config_path=tmp_path / "config.json")
    cfg.set_search_config(_konfig(tmp_path))

    def scheitern(e):
        raise zeitplan.ZeitplanFehler("Aufgabe ließ sich nicht einrichten: Zugriff verweigert")

    monkeypatch.setattr(zeitplan_speicher, "einrichten", scheitern)
    assert dienst.main(["--config", str(tmp_path / "config.json"), "zeitplan", "--einrichten"]) == 1
    assert "Zugriff verweigert" in capsys.readouterr().err


# --------------------------------------------------------------------------- Dienstaufruf und Browser-Oberflaeche

def test_dienst_kommando_fuer_den_zeitplan(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    python = tmp_path / "python.exe"
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(sys, "platform", "win32")
    assert Suchindex.dienst_kommando(zeitplan=True) == [str(python), "-m", "src.search.dienst"]
    (tmp_path / "pythonw.exe").write_bytes(b"")
    assert Suchindex.dienst_kommando(zeitplan=True) == [str(tmp_path / "pythonw.exe"), "-m", "src.search.dienst"]
    assert Suchindex.dienst_kommando() == [str(python), "-m", "src.search.dienst"]
    monkeypatch.setattr(sys, "platform", "darwin")
    assert Suchindex.dienst_kommando(zeitplan=True) == [str(python), "-m", "src.search.dienst"]


def _server(antwort: bytes, typ: str):
    class Antwort(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server-API)
            self.send_response(200)
            self.send_header("Content-Type", typ)
            self.end_headers()
            self.wfile.write(antwort)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Antwort)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_web_erreichbar_erkennt_die_eigene_oberflaeche(tmp_path):
    eigene = _server(json.dumps({"vorhanden": False, "laeuft": False}).encode(), "application/json")
    fremde = _server(b"<html>anderes Programm</html>", "text/html")
    try:
        assert Suchindex(_konfig(tmp_path, web_port=eigene.server_port)).web_erreichbar()
        assert not Suchindex(_konfig(tmp_path, web_port=fremde.server_port)).web_erreichbar()
    finally:
        eigene.shutdown()
        fremde.shutdown()
    assert not Suchindex(_konfig(tmp_path, web_port=eigene.server_port)).web_erreichbar()   # Port wieder frei


def test_web_starten(tmp_path, monkeypatch):
    gestartet = []
    monkeypatch.setattr(suchindex_modul.subprocess, "Popen", lambda args, **kw: gestartet.append((args, kw)))
    idx = Suchindex(_konfig(tmp_path, web_port=18555))
    assert idx.web_adresse() == "http://127.0.0.1:18555/"
    idx.web_starten()
    idx.web_starten(oeffnen=False, konfig_pfad="x.json")
    assert gestartet[0][0][-3:] == ["web", "--port", "18555"]
    assert gestartet[1][0][-6:] == ["--config", "x.json", "web", "--port", "18555", "--nicht-oeffnen"]
    assert gestartet[0][1]["stdout"] is subprocess.DEVNULL

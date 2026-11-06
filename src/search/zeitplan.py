"""Hintergrundindexierung und Web-Oberflaeche bei Anmeldung (Qt-frei).

Windows: Aufgabenplanung, Ordner ``\\PDF Sortier Meister\\``, ohne Adminrechte
(``schtasks /Create /XML``). Die Aufgabe „Indexierung“ startet taeglich zur
eingestellten Uhrzeit, aber erst nach 10 Minuten Leerlauf, bricht ab, sobald am
Rechner gearbeitet wird, und setzt bei erneutem Leerlauf fort (wie die
frueheren Aufgaben von PDFsuche). „Web-Oberflaeche“ startet bei der Anmeldung.

macOS: LaunchAgents in ``~/Library/LaunchAgents``. Der Indexlauf startet mit
``StartCalendarInterval`` und prueft den Leerlauf selbst (``--nur-leerlauf``),
die Web-Oberflaeche startet mit ``RunAtLoad``.

``abgleichen(konfig)`` richtet ein, was die Einstellungen verlangen, und
entfernt den Rest; geaendert wird nur, was abweicht. Tests ersetzen das
Betriebssystem durch ``Speicher`` (``tests/conftest.py``), damit nie eine echte
Aufgabe entsteht.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from src.search import plattform
from src.search.konfig import SearchConfig

ORDNER = "\\PDF Sortier Meister\\"
NAMEN = {"index": "Indexierung", "web": "Web-Oberflaeche"}
LABELS = {"index": "de.josi-create.pdf-sortier-meister.suche", "web": "de.josi-create.pdf-sortier-meister.web"}
BESCHREIBUNG = {
    "index": "PDF Sortier Meister: liest täglich bei Leerlauf neue und geänderte Dokumente in den Suchindex ein "
             "(zuerst die Vorrang-Ordner) und erkennt Scans per OCR. Bricht ab, sobald am Rechner gearbeitet wird.",
    "web": "PDF Sortier Meister: Browser-Oberfläche der Dokumentensuche (nur auf diesem Rechner erreichbar).",
}
LEERLAUF_MINUTEN = 10
HOECHSTDAUER_STUNDEN = 20
ARTEN = ("index", "web")


class ZeitplanFehler(Exception):  # noqa: N818 - Fachbegriff, wie Abbruch/Verschluesselt
    """Aufgabe bzw. LaunchAgent liess sich nicht einrichten oder entfernen."""


@dataclass(frozen=True)
class Eintrag:
    """Ein gewuenschter Zeitplaneintrag."""

    art: str                          # 'index' | 'web'
    programm: str
    argumente: tuple[str, ...]
    uhrzeit: str | None = None        # 'HH:MM' (taeglich); None = bei der Anmeldung
    arbeitsordner: str | None = None


def _ausfuehren(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=60, **plattform.popen_flags())


def _text(roh: bytes | str | None) -> str:
    """Ausgabe von schtasks/launchctl als Text (UTF-16 mit BOM, UTF-8 oder OEM-Codepage)."""
    if not roh:
        return ""
    if isinstance(roh, str):
        return roh
    if roh.startswith((b"\xff\xfe", b"\xfe\xff")):
        return roh.decode("utf-16", "replace")
    try:
        return roh.decode("utf-8")
    except UnicodeDecodeError:
        pass
    return roh.decode("oem" if sys.platform == "win32" else "latin-1", "replace")


def _meldung(r: subprocess.CompletedProcess) -> str:
    return " ".join((_text(r.stderr) or _text(r.stdout)).split()) or f"Rückgabewert {r.returncode}"


# --------------------------------------------------------------------------- Was die Einstellungen verlangen

def gewuenscht(konfig: SearchConfig, kommando: list[str] | None = None, konfig_pfad: str | None = None,
               arbeitsordner: str | None = None, leerlauf_selbst: bool = False) -> dict[str, Eintrag | None]:
    """``{'index': Eintrag | None, 'web': Eintrag | None}`` nach den Einstellungen.

    ``kommando``: Aufruf des Dienstes ohne Konsolenfenster (Standard
    ``Suchindex.dienst_kommando(zeitplan=True)``); ``konfig_pfad``: andere
    ``config.json`` als die des Nutzers (wird als ``--config`` mitgegeben);
    ``leerlauf_selbst``: der Zeitplan kennt keine Leerlaufbedingung (macOS),
    der Lauf pausiert selbst, solange am Rechner gearbeitet wird.
    """
    if kommando is None:
        from src.search.suchindex import Suchindex

        kommando = Suchindex.dienst_kommando(zeitplan=True)
        if arbeitsordner is None:
            arbeitsordner = (str(Path(kommando[0]).parent) if getattr(sys, "frozen", False)
                             else str(Path(__file__).resolve().parents[2]))
    programm, *vorne = kommando
    if konfig_pfad:
        vorne += ["--config", str(konfig_pfad)]
    erg: dict[str, Eintrag | None] = {"index": None, "web": None}
    if konfig.aktiv and konfig.hintergrund_aktiv:
        hinten = ["index", "--hintergrund"] + (["--nur-leerlauf"] if leerlauf_selbst else [])
        erg["index"] = Eintrag("index", programm, tuple(vorne + hinten), konfig.hintergrund_uhrzeit or "03:00",
                               arbeitsordner)
    if konfig.aktiv and konfig.web_aktiv and konfig.web_bei_anmeldung:
        erg["web"] = Eintrag("web", programm, tuple(vorne + ["web", "--nicht-oeffnen"]), None, arbeitsordner)
    return erg


def merkmale(konfig: SearchConfig) -> tuple:
    """Die Einstellungen, von denen der Zeitplan abhaengt (zum Vergleichen vor und nach dem Speichern)."""
    return (bool(konfig.aktiv and konfig.hintergrund_aktiv), konfig.hintergrund_uhrzeit,
            bool(konfig.aktiv and konfig.web_aktiv and konfig.web_bei_anmeldung))


def etwas_gewuenscht(konfig: SearchConfig) -> bool:
    a, _, w = merkmale(konfig)
    return a or w


# --------------------------------------------------------------------------- Windows: Aufgabenplanung

def _dauer(stunden: int) -> str:
    return f"PT{stunden}H" if stunden else "PT0S"


def aufgabe_xml(e: Eintrag, benutzer: str | None, beschreibung: str = "", heute: date | None = None) -> str:
    """XML fuer ``schtasks /Create /XML`` (Schema 1.2, ohne Adminrechte: InteractiveToken, LeastPrivilege)."""
    x = escape
    benutzer_xml = f"<UserId>{x(benutzer)}</UserId>" if benutzer else ""
    if e.uhrzeit:
        tag = (heute or date.today()).isoformat()
        ausloeser = (f"    <CalendarTrigger>\n      <StartBoundary>{tag}T{x(e.uhrzeit)}:00</StartBoundary>\n"
                     "      <Enabled>true</Enabled>\n"
                     "      <ScheduleByDay>\n        <DaysInterval>1</DaysInterval>\n      </ScheduleByDay>\n"
                     "    </CalendarTrigger>")
        leerlauf = (f"    <IdleSettings>\n      <Duration>PT{LEERLAUF_MINUTEN}M</Duration>\n"
                    f"      <WaitTimeout>{_dauer(HOECHSTDAUER_STUNDEN)}</WaitTimeout>\n"
                    "      <StopOnIdleEnd>true</StopOnIdleEnd>\n      <RestartOnIdle>true</RestartOnIdle>\n"
                    "    </IdleSettings>\n")
        nur_leerlauf, hoechstdauer = "true", _dauer(HOECHSTDAUER_STUNDEN)
    else:
        ausloeser = f"    <LogonTrigger>\n      <Enabled>true</Enabled>\n      {benutzer_xml}\n    </LogonTrigger>"
        leerlauf = ("    <IdleSettings>\n      <StopOnIdleEnd>false</StopOnIdleEnd>\n"
                    "      <RestartOnIdle>false</RestartOnIdle>\n    </IdleSettings>\n")
        nur_leerlauf, hoechstdauer = "false", _dauer(0)
    ordner = f"\n      <WorkingDirectory>{x(e.arbeitsordner)}</WorkingDirectory>" if e.arbeitsordner else ""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{x(beschreibung)}</Description>
  </RegistrationInfo>
  <Triggers>
{ausloeser}
  </Triggers>
  <Principals>
    <Principal id="Author">
      {benutzer_xml}
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
{leerlauf}    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>{nur_leerlauf}</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>{hoechstdauer}</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{x(e.programm)}</Command>
      <Arguments>{x(subprocess.list2cmdline(e.argumente))}</Arguments>{ordner}
    </Exec>
  </Actions>
</Task>
"""


def _xml_lesen(text: str) -> dict | None:
    """Merkmale aus ``schtasks /Query /XML``."""
    try:
        wurzel = ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", text.strip()))
    except ET.ParseError:
        return None
    werte: dict[str, str] = {}
    anmeldung = False
    for el in wurzel.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "LogonTrigger":
            anmeldung = True
        if tag in ("Command", "Arguments", "WorkingDirectory", "StartBoundary") and tag not in werte:
            werte[tag] = (el.text or "").strip()
    einstellungen = next((el for el in wurzel.iter() if el.tag.rsplit("}", 1)[-1] == "Settings"), None)
    aktiviert = True
    if einstellungen is not None:
        for el in einstellungen:
            if el.tag.rsplit("}", 1)[-1] == "Enabled":
                aktiviert = (el.text or "").strip().lower() != "false"
    start = werte.get("StartBoundary", "")
    return {
        "programm": os.path.normcase(werte.get("Command", "").strip('"')),
        "argumente": werte.get("Arguments", ""),
        "arbeitsordner": os.path.normcase(werte.get("WorkingDirectory", "").strip('"')),
        "uhrzeit": start[11:16] if len(start) >= 16 and not anmeldung else None,
        "anmeldung": anmeldung,
        "aktiviert": aktiviert,
    }


class Aufgabenplanung:
    """Windows-Aufgabenplanung ueber ``schtasks`` (ohne Adminrechte)."""

    titel = "Aufgabenplanung"
    leerlauf_selbst = False      # Leerlaufbedingung der Aufgabe: Start erst nach 10 Minuten, Abbruch bei Aktivitaet

    def __init__(self, ausfuehren=None, ordner: str = ORDNER, benutzer: str | None = None):
        self._ausfuehren = ausfuehren or _ausfuehren
        self.ordner = ordner if ordner.endswith("\\") else ordner + "\\"
        if benutzer is None:
            domaene, name = os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", "")
            benutzer = f"{domaene}\\{name}" if domaene and name else (name or None)
        self.benutzer = benutzer

    def name(self, art: str) -> str:
        return self.ordner + NAMEN[art]

    def merkmale(self, e: Eintrag) -> dict:
        return {"programm": os.path.normcase(e.programm), "argumente": subprocess.list2cmdline(e.argumente),
                "arbeitsordner": os.path.normcase(e.arbeitsordner or ""), "uhrzeit": e.uhrzeit,
                "anmeldung": e.uhrzeit is None}

    def abfragen(self, art: str) -> dict | None:
        r = self._ausfuehren(["schtasks", "/Query", "/TN", self.name(art), "/XML"])
        if r.returncode != 0 or not r.stdout:
            return None
        return _xml_lesen(_text(r.stdout))

    def einrichten(self, e: Eintrag) -> None:
        with tempfile.TemporaryDirectory(prefix="pdfsm-zeitplan-") as tmp:
            datei = Path(tmp) / "aufgabe.xml"
            datei.write_text(aufgabe_xml(e, self.benutzer, BESCHREIBUNG[e.art]), encoding="utf-16")
            r = self._ausfuehren(["schtasks", "/Create", "/TN", self.name(e.art), "/XML", str(datei), "/F"])
        if r.returncode != 0:
            raise ZeitplanFehler(f"Aufgabe „{self.name(e.art)}“ ließ sich nicht einrichten: {_meldung(r)}")

    def starten(self, art: str) -> None:
        self._ausfuehren(["schtasks", "/Run", "/TN", self.name(art)])

    def entfernen(self, art: str) -> None:
        if self.abfragen(art) is None:
            return
        if art == "web":
            self._ausfuehren(["schtasks", "/End", "/TN", self.name(art)])
        r = self._ausfuehren(["schtasks", "/Delete", "/TN", self.name(art), "/F"])
        if r.returncode != 0 and self.abfragen(art) is not None:
            raise ZeitplanFehler(f"Aufgabe „{self.name(art)}“ ließ sich nicht entfernen: {_meldung(r)}")

    def aufraeumen(self) -> None:
        """Den leeren Aufgabenordner entfernen (best effort, ``schtasks`` kennt keine Ordner)."""
        name = self.ordner.strip("\\")
        if not name or "'" in name:
            return
        ps = ("$s=New-Object -ComObject Schedule.Service;$s.Connect();"
              f"try{{$f=$s.GetFolder('\\{name}')}}catch{{exit 0}};"
              "if($f.GetTasks(1).Count -eq 0 -and $f.GetFolders(0).Count -eq 0)"
              f"{{$s.GetFolder('\\').DeleteFolder('{name}',0)}}")
        try:
            self._ausfuehren(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps])
        except (OSError, subprocess.SubprocessError):
            pass


# --------------------------------------------------------------------------- macOS: LaunchAgents

def launchagent(e: Eintrag, label: str) -> dict:
    """Inhalt der plist fuer einen LaunchAgent."""
    p: dict = {"Label": label, "ProgramArguments": [e.programm, *e.argumente],
               "StandardOutPath": "/dev/null", "StandardErrorPath": "/dev/null"}
    if e.arbeitsordner:
        p["WorkingDirectory"] = e.arbeitsordner
    if e.uhrzeit:
        stunde, minute = (int(t) for t in e.uhrzeit.split(":"))
        p.update({"StartCalendarInterval": {"Hour": stunde, "Minute": minute},
                  "ProcessType": "Background", "LowPriorityIO": True, "Nice": 10})
    else:
        p["RunAtLoad"] = True
    return p


class LaunchAgents:
    """macOS-LaunchAgents im Benutzerkontext (``launchctl bootstrap gui/<uid>``)."""

    titel = "LaunchAgent"
    leerlauf_selbst = True       # launchd kennt keine Leerlaufbedingung: --nur-leerlauf

    def __init__(self, ordner: Path | str | None = None, ausfuehren=None, uid: int | None = None):
        self.ordner = Path(ordner) if ordner else Path.home() / "Library" / "LaunchAgents"
        self._ausfuehren = ausfuehren or _ausfuehren
        self.uid = uid if uid is not None else (os.getuid() if hasattr(os, "getuid") else 0)

    def name(self, art: str) -> str:
        return LABELS[art]

    def datei(self, art: str) -> Path:
        return self.ordner / f"{LABELS[art]}.plist"

    def merkmale(self, e: Eintrag) -> dict:
        return {"argumente": [e.programm, *e.argumente], "arbeitsordner": e.arbeitsordner or "",
                "uhrzeit": e.uhrzeit, "anmeldung": e.uhrzeit is None}

    def abfragen(self, art: str) -> dict | None:
        try:
            with open(self.datei(art), "rb") as f:
                p = plistlib.load(f)
        except (OSError, plistlib.InvalidFileException, ValueError):
            return None
        intervall = p.get("StartCalendarInterval") or {}
        uhrzeit = (f"{int(intervall.get('Hour', 0)):02d}:{int(intervall.get('Minute', 0)):02d}"
                   if intervall else None)
        geladen = self._ausfuehren(["launchctl", "print", f"gui/{self.uid}/{LABELS[art]}"]).returncode == 0
        return {"argumente": list(p.get("ProgramArguments") or []), "arbeitsordner": p.get("WorkingDirectory", ""),
                "uhrzeit": uhrzeit, "anmeldung": bool(p.get("RunAtLoad")), "aktiviert": geladen}

    def einrichten(self, e: Eintrag) -> None:
        self.ordner.mkdir(parents=True, exist_ok=True)
        ziel = self.datei(e.art)
        self._ausfuehren(["launchctl", "bootout", f"gui/{self.uid}/{LABELS[e.art]}"])
        tmp = ziel.with_suffix(".plist.tmp")
        with open(tmp, "wb") as f:
            plistlib.dump(launchagent(e, LABELS[e.art]), f)
        os.replace(tmp, ziel)
        r = self._ausfuehren(["launchctl", "bootstrap", f"gui/{self.uid}", str(ziel)])
        if r.returncode != 0:
            raise ZeitplanFehler(f"LaunchAgent „{LABELS[e.art]}“ ließ sich nicht laden: {_meldung(r)}")

    def starten(self, art: str) -> None:
        pass   # RunAtLoad startet den Agenten schon beim Laden

    def entfernen(self, art: str) -> None:
        self._ausfuehren(["launchctl", "bootout", f"gui/{self.uid}/{LABELS[art]}"])
        try:
            self.datei(art).unlink()
        except FileNotFoundError:
            pass
        except OSError as ex:
            raise ZeitplanFehler(f"LaunchAgent „{LABELS[art]}“ ließ sich nicht entfernen: {ex}") from ex

    def aufraeumen(self) -> None:
        pass


# --------------------------------------------------------------------------- Tests: nur im Speicher

class Speicher:
    """Ersatz fuer das Betriebssystem in Tests (``tests/conftest.py``): merkt sich die Eintraege."""

    titel = "Speicher"
    leerlauf_selbst = False

    def __init__(self):
        self.eintraege: dict[str, Eintrag] = {}
        self.gestartet: list[str] = []

    def name(self, art: str) -> str:
        return ORDNER + NAMEN[art]

    def merkmale(self, e: Eintrag) -> dict:
        return asdict(e)

    def abfragen(self, art: str) -> dict | None:
        e = self.eintraege.get(art)
        return dict(asdict(e), aktiviert=True) if e else None

    def einrichten(self, e: Eintrag) -> None:
        self.eintraege[e.art] = e

    def starten(self, art: str) -> None:
        self.gestartet.append(art)

    def entfernen(self, art: str) -> None:
        self.eintraege.pop(art, None)

    def aufraeumen(self) -> None:
        pass


_backend_fuer_tests = None


def backend():
    """Zustaendige Plattform: Aufgabenplanung (Windows), LaunchAgents (macOS), sonst None."""
    if _backend_fuer_tests is not None:
        return _backend_fuer_tests
    if sys.platform == "win32":
        return Aufgabenplanung()
    if sys.platform == "darwin":
        return LaunchAgents()
    return None


# --------------------------------------------------------------------------- Oeffentliche Funktionen

def zustand(b=None) -> dict:
    """``{'unterstuetzt', 'titel', 'index': dict | None, 'web': dict | None}`` (Name, Uhrzeit, aktiviert)."""
    b = b or backend()
    if b is None:
        return {"unterstuetzt": False, "titel": "", "index": None, "web": None}
    erg = {"unterstuetzt": True, "titel": b.titel}
    for art in ARTEN:
        ist = b.abfragen(art)
        erg[art] = dict(ist, name=b.name(art)) if ist else None
    return erg


def abgleichen(konfig: SearchConfig, kommando: list[str] | None = None, konfig_pfad: str | None = None,
               b=None) -> list[str]:
    """Zeitplan an die Einstellungen anpassen; Liste der Aenderungen. ``ZeitplanFehler`` bei Misserfolg."""
    b = b or backend()
    soll = gewuenscht(konfig, kommando, konfig_pfad, leerlauf_selbst=getattr(b, "leerlauf_selbst", False))
    if b is None:
        if any(soll.values()):
            raise ZeitplanFehler("Die Hintergrundindexierung wird auf diesem Betriebssystem nicht unterstützt.")
        return []
    geaendert: list[str] = []
    for art in ARTEN:
        ist = b.abfragen(art)
        e = soll[art]
        if e is None:
            if ist is not None:
                b.entfernen(art)
                geaendert.append(f"entfernt: {b.name(art)}")
            continue
        m = b.merkmale(e)
        if ist is not None and ist.get("aktiviert", True) and {k: ist.get(k) for k in m} == m:
            continue
        b.einrichten(e)
        if art == "web":
            b.starten(art)
        geaendert.append(f"eingerichtet: {b.name(art)}")
    if not any(soll.values()):
        b.aufraeumen()
    return geaendert


def entfernen(b=None) -> list[str]:
    """Alle Eintraege entfernen (Deinstallation, ``pdfsm-dienst zeitplan --entfernen``)."""
    b = b or backend()
    if b is None:
        return []
    weg = []
    for art in ARTEN:
        if b.abfragen(art) is not None:
            b.entfernen(art)
            weg.append(f"entfernt: {b.name(art)}")
    b.aufraeumen()
    return weg


def zustand_text(z: dict) -> str:
    """Zustand als Text fuer ``pdfsm-dienst zeitplan --status``."""
    if not z.get("unterstuetzt"):
        return "Hintergrundindexierung: auf diesem Betriebssystem nicht unterstützt."
    zeilen = []
    for art, titel in (("index", "Hintergrundindexierung"), ("web", "Web-Oberfläche bei Anmeldung")):
        ist = z.get(art)
        if not ist:
            zeilen.append(f"{titel}: nicht eingerichtet")
            continue
        wann = f"täglich um {ist['uhrzeit']}" if ist.get("uhrzeit") else "bei der Anmeldung"
        aus = "" if ist.get("aktiviert", True) else " (deaktiviert)"
        zeilen.append(f"{titel}: {wann}{aus} – {z['titel']} {ist['name']}")
    return "\n".join(zeilen)

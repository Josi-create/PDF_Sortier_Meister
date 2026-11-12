"""Einrichtung des MCP-Servers ``pdfsuche`` in Claude Code und Claude Desktop (Qt-frei).

Baustein 3 aus ``docs/CHAT_MCP_PLAN.md``: Die Einstellungen (Reiter „Suche“, Gruppe
„KI-Assistenten (MCP)“) zeigen damit, ob ein Client installiert und eingerichtet ist,
und richten ihn auf Wunsch ein.

* Claude Code: ``claude mcp get pdfsuche`` (Status) und ``claude mcp add`` (Einrichten).
* Claude Desktop: Eintrag ``mcpServers.pdfsuche`` in ``claude_desktop_config.json``;
  uebrige Eintraege bleiben unveraendert, vorher entsteht eine Sicherungskopie.

Alle Funktionen liefern Fehlertexte statt Ausnahmen. Tests ersetzen
``claude_programm`` und ``claude_desktop_konfig`` (``tests/conftest.py``), damit nie das
echte Claude Code laeuft oder die echte Konfiguration gelesen wird.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.search import plattform
from src.i18n import tr

SERVER_NAME = "pdfsuche"

# Wurzel des Quellbaums (Entwicklungsmodus) und Einstiegsskript des Dienstes
QUELLBAUM = Path(__file__).resolve().parents[2]
EINSTIEG = QUELLBAUM / "packaging" / "pdfsm_dienst.py"

# ``claude mcp get`` startet den Server zur Pruefung (rund 2 s), ``claude`` selbst braucht etwas
CLAUDE_ZEITLIMIT_S = 60.0

# Werkzeuge des Servers, wie src/search/mcp_server.erstelle_server sie registriert
# (tests/test_mcp_einrichtung.py gleicht die Liste mit dem Server ab).
WERKZEUGE: tuple[str, ...] = ("suche", "dokument_lesen", "index_status", "ordner_vorschlag",
                              "korrespondent_info")
SQL_WERKZEUG = "sql_abfrage"

# Zustaende von claude_code_status / claude_desktop_status
NICHT_GEFUNDEN = "nicht_gefunden"
INSTALLIERT = "installiert"
EINGERICHTET = "eingerichtet"
ANDERER_PFAD = "anderer_pfad"   # eingerichtet, zeigt aber auf ein anderes Programm
FEHLER = "fehler"               # Pruefung gescheitert (Konfiguration defekt, claude haengt)


def werkzeug_namen(sql_erlaubt: bool) -> list[str]:
    """Die Werkzeuge, die ``pdfsm-dienst mcp`` anbietet (``sql_abfrage`` nur mit Schalter)."""
    return [*WERKZEUGE, SQL_WERKZEUG] if sql_erlaubt else list(WERKZEUGE)


# --------------------------------------------------------------------------- Aufruf des Dienstes


def befehlszeile(teile: list[str]) -> str:
    """Argumentliste als eine Zeile zum Anzeigen und Kopieren (Windows- bzw. POSIX-Quotierung)."""
    if sys.platform == "win32":
        return subprocess.list2cmdline(teile)
    return shlex.join(teile)


@dataclass(frozen=True)
class DienstAufruf:
    """Wie ein MCP-Client den Server startet: Programm, Argumente, zusaetzliche Umgebung."""

    programm: str
    argumente: tuple[str, ...]
    umgebung: dict[str, str] = field(default_factory=dict)
    gebaut: bool = True

    def befehlszeile(self) -> str:
        """Programm und Argumente als eine Zeile (ohne die Umgebung)."""
        return befehlszeile([self.programm, *self.argumente])


def _ist_gebaut() -> bool:
    return bool(getattr(sys, "frozen", False))


def dienst_aufruf() -> DienstAufruf:
    """Gebaut: ``pdfsm-dienst[.exe] mcp`` neben dem Programm (mit Konsole, MCP braucht stdio).

    Entwicklung: ``python packaging/pdfsm_dienst.py mcp`` mit ``PYTHONPATH`` auf den
    Quellbaum. Nicht ``python -m src.search.dienst``: dabei steht das Arbeitsverzeichnis
    vorn im Suchpfad, und Claude Code startet den Server im jeweiligen Projektordner.
    """
    if _ist_gebaut():
        name = "pdfsm-dienst.exe" if sys.platform == "win32" else "pdfsm-dienst"
        return DienstAufruf(str(Path(sys.executable).with_name(name)), ("mcp",))
    return DienstAufruf(sys.executable, (str(EINSTIEG), "mcp"), {"PYTHONPATH": str(QUELLBAUM)}, gebaut=False)


def dienst_pfad() -> Path | str:
    """Gebaut: Pfad von ``pdfsm-dienst``; Entwicklung: die ganze Befehlszeile (Text)."""
    aufruf = dienst_aufruf()
    return Path(aufruf.programm) if aufruf.gebaut else aufruf.befehlszeile()


def _gleicher_pfad(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a.strip())) == os.path.normcase(os.path.normpath(b.strip()))


def _gleicher_aufruf(programm: str, argumente: list[str] | tuple[str, ...], aufruf: DienstAufruf) -> bool:
    if not _gleicher_pfad(programm, aufruf.programm) or len(argumente) != len(aufruf.argumente):
        return False
    return all(_gleicher_pfad(str(x), y) for x, y in zip(argumente, aufruf.argumente, strict=True))


@dataclass
class Status:
    """Ergebnis einer Statuspruefung; ``text`` ist fuer die Anzeige gedacht."""

    zustand: str
    text: str
    pfad: Path | None = None   # Claude Desktop: Konfigurationsdatei


# --------------------------------------------------------------------------- Claude Code


def claude_programm() -> str | None:
    """Pfad des Befehls ``claude`` (Claude Code) oder None."""
    return shutil.which("claude")


def _ausfuehren(args: list[str], zeitlimit_s: float = CLAUDE_ZEITLIMIT_S) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=zeitlimit_s, stdin=subprocess.DEVNULL, **plattform.popen_flags())


def _letzte_zeilen(*texte: str, anzahl: int = 4) -> str:
    zeilen = [z.strip() for t in texte for z in (t or "").splitlines() if z.strip()]
    return "\n".join(zeilen[-anzahl:])


def _feld(ausgabe: str, name: str) -> str | None:
    """Wert einer Zeile ``  Name: Wert`` aus ``claude mcp get``."""
    for zeile in ausgabe.splitlines():
        kopf, sep, wert = zeile.strip().partition(":")
        if sep and kopf.strip().lower() == name.lower():
            return wert.strip()
    return None


def claude_code_befehl(aufruf: DienstAufruf | None = None, programm: str = "claude") -> list[str]:
    """``claude mcp add pdfsuche --scope user [-e K=V] -- <dienst> mcp`` als Argumentliste."""
    aufruf = aufruf or dienst_aufruf()
    befehl = [programm, "mcp", "add", SERVER_NAME, "--scope", "user"]
    for schluessel, wert in aufruf.umgebung.items():
        befehl += ["-e", f"{schluessel}={wert}"]
    return [*befehl, "--", aufruf.programm, *aufruf.argumente]


def claude_code_status(aufruf: DienstAufruf | None = None) -> Status:
    """``nicht_gefunden`` (kein ``claude``), ``installiert``, ``eingerichtet`` oder ``anderer_pfad``."""
    programm = claude_programm()
    if not programm:
        return Status(NICHT_GEFUNDEN, tr("nicht gefunden (Befehl „claude“ fehlt im Suchpfad)"))
    try:
        r = _ausfuehren([programm, "mcp", "get", SERVER_NAME])
    except subprocess.TimeoutExpired:
        return Status(FEHLER, tr("keine Antwort von „claude mcp get“ nach {CLAUDE_ZEITLIMIT_S:.0f} s").format(CLAUDE_ZEITLIMIT_S=CLAUDE_ZEITLIMIT_S))
    except OSError as exc:
        return Status(FEHLER, tr("„claude“ ließ sich nicht starten: {exc}").format(exc=exc))
    if r.returncode != 0:
        return Status(INSTALLIERT, tr("installiert, „{SERVER_NAME}“ noch nicht eingerichtet").format(SERVER_NAME=SERVER_NAME))
    aufruf = aufruf or dienst_aufruf()
    befehl = _feld(r.stdout, "Command")
    argumente = _feld(r.stdout, "Args")
    verbindung = _feld(r.stdout, "Status") or ""
    zusatz = "" if not verbindung or "connected" in verbindung.lower() else f" – {verbindung}"
    if befehl is None or _gleicher_aufruf(befehl, (argumente or "").split(), aufruf) or (
            aufruf.gebaut and _gleicher_pfad(befehl, aufruf.programm) and argumente is None):
        return Status(EINGERICHTET, f"eingerichtet{zusatz}")
    return Status(ANDERER_PFAD, tr("eingerichtet, startet aber {befehl}{zusatz}").format(befehl=befehl, zusatz=zusatz))


def claude_code_einrichten(ersetzen: bool = False, aufruf: DienstAufruf | None = None) -> str:
    """``claude mcp add …`` ausfuehren; ``ersetzen``: vorher ``claude mcp remove pdfsuche -s user``.

    Rueckgabe: Meldung fuer den Nutzer, bei Misserfolg beginnend mit „Fehler“.
    """
    programm = claude_programm()
    if not programm:
        return tr("Fehler: Claude Code nicht gefunden (Befehl „claude“ fehlt im Suchpfad).")
    try:
        if ersetzen:
            _ausfuehren([programm, "mcp", "remove", SERVER_NAME, "-s", "user"])
        r = _ausfuehren(claude_code_befehl(aufruf, programm))
    except subprocess.TimeoutExpired:
        return tr("Fehler: „claude mcp add“ hat nach {CLAUDE_ZEITLIMIT_S:.0f} s nicht geantwortet.").format(CLAUDE_ZEITLIMIT_S=CLAUDE_ZEITLIMIT_S)
    except OSError as exc:
        return tr("Fehler: „claude“ ließ sich nicht starten: {exc}").format(exc=exc)
    if r.returncode != 0:
        grund = _letzte_zeilen(r.stderr, r.stdout) or tr("Rückgabewert {returncode}").format(returncode=r.returncode)
        return tr("Fehler: Claude Code hat „{SERVER_NAME}“ nicht eingerichtet.\n{grund}").format(SERVER_NAME=SERVER_NAME, grund=grund)
    return (tr(
        "Claude Code: „{SERVER_NAME}“ ist eingerichtet (für alle Projekte). In laufenden "
        "Sitzungen erscheint der Server nach einem Neustart von Claude Code."
    ).format(SERVER_NAME=SERVER_NAME))


# --------------------------------------------------------------------------- Claude Desktop

KONFIG_NAME = "claude_desktop_config.json"


def claude_desktop_kandidaten(system: str | None = None, umgebung: dict[str, str] | None = None,
                              home: Path | None = None) -> list[Path]:
    """Moegliche Orte der Konfiguration, wahrscheinlichster zuerst.

    macOS: ``~/Library/Application Support/Claude``. Windows: die Store-Fassung legt ihre
    Daten heute unter ``%LOCALAPPDATA%\\Claude-Data\\claude_<id>`` ab, aeltere Store-Fassungen
    im Paketordner (``%LOCALAPPDATA%\\Packages\\Claude_<id>\\LocalCache\\Roaming\\Claude``,
    leer bis auf eine Markierungsdatei, sobald die Daten umgezogen sind), der klassische
    Installer unter ``%APPDATA%\\Claude``. Andere Systeme: keine (erst mit Linux-Builds).
    """
    system = system or sys.platform
    umgebung = os.environ if umgebung is None else umgebung
    home = home or Path.home()
    if system == "darwin":
        return [home / "Library" / "Application Support" / "Claude" / KONFIG_NAME]
    if system != "win32":
        return []
    kandidaten: list[Path] = []
    lokal = umgebung.get("LOCALAPPDATA")
    if lokal:
        kandidaten += [d / KONFIG_NAME for d in sorted(Path(lokal, "Claude-Data").glob("claude_*")) if d.is_dir()]
        for paket in sorted(Path(lokal, "Packages").glob("Claude_*")):
            ordner = paket / "LocalCache" / "Roaming" / "Claude"
            if not any(ordner.glob(".user-data-left*")):
                kandidaten.append(ordner / KONFIG_NAME)
    roaming = umgebung.get("APPDATA")
    if roaming:
        kandidaten.append(Path(roaming) / "Claude" / KONFIG_NAME)
    return kandidaten


def claude_desktop_konfig(system: str | None = None, umgebung: dict[str, str] | None = None,
                          home: Path | None = None) -> Path | None:
    """Die Konfigurationsdatei von Claude Desktop: zuerst eine vorhandene, sonst die in einem
    vorhandenen Datenordner (Claude Desktop installiert, aber noch nie eine Konfiguration
    gespeichert); None, wenn Claude Desktop nicht gefunden wurde."""
    try:
        kandidaten = claude_desktop_kandidaten(system, umgebung, home)
        for datei in kandidaten:
            if datei.is_file():
                return datei
        for datei in kandidaten:
            if datei.parent.is_dir():
                return datei
    except OSError:
        pass
    return None


def claude_desktop_eintrag(aufruf: DienstAufruf | None = None) -> dict:
    """Der Eintrag ``mcpServers.pdfsuche`` (``command``, ``args``, im Entwicklungsmodus ``env``)."""
    aufruf = aufruf or dienst_aufruf()
    eintrag: dict = {"command": aufruf.programm, "args": list(aufruf.argumente)}
    if aufruf.umgebung:
        eintrag["env"] = dict(aufruf.umgebung)
    return eintrag


def claude_desktop_eintrag_json(aufruf: DienstAufruf | None = None) -> str:
    """Vollstaendiges, gueltiges JSON zum Kopieren: ``{"mcpServers": {"pdfsuche": {...}}}``."""
    return json.dumps({"mcpServers": {SERVER_NAME: claude_desktop_eintrag(aufruf)}}, indent=2, ensure_ascii=False)


def _konfig_lesen(pfad: Path) -> tuple[dict | None, str]:
    """(Inhalt, Fehlertext). Fehlende Datei = leere Konfiguration."""
    try:
        roh = pfad.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}, ""
    except (OSError, UnicodeDecodeError) as exc:
        return None, tr("{pfad} lässt sich nicht lesen: {exc}").format(pfad=pfad, exc=exc)
    if not roh.strip():
        return {}, ""
    try:
        daten = json.loads(roh)
    except json.JSONDecodeError as exc:
        return None, tr("{pfad} ist kein gültiges JSON (Zeile {lineno}, Spalte {colno}).").format(pfad=pfad, lineno=exc.lineno, colno=exc.colno)
    if not isinstance(daten, dict):
        return None, tr("{pfad} enthält kein JSON-Objekt.").format(pfad=pfad)
    if not isinstance(daten.get("mcpServers", {}), dict):
        return None, tr("„mcpServers“ in {pfad} ist kein JSON-Objekt.").format(pfad=pfad)
    return daten, ""


def claude_desktop_status(pfad: Path | None = None, aufruf: DienstAufruf | None = None) -> Status:
    """``nicht_gefunden``, ``installiert``, ``eingerichtet``, ``anderer_pfad`` oder ``fehler``."""
    pfad = pfad or claude_desktop_konfig()
    if pfad is None:
        return Status(NICHT_GEFUNDEN, tr("nicht gefunden"))
    daten, fehler = _konfig_lesen(pfad)
    if daten is None:
        return Status(FEHLER, tr("Konfiguration nicht lesbar: {fehler}").format(fehler=fehler), pfad)
    eintrag = daten.get("mcpServers", {}).get(SERVER_NAME)
    if not isinstance(eintrag, dict):
        return Status(INSTALLIERT, tr("installiert, „{SERVER_NAME}“ noch nicht eingetragen").format(SERVER_NAME=SERVER_NAME), pfad)
    befehl = str(eintrag.get("command", ""))
    argumente = eintrag.get("args") or []
    if not isinstance(argumente, list):
        argumente = []
    if _gleicher_aufruf(befehl, [str(a) for a in argumente], aufruf or dienst_aufruf()):
        return Status(EINGERICHTET, "eingerichtet", pfad)
    return Status(ANDERER_PFAD, tr("eingetragen, startet aber {0}").format(befehl or tr("(kein Programm)")), pfad)


def _sicherung(pfad: Path, jetzt: datetime) -> Path:
    basis = f"{pfad.name}.bak-{jetzt:%Y%m%d-%H%M%S}"
    ziel = pfad.with_name(basis)
    nr = 1
    while ziel.exists():
        ziel = pfad.with_name(f"{basis}-{nr}")
        nr += 1
    shutil.copy2(pfad, ziel)
    return ziel


def claude_desktop_eintragen(pfad: Path, aufruf: DienstAufruf | None = None,
                             jetzt: datetime | None = None) -> str:
    """``mcpServers.pdfsuche`` in ``pfad`` setzen oder ersetzen; uebrige Eintraege bleiben.

    Eine vorhandene Datei wird vorher als ``<name>.bak-JJJJMMTT-HHMMSS`` gesichert; eine
    defekte Datei bleibt unberuehrt. Rueckgabe: Meldung, bei Misserfolg beginnend mit „Fehler“.
    """
    pfad = Path(pfad)
    daten, fehler = _konfig_lesen(pfad)
    if daten is None:
        return tr("Fehler: {fehler} Nichts geändert.").format(fehler=fehler)
    eintrag = claude_desktop_eintrag(aufruf)
    server = daten.setdefault("mcpServers", {})
    if server.get(SERVER_NAME) == eintrag:
        return tr("„{SERVER_NAME}“ ist in {pfad} bereits so eingetragen.").format(SERVER_NAME=SERVER_NAME, pfad=pfad)
    server[SERVER_NAME] = eintrag
    neu = pfad.with_name(pfad.name + ".neu")
    try:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        sicherung = _sicherung(pfad, jetzt or datetime.now()) if pfad.exists() else None
        neu.write_text(json.dumps(daten, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        os.replace(neu, pfad)
    except OSError as exc:
        try:
            neu.unlink(missing_ok=True)
        except OSError:
            pass
        return tr("Fehler: {pfad} ließ sich nicht schreiben: {exc}").format(pfad=pfad, exc=exc)
    text = tr("„{SERVER_NAME}“ in {pfad} eingetragen.").format(SERVER_NAME=SERVER_NAME, pfad=pfad)
    if sicherung:
        text += tr(" Sicherungskopie: {name}.").format(name=sicherung.name)
    return tr("{text} Claude Desktop neu starten, damit der Server erscheint.").format(text=text)

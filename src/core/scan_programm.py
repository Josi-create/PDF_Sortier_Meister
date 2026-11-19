"""Hinterlegtes Scanprogramm starten (Issue #270) - Qt-frei.

Der Knopf „Jetzt scannen“ startet nur das Programm, das in den Einstellungen
hinterlegt ist (z. B. VueScan). Gescannt wird dort; die neue Datei erscheint
ueber die Ordner-Beobachtung (Issue #232) von selbst.

GPL-3.0-or-later - Copyright (c) 2026
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

KONFIG_SCHLUESSEL = "scan_programm"


class ScanprogrammFehler(Exception):
    """Das Scanprogramm liess sich nicht starten."""


def bereinigt(pfad: str | None) -> str:
    """Pfad aus der Einstellung ohne Leerraum und umschliessende Anfuehrungszeichen."""
    return (pfad or "").strip().strip('"').strip()


def starten(pfad: str | None) -> None:
    """Startet das Programm unter ``pfad`` und kehrt sofort zurueck.

    Windows: wie ein Doppelklick im Explorer (auch Verknuepfungen .lnk).
    macOS: ein Programmpaket (.app) ueber ``open``. Sonst die Datei direkt.
    """
    pfad = bereinigt(pfad)
    if not pfad:
        raise ScanprogrammFehler("kein Scanprogramm hinterlegt")
    datei = Path(pfad)
    if not datei.exists():
        raise ScanprogrammFehler(f"nicht gefunden: {pfad}")
    try:
        if sys.platform == "win32":
            # Arbeitsordner = Programmordner, wie beim Start ueber das Startmenue
            os.startfile(str(datei), cwd=str(datei.parent))  # noqa: S606 - gewollter Shell-Aufruf
        elif sys.platform == "darwin" and datei.is_dir():
            subprocess.Popen(["open", str(datei)])  # noqa: S603, S607
        else:
            subprocess.Popen([str(datei)], cwd=str(datei.parent))  # noqa: S603
    except OSError as e:
        raise ScanprogrammFehler(str(e)) from e


# --- Auswahl erleichtern (Issue #338) ---

# Teile von Verknuepfungs-/Programmnamen, die auf ein Scanprogramm deuten (klein geschrieben).
# „scan“ deckt Epson Scan, ScanSnap, HP Scan, IJ Scan Utility, Windows-Fax und -Scan u. a. ab.
_SCAN_NAMEN = ("scan", "naps2", "paperport", "silverfast")
# Verknuepfungen mit diesen Wortteilen sind keine Programme zum Scannen.
_KEIN_PROGRAMM = (
    "uninstall", "deinstall", "entfernen", "remove", "hilfe", "help", "handbuch", "manual",
    "readme", "liesmich", "lizenz", "license", "update", "virus", "malware", "website", "web site",
    "registrier", "register", "support",
)


@dataclass(frozen=True)
class Vorschlag:
    """Ein gefundenes Scanprogramm: Anzeigename, einzutragender Pfad, laeuft es gerade?"""
    name: str
    pfad: str
    laeuft: bool = False


def _sieht_nach_scanprogramm_aus(name: str) -> bool:
    klein = name.lower()
    return any(t in klein for t in _SCAN_NAMEN) and not any(t in klein for t in _KEIN_PROGRAMM)


def startmenue_ordner() -> list[Path]:
    """Die Programme-Ordner des Startmenues (Windows): erst der des Nutzers, dann der fuer alle."""
    if sys.platform != "win32":
        return []
    ordner = []
    for var, teil in (("APPDATA", r"Microsoft\Windows\Start Menu\Programs"),
                      ("PROGRAMDATA", r"Microsoft\Windows\Start Menu\Programs")):
        basis = os.environ.get(var)
        if basis:
            ordner.append(Path(basis) / teil)
    return [o for o in ordner if o.is_dir()]


def _lese_cstring(daten: bytes, start: int, unicode: bool) -> str:
    if unicode:
        ende = start
        while ende + 1 < len(daten) and daten[ende:ende + 2] != b"\0\0":
            ende += 2
        return daten[start:ende].decode("utf-16-le", errors="replace")
    ende = daten.find(b"\0", start)
    roh = daten[start:ende if ende >= 0 else len(daten)]
    try:
        return roh.decode("mbcs")  # Windows: Systemcodepage
    except LookupError:
        return roh.decode("cp1252", errors="replace")


def verknuepfung_ziel(pfad: str | Path) -> str | None:
    """Ziel einer Windows-Verknuepfung (.lnk) oder None.

    Liest das Format „Shell Link“ selbst (keine Abhaengigkeit, laeuft ueberall). None, wenn
    die Datei keine lesbare Verknuepfung ist, kein lokales Ziel hat (z. B. Installer-
    Verknuepfungen von MSI) oder Startparameter mitgibt: die gingen mit dem blossen Ziel verloren.
    """
    try:
        daten = Path(pfad).read_bytes()
    except OSError:
        return None
    if len(daten) < 0x4C or struct.unpack_from("<I", daten, 0)[0] != 0x4C:
        return None
    flags = struct.unpack_from("<I", daten, 0x14)[0]
    if flags & 0x20:      # HasArguments
        return None
    if not flags & 0x02:  # HasLinkInfo
        return None
    pos = 0x4C
    try:
        if flags & 0x01:  # HasLinkTargetIDList
            pos += 2 + struct.unpack_from("<H", daten, pos)[0]
        info = pos
        groesse, kopf, info_flags = struct.unpack_from("<III", daten, info)
        if not info_flags & 0x01 or info + groesse > len(daten):  # VolumeIDAndLocalBasePath
            return None
        basis_off, _netz, suffix_off = struct.unpack_from("<III", daten, info + 16)
        if kopf >= 0x24:
            basis_u, suffix_u = struct.unpack_from("<II", daten, info + 28)
            basis = _lese_cstring(daten, info + basis_u, unicode=True)
            suffix = _lese_cstring(daten, info + suffix_u, unicode=True) if suffix_u else ""
        else:
            basis = _lese_cstring(daten, info + basis_off, unicode=False)
            suffix = _lese_cstring(daten, info + suffix_off, unicode=False) if suffix_off else ""
    except struct.error:
        return None
    ziel = basis + suffix
    return ziel or None


def eintragbarer_pfad(pfad: str | Path) -> str:
    """Pfad, der fuer ``pfad`` eingetragen wird: bei einer Verknuepfung ihr Ziel, falls es
    existiert, sonst die Verknuepfung selbst (``starten`` oeffnet auch .lnk)."""
    pfad = Path(pfad)
    if pfad.suffix.lower() == ".lnk":
        ziel = verknuepfung_ziel(pfad)
        if ziel and Path(ziel).is_file():
            return str(Path(ziel))
    return str(pfad)


def _bekannte_programmdateien() -> list[tuple[str, Path]]:
    """Feste Orte bekannter Scanprogramme (falls keine Startmenue-Verknuepfung existiert)."""
    if sys.platform == "win32":
        orte = []
        for var in ("ProgramFiles", "ProgramFiles(x86)"):
            basis = os.environ.get(var)
            if basis:
                orte += [
                    ("VueScan", Path(basis) / "VueScan" / "vuescan.exe"),
                    ("NAPS2", Path(basis) / "NAPS2" / "NAPS2.exe"),
                ]
        system = os.environ.get("SystemRoot")
        if system:
            orte.append(("Windows-Fax und -Scan", Path(system) / "System32" / "WFS.exe"))
        return orte
    if sys.platform == "darwin":
        return [
            ("VueScan", Path("/Applications/VueScan.app")),
            ("NAPS2", Path("/Applications/NAPS2.app")),
            ("Digitale Bilder", Path("/System/Applications/Image Capture.app")),
            ("Digitale Bilder", Path("/Applications/Image Capture.app")),
        ]
    orte = []
    for befehl, name in (("naps2", "NAPS2"), ("simple-scan", "Dokumentenscanner"),
                         ("xsane", "XSane"), ("vuescan", "VueScan")):
        gefunden = shutil.which(befehl)
        if gefunden:
            orte.append((name, Path(gefunden)))
    return orte


def laufende_programme() -> set[str]:
    """Dateinamen (klein) der gerade laufenden Programme; leer, wenn das nicht abfragbar ist."""
    try:
        if sys.platform == "win32":
            ausgabe = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, errors="replace", timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout
            return {zeile.split('","')[0].strip('"').lower() for zeile in ausgabe.splitlines() if zeile}
        ausgabe = subprocess.run(["ps", "-axo", "comm="], capture_output=True, text=True, errors="replace", timeout=5).stdout
        return {Path(zeile.strip()).name.lower() for zeile in ausgabe.splitlines() if zeile.strip()}
    except (OSError, subprocess.SubprocessError):
        return set()


def _laeuft(pfad: Path, laufend: set[str]) -> bool:
    if pfad.suffix.lower() == ".app":  # macOS: ausfuehrbare Datei heisst wie das Paket
        return pfad.stem.lower() in laufend
    return pfad.name.lower() in laufend


def vorschlaege(laufend: set[str] | None = None, ordner: list[Path] | None = None) -> list[Vorschlag]:
    """Gefundene Scanprogramme, laufende zuerst, sonst nach Namen.

    Durchsucht die Startmenue-Ordner nach Verknuepfungen mit Scan-Namen und feste Orte
    bekannter Programme. ``laufend``/``ordner`` sind fuer Tests vorgebbar.
    """
    if laufend is None:
        laufend = laufende_programme()
    if ordner is None:
        ordner = startmenue_ordner()
    kandidaten: list[tuple[str, Path]] = []
    for basis in ordner:
        try:
            for lnk in sorted(basis.rglob("*.lnk")):
                if _sieht_nach_scanprogramm_aus(lnk.stem):
                    kandidaten.append((lnk.stem, lnk))
        except OSError:
            continue
    kandidaten += [(name, p) for name, p in _bekannte_programmdateien() if p.exists()]

    gesehen: set[str] = set()
    ergebnis = []
    for name, quelle in kandidaten:
        pfad = Path(eintragbarer_pfad(quelle))
        schluessel = os.path.normcase(str(pfad))
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        ergebnis.append(Vorschlag(name, str(pfad), _laeuft(pfad, laufend)))
    ergebnis.sort(key=lambda v: (not v.laeuft, v.name.lower()))
    return ergebnis

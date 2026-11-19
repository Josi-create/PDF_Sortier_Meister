"""Hinterlegtes Scanprogramm starten (Issue #270) - Qt-frei.

Der Knopf „Jetzt scannen“ startet nur das Programm, das in den Einstellungen
hinterlegt ist (z. B. VueScan). Gescannt wird dort; die neue Datei erscheint
ueber die Ordner-Beobachtung (Issue #232) von selbst.

GPL-3.0-or-later - Copyright (c) 2026
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

KONFIG_SCHLUESSEL = "scan_programm"


class ScanprogrammFehler(Exception):
    """Das Scanprogramm liess sich nicht starten."""


def bereinigt(pfad: str | None) -> str:
    """Pfad aus der Einstellung ohne Leerraum und umschliessende Anfuehrungszeichen."""
    return (pfad or "").strip().strip('"').strip()


def _vergleichspfad(pfad: str) -> str:
    """Pfad in der Form, in der zwei Angaben derselben Datei gleich aussehen."""
    try:
        pfad = os.path.realpath(pfad)
    except (OSError, ValueError):
        pass
    return os.path.normcase(os.path.abspath(pfad))


def _verknuepfungsziel(datei: Path) -> str:
    """Ziel einer Windows-Verknuepfung (.lnk), sonst der Pfad selbst.

    Laesst sich die Verknuepfung nicht lesen, bleibt es beim Pfad; dann wird
    das Programm wie bisher einfach gestartet.
    """
    if datei.suffix.lower() != ".lnk":
        return str(datei)
    try:
        import win32com.client  # pywin32, unter Windows ohnehin installiert (Issue #9)

        ziel = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(datei)).TargetPath
    except Exception:  # noqa: BLE001 - ohne Ziel einfach starten
        return str(datei)
    return ziel or str(datei)


def _fenster_des_programms_windows(exe: str) -> int | None:
    """Oberstes sichtbares Hauptfenster eines laufenden Prozesses mit dieser exe."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]

    process_query_limited_information = 0x1000
    gw_owner = 4
    gesucht = _vergleichspfad(exe)
    pfade: dict[int, str] = {}
    gefunden: list[int] = []

    def exe_von(pid: int) -> str:
        if pid not in pfade:
            pfade[pid] = ""
            handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
            if handle:
                try:
                    puffer = ctypes.create_unicode_buffer(32768)
                    laenge = wintypes.DWORD(len(puffer))
                    if kernel32.QueryFullProcessImageNameW(handle, 0, puffer, ctypes.byref(laenge)):
                        pfade[pid] = _vergleichspfad(puffer.value)
                finally:
                    kernel32.CloseHandle(handle)
        return pfade[pid]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def je_fenster(hwnd, _lparam):
        # EnumWindows liefert von oben nach unten: das zuletzt benutzte Fenster zuerst
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, gw_owner):
            return True
        if not user32.GetWindowTextLengthW(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value and pid.value != os.getpid() and exe_von(pid.value) == gesucht:
            gefunden.append(hwnd)
            return False
        return True

    user32.EnumWindows(je_fenster, 0)
    return gefunden[0] if gefunden else None


def nach_vorn_holen(datei: Path) -> bool:
    """Holt das Fenster des schon laufenden Programms nach vorn (Issue #337).

    Gibt ``True`` zurueck, wenn ein Fenster gefunden wurde; dann wird nichts
    gestartet. Nur unter Windows: am Mac aktiviert ``open`` eine laufende App
    ohnehin, statt sie ein zweites Mal zu starten. Jeder Fehler hier fuehrt
    zurueck zum normalen Start.
    """
    if sys.platform != "win32":
        return False
    try:
        hwnd = _fenster_des_programms_windows(_verknuepfungsziel(datei))
        if not hwnd:
            return False
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        sw_restore = 9
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, sw_restore)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:  # noqa: BLE001 - im Zweifel wie bisher starten
        return False


def starten(pfad: str | None) -> bool:
    """Startet das Programm unter ``pfad`` und kehrt sofort zurueck.

    Laeuft es schon, wird nur sein Fenster nach vorn geholt (Issue #337); dann
    ist der Rueckgabewert ``True``, nach einem echten Start ``False``.

    Windows: wie ein Doppelklick im Explorer (auch Verknuepfungen .lnk).
    macOS: ein Programmpaket (.app) ueber ``open``. Sonst die Datei direkt.
    """
    pfad = bereinigt(pfad)
    if not pfad:
        raise ScanprogrammFehler("kein Scanprogramm hinterlegt")
    datei = Path(pfad)
    if not datei.exists():
        raise ScanprogrammFehler(f"nicht gefunden: {pfad}")
    if nach_vorn_holen(datei):
        return True
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
    return False

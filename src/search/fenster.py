"""Programme, die die Browser-Oberflaeche oeffnet, nach vorn holen (Windows).

Die Browser-Oberflaeche laeuft als Hintergrundaufgabe (Aufgabenplanung) und nicht
als das Programm, mit dem gerade gearbeitet wird. Programme, die sie startet
(Excel, Word, Mailprogramm, Explorer ...), duerfen ihr Fenster deshalb nicht
selbst in den Vordergrund setzen: Windows laesst nur den Taskleisten-Knopf
blinken, das Fenster bleibt hinter dem Browser. Darum wird das Fenster anhand
seines Titels gesucht und mit ``AttachThreadInput`` aktiviert (aus PDFsuche
uebernommen).

Unter macOS und Linux bringt das System das geoeffnete Programm selbst nach
vorn; dort sind ``sichtbare`` und ``nach_vorn`` ohne Wirkung. Die Win32-
Schnittstelle wird erst beim ersten Gebrauch geladen, der Import gelingt ueberall.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time

from src.utils.platform_paths import open_with_default_app

# Tests schalten es ab (tests/conftest.py), damit kein Test echte Fenster bewegt
AKTIV = sys.platform == "win32"

SW_RESTORE = 9
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002
EXPLORER_KLASSE = "CabinetWClass"     # Ordnerfenster: „<Ordner> – Datei-Explorer“

_api = None


def _winapi():
    """``(user32, kernel32, EnumWindows-Rueckruftyp, wintypes)`` mit Signaturen, beim ersten Gebrauch."""
    global _api
    if _api is None:
        from ctypes import wintypes

        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        enum = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        u32.EnumWindows.argtypes = [enum, wintypes.LPARAM]
        u32.GetForegroundWindow.restype = wintypes.HWND
        for f in (u32.IsWindowVisible, u32.IsIconic, u32.BringWindowToTop, u32.SetForegroundWindow,
                  u32.GetWindowTextLengthW):
            f.argtypes = [wintypes.HWND]
        u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        u32.SwitchToThisWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
        u32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_void_p]
        _api = (u32, k32, enum, wintypes)
    return _api


def _titel(hwnd: int) -> str:
    u32 = _winapi()[0]
    n = u32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    puffer = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(hwnd, puffer, n + 1)
    return puffer.value


def _klasse(hwnd: int) -> str:
    puffer = ctypes.create_unicode_buffer(256)
    _winapi()[0].GetClassNameW(hwnd, puffer, 256)
    return puffer.value


def sichtbare() -> dict[int, str]:
    """Alle sichtbaren Hauptfenster mit Titel: ``{hwnd: titel}`` (ohne Windows: leer)."""
    if not AKTIV:
        return {}
    u32, _, enum, _ = _winapi()
    erg: dict[int, str] = {}

    @enum
    def rueckruf(hwnd, _):
        if u32.IsWindowVisible(hwnd):
            t = _titel(hwnd)
            if t:
                erg[hwnd] = t
        return True

    u32.EnumWindows(rueckruf, 0)
    return erg


def _passt(titel: str, name: str, anfang: bool) -> bool:
    return titel.startswith(name) if anfang else name in titel


def _aktiviere(hwnd: int) -> bool:
    u32, k32, _, wintypes = _winapi()
    if u32.IsIconic(hwnd):
        u32.ShowWindow(hwnd, SW_RESTORE)
    if u32.GetForegroundWindow() == hwnd:
        return True
    eigen = k32.GetCurrentThreadId()
    msg = wintypes.MSG()
    u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)   # legt die eigene Nachrichtenwarteschlange an
    threads = set()
    for h in (u32.GetForegroundWindow(), hwnd):
        if h:
            t = u32.GetWindowThreadProcessId(h, None)
            if t and t != eigen:
                threads.add(t)
    angehaengt = [t for t in threads if u32.AttachThreadInput(t, eigen, True)]
    try:
        u32.BringWindowToTop(hwnd)
        u32.SetForegroundWindow(hwnd)
    finally:
        for t in angehaengt:
            u32.AttachThreadInput(t, eigen, False)
    if u32.GetForegroundWindow() == hwnd:
        return True
    u32.SwitchToThisWindow(hwnd, True)
    if u32.GetForegroundWindow() == hwnd:
        return True
    # Letzter Ausweg: ein simulierter Tastendruck macht diesen Prozess zum „zuletzt eingebenden“
    u32.keybd_event(VK_MENU, 0, 0, None)
    u32.SetForegroundWindow(hwnd)
    u32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, None)
    return u32.GetForegroundWindow() == hwnd


def _warte_und_aktiviere(namen: list[str], vorher: dict[int, str], sekunden: float, anfang: bool,
                         klasse: str | None, neu_frist: float, pause: float = 0.25) -> bool:
    """Wartet auf ein neues Fenster, dessen Titel zu einem der Namen passt, und holt es nach vorn.

    Erscheint innerhalb von ``neu_frist`` keins, genuegt ein schon vorhandenes
    (die Datei war bereits offen). Die Reihenfolge der Namen ist der Vorrang
    (voller Dateiname vor dem Stamm).
    """
    beginn = time.monotonic()
    while True:
        jetzt = sichtbare()
        if klasse:
            jetzt = {h: t for h, t in jetzt.items() if _klasse(h) == klasse}
        for name in namen:
            neu = [h for h, t in jetzt.items() if h not in vorher and _passt(t, name, anfang)]
            if neu:
                return _aktiviere(neu[0])
        if time.monotonic() - beginn > neu_frist:
            for name in namen:
                alt = [h for h, t in jetzt.items() if _passt(t, name, anfang)]
                if alt:
                    return _aktiviere(alt[0])
        if time.monotonic() - beginn > sekunden:
            return False
        time.sleep(pause)


def nach_vorn(namen: list[str], vorher: dict[int, str] | None = None, *, sekunden: float = 15.0,
              anfang: bool = False, klasse: str | None = None, neu_frist: float = 5.0) -> None:
    """Holt im Hintergrund das Fenster nach vorn, dessen Titel einen der Namen enthaelt.

    ``anfang``: der Titel muss mit dem Namen beginnen; ``klasse``: nur Fenster
    dieser Fensterklasse (z. B. ``EXPLORER_KLASSE``).
    """
    namen = [n for n in namen if n]
    if not AKTIV or not namen:
        return
    threading.Thread(target=_warte_und_aktiviere, args=(namen, vorher or {}, sekunden, anfang, klasse, neu_frist),
                     daemon=True, name="fenster-nach-vorn").start()


def starte(pfad: str | os.PathLike, namen: list[str] | None = None) -> None:
    """Datei mit dem Standardprogramm oeffnen und dessen Fenster anschliessend nach vorn holen."""
    pfad = os.fspath(pfad)
    if namen is None:
        name = os.path.basename(pfad)
        namen = [name, os.path.splitext(name)[0]]
    vorher = sichtbare()
    open_with_default_app(pfad)
    nach_vorn(namen, vorher)


def ordner_zeigen(pfad: str, zeigen) -> None:
    """``zeigen(pfad)`` (Datei im Dateimanager markieren) und das Explorer-Fenster des Ordners nach vorn holen."""
    vorher = sichtbare()
    zeigen(pfad)
    nach_vorn([os.path.basename(os.path.dirname(pfad))], vorher, anfang=True, klasse=EXPLORER_KLASSE)

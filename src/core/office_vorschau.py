"""Vorschau fuer .docx/.xlsx (Issue #9) - Qt-frei.

Kachelbild (schnell, ohne Word zu starten), in dieser Reihenfolge:
1. eingebettetes ``docProps/thumbnail.*`` der Datei (``eingebettetes_bild``)
2. Windows-Shell-Vorschaubild (``shell_bild``, IShellItemImageFactory)
3. erste Textzeilen des Dokuments (``erste_zeilen``) - gezeichnet wird in der GUI

Seitenansicht: ``vorschau_pdf`` wandelt die Datei (mit festem Druckdatum, siehe
``office_convert``) in ein temporaeres PDF im Cache-Ordner unter dem
App-Datenordner. Schluessel: Pfad + Aenderungszeit; die Originaldatei bleibt
unberuehrt. Die Zahl der Cache-Dateien ist begrenzt (die aeltesten gehen zuerst).

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path
from typing import Optional

from src.core.office_convert import umwandeln

MAX_CACHE_DATEIEN = 40
_THUMB_NAMEN = ("docProps/thumbnail.jpeg", "docProps/thumbnail.jpg", "docProps/thumbnail.png")


def eingebettetes_bild(pfad: Path | str) -> Optional[bytes]:
    """Bytes des in die Datei eingebetteten Vorschaubilds (jpeg/png), sonst None.

    EMF/WMF-Vorschauen liefert Word nur selten und Qt kann sie nicht darstellen.
    """
    try:
        with zipfile.ZipFile(pfad) as z:
            namen = {n.lower(): n for n in z.namelist()}
            for name in _THUMB_NAMEN:
                if name.lower() in namen:
                    info = z.getinfo(namen[name.lower()])
                    if info.file_size <= 5_000_000:
                        return z.read(info)
    except (OSError, zipfile.BadZipFile, KeyError):
        pass
    return None


def erste_zeilen(pfad: Path | str, anzahl: int = 14, breite: int = 60) -> list[str]:
    """Die ersten nichtleeren Textzeilen (docx: Dokument, xlsx: erstes Blatt)."""
    from src.search.office import office_text

    pfad = Path(pfad)
    fmt = pfad.suffix.lower().lstrip(".")
    try:
        seiten = office_text(str(pfad), fmt).get("seiten") or []
    except Exception:  # noqa: BLE001 - kaputte Datei: einfach kein Text
        return []
    if not seiten:
        return []
    zeilen = [z.strip() for z in str(seiten[0][2]).splitlines() if z.strip()]
    return [z[:breite] for z in zeilen[:anzahl]]


def shell_bild(pfad: Path | str, groesse: int = 256) -> Optional[tuple[int, int, bytes]]:
    """Windows-Shell-Vorschaubild als (Breite, Hoehe, BGRA-Bytes, von oben nach unten).

    Nur echte Vorschauen (kein Dateisymbol); None, wenn es keine gibt oder nicht Windows.
    """
    if sys.platform != "win32":
        return None
    try:
        return _shell_bild_win(str(pfad), groesse)
    except Exception:  # noqa: BLE001 - Shell-Fehler duerfen die Kachel nie verhindern
        return None


def _shell_bild_win(pfad: str, groesse: int) -> Optional[tuple[int, int, bytes]]:
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16),
                    ("d", ctypes.c_ubyte * 8)]

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

    class BITMAP(ctypes.Structure):
        _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long), ("bmHeight", ctypes.c_long),
                    ("bmWidthBytes", ctypes.c_long), ("bmPlanes", ctypes.c_ushort),
                    ("bmBitsPixel", ctypes.c_ushort), ("bmBits", ctypes.c_void_p)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", ctypes.c_ushort), ("biBitCount", ctypes.c_ushort),
                    ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
                    ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]

    # IID_IShellItemImageFactory = {bcc18b79-ba16-442f-80c4-8a59c30c463b}
    iid = GUID(0xBCC18B79, 0xBA16, 0x442F,
               (ctypes.c_ubyte * 8)(0x80, 0xC4, 0x8A, 0x59, 0xC3, 0x0C, 0x46, 0x3B))
    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32
    gdi32 = ctypes.windll.gdi32
    user32 = ctypes.windll.user32
    shell32.SHCreateItemFromParsingName.argtypes = [
        wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    shell32.SHCreateItemFromParsingName.restype = ctypes.c_long
    gdi32.GetObjectW.argtypes = [wintypes.HGDIOBJ, ctypes.c_int, ctypes.c_void_p]
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, ctypes.c_uint, ctypes.c_uint,
                                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]

    hr_init = ole32.CoInitialize(None)  # S_OK / S_FALSE: beides wird mit CoUninitialize ausgeglichen
    try:
        item = ctypes.c_void_p()
        if shell32.SHCreateItemFromParsingName(pfad, None, ctypes.byref(iid), ctypes.byref(item)) != 0:
            return None
        vtbl = ctypes.cast(item, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        get_image = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, SIZE, ctypes.c_int, ctypes.POINTER(wintypes.HBITMAP)
        )(vtbl[3])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
        hbm = wintypes.HBITMAP()
        try:
            # BIGGERSIZEOK (1) | THUMBNAILONLY (8): kein Dateisymbol als "Vorschau"
            hr = get_image(item, SIZE(groesse, groesse), 0x1 | 0x8, ctypes.byref(hbm))
        finally:
            release(item)
        if hr != 0 or not hbm.value:
            return None
        try:
            bm = BITMAP()
            gdi32.GetObjectW(hbm, ctypes.sizeof(BITMAP), ctypes.byref(bm))
            breite, hoehe = bm.bmWidth, abs(bm.bmHeight)
            if breite <= 0 or hoehe <= 0 or breite * hoehe > 4096 * 4096:
                return None
            info = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), breite, -hoehe, 1, 32, 0)
            puffer = ctypes.create_string_buffer(breite * hoehe * 4)
            hdc = user32.GetDC(None)
            try:
                zeilen = gdi32.GetDIBits(hdc, hbm, 0, hoehe, puffer, ctypes.byref(info), 0)
            finally:
                user32.ReleaseDC(None, hdc)
            if zeilen != hoehe:
                return None
            return breite, hoehe, puffer.raw
        finally:
            gdi32.DeleteObject(hbm)
    finally:
        if hr_init in (0, 1):
            ole32.CoUninitialize()


# --- Seitenansicht (temporaeres PDF) -------------------------------------------

def vorschau_cache_ordner() -> Path:
    from src.utils.platform_paths import get_app_data_dir

    ordner = get_app_data_dir() / "office_vorschau"
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


def _cache_praefix(quelle: Path) -> str:
    return hashlib.sha1(str(quelle.resolve()).lower().encode("utf-8")).hexdigest()[:16]


def cache_pfad(quelle: Path | str, cache_dir: Path | None = None) -> Path:
    """Cache-PDF fuer diese Datei in ihrem jetzigen Zustand (Pfad + Aenderungszeit)."""
    quelle = Path(quelle)
    cache_dir = cache_dir or vorschau_cache_ordner()
    return cache_dir / f"{_cache_praefix(quelle)}_{quelle.stat().st_mtime_ns}.pdf"


def vorschau_pdf(quelle: Path | str, cache_dir: Path | None = None,
                 max_dateien: int = MAX_CACHE_DATEIEN) -> Path:
    """Temporaeres Vorschau-PDF (aus dem Cache oder frisch umgewandelt).

    Die Quelle wird nur gelesen. Veraltete Eintraege derselben Datei werden
    entfernt, der Cache auf ``max_dateien`` begrenzt.

    Raises:
        UmwandlungFehler / KeinUmwandlerGefunden: siehe ``office_convert.umwandeln``
    """
    quelle = Path(quelle)
    cache_dir = cache_dir or vorschau_cache_ordner()
    cache_dir.mkdir(parents=True, exist_ok=True)
    ziel = cache_pfad(quelle, cache_dir)
    if ziel.exists() and ziel.stat().st_size > 0:
        ziel.touch()  # zuletzt benutzt
        return ziel
    ziel.unlink(missing_ok=True)
    erg = umwandeln(quelle, ziel)
    for alt in cache_dir.glob(f"{_cache_praefix(quelle)}_*.pdf"):
        if alt != erg.pdf:
            alt.unlink(missing_ok=True)
    _aufraeumen(cache_dir, max_dateien)
    return erg.pdf


def _aufraeumen(cache_dir: Path, max_dateien: int) -> None:
    dateien = sorted(cache_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    for alt in dateien[max_dateien:]:
        try:
            alt.unlink()
        except OSError:
            pass


def vorschau_loeschen(quelle: Path | str, cache_dir: Path | None = None) -> None:
    """Entfernt alle Cache-Eintraege dieser Datei (z. B. nach dem Loeschen)."""
    quelle = Path(quelle)
    cache_dir = cache_dir or vorschau_cache_ordner()
    for alt in cache_dir.glob(f"{_cache_praefix(quelle)}_*.pdf"):
        try:
            alt.unlink()
        except OSError:
            pass


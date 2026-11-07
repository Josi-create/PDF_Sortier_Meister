"""Schief gescannte Seiten gerade ausrichten (Issue #165, Qt-frei).

**Messen** (``seite_messen``): Die Seite wird in Graustufen gerendert, wie
sie angezeigt wird. Ihre dunklen Pixel werden fuer jeden Winkel zwischen
-10 und +10 Grad auf eine Achse projiziert (Projektionsprofil). Liegen
Textzeilen genau quer zur Achse, wechseln volle Zeilen und leere
Zeilenabstaende hart; das Profil ist dann am schaerfsten (Summe der
quadrierten Unterschiede benachbarter Werte). Gemessen wird in beiden
Richtungen, damit auch quer liegende Seiten (Issue #151) ihren Winkel
bekommen. Eine Seite ohne deutliches Linienmuster (Foto, leere Seite, wenige
Zeichen) bekommt keinen Winkel. Tesseract braucht es dafuer nicht: Die
meisten Scans bringen die Textebene des Scanprogramms schon mit.

**Ausrichten** (``ausrichten``): Der ganze bisherige Seiteninhalt wird in
``q <Drehung um die Seitenmitte> cm ... Q`` eingeschlossen; dazu kommen zwei
eigene, kleine Inhalts-Streams vorn und hinten. Bild-Streams und bisherige
Inhalts-Streams bleiben bytegleich (nichts wird neu gerendert oder
komprimiert), eine vorhandene Textebene dreht mit und bleibt deckungsgleich.
Die Seite behaelt ihre Groesse; die Ecken des Scans ragen um den kleinen
Winkel ueber den Rand. Der vordere Stream beginnt mit einem Kommentar
(``MARKE`` und Winkel); daran erkennt PDFSM eine schon ausgerichtete Seite und
kann die Ausrichtung wieder entfernen (``ausrichtung_entfernen``).

Winkel sind in Grad gegen den Uhrzeigersinn, wie man die angezeigte Seite
drehen muss, damit sie gerade steht. Die Seitendrehung (``/Rotate``) aendert
daran nichts.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import math
import re

MESS_DPI = 100          # Aufloesung fuer die Messung (0,1 Grad sind bei A4 gut 1 Pixel ueber die Breite)
MIN_WINKEL = 0.3        # kleinere Schraeglagen sieht man kaum; dafuer wird keine Datei geaendert
MAX_WINKEL = 10.0       # Suchbereich; groessere Lagen sind kein schiefer Scan (dafuer gibt es Drehen)
GROB = 0.25             # Schrittweite der ersten Suche (Grad)
FEIN = 0.02             # Schrittweite der Verfeinerung um das beste grobe Ergebnis
MIN_PUNKTE = 1500       # weniger dunkle Pixel: zu wenig Schrift fuer eine verlaessliche Messung
MAX_PUNKTE = 150_000    # mehr werden gleichmaessig ausgeduennt (Rechenzeit)
MAX_DUNKEL = 0.35       # mehr dunkle Flaeche: Foto oder Grafik, keine Textseite
MIN_SCHAERFE = 1.5      # bester Winkel mindestens so viel schaerfer als der typische: sonst kein Muster
SCAN_ANTEIL = 0.5       # ein Bild bedeckt mindestens diesen Teil der Seite: gescannte Seite

MARKE = b"%PDFSM gerade "                 # Anfang des vorderen Streams, danach der Winkel
ENDE = b"\nQ\n%PDFSM gerade Ende\n"        # der hintere Stream
_WINKEL = re.compile(rb"^%PDFSM gerade (-?\d+(?:\.\d+)?)\s")


# =========================================================================== Messen

def schraeglage(grau) -> float | None:
    """Winkel (Grad, gegen den Uhrzeigersinn), um den das Graustufenbild gedreht gerade steht.

    ``grau``: 2D-Array (Zeilen x Spalten, 0 = schwarz), wie die Seite angezeigt
    wird. None, wenn das Bild kein deutliches Zeilenmuster hat. Kleine Winkel
    unter ``MIN_WINKEL`` kommen als gemessener Wert zurueck; ob sich das
    Ausrichten lohnt, entscheidet ``lohnt``.
    """
    import numpy as np

    a = np.asarray(grau)
    if a.ndim != 2 or a.shape[0] < 50 or a.shape[1] < 50:
        return None
    median = float(np.median(a))
    grenze = median - max(40.0, 0.35 * median)
    dunkel = a < grenze
    n = int(dunkel.sum())
    if n < MIN_PUNKTE or n > MAX_DUNKEL * a.size:
        return None
    ys, xs = np.nonzero(dunkel)
    if n > MAX_PUNKTE:
        schritt = n // MAX_PUNKTE + 1
        ys, xs = ys[::schritt], xs[::schritt]
    y = ys.astype(np.float64) - a.shape[0] / 2
    x = xs.astype(np.float64) - a.shape[1] / 2

    def schaerfe(werte, quer, winkel: float) -> float:
        p = werte + quer * math.tan(math.radians(winkel))
        h = np.bincount(np.rint(p - p.min()).astype(np.int64))
        d = np.diff(h.astype(np.float64))
        return float(np.dot(d, d))

    grob = np.arange(-MAX_WINKEL, MAX_WINKEL + GROB / 2, GROB)
    beste = None
    # Zeilen waagerecht: y - x*tan(w) wird scharf; Zeilen senkrecht (Seite liegt quer): x + y*tan(w)
    for werte, quer in ((y, -x), (x, y)):
        s = np.array([schaerfe(werte, quer, w) for w in grob])
        typisch = float(np.median(s))
        i = int(np.argmax(s))
        if typisch <= 0:
            continue
        verhaeltnis = s[i] / typisch
        if beste is None or verhaeltnis > beste[0]:
            beste = (verhaeltnis, float(grob[i]), werte, quer)
    if beste is None or beste[0] < MIN_SCHAERFE:
        return None
    _v, mitte, werte, quer = beste
    if abs(mitte) >= MAX_WINKEL - GROB / 2:
        return None                 # am Rand des Suchbereichs: keine Schraeglage, sondern etwas anderes
    fein = np.arange(mitte - GROB, mitte + GROB + FEIN / 2, FEIN)
    s = [schaerfe(werte, quer, w) for w in fein]
    return round(float(fein[int(np.argmax(s))]), 2)


def lohnt(winkel: float | None) -> bool:
    """Lohnt sich das Ausrichten (deutlich schief, aber im Suchbereich)?"""
    return winkel is not None and MIN_WINKEL <= abs(winkel) < MAX_WINKEL


def ist_scan(seite) -> bool:
    """Bedeckt ein Bild (auch ein Inline-Bild) mindestens ``SCAN_ANTEIL`` der Seite?"""
    try:
        flaeche = abs(seite.rect)
        if not flaeche:
            return False
        for info in seite.get_image_info():
            import pymupdf

            r = pymupdf.Rect(info["bbox"]) & seite.rect
            if not r.is_empty and abs(r) >= SCAN_ANTEIL * flaeche:
                return True
    except Exception:
        return False
    return False


def seite_messen(seite, dpi: int = MESS_DPI) -> float | None:
    """Schraeglage einer PDF-Seite (PyMuPDF), so wie sie angezeigt wird; None ohne deutliches Zeilenmuster."""
    import numpy as np
    import pymupdf

    pix = seite.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    bild = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
    return schraeglage(bild)


# =========================================================================== Ausrichten

def _box(doc, xref: int, name: str) -> tuple[float, float, float, float] | None:
    """``/CropBox`` bzw. ``/MediaBox`` einer Seite, auch vom Pages-Knoten geerbt (PDF-Koordinaten)."""
    gesehen = set()
    while xref and xref not in gesehen:
        gesehen.add(xref)
        art, wert = doc.xref_get_key(xref, name)
        if art == "array":
            zahlen = [float(z) for z in wert.strip("[]").split()]
            if len(zahlen) == 4:
                x0, y0, x1, y1 = zahlen
                return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
        art, wert = doc.xref_get_key(xref, "Parent")
        xref = int(wert.split()[0]) if art == "xref" else 0
    return None


def _sichtbereich(doc, seite) -> tuple[float, float, float, float]:
    """Sichtbarer Bereich der Seite in PDF-Koordinaten (CropBox, sonst MediaBox)."""
    box = _box(doc, seite.xref, "CropBox") or _box(doc, seite.xref, "MediaBox")
    if box is None:
        r = seite.rect
        return 0.0, 0.0, r.width, r.height
    return box


def ausrichtung(doc, seite) -> float:
    """Winkel, um den PDFSM die Seite schon ausgerichtet hat (aeusserste Ausrichtung), sonst 0."""
    try:
        inhalte = seite.get_contents()
        if not inhalte:
            return 0.0
        m = _WINKEL.match(doc.xref_stream(inhalte[0]) or b"")
        return float(m.group(1)) if m else 0.0
    except Exception:
        return 0.0


def ist_ausgerichtet(doc, seite) -> bool:
    try:
        inhalte = seite.get_contents()
        return bool(inhalte) and (doc.xref_stream(inhalte[0]) or b"").startswith(MARKE)
    except Exception:
        return False


def _inhalte_setzen(doc, seite, xrefs: list[int]) -> None:
    doc.xref_set_key(seite.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in xrefs) + "]")


def _neuer_stream(doc, daten: bytes) -> int:
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, daten, compress=0)
    return xref


def matrix(winkel: float, box: tuple[float, float, float, float]) -> tuple[float, ...]:
    """``cm``-Matrix: Drehung um ``winkel`` Grad gegen den Uhrzeigersinn um die Mitte von ``box``."""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    r = math.radians(winkel)
    c, s = math.cos(r), math.sin(r)
    return c, s, -s, c, cx - (c * cx - s * cy), cy - (s * cx + c * cy)


def ausrichten(doc, seite, winkel: float) -> None:
    """Den ganzen Seiteninhalt um ``winkel`` Grad (gegen den Uhrzeigersinn) um die Seitenmitte drehen.

    Haengt zwei neue Inhalts-Streams vorn und hinten an; die bisherigen
    bleiben unveraendert. Ist die Seite schon ausgerichtet, kommt eine weitere
    Ausrichtung aussen herum (die gemessene Restschraeglage).
    """
    a, b, c, d, e, f = matrix(winkel, _sichtbereich(doc, seite))
    vorn = (MARKE + f"{winkel:.2f}\n".encode()
            + f"q {a:.6f} {b:.6f} {c:.6f} {d:.6f} {e:.4f} {f:.4f} cm\n".encode())
    inhalte = list(seite.get_contents())
    _inhalte_setzen(doc, seite, [_neuer_stream(doc, vorn), *inhalte, _neuer_stream(doc, ENDE)])


def ausrichtung_entfernen(doc, seite) -> bool:
    """Die aeusserste Ausrichtung von PDFSM wieder entfernen. False, wenn es keine gibt.

    Kam danach etwas hinter den hinteren Stream (z. B. eine Textebene), geht
    das nicht mehr sauber; auch dann False.
    """
    inhalte = list(seite.get_contents())
    if len(inhalte) < 2 or not ist_ausgerichtet(doc, seite):
        return False
    if (doc.xref_stream(inhalte[-1]) or b"") != ENDE:
        return False
    _inhalte_setzen(doc, seite, inhalte[1:-1])
    return True


def eigene_streams(doc, seite) -> set[int]:
    """Die Inhalts-Streams, die ``ausrichten`` angelegt hat (fuer Bild-Hash und Pruefung)."""
    erg: set[int] = set()
    try:
        for x in seite.get_contents():
            daten = doc.xref_stream(x) or b""
            if daten.startswith(MARKE) or daten == ENDE:
                erg.add(x)
    except Exception:
        pass
    return erg

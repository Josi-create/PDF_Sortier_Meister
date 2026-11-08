"""Fotografierte Dokumente entzerren (Issue #205) - Qt-frei, nur numpy, scipy und Pillow.

Ablauf
------
1. **Blatt finden** (``blatt_finden``): Das Foto wird auf ``ERKENNUNG_PX`` verkleinert.
   Zwei klassische Wege suchen die Blattflaeche:

   * *Helligkeit*: helle, wenig gesaettigte Pixel (Otsu-Schwelle auf dem geglaetteten
     Grauwert) bilden die Papierkarte; Oeffnen und Schliessen entfernen Bruecken und
     Textloecher, die groesste Komponente mit gefuellten Loechern ist das Blatt.
   * *Kanten*: Die Kantenstaerke (Sobel) wird schwellenwertig, geschlossen und gefuellt;
     das findet auch helles Papier auf hellem Untergrund, wenn der Rand sichtbar ist.

   Aus der konvexen Huelle der Flaeche wird ein Viereck gebildet: Die vier Extrempunkte
   (oben links, oben rechts, unten rechts, unten links) sind der Start, dann wird je eine
   Gerade an die Huellenpunkte jeder Seite gelegt und es werden die Schnittpunkte genommen.

2. **Konfidenz**: Der schwaechste von sechs Werten (Flaechenanteil, Fuellung der Huelle,
   Huelle gegen Viereck, Winkel, Seitenverhaeltnis der Gegenseiten, Kontrast am Rand), 0 bis 1. Ab
   ``KONFIDENZ_SICHER`` gilt das Ergebnis als sicher. Der bessere der beiden Wege gewinnt.

3. **Entzerren** (``entzerrte_seite``): perspektivische Abbildung des Vierecks auf ein
   Rechteck. Das Seitenverhaeltnis kommt aus den Kanten (mit Perspektivkorrektur nach Zhang
   und He, Rueckfall: Mittel der Gegenseiten). Liegt es nah an A4, A5 oder Letter, wird das
   genaue Format genommen (hoch oder quer), sonst bleibt das gemessene Verhaeltnis.

4. **Tonwerte**: Beleuchtung ausgleichen (Teilen durch eine weichgezeichnete Hintergrund-
   schaetzung), Papier weiss, Schrift kraeftig; "farbe" laesst Stempel, Unterschriften und
   Logos farbig, "grau" und "sw" (Schwarzweiss) fassen zusammen.

Alle Schwellen stehen als benannte Konstanten oben, damit sie mit echten Fotos
abgestimmt werden koennen (``tools/entzerren_pruefen.py``).

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import io
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from scipy import ndimage

# --- Erkennung -----------------------------------------------------------------
ERKENNUNG_PX = 800          # laengste Seite beim Suchen des Blatts
SAETTIGUNG_MAX = 0.45       # staerker gesaettigte Pixel (Holz, Haut) gelten nicht als Papier
GLAETTUNG = 2.0             # Gauss-Sigma vor der Schwelle (Pixel bei ERKENNUNG_PX)
OEFFNEN_PX = 4              # Oeffnen: trennt Brucken zum Untergrund
SCHLIESSEN_PX = 9           # Schliessen: schliesst Textzeilen und kleine Luecken
KANTEN_ANTEIL = 0.08        # Kantenschwelle: Anteil des 99,5-%-Wertes der Kantenstaerke
KANTEN_MIN = 3.5            # ... mindestens (Grauwertstufen)
KANTEN_SCHLIESSEN = 4       # Kantenring: so viele Pixel aufweiten, fuellen, zuruecknehmen
MIN_KOMPONENTE = 0.04       # kleinere Flaeche (Anteil am Bild): kein Blatt gefunden

# --- Konfidenz -----------------------------------------------------------------
KONFIDENZ_SICHER = 0.6      # ab hier gilt die Erkennung als sicher
MIN_FLAECHE = 0.12          # Blatt kleiner (Anteil am Bild): Konfidenz 0
GUTE_FLAECHE = 0.25         # ab hier voller Wert fuer die Groesse
VOLL_FLAECHE = 0.92         # fast das ganze Bild: nur noch abnehmender Wert ...
MAX_FLAECHE = 0.99          # ... ab hier 0,3 (vermutlich gar kein Blatt gefunden)
MIN_FUELLUNG = 0.70         # Flaeche / Huelle: darunter 0
GUTE_FUELLUNG = 0.90
MIN_VIERECK = 0.80          # Huelle / Viereck (bzw. umgekehrt): darunter 0
GUTES_VIERECK = 0.95
WINKEL_GUT = (65.0, 115.0)  # Innenwinkel des Vierecks: hier voller Wert
WINKEL_GRENZE = (45.0, 135.0)  # ausserhalb: 0
MAX_SEITENVERHAELTNIS = (1.8, 3.0)  # Gegenseiten: bis 1,8 voller Wert, ab 3,0 gleich 0
RAND_ABSTAND = 5            # Randkontrast: so viele Pixel innen und aussen der Viereckseite vergleichen
RAND_KONTRAST = (4.0, 12.0)  # mittlerer Helligkeitsunterschied am Rand: bis 4 gleich 0, ab 12 voller Wert

# --- Seitenformat und Ausgabe ------------------------------------------------------
FORMATE = (("A4", 210.0, 297.0), ("A5", 148.5, 210.0), ("Letter", 215.9, 279.4))  # mm; A5 = A4-Verhaeltnis
FORMAT_TOLERANZ = 0.08      # Abweichung des Verhaeltnisses, bis zu der das Format einrastet
ZIEL_DPI = 250              # Ausgabeaufloesung bezogen auf das Seitenformat
MIN_DPI = 100               # darunter nie zurueckrechnen (sehr kleine Quellen bleiben unscharf, aber nicht riesig)
BRENNWEITE_STANDARD = 0.8   # angenommene Brennweite (Anteil der langen Bildseite), wenn sie sich nicht messen laesst
BRENNWEITE_BEREICH = (0.4, 2.5)  # glaubwuerdige gemessene Brennweite (Anteil der langen Bildseite)
BESCHNITT = 0.006           # Anteil der Seitenlaenge, den das Ergebnis innen beschnitten wird (Randsaum vom Untergrund)
BOX_MM = (210.0, 297.0)     # Seiten mit unbekanntem Format passen in diesen Kasten (hoch oder quer)

# --- Tonwerte ------------------------------------------------------------------------
TONWERTE = ("farbe", "grau", "sw")
TONWERT_STANDARD = "farbe"
TONWERT_NAMEN = {"farbe": "Farbe aufgehellt", "grau": "Graustufen", "sw": "Schwarzweiß"}
HINTERGRUND_PX = 400        # laengste Seite der Hintergrundschaetzung
HINTERGRUND_FENSTER = 0.04  # Schliessfenster (Anteil der langen Seite): groesser als jeder Strich
HINTERGRUND_GROB = 0.30     # Fenster der groben Schaetzung (Anteil der langen Seite)
GROB_ANTEIL = 0.85          # Beleuchtung mindestens so hell wie dieser Teil der groben Schaetzung
HINTERGRUND_MIN = 0.15      # Beleuchtung nie dunkler annehmen (Division)
PAPIER_WEISS = 0.92         # ab diesem Wert (nach dem Ausgleich) ist Papier reinweiss
PAPIER_PROZENT = 0.9        # Pixel mit mindestens diesem Anteil der Beleuchtung gelten als Papier (Weissabgleich)
SCHRIFT_GAMMA = 1.3         # kraeftigere Schrift (>1 dunkelt Mitteltoene ab)
SW_SCHWELLE = 0.62          # Schwarzweiss: dunkler als dieser Wert (nach dem Ausgleich) ist schwarz
JPEG_QUALITAET = 88


@dataclass
class Erkennung:
    """Ergebnis von ``blatt_finden``; Ecken in Pixeln des untersuchten Bildes."""

    ecken: list[tuple[float, float]]   # oben links, oben rechts, unten rechts, unten links
    konfidenz: float
    sicher: bool
    methode: str = "keine"             # "helligkeit" | "kanten" | "keine"
    gruende: list[str] = field(default_factory=list)  # was die Konfidenz drueckt
    dauer: float = 0.0


@dataclass
class Entzerrung:
    """Auftrag fuer ``bilder_in_pdf``: Ecken (Pixel des ausgerichteten Fotos) und Tonwerte."""

    ecken: list[tuple[float, float]]
    tonwerte: str = TONWERT_STANDARD


# =========================================================================== Laden

def bild_laden(pfad: Path | str):
    """Foto als RGB-Bild, EXIF-Ausrichtung angewandt (HEIC mit ``pillow-heif``)."""
    from PIL import Image, ImageOps

    from src.core.bild_convert import heif_verfuegbar

    heif_verfuegbar()  # meldet den HEIC-Leser an, falls installiert
    with Image.open(pfad) as im:
        im.load()
        bild = ImageOps.exif_transpose(im)
        if bild.mode in ("RGBA", "LA", "PA") or "transparency" in bild.info:
            rgba = bild.convert("RGBA")
            flaeche = Image.new("RGB", rgba.size, "white")
            flaeche.paste(rgba, mask=rgba.getchannel("A"))
            return flaeche
        return bild.convert("RGB")


def standard_ecken(breite: float, hoehe: float, einzug: float = 0.05) -> list[tuple[float, float]]:
    """Ecken leicht eingerueckt an den Bildecken (Vorbelegung ohne Erkennung)."""
    ex, ey = breite * einzug, hoehe * einzug
    return [(ex, ey), (breite - ex, ey), (breite - ex, hoehe - ey), (ex, hoehe - ey)]


# =========================================================================== Erkennen

def _klein(bild, max_px: int):
    """(RGB-Array float 0..255, Faktor Original/klein)."""
    from PIL import Image

    faktor = max(bild.size) / max_px if max(bild.size) > max_px else 1.0
    if faktor > 1.0:
        groesse = (max(1, round(bild.width / faktor)), max(1, round(bild.height / faktor)))
        klein = bild.convert("RGB").resize(groesse, Image.Resampling.BOX if faktor >= 2 else Image.Resampling.BILINEAR)
    else:
        klein = bild.convert("RGB")
    return np.asarray(klein, dtype=np.float32), faktor


def _otsu(werte: np.ndarray) -> float:
    hist, kanten = np.histogram(werte, bins=256, range=(0, 256))
    mitte = (kanten[:-1] + kanten[1:]) / 2
    gesamt = hist.sum()
    if gesamt == 0:
        return 128.0
    w0 = np.cumsum(hist)
    w1 = gesamt - w0
    m0 = np.cumsum(hist * mitte) / np.maximum(w0, 1)
    mges = (hist * mitte).sum()
    m1 = (mges - np.cumsum(hist * mitte)) / np.maximum(w1, 1)
    zwischen = w0 * w1 * (m0 - m1) ** 2
    return float(mitte[int(np.argmax(zwischen))])


def _groesste_komponente(maske: np.ndarray) -> Optional[np.ndarray]:
    beschriftet, n = ndimage.label(maske)
    if n == 0:
        return None
    groessen = ndimage.sum(maske, beschriftet, index=np.arange(1, n + 1))
    return beschriftet == (int(np.argmax(groessen)) + 1)


def _quadrat(n: int) -> np.ndarray:
    return np.ones((n, n), dtype=bool)


def _karte_helligkeit(rgb: np.ndarray) -> Optional[np.ndarray]:
    grau = rgb.mean(axis=2)
    voll = rgb.max(axis=2)
    saettigung = (voll - rgb.min(axis=2)) / np.maximum(voll, 1.0)
    glatt = ndimage.gaussian_filter(grau, GLAETTUNG)
    schwelle = _otsu(glatt)
    maske = (glatt > schwelle) & (ndimage.gaussian_filter(saettigung, GLAETTUNG) < SAETTIGUNG_MAX)
    maske = ndimage.binary_opening(maske, _quadrat(OEFFNEN_PX))
    maske = ndimage.binary_closing(maske, _quadrat(SCHLIESSEN_PX))
    komponente = _groesste_komponente(maske)
    return None if komponente is None else ndimage.binary_fill_holes(komponente)


def _karte_kanten(rgb: np.ndarray) -> Optional[np.ndarray]:
    glatt = ndimage.gaussian_filter(rgb, (1.5, 1.5, 0))
    staerke = np.zeros(rgb.shape[:2], dtype=np.float32)
    for k in range(3):
        gx = ndimage.sobel(glatt[:, :, k], axis=1) / 8.0
        gy = ndimage.sobel(glatt[:, :, k], axis=0) / 8.0
        staerke = np.maximum(staerke, np.hypot(gx, gy))
    schwelle = max(KANTEN_MIN, KANTEN_ANTEIL * float(np.percentile(staerke, 99.5)))
    kanten = staerke > schwelle
    n = KANTEN_SCHLIESSEN
    maske = ndimage.binary_dilation(kanten, _quadrat(2 * n + 1))
    maske = ndimage.binary_fill_holes(maske)
    maske = ndimage.binary_erosion(maske, _quadrat(2 * n + 1))
    maske = ndimage.binary_opening(maske, _quadrat(OEFFNEN_PX))
    komponente = _groesste_komponente(maske)
    return None if komponente is None else ndimage.binary_fill_holes(komponente)


def _huelle(maske: np.ndarray) -> Optional[np.ndarray]:
    """Eckpunkte (x, y) der konvexen Huelle der Maske, gegen den Uhrzeigersinn."""
    from scipy.spatial import ConvexHull, QhullError

    rand = maske & ~ndimage.binary_erosion(maske)
    ys, xs = np.nonzero(rand)
    if len(xs) < 10:
        return None
    punkte = np.column_stack([xs, ys]).astype(np.float64)
    try:
        h = ConvexHull(punkte)
    except QhullError:
        return None
    return punkte[h.vertices]


def _flaeche(poly: np.ndarray) -> float:
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _extreme(punkte: np.ndarray) -> np.ndarray:
    """Start-Viereck: oben links, oben rechts, unten rechts, unten links."""
    s = punkte[:, 0] + punkte[:, 1]
    d = punkte[:, 0] - punkte[:, 1]
    return np.array([punkte[np.argmin(s)], punkte[np.argmax(d)], punkte[np.argmax(s)], punkte[np.argmin(d)]])


def _verdichten(huelle: np.ndarray, schritt: float = 2.0) -> np.ndarray:
    teile = []
    for i in range(len(huelle)):
        a, b = huelle[i], huelle[(i + 1) % len(huelle)]
        n = max(1, int(np.hypot(*(b - a)) / schritt))
        t = np.arange(n) / n
        teile.append(a + np.outer(t, b - a))
    return np.vstack(teile)


def _gerade_anpassen(punkte: np.ndarray):
    """(Punkt, Richtung) der Ausgleichsgeraden (kleinste Abstandsquadrate)."""
    mitte = punkte.mean(axis=0)
    _, _, vt = np.linalg.svd(punkte - mitte, full_matrices=False)
    return mitte, vt[0]


def _schnitt(g1, g2) -> Optional[np.ndarray]:
    p, r = g1
    q, s = g2
    nenner = r[0] * s[1] - r[1] * s[0]
    if abs(nenner) < 1e-6:
        return None
    t = ((q[0] - p[0]) * s[1] - (q[1] - p[1]) * s[0]) / nenner
    return p + t * r


def _viereck(huelle: np.ndarray) -> np.ndarray:
    """Vier Ecken (oben links, oben rechts, unten rechts, unten links) aus der Huelle."""
    ecken = _extreme(huelle)
    dicht = _verdichten(huelle)
    for _ in range(3):
        geraden = []
        for i in range(4):
            a, b = ecken[i], ecken[(i + 1) % 4]
            ab = b - a
            laenge2 = float(np.dot(ab, ab))
            if laenge2 < 1.0:
                return ecken
            t = np.clip(((dicht - a) @ ab) / laenge2, 0, 1)
            abstand = np.hypot(*(dicht - (a + np.outer(t, ab))).T)
            # Seite i: Punkte, die ihr naeher sind als jeder anderen Seite (nicht in den Ecken)
            geraden.append((t, abstand))
        zuordnung = np.argmin(np.vstack([g[1] for g in geraden]), axis=0)
        neu = []
        for i in range(4):
            t = geraden[i][0]
            wahl = (zuordnung == i) & (t > 0.1) & (t < 0.9)
            if wahl.sum() < 3:
                return ecken
            pts = dicht[wahl]
            p, r = _gerade_anpassen(pts)
            res = np.abs((pts - p) @ np.array([-r[1], r[0]]))
            behalten = res <= 2 * np.median(res) + 2.0  # Ausreisser (Finger, Schatten) weglassen
            if behalten.sum() >= 3:
                p, r = _gerade_anpassen(pts[behalten])
            neu.append((p, r))
        ecken_neu = []
        for i in range(4):
            ecke = _schnitt(neu[i - 1], neu[i])  # Ecke i = Schnitt der Seiten i-1 und i
            if ecke is None:
                return ecken
            ecken_neu.append(ecke)
        ecken = np.array(ecken_neu)
    return ecken


def _winkel(ecken: np.ndarray) -> list[float]:
    werte = []
    for i in range(4):
        a = ecken[i - 1] - ecken[i]
        b = ecken[(i + 1) % 4] - ecken[i]
        c = float(np.dot(a, b) / (np.hypot(*a) * np.hypot(*b) + 1e-9))
        werte.append(math.degrees(math.acos(max(-1.0, min(1.0, c)))))
    return werte


def _konvex(ecken: np.ndarray) -> bool:
    vorzeichen = []
    for i in range(4):
        a = ecken[(i + 1) % 4] - ecken[i]
        b = ecken[(i + 2) % 4] - ecken[(i + 1) % 4]
        vorzeichen.append(a[0] * b[1] - a[1] * b[0] > 0)
    return all(vorzeichen) or not any(vorzeichen)


def _rampe(wert: float, null: float, eins: float) -> float:
    """0 bei ``null``, 1 bei ``eins``, dazwischen linear (auch absteigend)."""
    if eins == null:
        return 1.0 if wert >= eins else 0.0
    return float(min(1.0, max(0.0, (wert - null) / (eins - null))))


def _randkontrast(grau: np.ndarray, ecken: np.ndarray) -> Optional[float]:
    """Mittlerer Helligkeitsunterschied innen/aussen entlang der Viereckseiten (nur innerhalb des Bildes).

    None, wenn keine Seite im Bild liegt (Blatt fuellt das Bild). Ein Blatt hat einen scharfen Rand,
    ein Schwellenschnitt durch einen weichen Verlauf nicht.
    """
    h, b = grau.shape
    mittel = ecken.mean(axis=0)
    werte = []
    for i in range(4):
        a, c = ecken[i], ecken[(i + 1) % 4]
        richtung = c - a
        laenge = float(np.hypot(*richtung))
        if laenge < 10:
            continue
        normale = np.array([-richtung[1], richtung[0]]) / laenge
        if np.dot(normale, mittel - (a + c) / 2) < 0:
            normale = -normale  # zeigt ins Innere
        t = np.linspace(0.1, 0.9, 25)[:, None]
        punkte = a + t * richtung
        innen, aussen = punkte + RAND_ABSTAND * normale, punkte - RAND_ABSTAND * normale
        ok = ((aussen[:, 0] >= 0) & (aussen[:, 0] <= b - 1) & (aussen[:, 1] >= 0) & (aussen[:, 1] <= h - 1)
              & (innen[:, 0] >= 0) & (innen[:, 0] <= b - 1) & (innen[:, 1] >= 0) & (innen[:, 1] <= h - 1))
        if ok.sum() < 5:
            continue
        vi = ndimage.map_coordinates(grau, [innen[ok, 1], innen[ok, 0]], order=1)
        va = ndimage.map_coordinates(grau, [aussen[ok, 1], aussen[ok, 0]], order=1)
        werte.append(float(np.median(np.abs(vi - va))))
    return float(np.mean(werte)) if werte else None


def _bewerten(maske: np.ndarray, ecken: np.ndarray, huelle: np.ndarray, groesse: tuple[int, int],
              grau: Optional[np.ndarray] = None) -> tuple[float, list[str]]:
    """Konfidenz 0..1 (schwaechstes Glied) und die Gruende fuer Abzuege."""
    hoehe, breite = groesse
    gruende: list[str] = []
    teile: dict[str, float] = {}
    if not _konvex(ecken):
        return 0.0, ["Viereck nicht konvex"]
    anteil = _flaeche(ecken) / (breite * hoehe)
    if anteil <= VOLL_FLAECHE:
        teile["Blattgröße"] = min(_rampe(anteil, MIN_FLAECHE, GUTE_FLAECHE), 1.0)
    else:
        teile["Blattgröße"] = 1.0 - 0.7 * _rampe(anteil, VOLL_FLAECHE, MAX_FLAECHE)
    hflaeche = _flaeche(huelle)
    teile["Fuellung"] = _rampe(float(maske.sum()) / max(hflaeche, 1.0), MIN_FUELLUNG, GUTE_FUELLUNG)
    verh = hflaeche / max(_flaeche(ecken), 1.0)
    teile["Viereck"] = _rampe(min(verh, 1.0 / verh), MIN_VIERECK, GUTES_VIERECK)
    abw = max(max(abs(w - 90.0) for w in _winkel(ecken)) - (WINKEL_GUT[1] - 90.0), 0.0)
    teile["Winkel"] = 1.0 - _rampe(abw, 0.0, WINKEL_GRENZE[1] - WINKEL_GUT[1])
    kanten = [float(np.hypot(*(ecken[(i + 1) % 4] - ecken[i]))) for i in range(4)]
    schlimmste = max(max(kanten[0], kanten[2]) / max(min(kanten[0], kanten[2]), 1e-6),
                     max(kanten[1], kanten[3]) / max(min(kanten[1], kanten[3]), 1e-6))
    teile["Seitenverhältnis"] = 1.0 - _rampe(schlimmste, *MAX_SEITENVERHAELTNIS)
    if grau is not None:
        kontrast = _randkontrast(grau, ecken)
        if kontrast is not None:
            teile["Randkontrast"] = _rampe(kontrast, *RAND_KONTRAST)
    for name, wert in teile.items():
        if wert < 0.99:
            gruende.append(f"{name} {wert:.2f}")
    return min(teile.values()), gruende


def _kandidat(maske: Optional[np.ndarray], groesse: tuple[int, int], grau: Optional[np.ndarray] = None):
    """(Konfidenz, Ecken, Gruende) einer Blattflaeche oder None."""
    if maske is None or maske.sum() < MIN_KOMPONENTE * groesse[0] * groesse[1]:
        return None
    huelle = _huelle(maske)
    if huelle is None or len(huelle) < 3:
        return None
    ecken = _viereck(huelle)
    konfidenz, gruende = _bewerten(maske, ecken, huelle, groesse, grau)
    return konfidenz, ecken, gruende


def blatt_finden(bild) -> Erkennung:
    """Sucht das fotografierte Blatt. Ecken in Pixeln von ``bild`` (PIL-Bild), Konfidenz 0..1."""
    t0 = time.perf_counter()
    rgb, faktor = _klein(bild, ERKENNUNG_PX)
    groesse = rgb.shape[:2]
    grau = ndimage.gaussian_filter(rgb.mean(axis=2), 1.0)
    kandidaten = []
    for methode, karte in (("helligkeit", _karte_helligkeit), ("kanten", _karte_kanten)):
        try:
            k = _kandidat(karte(rgb), groesse, grau)
        except Exception:  # noqa: BLE001 - ein Weg darf ausfallen, der andere zaehlt
            k = None
        if k is not None:
            kandidaten.append((k[0], methode, k[1], k[2]))
    if not kandidaten:
        ecken = standard_ecken(bild.width, bild.height)
        return Erkennung(ecken, 0.0, False, "keine", ["kein Blatt gefunden"], time.perf_counter() - t0)
    # Der erste Weg (Helligkeit) gewinnt bei Gleichstand; max() nimmt das erste Maximum
    konfidenz, methode, ecken, gruende = max(kandidaten, key=lambda k: k[0])
    ecken = [(float(x * faktor), float(y * faktor)) for x, y in ecken]
    ecken = [(min(max(x, 0.0), bild.width), min(max(y, 0.0), bild.height)) for x, y in ecken]
    return Erkennung(ecken, float(konfidenz), konfidenz >= KONFIDENZ_SICHER, methode, gruende,
                     time.perf_counter() - t0)


# =========================================================================== Format

def _kantenlaengen(ecken) -> tuple[float, float, float, float]:
    """(oben, unten, links, rechts)."""
    e = np.asarray(ecken, dtype=np.float64)
    d = lambda a, b: float(np.hypot(*(e[b] - e[a])))  # noqa: E731
    return d(0, 1), d(3, 2), d(0, 3), d(1, 2)


def _verhaeltnis_perspektive(ecken, bildgroesse) -> Optional[float]:
    """Breite/Hoehe des Blatts aus den vier Ecken (Zhang und He), Hauptpunkt = Bildmitte; None, wenn nicht bestimmbar."""
    e = np.asarray(ecken, dtype=np.float64)
    m1, m2, m4, m3 = (np.array([x, y, 1.0]) for x, y in e)  # oben links, oben rechts, unten rechts, unten links
    u0, v0 = bildgroesse[0] / 2.0, bildgroesse[1] / 2.0
    try:
        k2 = np.dot(np.cross(m1, m4), m3) / np.dot(np.cross(m2, m4), m3)
        k3 = np.dot(np.cross(m1, m4), m2) / np.dot(np.cross(m3, m4), m2)
    except (FloatingPointError, ZeroDivisionError):
        return None
    n2, n3 = k2 * m2 - m1, k3 * m3 - m1
    lang = max(bildgroesse)
    f = None
    nenner_f = n2[2] * n3[2]
    if abs(nenner_f) > 1e-12:
        f2 = -((n2[0] * n3[0] - (n2[0] * n3[2] + n2[2] * n3[0]) * u0 + n2[2] * n3[2] * u0 * u0)
               + (n2[1] * n3[1] - (n2[1] * n3[2] + n2[2] * n3[1]) * v0 + n2[2] * n3[2] * v0 * v0)) / nenner_f
        if np.isfinite(f2) and f2 > 0 and BRENNWEITE_BEREICH[0] * lang < math.sqrt(f2) < BRENNWEITE_BEREICH[1] * lang:
            f = math.sqrt(f2)
    if f is None:  # Perspektive nur in einer Richtung oder Messrauschen: typische Handykamera annehmen
        f = BRENNWEITE_STANDARD * lang
    ai = np.linalg.inv(np.array([[f, 0, u0], [0, f, v0], [0, 0, 1.0]]))
    m = ai.T @ ai
    zaehler, nenner = float(n2 @ m @ n2), float(n3 @ m @ n3)
    if zaehler <= 0 or nenner <= 0 or not np.isfinite(zaehler / nenner):
        return None
    return math.sqrt(zaehler / nenner)


def seitenverhaeltnis(ecken, bildgroesse) -> float:
    """Breite/Hoehe des Blatts (Perspektivkorrektur, Rueckfall: Mittel der Gegenseiten)."""
    verh = _verhaeltnis_perspektive(ecken, bildgroesse)
    oben, unten, links, rechts = _kantenlaengen(ecken)
    einfach = ((oben + unten) / 2.0) / max((links + rechts) / 2.0, 1e-6)
    if verh is None or not (0.5 * einfach < verh < 2.0 * einfach):
        return einfach
    return verh


def seitenformat(verhaeltnis: float) -> tuple[float, float, str]:
    """(Breite mm, Hoehe mm, Name) der Zielseite zu Breite/Hoehe ``verhaeltnis``.

    Liegt das Verhaeltnis nah an A4, A5 oder Letter (hoch oder quer, ``FORMAT_TOLERANZ``),
    kommt das genaue Format; sonst bleibt das gemessene Verhaeltnis (z. B. Kassenbon),
    eingepasst in ``BOX_MM``.
    """
    verhaeltnis = max(verhaeltnis, 1e-3)
    beste = None
    for name, b, h in FORMATE:
        for quer in (False, True):
            ziel = (h / b) if quer else (b / h)
            abw = abs(verhaeltnis - ziel) / ziel
            if abw <= FORMAT_TOLERANZ and (beste is None or abw < beste[0] - 1e-3):  # Gleichstand (A4/A5): das erste
                beste = (abw, (h, b) if quer else (b, h), name)
    if beste is not None:
        return beste[1][0], beste[1][1], beste[2]
    bw, bh = BOX_MM if verhaeltnis <= 1 else (BOX_MM[1], BOX_MM[0])
    skala = min(bw / verhaeltnis, bh) if verhaeltnis <= 1 else min(bw, bh * verhaeltnis)
    if verhaeltnis <= 1:
        return skala * verhaeltnis, skala, "frei"
    return skala, skala / verhaeltnis, "frei"


# =========================================================================== Entzerren

def _koeffizienten(ziel, quelle) -> np.ndarray:
    """Pillow-PERSPECTIVE-Koeffizienten (Ausgabepunkt -> Quellpunkt)."""
    a, b = [], []
    for (x, y), (u, v) in zip(ziel, quelle):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    return np.linalg.solve(np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64))


def _beleuchtung(lum: np.ndarray) -> np.ndarray:
    """Weichgezeichnete Hintergrundhelligkeit (ohne dunkle Schrift) in voller Groesse."""
    from PIL import Image

    h, b = lum.shape
    faktor = max(h, b) / HINTERGRUND_PX if max(h, b) > HINTERGRUND_PX else 1.0
    klein = Image.fromarray(lum.astype(np.float32), "F")
    if faktor > 1.0:
        klein = klein.resize((max(1, round(b / faktor)), max(1, round(h / faktor))), Image.Resampling.BOX)
    arr = np.asarray(klein, dtype=np.float32)
    fenster = max(5, int(max(arr.shape) * HINTERGRUND_FENSTER))
    bg = ndimage.grey_closing(arr, size=(fenster, fenster))
    bg = ndimage.gaussian_filter(bg, fenster / 2.0)
    # Grosse dunkle Flaechen (Logo, Foto) sind breiter als das Fenster und wuerden sonst "aufgehellt":
    # Die Beleuchtung faellt hoechstens um ``GROB_ANTEIL`` unter die grobe Schaetzung
    grob = max(fenster + 2, int(max(arr.shape) * HINTERGRUND_GROB))
    bg_grob = ndimage.gaussian_filter(ndimage.grey_closing(arr, size=(grob, grob)), grob / 4.0)
    bg = np.maximum(bg, GROB_ANTEIL * bg_grob)
    gross = Image.fromarray(bg.astype(np.float32), "F").resize((b, h), Image.Resampling.BILINEAR)
    return np.maximum(np.asarray(gross, dtype=np.float32), HINTERGRUND_MIN)


def tonwerte_anwenden(bild, tonwerte: str = TONWERT_STANDARD):
    """Beleuchtung ausgleichen: Papier weiss, Schrift kraeftig (``farbe``, ``grau``, ``sw``).

    Gibt ein PIL-Bild zurueck (RGB, L oder 1 bit).
    """
    from PIL import Image

    if tonwerte not in TONWERTE:
        tonwerte = TONWERT_STANDARD
    rgb = np.asarray(bild.convert("RGB"), dtype=np.float32) / 255.0
    lum = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    bg = _beleuchtung(lum)
    flach = rgb / bg[:, :, None]
    papier = (lum / bg) > PAPIER_PROZENT
    if papier.sum() > 100:
        med = np.median(flach[papier], axis=0)
        flach = flach / np.maximum(med / max(float(med.max()), 1e-3), 0.5)  # neutrales Weiss, nie ueber 2x
    flach = np.clip(flach / PAPIER_WEISS, 0.0, 1.0) ** SCHRIFT_GAMMA
    if tonwerte == "farbe":
        return Image.fromarray((flach * 255 + 0.5).astype(np.uint8), "RGB")
    grau = flach @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    if tonwerte == "grau":
        return Image.fromarray((grau * 255 + 0.5).astype(np.uint8), "L")
    # Schwarzweiss: Schwelle auf der ausgeglichenen Helligkeit (Schrift davor nicht durch Gamma verschoben)
    return Image.fromarray(grau >= SW_SCHWELLE ** SCHRIFT_GAMMA).convert("1")


def _beschneiden(ecken, anteil: float):
    """Ecken um ``anteil`` der Seitenlaengen nach innen ruecken (bilinear im Viereck)."""
    tl, tr, br, bl = (np.asarray(p, dtype=np.float64) for p in ecken)
    neu = []
    for u, v in ((anteil, anteil), (1 - anteil, anteil), (1 - anteil, 1 - anteil), (anteil, 1 - anteil)):
        oben, unten = tl + u * (tr - tl), bl + u * (br - bl)
        neu.append(tuple(oben + v * (unten - oben)))
    return neu


def entzerrte_seite(bild, ecken, tonwerte: str = TONWERT_STANDARD, max_pixel: Optional[int] = None):
    """Entzerrt das Foto: ``(PIL-Bild, (Breite_pt, Hoehe_pt), Formatname)``.

    Args:
        bild: PIL-Bild (EXIF-ausgerichtet)
        ecken: oben links, oben rechts, unten rechts, unten links (Pixel von ``bild``)
        tonwerte: ``farbe``, ``grau`` oder ``sw``
        max_pixel: laengste Seite des Ergebnisses begrenzen (fuer die Vorschau)

    Die Ausgabe hat die Aufloesung ``ZIEL_DPI`` bezogen auf das Seitenformat, hoechstens
    aber die der Quelle (nichts wird hochgerechnet), mindestens ``MIN_DPI``.
    """
    from PIL import Image

    e = [(float(x), float(y)) for x, y in ecken]
    verh = seitenverhaeltnis(e, bild.size)
    b_mm, h_mm, name = seitenformat(verh)
    oben, unten, links, rechts = _kantenlaengen(e)
    nativ_b, nativ_h = max(oben, unten), max(links, rechts)
    b_zoll, h_zoll = b_mm / 25.4, h_mm / 25.4
    dpi_quelle = (nativ_b / b_zoll + nativ_h / h_zoll) / 2.0
    dpi = min(float(ZIEL_DPI), max(dpi_quelle, float(MIN_DPI)))
    pixel_b, pixel_h = max(8, round(b_zoll * dpi)), max(8, round(h_zoll * dpi))
    if max_pixel and max(pixel_b, pixel_h) > max_pixel:
        f = max_pixel / max(pixel_b, pixel_h)
        pixel_b, pixel_h = max(8, round(pixel_b * f)), max(8, round(pixel_h * f))
    quelle = bild.convert("RGB")
    # Stark verkleinern: erst mit Boxfilter reduzieren (Pillow-Transformation mittelt nicht)
    reduktion = int(min(nativ_b / pixel_b, nativ_h / pixel_h))
    if reduktion >= 2:
        quelle = quelle.reduce(reduktion)
        e = [(x / reduktion, y / reduktion) for x, y in e]
    e = _beschneiden(e, BESCHNITT)
    koeff = _koeffizienten([(0, 0), (pixel_b, 0), (pixel_b, pixel_h), (0, pixel_h)], e)
    flach = quelle.transform((pixel_b, pixel_h), Image.Transform.PERSPECTIVE, tuple(koeff),
                             resample=Image.Resampling.BICUBIC)
    flach = tonwerte_anwenden(flach, tonwerte)
    return flach, (b_mm / 25.4 * 72.0, h_mm / 25.4 * 72.0), name


def seite_als_pdf_bytes(bild, ecken, tonwerte: str = TONWERT_STANDARD) -> bytes:
    """Einseitiges PDF mit dem entzerrten Foto in genauer Seitengroesse."""
    import pymupdf

    flach, (b_pt, h_pt), _name = entzerrte_seite(bild, ecken, tonwerte)
    puffer = io.BytesIO()
    if flach.mode == "1":
        flach.save(puffer, "PNG", optimize=True)  # Schwarzweiss verlustfrei und klein
    else:
        flach.save(puffer, "JPEG", quality=JPEG_QUALITAET)
    doc = pymupdf.open()
    try:
        seite = doc.new_page(width=b_pt, height=h_pt)
        seite.insert_image(seite.rect, stream=puffer.getvalue())
        return doc.tobytes()
    finally:
        doc.close()

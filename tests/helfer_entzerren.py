"""Synthetische Handyfotos fuer die Tests zu Issue #205 (Entzerren).

Ein weisses Blatt mit Textzeilen, Stempel und Logo wird perspektivisch auf einen
dunklen, hellen oder gemusterten Untergrund gelegt, optional mit Helligkeitsverlauf.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw


def blatt(breite: int = 700, hoehe: int = 990) -> Image.Image:
    """Weisses Blatt mit Textzeilen, rotem Stempel und blauem Logo."""
    bild = Image.new("RGB", (breite, hoehe), (248, 247, 244))
    zeichnen = ImageDraw.Draw(bild)
    rng = np.random.default_rng(7)
    y = int(hoehe * 0.12)
    while y < hoehe * 0.9:
        x = int(breite * 0.1)
        ende = int(breite * (0.75 + 0.15 * rng.random()))
        while x < ende:  # "Woerter": kurze dunkle Balken
            w = int(rng.integers(20, 70))
            zeichnen.rectangle([x, y, min(x + w, ende), y + 9], fill=(35, 35, 40))
            x += w + 14
        y += 28
    zeichnen.ellipse([breite * 0.55, hoehe * 0.72, breite * 0.85, hoehe * 0.72 + breite * 0.3], outline=(200, 30, 40), width=7)
    zeichnen.rectangle([breite * 0.1, hoehe * 0.04, breite * 0.3, hoehe * 0.09], fill=(30, 70, 190))
    return bild


def _koeffizienten(ziel, quelle) -> list[float]:
    a, b = [], []
    for (x, y), (u, v) in zip(ziel, quelle):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    return list(np.linalg.solve(np.array(a, float), np.array(b, float)))


def untergrund(groesse: tuple[int, int], art: str) -> Image.Image:
    b, h = groesse
    rng = np.random.default_rng(3)
    yy, xx = np.mgrid[0:h, 0:b]
    if art == "dunkel":
        arr = np.full((h, b, 3), (38, 42, 48), dtype=np.float32)
    elif art == "hell":  # helles Holz/Tisch, kaum dunkler als das Papier
        arr = np.full((h, b, 3), (212, 208, 200), dtype=np.float32)
    elif art == "muster":  # braunes Holz mit Maserung und Fliesenfugen
        maser = 20 * np.sin(xx / 9.0 + 4 * np.sin(yy / 60.0))
        arr = np.stack([120 + maser, 85 + maser * 0.8, 50 + maser * 0.5], axis=2).astype(np.float32)
        arr[(xx // 150 + yy // 150) % 2 == 0] *= 0.8
    else:
        raise ValueError(art)
    arr += rng.normal(0, 2.5, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def foto(ecken, groesse=(1200, 900), art="dunkel", verlauf=0.0, papier: Image.Image | None = None):
    """Foto mit dem Blatt auf den Ecken ``ecken`` (oben links, oben rechts, unten rechts, unten links).

    ``verlauf``: 0 = gleichmaessig, 0.4 = unten rechts 40 % dunkler (Schatten).
    """
    papier = papier or blatt()
    pb, ph = papier.size
    koeff = _koeffizienten(ecken, [(0, 0), (pb, 0), (pb, ph), (0, ph)])
    rgba = papier.convert("RGBA")
    warp = rgba.transform(groesse, Image.Transform.PERSPECTIVE, koeff, resample=Image.Resampling.BICUBIC)
    # Rand der Abbildung (ausserhalb des Blatts) ist transparent
    maske = Image.new("L", papier.size, 255).transform(groesse, Image.Transform.PERSPECTIVE, koeff)
    grund = untergrund(groesse, art)
    grund.paste(warp.convert("RGB"), mask=maske)
    if verlauf:
        yy, xx = np.mgrid[0:groesse[1], 0:groesse[0]]
        faktor = 1.0 - verlauf * (xx / groesse[0] * 0.6 + yy / groesse[1] * 0.4)
        arr = np.asarray(grund, dtype=np.float32) * faktor[:, :, None]
        grund = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    return grund


# Typische Aufnahme: leicht schief und von schraeg unten, Blatt gross im Bild
ECKEN_SCHRAEG = [(210, 90), (980, 140), (1060, 820), (140, 780)]


def ecken_abstand(a, b) -> float:
    """Groesster Abstand zwischen den Eckenpaaren (Pixel)."""
    return max(float(np.hypot(x1 - x2, y1 - y2)) for (x1, y1), (x2, y2) in zip(a, b))


def kamera_ecken(rx=0.0, ry=0.0, rz=0.0, z=450.0, f=1000.0, mitte=(600.0, 450.0), mm=(210.0, 297.0)):
    """Bildecken eines A4-Blatts, das um (rx, ry, rz) Grad gekippt vor einer Lochkamera liegt."""
    import math

    w, h = mm
    punkte = np.array([[-w / 2, -h / 2, 0], [w / 2, -h / 2, 0], [w / 2, h / 2, 0], [-w / 2, h / 2, 0]], float)
    ax, ay, az = (math.radians(v) for v in (rx, ry, rz))
    rot_x = np.array([[1, 0, 0], [0, math.cos(ax), -math.sin(ax)], [0, math.sin(ax), math.cos(ax)]])
    rot_y = np.array([[math.cos(ay), 0, math.sin(ay)], [0, 1, 0], [-math.sin(ay), 0, math.cos(ay)]])
    rot_z = np.array([[math.cos(az), -math.sin(az), 0], [math.sin(az), math.cos(az), 0], [0, 0, 1]])
    r = rot_z @ rot_y @ rot_x
    aus = []
    for p in punkte:
        q = r @ p + np.array([0, 0, z])
        aus.append((mitte[0] + f * q[0] / q[2], mitte[1] + f * q[1] / q[2]))
    return aus

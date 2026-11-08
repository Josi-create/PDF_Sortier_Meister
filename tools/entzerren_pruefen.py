"""Prueft die Blatt-Erkennung und das Entzerren an echten Fotos (Issue #205).

Aufruf:
    python tools/entzerren_pruefen.py <eingabeordner> <ausgabeordner> [--tonwerte farbe|grau|sw]

Je Foto (JPG, PNG, TIFF, BMP, WEBP, HEIC, auch in Unterordnern) entstehen im Ausgabeordner:
    <name>_ecken.jpg      das Foto mit eingezeichnetem Viereck, den Ecken und der Konfidenz
    <name>_entzerrt.jpg   das entzerrte Ergebnis (Tonwerte wie gewaehlt; "sw" als PNG)
und eine Zeile in uebersicht.csv: Datei, Konfidenz, sicher/unsicher, Methode, Erkennung_s,
Entzerren_s, Format, Gruende. Die Schwellen stehen als Konstanten oben in src/core/entzerren.py
(KONFIDENZ_SICHER, MIN_FLAECHE, WINKEL_*, ...); damit laesst sich die Erkennung abstimmen.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

from PIL import ImageDraw  # noqa: E402

from src.core import entzerren as ez  # noqa: E402
from src.core.bild_convert import bild_endungen  # noqa: E402

ANZEIGE_PX = 1600  # laengste Seite des Kontrollbildes


def _kontrollbild(bild, erk: ez.Erkennung):
    faktor = min(1.0, ANZEIGE_PX / max(bild.size))
    klein = bild.resize((max(1, round(bild.width * faktor)), max(1, round(bild.height * faktor))))
    zeichnen = ImageDraw.Draw(klein)
    farbe = (0, 200, 0) if erk.sicher else (230, 40, 40)
    punkte = [(x * faktor, y * faktor) for x, y in erk.ecken]
    zeichnen.line(punkte + [punkte[0]], fill=farbe, width=max(3, klein.width // 300))
    r = max(6, klein.width // 120)
    for nr, (x, y) in enumerate(punkte):
        zeichnen.ellipse([x - r, y - r, x + r, y + r], outline=(255, 200, 0), width=3)
        zeichnen.text((x + r + 2, y - r), str(nr + 1), fill=(255, 255, 0))
    text = f"{'sicher' if erk.sicher else 'UNSICHER'}  Konfidenz {erk.konfidenz:.2f}  ({erk.methode})"
    zeichnen.rectangle([0, 0, 12 + 9 * len(text), 24], fill=(0, 0, 0))
    zeichnen.text((6, 5), text, fill=farbe)
    return klein


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Blatt-Erkennung und Entzerren an Fotos pruefen (Issue #205).")
    ap.add_argument("eingabe", type=Path, help="Ordner mit Fotos")
    ap.add_argument("ausgabe", type=Path, help="Ordner fuer Kontrollbilder, Ergebnisse und uebersicht.csv")
    ap.add_argument("--tonwerte", choices=ez.TONWERTE, default=ez.TONWERT_STANDARD)
    args = ap.parse_args(argv)

    if not args.eingabe.is_dir():
        print(f"Eingabeordner nicht gefunden: {args.eingabe}", file=sys.stderr)
        return 2
    args.ausgabe.mkdir(parents=True, exist_ok=True)
    endungen = bild_endungen()
    fotos = sorted(p for p in args.eingabe.rglob("*") if p.is_file() and p.suffix.lower() in endungen)
    if not fotos:
        print("Keine Fotos gefunden.", file=sys.stderr)
        return 1

    zeilen = []
    for pfad in fotos:
        name = pfad.relative_to(args.eingabe).with_suffix("").as_posix().replace("/", "_")
        try:
            bild = ez.bild_laden(pfad)
            erk = ez.blatt_finden(bild)
            _kontrollbild(bild, erk).save(args.ausgabe / f"{name}_ecken.jpg", quality=88)
            t0 = time.perf_counter()
            flach, _pt, format_ = ez.entzerrte_seite(bild, erk.ecken, args.tonwerte)
            dauer_entzerren = time.perf_counter() - t0
            if flach.mode == "1":
                flach.save(args.ausgabe / f"{name}_entzerrt.png", optimize=True)
            else:
                flach.save(args.ausgabe / f"{name}_entzerrt.jpg", quality=90)
            zeile = [pfad.name, f"{erk.konfidenz:.2f}", "sicher" if erk.sicher else "unsicher", erk.methode,
                     f"{erk.dauer:.2f}", f"{dauer_entzerren:.2f}", format_, "; ".join(erk.gruende)]
        except Exception as e:  # noqa: BLE001 - ein defektes Foto darf den Lauf nicht stoppen
            zeile = [pfad.name, "", "Fehler", "", "", "", "", str(e)]
        zeilen.append(zeile)
        print("  ".join(zeile[:7]))

    with open(args.ausgabe / "uebersicht.csv", "w", newline="", encoding="utf-8-sig") as f:
        schreiber = csv.writer(f, delimiter=";")
        schreiber.writerow(["Datei", "Konfidenz", "Urteil", "Methode", "Erkennung_s", "Entzerren_s", "Format", "Gruende"])
        schreiber.writerows(zeilen)
    sicher = sum(1 for z in zeilen if z[2] == "sicher")
    print(f"\n{len(zeilen)} Foto(s), {sicher} sicher - Übersicht: {args.ausgabe / 'uebersicht.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

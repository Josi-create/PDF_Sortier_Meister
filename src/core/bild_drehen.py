"""
Bilder im Scan-Ordner drehen (Issue #252) - Qt-frei.

JPEG: verlustfrei ueber die EXIF-Ausrichtung. Die Bilddaten bleiben Byte fuer
Byte gleich; es aendert sich nur der Eintrag "Orientation" (0x0112), den das
Programm (Kachel, Vorschau, Umwandlung in PDF, Entzerren) und uebliche
Bildbetrachter beachten. Hat die Datei den Eintrag schon, werden genau seine
zwei Bytes geaendert; sonst wird ein EXIF-Abschnitt ergaenzt bzw. der
vorhandene mit dem Eintrag neu geschrieben.

PNG und BMP: Die Pixel werden gedreht und verlustfrei neu gespeichert (Farbtiefe,
Palette, Transparenz, Farbprofil, Aufloesung und PNG-Texte bleiben erhalten).
Vor dem Ersetzen wird die neue Datei zurueckgelesen und mit dem gedrehten Bild
verglichen.

Andere Formate (TIFF, GIF, WEBP, HEIC) werden nicht gedreht: Dort waere eine
Neukodierung mit Qualitaetsverlust oder der Verlust von Seiten/Animation moeglich.

Geschrieben wird wie beim Drehen von PDFs (``pdf_rotate``): temporaere Datei im
selben Ordner, die das Original ersetzt; bei kurzer Dateisperre mehrere Versuche.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Optional

from src.core.pdf_rotate import ERLAUBT, DrehenNichtMoeglich, _ersetzen_mit_wiederholung, tmp_pfad
from src.i18n import tr

JPEG_ENDUNGEN = (".jpg", ".jpeg")
NEU_SPEICHERN_ENDUNGEN = (".png", ".bmp")
DREHBARE_ENDUNGEN = JPEG_ENDUNGEN + NEU_SPEICHERN_ENDUNGEN

_ORIENTATION = 0x0112
_EXIF_KOPF = b"Exif\x00\x00"
# Neue EXIF-Ausrichtung, wenn das angezeigte Bild im Uhrzeigersinn gedreht wird
# (2, 4, 5, 7 sind die gespiegelten Lagen). Die Tests rechnen die Tabelle mit Pillow nach.
_NACH_DREHUNG = {
    90: {1: 6, 2: 7, 3: 8, 4: 5, 5: 2, 6: 3, 7: 4, 8: 1},
    180: {1: 3, 2: 4, 3: 1, 4: 2, 5: 7, 6: 8, 7: 5, 8: 6},
    270: {1: 8, 2: 5, 3: 6, 4: 7, 5: 4, 6: 1, 7: 2, 8: 3},
}


class BildDrehenNichtMoeglich(DrehenNichtMoeglich):
    """Das Bild kann nicht gedreht werden (Grund im Text)."""


def ist_drehbares_bild(pfad: Path | str) -> bool:
    return Path(pfad).suffix.lower() in DREHBARE_ENDUNGEN


def bild_drehen(pfad: Path | str, grad: int) -> Path:
    """Dreht das Bild um ``grad`` im Uhrzeigersinn (90, 180, 270 oder -90). Liefert den Pfad.

    Raises:
        ValueError: unzulaessiger Winkel.
        BildDrehenNichtMoeglich: Format nicht drehbar oder Datei nicht lesbar.
        PermissionError: Datei auch nach mehreren Versuchen gesperrt.
        FileNotFoundError: Datei existiert nicht (mehr).
    """
    if grad not in ERLAUBT:
        raise ValueError(tr("Drehwinkel {grad} nicht erlaubt (90, 180, 270 oder -90)").format(grad=grad))
    pfad = Path(pfad)
    if not pfad.is_file():
        raise FileNotFoundError(2, tr("Datei nicht vorhanden"), str(pfad))
    endung = pfad.suffix.lower()
    if endung not in DREHBARE_ENDUNGEN:
        raise BildDrehenNichtMoeglich(
            tr("{endung}-Bilder lassen sich hier nicht drehen (nur JPG, PNG und BMP).").format(
                endung=endung.lstrip(".").upper()))
    grad = grad % 360
    tmp = tmp_pfad(pfad)
    try:
        if endung in JPEG_ENDUNGEN:
            tmp.write_bytes(_jpeg_gedreht(pfad, grad))
        else:
            _gedreht_speichern(pfad, grad, tmp)
        _ersetzen_mit_wiederholung(pfad, tmp)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return pfad


# --- JPEG: nur die EXIF-Ausrichtung ---------------------------------------------

def _jpeg_abschnitte(daten: bytes) -> tuple[Optional[tuple[int, int]], int]:
    """``((anfang, ende) des EXIF-Abschnitts oder None, Einfuegestelle fuer einen neuen)``.

    ``anfang`` zeigt auf die Markierung (FF E1), ``ende`` hinter den Abschnitt.
    """
    if daten[:2] != b"\xff\xd8":
        raise BildDrehenNichtMoeglich(tr("Die Datei ist kein JPEG-Bild."))
    pos = 2
    einfuegen = 2
    while pos + 4 <= len(daten):
        if daten[pos] != 0xFF:
            break
        marke = daten[pos + 1]
        if marke == 0xFF:  # Fuellbyte
            pos += 1
            continue
        if marke in (0xDA, 0xD9):  # Bilddaten bzw. Ende: danach kommt kein Kopf mehr
            break
        laenge = struct.unpack(">H", daten[pos + 2:pos + 4])[0]
        ende = pos + 2 + laenge
        if laenge < 2 or ende > len(daten):
            break
        if marke == 0xE1 and daten[pos + 4:pos + 10] == _EXIF_KOPF:
            return (pos, ende), einfuegen
        if marke == 0xE0 and pos == 2:  # JFIF bleibt vorn
            einfuegen = ende
        pos = ende
    return None, einfuegen


def _orientation_stelle(daten: bytes, anfang: int, ende: int) -> Optional[tuple[int, str]]:
    """Stelle (in ``daten``) und Byte-Reihenfolge des Orientation-Werts; None, wenn es ihn nicht gibt."""
    tiff = anfang + 10
    ordnung = {b"II": "<", b"MM": ">"}.get(daten[tiff:tiff + 2])
    if ordnung is None or tiff + 8 > ende:
        return None
    if struct.unpack(ordnung + "H", daten[tiff + 2:tiff + 4])[0] != 42:
        return None
    ifd = tiff + struct.unpack(ordnung + "I", daten[tiff + 4:tiff + 8])[0]
    if ifd + 2 > ende:
        return None
    anzahl = struct.unpack(ordnung + "H", daten[ifd:ifd + 2])[0]
    for i in range(anzahl):
        eintrag = ifd + 2 + 12 * i
        if eintrag + 12 > ende:
            return None
        tag, typ, zahl = struct.unpack(ordnung + "HHI", daten[eintrag:eintrag + 8])
        if tag == _ORIENTATION:
            return (eintrag + 8, ordnung) if typ == 3 and zahl == 1 else None
    return None


def _jpeg_gedreht(pfad: Path, grad: int) -> bytes:
    daten = pfad.read_bytes()
    exif, einfuegen = _jpeg_abschnitte(daten)
    if exif is not None:
        stelle = _orientation_stelle(daten, *exif)
        if stelle is not None:
            pos, ordnung = stelle
            alt = struct.unpack(ordnung + "H", daten[pos:pos + 2])[0]
            neu = _NACH_DREHUNG[grad].get(alt, _NACH_DREHUNG[grad][1])
            return daten[:pos] + struct.pack(ordnung + "H", neu) + daten[pos + 2:]
    # Kein (brauchbarer) Orientation-Eintrag: EXIF-Abschnitt mit dem Eintrag schreiben
    try:
        from PIL import Image

        with Image.open(pfad) as bild:
            angaben = bild.getexif()
            alt = angaben.get(_ORIENTATION, 1)
            angaben[_ORIENTATION] = _NACH_DREHUNG[grad].get(alt, _NACH_DREHUNG[grad][1])
            block = angaben.tobytes()
    except Exception as e:  # noqa: BLE001 - Grund melden, Datei bleibt unveraendert
        raise BildDrehenNichtMoeglich(tr("Das Bild lässt sich nicht lesen: {fehler}").format(fehler=e)) from e
    if not block.startswith(_EXIF_KOPF):
        block = _EXIF_KOPF + block
    if len(block) + 2 > 0xFFFF:
        raise BildDrehenNichtMoeglich(tr("Die Bildinformationen (EXIF) sind zu groß, um die Drehung einzutragen."))
    abschnitt = b"\xff\xe1" + struct.pack(">H", len(block) + 2) + block
    if exif is not None:
        return daten[:exif[0]] + abschnitt + daten[exif[1]:]
    return daten[:einfuegen] + abschnitt + daten[einfuegen:]


# --- PNG, BMP: Pixel drehen, verlustfrei speichern --------------------------------

def _gedreht_speichern(pfad: Path, grad: int, ziel: Path) -> None:
    try:
        from PIL import Image, ImageOps
        from PIL.PngImagePlugin import PngInfo
    except ImportError as e:
        raise BildDrehenNichtMoeglich(tr("Zum Drehen wird das Paket \"Pillow\" benötigt.")) from e

    methode = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180,
               270: Image.Transpose.ROTATE_90}[grad]
    try:
        with Image.open(pfad) as bild:
            format_ = bild.format
            if format_ not in ("PNG", "BMP"):
                raise BildDrehenNichtMoeglich(
                    tr("Der Inhalt der Datei passt nicht zur Endung {endung}.").format(endung=pfad.suffix))
            if getattr(bild, "n_frames", 1) > 1:
                raise BildDrehenNichtMoeglich(tr("Animierte Bilder werden nicht gedreht."))
            texte = dict(getattr(bild, "text", {}) or {})
            # Eine EXIF-Ausrichtung (bei PNG selten) wird dabei in die Pixel uebernommen
            gedreht = ImageOps.exif_transpose(bild).transpose(methode)
            gedreht.load()
        optionen: dict = {}
        if gedreht.info.get("dpi"):
            optionen["dpi"] = gedreht.info["dpi"]
        if format_ == "PNG":
            if gedreht.info.get("icc_profile"):
                optionen["icc_profile"] = gedreht.info["icc_profile"]
            if texte:
                info = PngInfo()
                for schluessel, wert in texte.items():
                    info.add_text(str(schluessel), str(wert))
                optionen["pnginfo"] = info
        gedreht.save(ziel, format_, **optionen)
        with Image.open(ziel) as probe:
            gleich = (probe.size == gedreht.size and probe.mode == gedreht.mode
                      and probe.tobytes() == gedreht.tobytes())
    except BildDrehenNichtMoeglich:
        raise
    except Exception as e:  # noqa: BLE001 - Grund melden, Datei bleibt unveraendert
        raise BildDrehenNichtMoeglich(tr("Das Bild lässt sich nicht drehen: {fehler}").format(fehler=e)) from e
    if not gleich:
        raise BildDrehenNichtMoeglich(tr("Das gedrehte Bild ließ sich nicht verlustfrei speichern."))

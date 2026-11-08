"""Bilder in PDF umwandeln (Issue #184) - Qt-frei.

Unterstuetzt: JPG/JPEG, PNG, TIFF/TIF (auch mehrseitig), BMP, GIF und WEBP;
HEIC/HEIF mit ``pillow-heif`` (steht in requirements.txt, Issue #205; ist es
trotzdem nicht da, bleiben HEIC-Dateien unsichtbar).

Umwandlung
----------
pymupdf (``open(bild).convert_to_pdf()``) bettet das Bild ein; die
EXIF-Ausrichtung von Handyfotos beachtet es (geprueft). Formate, die pymupdf
nicht liest (WEBP, HEIC), laufen ueber Pillow (``ImageOps.exif_transpose``),
das ohnehin ueber pytesseract im Programm ist. Mehrere Bilder werden in der
uebergebenen Reihenfolge zu *einem* PDF zusammengefuegt.

Texterkennung
-------------
Es gibt keinen neuen OCR-Weg: Je Seite laeuft derselbe Tesseract-Aufruf wie bei
der Suche und bei "OCR neu durchfuehren" (``search.extract.ocr_seite_mit_textebene``),
die unsichtbare Textebene wird wie bei der Textebene fuer gescannte PDFs
aufgelegt (``search.textebene.ebene_auflegen``). Ist Tesseract nicht da, wird
ohne Texterkennung umgewandelt (``BildErgebnis.ocr_hinweis``).

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

BILD_ENDUNGEN = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".webp")
HEIC_ENDUNGEN = (".heic", ".heif")
_UEBER_PILLOW = (".webp",) + HEIC_ENDUNGEN  # liest pymupdf nicht
_MEHRSEITIG = (".tif", ".tiff")

_heif_geprueft: Optional[bool] = None


class BildFehler(Exception):
    """Umwandlung fehlgeschlagen (Grund im Text, deutsch)."""


@dataclass
class BildErgebnis:
    pdf: Path
    quellen: list[Path]
    seiten: int
    ocr_seiten: int = 0  # Seiten mit aufgelegter Textebene
    ocr_hinweis: Optional[str] = None  # warum keine (volle) Texterkennung
    hinweise: list[str] = field(default_factory=list)


def heif_verfuegbar() -> bool:
    """Ist ``pillow-heif`` installiert (und als Pillow-Leser angemeldet)?"""
    global _heif_geprueft
    if _heif_geprueft is None:
        try:
            import pillow_heif

            pillow_heif.register_heif_opener()
            _heif_geprueft = True
        except Exception:  # noqa: BLE001 - fehlt oder defekt: HEIC ignorieren
            _heif_geprueft = False
    return _heif_geprueft


def bild_endungen() -> tuple[str, ...]:
    """Sortierbare Bildendungen; HEIC/HEIF nur mit ``pillow-heif``."""
    return BILD_ENDUNGEN + (HEIC_ENDUNGEN if heif_verfuegbar() else ())


def ist_bild_datei(pfad: Path | str) -> bool:
    return Path(pfad).suffix.lower() in bild_endungen()


# --- Umwandlung --------------------------------------------------------------

def _pdf_bytes(quelle: Path) -> bytes:
    """Das Bild (alle Seiten) als PDF-Bytes."""
    import pymupdf

    endung = quelle.suffix.lower()
    if endung not in _UEBER_PILLOW:
        try:
            with pymupdf.open(str(quelle)) as bild:
                if bild.page_count > 0:
                    return bild.convert_to_pdf()
        except Exception:  # noqa: BLE001 - dann der Weg ueber Pillow
            pass
    return _pdf_ueber_pillow(quelle)


def _pdf_ueber_pillow(quelle: Path) -> bytes:
    import pymupdf

    try:
        from PIL import Image, ImageOps, ImageSequence
    except ImportError as e:
        raise BildFehler(f"Für {quelle.suffix.lower()}-Bilder wird das Paket \"Pillow\" benötigt.") from e
    endung = quelle.suffix.lower()
    if endung in HEIC_ENDUNGEN and not heif_verfuegbar():
        raise BildFehler("HEIC-Bilder brauchen das Paket \"pillow-heif\".")
    doc = pymupdf.open()
    try:
        with Image.open(quelle) as im:
            rahmen = ImageSequence.Iterator(im) if endung in _MEHRSEITIG else [im]
            for frame in rahmen:
                bild = ImageOps.exif_transpose(frame)
                transparent = bild.mode in ("RGBA", "LA", "PA") or "transparency" in bild.info
                if transparent:
                    rgba = bild.convert("RGBA")
                    flaeche = Image.new("RGB", rgba.size, "white")
                    flaeche.paste(rgba, mask=rgba.getchannel("A"))
                    bild = flaeche
                elif bild.mode not in ("RGB", "L"):
                    bild = bild.convert("RGB")
                puffer = io.BytesIO()
                bild.save(puffer, "JPEG", quality=90)
                with pymupdf.open("jpeg", puffer.getvalue()) as einzel:
                    with pymupdf.open("pdf", einzel.convert_to_pdf()) as seite:
                        doc.insert_pdf(seite)
        if doc.page_count == 0:
            raise BildFehler(f"{quelle.name}: keine Bildseite gefunden.")
        return doc.tobytes()
    finally:
        doc.close()


def pdf_lesbar(pdf: Path | str, min_seiten: int = 1) -> bool:
    """Existiert die PDF, laesst sie sich oeffnen und hat sie mindestens ``min_seiten`` Seiten?"""
    import pymupdf

    try:
        with pymupdf.open(str(pdf)) as doc:
            return doc.page_count >= max(1, min_seiten)
    except Exception:  # noqa: BLE001 - nicht lesbar
        return False


def erste_seite_png(pfad: Path | str, breite: int = 400) -> Optional[bytes]:
    """Erste Bildseite als PNG-Bytes (Kachel-Rueckfall, wenn Qt das Format nicht liest); sonst None."""
    import pymupdf

    try:
        with pymupdf.open("pdf", _pdf_bytes(Path(pfad))) as doc:
            seite = doc[0]
            zoom = min(1.0, breite / max(seite.rect.width, 1))
            return seite.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")
    except Exception:  # noqa: BLE001 - dann bleibt der Platzhalter
        return None


# --- Texterkennung (vorhandener Weg, siehe Moduldoku) ---------------------------

def ocr_einstellungen() -> Optional[dict]:
    """Tesseract-Einstellungen wie bei der interaktiven OCR; None ohne Tesseract. Tests ersetzen das."""
    from src.core.pdf_analyzer import ocr_einstellungen_fuer_analyse

    return ocr_einstellungen_fuer_analyse()


def ocr_seite(seite, cfg: dict) -> tuple[str, bytes]:
    """Eine Seite erkennen: ``(text, text_pdf)``. Tests ersetzen das."""
    from src.search.extract import ocr_seite_mit_textebene

    return ocr_seite_mit_textebene(seite, cfg)


def _textebene_auflegen(seite, text_pdf: bytes) -> bool:
    from src.search.textebene import ebene_auflegen, ebene_hat_text

    if not ebene_hat_text(text_pdf):
        return False
    ebene_auflegen(seite, text_pdf)
    return True


def _texterkennung(doc, erg: BildErgebnis) -> None:
    cfg = ocr_einstellungen()
    if cfg is None:
        erg.ocr_hinweis = "Keine Texterkennung (Tesseract nicht gefunden) - das PDF ist nicht durchsuchbar."
        return
    fehler = 0
    for seite in doc:
        try:
            _text, ebene = ocr_seite(seite, cfg)
            if _textebene_auflegen(seite, ebene):
                erg.ocr_seiten += 1
        except Exception:  # noqa: BLE001 - die Seite bleibt ohne Text, das PDF entsteht trotzdem
            fehler += 1
    if fehler:
        erg.ocr_hinweis = f"Texterkennung bei {fehler} Seite(n) fehlgeschlagen."


def _entzerrt_pdf_bytes(quelle: Path, auftrag) -> bytes:
    """Das Foto entzerrt (Ecken und Tonwerte aus ``auftrag``) als einseitiges PDF (Issue #205)."""
    from src.core.entzerren import bild_laden, seite_als_pdf_bytes

    try:
        bild = bild_laden(quelle)
    except Exception as e:  # noqa: BLE001
        raise BildFehler(f"{quelle.name}: Bild nicht lesbar ({e})") from e
    return seite_als_pdf_bytes(bild, auftrag.ecken, auftrag.tonwerte)


def bilder_in_pdf(quellen: list[Path | str], ziel: Path | str | None = None, ocr: bool = True,
                  entzerrung: Optional[dict] = None) -> BildErgebnis:
    """Wandelt ein oder mehrere Bilder in *ein* PDF um; die Quellen bleiben unveraendert.

    Args:
        quellen: Bilddateien in der gewuenschten Seitenreihenfolge
        ziel: gewuenschter PDF-Pfad; Standard: Ordner und Name des ersten Bildes, ``.pdf``.
            Existiert er schon, wird ``Name (1).pdf`` verwendet (nichts wird ueberschrieben).
        ocr: unsichtbare Textebene erzeugen (ohne Tesseract: ohne, mit ``ocr_hinweis``)
        entzerrung: ``{Bildpfad: Entzerrung}`` (Issue #205): diese Bilder werden vor dem
            Einbetten perspektivisch gerade gezogen (Ecken, Tonwerte); mehrseitige TIFFs nur
            mit der ersten Seite. Andere Bilder laufen wie bisher.

    Raises:
        BildFehler: Umwandlung fehlgeschlagen (nichts bleibt liegen)
    """
    import pymupdf

    from src.core.office_convert import _freier_pfad

    quellen = [Path(q) for q in quellen]
    entzerrung = {Path(k): v for k, v in (entzerrung or {}).items()}
    if not quellen:
        raise BildFehler("Kein Bild angegeben.")
    for q in quellen:
        if not q.is_file():
            raise BildFehler(f"Datei nicht gefunden: {q}")
        if not ist_bild_datei(q):
            raise BildFehler(f"Dateityp {q.suffix.lower() or '(keiner)'} wird nicht unterstützt.")
    ziel = _freier_pfad(Path(ziel) if ziel else quellen[0].with_suffix(".pdf"))
    teil = ziel.with_name(ziel.name + ".part")  # endet nicht auf .pdf: erscheint nie in der Ansicht
    doc = pymupdf.open()
    try:
        for q in quellen:
            try:
                auftrag = (entzerrung or {}).get(q)
                data = _entzerrt_pdf_bytes(q, auftrag) if auftrag is not None else _pdf_bytes(q)
                with pymupdf.open("pdf", data) as seiten:
                    doc.insert_pdf(seiten)
            except BildFehler:
                raise
            except Exception as e:  # noqa: BLE001
                raise BildFehler(f"{q.name}: {e}") from e
        erg = BildErgebnis(pdf=ziel, quellen=quellen, seiten=doc.page_count)
        if ocr:
            _texterkennung(doc, erg)
        try:
            doc.save(str(teil), garbage=3, deflate=True)
        except Exception as e:  # noqa: BLE001
            teil.unlink(missing_ok=True)
            raise BildFehler(f"PDF konnte nicht geschrieben werden: {e}") from e
    finally:
        doc.close()
    try:
        os.replace(teil, ziel)
    except OSError as e:
        teil.unlink(missing_ok=True)
        raise BildFehler(f"PDF konnte nicht geschrieben werden: {e}") from e
    if not pdf_lesbar(ziel, erg.seiten):
        ziel.unlink(missing_ok=True)
        raise BildFehler("Das erzeugte PDF ist nicht lesbar.")
    return erg

"""
PDF verlustfrei drehen (Issue #150) - Qt-frei.

Gedreht wird ueber den Seiteneintrag ``/Rotate``: Bilddaten, Textebene,
Info-Dict und XMP bleiben unveraendert, nur die Anzeige der Seite dreht sich.
Geschrieben wird in eine temporaere Datei im selben Ordner, die dann das
Original ersetzt (unter Windows mit ``ReplaceFileW`` wie beim Schreiben der
Textebene: die Datei behaelt ihre Identitaet fuer OneDrive, Erstellungsdatum
und Rechte). Ist die Datei kurz gesperrt (Vorschau, Virenscanner, OneDrive),
wird wie beim Verschieben mehrmals neu versucht.

Signierte und verschluesselte PDFs werden nicht gedreht: Eine Signatur waere
danach ungueltig, und beim Speichern ginge die Verschluesselung verloren.

Gerade ausrichten (Issue #165, ``gerade_ausrichten``): Schief gescannte Seiten
werden gemessen und ihr ganzer Inhalt um den kleinen Winkel gedreht
(``src.search.gerade``). Gespeichert wird inkrementell auf einer Kopie: Das
Original bleibt bytegleich der Anfang der neuen Datei, Scanbild und Textebene
bleiben unveraendert und drehen nur mit. ``ausrichtung_zuruecknehmen`` entfernt
die Ausrichtung wieder (Rueckgaengig).

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Iterable, Optional
from src.i18n import tr

# Gleiche Wartezeiten wie FileManager.MOVE_RETRY_DELAYS (Windows-Dateisperre)
RETRY_DELAYS = (0.1, 0.2, 0.3, 0.5, 0.8)
TMP_ENDUNG = ".drehen.tmp"
ERLAUBT = (90, 180, 270, -90)


class DrehenNichtMoeglich(Exception):
    """Die PDF darf oder kann nicht gedreht werden (Grund im Text)."""


def tmp_pfad(pfad: Path) -> Path:
    """Temporaere Datei im selben Ordner (``~$``/``.tmp``: OneDrive und Suche lassen sie aus)."""
    kennung = hashlib.blake2b(os.path.normcase(pfad.name).encode("utf-8"), digest_size=3).hexdigest()
    return pfad.with_name(f"~${pfad.stem[:40]}.{kennung}{TMP_ENDUNG}")


def _signiert(pdf) -> bool:
    try:
        acro = pdf.Root.get("/AcroForm")
        if acro is None:
            return False
        return int(acro.get("/SigFlags", 0)) & 1 == 1
    except Exception:  # noqa: BLE001 - im Zweifel nicht signiert; pikepdf liest es dann ohnehin
        return False


def drehung(path: Path | str) -> list[int]:
    """Aktuelle Drehung je Seite (0, 90, 180, 270) - fuer Tests und Anzeige."""
    import pikepdf

    with pikepdf.open(str(path)) as pdf:
        return [_geerbt(seite) for seite in pdf.pages]


def _geerbt(seite) -> int:
    """/Rotate kann vom Pages-Knoten geerbt sein."""
    knoten = seite.obj
    while knoten is not None:
        if "/Rotate" in knoten:
            return int(knoten.Rotate) % 360
        knoten = knoten.get("/Parent")
    return 0


def rotate_pdf(path: Path | str, grad: int, seiten: Optional[Iterable[int]] = None) -> Path:
    """Dreht die PDF (alle Seiten oder die 1-basierten ``seiten``) um ``grad`` im Uhrzeigersinn.

    ``grad``: 90 (rechts), -90 bzw. 270 (links) oder 180. Liefert den Pfad.

    Raises:
        ValueError: unzulaessiger Winkel oder Seitennummer.
        DrehenNichtMoeglich: signiert oder verschluesselt.
        PermissionError: Datei auch nach mehreren Versuchen gesperrt.
        FileNotFoundError: Datei existiert nicht (mehr).
    """
    import pikepdf

    if grad not in ERLAUBT:
        raise ValueError(tr("Drehwinkel {grad} nicht erlaubt (90, 180, 270 oder -90)").format(grad=grad))
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(2, tr("Datei nicht vorhanden"), str(path))
    tmp = tmp_pfad(path)
    try:
        try:
            pdf = pikepdf.open(str(path))
        except pikepdf.PasswordError as e:
            raise DrehenNichtMoeglich(tr("Die PDF ist kennwortgeschützt.")) from e
        with pdf:
            if pdf.is_encrypted:
                raise DrehenNichtMoeglich(tr("Die PDF ist verschlüsselt; beim Drehen ginge der Schutz verloren."))
            if _signiert(pdf):
                raise DrehenNichtMoeglich(tr("Die PDF ist digital signiert; Drehen würde die Signatur ungültig machen."))
            anzahl = len(pdf.pages)
            nummern = list(range(1, anzahl + 1)) if seiten is None else list(seiten)
            for nr in nummern:
                if not 1 <= nr <= anzahl:
                    raise ValueError(tr("Seite {nr} gibt es nicht (1 bis {anzahl})").format(nr=nr, anzahl=anzahl))
                pdf.pages[nr - 1].rotate(grad, relative=True)
            # Streams unveraendert uebernehmen (keine Neukompression der Scans)
            pdf.save(str(tmp), compress_streams=False, recompress_flate=False)
        _ersetzen_mit_wiederholung(path, tmp)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return path


def _ersetzen_mit_wiederholung(ziel: Path, ersatz: Path) -> None:
    from src.search.plattform import datei_ersetzen

    for pause in RETRY_DELAYS:
        try:
            datei_ersetzen(str(ziel), str(ersatz))
            return
        except PermissionError:
            time.sleep(pause)
    datei_ersetzen(str(ziel), str(ersatz))


def _schreibbar(doc) -> None:
    """Wie beim Drehen: keine verschluesselten oder signierten PDFs (``DrehenNichtMoeglich``)."""
    try:
        verschluesselt = doc.needs_pass or bool((doc.metadata or {}).get("encryption"))
    except Exception:
        verschluesselt = True
    if verschluesselt:
        raise DrehenNichtMoeglich(tr("Die PDF ist verschlüsselt; beim Speichern ginge der Schutz verloren."))
    try:
        signiert = doc.get_sigflags() > 0
    except Exception:
        signiert = False
    if signiert:
        raise DrehenNichtMoeglich(tr("Die PDF ist digital signiert; Ausrichten würde die Signatur ungültig machen."))


def _seiten_aendern(path: Path, aendern) -> None:
    """Kopie anlegen, ``aendern(doc)`` anwenden, inkrementell speichern und das Original ersetzen."""
    import shutil

    import pymupdf

    tmp = tmp_pfad(path)
    try:
        shutil.copyfile(path, tmp)
        doc = pymupdf.open(str(tmp))
        try:
            aendern(doc)
            if doc.can_save_incrementally():
                doc.saveIncr()
                neu = None
            else:   # reparierte Datei: vollstaendig speichern, ohne Aufraeumen und ohne Neukomprimieren
                neu = tmp.with_name(tmp.name + ".neu")
                doc.save(str(neu), garbage=0, clean=False, deflate=False)
        finally:
            doc.close()
        if neu is not None:
            os.replace(neu, tmp)
        _ersetzen_mit_wiederholung(path, tmp)
    finally:
        for rest in (tmp, tmp.with_name(tmp.name + ".neu")):
            try:
                rest.unlink()
            except OSError:
                pass


def gerade_ausrichten(path: Path | str, seiten: Optional[Iterable[int]] = None) -> dict[int, float]:
    """Schief gescannte Seiten (alle oder die 1-basierten ``seiten``) gerade ausrichten (Issue #165).

    Gemessen werden die gescannten Seiten, so wie sie angezeigt werden
    (``gerade.seite_messen``); ausgerichtet wird nur, was deutlich schief ist
    (``gerade.lohnt``). Eine schon ausgerichtete Seite bekommt eine weitere
    Ausrichtung um die Restschraeglage. Liefert ``{seite: winkel}``; leer,
    wenn nichts schief ist (die Datei bleibt dann unberuehrt).

    Raises:
        ValueError: unzulaessige Seitennummer.
        DrehenNichtMoeglich: signiert oder verschluesselt.
        PermissionError: Datei auch nach mehreren Versuchen gesperrt.
        FileNotFoundError: Datei existiert nicht (mehr).
    """
    import pymupdf

    from src.search import gerade

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(2, tr("Datei nicht vorhanden"), str(path))
    winkel: dict[int, float] = {}
    with pymupdf.open(str(path)) as doc:
        _schreibbar(doc)
        anzahl = doc.page_count
        nummern = list(range(1, anzahl + 1)) if seiten is None else list(seiten)
        for nr in nummern:
            if not 1 <= nr <= anzahl:
                raise ValueError(tr("Seite {nr} gibt es nicht (1 bis {anzahl})").format(nr=nr, anzahl=anzahl))
            seite = doc[nr - 1]
            if not gerade.ist_scan(seite):
                continue
            w = gerade.seite_messen(seite)
            if gerade.lohnt(w):
                winkel[nr] = w
    if winkel:
        def ausrichten(doc):
            for nr, w in sorted(winkel.items()):
                gerade.ausrichten(doc, doc[nr - 1], w)

        _seiten_aendern(path, ausrichten)
    return winkel


def ausrichtung_zuruecknehmen(path: Path | str, seiten: Iterable[int]) -> list[int]:
    """Die zuletzt angebrachte Ausrichtung dieser Seiten wieder entfernen (Rueckgaengig, Issue #165).

    Liefert die Seiten, bei denen das ging; die Datei bleibt unberuehrt, wenn
    keine dabei ist (z. B. weil inzwischen eine Textebene dazukam).
    """
    import pymupdf

    from src.search import gerade

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(2, tr("Datei nicht vorhanden"), str(path))
    with pymupdf.open(str(path)) as doc:
        _schreibbar(doc)
        moeglich = [nr for nr in sorted(set(seiten)) if 1 <= nr <= doc.page_count
                    and gerade.ist_ausgerichtet(doc, doc[nr - 1])]
    if not moeglich:
        return []
    erledigt: list[int] = []

    def entfernen(doc):
        for nr in moeglich:
            if gerade.ausrichtung_entfernen(doc, doc[nr - 1]):
                erledigt.append(nr)

    _seiten_aendern(path, entfernen)
    return erledigt


def gegenrichtung(grad: int) -> int:
    """Winkel, der eine Drehung um ``grad`` aufhebt (fuer Rueckgaengig)."""
    return {90: -90, -90: 90, 270: 90, 180: 180}[grad]

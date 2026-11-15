"""
Einzelne Seiten einer PDF loeschen, umsortieren und drehen (Issue #280) - Qt-frei.

``seiten_schreiben`` schreibt die PDF nach einem Plan neu: welche Seiten
bleiben, in welcher Reihenfolge und um wie viel sie zusaetzlich gedreht
werden. Die Seiten selbst (Scanbild, Textebene) bleiben unveraendert, ebenso
Info-Dict und XMP; gedreht wird wie beim Drehen der ganzen PDF ueber
``/Rotate``. Der Inhalt einer geloeschten Seite kommt nicht in die neue Datei,
er steht danach auch nicht mehr versteckt darin. Lesezeichen auf geloeschte
Seiten entfallen.

Vor dem Ersetzen wird das Original in eine Sicherungskopie gelegt;
``wiederherstellen`` holt es zurueck (Rueckgaengig). Ersetzt wird wie beim
Drehen (``ReplaceFileW``, mehrere Versuche bei gesperrter Datei).

Signierte und verschluesselte PDFs werden nicht bearbeitet: Eine Signatur
waere danach ungueltig, und beim Speichern ginge die Verschluesselung verloren.

``leere_seiten`` findet fast weisse Seiten (leere Rueckseiten beim
Duplex-Scan). Das ist nur ein Vorschlag; geloescht wird erst, was der Anwender
bestaetigt.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Sequence

from src.core.pdf_rotate import DrehenNichtMoeglich, _ersetzen_mit_wiederholung, _signiert, tmp_pfad
from src.i18n import tr
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

DREHUNGEN = (0, 90, 180, 270)

# Leere Seiten: Die Seite wird klein und grau gerendert. Als "Tinte" zaehlt, was
# deutlich dunkler ist als Papier (durchscheinende Schrift der Vorderseite ist
# heller). Der Rand bleibt aussen vor: dort liegen Lochung, Schatten der
# Blattkante und Heftklammern.
LEER_DPI = 72
LEER_DUNKEL = 160          # Grauwert (0 schwarz, 255 weiss), darunter ist es Tinte
LEER_RAND = 0.06           # Anteil je Seite, der nicht mitzaehlt
LEER_ANTEIL = 0.0004       # hoechster Tintenanteil einer leeren Seite (rund acht Buchstaben)


def _oeffnen(path: Path):
    """Oeffnet die PDF zum Bearbeiten; verschluesselte und signierte bleiben unberuehrt."""
    import pikepdf

    if not path.is_file():
        raise FileNotFoundError(2, tr("Datei nicht vorhanden"), str(path))
    try:
        pdf = pikepdf.open(str(path))
    except pikepdf.PasswordError as e:
        raise DrehenNichtMoeglich(tr("Die PDF ist kennwortgeschützt.")) from e
    try:
        if pdf.is_encrypted:
            raise DrehenNichtMoeglich(
                tr("Die PDF ist verschlüsselt; beim Speichern ginge der Schutz verloren."))
        if _signiert(pdf):
            raise DrehenNichtMoeglich(
                tr("Die PDF ist digital signiert; eine Änderung der Seiten würde die Signatur ungültig machen."))
    except Exception:
        pdf.close()
        raise
    return pdf


def seitenzahl(path: Path | str) -> int:
    """Zahl der Seiten; ``DrehenNichtMoeglich``, wenn die PDF nicht bearbeitet werden darf."""
    with _oeffnen(Path(path)) as pdf:
        return len(pdf.pages)


def unveraendert(plan: Sequence[tuple[int, int]], anzahl: int) -> bool:
    """Laesst der Plan die PDF, wie sie ist (alle Seiten, alte Reihenfolge, nichts gedreht)?"""
    return [(nr, grad % 360) for nr, grad in plan] == [(nr, 0) for nr in range(1, anzahl + 1)]


def _lesezeichen_bereinigen(pdf, geloescht: set) -> None:
    """Lesezeichen entfernen, die auf eine geloeschte Seite zeigen (und keine Unterpunkte mehr haben)."""
    import pikepdf

    def zeigt_auf_geloeschte(eintrag) -> bool:
        ziel = eintrag.destination
        if ziel is None and eintrag.action is not None:
            ziel = eintrag.action.get("/D")
        try:
            return isinstance(ziel, pikepdf.Array) and len(ziel) > 0 and ziel[0].objgen in geloescht
        except Exception:  # noqa: BLE001 - Ziel ohne Seitenobjekt (Seitennummer, Name)
            return False

    def filtern(eintraege) -> None:
        for eintrag in list(eintraege):
            filtern(eintrag.children)
            if zeigt_auf_geloeschte(eintrag) and not eintrag.children:
                eintraege.remove(eintrag)

    with pdf.open_outline() as lesezeichen:
        filtern(lesezeichen.root)


def seiten_schreiben(path: Path | str, plan: Sequence[tuple[int, int]], sicherung: Path | str) -> Path:
    """Schreibt die PDF neu: ``plan`` nennt die bleibenden Seiten in neuer Reihenfolge.

    Jeder Eintrag ist ``(seite, grad)``: die bisherige Seitennummer (1-basiert)
    und die zusaetzliche Drehung im Uhrzeigersinn (0, 90, 180, 270). Seiten,
    die im Plan fehlen, werden geloescht. Das Original liegt danach als Kopie
    unter ``sicherung`` (der Ordner wird angelegt).

    Raises:
        ValueError: leerer Plan, Seite doppelt oder nicht vorhanden, falscher Winkel.
        DrehenNichtMoeglich: signiert oder verschluesselt.
        PermissionError: Datei auch nach mehreren Versuchen gesperrt.
        FileNotFoundError: Datei existiert nicht (mehr).
    """
    path, sicherung = Path(path), Path(sicherung)
    plan = [(int(nr), int(grad) % 360) for nr, grad in plan]
    if not plan:
        raise ValueError(tr("Mindestens eine Seite muss bleiben."))
    tmp = tmp_pfad(path)
    gesichert = False
    try:
        with _oeffnen(path) as pdf:
            anzahl = len(pdf.pages)
            nummern = [nr for nr, _ in plan]
            for nr, grad in plan:
                if not 1 <= nr <= anzahl:
                    raise ValueError(tr("Seite {nr} gibt es nicht (1 bis {anzahl})").format(nr=nr, anzahl=anzahl))
                if grad not in DREHUNGEN:
                    raise ValueError(
                        tr("Drehwinkel {grad} nicht erlaubt (90, 180, 270 oder -90)").format(grad=grad))
            if len(set(nummern)) != len(nummern):
                raise ValueError(tr("Eine Seite steht doppelt im Plan."))
            alt = list(pdf.pages)
            for nr, grad in plan:
                if grad:
                    alt[nr - 1].rotate(grad, relative=True)
            if nummern != list(range(1, anzahl + 1)):
                bleibt = [alt[nr - 1] for nr in nummern]
                weg = [alt[nr - 1] for nr in range(1, anzahl + 1) if nr not in set(nummern)]
                for i in range(anzahl - 1, -1, -1):
                    del pdf.pages[i]
                for seite in bleibt:
                    pdf.pages.append(seite)
                if weg:
                    if "/Outlines" in pdf.Root:
                        try:
                            _lesezeichen_bereinigen(pdf, {seite.objgen for seite in weg})
                        except Exception as e:  # noqa: BLE001 - Lesezeichen sind Beiwerk
                            logger.warning("Lesezeichen von %s nicht bereinigt (%s)", path.name, e)
                    # Verweise von anderswo (Links, benannte Ziele, Formularfelder) koennen eine
                    # geloeschte Seite noch erreichen. Sie wird deshalb geleert: Ihr Inhalt
                    # (Scanbild, Text) ist dann nicht mehr erreichbar und wird nicht mitgeschrieben.
                    for seite in weg:
                        for schluessel in list(seite.obj.keys()):
                            if schluessel != "/Type":
                                del seite.obj[schluessel]
            # Streams unveraendert uebernehmen (keine Neukompression der Scans);
            # geschrieben wird nur, was noch erreichbar ist
            pdf.save(str(tmp), compress_streams=False, recompress_flate=False)
        sicherung.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(path), str(sicherung))
        gesichert = True
        _ersetzen_mit_wiederholung(path, tmp)
    except Exception:
        if gesichert:  # nichts geaendert: die Kopie wird nicht gebraucht
            sicherung.unlink(missing_ok=True)
        raise
    finally:
        tmp.unlink(missing_ok=True)
    return path


def wiederherstellen(path: Path | str, sicherung: Path | str) -> Path:
    """Legt die Sicherungskopie wieder an die Stelle der PDF (die Kopie bleibt liegen).

    Raises:
        FileNotFoundError: PDF oder Sicherung fehlt.
        PermissionError: Datei auch nach mehreren Versuchen gesperrt.
    """
    path, sicherung = Path(path), Path(sicherung)
    if not path.is_file():
        raise FileNotFoundError(2, tr("Datei nicht vorhanden"), str(path))
    if not sicherung.is_file():
        raise FileNotFoundError(2, tr("Sicherung nicht gefunden: {backup}").format(backup=sicherung), str(sicherung))
    tmp = tmp_pfad(path)
    try:
        shutil.copy2(str(sicherung), str(tmp))
        _ersetzen_mit_wiederholung(path, tmp)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def tintenanteil(seite) -> float:
    """Anteil dunkler Bildpunkte im Inneren der Seite (0.0 = ganz weiss)."""
    import numpy as np
    import pymupdf

    faktor = LEER_DPI / 72
    pix = seite.get_pixmap(matrix=pymupdf.Matrix(faktor, faktor), colorspace=pymupdf.csGRAY, alpha=False)
    bild = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
    rand_y, rand_x = int(pix.height * LEER_RAND), int(pix.width * LEER_RAND)
    innen = bild[rand_y:pix.height - rand_y, rand_x:pix.width - rand_x]
    if innen.size == 0:
        return 0.0
    return float((innen < LEER_DUNKEL).sum()) / innen.size


def leere_seiten(path: Path | str) -> list[int]:
    """1-basierte Nummern der fast weissen Seiten (Vorschlag zum Loeschen)."""
    import pymupdf

    with pymupdf.open(str(path)) as doc:
        if doc.needs_pass:
            return []
        return [nr for nr, seite in enumerate(doc, start=1) if tintenanteil(seite) <= LEER_ANTEIL]

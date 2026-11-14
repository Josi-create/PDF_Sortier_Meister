"""
Passwortschutz einer PDF entfernen (Issue #244) - Qt-frei.

Eine PDF, die sich nur mit Passwort oeffnen laesst, wird mit dem eingegebenen
Passwort gelesen und als ungeschuetzte **Kopie** neben das Original geschrieben
(``<Name> (entsperrt).pdf``). Das Original wird hier nie veraendert, verschoben
oder geloescht; was mit ihm geschieht, fragt die Oberflaeche erst, wenn die
Kopie fertig und geprueft ist.

Sicherheit:

- Das Passwort lebt nur als Argument dieses Aufrufs. Es wird nicht gespeichert,
  nicht protokolliert und steht in keiner Fehlermeldung.
- Geschrieben wird zuerst in eine temporaere Datei im selben Ordner. Erst wenn
  sie sich ohne Passwort oeffnen laesst und so viele Seiten hat wie das
  Original, bekommt sie ihren endgueltigen Namen. Geht etwas schief, bleibt
  nur das unveraenderte Original zurueck.
- Kein Ausprobieren: genau das uebergebene Passwort wird geprueft (in den
  Kodierungen, in denen PDF-Programme es abgelegt haben koennen).

Entfernt wird nur ein *Oeffnen*-Passwort. PDFs, die sich ohne Passwort oeffnen
lassen und nur Rechte einschraenken (Drucken, Kopieren), gelten hier nicht als
geschuetzt.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.i18n import tr

TMP_ENDUNG = ".entsperren.tmp"
# Gleiche Wartezeiten wie beim Drehen: Virenscanner oder OneDrive halten eine neue Datei kurz fest
RETRY_DELAYS = (0.1, 0.2, 0.3, 0.5, 0.8)


class FalschesPasswort(Exception):
    """Das Passwort oeffnet die PDF nicht."""


class EntsperrenNichtMoeglich(Exception):
    """Die Kopie ohne Schutz konnte nicht erstellt werden (Grund im Text, nie das Passwort)."""


@dataclass
class Entsperrt:
    """Ergebnis: die ungeschuetzte Kopie neben dem Original."""

    original: Path
    kopie: Path
    seiten: int
    signiert: bool  # das Original traegt eine digitale Signatur (sie gilt fuer die Kopie nicht)


def braucht_passwort(pfad: Path | str) -> bool:
    """True, wenn sich die PDF nur mit einem Passwort oeffnen laesst.

    Nicht lesbare Dateien und PDFs, die nur Rechte einschraenken, ergeben False.
    """
    import pymupdf

    try:
        with pymupdf.open(str(pfad)) as doc:
            return bool(doc.is_pdf and doc.needs_pass)
    except Exception:  # noqa: BLE001 - kaputte Datei: kein Fall fuers Entsperren
        return False


def tmp_pfad(pfad: Path) -> Path:
    """Temporaere Datei im selben Ordner (``~$``/``.tmp``: OneDrive und die Ansicht lassen sie aus)."""
    kennung = hashlib.blake2b(os.path.normcase(pfad.name).encode("utf-8"), digest_size=3).hexdigest()
    return pfad.with_name(f"~${pfad.stem[:40]}.{kennung}{TMP_ENDUNG}")


def kopie_name(original: Path) -> Path:
    """Freier Name der Kopie: ``<Name> (entsperrt).pdf``, sonst mit `` (2)``, `` (3)`` ..."""
    from src.core.ordner_verschieben import freier_name

    ziel = original.with_name(original.stem + tr(" (entsperrt)") + ".pdf")
    return freier_name(ziel) if ziel.exists() else ziel


def _kandidaten(passwort: str) -> list:
    """Das Passwort in den Kodierungen, in denen es in der PDF stehen kann.

    Neue PDFs (AES-256) rechnen mit UTF-8, aeltere mit PDFDocEncoding oder der
    Codepage des erzeugenden Programms. Das betrifft nur Passwoerter mit
    Umlauten oder Sonderzeichen; es ist dasselbe Passwort, kein Ausprobieren.
    """
    import pikepdf  # noqa: F401 - meldet die Kodierung "pdfdoc" an

    kandidaten: list = [passwort]
    for kodierung in ("pdfdoc", "cp1252", "latin-1"):
        try:
            roh = passwort.encode(kodierung)
        except (UnicodeError, LookupError):
            continue
        if roh != passwort.encode("utf-8") and roh not in kandidaten:
            kandidaten.append(roh)
    return kandidaten


def _oeffnen(pfad: Path, passwort: str):
    import pikepdf

    for kandidat in _kandidaten(passwort):
        try:
            return pikepdf.open(str(pfad), password=kandidat)
        except pikepdf.PasswordError:
            continue
    raise FalschesPasswort(tr("Das Passwort passt nicht."))


def _schreiben_pymupdf(pfad: Path, passwort: str, tmp: Path) -> Optional[tuple[int, bool]]:
    """Zweiter Weg, falls pikepdf das Passwort ablehnt, PyMuPDF es aber annimmt.

    Die beiden Bibliotheken bereiten Passwoerter mit Sonderzeichen nicht in
    jedem Fall gleich auf. Liefert ``(Seiten, signiert)`` oder ``None``, wenn
    das Passwort auch hier nicht passt.
    """
    import pymupdf

    with pymupdf.open(str(pfad)) as doc:
        if not doc.authenticate(passwort):
            return None
        try:
            signiert = doc.get_sigflags() > 0
        except Exception:  # noqa: BLE001 - im Zweifel nicht signiert
            signiert = False
        # Ohne Aufraeumen und ohne Neukomprimieren: der Inhalt bleibt, nur die Verschluesselung faellt weg
        doc.save(str(tmp), encryption=pymupdf.PDF_ENCRYPT_NONE, garbage=0, clean=False, deflate=False)
        return doc.page_count, signiert


def _pruefen(datei: Path, seiten: int) -> None:
    """Die geschriebene Datei muss sich ohne Passwort oeffnen lassen und alle Seiten haben."""
    import pymupdf

    with pymupdf.open(str(datei)) as doc:
        if doc.needs_pass or doc.is_encrypted or (doc.metadata or {}).get("encryption"):
            raise EntsperrenNichtMoeglich(tr("Die Kopie ist noch geschützt."))
        if doc.page_count != seiten or seiten < 1:
            raise EntsperrenNichtMoeglich(tr("Die Kopie hat nicht alle Seiten des Originals."))
        for nr in range(doc.page_count):
            doc.load_page(nr)


def _ohne_passwort(text: str, passwort: str) -> str:
    """Fehlertext einer Bibliothek: das Passwort darf darin nie stehen."""
    return text.replace(passwort, "***") if passwort else text


def entsperren(pfad: Path | str, passwort: str) -> Entsperrt:
    """Schreibt eine ungeschuetzte Kopie neben ``pfad``; das Original bleibt unberuehrt.

    Raises:
        FalschesPasswort: das Passwort oeffnet die PDF nicht.
        EntsperrenNichtMoeglich: kein Oeffnen-Passwort vorhanden, Datei nicht
            lesbar, Ordner nicht beschreibbar oder Kopie nicht in Ordnung.
        FileNotFoundError: Datei existiert nicht (mehr).
    """
    from src.core.pdf_rotate import _signiert

    pfad = Path(pfad)
    if not pfad.is_file():
        raise FileNotFoundError(2, tr("Datei nicht vorhanden"), str(pfad))
    if not braucht_passwort(pfad):
        raise EntsperrenNichtMoeglich(tr("Die PDF braucht kein Passwort zum Öffnen."))
    tmp = tmp_pfad(pfad)
    try:
        pdf = None
        try:
            pdf = _oeffnen(pfad, passwort)
        except FalschesPasswort:
            pass  # unten: zweiter Weg ueber PyMuPDF
        except Exception as e:  # noqa: BLE001 - z. B. beschaedigte Datei
            raise EntsperrenNichtMoeglich(
                tr("Die PDF konnte nicht gelesen werden: {grund}").format(grund=_ohne_passwort(str(e), passwort))
            ) from None
        try:
            if pdf is not None:
                with pdf:
                    seiten = len(pdf.pages)
                    signiert = _signiert(pdf)
                    with open(tmp, "wb") as ausgabe:
                        # encryption=False: unverschluesselt schreiben; die Streams bleiben, wie sie sind
                        pdf.save(ausgabe, encryption=False, compress_streams=False, recompress_flate=False)
                        ausgabe.flush()
                        os.fsync(ausgabe.fileno())
            else:
                ergebnis = _schreiben_pymupdf(pfad, passwort, tmp)
                if ergebnis is None:
                    raise FalschesPasswort(tr("Das Passwort passt nicht."))
                seiten, signiert = ergebnis
            _pruefen(tmp, seiten)
            kopie = _umbenennen(tmp, pfad)
        except (EntsperrenNichtMoeglich, FalschesPasswort):
            raise
        except PermissionError:
            raise EntsperrenNichtMoeglich(tr("Im Ordner kann nicht geschrieben werden.")) from None
        except Exception as e:  # noqa: BLE001 - Schreib- oder Lesefehler
            raise EntsperrenNichtMoeglich(
                tr("Die Kopie konnte nicht geschrieben werden: {grund}").format(grund=_ohne_passwort(str(e), passwort))
            ) from None
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return Entsperrt(original=pfad, kopie=kopie, seiten=seiten, signiert=signiert)


def _umbenennen(tmp: Path, original: Path) -> Path:
    """Gibt der geprueften Datei ihren endgueltigen Namen, ohne je eine vorhandene Datei zu ersetzen."""
    for _ in range(20):
        ziel = kopie_name(original)
        try:
            _verschieben_ohne_ersetzen(tmp, ziel)
        except FileExistsError:
            continue  # inzwischen heisst eine Datei so: naechster freier Name
        return ziel
    raise EntsperrenNichtMoeglich(tr("Kein freier Dateiname für die Kopie gefunden."))


def _verschieben_ohne_ersetzen(tmp: Path, ziel: Path) -> None:
    """Benennt ``tmp`` in ``ziel`` um; gibt es ``ziel`` schon, ``FileExistsError`` (nichts wird ersetzt).

    Ist die neue Datei kurz gesperrt (Virenscanner, OneDrive), wird mehrmals neu versucht.
    """
    for pause in (*RETRY_DELAYS, None):
        try:
            if os.name == "nt":
                os.rename(tmp, ziel)  # Windows: schlaegt fehl, wenn es das Ziel gibt
            else:
                _verknuepfen_ohne_ersetzen(tmp, ziel)
            return
        except FileExistsError:
            raise
        except PermissionError:
            if pause is None:
                raise
            time.sleep(pause)


def _verknuepfen_ohne_ersetzen(tmp: Path, ziel: Path) -> None:
    """macOS/Linux: ``os.rename`` wuerde ersetzen, ein harter Link auf einen vorhandenen Namen scheitert."""
    try:
        os.link(tmp, ziel)
    except FileExistsError:
        raise
    except OSError:
        # Dateisystem ohne harte Links (exFAT, manche Netzlaufwerke): Namen exklusiv anlegen, dann fuellen
        with open(ziel, "xb"):
            pass
        os.replace(tmp, ziel)
        return
    os.unlink(tmp)

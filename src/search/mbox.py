"""Thunderbird-mbox-Dateien lesen (ohne alles in den Speicher zu laden).

Uebernommen aus PDFsuche (``mbox.py``). Laeuft im Hauptprozess des Laufs; das
Zerlegen der einzelnen Mails uebernehmen die Arbeitsprozesse (``extract.mbox_stapel``).
"""

from __future__ import annotations

import os
import re
from typing import Iterator

MAX_KOPF = 6 * 1024 * 1024          # so viel einer Mail wird zum Zerlegen weitergegeben
_STATUS = re.compile(rb"^X-Mozilla-Status: ([0-9A-Fa-f]{1,4})", re.M)
MSG_EXPUNGED = 0x0008
_KEINE_MBOX = (".msf", ".dat", ".json", ".sqlite", ".html", ".txt", ".js", ".mozlz4")


def ist_mbox(pfad: str) -> bool:
    """Thunderbird legt neben jeder mbox eine .msf-Indexdatei an."""
    name = os.path.basename(pfad)
    if name.lower().endswith(_KEINE_MBOX):
        return False
    return os.path.isfile(pfad + ".msf")


def postfaecher(wurzel: str) -> Iterator[tuple[str, str]]:
    """Liefert (mbox-Pfad, Anzeigename) fuer alle Postfaecher unter ``wurzel``.

    Der Anzeigename ist ``Thunderbird/<Konto>/<Ordner>/<Postfach>``; Unterordner
    liegen bei Thunderbird in ``<Postfach>.sbd/``.
    """
    for ordner, _dirs, dateien in os.walk(wurzel):
        for d in dateien:
            p = os.path.join(ordner, d)
            if ist_mbox(p):
                rel = os.path.relpath(p, wurzel)
                rel = rel.replace(".sbd" + os.sep, "/").replace(os.sep, "/")
                yield p, "Thunderbird/" + rel


def anfang_passt(pfad: str, offset: int) -> bool:
    """Beginnt an ``offset`` eine neue Mail? (fuer das Weiterlesen angehaengter Mails)"""
    try:
        with open(pfad, "rb") as f:
            f.seek(offset)
            return f.read(5) == b"From "
    except OSError:
        return False


def mails(pfad: str, start: int = 0) -> Iterator[tuple[int, int, bytes]]:
    """Liefert (offset, laenge, rohdaten_ohne_From-Zeile) je Mail; geloeschte Mails werden uebersprungen."""
    with open(pfad, "rb", buffering=8 * 1024 * 1024) as f:
        f.seek(start)
        pos = start
        akt_off: int | None = None
        teile: list[bytes] = []
        laenge_puffer = 0
        vorher_leer = True

        def abschluss(ende: int):
            roh = b"".join(teile)
            m = _STATUS.search(roh[:8192])
            if m and int(m.group(1), 16) & MSG_EXPUNGED:
                return None
            return akt_off, ende - akt_off, roh

        for zeile in f:
            if zeile.startswith(b"From ") and (vorher_leer or akt_off is None or zeile.startswith(b"From - ")):
                if akt_off is not None:
                    r = abschluss(pos)
                    if r:
                        yield r
                akt_off = pos
                teile = []
                laenge_puffer = 0
            elif akt_off is not None and laenge_puffer < MAX_KOPF:
                teile.append(zeile)
                laenge_puffer += len(zeile)
            vorher_leer = zeile in (b"\n", b"\r\n")
            pos += len(zeile)
        if akt_off is not None:
            r = abschluss(pos)
            if r:
                yield r


def mail_roh(pfad: str, offset: int, laenge: int) -> bytes:
    """Eine einzelne Mail als .eml-Bytes (ohne die mbox-Trennzeile)."""
    with open(pfad, "rb") as f:
        f.seek(offset)
        roh = f.read(laenge)
    if roh.startswith(b"From "):
        nl = roh.find(b"\n")
        roh = roh[nl + 1:] if nl >= 0 else b""
    return roh

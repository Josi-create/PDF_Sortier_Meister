"""Issue #299: doppelte Dateien in einem Ordner samt Unterordnern finden (Kern ohne Qt).

Alle Dateien entstehen im Test unter tmp_path; Namen sind erfunden.
"""
from __future__ import annotations

import os
import sys

import pytest

from src.core.duplikate import Pruefsummen, dateien_unter, doppelte_unter

BRIEF = b"%PDF-1.4 Brief an Max Mustermann " * 30
RECHNUNG = b"%PDF-1.4 Rechnung von <Absender> !" * 30  # gleich gross wie BRIEF, anderer Inhalt


def _datei(pfad, inhalt: bytes, mtime: float | None = None):
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(inhalt)
    if mtime is not None:
        os.utime(pfad, (mtime, mtime))
    return pfad


def test_dateien_unter_geht_in_unterordner_aber_nicht_in_versteckte(tmp_path):
    a = _datei(tmp_path / "a.pdf", b"a")
    b = _datei(tmp_path / "Ämter 2024" / "Unter" / "b.pdf", b"b")
    _datei(tmp_path / ".versteckt" / "c.pdf", b"c")
    _datei(tmp_path / "$RECYCLE.BIN" / "d.pdf", b"d")
    assert sorted(dateien_unter(tmp_path)) == sorted([a, b])


def test_dateien_unter_ohne_ordner_ist_leer(tmp_path):
    assert dateien_unter(tmp_path / "gibt es nicht") == []


@pytest.mark.skipif(sys.platform != "win32", reason="Junction gibt es nur unter Windows")
def test_dateien_unter_betritt_keine_junction(tmp_path):
    import _winapi
    ziel = tmp_path / "Archiv"
    a = _datei(ziel / "a.pdf", BRIEF)
    _winapi.CreateJunction(str(ziel), str(tmp_path / "Verknuepfung"))
    assert dateien_unter(tmp_path) == [a]
    assert doppelte_unter(tmp_path, Pruefsummen()) == []  # dieselbe Datei ueber zwei Wege ist nicht doppelt


def test_doppelte_unter_findet_gleiche_ueber_unterordner_aelteste_zuerst(tmp_path):
    neu = _datei(tmp_path / "Scan 2.pdf", BRIEF, mtime=2_000_000_000)
    alt = _datei(tmp_path / "Briefe" / "2023" / "Brief Mustermann.pdf", BRIEF, mtime=1_700_000_000)
    _datei(tmp_path / "Rechnung.pdf", RECHNUNG)
    _datei(tmp_path / "einzeln.jpg", b"nur einmal")
    foto_a = _datei(tmp_path / "Fotos" / "IMG_1.jpg", b"\xff\xd8 Foto \xff\xd9", mtime=1_600_000_000)
    foto_b = _datei(tmp_path / "Fotos" / "IMG_1 (1).jpg", b"\xff\xd8 Foto \xff\xd9", mtime=1_650_000_000)

    gruppen = doppelte_unter(tmp_path, Pruefsummen())

    assert sorted(gruppen) == sorted([[alt, neu], [foto_a, foto_b]])
    assert [alt, neu] in gruppen  # die aelteste Datei steht vorn


def test_doppelte_unter_leere_dateien_zaehlen_nicht(tmp_path):
    _datei(tmp_path / "leer1.txt", b"")
    _datei(tmp_path / "Unter" / "leer2.txt", b"")
    assert doppelte_unter(tmp_path, Pruefsummen()) == []


def test_doppelte_unter_meldet_fortschritt_und_bricht_ab(tmp_path):
    for i in range(4):
        _datei(tmp_path / f"Ordner {i}" / "gleich.pdf", BRIEF)
    stand = []
    gruppen = doppelte_unter(tmp_path, Pruefsummen(), fortschritt=lambda g, n: stand.append((g, n)))
    assert len(gruppen) == 1 and len(gruppen[0]) == 4
    assert stand[-1] == (4, 4)

    speicher = Pruefsummen()
    assert doppelte_unter(tmp_path, speicher, abbrechen=lambda: True) == []
    assert speicher.gerechnet == 0  # nach dem Abbruch wird nichts mehr gelesen

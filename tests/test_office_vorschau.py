"""Tests fuer src/core/office_vorschau.py (Issue #9): Kachelquellen und Vorschau-Cache."""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from src.core import office_convert as oc
from src.core import office_vorschau as ov


def docx(pfad: Path, text: str = "Hallo Welt", thumb: bytes | None = None) -> Path:
    with zipfile.ZipFile(pfad, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>",
        )
        if thumb is not None:
            z.writestr("docProps/thumbnail.jpeg", thumb)
    return pfad


def test_eingebettetes_bild(tmp_path):
    assert ov.eingebettetes_bild(docx(tmp_path / "a.docx", thumb=b"JPEGDATA")) == b"JPEGDATA"
    assert ov.eingebettetes_bild(docx(tmp_path / "b.docx")) is None
    kaputt = tmp_path / "c.docx"
    kaputt.write_bytes(b"kein zip")
    assert ov.eingebettetes_bild(kaputt) is None


def test_erste_zeilen(tmp_path):
    zeilen = ov.erste_zeilen(docx(tmp_path / "a.docx", "Sehr geehrte Frau Meier"))
    assert zeilen and "Sehr geehrte Frau Meier" in zeilen[0]
    assert ov.erste_zeilen(tmp_path / "gibt_es_nicht.docx") == []


def test_cache_schluessel_aendert_sich_mit_mtime(tmp_path):
    d = docx(tmp_path / "a.docx")
    cache = tmp_path / "cache"
    cache.mkdir()
    k1 = ov.cache_pfad(d, cache)
    os.utime(d, ns=(1_000_000_000, 2_000_000_000))
    assert ov.cache_pfad(d, cache) != k1
    assert ov.cache_pfad(d, cache).parent == cache


def test_vorschau_pdf_cached_und_raeumt_alte_auf(tmp_path, monkeypatch):
    d = docx(tmp_path / "a.docx")
    cache = tmp_path / "cache"
    cache.mkdir()
    aufrufe = []

    def falsch(quelle, ziel=None, pdfa=False):
        aufrufe.append(Path(quelle))
        Path(ziel).write_bytes(b"%PDF-1.7")
        return oc.UmwandlungsErgebnis(pdf=Path(ziel), werkzeug="Word")

    monkeypatch.setattr(ov, "umwandeln", falsch)
    p1 = ov.vorschau_pdf(d, cache)
    assert p1.parent == cache and p1.exists()
    assert ov.vorschau_pdf(d, cache) == p1 and len(aufrufe) == 1  # aus dem Cache

    os.utime(d, ns=(1_000_000_000, 2_000_000_000))  # Datei geaendert -> neuer Eintrag, alter weg
    p2 = ov.vorschau_pdf(d, cache)
    assert p2 != p1 and len(aufrufe) == 2
    assert not p1.exists() and list(cache.glob("*.pdf")) == [p2]
    assert d.exists()  # Original unberuehrt


def test_cache_wird_begrenzt(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()

    def falsch(quelle, ziel=None, pdfa=False):
        Path(ziel).write_bytes(b"%PDF-1.7")
        return oc.UmwandlungsErgebnis(pdf=Path(ziel), werkzeug="Word")

    monkeypatch.setattr(ov, "umwandeln", falsch)
    for i in range(5):
        p = ov.vorschau_pdf(docx(tmp_path / f"d{i}.docx"), cache, max_dateien=3)
        os.utime(p, (1000 + i, 1000 + i))
    assert len(list(cache.glob("*.pdf"))) == 3


def test_vorschau_loeschen(tmp_path, monkeypatch):
    d = docx(tmp_path / "a.docx")
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(
        ov, "umwandeln",
        lambda q, ziel=None, pdfa=False: (Path(ziel).write_bytes(b"%PDF"), oc.UmwandlungsErgebnis(pdf=Path(ziel), werkzeug="Word"))[1],
    )
    ov.vorschau_pdf(d, cache)
    d.unlink()  # wie nach "Loeschen"
    ov.vorschau_loeschen(d, cache)
    assert list(cache.glob("*.pdf")) == []


def test_shell_bild_nie_ausnahme(tmp_path):
    # Auf Nicht-Windows None; auf Windows None oder Bild - aber nie eine Ausnahme
    erg = ov.shell_bild(tmp_path / "gibt_es_nicht.docx")
    assert erg is None

"""GUI-Test zu Issue #383: Streifen „Doppelt“ auch fuer abgelegte Fassungen derselben Datei.

Fixtures aus tests/test_doppelte_245_gui.py (tmp-Pfade, nie die echte Konfiguration).
Namen sind erfunden.
"""
from __future__ import annotations

import shutil

import pikepdf
import pytest

import helfer_suche as h
from src.core import duplikate
from src.core.pdf_metadata import PDFMetadata, write_metadata
from tests.test_auto_next_after_move_gui import (  # noqa: F401 - Fixtures
    fresh_singletons,
    main_window,
)
from tests.test_doppelte_245_gui import _geprueft, _hinweis, fenster  # noqa: F401 - Fixture


@pytest.fixture
def frische_merkmale(monkeypatch):
    monkeypatch.setattr(duplikate, "_merkmale", duplikate.PdfMerkmale())


def test_abgelegte_fassungen_tragen_den_streifen(fenster, frische_merkmale, qtbot):  # noqa: F811
    ordner = fenster.tmp / "Rechnungen 2026"
    ordner.mkdir()
    vorlage = h.scan_pdf(fenster.tmp / "Scan.pdf", ["Rechnung Nr. 4711", "Max Mustermann"])
    alt = ordner / "Rechnung alt.pdf"      # vor v0.31 abgelegt: Metadaten, kein Vermerk
    neu = ordner / "Rechnung neu.pdf"      # mit v0.31 abgelegt: Metadaten und Vermerk
    shutil.copyfile(vorlage, alt)
    shutil.copyfile(vorlage, neu)
    with pikepdf.open(alt, allow_overwriting_input=True) as pdf:
        pdf.docinfo["/Title"] = "Rechnung"
        pdf.save()
    assert write_metadata(neu, PDFMetadata(korrespondent="Beispiel GmbH"))
    anders = h.scan_pdf(ordner / "Brief.pdf", ["Sehr geehrter Herr Mustermann"])

    fenster._navigate_to_folder(ordner)
    _geprueft(fenster, qtbot)

    assert _hinweis(fenster, alt) == "Doppelt: wie Rechnung neu.pdf"
    assert _hinweis(fenster, neu) == "Doppelt: wie Rechnung alt.pdf"
    assert _hinweis(fenster, anders) == ""

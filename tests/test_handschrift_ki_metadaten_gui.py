"""Live-Test 08.11.2026: Nach "Als Text übernehmen" (Handschrift per KI) automatisch
"KI-Metadaten neu generieren" - aber erst, wenn die neue Analyse mit dem Text steht.

Fixtures aus tests/test_ocr_schwer_lesbar_47.py (nie die echte Konfiguration).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_ocr_schwer_lesbar_47 import (  # noqa: F401 - Fixtures
    _auf_ergebnis_warten,
    _kachel,
    _provider_setzen,
    _vision_provider,
    fenster,
    fresh_singletons,
    main_window,
    scan_ordner,
)


@pytest.fixture
def ablauf(fenster, monkeypatch):
    """Handschrift entziffern, Dialog sagt "Als Text übernehmen", Speichern gelingt."""
    from src.core import handschrift_ki as hk
    from src.gui import ocr_schwer_lesbar as osl

    _provider_setzen(fenster, _vision_provider("ollama"), "ollama", "qwen2.5vl:7b")
    monkeypatch.setattr(osl.HandschriftErgebnisDialog, "exec", lambda self: self.uebernehmen_button.click())
    monkeypatch.setattr(hk, "vorhandener_text", lambda p, s: False)
    monkeypatch.setattr(hk, "text_uebernehmen", lambda p, t: {"index": True, "seiten": len(t), "fehler": None})

    ki = []
    panel = fenster.detail_panel
    monkeypatch.setattr(panel, "ki_metadaten_neu_generieren", lambda: ki.append(panel.get_current_pdf()) or True)
    # Ohne echte Analyse (die Fixture stellt update_suggestions_for_pdf still): Detailansicht folgt der Auswahl
    monkeypatch.setattr(panel, "get_current_pdf", lambda: fenster.selected_pdf)
    fenster._ki = ki
    return fenster


def _analyse_fertig(fenster, pfad: Path, qtbot):
    from src.core.pdf_cache import PDFAnalysisResult

    fenster.pdf_cache._cache[pfad] = PDFAnalysisResult(pdf_path=pfad, file_modified=pfad.stat().st_mtime,
                                                       extracted_text="Lieber Hans, Montag 14 Uhr")
    fenster.pdf_cache.pdf_analyzed.emit(pfad)
    qtbot.wait(20)   # der Start laeuft nach dem naechsten Ereignisdurchlauf


def test_uebernehmen_startet_ki_metadaten_erst_nach_der_analyse(ablauf, qtbot):
    pdf = ablauf._pdf
    _kachel(ablauf).handschrift_requested.emit(pdf)
    _auf_ergebnis_warten(ablauf, qtbot)

    # Text gespeichert: PDF ausgewaehlt, Analyse verworfen und neu angefordert - KI noch nicht
    assert ablauf.selected_pdf == pdf
    assert ablauf._log["cleared"] == [pdf] and ablauf._log["analyse"][-1] == pdf
    qtbot.wait(20)
    assert ablauf._ki == []

    # Analyse eines anderen PDFs zaehlt nicht
    anderes = pdf.parent / "b.pdf"
    anderes.write_bytes(pdf.read_bytes())
    _analyse_fertig(ablauf, anderes, qtbot)
    assert ablauf._ki == []

    # Neue Analyse dieses PDFs: genau einmal KI-Metadaten
    _analyse_fertig(ablauf, pdf, qtbot)
    assert ablauf._ki == [pdf]
    _analyse_fertig(ablauf, pdf, qtbot)
    assert ablauf._ki == [pdf]


def test_keine_ki_metadaten_wenn_inzwischen_anderes_ausgewaehlt(ablauf, qtbot):
    pdf = ablauf._pdf
    _kachel(ablauf).handschrift_requested.emit(pdf)
    _auf_ergebnis_warten(ablauf, qtbot)

    ablauf._clear_selection()
    _analyse_fertig(ablauf, pdf, qtbot)
    assert ablauf._ki == []


def test_ohne_ki_hinweis_in_der_statusleiste(ablauf, qtbot, monkeypatch):
    monkeypatch.setattr(ablauf.detail_panel, "ki_metadaten_neu_generieren", lambda: False)
    pdf = ablauf._pdf
    _kachel(ablauf).handschrift_requested.emit(pdf)
    _auf_ergebnis_warten(ablauf, qtbot)
    _analyse_fertig(ablauf, pdf, qtbot)
    assert "keine KI eingerichtet" in ablauf.statusbar.currentMessage()


def test_ki_metadaten_neu_generieren_ohne_pdf_startet_nichts(main_window):
    assert main_window.detail_panel.ki_metadaten_neu_generieren() is False

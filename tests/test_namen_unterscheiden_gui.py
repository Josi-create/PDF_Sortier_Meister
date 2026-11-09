"""Issue #221 im Hauptfenster: gleiche Namen im Stapel unterscheidet die KI vor der Rueckfrage.

Fixtures aus tests/test_stapel_ablage_218_gui.py (tmp-Config, Rueckfragen protokolliert).
Kein Netz: der KI-Anbieter ist ein Stub mit fester Antwort.
"""
from __future__ import annotations

import json
import threading

from src.core.pdf_cache import LLMSuggestion
from tests.test_stapel_ablage_218_gui import (  # noqa: F401 - Fixtures
    _markieren,
    _panel_vorbelegung,
    fresh_singletons,
    main_window,
    stapel,
)

GLEICH = "2026-06-05_Rechnung_Absender_Monatsabrechnung.pdf"


class _Provider:
    def __init__(self, antwort, sperre: threading.Event | None = None):
        self.antwort = antwort
        self.sperre = sperre
        self.fragen: list[str] = []

    def answer_with_context(self, system_prompt, context_docs, user_question, max_tokens=1000):
        self.fragen.append(user_question)
        if self.sperre is not None:
            self.sperre.wait(5)
        return self.antwort


def _alle_gleich(stapel) -> None:
    """a und b bekommen von der KI denselben Namen (c bleibt anders)."""
    for p in (stapel["a"], stapel["b"]):
        stapel["win"].pdf_cache._cache[p].llm_suggestions = [
            LLMSuggestion(filename=GLEICH, confidence=0.9, metadata={"korrespondent": "Absender"})]


def _ki_an(monkeypatch, win, provider) -> None:
    monkeypatch.setattr(win.hybrid_classifier, "llm_provider", provider, raising=False)
    monkeypatch.setattr(win.hybrid_classifier, "is_llm_available", lambda: True)


def test_gleiche_namen_bekommen_ein_unterscheidungswort(stapel, monkeypatch):
    win, a, b, c, ziel = stapel["win"], stapel["a"], stapel["b"], stapel["c"], stapel["ziel"]
    _alle_gleich(stapel)
    name_a, name_c = _panel_vorbelegung(win, a)[0], _panel_vorbelegung(win, c)[0]
    assert _panel_vorbelegung(win, b)[0] == name_a  # Voraussetzung: gleicher Vorschlag
    provider = _Provider(json.dumps({"unterschiede": ["Vorderhaus", "Hinter Haus"]}))
    _ki_an(monkeypatch, win, provider)
    _markieren(win, a, b, c)

    win.stapel_verschieben([a, b, c], ziel)

    stamm = name_a[:-4]
    assert {p.name for p in ziel.iterdir()} == {
        f"{stamm}_Vorderhaus.pdf", f"{stamm}_Hinter-Haus.pdf", name_c}
    frage, = provider.fragen  # ein Aufruf fuer die eine Gruppe, mit beiden Texten
    assert "Dokument 2" in frage and "Dokument 3" not in frage
    (_t, text, zeilen, _j, _n), = stapel["fragen"]
    assert [neu for _alt, neu in zeilen][:2] == [f"{stamm}_Vorderhaus.pdf", f"{stamm}_Hinter-Haus.pdf"]
    assert "denselben Namen" not in text


def test_auch_beim_umbenennen_am_platz(stapel, monkeypatch):
    win, a, b, scan = stapel["win"], stapel["a"], stapel["b"], stapel["scan"]
    _alle_gleich(stapel)
    stamm = _panel_vorbelegung(win, a)[0][:-4]
    _ki_an(monkeypatch, win, _Provider('{"unterschiede": ["Garten", "Hof"]}'))
    _markieren(win, a, b)

    win.stapel_umbenennen_speichern([a, b])

    assert {f"{stamm}_Garten.pdf", f"{stamm}_Hof.pdf"} <= {p.name for p in scan.iterdir()}


def test_ki_fehler_laesst_die_namen_und_weist_darauf_hin(stapel, monkeypatch):
    win, a, b, ziel = stapel["win"], stapel["a"], stapel["b"], stapel["ziel"]
    _alle_gleich(stapel)
    name = _panel_vorbelegung(win, a)[0]
    _ki_an(monkeypatch, win, _Provider("[Claude-Fehler: 401]"))
    _markieren(win, a, b)
    meldungen: list[str] = []
    zeigen = win.statusbar.showMessage
    monkeypatch.setattr(win.statusbar, "showMessage", lambda t, *a_: (meldungen.append(t), zeigen(t, *a_)))

    win.stapel_verschieben([a, b], ziel)

    assert {p.name for p in ziel.iterdir()} == {name, f"{name[:-4]} (1).pdf"}
    (_t, text, _z, _j, _n), = stapel["fragen"]
    assert "denselben Namen" in text
    assert any("nicht unterschieden" in m for m in meldungen)


def test_ohne_ki_kein_aufruf(stapel, monkeypatch):
    win, a, b, ziel = stapel["win"], stapel["a"], stapel["b"], stapel["ziel"]
    _alle_gleich(stapel)
    _panel_vorbelegung(win, a)
    provider = _Provider('{"unterschiede": ["X", "Y"]}')
    monkeypatch.setattr(win.hybrid_classifier, "llm_provider", provider, raising=False)
    monkeypatch.setattr(win.hybrid_classifier, "is_llm_available", lambda: False)
    _markieren(win, a, b)

    win.stapel_verschieben([a, b], ziel)

    assert provider.fragen == [] and len(list(ziel.iterdir())) == 2


def test_nicht_mehr_warten_behaelt_die_namen(stapel, monkeypatch, qtbot):
    """Langsame KI: das Fortschrittsfenster erscheint; "Nicht mehr warten" faehrt ohne Woerter fort."""
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QProgressDialog

    win, a, b, ziel = stapel["win"], stapel["a"], stapel["b"], stapel["ziel"]
    _alle_gleich(stapel)
    name = _panel_vorbelegung(win, a)[0]
    sperre = threading.Event()
    _ki_an(monkeypatch, win, _Provider('{"unterschiede": ["X", "Y"]}', sperre))
    _markieren(win, a, b)
    gesehen: list[str] = []

    def abbrechen():
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QProgressDialog) and w.isVisible():
                gesehen.append(w.labelText())
                w.cancel()
                return
        QTimer.singleShot(50, abbrechen)

    QTimer.singleShot(50, abbrechen)
    try:
        win.stapel_verschieben([a, b], ziel)
    finally:
        sperre.set()

    assert gesehen and "unterscheidet" in gesehen[0]
    assert name in {p.name for p in ziel.iterdir()}
    assert not any("_X" in p.name or "_Y" in p.name for p in ziel.iterdir())

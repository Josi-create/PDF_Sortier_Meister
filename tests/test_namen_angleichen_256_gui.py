"""Issue #256 im Hauptfenster: gleichartige Namen im Stapel gleicht die KI vor der Rueckfrage an.

Fixtures aus tests/test_stapel_ablage_218_gui.py (tmp-Config, Rueckfragen protokolliert).
Kein Netz: der KI-Anbieter ist ein Stub mit fester Antwort.
"""
from __future__ import annotations

import json

from src.core.pdf_cache import LLMSuggestion
from tests.test_stapel_ablage_218_gui import (  # noqa: F401 - Fixtures
    _markieren,
    _panel_vorbelegung,
    fresh_singletons,
    main_window,
    stapel,
)

MIT = "2026-05-12_Rechnung_Anbieter_Festnetz Mai 2026.pdf"
OHNE = "2026-06-11_Rechnung_Anbieter_Festnetz.pdf"


class _Provider:
    def __init__(self, antworten: list[str]):
        self.antworten = list(antworten)
        self.fragen: list[str] = []

    def answer_with_context(self, system_prompt, context_docs, user_question, max_tokens=1000):
        self.fragen.append(user_question)
        return self.antworten.pop(0)


def _monatsrechnungen(stapel, name_a: str = MIT, name_b: str = OHNE) -> tuple[str, str]:
    """a bekommt von der KI einen Namen mit Monat, b einen ohne; liefert die Namen laut Detail-Panel."""
    win = stapel["win"]
    for p, name in ((stapel["a"], name_a), (stapel["b"], name_b)):
        win.pdf_cache._cache[p].llm_suggestions = [
            LLMSuggestion(filename=name, confidence=0.9, metadata={"korrespondent": "Anbieter"})]
    return _panel_vorbelegung(win, stapel["a"])[0], _panel_vorbelegung(win, stapel["b"])[0]


def _ki(monkeypatch, win, provider, an: bool = True) -> None:
    monkeypatch.setattr(win.hybrid_classifier, "llm_provider", provider, raising=False)
    monkeypatch.setattr(win.hybrid_classifier, "is_llm_available", lambda: an)


def test_fehlender_monat_wird_ergaenzt(stapel, monkeypatch):
    win, a, b, c, ziel = stapel["win"], stapel["a"], stapel["b"], stapel["c"], stapel["ziel"]
    name_a, name_b = _monatsrechnungen(stapel)
    assert (name_a, name_b) == (MIT, OHNE)  # Voraussetzung: das Panel uebernimmt die Vorschlaege
    name_c = _panel_vorbelegung(win, c)[0]
    provider = _Provider([json.dumps({"merkmale": ["Juni 2026"]})])
    _ki(monkeypatch, win, provider)
    _markieren(win, a, b, c)

    win.stapel_verschieben([a, b, c], ziel)

    angeglichen = f"{name_b[:-4]} Juni 2026.pdf"
    assert {p.name for p in ziel.iterdir()} == {name_a, angeglichen, name_c}
    frage, = provider.fragen  # ein Aufruf, nur mit dem Dokument ohne Monat
    assert '"Mai 2026"' in frage and "--- Dokument 1" in frage and "--- Dokument 2" not in frage
    (_t, _text, zeilen, _j, _n), = stapel["fragen"]
    assert (b.name, angeglichen) in zeilen


def test_auch_beim_umbenennen_am_platz_und_fuer_eine_datei_die_schon_so_heisst(stapel, monkeypatch):
    """b heisst bereits wie der Vorschlag ohne Monat (bliebe sonst unveraendert) und wird trotzdem angeglichen."""
    win, a, b, scan = stapel["win"], stapel["a"], stapel["b"], stapel["scan"]
    name_a, name_b = _monatsrechnungen(stapel)
    neu_b = b.with_name(name_b)
    b.rename(neu_b)
    win.pdf_cache._cache[neu_b] = win.pdf_cache._cache.pop(b)
    win.pdf_cache._cache[neu_b].pdf_path = neu_b
    win._navigate_to_folder(scan)
    _ki(monkeypatch, win, _Provider(['{"merkmale": ["Juni 2026"]}']))
    _markieren(win, a, neu_b)

    win.stapel_umbenennen_speichern([a, neu_b])

    assert {name_a, f"{name_b[:-4]} Juni 2026.pdf"} <= {p.name for p in scan.iterdir()}
    assert not neu_b.exists()


def test_ki_fehler_laesst_die_namen_und_weist_darauf_hin(stapel, monkeypatch):
    win, a, b, ziel = stapel["win"], stapel["a"], stapel["b"], stapel["ziel"]
    name_a, name_b = _monatsrechnungen(stapel)
    _ki(monkeypatch, win, _Provider(["[Claude-Fehler: 401]"]))
    _markieren(win, a, b)
    meldungen: list[str] = []
    zeigen = win.statusbar.showMessage
    monkeypatch.setattr(win.statusbar, "showMessage", lambda t, *a_: (meldungen.append(t), zeigen(t, *a_)))

    win.stapel_verschieben([a, b], ziel)

    assert {p.name for p in ziel.iterdir()} == {name_a, name_b}
    assert any("nicht angeglichen" in m for m in meldungen)


def test_ohne_ki_und_ohne_uneinheitliche_namen_kein_aufruf(stapel, monkeypatch):
    win, a, b, c, ziel = stapel["win"], stapel["a"], stapel["b"], stapel["c"], stapel["ziel"]
    _monatsrechnungen(stapel)
    provider = _Provider(['{"merkmale": ["Juni 2026"]}'])
    _ki(monkeypatch, win, provider, an=False)
    _markieren(win, a, b)
    win.stapel_verschieben([a, b], ziel)
    assert provider.fragen == [] and len(list(ziel.iterdir())) == 2

    # KI an, aber die Namen sind schon einheitlich aufgebaut (b ist weg, c hat einen ganz anderen Namen)
    _ki(monkeypatch, win, provider)
    win.stapel_umbenennen_speichern([c])
    assert provider.fragen == []


def test_angeglichene_namen_die_gleich_werden_unterscheidet_danach_221(stapel, monkeypatch):
    """Gleiches Datum, nach dem Angleichen derselbe Name: der zweite Aufruf (#221) unterscheidet sie."""
    win, a, b, ziel = stapel["win"], stapel["a"], stapel["b"], stapel["ziel"]
    name_a, name_b = _monatsrechnungen(stapel, name_b=MIT[:-13] + ".pdf")
    assert name_b[:-4] + " Mai 2026.pdf" == name_a  # Voraussetzung
    provider = _Provider(['{"merkmale": ["Mai 2026"]}', '{"unterschiede": ["Festnetz", "Mobil"]}'])
    _ki(monkeypatch, win, provider)
    _markieren(win, a, b)

    win.stapel_verschieben([a, b], ziel)

    assert {p.name for p in ziel.iterdir()} == {f"{name_a[:-4]}_Festnetz.pdf", f"{name_a[:-4]}_Mobil.pdf"}
    assert len(provider.fragen) == 2

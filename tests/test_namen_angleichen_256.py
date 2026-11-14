"""Issue #256: gleichartige Namen im Stapel gleich aufbauen (Qt-freier Kern)."""
from __future__ import annotations

import json

import pytest

from src.core import namen_unterscheiden as nu

MAI = "2025-05-12_Rechnung_Anbieter_Festnetz Mai 2025.pdf"
JUNI = "2025-06-11_Rechnung_Anbieter_Festnetz.pdf"
JULI = "2025-07-10_Rechnung_Anbieter_Festnetz.pdf"


class _Provider:
    def __init__(self, antwort):
        self.antwort = antwort
        self.fragen: list[str] = []

    def answer_with_context(self, system_prompt, context_docs, user_question, max_tokens=1000):
        self.fragen.append(user_question)
        return self.antwort


def test_gruppe_aus_namen_mit_und_ohne_zusatz_trotz_verschiedenem_datum():
    gruppe, = nu.uneinheitliche_gruppen([JUNI, "2025-01-02_Bescheid_Amt.pdf", MAI, None, JULI])
    assert gruppe.ohne == [0, 4]
    assert gruppe.mit == {2: " Mai 2025"}


def test_zusatz_mit_unterstrich_und_gross_klein():
    gruppe, = nu.uneinheitliche_gruppen(["Rechnung_Anbieter_festnetz.pdf", "Rechnung_Anbieter_Festnetz_RE-4711.pdf"])
    assert (gruppe.ohne, gruppe.mit) == ([0], {1: "_RE-4711"})


@pytest.mark.parametrize("namen", [
    [MAI, "2025-06-11_Rechnung_Anbieter_Festnetz Juni 2025.pdf"],  # alle mit Zusatz
    [JUNI, JULI],  # keiner mit Zusatz
    [JUNI, "2025-06-11_Rechnung_Anbieter_Festnetzanschluss.pdf"],  # kein Trennzeichen: anderes Wort
    ["Dokument.pdf", "Dokument (1).pdf", "Dokument_2.pdf"],  # Zaehler sind kein Zusatz
    ["Scan.pdf", "Scan Mai 2025.pdf"],  # zu kurzer gemeinsamer Anfang
    [JUNI, JUNI[:-4] + " " + "x" * 40 + ".pdf"],  # zu langer Zusatz: eher ein anderes Dokument
    [JUNI, "2025-06-11_Rechnung_Anbieter_Festnetz_2025-06-30.pdf"],  # ein weiteres Datum ist kein Merkmal
    [],
])
def test_keine_gruppe(namen):
    assert nu.uneinheitliche_gruppen(namen) == []


@pytest.mark.parametrize("roh, vorbild, erwartet", [
    ("Juni 2025", " Mai 2025", " Juni 2025"),
    ("  März / 2025 ", "_Mai-2025", "_Maerz-2025"),
    ("Juni 2025", "_Mai", "_Juni_2025"),
    ("", " Mai 2025", None),
    (None, " Mai 2025", None),
    ("...", " Mai 2025", None),
])
def test_zusatz_bereinigen_uebernimmt_die_schreibweise(roh, vorbild, erwartet):
    assert nu.zusatz_bereinigen(roh, vorbild) == erwartet


def test_zusatz_einfuegen_vor_der_endung():
    assert nu.zusatz_einfuegen(JUNI, " Juni 2025") == "2025-06-11_Rechnung_Anbieter_Festnetz Juni 2025.pdf"
    assert nu.zusatz_einfuegen("a_b.docx", "_X") == "a_b_X.docx"


def test_ergaenzen_fragt_mit_beispiel_und_nur_den_texten_ohne_zusatz():
    provider = _Provider("Hier:\n" + json.dumps({"merkmale": ["Juni 2025", ""]}))
    zusaetze = nu.ergaenzen(provider, [(MAI, " Mai 2025")], [JUNI, JULI],
                            ["Abrechnung fuer Juni 2025", "ohne Angabe"])
    assert zusaetze == [" Juni 2025", None]
    frage, = provider.fragen
    assert '"Mai 2025"' in frage and "Abrechnung fuer Juni 2025" in frage
    assert "--- Dokument 2" in frage and "--- Dokument 3" not in frage


@pytest.mark.parametrize("antwort, teil", [
    ("", "nicht geantwortet"),
    ("[Claude-Fehler: 401]", "401"),
    ("kein JSON", "kein passendes Merkmal"),
    ('{"merkmale": ["nur eins"]}', "kein passendes Merkmal"),  # falsche Anzahl
    ('{"merkmale": ["", ""]}', "kein passendes Merkmal"),  # nichts gefunden
])
def test_ergaenzen_meldet_unbrauchbare_antworten(antwort, teil):
    with pytest.raises(RuntimeError, match=teil):
        nu.ergaenzen(_Provider(antwort), [(MAI, " Mai 2025")], [JUNI, JULI], ["a", "b"])

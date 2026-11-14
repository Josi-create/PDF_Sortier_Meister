"""Der Chat gibt nicht zu frueh auf (Issue #264).

1. Der aus der Frage geratene Absender ("Vermieter", "Finanzamt") ist kein
   harter Filter mehr: Bleibt das Ergebnis leer oder duenn, fuellt dieselbe
   Suche ohne Absender auf.
2. Das Werkzeug ``suche`` liefert bei einem Absender-Filter ohne Treffer die
   Treffer ohne diesen Filter, deutlich gekennzeichnet.
3. Sagt das Modell nach weniger als ``MIN_SUCHVERSUCHE`` eigenen Suchen "keine
   passenden Dokumente", bekommt es einen Hinweis auf offene Suchwege.

Echte ``Database`` mit Suchindex unter ``tmp_path``, erfundene PDFs, kein Netz.
"""
from __future__ import annotations

import pytest

from src.ml.llm_provider import WerkzeugAntwort, WerkzeugAufruf
from src.rag.rag_controller import MIN_SUCHVERSUCHE, RAGController
from src.rag.retrieval import RetrievalService
from src.rag.werkzeuge import Werkzeugkasten
from src.utils.config import ChatConfig
from src.utils.database import Database
from tests import helfer_suche as h

OHNE_ABSENDER = "Scan_0001.pdf"
MIT_ABSENDER = "Vermieter_Mieterhoehung.pdf"
FREMD = "Scan_0002.pdf"
FRAGE = "Was schreibt der Vermieter zur Nebenkostenabrechnung?"
AUFGABE = "Ich finde dazu keine passenden Dokumente in deiner Sammlung."


@pytest.fixture
def db(tmp_path):
    """Ein Schreiben ohne gespeicherten Absender, eines mit Absender "Vermieter", ein fremdes."""
    db = Database(tmp_path / "t.db")
    ablage = tmp_path / "Ablage Größe"  # Pfad mit Umlaut und Leerzeichen
    ablage.mkdir()
    dateien = [
        (OHNE_ABSENDER, "Nebenkostenabrechnung 2024 Betriebskosten Nachzahlung 212,40 EUR Musterweg 1", {}),
        (MIT_ABSENDER, "Mieterhoehung zum 01.07.2025 Nebenkostenabrechnung folgt gesondert",
         {"korrespondent": "Vermieter"}),
        (FREMD, "Kraftfahrtversicherung Beitragsrechnung 2025 Jahresbeitrag 480,00 EUR", {}),
    ]
    for name, text, meta in dateien:
        h.pdf_mit_text(ablage / name, [text])
        db.index_document(str(ablage / name), name, **meta)
    return db


# --------------------------------------------------------------------------- 1) Suche vorab

def test_geratener_absender_wirft_dokumente_ohne_absender_nicht_mehr_heraus(db):
    rs = RetrievalService(db)
    assert rs._extract_filters(FRAGE).get("korrespondent") == "Vermieter"

    namen = [d.filename for d in rs.retrieve(FRAGE, k=8)]

    # Treffer mit dem Absender zuerst, dahinter das Schreiben ohne gespeicherten Absender
    assert namen[0] == MIT_ABSENDER
    assert OHNE_ABSENDER in namen
    assert len(namen) == len(set(namen))


def test_nur_dokumente_ohne_absender_werden_gefunden(db):
    # "Finanzamt" steht in keinem Absender-Feld: frueher null Treffer
    namen = [d.filename for d in RetrievalService(db).retrieve("Was will das Finanzamt zur Kraftfahrtversicherung?")]
    assert namen == [FREMD]


def test_genug_treffer_mit_absender_bleiben_unter_sich(db):
    namen = [d.filename for d in RetrievalService(db).retrieve(FRAGE, k=1)]
    assert namen == [MIT_ABSENDER]


def test_frage_ohne_absender_sucht_wie_bisher_nur_einmal(db, monkeypatch):
    rs = RetrievalService(db)
    aufrufe = []
    echt = rs._suche
    monkeypatch.setattr(rs, "_suche", lambda *a, **kw: aufrufe.append(kw) or echt(*a, **kw))
    rs.retrieve("Wo ist die Nebenkostenabrechnung?")
    assert len(aufrufe) == 1 and "korrespondent" not in aufrufe[0]


# --------------------------------------------------------------------------- 2) Werkzeug suche

def _kasten(db) -> Werkzeugkasten:
    return Werkzeugkasten(db, ChatConfig())


def test_werkzeug_suche_ohne_treffer_mit_absender_sucht_ohne_ihn(db):
    kasten = _kasten(db)
    text = kasten.ausfuehren(WerkzeugAufruf("suche", {"abfrage": "Betriebskosten", "korrespondent": "Hausverwaltung"}))

    assert text.startswith("Keine Treffer für „Betriebskosten“ (korrespondent=Hausverwaltung):")
    assert "ohne den Filter korrespondent" in text
    assert "1 Treffer für „Betriebskosten“:" in text and OHNE_ABSENDER in text
    assert kasten.protokoll[-1].zusammenfassung == (
        "Suche „Betriebskosten“ (korrespondent=Hausverwaltung): keine Treffer - "
        "ohne Filter korrespondent 1 Treffer (D1)"
    )
    assert [d.filename for d in kasten.dokumente()] == [OHNE_ABSENDER]


def test_werkzeug_suche_mit_treffern_zum_absender_bleibt_gefiltert(db):
    kasten = _kasten(db)
    text = kasten.ausfuehren(WerkzeugAufruf("suche", {"abfrage": "Nebenkostenabrechnung", "korrespondent": "Vermieter"}))
    assert text.startswith("1 Treffer für „Nebenkostenabrechnung“ (korrespondent=Vermieter):")
    assert OHNE_ABSENDER not in text


def test_werkzeug_suche_auch_ohne_absender_nichts(db):
    kasten = _kasten(db)
    text = kasten.ausfuehren(WerkzeugAufruf("suche", {"abfrage": "Segelboot", "korrespondent": "Vermieter"}))
    assert text.startswith("Keine Treffer für „Segelboot“ (korrespondent=Vermieter).")
    assert kasten.protokoll[-1].zusammenfassung == "Suche „Segelboot“ (korrespondent=Vermieter): keine Treffer"
    assert len(kasten.suchversuche()) == 1


# --------------------------------------------------------------------------- 3) Mindestzahl Suchversuche

class _LLM:
    """Provider-Stub mit vorgegebener Folge; merkt sich die Nachrichten und Werkzeuglisten."""

    def __init__(self, antworten):
        self.antworten = list(antworten)
        self.aufrufe: list[tuple[list[dict], list[str]]] = []

    def is_available(self) -> bool:
        return True

    def unterstuetzt_werkzeuge(self) -> bool:
        return True

    def chat_mit_werkzeugen(self, nachrichten, werkzeuge, max_tokens=1000) -> WerkzeugAntwort:
        self.aufrufe.append(([dict(n) for n in nachrichten], [w.name for w in werkzeuge]))
        return self.antworten.pop(0) if self.antworten else WerkzeugAntwort(text="darf nie kommen")


def _suche(abfrage: str) -> WerkzeugAntwort:
    return WerkzeugAntwort(text="", aufrufe=[WerkzeugAufruf("suche", {"abfrage": abfrage})])


def _hinweise(llm: _LLM) -> list[str]:
    return [n["content"] for n in llm.aufrufe[-1][0] if n["role"] == "user" and "Gib noch nicht auf" in n["content"]]


def test_zu_frueh_aufgegeben_bekommt_hinweis_und_sucht_weiter(db):
    llm = _LLM([
        WerkzeugAntwort(text=AUFGABE),
        _suche("Kraftfahrt*"),
        WerkzeugAntwort(text=f"Der Jahresbeitrag beträgt 480,00 EUR [1].\n\nQuellen:\n[1] {FREMD}"),
    ])
    meldungen: list[str] = []
    response = RAGController(db, llm, ChatConfig()).ask("Was kostet meine Autoversicherung?",
                                                         fortschritt=meldungen.append)

    assert len(llm.aufrufe) == 3 and not llm.antworten
    hinweise = _hinweise(llm)
    assert len(hinweise) == 1
    assert "noch gar nicht selbst gesucht" in hinweise[0] and "ohne Filter" in hinweise[0]
    # Die verworfene Aufgabe steht als Assistentennachricht davor, die Werkzeuge bleiben verfuegbar
    rollen = [n["role"] for n in llm.aufrufe[1][0]]
    assert rollen[-2:] == ["assistant", "user"] and "suche" in llm.aufrufe[1][1]
    assert any("weitere Suchwege" in m for m in meldungen)
    assert response.used_llm and [c.filename for c in response.citations] == [FREMD]


def test_hinweis_nennt_die_bisherigen_suchen(db):
    llm = _LLM([
        _suche("Autoversicherung"),
        WerkzeugAntwort(text=AUFGABE),
        _suche("Kfz* ODER Kraftfahrt*"),
        WerkzeugAntwort(text=f"480,00 EUR im Jahr [1].\n\nQuellen:\n[1] {FREMD}"),
    ])
    response = RAGController(db, llm, ChatConfig()).ask("Was kostet meine Autoversicherung?")

    hinweise = _hinweise(llm)
    assert len(hinweise) == 1 and "Bisher hast du gesucht: Suche „Autoversicherung“: keine Treffer." in hinweise[0]
    assert [c.filename for c in response.citations] == [FREMD]


def test_wer_nach_dem_hinweis_nicht_sucht_darf_aufgeben(db):
    llm = _LLM([WerkzeugAntwort(text=AUFGABE), WerkzeugAntwort(text=AUFGABE + " Am ehesten passt nichts.")])
    response = RAGController(db, llm, ChatConfig()).ask("Was kostet mein Segelboot im Hafen?")
    assert len(llm.aufrufe) == 2
    assert response.used_llm and response.answer_text.startswith(AUFGABE)


def test_nach_genug_suchversuchen_kein_hinweis(db):
    llm = _LLM([*[_suche(f"Segelboot{i}") for i in range(MIN_SUCHVERSUCHE)], WerkzeugAntwort(text=AUFGABE)])
    response = RAGController(db, llm, ChatConfig()).ask("Was kostet mein Segelboot im Hafen?")
    assert len(llm.aufrufe) == MIN_SUCHVERSUCHE + 1 and not _hinweise(llm)
    assert response.answer_text == AUFGABE


def test_antwort_mit_beleg_bekommt_keinen_hinweis(db):
    llm = _LLM([WerkzeugAntwort(text=f"480,00 EUR im Jahr [1].\n\nQuellen:\n[1] {FREMD}")])
    RAGController(db, llm, ChatConfig()).ask("Was kostet die Kraftfahrtversicherung?")
    assert len(llm.aufrufe) == 1


def test_obergrenze_der_schritte_bleibt(db):
    # Bei 2 Schritten waere der Schritt nach dem Hinweis schon der letzte (ohne Werkzeuge): kein Hinweis
    llm = _LLM([WerkzeugAntwort(text=AUFGABE)])
    response = RAGController(db, llm, ChatConfig(max_werkzeug_schritte=2)).ask("Was kostet mein Segelboot?")
    assert len(llm.aufrufe) == 1 and response.answer_text == AUFGABE

    # Bei 3 Schritten: Hinweis, eine Suche, dann der letzte Schritt ohne Werkzeuge - nie mehr als 3 Modellaufrufe
    llm = _LLM([WerkzeugAntwort(text=AUFGABE), _suche("Boot*"), WerkzeugAntwort(text=AUFGABE)])
    RAGController(db, llm, ChatConfig(max_werkzeug_schritte=3)).ask("Was kostet mein Segelboot?")
    assert len(llm.aufrufe) == 3 and llm.aufrufe[2][1] == []

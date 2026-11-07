"""Werkzeug-Schleife des RAGControllers (Issue #166/#167, Phase 2).

Fake-Provider mit vorgegebener Folge von ``WerkzeugAntwort``; echte
``Database`` mit Suchindex unter ``tmp_path`` und synthetischen PDFs aus
``tests/helfer_suche.py``. Keine Netz- und keine GUI-Abhaengigkeiten.
"""
from __future__ import annotations

import os
import threading

import pytest

from src.ml.llm_provider import WerkzeugAntwort, WerkzeugAufruf
from src.rag.bezug import Bezug
from src.rag.prompts import SYSTEM_PROMPT_WERKZEUGE, build_system_prompt_werkzeuge
from src.rag.rag_controller import ABGEBROCHEN_TEXT, RAGController, RAGResponse
from src.rag.werkzeuge import Schritt
from src.utils.config import ChatConfig
from src.utils.database import Database
from tests import helfer_suche as h

BEZUG_TEXT = (
    "Preisanpassung zum 03.05.2026 fuer Ihren Gasliefervertrag mit der Vertragsnummer G22504020299. "
    "Zaehlernummer 226541. Stadtwerke Musterstadt Jahresabrechnung Strom und Gas."
)
JAHRESABRECHNUNG = "Stadtwerke_Jahresabrechnung_Strom_2024.pdf"
STAMMDATEN = "Stadtwerke_Stammdaten.pdf"
TELEKOM = "Telekom_Rechnung_Internet.pdf"
FRAGE = "Zu welcher Abnahmestelle gehört dieses Dokument?"
OHNE_WERKZEUGE = ["suche", "dokument_lesen", "ordner_vorschlag", "korrespondent_info"]


class _WerkzeugLLM:
    """Provider-Stub: ``chat_mit_werkzeugen`` liefert eine vorgegebene Folge und merkt sich die Nachrichten.

    Ein Eintrag der Folge darf auch eine Funktion ``(nachrichten, werkzeuge) -> WerkzeugAntwort``
    sein (z.B. um mitten im Lauf den Abbruch zu setzen). Ist die Folge leer,
    kommt ``"Fertig."`` ohne Aufrufe.
    """

    def __init__(self, antworten=(), unterstuetzt: bool = True, available: bool = True):
        self.antworten = list(antworten)
        self._unterstuetzt = unterstuetzt
        self._available = available
        # je Modellaufruf: (Kopie der Nachrichten, Werkzeugnamen, max_tokens)
        self.aufrufe: list[tuple[list[dict], list[str], int]] = []
        self.answer_calls = 0
        self.context_docs: list = []

    def is_available(self) -> bool:
        return self._available

    def unterstuetzt_werkzeuge(self) -> bool:
        return self._unterstuetzt

    def chat_mit_werkzeugen(self, nachrichten, werkzeuge, max_tokens=1000) -> WerkzeugAntwort:
        self.aufrufe.append(([dict(n) for n in nachrichten], [w.name for w in werkzeuge], max_tokens))
        if not self.antworten:
            return WerkzeugAntwort(text="Fertig.")
        antwort = self.antworten.pop(0)
        if callable(antwort):
            antwort = antwort(nachrichten, werkzeuge)
        return antwort

    def answer_with_context(self, system_prompt, context_docs, user_question, max_tokens=1000) -> str:
        self.answer_calls += 1
        self.context_docs = list(context_docs or [])
        return "Alter Weg [1]."


@pytest.fixture
def sammlung(tmp_path):
    """Datenbank mit drei indexierten PDFs unter ``Ablage`` und einem nicht indexierten Bezug im Scan-Eingang."""
    db = Database(tmp_path / "t.db")
    ablage = tmp_path / "Ablage"
    energie = ablage / "Energie"
    telekom = ablage / "Telekom"
    energie.mkdir(parents=True)
    telekom.mkdir(parents=True)
    dateien = [
        (energie / JAHRESABRECHNUNG, [
            "Stadtwerke Musterstadt Jahresabrechnung Strom Vertragsnummer G22504020299 Kundennummer 4711",
            "Seite zwei: Zaehlernummer 226541 Abnahmestelle Kellermannstr. 3, 48149 Muenster",
            "Seite drei: Gesamtbetrag 480,00 EUR faellig am 15.04.2024",
        ], {"korrespondent": "Stadtwerke Musterstadt", "kategorie": "Rechnung", "steuerjahr": "2024",
            "betrag": "480.00"}, 1_600_000_000),
        (energie / STAMMDATEN, [
            "Stadtwerke Musterstadt Stammdatenblatt Zaehlernummer 226541 Netzbetreiber Stadtnetze Muenster",
        ], {"korrespondent": "Stadtwerke Musterstadt"}, 1_700_000_000),
        (telekom / TELEKOM, [
            "Telekom Rechnung Internet 49,95 EUR Kundennummer 99887 Wohnung Musterweg 1",
        ], {"korrespondent": "Telekom", "kategorie": "Rechnung", "steuerjahr": "2024", "betrag": "49.95"},
         1_650_000_000),
    ]
    for pfad, texte, meta, mtime in dateien:
        h.pdf_mit_text(pfad, texte)
        os.utime(pfad, (mtime, mtime))
        db.index_document(str(pfad), pfad.name, **meta)
    scan = tmp_path / "Scan"
    scan.mkdir()
    bezug = Bezug(pfad=scan / "Neu.pdf", text=BEZUG_TEXT, scan_ordner=scan, wurzeln=[ablage],
                  sortier_vorschlaege=["Ablage/Energie (80 %)", "Ablage/Telekom (10 %)"])
    return db, bezug


def _suche(abfrage: str, **mehr) -> WerkzeugAntwort:
    return WerkzeugAntwort(text="", aufrufe=[WerkzeugAufruf("suche", {"abfrage": abfrage}, **mehr)])


def _rollen(nachrichten: list[dict]) -> list[str]:
    return [n["role"] for n in nachrichten]


# --------------------------------------------------------------------------- (a) voller Lauf

def test_schleife_suche_lesen_antwort(sammlung):
    db, bezug = sammlung
    llm = _WerkzeugLLM([
        _suche("226541", id="call_1"),
        WerkzeugAntwort(text="Ich lese Seite 2.", aufrufe=[WerkzeugAufruf("dokument_lesen",
                                                                            {"dokument": "D2", "seiten": "2"})],
                        roh={"role": "assistant", "tool_calls": ["…"]}),
        WerkzeugAntwort(text=f"Die Abnahmestelle ist Kellermannstr. 3 [2].\n\nQuellen:\n[2] {JAHRESABRECHNUNG}"),
    ])
    ctrl = RAGController(db, llm, ChatConfig())

    response = ctrl.ask(FRAGE, bezug=bezug)

    # Vorab registriert: Bezug als D1, Kennungs-Treffer D2 (beide Kennungen) und D3
    docs = response.retrieved_docs
    assert [d.index for d in docs] == [1, 2, 3]
    assert docs[0].filename == "Neu.pdf" and docs[0].extra["bezug"] is True
    assert docs[1].filename == JAHRESABRECHNUNG and docs[2].filename == STAMMDATEN
    assert docs[1].extra["ordner"] == "Ablage/Energie"

    # Nachrichtenstruktur je Modellaufruf
    assert len(llm.aufrufe) == 3
    erste, werkzeuge, max_tokens = llm.aufrufe[0]
    assert _rollen(erste) == ["system", "user"]
    assert erste[0]["content"] == build_system_prompt_werkzeuge(8)
    assert "{max_schritte}" not in erste[0]["content"] and "höchstens 8 Schritte" in erste[0]["content"]
    assert "=== DOKUMENTE ===" in erste[1]["content"] and "BEZUGSDOKUMENT" in erste[1]["content"]
    assert "[D1] dateiname=Neu.pdf" in erste[1]["content"] and f"[D2] dateiname={JAHRESABRECHNUNG}" in erste[1]["content"]
    assert f"FRAGE: {FRAGE}" in erste[1]["content"]
    assert werkzeuge == OHNE_WERKZEUGE and max_tokens == 1000

    zweite = llm.aufrufe[1][0]
    assert _rollen(zweite) == ["system", "user", "assistant", "tool"]
    assistent = zweite[2]
    assert assistent["content"] == "" and assistent["roh"] is None
    assert [a.name for a in assistent["aufrufe"]] == ["suche"] and assistent["aufrufe"][0].id == "call_1"
    werkzeug = zweite[3]
    assert werkzeug["aufruf_id"] == "call_1" and werkzeug["name"] == "suche"
    assert werkzeug["content"].startswith("2 Treffer für „226541“")

    dritte = llm.aufrufe[2][0]
    assert _rollen(dritte) == ["system", "user", "assistant", "tool", "assistant", "tool"]
    assert dritte[4]["content"] == "Ich lese Seite 2." and dritte[4]["roh"] == {"role": "assistant", "tool_calls": ["…"]}
    assert dritte[4]["aufrufe"][0].id == "aufruf_2"  # ohne Id vom Provider: fortlaufend
    assert dritte[5]["aufruf_id"] == "aufruf_2" and dritte[5]["name"] == "dokument_lesen"
    assert dritte[5]["content"].startswith("[D2]\n# " + JAHRESABRECHNUNG) and "Kellermannstr" in dritte[5]["content"]
    assert llm.aufrufe[2][1] == OHNE_WERKZEUGE  # Schritt 3 von 6: noch mit Werkzeugen

    # Protokoll, Zitat, Status
    assert [s.werkzeug for s in response.schritte] == ["suche", "dokument_lesen"]
    assert all(isinstance(s, Schritt) and not s.fehler for s in response.schritte)
    assert response.schritte[0].zusammenfassung.startswith("Suche „226541“: 2 Treffer (D")
    assert sorted(response.schritte[0].dokumente) == [2, 3]  # Reihenfolge = Relevanz der Suche
    assert response.schritte[1].zusammenfassung.startswith("D2 gelesen (Seiten 2)")
    assert response.used_llm and response.werkzeuge_benutzt and not response.has_hallucinated_citations
    assert response.answer_text.startswith("Die Abnahmestelle ist Kellermannstr. 3 [2].")
    assert [c.index for c in response.citations] == [2]
    zitat = response.citations[0]
    assert zitat.filename == JAHRESABRECHNUNG and zitat.file_path == docs[1].file_path
    assert zitat.seite == 1  # Seite der ersten Fundstelle (Vertragsnummer auf Seite 1)
    assert [d.extra["status"] for d in docs] == ["gefunden", "zitiert", "gefunden"]
    assert llm.answer_calls == 0

    # Session-Historie wie bisher
    turns = ctrl.chat_session.get_recent(2)
    assert [t.role for t in turns] == ["user", "assistant"]
    assert turns[1].citations[0]["index"] == 2 and turns[1].citations[0]["seite"] == 1


def test_bezug_traegt_volltext_fuer_dokument_lesen(sammlung):
    db, bezug = sammlung
    llm = _WerkzeugLLM([
        WerkzeugAntwort(aufrufe=[WerkzeugAufruf("dokument_lesen", {"dokument": "D1"})]),
        WerkzeugAntwort(text="Vertragsnummer G22504020299 [1]."),
    ])
    response = RAGController(db, llm, ChatConfig()).ask("Welche Vertragsnummer?", bezug=bezug)
    tool = llm.aufrufe[1][0][3]
    assert tool["content"].startswith("[D1]\n# Neu.pdf") and "G22504020299" in tool["content"]
    assert response.retrieved_docs[0].extra["volltext"].startswith("Preisanpassung")
    assert response.retrieved_docs[0].extra["status"] == "zitiert"
    assert response.citations[0].index == 1


def test_ohne_bezug_kontext_sind_die_treffer_zur_frage(sammlung):
    db, bezug = sammlung
    llm = _WerkzeugLLM([WerkzeugAntwort(text="Telekom [1].")])
    response = RAGController(db, llm, ChatConfig()).ask("Telekom Rechnung Internet")
    erste = llm.aufrufe[0][0]
    assert "BEZUGSDOKUMENT" not in erste[1]["content"] and "[D1] dateiname=" in erste[1]["content"]
    assert response.retrieved_docs[0].filename == TELEKOM and response.citations[0].filename == TELEKOM
    assert response.werkzeuge_benutzt and response.schritte == []


# --------------------------------------------------------------------------- (b), (c) alter Weg

def test_provider_ohne_werkzeugunterstuetzung_geht_den_alten_weg(sammlung):
    db, bezug = sammlung
    llm = _WerkzeugLLM([_suche("x")], unterstuetzt=False)
    response = RAGController(db, llm, ChatConfig()).ask(FRAGE, bezug=bezug)
    assert llm.answer_calls == 1 and llm.aufrufe == []
    assert llm.context_docs[0]["bezug"] is True
    assert response.used_llm and response.answer_text == "Alter Weg [1]."
    assert response.schritte == [] and response.werkzeuge_benutzt is False


def test_werkzeuge_aktiv_aus_geht_den_alten_weg(sammlung):
    db, bezug = sammlung
    llm = _WerkzeugLLM([_suche("x")])
    response = RAGController(db, llm, ChatConfig(werkzeuge_aktiv=False)).ask(FRAGE, bezug=bezug)
    assert llm.answer_calls == 1 and llm.aufrufe == []
    assert response.schritte == [] and response.werkzeuge_benutzt is False


def test_provider_ohne_die_methoden_geht_den_alten_weg(sammlung):
    from tests.test_rag_controller import _SpyLLM

    db, bezug = sammlung
    llm = _SpyLLM()
    response = RAGController(db, llm, ChatConfig()).ask(FRAGE, bezug=bezug)
    assert llm.calls == 1 and response.used_llm and response.werkzeuge_benutzt is False


# --------------------------------------------------------------------------- (d), (e) Fehler

def test_fehler_im_ersten_schritt_faellt_auf_den_alten_weg_zurueck(sammlung):
    db, bezug = sammlung
    llm = _WerkzeugLLM([WerkzeugAntwort(fehler="HTTP 400: model does not support tools - Werkzeuge")])
    meldungen: list[str] = []
    response = RAGController(db, llm, ChatConfig()).ask(FRAGE, bezug=bezug, fortschritt=meldungen.append)
    assert len(llm.aufrufe) == 1 and llm.answer_calls == 1
    assert response.used_llm and response.answer_text == "Alter Weg [1]."
    assert response.werkzeuge_benutzt is False and response.schritte == []
    assert any("ohne Werkzeuge" in m for m in meldungen)


def test_leere_antwort_im_ersten_schritt_faellt_zurueck(sammlung):
    db, bezug = sammlung
    llm = _WerkzeugLLM([WerkzeugAntwort(text="   ")])
    response = RAGController(db, llm, ChatConfig()).ask(FRAGE, bezug=bezug)
    assert llm.answer_calls == 1 and response.answer_text == "Alter Weg [1]."


def test_fehler_im_zweiten_schritt_liefert_fehlertext(sammlung):
    db, bezug = sammlung
    llm = _WerkzeugLLM([_suche("Telekom"), WerkzeugAntwort(fehler="Verbindung abgebrochen")])
    ctrl = RAGController(db, llm, ChatConfig())
    response = ctrl.ask(FRAGE, bezug=bezug)
    assert response.answer_text == "Werkzeugaufruf fehlgeschlagen: Verbindung abgebrochen"
    assert response.used_llm is False and response.werkzeuge_benutzt is True
    assert llm.answer_calls == 0 and len(llm.aufrufe) == 2
    assert [s.werkzeug for s in response.schritte] == ["suche"]
    assert TELEKOM in [d.filename for d in response.retrieved_docs]
    # Fehler werden nicht gecacht: die gleiche Frage versucht es erneut
    llm.antworten = [WerkzeugAntwort(text="Jetzt klappt es.")]
    nochmal = ctrl.ask(FRAGE, bezug=bezug)
    assert nochmal.answer_text == "Jetzt klappt es." and len(llm.aufrufe) == 3


def test_provider_der_wirft_wird_wie_fehler_behandelt(sammlung):
    db, bezug = sammlung

    def kaputt(nachrichten, werkzeuge):
        raise RuntimeError("Stecker gezogen")

    llm = _WerkzeugLLM([_suche("Telekom"), kaputt])
    response = RAGController(db, llm, ChatConfig()).ask(FRAGE, bezug=bezug)
    assert response.answer_text == "Werkzeugaufruf fehlgeschlagen: Stecker gezogen"


# --------------------------------------------------------------------------- (f) Abbruch

def test_abbruch_vor_dem_ersten_modellaufruf(sammlung):
    db, bezug = sammlung
    llm = _WerkzeugLLM([_suche("x")])
    abbruch = threading.Event()
    abbruch.set()
    ctrl = RAGController(db, llm, ChatConfig())
    response = ctrl.ask(FRAGE, bezug=bezug, abbruch=abbruch)
    assert response.answer_text == ABGEBROCHEN_TEXT == "Abgebrochen."
    assert response.used_llm is False and response.schritte == []
    assert llm.aufrufe == [] and llm.answer_calls == 0
    assert [d.index for d in response.retrieved_docs] == [1, 2, 3]
    # Nicht gecacht: ohne Abbruch laeuft die Frage danach normal
    nochmal = ctrl.ask(FRAGE, bezug=bezug)
    assert nochmal.answer_text != ABGEBROCHEN_TEXT and len(llm.aufrufe) >= 1


def test_abbruch_vor_dem_werkzeugaufruf(sammlung):
    db, bezug = sammlung
    abbruch = threading.Event()

    def modell_antwortet_und_nutzer_bricht_ab(nachrichten, werkzeuge):
        abbruch.set()
        return _suche("Telekom")

    llm = _WerkzeugLLM([modell_antwortet_und_nutzer_bricht_ab, WerkzeugAntwort(text="nie")])
    response = RAGController(db, llm, ChatConfig()).ask(FRAGE, bezug=bezug, abbruch=abbruch)
    assert response.answer_text == ABGEBROCHEN_TEXT
    assert len(llm.aufrufe) == 1 and response.schritte == []  # Werkzeug lief nicht mehr
    assert TELEKOM not in [d.filename for d in response.retrieved_docs]


# --------------------------------------------------------------------------- (g) Schrittgrenze

def test_letzter_schritt_erzwingt_antwort_ohne_werkzeuge(sammlung):
    db, bezug = sammlung
    llm = _WerkzeugLLM([
        _suche("Telekom"),
        WerkzeugAntwort(text="Antwort nach zwei Schritten [1]."),
        WerkzeugAntwort(text="darf nie kommen"),
    ])
    response = RAGController(db, llm, ChatConfig(max_werkzeug_schritte=2)).ask(FRAGE, bezug=bezug)
    assert len(llm.aufrufe) == 2 and len(llm.antworten) == 1
    assert llm.aufrufe[0][1] == OHNE_WERKZEUGE and llm.aufrufe[1][1] == []
    assert "höchstens 2 Schritte" in llm.aufrufe[0][0][0]["content"]
    assert response.answer_text == "Antwort nach zwei Schritten [1]."
    assert response.used_llm and [s.werkzeug for s in response.schritte] == ["suche"]


def test_letzter_schritt_mit_aufrufen_nimmt_den_text(sammlung):
    db, bezug = sammlung
    llm = _WerkzeugLLM([
        _suche("Telekom"),
        WerkzeugAntwort(text="Trotzdem eine Antwort [1].", aufrufe=[WerkzeugAufruf("suche", {"abfrage": "x"})]),
    ])
    response = RAGController(db, llm, ChatConfig(max_werkzeug_schritte=2)).ask(FRAGE, bezug=bezug)
    assert response.answer_text == "Trotzdem eine Antwort [1]." and response.used_llm
    assert [s.werkzeug for s in response.schritte] == ["suche"]  # der zweite Aufruf lief nicht

    # Ohne Text folgt ein zweiter Anlauf mit Nachdruck (Live-Test-Befund); der Stub antwortet dann "Fertig."
    llm = _WerkzeugLLM([_suche("Telekom"), WerkzeugAntwort(aufrufe=[WerkzeugAufruf("suche", {"abfrage": "x"})])])
    response = RAGController(db, llm, ChatConfig(max_werkzeug_schritte=2)).ask(FRAGE, bezug=bezug)
    assert response.answer_text == "Fertig." and response.used_llm
    assert len(llm.aufrufe) == 3 and llm.aufrufe[2][1] == []
    assert llm.aufrufe[2][0][-1]["role"] == "user"


# --------------------------------------------------------------------------- (h) Fortschritt

def test_fortschritt_meldungen(sammlung):
    db, bezug = sammlung
    llm = _WerkzeugLLM([
        WerkzeugAntwort(aufrufe=[
            WerkzeugAufruf("suche", {"abfrage": "226541"}),
            WerkzeugAufruf("korrespondent_info", {"name": "Telekom"}),
        ]),
        WerkzeugAntwort(aufrufe=[WerkzeugAufruf("dokument_lesen", {"dokument": 2}),
                                 WerkzeugAufruf("ordner_vorschlag", {}),
                                 WerkzeugAufruf("sql_abfrage", {"sql": "SELECT 1"})]),
        WerkzeugAntwort(text="Fertig [2]."),
    ])
    meldungen: list[str] = []
    RAGController(db, llm, ChatConfig(sql_erlaubt=True)).ask(FRAGE, bezug=bezug, fortschritt=meldungen.append)
    assert meldungen[0] == "KI denkt (Schritt 1/8) …"
    assert "KI denkt (Schritt 2/8) …" in meldungen and "KI denkt (Schritt 3/8) …" in meldungen
    for erwartet in ("Suche „226541“ …", "Korrespondent „Telekom“ …", "Korrespondent „Telekom“: unbekannt",
                     "Lese D2 …", "Ordnervorschlag …", "SQL-Abfrage …", "SQL: 1 Zeilen"):
        assert erwartet in meldungen, (erwartet, meldungen)
    ergebnis = next(i for i, m in enumerate(meldungen) if m.startswith("Suche „226541“: 2 Treffer (D"))
    assert meldungen.index("KI denkt (Schritt 1/8) …") < meldungen.index("Suche „226541“ …") < ergebnis
    assert ergebnis < meldungen.index("KI denkt (Schritt 2/8) …") < meldungen.index("Lese D2 …")
    assert meldungen.index("SQL: 1 Zeilen") < meldungen.index("KI denkt (Schritt 3/8) …") == len(meldungen) - 1


def test_fortschritt_callback_der_wirft_stoert_nicht(sammlung):
    db, bezug = sammlung

    def kaputt(text):
        raise RuntimeError("GUI weg")

    llm = _WerkzeugLLM([_suche("Telekom"), WerkzeugAntwort(text="Ok [1].")])
    response = RAGController(db, llm, ChatConfig()).ask(FRAGE, bezug=bezug, fortschritt=kaputt)
    assert response.answer_text == "Ok [1]."


# --------------------------------------------------------------------------- (i) SQL-Freigabe

def test_sql_nur_mit_freigabe_in_den_definitionen(sammlung):
    db, bezug = sammlung
    llm = _WerkzeugLLM([])
    RAGController(db, llm, ChatConfig(sql_erlaubt=True)).ask(FRAGE, bezug=bezug)
    assert llm.aufrufe[0][1] == OHNE_WERKZEUGE + ["sql_abfrage"]

    llm = _WerkzeugLLM([])
    RAGController(db, llm, ChatConfig(sql_erlaubt=False)).ask(FRAGE, bezug=bezug)
    assert llm.aufrufe[0][1] == OHNE_WERKZEUGE

    # Ohne Freigabe lehnt der Kasten einen Aufruf ab, die Schleife laeuft weiter
    llm = _WerkzeugLLM([WerkzeugAntwort(aufrufe=[WerkzeugAufruf("sql_abfrage", {"sql": "SELECT 1"})]),
                        WerkzeugAntwort(text="Dann eben nicht.")])
    response = RAGController(db, llm, ChatConfig()).ask(FRAGE, bezug=bezug)
    assert llm.aufrufe[1][0][3]["content"] == "Fehler: SQL-Abfragen sind in den Einstellungen nicht freigegeben."
    assert response.schritte[0].fehler and response.answer_text == "Dann eben nicht."


# --------------------------------------------------------------------------- Sonstiges

def test_halluzinierte_zitate_werden_entfernt_und_gemeldet(sammlung):
    db, bezug = sammlung
    llm = _WerkzeugLLM([WerkzeugAntwort(text="Siehe [2] und [9].")])
    response = RAGController(db, llm, ChatConfig()).ask(FRAGE, bezug=bezug)
    assert response.answer_text == "Siehe [2] und ."
    assert response.has_hallucinated_citations and [c.index for c in response.citations] == [2]


def test_prompt_konstante_und_response_felder():
    assert "{max_schritte}" in SYSTEM_PROMPT_WERKZEUGE
    prompt = build_system_prompt_werkzeuge(3)
    assert "höchstens 3 Schritte" in prompt and "{max_schritte}" not in prompt
    for stichwort in ("suche", "dokument_lesen", "ordner_vorschlag", "korrespondent_info", "sql_abfrage",
                      "Ich finde dazu keine passenden Dokumente in deiner Sammlung.", "Quellen:",
                      "Antworte in der Sprache der Frage", "Fordere den Nutzer nicht auf", "[D7]"):
        assert stichwort in prompt, stichwort
    assert build_system_prompt_werkzeuge("kaputt").count("höchstens 1 Schritte") == 1
    antwort = RAGResponse(answer_text="x")
    assert antwort.schritte == [] and antwort.werkzeuge_benutzt is False

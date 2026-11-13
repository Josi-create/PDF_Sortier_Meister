"""Schlagwoerter mit Ebenen (Issue #231): Regeln, Speichern in der PDF, Filter im Suchindex, Auswahl der KI.

Alle Dokumente und Schlagwoerter sind erfunden.
"""
from __future__ import annotations

import pytest

from src.core import schlagwoerter as sw
from src.core.pdf_metadata import PDFMetadata, read_metadata, write_metadata
from src.search.indexer import Indexer
from src.search.suchindex import Suchindex
from tests import helfer_suche as h


# --------------------------------------------------------------------------- Regeln

def test_automatische_stichwoerter_sind_die_der_analyse():
    from src.core.pdf_analyzer import KEYWORD_PATTERNS

    assert sw.AUTO_STICHWOERTER == frozenset(KEYWORD_PATTERNS)


def test_eingabe_wird_normalform():
    assert sw.aus_eingabe(" Steuer / Werbungskosten ;Haus,, haus , /Auto/ ") == [
        "Steuer/Werbungskosten", "Haus", "Auto"]
    assert sw.als_text(["Steuer/Werbungskosten", "Haus"]) == "Steuer/Werbungskosten, Haus"
    assert sw.aus_eingabe("") == [] and sw.aus_eingabe(None) == []
    # Umlaute und Leerzeichen im Schlagwort bleiben
    assert sw.aus_eingabe("Büro/Möbel  und  Geräte") == ["Büro/Möbel und Geräte"]
    # Wer genau ein automatisches Stichwort tippt, bekommt ein eigenes Schlagwort daraus
    assert sw.aus_eingabe("steuer, steuer/fahrt") == ["Steuer", "steuer/fahrt"]


def test_aufteilen_trennt_automatische_von_eigenen():
    assert sw.aufteilen("rechnung, Steuer/Werbungskosten, bank, Steuer") == (
        ["rechnung", "bank"], ["Steuer/Werbungskosten", "Steuer"])
    assert sw.eigene("steuer, Steuer") == ["Steuer"]          # klein = Analyse, gross = Nutzer
    assert sw.zusammenfuehren(["steuer", "rechnung"], ["Steuer", "Haus"]) == "steuer, rechnung, Steuer, Haus"
    assert sw.zusammenfuehren(None, None) == ""


def test_ebenen_passen_und_zaehlen():
    assert sw.mit_oberebenen("Steuer/Werbungskosten/Fahrt") == [
        "Steuer", "Steuer/Werbungskosten", "Steuer/Werbungskosten/Fahrt"]
    assert sw.mit_oberebenen("") == []
    assert sw.passt("rechnung, Steuer/Werbungskosten", "Steuer")
    assert sw.passt("Steuer/Werbungskosten", "Steuer/Werbungskosten")
    assert not sw.passt("Steuerberater, steuer", "Steuer")      # kein Wortanfang, kein Analyse-Stichwort
    assert not sw.passt("Steuer", "Steuer/Werbungskosten")      # die Oberebene allein reicht nicht
    assert sw.zaehlen(["Steuer/Werbungskosten, Haus", "rechnung, Steuer/Sonderausgaben", "bank"]) == {
        "Steuer": 2, "Steuer/Werbungskosten": 1, "Steuer/Sonderausgaben": 1, "Haus": 1}


def test_ki_darf_nur_bekannte_nennen():
    bekannte = ["Steuer", "Steuer/Werbungskosten", "Haus"]
    assert sw.nur_bekannte(["steuer/werbungskosten", "Erfunden", "Haus"], bekannte) == [
        "Steuer/Werbungskosten", "Haus"]
    assert sw.nur_bekannte("Haus; Garten", bekannte) == ["Haus"]
    assert sw.nur_bekannte(None, bekannte) == []


def test_benutzte_ohne_quelle_leer_und_fehler_der_quelle_stoeren_nicht():
    assert sw.benutzte() == []
    sw.quelle_setzen(lambda haeufigste=None: ["Haus", "Steuer"][:haeufigste])
    assert sw.benutzte() == ["Haus", "Steuer"] and sw.benutzte(1) == ["Haus"]

    def kaputt(_haeufigste=None):
        raise RuntimeError("Index nicht lesbar")

    sw.quelle_setzen(kaputt)
    assert sw.benutzte() == []


# --------------------------------------------------------------------------- Speichern in der PDF

def _info_keywords(pdf) -> str:
    import pymupdf

    doc = pymupdf.open(str(pdf))
    try:
        return doc.metadata.get("keywords") or ""
    finally:
        doc.close()


def test_schlagwoerter_stehen_in_der_pdf_neben_den_automatischen(tmp_path):
    pdf = h.pdf_mit_text(tmp_path / "Bürostuhl Rechnung.pdf", ["Rechnung Buerostuhl"])
    assert write_metadata(pdf, PDFMetadata(keywords="rechnung, bank", schlagwoerter="Steuer/Werbungskosten; Haus"))
    gelesen = read_metadata(pdf)
    assert gelesen.keywords == "rechnung, bank, Steuer/Werbungskosten, Haus"
    assert gelesen.schlagwoerter == "Steuer/Werbungskosten, Haus"
    # auch im Info-Verzeichnis, das der Suchindex und andere Programme lesen
    assert _info_keywords(pdf) == "rechnung, bank, Steuer/Werbungskosten, Haus"


def test_spaeteres_schreiben_ohne_schlagwoerter_behaelt_sie(tmp_path):
    pdf = h.pdf_mit_text(tmp_path / "a.pdf", ["Rechnung"])
    assert write_metadata(pdf, PDFMetadata(keywords="rechnung", schlagwoerter="Steuer/Werbungskosten"))
    # z. B. Umbenennen-Dialog: nur die Stichwoerter der Analyse, kein Feld Schlagwoerter
    meta = PDFMetadata(keywords="rechnung, energie", korrespondent="Stadtwerke Musterstadt")
    assert write_metadata(pdf, meta)
    assert meta.keywords == "rechnung, energie, Steuer/Werbungskosten"   # Gesamtwert fuer den Suchindex
    assert read_metadata(pdf).schlagwoerter == "Steuer/Werbungskosten"
    # ganz ohne keywords (Korrespondenten-Verwaltung): pdf:Keywords bleibt unangetastet
    assert write_metadata(pdf, PDFMetadata(korrespondent="Stadtwerke"))
    assert read_metadata(pdf).keywords == "rechnung, energie, Steuer/Werbungskosten"


def test_schlagwoerter_aendern_und_entfernen(tmp_path):
    pdf = h.pdf_mit_text(tmp_path / "a.pdf", ["Rechnung"])
    assert write_metadata(pdf, PDFMetadata(keywords="rechnung", schlagwoerter="Steuer/Werbungskosten, Haus"))
    assert write_metadata(pdf, PDFMetadata(schlagwoerter="Haus"))
    assert read_metadata(pdf).keywords == "rechnung, Haus"
    assert write_metadata(pdf, PDFMetadata(schlagwoerter=""))
    gelesen = read_metadata(pdf)
    assert gelesen.keywords == "rechnung" and gelesen.schlagwoerter is None

    # ohne automatische Stichwoerter verschwindet pdf:Keywords ganz
    nur = h.pdf_mit_text(tmp_path / "b.pdf", ["Notiz"])
    assert write_metadata(nur, PDFMetadata(schlagwoerter="Haus"))
    assert read_metadata(nur).schlagwoerter == "Haus"
    meta = PDFMetadata(schlagwoerter="")
    assert write_metadata(nur, meta)
    assert meta.keywords is None
    assert read_metadata(nur).keywords is None and _info_keywords(nur) == ""


# --------------------------------------------------------------------------- Suchindex

@pytest.fixture
def index(tmp_path):
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    daten = {
        "stuhl.pdf": PDFMetadata(keywords="rechnung", schlagwoerter="Steuer/Werbungskosten", steuerjahr="2026"),
        "spende.pdf": PDFMetadata(keywords="steuer", schlagwoerter="Steuer/Sonderausgaben, Haus", steuerjahr="2026"),
        "fahrt.pdf": PDFMetadata(schlagwoerter="Steuer/Werbungskosten/Fahrt", steuerjahr="2025"),
        "berater.pdf": PDFMetadata(keywords="steuer", schlagwoerter="Steuerberater"),
    }
    for name, meta in daten.items():
        assert write_metadata(h.pdf_mit_text(ablage / name, [f"Dokument {name}"]), meta)
    h.pdf_mit_text(ablage / "ohne.pdf", ["Dokument ohne Schlagwort"])
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    assert Indexer(konfig, synchron=True).lauf() == 0
    return Suchindex(konfig)


def _namen(ergebnis: dict) -> list[str]:
    return sorted(t["name"] for t in ergebnis["treffer"])


def test_filter_schlagwort_schliesst_unterebenen_ein(index):
    assert _namen(index.suche("", schlagwort="Steuer")) == ["fahrt.pdf", "spende.pdf", "stuhl.pdf"]
    assert _namen(index.suche("", schlagwort="Steuer/Werbungskosten")) == ["fahrt.pdf", "stuhl.pdf"]
    assert _namen(index.suche("", schlagwort="Haus")) == ["spende.pdf"]
    assert _namen(index.suche("", schlagwort="Gibt es nicht")) == []
    # "alle Werbungskosten 2026": zusammen mit dem Steuerjahr und mit einem Suchbegriff
    assert _namen(index.suche("", schlagwort="Steuer/Werbungskosten", steuerjahr="2026")) == ["stuhl.pdf"]
    assert _namen(index.suche("Dokument", schlagwort="Steuer", steuerjahr="2025")) == ["fahrt.pdf"]


def test_benutzte_schlagwoerter_aus_dem_index(index):
    assert index.schlagwoerter() == [
        "Haus", "Steuer", "Steuer/Sonderausgaben", "Steuer/Werbungskosten", "Steuer/Werbungskosten/Fahrt",
        "Steuerberater"]
    assert index.schlagwoerter(haeufigste=2) == ["Steuer", "Steuer/Werbungskosten"]


def test_index_ohne_datenbank_liefert_keine_schlagwoerter(tmp_path):
    assert Suchindex(h.konfig_fuer(tmp_path)).schlagwoerter() == []


# --------------------------------------------------------------------------- KI

@pytest.fixture
def provider():
    from tests.test_llm_metadata_extraction import _StubProvider
    from src.ml.llm_provider import LLMConfig

    return _StubProvider(LLMConfig(api_key="dummy", model="dummy"))


def test_prompt_nennt_schlagwoerter_nur_wenn_es_welche_gibt(provider):
    ohne = provider._build_filename_prompt(text="Rechnung Buerostuhl", current_filename="scan.pdf")
    assert "schlagwoerter" not in ohne and "SCHLAGWÖRTER" not in ohne

    sw.quelle_setzen(lambda haeufigste=None: ["Steuer", "Steuer/Werbungskosten", "Haus"][:haeufigste])
    mit = provider._build_filename_prompt(text="Rechnung Buerostuhl", current_filename="scan.pdf")
    assert "SCHLAGWÖRTER DES NUTZERS" in mit
    assert "Steuer; Steuer/Werbungskosten; Haus" in mit
    assert '"schlagwoerter": [' in mit and "Erfinde keine neuen" in mit


def test_antwort_der_ki_wird_auf_benutzte_schlagwoerter_beschraenkt(provider):
    sw.quelle_setzen(lambda haeufigste=None: ["Steuer", "Steuer/Werbungskosten", "Haus"])
    data, fehler = provider._parse_json_response(
        '{"filename": "a.pdf", "metadata": {"category": "Rechnung", '
        '"schlagwoerter": ["steuer/werbungskosten", "Neu erfunden"]}}')
    assert fehler is None
    assert data["metadata"]["schlagwoerter"] == "Steuer/Werbungskosten"

    data, _ = provider._parse_json_response('{"metadata": {"tags": ["Neu erfunden"], "category": "Rechnung"}}')
    assert "schlagwoerter" not in data["metadata"] and "tags" not in data["metadata"]

    # ohne benutzte Schlagwoerter kommt nie eines durch
    sw.quelle_setzen(None)
    data, _ = provider._parse_json_response('{"metadata": {"schlagwoerter": ["Haus"]}}')
    assert "schlagwoerter" not in data["metadata"]

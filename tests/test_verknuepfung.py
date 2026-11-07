"""Ordnervorschlag aus verknuepften Dokumenten (Issue #166/#167, Phase 3)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core.similar_documents import merge_folder_suggestion
from src.ml.classifier import Suggestion
from src.rag.citation import Citation
from src.rag.retrieval import RetrievedDoc
from src.rag.verknuepfung import belegter_ordner, ordner_vorschlag_aus_chat, ordner_vorschlag_aus_kennungen
from src.utils.database import Database
from tests import helfer_suche as h

SCAN_TEXT = ("Preisanpassung fuer Ihren Gasliefervertrag mit der Vertragsnummer G22504020299 "
             "und den Gaszaehler mit der Gaszaehlernummer 226541.")


@pytest.fixture
def sammlung(tmp_path):
    """Zielordner ``Ablage`` mit Energie/2024 (zwei verknuepfte Dokumente), Telekom; Scan im Eingang."""
    db = Database(tmp_path / "t.db")
    ablage = tmp_path / "Ablage"
    energie = ablage / "Energie 2024"
    energie25 = ablage / "Energie 2025"
    telekom = ablage / "Telekom"
    downloads = tmp_path / "Downloads"
    for d in (energie, energie25, telekom, downloads):
        d.mkdir(parents=True)
    dateien = [
        (energie / "Abrechnung.pdf", ["Vertragsnummer G22504020299 Abnahmestelle Kellermannstr. 3"]),
        (energie / "Stammdaten.pdf", ["Zaehlernummer 226541 Netzbetreiber Stadtnetze"]),
        (telekom / "Telekom.pdf", ["Telekom Rechnung Internet 49,95 EUR Kundennummer 99887"]),
        (downloads / "Onlineabschluss.pdf", ["Zaehlernummer 226541 Onlineabschluss"]),  # ausserhalb der Zielordner
    ]
    for pfad, texte in dateien:
        h.pdf_mit_text(pfad, texte)
        db.index_document(str(pfad), pfad.name)
    scan = tmp_path / "Scan"
    scan.mkdir()
    return db, ablage, scan


def test_vorschlag_aus_verknuepften_dokumenten(sammlung):
    db, ablage, scan = sammlung
    s = ordner_vorschlag_aus_kennungen(SCAN_TEXT, db, [ablage], ausser=scan / "Neu.pdf")
    assert isinstance(s, Suggestion)
    assert Path(s.folder_path) == ablage / "Energie 2024"
    assert s.relative_path == "Ablage/Energie 2024"
    assert s.confidence == 0.9  # zwei verknuepfte Dokumente
    assert s.reason == "Verknüpft: gleiche Vertragsnummer, Zählernummer in 2 Dokumenten dieses Ordners"


def test_jahresordner_wird_auf_das_dokumentjahr_angepasst(sammlung):
    db, ablage, scan = sammlung
    s = ordner_vorschlag_aus_kennungen(SCAN_TEXT, db, [ablage], year=2025)
    assert Path(s.folder_path) == ablage / "Energie 2025"
    assert s.relative_path == "Ablage/Energie 2025" and s.reason.endswith("(Jahr angepasst)")
    # Gibt es den Jahresordner nicht, bleibt der Ordner der verknuepften Dokumente
    s = ordner_vorschlag_aus_kennungen(SCAN_TEXT, db, [ablage], year=2031)
    assert Path(s.folder_path) == ablage / "Energie 2024"


def test_kein_vorschlag_ohne_kennungen_oder_ausserhalb_der_zielordner(sammlung):
    db, ablage, scan = sammlung
    assert ordner_vorschlag_aus_kennungen("Nur Text ohne Nummern", db, [ablage]) is None
    assert ordner_vorschlag_aus_kennungen("", db, [ablage]) is None
    assert ordner_vorschlag_aus_kennungen(SCAN_TEXT, None, [ablage]) is None
    assert ordner_vorschlag_aus_kennungen(SCAN_TEXT, db, []) is None
    # Nur ein Treffer, und der liegt in Downloads (kein Zielordner)
    assert ordner_vorschlag_aus_kennungen("Zaehlernummer 999999", db, [ablage]) is None


def test_der_scan_selbst_zaehlt_nicht(sammlung):
    db, ablage, scan = sammlung
    kopie = h.pdf_mit_text(ablage / "Energie 2024" / "Kopie.pdf", [SCAN_TEXT])
    db.index_document(str(kopie), kopie.name)
    s = ordner_vorschlag_aus_kennungen(SCAN_TEXT, db, [ablage], ausser=kopie)
    assert "in 2 Dokumenten" in s.reason  # Abrechnung + Stammdaten, nicht die Kopie selbst
    s = ordner_vorschlag_aus_kennungen(SCAN_TEXT, db, [ablage])
    assert "in 3 Dokumenten" in s.reason and s.confidence == 0.95


def test_nur_unbenannte_zahlen_geben_weniger_vertrauen(sammlung):
    db, ablage, scan = sammlung
    extra = h.pdf_mit_text(ablage / "Telekom" / "Beleg.pdf", ["Buchung 3000083421 Telekom"])
    db.index_document(str(extra), extra.name)
    s = ordner_vorschlag_aus_kennungen("Transaktion 3000083421", db, [ablage])
    assert Path(s.folder_path) == ablage / "Telekom" and s.confidence == 0.7
    assert s.reason.startswith("Verknüpft: gleiche Kennung in 1 Dokument dieses Ordners")


def test_merge_mit_eigener_bestaetigung():
    a = Suggestion(folder_path=Path("/z/A"), folder_name="A", confidence=0.31, reason="Ähnlicher Name")
    b = Suggestion(folder_path=Path("/z/B"), folder_name="B", confidence=0.6, reason="Historie")
    v = Suggestion(folder_path=Path("/z/A"), folder_name="A", confidence=0.95, reason="Verknüpft: …")
    merged = merge_folder_suggestion([b, a], v, bestaetigung="verknüpfte Dokumente")
    assert merged[0] is a and a.confidence == 0.95 and a.reason == "Ähnlicher Name + verknüpfte Dokumente"
    merged = merge_folder_suggestion(merged, v, bestaetigung="verknüpfte Dokumente")
    assert a.reason.count("verknüpfte") == 1  # nicht doppelt
    # Bisheriges Verhalten des KI-Vorschlags unveraendert
    ki = Suggestion(folder_path=Path("/z/B"), folder_name="B", confidence=0.85, reason="KI: ähnliche Dokumente")
    merged = merge_folder_suggestion([a, b], ki)
    assert merged[0] is b and b.confidence == 0.9 and b.reason == "Historie + KI bestätigt"


def test_belegter_ordner_aus_zitaten(sammlung):
    db, ablage, scan = sammlung
    docs = [
        RetrievedDoc(index=1, file_path=str(scan / "Neu.pdf"), filename="Neu.pdf", text_snippet="", rank=0),
        RetrievedDoc(index=2, file_path=str(ablage / "Energie 2024" / "Abrechnung.pdf"), filename="Abrechnung.pdf",
                     text_snippet="", rank=0),
        RetrievedDoc(index=3, file_path=str(ablage / "Energie 2024" / "Stammdaten.pdf"), filename="Stammdaten.pdf",
                     text_snippet="", rank=0),
        RetrievedDoc(index=4, file_path=str(ablage / "Telekom" / "Telekom.pdf"), filename="Telekom.pdf",
                     text_snippet="", rank=0),
        RetrievedDoc(index=5, file_path=str(tmp := scan.parent / "Downloads" / "x.pdf"), filename="x.pdf",
                     text_snippet="", rank=0),
    ]
    zitate = [Citation(index=i, file_path=docs[i - 1].file_path, valid=True) for i in (1, 2, 3, 4, 5)]
    pfad, anzeige, grund = belegter_ordner(zitate, docs, [ablage], ausser=scan / "Neu.pdf")
    assert Path(pfad) == ablage / "Energie 2024" and anzeige == "Ablage/Energie 2024"
    assert grund == "belegt durch [2], [3]"
    assert belegter_ordner([], docs, [ablage]) == ("", "", "")
    assert belegter_ordner(zitate[:1], docs, [ablage], ausser=scan / "Neu.pdf") == ("", "", "")

    s = ordner_vorschlag_aus_chat(pfad, grund, [ablage])
    assert s.confidence == 0.9 and s.reason == "Chat: belegt durch [2], [3]" and s.relative_path == anzeige
    assert ordner_vorschlag_aus_chat(str(scan), grund, [ablage]) is None  # kein Zielordner
    assert ordner_vorschlag_aus_chat("", grund, [ablage]) is None

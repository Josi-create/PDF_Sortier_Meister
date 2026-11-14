"""Einheit bzw. Verbrauchsstelle erkennen und den Ordner dazu lernen (Issue #257).

Alle Anschriften, Zaehlernummern und Ordner sind erfunden.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.core import einheiten
from src.core.filename_placeholders import (
    PLACEHOLDER_BY_KEY, placeholder_values_from_metadata, render_with_values,
)
from src.core.pdf_metadata import PDFMetadata, read_metadata, write_metadata
from src.ml.llm_provider import normalize_llm_metadata
from src.utils.database import Database
from tests import helfer_suche as h


@pytest.fixture
def db(tmp_path):
    return Database(db_path=str(tmp_path / "einheiten.db"))


@pytest.fixture
def ablage(tmp_path) -> Path:
    wurzel = tmp_path / "Ablage"
    for rel in ("Haus/Whg 1/Strom", "Haus/Whg 2/Strom", "Haus/Whg 2/Nebenkosten 2025",
                "Haus/Whg 2/Nebenkosten 2026"):
        (wurzel / rel).mkdir(parents=True)
    return wurzel


# --------------------------------------------------------------------------- Vergleichsformen

def test_schluessel_gleichen_schreibweisen_an():
    assert einheiten.kennung_schluessel("70 4711-22") == "70471122"
    assert einheiten.kennung_schluessel(" DE-00/4711 ") == "de004711"
    assert einheiten.kennung_schluessel("12") == ""            # zu kurz
    assert einheiten.kennung_schluessel("Strom") == ""         # keine Ziffer
    assert einheiten.kennung_schluessel(None) == ""

    a = einheiten.einheit_schluessel("Musterstraße 5, Whg. 2")
    assert a == einheiten.einheit_schluessel("musterstrasse 5 whg 2") == einheiten.einheit_schluessel("Musterstr. 5 Whg 2")
    assert a != einheiten.einheit_schluessel("Musterstraße 5, Whg. 1")
    assert einheiten.einheit_schluessel("UNBEKANNT") == "" and einheiten.saeubern(" unbekannt ") == ""
    assert einheiten.saeubern("Musterweg 5\n Whg 2 ") == "Musterweg 5 Whg 2"


# --------------------------------------------------------------------------- Datenbank

def test_datenbank_lernt_einheit_je_ordner_und_zaehlt(db, ablage):
    whg2 = ablage / "Haus" / "Whg 2" / "Strom"
    assert db.get_einheit_zuordnungen() == []
    assert db.learn_einheit("Musterweg 5 Whg 2", "70 4711 22", whg2)
    assert db.learn_einheit("musterweg 5, whg. 2", "70471122", whg2)      # dieselbe Zeile
    assert db.learn_einheit("Musterweg 5 Whg 1", "", ablage / "Haus" / "Whg 1" / "Strom")

    zeilen = db.get_einheit_zuordnungen()
    assert len(zeilen) == 2
    nach_ordner = {Path(z["target_folder"]).parent.name: z for z in zeilen}
    assert nach_ordner["Whg 2"]["usage_count"] == 2 and nach_ordner["Whg 2"]["kennung"] == "70 4711 22"
    assert nach_ordner["Whg 1"]["kennung"] == ""

    # nichts zu lernen: weder Einheit noch brauchbare Kennung, oder kein Ordner
    assert not db.learn_einheit("", "", whg2)
    assert not db.learn_einheit("UNBEKANNT", "12", whg2)
    assert not db.learn_einheit("Musterweg 5", "4711", "")
    assert len(db.get_einheit_zuordnungen()) == 2


def test_ordner_umzug_nimmt_gelernte_einheiten_mit(db, ablage):
    db.learn_einheit("Musterweg 5 Whg 2", "70471122", ablage / "Haus" / "Whg 2" / "Strom")
    neu = ablage / "Mietshaus"
    db.pfade_umziehen(str(ablage / "Haus"), str(neu), [ablage])
    assert db.get_einheit_zuordnungen()[0]["target_folder"] == str(neu / "Whg 2" / "Strom")


# --------------------------------------------------------------------------- Vorschlag

def _z(einheit, kennung, ordner):
    return {"einheit": einheit, "kennung": kennung, "target_folder": str(ordner)}


def test_vorschlag_ueber_kennung_schlaegt_die_bezeichnung(ablage):
    whg1, whg2 = ablage / "Haus" / "Whg 1" / "Strom", ablage / "Haus" / "Whg 2" / "Strom"
    gelernt = [_z("Musterweg 5 Whg 1", "70471111", whg1), _z("Musterweg 5 Whg 2", "70471122", whg2)]

    # die KI nennt die falsche Wohnung, aber die richtige Zaehlernummer
    v = einheiten.ordner_vorschlag(
        {"einheit": "Musterweg 5 Whg 1", "einheit_kennung": "70 4711 22"}, "", gelernt, [ablage])
    assert v.folder_path == whg2 and v.relative_path == "Ablage/Haus/Whg 2/Strom"
    assert v.confidence == einheiten.VERTRAUEN_KENNUNG and "Musterweg 5 Whg 2" in v.reason

    # nur die Bezeichnung
    v = einheiten.ordner_vorschlag({"einheit": "musterweg 5, whg. 1"}, "", gelernt, [ablage])
    assert v.folder_path == whg1 and v.confidence == einheiten.VERTRAUEN_EINHEIT


def test_vorschlag_aus_zaehlernummer_im_text_ohne_ki(ablage):
    whg2 = ablage / "Haus" / "Whg 2" / "Strom"
    gelernt = [_z("Musterweg 5 Whg 2", "70471122", whg2)]
    text = "Stadtwerke Musterstadt\nRechnungsanschrift: Max Mustermann, Beispielallee 9\nZählernummer: 70471122\n"
    assert einheiten.ordner_vorschlag(None, text, gelernt, [ablage]).folder_path == whg2
    assert einheiten.ordner_vorschlag(None, "Zählernummer: 70479999", gelernt, [ablage]) is None
    assert einheiten.ordner_vorschlag({}, "", gelernt, [ablage]) is None
    assert einheiten.ordner_vorschlag({"einheit": "Musterweg 5 Whg 2"}, "", [], [ablage]) is None


def test_vorschlag_passt_jahresordner_an_und_ueberspringt_fehlende_ordner(ablage, tmp_path):
    nk25 = ablage / "Haus" / "Whg 2" / "Nebenkosten 2025"
    gelernt = [
        _z("Musterweg 5 Whg 2", "", ablage / "Haus" / "Whg 2" / "Geloescht"),   # neueste, gibt es nicht mehr
        _z("Musterweg 5 Whg 2", "", nk25),
    ]
    meta = {"einheit": "Musterweg 5 Whg 2"}
    v = einheiten.ordner_vorschlag(meta, "", gelernt, [ablage], year=2026)
    assert v.folder_path == ablage / "Haus" / "Whg 2" / "Nebenkosten 2026"
    assert einheiten.ordner_vorschlag(meta, "", gelernt, [ablage], year=2030).folder_path == nk25  # kein 2030-Ordner
    # Ordner ausserhalb der Zielordner zaehlen nicht
    fremd = tmp_path / "Woanders"
    fremd.mkdir()
    assert einheiten.ordner_vorschlag(meta, "", [_z("Musterweg 5 Whg 2", "", fremd)], [ablage]) is None


# --------------------------------------------------------------------------- KI

@pytest.fixture
def provider():
    from tests.test_llm_metadata_extraction import _StubProvider
    from src.ml.llm_provider import LLMConfig

    return _StubProvider(LLMConfig(api_key="dummy", model="dummy"))


def test_prompt_fragt_nach_einheit_und_nennt_bekannte_einheiten(provider, ablage):
    ohne = provider._build_filename_prompt(text="Stromrechnung", current_filename="scan.pdf")
    assert '"einheit":' in ohne and '"einheit_kennung":' in ohne and "Verbrauchsstelle" in ohne
    assert "BEKANNTE EINHEITEN" not in ohne

    einheiten.quelle_setzen(lambda: [
        {"einheit": "Musterweg 5 Whg 2", "kennung": "70471122", "ablageort": "Ablage/Haus/Whg 2/Strom"},
        {"einheit": "musterweg 5, whg. 2", "kennung": "70 4711 22", "ablageort": "Ablage/Haus/Whg 2/Alt"},  # doppelt
        {"einheit": "", "kennung": "999999", "ablageort": "Ablage/Haus"},                                  # ohne Namen
    ])
    mit = provider._build_filename_prompt(text="Stromrechnung", current_filename="scan.pdf")
    kopf = mit.split("REGELN FÜR DEN DATEINAMEN")[0]
    assert "BEKANNTE EINHEITEN DES NUTZERS" in kopf
    assert '- "Musterweg 5 Whg 2" (Zähler/Vertragskonto 70471122), zuletzt abgelegt in "Ablage/Haus/Whg 2/Strom"' in kopf
    assert "Whg 2/Alt" not in kopf and "999999" not in kopf


def test_prompt_abschnitt_ohne_quelle_und_bei_fehler_leer():
    assert einheiten.fuer_prompt() == ""

    def kaputt():
        raise RuntimeError("Datenbank weg")
    einheiten.quelle_setzen(kaputt)
    assert einheiten.gelernte() == [] and einheiten.fuer_prompt() == ""


def test_antwort_der_ki_einheit_und_kennung_werden_normalisiert(provider):
    md = normalize_llm_metadata({"Verbrauchsstelle": " Musterweg 5\nWhg 2 ", "zaehlernummer": 70471122})
    assert md == {"einheit": "Musterweg 5 Whg 2", "einheit_kennung": "70471122"}
    assert normalize_llm_metadata({"einheit": "UNBEKANNT", "einheit_kennung": "unbekannt"}) == {}
    # der kanonische Schluessel hat Vorrang vor dem Alias
    assert normalize_llm_metadata({"lieferanschrift": "B", "einheit": "A"})["einheit"] == "A"

    data, fehler = provider._parse_json_response(
        '{"filename": "a.pdf", "metadata": {"category": "Energie", "einheit": "Musterweg 5 Whg 2", '
        '"einheit_kennung": "70 4711 22"}}')
    assert fehler is None
    assert data["metadata"]["einheit"] == "Musterweg 5 Whg 2" and data["metadata"]["einheit_kennung"] == "70 4711 22"


# --------------------------------------------------------------------------- PDF und Dateiname

def test_einheit_steht_in_der_pdf(tmp_path):
    pdf = h.pdf_mit_text(tmp_path / "Abschlag Überlandwerk.pdf", ["Stromrechnung"])
    assert write_metadata(pdf, PDFMetadata(einheit="Musterweg 5 Whg 2"))
    gelesen = read_metadata(pdf)
    assert gelesen.einheit == "Musterweg 5 Whg 2" and gelesen.to_dict()["einheit"] == "Musterweg 5 Whg 2"
    assert PDFMetadata(einheit="x").has_any_data()


def test_platzhalter_einheit_im_dateinamen_muster():
    assert "einheit" in PLACEHOLDER_BY_KEY
    werte = placeholder_values_from_metadata(
        {"korrespondent": "Stadtwerke Musterstadt", "einheit": "Musterweg 5 Whg 2"}, doc_date="2026-03-12")
    assert werte["einheit"] == "Musterweg 5 Whg 2"
    assert render_with_values("{datum}_{kontakt}_{einheit}", werte) == "2026-03-12_Stadtwerke-Musterstadt_Musterweg-5-Whg-2.pdf"
    ohne = placeholder_values_from_metadata({"korrespondent": "Stadtwerke Musterstadt"}, doc_date="2026-03-12")
    assert render_with_values("{datum}_{kontakt}_{einheit}", ohne) == "2026-03-12_Stadtwerke-Musterstadt.pdf"

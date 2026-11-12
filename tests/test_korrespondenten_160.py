"""Issue #160: Korrespondent = Gegenpartei; Normalisierung, Gruppen, Auffaelliges, KI-Abgleich, Alias in der DB.

Qt-frei (kein Import aus ``src.gui``).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core import korrespondenten as kr
from src.ml.llm_provider import LLMConfig, LLMProvider

OWNER = ["Dr. med. Jonas Huber-Weber", "J. Huber", "Praxis Huber-Weber"]


# --------------------------------------------------------------------------- Prompt


class _StubProvider(LLMProvider):
    def _initialize_client(self): pass
    def classify_document(self, *a, **kw): pass
    def suggest_filename(self, *a, **kw): pass
    def is_available(self): return True
    def answer_with_context(self, *a, **kw): return ""


class _Cfg:
    def __init__(self, **werte):
        self._w = werte

    def get(self, key, default=None):
        return self._w.get(key, default)


@pytest.fixture
def provider():
    return _StubProvider(LLMConfig(api_key="x", model="m"))


def _prompts(provider):
    return (
        provider._build_filename_prompt(text="Mietvertrag", current_filename="scan.pdf"),
        provider._build_classification_prompt(text="Mietvertrag", available_folders=["Miete"]),
    )


def test_prompts_definieren_korrespondent_als_gegenpartei_mit_owner(provider, monkeypatch):
    import src.utils.config as cfg
    monkeypatch.setattr(cfg, "get_config", lambda: _Cfg(
        owner_name="Dr. Jonas Huber-Weber", owner_name_variants="J. Huber, Jonas Weber"))
    for prompt in _prompts(provider):
        assert "Firmenname des Absenders" not in prompt
        assert "GEGENPARTEI des Dokuments aus Sicht des Nutzers" in prompt
        assert "eine Person oder\neine Firma, Behörde, Praxis bzw. Institution" in prompt
        assert "Mietvertrag -> der Mieter" in prompt
        assert "Arztbrief, den der Nutzer als Arzt schreibt -> der\n  Patient" in prompt
        assert "Arztbrief an den Nutzer als Patienten -> der Arzt bzw. die Praxis" in prompt
        assert "Niemals ein Formularverlag, eine Druckerei" in prompt
        assert "genau einer je Dokument" in prompt
        assert ('Der Nutzer heißt "Dr. Jonas Huber-Weber" (auch "J. Huber", "Jonas Weber") '
                '- er ist nie der Korrespondent.') in prompt
        assert '"korrespondent": "Gegenpartei aus Sicht des Nutzers' in prompt
        assert "JSON" in prompt


def test_prompt_ohne_owner_name_sinngemaess(provider, monkeypatch):
    import src.utils.config as cfg
    monkeypatch.setattr(cfg, "get_config", lambda: _Cfg())
    for prompt in _prompts(provider):
        assert "Der Nutzer heißt" not in prompt
        assert "Der Nutzer ist der Besitzer dieser Dokumente" in prompt
        assert "er ist nie der Korrespondent" in prompt


# --------------------------------------------------------------------------- Normalisierung und Gruppen


@pytest.mark.parametrize("a, b", [
    ("Stadtwerke Göttingen AG", "stadtwerke goettingen"),
    ("Stadtwerke  Göttingen.", "STADTWERKE GÖTTINGEN"),
    ("Haus & Grund e.V.", "Haus und Grund"),
    ("Haus & Grund e. V.", "haus-und-grund"),
    ("Müller GmbH & Co. KG", "Mueller"),
    ("Telekom Deutschland GmbH", "Telekom Deutschland"),
    ("Karin_Huber", "Karin Huber"),
])
def test_schluessel_gleichwertige_schreibweisen(a, b):
    assert kr.schluessel(a) == kr.schluessel(b)


def test_schluessel_unterscheidet_echte_unterschiede():
    assert kr.schluessel("Stadtwerke Göttingen") != kr.schluessel("Stadtwerke GÖ")
    assert kr.schluessel("AG Göttingen") == "ag goettingen"  # Amtsgericht: Rechtsform nur hinten


def test_gruppieren_fasst_zusammen_und_waehlt_kanonische_schreibweise():
    zaehlung = [("Stadtwerke Göttingen AG", 2), ("Stadtwerke Goettingen", 3), ("Telekom", 4),
                ("Stadtwerke GÖ", 1), ("", 7)]
    gruppen = kr.gruppieren(zaehlung)
    namen = [(g.name, g.anzahl) for g in gruppen]
    # haeufigste Schreibweise ist kanonisch; leere Werte fallen weg; Anzahl absteigend, dann Name
    assert namen == [("Stadtwerke Goettingen", 5), ("Telekom", 4), ("Stadtwerke GÖ", 1)]
    assert set(gruppen[0].schreibweisen) == {"Stadtwerke Göttingen AG", "Stadtwerke Goettingen"}


def test_gruppieren_nutzer_schreibweise_und_alias_gewinnen():
    eintraege = [{"name": "Stadtwerke Göttingen", "aliases": ["Stadtwerke GÖ"], "usage_count": 0}]
    gruppen = kr.gruppieren([("Stadtwerke Goettingen AG", 3), ("Stadtwerke GÖ", 1)], eintraege)
    assert [(g.name, g.anzahl) for g in gruppen] == [("Stadtwerke Göttingen", 4)]
    assert kr.passt_zu(gruppen[0], "stadtwerke gö")
    assert kr.kanonisch("Stadtwerke GÖ", eintraege) == "Stadtwerke Göttingen"
    assert kr.kanonisch("Unbekannt AG", eintraege) == "Unbekannt AG"


def test_filter_passt_umlaute_egal():
    g = kr.Gruppe(name="Stadtwerke Göttingen", anzahl=1, schreibweisen=["Stadtwerke Göttingen"])
    assert kr.filter_passt(g, "goett")
    assert kr.filter_passt(g, "GÖTT")
    assert not kr.filter_passt(g, "Kassel")


# --------------------------------------------------------------------------- Auffaellig


@pytest.mark.parametrize("name, grund", [
    ("", kr.GRUND_LEER),
    (None, kr.GRUND_LEER),
    ("  ", kr.GRUND_LEER),
    ("Jonas Huber-Weber", kr.GRUND_NUTZER),
    ("Dr. Huber-Weber", kr.GRUND_NUTZER),
    ("Praxis Huber-Weber", kr.GRUND_NUTZER),
    ("Haus & Grund", kr.GRUND_VERLAG),
    ("Haus und Grund Göttingen e.V.", kr.GRUND_VERLAG),
    ("Avery Zweckform GmbH", kr.GRUND_VERLAG),
    ("RNK-Verlag", kr.GRUND_VERLAG),
    ("Stadtwerke Göttingen", None),
    ("Karin Huber-Weber", None),   # Familienmitglied, nicht der Nutzer
    ("Max Mieter", None),
])
def test_auffaelligkeit(name, grund):
    assert kr.auffaelligkeit(name, OWNER) == grund


def test_auffaellige_dokumente_nur_unter_zielordnern(tmp_path):
    ablage, fremd = tmp_path / "Ablage", tmp_path / "Woanders"
    doks = [
        {"id": 1, "datei": str(ablage / "Miete" / "a.pdf"), "korrespondent": "Haus & Grund"},
        {"id": 2, "datei": str(ablage / "b.pdf"), "korrespondent": ""},
        {"id": 3, "datei": str(ablage / "c.pdf"), "korrespondent": "J. Huber"},
        {"id": 4, "datei": str(ablage / "d.pdf"), "korrespondent": "Stadtwerke"},
        {"id": 5, "datei": str(fremd / "e.pdf"), "korrespondent": ""},
        {"id": 6, "datei": str(tmp_path / "Ablage2" / "f.pdf"), "korrespondent": ""},  # nur Namensanfang gleich
    ]
    treffer = kr.auffaellige_dokumente(doks, [ablage], OWNER)
    assert [(d["id"], d["grund"]) for d in treffer] == [
        (1, kr.GRUND_VERLAG), (2, kr.GRUND_LEER), (3, kr.GRUND_NUTZER)]


def test_erkennbare_eintraege_ohne_nutzer_und_verlag():
    eintraege = [{"name": "Haus & Grund"}, {"name": "Jonas Huber-Weber"}, {"name": "Stadtwerke"}]
    assert [e["name"] for e in kr.erkennbare_eintraege(eintraege, OWNER)] == ["Stadtwerke"]


# --------------------------------------------------------------------------- KI-Abgleich


def test_kandidaten_paare_unsichere_faelle():
    gruppen = kr.gruppieren([("Stadtwerke Göttingen", 3), ("Stadtwerke GÖ", 1), ("Telekom", 2),
                             ("Telekom Deutschland", 1), ("Finanzamt Kassel", 1), ("Bank", 5)])
    paare = kr.kandidaten_paare(gruppen)
    assert ("Stadtwerke Göttingen", "Stadtwerke GÖ") in paare
    assert ("Telekom", "Telekom Deutschland") in paare
    assert all("Bank" not in p and "Finanzamt Kassel" not in p for p in paare)
    # schon gepruefte Paare fallen weg
    geprueft = {kr.paar_schluessel("Stadtwerke GÖ", "Stadtwerke Göttingen")}
    assert ("Stadtwerke Göttingen", "Stadtwerke GÖ") not in kr.kandidaten_paare(gruppen, geprueft)


def test_ki_frage_und_tolerante_antwort():
    paare = [("Stadtwerke Göttingen", "Stadtwerke GÖ"), ("Stadtwerke Göttingen", "Stadtwerke Kassel")]
    frage = kr.ki_frage(paare)
    assert '1. "Stadtwerke Göttingen" | "Stadtwerke GÖ"' in frage
    assert "Antworte NUR mit diesem JSON" in frage
    antwort = 'Hier: ```json\n{"paare": [{"nr": 1, "gleich": true}, {"nr": 2, "gleich": "nein"}, {"nr": 9}]}\n```'
    assert kr.ki_antwort_lesen(antwort, paare) == [
        ("Stadtwerke Göttingen", "Stadtwerke GÖ", True), ("Stadtwerke Göttingen", "Stadtwerke Kassel", False)]
    assert kr.ki_antwort_lesen("keine Ahnung", paare) == []


def test_geprueft_speichern_und_laden(tmp_path):
    datei = tmp_path / "abgleich.json"
    assert kr.geprueft_laden(datei) == set()
    kr.geprueft_speichern(datei, {"a|b", "c|d"})
    assert kr.geprueft_laden(datei) == {"a|b", "c|d"}


def test_relativer_ordner(tmp_path):
    ablage = tmp_path / "Ablage"
    assert kr.relativer_ordner(str(ablage / "Miete" / "2024"), [ablage]) == os.path.join("Ablage", "Miete", "2024")
    assert kr.relativer_ordner(str(ablage), [ablage]) == "Ablage"
    assert kr.relativer_ordner(str(tmp_path / "X"), [ablage]) == str(tmp_path / "X")


# --------------------------------------------------------------------------- Datenbank


@pytest.fixture
def db(tmp_path):
    from src.utils.database import Database
    return Database(db_path=str(tmp_path / "history.db"))


def test_alias_setzen_legt_an_und_fuehrt_eintrag_zusammen_ohne_index(db, tmp_path):
    datei = tmp_path / "Ablage" / "gö.pdf"
    db.suchindex.metadaten_setzen(str(datei), {"korrespondent": "Stadtwerke GÖ"}, lesen=False)
    db.add_or_update_korrespondent("Stadtwerke GÖ", aliases=["SW GÖ"])
    db.learn_korrespondent_metadata("Stadtwerke GÖ", {"subject": "Energie"})

    db.korrespondent_alias_setzen("Stadtwerke Göttingen", "Stadtwerke GÖ")

    eintraege = {e["name"]: e for e in db.list_korrespondenten()}
    assert "Stadtwerke GÖ" not in eintraege
    assert set(eintraege["Stadtwerke Göttingen"]["aliases"]) == {"Stadtwerke GÖ", "SW GÖ"}
    # Suchindex bleibt unveraendert, die Zuordnung gilt beim Lesen
    assert db.suchindex.werte("korrespondent") == ["Stadtwerke GÖ"]
    assert db.kanonischer_korrespondent("stadtwerke gö") == "Stadtwerke Göttingen"
    # Gelerntes bleibt erhalten und gilt fuer den Alias
    assert db.get_korrespondent_metadata("Stadtwerke GÖ") == {"subject": "Energie"}


def test_lernen_unter_kanonischem_namen(db):
    db.korrespondent_alias_setzen("Stadtwerke Göttingen", "Stadtwerke GÖ")
    db.learn_korrespondent_metadata("Stadtwerke GÖ", {"subject": "Energie"})
    db.learn_korrespondent_metadata("Stadtwerke Göttingen AG", {"waehrung": "EUR"})
    assert db.get_all_korrespondenten() == ["Stadtwerke Göttingen"]
    assert db.get_korrespondent_metadata("Stadtwerke Göttingen") == {"subject": "Energie", "waehrung": "EUR"}


def test_wiedererkennen_nutzt_alias(db):
    from src.core.korrespondent_match import find_known_korrespondent
    db.korrespondent_alias_setzen("Stadtwerke Göttingen", "Stadtwerke GÖ")
    assert find_known_korrespondent("Ihre Abrechnung der Stadtwerke GÖ vom 3.4.", db.list_korrespondenten()) \
        == "Stadtwerke Göttingen"


def test_index_werte_mit_anzahl_und_dokumente(db, tmp_path):
    idx = db.suchindex
    ablage = tmp_path / "Ablage"
    idx.metadaten_setzen(str(ablage / "a.pdf"), {"korrespondent": "Telekom", "buchungsdatum": "2024-01-02"},
                         lesen=False)
    idx.metadaten_setzen(str(ablage / "b.pdf"), {"korrespondent": "Telekom", "buchungsdatum": "2025-03-04"},
                         lesen=False)
    idx.metadaten_setzen(str(ablage / "c.pdf"), {"korrespondent": "Telekom GmbH"}, lesen=False)
    idx.metadaten_setzen(str(ablage / "d.pdf"), {"korrespondent": "Bank"}, lesen=False)
    assert idx.werte_mit_anzahl("korrespondent") == [("Telekom", 2), ("Bank", 1), ("Telekom GmbH", 1)]
    namen = [d["name"] for d in idx.dokumente_mit_werten("korrespondent", ["Telekom", "Telekom GmbH"])]
    assert namen[:2] == ["b.pdf", "a.pdf"] and set(namen) == {"a.pdf", "b.pdf", "c.pdf"}
    liste = idx.metadaten_liste(None)
    assert {Path(d["datei"]).name for d in liste} == {"a.pdf", "b.pdf", "c.pdf", "d.pdf"}

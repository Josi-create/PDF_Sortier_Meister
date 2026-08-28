"""LLM-Metadaten-Schluessel werden auf die kanonischen Feldnamen abgebildet.

Hintergrund: Der Prompt verlangt u.a. ``beschreibung``/``category``/``mwst``,
das Detail-Panel und die Datenbank lesen aber ``description``/``subject``/
``mwst_satz``. Ohne Normalisierung blieb z.B. die Zusammenfassung leer, sobald
sich ein Modell an den Prompt hielt (im Nutzer-Cache: 367 Eintraege mit
``beschreibung`` neben 416 mit ``description``).
"""
from __future__ import annotations

import json

import pytest

from src.ml.llm_provider import normalize_llm_metadata


def test_german_prompt_keys_are_mapped_to_canonical():
    raw = {
        "category": "Versicherung",
        "korrespondent": "HEK Hanseatische Krankenkasse",
        "betrag_netto": "UNBEKANNT",
        "betrag_brutto": "UNBEKANNT",
        "waehrung": "EUR",
        "mwst": 7,
        "iban": "UNBEKANNT",
        "steuerjahr": 2025,
        "beschreibung": "Kostenuebernahme fuer eine Verhaltenstherapie.",
    }
    assert normalize_llm_metadata(raw) == {
        "subject": "Versicherung",
        "korrespondent": "HEK Hanseatische Krankenkasse",
        "waehrung": "EUR",
        "mwst_satz": 7,
        "steuerjahr": 2025,
        "description": "Kostenuebernahme fuer eine Verhaltenstherapie.",
    }


def test_canonical_keys_pass_through_unchanged():
    raw = {
        "subject": "Sonstiges",
        "korrespondent": "intan service plus GmbH",
        "betrag": "7.15",
        "waehrung": "EUR",
        "mwst_satz": "7",
        "steuerjahr": "2026",
        "description": "Auftragsbestaetigung.",
    }
    out = normalize_llm_metadata(raw)
    assert out == raw


def test_canonical_value_wins_over_alias():
    out = normalize_llm_metadata({"description": "Kanonisch", "beschreibung": "Alias"})
    assert out["description"] == "Kanonisch"
    out = normalize_llm_metadata({"beschreibung": "Alias", "description": "Kanonisch"})
    assert out["description"] == "Kanonisch"


def test_alias_fills_in_when_canonical_is_empty():
    out = normalize_llm_metadata({"description": "", "beschreibung": "Alias"})
    assert out["description"] == "Alias"


@pytest.mark.parametrize("value", [None, "", "UNBEKANNT", "unbekannt", "null", "n/a", "  "])
def test_placeholder_values_are_dropped(value):
    assert "iban" not in normalize_llm_metadata({"iban": value, "subject": "Rechnung"})


def test_betrag_is_not_reinterpreted():
    out = normalize_llm_metadata({"betrag": "10", "betrag_brutto": "11.9"})
    assert out == {"betrag": "10", "betrag_brutto": "11.9"}
    assert normalize_llm_metadata({"betrag": "10"}) == {"betrag": "10"}


def test_unknown_keys_and_case_are_handled():
    out = normalize_llm_metadata({"Beschreibung": "x", "SUBJECT": "y", "extra": "bleibt"})
    assert out == {"description": "x", "subject": "y", "extra": "bleibt"}


@pytest.mark.parametrize("bad", [None, "text", 42, ["liste"]])
def test_non_dict_returns_empty(bad):
    assert normalize_llm_metadata(bad) == {}


# --------------------------------------------------------------------- #
# Integration: Parser und Cache
# --------------------------------------------------------------------- #


def test_parse_json_response_normalizes_metadata():
    from src.ml.llm_provider import LLMConfig, LLMProvider

    class _P(LLMProvider):
        """Minimaler Stub - nur der Parser der Basisklasse wird getestet."""

        def _initialize_client(self):
            return None

        def is_available(self):
            return True

        def classify_document(self, *a, **k):
            return None

        def suggest_folder(self, *a, **k):
            return None

        def suggest_filename(self, *a, **k):
            return None

        def answer_with_context(self, *a, **k):
            return None

    provider = _P(LLMConfig(api_key="x", model="test-modell"))
    text = json.dumps({
        "filename": "a.pdf", "reason": "r", "confidence": 0.9,
        "metadata": {"category": "Arzt", "beschreibung": "Befund", "mwst": None},
    })
    data, error = provider._parse_json_response(text)
    assert error is None
    assert data["metadata"] == {"subject": "Arzt", "description": "Befund"}


def test_cache_load_normalizes_old_entries(tmp_path, monkeypatch):
    """Bereits gecachte Vorschlaege mit Roh-Schluesseln werden beim Laden umgeschrieben."""
    import sqlite3
    from datetime import datetime

    from src.core import pdf_cache as pc_mod
    from src.utils import config as cfg_mod
    from tests.conftest import patch_singletons

    cfg = cfg_mod.Config(config_path=tmp_path / "config.json")
    cfg.set("persist_pdf_cache", True)
    patch_singletons(monkeypatch, {"get_config": lambda: cfg})
    monkeypatch.setattr(pc_mod.PDFCache, "_instance", None)
    monkeypatch.setattr(pc_mod, "get_app_data_dir", lambda *a, **k: tmp_path, raising=False)

    cache = pc_mod.PDFCache()
    db_path = cache._db_path
    assert db_path is not None and db_path.exists()

    pdf = tmp_path / "alt.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    old_entry = json.dumps([{
        "filename": "alt.pdf", "confidence": 0.8, "source": "llm",
        "metadata": {"category": "Bank", "beschreibung": "Kontoauszug", "mwst": 19},
    }])
    con = sqlite3.connect(str(db_path))
    con.execute(
        "INSERT OR REPLACE INTO pdf_cache (pdf_path, extracted_text, keywords, dates, analyzed_at, "
        "file_modified, llm_suggestions, llm_fetched) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
        (str(pdf), "text", "[]", "[]", datetime.now().isoformat(), pdf.stat().st_mtime, old_entry),
    )
    con.commit()
    con.close()

    monkeypatch.setattr(pc_mod.PDFCache, "_instance", None)
    cache2 = pc_mod.PDFCache()
    result = cache2._cache.get(pdf)
    assert result is not None, "Eintrag wurde nicht aus der DB geladen"
    metadata = result.llm_suggestions[0].metadata
    assert metadata == {"subject": "Bank", "description": "Kontoauszug", "mwst_satz": 19}

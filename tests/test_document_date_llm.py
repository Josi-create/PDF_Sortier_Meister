"""Issue #132: Dokumentdatum in KI-Antwort und Prompt.

- "datum"/"date"/"dokumentdatum" aus der KI-Antwort landen als
  ``buchungsdatum`` (Feld "Datum"), egal in welchem Format.
- Der Prompt nennt den Quellordner als Hinweis, verlangt "datum" im Schema
  und erklaert, dass Fristen und Scandatum nicht das Dokumentdatum sind.
"""
import pytest

from src.ml.llm_provider import (
    LLMConfig,
    LLMProvider,
    normalize_llm_metadata,
    normalize_metadata_date,
)


class _StubProvider(LLMProvider):
    def _initialize_client(self): pass
    def classify_document(self, *a, **kw): pass
    def suggest_filename(self, *a, **kw): pass
    def is_available(self): return True
    def answer_with_context(self, *a, **kw): return ""


@pytest.fixture
def provider():
    return _StubProvider(LLMConfig(api_key="dummy", model="dummy"))


@pytest.mark.parametrize("key", ["datum", "date", "dokumentdatum", "document_date", "buchungsdatum"])
def test_datum_aliasse_werden_zu_buchungsdatum(key):
    assert normalize_llm_metadata({key: "2004-03-12"}) == {"buchungsdatum": "2004-03-12"}


@pytest.mark.parametrize("raw, expected", [
    ("12.03.2004", "2004-03-12"),
    ("2004-03-12", "2004-03-12"),
    ("12. Maerz 2004", "2004-03-12"),
])
def test_normalize_metadata_date_bringt_datum_auf_iso(raw, expected):
    assert normalize_metadata_date({"buchungsdatum": raw, "subject": "Brief"}) == {
        "buchungsdatum": expected, "subject": "Brief",
    }


def test_normalize_metadata_date_verwirft_unlesbares():
    assert normalize_metadata_date({"buchungsdatum": "Fruehjahr 2004"}) == {}
    assert normalize_metadata_date({"subject": "Brief"}) == {"subject": "Brief"}
    assert normalize_metadata_date("kein dict") == "kein dict"


def test_parse_json_response_liefert_iso_datum(provider):
    text = '{"filename":"x.pdf","metadata":{"datum":"12.03.2004","steuerjahr":"2004"}}'
    data, err = provider._parse_json_response(text)
    assert err is None
    assert data["metadata"] == {"buchungsdatum": "2004-03-12", "steuerjahr": "2004"}


def test_parse_json_response_verwirft_unbekanntes_datum(provider):
    text = '{"filename":"x.pdf","metadata":{"datum":"UNBEKANNT","steuerjahr":"UNBEKANNT"}}'
    data, _err = provider._parse_json_response(text)
    assert data["metadata"] == {}


def test_prompt_enthaelt_quellordner_und_datum_im_schema(provider):
    prompt = provider._build_filename_prompt(
        text="Sehr geehrte Damen und Herren", current_filename="scan.pdf",
        detected_date="2006-06-30", file_date="2006-07-01", source_folder="Briefe 2004",
    )
    assert "Quellordner (kann auf Zeitraum oder Thema hinweisen): Briefe 2004" in prompt
    assert '"datum": "JJJJ-MM-TT (Datum des Dokuments) oder UNBEKANNT"' in prompt
    assert "nicht Fristen, Faelligkeits-, Gueltigkeits- oder Geburtsdaten" in prompt
    assert "Hinweis aus der Texterkennung" in prompt
    assert "nur Notloesung" in prompt
    assert "Steuerjahr = Jahr des Dokumentdatums" in prompt


def test_prompt_ohne_quellordner(provider):
    prompt = provider._build_filename_prompt(text="Text", current_filename="scan.pdf")
    assert "Quellordner" not in prompt


def test_source_folder_hint_nicht_fuer_den_scan_ordner(tmp_path, monkeypatch):
    from src.ml import hybrid_classifier as hc

    class _Cfg:
        def get_scan_folder(self):
            return tmp_path / "Scans"

    monkeypatch.setattr(hc, "get_config", lambda: _Cfg())
    assert hc.source_folder_hint(tmp_path / "Scans" / "a.pdf") is None
    assert hc.source_folder_hint(tmp_path / "Archiv" / "Briefe 2004" / "a.pdf") == "Briefe 2004"


def test_source_folder_hint_ohne_scan_ordner(tmp_path, monkeypatch):
    from src.ml import hybrid_classifier as hc

    class _Cfg:
        def get_scan_folder(self):
            return None

    monkeypatch.setattr(hc, "get_config", lambda: _Cfg())
    assert hc.source_folder_hint(tmp_path / "Briefe 2004" / "a.pdf") == "Briefe 2004"

import pytest

from src.ml.llm_provider import LLMConfig, LLMProvider


class _StubProvider(LLMProvider):
    def _initialize_client(self): pass
    def classify_document(self, *a, **kw): pass
    def suggest_filename(self, *a, **kw): pass
    def is_available(self): return True
    # Phase 19 / M1: RAG-Chat. Stub-Implementierung damit die Klasse
    # weiterhin instanziierbar bleibt.
    def answer_with_context(self, *a, **kw): return ""


@pytest.fixture
def provider():
    return _StubProvider(LLMConfig(api_key="dummy", model="dummy"))


# --- _parse_json_response ---

def test_parse_clean_json(provider):
    text = '{"folder_suggestion":"Rechnungen","confidence":0.9,"metadata":{"betrag":50}}'
    data, err = provider._parse_json_response(text)
    assert err is None
    assert data == {
        "folder_suggestion": "Rechnungen",
        "confidence": 0.9,
        "metadata": {"betrag": 50},
    }


def test_parse_json_with_chatter_before(provider):
    text = 'Hier ist deine Analyse: {"folder":"Rechnungen","confidence":0.8}'
    data, err = provider._parse_json_response(text)
    assert err is None
    assert data["folder"] == "Rechnungen"


def test_parse_json_with_chatter_after(provider):
    text = '{"folder":"Steuer","confidence":0.7} Bitte beachte das noch.'
    data, err = provider._parse_json_response(text)
    assert err is None
    assert data["folder"] == "Steuer"


def test_parse_json_with_chatter_both_sides(provider):
    text = 'OK. {"folder":"Vertraege","confidence":0.6} Fertig.'
    data, err = provider._parse_json_response(text)
    assert err is None
    assert data["folder"] == "Vertraege"


def test_parse_json_with_newlines(provider):
    text = '{\n  "folder": "Rechnungen",\n  "confidence": 0.9,\n  "metadata": {}\n}'
    data, err = provider._parse_json_response(text)
    assert err is None
    assert data["folder"] == "Rechnungen"
    assert data["confidence"] == 0.9


def test_parse_no_json(provider):
    data, err = provider._parse_json_response("Ich habe keine Daten.")
    assert data is None
    assert err is not None
    assert len(err) > 0


def test_parse_malformed_json(provider):
    # Has braces but is not valid JSON
    data, err = provider._parse_json_response('{"key": "value", broken}')
    assert data is None
    assert err is not None
    assert len(err) > 0


def test_parse_empty_string(provider):
    data, err = provider._parse_json_response("")
    assert data is None
    assert err is not None


# --- prompt builders ---

def test_build_classification_prompt_contains_required_parts(provider):
    prompt = provider._build_classification_prompt(
        text="Rechnung von Telekom ueber 59,99 EUR",
        available_folders=["Rechnungen", "Steuer", "Vertraege"],
        keywords=["rechnung", "telekom"],
        detected_date="2024-01-15",
    )
    assert "metadata" in prompt
    assert "folder" in prompt
    assert "JSON" in prompt
    assert "Telekom" in prompt


def test_build_filename_prompt_contains_required_parts(provider):
    prompt = provider._build_filename_prompt(
        text="Rechnung von Telekom ueber 59,99 EUR",
        current_filename="scan_001.pdf",
        keywords=["rechnung"],
        detected_date="2024-01-15",
        target_folder="Rechnungen",
        file_date="2024-01-20",
    )
    assert "metadata" in prompt
    assert "scan_001.pdf" in prompt
    assert "JSON" in prompt

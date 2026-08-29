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


def test_build_filename_prompt_forbids_email_as_contact(provider):
    prompt = provider._build_filename_prompt(text="Text", current_filename="scan.pdf")
    assert "niemals eine E-Mail-Adresse" in prompt
    assert "kathrin.haerle@web.de -> Kathrin_Haerle" in prompt
    assert "Kein Punkt ausser vor .pdf" in prompt


class _CfgStub:
    def __init__(self, **values):
        self._v = values

    def get(self, key, default=None):
        return self._v.get(key, default)


def test_pattern_info_explains_initials_and_uses_configured_ones(provider, monkeypatch):
    import src.utils.config as cfg
    monkeypatch.setattr(cfg, "get_config", lambda: _CfgStub(
        filename_pattern="PROJEKTNUMMER_INITIALIEN/AKTENZEICHEN_YYYY-MM-DD_Betreff_Kontakt",
        folder_naming_initials="JW",
        owner_name="Johannes Haerle-Wack",
    ))
    info = provider._build_filename_pattern_info()
    assert "2-3 Großbuchstaben" in info
    assert "NIE ein ausgeschriebener Name" in info
    assert "Verwende genau: JW" in info


def test_pattern_info_derives_initials_from_owner_name(provider, monkeypatch):
    import src.utils.config as cfg
    monkeypatch.setattr(cfg, "get_config", lambda: _CfgStub(
        filename_pattern="INITIALEN_YYYY-MM-DD_Betreff",
        folder_naming_initials="",
        owner_name="Dr. med. Johannes Härle-Wack",
    ))
    assert "Verwende genau: JHW" in provider._build_filename_pattern_info()


def test_pattern_info_without_initials_placeholder_has_no_hint(provider, monkeypatch):
    import src.utils.config as cfg
    monkeypatch.setattr(cfg, "get_config", lambda: _CfgStub(
        filename_pattern="YYYY-MM-DD_Rechnung_Kontakt_Betreff",
        folder_naming_initials="JW",
    ))
    info = provider._build_filename_pattern_info()
    assert "YYYY-MM-DD_Rechnung_Kontakt_Betreff" in info
    assert "INITIAL" not in info


def test_derive_initials():
    from src.ml.llm_provider import derive_initials
    assert derive_initials("Johannes Härle-Wack") == "JHW"
    assert derive_initials("Dr. med. Johannes Wack") == "JW"
    assert derive_initials("Prof. Dr. Anna Maria Müller-Lüdenscheidt") == "AMM"
    assert derive_initials("Johannes") == ""
    assert derive_initials("") == ""

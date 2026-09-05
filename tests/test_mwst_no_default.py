"""MwSt-Satz darf kein geratener Standardwert sein.

Im Prompt-Schema stand ``"mwst": 7`` als Beispiel; kleine Modelle kopierten
das in jede Antwort. Jetzt: Beispiel ohne feste Zahl, Prompt-Regel, und ein
Satz, der im Dokumenttext nicht vorkommt, wird verworfen.
"""
import pytest

from src.ml.llm_provider import drop_unsupported_mwst

from tests.test_llm_metadata_extraction import provider  # noqa: F401 - Fixture


@pytest.mark.parametrize("text", [
    "Rechnung Nr. 12 ... zzgl. 19 % MwSt ... Gesamt 119,00 EUR",
    "Umsatzsteuer 19%",
    "Betrag 100,00 zzgl. USt (19,00 %)",
    "enthaltene Mehrwertsteuer: 7 %",           # Steuer-Wort reicht
])
def test_rate_kept_when_document_mentions_tax(text):
    assert drop_unsupported_mwst({"mwst_satz": 19}, text) == {"mwst_satz": 19}


@pytest.mark.parametrize("text", [
    "Klaviernoten Praeludium C-Dur, Seite 1 von 4",
    "Befundbericht: Patient klagt ueber Kopfschmerzen. Termin in 7 Tagen.",
    "Mietvertrag ueber die Wohnung, Miete 700 EUR monatlich",
])
def test_rate_dropped_when_document_has_no_tax(text):
    for rate in (7, "7", "7 %", 19, "19%"):
        out = drop_unsupported_mwst({"mwst_satz": rate, "subject": "Sonstiges"}, text)
        assert "mwst_satz" not in out, (rate, text)
        assert out["subject"] == "Sonstiges"


def test_no_text_or_no_rate_is_untouched():
    assert drop_unsupported_mwst({"mwst_satz": 7}, None) == {"mwst_satz": 7}
    assert drop_unsupported_mwst({"subject": "Arzt"}, "kein steuertext") == {"subject": "Arzt"}
    assert drop_unsupported_mwst("kein dict", "x") == "kein dict"


def test_parse_json_response_applies_document_check(provider):  # noqa: F811
    raw = '{"filename": "a.pdf", "metadata": {"category": "Arzt", "mwst": 7, "steuerjahr": 2025}}'
    data, err = provider._parse_json_response(raw, document_text="Befund ohne Steuer")
    assert err is None
    assert data["metadata"] == {"subject": "Arzt", "steuerjahr": 2025}
    data, _ = provider._parse_json_response(raw)   # ohne Text: unveraendert
    assert data["metadata"]["mwst_satz"] == 7


def test_prompts_have_no_example_rate(provider):  # noqa: F811
    p1 = provider._build_filename_prompt(text="t", current_filename="s.pdf")
    p2 = provider._build_classification_prompt("t", ["A", "B"])
    for p in (p1, p2):
        assert '"mwst": 7' not in p and '"steuerjahr": 2024' not in p
        assert "UNBEKANNT" in p
    assert "Niemals einen Standardwert" in p1

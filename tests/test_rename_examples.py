"""Historie als Stil-Beispiele im KI-Prompt statt „Gelernt“-Vorschlaege."""
from dataclasses import dataclass

import pytest

from src.core.rename_examples import (
    describe_examples_for_prompt,
    name_tokens,
    rank_examples,
    score_example,
)
from tests.test_llm_metadata_extraction import provider  # noqa: F401 - Fixture


@dataclass
class _Entry:
    new_filename: str
    keywords: str | None = None


TEXT = (
    "Commerzbank AG Depotauszug per 31.12.2024 fuer Johannes Wack. "
    "Wertpapiere und Kurswerte. Rechnung fuer Depotgebuehren."
)


def test_name_tokens_drop_dates_initials_and_generic_words():
    tokens = name_tokens("JW_2024-01-31_Rechnung_Commerzbank_Depotauszug-Wertpapiere.pdf")
    assert tokens == {"commerzbank", "depotauszug", "wertpapiere"}


def test_single_shared_keyword_is_not_similar():
    # Das alte Verhalten: "rechnung" allein machte jeden Eintrag zum Treffer
    assert score_example("2024-01-01_Rechnung_Telekom.pdf", "rechnung,telekom", TEXT, ["rechnung"]) == 1
    assert rank_examples([_Entry("2024-01-01_Rechnung_Telekom.pdf", "rechnung,telekom")],
                         TEXT, ["rechnung"]) == []


def test_name_in_text_or_two_keywords_count_as_similar():
    by_name = _Entry("2022-04-03_Commerzbank_Depotauszug.pdf", "bank")
    by_keywords = _Entry("2023-02-01_Kostenrechnung_Notar.pdf", "rechnung,depot")
    unrelated = _Entry("2024-02-04_Bank_Nachlassvollmacht.pdf", "vollmacht")
    ranked = rank_examples([unrelated, by_keywords, by_name], TEXT, ["rechnung", "depot"])
    assert ranked == [by_name, by_keywords]  # 4 Punkte vor 2 Punkten


def test_ties_keep_newest_first_and_dedupe_names():
    newest = _Entry("2025-01-01_Commerzbank_Auszug.pdf", "")
    older = _Entry("2024-01-01_Commerzbank_Auszug.pdf", "")
    same_name = _Entry("2025-01-01_Commerzbank_Auszug.pdf", "")
    ranked = rank_examples([newest, same_name, older], TEXT, [], limit=5)
    assert ranked == [newest, older]
    assert rank_examples([newest, older], TEXT, [], limit=1) == [newest]


def test_describe_examples_for_prompt():
    assert describe_examples_for_prompt([]) == ""
    block = describe_examples_for_prompt(["A_B.pdf", "", "C_D.pdf"])
    assert "ÄHNLICHE DOKUMENTE ZULETZT BENANNT" in block
    assert "- A_B.pdf\n- C_D.pdf" in block
    assert "aus DIESEM Dokument" in block


def test_prompt_contains_examples_only_when_given(provider):  # noqa: F811
    prompt = provider._build_filename_prompt(
        text=TEXT, current_filename="scan.pdf", keywords=["bank"],
        examples=["2022-04-03_Commerzbank_Depotauszug.pdf"],
    )
    assert "- 2022-04-03_Commerzbank_Depotauszug.pdf" in prompt
    assert "ZULETZT BENANNT" in prompt
    plain = provider._build_filename_prompt(text=TEXT, current_filename="scan.pdf")
    assert "ZULETZT BENANNT" not in plain


def test_database_returns_similar_renames(tmp_path):
    from src.utils.database import Database
    db = Database(db_path=tmp_path / "hist.db")
    db.add_rename_entry("scan1.pdf", "2024-02-04_Bank_Nachlassvollmacht.pdf",
                        extracted_text="Vollmacht", keywords=["vollmacht", "bank"])
    db.add_rename_entry("scan2.pdf", "2022-04-03_Commerzbank_Depotauszug.pdf",
                        extracted_text="Depot", keywords=["bank"])
    db.add_rename_entry("scan3.pdf", "2023-02-25_Kostenrechnung_Notar_Eisenburger.pdf",
                        extracted_text="Notar", keywords=["rechnung", "notar"])

    names = [e.new_filename for e in db.get_rename_examples(TEXT, ["rechnung", "bank"])]
    assert names == ["2022-04-03_Commerzbank_Depotauszug.pdf"]
    assert db.get_rename_examples("", []) == []


def test_hybrid_passes_examples_to_provider(monkeypatch, tmp_path):
    """Der KI-Aufruf bekommt die Historien-Beispiele; ohne DB laeuft er trotzdem."""
    from src.ml import hybrid_classifier as hc
    from src.ml.llm_provider import LLMResponse
    from src.utils.database import Database

    db = Database(db_path=tmp_path / "hist.db")
    db.add_rename_entry("s.pdf", "2022-04-03_Commerzbank_Depotauszug.pdf", keywords=["bank"])
    monkeypatch.setattr(hc, "get_database", lambda: db)

    calls = {}

    class _Provider:
        def suggest_filename(self, **kwargs):
            calls.update(kwargs)
            return LLMResponse(success=True, filename_suggestion="2024-12-31_Bank_Commerzbank_Depotauszug.pdf",
                               confidence=0.9, tokens_used=1)

    classifier = hc.HybridClassifier.__new__(hc.HybridClassifier)
    classifier.llm_provider = _Provider()
    classifier.total_tokens_used = 0
    classifier.last_llm_error = None

    result = classifier._get_llm_filename_suggestion(TEXT, "scan.pdf", ["bank"], None, None)
    assert result is not None and result.filename.startswith("2024-12-31_Bank_Commerzbank")
    assert calls["examples"] == ["2022-04-03_Commerzbank_Depotauszug.pdf"]

    def boom():
        raise RuntimeError("keine DB")
    monkeypatch.setattr(hc, "get_database", boom)
    assert classifier._rename_examples(TEXT, ["bank"]) == []

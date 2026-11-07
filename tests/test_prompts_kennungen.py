"""System-Prompt und Kontextblock seit Issue #166/#167."""
from src.rag.prompts import (
    GEMEINSAME_KENNUNGEN_PRAEFIX,
    KENNUNGEN_PRAEFIX,
    SYSTEM_PROMPT,
    build_context_block,
)


def test_system_prompt_erlaubt_ketten_und_verbietet_such_aufforderung():
    assert "gemeinsame Kennung" in SYSTEM_PROMPT
    assert "Nenne dann die Kette" in SYSTEM_PROMPT
    assert "Fordere den Nutzer\n   nicht auf, selbst zu suchen." in SYSTEM_PROMPT
    assert "schlage vor, wonach" not in SYSTEM_PROMPT
    # Die ehrliche Standardantwort bleibt woertlich erhalten
    assert '"Ich finde dazu keine passenden Dokumente in deiner Sammlung."' in SYSTEM_PROMPT
    assert "7. Antworte in der Sprache der Frage." in SYSTEM_PROMPT


def test_prompts_warnen_vor_wortuebereinstimmungen_und_verlangen_suche_bei_summen():
    from src.rag.prompts import SYSTEM_PROMPT_WERKZEUGE, build_system_prompt_werkzeuge

    for prompt in (SYSTEM_PROMPT, SYSTEM_PROMPT_WERKZEUGE):
        assert "gemeinsame Kennungen mit dem Bezugsdokument" in prompt
        assert "bloße Wortübereinstimmungen" in prompt
    assert "Beträgen, Summen oder einem Zeitraum" in SYSTEM_PROMPT_WERKZEUGE
    assert "aus einem Dateinamen allein" in SYSTEM_PROMPT_WERKZEUGE
    assert "höchstens 4 Schritte" in build_system_prompt_werkzeuge(4)
    assert "{max_schritte}" not in build_system_prompt_werkzeuge("x")


def test_kontextblock_mit_kennungen():
    docs = [
        {"index": 1, "filename": "Scan.pdf", "text_snippet": "Vertrag", "bezug": True, "ordner": "Scan",
         "kennungen": ["G1 (Vertragsnummer)", "226541 (Zählernummer)"]},
        {"index": 2, "filename": "Abrechnung.pdf", "text_snippet": "Abnahmestelle X",
         "gemeinsame_kennungen": ["G1 (Vertragsnummer)"], "hinweise": ["HINWEIS"]},
        {"index": 3, "filename": "Andere.pdf", "text_snippet": "Nichts", "kennungen": [], "gemeinsame_kennungen": None},
    ]
    block = build_context_block(docs)
    assert f"     {KENNUNGEN_PRAEFIX} G1 (Vertragsnummer), 226541 (Zählernummer)" in block
    assert f"     {GEMEINSAME_KENNUNGEN_PRAEFIX} G1 (Vertragsnummer)" in block
    assert block.count(KENNUNGEN_PRAEFIX) == 1 and block.count(GEMEINSAME_KENNUNGEN_PRAEFIX) == 1
    d2 = block[block.index("[D2]"):block.index("[D3]")]
    assert d2.index(GEMEINSAME_KENNUNGEN_PRAEFIX) < d2.index("HINWEIS") < d2.index("--- text ---")

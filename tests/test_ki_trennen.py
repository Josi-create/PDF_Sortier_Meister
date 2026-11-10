"""KI-unterstuetztes Trennen: Qt-freier Kern (Prompt, Antwort, Seitenangaben) und ``split_pdf_teile``."""
from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

from src.core import ki_trennen as kt
from src.core.file_manager import FileManager
from src.core.ki_trennen import Teil


class _Provider:
    def __init__(self, antwort):
        self.antwort = antwort
        self.fragen: list[str] = []
        self.max_tokens = None

    def answer_with_context(self, system_prompt, context_docs, user_question, max_tokens=1000):
        self.fragen.append(user_question)
        self.max_tokens = max_tokens
        return self.antwort


def _pdf(pfad: Path, texte: list[str]) -> Path:
    doc = pymupdf.open()
    for text in texte:
        seite = doc.new_page()
        if text:
            seite.insert_text((50, 100), text)
    doc.save(str(pfad))
    doc.close()
    return pfad


def _antwort(*dokumente) -> str:
    return json.dumps({"dokumente": [{"erste_seite": s, "name": n} for s, n in dokumente]})


# --- Prompt -----------------------------------------------------------------------

def test_prompt_nennt_jede_seite_und_markiert_leere():
    prompt = kt.ki_prompt(["Stadtwerke Rechnung", "", "Finanzamt"])
    assert "hat 3 Seiten" in prompt
    assert "=== Seite 1 ===\nStadtwerke Rechnung" in prompt
    assert "=== Seite 2 ===\n(leere Seite / kein Text)" in prompt
    assert "=== Seite 3 ===\nFinanzamt" in prompt
    assert '"erste_seite"' in prompt


def test_prompt_kuerzt_lange_seiten_auf_anfang_und_ende():
    text = "ANFANG " + "x" * 5000 + " Seite 2 von 3 ENDE"
    prompt = kt.ki_prompt([text])
    assert "ANFANG" in prompt and "ENDE" in prompt and "[...]" in prompt
    assert len(prompt) < 3500


def test_prompt_bleibt_bei_grossem_stapel_im_rahmen():
    prompt = kt.ki_prompt(["y" * 5000] * 200)
    assert "=== Seite 200 ===" in prompt
    # 200 Seiten zu je mindestens ZEICHEN_JE_SEITE_MIN, nicht zu je 1200
    assert len(prompt) < 200 * (kt.ZEICHEN_JE_SEITE_MIN + 40) + 3000


# --- Antwort ----------------------------------------------------------------------

def test_antwort_ergibt_lueckenlose_bereiche():
    teile = kt.antwort_auswerten(_antwort((1, "A"), (4, "B"), (9, "C")), 12)
    assert teile == [Teil([1, 2, 3], "A"), Teil([4, 5, 6, 7, 8], "B"), Teil([9, 10, 11, 12], "C")]


def test_antwort_mit_text_drumherum_und_unsortiert():
    text = "Gern, hier das Ergebnis:\n```json\n" + _antwort((3, "Zwei"), (1, "Eins")) + "\n```"
    assert kt.antwort_auswerten(text, 4) == [Teil([1, 2], "Eins"), Teil([3, 4], "Zwei")]


def test_antwort_erstes_dokument_beginnt_immer_auf_seite_eins():
    assert kt.antwort_auswerten(_antwort((2, "A"), (4, "B")), 5) == [Teil([1, 2, 3], "A"), Teil([4, 5], "B")]


def test_antwort_ungueltige_und_doppelte_anfaenge_fallen_weg():
    text = json.dumps({"dokumente": [
        {"erste_seite": 1, "name": "A"}, {"erste_seite": 9, "name": "zu weit"},
        {"erste_seite": "drei", "name": "kein Zahl"}, {"erste_seite": 0, "name": "null"},
        {"erste_seite": 3, "name": "B"}, {"erste_seite": 3, "name": "B nochmal"}, "kaputt",
        {"erste_seite": "2", "name": "Zahl als Text"},
    ]})
    assert kt.antwort_auswerten(text, 4) == [Teil([1], "A"), Teil([2], "Zahl als Text"), Teil([3, 4], "B")]


def test_antwort_namen_werden_bereinigt_und_ersetzt():
    teile = kt.antwort_auswerten(_antwort((1, "2026-10-05_Müller: Strom/Gas.pdf"), (2, ""), (3, None)), 3, "scan")
    assert teile[0].name == "2026-10-05_Mueller_Strom_Gas"
    assert teile[1].name == "scan_Teil_2" and teile[2].name == "scan_Teil_3"


def test_antwort_ein_einziges_dokument():
    assert kt.antwort_auswerten(_antwort((1, "Vertrag")), 7) == [Teil([1, 2, 3, 4, 5, 6, 7], "Vertrag")]


@pytest.mark.parametrize("text", [
    "", "kein json", "{kaputt", "[1, 2]", '{"dokumente": []}', '{"dokumente": "x"}', '{"andere": 1}',
    '{"dokumente": [{"erste_seite": 99, "name": "A"}]}',
])
def test_antwort_unbrauchbar_ist_none(text):
    assert kt.antwort_auswerten(text, 4) is None


def test_name_bereinigen_kuerzt_und_faellt_zurueck():
    assert len(kt.name_bereinigen("a" * 300)) == kt.NAME_MAX
    assert kt.name_bereinigen("  ", "Ersatz") == "Ersatz"
    assert kt.name_bereinigen("Brief.PDF") == "Brief"


# --- vorschlagen ------------------------------------------------------------------

def test_vorschlagen_fragt_einmal_und_liefert_teile():
    provider = _Provider(_antwort((1, "Rechnung"), (3, "Bescheid")))
    teile = kt.vorschlagen(provider, ["a", "b", "c", ""], "stapel")
    assert teile == [Teil([1, 2], "Rechnung"), Teil([3, 4], "Bescheid")]
    assert len(provider.fragen) == 1 and "=== Seite 4 ===" in provider.fragen[0]
    assert provider.max_tokens >= 1000


@pytest.mark.parametrize("antwort, meldung", [
    ("", "nicht geantwortet"),
    (None, "nicht geantwortet"),
    ("[OpenAI-Fehler: Zeitüberschreitung]", "Zeitüberschreitung"),
    ("Das kann ich nicht sagen.", "keine brauchbare Aufteilung"),
])
def test_vorschlagen_meldet_fehler_lesbar(antwort, meldung):
    with pytest.raises(RuntimeError, match=meldung):
        kt.vorschlagen(_Provider(antwort), ["a", "b"])


# --- Seitenangaben ----------------------------------------------------------------

@pytest.mark.parametrize("text, erwartet", [
    ("1-3", [1, 2, 3]),
    ("5", [5]),
    ("1-3, 7", [1, 2, 3, 7]),
    (" 7 ; 1 - 2 ,2", [1, 2, 7]),
    ("4–6", [4, 5, 6]),  # Halbgeviertstrich
])
def test_seiten_parsen(text, erwartet):
    assert kt.seiten_parsen(text, 8) == erwartet


@pytest.mark.parametrize("text", ["", " , ", "abc", "0", "9", "3-1", "1-9", "1-2-3", "-2"])
def test_seiten_parsen_fehler(text):
    with pytest.raises(ValueError):
        kt.seiten_parsen(text, 8)


@pytest.mark.parametrize("seiten, erwartet", [
    ([1, 2, 3, 7], "1-3, 7"),
    ([5], "5"),
    ([3, 1, 2, 2], "1-3"),
    ([1, 3, 5, 6], "1, 3, 5-6"),
    ([], ""),
])
def test_seiten_als_text(seiten, erwartet):
    assert kt.seiten_als_text(seiten) == erwartet


# --- Seitentexte ------------------------------------------------------------------

def test_seiten_texte_aus_der_textebene_leere_seiten_bleiben_leer(tmp_path, monkeypatch):
    from src.core import pdf_analyzer as pa
    monkeypatch.setattr(pa, "suchindex_fuer_analyse", lambda: None)
    monkeypatch.setattr(pa, "ocr_einstellungen_fuer_analyse", lambda: None)
    pdf = _pdf(tmp_path / "s.pdf", ["Stadtwerke Rechnung Nummer 4711 vom Oktober", "", "Finanzamt Bescheid Einkommensteuer"])
    texte = kt.seiten_texte(pdf)
    assert len(texte) == 3
    assert "Stadtwerke" in texte[0] and texte[1].strip() == "" and "Finanzamt" in texte[2]


def test_seiten_texte_nimmt_den_aktuellen_indexeintrag(tmp_path, monkeypatch):
    from src.core import pdf_analyzer as pa

    class _Index:
        def text_fuer_datei(self, pfad):
            return {"aktuell": True, "textstatus": "text", "ocr_offen": [],
                    "seiten": [(1, "text", "aus dem Index"), (2, "ocr", "per OCR")]}

    monkeypatch.setattr(pa, "suchindex_fuer_analyse", lambda: _Index())
    pdf = _pdf(tmp_path / "s.pdf", ["anders", "anders"])
    assert kt.seiten_texte(pdf) == ["aus dem Index", "per OCR"]


def test_seiten_texte_liest_offene_seiten_per_ocr(tmp_path, monkeypatch):
    from src.core import pdf_analyzer as pa
    from src.search import extract

    monkeypatch.setattr(pa, "suchindex_fuer_analyse", lambda: None)
    monkeypatch.setattr(pa, "ocr_einstellungen_fuer_analyse", lambda: {"x": 1})
    monkeypatch.setattr(extract, "pdf_text", lambda pfad, mz, gerade=False: {
        "status": "text", "anzahl": 3, "ohne_text": [2, 3], "fehler": None,
        "seiten": [(1, "text", "Seite eins"), (2, "ohne_text", ""), (3, "ohne_text", "")]})
    gefragt = []
    monkeypatch.setattr(extract, "pdf_ocr", lambda pfad, seiten, cfg: gefragt.append(seiten) or {
        "texte": {2: "erkannt", 3: "  "}, "fehler": None})
    pdf = _pdf(tmp_path / "s.pdf", ["a", "b", "c"])
    assert kt.seiten_texte(pdf) == ["Seite eins", "erkannt", ""]
    assert gefragt == [[2, 3]]


def test_seiten_texte_ocr_fehler_laesst_seiten_leer(tmp_path, monkeypatch):
    from src.core import pdf_analyzer as pa
    from src.search import extract

    monkeypatch.setattr(pa, "suchindex_fuer_analyse", lambda: None)
    monkeypatch.setattr(pa, "ocr_einstellungen_fuer_analyse", lambda: {"x": 1})
    monkeypatch.setattr(extract, "pdf_text", lambda pfad, mz, gerade=False: {
        "status": "text", "anzahl": 2, "ohne_text": [2], "fehler": None,
        "seiten": [(1, "text", "eins"), (2, "ohne_text", "")]})
    monkeypatch.setattr(extract, "pdf_ocr", lambda *a: (_ for _ in ()).throw(OSError("tesseract weg")))
    assert kt.seiten_texte(_pdf(tmp_path / "s.pdf", ["a", "b"])) == ["eins", ""]


def test_seiten_texte_verschluesselt_und_kaputt(tmp_path, monkeypatch):
    from src.core import pdf_analyzer as pa
    from src.search import extract

    monkeypatch.setattr(pa, "suchindex_fuer_analyse", lambda: None)
    pdf = _pdf(tmp_path / "s.pdf", ["a"])
    monkeypatch.setattr(extract, "pdf_text", lambda *a, **k: {"status": "verschluesselt", "anzahl": 1})
    with pytest.raises(RuntimeError, match="verschlüsselt"):
        kt.seiten_texte(pdf)
    monkeypatch.setattr(extract, "pdf_text", lambda *a, **k: {"status": "fehler", "fehler": "Öffnen: kaputt"})
    with pytest.raises(RuntimeError, match="kaputt"):
        kt.seiten_texte(pdf)


# --- FileManager.split_pdf_teile ----------------------------------------------------

def _seitentexte(pfad: Path) -> list[str]:
    with pymupdf.open(str(pfad)) as doc:
        return [s.get_text().strip() for s in doc]


def test_split_pdf_teile_schreibt_mehrseitige_dokumente(tmp_path):
    quelle = _pdf(tmp_path / "stapel.pdf", ["S1", "S2", "S3", "S4", "S5", "S6"])
    aus = FileManager().split_pdf_teile(
        quelle, tmp_path, [([1, 2, 3], "Brief"), ([4], "Rechnung.pdf"), ([5, 6], "Bescheid")])
    assert [p.name for p in aus] == ["Brief.pdf", "Rechnung.pdf", "Bescheid.pdf"]
    assert _seitentexte(aus[0]) == ["S1", "S2", "S3"]
    assert _seitentexte(aus[1]) == ["S4"]
    assert _seitentexte(aus[2]) == ["S5", "S6"]
    assert _seitentexte(quelle) == ["S1", "S2", "S3", "S4", "S5", "S6"]  # Original unveraendert


def test_split_pdf_teile_nicht_zusammenhaengende_seiten(tmp_path):
    quelle = _pdf(tmp_path / "stapel.pdf", ["S1", "S2", "S3", "S4"])
    aus = FileManager().split_pdf_teile(quelle, tmp_path, [([1, 4], "A"), ([2, 3], "B")])
    assert _seitentexte(aus[0]) == ["S1", "S4"] and _seitentexte(aus[1]) == ["S2", "S3"]


def test_split_pdf_teile_gleiche_und_vorhandene_namen_bekommen_nummer(tmp_path):
    quelle = _pdf(tmp_path / "stapel.pdf", ["S1", "S2", "S3"])
    (tmp_path / "Brief.pdf").write_bytes(b"schon da")
    aus = FileManager().split_pdf_teile(quelle, tmp_path, [([1], "Brief"), ([2], "Brief"), ([3], "stapel")])
    assert len({p.name for p in aus}) == 3 and all(p.exists() for p in aus)
    assert (tmp_path / "Brief.pdf").read_bytes() == b"schon da"
    assert quelle not in aus and _seitentexte(quelle) == ["S1", "S2", "S3"]


@pytest.mark.parametrize("teile", [[([0], "A")], [([1, 5], "A")], [([], "A")]])
def test_split_pdf_teile_ungueltige_seiten_schreiben_nichts(tmp_path, teile):
    quelle = _pdf(tmp_path / "stapel.pdf", ["S1", "S2"])
    with pytest.raises(ValueError):
        FileManager().split_pdf_teile(quelle, tmp_path, [([1], "Gut")] + teile)
    assert [p.name for p in tmp_path.iterdir()] == ["stapel.pdf"]


def test_split_pdf_teile_fehlende_quelle_und_ziel(tmp_path):
    quelle = _pdf(tmp_path / "stapel.pdf", ["S1", "S2"])
    with pytest.raises(FileNotFoundError):
        FileManager().split_pdf_teile(tmp_path / "fehlt.pdf", tmp_path, [([1], "A")])
    with pytest.raises(ValueError):
        FileManager().split_pdf_teile(quelle, tmp_path / "fehlt", [([1], "A")])

"""Issue #196: Zielvorschlaege fuer einen ganzen Ordner (a: Inhalt, b: Namensvetter, c: KI)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core import ordner_vorschlaege as ov
from src.core.pdf_cache import LLMSuggestion


def _ordner(*teile) -> Path:
    p = Path(*teile)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _datei(pfad: Path, inhalt: bytes = b"x") -> Path:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(inhalt)
    return pfad


def _ki_cache(zuordnung: dict):
    """cache_get: Datei -> Analyse mit KI-Vorschlag (Metadaten "zielordner")."""
    def get(pfad):
        rel = zuordnung.get(Path(pfad).name)
        if rel is None:
            return None
        return SimpleNamespace(
            extracted_text="", keywords=[], dates=[],
            llm_suggestions=[LLMSuggestion(filename="x.pdf", metadata={"zielordner": rel})],
        )
    return get


@pytest.fixture
def ablage(tmp_path):
    root = _ordner(tmp_path, "Ablage")
    _ordner(root, "Steuer 2024", "Versicherungen")
    _ordner(root, "Steuer 2025")
    _ordner(root, "Privat")
    return root


# --- a) Inhalt ------------------------------------------------------------------

def test_inhalt_mehrheit_der_ki_vorschlaege_gewinnt(tmp_path, ablage):
    ordner = _ordner(tmp_path, "Eingang", "Rechnungen")
    for n in ("a.pdf", "b.pdf", "c.pdf"):
        _datei(ordner / n)
    cache = _ki_cache({
        "a.pdf": "Ablage/Steuer 2025", "b.pdf": "Ablage/Steuer 2025", "c.pdf": "Ablage/Privat",
    })
    liste = ov.vorschlaege_fuer_ordner(ordner, [ablage], cache_get=cache)
    assert liste[0].folder_path == ablage / "Steuer 2025"  # Name verschieden: Zielordner selbst ist der Eltern
    assert liste[1].folder_path == ablage / "Privat"
    assert liste[0].confidence > liste[1].confidence
    assert "Inhalt" in liste[0].reason


def test_inhalt_gleichnamiges_ziel_leitet_den_eltern_ab(tmp_path, ablage):
    """Dateien gehoeren nach "Steuer 2025/Versicherungen" -> der Ordner "Versicherungen" nach "Steuer 2025"."""
    _ordner(ablage, "Steuer 2025", "Versicherungen")
    ordner = _ordner(tmp_path, "Eingang", "Versicherungen")
    _datei(ordner / "p.pdf")
    liste = ov.vorschlaege_fuer_ordner(
        ordner, [ablage], cache_get=_ki_cache({"p.pdf": "Ablage/Steuer 2025/Versicherungen"})
    )
    assert liste[0].folder_path == ablage / "Steuer 2025"


def test_inhalt_unterordner_des_gleichnamigen_ziels_leitet_den_oberordner_ab(tmp_path, ablage):
    _ordner(ablage, "Steuer 2025", "Versicherungen", "Kfz")
    ordner = _ordner(tmp_path, "Eingang", "Versicherungen")
    _datei(ordner / "p.pdf")
    liste = ov.vorschlaege_fuer_ordner(
        ordner, [ablage], cache_get=_ki_cache({"p.pdf": "Ablage/Steuer 2025/Versicherungen/Kfz"})
    )
    assert liste[0].folder_path == ablage / "Steuer 2025"


def test_inhalt_klassifikator_und_historie_zaehlen_mit(tmp_path, ablage):
    ordner = _ordner(tmp_path, "Eingang", "Gemischt")
    _datei(ordner / "Brief.pdf")
    _datei(ordner / "Rechnung.pdf")
    _datei(ordner / "Leer.pdf")
    cache = lambda p: (SimpleNamespace(extracted_text="Text", keywords=["k"], dates=[], llm_suggestions=[])
                       if Path(p).name == "Rechnung.pdf" else None)
    vorgabe = SimpleNamespace(folder_path=ablage / "Steuer 2025", confidence=0.8)
    schwach = SimpleNamespace(folder_path=ablage / "Privat", confidence=0.3)  # nur "haeufig verwendet"
    db = SimpleNamespace(get_history_brief=lambda limit=0: [
        {"original_filename": "Brief.pdf", "new_filename": None, "target_folder": str(ablage / "Privat")},
    ])

    liste = ov.vorschlaege_fuer_ordner(
        ordner, [ablage], db=db, cache_get=cache, suggest_fn=lambda t, k: [vorgabe, schwach]
    )
    pfade = [s.folder_path for s in liste]
    assert pfade[:2] == [ablage / "Steuer 2025", ablage / "Privat"] or pfade[:2] == [ablage / "Privat", ablage / "Steuer 2025"]
    assert len(pfade) == 2  # "haeufig verwendet" (0.3) zaehlt nicht als Stimme


def test_aktueller_eltern_ordner_selbst_und_unterordner_werden_nie_vorgeschlagen(tmp_path):
    root = _ordner(tmp_path, "Ablage")
    ordner = _ordner(root, "Steuer 2025", "Versicherungen")
    _datei(ordner / "a.pdf")
    _datei(ordner / "Sub" / "b.pdf")
    cache = _ki_cache({
        "a.pdf": "Ablage/Steuer 2025",  # = aktueller Elternordner
        "b.pdf": "Ablage/Steuer 2025/Versicherungen",  # = der Ordner selbst
    })
    assert ov.vorschlaege_fuer_ordner(ordner, [root], cache_get=cache) == []


def test_ohne_daten_keine_vorschlaege(tmp_path, ablage):
    ordner = _ordner(tmp_path, "Eingang", "Einzigartig")
    _datei(ordner / "a.pdf")
    assert ov.vorschlaege_fuer_ordner(ordner, [ablage], cache_get=lambda p: None) == []


# --- b) Namensvetter ---------------------------------------------------------------

def test_namensvetter_mit_jahresanpassung_vorhandener_elternordner(tmp_path, ablage):
    ordner = _ordner(tmp_path, "Scan 2025", "Versicherungen")  # Jahr 2025 aus dem Pfad
    _datei(ordner / "a.pdf")
    liste = ov.vorschlaege_fuer_ordner(ordner, [ablage])
    pfade = [s.folder_path for s in liste]
    assert pfade[0] == ablage / "Steuer 2025"  # "Steuer 2024/Versicherungen" -> "Steuer 2025"
    assert ablage / "Steuer 2024" in pfade  # der Namensvetter selbst bleibt zweite Wahl
    assert liste[0].confidence > liste[1].confidence
    assert "2025" in liste[0].reason


def test_namensvetter_existiert_im_neuen_jahr_schon(tmp_path, ablage):
    _ordner(ablage, "Steuer 2025", "Versicherungen")
    ordner = _ordner(tmp_path, "Scan 2025", "Versicherungen")
    liste = ov.vorschlaege_fuer_ordner(ordner, [ablage])
    assert liste[0].folder_path == ablage / "Steuer 2025"
    assert "existiert" in liste[0].reason


def test_namensvetter_neues_jahr_ohne_elternordner_wird_neuer_ordner(tmp_path):
    root = _ordner(tmp_path, "Ablage")
    _ordner(root, "Steuer 2024", "Versicherungen")
    ordner = _ordner(tmp_path, "Scan 2026", "Versicherungen")
    liste = ov.vorschlaege_fuer_ordner(ordner, [root])
    neu = [s for s in liste if s.new_source]
    assert len(neu) == 1 and neu[0].folder_path == root / "Steuer 2026"
    assert not neu[0].folder_path.exists()
    assert liste[0] is neu[0]


def test_namensvetter_ohne_jahr_schlaegt_den_eltern_vor(tmp_path):
    root = _ordner(tmp_path, "Ablage")
    _ordner(root, "Privat", "Garten")
    ordner = _ordner(tmp_path, "Eingang", "garten")  # Gross/Klein egal
    liste = ov.vorschlaege_fuer_ordner(ordner, [root])
    assert [s.folder_path for s in liste] == [root / "Privat"]
    assert "Gleichnamiger" in liste[0].reason


def test_inhalt_und_namensvetter_bestaetigen_sich(tmp_path):
    root = _ordner(tmp_path, "Ablage")
    _ordner(root, "Privat", "Garten")
    ordner = _ordner(tmp_path, "Eingang", "Garten")
    _datei(ordner / "a.pdf")
    nur_b = ov.vorschlaege_fuer_ordner(ordner, [root], cache_get=lambda p: None)
    beide = ov.vorschlaege_fuer_ordner(
        ordner, [root], cache_get=_ki_cache({"a.pdf": "Ablage/Privat/Garten"})
    )
    assert len(beide) == 1 and beide[0].confidence > nur_b[0].confidence
    assert "Inhalt" in beide[0].reason and "Gleichnamiger" in beide[0].reason


def test_ziel_jahr_quellen(tmp_path):
    ordner = _ordner(tmp_path, "Eingang", "X")
    a = _datei(ordner / "a.pdf")
    # 1. Pfad
    assert ov.ziel_jahr(_ordner(tmp_path, "Jahr 2023", "X"), [], None) == 2023
    # 2. Datum aus dem Cache
    cache = lambda p: SimpleNamespace(dates=["2024-05-01"])
    assert ov.ziel_jahr(ordner, [a], cache) == 2024
    # 3. Dateidatum
    import os
    os.utime(a, (1_600_000_000, 1_600_000_000))  # 2020
    assert ov.ziel_jahr(ordner, [a], lambda p: None) == 2020


# --- c) KI ---------------------------------------------------------------------------

class FakeProvider:
    def __init__(self, antwort):
        self.antwort = antwort
        self.gefragt = []

    def answer_with_context(self, system_prompt, context_docs, user_question, max_tokens=1000):
        self.gefragt.append(user_question)
        return self.antwort


def test_ki_prompt_enthaelt_name_inhalt_und_ordnerliste(tmp_path, ablage):
    ordner = _ordner(tmp_path, "Eingang", "Versicherungen")
    _datei(ordner / "Police.pdf")
    cache = lambda p: SimpleNamespace(llm_suggestions=[
        LLMSuggestion(filename="x", metadata={"korrespondent": "Allianz", "steuerjahr": "UNBEKANNT"})])
    prompt = ov.ki_prompt(ordner, [ablage], cache)
    assert "ORDNERNAME: Versicherungen" in prompt
    assert "Police.pdf (Allianz)" in prompt
    assert "VORHANDENE ORDNER DES NUTZERS" in prompt and "Ablage/Steuer 2025" in prompt


def test_ki_zielordner_vorhanden(tmp_path, ablage):
    ordner = _ordner(tmp_path, "Eingang", "Versicherungen")
    p = FakeProvider('Hier: {"zielordner": "Ablage/Steuer 2025", "begruendung": "Passt zum Jahr"}')
    s = ov.ki_zielordner(p, ordner, [ablage])
    assert s.folder_path == ablage / "Steuer 2025" and not s.new_source
    assert "Passt zum Jahr" in s.reason
    assert p.gefragt and "Versicherungen" in p.gefragt[0]


def test_ki_zielordner_neu_nur_unter_einem_zielordner(tmp_path, ablage):
    ordner = _ordner(tmp_path, "Eingang", "Versicherungen")
    s = ov.ki_zielordner(FakeProvider('{"zielordner": "Ablage/Steuer 2026"}'), ordner, [ablage])
    assert s.new_source == "ki" and s.folder_path == ablage / "Steuer 2026"
    assert ov.ki_zielordner(FakeProvider('{"zielordner": "../../Windows"}'), ordner, [ablage]) is None


@pytest.mark.parametrize("antwort", [
    '{"zielordner": "UNBEKANNT"}', "kein json", '{"zielordner": ""}',
    '{"zielordner": "Ablage/Steuer 2025/Versicherungen/Unter"}' ,
])
def test_ki_zielordner_unbrauchbare_antworten(tmp_path, ablage, antwort):
    ordner = _ordner(ablage, "Steuer 2025", "Versicherungen")  # Unterordner des Ordners faellt weg
    _ordner(ordner, "Unter")
    assert ov.ki_zielordner(FakeProvider(antwort), ordner, [ablage]) is None


def test_ki_zielordner_aktueller_eltern_wird_verworfen(tmp_path, ablage):
    ordner = _ordner(ablage, "Steuer 2025", "Versicherungen")
    assert ov.ki_zielordner(FakeProvider('{"zielordner": "Ablage/Steuer 2025"}'), ordner, [ablage]) is None


def test_ki_fehler_werden_zur_runtimeerror(tmp_path, ablage):
    ordner = _ordner(tmp_path, "Eingang", "V")
    with pytest.raises(RuntimeError, match="Claude-Fehler"):
        ov.ki_zielordner(FakeProvider("[Claude-Fehler: Zeitüberschreitung]"), ordner, [ablage])
    with pytest.raises(RuntimeError):
        ov.ki_zielordner(FakeProvider(""), ordner, [ablage])

"""Issue #116: Vorschlaege fuer neue Ordner (Jahresregel, KI-Pfade, Prompt, Anlegen/Wegraeumen).

Reine Logik ohne GUI, ohne Netz; alle Ordner liegen unter tmp_path.
"""
from pathlib import Path

import pytest

from src.core import neuer_ordner
from src.ml.classifier import PDFClassifier, Suggestion


@pytest.fixture(autouse=True)
def _liste_vergessen():
    neuer_ordner.invalidieren()
    yield
    neuer_ordner.invalidieren()


def _tree(root: Path, *folders) -> Path:
    root.mkdir(exist_ok=True)
    for f in folders:
        (root / f).mkdir(parents=True, exist_ok=True)
    return root


def _s(path: Path, rel: str, conf: float = 0.7, new_source: str = "") -> Suggestion:
    return Suggestion(path, path.name, conf, "gelernt", relative_path=rel, new_source=new_source)


# --- _year_variant ---------------------------------------------------------------

def test_year_variant_must_exist_false_liefert_fehlenden_ordner(tmp_path):
    root = _tree(tmp_path / "Ablage", "Steuer 2025/Medikamente")
    folder = root / "Steuer 2025" / "Medikamente"
    assert PDFClassifier._year_variant(folder, "Ablage/Steuer 2025/Medikamente", 2028) is None
    assert PDFClassifier._year_variant(
        folder, "Ablage/Steuer 2025/Medikamente", 2028, must_exist=False
    ) == (root / "Steuer 2028" / "Medikamente", "Ablage/Steuer 2028/Medikamente")


# --- Jahresregel (A) -------------------------------------------------------------

def test_jahresregel_fehlender_ordner_wird_neu_mit_unterstruktur(tmp_path):
    root = _tree(tmp_path / "Ablage", "Steuer 2025/Medikamente")
    best = _s(root / "Steuer 2025" / "Medikamente", "Ablage/Steuer 2025/Medikamente", 0.8)

    neu = neuer_ordner.jahres_neuer_ordner([best], 2027, [root])

    assert neu.folder_path == root / "Steuer 2027" / "Medikamente"
    assert neu.relative_path == "Ablage/Steuer 2027/Medikamente"
    assert neu.new_source == neuer_ordner.QUELLE_JAHR and neuer_ordner.ist_neu(neu)
    assert neu.confidence == 0.8 and "2027" in neu.reason
    assert not neu.folder_path.exists()  # nur Vorschlag, nichts angelegt


def test_jahresregel_existierender_ordner_bleibt_wie_bisher(tmp_path):
    """Gibt es den Jahresordner, liefert die alte Variante (#30) ihn - kein neuer Ordner."""
    root = _tree(tmp_path / "Ablage", "Steuer 2025/Medikamente", "Steuer 2026/Medikamente")
    learned = root / "Steuer 2025" / "Medikamente"
    assert neuer_ordner.jahres_neuer_ordner(
        [_s(learned, "Ablage/Steuer 2025/Medikamente")], 2026, [root]
    ) is None

    c = PDFClassifier.__new__(PDFClassifier)
    c.suggest = lambda text, keywords=None, max_suggestions=5: [Suggestion(learned, "Medikamente", 0.8, "g")]
    out = c.suggest_with_subfolders("t", None, detected_date="2026-03-01", root_folders=[root])
    assert [s.relative_path for s in out][:2] == ["Ablage/Steuer 2026/Medikamente", "Ablage/Steuer 2025/Medikamente"]
    assert not any(neuer_ordner.ist_neu(s) for s in out)


def test_jahresregel_ohne_jahr_oder_gleiches_jahr_oder_ohne_jahreszahl(tmp_path):
    root = _tree(tmp_path / "Ablage", "Steuer 2025", "Banken")
    s_jahr = _s(root / "Steuer 2025", "Ablage/Steuer 2025")
    s_ohne = _s(root / "Banken", "Ablage/Banken")
    assert neuer_ordner.jahres_neuer_ordner([s_jahr], None, [root]) is None
    assert neuer_ordner.jahres_neuer_ordner([s_jahr], 2025, [root]) is None
    assert neuer_ordner.jahres_neuer_ordner([s_ohne], 2027, [root]) is None
    # Der erste Vorschlag ohne Jahreszahl wird uebersprungen, der mit Jahr zaehlt
    neu = neuer_ordner.jahres_neuer_ordner([s_ohne, s_jahr], 2027, [root])
    assert neu.relative_path == "Ablage/Steuer 2027"


def test_dokument_jahr_steuerjahr_vor_datum():
    assert neuer_ordner.dokument_jahr("2026-01-10", {"steuerjahr": "2025"}) == 2025
    assert neuer_ordner.dokument_jahr("2026-01-10", {}) == 2026
    assert neuer_ordner.dokument_jahr(None, None) is None


# --- KI-Pfade (B) ----------------------------------------------------------------

def test_ki_pfad_gueltig_unter_zielordner(tmp_path):
    root = _tree(tmp_path / "Ablage", "Nebenkosten 2025/Wohnung xy/Energierechnung")
    neu = neuer_ordner.ki_neuer_ordner(
        {"zielordner": "Ablage/Nebenkosten 2027/Wohnung xy/Energierechnung"}, [root]
    )
    assert neu.folder_path == root / "Nebenkosten 2027" / "Wohnung xy" / "Energierechnung"
    assert neu.relative_path == "Ablage/Nebenkosten 2027/Wohnung xy/Energierechnung"
    assert neu.new_source == neuer_ordner.QUELLE_KI


def test_ki_pfad_ohne_zielordnernamen_nur_bei_einem_zielordner(tmp_path):
    a = _tree(tmp_path / "A")
    b = _tree(tmp_path / "B")
    assert neuer_ordner.neuer_pfad_unter_zielordner("Klaviernoten", [a]) == a / "Klaviernoten"
    assert neuer_ordner.neuer_pfad_unter_zielordner("Klaviernoten", [a, b]) is None
    assert neuer_ordner.neuer_pfad_unter_zielordner("B/Klaviernoten", [a, b]) == b / "Klaviernoten"


@pytest.mark.parametrize("rel", [
    "../Ausserhalb",
    "Ablage/../../Ausserhalb",
    "Ablage/./Steuer",
    "/etc/Steuer",
    "C:/Steuer 2027",
    "C:\\Windows\\Steuer",
    "\\\\server\\share\\Steuer",
    "file://x/Steuer",
    "Ablage/CON",
    "Ablage/nul.txt",
    "Ablage",           # nur der Zielordner selbst
    "Ablage/<>|?*",      # besteht nur aus verbotenen Zeichen
    "",
])
def test_ki_pfad_wird_abgelehnt(tmp_path, rel):
    root = _tree(tmp_path / "Ablage")
    assert neuer_ordner.neuer_pfad_unter_zielordner(rel, [root]) is None
    assert neuer_ordner.ki_neuer_ordner({"zielordner": rel}, [root]) is None


def test_ki_pfad_ausserhalb_der_zielordner_verworfen(tmp_path):
    root = _tree(tmp_path / "Ablage")
    _tree(tmp_path / "Fremd")
    # "Fremd" ist kein Zielordner; bei mehreren Zielordnern unbekannt -> verworfen
    other = _tree(tmp_path / "Zweite")
    assert neuer_ordner.ki_neuer_ordner({"zielordner": "Fremd/Neu"}, [root, other]) is None


def test_ki_pfad_ungueltige_zeichen_werden_bereinigt(tmp_path):
    root = _tree(tmp_path / "Ablage")
    path = neuer_ordner.neuer_pfad_unter_zielordner('Ablage\\Steuer: 2027/Arzt?  Rechnungen. ', [root])
    assert path == root / "Steuer 2027" / "Arzt Rechnungen"


def test_ki_pfad_trifft_datei_wird_verworfen(tmp_path):
    root = _tree(tmp_path / "Ablage")
    (root / "notiz").write_text("x")
    assert neuer_ordner.neuer_pfad_unter_zielordner("Ablage/notiz/Neu", [root]) is None


def test_ki_treffer_auf_bestehenden_pfad_ist_kein_neuer_ordner(tmp_path):
    from src.core.similar_documents import folder_suggestion_from_metadata
    root = _tree(tmp_path / "Ablage", "Steuer 2027/Medikamente")
    meta = {"zielordner": "Ablage/Steuer 2027/Medikamente"}
    assert neuer_ordner.ki_neuer_ordner(meta, [root]) is None
    bestehend = folder_suggestion_from_metadata(meta, [root], 2027)
    assert bestehend.folder_path == root / "Steuer 2027" / "Medikamente"
    assert not neuer_ordner.ist_neu(bestehend)
    # auch ohne den Namen des Zielordners
    assert neuer_ordner.ki_neuer_ordner({"zielordner": "Steuer 2027/Medikamente"}, [root]) is None


def test_ki_ohne_zielordner_oder_metadaten(tmp_path):
    root = _tree(tmp_path / "Ablage")
    assert neuer_ordner.ki_neuer_ordner(None, [root]) is None
    assert neuer_ordner.ki_neuer_ordner({}, [root]) is None


# --- hoechstens einer, Prioritaet ------------------------------------------------

def test_hoechstens_ein_neuer_vorne_jahresregel_vor_ki(tmp_path):
    root = _tree(tmp_path / "Ablage", "Banken")
    bestehend = _s(root / "Banken", "Ablage/Banken", 0.9)
    ki = _s(root / "KI-Neu", "Ablage/KI-Neu", 0.8, new_source=neuer_ordner.QUELLE_KI)
    jahr = _s(root / "Steuer 2027", "Ablage/Steuer 2027", 0.5, new_source=neuer_ordner.QUELLE_JAHR)

    out = neuer_ordner.hoechstens_einer_vorne([bestehend, ki, jahr])

    assert out == [jahr, bestehend]
    assert neuer_ordner.hoechstens_einer_vorne([bestehend, ki]) == [ki, bestehend]
    assert neuer_ordner.hoechstens_einer_vorne([bestehend]) == [bestehend]


# --- Prompt ----------------------------------------------------------------------

def test_ordnerliste_relative_pfade_und_begrenzung(tmp_path):
    root = _tree(tmp_path / "Ablage", "Steuer 2025/Medikamente", ".versteckt", "Banken")
    text = neuer_ordner.ordnerliste_fuer_prompt([root])
    assert neuer_ordner.ORDNERLISTE_KOPF in text
    for rel in ("- Ablage", "- Ablage/Banken", "- Ablage/Steuer 2025", "- Ablage/Steuer 2025/Medikamente"):
        assert rel in text.splitlines()
    assert "versteckt" not in text
    assert "NEUEN Ordner" in text

    neuer_ordner.invalidieren()
    viele = _tree(tmp_path / "Viele", *(f"Ordner {i:03d}" for i in range(300)))
    text = neuer_ordner.ordnerliste_fuer_prompt([viele], max_zeichen=500)
    assert len(text) < 1500 and "gekürzt" in text
    assert len(neuer_ordner.ordner_relativ([viele])) == neuer_ordner.PROMPT_MAX_ORDNER


def test_ordnerliste_flache_ebenen_zuerst(tmp_path):
    root = _tree(tmp_path / "R", "a/b/c/d/e/f")
    pfade = neuer_ordner.ordner_relativ([root], max_tiefe=2)
    assert pfade == ["R", "R/a", "R/a/b"]


def test_prompt_feld_zielordner_erlaubt_neuen_pfad_nur_mit_ordnerliste(tmp_path):
    from src.ml.llm_provider import LLMProvider, LLMConfig

    class _Fake(LLMProvider):
        def _initialize_client(self): pass
        def classify_document(self, *a, **k): pass
        def suggest_filename(self, *a, **k): pass
        def is_available(self): return True
        def answer_with_context(self, *a, **k): return ""

    p = _Fake(LLMConfig(api_key="", model="x"))
    root = _tree(tmp_path / "Ablage", "Steuer 2025")
    ohne = p._build_filename_prompt("Text", "scan.pdf", similar_info="\nÄHNLICHE DOKUMENTE ...")
    mit = p._build_filename_prompt(
        "Text", "scan.pdf", similar_info=neuer_ordner.ordnerliste_fuer_prompt([root])
    )
    assert '"zielordner": "Ablageort wie in den Beispielen' in ohne
    assert "neuer Pfad, der mit einem Zielordner beginnt" in mit
    assert "- Ablage/Steuer 2025" in mit
    assert '"zielordner"' not in p._build_filename_prompt("Text", "scan.pdf")


def test_hybrid_haengt_ordnerliste_nur_bei_eingeschaltetem_schalter_an(tmp_path, monkeypatch, fresh_config):
    from src.ml import hybrid_classifier as hc
    root = _tree(tmp_path / "Ablage", "Steuer 2025")
    fresh_config.add_target_folder(root)
    monkeypatch.setattr(hc, "get_database", lambda: type("Db", (), {
        "get_history_brief": lambda self, limit=0: [],
        "get_indexed_documents_brief": lambda self, limit=0: [],
    })())
    c = hc.HybridClassifier.__new__(hc.HybridClassifier)

    assert neuer_ordner.ORDNERLISTE_KOPF in c._similar_documents_info("t", [], None, None)
    fresh_config.set("suggest_new_folders", False, auto_save=False)
    assert c._similar_documents_info("t", [], None, None) == ""


# --- Anlegen und Wegraeumen ------------------------------------------------------

def test_anlegen_und_nur_leere_neue_wegraeumen(tmp_path):
    root = _tree(tmp_path / "Ablage", "Steuer 2025")
    ziel = root / "Steuer 2027" / "Medikamente"

    angelegt = neuer_ordner.anlegen(ziel)

    assert angelegt == [root / "Steuer 2027", ziel] and ziel.is_dir()
    (ziel / "x.pdf").write_bytes(b"%PDF")
    assert neuer_ordner.leere_wegraeumen(angelegt) == 0  # nicht leer -> bleibt
    (ziel / "x.pdf").unlink()
    assert neuer_ordner.leere_wegraeumen(angelegt) == 2
    assert not (root / "Steuer 2027").exists()
    assert (root / "Steuer 2025").is_dir() and root.is_dir()

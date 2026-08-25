"""Issue #30: Jahres-Variante der Ordnervorschlaege ("Steuer 2025" -> "Steuer 2026")."""
from datetime import datetime

from src.ml.classifier import PDFClassifier, Suggestion


def _bare_classifier(base):
    """PDFClassifier ohne __init__ (kein DB/Config-Zugriff); suggest() gestubbt."""
    c = PDFClassifier.__new__(PDFClassifier)
    c.suggest = lambda text, keywords=None, max_suggestions=5: list(base)
    return c


def _tree(tmp_path, *folders):
    for f in folders:
        (tmp_path / f).mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_year_variant_returns_existing_folder(tmp_path):
    root = _tree(tmp_path, "Steuer 2025/Medikamente", "Steuer 2026/Medikamente")
    out = PDFClassifier._year_variant(
        root / "Steuer 2025" / "Medikamente", "Steuer 2025/Medikamente", 2026
    )
    assert out == (root / "Steuer 2026" / "Medikamente", "Steuer 2026/Medikamente")


def test_year_variant_none_when_folder_missing(tmp_path):
    root = _tree(tmp_path, "Steuer 2025/Medikamente")
    assert PDFClassifier._year_variant(
        root / "Steuer 2025" / "Medikamente", "Steuer 2025/Medikamente", 2026
    ) is None


def test_year_variant_none_without_year_or_same_year(tmp_path):
    root = _tree(tmp_path, "Banken", "Briefe 2026")
    assert PDFClassifier._year_variant(root / "Banken", "Banken", 2026) is None
    assert PDFClassifier._year_variant(root / "Briefe 2026", "Briefe 2026", 2026) is None


def test_year_variant_ignores_numbers_that_are_not_years(tmp_path):
    root = _tree(tmp_path, "Kunde 20250/Belege")
    assert PDFClassifier._year_variant(
        root / "Kunde 20250" / "Belege", "Kunde 20250/Belege", 2026
    ) is None


def test_detected_year_puts_variant_first(tmp_path):
    root = _tree(tmp_path, "Steuer 2025/Medikamente", "Steuer 2026/Medikamente")
    learned = root / "Steuer 2025" / "Medikamente"
    c = _bare_classifier([Suggestion(learned, "Medikamente", 0.8, "gelernt")])

    out = c.suggest_with_subfolders("text", None, detected_date="2026-03-14", root_folders=[root])

    assert [s.relative_path for s in out][:2] == [
        f"{root.name}/Steuer 2026/Medikamente",
        f"{root.name}/Steuer 2025/Medikamente",
    ]
    assert out[0].confidence > out[1].confidence
    assert "2026" in out[0].reason


def test_without_detected_year_variant_comes_after_original(tmp_path):
    year = datetime.now().year
    root = _tree(tmp_path, "Briefe 2019", f"Briefe {year}")
    c = _bare_classifier([Suggestion(root / "Briefe 2019", "Briefe 2019", 0.6, "gelernt")])

    out = c.suggest_with_subfolders("text", None, detected_date=None, root_folders=[root])

    assert [s.folder_name for s in out] == ["Briefe 2019", f"Briefe {year}"]
    assert out[1].confidence < out[0].confidence


def test_variant_not_duplicated_when_already_suggested(tmp_path):
    root = _tree(tmp_path, "Steuer 2025", "Steuer 2026")
    c = _bare_classifier([
        Suggestion(root / "Steuer 2025", "Steuer 2025", 0.7, "gelernt"),
        Suggestion(root / "Steuer 2026", "Steuer 2026", 0.5, "gelernt"),
    ])
    out = c.suggest_with_subfolders("text", None, detected_date="2026-01-05", root_folders=[root])
    assert [s.folder_name for s in out] == ["Steuer 2026", "Steuer 2025"]


def test_max_suggestions_respected(tmp_path):
    root = _tree(tmp_path, "Ordner 2024", "Ordner 2025", "Ordner 2026", "Sonstiges")
    c = _bare_classifier([
        Suggestion(root / "Ordner 2024", "Ordner 2024", 0.9, "a"),
        Suggestion(root / "Ordner 2025", "Ordner 2025", 0.8, "b"),
        Suggestion(root / "Sonstiges", "Sonstiges", 0.1, "c"),
    ])
    out = c.suggest_with_subfolders(
        "t", None, detected_date="2026-06-01", root_folders=[root], max_suggestions=3
    )
    assert len(out) == 3
    assert out[0].folder_name == "Ordner 2026"

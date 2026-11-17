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


def test_bezugsjahr_im_text_schlaegt_briefdatum(tmp_path):
    """Issue #254: Bescheid "fuer 2020", Brief von 2022 -> "Steuer 2020" steht oben."""
    root = _tree(tmp_path, "Steuer 2020", "Steuer 2022", "Steuer 2023")
    c = _bare_classifier([
        Suggestion(root / "Steuer 2022", "Steuer 2022", 0.8, "gelernt"),
        Suggestion(root / "Steuer 2023", "Steuer 2023", 0.7, "gelernt"),
    ])
    text = "Finanzamt Musterstadt\nBescheid für 2020 über Einkommensteuer\nMusterstadt, 14.03.2022"

    out = c.suggest_with_subfolders(text, None, detected_date="2022-03-14", root_folders=[root])

    assert out[0].relative_path == f"{root.name}/Steuer 2020"
    assert out[0].confidence == max(s.confidence for s in out)
    assert f"{root.name}/Steuer 2022" in [s.relative_path for s in out]  # Gelerntes bleibt


def test_ordner_mit_fernem_jahr_faellt_weg(tmp_path):
    """Issue #308: Bescheid fuer 2020 -> "Steuer 2010" (aehnlicher alter Bescheid) nicht anbieten."""
    root = _tree(tmp_path, "Steuer 2010", "Steuer 2020")
    c = _bare_classifier([Suggestion(root / "Steuer 2010", "Steuer 2010", 0.56, "Ähnlicher Inhalt")])
    text = "Finanzamt Musterstadt\nBescheid für 2020 über Einkommensteuer\nMusterstadt, 14.03.2022"

    out = c.suggest_with_subfolders(text, None, detected_date="2022-03-14", root_folders=[root])

    assert [s.folder_name for s in out] == ["Steuer 2020"]


def test_ordner_mit_fernem_jahr_faellt_auch_ohne_variante_weg(tmp_path):
    root = _tree(tmp_path, "Steuer 2010")
    c = _bare_classifier([
        Suggestion(root / "Steuer 2010", "Steuer 2010", 0.56, "Ähnlicher Inhalt"),
        Suggestion(root / "Banken", "Banken", 0.3, "gelernt"),
    ])
    text = "Bescheid für 2020 über Einkommensteuer"

    out = c.suggest_with_subfolders(text, None, detected_date="2022-03-14", root_folders=[root])

    assert [s.folder_name for s in out] == ["Banken"]


def test_nachbarjahr_des_bezugsjahrs_bleibt(tmp_path):
    """Die erste Jahresnennung kann eine Vorauszahlung sein: +/- 1 Jahr bleibt Vorschlag."""
    root = _tree(tmp_path, "Steuer 2019", "Steuer 2020")
    c = _bare_classifier([Suggestion(root / "Steuer 2019", "Steuer 2019", 0.6, "gelernt")])

    out = c.suggest_with_subfolders(
        "Bescheid für 2020", None, detected_date="2020-12-01", root_folders=[root])

    assert [s.folder_name for s in out] == ["Steuer 2020", "Steuer 2019"]


def test_lohnsteuerbescheinigung_im_januar_bleibt(tmp_path):
    """Nur Briefdatum 2026: "Steuer 2025" bleibt (Issue #30), "Steuer 2015" faellt weg."""
    root = _tree(tmp_path, "Steuer 2015", "Steuer 2025", "Steuer 2026")
    c = _bare_classifier([
        Suggestion(root / "Steuer 2025", "Steuer 2025", 0.7, "gelernt"),
        Suggestion(root / "Steuer 2015", "Steuer 2015", 0.6, "gelernt"),
    ])

    out = c.suggest_with_subfolders("Bescheinigung", None, detected_date="2026-01-10", root_folders=[root])

    assert [s.folder_name for s in out] == ["Steuer 2026", "Steuer 2025"]


def test_jahr_im_zielordner_selbst_zaehlt_nicht(tmp_path):
    root = _tree(tmp_path / "Archiv 2015", "Banken")
    c = _bare_classifier([Suggestion(root / "Banken", "Banken", 0.6, "gelernt")])

    out = c.suggest_with_subfolders("Kontoauszug", None, detected_date="2026-03-01", root_folders=[root])

    assert [s.folder_name for s in out] == ["Banken"]


def test_ohne_erkanntes_jahr_bleibt_alter_ordner(tmp_path):
    root = _tree(tmp_path, "Steuer 2010")
    c = _bare_classifier([Suggestion(root / "Steuer 2010", "Steuer 2010", 0.56, "gelernt")])

    out = c.suggest_with_subfolders("ohne Jahr", None, detected_date=None, root_folders=[root])

    assert [s.folder_name for s in out] == ["Steuer 2010"]


def test_ohne_bezugsjahr_bleibt_das_briefdatum(tmp_path):
    root = _tree(tmp_path, "Steuer 2020", "Steuer 2022")
    c = _bare_classifier([Suggestion(root / "Steuer 2022", "Steuer 2022", 0.8, "gelernt")])

    out = c.suggest_with_subfolders(
        "Rechnung Nr. 2020 vom 14.03.2022", None, detected_date="2022-03-14", root_folders=[root])

    assert [s.folder_name for s in out] == ["Steuer 2022"]

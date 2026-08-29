"""Fremde dc:description, die nur ein Dateiname ist, gilt nicht als Zusammenfassung."""
import pytest

pikepdf = pytest.importorskip("pikepdf")


def _pdf_with_description(tmp_path, description):
    path = tmp_path / "huk.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    with pdf.open_metadata() as meta:
        meta["dc:title"] = "Schriftwechsel_HUK"
        meta["dc:description"] = description
    pdf.save(path)
    return path


def test_filename_like_description_is_ignored(tmp_path):
    from src.core.pdf_metadata import read_metadata

    meta = read_metadata(_pdf_with_description(tmp_path, "2024-01-31_Schriftwechsel_HUK_23-13.pdf"))
    assert meta is not None
    assert meta.description is None


def test_real_summary_is_kept(tmp_path):
    from src.core.pdf_metadata import read_metadata

    meta = read_metadata(_pdf_with_description(tmp_path, "Leistungsabrechnung der HUK vom 31.01.2024."))
    assert meta.description == "Leistungsabrechnung der HUK vom 31.01.2024."


@pytest.mark.parametrize("value,expected", [
    ("2024-01-31_Schriftwechsel_HUK_23-13.pdf", True),
    ("Brief.PDF", True),
    ("Rechnung von HUK.pdf", False),   # Leerzeichen -> Satz, kein reiner Dateiname
    ("Zusammenfassung ohne Endung", False),
    ("", False),
    (None, False),
])
def test_looks_like_filename(value, expected):
    from src.core.pdf_metadata import looks_like_filename
    assert looks_like_filename(value) is expected

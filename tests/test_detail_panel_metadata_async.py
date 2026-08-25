"""DetailPanel liest XMP-Metadaten im Hintergrund und traegt sie nach."""
from pathlib import Path


def test_metadata_applied_after_background_read(qtbot, tmp_path, monkeypatch):
    from src.gui import detail_panel as dp
    from src.core.pdf_metadata import PDFMetadata

    meta = PDFMetadata(); meta.korrespondent = "Stadtwerke"; meta.steuerjahr = "2026"
    monkeypatch.setattr("src.core.pdf_metadata.read_metadata", lambda p: meta)

    panel = dp.DetailPanel(); qtbot.addWidget(panel)
    pdf = tmp_path / "a.pdf"; pdf.write_bytes(b"%PDF")
    panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="x", keywords=["rechnung"])
    assert panel._current_pdf == pdf
    qtbot.waitUntil(lambda: panel._metadata_source == "pdf", timeout=5000)
    assert panel.get_metadata().get("korrespondent") == "Stadtwerke"


def test_stale_result_for_other_pdf_is_ignored(qtbot, tmp_path):
    from src.gui import detail_panel as dp
    from src.core.pdf_metadata import PDFMetadata

    panel = dp.DetailPanel(); qtbot.addWidget(panel)
    a = tmp_path / "a.pdf"; a.write_bytes(b"%PDF")
    panel._current_pdf = tmp_path / "b.pdf"
    meta = PDFMetadata(); meta.korrespondent = "Alt"
    panel._on_pdf_metadata_read(a, meta)  # gehoert zu a, ausgewaehlt ist b
    assert panel.get_metadata().get("korrespondent") in (None, "")

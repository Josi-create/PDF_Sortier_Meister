"""'Quelle: aus PDF gelesen' nur, wenn wirklich alle Felder aus dem PDF stammen."""


def test_partial_pdf_metadata_is_not_marked_saved(qtbot, tmp_path, monkeypatch):
    from src.gui import detail_panel as dp
    from src.core.pdf_metadata import PDFMetadata

    # PDF liefert nur eine Zusammenfassung; Kategorie/Steuerjahr kommen aus der Analyse
    meta = PDFMetadata(); meta.description = "Leistungsabrechnung der HUK."
    monkeypatch.setattr("src.core.pdf_metadata.read_metadata", lambda p: meta)

    panel = dp.DetailPanel(); qtbot.addWidget(panel)
    pdf = tmp_path / "a.pdf"; pdf.write_bytes(b"%PDF")
    panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="x",
                  keywords=["rechnung"], detected_date="2024-01-31")
    qtbot.waitUntil(lambda: panel._metadata_source in ("pdf", "pdf_partial"), timeout=5000)

    assert panel._metadata_source == "pdf_partial"
    assert panel.get_metadata()["subject"] == "Rechnung"
    assert panel._saved_metadata_snapshot == {"description": "Leistungsabrechnung der HUK."}
    assert panel.save_metadata_btn.isEnabled()
    assert panel.save_metadata_btn.text() == "Metadaten speichern"
    assert "teils" in panel.metadata_status_label.text()


def test_full_pdf_metadata_is_marked_saved(qtbot, tmp_path, monkeypatch):
    from src.gui import detail_panel as dp
    from src.core.pdf_metadata import PDFMetadata

    meta = PDFMetadata(); meta.subject = "Rechnung"; meta.steuerjahr = "2024"
    monkeypatch.setattr("src.core.pdf_metadata.read_metadata", lambda p: meta)

    panel = dp.DetailPanel(); qtbot.addWidget(panel)
    pdf = tmp_path / "a.pdf"; pdf.write_bytes(b"%PDF")
    panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="x",
                  keywords=["rechnung"], detected_date="2024-05-01")
    qtbot.waitUntil(lambda: panel._metadata_source == "pdf", timeout=5000)

    assert not panel.save_metadata_btn.isEnabled()
    assert panel.save_metadata_btn.text() == "Metadaten gespeichert"
    assert panel.metadata_status_label.text() == "Quelle: aus PDF gelesen"

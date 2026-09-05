"""Issue #132: Feld "Datum" im Detail-Panel.

Das Datum ist die eine Quelle fuer {datum} in den Mustern, belegt das
Steuerjahr vor und laesst sich aus der Vorschau uebernehmen oder tippen.
"""
from PyQt6.QtWidgets import QLineEdit

from src.gui.rename_dialog import RenameSuggestion

MUSTER = "{datum}_{kategorie}_{kontakt}"


def _panel(qtbot, monkeypatch, tmp_path, pdf_meta=None, **config_values):
    """Panel mit eigener Config/DB. ``pdf_meta``: PDFMetadata, die der
    XMP-Reader (echter Thread, wie in der App nach set_pdf) liefern soll."""
    from src.utils import config as cfg_mod
    from src.utils.config import Config
    cfg = Config.__new__(Config)
    cfg.config_path = tmp_path / "config.json"
    cfg._config = {}
    cfg.load()
    for key, value in config_values.items():
        cfg.set(key, value, auto_save=False)
    monkeypatch.setattr(cfg_mod, "get_config", lambda: cfg)
    from src.utils.database import Database
    db = Database(db_path=tmp_path / "panel.db")
    monkeypatch.setattr("src.utils.database.get_database", lambda: db)
    cfg._db = db

    from src.gui import detail_panel as dp
    monkeypatch.setattr("src.core.pdf_metadata.read_metadata", lambda p: pdf_meta)
    if pdf_meta is None:
        # Kein Hintergrund-Thread noetig: synchron ohne Ergebnis
        monkeypatch.setattr(dp._PdfMetadataReader, "start", lambda self: self.run())
    monkeypatch.setattr(dp.PdfPreviewWidget, "load_pdf", lambda self, path: None)
    panel = dp.DetailPanel()
    qtbot.addWidget(panel)
    return panel


def _show(panel, tmp_path, suggestions=None, detected_date="2004-03-12"):
    pdf = tmp_path / "brief.pdf"
    pdf.write_bytes(b"%PDF")
    panel.set_pdf(pdf_path=pdf, suggestions=suggestions or [], extracted_text="Brief",
                  keywords=["rechnung"], detected_date=detected_date)
    return pdf


def _rows(panel):
    lst = panel.suggestions_list
    return [lst.item(i).text() for i in range(lst.count())]


def test_datum_feld_wird_aus_analyse_vorbelegt_und_steuerjahr_folgt(qtbot, monkeypatch, tmp_path):
    panel = _panel(qtbot, monkeypatch, tmp_path)
    _show(panel, tmp_path)
    datum = panel._metadata_inputs["buchungsdatum"]
    assert isinstance(datum, QLineEdit)
    assert datum.text() == "2004-03-12"
    assert panel._metadata_inputs["steuerjahr"].text() == "2004"
    assert panel.get_metadata()["buchungsdatum"] == "2004-03-12"
    assert panel.current_date() == "2004-03-12"


def test_ki_datum_schlaegt_analyse_datum(qtbot, monkeypatch, tmp_path):
    panel = _panel(qtbot, monkeypatch, tmp_path)
    ki = RenameSuggestion("2004-03-12_Brief_Finanzamt.pdf", "KI-Vorschlag", 0.9,
                          metadata={"buchungsdatum": "2004-03-12", "subject": "Brief"})
    # Analyse hat das juengere Datum (Frist) erwischt, die KI das Briefdatum
    _show(panel, tmp_path, suggestions=[ki], detected_date="2006-06-30")
    assert panel._metadata_inputs["buchungsdatum"].text() == "2004-03-12"
    assert panel._metadata_inputs["steuerjahr"].text() == "2004"


def test_steuerjahr_folgt_dem_datum_solange_es_nicht_eigenstaendig_ist(qtbot, monkeypatch, tmp_path):
    panel = _panel(qtbot, monkeypatch, tmp_path)
    _show(panel, tmp_path)
    datum = panel._metadata_inputs["buchungsdatum"]
    steuerjahr = panel._metadata_inputs["steuerjahr"]

    datum.setText("2005-01-31")
    assert steuerjahr.text() == "2005"

    # Nutzer setzt das Steuerjahr bewusst anders (Bescheid fuer ein Vorjahr)
    steuerjahr.setText("2003")
    datum.setText("2006-02-02")
    assert steuerjahr.text() == "2003"

    # Leeres Steuerjahr wird wieder gefuellt
    steuerjahr.setText("")
    datum.setText("2007-07-07")
    assert steuerjahr.text() == "2007"


def test_eingabe_in_anderem_format_wird_beim_verlassen_normalisiert(qtbot, monkeypatch, tmp_path):
    panel = _panel(qtbot, monkeypatch, tmp_path)
    _show(panel, tmp_path)
    datum = panel._metadata_inputs["buchungsdatum"]
    datum.setText("12.3.2005")
    # Schon vor dem Verlassen liefert get_metadata ISO
    assert panel.get_metadata()["buchungsdatum"] == "2005-03-12"
    datum.editingFinished.emit()
    assert datum.text() == "2005-03-12"
    assert panel._metadata_inputs["steuerjahr"].text() == "2005"


def test_unlesbares_datum_wird_nicht_gespeichert_und_rot_markiert(qtbot, monkeypatch, tmp_path):
    panel = _panel(qtbot, monkeypatch, tmp_path)
    _show(panel, tmp_path)
    datum = panel._metadata_inputs["buchungsdatum"]
    datum.setText("Rechnung Nr. 12")
    assert "buchungsdatum" not in panel.get_metadata()
    assert panel.current_date() is None
    assert "#d32f2f" in datum.styleSheet()
    assert "Kein Datum erkannt" in datum.toolTip()
    # Steuerjahr bleibt vom letzten lesbaren Datum
    assert panel._metadata_inputs["steuerjahr"].text() == "2004"

    datum.setText("2004-04-04")
    assert "#d32f2f" not in datum.styleSheet()
    assert "Kein Datum erkannt" not in datum.toolTip()


def test_markierter_text_aus_der_vorschau_wird_als_datum_uebernommen(qtbot, monkeypatch, tmp_path):
    panel = _panel(qtbot, monkeypatch, tmp_path)
    _show(panel, tmp_path)
    panel.apply_preview_text("buchungsdatum", "München, den 12. März 2004")
    assert panel._metadata_inputs["buchungsdatum"].text() == "2004-03-12"

    # Kein Datum in der Markierung: Text steht rot im Feld, Eingabe ersetzt ihn
    panel.apply_preview_text("buchungsdatum", "Sehr geehrte Damen")
    datum = panel._metadata_inputs["buchungsdatum"]
    assert datum.text() == "Sehr geehrte Damen"
    assert datum.selectedText() == "Sehr geehrte Damen"
    assert "#d32f2f" in datum.styleSheet()
    assert "buchungsdatum" not in panel.get_metadata()


def test_muster_vorschlag_nimmt_das_datum_aus_dem_feld(qtbot, monkeypatch, tmp_path):
    panel = _panel(qtbot, monkeypatch, tmp_path, filename_pattern=MUSTER)
    _show(panel, tmp_path)
    panel._metadata_inputs["korrespondent"].setText("Finanzamt")
    assert any(row.startswith("2004-03-12_Rechnung_Finanzamt") for row in _rows(panel)), _rows(panel)

    panel._metadata_inputs["buchungsdatum"].setText("1999-12-31")
    rows = _rows(panel)
    assert any(row.startswith("1999-12-31_Rechnung_Finanzamt") for row in rows), rows
    assert not any(row.startswith("2004-03-12_") for row in rows)


def test_pdf_metadaten_ohne_datum_verwerfen_das_analyse_datum(qtbot, monkeypatch, tmp_path):
    """Bereits sortierte PDFs sollen nicht wegen des Analyse-Datums als
    'teilweise gespeichert' erscheinen; {datum} faellt auf die Analyse zurueck."""
    from src.core.pdf_metadata import PDFMetadata
    meta = PDFMetadata(); meta.subject = "Brief"; meta.steuerjahr = "2004"; meta.korrespondent = "Amt"
    panel = _panel(qtbot, monkeypatch, tmp_path, pdf_meta=meta, filename_pattern=MUSTER)
    _show(panel, tmp_path, detected_date="2006-06-30")
    qtbot.waitUntil(lambda: panel._metadata_source == "pdf", timeout=5000)
    assert panel._metadata_inputs["buchungsdatum"].text() == ""
    assert panel._metadata_inputs["steuerjahr"].text() == "2004"
    assert not panel.save_metadata_btn.isEnabled()
    assert any(row.startswith("2006-06-30_Brief_Amt") for row in _rows(panel)), _rows(panel)


def test_gespeichertes_datum_kommt_aus_der_pdf(qtbot, monkeypatch, tmp_path):
    from src.core.pdf_metadata import PDFMetadata
    meta = PDFMetadata(); meta.buchungsdatum = "2004-03-12"; meta.steuerjahr = "2004"; meta.subject = "Brief"
    panel = _panel(qtbot, monkeypatch, tmp_path, pdf_meta=meta)
    _show(panel, tmp_path, detected_date="2006-06-30")
    qtbot.waitUntil(lambda: panel._metadata_source == "pdf", timeout=5000)
    assert panel._metadata_inputs["buchungsdatum"].text() == "2004-03-12"
    assert "buchungsdatum" in panel._saved_metadata_snapshot

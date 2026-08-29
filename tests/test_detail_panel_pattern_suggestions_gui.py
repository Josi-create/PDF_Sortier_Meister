"""Issue #99: Muster-Vorschlaege im Detail-Panel.

Die Vorschlagsliste zeigt zusaetzlich den Dateinamen nach dem Muster aus
Einstellungen > Dateinamen (oder einer anderen Vorlage), gerendert aus den
Metadaten der ausgewaehlten PDF; per Combo laesst sich das Muster umschalten.
"""
from src.gui.rename_dialog import RenameSuggestion

RECHNUNGEN = "{datum}_{kategorie}_{kontakt}_{betreff}"
BUERO = "{initialen} {datum}-{betreff}"


def _panel(qtbot, monkeypatch, tmp_path, **config_values):
    from src.utils import config as cfg_mod
    from src.utils.config import Config
    cfg = Config.__new__(Config)
    cfg.config_path = tmp_path / "config.json"
    cfg._config = {}
    cfg.load()
    for key, value in config_values.items():
        cfg.set(key, value, auto_save=False)
    monkeypatch.setattr(cfg_mod, "get_config", lambda: cfg)

    from src.gui import detail_panel as dp
    # Keine Hintergrund-Threads im Unit-Test (Teardown-Crash): XMP-Lesen
    # synchron ohne Ergebnis, Vorschau gar nicht laden
    monkeypatch.setattr("src.core.pdf_metadata.read_metadata", lambda p: None)
    monkeypatch.setattr(dp._PdfMetadataReader, "start", lambda self: self.run())
    monkeypatch.setattr(dp.PdfPreviewWidget, "load_pdf", lambda self, path: None)
    panel = dp.DetailPanel()
    qtbot.addWidget(panel)
    return panel, cfg


def _ki_suggestion(name="2024-01-31_Rechnung_Testfirma.pdf"):
    return RenameSuggestion(
        name=name, reason="KI-Vorschlag", confidence=0.95,
        metadata={
            "korrespondent": "Testfirma GmbH",
            "subject": "Rechnung",
            "description": "Beratung im Maerz 2024 inkl. Fahrtkosten",
        },
    )


def _rows(panel):
    lst = panel.suggestions_list
    return [lst.item(i).text() for i in range(lst.count())]


def _select(panel, tmp_path, suggestions, detected_date="2024-01-31"):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    panel.set_pdf(pdf_path=pdf, suggestions=suggestions, extracted_text="x",
                  keywords=["rechnung"], detected_date=detected_date)
    return pdf


def test_settings_pattern_becomes_a_suggestion(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path, filename_pattern=RECHNUNGEN)
    _select(panel, tmp_path, [_ki_suggestion(),
                              RenameSuggestion("Dokument.pdf", "Automatisch erkannt", 0.5)])

    rows = _rows(panel)
    assert rows[0].startswith("2024-01-31_Rechnung_Testfirma.pdf")
    assert rows[1] == (
        "2024-01-31_Rechnung_Testfirma-GmbH_Beratung-im-Maerz-2024.pdf  [Muster: Rechnungen & Belege]"
    )
    assert rows[2].startswith("Dokument.pdf")
    # Combo steht auf dem Einstellungs-Muster
    assert panel.pattern_combo.currentData() == RECHNUNGEN
    # Name bleibt der KI-Vorschlag (Muster-Vorschlag draengt sich nicht vor)
    assert panel.name_input.text() == "2024-01-31_Rechnung_Testfirma"
    assert not panel.has_user_edits()


def test_standard_pattern_adds_no_row(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, [_ki_suggestion()])
    assert panel.pattern_combo.currentIndex() == 0
    assert panel.pattern_combo.currentData() == ""
    assert len(_rows(panel)) == 1


def test_no_row_without_any_metadata(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path, filename_pattern="{kontakt}_{betreff}")
    _select(panel, tmp_path, [], detected_date=None)
    assert _rows(panel) == ["Keine Vorschläge verfügbar"]


def test_switching_pattern_updates_row_and_name(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path, filename_pattern=RECHNUNGEN,
                      owner_initials="JW")
    _select(panel, tmp_path, [_ki_suggestion()])

    idx = panel.pattern_combo.findData(BUERO)
    assert idx > 0
    panel.pattern_combo.setCurrentIndex(idx)
    panel.pattern_combo.activated.emit(idx)

    assert _rows(panel)[1] == "JW 2024-01-31-Beratung-im-Maerz-2024.pdf  [Muster: Büro-Kürzel voran]"
    assert panel.name_input.text() == "JW 2024-01-31-Beratung-im-Maerz-2024"

    # Zurueck auf Standard: Zeile weg, Name bleibt wie zuletzt gewaehlt
    panel.pattern_combo.setCurrentIndex(0)
    panel.pattern_combo.activated.emit(0)
    assert len(_rows(panel)) == 1
    assert panel.name_input.text() == "JW 2024-01-31-Beratung-im-Maerz-2024"


def test_custom_settings_pattern_gets_own_entry(qtbot, monkeypatch, tmp_path):
    from src.core.filename_placeholders import PATTERN_CHOICE_SETTINGS
    panel, _ = _panel(qtbot, monkeypatch, tmp_path, filename_pattern="{kontakt}_{lieferant}")
    _select(panel, tmp_path, [_ki_suggestion()])
    assert panel.pattern_combo.currentText() == PATTERN_CHOICE_SETTINGS
    assert _rows(panel)[1] == "Testfirma-GmbH.pdf  [Muster: Eigenes Muster]"


def test_choice_survives_next_pdf_but_follows_settings_change(qtbot, monkeypatch, tmp_path):
    panel, cfg = _panel(qtbot, monkeypatch, tmp_path, filename_pattern=RECHNUNGEN,
                        owner_initials="JW")
    _select(panel, tmp_path, [_ki_suggestion()])
    idx = panel.pattern_combo.findData(BUERO)
    panel.pattern_combo.setCurrentIndex(idx)
    panel.pattern_combo.activated.emit(idx)

    # Naechste PDF: Umschaltung des Nutzers bleibt
    _select(panel, tmp_path, [_ki_suggestion("2024-02-01_Rechnung_Andere.pdf")])
    assert panel.pattern_combo.currentData() == BUERO

    # Einstellungen geaendert: Combo folgt dem neuen Muster
    cfg.set("filename_pattern", "{jahr}_{kontakt}", auto_save=False)
    _select(panel, tmp_path, [_ki_suggestion()])
    assert panel.pattern_combo.currentData() == "{jahr}_{kontakt}"
    assert _rows(panel)[1].startswith("2024_Testfirma-GmbH.pdf")


def test_clicking_pattern_row_takes_name_without_touching_metadata(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path, filename_pattern=RECHNUNGEN)
    _select(panel, tmp_path, [_ki_suggestion(),
                              RenameSuggestion("Dokument.pdf", "Automatisch erkannt", 0.5)])
    panel._on_suggestion_clicked(panel.suggestions_list.item(1))
    assert panel.name_input.text() == "2024-01-31_Rechnung_Testfirma-GmbH_Beratung-im-Maerz-2024"
    assert panel.get_metadata()["korrespondent"] == "Testfirma GmbH"
    # Dritte Zeile (Index-Verschiebung durch die Muster-Zeile) trifft weiter den richtigen Vorschlag
    panel._on_suggestion_clicked(panel.suggestions_list.item(2))
    assert panel.name_input.text() == "Dokument"


def test_date_falls_back_to_ki_filename(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path, filename_pattern="{datum}_{kontakt}")
    _select(panel, tmp_path, [_ki_suggestion("2023-12-24_Rechnung_Testfirma.pdf")], detected_date=None)
    assert _rows(panel)[1].startswith("2023-12-24_Testfirma-GmbH.pdf")

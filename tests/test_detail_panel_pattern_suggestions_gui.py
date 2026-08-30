"""Issues #99/#106: Einheitliche Vorschlagsliste im Detail-Panel.

Die Liste zeigt KI-Vorschlaege, je Vorlage (und eigenem Einstellungs-Muster)
einen Muster-Vorschlag aus den Metadaten der PDF sowie die einfachen
Analyse-Vorschlaege - alles in einer Liste, sortiert nach der gemerkten
Rangfolge: die zuletzt angeklickte Art steht beim naechsten Dokument oben
und wird als Dateiname uebernommen.
"""
from src.core.suggestion_order import CONFIG_KEY, KIND_AUTO, KIND_KI, pattern_kind
from src.gui.rename_dialog import RenameSuggestion

RECHNUNGEN = "{datum}_{kategorie}_{kontakt}_{betreff}"
AKTEN = "{initialen}_{aktenzeichen}_{datum}_{betreff}_{kontakt}"
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
    # Eigene Datenbank pro Test: Korrespondenten-Lernen, Kategorie-Liste (#109/#110)
    from src.utils.database import Database
    db = Database(db_path=tmp_path / "panel.db")
    monkeypatch.setattr("src.utils.database.get_database", lambda: db)
    cfg._db = db

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


def _analysis_suggestions():
    return [
        RenameSuggestion("Dokument.pdf", "Automatisch erkannt", 0.6),
        RenameSuggestion("2024-01-31.pdf", "Nur Datum", 0.3),
        RenameSuggestion("2024-01-31 Rechnung.pdf", "Datum + Kategorie (Rechnung)", 0.5),
        RenameSuggestion("Rechnung Nr4711.pdf", "Kategorie + Nummer", 0.4),
    ]


def _rows(panel):
    lst = panel.suggestions_list
    return [lst.item(i).text() for i in range(lst.count())]


def _reasons(panel):
    return [row.split("  [")[1].rstrip("]") for row in _rows(panel)]


def _select(panel, tmp_path, suggestions, detected_date="2024-01-31"):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    panel.set_pdf(pdf_path=pdf, suggestions=suggestions, extracted_text="x",
                  keywords=["rechnung"], detected_date=detected_date)
    return pdf


def test_unified_list_ki_then_all_patterns_then_analysis(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path, owner_initials="JW")
    _select(panel, tmp_path, [_ki_suggestion()] + _analysis_suggestions())

    assert _reasons(panel) == [
        "KI-Vorschlag",
        "Muster: Rechnungen & Belege",
        "Muster: Akten & Projekte",
        "Muster: Büro-Kürzel voran",
        "Automatisch erkannt",
        "Datum + Kategorie (Rechnung)",
        "Kategorie + Nummer",
    ]
    rows = _rows(panel)
    assert rows[1].startswith("2024-01-31_Rechnung_Testfirma-GmbH_Beratung-im-Maerz-2024.pdf")
    assert rows[2].startswith("JW_2024-01-31_Beratung-im-Maerz-2024_Testfirma-GmbH.pdf")
    assert rows[3].startswith("JW 2024-01-31-Beratung-im-Maerz-2024.pdf")
    # Keine Muster-Combo mehr (#106)
    assert not hasattr(panel, "pattern_combo")
    # Oberste Zeile = Dateiname, gilt nicht als Nutzer-Aenderung
    assert panel.name_input.text() == "2024-01-31_Rechnung_Testfirma"
    assert not panel.has_user_edits()


def test_settings_pattern_ranks_first_among_patterns(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path, filename_pattern=BUERO, owner_initials="JW")
    _select(panel, tmp_path, [_ki_suggestion()])
    assert _reasons(panel) == [
        "KI-Vorschlag", "Muster: Büro-Kürzel voran",
        "Muster: Rechnungen & Belege", "Muster: Akten & Projekte",
    ]


def test_custom_settings_pattern_gets_own_row(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path, filename_pattern="{kontakt}_{betreff}")
    _select(panel, tmp_path, [_ki_suggestion()])
    assert _rows(panel)[1] == "Testfirma-GmbH_Beratung-im-Maerz-2024.pdf  [Muster: Eigenes Muster]"


def test_no_rows_without_any_metadata(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, [], detected_date=None)
    assert _rows(panel) == ["Keine Vorschläge verfügbar"]
    assert panel.name_input.text() == ""


def test_patterns_with_fewer_than_two_values_are_skipped(qtbot, monkeypatch, tmp_path):
    # Nur Datum + Kategorie (aus Stichwort), keine Initialen: Rechnungen rendert
    # zwei Werte, Akten und Buero haetten nur das Datum -> weg
    panel, _ = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, [RenameSuggestion("Dokument.pdf", "Automatisch erkannt", 0.6)])
    assert _reasons(panel) == ["Muster: Rechnungen & Belege", "Automatisch erkannt"]
    assert _rows(panel)[0].startswith("2024-01-31_Rechnung.pdf")


def test_clicking_a_pattern_makes_it_default_for_next_pdf(qtbot, monkeypatch, tmp_path):
    panel, cfg = _panel(qtbot, monkeypatch, tmp_path, owner_initials="JW")
    _select(panel, tmp_path, [_ki_suggestion()] + _analysis_suggestions())

    # Buero-Muster anklicken: Name uebernommen, Liste bleibt fuer DIESES Dokument stehen
    idx = _reasons(panel).index("Muster: Büro-Kürzel voran")
    panel._on_suggestion_clicked(panel.suggestions_list.item(idx))
    assert panel.name_input.text() == "JW 2024-01-31-Beratung-im-Maerz-2024"
    assert _reasons(panel)[0] == "KI-Vorschlag"
    assert cfg.get(CONFIG_KEY)[:2] == [pattern_kind(BUERO), KIND_KI]
    assert (tmp_path / "config.json").exists()  # persistiert

    # Naechstes Dokument: Buero-Muster ganz oben, Rest eine Stufe tiefer, Name = Buero
    _select(panel, tmp_path, [_ki_suggestion("2024-02-01_Rechnung_Andere.pdf")] + _analysis_suggestions())
    assert _reasons(panel)[:3] == [
        "Muster: Büro-Kürzel voran", "KI-Vorschlag", "Muster: Rechnungen & Belege",
    ]
    assert panel.name_input.text() == "JW 2024-01-31-Beratung-im-Maerz-2024"
    assert not panel.has_user_edits()

    # Jetzt "Automatisch erkannt": wird neuer Default, Buero rueckt auf 2
    idx = _reasons(panel).index("Automatisch erkannt")
    panel._on_suggestion_clicked(panel.suggestions_list.item(idx))
    _select(panel, tmp_path, [_ki_suggestion()] + _analysis_suggestions())
    assert _reasons(panel)[:3] == [
        "Automatisch erkannt", "Muster: Büro-Kürzel voran", "KI-Vorschlag",
    ]
    assert panel.name_input.text() == "Dokument"
    assert cfg.get(CONFIG_KEY)[:2] == [KIND_AUTO, pattern_kind(BUERO)]


def test_saved_order_is_respected_on_start(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path,
                      **{CONFIG_KEY: [pattern_kind(RECHNUNGEN), KIND_AUTO]})
    _select(panel, tmp_path, [_ki_suggestion()] + _analysis_suggestions())
    assert _reasons(panel)[:3] == ["Muster: Rechnungen & Belege", "Automatisch erkannt", "KI-Vorschlag"]
    assert panel.name_input.text() == "2024-01-31_Rechnung_Testfirma-GmbH_Beratung-im-Maerz-2024"


def test_duplicate_names_shown_once_higher_rank_wins(qtbot, monkeypatch, tmp_path):
    # KI folgt exakt dem Rechnungen-Muster -> nur die KI-Zeile bleibt
    panel, _ = _panel(qtbot, monkeypatch, tmp_path)
    ki = _ki_suggestion("2024-01-31_Rechnung_Testfirma-GmbH_Beratung-im-Maerz-2024.pdf")
    _select(panel, tmp_path, [ki])
    reasons = _reasons(panel)
    assert reasons[0] == "KI-Vorschlag"
    assert "Muster: Rechnungen & Belege" not in reasons


def test_nur_datum_and_learned_are_not_listed(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, _analysis_suggestions() + [
        RenameSuggestion("2022-04-03_Commerzbank_Depotauszug.pdf",
                         "Gelernt: ähnlich zu Depotauszug.pdf", 0.7),
    ])
    reasons = _reasons(panel)
    assert "Nur Datum" not in reasons
    assert not any(r.startswith("Gelernt") for r in reasons)


def test_clicking_ki_row_takes_metadata_pattern_row_does_not(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, [_ki_suggestion()] + _analysis_suggestions())
    idx = _reasons(panel).index("Muster: Rechnungen & Belege")
    panel._on_suggestion_clicked(panel.suggestions_list.item(idx))
    assert panel.name_input.text() == "2024-01-31_Rechnung_Testfirma-GmbH_Beratung-im-Maerz-2024"
    assert panel.get_metadata()["korrespondent"] == "Testfirma GmbH"
    idx = _reasons(panel).index("Automatisch erkannt")
    panel._on_suggestion_clicked(panel.suggestions_list.item(idx))
    assert panel.name_input.text() == "Dokument"


def test_date_falls_back_to_ki_filename(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, [_ki_suggestion("2023-12-24_Rechnung_Testfirma.pdf")], detected_date=None)
    assert _rows(panel)[1].startswith("2023-12-24_Rechnung_Testfirma-GmbH_Beratung-im-Maerz-2024.pdf")


def test_pdf_metadata_arriving_later_updates_auto_name_only(qtbot, monkeypatch, tmp_path):
    """XMP-Werte kommen nach: oberste Muster-Zeile aendert sich -> Name folgt,
    ausser der Nutzer hat schon selbst getippt."""
    from src.core.pdf_metadata import PDFMetadata
    panel, _ = _panel(qtbot, monkeypatch, tmp_path,
                      **{CONFIG_KEY: [pattern_kind(RECHNUNGEN)]})
    pdf = _select(panel, tmp_path, [_ki_suggestion()])
    assert panel.name_input.text() == "2024-01-31_Rechnung_Testfirma-GmbH_Beratung-im-Maerz-2024"

    meta = PDFMetadata(korrespondent="Andere AG", subject="Rechnung", description="Wartung")
    panel._on_pdf_metadata_read(pdf, meta)
    assert panel.name_input.text() == "2024-01-31_Rechnung_Andere-AG_Wartung"
    assert not panel.has_user_edits()

    # Nutzer tippt -> spaetere Metadaten aendern den Namen nicht mehr
    panel.name_input.setText("Mein Name")
    panel._on_pdf_metadata_read(pdf, PDFMetadata(korrespondent="Dritte KG"))
    assert panel.name_input.text() == "Mein Name"


def test_header_folder_naming_switch_mirrors_config(qtbot, monkeypatch, tmp_path):
    panel, cfg = _panel(qtbot, monkeypatch, tmp_path, folder_naming_enabled=True)
    _select(panel, tmp_path, [_ki_suggestion()])
    assert panel.folder_naming_checkbox.isChecked()

    # Schalter schreibt die Config (dieselbe Einstellung wie im Dialog)
    panel.folder_naming_checkbox.setChecked(False)
    assert cfg.get("folder_naming_enabled") is False
    assert (tmp_path / "config.json").exists()

    # Dialog aendert die Config -> refresh_settings zieht den Schalter nach
    cfg.set("folder_naming_enabled", True, auto_save=False)
    panel.refresh_settings()
    assert panel.folder_naming_checkbox.isChecked()


def test_header_edit_pattern_button_emits_signal(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path)
    with qtbot.waitSignal(panel.edit_pattern_requested, timeout=1000):
        panel.edit_pattern_btn.click()


def test_saved_custom_pattern_becomes_a_row(qtbot, monkeypatch, tmp_path):
    panel, _ = _panel(qtbot, monkeypatch, tmp_path,
                      custom_patterns=[{"name": "Mieter", "pattern": "{jahr}_{kontakt}_Miete"}])
    _select(panel, tmp_path, [_ki_suggestion()])
    rows = _rows(panel)
    assert "2024_Testfirma-GmbH_Miete.pdf  [Muster: Mieter]" in rows
    assert _reasons(panel)[-1] == "Muster: Mieter"  # nach den eingebauten Vorlagen


# --- Issues #109/#110: Kategorie-Auswahl, Text aus der Vorschau, Lernen ---


def test_category_field_is_editable_combo_with_choices(qtbot, monkeypatch, tmp_path):
    from src.core.metadata_choices import DEFAULT_CATEGORIES
    panel, cfg = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, [_ki_suggestion()])
    combo = panel._metadata_inputs["subject"]
    items = [combo.itemText(i) for i in range(combo.count())]
    assert items[: len(DEFAULT_CATEGORIES)] == list(DEFAULT_CATEGORIES)
    # Verhaelt sich wie das Textfeld: Wert aus dem KI-Vorschlag, get_metadata liest ihn
    assert combo.text() == "Rechnung"
    assert panel.get_metadata()["subject"] == "Rechnung"
    # Auswahl aus der Liste = Nutzer-Eingabe
    combo.setCurrentIndex(items.index("Vertrag"))
    assert panel.get_metadata()["subject"] == "Vertrag"
    assert panel.has_user_edits()
    # clear() leert nur den Text, die Liste bleibt
    combo.clear()
    assert combo.text() == "" and combo.count() == len(items)

    # Neue Kategorie verwenden + speichern -> steht beim naechsten Mal ganz oben
    combo.setText("Liste")
    panel.mark_metadata_saved()
    assert cfg.get("recent_categories") == ["Liste"]
    assert combo.itemText(0) == "Liste"
    _select(panel, tmp_path, [_ki_suggestion()])
    assert combo.itemText(0) == "Liste" and combo.itemText(1) == "Rechnung"


def test_preview_text_goes_into_field_and_korrespondent_is_learned(qtbot, monkeypatch, tmp_path):
    panel, cfg = _panel(qtbot, monkeypatch, tmp_path)
    _select(panel, tmp_path, [_ki_suggestion()])
    assert panel.get_metadata()["korrespondent"] == "Testfirma GmbH"

    panel.preview.apply_text_requested.emit("korrespondent", "  Commerzbank   AG ")
    assert panel.get_metadata()["korrespondent"] == "Commerzbank AG"
    assert panel.has_user_edits()
    assert [k["name"] for k in cfg._db.list_korrespondenten()] == ["Commerzbank AG"]

    panel.preview.apply_text_requested.emit("description", "Depotauszug 2024")
    assert panel.get_metadata()["description"] == "Depotauszug 2024"
    panel.preview.apply_text_requested.emit("subject", "Bank")
    assert panel.get_metadata()["subject"] == "Bank"
    # Alle Felder erreichbar, mit Aufbereitung
    panel.preview.apply_text_requested.emit("iban", "DE89 3704 0044 0532 0130 00")
    panel.preview.apply_text_requested.emit("betrag_brutto", "1.234,56 €")
    panel.preview.apply_text_requested.emit("mwst_satz", "19 %")
    panel.preview.apply_text_requested.emit("steuerjahr", "Steuerjahr 2024")
    md = panel.get_metadata()
    assert md["iban"] == "DE89370400440532013000"
    assert md["betrag_brutto"] == "1.234,56"
    assert md["mwst_satz"] == "19"
    assert md["steuerjahr"] == "2024"


def test_known_korrespondent_in_text_beats_ki_suggestion(qtbot, monkeypatch, tmp_path):
    panel, cfg = _panel(qtbot, monkeypatch, tmp_path)
    cfg._db.add_or_update_korrespondent("Commerzbank AG", aliases=["Coba"])

    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    panel.set_pdf(pdf_path=pdf, suggestions=[_ki_suggestion()],
                  extracted_text="Depotauszug der Coba fuer Kunde 4711",
                  keywords=["bank"], detected_date="2024-01-31")
    assert panel.get_metadata()["korrespondent"] == "Commerzbank AG"

    # Ohne Treffer im Text bleibt der KI-Vorschlag
    panel.set_pdf(pdf_path=pdf, suggestions=[_ki_suggestion()],
                  extracted_text="Rechnung der Testfirma", keywords=["rechnung"],
                  detected_date="2024-01-31")
    assert panel.get_metadata()["korrespondent"] == "Testfirma GmbH"


def test_new_settings_pattern_is_applied_immediately(qtbot, monkeypatch, tmp_path):
    """Einstellungen > Dateinamen gespeichert -> neues Muster oben + im Namensfeld."""
    panel, cfg = _panel(qtbot, monkeypatch, tmp_path, owner_initials="JW")
    _select(panel, tmp_path, [_ki_suggestion()] + _analysis_suggestions())
    assert _reasons(panel)[0] == "KI-Vorschlag"
    panel.name_input.setText("Selbst getippt")  # wird bewusst ueberschrieben

    cfg.set("filename_pattern", "{jahr}_{kontakt}_Miete", auto_save=False)
    panel.refresh_settings()  # macht MainWindow._on_settings_changed

    assert _reasons(panel)[0] == "Muster: Eigenes Muster"
    assert panel.name_input.text() == "2024_Testfirma-GmbH_Miete"
    assert not panel.has_user_edits()
    assert cfg.get(CONFIG_KEY)[0] == pattern_kind("{jahr}_{kontakt}_Miete")

    # Naechste PDF: bleibt oben
    _select(panel, tmp_path, [_ki_suggestion("2024-02-01_Rechnung_Andere.pdf")])
    assert _reasons(panel)[0] == "Muster: Eigenes Muster"

    # Unveraenderte Einstellungen: nichts passiert, Nutzertext bleibt
    panel.name_input.setText("Mein Name")
    panel.refresh_settings()
    assert panel.name_input.text() == "Mein Name"


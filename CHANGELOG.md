# Changelog

Alle nennenswerten Aenderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Hinzugefuegt
- **Jahres-Variante bei Ordnervorschlaegen (Issue #30)**: Zu einem gelernten Vorschlag wie
  "Steuer 2025/Medikamente" wird zusaetzlich "Steuer 2026/Medikamente" angeboten, wenn der
  Ordner existiert. Passt das im Dokument erkannte Jahr, steht die Variante vorn; ohne
  erkanntes Jahr dahinter. Der gelernte Ordner bleibt immer erhalten (nichts wird
  stillschweigend umgeschrieben). Relative Pfade in Vorschlaegen nutzen jetzt einheitlich "/".
- **Explorer-Gefuehl im Scan-Bereich (Sprint 1, Issues #29/#26/#23)**
  - Ordner-Kacheln im PDF-Raster: ".." (uebergeordneter Ordner) und alle Unterordner
    mit PDF-Anzahl; Doppelklick wechselt hinein, PDFs lassen sich per Drag & Drop
    direkt in eine Kachel verschieben
  - Klickbarer Breadcrumb-Pfad unter der Kopfzeile; Menue Ansicht -> "Uebergeordneter
    Ordner" (Alt+Up), wie im Windows-Explorer
  - Zielordner-Baum: Doppelklick oeffnet den Ordner links, ohne vorher die selektierte
    PDF zu verschieben (Einfachklick wird erst nach dem Doppelklick-Intervall ausgefuehrt);
    Kontextmenue "Ordner links oeffnen"
  - Versteckte Ordner (., $, ~) werden ausgeblendet, Unterordner alphabetisch sortiert

### Tests
- `tests/conftest.py`: `patch_singletons()` ersetzt Singleton-Fabriken in allen src-Modulen
  (GUI-Tests liefen je nach Import-Reihenfolge gegen die echte Nutzer-Config)

## [0.14.0] - 2026-08-25

### Hinzugefuegt
- **OpenRouter** als LLM-Provider (OpenAI-kompatible API, viele Modelle mit einem Key)
  - Einstellungen, Setup-Wizard, HybridClassifier, Consent-Gate
- **API-Keys pro Provider** (Issue #11): Keys bleiben beim Provider-Wechsel erhalten,
  Label zeigt den Besitzer ("API-Key (OpenRouter):")
- **Datenschutz-Einwilligung** in den KI-Einstellungen (Checkbox + Hinweis); vorher gab
  es keine Bedienoberflaeche fuer das Consent-Gate
- **Statusleiste**: Doppelklick auf "LLM:" oeffnet die Einstellungen; Doppelklick auf
  den Analyse-Fortschritt zeigt Details (Fortschritt, letzter KI-Fehler, Log-Pfad)
- **Fortschritt der Hintergrund-Analyse**: "Analyse: x/n | KI-Vorschlaege: y/n" mit
  Fehlermarkierung; KI-Vorabfrage wird nach Einstellungsaenderung neu angestossen
- **Backup-Hinweis** beim Start, abhakbar (Issue #7); Macrium-Log-Parsing bleibt #14
- **App-Icon** (Mann aus dem Splash) fuer Fenster, Taskleiste und .exe
- "+ Zielordner" startet im uebergeordneten Ordner des Scan-Ordners (Issue #11)
- **pdfs-Master-Tabelle mit stabiler pdf_id** (Issue #25, Phasen 1-3)
- **Consent-Gate** fuer Cloud-Provider in HybridClassifier (`llm.cloud_consent`)

### Geaendert
- Lizenz: MIT -> **GPL-3.0-or-later** (PyQt6/PyMuPDF Copyleft), LICENSE-Datei ergaenzt
- `OpenAIProvider`: Fehlermeldungen ueber `API_NAME` parametrisiert (fuer Subklassen)

### Behoben
- Einstellungen speichern verwarf `cloud_consent` und `cached_models`
- `Config.DEFAULTS` wurde flach kopiert (verschachtelte Dicts instanzuebergreifend geteilt)
- Analyse-Fortschritt blieb bei "0/n" haengen, wenn alle PDFs bereits im Cache waren
- KI-Vorabfrage lief ins Leere, wenn das LLM beim Einreihen noch deaktiviert war
- LLM-Queue dedupliziert (keine doppelten API-Aufrufe bei erneutem Pre-Cache)

### Tests
- 339 Tests (285 -> 339): OpenRouter-Provider, Keys/Consent-GUI, Cache-LLM-Queue,
  pdf_id-Propagation, Consent-Gate

## [0.13.0] - 2026-06-17

### Hinzugefuegt
- **Phase 20: Korrespondenten-Verwaltung (Issue #21)** - Verwaltungstabelle + GUI-Sidebar
  - Neue SQLAlchemy-Tabelle `korrespondenten` (Name, Aliase, Kategorie, Farbe, Notizen, usage_count)
  - CRUD + merge_korrespondenten (FTS5-Update) + auto_collect_from_history
  - GUI: KorrespondentSidebar im rechten Bereich (Tab "Korrespondenten")
  - GUI: KorrespondentEditDialog + KorrespondentMergeDialog
  - Klick auf Korrespondent filtert PDF-Liste
- **Phase 21: Automatisierungs-Regeln (Issue #22)** - WENN-DANN-Regeln
  - DB-Tabelle `automation_rules` (priority, enabled, conditions_json, actions_json)
  - `RuleEngine.evaluate()` + `apply_actions()` mit 5 Condition-Typen
    (korrespondent, kategorie, betrag, datum, keywords) und 4 Action-Typen
    (target_folder, filename_pattern, metadata_field, tag)
  - Platzhalter: {datum}, {steuerjahr}, {korrespondent}, {kategorie},
    {betrag_brutto}
  - Confidence-Berechnung (1.0 exakt, 0.8 bei contains, N/M partial)
  - Settings-Tab "Automatisierungs-Regeln" mit visuellem Rule-Editor
- **STAB-Block: pytest-qt GUI-Tests** fuer die bestehende Haupt-GUI
  - 39 neue Tests: FolderWidget (14), RenameDialog (12), MainWindow (13)
  - Phase-20: 34 neue Tests fuer Korrespondenten-Verwaltung
  - Phase-21: 23 neue Tests fuer Rule-Edit-Dialog und Settings-Tab

### Geaendert
- `ENTWICKLUNGSSTAND.md` -> v0.13.0 (Phase 20+21 abgeschlossen)

### Behoben
- Phase-21: replace_all=true hatte `main_window.py` zwischenzeitlich
  zerschossen -> via `git checkout` zurueckgesetzt und 3 Move-Pfade
  sauber einzeln nachgepatcht (kein Produktion-Regression, war vor Commit)
- Cancel-Cooldown aus M4-Regression nochmal verifiziert (war schon im
  M4-Commit gefixt)

### Migration
- Neue Tabelle `korrespondenten` und `automation_rules` werden via
  idempotenter `CREATE TABLE IF NOT EXISTS`-Migration angelegt -
  kein Eingriff noetig fuer bestehende Datenbanken
- CHANGELOG.md-Header v0.12.0 zeigt RAG-Chat (Phase 19)
## [0.12.0] - 2026-06-14

### Hinzugefuegt
- **Phase 19: RAG-Chat (Issue #20)** - Intelligente Dokumentensuche per natuerlicher Sprache
  - Neuer Chat-Tab im Hauptfenster (3-Spalten-Layout bleibt erhalten)
  - FTS5-basiertes Retrieval (keine Embedding-Dependency) ueber bestehende `document_search`-Tabelle
  - LLM-Synthese mit klickbaren Quellenangaben `[1]`, `[2]`, ... (Whitelist-validiert; halluzinierte Quellen werden stillschweigend gedroppt)
  - Offline-Fallback: kein LLM konfiguriert -> Keyword-Trefferliste mit klickbaren Quellen
  - In-Session-History (in-memory), Read-only in v1
  - Cancel-Button mit 500ms-Cooldown (M3-Hardening, schuetzt vor Doppel-Klicks)
  - Return-Taste sendet Frage, Shift+Return fuer Zeilenumbruch (M3-UX-Polish)
  - Citation-Parser droppt ungueltige Marker (`[99]`, `[42]`, etc.)
  - Stale-Signal-Guard: `finished()`-Signal nach `cancel()` wird ignoriert
- **M3 Hardening**: Signal-Safety im ChatWorker (`_finished_emitted`/`_failed_emitted` Flags,
  idempotente `cancel()`, `is_finished` Property)
- **M3 Hardening**: Defensiv-Guards in `RAGController` und `CitationParser` (None-Toleranz,
  leere DB, kein LLM)
- **Bugfix**: Suchpfad-Bug (Issue #25) - `update_pdf_path` und `bulk_index_directory` ergaenzt
  - Vorher: nach Verschieben einer PDF blieben DB-Eintraege am alten Pfad zurueck (Orphans)
  - Nachher: atomar DELETE-old + INSERT-new, plus Bulk-Index fuer ganze Ordner
- **Test-Suite**: 112 Tests (68 -> 112), davon 35 neu fuer RAG-Pipeline
  - Pytest-qt fuer GUI-Tests
  - Headless-Smoke-Tests fuer alle 4 LLM-Provider (Ollama/Claude/OpenAI/Poe)

### Geaendert
- `database.search_documents`: akzeptiert jetzt optionale Filter (steuerjahr, kategorie,
  korrespondent, datum_von/bis, betrag_von/bis) UND optionale Text-Query (M3-Hardening,
  Bugfix fuer OR-Operator)
- `LLMProvider.answer_with_context`: neue abstrakte Methode, in allen 4 Providern
  implementiert via stdlib `urllib` (kein anthropic/openai-Import noetig fuer Tests)
- `ENTWICKLUNGSSTAND.md` -> v0.12.0 (Phase 19 abgeschlossen)

### Behoben
- Cancel-Cooldown wurde durch `_reset_input_state()` ueberschrieben (M3-Bugfix)
- FTS5-OR-Query lieferte 0 Treffer (Production-Bug, gefixt in `search_documents`)

## [0.11.0] - 2026-06-14

### Hinzugefuegt
- Phase 8: 34 Unit-Tests (vorher nur 3 in `test_file_manager.py`)
- Phase 17: Filter-Kombinationen in der Volltext-Suche (Issue #18)
  - Steuerjahr/Kategorie/Korrespondent-Dropdowns
  - Datums- und Betragsbereich
  - Live-Trefferzaehler mit Echtzeit-Aktualisierung
- Phase 6: JSON-Mode fuer LLM-Provider (Ollama native `format=json`, Cloud-Provider ueber
  Regex-Parser)
- `bulk_index_directory` fuer rekursives Neu-Indizieren ganzer Ordner

### Geaendert
- `ENTWICKLUNGSSTAND.md` -> v0.11.0

[Unreleased]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.14.0...HEAD
[0.14.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.13.0...v0.14.0
[0.12.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.10.0...v0.11.0
[0.13.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.12.0...v0.13.0

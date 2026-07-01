# PDF Sortier Meister - Entwicklungsstand

**Datum:** 01.07.2026
**Aktuelle Version:** 0.13.1 (in Entwicklung)

> **Was ist neu in v0.13.0?** Siehe [Changelog v0.13.0](#changelog-v0130) am Ende des Dokuments.

---
### v0.13.1 (2026-07-01) - Lizenz-Korrektur (Monetarisierungs-Fundament)
- Lizenz von MIT auf **GPL-3.0-or-later** korrigiert (Pfad A der Monetarisierungs-Roadmap)
- Grund: PyQt6 (GPLv3) + PyMuPDF (AGPLv3) sind Copyleft -> MIT war rechtlich nicht haltbar
- LICENSE-Datei (GPLv3-Volltext) im Projekt-Root ergaenzt (fehlte zuvor komplett)
- pyproject.toml: license + OSI-Classifier auf GPLv3+ umgestellt
- README: Lizenz-Abschnitt + Dritt-Bibliotheken-Uebersicht ergaenzt
- Geschaeftsmodell-Basis: Open Source (GPL) + Verkauf von Installer/Komfort/Support
- Keine Code-Aenderung -> 285/285 Tests unveraendert gruen
### v0.12.0 (2026-06-14) - Phase 19 RAG-Chat abgeschlossen
- Chat-Tab mit FTS5-Retrieval + LLM-Synthese + Citations
- Offline-Fallback, Cancel-Flow, Return-UX-Polish
- M3-Hardening: Signal-Safety, CitationParser-Edge-Cases, Defensiv-Guards
- Bugfix: Cancel-Cooldown wurde durch _reset_input_state ueberschrieben
- 112/112 Tests gruen (35 neu fuer RAG-Pipeline)

### v0.13.0 (2026-06-17) - Phase 20+21 abgeschlossen + 5/5 INTEL fertig
- Phase 20 Korrespondenten-Verwaltung: DB-Tabelle + Sidebar + Edit/Merge-Dialoge
- Phase 21 Automatisierungs-Regeln: RuleEngine + Settings-Tab mit visuellem Editor
- 4 Issues geschlossen (#15, #17, #18, #24 - waren vergessen worden)
- 285/285 Tests gruen (262 -> 285, 23 neue in dieser Version)
- ENTWICKLUNGSSTAND.md auf v0.13.0


## Abgeschlossene Phasen

### Phase 1: Grundgerüst (100% fertig)
- [x] Projektstruktur erstellt
- [x] requirements.txt mit Abhängigkeiten
- [x] Konfigurationssystem (`src/utils/config.py`)
- [x] Basis-GUI mit PyQt6 (`src/gui/main_window.py`)
- [x] Haupteinstiegspunkt (`src/main.py`, `run.py`)

### Phase 2: PDF-Verarbeitung (100% fertig)
- [x] PDF-Thumbnail-Generierung (`src/core/pdf_analyzer.py`)
- [x] Textextraktion (direkt + OCR-Fallback)
- [x] Metadaten-Extraktion
- [x] Datumsextraktion aus Dokumentinhalt
- [x] Schlüsselwort-Erkennung
- [x] Intelligente Dateinamen-Vorschläge
- [x] File-Manager (`src/core/file_manager.py`)
- [x] PDF-Thumbnail-Widget (`src/gui/pdf_thumbnail.py`)
- [x] Ordner-Widget (`src/gui/folder_widget.py`)

### Phase 3: Lernfähiges Klassifikationssystem (100% fertig)
- [x] SQLite-Datenbank für Sortierhistorie (`src/utils/database.py`)
- [x] TF-IDF Text-Embedding-System
- [x] Klassifikator mit Ähnlichkeitssuche (`src/ml/classifier.py`)
- [x] Training bei Benutzerentscheidungen
- [x] GUI-Integration: Vorschläge anzeigen
- [x] Trainingsstand in Statusleiste

### Phase 4: Intelligente Umbenennung (100% fertig)
- [x] Verbesserter Umbenennungsdialog (`src/gui/rename_dialog.py`)
- [x] Live-Vorschau des neuen Namens
- [x] Mehrere Namensvorschläge mit Konfidenz-Anzeige
- [x] Regelbasierte Namensvorschläge (Datum, Kategorie, Firmennamen)
- [x] Lernen aus Umbenennungen (neue `RenameHistory` Tabelle)
- [x] Gelernte Muster werden als Vorschläge angezeigt

### Phase 6: LLM-Integration - Hybrid-Ansatz (100% fertig)
- [x] LLM Provider-Abstraktion (`src/ml/llm_provider.py`)
- [x] Claude API Integration (`src/ml/claude_provider.py`)
- [x] OpenAI API Integration (`src/ml/openai_provider.py`)
- [x] Poe.com API Integration (`src/ml/poe_provider.py`)
- [x] Hybrid-Klassifikator (`src/ml/hybrid_classifier.py`)
- [x] Automatische Entscheidung: Lokal vs. LLM basierend auf Konfidenz
- [x] API-Key Verwaltung in Config (`src/utils/config.py`)
- [x] Einstellungsdialog mit LLM-Konfiguration (`src/gui/settings_dialog.py`)
- [x] Verbindungstest für API-Keys
- [x] LLM-Status in Statusleiste
- [x] Fallback auf lokalen Klassifikator bei API-Fehler
- [x] **LLM-Textlimit konfigurierbar** (500-5000 Zeichen, Default: 1500)
- [x] **LLM erkennt Rechnungsnummern und Betreff** bei Rechnungen (nicht nur Firmennamen)
- [x] **Fallback auf Scandatum** wenn kein Datum im PDF gefunden wird (kein Phantasiedatum mehr)
- [x] **Strukturierte JSON-Antworten mit Metadaten-Extraktion** *(v0.11.0)*
  - Alle LLM-Provider (Claude, OpenAI, Poe, Ollama) liefern strukturiertes JSON statt Freitext
  - Erweitertes Metadaten-Schema: `kategorie`, `korrespondent`, `betrag_netto`, `betrag_brutto`, `waehrung`, `mwst`, `iban`, `steuerjahr`, `beschreibung`
  - **Robuster JSON-Parser** (`_parse_json_response` in `llm_provider.py`): Regex-basierte Extraktion aus LL-M-Output, immun gegen "Plauder-Text" vor/nach dem JSON
  - **Ollama JSON-Mode**: Lokales Modell nutzt `"format": "json"` für deterministische Antworten
  - **Sichere f-string-Templates**: Alle JSON-Beispiele in Prompts doppelt escaped (`{{` / `}}`) — Syntax-Bug-Fix der die Pipeline lauffähig gemacht hat
  - **Lebenszyklus**: JSON wird geparst → in `LLMResponse.metadata` gemappt → in der GUI angezeigt → in der DB indexiert

### Phase 12: Hierarchische Ordnerstruktur (100% fertig)
- [x] Ordner-Baumansicht Widget (`src/gui/folder_tree_widget.py`)
- [x] FolderManager für rekursive Unterordner erweitert
- [x] Datenbank-Schema für vollständige Pfade (`target_relative_path`)
- [x] Klassifikator für hierarchische Pfade erweitert (`suggest_with_subfolders`)
- [x] Jahres-Muster bleibt erhalten (keine automatische Änderung 2025→2026)
- [x] Hervorhebung vorgeschlagener Ordner in der Baumansicht
- [x] Relativer Pfad in Vorschlägen (z.B. "Steuer 2026/Banken")
- [x] MainWindow mit Baumansicht integriert
- [x] Kontextmenü zum Erstellen neuer Unterordner (Rechtsklick → "Neuer Unterordner")
- [x] **Doppelklick auf Ordner** wechselt Scan-Ordner und zeigt dessen PDFs an

### Phase 5: GUI-Vervollständigung / Drag & Drop (100% fertig)
- [x] Drag & Drop von PDF-Thumbnails auf Ordner
- [x] Visuelles Feedback beim Ziehen (grün hervorgehobene Drop-Ziele)
- [x] Mehrfachauswahl von PDFs (Ctrl+Klick)
- [x] Thumbnail wird beim Ziehen als Vorschau angezeigt
- [x] Lernen aus Drag & Drop Entscheidungen
- [x] **PDF-Analyse-Caching** (`src/core/pdf_cache.py`):
  - Bereits analysierte PDFs werden nicht erneut analysiert
  - Hintergrund-Worker mit Prioritäten (User-Klick = höchste)
  - Pre-Caching: PDFs werden automatisch im Hintergrund voranalysiert
  - Sofortige Reaktion bei gecachten PDFs
  - **Persistenter Cache** (SQLite): Bleibt über Programmende erhalten
  - Cache-Einstellungen in Extras → Einstellungen → Allgemein
  - Cache kann für Debugging geleert werden
- [x] **LLM-Pre-Caching** im Hintergrund:
  - LLM-Vorschläge werden vorgeladen bevor Dialog geöffnet wird
  - Einstellbar in Extras → Einstellungen → Allgemein
  - Debug-Ausgaben für Analyse aktivierbar
- [x] **Optimiertes Verschieben/Löschen/Umbenennen**:
  - Kein vollständiger Refresh der Ansicht mehr nach Operationen
  - Nur das betroffene PDF-Widget wird entfernt/aktualisiert
  - Kein erneutes Pre-Caching aller PDFs (verhindert Lag)

---

## Noch offene Phasen

### Phase 13: UX-Verbesserungen (NEU - Hohe Priorität)

- [ ] **Drag & Drop Haptik verbessern**
  - Besseres visuelles Feedback beim Ziehen
  - Farb-Highlighting auch in der Listenansicht (nicht nur Vorschlagsbereich)

- [x] **Undo für Verschiebungen** *(erledigt in v0.9.0)*
  - Ctrl+Z macht letzte Verschiebung rückgängig (alle Codepfade: Vorschlag-Klick, Drag&Drop, Kontextmenü, Baumansicht)
  - History der letzten 20 Aktionen mit Beschreibung in Toolbar und Menü

- [x] **Kopieren-Option** *(erledigt in v0.8.0)*
  - Rechtsklick → "Kopie erstellen" im Kontextmenü

- [ ] **Zielordner-Dialog Startpfad**
  - "+ Zielordner" öffnet im aktuellen/übergeordneten Ordner

- [x] **Zurück-Button** *(erledigt in v0.9.0)*
  - ⬅ Button im Header navigiert zum vorherigen Scan-Ordner
  - Alt+Left Tastenkürzel + Menüeintrag unter Ansicht → Zurück
  - History-Stack speichert bis zu 50 vorherige Ordner

- [x] **Umbenennung rückgängig** *(erledigt in v0.9.0)*
  - Ctrl+Z macht auch Umbenennungen rückgängig (gemeinsamer Undo-Stack mit Verschiebungen)
  - Cache-Einträge werden beim Rückgängig-Machen korrekt migriert

- [x] **Dreizeilige Vorschlags-Buttons** *(erledigt in v0.8.0)*
  - Text in den grünen Vorschlagsbuttons auf 3 Zeilen umbrechen
  - Ordnernamen können sehr lang sein — kein Abschneiden mehr

- [x] **Info-Dialog erweitern** *(erledigt in v0.8.0)*
  - Aktuelle Versionsnummer anzeigen
  - Klickbarer Link zum GitHub-Repository
  - Hinweis auf MIT-Lizenz

- [x] **De-Selektion von PDFs** *(erledigt in v0.9.0)*
  - Klick auf leere (weiße) Fläche hebt alle Selektionen auf
  - Escape-Taste hebt Auswahl auf (Menü: Bearbeiten → Auswahl aufheben)
  - Vorschläge werden beim Deselektieren automatisch geleert

- [x] **F2-Taste für Umbenennen** *(erledigt in v0.9.0)*
  - F2 öffnet Umbenennungsdialog für ausgewählte PDF (Windows-Standard)
  - Menüeintrag unter Bearbeiten → Umbenennen...

- [ ] **Mehrere LLM API-Keys verwalten**
  - In den Einstellungen mehrere API-Keys für verschiedene Provider speichern
  - Schnelles Umschalten des aktiven LLM-Modells ohne erneute Key-Eingabe

### Phase 14: PDF-Bearbeitung (NEU - Mittlere Priorität)

**Inspiriert von Nuance PaperPort (to do #13-15):**

- [ ] **PDFs zusammenfügen** (to do #13)
  - Zwei PDFs per Drag & Drop zusammenfügen
  - Nützlich für mehrseitige Scans die getrennt wurden

- [ ] **PDFs trennen** (to do #15)
  - Mehrseitiges PDF in einzelne Seiten aufteilen
  - Rechtsklick → "PDF trennen"

### Phase 15: Layout-Optimierungen (NEU - Mittlere Priorität)

- [ ] **Dynamische Thumbnail-Spalten** (to do #16)
  - Mehr Spalten bei größerem Fenster
  - Responsive Grid-Layout

- [ ] **Explorer-ähnliche Listenansicht** (to do #18)
  - Sortierbare Spalten im Zielordner-Bereich
  - Details-Ansicht

- [ ] **Konfidenz-Visualisierung** (to do #17)
  - Visueller Rahmen bei hoher Konfidenz (>50%)
  - Animiertes Highlight für Top-Vorschläge

### Phase 7: Backup-Integration (offen - Niedrige Priorität)
- [ ] Macrium Reflect Log-Dateien finden
- [ ] Backup-Status parsen
- [ ] Warnung bei veraltetem Backup anzeigen
- [ ] Statusleiste-Integration

### Phase 8: Testing & Polishing (in Arbeit)

- [x] **Unit Tests für Kernfunktionen** *(v0.11.0, in Arbeit)*
  - **pytest als dev-dependency** installiert (war vorher verwaist im venv)
  - **34 Tests aktuell grün** (Laufzeit: ~4 Sekunden)
  - **Test-Suiten**:
    - `tests/test_file_manager.py` (3 Tests): PDF-Merge, PDF-Split, Fehlerbehandlung
    - `tests/test_llm_metadata_extraction.py` (10 Tests): JSON-Parser, Prompt-Builder
    - `tests/test_database_filters.py` (21 Tests): FTS5-Suche, alle Filter, Distinct-Helfer, Index-Replacement, `update_pdf_path`, `bulk_index_directory`
  - **End-to-End Smoke-Test**: Bislang manuell vor jedem Commit (sollte automatisiert werden)
  - **Was noch fehlt**: Tests für `HybridClassifier` (Herzstück der ML/LLM-Logik), `FileManager` (Move/Rename-Pfade), GUI-Tests (erfordern pytest-qt)
- [ ] Error Handling verbessern (laufend)
- [ ] Installer erstellen (PyInstaller) — `installer.iss` existiert bereits, Build-Skript fehlt
- [x] **Dokumentation** *(v0.11.0, in Arbeit)*
  - Diese Datei (`ENTWICKLUNGSSTAND.md`) wird mit jedem Sprint aktualisiert
  - README.md vorhanden
  - Changelog inline unter [Changelog v0.13.0](#changelog-v0130)
- [ ] Startbildschirm optimieren (schnellere Thumbnail-Ladung, Caching vom letzten Start)
### Phase 9: Semi-Automatischer Workflow (offen)
- [ ] **Schaltfläche "(Semi)-Auto Rename"** in der Toolbar
- [ ] Erkennung von PDFs mit "nichtssagenden" Dateinamen (z.B. `YYYY-MM-DD-001.pdf`)
- [ ] Workflow: PDF anzeigen → LLM-Vorschlag → Bestätigen oder Anpassen → Nächste PDF
- [ ] Optional: Konfidenz-Schwelle für vollautomatische Umbenennung (z.B. >90%)
- [ ] Batch-Verarbeitung mit Mehrfachauswahl
- [ ] Fortschrittsanzeige bei Massenverarbeitung

### Phase 10: Verbesserte Benutzeroberfläche (offen)
- [ ] Drei-Spalten-Layout für Umbenennung:
  ```
  ┌─────────────┬──────────────────────┬─────────────────┐
  │ Navigation  │   PDF-Vorschau       │  Aktionen       │
  │ [Thumbnail] │   (großes PDF)       │ - Neuer Name    │
  │ [Thumbnail] │                      │ - Vorschläge    │
  │ [Thumbnail] │                      │ - Zielordner    │
  └─────────────┴──────────────────────┴─────────────────┘
  ```
- [ ] Große PDF-Vorschau mit Zoom und Scroll
- [ ] Mehrseitige PDFs blätterbar
- [ ] Text-Selektion zum Kopieren in Dateinamen
- [ ] Hervorhebung erkannter Schlüsselwörter
- [ ] **Grüner Haken** bei bereits umbenannten Thumbnails
- [ ] **Zielordner-Vorschlag im Umbenennen-Dialog** (PDF geöffnet → gleich Zielordner wählen)
- [ ] **LLM-Auswahl im Umbenennungsdialog**
  - Direkt im Dialog das LLM-Modell wechseln (nur Modelle für die ein Key hinterlegt ist)
  - "LLM-Vorschlag neu generieren"-Button im Dialog
- [ ] **Ausschließlich LLM-Vorschläge anzeigen** (keine ML-Vorschläge mehr)
  - Die ML-Vorschläge (TF-IDF) ergeben beim Umbenennen kaum brauchbare Hinweise
  - Stattdessen: bis zu **3 verschiedene LLM-Vorschläge** zur Auswahl
  - ML bleibt intern für Ordner-Sortierung erhalten, aber nicht im Umbenennen-Dialog sichtbar

### Phase 16: PDF-Metadaten direkt in PDF-Dateien schreiben (100% fertig)

**Inspiration: paperless-ai Vergleich (März 2026)**

Kernidee: Metadaten werden **dual** gespeichert — direkt als XMP-Standard in die PDF-Datei eingebettet **und** zusätzlich in der SQLite-Datenbank für schnelle Indizierung/Suche. Damit bleiben Metadaten portabel und bei der Datei, unabhängig vom Programm.

- [x] **pikepdf als neue Abhängigkeit** für XMP-Metadaten-Schreibzugriff *(v0.9.0)*
- [x] **Neues Modul `src/core/pdf_metadata.py`** *(v0.9.0)*
  - `PDFMetadata` Datenklasse für alle Metadaten-Felder
  - `write_metadata()` schreibt XMP + Info Dictionary in PDF
  - `read_metadata()` liest Metadaten aus PDF zurück
- [x] **Schreiben folgender Felder** bei Umbenennung:
  - `dc:title` → Dokumententitel (aus Umbenennung)
  - `dc:subject` → Kategorie (Rechnung, Vertrag, Steuer, ...)
  - `dc:description` → Kurzzusammenfassung (LLM-generiert)
  - `pdf:Keywords` → Erkannte Schlagworte (kommagetrennt)
  - Info Dictionary: Korrespondent, Buchungsdatum, Steuerjahr, Betrag, Währung, MwSt, SteuerlichAbsetzbar
- [x] **LLM-Prompt erweitert** für Metadaten-Extraktion *(v0.9.0)*
  - LLM extrahiert jetzt: Kategorie, Korrespondent, Betrag, Währung, MwSt, Steuerjahr, Zusammenfassung
  - Alle 3 Provider (Claude, OpenAI, Poe) unterstützen Metadaten in der Response
  - `_parse_response()` erkennt neue Felder (KATEGORIE, KORRESPONDENT, BETRAG, etc.)
- [x] **SQLite-Datenbank als Index-Spiegel** erweitert *(v0.9.0)*
  - `SortingHistory` um 8 neue Felder: `korrespondent`, `betrag`, `waehrung`, `mwst_satz`, `steuerjahr`, `steuerlich_absetzbar`, `kategorie`, `zusammenfassung`
  - Automatische Migration älterer Datenbanken
- [x] **Metadaten direkt beim Umbenennen setzen** *(v0.9.0)*
  - Umbenennungsdialog zeigt 7 editierbare Metadaten-Felder
  - LLM füllt Felder automatisch vor, Nutzer kann anpassen
  - Bei Vorschlag-Klick werden Metadaten des jeweiligen Vorschlags übernommen
  - Nach Bestätigung: Metadaten in PDF + DB geschrieben
- [x] **Kompatibilität** mit Paperless-ngx, DEVONthink, Adobe Acrobat (XMP + Info Dictionary)

### Phase 17: Volltext-Suche mit SQLite FTS5 (100% fertig)

- [x] **SQLite FTS5-Index** für extrahierten Dokumententext *(v0.9.0)*
  - Virtuelle Tabelle `document_search` mit unicode61-Tokenizer
  - Speichert: Volltext, Dateiname, Keywords, Korrespondent, Kategorie, Betrag, Steuerjahr, Zusammenfassung
- [x] **Suchleiste in der Toolbar** (Ctrl+F) *(v0.9.0)*
  - Live-Suche ab 2 Zeichen mit Prefix-Matching
  - Ergebnis-Anzeige im Detail-Panel mit Dateiname, Korrespondent, Kategorie, Betrag
  - Doppelklick auf Treffer öffnet die PDF
  - Treffer-Zähler in der Toolbar
- [x] **Suche über alle Felder**: Dateiinhalt, Dateiname, alle Metadaten
- [x] **Index wird beim Verschieben/Sortieren automatisch befüllt** *(v0.9.0)*
  - Sowohl im neuen 3-Spalten-Workflow als auch bei Drag&Drop
- [x] **Filter-Kombinationen** *(v0.11.0)* — Issue #18
  - **Ein-/ausklappbare Filterleiste** in der Toolbar (standardmäßig zugeklappt)
  - **Steuerjahr-Dropdown**, befüllt mit echten Werten aus der DB (`get_distinct_steuerjahre`)
  - **Kategorie-Dropdown** (`get_distinct_kategorien`)
  - **Korrespondent-Dropdown** (`get_distinct_korrespondenten`)
  - **Datumsbereich** (Von/Bis) mit aktivierbaren QDateEdit-Widgets
  - **Betragsbereich** (Von/Bis in €) via QDoubleSpinBox
  - **UND-Verknüpfung** aller aktiven Filter
  - **Live-Aktualisierung**: Treffer-Zähler aktualisiert sich in Echtzeit
  - **Wichtige Eigenschaft**: Text-Query ist *optional* — Filtern funktioniert auch ohne Suchwort
  - **Betrags-Cast**: TEXT-Spalte `betrag` wird via `CAST(NULLIF(betrag,'') AS REAL)` verglichen (robust gegen Leerwerte/Nicht-Zahlen)
  - **"Filter zurücksetzen"-Button** setzt alle Filter mit einem Klick zurück
  - Persistenz + Re-Index bei Sortier-Operationen
  - 12 Unit-Tests sichern die Logik ab (siehe Phase 8)

### Phase 18: Buchhaltungs- und Steuerfelder (NEU - Hohe Priorität)

Dedizierte Felder für deutschen Steuerbüro-Workflow — Feature das paperless-ai **nicht** hat:

- [ ] **LLM-Prompt-Erweiterung** für Steuer-/Buchhaltungsdaten:
  - Rechnungsbetrag (netto/brutto)
  - Mehrwertsteuersatz (7% / 19%)
  - IBAN / Kontonummer des Absenders
  - Steuerjahr (aus Datum abgeleitet)
- [ ] **Metadaten-Sidebar** im Hauptfenster (rechts neben Ordnerbaum):
  - Anzeige aller erkannten Felder für ausgewähltes PDF
  - Direkte Bearbeitung ohne externen PDF-Editor
  - Änderungen sofort in PDF + Datenbank schreiben
- [ ] **Steuer-Auswertung** (einfache Statistik):
  - Summe aller Rechnungen pro Steuerjahr
  - Summe steuerlich absetzbarer Beträge
  - Export als CSV für Steuerberater

### Phase 19: RAG-Chat / Dokumentensuche per natürlicher Sprache (NEU - Mittlere Priorität)

**Status:** ✅ fertig (M1 Foundation + M2 GUI + M3 Hardening + M4 Tests+Polish)

**Paperless-ai's stärkstes Feature** — Fragen wie:
- *"Was habe ich 2023 für Strom bezahlt?"*
- *"Zeig alle Verträge mit der GEZ"*
- *"Wann läuft meine Kfz-Versicherung ab?"*

- [ ] **Chat-Tab** im Hauptfenster (neben oder unter dem Thumbnail-Grid)
- [ ] Bestehende LLM-Provider (Claude/OpenAI/Poe) als Backend nutzen
- [ ] LLM erhält relevante Dokumente aus SQLite-Datenbank als Kontext
- [ ] **Antworten mit Quellenangabe** — klickbar öffnet das jeweilige PDF
- [ ] Konversationshistorie innerhalb einer Sitzung
- [ ] Offline-Fallback: Einfache Keyword-Suche wenn kein LLM konfiguriert

### Phase 20: Korrespondenten-Verwaltung (NEU - Mittlere Priorität)

**Status:** ✅ fertig (Issue #21 closed)

Analog zu paperless-ai: Erkannte Firmen/Personen als persistente Kontakte:

- [ ] **Korrespondenten-Liste** aus Sortierhistorie automatisch aufbauen
- [ ] Neue Datenbanktabelle `Korrespondent` (Name, Alias-Liste, Kategorie, Farbe)
- [ ] **Automatische Erkennung** per LLM oder Regex
- [ ] Filterbar im Hauptfenster (Klick auf Korrespondent → zeigt alle PDFs)
- [ ] Wird in PDF-XMP-Metadaten als `custom:Korrespondent` persistiert

### Phase 21: Automatisierungs-Regeln (NEU - Mittlere Priorität)

**Status:** ✅ fertig (Issue #22 closed)

Paperless-ai ermöglicht Custom Rules — für bekannte Absender vollautomatisches Sortieren:

- [ ] **Regel-Editor** in den Einstellungen
- [ ] Regelstruktur: WENN [Bedingung] DANN [Aktion]
  ```
  WENN Korrespondent = "Finanzamt"
    UND Kategorie = "Steuerbescheid"
  DANN Zielordner = "Steuern/Bescheide/{Steuerjahr}"
       Steuerjahr-Feld = auto
       Tag = "steuerlich-relevant"
  ```
- [ ] Bedingungen: Korrespondent, Kategorie, Betrag-Bereich, Datumsbereich, Schlüsselwörter
- [ ] Aktionen: Zielordner setzen, Tag hinzufügen, Feld setzen, umbenennen
- [ ] Regeln werden **vor** manuellem Eingriff geprüft (vollautomatisch wenn Konfidenz >90%)

### Phase 11: Lokales LLM / Ollama (100% fertig)

- [x] **Provider `OllamaProvider`** für lokale Modelle (`src/ml/ollama_provider.py`)
- [x] **Native HTTP-API** (`http://localhost:11434`) — kein API-Key, volle Datenhoheit
- [x] **Auto-Start-Helper** (`src/ml/ollama_launcher.py`): Startet lokalen Server auf Wunsch
- [x] **JSON-Mode**: `"format": "json"` für deterministische strukturierte Antworten (v0.11.0)
- [x] **Robuste HTTP-Kommunikation** mit `urllib` (keine zusätzliche Dependency)
- [x] Timeout 120s (lokale Modelle brauchen auf Consumer-Hardware länger)
- [x] Modell-Liste via `/api/tags` zur Auswahl in den Einstellungen

**Empfohlene Modelle für RTX 3060 Ti (8GB VRAM):**

| Modell | VRAM | Qualität | Geschwindigkeit |
|--------|------|----------|-----------------|
| Llama 3.2 3B | ~4GB | Gut | Sehr schnell |
| Phi-3 Mini 3.8B | ~4GB | Gut | Sehr schnell |
| Mistral 7B Q4 | ~5GB | Sehr gut | Schnell |
| Llama 3.1 8B Q4 | ~6GB | Sehr gut | Mittel |
| Gemma 2 9B Q4 | ~7GB | Exzellent | Mittel |

---

## Priorisierung der offenen Phasen

| Phase | Feature | Aufwand | Nutzen | Priorität |
|-------|---------|---------|--------|-----------|
| **13** | **UX-Verbesserungen (Undo, Kopieren)** | **Mittel** | **Sehr Hoch** | ⭐⭐⭐⭐⭐ |
| **16** | **PDF-XMP-Metadaten schreiben** | **Mittel** | **Sehr Hoch** | ⭐⭐⭐⭐⭐ |
| **17** | **Volltext-Suche (FTS5)** | **Mittel** | **Sehr Hoch** | ⭐⭐⭐⭐** |
| **18** | **Buchhaltungs-/Steuerfelder + Sidebar** | **Mittel** | **Sehr Hoch** | ⭐⭐⭐⭐ |
| 9 | Semi-Auto Workflow | Mittel | Hoch | ⭐⭐⭐ |
| 20 | Korrespondenten-Verwaltung | Mittel | Hoch | ⭐⭐⭐ |
| 19 | RAG-Chat (natürliche Sprachsuche) | Hoch | Hoch | ⭐⭐⭐ |
| 21 | Automatisierungs-Regeln | Hoch | Hoch | ⭐⭐⭐ |
| 14 | PDF-Bearbeitung (Merge/Split) | Mittel | Mittel | ⭐⭐ |
| 15 | Layout-Optimierungen | Mittel | Mittel | ⭐⭐ |
| 10 | 3-Spalten-Layout | Hoch | Mittel | ⭐⭐ |
| 11 | Lokales LLM | Mittel | Mittel | ⭐⭐ |
| 8 | Testing & Polishing | Mittel | Hoch | ⭐⭐ |
| 7 | Backup-Integration | Niedrig | Niedrig | ⭐ |

**Empfehlung:** Phase 13 + 16 parallel angehen — UX-Verbesserungen für sofortigen Komfort, PDF-Metadaten als strategische Kernfunktion.

---

## Erledigte Items aus Benutzer-Feedback

Die folgenden Punkte aus `to do.md` wurden bereits umgesetzt:

| Feature | Status | Umsetzung |
|---------|--------|-----------|
| Neuen Ordner erstellen (Rechtsklick) | ✅ | Phase 12 - Kontextmenü in Baumansicht |
| Grüne Vorschlagsordner Bug | ✅ | Behoben |
| Doppelklick auf Ordner → Navigation | ✅ | Doppelklick wechselt Scan-Ordner |
| LLM erkennt Rechnungsnummer/Betreff | ✅ | LLM-Prompt erweitert |
| Scandatum statt Phantasiedatum | ✅ | Datei-Änderungsdatum als Fallback |
| LLM-Pre-Caching mit Flag (kein Re-Upload umbenannter Dateien) | ✅ | Phase 5 - Flag verhindert doppeltes Caching |
| Mehrere Thumbnails markieren → Batch-Umbenennung per LLM | ✅ | Shift+Klick Bereichsauswahl + Rechtsklick-Menü |
| Shift+Klick Bereichsauswahl + Toggle-Deselect | ✅ | pdf_thumbnail.py erweitert |
| Multi-Selektion beim Verschieben (mehrere PDFs gleichzeitig) | ✅ | Implementiert |
| Dreizeilige Ordnernamen in Vorschlags-Buttons | ✅ | v0.8.0 - folder_widget.py |
| Info-Dialog: Version + GitHub-Link + Lizenz | ✅ | v0.8.0 - main_window.py |
| Kopie erstellen (Rechtsklick-Menü) | ✅ | v0.8.0 - main_window.py |
| paperless-ai Funktionsvergleich + Roadmap Phase 16–21 | ✅ | März 2026 - ENTWICKLUNGSSTAND.md aktualisiert |
| Undo für Verschiebungen (alle Codepfade) | ✅ | v0.9.0 - Ctrl+Z, Undo-Stack mit 20 Einträgen |
| Umbenennung rückgängig (Ctrl+Z) | ✅ | v0.9.0 - Gemeinsamer Undo-Stack für Move+Rename |
| F2-Taste für Umbenennen | ✅ | v0.9.0 - Windows-Standard-Shortcut || Phase 19 RAG-Chat abgeschlossen (Issue #20) | ✅ | v0.12.0 - Chat-Tab, FTS5-Retrieval, LLM-Synthese, Citations, Offline-Fallback, Cancel, 112/112 Tests |

| De-Selektion (Klick auf leere Fläche / Escape) | ✅ | v0.9.0 - mousePressEvent + Escape-Shortcut |
| Zurück-Button (Ordner-History) | ✅ | v0.9.0 - ⬅ Button + Alt+Left + Menü |
| Phase 16: PDF-XMP-Metadaten schreiben | ✅ | v0.9.0 - pikepdf + LLM-Extraktion + Umbenennungsdialog |
| LLM extrahiert Betrag/MwSt/Steuerjahr/Korrespondent | ✅ | v0.9.0 - Erweiterter Prompt für alle 3 Provider |
| SortingHistory um 8 Metadaten-Felder erweitert | ✅ | v0.9.0 - Automatische Migration |
| Metadaten-Panel im Umbenennungsdialog | ✅ | v0.9.0 - 7 editierbare Felder |
| Bugfix: 'Neuer Dateiname' zeigte ML- statt LLM-Namen (Issue #24) | ✅ | v0.11.0 - name_input.setText + Cache-Rückschreibung in detail_panel |
| Bugfix: Orphan-Rows beim Verschieben (Pfad nicht aktualisiert) | ✅ | v0.11.0 - update_pdf_path() löst DELETE-old + INSERT-new atomar |
| LLM-Metadaten-Extraktion mit JSON-Mode + robustem Parser | ✅ | v0.11.0 - Regex-Parser, Ollama-Format-JSON, f-string-Fix |
| Filter-Kombinationen in Volltext-Suche (Issue #18) | ✅ | v0.11.0 - 5 Dropdown-Filter + Datums-/Betrags-Range, kombinierbar |
| Bulk-Index-Funktion für Verzeichnisse (RAG-Vorbereitung) | ✅ | v0.11.0 - bulk_index_directory() mit analyze=True/False |
| Test-Infrastruktur aufgebaut | ✅ | v0.11.0 - 34 pytest-Tests in 3 Suiten, alle grün |
| Phase 19 RAG-Chat (Issue #20) abgeschlossen | ✅ | v0.12.0 - Chat-Tab, FTS5-Retrieval, LLM-Synthese, Citations, Offline-Fallback, Cancel-Flow, 112/112 Tests |
| Phase 20 Korrespondenten-Verwaltung (Issue #21) abgeschlossen | ✅ | v0.13.0 - DB `korrespondenten` + Sidebar + Edit/Merge-Dialoge, auto_collect, 34 neue Tests |
| Phase 21 Automatisierungs-Regeln (Issue #22) abgeschlossen | ✅ | v0.13.0 - RuleEngine (5 Condition, 4 Action-Typen, Confidence) + Settings-Tab mit Editor, 23 neue Tests |


---

## Aktuelle Projektstruktur

```
PDF_Sortier_Meister/
├── run.py                      # Startskript
├── requirements.txt            # Python-Abhängigkeiten
├── README.md                   # Projektbeschreibung
├── LICENSE                     # MIT Lizenz
├── ENTWICKLUNGSSTAND.md        # Diese Datei
├── to do.md                    # Benutzer-Feedback & Ideen
├── src/
│   ├── __init__.py
│   ├── main.py                 # Haupteinstiegspunkt
│   ├── gui/
│   │   ├── __init__.py
│   │   ├── main_window.py      # Hauptfenster (Version 0.7.1)
│   │   ├── pdf_thumbnail.py    # PDF-Miniaturansicht Widget (mit Drag & Drop)
│   │   ├── folder_widget.py    # Zielordner-Widget
│   │   ├── folder_tree_widget.py # Ordner-Baumansicht (Phase 12)
│   │   ├── rename_dialog.py    # Verbesserter Umbenennungsdialog
│   │   └── settings_dialog.py  # Einstellungsdialog (erweitert)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── pdf_analyzer.py     # PDF-Analyse, OCR, Thumbnails
│   │   ├── pdf_cache.py        # Analyse-Cache mit LLM-Pre-Caching
│   │   ├── pdf_metadata.py     # XMP-Metadaten in PDF schreiben (Phase 16)
│   │   └── file_manager.py     # Dateisystem-Operationen (erweitert)
│   ├── ml/
│   │   ├── __init__.py
│   │   ├── classifier.py       # Lernfähiger Klassifikator (erweitert)
│   │   ├── llm_provider.py     # LLM Provider-Abstraktion (text_limit)
│   │   ├── claude_provider.py  # Claude API Provider
│   │   ├── openai_provider.py  # OpenAI API Provider
│   │   ├── poe_provider.py     # Poe.com API Provider
│   │   └── hybrid_classifier.py # Hybrid TF-IDF + LLM
│   └── utils/
│       ├── __init__.py
│       ├── config.py           # Konfigurationsverwaltung
│       └── database.py         # SQLite-Datenbank (erweitert)
└── data/
    └── model/                  # Gespeicherte ML-Modelle
```

---

## Installierte Abhängigkeiten

Alle Pakete aus `requirements.txt` wurden installiert:
- PyQt6 6.10.1
- PyMuPDF 1.26.7
- pytesseract 0.3.13
- scikit-learn 1.8.0
- SQLAlchemy 2.0.45
- python-dateutil 2.9.0
- watchdog 6.0.0
- pikepdf 10.5.1 *(NEU in v0.9.0 — Phase 16)*

**Optional für LLM-Integration:**
- anthropic (für Claude API direkt)
- openai (für OpenAI API direkt oder Poe.com)

```bash
pip install anthropic openai
```

**Tipp:** Mit einem Poe.com Account benötigen Sie nur `openai` und haben Zugang zu vielen Modellen (GPT, Claude, Gemini, Llama, etc.).

**Hinweis:** Für OCR muss Tesseract separat installiert werden.

---

## LLM-Integration (Phase 6)

Die LLM-Integration ermöglicht optional bessere Klassifikations- und Benennungsvorschläge:

### Funktionsweise
1. **Lokaler TF-IDF** wird immer zuerst verwendet (schnell, kostenlos)
2. **LLM wird automatisch hinzugezogen** wenn:
   - Lokale Konfidenz unter 60% liegt
   - Keine lokalen Vorschläge gefunden wurden
3. **Hybrid-Kombination**: Bei Übereinstimmung wird Konfidenz erhöht

### Neue Einstellungen (v0.7.1)
- **Text-Limit**: Konfigurierbar 500-5000 Zeichen (Default: 1500)
- **LLM-Pre-Caching**: Ein/Ausschaltbar für Debugging

### Konfiguration
1. Menü: Extras → Einstellungen
2. Tab: KI-Assistent (LLM)
3. Provider auswählen (Claude, OpenAI oder Poe.com)
4. API-Key eingeben
5. Modell wählen
6. Optional: Auto-LLM aktivieren

### Unterstützte Provider & Modelle

**Anthropic Claude** (direkt):
- haiku (günstig), sonnet (ausgewogen), opus (beste Qualität)

**OpenAI GPT** (direkt):
- gpt-4o-mini (günstig), gpt-4o (ausgewogen), gpt-4-turbo (beste Qualität)

**Poe.com** (empfohlen - viele Modelle mit einem Account):
- GPT-4o, GPT-4o-Mini, GPT-5
- Claude-3.5-Sonnet, Claude-3-Haiku
- Gemini-2-Flash, Gemini-Pro
- Llama-3.1-405B, Mistral-Large
- API-Key: [poe.com/api_key](https://poe.com/api_key)

---

## Nächste Schritte (Empfehlung)

### Sofort (Phase 13 - verbleibende UX-Verbesserungen):

1. **Drag & Drop Haptik** - Visuelles Feedback in Listenansicht
2. **Mehrere LLM API-Keys verwalten** - Schnelles Umschalten zwischen Providern

### Nächstes (Phase 17+18 - Suche & Steuerfelder):

3. **FTS5-Volltext-Index** aufbauen und Such-Leiste im Hauptfenster integrieren
4. **Metadaten-Sidebar** mit editierbaren Steuer-/Buchhaltungsfeldern

### Mittelfristig (Phase 9 - Semi-Auto Workflow):

5. **Batch-Umbenennung** mit LLM-Unterstützung
   - Mehrere PDFs auf einmal umbenennen
   - Fortschrittsanzeige

---

## Wettbewerbsanalyse: paperless-ai (März 2026)

Vergleich mit [paperless-ai](https://github.com/clusterzx/paperless-ai) (Add-On für Paperless-ngx):

| Feature | paperless-ai | PDF Sortier Meister | Geplant |
|---|---|---|---|
| Automatisches Tagging per LLM | Ja | Ja (Hybrid TF-IDF+LLM) | — |
| Dokumententyp-Klassifizierung | Ja | Ja (10 Kategorien) | — |
| Korrespondenten-Erkennung | Ja | Teilweise (Firmenname) | Phase 20 |
| Metadaten direkt in PDF schreiben | Nein | **Ja (v0.9.0)** | — |
| Steuerjahr / Buchhaltungsfelder | Nein | **Ja (v0.9.0)** | Phase 18 (Sidebar) |
| Betrag / MwSt-Extraktion | Nein | **Ja (v0.9.0)** | — |
| Volltext-Suche | Nein | **Ja (v0.9.0)** | — |
| RAG-Chat (natürliche Sprache) | Ja | Nein | Phase 19 |
| Automatisierungs-Regeln | Ja | Nein | Phase 21 |
| Desktop-Anwendung (offline) | Nein (Web) | Ja | — |
| Lokales LLM (Ollama) | Ja | Nein | Phase 11 |
| Drag & Drop Sortierung | Nein | Ja | — |
| Lernsystem (TF-IDF) | Nein | Ja | — |
| PDF-Merge/Split | Nein | Nein | Phase 14 |

**Strategischer Vorteil:** PDF Sortier Meister ist die einzige Lösung mit Metadaten **direkt in der PDF-Datei** (Dual-Layer: XMP + SQLite-Index). Dadurch bleiben alle Metadaten portabel und unabhängig von einem Server/Datenbank-Backend.

---

## Bekannte Einschränkungen

1. OCR funktioniert nur mit installiertem Tesseract
2. LLM-Nutzung erfordert API-Key und verursacht Kosten
3. Grüne Vorschlagsordner können bei vielen Ordnern unübersichtlich werden
4. **DB-Architektur ist path-zentriert** (Issue #25): Bei einem Pfadwechsel müssen alle Metadaten migriert werden. Stabile `pdf_id` als Refactoring geplant (nach Phase 19).
5. **Lokal laufendes Ollama kann bei großen Texten langsam sein** — Timeout in `ollama_provider.py` auf 120s gesetzt

---

## Zum Starten

```bash
cd "..\\PDF_Sortier_Meister"
python run.py
```


---

## Changelog v0.13.0

**Release-Datum:** 14.06.2026
**Fokus:** Robustheit, LLM-Metadaten-Extraktion, Such-Filter, Test-Grundlage

### ✨ Neue Features

- **Strukturierte JSON-LLM-Antworten** (Phase 6)
  - Alle Provider (Claude, OpenAI, Poe, Ollama) liefern JSON statt Freitext
  - Erweitertes Metadaten-Schema inkl. Steuer-/Buchhaltungs-Feldern
  - Ollama nutzt nativen `format: json` Mode
- **Filter-Kombinationen in der Volltext-Suche** (Issue #18, Phase 17)
  - 5 kombinierbare Filter: Steuerjahr, Kategorie, Korrespondent, Datumsbereich, Betragsbereich
  - Ein-/ausklappbare Filterleiste mit Live-Trefferzähler
  - Filter funktionieren auch ohne Suchwort
- **Bulk-Import für Verzeichnisse** (Vorbereitung Phase 19 RAG)
  - `Database.bulk_index_directory(folder, recursive, analyze)` — scannt Tausende bereits getaggte PDFs
  - Zwei Modi: `analyze=True` (volle Pipeline) oder `analyze=False` (nur Registrierung, schnell)
- **Move-Pfad-Update mit Metadaten-Erhalt** (DB)
  - `Database.update_pdf_path(old, new, new_filename)` — atomar, erhält alle Metadaten
  - Behebt den Orphan-Row-Bug beim Verschieben

### 🐛 Bugfixes

- **Issue #24**: Mittleres Panel zeigte schlechten ML- statt LLM-Namen
  - Fix: `name_input.setText()` mit LLM-Filename in `_request_llm_metadata()`
  - LLM-Vorschläge werden in PDF-Cache zurückgeschrieben
- **Orphan-Row-Bug beim Verschieben**: Alte Pfad-Einträge blieben im FTS5-Index stehen
  - Fix: `update_pdf_path()` mit atomarer DELETE-old + INSERT-new Transaktion
- **f-string Syntax-Fehler in LLM-Prompts**: JSON-Schemas mit ungeschweiften Klammern
  - Fix: Alle literalen `{`/`}` in f-strings jetzt korrekt als `{{`/`}}` escaped

### 🧪 Tests & Qualitätssicherung

- **34/34 Unit-Tests grün** (Laufzeit: ~4s)
- Neue Test-Suiten:
  - `tests/test_llm_metadata_extraction.py` (10 Tests): JSON-Parser, Prompt-Builder
  - `tests/test_database_filters.py` (21 Tests): Filter-Logik, Distinct-Helfer, Bulk-Import
- `pytest` als dev-dependency hinzugefügt

### 🏗 Architektur-Entscheidungen

- **Option A umgesetzt** (path-basiert + Update-Helper) — Quick Win
- **Option B dokumentiert** (Issue #25): Master-Tabelle `pdfs` mit stabiler `pdf_id` als FK-Referenz
  - Geplant für NACH Phase 19 (RAG-Chat)
  - 2-3 Sprints Aufwand
  - Breaking-Change in der DB-Struktur, aber API-kompatibel

### 📝 Geänderte Dateien (Commits seit v0.10.0)

| Commit | Beschreibung |
|:--|:--|
| `4fa559b` | Phase 16 + LLM-Dateiname-Sync (#24) |
| `a2d1baf` | Phase 17: Filter-Kombinationen Volltext-Suche (#18) |
| `60ab155` | STAB: Move-Bugfix + bulk_index_directory (Vorbereitung RAG) |

### 🔗 Neue/aktualisierte GitHub-Issues

- **#18** Phase 17: Filter-Kombinationen in der Volltext-Suche — ✅ geschlossen
- **#24** Bugfix: 'Neuer Dateiname' im mittleren Panel — ✅ geschlossen
- **#25** Refactoring: 'pdfs' Master-Tabelle mit stabiler pdf_id — 📋 offen (Backlog)

### ⚠️ Bekannte Mängel / Ausblick

- Filter-Dropdowns laden erst beim ersten Aufklappen der Filterleiste
- HybridClassifier hat noch keine dedizierten Unit-Tests (nächster STAB-Sprint)
- Pfad-zentrierte DB-Architektur (Refactoring in #25 geplant)

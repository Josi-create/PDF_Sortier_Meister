# PDF Sortier Meister - Entwicklungsstand

**Datum:** 08.01.2026
**Aktuelle Version:** 0.7.1

---

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

**Aus Benutzer-Feedback (to do.md):**

- [ ] **Drag & Drop Haptik verbessern** (to do #1)
  - Besseres visuelles Feedback beim Ziehen
  - Farb-Highlighting auch in der Listenansicht (nicht nur Vorschlagsbereich)

- [ ] **Undo für Verschiebungen** (to do #2)
  - Nach dem Verschieben: Möglichkeit zum Zurückverschieben
  - History der letzten Aktionen

- [ ] **Kopieren-Option** (to do #9)
  - PDF in mehrere Ordner kopieren (z.B. Versicherung UND Steuer)
  - Kontextmenü-Option "Kopieren nach..."

- [ ] **Zielordner-Dialog Startpfad** (to do #4)
  - "+ Zielordner" öffnet im aktuellen/übergeordneten Ordner

- [ ] **Zurück-Button** (to do #7)
  - Navigation zum vorherigen Scan-Ordner
  - Breadcrumb-Navigation

- [ ] **Umbenennung rückgängig** (to do #11)
  - Rechtsklick auf Thumbnail → "Umbenennung rückgängig"

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

### Phase 8: Testing & Polishing (offen)
- [ ] Unit Tests für Kernfunktionen
- [ ] Error Handling verbessern
- [ ] Installer erstellen (PyInstaller)
- [ ] Dokumentation
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

### Phase 11: Lokales LLM / Ollama (offen)
- [ ] Neuer Provider: `OllamaProvider` für lokale Modelle
- [ ] API-Endpunkt: `http://localhost:11434/v1/chat/completions`
- [ ] Kein API-Key erforderlich, volle Datenschutz-Kontrolle

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
| **13** | **UX-Verbesserungen (Undo, Kopieren)** | **Mittel** | **Sehr Hoch** | ⭐⭐⭐⭐ |
| 9 | Semi-Auto Workflow | Mittel | Hoch | ⭐⭐⭐ |
| 14 | PDF-Bearbeitung (Merge/Split) | Mittel | Mittel | ⭐⭐ |
| 15 | Layout-Optimierungen | Mittel | Mittel | ⭐⭐ |
| 10 | 3-Spalten-Layout | Hoch | Mittel | ⭐⭐ |
| 11 | Lokales LLM | Mittel | Mittel | ⭐⭐ |
| 8 | Testing & Polishing | Mittel | Hoch | ⭐⭐ |
| 7 | Backup-Integration | Niedrig | Niedrig | ⭐ |

**Empfehlung:** Phase 13 (UX-Verbesserungen) als nächstes - direktes Benutzer-Feedback!

---

## Erledigte Items aus Benutzer-Feedback

Die folgenden Punkte aus `to do.md` wurden bereits umgesetzt:

| # | Feature | Status | Umsetzung |
|---|---------|--------|-----------|
| 3 | Neuen Ordner erstellen (Rechtsklick) | ✅ | Phase 12 - Kontextmenü in Baumansicht |
| 5 | Grüne Vorschlagsordner Bug | ✅ | Behoben |
| 6 | Doppelklick auf Ordner → Navigation | ✅ | Doppelklick wechselt Scan-Ordner |
| 10 | LLM erkennt Rechnungsnummer/Betreff | ✅ | LLM-Prompt erweitert |
| 12 | Scandatum statt Phantasiedatum | ✅ | Datei-Änderungsdatum als Fallback |

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

### Sofort (Phase 13 - UX-Verbesserungen):

1. **Undo für Verschiebungen** - Wichtigstes Benutzer-Feedback
   - History-Stack für letzte Aktionen
   - Rechtsklick → "Rückgängig" oder Ctrl+Z

2. **Kopieren-Option** - Für Dokumente die mehrfach abgelegt werden
   - Kontextmenü erweitern
   - "Kopieren nach..." neben "Verschieben nach..."

3. **Drag & Drop Haptik** - Visuelles Feedback in Listenansicht

### Danach (Phase 9 - Semi-Auto Workflow):

4. **Batch-Umbenennung** mit LLM-Unterstützung
   - Mehrere PDFs auf einmal umbenennen
   - Fortschrittsanzeige

---

## Bekannte Einschränkungen

1. OCR funktioniert nur mit installiertem Tesseract
2. LLM-Nutzung erfordert API-Key und verursacht Kosten
3. Grüne Vorschlagsordner können bei vielen Ordnern unübersichtlich werden

---

## Zum Starten

```bash
cd "e:\Users\johan_000\OneDrive\VisualStudioCode Stuff\PDF_Sortier_Meister"
python run.py
```

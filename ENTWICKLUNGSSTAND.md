# PDF Sortier Meister - Entwicklungsstand

**Datum:** 08.01.2026
**Aktuelle Version:** 0.6.0

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

---

## Noch offene Phasen

### Phase 5: GUI-Vervollständigung / Drag & Drop (offen)
- [ ] Drag & Drop von PDF-Thumbnails auf Ordner
- [ ] Visuelles Feedback beim Ziehen
- [ ] Mehrfachauswahl von PDFs
- [ ] Verbessertes Layout

### Phase 7: Backup-Integration (offen)
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
- [ ] **LLM-Antworten cachen** (beim Wechsel zwischen PDFs bleiben Vorschläge erhalten)
- [ ] **Pre-Caching im Hintergrund** (LLM für nächste PDFs vorbereiten während User arbeitet)

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
| 9 | Semi-Auto Workflow | Mittel | Hoch | ⭐⭐⭐ |
| 5 | Drag & Drop | Mittel | Mittel | ⭐⭐ |
| 10 | 3-Spalten-Layout | Hoch | Mittel | ⭐⭐ |
| 11 | Lokales LLM | Mittel | Mittel | ⭐⭐ |
| 7 | Backup-Integration | Niedrig | Niedrig | ⭐ |
| 8 | Testing & Polishing | Mittel | Hoch | ⭐⭐ |

**Empfehlung:** Phase 9 (Semi-Auto Workflow) oder Phase 5 (Drag & Drop) als nächstes.

---

## Aktuelle Projektstruktur

```
PDF_Sortier_Meister/
├── run.py                      # Startskript
├── requirements.txt            # Python-Abhängigkeiten
├── README.md                   # Projektbeschreibung
├── LICENSE                     # MIT Lizenz
├── ENTWICKLUNGSSTAND.md        # Diese Datei
├── src/
│   ├── __init__.py
│   ├── main.py                 # Haupteinstiegspunkt
│   ├── gui/
│   │   ├── __init__.py
│   │   ├── main_window.py      # Hauptfenster (Version 0.6.0)
│   │   ├── pdf_thumbnail.py    # PDF-Miniaturansicht Widget
│   │   ├── folder_widget.py    # Zielordner-Widget
│   │   ├── folder_tree_widget.py # Ordner-Baumansicht (NEU Phase 12)
│   │   ├── rename_dialog.py    # Verbesserter Umbenennungsdialog
│   │   └── settings_dialog.py  # Einstellungsdialog
│   ├── core/
│   │   ├── __init__.py
│   │   ├── pdf_analyzer.py     # PDF-Analyse, OCR, Thumbnails
│   │   └── file_manager.py     # Dateisystem-Operationen (erweitert)
│   ├── ml/
│   │   ├── __init__.py
│   │   ├── classifier.py       # Lernfähiger Klassifikator (erweitert)
│   │   ├── llm_provider.py     # LLM Provider-Abstraktion
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

1. **Phase 5 (Drag & Drop)** - Macht die Bedienung intuitiver:
   - PDFs auf Ordner ziehen zum Sortieren
   - Mehrfachauswahl ermöglichen

2. **Testen** - Das Programm mit echten PDFs testen:
   ```bash
   python run.py
   ```

3. **LLM testen** - Mit Claude oder OpenAI API-Key:
   - Extras → Einstellungen → KI-Assistent
   - API-Key eingeben und testen

4. **Phase 7** - Backup-Integration (niedrigere Priorität)

---

## Bekannte Einschränkungen

1. OCR funktioniert nur mit installiertem Tesseract
2. Drag & Drop von PDFs auf Ordner noch nicht implementiert
3. Keine Mehrfachauswahl von PDFs möglich
4. LLM-Nutzung erfordert API-Key und verursacht Kosten

---

## Zum Starten

```bash
cd "e:\Users\johan_000\OneDrive\VisualStudioCode Stuff\PDF_Sortier_Meister"
python run.py
```

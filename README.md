# PDF Sortier Meister

Ein intelligentes Desktop-Programm zum Sortieren, Umbenennen und Verwalten von gescannten PDF-Dokumenten — mit lernfähiger KI-Klassifikation und optionaler LLM-Integration.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)
![Version](https://img.shields.io/badge/Version-0.8.0-orange.svg)

---

## Features

### Kernfunktionen

- **PDF-Vorschau**: Thumbnails aller PDFs im Scan-Ordner als responsives Grid
- **Intelligente Sortierung**: Vorschläge für Zielordner basierend auf PDF-Inhalt (TF-IDF + optional LLM)
- **Lernfähig**: Das System lernt aus jeder Sortier- und Umbenennungsentscheidung und verbessert seine Vorschläge kontinuierlich
- **Hierarchische Ordnerstruktur**: Vollständige Unterstützung für verschachtelte Ordner mit Baumansicht
- **Intelligente Umbenennung**: Automatische Namensvorschläge aus:
  - Erkannten Datumsangaben (deutsch: TT.MM.JJJJ, geschriebene Monate, ISO)
  - Dokumentkategorien (Rechnung, Vertrag, Steuer, Versicherung, Bank, Gehalt, ...)
  - Firmen- und Absendernamen (Regex-basiert)
  - Gelernten Mustern aus der Umbenennungshistorie
- **OCR-Unterstützung**: Texterkennung für gescannte Dokumente via Tesseract (Deutsch)
- **Drag & Drop**: PDFs per Drag & Drop in Zielordner verschieben — mit visuellem Feedback
- **Mehrfachauswahl**: Shift+Klick für Bereichsauswahl, Ctrl+Klick für Einzelauswahl; Batch-Verschieben/Kopieren
- **Undo**: Letzte Verschiebungen rückgängig machen
- **Kopieren**: PDF in mehrere Ordner kopieren (z.B. Versicherung UND Steuer)

### KI & Klassifikation

- **Hybrid-Klassifikator**: Kombiniert lokales TF-IDF mit optionalem LLM
  - Lokales Modell immer zuerst (schnell, kostenlos, offline)
  - LLM automatisch hinzugezogen wenn lokale Konfidenz < 60%
  - Gewichtung: 60% lokal + 40% LLM bei Übereinstimmung
- **LLM-Provider** (optional):
  - **Anthropic Claude** (Haiku, Sonnet, Opus)
  - **OpenAI GPT** (GPT-4o-mini, GPT-4o, GPT-4-turbo)
  - **Poe.com** (ein Account, viele Modelle: GPT, Claude, Gemini, Llama, Mistral)
- **LLM Pre-Caching**: LLM-Vorschläge werden im Hintergrund vorgeladen
- **Konfigurierbares Text-Limit**: 500–5000 Zeichen pro LLM-Anfrage (Default: 1500)

### Performance & Caching

- **Persistenter Analyse-Cache** (SQLite): Bereits analysierte PDFs werden nicht erneut verarbeitet — bleibt über Programmende erhalten
- **Hintergrund-Worker** mit Prioritätswarteschlange: UI bleibt immer reaktionsfähig
- **LRU-Thumbnail-Cache**: Flüssiges Scrollen durch viele PDFs

### GUI

- **Baumansicht** für hierarchische Ordnerstruktur mit Kontextmenü (Neuer Unterordner)
- **Doppelklick** auf Ordner wechselt den Scan-Ordner
- **Grün hervorgehobene** Vorschlagsordner in der Baumansicht
- **Statusleiste**: Trainingsstand, PDF-Anzahl, LLM-Status
- **Einstellungsdialog**: LLM-Konfiguration, Caching, Debug-Optionen
- **Info-Dialog** und integriertes Logging-System

---

## Geplante Features (Roadmap)

### Kurzfristig (Phase 16–18)

- **PDF-XMP-Metadaten schreiben**: Schlagworte, Kategorie, Korrespondent, Steuerjahr, Betrag direkt in die PDF-Datei einbetten (portabel, ISO-Standard, Dual-Layer mit SQLite-Index)
- **Volltext-Suche**: SQLite FTS5-Index mit Filterleiste (Steuerjahr, Kategorie, Datumsbereich, Betrag)
- **Buchhaltungs-/Steuerfelder**: LLM extrahiert Betrag, MwSt, Steuerjahr; editierbare Metadaten-Sidebar

### Mittelfristig (Phase 19–21)

- **RAG-Chat**: Dokumente per natürlicher Sprache befragen ("Was habe ich 2023 für Strom gezahlt?")
- **Korrespondenten-Verwaltung**: Bekannte Absender als persistente Kontakte
- **Automatisierungs-Regeln**: WENN/DANN-Regeln für bekannte Absender (vollautomatische Sortierung)
- **Lokales LLM (Ollama)**: Volle Datenschutzkontrolle, kein API-Key erforderlich

---

## Installation

### Voraussetzungen

- Python 3.10 oder höher
- Windows 10/11

### Abhängigkeiten installieren

```bash
git clone https://github.com/YOURUSERNAME/PDF_Sortier_Meister.git
cd PDF_Sortier_Meister
pip install -r requirements.txt
```

### OCR (optional, für gescannte Dokumente)

```bash
winget install UB-Mannheim.TesseractOCR
```

### LLM-Integration (optional)

```bash
pip install anthropic openai
```

### Starten

```bash
python run.py
```

---

## Verwendung

1. **Scan-Ordner wählen**: Toolbar → "Scan-Ordner" → Ordner mit gescannten PDFs auswählen
2. **Zielordner hinzufügen**: "+ Zielordner" oder Rechtsklick in der Baumansicht → "Neuer Unterordner"
3. **PDF auswählen**: Klick auf Thumbnail → Sortiervorschläge erscheinen (grün hervorgehoben)
4. **Sortieren**:
   - Klick auf einen vorgeschlagenen Ordner, oder
   - Drag & Drop auf beliebigen Ordner
5. **Umbenennen**: Rechtsklick → "Umbenennen..." → KI-Vorschläge mit Konfidenz auswählen
6. **LLM konfigurieren**: Extras → Einstellungen → KI-Assistent

Das System lernt aus jeder Entscheidung und verbessert seine Vorschläge kontinuierlich.

---

## Projektstruktur

```
PDF_Sortier_Meister/
├── run.py                          # Startskript
├── pyproject.toml                  # Paket-Konfiguration / PyInstaller
├── src/
│   ├── main.py                     # Haupteinstiegspunkt (v0.8.0)
│   ├── gui/
│   │   ├── main_window.py          # Hauptfenster
│   │   ├── pdf_thumbnail.py        # Thumbnail-Widget (Drag & Drop)
│   │   ├── folder_widget.py        # Zielordner-Widget
│   │   ├── folder_tree_widget.py   # Hierarchische Baumansicht
│   │   ├── rename_dialog.py        # Umbenennungsdialog mit KI-Vorschlägen
│   │   └── settings_dialog.py      # Einstellungen & LLM-Konfiguration
│   ├── core/
│   │   ├── pdf_analyzer.py         # PDF-Analyse, OCR, Thumbnails, Metadaten
│   │   ├── pdf_cache.py            # Persistenter Cache + LLM Pre-Caching
│   │   └── file_manager.py         # Datei- und Ordner-Operationen
│   ├── ml/
│   │   ├── classifier.py           # TF-IDF Klassifikator (lernfähig)
│   │   ├── hybrid_classifier.py    # Hybrid TF-IDF + LLM
│   │   ├── llm_provider.py         # Abstrakte Provider-Schnittstelle
│   │   ├── claude_provider.py      # Anthropic Claude
│   │   ├── openai_provider.py      # OpenAI GPT
│   │   └── poe_provider.py         # Poe.com (Multi-Modell)
│   └── utils/
│       ├── config.py               # Konfigurationsverwaltung
│       ├── database.py             # SQLite (Sortier- & Umbenennungshistorie)
│       └── logging_config.py       # Logging-System
```

---

## Technologien

| Bibliothek | Zweck |
|---|---|
| PyQt6 | Moderne Desktop-GUI |
| PyMuPDF (fitz) | PDF-Rendering, Textextraktion, Metadaten |
| pytesseract | OCR für gescannte Dokumente (Deutsch) |
| scikit-learn | TF-IDF Vektorisierung, Kosinus-Ähnlichkeit |
| SQLAlchemy | ORM für SQLite-Lernhistorie |
| anthropic | Claude API (optional) |
| openai | OpenAI / Poe.com API (optional) |
| pikepdf | PDF-XMP-Metadaten schreiben (geplant, Phase 16) |

---

## Lizenz

MIT License — siehe [LICENSE](LICENSE)

---

*Entwickelt mit Unterstützung von Claude Code*

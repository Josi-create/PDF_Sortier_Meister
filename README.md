# PDF Sortier Meister

Ein intelligentes Desktop-Programm zum Sortieren, Umbenennen und Verwalten von gescannten PDF-Dokumenten — mit lernfähiger KI-Klassifikation und optionaler LLM-Integration.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)
![Version](https://img.shields.io/badge/Version-0.10.0-orange.svg)

---

## ⚡ Schnellinstallation für DAUs

**Kein Python. Keine Konsole. Kein Ärger.** Nur Doppelklick.

### 📥 In 3 Schritten startklar

1. **Herunterladen:** 👉 [**PDF_Sortier_Meister_v0.10.0.zip**](https://github.com/Josi-create/PDF_Sortier_Meister/releases/latest/download/PDF_Sortier_Meister_v0.10.0.zip) *(ca. 150 MB)*
2. **Entpacken** irgendwo hin, z. B. nach `Dokumente\PDF_Sortier_Meister\`
3. **Doppelklick** auf `PDF_Sortier_Meister.exe` → fertig! 🎉

> 💡 Beim ersten Start erscheint sofort der Splash-Screen, während im Hintergrund die KI-Komponenten geladen werden.
>
> 🛡️ **Windows SmartScreen warnt?** Klick auf *"Weitere Informationen"* → *"Trotzdem ausführen"*. Das passiert bei unsignierten Apps — der Code ist auf GitHub öffentlich einsehbar.
>
> 🔗 Alle Versionen: [Releases-Seite](https://github.com/Josi-create/PDF_Sortier_Meister/releases)

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
- **Mehrfachauswahl**: Shift+Klick für Bereichsauswahl, Ctrl+Klick für Einzelauswahl; Batch-Verschieben und Batch-Umbenennung per LLM
- **Kopieren**: Rechtsklick → "Kopie erstellen" für Ablage in mehreren Ordnern (z.B. Versicherung UND Steuer)

### KI & Klassifikation

- **Hybrid-Klassifikator**: Kombiniert lokales TF-IDF mit optionalem LLM
  - Lokales Modell immer zuerst (schnell, kostenlos, offline)
  - LLM automatisch hinzugezogen wenn lokale Konfidenz < 60%
  - Gewichtung: 60% lokal + 40% LLM bei Übereinstimmung
- **LLM-Provider** (optional):
  - **Anthropic Claude** (Haiku, Sonnet, Opus)
  - **OpenAI GPT** (GPT-4o-mini, GPT-4o, GPT-4-turbo)
  - **Poe.com** (ein Account, viele Modelle: GPT, Claude, Gemini, Llama, Mistral)
  - **Ollama** (lokal, kein API-Key, volle Datenschutzkontrolle — *neu in v0.10.0*)
- **Benutzerdefiniertes Dateinamen-Muster** *(neu in v0.10.0)*: zwei vorgefertigte Vorlagen oder freier Freitext-Template, das die LLM beim Benennen imitiert
- **LLM Pre-Caching**: LLM-Vorschläge werden im Hintergrund vorgeladen
- **Konfigurierbares Text-Limit**: 500–5000 Zeichen pro LLM-Anfrage (Default: 1500)

### Performance & Caching

- **Persistenter Analyse-Cache** (SQLite): Bereits analysierte PDFs werden nicht erneut verarbeitet — bleibt über Programmende erhalten
- **Hintergrund-Worker** mit Prioritätswarteschlange: UI bleibt immer reaktionsfähig
- **LRU-Thumbnail-Cache**: Flüssiges Scrollen durch viele PDFs

### GUI

- **Baumansicht** für hierarchische Ordnerstruktur mit Kontextmenü (Neuer Unterordner)
- **Doppelklick** auf Ordner wechselt den Scan-Ordner
- **Grün hervorgehobene** Vorschlagsordner mit dreizeiligen Ordnernamen (auch bei langen Pfaden)
- **Erststart-Wizard** *(neu in v0.10.0)*: geführte 5-Seiten-Einrichtung beim ersten Start (Scan-Ordner, LLM-Provider, API-Key) — auch jederzeit über Extras → Einrichtungs-Assistent erneut aufrufbar
- **"Nur verschieben"-Toggle** *(neu in v0.10.0)*: roter Schiebeschalter im Detail-Panel — wenn aktiv, wird beim Klick auf einen Zielordner nur verschoben, ohne Umbenennen und ohne Metadaten-Schreiben
- **Helle Palette erzwungen** *(neu in v0.10.0)*: App ignoriert dunkle System-Themes und bleibt durchgängig lesbar (Fix für Issue #1)
- **Statusleiste**: Trainingsstand, PDF-Anzahl, LLM-Status
- **Einstellungsdialog**: LLM-Konfiguration, Caching, Debug-Optionen, Dateinamen-Muster-Tab
- **Info-Dialog** (Hilfe → Über): Version, GitHub-Link, Lizenzhinweis, LLM-Status, Lernstatistik
- **Integriertes Logging-System** mit rotierenden Log-Dateien (AppData/logs/)
- **SplashScreen** beim Programmstart

---

## Geplante Features (Roadmap)

### UX & Umbenennungsdialog (Phase 13 + 10)

- **Undo für Verschiebungen**: History-Stack, Ctrl+Z oder Rechtsklick → "Rückgängig"
- **Umbenennung rückgängig**: Rechtsklick auf Thumbnail → Original-Dateiname wiederherstellen
- **De-Selektion**: Klick auf leere Fläche oder nochmaliges Anklicken hebt Selektion auf
- **F2 für Umbenennen**: Windows-Standard-Shortcut für ausgewähltes PDF
- **Mehrere LLM API-Keys**: Schnelles Umschalten zwischen gespeicherten Profilen
- **Umbenennungsdialog**: LLM-Modell direkt im Dialog wählen + "Neu generieren"-Button
- **3 LLM-Vorschläge** statt ML-Vorschläge im Umbenennungsdialog (ML bleibt intern für Sortierung)

### Metadaten & Suche (Phase 16–18)

- **PDF-XMP-Metadaten schreiben**: Schlagworte, Kategorie, Korrespondent, Steuerjahr, Betrag direkt in die PDF-Datei einbetten — portabel, ISO-Standard, unabhängig vom Programm (Dual-Layer mit SQLite-Index)
- **Metadaten beim Umbenennen**: LLM schlägt gleichzeitig Steuerjahr, Betrag, Kategorie vor; Lerneffekt verbessert Genauigkeit über Zeit
- **Volltext-Suche**: SQLite FTS5-Index mit Filterleiste (Steuerjahr, Kategorie, Datumsbereich, Betrag)
- **Buchhaltungs-/Steuerfelder**: Editierbare Metadaten-Sidebar; Steuer-Auswertung (Summen pro Jahr, CSV-Export)

### KI-Erweiterungen (Phase 9, 19–21)

- **Semi-Auto Workflow**: "(Semi)-Auto Rename"-Button für Batch-Umbenennung mit LLM-Bestätigung
- **RAG-Chat**: Dokumente per natürlicher Sprache befragen (*"Was habe ich 2023 für Strom gezahlt?"*)
- **Korrespondenten-Verwaltung**: Bekannte Absender als persistente Kontakte, filterbar
- **Automatisierungs-Regeln**: WENN/DANN-Regeln für bekannte Absender (vollautomatische Sortierung)

### Weitere Features (Phase 14–15)

- **PDF-Bearbeitung**: Merge (Drag & Drop zweier PDFs) und Split (mehrseitiges PDF aufteilen)
- **Layout**: Responsive Grid-Spalten, Explorer-ähnliche Listenansicht, Konfidenz-Visualisierung

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
│   ├── main.py                     # Haupteinstiegspunkt (v0.10.0)
│   ├── gui/
│   │   ├── main_window.py          # Hauptfenster
│   │   ├── pdf_thumbnail.py        # Thumbnail-Widget (Drag & Drop)
│   │   ├── folder_widget.py        # Zielordner-Widget
│   │   ├── folder_tree_widget.py   # Hierarchische Baumansicht
│   │   ├── rename_dialog.py        # Umbenennungsdialog mit KI-Vorschlägen
│   │   ├── detail_panel.py         # Detail-Panel mit Move-Only-Toggle
│   │   ├── setup_wizard.py         # Erststart-Wizard (v0.10.0)
│   │   └── settings_dialog.py      # Einstellungen, LLM, Dateinamen-Muster
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
│   │   ├── poe_provider.py         # Poe.com (Multi-Modell)
│   │   └── ollama_provider.py      # Ollama (lokal, v0.10.0)
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

## Vergleich mit paperless-ngx

Siehe [Vergleich paperless-ngx.md](Vergleich%20paperless-ngx.md) für eine detaillierte Gegenüberstellung beider Programme.

---

## Lizenz

**GPL-3.0-or-later** — siehe [LICENSE](LICENSE)

Dieses Programm ist Freie/Open-Source-Software und steht unter der GNU General
Public License v3 (oder neuer). Du darfst es nutzen, weitergeben und verändern.

> **Warum GPL statt MIT?** Zwei Kernbibliotheken sind Copyleft: **PyQt6** (GPLv3)
> und **PyMuPDF** (AGPLv3). Ein daraus gebautes Gesamtwerk muss dieselbe Freiheit
> weitergeben — GPL-3.0-or-later ist die korrekte, ehrliche Lizenz dafür.

### Dritt-Bibliotheken (Lizenzübersicht)

| Bibliothek | Lizenz |
|------------|--------|
| PyQt6 | GPL v3 / kommerziell (Riverbank) |
| PyMuPDF | AGPL v3 / kommerziell (Artifex) |
| pikepdf | MPL-2.0 |
| scikit-learn, SQLAlchemy, numpy, python-dateutil, watchdog | BSD / permissiv |
| pytesseract | Apache-2.0 |
| anthropic, openai (optional) | MIT / Apache-2.0 |

---

*Entwickelt mit Unterstützung von Claude Code*

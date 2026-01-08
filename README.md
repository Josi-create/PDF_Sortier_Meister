# PDF Sortier Meister

Ein intelligentes Desktop-Programm zum Sortieren und Umbenennen von gescannten PDF-Dokumenten mit lernfähiger Klassifikation.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Features

- **PDF-Vorschau**: Thumbnails aller PDFs im Scan-Ordner
- **Intelligente Sortierung**: Vorschläge für Zielordner basierend auf PDF-Inhalt
- **Lernfähig**: Das System lernt aus Ihren Sortierentscheidungen
- **Intelligente Umbenennung**: Automatische Namensvorschläge basierend auf:
  - Erkannten Datumsangaben
  - Dokumentkategorien (Rechnung, Vertrag, etc.)
  - Firmennamen
  - Gelernten Mustern
- **OCR-Unterstützung**: Texterkennung für gescannte Dokumente (benötigt Tesseract)
- **TF-IDF Klassifikation**: Ähnlichkeitsbasierte Ordnervorschläge

## Screenshots

*Coming soon*

## Installation

### Voraussetzungen

- Python 3.10 oder höher
- Windows 10/11 (andere Betriebssysteme nicht getestet)

### Installation

1. Repository klonen:
```bash
git clone https://github.com/YOURUSERNAME/PDF_Sortier_Meister.git
cd PDF_Sortier_Meister
```

2. Abhängigkeiten installieren:
```bash
pip install -r requirements.txt
```

3. (Optional) Tesseract für OCR installieren:
```bash
winget install UB-Mannheim.TesseractOCR
```

### Starten

```bash
python run.py
```

## Verwendung

1. **Scan-Ordner auswählen**: Klicken Sie auf "Scan-Ordner" und wählen Sie den Ordner mit Ihren gescannten PDFs
2. **Zielordner hinzufügen**: Fügen Sie Ihre Zielordner über "+ Zielordner" hinzu
3. **PDF auswählen**: Klicken Sie auf eine PDF, um sie auszuwählen und Sortiervorschläge zu sehen
4. **Sortieren**: Klicken Sie auf einen Zielordner oder Vorschlag, um die PDF zu verschieben
5. **Umbenennen**: Rechtsklick auf eine PDF → "Umbenennen..." für intelligente Namensvorschläge

Das System lernt aus jeder Ihrer Entscheidungen und verbessert seine Vorschläge kontinuierlich.

## Projektstruktur

```
PDF_Sortier_Meister/
├── run.py                      # Startskript
├── requirements.txt            # Python-Abhängigkeiten
├── src/
│   ├── main.py                 # Haupteinstiegspunkt
│   ├── gui/
│   │   ├── main_window.py      # Hauptfenster
│   │   ├── pdf_thumbnail.py    # PDF-Miniaturansicht
│   │   ├── folder_widget.py    # Zielordner-Widget
│   │   └── rename_dialog.py    # Umbenennungsdialog
│   ├── core/
│   │   ├── pdf_analyzer.py     # PDF-Analyse, OCR, Thumbnails
│   │   └── file_manager.py     # Dateisystem-Operationen
│   ├── ml/
│   │   └── classifier.py       # TF-IDF Klassifikator
│   └── utils/
│       ├── config.py           # Konfigurationsverwaltung
│       └── database.py         # SQLite-Datenbank
```

## Technologien

- **PyQt6**: Moderne GUI-Bibliothek
- **PyMuPDF (fitz)**: PDF-Rendering und Textextraktion
- **pytesseract**: OCR für gescannte Dokumente
- **scikit-learn**: TF-IDF Vektorisierung und Ähnlichkeitsberechnung
- **SQLAlchemy**: Datenbankabstraktion für Lernhistorie

## Geplante Features

- [ ] Drag & Drop von PDFs auf Ordner
- [ ] LLM-Integration (Claude API) für bessere Vorschläge
- [ ] Backup-Status-Anzeige (Macrium Reflect)
- [ ] Mehrfachauswahl von PDFs

## Lizenz

MIT License - siehe [LICENSE](LICENSE) Datei

## Mitwirken

Beiträge sind willkommen! Bitte erstellen Sie einen Issue oder Pull Request.

---

*Entwickelt mit Unterstützung von Claude Code*

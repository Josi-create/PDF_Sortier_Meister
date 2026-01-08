Ein Programm, das mir hilft meine PDFs weg zu sortieren und umzubenennen.
Es soll in meinem "FrischGescannt" Verzeichnis die neu gescannten PDFs untersuchen, mir anzeigen und mir dann vorschläge machen, wo es hin sortiert werden soll (in welchen Ordner), wichtig ist, dass das Programm lernfähig ist.
z.B. wenn ich ein Dokument nach "Steuer 2026" sortiert haben will, soll es das Dokument untersuchen und mir künftig bei ähnlichen Dokumente auch vorschlagen, sie nach "Steuer 2026" zu verschieben. Es soll mich immer fragen: soll das Dokument nach z.B. "Steuer 2026" verschoben werden, oder wo ander hin? Wenn ich dann angebe: Nein nach "Steuer 2025" soll es auch "Steuer 2025" in die künftige Auswahlliste mit aufnehmen.
Das Programm soll in Windows laufen und eine grafische Benutzeroberfläche haben, am besten sollen kleine PDF-Minaturen angezeigt werden, die dann auf die Miniatur-Bildchen verschoben werden können.
Das Programm soll direkten Zugriff auf das Dateisystem haben.
Es soll auch eine Backup - Funktion haben, bzw es soll überprüfen, ob Macrium Reflect ein (inkrementelles) Backup durchgeführt hat in den letzten 7 Tagen.
Momentan sind im Ordner "Frisch Gescannt" überwiegend PDFs mit den Dateibezeichnungen YYYY-MM-DD-001.pdf. Das Programm soll die PDFs analysieren und Vorschläge machen, wie der Dateiname sinnvoll umbenannt weden könnte, z.B "Rechnung Handwerker Meier Heizkörper Mai 2025.pdf"

-----------------------------------------------

# Vorschläge für weitere Verbesserungen

## Phase 9: Semi-Automatischer Workflow

### 9.1 Auto-Rename Funktion
- **Schaltfläche "(Semi)-Auto Rename"** in der Toolbar
- Alle PDFs mit "nichtssagenden" Dateinamen (z.B. `YYYY-MM-DD-001.pdf`) werden erkannt
- PDFs werden der Reihe nach aufgerufen und können schnell abgearbeitet werden
- Workflow: PDF anzeigen → LLM-Vorschlag → Bestätigen oder Anpassen → Nächste PDF
- Optional: Konfidenz-Schwelle für vollautomatische Umbenennung (z.B. >90%)

### 9.2 Batch-Verarbeitung
- Mehrfachauswahl von PDFs ermöglichen
- Gleiche Kategorie für mehrere PDFs auf einmal zuweisen
- Fortschrittsanzeige bei Massenverarbeitung

---

## Phase 10: Verbesserte Benutzeroberfläche

### 10.1 Drei-Spalten-Layout für Umbenennung
```
┌─────────────┬──────────────────────┬─────────────────┐
│ Navigation  │   PDF-Vorschau       │  Aktionen       │
│             │   (großes PDF)       │                 │
│ [Thumbnail] │                      │ - Neuer Name    │
│ [Thumbnail] │   ┌──────────────┐   │ - Vorschläge    │
│ [Thumbnail] │   │              │   │ - Zielordner    │
│ [Thumbnail] │   │   Seite 1    │   │                 │
│ [Thumbnail] │   │              │   │ [Umbenennen]    │
│ [Thumbnail] │   └──────────────┘   │ [Überspringen]  │
│             │                      │ [Löschen]       │
└─────────────┴──────────────────────┴─────────────────┘
```

### 10.2 PDF-Viewer Integration
- Große PDF-Vorschau mit Zoom und Scroll
- Mehrseitige PDFs blätterbar
- Text-Selektion zum Kopieren in Dateinamen
- Hervorhebung erkannter Schlüsselwörter

---

## Phase 11: Lokales LLM (Datenschutz)

### 11.1 Lokale KI-Modelle
Für Desktop-PCs mit NVIDIA RTX 3060 Ti (8GB VRAM) geeignete Modelle:

| Modell | VRAM | Qualität | Geschwindigkeit |
|--------|------|----------|-----------------|
| **Llama 3.2 3B** | ~4GB | Gut | Sehr schnell |
| **Phi-3 Mini 3.8B** | ~4GB | Gut | Sehr schnell |
| **Mistral 7B Q4** | ~5GB | Sehr gut | Schnell |
| **Llama 3.1 8B Q4** | ~6GB | Sehr gut | Mittel |
| **Gemma 2 9B Q4** | ~7GB | Exzellent | Mittel |

### 11.2 Integration über Ollama
```bash
# Installation
winget install Ollama.Ollama

# Modell laden
ollama pull llama3.2:3b
# oder für bessere Qualität:
ollama pull mistral:7b-q4_K_M
```

### 11.3 Implementierung
- Neuer Provider: `OllamaProvider` für lokale Modelle
- API-Endpunkt: `http://localhost:11434/v1/chat/completions`
- Kein API-Key erforderlich
- Volle Datenschutz-Kontrolle - keine Daten verlassen den PC

---

## Phase 12: Hierarchische Ordnerstruktur

### 12.1 Unterordner-Unterstützung
Beispiel-Struktur:
```
📁 Steuer 2026/
   ├── 📁 Banken/
   ├── 📁 Belege/
   └── 📁 Bescheide/
📁 Steuer 2025/
   ├── 📁 Banken/
   └── 📁 Belege/
📁 Nebenkosten 2026/
   ├── 📁 Heizung/
   ├── 📁 Versicherung/
   └── 📁 Strom/
```

### 12.2 Intelligentes Lernen der Hierarchie
- Beim Sortieren wird der **vollständige Pfad** gelernt (z.B. `Steuer 2026/Banken`)
- Bei ähnlichen Dokumenten wird der passende Unterordner vorgeschlagen
- Automatische Erkennung von Jahres-Mustern (2025 → 2026)
- Kategorie-übergreifendes Lernen (Banken in Steuer ≈ Banken in Nebenkosten)

### 12.3 Ordner-Browser mit Baumansicht
```
📁 Zielordner
├── 📁 Steuer 2026          [5 PDFs]
│   ├── 📁 Banken           [2 PDFs]
│   ├── 📁 Belege           [3 PDFs]
│   └── 📁 Bescheide        [0 PDFs]
└── 📁 Nebenkosten 2026     [8 PDFs]
    ├── 📁 Heizung          [4 PDFs]
    └── 📁 Versicherung     [4 PDFs]
```

---

## Priorisierung

| Phase | Feature | Aufwand | Nutzen | Priorität |
|-------|---------|---------|--------|-----------|
| 12 | Unterordner-Struktur | Mittel | Hoch | ⭐⭐⭐ |
| 9 | Semi-Auto Workflow | Mittel | Hoch | ⭐⭐⭐ |
| 10 | 3-Spalten-Layout | Hoch | Mittel | ⭐⭐ |
| 11 | Lokales LLM | Mittel | Mittel | ⭐⭐ |

**Empfehlung:** Phase 12 (Unterordner) zuerst, da es die alltägliche Nutzung am meisten verbessert.

--------------------------

Ich schreibe ein Programm zum KI-gestützten sortieren von gescannten PDF files, sozusagen ein KI gestütztes Dokumenten-Managment-System auf Fileebene (Windows 11, Python). Motivation war in erster linie, dass Nuance Paperport seit 10 Jahren nicht weiterentwickelt wurde und ich dieses Programm sehr geschätzt habe. Ich würde gerne Beta-Tester dazu einladen, mein Programm zu nutzen sowie andere Entwickler, am Projekt mitzuarbeiten. Falls jemand im Internet nach "Nuance Paperport Nachfolge" oder DMS auf Fileebene sucht, soll er auf mein Projekt aufmerksam gemacht werden.


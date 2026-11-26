# Erste Schritte

PDF Sortier Meister (kurz PDFSM) sortiert gescannte PDFs in deine eigenen Ordner, benennt sie
sinnvoll um und findet sie später wieder. Alles läuft auf deinem Rechner; die Dateien bleiben
ganz normale PDFs in ganz normalen Ordnern (auch in OneDrive).

## Installation

- **Windows:** `PDF_Sortier_Meister_Setup.exe` von der Release-Seite auf GitHub laden und starten.
  Windows warnt beim ersten Start („Der Computer wurde durch Windows geschützt“), weil das Programm
  noch nicht signiert ist: auf „Weitere Informationen“ und dann „Trotzdem ausführen“ klicken.
  Wer nichts installieren möchte, nimmt das portable ZIP.
- **macOS:** Die passende DMG laden (Apple Silicon oder Intel), öffnen und „PDF Sortier Meister“
  auf „Applications“ ziehen.
- Die Texterkennung (OCR, Tesseract) ist in beiden Fassungen enthalten.
- **Update:** Die neue Version einfach über die alte installieren. Einstellungen und Lerndaten
  bleiben erhalten. **Hilfe › Nach Updates suchen…** prüft, ob es eine neuere Version gibt.

## Der Einrichtungs-Assistent

Beim ersten Start führt ein Assistent durch die Einrichtung:

1. **Scan-Ordner:** der Ordner, in dem neue Scans landen.
2. **Zielordner:** die Ordner, in die du sortierst (z. B. `Steuer 2026`, `Versicherungen`).
3. **KI-Anbieter (freiwillig):** Der Assistent prüft die Grafikkarte und empfiehlt ein lokales
   Modell oder einen Cloud-Anbieter. Ohne KI funktioniert das Sortieren trotzdem.
4. **Dokumentensuche (freiwillig):** Ordner und Laufwerke, die durchsucht werden sollen.

Den Assistenten kannst du jederzeit über **Extras › Einrichtungs-Assistent…** erneut aufrufen.

## Das Hauptfenster

Das Fenster hat drei Spalten:

- **Links** die Dateien des Scan-Ordners als Kacheln. Darüber die Reiter **„PDFs“**, **„Chat“**
  und **„Korrespondenten“**.
- **In der Mitte** die Reiter **„Vorschau“** (die gewählte PDF mit Vorschlägen für Namen und
  Metadaten) und **„Suche“** (Volltextsuche).
- **Rechts** die Zielordner. Vorgeschlagene Ordner sind grün hervorgehoben.

**Hilfe › Erste Schritte** zeigt die Kurzanleitung zu diesem Ablauf noch einmal. **Hilfe ›
Handbuch** (`F1`) öffnet dieses Handbuch.

## Der Ablauf in drei Schritten

1. Links eine PDF anklicken. Die Mitte zeigt die Vorschau und schlägt einen Dateinamen vor.
2. Den Namen bei Bedarf anpassen.
3. Rechts auf den Zielordner klicken. Die PDF wird verschoben, umbenannt und die Metadaten
   werden gespeichert, alles in einem Schritt. `Strg+Z` macht es rückgängig.

Tipp für den Anfang: Erst mit einer Kopie eines Scan-Ordners üben. Das Programm verschiebt und
benennt Dateien wirklich um.

Weiter: [Scan-Ordner und Zielordner](02-ordner.md)

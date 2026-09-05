# PDF Sortier Meister vs. paperless-ngx

**Stand: September 2026** — verglichen werden PDF Sortier Meister **v0.23.0** (30.08.2026) und paperless-ngx **v3.1.3** (04.09.2026) samt den KI-Erweiterungen **paperless-ai** (v3.0.9, letztes Release 04.11.2025) und **paperless-gpt** (v0.27.0, 21.07.2026). Ersetzt die Fassung vom März 2026. Zeilenangaben beziehen sich auf den Stand v0.23.0 (Commit 72d4389).

> Kurzfassung: paperless-ngx ist ein Server-Archiv, das Dokumente *übernimmt* und in einer eigenen Ablage verwaltet — mit allem, was ein Mehrgeräte-/Mehrbenutzer-System braucht. PDF Sortier Meister ist ein Desktop-Werkzeug, das Scans *in der eigenen Ordnerstruktur* sortiert, benennt und die Metadaten in die PDF selbst schreibt. Seit v3.0 (Juli 2026) hat paperless-ngx eingebaute KI (Vorschläge, Embedding-Index, Dokumenten-Chat) — der frühere Vorsprung von PDFSM bei „KI ohne Zusatz-Container“ ist damit kleiner geworden. Umgekehrt hat PDFSM fast alles nachgezogen, was im März noch „geplant“ war: Volltextsuche, RAG-Chat, Korrespondenten, Regeln, XMP-Metadaten, Merge/Split, Ollama.

---

## 1. Grundkonzept

| | **PDF Sortier Meister** | **paperless-ngx** |
|---|---|---|
| **Typ** | Desktop-App (Windows 10/11, macOS) | Web-App, self-hosted (Docker, Linux) |
| **Zielgruppe** | Einzelperson, Haushalt, Selbstständige, Steuerbüro-Zuarbeit | Heimserver, Familien, kleine Teams |
| **Betrieb** | Installer/DMG, läuft nur, wenn das Fenster offen ist | Dauerhaft laufende Container: App, PostgreSQL/MariaDB/SQLite, Redis; optional Tika/Gotenberg |
| **Datenhaltung** | Dateien bleiben in den eigenen Ordnern (auch OneDrive); Metadaten **in der PDF** (XMP + Info-Dictionary) und als SQLite-Index | Zentrales Medienverzeichnis mit eigenem Schema (Original + PDF/A-Archivkopie), Metadaten **nur in der Datenbank** |
| **Bedienidee** | Explorer-artig: Scan-Ordner links, Zielordner rechts, Klick/Drag & Drop verschiebt und benennt | Posteingang → automatische Verarbeitung → Tags/Korrespondent/Typ; man arbeitet mit Filtern und Ansichten, nicht mit Ordnern |
| **Lizenz / Größe** | GPL-3.0, Solo-Projekt, rund 28.000 Zeilen Python in `src/` plus Tests, 856 Tests | GPL-3.0, Team-Projekt, ~45.000 GitHub-Sterne |

---

## 2. Was sich seit März 2026 geändert hat

**PDF Sortier Meister** (v0.12 → v0.23): RAG-Chat mit Quellen (v0.12.0), Korrespondenten-Verwaltung und WENN-DANN-Regeln (v0.13.0), OpenRouter/Ollama Cloud, Windows-Installer mit gebündeltem Tesseract, macOS-Build, integrierte PDF-Vorschau, Update-Prüfung, Dateinamen-Muster mit Platzhaltern, Backup/Restore, Text aus der Vorschau in Metadaten übernehmen (siehe CHANGELOG.md).

**paperless-ngx**: v2.19 (Okt. 2025) verschachtelte Tags; **v3.0.0 (22.07.2026)**: native KI (LLM-Vorschläge für Titel/Datum/Tags/Korrespondent/Typ, Embedding-Index, Dokumenten-Chat mit Quellen, Ollama oder OpenAI-kompatibel), neue Volltextsuche (Tantivy), Dokumentversionen, Remote-OCR (Azure AI), Share-Link-Bundles, Parser-Plugins; **v3.1.0 (27.08.2026)**: Workflow-Aktion „KI-Vorschläge anwenden“, Dateien als Versionen zusammenführen.

**KI-Addons**: paperless-ai (Auto-Tagging + RAG-Chat) hat seit November 2025 kein Release mehr — die Kernfunktionen sind jetzt in paperless-ngx selbst. paperless-gpt ist aktiv und hat sich auf **LLM-Vision-OCR** spezialisiert (schlechte Scans per Bildmodell lesen, durchsuchbare PDFs erzeugen).

---

## 3. Feature-Vergleich

Legende: ✅ vorhanden · ◐ teilweise · ❌ nicht vorhanden. „Beleg“ nennt die Stelle im PDFSM-Code oder die CHANGELOG-Version.

### 3.1 Dokumenteneingang und Automatisierung

| Feature | paperless-ngx | PDF Sortier Meister | Beleg |
|---|---|---|---|
| Eingangsordner wird **automatisch überwacht** | ✅ Consume-Ordner, Verarbeitung im Hintergrund | ❌ Analyse startet nur, wenn die App offen ist und der Ordner geladen wird (Vorab-Analyse und KI-Queue laufen dann im Hintergrund) | `watchdog` steht in `requirements.txt:19`, wird aber nirgends importiert; `main_window._schedule_pre_caching`, `pdf_cache.PDFAnalysisWorker` |
| Upload per Web-Oberfläche / Drag & Drop | ✅ | — (nicht anwendbar, Dateien liegen lokal) | |
| **E-Mail-Abruf** (IMAP, Regeln, OAuth Gmail/Outlook, alle 10 min) | ✅ | ❌ | grep imap: keine Treffer |
| REST-API / Webhooks / Pre-/Post-Consume-Skripte | ✅ | ❌ (nur Startparameter „Ordner oder PDF-Datei öffnen“ und Explorer-Kontextmenü auf Ordnern) | `src/main.py:59-62 _extract_path_arg`, `src/utils/explorer_integration.py:12-14` |
| **Regeln / Workflows** | ✅ Trigger (Eingang, hinzugefügt, geändert, zeitgesteuert), Aktionen (Zuweisen/Entfernen von Tags, Korrespondent, Typ, Pfad, Custom Fields, Besitzer, E-Mail, Webhook, Papierkorb, Passwort entfernen, KI-Vorschläge anwenden) | ◐ WENN-DANN-Regeln mit 5 Bedingungen (Korrespondent, Kategorie, Betrag, Datum, Stichwörter) und 4 Aktionstypen — **aber nur als Hinweis in der Statusleiste**, und der wird erst *nach* dem Verschieben geprüft, in zwei von drei Pfaden ohne Metadaten. Praktisch greift heute keine Regel. | `src/core/rule_engine.py:50-56`, `src/gui/main_window.py:537-573` („KEIN Auto-Move ohne User-Bestätigung in v1“), Aufrufe `:2067, :2144, :2655` |
| **Lernender Klassifikator** | ✅ „Auto“-Matching (Klassifikator wird stündlich aus den Dokumenten trainiert) | ✅ TF-IDF lernt aus jeder Verschiebung, Jahres-Varianten von Ordnern; LLM nur bei niedriger Konfidenz | `src/ml/classifier.py:349 learn`, `:604-608 _year_variant` (v0.15.0 #30), `hybrid_classifier.py:63 LOCAL_CONFIDENCE_THRESHOLD` |
| **Barcodes / ASN** (Trennseiten, Archivnummer, Tag-Barcodes) | ✅ | ❌ | grep barcode: keine Treffer |
| Duplikaterkennung (Prüfsumme) | ✅ prüfsummenbasiert, Duplikate werden markiert (optional verworfen) | ❌ | — |
| Weitere Formate (Bilder, Office, E-Mail) | ✅ (Office via Tika/Gotenberg) | ❌ nur `*.pdf` | `src/core/file_manager.py:67-70` |

### 3.2 Metadaten und Organisation

| Feature | paperless-ngx | PDF Sortier Meister | Beleg |
|---|---|---|---|
| **Ordnerstruktur frei wählbar** | ◐ Storage Paths mit Jinja2-Vorlagen (`{{created_year}}/{{correspondent}}`), aber innerhalb des paperless-Medienordners | ✅ Bestehende Ordner bleiben; Vorschläge kommen aus der eigenen Struktur (gelernt + Jahres-Variante). Der KI-Ordnerpfad (`suggest_folders`) ist vorhanden, wird aber aus der Oberfläche nicht aufgerufen (siehe Issue #116) | `classifier.py:604-608`, `hybrid_classifier.py:221-283` |
| **Dateiname** selbst bestimmen | ◐ Dateinamen-Format global/pro Storage Path | ✅ Muster mit Platzhaltern (`{datum}_{kontakt}_{betreff}`, eigene Muster speichern), KI füllt sie aus; Ordnernummern-Präfix (`JK 069-03-05-…`) | `src/core/filename_placeholders.py:23-79`, `folder_naming.py` (v0.17.0 #42, v0.21–0.23) |
| **Tags** (mehrwertig, verschachtelt, farbig) | ✅ inkl. Nested Tags (Tiefe 5) | ❌ eine einwertige **Kategorie**; Stichwörter landen als `pdf:Keywords` in der PDF, sind aber nicht als Tag-System bedienbar | `src/core/metadata_choices.py:9-12`, `pdf_metadata.py:91-92` |
| **Korrespondenten** | ✅ mit Matching-Regeln | ✅ Tabelle mit Aliasen, Farbe, Notizen, Zusammenführen, automatisches Sammeln aus der Historie, Wiedererkennung im Text; Klick filtert | `database.py:136, 1934, 2031, 2190`, `korrespondent_match.py:32` (v0.13.0, v0.23.0 #109) |
| Dokumenttypen | ✅ | ✅ als Kategorie (Rechnung, Vertrag, Steuer, Versicherung, Bank, Gehalt, Arzt, Energie, …) | `metadata_choices.py` (#110) |
| **Custom Fields** (Text, Zahl, Datum, Währung, Auswahl, Dokument-Link, URL, Boolean) | ✅ 9 Feldtypen, frei definierbar | ◐ fester Satz Steuer-/Buchhaltungsfelder: Korrespondent, Buchungsdatum, Steuerjahr, Netto, Brutto, Währung, MwSt, IBAN, steuerlich absetzbar, Zusammenfassung | `src/core/pdf_metadata.py:20-38` |
| **Metadaten in der PDF-Datei** (portabel) | ❌ nur Datenbank; eingebettete PDF-Metadaten werden beim Import **nicht ausgewertet** (Maintainer, Discussion #5053) | ✅ XMP (`dc:title`, `dc:subject`, `dc:description`, `pdf:Keywords`) + Info-Dictionary (`/Korrespondent`, `/Steuerjahr`, `/IBAN`, …), im Hintergrund geschrieben und gelesen | `pdf_metadata.py:82-92, 171-190`; `main_window.py:1057`; `detail_panel.py:49` |
| Notizen pro Dokument, Audit-Historie, **Dokumentversionen** | ✅ | ❌ (nur Undo-Stack der letzten Aktionen) | `main_window.py:2785` |
| Gespeicherte Ansichten / Dashboard | ✅ | ❌ | — |
| Mehrfachauswahl / Stapelbearbeitung | ✅ Bulk-Edit | ✅ Shift/Ctrl-Auswahl, Verschieben, Kopieren, LLM-Stapelumbenennung | `main_window.py:2151, 2933` |

### 3.3 Suche und KI

| Feature | paperless-ngx | PDF Sortier Meister | Beleg |
|---|---|---|---|
| **Volltextsuche** | ✅ Tantivy (seit v3.0), Autovervollständigung, Feldsyntax (`tag:… created:[2024 to 2025]`), Fuzzy, „Mehr wie dieses“ | ✅ SQLite FTS5 (`unicode61`), Live-Suche ab 2 Zeichen, Filter Steuerjahr/Kategorie/Korrespondent/Datum/Betrag; OR/AND/NEAR/NOT werden durchgereicht; kein „Mehr wie dieses“, keine Feldsyntax | `database.py:400-416, 976-1028`, `main_window.py:3452, 3622` (v0.9.0/v0.11.0 #18) |
| Index-Umfang | ganzes Archiv automatisch, Volltext | ◐ alles, was verschoben/umbenannt wurde (über `update_pdf_path`); Bestandsordner **manuell** über „Ordner zum Suchindex hinzufügen“. **Von jedem Dokument stehen nur die ersten 5.000 Zeichen** (etwa zwei Seiten) im Index und im RAG-Kontext | `database.py:230 MAX_EXTRACTED_TEXT_LENGTH`, `:602, :677, :731`; `main_window.py:2034, 2125, 3702`; Entscheidung Q3/R8 in `docs/ARCHITECTURE.md` |
| **KI-Vorschläge** (Titel/Name, Kategorie, Korrespondent, Datum) | ✅ nativ seit v3.0 (Ollama oder OpenAI-kompatibel, `PAPERLESS_AI_ENABLED`); Addons paperless-ai/-gpt zusätzlich | ✅ Ollama (lokal, Auto-Start, Hardware-Empfehlung im Assistenten), Ollama Cloud, OpenRouter, Claude, OpenAI, Poe; Metadaten-Extraktion (Betrag, MwSt, IBAN, Steuerjahr); gelernte Stil-Beispiele im Prompt | `src/ml/*_provider.py`, `llm_provider.py:396`, `src/utils/hardware.py` (v0.16.0, v0.20.0) |
| **RAG-Chat** über die eigenen Dokumente | ✅ nativ seit v3.0: Embedding-Index (HuggingFace/Ollama/OpenAI-kompatibel, täglicher Cron), Chat über ein oder mehrere Dokumente mit Quellenlinks | ✅ Chat-Tab, Antworten mit klickbaren Quellen, Whitelist gegen erfundene Zitate, Offline-Fallback als Trefferliste; **Retrieval rein stichwortbasiert** (FTS5-OR-Query, Top-8, 1 PDF = 1 Chunk à 2000 Zeichen), keine Embeddings (bewusste v1-Entscheidung in `docs/ARCHITECTURE.md`), Verlauf nur in der Sitzung | `src/rag/retrieval.py:240`, `rag_controller.py:85 ask`, `config.py:36-40`, `chat_view.py:87` (v0.12.0 #20) |
| KI-Datenschutz | Opt-in, Warnhinweis; lokale Modelle möglich | Consent-Gate für Cloud-Provider, nur Textauszug (500–5000 Zeichen), Standard „keine KI“ | `config.py:95 cloud_consent` |
| LLM-Vision-OCR für schlechte Scans | ◐ über paperless-gpt (OpenAI/Ollama/Mistral/Claude, Azure DI, Google Document AI) | ❌ | — |

### 3.4 OCR und PDF-Verarbeitung

| Feature | paperless-ngx | PDF Sortier Meister | Beleg |
|---|---|---|---|
| **OCR** | ✅ Tesseract für alle Dokumente, 100+ Sprachen, OCRmyPDF; optional Azure AI | ◐ Tesseract gebündelt (Win/Mac), aber nur als **Fallback ohne Textebene**, nur die **ersten 5 Seiten**, nur Deutsch (fest kodiert, kein Config-Schlüssel) | `pdf_analyzer.py:139-141, 170, 182`; offene Issues #46, #47 |
| Durchsuchbare PDF / **PDF/A-Archivkopie** | ✅ Textebene wird eingebettet, PDF/A erzeugt | ❌ Originaldatei bleibt unverändert (nur Metadaten werden geschrieben) | kein ocrmypdf/PDF-A im Code |
| Seiten **trennen / zusammenfügen** | ✅ | ✅ alle Seiten einzeln oder Bereich; Merge per Kontextmenü | `file_manager.py:227, 273` (#12) |
| Seiten drehen, löschen, umsortieren | ✅ | ❌ | grep rotate: keine Treffer |
| Integrierte Vorschau | ✅ (PDF.js/PNGX) | ✅ QtPdf-Vorschau, Text markieren → als Metadatum übernehmen | `pdf_preview_widget.py` (v0.19.0, v0.23.0 #109) |
| Passwortgeschützte PDFs entschlüsseln | ✅ Workflow-Aktion | ❌ | — |

### 3.5 Betrieb, Sicherheit, Daten

| Feature | paperless-ngx | PDF Sortier Meister | Beleg |
|---|---|---|---|
| **Mehrbenutzer, Berechtigungen** (global + pro Objekt), OIDC/SSO, 2FA | ✅ | ❌ (Einzelnutzer, keine Anmeldung) | — |
| **Mobil / anderes Gerät** | ✅ Web-UI, Apps „Paperless Mobile“ (Android), „Swift Paperless“ (iOS) | ◐ keine App; Dateien und XMP-Metadaten sind über OneDrive/iCloud auf dem Handy sichtbar, Suche/Chat nicht | — |
| **Freigabe-Links** (öffentlich, ablaufend, Bundles) | ✅ | ❌ (Datei per Explorer/OneDrive teilen) | — |
| **Papierkorb** (30 Tage), Wiederherstellen | ✅ | ❌ Löschen nach Rückfrage, danach endgültig (`unlink`, kein Papierkorb); Undo nur für Verschieben/Umbenennen | `file_manager.py:225`, `main_window.py:2613-2620, 2785` |
| Backup / Export | ✅ Document-Exporter (Dateien + Metadaten), Importer | ✅ ZIP mit Datenbank, KI-Cache, Modell, Einstellungen; Wiederherstellen beim nächsten Start; Backup-Erinnerung | `src/utils/backup.py:1-45` (v0.22.0 #98, v0.14.0 #7) |
| **Steuerauswertung** (Summen je Jahr/Kategorie, CSV) | ❌ (nur über Custom Fields + Export selbst bauen) | ✅ | `database.py:1809`, `steuerauswertung_dialog.py:130-143` |
| Update-Mechanismus | Container-Image ziehen | ✅ Hinweis auf neue Version (GitHub `releases/latest`), Drüberinstallieren | `update_check.py:22-24` (v0.19.0 #73) |
| Plattform | Linux/Docker (Windows „not supported“, nur via WSL/NAS) | Windows 10/11, macOS (Intel + Apple Silicon), signiert/notarisiert | README, `build.sh` (v0.18.0) |
| Cloud-Sync-Ordner (OneDrive „Dateien bei Bedarf“) | ⚠ Medienordner gehört nicht in Sync-Ordner | ✅ ausdrücklich unterstützt, langsame Zugriffe laufen in Threads | CHANGELOG 0.15.1 |
| Einrichtung | Docker Compose oder Installationsskript, Reverse-Proxy für Zugriff von außen | ✅ Setup.exe/DMG, Assistent (Ordner, GPU-Check, Ollama-Modell per Klick) | `setup_wizard.py:96-102` (v0.16.0, v0.20.0) |

---

## 4. Lücken-Tabelle: Was paperless-ngx kann und PDFSM heute nicht

Relevanz bezieht sich auf eine **Desktop-App für Einzelnutzer**. Aufwand: S < 0,5 Tag · M 0,5–1,5 Tage · L 2–4 Tage · XL > 1 Woche (Grobschätzung ohne Spike).

| # | Feature | paperless-ngx | PDFSM heute (Beleg) | Relevanz | Aufwand | Anmerkung |
|---|---|---|---|---|---|---|
| 1 | **Papierkorb** statt endgültigem Löschen (#124) | Trash, 30 Tage | Rückfrage, dann `unlink()` (`file_manager.py:225`) | mittel–hoch | S | `QFile.moveToTrash` ist in Qt 6.11 vorhanden; Undo-Eintrag ergänzen; Test für `delete_file` fehlt bisher ganz |
| 2 | **Regeln wirklich anwenden** (#125) | Workflows setzen Felder, Pfad, Tags automatisch | Hinweis erst nach dem Verschieben, in zwei von drei Pfaden ohne Metadaten (`main_window.py:537-573, 2067, 2144, 2655`); kein Konsument für die Aktionen | **hoch** | M–L | Auswertung *vor* den Move in alle drei Pfade ziehen, mit `detail_panel.get_metadata()` füttern (liegt erst nach der KI-Analyse vor), Zielordner/Dateiname im Detail-Panel vorbelegen; Auto-Verschieben ab Konfidenz 0,9 als Opt-in; Tests fehlen bisher |
| 3 | **OCR aller Seiten, mehrsprachig, Textebene zurückschreiben** | OCRmyPDF, PDF/A, 100+ Sprachen | 5 Seiten, `deu`, keine Textebene (`pdf_analyzer.py:170, 182`); Suchindex zusätzlich bei **jedem** Dokument auf 5.000 Zeichen gekappt (`database.py:230`) | **hoch** (Suche/RAG sehen sonst nur den Anfang) | M–L | Bereits als #46/#47 offen; dort ergänzen: alle Seiten, `deu+eng`, Textebene per `image_to_pdf_or_hocr` + pikepdf, und `MAX_EXTRACTED_TEXT_LENGTH` bzw. Chunking pro Seite mitziehen, sonst bringt OCR aller Seiten der Suche nichts. Erst nach #108 (Klick-Freeze), sonst wächst der Freeze auf 30 s |
| 4 | **Eingang im Hintergrund** (Watch-Folder, Tray, Autostart, #126) | Consume-Ordner 24/7 | nur bei offenem Fenster; `watchdog` ungenutzt | **hoch** — das ist der eigentliche Kern der „Server-Frage“ | L | Nur der Trigger fehlt: `QFileSystemWatcher`/watchdog auf den Scan-Ordner, dann die vorhandene Vorab-Analyse (`PDFAnalysisWorker`) und KI-Queue (`_llm_queued`) nutzen; `QSystemTrayIcon`, Autostart (HKCU Run / LaunchAgent) |
| 5 | **Mehrwertige Tags** (verschachtelt, farbig, filterbar) | Nested Tags | einwertige Kategorie; `pdf:Keywords` nur geschrieben | mittel | L | Tags in `pdf:Keywords` + FTS-Spalte `keywords` abbilden; Filterleiste erweitern |
| 6 | **Semantische Suche / Embeddings im RAG** | Vektorindex (HF/Ollama/OpenAI) + Chat | FTS5-Stichwort-Retrieval (`retrieval.py:240`); „Keine Embeddings“ ist in `docs/ARCHITECTURE.md` als v1-Entscheidung festgehalten | mittel (Fragen ohne Stichworttreffer scheitern) | L | Hybrid: FTS5 + Ollama-Embeddings (`/api/embeddings`) mit `sqlite-vec` oder numpy; Chunking pro Seite; setzt #3 voraus, sonst indexiert man Lücken. Entscheidung in ARCHITECTURE.md dann fortschreiben |
| 7 | Duplikaterkennung | Prüfsumme, Duplikate markiert | keine | mittel | S–M | Hash in `pdfs`-Mastertabelle (#25) |
| 8 | Bilder (JPG/PNG) als Eingang | ja | nur PDF (`file_manager.py:67-70`) | mittel | M | PyMuPDF wandelt Bild → PDF, dann normaler Weg |
| 9 | Seiten drehen / löschen / umsortieren | PDF-Editor | Merge/Split nur | mittel | M | pikepdf/PyMuPDF; in `split_pdf_dialog` andocken |
| 10 | Freie **Custom Fields** | 9 Feldtypen | fester Feldsatz (`pdf_metadata.py:20-38`); die Konstante `CUSTOM_NS` existiert, wird aber nicht genutzt — Custom-Felder landen im Info-Dictionary | mittel | L | Eigener XMP-Namespace, UI und FTS-Spalten dynamisch |
| 11 | Gespeicherte Suchen / Ansichten | Saved Views, Dashboard | keine | niedrig–mittel | S–M | Filterzustand als benannte Config-Einträge |
| 12 | Suchsyntax mit Feldern (`kategorie:Rechnung`, Datumsbereich im Text) | Tantivy-Syntax | nur Dropdown-Filter; FTS5-Spaltenfilter wären nativ möglich | niedrig | S–M | `search_documents` erkennt heute nur OR/AND/NEAR/NOT (`database.py:1023-1028`) |
| 13 | LLM-Vision-OCR (paperless-gpt) | ja | nein | mittel bei vielen schlechten Scans | M | Ollama-Vision-Modelle (gemma3) und Claude/OpenAI können Bilder; an `_extract_text_ocr` als 2. Fallback |
| 14 | **E-Mail-Abruf** (Rechnungen aus dem Postfach) | IMAP-Regeln, OAuth | nein | mittel (viele Rechnungen kommen per Mail), aber nur sinnvoll mit #4 | L | `imaplib` (stdlib), Anhänge in den Scan-Ordner legen; läuft nur, wenn die App läuft |
| 15 | Barcode-Trennseiten / ASN | ja | nein | niedrig (Haushalt) / mittel (Steuerbüro, Stapelscan) | M–L | `pyzbar` + zbar-DLL bündeln |
| 16 | Notizen, Audit-Historie, Dokumentversionen | ja | nein | niedrig | L | widerspricht teils „Datei bleibt Datei“ |
| 17 | Passwort entfernen | Workflow-Aktion | nein | niedrig | S | pikepdf `open(password=…)` |
| 18 | **Mobil / Web-UI / Apps** | Web + 2 Apps | nein; Dateien via OneDrive | niedrig–mittel | XL | nur mit Server; siehe Abschnitt 6 |
| 19 | **Mehrbenutzer, Berechtigungen, Freigabe-Links** | ja | nein | niedrig | XL | nur mit Server |
| 20 | REST-API / Webhooks / Skript-Hooks | ja | nein | niedrig | L–XL | Kommandozeilen-Hooks (Post-Move-Skript) wären eine Desktop-Variante (M) |
| 21 | Office-Formate (Tika/Gotenberg) | ja | nein | niedrig | XL | außerhalb des Produktkerns (siehe Issue #9) |

---

## 5. Wo PDF Sortier Meister voraus ist

- **Kein Lock-in:** Dateien bleiben normale PDFs in normalen Ordnern — Explorer, OneDrive, Steuerberater-Upload funktionieren unverändert. paperless-ngx übernimmt die Datei in sein Medienverzeichnis; wer aussteigt, braucht den Exporter.
- **Metadaten reisen mit der Datei:** Kategorie, Korrespondent, Betrag, MwSt, IBAN, Steuerjahr, Zusammenfassung stehen als XMP/Info-Dictionary in der PDF (`pdf_metadata.py`) und sind in Acrobat, DEVONthink oder den Windows-Eigenschaften sichtbar. paperless-ngx hält Metadaten nur in der Datenbank (Feature-Request #7049 ohne Umsetzung).
- **Steuer- und Buchhaltungsfelder plus Auswertung:** Netto/Brutto/MwSt/absetzbar je Steuerjahr mit CSV-Export (`steuerauswertung_dialog.py`) — in paperless nur über selbst angelegte Custom Fields und externe Auswertung.
- **Explorer-artiges Sortieren:** Zielordner-Vorschläge aus der eigenen Struktur, Jahres-Varianten („Steuer 2025“ → „Steuer 2026“), Drag & Drop, Ctrl+Z, Explorer-Kontextmenü.
- **Dateinamen mit Verstand:** Muster mit Platzhaltern, die die KI ausfüllt, Ordnernummern-Präfix aus dem Zielpfad, gelernte Stil-Beispiele im Prompt (v0.21–0.23).
- **Zero-Setup-KI:** Assistent prüft die Grafikkarte, empfiehlt ein Modell, startet Ollama automatisch und lädt das Modell per Klick — ohne Terminal, ohne Docker.
- **Native Desktop-Apps** für Windows und macOS mit gebündeltem Tesseract; paperless-ngx läuft offiziell nur unter Linux/Docker.
- **Text aus der Vorschau in Metadaten** übernehmen, Korrespondent wird daraus gelernt (#109).

---

## 6. Braucht man die Server-Funktionalität wirklich?

„Server“ bedeutet bei paperless-ngx zwei verschiedene Dinge, die getrennt zu bewerten sind:

### 6.1 Nur mit Server möglich

| Nutzen | Für wen relevant |
|---|---|
| **Zugriff von mehreren Geräten / mobil** auf Suche, Metadaten, Chat (Web-UI, Android-/iOS-Apps) | Wer unterwegs *suchen* will. Wer nur die *Dateien* braucht, hat sie bei PDFSM ohnehin via OneDrive/iCloud auf dem Handy — samt XMP-Metadaten. |
| **Mehrbenutzer** mit Berechtigungen, Besitzer, Gruppen, SSO | Familien-/Teamarchiv. Für Einzelnutzer irrelevant. |
| **Freigabe-Links** (ablaufend, ohne Login) | Belege an Steuerberater/Vermieter schicken — geht bei PDFSM per OneDrive-Freigabe oder E-Mail-Anhang. |
| **Verarbeitung rund um die Uhr, auch bei ausgeschaltetem PC** (Mail-Abruf, Consume-Ordner, geplante Workflows, Embedding-Index per Cron) | Nur, wenn Dokumente eintreffen, während kein Rechner läuft (z. B. Scanner schickt direkt per Mail/SMB). |
| **API/Webhooks** für andere Systeme (Home Assistant, n8n, Nextcloud) | Automatisierer. |

### 6.2 Geht auch als Desktop-App (heute teils fehlend, siehe Lücken #1–#4)

- **Eingangsordner beobachten** und neue Scans sofort analysieren, OCR-en und KI-Vorschläge vorbereiten — solange die App läuft (Tray-Icon, Autostart). Analyse-Worker und KI-Queue laufen heute schon im Hintergrund, es fehlt nur der Auslöser. Der Scanner legt sowieso in einen lokalen/OneDrive-Ordner ab; ob die Auswertung um 3 Uhr nachts oder beim nächsten Einschalten passiert, ist für einen Haushalt egal.
- **Regeln automatisch anwenden** (Stadtwerke → Wohnung/Nebenkosten) — braucht keinen Server. Heute läuft die Prüfung erst nach dem Verschieben und meist ohne Metadaten; sie muss vor den Move und an die Metadaten des Detail-Panels (M–L, Lücke #2).
- **Mail-Import**: IMAP-Abruf beim App-Start oder alle n Minuten ist Desktop-tauglich; er läuft eben nur, wenn der PC an ist.
- **Volltext + RAG**: läuft bereits lokal; Embeddings wären auch lokal (Ollama) möglich.
- **Backup/Restore**: vorhanden.

### 6.3 Bewertung

Für die Zielgruppe von PDF Sortier Meister — Einzelnutzer, Scans landen ohnehin in einem (OneDrive-)Ordner, Ordnerstruktur soll erhalten bleiben — ist ein Server **nicht nötig**. Die spürbaren Vorteile von paperless-ngx im Alltag sind nicht der Server an sich, sondern **(a) alles passiert automatisch im Hintergrund**, **(b) OCR ist immer vollständig und in der Datei**, **(c) Regeln greifen ohne Klick**. Alle drei sind als Desktop-Funktionen umsetzbar (Lücken #2–#4) und sollten Vorrang vor jeder Server-Überlegung haben. Ein eigener Web-/Server-Modus (XL) würde dagegen genau das Kernversprechen („kein Docker, kein Server, keine Datenbank-Silo“) aufgeben, mit dem sich PDFSM von paperless-ngx unterscheidet.

Wer Mehrbenutzer, Handy-Suche oder 24/7-Mail-Abruf wirklich braucht, ist bei paperless-ngx richtig — und kann PDFSM davor schalten (Abschnitt 7).

---

## 7. Beide zusammen verwenden

PDFSM als „Vorsortierer“ vor paperless-ngx funktioniert, aber anders als im März 2026 angenommen: **paperless-ngx liest eingebettete PDF-Metadaten nicht aus** („embedded PDF metadata … is not utilized by paperless, nor is it changed by paperless“, Maintainer in Discussion #5053). Was beim Import ankommt, ist der **Dateiname** (paperless erkennt Datum und Titel aus dem Dateinamen, z. B. `2026-03-12 Telekom - Rechnung.pdf`) und der Ordnerpfad (per Workflow-Filter auf den Consume-Pfad). Praktisch heißt das:

1. In PDFSM sortieren und mit sprechendem Muster benennen (`{datum}_{kontakt}_{betreff}`).
2. Den fertigen Ordner in den paperless-Consume-Ordner kopieren (oder paperless auf den PDFSM-Zielordner zeigen lassen).
3. In paperless per Workflow „Consumption Started“ mit Pfadfilter Tags/Korrespondent zuweisen — oder die native KI Vorschläge machen lassen.

Die XMP-Metadaten bleiben in der Originaldatei erhalten und sind in paperless im Tab „Metadata“ sichtbar, werden aber nicht zu Tags. Umgekehrt (paperless → PDFSM) übernimmt PDFSM die Ordnerstruktur des Exporters und liest vorhandene XMP-Felder.

---

## 8. Fazit und Empfehlung für die PDFSM-Roadmap

1. **Kein Server, kein Web-Modus.** Die Differenzierung „Dateien bleiben deine Dateien, Metadaten in der PDF, kein Docker“ ist intakt und durch paperless' Roadmap (v3: KI, Versionen, Remote-OCR — alles serverseitig) eher schärfer geworden.
2. **Die Alltagslücken schließen**, die paperless-Nutzer als „Server-Vorteil“ empfinden, aber keine sind: Papierkorb (#124, S), Regeln anwenden (#125, M–L), OCR vollständig mit Textebene und ohne 5.000-Zeichen-Deckel (#46/#47, M–L), Postfach-Modus mit Watch-Folder + Tray (#126, L).
3. **RAG ehrlich einordnen:** PDFSM-Chat ist stichwortbasiert (FTS5) und damit robust, aber bei Fragen ohne Wortüberschneidung unterlegen. „Keine Embeddings“ war eine bewusste v1-Entscheidung (`docs/ARCHITECTURE.md`, Abschnitt 3; Zusammenfassung in `docs/RAG_ARCHITECTURE_SUMMARY.md`). Ein hybrider Modus mit lokalen Embeddings (Ollama) ist der nächste sinnvolle Schritt, sobald OCR alle Seiten liefert und der Index nicht mehr kappt — vorher indexiert man Lücken. Die Entscheidung dann in ARCHITECTURE.md fortschreiben.
4. **Tags** erst danach; Kategorie + Korrespondent + Steuerfelder decken den Steuer-/Haushalts-Fall ab, verschachtelte Tags sind ein paperless-Konzept, das ohne Ordnerbezug arbeitet.
5. Dieses Dokument bei jedem Release gegen die aktuelle paperless-ngx-Version prüfen (Punkt in `docs/RELEASE_CHECKLISTE.md`), sonst ist es in sechs Monaten wieder falsch.

---

## Quellen (abgerufen 05.09.2026)

- paperless-ngx Dokumentation (Branch `dev`, docs.paperless-ngx.com blockt automatisierte Abrufe): Usage <https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/dev/docs/usage.md>, Advanced Usage <https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/dev/docs/advanced_usage.md>, Configuration <https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/dev/docs/configuration.md>, Setup <https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/dev/docs/setup.md>, Übersicht <https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/dev/docs/index.md>
- paperless-ngx Releases: v3.0.0 (22.07.2026) <https://github.com/paperless-ngx/paperless-ngx/releases/tag/v3.0.0>, v3.1.0 (27.08.2026) <https://github.com/paperless-ngx/paperless-ngx/releases/tag/v3.1.0>, v2.19.0 (21.10.2025, Nested Tags) <https://github.com/paperless-ngx/paperless-ngx/releases/tag/v2.19.0>
- PDF-Metadaten werden von paperless nicht ausgewertet: <https://github.com/paperless-ngx/paperless-ngx/discussions/5053>; Feature-Request Metadaten in PDF speichern: <https://github.com/paperless-ngx/paperless-ngx/discussions/7049>
- paperless-ai (clusterzx): <https://github.com/clusterzx/paperless-ai>, Funktionen <https://github.com/clusterzx/paperless-ai/wiki/3.-Functions>
- paperless-gpt (icereed): <https://github.com/icereed/paperless-gpt>
- Mobile Apps: Paperless Mobile <https://github.com/astubenbord/paperless-mobile>, Swift Paperless <https://github.com/paulgessinger/swift-paperless>, Related Projects <https://github.com/paperless-ngx/paperless-ngx/wiki/Related-Projects>
- PDF Sortier Meister: CHANGELOG.md, README.md, docs/ARCHITECTURE.md (RAG), Quellcode v0.23.0 (Belege in den Tabellen).

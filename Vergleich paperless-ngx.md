# PDF Sortier Meister vs. paperless-ngx

**Stand: November 2026** — verglichen werden PDF Sortier Meister **v0.24.0** (Release in Vorbereitung, 06.11.2026) und paperless-ngx **v3.4.2** (03.11.2026) samt den KI-Erweiterungen **paperless-ai** (v3.0.9, letztes Release 04.11.2025) und **paperless-gpt** (v0.31.0, 14.10.2026). Fortschreibung der Fassung vom September 2026 (PDFSM v0.23.0 gegen paperless-ngx v3.1.3), die ihrerseits die Fassung vom März 2026 ersetzt hatte. Belege beziehen sich auf den Stand v0.24.0; Zeilenangaben in Tabellenzeilen, die sich seit v0.23.0 inhaltlich nicht geändert haben, sind nicht alle neu geprüft und können sich um einige Zeilen verschoben haben.

> Kurzfassung: paperless-ngx ist ein Server-Archiv, das Dokumente *übernimmt* und in einer eigenen Ablage verwaltet — mit allem, was ein Mehrgeräte-/Mehrbenutzer-System braucht. PDF Sortier Meister ist ein Desktop-Werkzeug, das Scans *in der eigenen Ordnerstruktur* sortiert, benennt und die Metadaten in die PDF selbst schreibt. Seit v3.0 (Juli 2026) hat paperless-ngx eingebaute KI (Vorschläge, Embedding-Index, Dokumenten-Chat) — der frühere Vorsprung von PDFSM bei „KI ohne Zusatz-Container“ ist damit kleiner geworden; v3.2 bis v3.4 haben das vor allem verfeinert (Duplikat-Filter, durchsuchbare Barcode-Inhalte, mehr KI-Einstellungen). Umgekehrt hat PDFSM fast alles nachgezogen, was im März noch „geplant“ war: Volltextsuche, RAG-Chat, Korrespondenten, Regeln, XMP-Metadaten, Merge/Split, Ollama. Mit v0.24.0 kommt eine **Dokumentensuche über den ganzen PC** dazu — Volltext aller Seiten mit OCR im Hintergrund, auch Office-Dateien, Markdown und Mails, mit Reiter „Suche“, Browser-Oberfläche und MCP-Server für KI-Assistenten —, und neue Scans bekommen ihren OCR-Text als unsichtbare Textebene in die PDF. Die Lücken „OCR nur 5 Seiten“ und „Suchindex 5.000 Zeichen“ sind damit geschlossen.

---

## 1. Grundkonzept

| | **PDF Sortier Meister** | **paperless-ngx** |
|---|---|---|
| **Typ** | Desktop-App (Windows 10/11, macOS) | Web-App, self-hosted (Docker, Linux) |
| **Zielgruppe** | Einzelperson, Haushalt, Selbstständige, Steuerbüro-Zuarbeit | Heimserver, Familien, kleine Teams |
| **Betrieb** | Installer/DMG; das Sortieren läuft nur, wenn das Fenster offen ist, die Dokumentensuche indiziert einmal täglich im Leerlauf über die Windows-Aufgabenplanung bzw. einen macOS-LaunchAgent (ohne Adminrechte) | Dauerhaft laufende Container: App, PostgreSQL/MariaDB/SQLite, Redis; optional Tika/Gotenberg |
| **Datenhaltung** | Dateien bleiben in den eigenen Ordnern (auch OneDrive); Metadaten **in der PDF** (XMP + Info-Dictionary), Volltext und Metadaten in einem lokalen SQLite-Suchindex; OCR-Text auf Wunsch (für neue Scans Standard) als unsichtbare Textebene in der PDF | Zentrales Medienverzeichnis mit eigenem Schema (Original + PDF/A-Archivkopie), Metadaten **nur in der Datenbank** |
| **Bedienidee** | Explorer-artig: Scan-Ordner links, Zielordner rechts, Klick/Drag & Drop verschiebt und benennt; dazu ein Reiter „Suche“ für die Volltextsuche | Posteingang → automatische Verarbeitung → Tags/Korrespondent/Typ; man arbeitet mit Filtern und Ansichten, nicht mit Ordnern |
| **Lizenz / Größe** | GPL-3.0, Solo-Projekt, rund 40.000 Zeilen Python in `src/` plus Tests, 1.322 Tests | GPL-3.0, Team-Projekt, ~48.000 GitHub-Sterne |

---

## 2. Was sich seit März 2026 geändert hat

**PDF Sortier Meister** (v0.12 → v0.23): RAG-Chat mit Quellen (v0.12.0), Korrespondenten-Verwaltung und WENN-DANN-Regeln (v0.13.0), OpenRouter/Ollama Cloud, Windows-Installer mit gebündeltem Tesseract, macOS-Build, integrierte PDF-Vorschau, Update-Prüfung, Dateinamen-Muster mit Platzhaltern, Backup/Restore, Text aus der Vorschau in Metadaten übernehmen (siehe CHANGELOG.md).

**PDF Sortier Meister v0.24.0** (seit dem Vergleich vom September 2026): Die **Dokumentensuche** aus dem bisher eigenständigen Programm PDFsuche ist eingebaut — ein lokaler Volltextindex (SQLite FTS5, seitenweise) über PDFs, Office-Dateien (docx, xlsx, odt, doc, xls), Markdown und Mails (Thunderbird, .eml, .msg) in frei wählbaren Ordnern und Laufwerken; gescannte PDFs werden im Hintergrund über alle Seiten per OCR erkannt. Neuer Reiter **Suche** mit Filtern (Typ, Ordner, Zeitraum, Steuerjahr, Kategorie, Korrespondent, Betrag) und Vorschau direkt auf der Trefferseite, eine **Browser-Oberfläche** (nur lokal) und ein **MCP-Server** für KI-Assistenten wie Claude (`suche`, `dokument_lesen`, `index_status`). Der Hintergrunddienst `pdfsm-dienst` indiziert einmal täglich, sobald der Rechner zehn Minuten nicht benutzt wird. Volltext und PDFSM-Metadaten liegen in **einer** Such-Datenbank, **nie doppelt OCR** dank OCR-Cache nach Bildinhalt, und neue Scans bekommen standardmäßig eine **Textebene** (abschaltbar, Altbestand auf Wunsch). Außerdem: eigenes Feld **Datum** mit besserer Datumserkennung (#132), die KI kennt die Ablageorte ähnlicher Dokumente, lokaler KI-Anbieter Strata, PDFs stapeln wie in PaperPort, kleinere Kacheln (#117), Dateiname folgt sofort der Kategorie (#113), KI-Statusanzeige mit Grund und Abhilfe, kein langes Warten mehr beim ersten Klick auf gescannte PDFs (#108) (siehe CHANGELOG.md).

**paperless-ngx**: v2.19 (Okt. 2025) verschachtelte Tags; **v3.0.0 (22.07.2026)**: native KI (LLM-Vorschläge für Titel/Datum/Tags/Korrespondent/Typ, Embedding-Index, Dokumenten-Chat mit Quellen, Ollama oder OpenAI-kompatibel), neue Volltextsuche (Tantivy), Dokumentversionen, Remote-OCR (Azure AI), Share-Link-Bundles, Parser-Plugins; **v3.1.0 (27.08.2026)**: Workflow-Aktion „KI-Vorschläge anwenden“, Dateien als Versionen zusammenführen; **v3.2.0 (19.09.2026)**: Filter für Duplikate, zentrale Verwaltung von Freigabe-Links und Bundles, erweiterte Suche mit Whoosh-kompatibler Syntax, besseres Matching für Korrespondenten, Speicherpfade und Labels (Mindestschwelle), automatische KI-Vorschläge für den Posteingang abschaltbar; **v3.3.0 (06.10.2026)**: Barcode-Inhalte werden gespeichert, gelistet und sind durchsuchbar, eigener API-Key für Embeddings, Zusatzparameter für LLMs, mehr Kontrolle über Vorschlagsanfragen; **v3.4.0 (29.10.2026)**: Custom Fields in Titelvorlagen von Workflows, relative Datumsabfragen auf Custom Fields, Markdown im KI-Chat, Upload-Knopf in der Navigationsleiste. Dazwischen Fehlerbehebungen bis **v3.4.2 (03.11.2026)**, darunter eine Sicherheitslücke (v3.3.2, GHSA-c8f3-pqr2-rr24) und Sicherheitsupdates von Abhängigkeiten (v3.3.4).

**KI-Addons**: paperless-ai (Auto-Tagging + RAG-Chat) hat seit November 2025 (v3.0.9) kein Release mehr — die Kernfunktionen sind jetzt in paperless-ngx selbst. paperless-gpt ist aktiv (v0.28 bis v0.31, September/Oktober 2026) und hat sich auf **LLM-Vision-OCR** spezialisiert (schlechte Scans per Bildmodell lesen, durchsuchbare PDFs erzeugen — seit v0.30.0 auch als neue Dokumentversion, und auf Wunsch ohne OCR für Seiten, die schon sauberen Text haben). Dazu kamen **KI-Workflows** mit eigenen Prompts und Schritten je Dokumentart (v0.30.0, eigene Custom Fields je Workflow in v0.31.0) und die **automatische Verknüpfung** zusammengehöriger Dokumente (z. B. Mahnung und Rechnung, gleiches Aktenzeichen) über Document-Link-Felder (v0.29.0).

---

## 3. Feature-Vergleich

Legende: ✅ vorhanden · ◐ teilweise · ❌ nicht vorhanden. „Beleg“ nennt die Stelle im PDFSM-Code oder die CHANGELOG-Version.

### 3.1 Dokumenteneingang und Automatisierung

| Feature | paperless-ngx | PDF Sortier Meister | Beleg |
|---|---|---|---|
| Eingangsordner wird **automatisch überwacht** | ✅ Consume-Ordner, Verarbeitung im Hintergrund | ◐ Die Sortier-Analyse startet nur, wenn die App offen ist und der Ordner geladen wird (Vorab-Analyse und KI-Queue laufen dann im Hintergrund). Seit v0.24.0 liest die Dokumentensuche neue Scans beim täglichen Lauf im Leerlauf oder per „Jetzt indizieren“ ein, mit OCR und Textebene, auch ohne geöffnetes Fenster. Ein Ordner-Watcher fehlt weiterhin | `watchdog` steht in `requirements.txt:25`, wird aber nirgends importiert; `src/search/zeitplan.py`; `main_window._schedule_pre_caching`, `pdf_cache.PDFAnalysisWorker` |
| Upload per Web-Oberfläche / Drag & Drop | ✅ | — (nicht anwendbar, Dateien liegen lokal) | |
| **E-Mail-Abruf** (IMAP, Regeln, OAuth Gmail/Outlook, alle 10 min) | ✅ | ❌ kein Abruf; lokale Postfächer (Thunderbird, `.eml`, `.msg`) sind seit v0.24.0 durchsuchbar, werden aber nicht sortiert | kein IMAP-Abruf im Code (grep imap trifft nur den Thunderbird-Ordner `ImapMail/`); `src/search/mbox.py` |
| REST-API / Webhooks / Pre-/Post-Consume-Skripte | ✅ | ◐ keine REST-API, keine Webhooks; seit v0.24.0 ein MCP-Server für KI-Assistenten (nur lesend: `suche`, `dokument_lesen`, `index_status`) und die Kommandozeile `pdfsm-dienst` (u. a. `index`, `suche`, `lesen`, `status`, `web`, `mcp`, `textebene`); dazu Startparameter „Ordner oder PDF-Datei öffnen“ und Explorer-Kontextmenü auf Ordnern | `src/search/mcp_server.py:71-101`, `src/search/dienst.py:64-122`, `src/main.py:75 _extract_path_arg`, `src/utils/explorer_integration.py:12-14` |
| **Regeln / Workflows** | ✅ Trigger (Eingang, hinzugefügt, geändert, zeitgesteuert), Aktionen (Zuweisen/Entfernen von Tags, Korrespondent, Typ, Pfad, Custom Fields, Besitzer, E-Mail, Webhook, Papierkorb, Passwort entfernen, KI-Vorschläge anwenden); Titelvorlagen auch mit Custom Fields (v3.4.0) | ◐ WENN-DANN-Regeln mit 5 Bedingungen (Korrespondent, Kategorie, Betrag, Datum, Stichwörter) und 4 Aktionstypen — **aber nur als Hinweis in der Statusleiste**, und der wird erst *nach* dem Verschieben geprüft, in zwei von drei Pfaden ohne Metadaten. Praktisch greift heute keine Regel. | `src/core/rule_engine.py:50-56`, `src/gui/main_window.py:600-636` („KEIN Auto-Move ohne User-Bestätigung in v1“), Aufrufe `:2281, :2358, :2891` |
| **Lernender Klassifikator** | ✅ „Auto“-Matching (Klassifikator wird stündlich aus den Dokumenten trainiert) | ✅ TF-IDF lernt aus jeder Verschiebung, Jahres-Varianten von Ordnern; LLM nur bei niedriger Konfidenz | `src/ml/classifier.py:349 learn`, `:668 _year_variant` (v0.15.0 #30), `hybrid_classifier.py:80 LOCAL_CONFIDENCE_THRESHOLD` |
| **Barcodes / ASN** (Trennseiten, Archivnummer, Tag-Barcodes) | ✅ seit v3.3.0 werden Barcode-Inhalte auch gespeichert, gelistet und sind durchsuchbar | ❌ | grep barcode: keine Treffer |
| Duplikaterkennung (Prüfsumme) | ✅ prüfsummenbasiert, Duplikate werden markiert (optional verworfen); Filter für Duplikate seit v3.2.0 | ❌ | — |
| Weitere Formate (Bilder, Office, E-Mail) | ✅ (Office via Tika/Gotenberg) | ◐ Sortieren nur `*.pdf`; die Dokumentensuche indiziert seit v0.24.0 auch Office-Dateien (docx/docm, xlsx/xlsm, doc, xls, odt), Markdown und Mails; Bilder (JPG/PNG) weder noch | `src/core/file_manager.py:64 get_pdf_files`, `src/search/konfig.py:25-27 STANDARD_ENDUNGEN` |

### 3.2 Metadaten und Organisation

| Feature | paperless-ngx | PDF Sortier Meister | Beleg |
|---|---|---|---|
| **Ordnerstruktur frei wählbar** | ◐ Storage Paths mit Jinja2-Vorlagen (`{{created_year}}/{{correspondent}}`), aber innerhalb des paperless-Medienordners | ✅ Bestehende Ordner bleiben; Vorschläge kommen aus der eigenen Struktur (gelernt + Jahres-Variante). Seit v0.24.0 nennt die KI zusätzlich den Ablageort ähnlicher, schon einsortierter Dokumente („KI: ähnliche Dokumente liegen dort“, ganz oben; das Jahr wird auf das Dokumentjahr korrigiert). Neue Unterordner schlägt sie nicht vor; der KI-Ordnerpfad `suggest_folders` wird aus der Oberfläche weiterhin nicht aufgerufen (siehe Issue #116) | `classifier.py:668`, `hybrid_classifier.py:242 suggest_folders`, `src/core/similar_documents.py` |
| **Dateiname** selbst bestimmen | ◐ Dateinamen-Format global/pro Storage Path | ✅ Muster mit Platzhaltern (`{datum}_{kontakt}_{betreff}`, eigene Muster speichern), KI füllt sie aus; der Vorschlag zieht sofort nach, wenn Kategorie oder Korrespondent eingetragen werden (#113); `{datum}` kommt aus dem Feld Datum (#132); Ordnernummern-Präfix (`JK 069-03-05-…`) | `src/core/filename_placeholders.py:23-79`, `folder_naming.py` (v0.17.0 #42, v0.21–0.23, v0.24.0 #113, #132) |
| **Tags** (mehrwertig, verschachtelt, farbig) | ✅ inkl. Nested Tags (Tiefe 5) | ❌ eine einwertige **Kategorie**; Stichwörter landen als `pdf:Keywords` in der PDF, sind aber nicht als Tag-System bedienbar | `src/core/metadata_choices.py:9-12`, `pdf_metadata.py:93-94` |
| **Korrespondenten** | ✅ mit Matching-Regeln | ✅ Tabelle mit Aliasen, Farbe, Notizen, Zusammenführen, automatisches Sammeln aus der Historie, Wiedererkennung im Text; Klick filtert | `database.py:136, 1684, 1781, 1915`, `korrespondent_match.py:32` (v0.13.0, v0.23.0 #109) |
| Dokumenttypen | ✅ | ✅ als Kategorie (Rechnung, Vertrag, Steuer, Versicherung, Bank, Gehalt, Arzt, Energie, …) | `metadata_choices.py` (#110) |
| **Custom Fields** (Text, Zahl, Datum, Währung, Auswahl, Dokument-Link, URL, Boolean) | ✅ 9 Feldtypen, frei definierbar; relative Datumsabfragen seit v3.4.0 | ◐ fester Satz Steuer-/Buchhaltungsfelder: Korrespondent, Datum (Buchungsdatum, seit v0.24.0 eigenes Feld im Detail-Panel, #132), Steuerjahr, Netto, Brutto, Währung, MwSt, IBAN, steuerlich absetzbar, Zusammenfassung | `src/core/pdf_metadata.py:20-38` |
| **Metadaten in der PDF-Datei** (portabel) | ❌ nur Datenbank; eingebettete PDF-Metadaten werden beim Import **nicht ausgewertet** (Maintainer, Discussion #5053) | ✅ XMP (`dc:title`, `dc:subject`, `dc:description`, `pdf:Keywords`) + Info-Dictionary (`/Korrespondent`, `/Buchungsdatum`, `/Steuerjahr`, `/IBAN`, …), im Hintergrund geschrieben und gelesen; seit v0.24.0 liest auch der Suchindex die Felder aus der Datei, so dass auf anderen Rechnern sortierte PDFs ihre Werte mitbringen | `pdf_metadata.py:84-94, 173-190`; `main_window.py:2473 _write_pdf_metadata`; `detail_panel.py:817 load_metadata_from_pdf`; `src/search/extract.py:219 pdf_metadaten` |
| Notizen pro Dokument, Audit-Historie, **Dokumentversionen** | ✅ | ❌ (nur Undo-Stack der letzten Aktionen; Sicherungskopien beim Stapeln und vor dem Schreiben der Textebene, dort mit Protokoll und Rückgängig) | `main_window.py:3112 undo_last_action`, `src/search/textebene.py` |
| Gespeicherte Ansichten / Dashboard | ✅ | ❌ | — |
| Mehrfachauswahl / Stapelbearbeitung | ✅ Bulk-Edit | ✅ Shift/Ctrl-Auswahl, Verschieben, Kopieren, LLM-Stapelumbenennung | `main_window.py:2365, 3263` |

### 3.3 Suche und KI

| Feature | paperless-ngx | PDF Sortier Meister | Beleg |
|---|---|---|---|
| **Volltextsuche** | ✅ Tantivy (seit v3.0), Autovervollständigung, Feldsyntax (`tag:… created:[2024 to 2025]`), Fuzzy, „Mehr wie dieses“; erweiterte Suche seit v3.2.0 mit Whoosh-kompatibler Syntax | ✅ Reiter **Suche** (seit v0.24.0): SQLite FTS5 je Seite, Syntaxhilfe (Wortfolgen, UND/ODER/NICHT/NAHE, Wortanfang), Filter Typ/Ordner/Zeitraum/Sortierung und Steuerjahr/Kategorie/Korrespondent/Betrag (auch ohne Suchbegriff), hervorgehobene Fundstellen mit Seitenangabe, Vorschau springt auf die Trefferseite; die Werkzeugleisten-Suche (Strg+F) zeigt ihre Treffer dort; dieselbe Suche in der Browser-Oberfläche und per MCP; kein „Mehr wie dieses“, keine Feldsyntax im Suchtext | `src/search/db.py:571 fts_abfrage, :634 suche`, `src/gui/search_view.py` (v0.24.0) |
| Index-Umfang | ganzes Archiv automatisch, Volltext | ✅ frei wählbare Ordner und Laufwerke, auch außerhalb der Sortier-Ordner (mit Vorrang-Ordnern und Ausschlüssen), täglicher Lauf im Leerlauf; **Volltext aller Seiten** (OCR aller Bildseiten; Dokumente mit mehr als 1.000 Bildseiten werden übersprungen, Grenze einstellbar); sortierte, umbenannte und gestapelte PDFs melden sich sofort beim Index. Die frühere 5.000-Zeichen-Grenze des Index ist weg; nur der Chat-Kontext nimmt je Dokument weiter die ersten 5.000 Zeichen (siehe RAG-Chat) | `src/search/konfig.py:110 ocr_max_seiten`, `src/search/indexer.py`; `database.py:904` (Chat-Kontext); `docs/SUCHE_ARCHITEKTUR.md` Abschnitt 3.1 |
| **KI-Vorschläge** (Titel/Name, Kategorie, Korrespondent, Datum) | ✅ nativ seit v3.0 (Ollama oder OpenAI-kompatibel, `PAPERLESS_AI_ENABLED`), seit v3.2/v3.3 feiner steuerbar (automatische Vorschläge im Posteingang abschaltbar, Zusatzparameter für LLMs); Addons paperless-ai/-gpt zusätzlich | ✅ Ollama (lokal, Auto-Start, Hardware-Empfehlung im Assistenten), Strata (lokaler OpenAI-kompatibler Server, seit v0.24.0), Ollama Cloud, OpenRouter, Claude, OpenAI, Poe; Metadaten-Extraktion (Datum, Betrag, MwSt, IBAN, Steuerjahr); gelernte Stil-Beispiele und seit v0.24.0 die Ablageorte von bis zu fünf ähnlichen Dokumenten im Prompt | `src/ml/*_provider.py` (u. a. `strata_provider.py`), `llm_provider.py`, `src/core/similar_documents.py`, `src/utils/hardware.py` (v0.16.0, v0.20.0, v0.24.0) |
| **RAG-Chat** über die eigenen Dokumente | ✅ nativ seit v3.0: Embedding-Index (HuggingFace/Ollama/OpenAI-kompatibel, täglicher Cron), Chat über ein oder mehrere Dokumente mit Quellenlinks; eigener API-Key für Embeddings (v3.3.0), Markdown im Chat (v3.4.0) | ✅ Chat-Tab, Antworten mit klickbaren Quellen (seit v0.24.0 direkt auf der Seite der Fundstelle), Whitelist gegen erfundene Zitate, Offline-Fallback als Trefferliste; sucht seit v0.24.0 im neuen Index, also auch in Mails und Office-Dateien; **Retrieval weiterhin rein stichwortbasiert** (FTS5-OR-Query, Top-8, je Dokument ein Ausschnitt von 2.000 Zeichen aus den ersten 5.000 Zeichen), keine Embeddings (bewusste v1-Entscheidung in `docs/ARCHITECTURE.md`), Verlauf nur in der Sitzung | `src/rag/retrieval.py:223 _build_fts5_query`, `rag_controller.py:85 ask`, `src/utils/config.py:36-40`, `database.py:904` (v0.12.0 #20) |
| KI-Datenschutz | Opt-in, Warnhinweis; lokale Modelle möglich | Consent-Gate für Cloud-Provider (Strata zählt als lokal), nur Textauszug (500–5000 Zeichen), Standard „keine KI“; Dokumentensuche: ohne Zustimmung im Assistenten wird nichts indiziert, der Index bleibt auf dem Rechner (ein KI-Assistent liest per MCP nur, wenn er dafür eingerichtet wird) | `config.py:97 cloud_consent`, `settings_dialog.py:242` |
| LLM-Vision-OCR für schlechte Scans | ◐ über paperless-gpt (OpenAI/Ollama/Mistral/Claude, Azure DI, Google Document AI); seit v0.30.0 auf Wunsch nur für Seiten ohne sauberen Text | ❌ | — |

### 3.4 OCR und PDF-Verarbeitung

| Feature | paperless-ngx | PDF Sortier Meister | Beleg |
|---|---|---|---|
| **OCR** | ✅ Tesseract für alle Dokumente, 100+ Sprachen, OCRmyPDF; optional Azure AI | ✅ Tesseract gebündelt (Win/Mac); seit v0.24.0 erkennt die Dokumentensuche im Hintergrund alle Bildseiten (Dokumente mit mehr als 1.000 Bildseiten werden übersprungen, Grenze einstellbar), Sprachen einstellbar (Standard `deu+eng`), 300 dpi; die Analyse beim Klick nimmt den Text aus dem Index und erkennt nur, wenn er fehlt, höchstens 5 Bildseiten; ein OCR-Cache nach Bildinhalt verhindert doppelte OCR (übersteht Umbenennen, Verschieben, Metadaten-Schreiben, Stapeln, Teilen). Kein Drehen/Bestwert für schwer lesbare Scans (#47) | `src/search/konfig.py:107-110`, `pdf_analyzer.py:76 OCR_MAX_SEITEN`, `docs/SUCHE_ARCHITEKTUR.md` Abschnitt 3.3 |
| Durchsuchbare PDF / **PDF/A-Archivkopie** | ✅ Textebene wird eingebettet, PDF/A erzeugt | ◐ seit v0.24.0 **Textebene** (unsichtbarer OCR-Text), geschrieben vom Indexlauf der Dokumentensuche: für neue Scans im Scan-Eingang standardmäßig, Altbestand auf Wunsch (mit Schätzung vorab); das Scanbild bleibt byte-genau, rund 3 KB je Seite, Sicherungskopie (Standard 30 Tage), Protokoll mit Rückgängig; signierte, verschlüsselte und PDF/A-Dateien bleiben unberührt. Kein PDF/A, keine Archivkopie | `src/search/textebene.py`, `src/search/konfig.py:118 textebene` |
| Seiten **trennen / zusammenfügen** | ✅ | ✅ alle Seiten einzeln oder Bereich; Merge per Kontextmenü; seit v0.24.0 PDFs stapeln per Drag & Drop wie in PaperPort (Ctrl+Z macht es rückgängig) | `file_manager.py:239 merge_pdfs, :286 stack_pdfs, :383 split_pdf` (#12, v0.24.0) |
| Seiten drehen, löschen, umsortieren | ✅ | ❌ | grep rotate: nur `src/search/textebene.py` (Drehung beim Auflegen der Textebene), kein Seiten-Editor |
| Integrierte Vorschau | ✅ (PDF.js/PNGX) | ✅ QtPdf-Vorschau, Text markieren → als Metadatum übernehmen (seit v0.24.0 auch „Als Datum übernehmen“); Suchtreffer und Chat-Zitate öffnen die Vorschau auf der Trefferseite | `pdf_preview_widget.py` (v0.19.0, v0.23.0 #109, v0.24.0 #132) |
| Passwortgeschützte PDFs entschlüsseln | ✅ Workflow-Aktion | ❌ | — |

### 3.5 Betrieb, Sicherheit, Daten

| Feature | paperless-ngx | PDF Sortier Meister | Beleg |
|---|---|---|---|
| **Mehrbenutzer, Berechtigungen** (global + pro Objekt), OIDC/SSO, 2FA | ✅ | ❌ (Einzelnutzer, keine Anmeldung) | — |
| **Mobil / anderes Gerät** | ✅ Web-UI, Apps „Paperless Mobile“ (Android), „Swift Paperless“ (iOS) | ◐ keine App; Dateien und XMP-Metadaten sind über OneDrive/iCloud auf dem Handy sichtbar, Suche/Chat nicht — die Browser-Oberfläche der Suche ist nur lokal erreichbar (127.0.0.1) | `src/search/web.py:24 ERLAUBTE_HOSTS`, `src/search/konfig.py:116` |
| **Freigabe-Links** (öffentlich, ablaufend, Bundles) | ✅ seit v3.2.0 zentral verwaltet | ❌ (Datei per Explorer/OneDrive teilen) | — |
| **Papierkorb** (30 Tage), Wiederherstellen | ✅ | ❌ Löschen nach Rückfrage, danach endgültig (`unlink`, kein Papierkorb); Undo nur für Verschieben/Umbenennen/Stapeln | `file_manager.py:236`, `main_window.py:2850-2860, 3112` |
| Backup / Export | ✅ Document-Exporter (Dateien + Metadaten), Importer | ✅ ZIP mit Datenbank, KI-Cache, Modell, Einstellungen; Wiederherstellen beim nächsten Start; Backup-Erinnerung. Der neue Suchindex (`suche.db`, mit den OCR-Ergebnissen) gehört nicht zum Backup | `src/utils/backup.py:33-34 BACKUP_FILES/BACKUP_DIRS` (v0.22.0 #98, v0.14.0 #7) |
| **Steuerauswertung** (Summen je Jahr/Kategorie, CSV) | ❌ (nur über Custom Fields + Export selbst bauen) | ✅ | `database.py:1559 get_steuerauswertung`, `steuerauswertung_dialog.py:130-143` |
| Update-Mechanismus | Container-Image ziehen | ✅ Hinweis auf neue Version (GitHub `releases/latest`), Drüberinstallieren | `update_check.py:22-24` (v0.19.0 #73) |
| Plattform | Linux/Docker (Windows „not supported“, nur via WSL/NAS) | Windows 10/11, macOS (Intel + Apple Silicon), signiert/notarisiert | README, `build.sh` (v0.18.0) |
| Cloud-Sync-Ordner (OneDrive „Dateien bei Bedarf“) | ⚠ Medienordner gehört nicht in Sync-Ordner | ✅ ausdrücklich unterstützt, langsame Zugriffe laufen in Threads; die Suche erkennt nur in der Cloud liegende Dateien und lädt sie nicht ungefragt herunter | CHANGELOG 0.15.1; `src/search/plattform.py` (v0.24.0) |
| Einrichtung | Docker Compose oder Installationsskript, Reverse-Proxy für Zugriff von außen | ✅ Setup.exe/DMG, Assistent (Ordner, GPU-Check, Ollama-Modell per Klick, seit v0.24.0 Seite „Dokumentensuche“) | `setup_wizard.py:97 detect_ollama_environment` (v0.16.0, v0.20.0, v0.24.0) |

---

## 4. Lücken-Tabelle: Was paperless-ngx kann und PDFSM heute nicht

Relevanz bezieht sich auf eine **Desktop-App für Einzelnutzer**. Aufwand: S < 0,5 Tag · M 0,5–1,5 Tage · L 2–4 Tage · XL > 1 Woche (Grobschätzung ohne Spike).

| # | Feature | paperless-ngx | PDFSM heute (Beleg) | Relevanz | Aufwand | Anmerkung |
|---|---|---|---|---|---|---|
| 1 | **Papierkorb** statt endgültigem Löschen (#124) | Trash, 30 Tage | Rückfrage, dann `unlink()` (`file_manager.py:236`) | mittel–hoch | S | `QFile.moveToTrash` ist in Qt 6 vorhanden; Undo-Eintrag ergänzen; Test für `delete_file` fehlt bisher ganz |
| 2 | **Regeln wirklich anwenden** (#125) | Workflows setzen Felder, Pfad, Tags automatisch | Hinweis erst nach dem Verschieben, in zwei von drei Pfaden ohne Metadaten (`main_window.py:600-636, 2281, 2358, 2891`); kein Konsument für die Aktionen | **hoch** | M–L | Auswertung *vor* den Move in alle drei Pfade ziehen, mit `detail_panel.get_metadata()` füttern (liegt erst nach der KI-Analyse vor), Zielordner/Dateiname im Detail-Panel vorbelegen; Auto-Verschieben ab Konfidenz 0,9 als Opt-in; Tests fehlen bisher |
| 3 | **OCR aller Seiten, mehrsprachig, Textebene zurückschreiben** — mit v0.24.0 weitgehend erledigt | OCRmyPDF, PDF/A, 100+ Sprachen | Index-OCR aller Bildseiten im Hintergrund (Grenze 1.000 Bildseiten je Dokument, einstellbar), Sprachen einstellbar (Standard `deu+eng`), Volltext seitenweise ohne 5.000-Zeichen-Grenze, Textebene für neue Scans standardmäßig, nie doppelt OCR (`src/search/konfig.py:107-118`, `src/search/textebene.py`); beim Klick weiter höchstens 5 Bildseiten, wenn der Index den Text noch nicht hat (`pdf_analyzer.py:76`) | niedrig (Rest) | S–M (Rest) | #46 ist damit inhaltlich erfüllt. Offen: #47 (schwer lesbare Scans drehen und das beste Ergebnis nehmen, als schwer lesbar markieren); kein PDF/A; signierte, verschlüsselte und PDF/A-Dateien bekommen keine Textebene; der Chat-Kontext nutzt noch die ersten 5.000 Zeichen statt der Trefferseiten (siehe #6) |
| 4 | **Eingang im Hintergrund** (Watch-Folder, Tray, Autostart, #126) | Consume-Ordner 24/7 | Sortier-Analyse und KI-Vorschläge nur bei offenem Fenster; `watchdog` ungenutzt. Seit v0.24.0 indiziert der Hintergrunddienst täglich im Leerlauf, mit OCR und Textebene (`src/search/zeitplan.py`) | **hoch** — das ist der eigentliche Kern der „Server-Frage“ | M–L | Es fehlt der Auslöser bei neuen Dateien: `QFileSystemWatcher`/watchdog auf den Scan-Ordner, dann die vorhandene Vorab-Analyse (`PDFAnalysisWorker`) und KI-Queue (`_llm_queued`) nutzen; `QSystemTrayIcon`; für den Autostart lassen sich Aufgabenplanung bzw. LaunchAgent aus `zeitplan.py` wiederverwenden |
| 5 | **Mehrwertige Tags** (verschachtelt, farbig, filterbar) | Nested Tags | einwertige Kategorie; `pdf:Keywords` wird geschrieben und ist im Suchindex durchsuchbar (Spalte `schlagwoerter`), aber nicht als Tags bedienbar | mittel | L | Tags in `pdf:Keywords` abbilden (die Index-Spalte gibt es schon); Filterleiste erweitern |
| 6 | **Semantische Suche / Embeddings im RAG** | Vektorindex (HF/Ollama/OpenAI) + Chat | FTS5-Stichwort-Retrieval (`retrieval.py:223`), Kontext je Dokument aus den ersten 5.000 Zeichen (`database.py:904`); „Keine Embeddings“ ist in `docs/ARCHITECTURE.md` als v1-Entscheidung festgehalten | mittel (Fragen ohne Stichworttreffer scheitern) | L | Hybrid: FTS5 + Ollama-Embeddings (`/api/embeddings`) mit `sqlite-vec` oder numpy. Die Voraussetzung aus #3 ist seit v0.24.0 erfüllt: Der Volltext aller Seiten liegt seitenweise im Index, Chunking pro Seite bietet sich an. Entscheidung in ARCHITECTURE.md dann fortschreiben |
| 7 | Duplikaterkennung | Prüfsumme, Duplikate markiert, Filter (v3.2.0) | keine | mittel | S–M | Hash in `pdfs`-Mastertabelle (#25); der Suchindex kennt seit v0.24.0 schon Bild-Hashes je Seite (OCR-Cache) |
| 8 | Bilder (JPG/PNG) als Eingang | ja | nur PDF (`file_manager.py:64`); auch die Suche indiziert keine Bilder | mittel | M | PyMuPDF wandelt Bild → PDF, dann normaler Weg |
| 9 | Seiten drehen / löschen / umsortieren | PDF-Editor | Merge/Split/Stapeln nur | mittel | M | pikepdf/PyMuPDF; in `split_pdf_dialog` andocken |
| 10 | Freie **Custom Fields** | 9 Feldtypen | fester Feldsatz (`pdf_metadata.py:20-38`); die Konstante `CUSTOM_NS` existiert, wird aber nicht genutzt — Custom-Felder landen im Info-Dictionary | mittel | L | Eigener XMP-Namespace, UI und Index-Spalten dynamisch |
| 11 | Gespeicherte Suchen / Ansichten | Saved Views, Dashboard | keine | niedrig–mittel | S–M | Filterzustand als benannte Config-Einträge |
| 12 | Suchsyntax mit Feldern (`kategorie:Rechnung`, Datumsbereich im Text) | Tantivy-Syntax | Operatoren UND/ODER/NICHT/NAHE, Wortfolgen, Wortanfang (`src/search/db.py:571`); Felder nur als Filter (Reiter Suche, Strg+F-Filterleiste, MCP-Parameter `steuerjahr`, `kategorie`, `korrespondent`), nicht im Suchtext | niedrig | S–M | kleiner Parser für `feld:wert` vor `fts_abfrage`, der die vorhandenen Filter setzt |
| 13 | LLM-Vision-OCR (paperless-gpt) | ja | nein | mittel bei vielen schlechten Scans | M | Ollama-Vision-Modelle (gemma3) und Claude/OpenAI können Bilder; an `PDFAnalyzer._ocr_seiten` bzw. `extract.pdf_ocr` als 2. Fallback |
| 14 | **E-Mail-Abruf** (Rechnungen aus dem Postfach) | IMAP-Regeln, OAuth | nein; lokale Postfächer (Thunderbird, `.eml`, `.msg`) sind seit v0.24.0 durchsuchbar | mittel (viele Rechnungen kommen per Mail), aber nur sinnvoll mit #4 | L | `imaplib` (stdlib), Anhänge in den Scan-Ordner legen; läuft nur, wenn die App läuft |
| 15 | Barcode-Trennseiten / ASN | ja, seit v3.3.0 Barcode-Inhalte durchsuchbar | nein | niedrig (Haushalt) / mittel (Steuerbüro, Stapelscan) | M–L | `pyzbar` + zbar-DLL bündeln |
| 16 | Notizen, Audit-Historie, Dokumentversionen | ja | nein (nur Sicherungskopien bei Stapeln und Textebene) | niedrig | L | widerspricht teils „Datei bleibt Datei“ |
| 17 | Passwort entfernen | Workflow-Aktion | nein | niedrig | S | pikepdf `open(password=…)` |
| 18 | **Mobil / Web-UI / Apps** | Web + 2 Apps | nein; Browser-Oberfläche der Suche nur lokal (127.0.0.1); Dateien via OneDrive | niedrig–mittel | XL | nur mit Server; siehe Abschnitt 6 |
| 19 | **Mehrbenutzer, Berechtigungen, Freigabe-Links** | ja | nein | niedrig | XL | nur mit Server |
| 20 | REST-API / Webhooks / Skript-Hooks | ja | keine REST-API; seit v0.24.0 MCP-Server (lesend) und Kommandozeile `pdfsm-dienst` | niedrig | L–XL | MCP deckt den Fall „KI-Assistent fragt das Archiv ab“ ab; Kommandozeilen-Hooks (Post-Move-Skript) wären eine Desktop-Variante (M) |
| 21 | Office-Formate (Tika/Gotenberg) | ja | Suche: docx, xlsx, odt, doc, xls (seit v0.24.0); Sortieren/Archivieren: nein | niedrig | XL | Umwandeln nach PDF bleibt außerhalb des Produktkerns (siehe Issue #9) |

---

## 5. Wo PDF Sortier Meister voraus ist

- **Kein Lock-in:** Dateien bleiben normale PDFs in normalen Ordnern — Explorer, OneDrive, Steuerberater-Upload funktionieren unverändert. paperless-ngx übernimmt die Datei in sein Medienverzeichnis; wer aussteigt, braucht den Exporter.
- **Metadaten reisen mit der Datei:** Kategorie, Korrespondent, Datum, Betrag, MwSt, IBAN, Steuerjahr, Zusammenfassung stehen als XMP/Info-Dictionary in der PDF (`pdf_metadata.py`) und sind in Acrobat, DEVONthink oder den Windows-Eigenschaften sichtbar; der Suchindex liest sie beim Indizieren wieder aus. paperless-ngx hält Metadaten nur in der Datenbank (Feature-Request #7049 ohne Umsetzung).
- **OCR-Text in der Originaldatei** (v0.24.0): Die Textebene kommt unsichtbar in die PDF selbst, das Scanbild bleibt byte-genau, mit Sicherungskopie und Rückgängig; Explorer-Suche, Acrobat und PaperPort finden den Text. paperless-ngx legt stattdessen eine PDF/A-Archivkopie in seinem Medienverzeichnis an.
- **Suche über den ganzen PC, nicht nur über das Archiv** (v0.24.0): PDFs (auch gescannte), Office-Dateien, Markdown und Mails werden dort durchsucht, wo sie liegen, ohne sie in eine Ablage zu übernehmen; KI-Assistenten wie Claude lesen den Index per MCP mit.
- **Steuer- und Buchhaltungsfelder plus Auswertung:** Netto/Brutto/MwSt/absetzbar je Steuerjahr mit CSV-Export (`steuerauswertung_dialog.py`) — in paperless nur über selbst angelegte Custom Fields und externe Auswertung.
- **Explorer-artiges Sortieren:** Zielordner-Vorschläge aus der eigenen Struktur und aus den Ablageorten ähnlicher Dokumente, Jahres-Varianten („Steuer 2025“ → „Steuer 2026“), Drag & Drop, Stapeln wie in PaperPort, Ctrl+Z, Explorer-Kontextmenü.
- **Dateinamen mit Verstand:** Muster mit Platzhaltern, die die KI ausfüllt, Ordnernummern-Präfix aus dem Zielpfad, gelernte Stil-Beispiele im Prompt (v0.21–0.23), Name folgt sofort Kategorie und Datum (v0.24.0).
- **Zero-Setup-KI:** Assistent prüft die Grafikkarte, empfiehlt ein Modell, startet Ollama automatisch und lädt das Modell per Klick — ohne Terminal, ohne Docker.
- **Native Desktop-Apps** für Windows und macOS mit gebündeltem Tesseract; paperless-ngx läuft offiziell nur unter Linux/Docker.
- **Text aus der Vorschau in Metadaten** übernehmen, Korrespondent wird daraus gelernt (#109); markiertes Datum wird zum Feld Datum (#132).

---

## 6. Braucht man die Server-Funktionalität wirklich?

„Server“ bedeutet bei paperless-ngx zwei verschiedene Dinge, die getrennt zu bewerten sind:

### 6.1 Nur mit Server möglich

| Nutzen | Für wen relevant |
|---|---|
| **Zugriff von mehreren Geräten / mobil** auf Suche, Metadaten, Chat (Web-UI, Android-/iOS-Apps) | Wer unterwegs *suchen* will. Wer nur die *Dateien* braucht, hat sie bei PDFSM ohnehin via OneDrive/iCloud auf dem Handy — samt XMP-Metadaten. Die Browser-Oberfläche der PDFSM-Suche ist nur lokal erreichbar. |
| **Mehrbenutzer** mit Berechtigungen, Besitzer, Gruppen, SSO | Familien-/Teamarchiv. Für Einzelnutzer irrelevant. |
| **Freigabe-Links** (ablaufend, ohne Login) | Belege an Steuerberater/Vermieter schicken — geht bei PDFSM per OneDrive-Freigabe oder E-Mail-Anhang. |
| **Verarbeitung rund um die Uhr, auch bei ausgeschaltetem PC** (Mail-Abruf, Consume-Ordner, geplante Workflows, Embedding-Index per Cron) | Nur, wenn Dokumente eintreffen, während kein Rechner läuft (z. B. Scanner schickt direkt per Mail/SMB). |
| **API/Webhooks** für andere Systeme (Home Assistant, n8n, Nextcloud) | Automatisierer. |

### 6.2 Geht auch als Desktop-App (heute teils fehlend, siehe Lücken #1–#4)

- **Eingangsordner beobachten** und neue Scans sofort analysieren, OCR-en und KI-Vorschläge vorbereiten — solange die App läuft (Tray-Icon, Autostart). Seit v0.24.0 laufen Indexierung, OCR und Textebene schon ohne geöffnetes Fenster (täglich im Leerlauf über Aufgabenplanung bzw. LaunchAgent); für die Sortier-Analyse und die KI-Vorschläge fehlt weiter der Auslöser. Der Scanner legt sowieso in einen lokalen/OneDrive-Ordner ab; ob die Auswertung um 3 Uhr nachts oder beim nächsten Einschalten passiert, ist für einen Haushalt egal.
- **Regeln automatisch anwenden** (Stadtwerke → Wohnung/Nebenkosten) — braucht keinen Server. Heute läuft die Prüfung erst nach dem Verschieben und meist ohne Metadaten; sie muss vor den Move und an die Metadaten des Detail-Panels (M–L, Lücke #2).
- **Mail-Import**: IMAP-Abruf beim App-Start oder alle n Minuten ist Desktop-tauglich; er läuft eben nur, wenn der PC an ist. Lokale Postfächer durchsucht PDFSM seit v0.24.0 bereits.
- **Volltext + RAG**: läuft lokal, seit v0.24.0 über alle Seiten und auch über Office-Dateien, Markdown und Mails; Embeddings wären auch lokal (Ollama) möglich.
- **Zugriff für KI-Assistenten**: per MCP vorhanden, lokal.
- **Backup/Restore**: vorhanden (ohne den Suchindex).

### 6.3 Bewertung

Für die Zielgruppe von PDF Sortier Meister — Einzelnutzer, Scans landen ohnehin in einem (OneDrive-)Ordner, Ordnerstruktur soll erhalten bleiben — ist ein Server **nicht nötig**. Die spürbaren Vorteile von paperless-ngx im Alltag sind nicht der Server an sich, sondern **(a) alles passiert automatisch im Hintergrund**, **(b) OCR ist immer vollständig und in der Datei**, **(c) Regeln greifen ohne Klick**. Alle drei sind als Desktop-Funktionen umsetzbar (Lücken #2–#4) und sollten Vorrang vor jeder Server-Überlegung haben; (b) ist mit v0.24.0 weitgehend umgesetzt, (a) zur Hälfte (Indexierung ja, Sortier-Analyse nein). Ein eigener Web-/Server-Modus (XL) würde dagegen genau das Kernversprechen („kein Docker, kein Server, keine Datenbank-Silo“) aufgeben, mit dem sich PDFSM von paperless-ngx unterscheidet.

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

1. **Kein Server, kein Web-Modus für andere Geräte.** Die Differenzierung „Dateien bleiben deine Dateien, Metadaten in der PDF, kein Docker“ ist intakt und durch paperless' Roadmap (v3: KI, Versionen, Remote-OCR — alles serverseitig) eher schärfer geworden. Die Browser-Oberfläche der Suche bleibt lokal.
2. **Die Alltagslücken schließen**, die paperless-Nutzer als „Server-Vorteil“ empfinden, aber keine sind: OCR vollständig mit Textebene und ohne 5.000-Zeichen-Deckel ist mit v0.24.0 erledigt (#46; Rest #47). Offen bleiben Papierkorb (#124, S), Regeln anwenden (#125, M–L) und der Postfach-Modus mit Watch-Folder + Tray (#126, M–L; Hintergrunddienst und Zeitplan gibt es seit v0.24.0).
3. **RAG ehrlich einordnen:** PDFSM-Chat ist stichwortbasiert (FTS5) und damit robust, aber bei Fragen ohne Wortüberschneidung unterlegen. „Keine Embeddings“ war eine bewusste v1-Entscheidung (`docs/ARCHITECTURE.md`, Abschnitt 3; Zusammenfassung in `docs/RAG_ARCHITECTURE_SUMMARY.md`). Die Voraussetzungen für einen hybriden Modus mit lokalen Embeddings (Ollama) sind seit v0.24.0 erfüllt (OCR aller Seiten, Volltext seitenweise im Index); er ist damit der nächste sinnvolle Schritt, zusammen mit einem Chat-Kontext aus den Trefferseiten statt aus den ersten 5.000 Zeichen. Die Entscheidung dann in ARCHITECTURE.md fortschreiben.
4. **Tags** erst danach; Kategorie + Korrespondent + Steuerfelder decken den Steuer-/Haushalts-Fall ab, verschachtelte Tags sind ein paperless-Konzept, das ohne Ordnerbezug arbeitet.
5. Dieses Dokument bei jedem Release gegen die aktuelle paperless-ngx-Version prüfen (Punkt in `docs/RELEASE_CHECKLISTE.md`), sonst ist es in sechs Monaten wieder falsch.

---

## Quellen (abgerufen 05.09.2026, Releases ergänzt 06.11.2026)

- paperless-ngx Dokumentation (Branch `dev`, docs.paperless-ngx.com blockt automatisierte Abrufe): Usage <https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/dev/docs/usage.md>, Advanced Usage <https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/dev/docs/advanced_usage.md>, Configuration <https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/dev/docs/configuration.md>, Setup <https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/dev/docs/setup.md>, Übersicht <https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/dev/docs/index.md>
- paperless-ngx Releases: v3.0.0 (22.07.2026) <https://github.com/paperless-ngx/paperless-ngx/releases/tag/v3.0.0>, v3.1.0 (27.08.2026) <https://github.com/paperless-ngx/paperless-ngx/releases/tag/v3.1.0>, v2.19.0 (21.10.2025, Nested Tags) <https://github.com/paperless-ngx/paperless-ngx/releases/tag/v2.19.0>, v3.2.0 (19.09.2026) <https://github.com/paperless-ngx/paperless-ngx/releases/tag/v3.2.0>, v3.3.0 (06.10.2026) <https://github.com/paperless-ngx/paperless-ngx/releases/tag/v3.3.0>, v3.3.2 (16.10.2026, Sicherheitsupdate) <https://github.com/paperless-ngx/paperless-ngx/releases/tag/v3.3.2>, v3.4.0 (29.10.2026) <https://github.com/paperless-ngx/paperless-ngx/releases/tag/v3.4.0>, v3.4.2 (03.11.2026) <https://github.com/paperless-ngx/paperless-ngx/releases/tag/v3.4.2>
- PDF-Metadaten werden von paperless nicht ausgewertet: <https://github.com/paperless-ngx/paperless-ngx/discussions/5053>; Feature-Request Metadaten in PDF speichern: <https://github.com/paperless-ngx/paperless-ngx/discussions/7049>
- paperless-ai (clusterzx): <https://github.com/clusterzx/paperless-ai>, Funktionen <https://github.com/clusterzx/paperless-ai/wiki/3.-Functions>, Releases (letztes v3.0.9, 04.11.2025) <https://github.com/clusterzx/paperless-ai/releases>
- paperless-gpt (icereed): <https://github.com/icereed/paperless-gpt>, Releases v0.29.0 (05.10.2026), v0.30.0 (12.10.2026), v0.31.0 (14.10.2026) <https://github.com/icereed/paperless-gpt/releases>
- Mobile Apps: Paperless Mobile <https://github.com/astubenbord/paperless-mobile>, Swift Paperless <https://github.com/paulgessinger/swift-paperless>, Related Projects <https://github.com/paperless-ngx/paperless-ngx/wiki/Related-Projects>
- PDF Sortier Meister: CHANGELOG.md (Einträge für v0.24.0), README.md, docs/ARCHITECTURE.md (RAG), docs/SUCHE_ARCHITEKTUR.md (Dokumentensuche), Quellcode Stand v0.24.0 (Belege in den Tabellen).

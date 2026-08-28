# Changelog

Alle nennenswerten Aenderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Hinzugefuegt
- **Ollama-Empfehlung fuer Laptops ohne dedizierte GPU** (Issue #62): hat das
  System genug Arbeitsspeicher (ab 16 GB, z.B. schneller Shared-RAM), empfiehlt
  der Einrichtungs-Assistent jetzt `gemma3:1b` lokal als "moeglich, aber
  langsamer" statt direkt auf Ollama Cloud zu verweisen; Ollama Cloud bleibt
  als Alternative im Empfehlungstext genannt. Bei wenig Arbeitsspeicher bleibt
  es bei der bisherigen Cloud-Empfehlung.
- `docs/RELEASE_CHECKLISTE.md`: Ablauf fuer Releases mit Pflichtpunkt
  "LLM-Modell-Empfehlungen pruefen" (Issue #63), in README verlinkt.
- **Einrichtungs-Assistent: Default-Ordner und Zielordner-Schritt** (Issues #61, #64):
  Der Scan-Ordner-Schritt schlaegt jetzt automatisch `Dokumente/Scans` vor
  (bzw. `~/Documents/Scans` unter macOS), sobald noch kein Ordner konfiguriert
  ist - der Vorschlag kann per "Weiter" uebernommen oder ueber "Ordner
  auswaehlen" ersetzt werden. Neuer Schritt "Zielordner" direkt danach mit
  demselben Bedienkonzept (Default `Dokumente/PDF-Sammlung`); beide Ordner
  werden beim Abschluss des Assistenten angelegt, falls sie noch nicht
  existieren, der Zielordner wird zugleich als Zielordner registriert. Nach
  dem Assistenten (Erststart wie auch erneuter Aufruf ueber Extras) zeigt das
  Hauptfenster links den Scan-Ordner und rechts sofort den neuen Zielordner an.
- **Aktivitaetsanzeige fuer KI-Aufrufe** (Issue #68): Solange die KI arbeitet, zeigt
  die Statusleiste eine vorwaerts laufende Uhr ("KI arbeitet „rechnung.pdf“ seit 0:42")
  und - sobald Erfahrungswerte fuer dasselbe Provider/Modell-Setting vorliegen - eine
  Schaetzung ("ca. 30 s", Median der letzten 20 Aufrufe, gespeichert in
  `llm_timing.json` im Datenverzeichnis). Dasselbe im Chat ("KI denkt… seit 0:05 ·
  ca. 20 s") und auf dem Button "KI-Metadaten neu generieren".
- "KI-Metadaten neu generieren" laeuft jetzt im Hintergrund - vorher fror das Fenster
  fuer die Dauer der Anfrage ein (Kern: `src/core/llm_activity.py`).

### Geaendert
- `src/utils/hardware.py`: Modell-Empfehlungstabelle (`MODEL_TIERS`,
  `RAM_ONLY_MODEL`, `CLOUD_MODEL`) zu einer zentralen, kommentierten
  Datenstruktur mit Pruefdatum (`MODEL_TIERS_CHECKED_ON`) zusammengefasst,
  damit ein Update der LLM-Empfehlungen an einer Stelle passiert (Issue #63).
- Poe.com ist wieder als KI-Anbieter waehlbar (poe.com vergibt wieder API-Keys;
  in 0.19.0 entfernt).


## [0.19.0] - 2026-08-28

### Hinzugefuegt
- **Integrierte PDF-Vorschau** (Issues #74, #76) auf Basis von QtPdf (Qts eigener,
  PDFium-basierter Viewer - kein Browser, kein QtWebEngine, kein eigener Renderer):
  - Unten im mittleren Bereich zeigt das Detail-Panel die ausgewaehlte PDF mit
    Seitenblaettern, Zoom (auch Strg+Mausrad), "Breite"/"Seite"-Anpassung; ein
    vertikaler Splitter regelt die Aufteilung zwischen Metadaten und Vorschau.
  - Doppelklick auf ein Thumbnail (bzw. "PDF oeffnen" im Kontextmenue, Suchtreffer,
    Chat-Zitate) oeffnet standardmaessig ein eigenes Vorschau-Fenster statt des
    Browsers/Office. Das Fenster wird wiederverwendet, merkt sich seine Groesse,
    Esc schliesst es; "Extern oeffnen" startet das externe Programm.
  - Einstellungen > Allgemein > **PDF oeffnen**: Integrierte Vorschau (Default),
    Standardprogramm des Systems oder eigenes Programm mit Pfad (z.B. PDF-XChange,
    Acrobat); fehlt das Programm, faellt die App mit Hinweis auf das Standardprogramm
    zurueck (`src/utils/pdf_open.py`).
  - Die Vorschau haelt keinen Datei-Handle offen (PDF wird in den Speicher gelesen),
    damit Verschieben und Umbenennen waehrend der Anzeige weiter funktionieren; das
    Einlesen laeuft im Hintergrund (OneDrive Files-On-Demand blockiert die GUI nicht).
  - PyInstaller-Spec buendelt `PyQt6.QtPdf`/`QtPdfWidgets` (Qt6Pdf.dll).
  - Detail-Panel kompakter: Metadaten zweispaltig (Kategorie|Korrespondent, Netto|Brutto,
    Waehrung|MwSt, IBAN|Steuerjahr, Zusammenfassung volle Breite), Vorschlagsliste nur so
    hoch wie noetig, kleinere Abstaende; die Aufteilung Details/Vorschau wird gespeichert.
- **Update-Pruefung** (Issue #73): Kurz nach dem Start fragt die App im Hintergrund
  die Versionsnummer des neuesten GitHub-Releases ab (`src/utils/update_check.py`,
  nur `releases/latest`, keine Nutzerdaten). Gibt es eine neuere Version, erscheint
  ein Hinweis in der Statusleiste und ein Dialog mit "Download-Seite oeffnen",
  "Diese Version ueberspringen" und "Spaeter". Manuell ueber Hilfe > Nach Updates
  suchen; abschaltbar unter Einstellungen > Allgemein > Updates.

### Behoben
- **KI-Zusammenfassung blieb leer** (und teils Kategorie/MwSt-Satz): Der Prompt fragt
  die Schluessel `beschreibung`, `category`, `mwst` ab, Detail-Panel, Umbenennen-Dialog
  und Datenbank lesen aber `description`, `subject`, `mwst_satz`. Ob die Felder gefuellt
  wurden, hing davon ab, ob sich das Modell an den Prompt hielt. Jetzt werden alle
  bekannten Schluessel-Varianten beim Parsen der Antwort und beim Laden aelterer
  Cache-Eintraege auf einen Satz kanonischer Namen abgebildet
  (`normalize_llm_metadata` in `src/ml/llm_provider.py`); Platzhalter wie `UNBEKANNT`
  landen nicht mehr in den Feldern.

## [0.18.0] - 2026-08-28

### Hinzugefuegt
- **macOS-Unterstuetzung** bei gemeinsamer Codebasis: Der Build erzeugt neben der
  Windows-Version jetzt auch eine macOS-App (`.app` + DMG, Apple Silicon und Intel).
  Tesseract-OCR ist wie unter Windows gebuendelt (`scripts/prepare_tesseract_mac.py`),
  die DMGs werden mit Developer ID signiert und notarisiert. Lokaler Build: `./build.sh`.
- **GitHub-Actions-CI**: Tests laufen bei jedem PR auf Windows und macOS; ein
  Versions-Tag baut automatisch alle Release-Assets (Setup.exe, win64-Zip, zwei DMGs)
  als Draft-Release.
- Neues Modul `src/utils/platform_paths.py` buendelt alle plattformabhaengigen
  Basisfunktionen (Datenverzeichnis, Dateien/Ordner oeffnen, Dateimanager-Name).
  Unter macOS liegen Einstellungen/Lerndaten in `~/Library/Application Support/
  PDF_Sortier_Meister`; unter Windows unveraendert `%APPDATA%\PDF_Sortier_Meister`.
- Ollama-Empfehlung kennt Apple Silicon: Unified Memory zaehlt als Grafikspeicher
  (Metal), RAM-Erkennung via `sysctl`.
- **Demo-PDFs fuer Beta-Tester** (Issue #52): `python scripts/generate_demo_pdfs.py`
  erzeugt 23 fiktive Testdokumente (Rechnungen, Vertraege, Kontoauszug,
  Gehaltsabrechnung, Steuerbescheid, gescannte Belege ohne Textebene, Sammelscan
  zum Aufteilen) und packt sie als ZIP nach `data/demo/`.

### Behoben
- Doppelklick auf eine PDF haette die App unter macOS zum Absturz gebracht
  (ungeschuetztes `os.startfile`); oeffnet jetzt plattformuebergreifend den
  Standard-Viewer.
- **Absturz beim Schliessen** waehrend eines laufenden Ordner-Scans oder
  Metadaten-Lesens: Das Hauptfenster stoppt beim Schliessen seine Timer und
  wartet auf seine Hintergrund-Threads; der PDF-Cache haelt einen nach dem
  Stop-Timeout noch laufenden Analyse-Thread referenziert, statt ihn Qt im
  Betrieb loeschen zu lassen (harter Prozessabbruch).
- CI-Testlauf auf Windows und macOS repariert (`pythonpath` fuer pytest,
  Hardware-Tests unabhaengig vom Apple-Silicon-Runner).

## [0.17.0] - 2026-08-27

### Hinzugefuegt
- **Dateiname aus Ordnerstruktur** (Issue #42, Opt-in unter Einstellungen >
  Dateinamen-Muster): Beim Verschieben wird der Dateiname nach einer konfigurierbaren
  Vorlage aus dem Zielordner-Pfad aufgebaut. Platzhalter: `{initialen}`,
  `{ordnernummern}` (Nummernkette aus dem Zielordner-Namen, z.B. "069-03-05"),
  `{ordnerpfad}`, `{datum}` (JJJJMMTT), `{datum_iso}`, `{text}` (bisheriger Name ohne
  Datum). Default-Vorlage `{initialen} {ordnernummern}-{datum}-{text}` ergibt z.B.
  `JK 069-03-05-20260512-Rechnung.pdf` (Kernlogik: `src/core/folder_naming.py`).
- **Tooltips fuer den Kern-Workflow** (Issue #51): Zielordner-Baum und -Kacheln
  erklaeren Einfachklick (PDF verschieben) vs. Doppelklick (Ordner oeffnen);
  Thumbnails, Metadaten-Felder, Filterleiste und Tabs haben erklaerende Tooltips.
- **"Erste Schritte"-Hinweis** (Issue #51): einmaliger Dialog nach dem Start erklaert
  den 3-Spalten-Workflow, mit "Nicht mehr anzeigen"-Checkbox; jederzeit erneut ueber
  Hilfe > Erste Schritte.

### Behoben (Beta-Feedback, Issue #50)
- Die "uebergeordneter Ordner"-Kachel (`..`) reagiert jetzt auf Einfachklick (mit
  Zeitfenster-Guard, damit ein Doppelklick nicht zwei Ebenen springt).
- 125% Windows-Skalierung: Das PDF-Raster passt die Spaltenzahl der Panelbreite an
  (statt fix 3 Spalten, die abgeschnitten wurden); horizontale Scrollbalken erscheinen
  bei Bedarf (linkes Panel und Detail-Panel).
- Fenstergeometrie: Der maximierte Zustand wird als eigenes Flag gespeichert, die
  Normalgroesse nicht mehr mit der Bildschirmgroesse ueberschrieben und beim Start auf
  den verfuegbaren Bildschirm begrenzt ("Titelleiste breiter als das Fenster").
- Splashscreen wird beim Erststart geschlossen, bevor der Einrichtungs-Assistent
  erscheint (lag vorher bis zu 15 s darueber).

### Geaendert
- Installer heisst jetzt fest `PDF_Sortier_Meister_Setup.exe`, damit der Link
  `releases/latest/download/PDF_Sortier_Meister_Setup.exe` immer auf die neueste
  Version zeigt (Issue #49).
- Beim Drueber-Installieren entfernt der Installer die `_internal`-Dateien der
  Vorversion; README dokumentiert Update und Deinstallation inkl. verbleibender
  Nutzerdaten in `%APPDATA%\PDF_Sortier_Meister` (Issue #48).

## [0.16.0] - 2026-08-26

### Hinzugefuegt
- **Einrichtungs-Assistent erkennt Ollama und die Hardware**
  - Provider-Seite zeigt, ob Ollama installiert ist bzw. laeuft, und prueft die
    Grafikkarte (nvidia-smi, sonst Registry-Display-Adapter) - `src/utils/hardware.py`
  - Empfehlung nach Grafikspeicher: gemma3:4b (ab 4 GB), gemma3:12b (ab 10 GB),
    gemma3:27b (ab 20 GB). Ohne dedizierte Grafikkarte (nur integrierte Grafik /
    Shared Memory), unter 4 GB oder mit Intel-GPU: Ollama lokal **nicht** empfohlen,
    stattdessen Ollama Cloud. Die Empfehlung wird vorausgewaehlt, solange noch kein
    Provider konfiguriert ist.
  - Ollama-Seite listet die installierten Modelle (`/api/tags`, Server wird bei Bedarf
    gestartet) und laedt das empfohlene Modell per Klick mit Fortschrittsbalken
    (`/api/pull`, abbrechbar) - kein Terminal mehr noetig. Gewaehltes Modell wird gespeichert.
- **Ollama Cloud** als Provider (`ollama_cloud`): dieselbe API wie lokal, aber gegen
  https://ollama.com mit API-Key (Bearer). Gilt als Cloud-Provider (Einwilligung noetig).
  Standardmodell gpt-oss:120b; Einstellungen-Dialog mit Modell-Liste, "Modelle
  aktualisieren" und Verbindungstest.
- `OllamaProvider` sendet `Authorization: Bearer <key>`, wenn ein API-Key gesetzt ist.

## [0.15.1] - 2026-08-26

### Hinzugefuegt
- **Windows-Installer** (`PDF_Sortier_Meister_Setup_<version>.exe`, Inno Setup): installiert
  ohne Admin-Rechte nach `%LocalAppData%\Programs`, Startmenue-Eintrag, Deinstallation ueber
  "Apps & Features", Update durch Drueberinstallieren. Das portable ZIP bleibt erhalten.
  Bauen: `build.bat` (ruft `scripts/build_installer.py`, Version aus `src/main.py`).
- **Tesseract OCR wird mitgeliefert**: `scripts/prepare_tesseract.py` kopiert tesseract.exe,
  die benoetigten DLLs und die Sprachdaten deu/eng nach `vendor/tesseract`; PyInstaller
  buendelt sie nach `_internal/tesseract`. OCR funktioniert damit ohne separate Installation.

### Behoben
- **OCR fand Tesseract nicht**: `pytesseract` wurde ohne Pfad aufgerufen und verliess sich auf
  den PATH, in den der Tesseract-Installer nichts eintraegt - OCR schlug still fehl.
  `find_tesseract()` sucht jetzt gebuendelt -> `Programme\Tesseract-OCR` ->
  `%LocalAppData%\Programs\Tesseract-OCR` -> PATH und setzt `TESSDATA_PREFIX`.

### Geaendert
- **OneDrive-Wartezeiten aus dem UI-Thread geholt (Log-Analyse 25./26.08.)**
  - XMP-Metadaten der angeklickten PDF werden im Hintergrund gelesen und nachgetragen
    ("Files On-Demand" laedt die Datei erst beim ersten Zugriff: 2-8 s pro Klick)
  - Ordner-Cache des Klassifikators (rglob ueber alle Zielordner, 16,8 s beim ersten
    Klick) wird nach dem Start vorgewaermt und bei Aenderungen im Hintergrund neu gebaut
  - Zielordner-Baum wird in einem Worker gescannt und erst dann befuellt (Start und
    Neuaufbau blockieren nicht mehr); neue Zielordner werden inkrementell eingehaengt
- **Erster Klick nach dem Start**: blockiert nicht mehr, bis das KI-Modell geladen ist.
  Stattdessen Wartecursor + Statusmeldung "KI-Modell wird geladen, Vorschlaege folgen
  gleich..."; die Vorschlaege werden automatisch nachgezogen. pikepdf und die
  sklearn-Aehnlichkeitssuche werden direkt nach dem Start im Hintergrund vorgewaermt.
- Verzoegerte Timer (Pre-Caching, Modell-Warteschleife) sind an das Fenster gebunden
  und feuern nicht mehr nach dessen Schliessen.
- **Verschieben im echten Betrieb (Issue #28, Nachschlag)**
  - Nach einem Verschieben wird der Zielordner-Baum nicht mehr komplett neu aufgebaut
    (alle Ordner 3 Ebenen tief listen + PDFs zaehlen, auf OneDrive der teuerste Teil);
    nur Quell- und Zielordner werden neu gezaehlt (`FolderTreeWidget.refresh_counts`).
  - XMP-Metadaten werden im Hintergrund in die PDF geschrieben (pikepdf schreibt die
    Datei komplett neu); Rueckgaengig wartet auf laufende Schreibvorgaenge.
  - Stoppuhren: `Klick ...` und `Verschieben ...` erscheinen als INFO-Zeilen im Log
    (`%APPDATA%\PDF_Sortier_Meister\logs`), sobald ein Vorgang >= 100 ms dauert -
    mit Aufschluesselung pro Schritt (move | cache | metadata | learn | index | tree ...).

## [0.15.0] - 2026-08-25

### Geaendert
- **Geschwindigkeit (Issue #28)** - gemessen mit 900 Verlaufseintraegen / 100 PDFs
  - Verschieben blockiert nicht mehr: `classifier.learn()` trainierte TF-IDF bei jedem
    Vorgang synchron neu (~450 ms bei 900 Eintraegen). Jetzt entprellt (1,5 s) im
    Hintergrund-Thread mit atomarem Modell-Tausch; beim Beenden wird ausstehendes
    Training abgeschlossen.
  - scikit-learn/numpy werden nicht mehr beim Programmstart importiert (~1,3 s); das
    Modell laedt in einem Hintergrund-Thread, Vorschlaege warten bei Bedarf darauf.
  - Thumbnails werden als PNG unter `<Datenordner>/thumbnails/` gecacht (Schluessel:
    Pfad, Groesse, mtime); Rendern ~17 ms -> Laden ~1 ms pro PDF.

### Hinzugefuegt
- **Jahres-Variante bei Ordnervorschlaegen (Issue #30)**: Zu einem gelernten Vorschlag wie
  "Steuer 2025/Medikamente" wird zusaetzlich "Steuer 2026/Medikamente" angeboten, wenn der
  Ordner existiert. Passt das im Dokument erkannte Jahr, steht die Variante vorn; ohne
  erkanntes Jahr dahinter. Der gelernte Ordner bleibt immer erhalten (nichts wird
  stillschweigend umgeschrieben). Relative Pfade in Vorschlaegen nutzen jetzt einheitlich "/".
- **Explorer-Gefuehl im Scan-Bereich (Sprint 1, Issues #29/#26/#23)**
  - Ordner-Kacheln im PDF-Raster: ".." (uebergeordneter Ordner) und alle Unterordner
    mit PDF-Anzahl; Doppelklick wechselt hinein, PDFs lassen sich per Drag & Drop
    direkt in eine Kachel verschieben
  - Klickbarer Breadcrumb-Pfad unter der Kopfzeile; Menue Ansicht -> "Uebergeordneter
    Ordner" (Alt+Up), wie im Windows-Explorer
  - Zielordner-Baum: Doppelklick oeffnet den Ordner links, ohne vorher die selektierte
    PDF zu verschieben (Einfachklick wird erst nach dem Doppelklick-Intervall ausgefuehrt);
    Kontextmenue "Ordner links oeffnen"
  - Versteckte Ordner (., $, ~) werden ausgeblendet, Unterordner alphabetisch sortiert

### Tests
- `tests/conftest.py`: `patch_singletons()` ersetzt Singleton-Fabriken in allen src-Modulen
  (GUI-Tests liefen je nach Import-Reihenfolge gegen die echte Nutzer-Config)

## [0.14.0] - 2026-08-25

### Hinzugefuegt
- **OpenRouter** als LLM-Provider (OpenAI-kompatible API, viele Modelle mit einem Key)
  - Einstellungen, Setup-Wizard, HybridClassifier, Consent-Gate
- **API-Keys pro Provider** (Issue #11): Keys bleiben beim Provider-Wechsel erhalten,
  Label zeigt den Besitzer ("API-Key (OpenRouter):")
- **Datenschutz-Einwilligung** in den KI-Einstellungen (Checkbox + Hinweis); vorher gab
  es keine Bedienoberflaeche fuer das Consent-Gate
- **Statusleiste**: Doppelklick auf "LLM:" oeffnet die Einstellungen; Doppelklick auf
  den Analyse-Fortschritt zeigt Details (Fortschritt, letzter KI-Fehler, Log-Pfad)
- **Fortschritt der Hintergrund-Analyse**: "Analyse: x/n | KI-Vorschlaege: y/n" mit
  Fehlermarkierung; KI-Vorabfrage wird nach Einstellungsaenderung neu angestossen
- **Backup-Hinweis** beim Start, abhakbar (Issue #7); Macrium-Log-Parsing bleibt #14
- **App-Icon** (Mann aus dem Splash) fuer Fenster, Taskleiste und .exe
- "+ Zielordner" startet im uebergeordneten Ordner des Scan-Ordners (Issue #11)
- **pdfs-Master-Tabelle mit stabiler pdf_id** (Issue #25, Phasen 1-3)
- **Consent-Gate** fuer Cloud-Provider in HybridClassifier (`llm.cloud_consent`)

### Geaendert
- Lizenz: MIT -> **GPL-3.0-or-later** (PyQt6/PyMuPDF Copyleft), LICENSE-Datei ergaenzt
- `OpenAIProvider`: Fehlermeldungen ueber `API_NAME` parametrisiert (fuer Subklassen)

### Behoben
- Einstellungen speichern verwarf `cloud_consent` und `cached_models`
- `Config.DEFAULTS` wurde flach kopiert (verschachtelte Dicts instanzuebergreifend geteilt)
- Analyse-Fortschritt blieb bei "0/n" haengen, wenn alle PDFs bereits im Cache waren
- KI-Vorabfrage lief ins Leere, wenn das LLM beim Einreihen noch deaktiviert war
- LLM-Queue dedupliziert (keine doppelten API-Aufrufe bei erneutem Pre-Cache)

### Tests
- 339 Tests (285 -> 339): OpenRouter-Provider, Keys/Consent-GUI, Cache-LLM-Queue,
  pdf_id-Propagation, Consent-Gate

## [0.13.0] - 2026-06-17

### Hinzugefuegt
- **Phase 20: Korrespondenten-Verwaltung (Issue #21)** - Verwaltungstabelle + GUI-Sidebar
  - Neue SQLAlchemy-Tabelle `korrespondenten` (Name, Aliase, Kategorie, Farbe, Notizen, usage_count)
  - CRUD + merge_korrespondenten (FTS5-Update) + auto_collect_from_history
  - GUI: KorrespondentSidebar im rechten Bereich (Tab "Korrespondenten")
  - GUI: KorrespondentEditDialog + KorrespondentMergeDialog
  - Klick auf Korrespondent filtert PDF-Liste
- **Phase 21: Automatisierungs-Regeln (Issue #22)** - WENN-DANN-Regeln
  - DB-Tabelle `automation_rules` (priority, enabled, conditions_json, actions_json)
  - `RuleEngine.evaluate()` + `apply_actions()` mit 5 Condition-Typen
    (korrespondent, kategorie, betrag, datum, keywords) und 4 Action-Typen
    (target_folder, filename_pattern, metadata_field, tag)
  - Platzhalter: {datum}, {steuerjahr}, {korrespondent}, {kategorie},
    {betrag_brutto}
  - Confidence-Berechnung (1.0 exakt, 0.8 bei contains, N/M partial)
  - Settings-Tab "Automatisierungs-Regeln" mit visuellem Rule-Editor
- **STAB-Block: pytest-qt GUI-Tests** fuer die bestehende Haupt-GUI
  - 39 neue Tests: FolderWidget (14), RenameDialog (12), MainWindow (13)
  - Phase-20: 34 neue Tests fuer Korrespondenten-Verwaltung
  - Phase-21: 23 neue Tests fuer Rule-Edit-Dialog und Settings-Tab

### Geaendert
- `ENTWICKLUNGSSTAND.md` -> v0.13.0 (Phase 20+21 abgeschlossen)

### Behoben
- Phase-21: replace_all=true hatte `main_window.py` zwischenzeitlich
  zerschossen -> via `git checkout` zurueckgesetzt und 3 Move-Pfade
  sauber einzeln nachgepatcht (kein Produktion-Regression, war vor Commit)
- Cancel-Cooldown aus M4-Regression nochmal verifiziert (war schon im
  M4-Commit gefixt)

### Migration
- Neue Tabelle `korrespondenten` und `automation_rules` werden via
  idempotenter `CREATE TABLE IF NOT EXISTS`-Migration angelegt -
  kein Eingriff noetig fuer bestehende Datenbanken
- CHANGELOG.md-Header v0.12.0 zeigt RAG-Chat (Phase 19)
## [0.12.0] - 2026-06-14

### Hinzugefuegt
- **Phase 19: RAG-Chat (Issue #20)** - Intelligente Dokumentensuche per natuerlicher Sprache
  - Neuer Chat-Tab im Hauptfenster (3-Spalten-Layout bleibt erhalten)
  - FTS5-basiertes Retrieval (keine Embedding-Dependency) ueber bestehende `document_search`-Tabelle
  - LLM-Synthese mit klickbaren Quellenangaben `[1]`, `[2]`, ... (Whitelist-validiert; halluzinierte Quellen werden stillschweigend gedroppt)
  - Offline-Fallback: kein LLM konfiguriert -> Keyword-Trefferliste mit klickbaren Quellen
  - In-Session-History (in-memory), Read-only in v1
  - Cancel-Button mit 500ms-Cooldown (M3-Hardening, schuetzt vor Doppel-Klicks)
  - Return-Taste sendet Frage, Shift+Return fuer Zeilenumbruch (M3-UX-Polish)
  - Citation-Parser droppt ungueltige Marker (`[99]`, `[42]`, etc.)
  - Stale-Signal-Guard: `finished()`-Signal nach `cancel()` wird ignoriert
- **M3 Hardening**: Signal-Safety im ChatWorker (`_finished_emitted`/`_failed_emitted` Flags,
  idempotente `cancel()`, `is_finished` Property)
- **M3 Hardening**: Defensiv-Guards in `RAGController` und `CitationParser` (None-Toleranz,
  leere DB, kein LLM)
- **Bugfix**: Suchpfad-Bug (Issue #25) - `update_pdf_path` und `bulk_index_directory` ergaenzt
  - Vorher: nach Verschieben einer PDF blieben DB-Eintraege am alten Pfad zurueck (Orphans)
  - Nachher: atomar DELETE-old + INSERT-new, plus Bulk-Index fuer ganze Ordner
- **Test-Suite**: 112 Tests (68 -> 112), davon 35 neu fuer RAG-Pipeline
  - Pytest-qt fuer GUI-Tests
  - Headless-Smoke-Tests fuer alle 4 LLM-Provider (Ollama/Claude/OpenAI/Poe)

### Geaendert
- `database.search_documents`: akzeptiert jetzt optionale Filter (steuerjahr, kategorie,
  korrespondent, datum_von/bis, betrag_von/bis) UND optionale Text-Query (M3-Hardening,
  Bugfix fuer OR-Operator)
- `LLMProvider.answer_with_context`: neue abstrakte Methode, in allen 4 Providern
  implementiert via stdlib `urllib` (kein anthropic/openai-Import noetig fuer Tests)
- `ENTWICKLUNGSSTAND.md` -> v0.12.0 (Phase 19 abgeschlossen)

### Behoben
- Cancel-Cooldown wurde durch `_reset_input_state()` ueberschrieben (M3-Bugfix)
- FTS5-OR-Query lieferte 0 Treffer (Production-Bug, gefixt in `search_documents`)

## [0.11.0] - 2026-06-14

### Hinzugefuegt
- Phase 8: 34 Unit-Tests (vorher nur 3 in `test_file_manager.py`)
- Phase 17: Filter-Kombinationen in der Volltext-Suche (Issue #18)
  - Steuerjahr/Kategorie/Korrespondent-Dropdowns
  - Datums- und Betragsbereich
  - Live-Trefferzaehler mit Echtzeit-Aktualisierung
- Phase 6: JSON-Mode fuer LLM-Provider (Ollama native `format=json`, Cloud-Provider ueber
  Regex-Parser)
- `bulk_index_directory` fuer rekursives Neu-Indizieren ganzer Ordner

### Geaendert
- `ENTWICKLUNGSSTAND.md` -> v0.11.0

[Unreleased]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.18.0...HEAD
[0.18.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.15.1...v0.16.0
[0.15.1]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.15.0...v0.15.1
[0.15.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.13.0...v0.14.0
[0.12.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.10.0...v0.11.0
[0.13.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.12.0...v0.13.0

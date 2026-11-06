# Dokumentensuche – Architektur der Integration von PDFsuche

**Stand:** 05.11.2026 (Phase 0: Analyse und Entwurf, noch kein Code; Entscheidungen
des Auftraggebers vom 05.11.2026 eingearbeitet, siehe Abschnitt 11)
**Ziel:** Das bisher eigenstaendige Programm PDFsuche (lokaler Volltextindex ueber
PDFs mit OCR, Office-Dateien, Markdown und Mails) geht als Modul `src/search/`
in PDF Sortier Meister (PDFSM) auf. Die Suchdatenbank bleibt fuer Claude per MCP
erreichbar.

Dieses Dokument legt fest, **wie** die Integration gebaut wird. Die Phasen 1 bis 8
am Ende sind die daraus abgeleitete, praezisierte Arbeitsplanung.

---

## 1. Ausgangslage

### 1.1 PDFsuche (Quelle)

Elf Module, rund 2.450 Zeilen, keine Tests, entwickelt unter Python 3.14:

| Modul | Aufgabe | Qt-frei | Plattformabhaengig |
|---|---|---|---|
| `config.py` | `config.toml` lesen (Dataclass `Config`) | ja | Pfadnormalisierung mit Backslash |
| `db.py` | Schema v1, `speichere()`, `loesche()`, `suche()`, `dokument()`, `seiten_text()`, `status()` | ja | nein |
| `extract.py` | PDF-Textebene, Bildseiten-Erkennung, OCR via `tesseract` (stdin/stdout), Markdown, `.eml`, `.msg`, mbox-Stapel; laeuft in Arbeitsprozessen | ja | `CREATE_NO_WINDOW`, `SetPriorityClass`, fester Tesseract-Pfad |
| `office.py` | docx/docm, xlsx/xlsm, odt (XML), `.doc` (Piece-Table), `.xls` (xlrd), RTF/HTML mit falscher Endung, ZIP-Bomben-Schutz | ja | nein |
| `mbox.py` | Thunderbird-mbox zeilenweise, geloeschte Mails ueberspringen, Weiterlesen ab Offset | ja | `.sbd\` Trenner |
| `indexer.py` | Lauf in Phasen, ProcessPool mit Zeitlimits, Absturz-Erkennung, unveraendert/verschoben/kopiert/geloescht, Aufraeumen, Dateisperre, Job-Objekt, Cloud-Dateien | ja | `msvcrt`, `ctypes.wintypes`, Job-Objekt, `st_file_attributes`, `st_reparse_tag`, `kill_workers` (3.14) |
| `web.py` + `static/index.html` | Flask/waitress-Oberflaeche, nur 127.0.0.1, Host-Pruefung, POST nur mit `X-PDFsuche: 1` | ja | `os.startfile`, `explorer /select,`, `pythonw.exe`, `DETACHED_PROCESS` |
| `mcp_server.py` | MCP-Werkzeuge `suche`, `dokument_lesen`, `index_status` (nur lesend) | ja | nein |
| `cli.py`, `ausgabe.py` | `pdfsuche suche/lesen/status/index/web`, Textausgabe | ja | nein |

Bekannte Schwaechen (siehe Abschnitt 9 fuer die Loesungen): mbox-Fortschritt nur
je Postfach, Lesefehler nicht ausgewertet, Excel-Datumswerte als Seriennummern,
Mail-Anhaenge nur mit Namen, `kill_workers()` erst ab 3.14.

**Pruefergebnis Python 3.11:** Alle elf Module kompilieren unter dem PDFSM-venv
(3.11.15, SQLite 3.53). Laufzeitfallen sind nur `ProcessPoolExecutor.kill_workers`
(Fallback ueber `_processes` vorhanden, aber ungetestet), die Modul-Importe von
`msvcrt`/`ctypes.wintypes` (muessen hinter die Plattformschicht) und `tomllib`
(ab 3.11 vorhanden, wird nur fuer die Migration der alten `config.toml` gebraucht).

**Abhaengigkeiten und Lizenzen** (alle GPL-3.0-vertraeglich):

| Paket | Version | Lizenz | Pflicht/optional |
|---|---|---|---|
| `extract-msg` | 0.58 | GPL-3.0 | Pflicht (`.msg`) |
| `olefile` | 0.47 | BSD | Pflicht (`.doc`, Teil von extract-msg) |
| `xlrd` | 2.0 | BSD | Pflicht (`.xls`) |
| `mcp` | 2.3 (`>=3.10`) | MIT | Pflicht (MCP-Server) |
| `flask` / `waitress` | 3.1 / 3.0 | BSD-3 / ZPL 2.1 | optional, Extra `suche-web` |
| `pymupdf` | 1.28 in PDFSM | AGPL (bereits Pflicht in PDFSM) | vorhanden |

### 1.2 Vorhandene Datenbank

`pdfsuche.db` (Schema-Version 1, WAL, Seitengroesse 4096): rund 3 GB, rund
260.000 Dokumente (davon rund 223.000 Mails, 29.700 PDFs, 7.400 Markdown), rund
567.000 Seiten, davon rund 59.000 Seiten noch ohne Text (OCR-Rueckstand,
rund 5.000 Dokumente). Die OCR laeuft zur Zeit (Sperrdatei aktiv). Office-Dateien
kommen mit dem naechsten Lauf, weil der aktuelle Lauf vor dem Office-Commit
gestartet wurde.

**Auswertung der 492 Lesefehler** (`textstatus = 'fehler'`):

| Anzahl | Format | Ursache | Loesung |
|---|---|---|---|
| 471 | `.msg` | Keine Outlook-Mails, sondern Tcl-Message-Kataloge (`msgs/*.msg` einer Tcl/Tk-Installation, beginnen mit `# created by tools/loadICU.tcl`) | Format am Inhalt erkennen, nicht an der Endung: OLE2-Magic -> extract-msg; RFC-822-Kopfzeilen -> eml-Parser; sonst Status `leer` mit Hinweis „kein Outlook-Format“ (kein Text, kein erneuter Versuch) |
| 7 | `.pdf` | Leere Dateien (0 Byte) | eigener Status `leer`, Fehlertext „leere Datei“ |
| 14 | `.pdf` | Keine PDF-Struktur (beschaedigt bzw. anderes Format mit Endung `.pdf`) | bleibt `fehler`, kuerzerer Fehlertext ohne Pfad |

### 1.3 Was in PDFSM schon existiert

**Ueberschneidung mit der neuen Suche**

- `src/utils/database.py`: FTS5-Tabelle `document_search` (Spalten `pdf_id`,
  `file_path`, `filename`, `extracted_text` (auf 5.000 Zeichen gekappt),
  `keywords`, `korrespondent`, `kategorie`, `steuerjahr`, `betrag`,
  `zusammenfassung`, `target_folder`; Tokenizer `unicode61` ohne
  Diakritika-Entfernung). Dazu `index_document()`, `update_pdf_path()`
  (pflegt auch die Master-Tabelle `pdfs` mit der stabilen `pdf_id`),
  `update_pdf_metadata()` (schreibt die Metadaten in `pdfs`),
  `search_documents()` (Textsuche plus Metadatenfilter), `bulk_index_directory()`,
  Hilfsabfragen `get_distinct_*`, Korrespondenten-Merge schreibt FTS-Zeilen um.
- Nutzer: `main_window.py` (Werkzeugleisten-Suche Strg+F mit Filtern, Ergebnisse
  im Detail-Panel; „Ordner zum Suchindex hinzufuegen“ mit Analyse und optionaler
  KI-Metadatenextraktion, `_index_pdfs_batch`), `src/rag/retrieval.py`
  (OR-Abfragen mit Praefix, Filter aus der Frage), `src/rag/rag_controller.py`,
  `src/gui/chat_view.py` (`search_documents(pdf_id=...)` zum Oeffnen).
- `src/core/pdf_cache.py`: Singleton `PDFCache` mit `pdf_cache.db`
  (`extracted_text`, `keywords`, `dates`, LLM-Vorschlaege, `file_modified`),
  Hintergrund-Worker `PDFAnalysisWorker` (ein Thread), `migrate_cache_entry()`.
- `src/core/pdf_analyzer.py`: `extract_text()` (Textebene, sonst OCR der ersten
  5 Seiten per pytesseract, Sprache `deu`, 2-fach-Matrix), `find_tesseract()`
  (gebuendeltes Tesseract unter `_internal/tesseract`, Standardorte, PATH).
  **Achtung:** das Modul importiert PyQt6 (QImage/QPixmap), `find_tesseract()`
  muss deshalb in ein Qt-freies Modul wandern.
- **Metadaten stehen in der PDF selbst:** `src/core/pdf_metadata.py` schreibt
  Titel, Betreff und Schlagwoerter als XMP und die PDFSM-Felder in das Info-Dict
  (`/Korrespondent`, `/Buchungsdatum`, `/Steuerjahr`, `/Betrag`, `/BetragNetto`,
  `/BetragBrutto`, `/IBAN`), dual zur Datenbank. Die PDF ist damit die
  Quelle, aus der sich die Metadaten jederzeit wieder einlesen lassen.

**Infrastruktur**

- `src/utils/platform_paths.py`: `get_app_data_dir()`, `open_with_default_app()`,
  `file_manager_name()`; `sys.platform` wird zur Aufrufzeit gelesen (testbar).
- `src/utils/config.py`: `Config` (JSON unter `get_app_data_dir()/config.json`),
  `ChatConfig` als Dataclass-Block `"chat"` – Vorbild fuer `SearchConfig`.
  Die Import-Kette `config.py -> platform_paths.py` ist Qt-frei.
- Datenverzeichnis heute: `config.json`, `history.db`, `pdf_cache.db`,
  `llm_timing.json`, `logs/`, `model/`, `thumbnails/`, `stapel_sicherung/`.
  `backup.py` sichert `config.json`, `history.db`, `pdf_cache.db`, `llm_timing.json`.
- Build: `pdf_sortier_meister.spec` (onedir, `console=False`, Splash, macOS-BUNDLE),
  `installer.iss` (Inno Setup, per-user), `build.bat`/`build.sh`,
  CI `test.yml` (Matrix mit Python 3.11, auch macOS) und `release.yml`.
- Tests: 1.003 Tests (`pytest --co`), GUI-Tests mit pytest-qt, `conftest.patch_singletons`.
- Dateioperationen laufen ueber `FileManager` (`move_file`, `rename_file`,
  `delete_file`, `stack_pdfs`, `split_pdf`, `merge_pdfs`); `main_window.py` ruft
  danach `pdf_cache.migrate_cache_entry()` und `db.update_pdf_path()` auf. Das sind
  die Stellen, an denen der Index kuenftig mitbenachrichtigt wird.
- PDFSM **veraendert PDFs**: XMP- und Info-Dict-Metadaten werden in die Datei
  geschrieben (`_write_pdf_metadata`), Stapeln haengt Seiten an. Jede solche
  Aenderung aendert Groesse und mtime, der Index muss die Datei dann neu lesen.
  Ohne Vorkehrung wuerde dabei die OCR wiederholt (siehe Abschnitt 3.3).

---

## 2. Modulaufbau `src/search/` und oeffentliche Schnittstelle

### 2.1 Grundsaetze

1. **Qt-frei.** Nichts unter `src/search/` importiert PyQt6, sklearn oder
   `src.gui`. Ein Test startet `python -c "import src.search; assert 'PyQt6' not in sys.modules"`
   in einem Unterprozess. Grund: Hintergrunddienst, MCP und Web-Oberflaeche
   laufen ohne Oberflaeche, und jeder Arbeitsprozess des Pools importiert das
   Modul beim Start erneut (spawn).
2. **Eine Konfiguration.** `SearchConfig` ist eine Dataclass in
   `src/search/konfig.py` und wird von `src/utils/config.py` nur re-exportiert
   (`Config.get_search_config()`), analog zu `ChatConfig`. Das Modul kennt PDFSMs
   `Config`-Klasse nicht.
3. **Deutsche Bezeichner wie in PDFsuche** innerhalb des Pakets (Tabellen, Felder,
   Funktionen), deutsche Kommentare und Oberflaechentexte wie in PDFSM.
4. **Keine persoenlichen Pfade im Code.** Standardwerte sind plattformabhaengig
   berechnet (Scan-Ordner, Zielordner, Thunderbird-Profil aus `profiles.ini`).

### 2.2 Dateien

```
src/search/
  __init__.py      oeffentliche Schnittstelle (Re-Exports), SCHEMA_VERSION
  konfig.py        SearchConfig (Dataclass), Standardwerte, Normalisierung,
                   lade_alte_config_toml() fuer die Migration
  db.py            Schema v1 -> v2 (in-place, additiv), verbinde(), speichere(),
                   loesche(), suche(), dokument(), dokument_nach_pfad(),
                   seiten_text(), volltext(), text_fuer_datei(), status()
  suchindex.py     Klasse Suchindex: Lese-Helfer + Schreibmeldungen der GUI
                   (datei_verschoben, datei_geloescht, datei_geaendert,
                   datei_aufnehmen, ocr_eintragen, metadaten_setzen,
                   metadaten_ersetzen), laeuft_gerade(), lauf_starten()
  indexer.py       Klasse Indexer (bisher Lauf): Phasen, ProcessPool, OCR, Mails,
                   Aufraeumen, Leerlauf-Pause (macOS), OCR-Cache, Metadaten aus PDF
  extract.py       PDF-Textebene, Info-Dict-Metadaten, Bild-Hash je Seite, OCR
                   (Tesseract), Markdown, eml/msg (Format-Sniffing), mbox-Stapel
                                                                [Arbeitsprozesse]
  office.py        docx/docm, xlsx/xlsm (mit Datumsformaten), odt, doc, xls, RTF
  mbox.py          Thunderbird-mbox, Zwischenstaende (Offset), Profilsuche
  plattform.py     Dateisperre, Prozessgruppe/Job-Objekt, Hintergrundprioritaet,
                   Cloud-Platzhalter, Junction/Symlink, Leerlaufzeit,
                   Thunderbird-Profil, Datei im Dateimanager zeigen,
                   Unterprozess-Flags, Tesseract-Suche (ueber src/utils/tesseract.py)
  zeitplan.py      Hintergrundindexierung ein/aus: Windows-Aufgabenplanung,
                   macOS-LaunchAgent; Zustand abfragen
  dienst.py        Konsolenprogramm pdfsm-dienst (argparse), freeze_support()
  mcp_server.py    MCP-Werkzeuge suche, dokument_lesen, index_status
  web.py           Flask-App (optionales Extra), static/index.html
  ausgabe.py       Textausgabe fuer CLI und MCP

src/utils/tesseract.py   find_tesseract() + Sprachdaten-Ordner, Qt-frei
                         (pdf_analyzer.py re-exportiert die Funktion)

src/gui/
  search_view.py     Reiter „Suche“: Suchfeld, Filter, Trefferliste, Vorschau, Status
  search_worker.py   QThread fuer Abfragen; geordnete Warteschlange fuer Index-Meldungen
  settings_dialog.py Registerkarte „Suche“
  setup_wizard.py    Seite „Dokumentensuche“
```

### 2.3 Oeffentliche Schnittstelle

Alles ueber `from src.search import ...`. Zeiten sind Unix-Sekunden, Pfade
Strings in Betriebssystemschreibweise, Treffer sind `dict`s (JSON-faehig, damit
Web und MCP sie unveraendert weiterreichen).

```python
@dataclass
class SearchConfig:                      # src/search/konfig.py
    aktiv: bool = False                  # Suche eingerichtet?
    db_pfad: str = ""                    # leer = get_app_data_dir()/suche/suche.db;
                                         # bei Uebernahme einer PDFsuche der bisherige Ort
    wurzeln: list[str]                   # Ordner/Laufwerke (Standard: Scan- und Zielordner)
    prioritaet: list[str]                # Vorrang-Ordner (Standard: Scan-Ordner)
    endungen: set[str]                   # .pdf .md .eml .msg .docx .docm .doc .xlsx .xlsm .xls .odt
    ordner_ausschliessen: set[str]       # Ordnernamen (plattformabhaengige Standardliste)
    pfade_ausschliessen: set[str]
    cloud_herunterladen: bool = False
    max_dateigroesse_mb: int = 500
    mails_aktiv: bool = False
    mail_ordner: list[str]               # Standard: Thunderbird-Profil (Mail/, ImapMail/)
    ocr_aktiv: bool = True
    ocr_sprachen: str = "deu+eng"
    ocr_dpi: int = 300
    ocr_min_zeichen: int = 25
    ocr_max_seiten: int = 1000
    prozesse: int = 0                    # 0 = halbe Kernzahl, hoechstens 8
    hintergrund_aktiv: bool = False      # taegliche Aufgabe / LaunchAgent
    hintergrund_uhrzeit: str = "03:00"
    web_aktiv: bool = False
    web_bei_anmeldung: bool = False
    web_port: int = 18425
```

```python
class Suchindex:                          # src/search/suchindex.py, leichtgewichtig
    def __init__(self, konfig: SearchConfig) -> None

    # Lesen (eigene Nur-Lese-Verbindung je Aufruf oder je Thread)
    def suche(self, abfrage: str, *, typ=None, ordner=None, von=None, bis=None,
              sortierung="relevanz", anzahl=30, start=0, max_stellen=3,
              nur_namen=False, steuerjahr=None, kategorie=None, korrespondent=None,
              betrag_von=None, betrag_bis=None, pdf_id=None) -> dict
        # -> {"treffer": [...], "gesamt": n, "mehr": bool, "abfrage": fts, "dauer_ms": ms}
        # Treffer: id, pfad, datei, name, ordner, typ, format, groesse, datum, seiten,
        #          textstatus, ocr_seiten, mail_*, pdf_id, korrespondent, kategorie,
        #          steuerjahr, betrag, buchungsdatum, zusammenfassung, schlagwoerter,
        #          rang, stellen[{seite, quelle, text}], treffer_seiten, im_namen
    def dokument(self, dok_id: int) -> dict | None
    def dokument_nach_pfad(self, pfad: str) -> dict | None
    def seiten_text(self, dok_id: int, von=None, bis=None, hervorheben=None) -> list[dict]
    def volltext(self, dok_id: int) -> str          # Seiten mit \f getrennt
    def text_fuer_datei(self, pfad: str) -> TextStand | None
        # TextStand: text, seiten[(nr, quelle, text)], textstatus, aktuell (Groesse+mtime passen),
        #            ocr_offen[list[int]]  -> Quelle fuer pdf_analyzer
    def werte(self, feld: str) -> list[str]          # distinct steuerjahr/kategorie/korrespondent
    def status(self) -> dict                         # Zaehler, OCR-Rueckstand, letzte Laeufe, Fortschritt
    def laeuft_gerade(self) -> bool                  # Sperrdatei

    # Schreibmeldungen der GUI (kurze Transaktionen, siehe Abschnitt 4)
    def datei_verschoben(self, alt: str, neu: str) -> bool   # Umbenennen und Verschieben
    def datei_geloescht(self, pfad: str) -> bool
    def datei_geaendert(self, pfad: str) -> None             # Inhalt geaendert (XMP, Stapeln):
                                                             # Textebene neu, OCR aus Cache
    def datei_aufnehmen(self, pfad: str, prioritaet: int = 0) -> int | None
                                                             # sofort indizieren (Textebene),
                                                             # Bildseiten bleiben fuer OCR offen
    def ocr_eintragen(self, pfad: str, texte: dict[int, str]) -> None
                                                             # OCR-Ergebnis der GUI uebernehmen
    def metadaten_setzen(self, pfad: str, felder: dict, pdf_id: str | None = None) -> bool
                                                             # Korrespondent, Kategorie, Steuerjahr,
                                                             # Betrag, Buchungsdatum, Zusammenfassung,
                                                             # Schlagwoerter; Quelle 'pdfsm' (Vorrang)
    def metadaten_ersetzen(self, feld: str, alt: str, neu: str) -> int
                                                             # z. B. Korrespondenten-Merge

    # Laeufe
    def lauf_starten(self, *, nur_prioritaet=False, pfad=None, hintergrund=True) -> subprocess.Popen
                                                             # startet pdfsm-dienst als eigenen Prozess
    def lauf_abbrechen(self) -> bool
```

```python
class Indexer:                            # src/search/indexer.py, laeuft im Dienstprozess
    def __init__(self, konfig: SearchConfig, hintergrund=False, max_minuten=0)
    def lauf(self, *, nur_prioritaet=False, ohne_ocr=False, ohne_mail=False,
             nur_pfad: str | None = None) -> int     # 0 fertig, 1 abgebrochen/fehler, 2 laeuft schon
```

Die Modulfunktionen in `db.py` (`suche(con, ...)`, `seiten_text(con, ...)`, …)
bleiben erhalten und werden von `Suchindex`, Web, MCP und CLI gemeinsam genutzt.

---

## 3. Verhaeltnis zur vorhandenen Suche

### 3.1 Entscheidung: eine Such-Datenbank, Metadaten kommen aus der PDF

**Entschieden (05.11.2026):** Volltext **und** PDFSM-Metadaten liegen in
`suche.db`. `document_search` in `history.db` wird nach einer einmaligen
Uebernahme abgeschafft. `history.db` behaelt, was zum Lern- und
Historienbestand gehoert: `pdfs` (stabile `pdf_id` samt Metadaten),
Sortierhistorie, Korrespondenten, Regeln.

Begruendung:

- PDFSM schreibt die Metadaten ohnehin in jede sortierte PDF (Info-Dict und
  XMP, Abschnitt 1.3). Der Index liest sie beim Indizieren wie heute Titel und
  Autor mit. Damit sind die Metadaten in `suche.db` **aus den Dateien
  wiederherstellbar**, und PDFs, die auf einem anderen Rechner oder vor der
  Einfuehrung von `document_search` sortiert wurden, bekommen ihre Metadaten
  von selbst.
- Filter (`steuerjahr = ?`, `betrag BETWEEN`) sind einfache Bedingungen auf
  `dokumente`, keine Verknuepfung zweier Datenbanken ueber den Pfad.
- Der Text in `document_search` war auf 5.000 Zeichen gekappt, ohne OCR und
  ohne Seitenbezug. Ein zweiter Textindex entfaellt vollstaendig.

**Neue Spalten in `dokumente`** (Schema-Version 2, Abschnitt 3.3): `pdf_id`,
`korrespondent`, `kategorie`, `steuerjahr`, `betrag` (REAL, brutto),
`buchungsdatum` (ISO), `zusammenfassung`, `schlagwoerter`, `metadaten_quelle`
(`'pdf'` = beim Indizieren aus der Datei gelesen, `'pdfsm'` = von PDFSM gesetzt).
Dazu `metadaten_fts` (FTS5 ueber `korrespondent`, `kategorie`, `zusammenfassung`,
`schlagwoerter`, per Trigger synchron), damit „Telekom“ auch dann trifft, wenn
die OCR der Seite schlecht ist.

**Vorrangregel:** Werte mit `metadaten_quelle = 'pdfsm'` ueberschreibt der
Indexer nie aus der PDF; er fuellt nur leere Felder oder Felder mit Quelle
`'pdf'`. So ueberlebt ein Korrespondenten-Merge (aendert die Datenbank, nicht die
PDFs) jedes Neulesen. Nicht-PDF-Dokumente (Mails, Office, Markdown) haben die
Felder leer.

**Fassade `search_documents()`** behaelt Signatur und Ergebnisschluessel
(`pdf_id`, `file_path`, `filename`, `text_snippet`, `keywords`, `korrespondent`,
`kategorie`, `steuerjahr`, `betrag`, `zusammenfassung`, `target_folder`),
ergaenzt um `dok_id` und `seite`, und liest aus `suche.db`. `pdf_id` kommt aus
`dokumente.pdf_id` (von PDFSM beim Setzen der Metadaten eingetragen), sonst per
Pfad aus `pdfs`. Damit laufen RAG-Chat, Korrespondenten-Merge und Chat-Oeffnen
ohne Umbau weiter; Zitate im Chat verlinken ab Phase 5 auf Dokument **und Seite**.
`get_distinct_steuerjahre/kategorien/korrespondenten` und `get_top_kategorien`
lesen ueber `Suchindex.werte()`.

**Umstellung der Schreibwege in PDFSM:**

| bisher | kuenftig |
|---|---|
| `index_document(file_path, ..., extracted_text=...)` | `metadaten_setzen(pfad, felder, pdf_id)` + `datei_aufnehmen(pfad)`; kein Text mehr von PDFSM |
| `update_pdf_metadata()` (schreibt `pdfs`) | zusaetzlich `metadaten_setzen()` |
| `update_pdf_path()` (schreibt `pdfs`, `document_search`) | schreibt `pdfs`, ruft `datei_verschoben()` |
| Korrespondenten-Merge (FTS-Zeilen umschreiben) | `metadaten_ersetzen("korrespondent", alt, neu)` |
| `bulk_index_directory()`, „Ordner zum Suchindex hinzufuegen“ | `lauf_starten(pfad=...)`; optionale KI-Metadatenextraktion liest den Text aus dem Index und setzt die Felder per `metadaten_setzen()` |

**Einmalige Uebernahme von `document_search`** (beim ersten Start nach dem
Update, in Phase 5 gebaut): fuer jede Zeile, deren Datei existiert, die Felder
per `metadaten_setzen()` in `suche.db` eintragen (Datei bei Bedarf sofort per
`datei_aufnehmen()` indizieren). Zeilen ohne Datei werden verworfen (ihre
`pdfs`-Eintraege bleiben). Danach `DROP TABLE document_search`; die
`_migrate_document_search`-Logik und `_create_fts_index` entfallen. Von PDFSM
verwaltete Dokumente (`metadaten_quelle = 'pdfsm'`) werden beim Aufraeumen
(Abschnitt 4.2) nie entfernt, solange die Datei existiert, auch ausserhalb der
Wurzeln.

### 3.2 `pdf_cache` und `pdf_analyzer`: Text aus dem Index, eine OCR-Implementierung

- `PDFAnalyzer.extract_text()` fragt zuerst `Suchindex.text_fuer_datei(pfad)`.
  Ist der Eintrag aktuell (Groesse und mtime stimmen) und der Status einer von
  `text`, `ocr`, `leer`, `ocr_teilweise`, kommt der Text aus dem Index, ohne die
  PDF zu oeffnen.
- Fehlt der Eintrag oder stehen Seiten auf `ocr_ausstehend`, extrahiert der
  Analyzer selbst, **aber mit denselben Funktionen** aus `src/search/extract.py`
  (`pdf_text`, `pdf_ocr`: Tesseract ueber `find_tesseract()`, `deu+eng`,
  300 dpi, Graustufen, `psm 1`). Die bisherige 5-Seiten-Grenze fuer die
  interaktive OCR bleibt, damit die Oberflaeche schnell antwortet.
- Das Ergebnis schreibt der Analyzer zurueck: `datei_aufnehmen()` fuer neue
  Dateien unter einer Wurzel, `ocr_eintragen()` fuer erkannte Seiten. Der
  naechste Lauf findet die Seiten fertig vor und erkennt nur die restlichen.
- `pdf_cache.db` bleibt als Sitzungs-Cache fuer Schlagwoerter, Datumskandidaten
  und KI-Vorschlaege bestehen; `extracted_text` darin wird kuenftig aus dem Index
  befuellt. Ein spaeterer Abbau der Spalte ist moeglich, aber nicht Teil dieser
  Integration.
- `pytesseract` wird damit fuer die Textgewinnung ueberfluessig (bleibt vorerst
  als Abhaengigkeit, Entfernen ist ein Folgeschritt).

### 3.3 Nie doppelt OCR: OCR-Cache nach Bildinhalt, Schema-Version 2

PDFSM schreibt Metadaten in PDFs, stapelt und teilt sie. Jede dieser
Aenderungen veraendert Groesse und mtime, der Index muss neu lesen. Die bisherige
Erkennung verschobener Dateien ueber (Name, Groesse, mtime) hilft dann nicht,
und die OCR-Arbeit waere verloren. Deshalb:

- **Bild-Hash je Seite:** Fuer jede Seite ohne Textebene berechnet `extract.pdf_text`
  einen BLAKE2b-Hash (16 Byte) ueber die Rohdaten der Bild-Streams der Seite
  (`xref_stream_raw`, bei Inline-Bildern ueber den Content-Stream). Das Lesen
  der komprimierten Streams kostet Millisekunden, kein Rendern.
- **Tabelle `ocr_cache`** und Spalte `seiten.bild_hash`. Beim Speichern einer
  Seite ohne Text wird der Cache befragt: Treffer -> Seite sofort `quelle='ocr'`
  mit dem Text. Jedes OCR-Ergebnis (Lauf oder GUI) landet im Cache.
- Damit ueberleben OCR-Texte Umbenennen, Verschieben, XMP-Schreiben, Stapeln,
  Teilen, Kopieren und Wiederherstellen aus `stapel_sicherung`, auch ohne
  Meldung der GUI.
- **Auffuellen des Bestands:** Ein Laufabschnitt „OCR-Cache ergaenzen“ berechnet
  die Hashes fuer vorhandene Seiten mit `quelle='ocr'` und `bild_hash IS NULL`
  (derzeit rund 1.400 Dokumente) und traegt sie in den Cache ein. Der Schritt ist
  idempotent und laeuft nebenbei.

**Schema-Version 2** (entschieden 05.11.2026): Das neue Modul ergaenzt beim
ersten Oeffnen einer Version-1-Datenbank **in-place und additiv**, idempotent
(`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN` nur, wenn die Spalte
fehlt), Laufzeit unter einer Sekunde auch bei 3 GB, kein Neuaufbau, keine OCR
geht verloren:

```
ocr_cache(bild_hash TEXT PRIMARY KEY, text TEXT NOT NULL, sprachen TEXT, dpi INTEGER, erstellt TEXT)
seiten.bild_hash TEXT
dokumente.pdf_id, korrespondent, kategorie, steuerjahr, buchungsdatum,
          zusammenfassung, schlagwoerter, metadaten_quelle TEXT; betrag REAL
Indizes: ix_dok_pdf_id, ix_dok_steuerjahr, ix_dok_korrespondent, ix_dok_kategorie
metadaten_fts: FTS5 (content='dokumente') ueber korrespondent, kategorie,
          zusammenfassung, schlagwoerter; Trigger wie bei dokumente_fts
meta.schema_version = '2'
```

Das alte PDFsuche kann eine Version-2-Datei weiter lesen und schreiben (es
benennt alle Spalten explizit und ignoriert Unbekanntes), setzt aber bei jedem
Start `meta.schema_version` auf 1 zurueck. Deshalb erkennt das neue Modul die
Version **an der Struktur** (Tabellen und Spalten vorhanden?) und fuehrt die
Ergaenzung bei Bedarf erneut aus. Beim Auftraggeber geschieht der Sprung auf
Version 2 erst in Phase 7 an der Datenbank am bisherigen Ort (Abschnitt 7).

---

## 4. Prozessmodell

### 4.1 Wer schreibt, wer liest

| Rolle | Prozess | Zugriff |
|---|---|---|
| **Indexlauf** | `pdfsm-dienst index` (eigener Prozess, gestartet von Aufgabenplanung/LaunchAgent, GUI oder Web) | Schreibverbindung, Sperrdatei `indexer.lock` neben der Datenbank verhindert einen zweiten Lauf |
| **GUI-Meldungen** | PDFSM-Oberflaeche ueber `Suchindex.datei_*`, `ocr_eintragen`, `metadaten_*` | kurze Schreibtransaktionen (einzelne Zeilen), nie im GUI-Thread |
| GUI-Suche | `search_worker.py` (QThread) | eine Nur-Lese-Verbindung je Thread |
| MCP | `pdfsm-dienst mcp` | nur lesend, Verbindung je Aufruf |
| Web | `pdfsm-dienst web` | nur lesend (thread-lokale Verbindung); „Jetzt indizieren“ startet einen eigenen Dienstprozess |
| CLI | `pdfsm-dienst suche/lesen/status` | nur lesend |

„Eine Schreibquelle“ heisst: **ein Modul** (`src/search/db.py` und `suchindex.py`)
kennt das Schema und fuehrt alle Schreibzugriffe aus, aus hoechstens zwei
Prozessen (Lauf und GUI). SQLite im WAL-Modus serialisiert Schreiber ueber
`busy_timeout` (30 s); Leser werden nie blockiert. Der Lauf committet alle 3 s
bzw. 300 Aenderungen, eine GUI-Meldung wartet also hoechstens wenige Sekunden.
Deshalb laufen GUI-Meldungen in einer **geordneten Warteschlange** in einem
eigenen Thread (`search_worker.IndexMeldungen`), nie im GUI-Thread; Reihenfolge
(erst verschieben, dann umbenennen) bleibt gewahrt, Fehler landen im Log und in
der Statusleiste.

Zwei Laeufe (Aufgabenplanung und „Jetzt indizieren“) schliesst die Sperrdatei
aus; der zweite Aufruf endet mit Rueckgabe 2 und einer Meldung. Liegt die
Datenbank am bisherigen PDFsuche-Ort, teilen altes und neues Programm dieselbe
Sperrdatei (beide legen sie neben die Datenbank), gleichzeitige Laeufe sind
also auch waehrend der Umstellung ausgeschlossen.

### 4.2 Lauf und GUI-Meldungen gleichzeitig

Der Indexer haelt die bekannten Dateien im Speicher (`bekannt`). Aendert die GUI
waehrend eines Laufs Pfade, waere dieser Speicher veraltet. Regeln:

- Vor jeder Entscheidung „neu lesen“ fragt der Indexer die Zeile per Pfad in der
  Datenbank nach (eindeutiger Index, eine Zeile) statt dem Speicher zu glauben.
- Die Signatur zum Erkennen verschobener Dateien wird (Groesse, mtime_ns) mit
  dem Namen nur als Vorzugskriterium; damit erkennt der Lauf auch Umbenennungen
  ohne Meldung der GUI.
- Der OCR-Cache (3.3) faengt alles auf, was trotzdem neu gelesen wird.
- Beim Neulesen bleiben Metadaten mit Quelle `'pdfsm'` erhalten (Vorrangregel 3.1).
- Aufraeumen (Loeschen nicht mehr vorhandener Eintraege) bleibt auf vollstaendig
  durchlaufene Wurzeln beschraenkt. Neu: nach einem vollstaendigen Lauf werden
  auch Eintraege entfernt, die ausserhalb aller konfigurierten Wurzeln und
  Vorrang-Ordner liegen (bisher blieben sie fuer immer stehen), ausgenommen
  Dokumente mit `metadaten_quelle = 'pdfsm'`, deren Datei noch existiert.

### 4.3 Meldungen aus PDFSM

| Stelle in PDFSM | Meldung |
|---|---|
| `FileManager.move_file`, `rename_file` (alle Aufrufer in `main_window.py`, inkl. Rueckgaengig) | `datei_verschoben(alt, neu)` direkt nach `migrate_cache_entry()`/`update_pdf_path()` |
| `FileManager.delete_file` | `datei_geloescht(pfad)` |
| `_write_pdf_metadata`, `stack_pdfs`, `restore_stack`, `split_pdf`, `merge_pdfs` | `datei_geaendert(pfad)` bzw. `datei_aufnehmen(neu)` fuer entstandene Dateien |
| `index_document`, `update_pdf_metadata`, Metadaten-Sidebar | `metadaten_setzen(pfad, felder, pdf_id)` |
| Korrespondenten-Merge | `metadaten_ersetzen("korrespondent", alt, neu)` |
| `PDFAnalysisWorker` (Analyse abgeschlossen) | `ocr_eintragen()` bei eigener OCR, `datei_aufnehmen()` bei unbekannter Datei unter einer Wurzel |

Alle Meldungen sind fehlertolerant: Ist die Suche nicht eingerichtet
(`aktiv=False`), passiert nichts; liegt eine Datei ausserhalb der Wurzeln, wird
sie bei `metadaten_setzen()` trotzdem aufgenommen (PDFSM-verwaltet), bei den
uebrigen Meldungen ignoriert.

### 4.4 Statusanzeige

Die GUI liest `status()` (Zaehler, OCR-Rueckstand, `laeufe`, `meta.fortschritt`)
und `laeuft_gerade()` per `QTimer` alle 3 s, solange ein Lauf aktiv ist, sonst
beim Oeffnen des Reiters. Kein IPC noetig.

---

## 5. Plattformschicht (`src/search/plattform.py`)

| Bereich | Windows (heute in PDFsuche) | macOS | Hinweise |
|---|---|---|---|
| Dateisperre `indexer.lock` | `msvcrt.locking(LK_NBLCK)` | `fcntl.flock(LOCK_EX \| LOCK_NB)` | `flock` statt `lockf`: wirkt auch zwischen zwei Oeffnungen im selben Prozess, damit `laeuft_gerade()` im Dienst selbst stimmt |
| Arbeitsprozesse sterben mit | Job-Objekt `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (erfasst auch `tesseract.exe`) | Eigene Prozessgruppe (`os.setpgrp`), Abbruch per `os.killpg(SIGTERM)`; in jedem Arbeitsprozess ein Waechter-Thread, der `os.getppid()` alle 2 s prueft und bei Elternwechsel `os._exit` ruft; Tesseract ohne `start_new_session`, damit es in der Gruppe bleibt | `select.kqueue` mit `KQ_NOTE_EXIT` waere moeglich, Polling ist einfacher und reicht |
| Hintergrundprioritaet | `SetPriorityClass(PROCESS_MODE_BACKGROUND_BEGIN)`, Fallback `BELOW_NORMAL` | `os.nice(19)`; beim geplanten Lauf zusaetzlich LaunchAgent-Schluessel `ProcessType=Background`, `LowPriorityIO=true`; bei GUI-Start ueber `taskpolicy -b`, falls vorhanden | Arbeitsprozesse erben die Einstellung |
| „Nur in der Cloud“ | `st_file_attributes & (OFFLINE \| RECALL_ON_OPEN \| RECALL_ON_DATA_ACCESS)` | `st_flags & SF_DATALESS` (0x40000000, File-Provider: OneDrive, Dropbox, iCloud) und Platzhalter `.name.icloud` ueberspringen | `os.stat` loest keinen Download aus, `open` schon |
| Junctions/Symlinks | Reparse-Tag `MOUNT_POINT`/`SYMLINK` ueberspringen | `is_dir(follow_symlinks=False)` ueberspringt Symlinks bereits; zusaetzlich `/Volumes` nur als explizite Wurzel, Netzlaufwerke nicht implizit | Python 3.11 hat `st_reparse_tag`, `os.path.isjunction` erst ab 3.12 |
| Wurzeln (Vorschlaege im Assistenten) | Laufwerksbuchstaben (`GetLogicalDrives`), Standard: Scan- und Zielordner | Benutzerordner `~` und eingehaengte `/Volumes/*`; Standard: Scan- und Zielordner | Standardausschluesse je Plattform (`Windows`, `AppData`, `$Recycle.Bin` … bzw. `Library`, `.Trash`, `node_modules`, `.git` …) |
| Thunderbird-Profil | `%APPDATA%\Thunderbird\profiles.ini` | `~/Library/Thunderbird/profiles.ini` | `[ProfileN]`: `Path`, `IsRelative` (0 = absoluter Pfad), `Default=1`; Postfaecher unter `<Profil>/Mail` und `<Profil>/ImapMail`. Apple Mail (`.emlx`) nur vorgemerkt |
| Tesseract | `find_tesseract()` (gebuendelt, Standardorte, PATH), Sprachdaten `tessdata` daneben | gleiche Funktion (Homebrew-Pfade) | wandert nach `src/utils/tesseract.py`; `TESSDATA_PREFIX` je Aufruf setzen; Sprachen `deu+eng`; fehlen die Daten, OCR deaktivieren und im Status zeigen |
| Unterprozesse | `creationflags=CREATE_NO_WINDOW`, Start des Laufs mit `DETACHED_PROCESS \| CREATE_NEW_PROCESS_GROUP` | keine Flags, Start mit `start_new_session=True` | `plattform.popen_flags()` |
| Datei im Dateimanager zeigen | `explorer /select,` | `open -R` | Texte ueber `file_manager_name()` |
| Datei oeffnen | `os.startfile` | `open` | ueber `platform_paths.open_with_default_app` |
| Pfade | Backslash, `pfad COLLATE NOCASE`, Schluessel klein geschrieben | `os.path.normpath`, Case-Insensitivitaet bleibt (APFS ist standardmaessig case-insensitive) | `konfig._norm` wird plattformneutral |
| mbox-Anzeigename | `.sbd\` -> `/` | `.sbd/` | `os.sep` |
| Hintergrundindexierung | Aufgabenplanung `\PDF Sortier Meister\Indexierung` (taeglich, nur bei Leerlauf, Abbruch bei Aktivitaet, Fortsetzung bei Leerlauf, ohne Adminrechte, Prioritaet 7) | LaunchAgent `de.josi-create.pdf-sortier-meister.suche.plist` mit `StartCalendarInterval`; Leerlauf prueft der Indexer selbst ueber `ioreg -c IOHIDSystem` (`HIDIdleTime`, Nanosekunden) alle 30 s und pausiert, solange der Nutzer aktiv ist | Windows-Neustart des Laufs ist billig: unveraenderte Dateien werden uebersprungen, mbox hat Zwischenstaende |
| Web-Oberflaeche bei Anmeldung | Aufgabe `\PDF Sortier Meister\Web-Oberflaeche` (bei Anmeldung) | LaunchAgent mit `RunAtLoad` | nur, wenn `web_bei_anmeldung` |
| Fensterloser Start | `pdfsm-dienstw.exe` (`console=False`, wie `pythonw.exe`) | nicht noetig: ein Kommandozeilenprogramm oeffnet unter macOS kein Fenster, wenn launchd oder die GUI es startet | siehe Abschnitt 6 |

Linux laeuft als Nebenprodukt der macOS-Zweige mit (`fcntl`, `nice`, keine
Cloud-Attribute), ist aber kein Ziel.

Alle Windows-Importe (`msvcrt`, `ctypes.wintypes`) liegen in Funktionen hinter
`sys.platform == "win32"`, damit das Paket in der macOS-CI importierbar ist.
Die Plattformtests simulieren `sys.platform` per `monkeypatch` wie
`tests/test_platform_paths.py`.

**Umsetzung (Phase 2, 06.11.2026):** `src/search/plattform.py` buendelt die
Tabelle in Funktionen: `sperren`/`entsperren`; `kinder_an_mich_binden`
(Windows Job-Objekt; unter macOS kein eigenes `setpgrp`, weil die Oberflaeche
den Dienst ohnehin mit `start_new_session=True` in eigener Sitzung startet und
ein `setpgrp` im Terminal das Strg+C abschneiden wuerde) und
`elternwaechter_starten` (Thread
in jedem Arbeitsprozess, prueft `os.getppid()` alle 2 s und ruft bei
Elternwechsel `os._exit`; unter Windows unnoetig); `niedrige_prioritaet_setzen`
(`PROCESS_MODE_BACKGROUND_BEGIN` bzw. `nice` 19, unter macOS dazu
`setiopolicy_np` und `taskpolicy -b -p`); `popen_flags(abgekoppelt)`;
`nur_cloud` und `icloud_platzhalter` (ein `.Name.pdf.icloud` wird als Eintrag
`cloud` nur mit Namen aufgenommen, ein schon gelesener Text bleibt stehen);
`verknuepfung`; `im_dateimanager_zeigen`; `leerlauf_sekunden`
(`GetLastInputInfo` bzw. `ioreg -c IOHIDSystem`); `thunderbird_profile` und
`thunderbird_mail_ordner` (Standard fuer leeres `mail_ordner` ueber
`SearchConfig.mail_ordner_effektiv()`); `wurzel_vorschlaege`. Der Lauf kennt
`nur_leerlauf` (`pdfsm-dienst index --nur-leerlauf`): alle 30 s wird die
Leerlaufzeit abgefragt, bei Aktivitaet pausiert der Lauf, bis der Nutzer 60 s
untaetig war - fuer den macOS-LaunchAgent, der keine Leerlaufbedingung kennt.
Fehlen Tesseract oder die Sprachdaten (`deu+eng`), ist
`ocr_einstellungen()["aktiv"]` False und `grund` nennt die Ursache; der Status
(`Suchindex.status()["ocr_grund"]`, `pdfsm-dienst status`) zeigt sie an.
Apple Mail (`.emlx`) bleibt vorgemerkt.

---

## 6. Build: Konsolenprogramm `pdfsm-dienst`

**Warum:** Die GUI-EXE hat keine Konsole (`console=False`), MCP braucht stdio,
und ein `ProcessPoolExecutor` mit `spawn` darf nie die GUI-EXE als Arbeitsprozess
starten (Splash, Qt-Import, Hauptfenster).

**Unterbefehle** (`src/search/dienst.py`, argparse, Rueckgabecodes wie `cli.py`):

```
pdfsm-dienst index [--hintergrund] [--nur-prioritaet] [--pfad ORDNER] [--ohne-ocr] [--ohne-mail] [--max-minuten N]
pdfsm-dienst mcp
pdfsm-dienst web [--port N] [--nicht-oeffnen]
pdfsm-dienst suche "Abfrage" [--typ ...] [--ordner ...] [--von ...] [--bis ...] [-n N] [--json]
pdfsm-dienst lesen ID [--seiten 2-5]
pdfsm-dienst status
pdfsm-dienst zeitplan --einrichten | --entfernen | --status     (Aufgabenplanung / LaunchAgent)
pdfsm-dienst migration --von ORDNER                              (alte PDFsuche uebernehmen, auch ohne GUI)
pdfsm-dienst --version
```

**Einstieg:** erste Zeilen `multiprocessing.freeze_support()` und
`multiprocessing.set_start_method("spawn")`, dann Logging nach
`get_app_data_dir()/logs/suche.log` (rotierend), dann Konfiguration ueber
`src.utils.config` (Qt-frei) laden. Kein Import von PyQt6, sklearn oder `src.gui`.
Start-Zeit zaehlt: MCP-Clients warten auf den Handshake, Arbeitsprozesse
importieren das Modul erneut.

**Executables aus einem Build** (`pdf_sortier_meister.spec`):

| EXE | Skript | `console` | Verwendung |
|---|---|---|---|
| `PDF_Sortier_Meister.exe` | `src/main.py` | nein (Splash) | wie bisher |
| `pdfsm-dienst.exe` | `src/search/dienst.py` | ja | MCP, CLI, manuelle Laeufe |
| `pdfsm-dienstw.exe` (nur Windows) | `src/search/dienst.py` | nein | Aufgabenplanung, GUI-gestartete Laeufe, Web bei Anmeldung: kein Konsolenfenster, kein Aufblitzen |

**macOS:** Ein Binary `pdfsm-dienst` im Bundle (`Contents/MacOS/pdfsm-dienst`)
genuegt fuer alle Zwecke. Unter macOS gibt es keine Konsolenfenster, die ein
Kommandozeilenprogramm beim Start aufmacht: Von launchd oder von der GUI per
`subprocess` gestartet laeuft es unsichtbar, stdio bleibt fuer MCP verfuegbar.
Nur ein Doppelklick im Finder wuerde ein Terminal oeffnen, und das ist kein
vorgesehener Weg. Die zweite Windows-EXE ersetzt lediglich `pythonw.exe`.

Zwei `Analysis`-Objekte (`main.py`, `dienst.py`), alle `EXE`s mit
`exclude_binaries=True` in **einem** `COLLECT` (gemeinsamer `_internal`-Ordner,
Tesseract einmal). Der LaunchAgent und die MCP-Registrierung auf macOS zeigen
auf `.../Contents/MacOS/pdfsm-dienst`. Die GUI findet den Dienst im
eingefrorenen Zustand neben `sys.executable`, in der Entwicklungsumgebung als
`[sys.executable, "-m", "src.search.dienst"]`.

**Weitere Bauschritte:**

- `pyproject.toml`: Abhaengigkeiten `extract-msg`, `olefile`, `xlrd`, `mcp`;
  Extra `suche-web = ["flask>=3", "waitress>=3"]`; `[project.scripts] pdfsm-dienst = "src.search.dienst:main"`.
  `requirements.txt` entsprechend; `build.bat`/`build.sh` und `release.yml`
  installieren das Web-Extra, damit die Option im Release funktioniert.
- `installer.iss`: nichts Besonderes fuer die EXEs (`recursesubdirs`);
  `[UninstallRun]` ruft `pdfsm-dienst zeitplan --entfernen`, damit die Aufgabe
  beim Deinstallieren verschwindet. Nutzerdaten (auch `suche/`) bleiben.
- Hidden Imports: `mcp`-Teilpakete (pydantic, starlette, anyio), `extract_msg`,
  `xlrd`, `olefile`, `flask`, `waitress` pruefen.
- Rauchtest im Build: `pdfsm-dienst --version`, `pdfsm-dienst status` (leere DB),
  ein `index --pfad` auf einen Testordner mit synthetischen PDFs (prueft
  Pool/spawn im eingefrorenen Zustand), `mcp`-Handshake per `claude mcp get`.

---

## 7. Speicherort und Migration der Datenbank

**Entschieden (05.11.2026):**

- **Neuinstallation:** `get_app_data_dir()/suche/suche.db` (dazu `-wal`, `-shm`,
  `indexer.lock`), umstellbar ueber `SearchConfig.db_pfad` (Einstellungen,
  „Erweitert“), etwa wenn das Systemlaufwerk zu klein ist.
- **Uebernahme einer vorhandenen PDFsuche:** Die Datenbank **bleibt am bisherigen
  Ort**; `db_pfad` zeigt dorthin, die Sperrdatei liegt wie bisher daneben, es wird
  nichts kopiert. Das Original wird dadurch die Arbeitsdatenbank; der alte
  Projektordner darf erst nach Phase 7 aufgeraeumt werden.
- Log immer unter `get_app_data_dir()/logs/suche.log`.
- Die Schema-Version bleibt bei der Uebernahme **1**; das neue Modul hebt sie
  beim ersten Oeffnen additiv auf 2 (Abschnitt 3.3). Beim Auftraggeber ist das
  der Moment der Umstellung in Phase 7, nicht frueher: in den Phasen 1 bis 6
  arbeitet der neue Code nur gegen Testdatenbanken in `tmp_path`.

**Erkennen einer vorhandenen PDFsuche** (ohne festen Pfad im Code):

1. Windows-Aufgabe `\PDFsuche\Indexierung` vorhanden -> Arbeitsverzeichnis der
   Aktion ist der Projektordner.
2. MCP-Eintrag `pdfsuche` in `~/.claude.json` -> Pfad der `pdfsuche-mcp.exe`
   zeigt in das `.venv` des Projekts.
3. Sonst: Schaltflaeche „Vorhandene PDFsuche uebernehmen …“ mit Ordnerauswahl
   (im Assistenten und in den Einstellungen).

**Ablauf der Uebernahme** (GUI-Dialog oder `pdfsm-dienst migration --von ORDNER`):

1. `config.toml` lesen (`tomllib`) und in `SearchConfig` ueberfuehren: Wurzeln,
   Vorrang-Ordner, Ausschluesse, Endungen, Mail-Ordner, OCR-Einstellungen,
   Prozesse, Web-Port, `db_pfad` aus `[datenbank] pfad`. Vorschau im Dialog,
   Nutzer bestaetigt.
2. Sperre pruefen: `indexer.lock` neben der Datenbank (Plattform-Lock). Ist ein
   Lauf aktiv, abbrechen mit Hinweis, nicht warten.
3. Integritaet am Ort: `PRAGMA quick_check`, Zaehler (`dokumente`, `seiten`,
   `ocr_seiten`) anzeigen, `meta.schema_version` muss 1 oder 2 sein. Danach
   `meta.migriert_von`, `meta.migriert_am` setzen (erste Schreibung durch das
   neue Modul, zusammen mit der Ergaenzung auf Version 2).
4. `aktiv = True`, Einstellungen speichern. Die alten Aufgaben werden hier
   **nicht** angefasst (das macht Phase 7 bewusst).
5. Optional im selben Dialog: „Datenbank in das Datenverzeichnis kopieren“
   (fuer Nutzer, die den alten Ordner loswerden wollen): `PRAGMA wal_checkpoint(TRUNCATE)`
   auf der Quelle, Kopie im Worker mit Fortschritt, `quick_check` und
   Zaehlervergleich auf der Kopie, dann `db_pfad` umstellen. Nicht der
   Standardweg.

**Umsetzung (Phase 3, 06.11.2026):** `src/search/migration.py` (Qt-frei):
`finde_pdfsuche()` (Aufgabe `\PDFsuche\Indexierung` per `schtasks /Query /XML`,
MCP-Eintrag `pdfsuche` in `~/.claude.json`; nur Ordner mit `config.toml`),
`pruefen(ordner)` -> `Uebernahme` (Vorschau aus `lade_config_toml`, `db_pfad`
relativ zum Projektordner aufgeloest, Sperre ueber `laeuft_gerade`, `quick_check`
und Zaehler nur lesend, Schema-Version 1 oder 2), `uebernehmen(u, config,
kopieren)` (setzt `meta.migriert_von/-am`, speichert `SearchConfig` mit
`aktiv=True`), `kopiere_db` (SQLite-Sicherungsschnittstelle mit Fortschritt,
Kopie als `.teil`, `quick_check` und Dokumentzahl, dann `os.replace`).
Kommandozeile `pdfsm-dienst migration [--von ORDNER] [--kopieren] [--ja]`
(ohne `--ja` nur Vorschau). Oberflaeche: `src/gui/search_migration_dialog.py`
(Pruefung und Uebernahme im `QThread`, Fortschrittsbalken beim Kopieren),
erreichbar aus der Registerkarte „Suche“ und der Assistentenseite. Die
Registerkarte „Suche“ (`SettingsDialog._create_search_tab`) zeigt alle Felder
der `SearchConfig` inklusive der Stufen der Textebene (`textebene`,
`textebene_sicherung_tage`, neu in der Dataclass, Wirkung ab Phase 5b); die
Assistentenseite „Dokumentensuche“ (`setup_wizard.SearchPage`, nach der
KI-Seite, Standard **aus**) fragt Ordner (vorbelegt Scan-/Zielordner, Laufwerke
bzw. Benutzerordner abwaehlbar), Mails (nur bei gefundenem Thunderbird-Profil),
OCR (nur bei gefundenem Tesseract) und Hintergrundindexierung ab und speichert
nur, wenn sie gesehen wurde.

---

## 8. Oberflaeche (Vorgaben fuer Phase 3 und 4)

- **Reiter „Suche“** im mittleren `QTabWidget` neben „Vorschau“ und „Chat“
  (entschieden). Innen ein `QSplitter`: links Suchfeld, Syntaxhilfe
  (Tooltip/Hilfe-Knopf), Filterleiste (Typ als Chips PDF/Office/Markdown/Mail,
  Ordner, Zeitraum, Sortierung, PDFSM-Metadaten Steuerjahr/Kategorie/
  Korrespondent/Betrag) und Trefferliste mit hervorgehobenen Ausschnitten und
  Seiten-/Blattangabe; rechts eine **eigene Instanz** von `PdfPreviewWidget`
  (springt per `go_to_page()` auf die Trefferseite) bzw. eine Textvorschau mit
  Hervorhebung fuer Office, Markdown und Mails. So bleibt die Trefferliste beim
  Blaettern sichtbar. Aktionen je Treffer: Oeffnen, im Explorer/Finder zeigen,
  Pfad kopieren, Mail als `.eml` oeffnen (Temp-Datei).
- Die Werkzeugleisten-Suche (Strg+F) bleibt und zeigt ihre Ergebnisse ab Phase 5
  im Reiter „Suche“ statt im Detail-Panel; Metadatenfilter bleiben erhalten.
- Statusleiste unten im Reiter: Dokumente im Index, OCR-Rueckstand, laufende
  Phase, Fortschritt, Knopf „Jetzt indizieren“ (Vorrang-Ordner) und
  „Kompletten Lauf starten“. Ist die Suche nicht eingerichtet, zeigt der Reiter
  einen Hinweis mit Knopf zur Einrichtung.
- Alle Abfragen im `QThread` (`search_worker.SuchAbfrage`), eine
  Nur-Lese-Verbindung je Thread, Abbruch veralteter Abfragen bei Neueingabe.
- Einstellungen, Registerkarte „Suche“: Wurzeln, Vorrang-Ordner, Ausschluesse,
  Endungen, Mails (Thunderbird-Profil erkannt/auswaehlen), OCR (Sprachen,
  Seitengrenze), Cloud-Dateien herunterladen, Hintergrundindexierung (Uhrzeit),
  Web-Oberflaeche (an/aus, bei Anmeldung, Port), Prozesse, Speicherort,
  „Vorhandene PDFsuche uebernehmen …“.
- Assistent, Seite „Dokumentensuche“: Suche einschalten? Welche Ordner
  (vorbelegt: Scan- und Zielordner; zusaetzlich Laufwerke bzw. Benutzerordner
  und Volumes waehlbar), Mails ja/nein (nur wenn ein Profil gefunden wurde),
  OCR ja/nein mit Hinweis auf Rechenzeit, Hintergrundindexierung ja/nein.
  Datenschutzhinweis: Index und OCR-Text bleiben lokal, Dateien werden nur
  gelesen, nichts verlaesst den Rechner. Ohne Zustimmung wird nichts indiziert.

**Umsetzung (Phase 4, 06.11.2026):** `src/gui/search_view.py` (`SearchView`,
dritter Reiter „Suche“ im mittleren `QTabWidget`, Menue Ansicht >
„Volltextsuche“, Strg+Umschalt+F) und `src/gui/search_worker.py`
(`SuchAbfrage`, `DokumentLaden`, `StatusAbfrage` als `QThread`; die Fassade
oeffnet je Aufruf eine Nur-Lese-Verbindung, Ergebnisse veralteter Generationen
werden verworfen). Links: Suchfeld (Hilfe als Tooltip, „?“ und in der leeren
Liste; Suche beim Tippen nach 500 ms ab drei Zeichen, Enter sofort), Filter
Typ (Alle/PDF/Office/Markdown/Mail), Ordner (Teil des Pfads bzw. Postfachs),
Zeitraum (von/bis, „–“ = kein Filter), Sortierung; Trefferkarten
(`TrefferKarte`) mit Typ, Titel, Statusmarke, Metazeile, Pfad und Fundstellen
mit Hervorhebung und Link „S. n“ bzw. „Blatt n“; „Weitere Treffer laden“ in
Schritten von 50; Auswahl auch per Pfeiltasten, Enter oeffnet. Rechts: eigene
`PdfPreviewWidget`-Instanz, die nach `document_loaded` per `go_to_page()` auf
die Trefferseite springt (Fundstellen-Link springt in der geladenen PDF
weiter); fuer Office, Markdown, Mails und fehlende PDFs die Textvorschau
(`QTextBrowser`, Seiten/Blaetter mit Hervorhebung, Anker auf die erste
Fundstelle). Aktionen (Knoepfe und Kontextmenue): Oeffnen (PDF ueber
`MainWindow.open_pdf` nach Einstellung, sonst Standardprogramm, Mail als
`.eml`), im Explorer/Finder zeigen, Pfad kopieren, Mail „Als .eml speichern…“;
`Suchindex.mail_als_eml()` schreibt die Mail aus der mbox in den Temp-Ordner
(auch von `web.py` genutzt). Statuszeile unten: `status_zeile()` (Dokumente je
Typ, OCR-Rueckstand, OCR-Grund, laufender Lauf mit Fortschritt bzw. letzter
Lauf), „Jetzt indizieren“ (`lauf_starten(nur_prioritaet=True)`) und
„Kompletten Lauf starten“, waehrend eines Laufs alle 15 s aktualisiert. Ohne
eingerichtete Suche zeigt der Reiter den Hinweis mit „Einrichten…“
(Einstellungen > Suche); `refresh_settings()` nach dem Einstellungsdialog.
Noch offen fuer Phase 5: Metadatenfilter (Steuerjahr, Kategorie, Korrespondent,
Betrag - brauchen Schema-Version 2) und die Umleitung der Werkzeugleisten-Suche.

---

## 9. Behebung der bekannten Schwaechen

| Schwaeche | Loesung | Phase |
|---|---|---|
| mbox-Fortschritt nur je Postfach | `mbox_stand.groesse` bedeutet schon heute „bis hierher gelesen“ (Weiterlesen ab Offset). Der Lauf schreibt den Stand kuenftig alle 30 s mit dem zusammenhaengend fertigen Offset (Wasserstandsmarke ueber die asynchron erledigten Stapel, wie TCP). Kein Schemawechsel. | 1b |
| 492 Lesefehler | Format-Sniffing fuer `.msg` (OLE2 / RFC-822 / sonst), leere Dateien als `leer`, kuerzere Fehlertexte | 1b |
| Excel-Datumswerte | `styles.xml` auswerten: `cellXfs/xf@numFmtId`, eingebaute Datumsformate (14–22, 27–36, 45–47, 50–58) und eigene `numFmts` mit Tages-/Monats-/Jahreszeichen ausserhalb von Anfuehrungszeichen; `workbookPr@date1904`; Ausgabe `TT.MM.JJJJ[ HH:MM]` wie bei `.xls` | 1b |
| `kill_workers()` erst ab 3.14 | Fallback ueber `pool._processes` bleibt, bekommt einen Test mit absichtlich haengendem Arbeitsprozess unter 3.11; zusaetzlich `shutdown(cancel_futures=True)` | 1 |
| Mail-Anhaenge nur mit Namen | **nicht Teil dieser Integration**; Schema laesst es zu (`dokumente.pfad = "<mbox>#<offset>/<anhang>"`), wird nach Phase 8 gesondert abgestimmt | spaeter |
| Eintraege ausserhalb aller Wurzeln bleiben fuer immer | Aufraeumen nach vollstaendigem Lauf (Abschnitt 4.2) | 1b |
| Web-Oberflaeche heisst „PDFsuche“, MCP-Beschreibung nennt feste Laufwerke | Umbenennen in „PDF Sortier Meister – Suche“, MCP-`instructions` aus der Konfiguration erzeugen; Werkzeugnamen und Servername `pdfsuche` bleiben | 1 / 6 |

---

## 10. Praezisierte Phasen 0 bis 8

Jede Phase: eigener Branch von `main`, PR nach `main`, nicht selbst mergen,
Testsuite gruen, `CHANGELOG.md` unter „Unreleased“ gepflegt,
`ENTWICKLUNGSSTAND.md` am Ende jeder Phase ergaenzt. Keine persoenlichen Pfade,
Namen oder Mailinhalte im Repo.

### Phase 0 – Dieses Dokument (Branch `docs/suche-0-architektur`)

Nur `docs/SUCHE_ARCHITEKTUR.md`, keine Code-Aenderung.

### Phase 1 – Uebernahme und Tests (Branch `feat/suche-1-modul`)

- **Kein `git subtree`** (entschieden). Das PDFsuche-Repo fuehrt `config.toml`
  und `README.md` mit persoenlichen Pfaden und Postfachnamen in der Historie;
  jede Subtree-Variante (auch `--squash`) truege sie ins oeffentliche Repo.
  Stattdessen: Code der elf Module und `static/index.html` aus Commit `b763b1a`
  kopieren, Commit-Nachricht nennt Quelle und Hash. Die Historie bleibt im
  archivierten Privat-Repo lesbar.
- Umbau der Importe auf `src.search…`, `Lauf` -> `Indexer.lauf()`, `Config` ->
  `SearchConfig` (`konfig.py`), `Suchindex`-Fassade, Logging ueber
  `get_app_data_dir()/logs/suche.log`.
- `find_tesseract()` nach `src/utils/tesseract.py` (Re-Export in `pdf_analyzer.py`).
- Abhaengigkeiten in `pyproject.toml`/`requirements.txt`, Extra `suche-web`;
  Lizenzhinweise im README-Abschnitt „Dritt-Bibliotheken“.
- Python 3.11: Windows-Importe hinter Funktionen, `kill_workers`-Fallback mit Test.
- Tests (alle Daten synthetisch im Test erzeugt): `suche()` (UND/ODER/NICHT,
  Phrase, Praefix, NEAR, Umlaute, Syntaxfehler-Fallback, Filter typ/ordner/von/bis,
  Sortierung, Namenstreffer); Office (docx mit Kopf-/Fusszeile, xlsx mit
  sharedStrings und inlineStr, odt, doc via olefile-erzeugtem Minimal-Container,
  xls via Fixture oder uebersprungen wenn nicht erzeugbar, RTF als `.doc`, HTML
  als `.doc`, verschluesselt); mbox (Trennung, `From - `, X-Mozilla-Status
  geloescht, Weiterlesen ab Offset, `mail_roh`); Indexer in `tmp_path` (neu,
  geaendert, unveraendert, verschoben mit Texterhalt, kopiert, geloescht nur bei
  vollstaendigem Durchlauf, Cloud-Platzhalter per Monkeypatch der
  Stat-Attribute, Zeitlimit, Absturz eines Arbeitsprozesses); OCR-Pfad mit
  Tesseract-Mock (`subprocess.run` gepatcht); Qt-Freiheit per Unterprozess.
- **Nicht** in Phase 1: Oberflaeche, Dienst-EXE, Migration, Schema v2.

### Phase 1b – Bekannte Schwaechen (Branch `feat/suche-1b-schwaechen`)

Kleine, einzeln testbare Korrekturen aus Abschnitt 9: `.msg`-Sniffing, leere
Dateien, mbox-Zwischenstaende, Excel-Datumsformate, Aufraeumen ausserhalb der
Wurzeln. Getrennt von Phase 1, damit der Uebernahme-PR ein reiner Port bleibt
(entschieden).

### Phase 2 – Plattformschicht (Branch `feat/suche-2-plattform`)

`plattform.py` nach Abschnitt 5 inklusive Thunderbird-Profilsuche, Leerlaufzeit
(macOS), Prozessgruppe/Waechter, Cloud-Attribute, Wurzel-Vorschlaege. Tests mit
simuliertem `sys.platform`; die macOS-CI muss das Paket importieren und die
plattformneutralen Tests bestehen.

### Phase 3 – Konfiguration, Assistent, Migration (Branch `feat/suche-3-einrichtung`)

`SearchConfig` im `"suche"`-Block von `config.json`, Registerkarte „Suche“,
Assistentenseite „Dokumentensuche“, Migrationsdialog und
`pdfsm-dienst migration` nach Abschnitt 7 (Datenbank bleibt am Ort; die
Kommandozeile entsteht hier schon als Modul `dienst.py`, die EXE erst in
Phase 6). GUI-Tests im Stil der vorhandenen `*_gui.py` mit `fresh_config`.

### Phase 4 – Reiter „Suche“ (Branch `feat/suche-4-oberflaeche`)

`search_view.py`, `search_worker.py` nach Abschnitt 8; Statusanzeige und
„Jetzt indizieren“ (startet `python -m src.search.dienst` bzw. die EXE).
GUI-Tests: Abfrage im Thread, Trefferliste, Sprung auf Trefferseite, Aktionen,
Hinweis bei nicht eingerichteter Suche.

### Phase 5 – Zusammenfuehren (Branch `feat/suche-5-zusammenfuehren`)

Abschnitt 3 vollstaendig: Schema-Version 2 (OCR-Cache, Metadatenspalten,
`metadaten_fts`, Erkennung an der Struktur), Metadaten beim Indizieren aus dem
Info-Dict lesen (Vorrangregel), `metadaten_setzen`/`metadaten_ersetzen`,
einmalige Uebernahme und Abschaffung von `document_search`,
`search_documents()` als Fassade, `index_document`/`update_pdf_metadata`/
`update_pdf_path`/`bulk_index_directory` umgestellt, `PDFAnalyzer` liest aus
dem Index und nutzt die gemeinsamen Extraktions- und OCR-Funktionen mit
Rueckschreiben, OCR-Cache mit Auffuellen, Meldungen aus allen
`FileManager`-Aufrufern (Abschnitt 4.3), RAG-Retrieval mit Seitenangabe in den
Zitaten, Werkzeugleisten-Suche auf den Reiter umgeleitet. Tests fuer jede
Fassade, fuer die Vorrangregel, fuer die Uebernahme von `document_search` und
fuer „keine doppelte OCR“ (Mock zaehlt Tesseract-Aufrufe ueber Umbenennen,
XMP-Schreiben, Stapeln).

### Phase 6 – Dienst, MCP, Build (Branch `feat/suche-6-dienst-build`)

`pdfsm-dienst` (alle Plattformen) und `pdfsm-dienstw` (nur Windows) nach
Abschnitt 6, `zeitplan.py` (Aufgabenplanung ohne Adminrechte, LaunchAgent),
Einstellungen schalten die Hintergrundindexierung und die Web-Oberflaeche
ein/aus, MCP-Server mit unveraenderten Werkzeugnamen, Spec/Installer/Build-Skripte,
lokaler Build und Rauchtest beider EXEs, `release.yml` angepasst.

### Phase 7 – Umstellung beim Entwickler (erst nach ausdruecklichem OK)

Wie im Auftrag, mit Datenbank am bisherigen Ort (kein Kopieren): Sperre
pruefen, alte Aufgaben deaktivieren, Uebernahme nach Abschnitt 7 (dabei
Version 2), Pruefung, dass die OCR-Warteschlange (derzeit rund 59.000 Seiten)
im neuen Dienst weiterlaeuft, neue Aufgaben einrichten, Testlauf
`--nur-prioritaet`, MCP umstellen (`claude mcp get pdfsuche` zeigt den neuen
Pfad), je eine Suche ueber MCP, GUI und Web, Bericht mit Zaehlern
vorher/nachher. Alte Aufgaben nur deaktivieren; Loeschen und
`gh repo archive` erst nach Bestaetigung.

### Phase 8 – Dokumentation und Release

`README.md` (Abschnitt „Dokumentensuche“, MCP-Einrichtung, Browser-Oberflaeche,
Dritt-Bibliotheken), `docs/SUCHE_SCHEMA.md` (aus `SCHEMA.md`, Version 2),
`docs/ARCHITECTURE.md` (RAG liest aus dem neuen Index), `ENTWICKLUNGSSTAND.md`,
`CHANGELOG.md`, Release nach `docs/RELEASE_CHECKLISTE.md` ohne Veroeffentlichung
ohne OK.

---

## 11. Entscheidungen des Auftraggebers (05.11.2026)

1. **Branch-Basis:** Der offene Branch `feat/paperport-drag-drop` wird zuerst
   nach `main` gemergt; alle Phasen-Branches zweigen danach von `main` ab.
2. **Kein Subtree**, Kopie des Codes mit Verweis auf den Quell-Commit.
3. **Schema-Version 2 additiv** in `suche.db`, automatisch beim ersten Oeffnen
   durch das neue Modul (beim Auftraggeber in Phase 7).
4. **Eine Such-Datenbank:** PDFSM-Metadaten als Spalten in `suche.db`, beim
   Indizieren aus der PDF gelesen und von PDFSM sofort gesetzt;
   `document_search` entfaellt nach einmaliger Uebernahme.
5. **Windows:** zusaetzliche fensterlose EXE `pdfsm-dienstw.exe`. **macOS:** ein
   Binary `pdfsm-dienst` genuegt (kein Konsolenfenster-Konzept).
6. **Reiter „Suche“** im mittleren Bereich mit eigener Vorschau-Instanz.
7. **Speicherort:** bei Uebernahme einer PDFsuche bleibt die Datenbank am
   bisherigen Ort; Neuinstallationen nutzen `get_app_data_dir()/suche/` mit
   Umstellmoeglichkeit.
8. **Phase 1b** (bekannte Schwaechen) als eigener Schritt nach dem reinen Port.

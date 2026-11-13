# Datenbankschema der Dokumentensuche (Version 2)

Fuer Programme und Skripte, die den Suchindex von PDF Sortier Meister lesen
wollen. Hervorgegangen aus `SCHEMA.md` von PDFsuche (Version 1); Version 2
ergaenzt OCR-Cache, PDFSM-Metadaten und das Protokoll der Textebene.
Hintergruende und Entscheidungen: [SUCHE_ARCHITEKTUR.md](SUCHE_ARCHITEKTUR.md).

## Datei und Zugriff

SQLite 3 im WAL-Modus. Standardort:

| System | Pfad |
|---|---|
| Windows | `%APPDATA%\PDF_Sortier_Meister\suche\suche.db` |
| macOS | `~/Library/Application Support/PDF_Sortier_Meister/suche/suche.db` |

Der Ort laesst sich in den Einstellungen (Suche > Erweitert) umstellen
(`SearchConfig.db_pfad`). Nach der Uebernahme einer vorhandenen PDFsuche bleibt
deren Datenbank an ihrem bisherigen Ort; welcher Ort gilt, zeigt
`pdfsm-dienst status`. Neben der Datenbank liegen `-wal`, `-shm` und
`indexer.lock` (Sperre des laufenden Indexers).

**Nur lesend oeffnen.** Geschrieben wird ausschliesslich ueber `src/search`
(Indexer, `Suchindex`); fremde Schreibzugriffe sind nicht abgestimmt.

```python
import sqlite3
from pathlib import Path

db = Path.home() / "AppData/Roaming/PDF_Sortier_Meister/suche/suche.db"   # Windows-Standard
con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
con.execute("PRAGMA busy_timeout=30000")
```

Der Indexer schreibt nebenher: kurze Transaktionen, `busy_timeout` setzen.

## Version

`meta.schema_version` = `2`. Eine Version-1-Datenbank (PDFsuche) hebt das
Programm beim ersten Oeffnen **additiv** an (`db.ergaenze_schema`: neue Spalten
per `ALTER TABLE`, neue Tabellen mit `IF NOT EXISTS`, kein Neuaufbau, keine OCR
geht verloren). Lesende Programme fuer Version 1 funktionieren unveraendert
weiter: Version 2 entfernt und benennt nichts.

## Tabelle `meta`

| `schluessel` | Bedeutung |
|---|---|
| `schema_version` | `2` |
| `fortschritt` | Stand des laufenden bzw. letzten Laufs (JSON, fuer die Statusanzeige) |
| `voller_lauf_am` | Ende des letzten vollstaendigen Laufs (ISO); `index --einmal-taeglich` prueft das |
| `migriert_von`, `migriert_am` | bei Uebernahme einer PDFsuche: Herkunftsordner und Zeitpunkt |

## Tabelle `dokumente` – ein Datensatz je Datei bzw. je Mail

| Spalte | Bedeutung |
|---|---|
| `id` | Schluessel |
| `pfad` | Eindeutiger Pfad (Gross-/Kleinschreibung egal). Bei Mails aus Thunderbird: `<mbox-Datei>#<Byte-Offset>` |
| `datei` | Echte Datei auf der Platte (bei Thunderbird die mbox-Datei) |
| `name` | Dateiname bzw. Mail-Betreff |
| `ordner` | Ordner bzw. `Thunderbird/<Konto>/<Postfach>` |
| `typ` | `pdf`, `md`, `mail`, `office` |
| `format` | `pdf`, `md`, `eml`, `msg`, `mbox`, `doc`, `docx`, `docm`, `xls`, `xlsx`, `xlsm`, `odt`, `txt` |
| `groesse`, `mtime_ns` | Dateigroesse (Bytes) und Aenderungszeit (Nanosekunden) |
| `datum` | Unix-Zeit: Mail-Datum bzw. Aenderungsdatum der Datei |
| `seiten` | Seitenzahl (PDF) bzw. Zahl der Tabellenblaetter, sonst 1 |
| `textstatus` | siehe unten |
| `ocr_seiten` | Anzahl per OCR erkannter Seiten |
| `prioritaet` | Index des Vorrang-Ordners (0 = erster, typischerweise der Scan-Eingang), 9 = uebrige Ordner |
| `titel`, `autor` | PDF-Metadaten |
| `mail_von`, `mail_an`, `mail_datum` (ISO), `mail_betreff`, `mail_anhaenge` | Mailangaben; Anhaenge durch ` \| ` getrennt |
| `mbox_offset`, `mbox_laenge` | Lage der Mail in der mbox-Datei |
| `fehler` | Fehlermeldung beim Lesen |
| `indiziert_am` | Zeitpunkt der Aufnahme (ISO) |

**Neu in Version 2 – Metadaten** (bei Nicht-PDF-Dokumenten leer):

| Spalte | Bedeutung |
|---|---|
| `pdf_id` | Stabile Kennung aus der `pdfs`-Tabelle von PDFSM (`history.db`) |
| `korrespondent`, `kategorie`, `steuerjahr` | wie im Detailbereich von PDFSM |
| `betrag` | Bruttobetrag (REAL) |
| `buchungsdatum` | Dokumentdatum (ISO) |
| `zusammenfassung`, `schlagwoerter` | Text der KI bzw. des Nutzers |
| `metadaten_quelle` | `pdf` = beim Indizieren aus der Datei gelesen (XMP/Info), `pdfsm` = von PDFSM gesetzt |
| `textebene_am` | Zeitpunkt, zu dem die OCR als unsichtbare Textebene in die PDF geschrieben wurde; `NULL` = nicht |
| `textebene_grund` | Warum (noch) keine Textebene geschrieben wurde, z. B. `signiert`, `gesperrt` |

**Vorrang:** Werte mit `metadaten_quelle = 'pdfsm'` ueberschreibt der Indexer
nie aus der PDF; er fuellt nur leere Felder oder Felder mit Quelle `pdf`.

**`textstatus`:**
`text` (Textebene vorhanden) · `ocr` (vollstaendig per OCR erkannt) ·
`ocr_ausstehend` (wartet auf OCR) · `ocr_teilweise` (einzelne Seiten nicht
erkennbar) · `leer` (kein Text, keine Bilder) · `cloud` (OneDrive-/iCloud-Datei
nur online, nur der Name ist erfasst) · `zu_gross` · `verschluesselt` ·
`fehler` · `ausstehend` (von PDFSM mit Metadaten angelegt, den Text liest der
naechste Lauf)

## Tabelle `seiten` – Text je Seite

| Spalte | Bedeutung |
|---|---|
| `dok_id` | → `dokumente.id` (`ON DELETE CASCADE`) |
| `seite` | Seitennummer ab 1; bei Excel die Nummer des Tabellenblatts (Text beginnt mit „Tabellenblatt: Name“); Word, Markdown, Mails: immer 1 |
| `quelle` | `text` (Textebene), `ocr` (Tesseract), `ohne_text` (wartet auf OCR), `ocr_fehler` |
| `text` | Seitentext |
| `bild_hash` | **neu in Version 2:** BLAKE2b (16 Byte, hex) ueber die Bild-Streams der Seite, Schluessel in `ocr_cache` |

Volltext eines Dokuments am Stueck: Sicht **`v_dokument_text`** (`volltext`,
Seiten durch Seitenvorschub `\f` getrennt).

## Tabelle `ocr_cache` (neu in Version 2)

Jedes Seitenbild wird nur einmal erkannt, auch wenn die Datei verschoben,
umbenannt, kopiert oder mit neuen Metadaten gespeichert wird.

| Spalte | Bedeutung |
|---|---|
| `bild_hash` | Schluessel, wie `seiten.bild_hash` |
| `text` | erkannter Text |
| `sprachen`, `dpi` | Einstellungen der Erkennung (z. B. `deu+eng`, 300) |
| `erstellt` | Zeitpunkt (ISO) |
| `ebene`, `ebene_am` | reine Text-PDF von Tesseract fuer die Textebene, solange sie gebraucht wird |
| `drehung` | Issue #151: Text und Text-PDF stammen aus der um so viel Grad (90/180/270, im Uhrzeigersinn) gedrehten Seite; `NULL` = wie angezeigt |
| `drehen` | Issue #151: `1` = diese Drehung beim naechsten Lauf in die PDF schreiben (bei der OCR vorgemerkt, Stufe `auto_drehen`) |

## Tabelle `textebene_protokoll` (neu in Version 2)

Jede Aenderung einer PDF durch die Textebene oder das automatische Drehen
(Issue #151), mit Sicherungskopie zum Rueckgaengigmachen
(`pdfsm-dienst textebene rueckgaengig <id>`).

| Spalte | Bedeutung |
|---|---|
| `id` | Schluessel |
| `dok_id` | → `dokumente.id` (ohne Fremdschluessel: der Eintrag bleibt, wenn das Dokument verschwindet) |
| `pfad`, `am` | Datei und Zeitpunkt |
| `seiten` | Seiten mit neuer Textebene, z. B. `1,2,5` |
| `gedreht` | Issue #151: richtig herum gedrehte Seiten mit Grad, z. B. `1:180,3:90`; `NULL` = nichts gedreht |
| `gerade` | Issue #165: gerade ausgerichtete Seiten mit Winkel (Grad gegen den Uhrzeigersinn), z. B. `1:-1.75`; `NULL` = nichts ausgerichtet |
| `sicherung` | Pfad der Sicherungskopie; `NULL` = abgelaufen bzw. nach Rueckgaengig entfernt |
| `groesse_vorher`, `mtime_ns_vorher`, `groesse_nachher`, `mtime_ns_nachher` | Dateistand vor und nach dem Schreiben |
| `status` | `geschrieben` oder `rueckgaengig` |
| `rueckgaengig_am` | Zeitpunkt des Rueckgaengigmachens |

## Tabelle `schraeglage` (Issue #165)

Gemessene Schraeglage schief gescannter Seiten, am Bild-Hash wie der OCR-Cache.
Nur Seiten, bei denen sich das Ausrichten lohnt (ab 0,3 Grad), stehen hier.

| Spalte | Bedeutung |
|---|---|
| `bild_hash` | Schluessel, wie `seiten.bild_hash` (fuer gemessene Seiten auch bei Textseiten gesetzt) |
| `winkel` | Grad gegen den Uhrzeigersinn, um die die angezeigte Seite gerade steht |
| `gerade` | `1` = beim naechsten Lauf ausrichten (beim Einlesen vorgemerkt, Stufe `auto_gerade`); `0` = erledigt, auch nach Rueckgaengig |
| `erkannt` | Zeitpunkt der Messung (ISO) |

Teilindex `ix_schraeglage_gerade` (nur vorgemerkte Seiten).

## Tabelle `seiten_vektor` (Issue #230, nur mit eingeschalteter Bedeutungssuche)

Bedeutungsvektor je Seite fuer die Bedeutungssuche des Chats. Die Tabelle gehoert
nicht zum Grundschema: `bedeutung.schema` legt sie an, wenn der Indexlauf die
Seiten zum ersten Mal vorbereitet. Ohne den Schalter gibt es sie nicht.

| Spalte | Bedeutung |
|---|---|
| `seite_id` | Primaerschluessel, `seiten.id` |
| `modell` | Ollama-Modell, das den Vektor berechnet hat (`bedeutung_modell`); nach einem Modellwechsel rechnet der Lauf neu |
| `vektor` | 256 Bytes: die ersten 256 Werte des Modells, normiert, mit 508 multipliziert und als `int8` gerundet |

Die Trigger `seiten_vektor_ad` und `seiten_vektor_au` loeschen den Vektor, wenn
die Seite geloescht oder ihr Text geaendert wird. Seiten unter 40 Zeichen
bekommen keinen Vektor. Platzbedarf mit Verwaltungsdaten: gemessen rund 0,6 MB
je 1.000 Seiten.

## Weitere Tabellen

- `mbox_stand` – je mbox-Datei, bis zu welchem Byte gelesen wurde (`datei`, `groesse`, `mtime_ns`)
- `laeufe` – Indexlaeufe (`beginn`, `ende`, `status` = `laeuft`/`fertig`/`abgebrochen`/`fehler`, `phase`, `statistik` als JSON)

## Volltextsuche (FTS5)

* `seiten_fts` – Index ueber `seiten.text` (rowid = `seiten.id`)
* `dokumente_fts` – Index ueber `dokumente.name` und `dokumente.ordner`
* `metadaten_fts` (neu in Version 2) – Index ueber `korrespondent`, `kategorie`,
  `zusammenfassung`, `schlagwoerter` (rowid = `dokumente.id`); so trifft
  „Telekom“ auch dann, wenn die OCR der Seite schlecht ist

Tokenizer `unicode61 remove_diacritics 2`, also ü = u, é = e. Trigger halten
alle drei FTS-Tabellen automatisch aktuell.

```sql
-- Dokumente mit "Unterhalt" und "2019", beste Seite zuerst
SELECT d.id, d.pfad, s.seite,
       snippet(seiten_fts, 0, '[', ']', ' … ', 20) AS ausschnitt
FROM seiten_fts
JOIN seiten s    ON s.id = seiten_fts.rowid
JOIN dokumente d ON d.id = s.dok_id
WHERE seiten_fts MATCH 'Unterhalt 2019'
ORDER BY bm25(seiten_fts)
LIMIT 50;

-- Rechnungen eines Korrespondenten im Steuerjahr 2025 mit Summe
SELECT count(*), sum(betrag)
FROM dokumente
WHERE korrespondent = 'Stadtwerke Musterstadt' AND kategorie = 'Rechnung' AND steuerjahr = '2025';

-- Volltext eines Dokuments per Pfad
SELECT volltext FROM v_dokument_text WHERE pfad = ?;
```

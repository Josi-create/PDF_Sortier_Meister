# Chat und MCP – Ausbauplan in vier Bausteinen

**Stand:** 09.11.2026 (Planung, noch kein Code; Entscheidungen des Auftraggebers vom
09.11.2026 eingearbeitet, siehe Abschnitt 2)
**Ziel:** Der Chat im Programm bleibt ein rein lesender Assistent und wird durch
klickbare Vorschlaege nuetzlicher. Alles, was mehr Macht braucht (freies Planen,
Schreiben), laeuft ueber den MCP-Server `pdfsm-dienst mcp` in einem externen
KI-Assistenten (Claude Desktop, Claude Code, andere MCP-Clients), der vor jeder
Aktion den Nutzer fragt.

Dieses Dokument legt fest, **wie** das gebaut wird. `docs/CHAT_MCP_PROMPT.md`
enthaelt die daraus abgeleiteten Arbeitsauftraege fuer Claude Code, je Baustein einer.

---

## 1. Ausgangslage

### 1.1 Was heute existiert

| Teil | Datei | Stand |
|---|---|---|
| Chat-Oberflaeche | `src/gui/chat_view.py`, `src/gui/chat_worker.py` | Bubbles, Quellenliste mit Seite, Knopf „Nach … verschieben“ (nur mit Bezugsdokument), aufklappbare Schritte „Was hat die KI getan?“ |
| RAG-Controller | `src/rag/rag_controller.py` | Retrieval ueber den Suchindex, Werkzeug-Schleife bis `chat.max_werkzeug_schritte` (Standard 8), Rueckfall ohne Werkzeuge |
| Werkzeugkasten des Chats | `src/rag/werkzeuge.py` | `suche`, `dokument_lesen`, `ordner_vorschlag`, `korrespondent_info`, optional `sql_abfrage` (nur lesend, `query_only`, Schluesselwort-Pruefung, Zeitlimit). Vergibt chat-lokale Nummern D1, D2, … |
| MCP-Server | `src/search/mcp_server.py` | `suche`, `dokument_lesen`, `index_status`; Index-IDs; nur lesend; Start `pdfsm-dienst mcp` (stdio) |
| Dienst | `src/search/dienst.py`, `packaging/pdfsm_dienst.py` | Konsolenprogramm ohne PyQt6 und ohne SQLAlchemy (`excludes` in `pdf_sortier_meister.spec`) |
| Konfiguration | `src/utils/config.py` | `ChatConfig` (Block `"chat"`: `werkzeuge_aktiv`, `max_werkzeug_schritte`, `sql_erlaubt`, eigenes Modell), `SearchConfig` (Block `"suche"`); der Dienst liest dieselbe `config.json` ueber `src/search/konfig.lade()` |

### 1.2 Fakten, die den Plan praegen

1. **Der Werkzeugkasten haengt an `Database`.** `src/rag/werkzeuge.py`, `src/rag/retrieval.py`
   und `src/core/similar_documents.py` rufen genau sechs Methoden:
   `search_documents`, `get_indexed_documents_brief`, `get_history_brief`,
   `get_korrespondent`, `get_korrespondent_metadata`, `list_korrespondenten`.
   `search_documents` und `get_indexed_documents_brief` sind bereits Fassaden auf
   `Suchindex`; nur Historie und Korrespondenten kommen aus der SQLAlchemy-Datenbank
   (`sorting_history`, `korrespondenten`, `korrespondent_metadata`).
2. **Der Dienst hat kein SQLAlchemy.** `pdfsm-dienst` muss schnell starten (MCP-Clients
   warten auf den Handshake) und bleibt klein. Deshalb liest der Dienst die
   Hauptdatenbank mit `sqlite3` schreibgeschuetzt (Entscheidung, Abschnitt 2).
3. **MCP sieht Index-IDs, der Chat D-Nummern.** Die Logik der Werkzeuge muss unter
   der Nummerierung liegen, die Nummerierung darueber.
4. **Alle beteiligten Module sind Qt-frei und leicht.** `src/rag/*`, `src/core/similar_documents.py`,
   `src/core/korrespondenten.py`, `src/utils/config.py` importieren weder PyQt6 noch numpy
   oder sklearn. Sie duerfen in den Dienst.
5. **Schreibende Dateiaktionen existieren Qt-frei.** `src/core/file_manager.py`
   (`move_file`, `rename_file`, `_get_unique_path`), `src/utils/filename_sanitizer.py`
   (`sanitize_filename`), `Suchindex.datei_verschoben`. Das Protokoll-und-Rueckgaengig-Muster
   gibt es schon fuer die Textebene (`src/search/textebene.py`: `protokoll`, `rueckgaengig`;
   CLI `pdfsm-dienst textebene protokoll|rueckgaengig`).

### 1.3 Sicherheitsmodell

Dokumente sind fremder Text, der ins Modell fliesst (Prompt Injection). Der Schutz
ist einfach und bleibt in allen Bausteinen gleich:

- Im **Chat des Programms** kann das Modell nichts veraendern. Es sucht, liest und
  **schlaegt vor**. Jede Aktion ist ein Knopf, den der Nutzer sieht und klickt. Der
  Zielpfad steht vollstaendig auf dem Knopf oder im Tooltip.
- **Ueber MCP** entscheidet der Host (Claude Desktop, Claude Code) vor jedem
  Werkzeugaufruf; die Werkzeuge tragen MCP-Annotationen (`readOnlyHint`,
  `destructiveHint`). Schreibende Werkzeuge gibt es nur hinter einem Schalter, nur im
  Zwei-Schritt-Muster „planen, dann ausfuehren“, nur innerhalb der Zielordner und des
  Scan-Eingangs, nie loeschen, nie ueberschreiben, immer mit Protokoll und Rueckgaengig.
- Argumente des Modells werden **geprueft, nicht geglaubt**: Pfade gegen die Wurzeln,
  Namen durch `sanitize_filename`, SQL durch die bestehende Pruefung.
- Keine Shell-, Netzwerk- oder Dateisystem-Werkzeuge ausserhalb dieser Liste.
- Eine Weiterleitung des Chatfensters an Claude Desktop per Terminal gibt es nicht
  (Claude Desktop hat keine solche Schnittstelle) und wird auch nicht als Option angeboten.

---

## 2. Entscheidungen des Auftraggebers (09.11.2026)

| Frage | Entscheidung |
|---|---|
| Datenquelle fuer Historie/Korrespondenten im Dienst | **sqlite3-Leser** (schreibgeschuetzt), kein SQLAlchemy im Dienst |
| Baustein 4 (Schreiben per MCP) | **wird gebaut**, nach den Bausteinen 1 bis 3 |
| Reihenfolge | 1 → 3 → 2 → 4 (Einstellungen vor den Vorschlags-Werkzeugen, weil klein und Baustein 1 damit sofort nutzbar ist) |
| `sql_abfrage` ueber MCP | gleicher Schalter wie im Chat (`chat.sql_erlaubt`) |

---

## 3. Baustein 1 – MCP-Server auf den Stand des Werkzeugkastens

**Branch:** `feat/mcp-werkzeugkasten`
**Ergebnis:** Ein MCP-Client kann alles, was das Chat-Modell kann: suchen, lesen,
Ordnervorschlag, Korrespondent-Info, optional SQL. Chat und MCP teilen sich die Logik.

### 3.1 Schritte

1. **Datenquelle entkoppeln – `src/rag/daten.py`.**
   `typing.Protocol` `ChatDaten` mit den sechs Methoden aus 1.2 (Signaturen und
   Rueckgabeformen 1:1 von `Database` uebernehmen). `Database` erfuellt das Protokoll
   unveraendert (strukturelle Typisierung, kein Import von `src.utils.database` in
   `src/rag`). Typannotationen in `werkzeuge.py`, `retrieval.py`, `similar_documents.py`
   auf `ChatDaten` umstellen.
2. **Leser fuer den Dienst – `src/search/pdfsm_daten.py`.**
   Klasse `PdfsmDaten(suchindex, db_pfad)`:
   - `search_documents` und `get_indexed_documents_brief` delegieren an `Suchindex`
     genau wie `Database` (die Fassadenlogik aus `Database.search_documents`, z. B.
     Kappung des Volltexts, in eine gemeinsame Funktion ziehen, falls sie mehr als
     Weiterreichen tut).
   - `get_history_brief`, `get_korrespondent`, `get_korrespondent_metadata`,
     `list_korrespondenten` lesen `sorting_history`, `korrespondenten`,
     `korrespondent_metadata` ueber `sqlite3.connect("file:...?mode=ro", uri=True)`,
     `timeout` wenige Sekunden, Spalten aus den Modellen in `src/utils/database.py`.
   - Fehlende Datenbank oder fehlende Tabelle: leere Ergebnisse, kein Fehler.
   - Pfad: `Config.database_path` (der Dienst laedt `Config` bereits in `konfig.lade`).
3. **Kern herausloesen – `src/rag/werkzeug_kern.py`.**
   Reine, nummerierungsfreie Funktionen aus `Werkzeugkasten` herausziehen:
   - `such_argumente(argumente) -> dict` (Typ-Aliase `TYP_ALIASE`, Sortierungen,
     Anzahl-Kappung),
   - `ordner_vorschlag(doc, daten, wurzeln, scan_ordner, sortier_vorschlaege) -> OrdnerVorschlag`
     (Vorschlaege der Sortierlogik, aehnliche Dokumente ueber
     `find_similar_documents`, Ablageort),
   - `korrespondent_info(name, daten) -> KorrespondentInfo`,
   - `sql_pruefen(sql) -> str` und `sql_abfrage(db_pfad, sql, zeitlimit_s) -> SqlErgebnis`
     (Nur-Lese-Verbindung, `query_only`, Fortschritts-Handler, Zeilen- und Zeichenkappung).
   Die Datenklassen tragen Daten, keinen fertigen Text; `Werkzeugkasten` und MCP
   formatieren selbst (D-Nummern bzw. Index-IDs). `Werkzeugkasten` wird zur Huelle:
   Registrierung, D-Nummern, Protokoll, Fehlertexte. Die vorhandenen Tests
   `tests/test_rag_werkzeuge*.py` muessen unveraendert gruen bleiben.
4. **MCP-Server erweitern – `src/search/mcp_server.py`.**
   - `erstelle_server(konfig)` baut zusaetzlich `PdfsmDaten`, liest Zielordner
     (`Config.get_target_folders()`) und Scan-Eingang (`scan_folder`) und haelt beides
     im Server-Zustand.
   - Neue Werkzeuge mit denselben Parameternamen wie im Chat:
     `ordner_vorschlag(dok_id)`, `korrespondent_info(name)`,
     `sql_abfrage(sql)` (nur registriert, wenn `chat.sql_erlaubt`).
   - `suche` versteht die Typ-Aliase (`excel`, `e-mail`, …) ueber `such_argumente`.
   - Alle Werkzeuge: `annotations=ToolAnnotations(readOnlyHint=True)` (Vorhandensein
     in der installierten `mcp`-Version pruefen; Fallback ohne Annotation).
   - `beschreibung()` nennt die neuen Werkzeuge und den Zweck (Ordnervorschlag fuer
     unsortierte Dokumente im Scan-Eingang).
   - Ausgabe ueber `src/search/ausgabe.py` mit Index-IDs (Format wie `suche`).
5. **Build.** `pdf_sortier_meister.spec`: `dienst_hiddenimports` um `src.rag.werkzeug_kern`,
   `src.rag.daten`, `src.core.similar_documents`, `src.core.rename_examples` ergaenzen,
   falls PyInstaller sie nicht von selbst findet. `sqlalchemy` bleibt ausgeschlossen.
   Startzeit `pdfsm-dienst mcp` vorher/nachher messen (Handshake unter 2 s).
6. **Doku.** README-Abschnitt „Dokumentensuche fuer KI-Assistenten (MCP)“ (Werkzeugliste),
   Tabelle in `docs/SUCHE_ARCHITEKTUR.md` (Abschnitt 2.2 und 4.1), Datenschutz-Tabelle
   (SQL-Abfrage ueber MCP), `CHANGELOG.md`, `ENTWICKLUNGSSTAND.md`.

### 3.2 Tests

- `tests/test_rag_daten.py`: `Database` und `PdfsmDaten` gegen dieselbe Testdatenbank
  (Historie, Korrespondenten mit Metadaten) liefern gleiche Ergebnisse; fehlende DB → leer.
- `tests/test_werkzeug_kern.py`: Typ-Aliase, Ordnervorschlag mit und ohne aehnliche
  Dokumente, Korrespondent-Info, SQL-Pruefung (verbotene Schluesselwoerter, Zeitlimit).
- `tests/test_suche_mcp.py`: Werkzeugfunktionen des Servers gegen einen kleinen Index
  (Muster: `tests/test_suche_dienst.py`, Helfer `tests/helfer_suche.py`); `sql_abfrage`
  fehlt, wenn der Schalter aus ist; Annotationen gesetzt.
- `tests/test_suche_qtfrei.py` erweitern: `src.rag.werkzeug_kern`, `src.rag.daten`,
  `src.search.pdfsm_daten` importieren kein PyQt6 und kein SQLAlchemy.

### 3.3 Abnahme

- `pdfsm-dienst mcp` in Claude Code (`claude mcp add …`) zeigt sechs bzw. fuenf Werkzeuge.
- Frage in Claude Desktop „In welchen Ordner gehoert die Rechnung X im Scan-Eingang?“
  fuehrt zu `suche` → `ordner_vorschlag` → begruendeter Antwort.
- Chat im Programm verhaelt sich unveraendert (`tests/test_chat_*`, `tests/test_rag_*` gruen).

---

## 4. Baustein 3 – Einstellungen fuehren zu Claude Desktop und Claude Code

**Branch:** `feat/mcp-einrichtung`
**Ergebnis:** Der Nutzer sieht im Programm, ob ein MCP-Client installiert und eingerichtet
ist, und richtet ihn mit einem Klick ein.

### 4.1 Schritte

1. **Logik Qt-frei – `src/search/mcp_einrichtung.py`.**
   - `dienst_pfad() -> Path | str`: gebaut neben `sys.executable` (`pdfsm-dienst[.exe]`),
     im Entwicklungsmodus der Aufruf `python -m src.search.dienst mcp`.
   - `claude_code_status()`: `claude` im Pfad? `claude mcp get pdfsuche` erfolgreich?
     → `nicht_gefunden | installiert | eingerichtet`.
   - `claude_desktop_status()`: Konfigurationsdatei vorhanden (macOS
     `~/Library/Application Support/Claude/claude_desktop_config.json`, Windows
     `%APPDATA%\Claude\claude_desktop_config.json`)? Eintrag `mcpServers.pdfsuche`
     vorhanden und zeigt auf den aktuellen Dienstpfad?
   - `claude_desktop_eintrag() -> dict` und `claude_desktop_eintragen(pfad) -> str`:
     JSON lesen, `mcpServers.pdfsuche` setzen oder ersetzen, uebrige Eintraege
     unveraendert, Sicherungskopie `*.bak-JJJJMMTT-HHMMSS`, Fehlertext statt Exception.
   - `claude_code_befehl() -> list[str]`: der `claude mcp add`-Befehl als Argumentliste.
2. **Oberflaeche – `src/gui/settings_dialog.py`, Reiter „Suche“.**
   Gruppe „KI-Assistenten (MCP)“:
   - Pfad des Dienstes (kopierbar), Liste der freigegebenen Werkzeuge, Schalter
     „SQL-Abfragen erlauben“ (derselbe Wert wie im Chat, dort querverweisen).
   - Zeile Claude Code: Status, Knopf „Einrichten“ (Rueckfrage, dann Befehl im
     Hintergrund, Ergebnis anzeigen).
   - Zeile Claude Desktop: Status, Knopf „Eintrag kopieren“ (JSON in die Zwischenablage),
     Knopf „In Konfiguration eintragen“ (Rueckfrage mit Dateipfad, danach Hinweis
     „Claude Desktop neu starten“).
   - Hinweistext: „Der Assistent fragt vor jeder Aktion. Der Dienst liest den Index nur.“
3. **Doku.** README-Abschnitt MCP um den Weg ueber die Einstellungen ergaenzen.

### 4.2 Tests

- `tests/test_mcp_einrichtung.py`: Pfaderkennung gebaut/entwickelt (`sys.frozen`
  gepatcht), Statuslogik mit gepatchtem `shutil.which`/`subprocess.run`, JSON-Merge
  (leer, vorhanden mit anderen Servern, defekt → Fehlertext, Sicherungskopie).
- `tests/test_settings_mcp_gui.py`: Gruppe erscheint, Knoepfe rufen die Logik mit
  dem richtigen Pfad, Zwischenablage enthaelt gueltiges JSON.

---

## 5. Baustein 2 – Chat bleibt lesend, wird aber nuetzlicher

**Branch:** `feat/chat-vorschlaege`
**Ergebnis:** Das Modell kann Aktionen vorschlagen; der Nutzer fuehrt sie per Klick aus.
Das Modell fuehrt weiterhin nichts aus.

### 5.1 Vorschlags-Werkzeuge im Werkzeugkasten

Neue Werkzeuge in `src/rag/werkzeuge.py` (Definitionen) mit Kernlogik in
`src/rag/werkzeug_kern.py` (Pruefung):

| Werkzeug | Argumente | Pruefung | Ergebnis |
|---|---|---|---|
| `vorschlag_verschieben` | `dokument` (D-Nummer, Standard Bezug), `zielordner` (relativ zu einem Zielordner oder absolut), `begruendung` | Ziel liegt innerhalb eines Zielordners (`liegt_in`), Quelle ist Bezug oder liegt im Scan-Eingang/Zielordnern | `Vorschlag(art="verschieben", quelle, ziel, begruendung)` |
| `vorschlag_umbenennen` | `dokument`, `name`, `begruendung` | `sanitize_filename`; Name nicht leer, keine Pfadtrenner | `Vorschlag(art="umbenennen", quelle, name)` |
| `vorschlag_metadaten` | `dokument`, `korrespondent`, `kategorie`, `steuerjahr`, `betrag`, `datum`, `begruendung` | Kategorie ueber `clean_category`, Steuerjahr vierstellig, Betrag numerisch, Datum JJJJ-MM-TT | `Vorschlag(art="metadaten", quelle, felder)` |

- Ein Vorschlag fuehrt **nichts aus**. Er landet im `protokoll` als `Schritt` und in
  `Werkzeugkasten.vorschlaege`. Ungueltige Vorschlaege kommen als `"Fehler: …"` zurueck
  (wie alle Werkzeugfehler) und erscheinen nicht in der Liste.
- Hoechstens ein Vorschlag je Art und Dokument; ein spaeterer ersetzt den frueheren.
- `RAGResponse` erhaelt `vorschlaege: list[Vorschlag]`; der bestehende
  `ordner_vorschlag`/`ordner_anzeige`/`ordner_begruendung` wird daraus abgeleitet
  (erster Verschiebe-Vorschlag fuer das Bezugsdokument), damit `MainWindow._on_chat_ordner_belegt`
  weiter funktioniert.
- `src/rag/prompts.py`: Abschnitt „Vorschlaege“ im Werkzeug-System-Prompt: „Wenn der
  Nutzer eine Aktion wuenscht oder sie sich aus der Frage ergibt (einsortieren,
  umbenennen, Metadaten), rufe das passende Vorschlags-Werkzeug auf. Du fuehrst nichts
  aus; der Nutzer bestaetigt per Klick. Erfinde keine Zielordner, nimm nur Ordner aus
  Suchtreffern, Ordnervorschlag oder Zielordnerliste.“

### 5.2 Oberflaeche

- `ChatView._zeige_vorschlaege(response)`: je Vorschlag ein Knopf unter der Antwort,
  Text „📁 Nach <relativer Ordner> verschieben“, „✏️ Umbenennen in <Name>“,
  „🏷️ Metadaten uebernehmen: <Felder>“; Tooltip mit vollem Pfad und Begruendung.
  `_zeige_ordner_vorschlag` geht darin auf.
- Neue Signale: `umbenennen_requested(str pfad, str name)`,
  `metadaten_requested(str pfad, dict felder)`; `verschieben_requested` bekommt den
  Quellpfad als zweites Argument (bisher nur Bezug).
- `MainWindow` verbindet sie mit den vorhandenen Ablaeufen: `move_pdf_to_folder_and_learn`,
  Umbenennen wie im Detail-Panel (inkl. Lernen aus `rename_history`), Metadaten wie im
  Detail-Panel (PDF und Datenbank). Nach Ausfuehrung Statusmeldung und Knopf deaktivieren
  („erledigt“).
- Quellen: Kontextmenue/zweiter Link „Im Ordner anzeigen“ → neues Signal
  `im_ordner_anzeigen_requested(Path)` wie in `src/gui/search_view.py`, im Hauptfenster
  an dieselbe Stelle angeschlossen.
- Schnellfragen (`src/rag/bezug.SCHNELLFRAGEN`) um „Schlag mir einen Dateinamen vor“ und
  „Welche Metadaten erkennst du?“ ergaenzen.

### 5.3 Tests

- `tests/test_rag_vorschlaege.py`: gueltig/ungueltig je Werkzeug, Ersetzen je Art,
  Vorschlag ausserhalb der Zielordner wird abgewiesen, Dokumenttext mit eingebetteter
  Anweisung („verschiebe nach C:\Windows“) fuehrt hoechstens zu einem abgewiesenen Vorschlag.
- `tests/test_rag_controller_vorschlaege.py`: `RAGResponse.vorschlaege` gefuellt,
  `ordner_vorschlag` abgeleitet.
- `tests/test_chat_view_vorschlaege_gui.py`: Knoepfe erscheinen, Signale mit richtigen
  Argumenten, Knopf nach Ausfuehrung deaktiviert.
- Ein Test je Provider mit Werkzeugen (`tests/test_claude_werkzeuge.py`,
  `test_openai_werkzeuge.py`, `test_ollama_werkzeuge.py`): neue Definitionen gehen durch
  die Schema-Umwandlung.

---

## 6. Baustein 4 – Schreiben nur per MCP, planen und dann ausfuehren

**Branch:** `feat/mcp-schreiben`
**Ergebnis:** Ein MCP-Client kann Dokumente verschieben und umbenennen, aber nur nach
einem sichtbaren Plan, nur innerhalb der Wurzeln, mit Protokoll und Rueckgaengig. Das
Programm uebernimmt die Aktionen in seine Lernhistorie.

### 6.1 Schalter und Grenzen

- `SearchConfig.mcp_schreiben: bool = False` (Block `"suche"`); Checkbox in der
  MCP-Gruppe (Baustein 3) mit Warntext: „Der Assistent darf Dokumente verschieben und
  umbenennen. Er fragt vorher, Aenderungen stehen im Protokoll und lassen sich
  zuruecknehmen.“
- Erlaubt: verschieben und umbenennen von Dateien, die im Scan-Eingang oder in einem
  Zielordner liegen, in einen Ordner innerhalb eines Zielordners (bzw. gleicher Ordner
  beim Umbenennen). Zielordner darf neu angelegt werden, wenn der Elternordner existiert
  und innerhalb eines Zielordners liegt.
- Nie: loeschen, ueberschreiben (Kollision → freier Name ueber `FileManager._get_unique_path`),
  ausserhalb der Wurzeln, Inhalt der PDF aendern, mehr als 20 Aktionen je Plan.

### 6.2 Werkzeuge – `src/search/mcp_aktionen.py` (Qt-frei) und `mcp_server.py`

| Werkzeug | Annotation | Verhalten |
|---|---|---|
| `verschieben_planen(dok_id, zielordner, neuer_name=None)` | `readOnlyHint=True` | Prueft wie 6.1, erzeugt `Plan` mit `plan_id` (zufaellig, kurz), Quelle, Ziel, Pruefergebnis, gueltig 10 Minuten; fuehrt nichts aus. Rueckgabetext: vorher/nachher und „Zum Ausfuehren: plan_ausfuehren('<id>')“. |
| `umbenennen_planen(dok_id, neuer_name)` | `readOnlyHint=True` | wie oben, Name durch `sanitize_filename` |
| `plan_ausfuehren(plan_id)` | `destructiveHint=True`, `idempotentHint=False` | Plan muss existieren und gueltig sein, Quelle unveraendert (mtime/Groesse wie beim Planen). Fuehrt `FileManager.move_file`/`rename_file` aus, meldet `Suchindex.datei_verschoben`, schreibt Eintrag ins Aktionsprotokoll, verwirft den Plan. |
| `aktionen_protokoll(anzahl=50)` | `readOnlyHint=True` | letzte Eintraege mit Nummer, Zeit, Art, vorher, nachher, Zustand (ausgefuehrt/zurueckgenommen) |
| `aktion_rueckgaengig(nummer)` | `destructiveHint=True` | verschiebt zurueck, wenn das Ziel unveraendert ist und die Quelle frei; sonst Fehlertext |

Plaene leben im Serverprozess (ein Prozess je Client-Sitzung). Das Aktionsprotokoll
ist eine Datei `aktionen.jsonl` im Datenordner (`get_app_data_dir()`), eine Zeile je
Aktion (`nr`, `zeit`, `art`, `quelle`, `ziel`, `client`, `zustand`, `rueckgaengig_zeit`).
Zugriff ueber Dateisperre aus `src/search/plattform.py`.

### 6.3 CLI

`pdfsm-dienst aktionen` (`protokoll`, `rueckgaengig <nr>`) nach dem Vorbild von
`pdfsm-dienst textebene protokoll|rueckgaengig`.

### 6.4 Anbindung an die Oberflaeche

- `MainWindow` liest beim Start, beim Fokuswechsel ins Fenster und nach jedem
  Index-Lauf neue Zeilen aus `aktionen.jsonl` (Merker: letzte verarbeitete `nr` in der
  Konfiguration).
- Je neuer Aktion: `Database.add_history`/`record_rename` wie beim manuellen
  Verschieben (Lernen), Kacheln und Baum aktualisieren, Statusmeldung
  „KI-Assistent: <Datei> nach <Ordner> verschoben“ mit Knopf „Rueckgaengig“.
- Der Dienst schreibt **nie** in die SQLAlchemy-Datenbank; die Lernhistorie entsteht nur
  in der Oberflaeche.

### 6.5 Tests

- `tests/test_mcp_aktionen.py`: planen gueltig/ungueltig (ausserhalb der Wurzeln,
  Quelle fehlt, Name unzulaessig, Ueberschreiben → freier Name), Plan verfallen,
  Quelle veraendert → Abbruch, ausfuehren verschiebt und protokolliert, Rueckgaengig,
  Rueckgaengig bei veraendertem Ziel → Fehlertext, Schalter aus → Werkzeuge nicht
  registriert, Annotationen gesetzt.
- `tests/test_suche_dienst.py` erweitern: `aktionen protokoll|rueckgaengig`.
- `tests/test_main_window_aktionen_gui.py`: neue Protokollzeile → Historie-Eintrag,
  Statusmeldung, Merker fortgeschrieben.

### 6.6 Doku

README (Abschnitt MCP: Schalter, was erlaubt ist, Protokoll und Rueckgaengig),
Datenschutz-Tabelle, `docs/SUCHE_ARCHITEKTUR.md` Abschnitt 4.1 „Wer schreibt, wer liest“
(der Dienst schreibt nun Dateien und `aktionen.jsonl`, nicht die Hauptdatenbank),
`CHANGELOG.md`, `ENTWICKLUNGSSTAND.md`.

---

## 7. Reihenfolge, Umfang, Abhaengigkeiten

| Nr. | Baustein | Branch | Umfang | Haengt ab von |
|---|---|---|---|---|
| 1 | MCP = Werkzeugkasten | `feat/mcp-werkzeugkasten` | gross (Kern-Refactoring + Leser + Server) | – |
| 2 | Einstellungen MCP | `feat/mcp-einrichtung` | klein | – (parallel zu 1 moeglich) |
| 3 | Vorschlags-Werkzeuge im Chat | `feat/chat-vorschlaege` | mittel | 1 (Kernmodul) |
| 4 | Schreiben per MCP | `feat/mcp-schreiben` | mittel | 1, 2 (Schalter in der Gruppe) |

Jeder Baustein ist ein eigener Branch von `main` mit Pull Request; Tests gruen
(`pytest -q`), `CHANGELOG.md` und `ENTWICKLUNGSSTAND.md` gepflegt, Commit-Stil wie im
Repository (`feat(mcp): …`, `feat(chat): …`, deutsch, ohne Umlaute in der Betreffzeile).

## 8. Offene Punkte

- ~~Annotationen pruefen~~ (erledigt in Baustein 1, 09.11.2026): `mcp` 2.3.0 kennt
  `ToolAnnotations` und `server.tool(annotations=...)`. Gesetzt sind `readOnlyHint=True` und
  zusaetzlich `openWorldHint=False` (nur lokale Daten); `_werkzeug()` registriert ohne
  Annotation, falls eine aeltere Version den Parameter nicht kennt.
- ~~Startzeit messen~~ (erledigt in Baustein 1): Handshake `python -m src.search.dienst mcp`
  bis zur Antwort auf `initialize` im Median 1,46 s vorher, 1,42 s nachher (je 5 bzw. 7
  Starts) - keine verzoegerten Importe noetig.
- Abweichungen in Baustein 1, vom Code erzwungen oder zur Sicherheit:
  - `ChatDaten` hat neben den sechs Methoden das Attribut `suchindex`: der Werkzeugkasten
    liest damit Volltext, Seiten und die SQL-Datenbank (`db.suchindex`).
  - `ordner_vorschlag(doc, daten, wurzeln, scan_ordner, sortier_vorschlaege)` bekommt als
    `doc` eine kleine Datenklasse `Dokument(pfad, name, text)`; den Volltext besorgt der
    Aufrufer (Chat: Kontext, Index oder Bezug; MCP: Index). `sortier_vorschlaege=None` heisst
    "liegen nicht vor"; `im_scan_eingang` kann der Chat vorgeben (Sonderfall Bezug).
  - Der MCP-Server liefert beim Ordnervorschlag **keine Vorschlaege der Sortierlogik**: die
    entstehen im Klassifikator (sklearn) der Oberflaeche, der nicht im Dienst ist. Er
    stuetzt sich auf aehnliche Dokumente (Historie und Index), Zielordner und Lage.
  - `erstelle_server(konfig, umgebung=None)`: Hauptdatenbank, Zielordner, Scan-Eingang und
    SQL-Schalter kommen als `Umgebung` herein; `main()` laedt sie mit `lade_umgebung()`
    (gleiche `config.json` wie `konfig.lade`, `--config` wird durchgereicht). So lesen Tests
    nie die echte Konfiguration. Aenderungen in den Einstellungen wirken nach Neustart des
    Assistenten.
  - `such_argumente(..., abfrage_pflicht=False)` fuer MCP: dort war eine Suche nur mit
    Filtern schon bisher moeglich. Ungueltige Argumente kommen beim MCP wie im Chat als Text
    `"Fehler: ..."` zurueck (nicht als MCP-Fehler).
  - Gemeinsame Textform nur ohne Dokumentnummern: `korrespondent_text`, `sql_tabelle`,
    `sql_beschreibung` (mit eigenem Schlusssatz je Aufrufer).
  - Build: PyInstaller findet die neuen Module selbst (modulegraph geprueft), keine
    `hiddenimports`. Neu ausgeschlossen im Dienst: `src.utils.database` und
    `src.ml.classifier`, die nur ueber verzoegerte Importe erreichbar sind.
  - `tests/test_suche_dienst.py::test_mcp_werkzeuge`: erwartete Werkzeugliste um
    `ordner_vorschlag` und `korrespondent_info` ergaenzt (Folge von 3.1 Schritt 4).
- Abweichungen in Baustein 3 (09.11.2026), vom Code bzw. vom System erzwungen:
  - **Konfiguration von Claude Desktop unter Windows an drei Orten.** Die Store-Fassung
    (MSIX, auf dem Entwicklungsrechner 4.23118) legt sie unter
    `%LOCALAPPDATA%\Claude-Data\claude_<id>\claude_desktop_config.json` ab; `%APPDATA%\Claude`
    gibt es dort nicht. Aeltere Store-Fassungen nutzen den Paketordner
    (`%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Roaming\Claude`, nach dem Umzug nur noch
    eine Markierungsdatei `.user-data-left.*`), der klassische Installer `%APPDATA%\Claude`.
    `claude_desktop_konfig()` nimmt die erste vorhandene Datei, sonst den ersten vorhandenen
    Ordner, sonst „nicht gefunden“.
  - **Entwicklungsmodus:** `python packaging/pdfsm_dienst.py mcp` mit `PYTHONPATH` auf den
    Quellbaum statt `python -m src.search.dienst mcp` - bei `-m` steht das Arbeitsverzeichnis
    vorn im Suchpfad, und Claude Code startet den Server im jeweiligen Projektordner.
    `dienst_pfad()` liefert dort die ganze Befehlszeile; `dienst_aufruf()` liefert Programm,
    Argumente und Umgebung fuer beide Clients.
  - **Zustaende:** zusaetzlich zu `nicht_gefunden | installiert | eingerichtet` gibt es
    `anderer_pfad` (eingetragen, startet aber ein anderes Programm, z. B. eine andere
    Installation oder den Entwicklungsstand) und `fehler` (Konfiguration kein gueltiges JSON,
    `claude` haengt). Bei `eingerichtet`/`anderer_pfad` heisst der Knopf fuer Claude Code
    „Neu einrichten“ und fuehrt vorher `claude mcp remove pdfsuche -s user` aus, weil
    `claude mcp add` einen vorhandenen Namen ablehnt.
  - **„Eintrag kopieren“** legt vollstaendiges JSON `{"mcpServers": {"pdfsuche": {...}}}` in die
    Zwischenablage (gueltig fuer sich, so auch als ganze Datei verwendbar).
  - **Pruefung erst beim Oeffnen des Reiters „Suche“**, Claude Code im Hintergrund:
    `claude mcp get` startet den Server zur Probe (rund 2 s). `tests/conftest.py` setzt fuer alle
    Tests `claude_programm` und `claude_desktop_konfig` auf „nicht gefunden“, damit kein Test das
    echte Claude Code startet oder die echte Konfiguration liest.
- Claude-Desktop-Konfigurationspfad unter Linux (`~/.config/Claude/`) nur aufnehmen,
  wenn Linux-Builds kommen.
- Metadaten-Schreiben ueber MCP (Korrespondent, Kategorie, Steuerjahr in PDF und Index)
  ist bewusst **nicht** Teil von Baustein 4; spaeter als eigener Baustein moeglich, dann
  ebenfalls planen/ausfuehren.

# Arbeitsauftraege fuer Claude Code – Chat und MCP

Diese Datei gehoert zu `docs/CHAT_MCP_PLAN.md`. Je Baustein steht hier ein fertiger
Prompt, der in Claude Code eingefuegt wird (Projektordner geoeffnet, Branch `main`
aktuell). Die Bausteine in der Reihenfolge 1 → 3 → 2 → 4 abarbeiten, jeder in einer
eigenen Sitzung und auf einem eigenen Branch. Vor dem naechsten Baustein den Pull Request
des vorigen mergen und `main` ziehen.

Vorbereitung am PC:

```bash
git checkout main
git pull
```

---

## Prompt 0 – Einstieg (vor jedem Baustein voranstellen)

```text
Lies zuerst docs/CHAT_MCP_PLAN.md vollstaendig, danach ENTWICKLUNGSSTAND.md (Kopf) und
CHANGELOG.md (oberster Eintrag). Der Plan ist beschlossen; weiche nur ab, wenn der Code
etwas anderes erzwingt, und schreib die Abweichung dann in den Plan unter "Offene Punkte".

Regeln fuer diese Arbeit:
- Arbeite auf dem im Auftrag genannten Branch, abgezweigt von main. Kleine, thematische
  Commits auf Deutsch ohne Umlaute in der Betreffzeile, Praefix wie im Repository
  (feat(mcp): ..., feat(chat): ..., test: ..., docs: ...).
- Qt-freie Logik bleibt Qt-frei (src/rag, src/search, src/core). Nichts aus src/gui in
  diese Module importieren. src/search darf kein SQLAlchemy importieren.
- Jede neue Logik bekommt Tests nach dem Muster der Nachbartests in tests/. Vorhandene
  Tests duerfen nicht angepasst werden, um gruen zu werden, ausser der Plan sagt es.
- Fuehre am Ende die gesamte Testsammlung aus (pytest -q) und berichte das Ergebnis
  woertlich. Gib nicht "fertig" aus, solange Tests fehlschlagen.
- Pflege CHANGELOG.md (neuer Abschnitt "Unreleased" oder vorhandener) und
  ENTWICKLUNGSSTAND.md (Abschnitt "Chat und MCP") mit Datum.
- Lege am Ende einen Pull Request gegen main an (gh pr create) mit Zusammenfassung,
  Testergebnis und Hinweis, was manuell zu pruefen ist. Nicht mergen.
- Frag nicht nach, wenn der Plan die Antwort enthaelt. Wenn etwas im Plan nicht
  umsetzbar ist, setze alles Uebrige um und benenne die Luecke klar im PR.
```

---

## Prompt 1 – Baustein 1: MCP-Server auf den Stand des Werkzeugkastens

```text
Auftrag: Baustein 1 aus docs/CHAT_MCP_PLAN.md, Abschnitt 3, auf dem Branch
feat/mcp-werkzeugkasten.

Vorgehen in dieser Reihenfolge, nach jedem Schritt Tests und Commit:

1. src/rag/daten.py: Protocol ChatDaten mit den sechs Methoden search_documents,
   get_indexed_documents_brief, get_history_brief, get_korrespondent,
   get_korrespondent_metadata, list_korrespondenten (Signaturen aus
   src/utils/database.py uebernehmen). Typannotationen in src/rag/werkzeuge.py,
   src/rag/retrieval.py und src/core/similar_documents.py auf ChatDaten umstellen.
   Kein Import von src.utils.database in src/rag.

2. src/search/pdfsm_daten.py: Klasse PdfsmDaten(suchindex, db_pfad), erfuellt ChatDaten.
   Suche und indizierte Dokumente ueber Suchindex wie in Database; Historie und
   Korrespondenten per sqlite3 schreibgeschuetzt (URI mode=ro) aus sorting_history,
   korrespondenten, korrespondent_metadata. Fehlende Datei oder Tabelle -> leere
   Ergebnisse. Test tests/test_rag_daten.py vergleicht Database und PdfsmDaten gegen
   dieselbe Testdatenbank.

3. src/rag/werkzeug_kern.py: nummerierungsfreie Kernfunktionen aus Werkzeugkasten
   herausloesen (such_argumente, ordner_vorschlag, korrespondent_info, sql_pruefen,
   sql_abfrage) mit Datenklassen als Rueckgabe. Werkzeugkasten wird zur Huelle
   (D-Nummern, Protokoll, Fehlertexte). tests/test_rag_werkzeuge*.py bleiben
   unveraendert gruen. Neue Tests in tests/test_werkzeug_kern.py.

4. src/search/mcp_server.py: PdfsmDaten, Zielordner (Config.get_target_folders) und
   Scan-Eingang im Server; neue Werkzeuge ordner_vorschlag(dok_id),
   korrespondent_info(name), sql_abfrage(sql) (nur wenn chat.sql_erlaubt); suche
   versteht Typ-Aliase; Ausgabe mit Index-IDs ueber src/search/ausgabe.py;
   ToolAnnotations(readOnlyHint=True) fuer alle Werkzeuge, mit Fallback, falls die
   installierte mcp-Version den Parameter nicht kennt; beschreibung() erweitern.
   Tests in tests/test_suche_mcp.py nach dem Muster von tests/test_suche_dienst.py.

5. tests/test_suche_qtfrei.py erweitern: die neuen Module importieren weder PyQt6 noch
   sqlalchemy. pdf_sortier_meister.spec: dienst_hiddenimports ergaenzen, falls noetig.
   Startzeit von "python -m src.search.dienst mcp" bis zum Handshake messen und im PR
   nennen.

6. Doku: README-Abschnitt "Dokumentensuche fuer KI-Assistenten (MCP)" (Werkzeugliste),
   docs/SUCHE_ARCHITEKTUR.md Abschnitt 2.2 und 4.1, Datenschutz-Tabelle im README,
   CHANGELOG.md, ENTWICKLUNGSSTAND.md.

Abnahme laut Plan 3.3. Im PR beschreiben, wie ich das in Claude Desktop pruefe.
```

---

## Prompt 3 – Baustein 3: Einstellungen fuehren zu Claude Desktop und Claude Code

```text
Auftrag: Baustein 3 aus docs/CHAT_MCP_PLAN.md, Abschnitt 4, auf dem Branch
feat/mcp-einrichtung.

1. src/search/mcp_einrichtung.py (Qt-frei): dienst_pfad(), claude_code_status(),
   claude_desktop_status(), claude_desktop_eintrag(), claude_desktop_eintragen(pfad)
   mit Sicherungskopie, claude_code_befehl(). Konfigurationspfade fuer macOS und
   Windows wie im Plan. Alle Funktionen liefern Fehlertexte statt Exceptions.
   Tests in tests/test_mcp_einrichtung.py mit gepatchtem shutil.which, subprocess.run,
   sys.frozen und temporaeren Konfigurationsdateien (leer, mit anderen Servern, defekt).

2. src/gui/settings_dialog.py, Reiter "Suche": Gruppe "KI-Assistenten (MCP)" mit
   Dienstpfad (kopierbar), Werkzeugliste, Schalter "SQL-Abfragen erlauben" (gleicher
   Wert wie chat.sql_erlaubt, Querverweis im Tooltip), Zeile Claude Code (Status, Knopf
   "Einrichten" mit Rueckfrage, Befehl im Hintergrund, Ergebnis anzeigen), Zeile Claude
   Desktop (Status, "Eintrag kopieren", "In Konfiguration eintragen" mit Rueckfrage und
   Hinweis auf Neustart). Hinweistext laut Plan. Keine Option fuer eine Weiterleitung
   per Terminal. GUI-Test tests/test_settings_mcp_gui.py.

3. README-Abschnitt MCP um den Weg ueber die Einstellungen ergaenzen; CHANGELOG.md,
   ENTWICKLUNGSSTAND.md.
```

---

## Prompt 2 – Baustein 2: Vorschlags-Werkzeuge im Chat

```text
Auftrag: Baustein 2 aus docs/CHAT_MCP_PLAN.md, Abschnitt 5, auf dem Branch
feat/chat-vorschlaege. Voraussetzung: Baustein 1 ist gemerged (src/rag/werkzeug_kern.py
existiert).

1. Datenklasse Vorschlag (art, quelle, ziel/name/felder, begruendung) und Pruefung in
   src/rag/werkzeug_kern.py. Werkzeuge vorschlag_verschieben, vorschlag_umbenennen,
   vorschlag_metadaten in src/rag/werkzeuge.py laut Tabelle 5.1: Pruefung mit liegt_in,
   sanitize_filename, clean_category; ungueltig -> "Fehler: ..."; hoechstens ein
   Vorschlag je Art und Dokument; Werkzeugkasten.vorschlaege; nichts wird ausgefuehrt.
   Tests tests/test_rag_vorschlaege.py einschliesslich Injection-Fall (Dokumenttext mit
   eingebetteter Anweisung fuehrt hoechstens zu einem abgewiesenen Vorschlag).

2. RAGResponse.vorschlaege in src/rag/rag_controller.py; ordner_vorschlag,
   ordner_anzeige, ordner_begruendung daraus ableiten, damit MainWindow unveraendert
   funktioniert. System-Prompt in src/rag/prompts.py um den Abschnitt "Vorschlaege"
   laut Plan 5.1 ergaenzen. Tests tests/test_rag_controller_vorschlaege.py.

3. src/gui/chat_view.py: _zeige_vorschlaege(response) ersetzt _zeige_ordner_vorschlag;
   Knoepfe laut Plan 5.2 mit vollem Pfad im Tooltip; Signale umbenennen_requested,
   metadaten_requested, verschieben_requested mit Quellpfad; "Im Ordner anzeigen" fuer
   Quellen (Signal im_ordner_anzeigen_requested wie in src/gui/search_view.py).
   src/gui/main_window.py verbindet die Signale mit den vorhandenen Ablaeufen
   (move_pdf_to_folder_and_learn, Umbenennen und Metadaten wie im Detail-Panel),
   deaktiviert den Knopf nach Ausfuehrung und zeigt eine Statusmeldung.
   GUI-Test tests/test_chat_view_vorschlaege_gui.py.

4. Schnellfragen in src/rag/bezug.py ergaenzen. Pruefen, dass die neuen
   Werkzeugdefinitionen durch die Schema-Umwandlung aller Provider mit Werkzeugen gehen
   (tests/test_claude_werkzeuge.py, test_openai_werkzeuge.py, test_ollama_werkzeuge.py
   um je einen Fall erweitern). docs/ARCHITECTURE.md, CHANGELOG.md, ENTWICKLUNGSSTAND.md.
```

---

## Prompt 4 – Baustein 4: Schreiben nur per MCP, planen und dann ausfuehren

```text
Auftrag: Baustein 4 aus docs/CHAT_MCP_PLAN.md, Abschnitt 6, auf dem Branch
feat/mcp-schreiben. Voraussetzung: Bausteine 1 und 3 sind gemerged.

1. SearchConfig.mcp_schreiben (Standard False) in src/search/konfig.py und
   src/utils/config.py; Checkbox mit Warntext in der MCP-Gruppe der Einstellungen.

2. src/search/mcp_aktionen.py (Qt-frei): Plan (plan_id, quelle, ziel, mtime/Groesse,
   gueltig_bis), Pruefung laut Plan 6.1 (innerhalb Scan-Eingang/Zielordner, nie
   loeschen, nie ueberschreiben, sanitize_filename, hoechstens 20 Aktionen),
   Aktionsprotokoll aktionen.jsonl im Datenordner mit Dateisperre aus
   src/search/plattform.py, Rueckgaengig nur bei unveraendertem Ziel und freier Quelle.
   Dateiaktionen ueber src/core/file_manager.py, Indexmeldung ueber
   Suchindex.datei_verschoben. Tests tests/test_mcp_aktionen.py laut Plan 6.5.

3. src/search/mcp_server.py: Werkzeuge verschieben_planen, umbenennen_planen,
   plan_ausfuehren, aktionen_protokoll, aktion_rueckgaengig mit Annotationen laut
   Tabelle 6.2; nur registriert, wenn suche.mcp_schreiben gesetzt ist. beschreibung()
   erklaert das Zwei-Schritt-Muster.

4. src/search/dienst.py: Unterbefehl "aktionen" mit "protokoll" und "rueckgaengig <nr>"
   nach dem Vorbild von "textebene". tests/test_suche_dienst.py erweitern.

5. src/gui/main_window.py: neue Zeilen aus aktionen.jsonl beim Start, beim Fokuswechsel
   und nach einem Index-Lauf lesen (Merker letzte nr in der Konfiguration), Lernhistorie
   wie beim manuellen Verschieben/Umbenennen schreiben, Ansicht aktualisieren,
   Statusmeldung mit Knopf "Rueckgaengig". Der Dienst schreibt nie in die
   SQLAlchemy-Datenbank. GUI-Test tests/test_main_window_aktionen_gui.py.

6. README (Abschnitt MCP und Datenschutz-Tabelle), docs/SUCHE_ARCHITEKTUR.md Abschnitt
   4.1, CHANGELOG.md, ENTWICKLUNGSSTAND.md.

Im PR beschreiben, wie ich in Claude Desktop einen Plan erzeuge, ausfuehre und
zuruecknehme.
```

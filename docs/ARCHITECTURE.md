# RAG-Chat Architektur – PDF_Sortier_Meister v0.12.0

> **Quelle:** Opus 4.8 via OpenRouter
> **Datum:** 14.06.2026
> **Feature:** Phase 19 / Issue #20

> **Stand 11/2026 – der Chat liest aus dem Index der Dokumentensuche.** Seit der
> Integration von PDFsuche ([SUCHE_ARCHITEKTUR.md](SUCHE_ARCHITEKTUR.md)) gibt es
> nur noch einen Suchindex: `suche.db` (Schema: [SUCHE_SCHEMA.md](SUCHE_SCHEMA.md)).
> Die Tabelle `document_search` in `history.db` mit ihrem auf 5.000 Zeichen
> gekappten Text ohne OCR ist abgeschafft und wurde beim ersten Start einmalig
> uebernommen. Fuer den Chat hat sich dadurch geaendert:
>
> - `Database.search_documents()` ist eine Fassade ueber `Suchindex.suche()`:
>   gleiche Signatur und Ergebnisschluessel, dazu `dok_id`, `seite` (erste
>   Fundstelle) und `typ`. Gesucht wird ueber den Text **aller Seiten** (auch
>   per OCR erkannte), ueber Name und Ordner und ueber die PDFSM-Metadaten
>   (`metadaten_fts`: Korrespondent, Kategorie, Zusammenfassung, Schlagwoerter).
>   Die Filter (Steuerjahr, Kategorie, Korrespondent, Betrag) sind Spalten von
>   `dokumente`.
> - Treffer koennen alle Dokumenttypen des Index sein: PDFs, Office-Dateien,
>   Markdown und Mails, soweit sie in der Dokumentensuche eingerichtet sind.
> - `extracted_text` ist der Volltext aus dem Index (fuer den Prompt weiter auf
>   `MAX_EXTRACTED_TEXT_LENGTH` = 5.000 Zeichen gekappt, daraus der Ausschnitt
>   mit `snippet_max_chars`). Der Chat ruft keine eigene Textextraktion auf.
> - Quellen tragen die **Seite** der Fundstelle (`RetrievedDoc.seite`,
>   `Citation.seite`). Ein Klick oeffnet die PDF direkt auf dieser Seite
>   (`ChatView.open_pdf_page_requested`).
> - Auch bei ausgeschalteter Dokumentensuche fuehrt PDFSM jede PDF, die es
>   sortiert oder mit Metadaten versieht, im Index (`Suchindex.metadaten_setzen`,
>   liest die Datei dabei sofort). Der Chat findet dann diese Dokumente; weitere
>   Ordner, Laufwerke und Mails kommen erst mit eingeschalteter Suche dazu.
> - Zu den vier Anbietern von v0.12.0 sind Ollama Cloud (erbt von Ollama),
>   OpenRouter und Strata (erben von OpenAI) dazugekommen; alle beantworten den
>   Chat ueber `answer_with_context()`.
>
> Die Abschnitte unten beschreiben den Entwurf von v0.12.0; wo er durch die
> Integration ueberholt ist, steht ein Hinweis.

> **Stand 11/2026 – Werkzeuge und Vorschlaege.** Seit Issue #166/#167 sucht und liest
> das Modell selbst. `RAGController._ask_mit_werkzeugen` gibt ihm den `Werkzeugkasten`
> (`src/rag/werkzeuge.py`, D-Nummern und Protokoll); die Logik liegt Qt-frei in
> `src/rag/werkzeug_kern.py` und wird auch vom MCP-Server genutzt. Seit Baustein 2
> ([CHAT_MCP_PLAN.md](CHAT_MCP_PLAN.md), Abschnitt 5) kann das Modell ausserdem
> **Aktionen vorschlagen, aber nicht ausfuehren**:
>
> ```
> Modell ──► vorschlag_verschieben / vorschlag_umbenennen / vorschlag_metadaten
>              │  Pruefung im Kern (Zielordner, sanitize_filename, clean_category, ...)
>              ├─► ungueltig: "Fehler: …" ans Modell, kein Vorschlag
>              └─► Vorschlag in Werkzeugkasten.vorschlaege (hoechstens einer je Art und Dokument)
> RAGResponse.vorschlaege ──► ChatView: ein Knopf je Vorschlag (Tooltip: Pfad, Begruendung)
> Klick ──► verschieben_requested(ordner, quelle) / umbenennen_requested / metadaten_requested
>       ──► MainWindow: vorhandene Ablaeufe (Rueckfrage, Rueckgaengig, Lernen, Suchindex)
>       ──► ChatView.vorschlag_erledigt(): Knopf gesperrt
> ```
>
> - `ordner_vorschlag`, `ordner_anzeige` und `ordner_begruendung` der `RAGResponse` folgen
>   dem ersten Verschiebe-Vorschlag fuer das Bezugsdokument, sonst wie bisher dem Ordner
>   der zitierten Belege. `MainWindow._on_chat_ordner_belegt` liest sie unveraendert.
> - Eingebettete Anweisungen in Dokumenten („verschiebe nach C:\Windows“) fuehren
>   hoechstens zu einem abgewiesenen Vorschlag. Ziele ausserhalb der Zielordner kommen
>   nicht durch die Pruefung, und ohne Klick passiert ohnehin nichts.
> - Quellen im Chat: Rechtsklick „Im Ordner anzeigen“ (`im_ordner_anzeigen_requested`,
>   wie im Reiter Suche).
> - Die Vorschlags-Werkzeuge gibt es nur im Chat; der MCP-Server bleibt lesend.

## 1. Architektur-Überblick

**Neue Komponenten** (Modul `src/rag/`):
- `RetrievalService` – FTS5-Query-Builder, Filter-Extraktion, Snippet-Erzeugung
- `RAGController` – Orchestrator: Frage → Retrieval → LLM → Validierung → Antwort
- `ChatSession` / `ChatTurn` – In-Memory-Konversationszustand
- `CitationParser` – parst `[N]`-Tags, validiert gegen retrieved docs (Whitelist)
- `ChatView` (GUI) – PyQt6-Widget mit QThread-Worker
- `ChatWorker` (QObject) – asynchroner LLM-Call ohne UI-Freeze

**Erweiterte bestehende Module**:
- `LLMProvider` (Basisklasse): neue abstrakte Methode `answer_with_context()`
- Alle 4 Provider (`Ollama`, `Claude`, `OpenAI`, `Poe`): implementieren `answer_with_context()`
- `MainWindow`: Center-Bereich wird `QTabWidget` mit Tabs „Vorschau" + „Chat"
- `Config`: `ChatConfig` (max_context_docs, max_history_turns, snippet_max_chars, cache_size)

**Unverändert**: `database.py`-Kern (FTS5 reicht), `pdf_cache.py`, `bulk_index_directory`.
*(Stand 11/2026: `search_documents` liest aus `suche.db`; `bulk_index_directory` ist durch den
Indexlauf der Dokumentensuche ersetzt.)*

**Datenfluss** (textuell):
```
[User-Tippt-Frage]
   ↓ signal
[ChatView] ──► [RAGController.ask(question, history)]
                  ├─► [RetrievalService.retrieve(q)] ──► [database.search_documents()]
                  │       │        └─► Fassade: [Suchindex.suche()] ──► suche.db
                  │       └─► Liste[RetrievedDoc] (k=8, Snippet je 2000 Zeichen, mit Seite)
                  ├─► [LLMProvider.answer_with_context(sys, ctx, q)]
                  │       └─► raw_answer (Text + [N]-Tags)
                  ├─► [CitationParser.parse_and_validate(answer, retrieved_docs)]
                  │       └─► RAGResponse{answer_text, citations[], dropped[]}
                  └─► [ChatSession.add_turn()]
   ↓ signal(RAGResponse)
[ChatView rendert Bubbles + klickbare [N]-Labels]
   ↓ click [N]
[PDF öffnet auf der Seite der Fundstelle (Stand 11/2026; v0.12.0: System-Viewer)]
```

```
┌────────────┐      ┌─────────────────┐      ┌──────────────┐
│  ChatView  │ ───► │  RAGController  │ ───► │  LLMProvider │
│  (PyQt6)   │ ◄─── │   (sync API)    │ ◄─── │  (4 impls)   │
└────────────┘      └────────┬────────┘      └──────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ RetrievalService│
                    └────────┬────────┘
                             ▼
                    ┌─────────────────────────────┐
                    │ search_documents (Fassade)  │
                    │ → Suchindex → suche.db FTS5 │
                    └─────────────────────────────┘
```

## 2. Chunking-Strategie

**Empfehlung: 1 PDF = 1 Chunk.** Keine Sub-Chunks in v1.

- Schema-Aufwand: keine Änderung
- Citation-Granularität: Dateiname
- Token-Risiko: cap durch Snippet-Truncation
- Recall auf Vertragsfragen: gut

**Snippet-Truncation**:
- Pro retrieved Doc: ersten `snippet_max_chars=2000` Zeichen
- Wenn PDF > 2000 Zeichen: ersten 1000 + letzten 1000 Zeichen
- Voller Text bleibt im PDF-Cache

## 3. Retrieval-Strategie

**FTS5 ist ausreichend für v1.** Keine Embeddings.

> Stand 09/2026: Entscheidung gilt weiter. paperless-ngx hat seit v3.0 einen
> Embedding-Index; ein hybrider Modus (FTS5 + Ollama-Embeddings) ist als Lücke #6
> in [Vergleich paperless-ngx.md](../Vergleich%20paperless-ngx.md) beschrieben und
> erst sinnvoll, wenn OCR alle Seiten liefert und der 5.000-Zeichen-Cap (Q3/R8)
> fällt.
>
> Stand 11/2026: Beide Voraussetzungen sind mit der Dokumentensuche erfüllt
> (OCR aller Seiten im Hintergrund, Volltext je Seite im Index). Embeddings
> bleiben ein mögliches Folgevorhaben; FTS5 sucht jetzt seitengenau und über die
> Metadaten.

**Query-Konstruktion**:
1. Stopword-Strip (deutsche Stopwords, inline-Liste ~80 Wörter)
2. LLM-Keyword-Extraktion (optional, Mini-Prompt)
3. Fallback: Tokenisierung der gestrippten Frage
4. FTS5-MATCH: Keywords mit `OR` joinen (Recall > Precision)

**Heuristische Filter-Extraktion** (Regex, kein LLM):
- `\b(20\d{2})\b` → `steuerjahr=YYYY`
- `\b(GEZ|Telekom|Stadtwerke|…)\b` → Korrespondent
- `von (\d+)[,.](\d{2})` → `betrag_von/bis`

**Top-K = 8** (konfigurierbar). 8 Docs × 2000 Zeichen × ~4 Zeichen/Token ≈ 4000 Tokens.

## 4. LLM-Prompt-Struktur

**System-Prompt** (verbatim; Regel 2 und 3 seit Issue #166/#167):
```
Du bist ein Assistent für die private PDF-Sammlung des Nutzers.

REGELN:
1. Antworte NUR basierend auf den unten bereitgestellten Dokumentauszügen.
2. Schlussfolgerungen über mehrere Dokumente hinweg sind erwünscht, wenn eine
   gemeinsame Kennung (Vertragsnummer, Zählernummer, Kundennummer,
   Rechnungsnummer, IBAN, Adresse) die Verbindung belegt. Auch Dateiname und
   Ablageort eines Dokuments sind Belege. Nenne dann die Kette, z.B.
   "[1] nennt die Vertragsnummer X; [2] ordnet X der Abnahmestelle Y zu".
3. Wenn die Auszüge die Frage NICHT beantworten, sage wörtlich:
   "Ich finde dazu keine passenden Dokumente in deiner Sammlung."
   und nenne, was in den Auszügen am ehesten dazu passt. Fordere den Nutzer
   nicht auf, selbst zu suchen.
4. Erfinde KEINE Quellen, Zahlen, Daten oder Fakten, die nicht in den Auszügen stehen.
5. Zitiere jede konkrete Aussage mit [1], [2], ... (Index auf die bereitgestellten Dokumente).
6. Am Ende der Antwort: "Quellen:" gefolgt von der nummerierten Liste.
7. Antworte in der Sprache der Frage.
```

**Context-Block**:
```
=== DOKUMENTE ===

[D1] dateiname=2024-01-15_Telekom_Rechnung.pdf
     kategorie=Telekommunikation | steuerjahr=2024 | betrag=49.95 EUR
     korrespondent=Telekom Deutschland GmbH
--- text ---
<reduzierter extracted_text, max 2000 Zeichen>

[D2] dateiname=2023-12-01_Telekom_Rechnung.pdf
     ...
--- text ---
...

=== ENDE DOKUMENTE ===
```

**Anti-Halluzination – vier Maßnahmen**:
1. System-Prompt-Regel 1+3
2. Strukturierter Kontext mit klar abgegrenzten Dokumenten
3. CitationParser-Whitelist
4. „keine passenden Dokumente"-Antwort

## 5. Konversationshistorie

**In-Memory pro `RAGController`-Instanz (Session-scoped)**.

- `ChatSession` = Liste von `ChatTurn(role, content, citations, timestamp)`
- **N = 4 letzte Turns** (= 2 Frage-Antwort-Paare)
- **Token-Budget-Management**: Bei Überlauf älteste Turns droppen

## 6. Quellenangaben (Citations)

**`[N]`-Tag-Format + Whitelist-Validierung**.

**Format**:
- LLM-Body: Inline-Marker `[1]`, `[2]`, …
- LLM-Footer: `Quellen:` + nummerierte Liste

**Klickbarkeit im UI**:
- `ChatView` rendert Antwort in `QTextEdit` (read-only)
- `[N]` → `CitationLabel(QPushButton)` mit Text „Quelle N öffnen"
- Klick → `QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))`
  *(Stand 11/2026: mit bekannter Seite öffnet die PDF direkt auf der Fundstelle)*

**Validierung (Halluzinations-Schutz)**:
- Jeder zitierte Dateiname gegen `set(retrieved_docs.filename)` prüfen
- Bei Mismatch: stillschweigend entfernen
- Wenn alle Quellen invalide → Warn-Icon in GUI

## 7. Offline-Fallback

**Graceful Degradation in 3 Stufen, niemals Crash**.

1. **Detection**: `is_available()` einmalig cachen
2. **UI-Hinweis**: Statusbar + dezenter Banner
3. **Antwort-Verhalten**: Top-8 FTS5-Treffer als klickbare Liste

## 8. GUI-Integration

**QTabWidget im Center-Bereich, Tab „Chat" neben „Vorschau"**.

**Layout des Chat-Tabs**:
```
┌─ Chat-Tab ─────────────────────────────────────────────┐
│  [Banner: "Kein LLM verfügbar" – nur bei Bedarf]       │
│ ┌─────────────────────────────────┬──────────────────┐ │
│ │  Message-History (QScrollArea)  │ Quellen-Panel    │ │
│ │   • User-Bubble (rechts, blau)  │ (collapsible,    │ │
│ │   • Assistant-Bubble (links)    │  QListWidget)    │ │
│ │       mit [1][3] Citations     │  • D1: datei.pdf │ │
│ │   • Lade-Spinner (während Call) │  • D2: datei.pdf │ │
│ │                                 │  • D3: datei.pdf │ │
│ ├─────────────────────────────────┴──────────────────┤ │
│ │  [Multiline QTextEdit]              [Senden] [✕]   │ │
│ │  Status: "Suche läuft…" → "LLM antwortet…" → idle  │ │
│ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**UI-Freeze-Prävention** (Pflicht):
- `ChatWorker(QObject)` mit Signal/Slot-Pattern
- `worker.moveToThread(QThread)`
- Cancel: `threading.Event` zwischen Stages
- Während Call: Input disabled, „Abbrechen"-Button, Spinner

## 9. Performance & Skalierung

**Latenz-Budget**:
- FTS5 + Snippet-Slice: <200ms
- LLM-Keyword-Extraktion: ~1–3s
- LLM-Antwort: 5–30s
- **Gesamt: 5–35s, Ziel-p50 8s**

**Caching**: Q&A-LRU-Cache, Session-scoped, 100 Einträge.
- Key: `hash(question_normalized + tuple(retrieved_doc_paths_sorted) + chat_session_id)`

**Skalierung auf 10.000 PDFs**: FTS5 bleibt <100ms.

## 10. Konkrete Datei-Änderungen

### Neue Dateien (~1140 LOC)

| Pfad | Inhalt | ~LOC |
|---|---|---|
| `src/rag/__init__.py` | Package-Init | 10 |
| `src/rag/retrieval.py` | `RetrievalService`, `RetrievedDoc`, Query-Building | 150 |
| `src/rag/rag_controller.py` | `RAGController`, `RAGResponse`, Prompts, Cache | 180 |
| `src/rag/chat_session.py` | `ChatSession`, `ChatTurn` | 60 |
| `src/rag/citation.py` | `CitationParser`, Whitelist | 50 |
| `src/rag/prompts.py` | `SYSTEM_PROMPT`, Builder | 40 |
| `src/gui/chat_view.py` | `ChatView`, Bubbles, Citation-Labels | 280 |
| `src/gui/chat_worker.py` | `ChatWorker`, Signals | 70 |
| `tests/test_retrieval.py` | Query-Building, Stopwords | 120 |
| `tests/test_citation_parser.py` | Halluzinations-Check | 80 |
| `tests/test_rag_controller.py` | End-to-End Mock | 100 |

### Geänderte Dateien (~280 LOC)

| Pfad | Änderung | LOC |
|---|---|---|
| `src/ml/llm_provider.py` | `answer_with_context()` abstrakt + `LLMConfig.context_window` | +30 |
| `src/ml/ollama_provider.py` | `answer_with_context()` | +30 |
| `src/ml/claude_provider.py` | `answer_with_context()` | +25 |
| `src/ml/openai_provider.py` | `answer_with_context()` | +25 |
| `src/ml/poe_provider.py` | `answer_with_context()` | +25 |
| `src/gui/main_window.py` | `QTabWidget` + Chat-Tab verdrahten | +60 |
| `src/utils/config.py` | `ChatConfig` | +40 |
| `src/utils/database.py` | Optional: `save_chat_turn()` für Persistenz | +60 |

## 11. Risiken & offene Fragen

### Risiken (alle mitigiert)

| # | Risiko | Mitigation |
|---|---|---|
| R1 | Kleine Ollama-Modelle ignorieren Citation-Format | Explizites Beispiel im System-Prompt |
| R2 | Halluzination konkreter Zahlen | Whitelist + User-Hinweis |
| R3 | PyQt6-Threading-Bugs | QObject-move-to-thread Pattern strikt |
| R4 | Cloud-Provider leaken Snippets | Privacy-Hinweis, Snippet-Größe klein |
| R5 | FTS5 OR-Query zu permissiv | Top-K=8 cap, AND-Fallback |
| R6 | OCR-Qualität schlecht | Out-of-scope v1, Issue für v0.13 *(11/2026: OCR aller Seiten mit Tesseract `deu+eng`, 300 dpi, im Index)* |
| R7 | Token-Limit-Überschreitung Ollama 8B | `snippet_max_chars=2000` × 8 = 4000 worst case |
| R8 | `extracted_text` wächst unkontrolliert | 5.000-Zeichen-Cap beim Insert (siehe Q3) *(11/2026: Volltext je Seite in `suche.db`, Cap nur noch beim Prompt)* |

### Offene Fragen (alle entschieden)

- **Q1** ✅ In-Memory default, SQLite optional
- **Q3** ✅ 5.000-Zeichen-Cap beim Bulk-Index *(überholt 11/2026: der Index hält den vollen Text, gekappt wird nur der Kontext für die KI)*
- **Q5** ✅ Read-only v1
- Q2, Q4, Q6–Q8 → Defaults von Opus übernommen, später entscheidbar

## Empfohlene Reihenfolge (Milestones)

1. **M1 – Foundation** (1–2 Tage): `answer_with_context()` in 4 Providern, `RAGController` + `RetrievalService` + Prompts
2. **M2 – GUI** (1–2 Tage): `ChatView`, `ChatWorker`, `QTabWidget`-Integration
3. **M3 – Hardening** (1 Tag): `CitationParser` + Halluzinations-Whitelist, Offline-Fallback, Cancel
4. **M4 – Tests + Polish** (1 Tag): Unit-Tests, manuelle QA, README/CHANGELOG

**Gesamt: 4–6 Tage, Ziel-Release v0.12.0**

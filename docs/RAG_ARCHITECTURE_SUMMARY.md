# RAG-Chat Architektur (Opus 4.8)

> **Generiert via OpenRouter** (Opus 4.8, reasoning effort=high) — 11.500 Output-Tokens
> **Datum:** 14.06.2026
> **Feature:** Phase 19 / Issue #20
> **Ziel-Release:** v0.12.0

## Genehmigte Designentscheidungen (User bestätigt)

- **Q1:** Chat-Historie In-Memory default, SQLite-Persistenz nur als opt-in Toggle
- **Q3:** `extracted_text` auf 5.000 Zeichen pro Row truncaten beim Bulk-Index
- **Q5:** Read-only Chat v1 (LLM darf keine Aktionen auslösen)

## Vollständiges Architektur-Dokument

Siehe [ARCHITECTURE.md](ARCHITECTURE.md) für die komplette Opus-4.8-Ausarbeitung (alle 11 Abschnitte: Überblick, Chunking, Retrieval, Prompt-Struktur, History, Citations, Offline-Fallback, GUI, Performance, Datei-Änderungen, Risiken).

## Kurzfassung der Implementierungs-Reihenfolge

| Milestone | Inhalt | Dauer | Status |
|:--|:--|:--|:--:|
| **M1** | `answer_with_context()` in 4 Providern + `RetrievalService` + `RAGController` + Prompts | 1–2 Tage | 🔄 next |
| **M2** | `ChatView` + `ChatWorker` + `QTabWidget`-Integration + klickbare Citations | 1–2 Tage | 📋 |
| **M3** | `CitationParser` + Whitelist + Offline-Fallback + Cancel-Button | 1 Tag | 📋 |
| **M4** | Unit-Tests + manuelle QA aller 4 Provider + README/CHANGELOG | 1 Tag | 📋 |

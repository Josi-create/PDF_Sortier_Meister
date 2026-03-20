# PDF Sortier Meister vs. paperless-ngx

## Grundkonzept

| | **PDF Sortier Meister** | **paperless-ngx** |
|---|---|---|
| **Typ** | Desktop-App (Windows) | Web-App (Self-hosted Server) |
| **Zielgruppe** | Einzelperson, Heimanwender | Heimserver, kleine Teams |
| **Betrieb** | Lokal, keine Installation nötig | Docker/Server, immer laufend |
| **Datenhaltung** | Dateien bleiben im eigenen Ordner | Zentrales Archiv (eigene Struktur) |

---

## Feature-Vergleich

| Feature | PDF Sortier Meister | paperless-ngx |
|---|---|---|
| **Ordnerstruktur frei wählbar** | Ja — volle Kontrolle | Nein — eigenes Archiv-Schema |
| **Dateinamen selbst bestimmen** | Ja — mit KI-Vorschlägen | Begrenzt (Namensregeln) |
| **KI-Klassifikation** | Hybrid TF-IDF + LLM | Regelbasiert + optionale LLM-Addons |
| **LLM-Integration** | Claude, OpenAI, Poe, (Ollama geplant) | Über paperless-ai Addon (Ollama, OpenAI) |
| **OCR** | Tesseract (Fallback) | Tesseract (immer, für alle Dokumente) |
| **Volltext-Suche** | Geplant (Phase 17) | Ja, ausgereift |
| **Web-Interface** | Nein | Ja — auch mobil erreichbar |
| **Mehrbenutzer** | Nein | Ja (Benutzer, Gruppen, Berechtigungen) |
| **Tags / Labels** | Kategorien (10 Typen) | Flexibles Tag-System |
| **Korrespondenten** | Geplant (Phase 20) | Ja, vollständig |
| **Metadaten in PDF** | Geplant (Phase 16) | Nein (nur interne DB) |
| **Drag & Drop Sortierung** | Ja | Nein |
| **Lernfähig aus Entscheidungen** | Ja (TF-IDF lernt) | Nein |
| **PDF Merge/Split** | Geplant | Nein |
| **Automatisierungsregeln** | Geplant (Phase 21) | Ja, ausgereift (Workflows) |
| **RAG-Chat** | Geplant (Phase 19) | Über paperless-ai Addon |
| **Portabilität der Metadaten** | Ja (XMP in PDF, Phase 16) | Nein (DB-gebunden) |

---

## Wann welches Programm?

**PDF Sortier Meister** ist besser wenn:
- Man Dokumente im eigenen Ordnersystem behalten will (kein Lock-in)
- Man aktiv mit PDFs arbeitet und sie manuell/halb-automatisch sortiert
- Kein Server betrieben werden soll (reines Desktop-Tool)
- Die Metadaten portabel in den Dateien selbst stecken sollen (Phase 16)

**paperless-ngx** ist besser wenn:
- Ein dauerhaft laufendes Archiv gewünscht ist (Posteingang → automatisch archiviert)
- Volltext-Suche und ausgefeilte Filter sofort gebraucht werden
- Mehrere Personen oder Geräte auf die Dokumente zugreifen sollen
- Man kein Problem mit dem eigenen Archivschema von paperless hat

---

## Fazit

Die Programme schließen sich nicht aus — PDF Sortier Meister kann als Frontend zum manuellen Sortieren/Umbenennen dienen, bevor Dokumente in paperless-ngx importiert werden. Mit Phase 16 (XMP-Metadaten in PDF) würden Tags und Kategorien beim Import automatisch übernommen.

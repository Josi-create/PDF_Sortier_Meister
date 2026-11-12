# Übersetzung der Oberfläche

Die Texte stehen auf Deutsch im Code und laufen durch `tr(...)` aus `src/i18n`.
Die Übersetzungen liegen in `locale/<kürzel>.po` (gettext-Format). Mit Sprache
Deutsch gibt `tr` den Text unverändert zurück.

## Einen Text hinzufügen

```python
from src.i18n import tr

label.setText(tr("Zielordner"))
status.showMessage(tr("{anzahl} Dateien verschoben").format(anzahl=n))
```

- Immer ein Zeichenkettenliteral übergeben, keine f-Strings und keine Variablen
  (sonst findet die Prüfung den Text nicht).
- Platzhalter mit Namen (`{anzahl}`), damit die Übersetzung die Wortstellung
  ändern kann.
- Danach `python tools/i18n_werkzeug.py offen` (zeigt Texte ohne Übersetzung) und
  die Übersetzung in `locale/en.po` eintragen. Der Test
  `tests/test_i18n.py` schlägt fehl, solange ein markierter Text keinen
  englischen Eintrag hat.
- Gleicher deutscher Text, verschiedene Übersetzungen: `tr("Datei", "Menü")`
  (wird in der .po-Datei zu `msgctxt`).

## Eine Sprache hinzufügen

`locale/en.po` nach `locale/<kürzel>.po` kopieren, im Kopf `Language` und
`X-Language-Name` anpassen, die `msgstr`-Zeilen übersetzen. Die Sprache
erscheint dann in Einstellungen → Allgemein → Sprache. Sonst ist nichts zu tun;
die Datei wird über `pdf_sortier_meister.spec` mit ausgeliefert.

## Programmname

Der Name steht je Sprache an einer Stelle: im Eintrag
`msgid "PDF Sortier Meister"` der .po-Datei. `tr` setzt dessen Übersetzung in
allen Texten dieser Sprache ein.

## Was nicht übersetzt wird

- Texte, die an die KI gehen (Prompts), und was die KI zurückgibt (Dateinamen,
  Kategorien, Zusammenfassungen)
- Protokollzeilen (Log)
- Werte, die gespeichert werden (Kategorien, Namen von Mustern)

## Begriffsliste Deutsch → Englisch

| Deutsch | Englisch |
|---|---|
| Scan-Ordner | scan folder |
| Zielordner | target folder |
| Unterordner | subfolder |
| Ablage, ablegen | filing, file |
| Verschieben | move |
| Umbenennen | rename |
| Vorschlag | suggestion |
| Korrespondent | correspondent |
| Kategorie | category |
| Steuerjahr | tax year |
| Betrag (netto / brutto) | amount (net / gross) |
| MwSt. | VAT |
| Zusammenfassung | summary |
| Kachel | tile |
| Favorit | favorite |
| Vorschau | preview |
| Einstellungen | Settings |
| Einrichtungs-Assistent | setup wizard |
| KI, KI-Assistent | AI, AI assistant |
| KI-Anbieter | AI provider |
| Modell | model |
| Einwilligung | consent |
| Texterkennung (OCR) | text recognition (OCR) |
| Textebene | text layer |
| Gerade ausrichten | straighten |
| Entzerren (Foto) | correct perspective |
| Trennen (PDF) | split |
| Zusammenfügen | merge |
| Stapel | batch |
| Dateinamen-Muster | file name pattern |
| Platzhalter | placeholder |
| Papierkorb | Recycle Bin |
| Rückgängig | Undo |
| Sicherung, Backup | backup |
| Wiederherstellen | restore |
| Dokumentensuche | document search |
| Suchindex, Indexierung | search index, indexing |
| Hintergrunddienst | background service |
| Treffer | result |
| Schnellfrage | quick question |
| Gelernt | learned |
| Sie | you |

Schreibweise: Satzanfang groß, sonst klein („Move to target folder“, nicht
„Move To Target Folder“); Menüeinträge mit `…` behalten die drei Punkte;
Tastenkürzel (`&`) und Platzhalter (`{name}`) bleiben erhalten.

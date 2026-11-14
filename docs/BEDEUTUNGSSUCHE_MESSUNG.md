# Bedeutungssuche: Probelauf vor dem Bau (Issue #230)

Stand: 13.11.2026. Der Probelauf war die Bedingung für die Umsetzung: gebaut
wird nur, wenn die Bedeutungssuche im Chat wirklich etwas bringt.

## Ergebnis in Kürze

50 Fragen in Alltagssprache an ein Archiv aus 3.110 erfundenen Dokumenten
(3.665 Seiten). Gezählt wurde, bei wie vielen Fragen das richtige Dokument
gefunden bzw. vom Chat als Beleg genannt wurde.

| Verfahren | richtig bei … von 50 Fragen |
|---|---|
| Chat wie bisher (Wortsuche, das Modell sucht selbst weiter), gpt-oss:20b | 22 |
| Chat mit Bedeutungssuche (der Programmcode dieses Standes), gpt-oss:20b | 41 |
| Chat wie bisher, gemma4:12b | 18 |
| Chat mit Bedeutungssuche, gemma4:12b | 43 |

Nur die Suche, ohne Sprachmodell (richtiges Dokument unter den ersten 8 Treffern,
das ist die Zahl der Dokumente, die der Chat vorab bekommt):

| Verfahren | 110 Dokumente | 3.110 Dokumente |
|---|---|---|
| Wortsuche des Chats (`RetrievalService.retrieve`) | 28 von 50 | 17 von 50 |
| Bedeutungssuche, Modell `embeddinggemma` | 49 von 50 | 48 von 50 |
| Bedeutungssuche, Modell `bge-m3` | 48 von 50 | 41 von 50 |
| Bedeutungssuche, Modell `qwen3-embedding:0.6b` | 38 von 50 | nicht gemessen |

Auf Platz 1 stand das richtige Dokument im großen Archiv bei der Wortsuche
8-mal, bei `embeddinggemma` 45-mal.

## Aufbau

- **Dokumente:** 110 erfundene Schreiben einer Familie (Versicherungen, Energie,
  Miete, Steuer, Bank, Gesundheit, Auto, Arbeit, Schule, Käufe, Urkunden), je
  150 bis 500 Wörter, ein bis drei Seiten, in der Sprache des jeweiligen
  Absenders. Geschrieben von zwei KI-Agenten, die nur die Liste der
  Dokumentarten kannten, nicht die Fragen.
- **Fülldokumente:** 3.000 aus Bausteinen erzeugte Kontoauszüge, Bestellungen,
  Kundeninformationen, Rundschreiben und einige Werbebriefe. Sie enthalten
  viele Alltagswörter (Strom, Miete, Versicherung), beantworten aber keine Frage.
- **Fragen:** 50, so wie man sie im Chat stellt („Was zahle ich im Jahr für
  meine Autoversicherung?“, „Wann muss das Auto wieder zum TÜV?“). Geschrieben
  vor dem Lesen der Dokumente, nur anhand der Liste der Dokumentarten. Je Frage
  stand vorher fest, welche Dokumente sie beantworten.
- **Index:** der echte Suchindex des Programms (`src/search/db.py`), neutrale
  Dateinamen, keine Metadaten.
- **Chat:** die echte Werkzeug-Schleife (`RAGController.ask`) mit lokalen
  Modellen über Ollama, jede Frage in einem frischen Gespräch. „Richtig“ heißt:
  Die Antwort zitiert eines der Zieldokumente oder nennt es beim Dateinamen.
- **Rechner:** Ryzen 7 5800X3D, RTX 5080 (16 GB), Ollama 0.40.15.

## Was auffiel

- Die Wortsuche scheitert genau an den Fragen, um die es im Issue geht: In
  keinem der 110 Dokumente steht „Autoversicherung“ (dort heißt es
  „Kraftfahrtversicherung“), „Müllabfuhr“ („Abfallgebühren“) oder
  „Elektrofahrrad“ („Pedelec“).
- Das Weitersuchen des Modells gleicht das nur zum Teil aus. gpt-oss:20b suchte
  im Schnitt 1,3-mal selbst und antwortete bei 10 von 50 Fragen „Ich finde dazu
  keine passenden Dokumente“, gemma4:12b suchte fast nie selbst und sagte das
  bei 20 Fragen. Mit Bedeutungssuche kam das noch bei höchstens einer Frage
  vor, und die Antworten kamen schneller (gpt-oss:20b: 9 statt 12 Sekunden je
  Frage), weil das Modell seltener nachsuchen musste.
- Im großen Archiv verdrängen Fülldokumente die richtigen Treffer der Wortsuche
  (ODER-Abfrage mit häufigen Wörtern, bei gleicher Relevanz das neuere zuerst).
- Treffer der beiden Suchen nach Rang zu mischen (Reciprocal Rank Fusion) war
  schlechter als die Bedeutungssuche allein (42 statt 48 von 50). Deshalb stehen
  im Chat bis zu vier Bedeutungstreffer vorn, die übrigen Plätze behält die
  Wortsuche.
- Kürzen der Vektoren von 768 auf 256 Werte und Runden auf ganze Bytes kostete
  keinen Treffer unter den ersten 8 (Platz 1: 44 statt 45). 128 Werte waren
  merklich schlechter. Gespeichert werden deshalb 256 Bytes je Seite.
- Völlig fremde Fragen („Wie backe ich einen Apfelkuchen?“) erreichen
  Ähnlichkeiten um 0,2; die richtigen Dokumente lagen bei 0,29 und mehr, in der
  Mitte bei 0,55. Unter 0,30 gilt eine Seite deshalb nicht als Treffer. Fragen
  nach etwas, das es im Archiv nur so ähnlich gibt („Was kostet mein Segelboot
  im Hafen?“), kommen aber auf bis zu 0,43: Die Schwelle hält nur groben Unsinn
  fern, den Rest muss das Sprachmodell beim Lesen erkennen.

## Kosten

| | gemessen |
|---|---|
| Speicher in `suche.db` | 0,6 KB je Seite, also rund 60 MB je 100.000 Seiten (im Issue geschätzt: 400 MB) |
| Berechnen mit Grafikkarte | 26 ganze Briefseiten je Sekunde, rund 1 Stunde je 100.000 Seiten |
| Berechnen ohne Grafikkarte (8 Kerne) | 1,6 Seiten je Sekunde, rund 17 Stunden je 100.000 Seiten |
| Suche je Frage (3.665 Seiten, Modell geladen) | 0,05 Sekunden einschließlich Umrechnen der Frage |
| Modell `embeddinggemma` | 620 MB auf der Platte, rund 700 MB im Speicher der Grafikkarte |

Die Zeiten entstanden, während auf demselben Rechner andere Arbeiten liefen;
sie sind Größenordnungen.

## Grenzen dieser Messung

- Erfundene Dokumente, keine echten. Echte Schreiben enthalten Markennamen
  („TÜV“), die hier fehlen, weil alle Absender erfunden sind. Das benachteiligt
  die Wortsuche.
- Die Dokumente hatten weder sprechende Dateinamen noch Metadaten. Von PDF
  Sortier Meister einsortierte PDFs tragen Korrespondent, Kategorie,
  Zusammenfassung und Schlagwörter, die die Wortsuche mit durchsucht. Für sie
  ist der Abstand in Wirklichkeit kleiner; für den übrigen Bestand der
  Dokumentensuche (ganze Laufwerke, Mails) gilt er eher so wie gemessen.
- Sauberer Text. Fehler der Texterkennung in Scans wurden nicht nachgestellt.
- Je Einstellung ein Durchlauf. Antworten von Sprachmodellen schwanken; einzelne
  Fragen fallen bei einer Wiederholung anders aus, der Abstand ist aber groß.
- „Richtig“ wurde am genannten Dokument gemessen. Ob jede Zahl in der Antwort
  stimmt, wurde nur stichprobenweise nachgelesen.
- Nicht gemessen: Mails, lange Dokumente (von sehr langen Seiten gehen nur die
  ersten 6.000 Zeichen in die Berechnung ein), fremdsprachige Texte, Archive
  über 4.000 Seiten.

## Nebenbefunde (nicht Teil dieser Änderung)

- Die Wortsuche des Chats leitet aus Wörtern wie „Vermieter“, „Finanzamt“ oder
  „GEZ“ einen Korrespondenten-Filter ab. Dokumente ohne Metadaten fallen dann
  alle heraus; drei der 50 Fragen hatten deshalb vorab null Treffer.
- gpt-oss:20b gibt nach ein bis zwei eigenen Suchen auf. Ein Hinweis im Prompt,
  es mit Fachbegriffen und Wortanfängen zu versuchen, wäre ein eigener Versuch.

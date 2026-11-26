# Suche, Mails und Chat

## Dokumentensuche einschalten

Die Volltextsuche ist anfangs aus. Einschalten im Einrichtungs-Assistenten oder unter
**Einstellungen › Suche**. Dort wählst du die Ordner und Laufwerke aus, die durchsucht werden.
**Extras › Ordner zum Suchindex hinzufügen…** nimmt weitere Ordner auf.

Durchsucht werden:

- PDFs, auch gescannte: Die Texterkennung liest im Hintergrund alle Seiten. Jede Seite wird nur
  einmal erkannt, auch wenn die Datei später verschoben oder umbenannt wird.
- Word, Excel und OpenDocument (`doc`, `docx`, `xls`, `xlsx`, `odt`) und Markdown.
- **Mails:** Thunderbird, auf dem Mac auch Apple Mail, dazu gespeicherte `.eml`- und
  `.msg`-Dateien (z. B. aus Outlook).

Der Index wird **einmal täglich im Hintergrund** aufgefrischt, sobald der Rechner nicht benutzt
wird. War der Rechner zur eingestellten Zeit aus, holt PDFSM den Lauf später im Leerlauf nach.
„Jetzt indizieren“ liest neue Dateien sofort ein.

## Der Reiter „Suche“

`Strg+Umschalt+F` öffnet den Reiter **„Suche“** in der Mitte. Die Treffer zeigen die Fundstelle
hervorgehoben und mit Seite; die Vorschau springt auf die Trefferseite. Filter gibt es nach Typ,
Ordner, Zeitraum und den PDFSM-Metadaten (Steuerjahr, Kategorie, Korrespondent, Betrag). Die
Auswahl „Sortierung“ ordnet nach Relevanz, Datum oder dem Datum im Dateinamen.

Suchsyntax:

| Eingabe | findet |
|---|---|
| `Rechnung Stadtwerke` | alle Wörter |
| `"genaue Wortfolge"` | genau diese Wortfolge |
| `Rechnung*` | Wörter, die so beginnen |
| `Strom ODER Gas` | eines der Wörter |
| `Rechnung NICHT Mahnung` | das erste ohne das zweite |

Umlaute sind dabei egal.

`Strg+F` (**Ansicht › Dokumentensuche…**) sucht in den Metadaten der sortierten PDFs.

## Chat über die eigenen Dokumente

Mit eingerichteter KI gibt es links den Reiter **„Chat“**. Frag in normalen Worten, z. B. „Was
habe ich 2025 für Strom gezahlt?“. Der Chat sucht im selben Index, zitiert mit Seitenangabe, und
die Quellen sind anklickbar.

- Die gewählte PDF ist der Bezug: Vertrags-, Zähler- und Kundennummern daraus holen verknüpfte
  Unterlagen (Abrechnung, Vertrag, Mails) dazu.
- Belegt eine Antwort einen Zielordner, verschiebt „Nach … verschieben“ die PDF mit einem Klick.
- Modelle mit Werkzeugaufrufen suchen und lesen selbst in der Sammlung und zeigen ihre
  Arbeitsschritte.
- Für den Chat lässt sich ein anderes Modell wählen als für die Sortierung.

## Browser-Oberfläche

Auf Wunsch gibt es dieselbe Suche im Browser unter `http://localhost:18425`. Sie ist nur auf
diesem Rechner erreichbar und startet auf Wunsch bei der Anmeldung.

## KI-Assistenten (MCP)

Programme wie Claude Code, Claude Desktop oder Hermes Agent können den Suchindex direkt
durchsuchen. Eingerichtet wird das unter **Einstellungen › Suche › KI-Assistenten (MCP)**: Dort
steht je Assistent, ob er installiert und eingerichtet ist, mit einem Knopf zum Einrichten.
Danach den Assistenten neu starten. Alle Werkzeuge lesen nur; keines verschiebt oder ändert
etwas.

Weiter: [KI-Anbieter](06-ki.md)

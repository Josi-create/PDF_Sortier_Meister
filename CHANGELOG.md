# Changelog

Alle nennenswerten Aenderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Geändert
- **Doppelklick im Zielordner-Baum klappt den Ordner rechts auf bzw. zu**,
  statt ihn links als Scan-Ordner zu öffnen. Das funktioniert jetzt auch bei
  tief verschachtelten Ordnern, deren Unterordner erst beim Aufklappen
  nachgeladen werden (typisch für große OneDrive-Bäume) – dort hat der
  Doppelklick bisher nichts aufgeklappt. Ordner ohne bekannte Unterordner
  werden frisch gelesen, sodass auch inzwischen angelegte oder synchronisierte
  Unterordner erscheinen; hat ein Ordner keine, sagt das die Statusleiste.
  Links öffnen geht weiter per Rechtsklick › „Ordner links öffnen“.

### Behoben
- **Angehakte Checkboxen zeigen wieder ein Häkchen.** Sie waren nur blau
  gefüllt und wurden leicht als „aus“ gelesen – z. B. „Ordnerstruktur im
  Namen“, wodurch beim Verschieben unerwartet die Initialen vor dem
  Dateinamen standen.
- **Einstellungen › Dateinamen › „Beim Verschieben in einen Ordner“ klarer
  beschriftet:** statt „Dateinamen beibehalten“ heißt es jetzt „Nichts
  ergänzen – Name wie vorgeschlagen bzw. eingegeben“, die zweite Option „Nach
  Vorlage ergänzen (z. B. Initialen und Ordnernummer voranstellen)“. Beide
  gehen vom Namen im Feld „Neuer Dateiname“ aus (KI-Vorschlag oder eigene
  Eingabe) – der alte Text klang, als würde der KI-Vorschlag verworfen.

## [0.26.0] - 2026-11-08

### Neu
- **Word- und Excel-Dateien sortieren und in PDF umwandeln** (#9): .docx- und
  .xlsx-Dateien im Scan-Ordner erscheinen als Kacheln mit Vorschaubild
  (eingebettetes Bild, Windows-Vorschau oder die ersten Textzeilen) und zeigen
  beim Anklicken eine Seitenvorschau; Word-Sperrdateien (`~$…`) bleiben
  ausgeblendet. Sie lassen sich wie PDFs auswählen, bekommen Ordnervorschläge,
  werden per Vorschlag, Baumklick oder Drag & Drop verschoben, beim Umbenennen
  behalten sie ihre Endung, und Strg+Z macht das rückgängig. Doppelklick öffnet
  sie im Standardprogramm. Rechtsklick › „In PDF umwandeln“ bzw. „In PDF/A
  umwandeln“ (bei Mehrfachauswahl „… (N Dateien)“) legt das PDF neben das
  Original, wählt es aus und scrollt es ins Bild; schlägt eine Datei fehl,
  laufen die anderen weiter. Umgewandelt wird mit Word bzw. Excel, sonst mit
  LibreOffice; fehlt beides, sagt eine Meldung, was fehlt. Datums- und
  Zeitfelder in Word-Briefen (`PRINTDATE`, `DATE`, `TIME`) zeigen im PDF das
  letzte Druckdatum des Dokuments statt des heutigen Datums; fehlt es, wird
  ersatzweise das Änderungs- oder Erstelldatum genommen und darauf hingewiesen.
  Die Originaldatei bleibt dabei unverändert. PDF/A aus Excel gibt es nur über
  LibreOffice, sonst entsteht ein normales PDF mit Hinweis. Die Kacheln tragen
  oben links ein Etikett mit der Endung („DOCX“, „XLSX“) und werden nach der
  Erkennung hellblau statt grün. Drehen, OCR, Zusammenfügen und Stapeln bleiben
  PDFs vorbehalten.
- **OpenDocument-Text (.odt) wie .docx**: .odt-Dateien erscheinen als Kachel
  (Etikett „ODT“) mit Vorschau, fließen in die Ordner-Vorschläge ein, behalten
  beim Verschieben/Umbenennen/Hierhin-Kopieren ihre Endung und lassen sich per
  Rechtsklick (auch mehrere) in PDF bzw. PDF/A umwandeln – mit Word oder
  LibreOffice. Datumsfelder (`text:date`, `text:time`, `text:print-date`,
  `text:print-time`) werden vor dem Umwandeln auf das Druckdatum aus `meta.xml`
  festgesetzt, damit ein alter Brief nicht das heutige Datum bekommt.
- **Bilder sortieren und in PDF umwandeln** (#184): JPG, PNG, TIFF (auch
  mehrseitig), BMP, GIF, WEBP und HEIC/HEIF erscheinen wie Word-Dateien als
  Kacheln, mit Vorschaubild in der richtigen Ausrichtung (EXIF) und Vorschau in
  der Mitte, und lassen sich verschieben, kopieren und löschen. Rechtsklick ›
  „In PDF umwandeln“ erzeugt ein PDF mit Texterkennung, damit es durchsuchbar
  ist; ohne Tesseract entsteht es ohne Texterkennung, mit Hinweis in der
  Statusleiste. Bei mehreren markierten Bildern gibt es „Einzeln in PDFs
  umwandeln (N Bilder)“, je Bild ein PDF, und „Zu einem PDF zusammenfügen“ in
  der Reihenfolge der Ansicht, benannt nach dem ersten Bild. Bildkacheln tragen
  ein Etikett mit dem Format und werden nach der Erkennung rosa.
- **Fotos entzerren beim Umwandeln** (#205): Ein mit dem Handy fotografiertes
  Blatt wird beim Umwandeln in PDF gerade gezogen und zugeschnitten. Rechtsklick
  auf ein Bild › „In PDF umwandeln und automatisch entzerren“ bzw. „… und von
  Hand entzerren“, bei mehreren markierten Bildern das Untermenü „Fotos
  entzerren (N Bilder)“, je einzeln oder zu einem PDF zusammengefügt.
  Automatisch sucht PDFSM das Blatt selbst; ist die Erkennung unsicher, öffnet
  sich für diese Fotos das Fenster „Foto entzerren“, vorbelegt mit dem besten
  Versuch. Dort lassen sich die vier Ecken ziehen, rechts steht die Vorschau,
  dazu „Zurücksetzen“ und Blättern zwischen mehreren Fotos; „Abbrechen“ ändert
  nichts. Liegt das Blatt nah an A4, bekommt die Seite genau das A4-Format; ist
  es am Bildrand angeschnitten, bleibt das gemessene Format. Blattecken dürfen
  knapp außerhalb des Fotos liegen, der fehlende Zipfel wird weiß. Die Tonwerte
  (Farbe aufgehellt, Graustufen, Schwarzweiß) stehen unter Einstellungen ›
  Allgemein › „Fotos entzerren“ und lassen sich im Fenster je Auftrag ändern.
  Das PDF bekommt wie beim normalen Umwandeln eine Texterkennung.
- **Original nach dem Umwandeln oder Trennen wegräumen** (#187): Nach „In PDF
  umwandeln“ (Bilder, Word, Excel, .odt) und nach „PDF trennen...“ fragt PDFSM,
  ob das Original in den Papierkorb soll (Standard Ja, mit „Nicht mehr fragen“).
  Bei mehreren Dateien kommt die Frage einmal für alle. Weggeräumt wird nur bei
  lesbarem Ergebnis und nie endgültig: Strg+Z holt alle Originale zurück, das
  PDF bzw. die Teile bleiben. Unter Einstellungen › Allgemein › „Original nach
  dem Umwandeln und Trennen“ lässt sich je Aktion „Jedes Mal fragen“, „In den
  Papierkorb verschieben“ oder „Behalten“ wählen. Die Lücke der entfernten
  Kachel schließt sich sofort.
- **Ganze Ordner verschieben und kopieren** (#196): Ordner lassen sich wie PDFs
  einsortieren: „Versicherungen“ auf „Steuer 2025“ ergibt
  „Steuer 2025/Versicherungen“, mit allen Unterordnern und allen Dateien. Ein
  Einfachklick auf eine Ordnerzeile links markiert den Ordner (blau), ein
  zweiter hebt die Markierung auf, Doppelklick öffnet ihn wie bisher. Rechts
  erscheinen dann „Vorgeschlagene Ziele für Ordner …“; ein Klick auf einen
  Vorschlag oder einen Ordner im Zielordner-Baum verschiebt. Ziehen der
  Ordnerzeile auf den Baum verschiebt, mit Strg (macOS: Wahltaste) wird kopiert.
  Im Rechtsklickmenü der Ordnerzeile stehen „📁 Ordner verschieben nach …“ und
  „📁 Ordner kopieren nach …“ mit den Vorschlägen und „Anderen Ordner wählen …“.
  Die Vorschläge kommen aus dem Inhalt (gelernte Zuordnungen, Sortierlogik,
  gespeicherte KI-Vorschläge) und aus gleichnamigen Ordnern mit Jahresanpassung
  („Steuer 2024/Versicherungen“ → „Steuer 2025“; fehlt der Jahresordner, wird er
  nach Rückfrage angelegt). „🤖 KI fragen“ holt auf Knopfdruck einen Vorschlag
  der KI. Vor dem Ausführen nennt eine Rückfrage die Zahl der Dateien, ein
  Fortschrittsfenster mit „Abbrechen“ zeigt den Stand. Gibt es das Ziel schon,
  wird zusammengeführt: gleiche Namen bekommen „(2)“, inhaltsgleiche Dateien
  landen nicht doppelt, leere Quellordner verschwinden. Strg+Z macht Verschieben
  und Kopieren rückgängig (eine Kopie wandert in den Papierkorb). Gespeicherte
  Pfade ziehen beim Verschieben mit: Zielordner, „zuletzt verwendet“, Favoriten,
  gelernte Zuordnungen, Analyse-Zwischenspeicher und Suchindex. Jede Datei mit
  erkanntem Text zählt dabei als einzeln einsortiert.
- **Neue Ordner vorschlagen** (#116): PDFSM schlägt jetzt auch Ordner vor, die
  es noch nicht gibt. Sieht eine Rechnung mit Datum 2027 aus wie die bisherigen
  in „Steuer 2025/Medikamente“, steht vorne „➕ neu: Steuer 2027/Medikamente“ mit
  derselben Unterstruktur (Jahresregel ohne KI; das Jahr kommt aus dem
  Steuerjahr, sonst aus dem erkannten Datum). Passt kein vorhandener Ordner,
  darf auch die KI einen neuen Pfad unter einem Zielordner nennen; sie bekommt
  dafür die vorhandenen Ordner als Liste. Je Dokument gibt es höchstens einen
  solchen Vorschlag, blau gestrichelt an erster Stelle. Ein Klick fragt
  „Ordner … anlegen und Datei dorthin verschieben?“; danach läuft alles wie bei
  einem bestehenden Ordner (Namensvorlage, Lernen, Metadaten). Strg+Z verschiebt
  zurück und entfernt die dabei angelegten Ordner wieder, sofern sie leer sind.
  Ziehen auf den neuen Ordner verschiebt nicht, „hierhin kopieren“ (auch
  Strg+Ziehen) geht aber. Abschalten lässt sich das unter Einstellungen ›
  Allgemein › Darstellung › „Neue Ordner vorschlagen“ (Standard: an).
- **Favoriten-Leiste** (#114): Über der Pfadzeile der PDF-Ansicht steht eine
  Leiste mit Lieblingsordnern als graue Knöpfe. Ein Klick öffnet den Ordner
  (Zurück und Alt+Links funktionieren weiter), der geöffnete Ordner ist
  hervorgehoben, der Tooltip zeigt den vollen Pfad. Gemerkt wird per Rechtsklick
  auf eine Ordnerzeile links, einen Ordner im Zielordner-Baum oder die Pfadzeile
  („Aktuellen Ordner als Favorit merken“). Rechtsklick auf einen Favoriten:
  „Entfernen“, „Umbenennen (Anzeigename)“, „Nach links“, „Nach rechts“, „Im
  Explorer öffnen“. Viele Favoriten scrollen seitwärts, das Fenster wird nicht
  breiter. Fehlt ein Ordner, wird der Knopf grau und kursiv, und ein Klick
  bietet das Entfernen an. Beim ersten Start steht der Scan-Ordner als erster
  Favorit drin; ohne Favoriten ist die Leiste ausgeblendet.
- **Hierhin kopieren** (#179, #183): Im Rechtsklickmenü der Ordnervorschläge,
  der Ordnerzeilen links, des Zielordner-Baums und der Favoriten steht „📄 PDF
  hierhin kopieren“ (bei mehreren „📄 N Dateien hierhin kopieren“), auch für neu
  anzulegende Ordner. Mit gedrückter Strg-Taste (macOS: Wahltaste) kopiert auch
  das Ziehen auf einen Ordner, statt zu verschieben. Die Kopie bekommt Namen und
  Metadaten wie beim Verschieben und kommt in den Suchindex; das Original bleibt
  unverändert und ausgewählt und zeigt „📄 kopiert nach …“. Gelernt wird wie beim
  Verschieben, dasselbe Dokument im selben Ordner zählt je Sitzung aber nur
  einmal. Die Ordnerzeilen links haben außerdem „➡ PDF hierhin verschieben“,
  „🌳 Rechts im Baum zeigen“ und „⭐ Als Zielordner merken“ bzw. „Aus Zielliste
  entfernen“.
- **Ordnersuche** (#159): Über dem Zielordner-Baum steht ein Suchfeld. Ein
  Treffer aus der Liste klappt den Baum bis dorthin auf (auch tiefer als bisher
  eingelesen), markiert den Ordner und scrollt ihn ins Bild, ohne etwas zu
  verschieben. Links öffnet ein Klick auf die freie Fläche der Pfadzeile oder
  auf die Lupe dasselbe Suchfeld; ein Treffer öffnet den Ordner in der
  PDF-Ansicht, Esc bringt die Pfadzeile zurück. Gesucht wird nach Teilen des
  Namens ohne Rücksicht auf Groß-/Kleinschreibung, `*` und `?` sind Platzhalter.
  Die Suche läuft im Hintergrund unter Scan-Ordner und Zielordnern, bis acht
  Ebenen tief und mit höchstens 50 Treffern; versteckte und Systemordner sowie
  symbolische Links werden übersprungen.
- **Größeres Rechtsklickmenü im Zielordner-Baum** (#93): Das Menü ist neu
  gegliedert. Neu sind „📂 Unterordner öffnen“ (Untermenü), „➕ Alle Unterordner
  aufklappen“ (drei Ebenen), „➖ Unterordner zuklappen“, „➖ Alles zuklappen“ und
  „🔎 Diesen Ordner als Wurzel anzeigen“ (mit „Zurück zur Gesamtansicht“),
  „📥 Hierhin verschieben“ für die links ausgewählten PDFs (wie ein Klick auf den
  Ordner), „✏️ Ordner umbenennen“, „🗑️ Ordner löschen (in den Papierkorb)“ für
  leere Ordner und „ℹ️ Inhalt anzeigen“ (in der Statusleiste). Beim Umbenennen
  ziehen gespeicherte Zielordner, Favoriten, gelernte Zuordnungen und der
  Suchindex mit. Doppelklick bleibt wie bisher.
- **Korrespondenten neu gedacht** (#160): Der Korrespondent ist jetzt immer die
  Gegenpartei aus Sicht des Nutzers – bei fremder Post der Absender, bei eigenen
  Schreiben der Empfänger bzw. die andere Vertragspartei (Mietvertrag → Mieter,
  Arztbrief als Arzt → Patient). Nie der Nutzer selbst, nie ein Formularverlag
  wie „Haus & Grund“ oder Zweckform. Der bisherige rechte Reiter
  „Korrespondenten“ entfällt (rechts steht nur noch der Zielordner-Baum);
  stattdessen gibt es links neben „PDFs“ und „Chat“ den Reiter
  „Korrespondenten“: alle Korrespondenten aus dem Suchindex mit Anzahl und
  Suchfeld, darunter die Dokumente des gewählten (Klick zeigt sie in der
  Vorschau, Doppelklick öffnet, Rechtsklick „Im Explorer zeigen“ / „Ordner links
  öffnen“). Ein Klick auf ein Dokument füllt Detailbereich, Dateinamen- und
  Ordnervorschläge wie unter „PDFs“; Verschieben, Kopieren, Umbenennen, Lernen
  und Strg+Z funktionieren auch für Dateien außerhalb des links geöffneten
  Ordners. Mehrere Dokumente lassen sich mit Strg/Umschalt markieren und
  gemeinsam verschieben (ohne Umbenennen) oder kopieren, auch per Ziehen auf
  einen Ordner (mit Strg wird kopiert). Beim Zurückwechseln ist die Auswahl
  unter „PDFs“ wieder da. Schreibvarianten werden automatisch zusammengeführt
  (Groß/klein, Satzzeichen, Rechtsformen, ae/ä; unklare Fälle entscheidet die KI
  einmal im Hintergrund). Rechtsklick auf das Detailfeld Korrespondent springt
  zu allen Dokumenten dieses Korrespondenten. „Aufräumen…“ prüft nur auffällige
  Dokumente (leer, der Nutzer selbst, Formularverlag) erneut per KI und
  speichert wie „Metadaten speichern“. Bearbeiten-, Zusammenführen- und
  Farb-Dialog entfallen.
- **Chat in der linken Spalte, Verschieben mit einem Klick** (#166): Der Chat
  ist jetzt ein zweiter Reiter neben „PDFs“ in der linken Spalte des
  Vorschau-Reiters; Detailbereich, Vorschau und Zielordner bleiben dabei
  sichtbar. Beim Wechsel in den Chat wird die ausgewählte PDF zum Bezug.
  Belegt eine Antwort einen Zielordner (die zitierten Dokumente liegen dort),
  erscheint darunter „Nach … verschieben“: ein Klick verschiebt die PDF wie
  ein Klick auf den Zielordner, danach zeigt die linke Spalte wieder die PDFs,
  der Chat bleibt mit Verlauf im Hintergrund. Quellen stehen eingeklappt unter
  dem Verlauf, die Schnellfragen untereinander über dem Eingabefeld; bei wenig
  Höhe (kleiner Monitor) klappen sie hinter ein Dreieck, das sie jederzeit
  wieder aufklappt. Die Schnellfragen lassen sich unter Einstellungen >
  KI-Assistent > Chat ändern und ergänzen (eine je Zeile, „Standard
  wiederherstellen“); geänderte Chat-Einstellungen gelten ab der nächsten
  Frage ohne Neustart.
- **Verknüpfte Dokumente als Sortiervorschlag** (#166): Nennt ein Scan eine
  Vertrags-, Zähler-, Kunden- oder Rechnungsnummer und liegen Dokumente mit
  derselben Nummer schon in einem Zielordner, steht dieser Ordner mit 85 bis
  95 % ganz oben („Verknüpft: gleiche Vertragsnummer, Zählernummer in 3
  Dokumenten dieses Ordners“), auch ohne Chat. Ein vom Chat belegter Ordner
  wird ebenfalls als Vorschlag übernommen („Chat bestätigt“).
- **Der Chat sucht und liest selbst** (#167): Kann das Modell Werkzeuge
  aufrufen (Ollama mit gpt-oss, Qwen3, Gemma, alle OpenAI-kompatiblen Anbieter,
  Claude), bekommt es die Werkzeuge „suche“ (Volltextsuche mit Dateityp-,
  Ordner-, Zeitraum- und Metadatenfiltern), „dokument_lesen“ (Volltext,
  seitenweise, bei Excel das Tabellenblatt), „ordner_vorschlag“ (Sortierlogik
  und ähnliche, bereits einsortierte Dokumente) und „korrespondent_info“
  (Aliase, Notizen, MwSt, absetzbar). Es darf bis zu acht Schritte lang
  suchen und lesen, bevor es antwortet; die Statuszeile zeigt jeden Schritt,
  „Abbrechen“ greift zwischen den Schritten. Im letzten Schritt wird das
  Modell ausdrücklich zur Antwort aufgefordert; bleibt sie aus, zeigt der Chat
  den Zwischenstand der Werkzeuge statt einer Fehlermeldung. Im Chat erscheinen die
  Arbeitsschritte („🔎 Suche „226541“: 3 Treffer“) ein- und ausklappbar vor
  der Antwort, das Quellen-Panel unterscheidet zitierte, gelesene und
  gefundene Dokumente. Modelle ohne Werkzeuge antworten wie bisher; in den
  Einstellungen lässt sich das Verhalten abschalten und die Zahl der Schritte
  wählen.
- **SQL-Abfragen im Chat als Option** (#167): „SQL-Abfragen auf der
  Suchdatenbank erlauben“ gibt dem Modell das Werkzeug „sql_abfrage“ für Summen,
  Zählungen und Listen über viele Dokumente. Die Verbindung ist nur lesend
  (`mode=ro`, `query_only`), es ist genau eine SELECT-/WITH-Anweisung erlaubt,
  Zeitlimit 15 Sekunden, höchstens 200 Zeilen. Standard ist aus; empfohlen für
  große Modelle, die SQLite-Fehlermeldungen selbst korrigieren.
- **Eigenes Modell für den Chat** (#167): Unter Einstellungen > KI-Assistent
  lässt sich für den Chat ein anderer Anbieter und ein anderes Modell wählen
  als für die Sortierung, etwa ein kleines lokales Modell zum Sortieren und
  ein großes Modell (Ollama Cloud, OpenRouter, Claude) zum Fragen. Die
  Einwilligung für Cloud-Anbieter gilt auch hier. Die Statusleiste zeigt
  „Chat: Anbieter/Modell“, wenn es abweicht.
- **Schwer lesbare Scans** (#47): Ist der Text eines Scans schlecht erkannt
  (weniger als 60 % der Zeichen sicher gelesen), trägt die Kachel oben rechts
  ein orangefarbenes Warndreieck. Im Rechtsklickmenü gibt es „OCR wiederholen
  mit …“ mit den installierten Tesseract-Sprachen und Kombinationen wie
  Deutsch + Englisch; fehlt Fraktur, steht dort ein Installationshinweis. Ein
  besseres Ergebnis ersetzt den Text in Analyse und Suchindex, ein schlechteres
  wird verworfen, gemeldet wird beides; die Textebene in der PDF bleibt
  unverändert. „Handschrift mit KI entziffern (Bilderkennung)“ schickt bis zu
  zehn Seiten als Bild an das eingestellte Modell, sofern es Bilder versteht
  (Claude, OpenAI, OpenRouter, Strata, Ollama); sonst erklärt ein Hinweis, wo
  man ein passendes Modell einstellt. Bei Cloud-Anbietern wird vorher gefragt.
  Das Ergebnis lässt sich kopieren oder mit „Als Text übernehmen“ speichern;
  danach analysiert PDFSM das PDF neu und erzeugt die KI-Metadaten aus dem
  entzifferten Text.
- **LM Studio als lokaler KI-Anbieter** (#45): Wer LM Studio bereits nutzt,
  kann es in den Einstellungen als Anbieter „LM Studio“ wählen. Ein API-Key ist
  nicht nötig, die Server-URL ist einstellbar (Standard
  `http://localhost:1234/v1`). Läuft LM Studio, erkennt die App das sofort und
  zeigt die verfügbaren Modelle zur Auswahl (Embedding-Modelle ausgenommen);
  sonst erscheint der Hinweis, LM Studio zu starten und den lokalen Server zu
  aktivieren. Im Einrichtungsassistenten wird LM Studio nur angeboten, wenn es
  gerade läuft; die Empfehlung bleibt Ollama. Die App bietet LM Studio nie zum
  Download an. LM Studio lässt sich auch als eigenes Chat-Modell wählen.
- **Sortierung der Kacheln** (#33): Über den Kacheln steht neben „Ansicht:“ das
  Auswahlfeld „Sortieren:“ mit Datum (neueste/älteste zuerst), Name (A–Z/Z–A)
  und Größe (größte/kleinste zuerst). Namen werden natürlich sortiert („Scan 2“
  vor „Scan 10“). Umschalten ordnet nur um, ohne neue Analyse; Auswahl und
  Mehrfachauswahl bleiben, die Wahl bleibt nach einem Neustart erhalten.
  Standard ist wie bisher Datum, neueste zuerst.
- **Suche: „Im Ordner anzeigen“**: Rechtsklick auf einen Treffer (PDF oder
  sortierbare Office-Datei) im Reiter „Suche“ › „📂 Im Ordner anzeigen“ öffnet
  dessen Ordner unter „PDFs“, wechselt auf „Vorschau“ und wählt die Datei aus.
  Von dort lässt sie sich umbenennen und verschieben.
- **Alle markieren (Strg+A)**: Bearbeiten › „Alle markieren“ markiert in der
  Kachelansicht „PDFs“ alle Kacheln, sobald der Fokus dort liegt (ein Klick auf
  eine Kachel oder die Fläche genügt); in Textfeldern markiert Strg+A wie
  gewohnt den Text. Die aktive PDF bleibt aktiv.
- **Regenbogenrahmen am besten Vorschlag** (#32): Ist der beste Ordnervorschlag
  zu mindestens 85 % sicher, läuft ein farbiger Rahmen um ihn. Nur der erste
  solche Vorschlag bekommt ihn, nie ein neu anzulegender Ordner; Klickverhalten
  und grüne Hervorhebung bleiben.
- **Backup-Erinnerung** (#14): Alle 7 Tage (einstellbar unter Einstellungen ›
  Allgemein › „Backup-Erinnerung“, 0 = aus) fragt PDFSM „Haben Sie in den
  letzten 7 Tagen ein Backup gemacht?“. Bei „Nein“ steht dezent „Kein aktuelles
  Backup gemacht“ in der Statusleiste, auch nach einem Neustart; ein Klick
  darauf bestätigt das Backup. Ist das neueste Protokoll von Macrium Reflect
  jünger als der eingestellte Abstand, entfällt die Frage. Beim Start erscheint
  höchstens ein Hinweisfenster, das erste fällige aus Erste Schritte,
  Backup-Hinweis, Backup-Frage und Unterstützen.
- **Unterstützen** (#115): Hilfe › „Unterstützen ...“ öffnet einen Dialog mit
  freiwilligen Beträgen in Stufen (z. B. „Ein Kaffee – 3 €“); jeder Knopf führt
  zur Zahlungsseite, der Betrag wird dort eingegeben. Ausdrücklich ohne
  Gegenleistung und ohne Freischaltung von Funktionen. Nach „Ich habe gerade
  unterstützt“ pausiert der Hinweis je nach Betrag, ab 49 € für immer, und der
  Über-Dialog zeigt „Unterstützer seit …“. Von selbst erscheint der Hinweis erst
  ab 50 sortierten Dokumenten und dann höchstens alle 30 Tage; unter
  Einstellungen › Allgemein › „Unterstützen“ lässt er sich abschalten.

### Behoben
- **Stapeln rückgängig machen** (#189): Lag das Dokument auf einem anderen
  Laufwerk als der Programmordner (`%APPDATA%`), scheiterte „Rückgängig“ mit
  „[WinError 17] Das System kann die Datei nicht auf ein anderes Laufwerk
  verschieben“. Die Sicherung wird jetzt über Laufwerksgrenzen kopiert und
  erst nach dem Einsetzen gelöscht; bei einem Fehler bleibt sie erhalten und
  der Eintrag in „Rückgängig“ bestehen.
- **Stapeln wie bei Papier** (#190): Die gezogene PDF wird Seite 1, die
  darunterliegende folgt (bisher umgekehrt). Mehrere gezogene PDFs kommen in
  ihrer Reihenfolge alle davor. Namen und Ablageort behält die Ziel-PDF.
- **Mehrere PDFs auf einen Ordner ziehen**: Zog man mehrere markierte PDFs auf
  einen Ordner, wurden sie verschoben, aber für jede weitere Datei kam
  zusätzlich ein Fehlerdialog „Quelldatei nicht gefunden“.
- **Mittlere Spalte ließ sich nicht vergrößern** (#188): Die Trennstriche
  zwischen den drei Spalten des Hauptfensters standen am Anschlag, weil
  Beschriftungen, Auswahlfelder und Vorschläge zusammen über 2400 Pixel
  Mindestbreite verlangten. Jetzt haben die Spalten feste Mindestbreiten, die
  Trennstriche lassen sich stufenlos ziehen (auch über Remote Desktop), und
  keine Spalte klappt dabei ganz zu.
- **Kategorie ist genau ein Wert**: Die KI schrieb gelegentlich die
  Auswahlliste aus dem Prompt ab („Rechnung/Vertrag/Steuer/…“), ältere PDFs
  trugen „{'Sonstiges'}“. Solche Werte landen nicht mehr in PDF, Suchindex,
  Dateinamen und gelernten Korrespondenten-Daten; schon gespeicherte heilen
  beim nächsten Lernen. Der Prompt verlangt ausdrücklich genau eine Kategorie.
- **Verschieben auf einen Pfad mit altem Eintrag**: „UNIQUE constraint failed:
  pdfs.file_path“ brach das Umtragen ab – dabei bekam auch der Suchindex das
  Verschieben nicht mit. Der veraltete Eintrag am Ziel wird jetzt entfernt.
- **Word/Excel ohne PDF-Metadaten-Versuch**: Für .docx/.xlsx (und Bilder) wird
  nicht mehr versucht, PDF-Metadaten zu lesen oder zu schreiben (Meldung
  „unable to find trailer dictionary“). Nach dem Schreiben in eine PDF geht die
  Meldung an den Suchindex vor der Konsolenausgabe raus.

### Verbessert
- **Ordnervorschläge als kompakte Zeilen**: Die Vorschläge rechts stehen nicht
  mehr als Kacheln, sondern als schmale Zeilen in ein bis drei Spalten je nach
  Breite: oben grau der Anfang des Pfads mit Laufwerk, unten das Ende mit dem
  Zielordner fett, rechts die Prozentzahl. Ist der Pfad zu lang, fallen links
  ganze Ordner weg; der Tooltip zeigt den vollen Pfad und ist nicht mehr
  schwarz. Sortiert wird nach Konfidenz (ein neu anzulegender Ordner steht
  vorn), bisher stand der KI- oder Verknüpfungsordner immer oben. Der Ordner, in
  dem die PDF schon liegt, wird nicht mehr vorgeschlagen.
- **Löschen in den Papierkorb** (#124): „Löschen“ verschiebt Dateien jetzt in
  den Papierkorb des Systems, statt sie endgültig zu löschen, und Strg+Z holt
  sie zurück, mit klarer Meldung, wenn die Datei nicht mehr im Papierkorb liegt
  oder der Platz belegt ist. Ist kein Papierkorb verfügbar, fragt PDFSM
  ausdrücklich, ob endgültig gelöscht werden soll. Das gilt auch für Word-,
  Excel- und Bilddateien.
- **Zeitraum frei eintippen** (#161): Statt Kalenderfeldern mit Häkchen für
  „von“ und „bis“ gibt es in der Filterleiste („Filter ▼“) und im Reiter „Suche“
  ein Feld „Zeitraum“: `2024`, `12/2024`, `Jan 2024`, `Q2 2024`, `3.5.2024`,
  Bereiche wie `2004-2006`, `12/2023-3/2024` oder `2004 bis 2006` und offene
  Angaben wie `ab 2020` oder `bis 12/2023`. Darunter steht grau, wie die Eingabe
  verstanden wird; Unlesbares bekommt einen roten Rand und löst keine Suche aus.
  Das Datumsfeld in der Detailansicht nimmt „3.5.24“, „03.05.2024“,
  „3. Mai 2024“ oder „2024-05-03“ und schreibt daraus beim Verlassen JJJJ-MM-TT.
- **Chat-Antworten formatiert** (#199): Antworten im Chat erscheinen mit Fett-
  und Kursivschrift, Listen, Überschriften, Code in Festbreitenschrift und
  Tabellen statt mit Markdown-Zeichen. Die Quellenverweise wie `[1]` bleiben
  klickbar, auch in Listen und Fettdruck. HTML aus der Antwort erscheint als
  Text, andere Links sind nicht anklickbar.
- **Chat findet verknüpfte Dokumente über Kennungen** (#166, #167): Mit
  Bezugsdokument zieht der Chat Vertrags-, Kunden-, Zähler- und
  Rechnungsnummern, IBANs und ähnliche Codes aus dem Text und sucht damit
  exakt im Index. Die Verbrauchsabrechnung mit derselben Vertragsnummer steht
  so als Erstes im Kontext, markiert mit der gemeinsamen Kennung, und die KI
  darf die Kette („gleiche Vertragsnummer, Abnahmestelle X“) ausdrücklich
  ziehen. Fragewörter („bitte“, „zeig mir“, „Dokument“, „Ordner“) verwässern
  die Suche nicht mehr; nennt die Frage „Excel“, „Tabelle“ oder „Mail“, kommt
  eine zweite Suche nur in diesem Dateityp dazu. Kopien derselben Datei
  (OneDrive, Archiv) zählen einmal, bei nahezu gleicher Relevanz stehen
  neuere Dokumente vorn. Der Auszug eines Treffers besteht jetzt aus den
  Fundstellen und der Trefferseite statt aus Anfang und Ende des Dokuments.
- **Chat fordert nicht mehr zum Selbst-Suchen auf** (#167): Der Systemprompt
  verlangt statt „schlage vor, wonach der Nutzer suchen könnte“ jetzt, das
  Nächstliegende aus den Auszügen zu nennen. Ein Bezugsdokument im
  Scan-Eingang wird als „noch unsortiert“ gekennzeichnet, damit die KI den
  Eingang nicht als Ablageort vorschlägt.

### Entfernt
- **Automatisierungs-Regeln** (#125): Der Reiter „Automatisierungs-Regeln“ in
  den Einstellungen, der Regel-Editor und der Statusleisten-Hinweis nach dem
  Verschieben sind weg. Die Regeln griffen in der Praxis nie, weil sie erst
  nach dem Verschieben geprüft wurden und nur einen Hinweis zeigten. Bereits
  gespeicherte Regeln bleiben unberührt in der Datenbank, bestehende
  Datenbanken öffnen weiter ohne Migration.

## [0.25.0] - 2026-11-07

### Neu
- **Rechtsklick: „Pfad kopieren“ und „Im Explorer anzeigen“** (#154): Die
  PDF-Kacheln haben unter „PDF öffnen“ zwei neue Einträge: „Im Explorer
  anzeigen“ öffnet den Ordner und markiert die Datei, „Pfad kopieren“ legt den
  vollständigen Pfad in die Zwischenablage. Die Ordner im linken Fenster
  (auch „..“) bekommen dafür erstmals ein Kontextmenü mit „Im Explorer
  öffnen“ und „Pfad kopieren“; der Zielordner-Baum und die grünen
  Vorschlagskacheln haben „Pfad kopieren“ zusätzlich. Unter macOS heißen die
  Einträge „Im Finder zeigen“ bzw. „Im Finder öffnen“.
- **PDF drehen und Texterkennung neu** (#150): Im Rechtsklickmenü einer
  PDF-Kachel gibt es „Drehen“ mit „90° nach links“, „90° nach rechts“ und
  „180°“ sowie „OCR neu durchführen“. Bei Mehrfachauswahl gilt beides für alle
  markierten PDFs. Gedreht wird die ganze PDF verlustfrei über die
  Seitendrehung: Scanbild, Textebene und gespeicherte Metadaten bleiben
  unverändert, „Rückgängig“ (Strg+Z) dreht zurück. Kachel, Vorschau und
  Suchindex zeigen sofort den neuen Stand. Digital signierte und
  verschlüsselte PDFs werden nicht gedreht (die Signatur würde ungültig bzw.
  der Schutz ginge verloren); kurz gesperrte Dateien (OneDrive, Vorschau)
  werden mehrmals versucht. „OCR neu durchführen“ erkennt die gescannten
  Seiten im Hintergrund noch einmal – am Zwischenspeicher der Texterkennung
  vorbei, dessen Einträge dabei ersetzt werden. Nach dem Drehen ist das in der
  Regel nicht nötig: Die Drehung gehört jetzt zum Erkennungsmerkmal einer
  Seite, die nächste Analyse liest gedrehte Seiten deshalb von selbst neu,
  statt den alten, falsch ausgerichteten Text wiederzuverwenden.
- **Chat mit Bezugsdokument** (#148, #27): Wer im Reiter „Vorschau“ ein PDF
  auswählt und in den „Chat“ wechselt, kann direkt Fragen zu diesem PDF
  stellen. Über dem Eingabefeld steht dann „Bezug: <Dateiname>  ✕“, darunter
  vier Schnellfragen, die mit einem Klick gestellt werden: „Zu welcher
  Wohnung / welchem Objekt gehört dieses Dokument?“, „Zeig mir ähnliche
  Rechnungen“, „Gibt es schon einen Ordner mit ähnlichen Dokumenten?“ und „In
  welchen Ordner gehört dieses PDF?“. Die KI bekommt das PDF als erstes
  Dokument (Text und Metadaten aus dem Suchindex, sonst aus der laufenden
  Analyse) und dazu Dokumente aus der Sammlung, die zu Korrespondent,
  Kategorie und Steuerjahr passen, jeweils mit ihrem Ablageort. Bei Fragen
  nach dem Ordner steht der Vorschlag der Sortierlogik mit im Kontext. Der
  Bezug gilt für alle weiteren Fragen, bis ✕ ihn entfernt oder beim nächsten
  Wechsel in den Chat ein anderes PDF ausgewählt ist. Ohne KI zeigt der Chat
  wie bisher die gefundenen Dokumente, bei der Ordnerfrage zusätzlich den
  Vorschlag der Sortierlogik.
- **Schief gescannte Seiten gerade ausrichten** (#165): Zieht der Scanner ein
  Blatt schief ein, misst PDFSM den Winkel und dreht den Seiteninhalt gerade.
  Neue Scans im ersten Vorrang-Ordner werden beim nächsten Indexlauf von selbst
  ausgerichtet, auch wenn das Scanprogramm schon eine Textebene geschrieben hat
  (Einstellungen › Suche › „Schief gescannte Seiten gerade ausrichten“: nur
  neue Scans, aus oder alle neu eingelesenen). Einzelne PDFs per Rechtsklick ›
  Drehen › „Gerade ausrichten“, auch für mehrere markierte PDFs, rückgängig mit
  Strg+Z. Das Scanbild wird nicht neu berechnet oder komprimiert, eine
  vorhandene Textebene dreht mit. Wie bei der Textebene entsteht beim
  automatischen Ausrichten vorher eine Sicherungskopie, und die Änderung steht
  im Protokoll. Drehen, Textebene und Ausrichten entstehen in einem Schritt.
  Ersetzt den Umweg über `ocrmypdf --deskew` in WSL. Das Ergebnis ist ein
  normales PDF, kein PDF/A.
- **Gedrehte Scans richtig herum** (#151): Liest die Texterkennung eine
  Seite nicht, weil sie auf dem Kopf steht oder quer liegt, versucht sie die
  drei anderen Lagen und nimmt die beste. Die Suche findet den Text dann auch
  in falsch herum eingelegten Scans. So herum wird die PDF beim nächsten
  Indexlauf gespeichert, standardmäßig nur für neue Scans im ersten
  Vorrang-Ordner (Einstellungen › Suche › „Gedrehte Seiten richtig herum
  speichern“: nur neue Scans, aus oder alle). Das gilt auch, wenn der Scan bis
  dahin schon einsortiert ist. Geändert wird nur die Drehangabe der Seite, das
  Scanbild bleibt unverändert. Wie bei der Textebene entsteht vorher eine
  Sicherungskopie, die Änderung steht im Protokoll („Geänderte PDFs anzeigen /
  rückgängig machen…“, Spalte „Gedreht“) und lässt sich zurücknehmen. Mit
  Textebene entstehen Drehung und Textebene in einem Schritt. Bleibt eine Datei
  ungedreht, liegt die Textebene trotzdem passend auf dem Scan. Signierte,
  verschlüsselte, PDF/A- und geöffnete Dateien bleiben unberührt. Eine
  aufrechte Seite kostet keinen zusätzlichen Erkennungslauf, eine falsch
  liegende drei.

### Geaendert
- **Kompakteres Detail-Panel: Vorschläge einklappbar** (#146): Die
  Vorschlagsliste steht nicht mehr als eigener Block über dem Namen, sondern
  eingeklappt in der Gruppe „Neuer Dateiname“. Rechts in deren Kopfzeile
  zeigt ein Pfeil „Vorschläge (n)“, wie viele Vorschläge es gibt; ein Klick
  klappt darunter den Schalter „Ordnerstruktur im Namen“, „Muster
  bearbeiten…“ und die Liste auf. Eingeklappt (Standard) bleiben nur
  Namensfeld, Vorschau und Warnung stehen, und die Vorschau der PDF bekommt
  den Platz. Der oberste Vorschlag wird wie bisher automatisch als Dateiname
  eingetragen. Der gewählte Zustand gilt für alle folgenden Dokumente und
  bleibt nach einem Neustart erhalten; treffen KI-Vorschläge im Hintergrund
  ein, zählt der Pfeil mit, ohne aufzuklappen.
- **Ordner im linken Fenster als Zeilen** (#147): Unterordner und „..“
  stehen nicht mehr als große Kacheln zwischen den PDFs, sondern als schmale
  Zeilen darüber – Symbol, Name und rechts in Grau die Anzahl PDFs, z. B.
  „📁 Archiv … 365 PDFs“. Ab knapp 500 Pixel Breite stehen sie in zwei
  Spalten, sonst in einer. Lange Namen werden gekürzt, der volle Pfad steht im
  Tooltip. Höhe und Schrift der Zeilen sind fest; die Kachelgröße
  (Klein/Mittel/Groß) gilt nur noch für die PDFs. Klick auf „..“, Doppelklick
  auf einen Ordner, Ablegen von PDFs per Drag & Drop und das Kontextmenü
  funktionieren wie bisher.

### Behoben
- **Tiefe Zielordner liessen sich nicht aufklappen**: Der Zielordner-Baum
  liest nur drei Ebenen unter jedem Zielordner ein. Ordner auf der dritten
  Ebene zeigten deshalb keinen Pfeil, auch wenn sie Unterordner hatten.
  Jetzt bekommen sie den Pfeil, und die Unterordner werden beim ersten
  Aufklappen nachgeladen, samt PDF-Zaehler. Das gilt auch, wenn eine PDF beim
  Ziehen ueber dem Ordner verweilt.
- **macOS (Intel): Release-Build gescheitert**: Für Intel-Macs gibt es von
  `cryptography` ab Version 49 und von `pikepdf` ab 10.14 keine fertigen
  Pakete mehr. Beim Bau aus dem Quellcode passten die mitgelieferte und die
  benötigte OpenSSL-Bibliothek nicht zusammen, und `pdfsm-dienst` brach beim
  Start der KI-Anbindung (MCP) ab. Deshalb ist v0.24.0 nicht erschienen. Auf
  Intel-Macs bleiben beide Pakete jetzt bei der letzten Version mit fertigem
  Paket. Der Dienst-Rauchtest findet die Programme auch unter macOS.

## [0.24.0] - 2026-11-06

> Nicht veröffentlicht: Der Release-Build scheiterte auf macOS (Intel). Alle
> Änderungen dieser Version sind mit v0.25.0 erschienen.

### Neu
- **Dokumentensuche, Grundstein** (Integration von PDFsuche, Phase 1): Neues,
  Qt-freies Modul `src/search` mit lokalem Volltextindex (SQLite FTS5) ueber
  PDFs mit OCR, Office-Dateien (docx, xlsx, odt, doc, xls), Markdown und Mails
  (Thunderbird-mbox, .eml, .msg), uebernommen aus dem bisher eigenstaendigen
  Programm PDFsuche und mit 77 Tests abgesichert. Noch ohne Oberflaeche und
  ohne Einrichtung: Kommandozeile `python -m src.search.dienst` (Befehle
  `index`, `suche`, `lesen`, `status`, `web`, `mcp`). Entwurf und Plan:
  `docs/SUCHE_ARCHITEKTUR.md`.
- **Dokumentensuche, bekannte Schwaechen behoben** (Phase 1b): `.msg`-Dateien
  werden am Inhalt erkannt - Outlook-Container ueber extract-msg, als Text
  gespeicherte Mails wie `.eml`, alles andere (z. B. Tcl-Nachrichtenkataloge,
  die ebenfalls `.msg` heissen) gilt als leer statt als Lesefehler; leere
  Dateien jeder Art ebenso. Fehlertexte sind kurz, einzeilig und ohne
  Dateipfad. Thunderbird-Postfaecher sichern beim Lesen alle 30 s einen
  Zwischenstand (bis wohin lueckenlos gelesen); ein abgebrochener Lauf setzt
  dort fort, statt das Postfach von vorn zu lesen. Excel-Datumswerte in xlsx
  erscheinen als `TT.MM.JJJJ[ HH:MM]` statt als Seriennummer (Zellformate aus
  `styles.xml`: eingebaute und eigene Datumsformate, 1904-Datumssystem). Nach
  einem vollstaendigen Lauf verschwinden Eintraege, die ausserhalb aller
  konfigurierten Ordner liegen (bisher blieben sie fuer immer stehen).
- **Dokumentensuche, Plattformschicht** (Phase 2): Alles
  Betriebssystem-abhaengige liegt jetzt in `src/search/plattform.py`, damit
  die Suche unter Windows und macOS gleich laeuft - Dateisperre gegen
  Doppellaeufe, Arbeitsprozesse enden mit dem Dienst (Windows-Job-Objekt bzw.
  Prozessgruppe mit Elternwaechter), Hintergrundprioritaet fuer CPU und
  Festplatte, Erkennung nur in der Cloud liegender Dateien (OneDrive-
  Platzhalter, iCloud-Drive-Platzhalter `.Name.pdf.icloud`,
  File-Provider-Flag), Junctions und Symlinks werden uebersprungen. Neu:
  `pdfsm-dienst index --nur-leerlauf` pausiert den Lauf, solange der Nutzer
  aktiv ist (fuer den macOS-Zeitplan; unter Windows erledigt das die
  Aufgabenplanung); das Thunderbird-Profil wird ueber `profiles.ini` gefunden
  und ist der Standard fuer die Postfaecher; der Einrichtungsassistent bekommt
  Vorschlaege fuer Wurzeln (Laufwerke bzw. Benutzerordner und `/Volumes`);
  fehlen Tesseract oder die Sprachdaten `deu+eng`, bleibt die Texterkennung
  aus und der Status nennt den Grund.
- **Dokumentensuche einrichten** (Phase 3): Neue Registerkarte **Suche** in
  den Einstellungen mit allen Optionen - Ordner und Laufwerke (mit
  Vorschlaegen), Vorrang-Ordner, Ausschluesse, Dateiendungen, Mails
  (Thunderbird-Profil wird erkannt), Texterkennung (Sprachen, Seitengrenze,
  Tesseract-Status), Cloud-Dateien, Hintergrundindexierung mit Uhrzeit,
  Browser-Oberflaeche mit Port, Arbeitsprozesse, Speicherort der Datenbank
  und die Stufen fuer die Textebene in gescannten PDFs (aus / nur neue Scans /
  alle, mit Aufbewahrung der Sicherungskopien). Der Einrichtungs-Assistent
  bekommt die Seite „Dokumentensuche“: Sie fragt, ob und welche Ordner
  durchsucht werden (vorbelegt sind Scan- und Zielordner), ob Mails und
  Texterkennung dazukommen und ob taeglich im Hintergrund indiziert wird -
  ohne Zustimmung wird nichts indiziert, alles bleibt auf dem Rechner. Wer
  das fruehere Programm PDFsuche benutzt hat, uebernimmt dessen Einstellungen
  und Datenbank per Dialog oder `pdfsm-dienst migration`: PDFSM findet die
  Installation ueber die Aufgabenplanung bzw. den MCP-Eintrag, prueft die
  Datenbank am Ort (kein laufender Index, Integritaet, Zaehler) und laesst
  sie dort liegen; auf Wunsch wird sie geprueft in das Datenverzeichnis
  kopiert.
- **Reiter „Suche“ im Hauptfenster** (Phase 4): Neben „Vorschau“ und „Chat“
  gibt es den Reiter **Suche** (auch Ansicht > Volltextsuche, Strg+Umschalt+F)
  fuer die Volltextsuche in PDFs (auch gescannten), Office-Dateien, Markdown
  und Mails. Suchfeld mit Hilfe zur Syntax (Wortfolgen, ODER/NICHT, Wortanfang,
  Naehe), Filter fuer Typ, Ordner, Zeitraum und Sortierung, Trefferliste mit
  hervorgehobenen Fundstellen und Seiten- bzw. Blattangabe, weitere Treffer auf
  Knopfdruck. Ein Klick zeigt die PDF rechts in der Vorschau direkt auf der
  Trefferseite (der Link „S. 3“ springt weiter), Office-Dateien, Markdown und
  Mails erscheinen als Text mit Hervorhebung. Aktionen je Treffer: Oeffnen (PDFs
  wie in den Einstellungen gewaehlt), im Explorer bzw. Finder zeigen, Pfad
  kopieren, Mails mit dem Mailprogramm oeffnen oder als `.eml` speichern.
  Unten steht der Indexstand (Dokumente je Typ, OCR-Rueckstand, laufender
  Lauf) mit „Jetzt indizieren“ fuer die Vorrang-Ordner und „Kompletten Lauf
  starten“. Alle Abfragen laufen im Hintergrund, die Oberflaeche bleibt
  bedienbar; solange die Suche nicht eingerichtet ist, fuehrt ein Hinweis zu
  Einstellungen > Suche.
- **Eine Such-Datenbank** (Phase 5): Volltext und die PDFSM-Metadaten
  (Korrespondent, Kategorie, Steuerjahr, Betrag, Buchungsdatum,
  Zusammenfassung, Schlagwoerter) liegen jetzt gemeinsam im Suchindex. Beim
  ersten Start wird die bisherige Suchtabelle einmalig uebernommen; die
  Metadaten jeder sortierten PDF liest der Index ausserdem aus der Datei
  selbst (Info-Dict und XMP), so dass auch auf anderen Rechnern sortierte
  PDFs ihre Werte mitbringen. Werte, die PDF Sortier Meister gesetzt hat,
  haben Vorrang. Der Reiter **Suche** bekommt dafuer Filter fuer Steuerjahr,
  Kategorie, Korrespondent und Betrag (auch ohne Suchbegriff), die
  Werkzeugleisten-Suche (Strg+F) samt Filterleiste zeigt ihre Treffer dort,
  und Chat-Zitate oeffnen die PDF direkt auf der Seite der Fundstelle.
  Umbenennen, Verschieben, Loeschen, Kopieren, Stapeln, Teilen und
  Zusammenfuegen melden sich sofort beim Index (im Hintergrund), der
  Dokumenten-Chat sucht im neuen Index (auch Mails und Office-Dateien).
- **Nie doppelt OCR**: Die PDF-Analyse holt ihren Text aus dem Suchindex,
  wenn er aktuell ist, und nutzt sonst dieselbe Texterkennung wie der Index
  (Tesseract, deu+eng, 300 dpi, hoechstens fuenf Bildseiten interaktiv);
  was sie erkennt, geht an den Index zurueck. Ein OCR-Cache nach Bildinhalt
  sorgt dafuer, dass erkannter Text Umbenennen, Verschieben, das Schreiben
  von Metadaten in die PDF, Stapeln, Teilen und Kopieren ueberlebt; fuer den
  Altbestand wird der Cache beim naechsten vollstaendigen Lauf nachgefuellt.
  Die Datenbank wird beim ersten Zugriff in-place auf Schema-Version 2
  erweitert (keine OCR geht verloren). `pdfsm-dienst suche` und das
  MCP-Werkzeug `suche` kennen die Filter `steuerjahr`, `kategorie` und
  `korrespondent`.
- **Textebene in gescannten PDFs** (Phase 5b, standardmaessig aus): Auf
  Wunsch legt PDF Sortier Meister den erkannten Text als unsichtbare Ebene in
  die PDF. Dann finden ihn auch die Explorer-Suche, Acrobat und PaperPort, und
  man kann ihn markieren. Das Scanbild bleibt byte-genau erhalten, die Datei
  waechst um rund 3 KB je Seite. Einstellbar unter Einstellungen > Suche:
  nur neue Scans aus dem Scan-Eingang oder auch der Altbestand. Fuer den
  Altbestand zeigt PDF Sortier Meister vorher eine Schaetzung von Dauer,
  OneDrive-Upload und Platz der Sicherungskopien. Geschrieben wird beim
  naechsten Indexlauf, auch wenn die Datei inzwischen einsortiert ist. Vor
  jeder Aenderung entsteht eine Sicherungskopie (Standard 30 Tage), die neue
  Fassung wird vor dem Ersetzen geprueft. Signierte, verschluesselte und
  PDF/A-Dateien, schreibgeschuetzte, geoeffnete und nur in der Cloud liegende
  Dateien bleiben unberuehrt. Ein Protokoll zeigt alle geaenderten PDFs und
  nimmt einzelne Aenderungen zurueck. Ein laufender Indexlauf laesst sich im
  Reiter **Suche** anhalten. Auf der Kommandozeile gibt es
  `pdfsm-dienst textebene` (schaetzen, protokoll, rueckgaengig, schreiben).
- **Dokumentensuche im Hintergrund** (Phase 6): PDF Sortier Meister bringt
  den Hintergrunddienst `pdfsm-dienst` mit, unter Windows zusaetzlich
  `pdfsm-dienstw` ohne Konsolenfenster. Ist unter Einstellungen > Suche die
  taegliche Indexierung eingeschaltet, richtet PDF Sortier Meister beim
  Speichern eine Aufgabe in der Windows-Aufgabenplanung ein, ohne
  Administratorrechte. Sie startet erst, wenn der Rechner zehn Minuten nicht
  benutzt wurde, und haelt an, sobald jemand weiterarbeitet. Unter macOS
  uebernimmt das ein LaunchAgent. Die Browser-Oberflaeche der Suche laesst
  sich bei der Anmeldung starten oder im Reiter **Suche** mit „Im Browser
  öffnen“. KI-Assistenten wie Claude erreichen den Index ueber
  `pdfsm-dienst mcp`, mit denselben Werkzeugnamen wie bisher. Beim
  Deinstallieren werden die Aufgaben entfernt; Einstellungen und Index
  bleiben erhalten.
- **KI kennt die Ablageorte aehnlicher Dokumente**: Beim Beurteilen eines
  neuen Scans bekommt die KI aus der Datenbank (Sortierhistorie und
  Suchindex) bis zu fuenf aehnliche, bereits einsortierte Dokumente mit
  Ordner und Jahr. Sie nennt daraufhin einen Zielordner, der als
  Ordnervorschlag „KI: aehnliche Dokumente liegen dort“ ganz oben erscheint
  bzw. einen vorhandenen Vorschlag bestaetigt. Jahres-Regel: Eine Rechnung,
  die fast genauso aussieht wie eine in „Steuer 2024“, gehoert trotzdem in
  den Ordner fuer ihr eigenes Jahr. Der Prompt sagt das ausdruecklich und
  nennt die passende Jahres-Variante („Steuer 2026/…“), und uebernimmt die KI
  doch das Beispieljahr, korrigiert PDFSM den Ordner auf das Dokumentjahr.
- **Strata als lokaler KI-Anbieter**: In den Einstellungen gibt es den
  Anbieter „Strata“ fuer einen lokalen Modell-Server mit OpenAI-kompatibler
  Schnittstelle (Standard `http://127.0.0.1:8080/v1`, Angabe ohne `/v1`
  geht auch). Strata braucht einen eigenen API-Key, schickt aber nichts ins
  Internet und zaehlt deshalb nicht als Cloud-Anbieter. Ohne Modellangabe
  nimmt PDFSM das Modell, das der Server gerade geladen hat; „Modelle
  aktualisieren“ und „Verbindung testen“ funktionieren. Die Server-URL wird
  jetzt pro Anbieter gemerkt, Ollama- und Strata-URL ueberschreiben sich
  nicht mehr.
- **PDFs stapeln wie in PaperPort**: Eine PDF (oder eine Mehrfachauswahl)
  auf eine andere PDF ziehen haengt ihre Seiten hinten an. Die Ziel-Kachel
  leuchtet beim Darueberziehen orange gestrichelt auf; die Ziel-PDF behaelt
  Namen und Metadaten, die gezogenen PDFs aus demselben Ordner gehen im
  Stapel auf. PDFs aus anderen Ordnern (z. B. aus dem Explorer gezogen)
  werden nur gelesen und bleiben, wo sie sind. Keine Rueckfrage - `Ctrl+Z`
  macht das Stapeln rueckgaengig; die Originale liegen dafuer 30 Tage unter
  `%APPDATA%\PDF_Sortier_Meister\stapel_sicherung`.
- **Ordnerbaum beim Ziehen**: Wer eine PDF an den oberen oder unteren Rand
  des Zielordner-Baums zieht, laesst den Baum jetzt automatisch scrollen
  (bisher blieb er stehen, Ordner ausserhalb des sichtbaren Bereichs waren
  per Drag & Drop unerreichbar). Verweilt die PDF kurz ueber einem
  zugeklappten Ordner, klappt er auf.
- **Feld „Datum“ im Detail-Panel** (#132): Das Dokumentdatum steht jetzt als
  eigenes Metadaten-Feld (JJJJ-MM-TT) neben dem Steuerjahr und wird in die
  PDF geschrieben (`Buchungsdatum`). Es ist die eine Quelle fuer `{datum}` in
  den Dateinamen-Mustern und belegt das Steuerjahr vor - solange das
  Steuerjahr nicht bewusst anders gesetzt wurde, folgt es dem Datum. Eingabe
  auch als „12.3.2004“ oder „12. Maerz 2004“ (wird beim Verlassen des Felds
  normalisiert); Unlesbares wird rot markiert und nicht gespeichert. In der
  Vorschau: Datum markieren, Rechtsklick, „Als Datum uebernehmen“ - kann die
  Texterkennung auch die Markierung nicht lesen, steht der Text rot im Feld
  und wird durch die eigene Eingabe ersetzt. Bereits sortierte PDFs mit
  Metadaten, aber ohne Datum, zeigen das Feld leer (kein „teilweise
  gespeichert“ nur wegen des Analyse-Datums).
- **Kleinere Kacheln im Scan-Bereich** (#117, Probelauf): Ueber der
  PDF-Liste links steht jetzt „Ansicht: Klein / Mittel / Gross“, wie die
  Symbolgroesse im Explorer. Standard ist „Klein“: Kachel etwa halb so breit
  wie bisher, das Bild fuellt die Kachelbreite und zeigt den Kopf der Seite
  (unten abgeschnitten) statt einer winzigen Gesamtseite; „Mittel“ zeigt die
  ganze Seite verkleinert, „Gross“ entspricht der bisherigen Darstellung.
  Bei kleinen und mittleren Kacheln blendet der Mauszeiger auf
  einer PDF nach kurzem Verweilen die grosse Vorschau neben der Kachel ein;
  Ordner-Kacheln haben keine Vorschau. Die Wahl wird gespeichert
  (`tile_view`). Das Thumbnail wird weiterhin in 140x160 gerendert und
  gecacht, kleinere Ansichten skalieren nur herunter. Die wirkungslose
  Einstellung „Thumbnail-Groesse“ unter Allgemein entfaellt; dort steht ein
  Hinweis auf die neue Auswahl.
- **Kategorie sofort im Dateinamen** (#113): Wer im Detail-Panel eine
  Kategorie, einen Korrespondenten oder ein anderes Metadaten-Feld
  eintraegt, sieht den Dateinamen-Vorschlag sofort nachziehen: Die
  Vorschlagsliste rendert mit den neuen Werten, und solange der Dateiname
  aus der Liste stammt (oberste Zeile, angeklickte Zeile, KI-Ergebnis),
  folgt er der Eingabe. Ein selbst getippter Name bleibt unangetastet. In
  KI-Vorschlaegen werden „Sonstiges“/„Unbekannt“ und die alte Kategorie
  bzw. der alte Korrespondent durch die Eingabe ersetzt.
- **KI-Prompt:** Neue Regel gegen nichtssagende Dateinamen („Sonstiges“,
  „Unbekannt“, „Dokument“, „Scan“); passt keine Standard-Kategorie, soll
  die KI konkret benennen, worum es geht.

### Geaendert
- **Textebene für neue Scans ist Standard**: Gescannte PDFs ohne Text im
  Scan-Eingang bekommen den erkannten Text als unsichtbare Ebene, mit
  Sicherungskopie und Protokoll. Abschalten lässt sich das im Assistenten
  (Häkchen) und unter Einstellungen > Suche > Textebene („Aus“).
- **Neue Abhaengigkeit PyQt6-Pdf:** Seit PyQt6 6.12 (Oktober 2026) liegen
  die Module `QtPdf` und `QtPdfWidgets` der integrierten PDF-Vorschau im
  eigenen Paket `PyQt6-Pdf`. `requirements.txt` und `pyproject.toml`
  verlangen jetzt `PyQt6>=6.12` und `PyQt6-Pdf>=6.140`; bei einer
  bestehenden Installation einmal `pip install -r requirements.txt`
  ausfuehren. War vorher PyQt6 < 6.12 installiert, danach zusaetzlich
  `pip install --force-reinstall --no-deps PyQt6-Pdf PyQt6-Pdf-Qt6`: pip
  loescht beim Entfernen der alten Version die Dateien, die `PyQt6-Pdf`
  gerade installiert hat, und die App startet dann mit `ModuleNotFoundError:
  No module named 'PyQt6.QtPdf'`. Der Programmstart nennt in diesem Fall
  jetzt genau diese Befehle. Ohne das Paket startet die Vorschau nicht, und
  die Tests auf GitHub Actions schlugen seit dem 5. November 2026 beim
  Einsammeln fehl.
- **Ollama-Fehler nennen den Grund:** Antwortet Ollama mit einem
  HTTP-Fehler, steht im Log und in Fehlermeldungen jetzt der Text aus der
  Antwort, z. B. `Ollama HTTP 500: llama runner process has terminated:
  exit status 0xc0000409` (Modell beim Laden abgestuerzt) statt nur
  `Ollama HTTP 500`. Gilt fuer KI-Anfragen und den Modell-Download im
  Assistenten.
- **Erst-Klick auf eine noch nicht analysierte PDF** (#108, Teil 2): Waehrend
  die Texterkennung laeuft, zeigt die Kachel „Analysiere…“, der Mauszeiger
  wird zum Wartezeiger und die Statusleiste erklaert, dass OCR einige
  Sekunden dauern kann. Dieselbe PDF wird nicht mehr mehrfach analysiert,
  wenn sie gleichzeitig vom Vorab-Laden und vom Klick angefordert wird.
- **Log:** Zu jeder Analyse steht jetzt eine Zeile `Analyse <datei> <ms>:
  seiten … | ocr ja/nein | zeichen …`, und der Klick-Pfad nach einer
  Analyse loggt als `Klick nach Analyse …`. Damit ist im Log sichtbar, ob
  eine Wartezeit von der OCR oder von der Oberflaeche kommt.
- **Vergleich mit paperless-ngx neu geschrieben** (#112): Stand 09/2026 gegen
  paperless-ngx v3.1.3 (native KI und RAG seit v3.0), mit Feature-Tabellen,
  21 belegten Luecken, Bewertung der Server-Frage (Antwort: nein) und
  Hinweisen zum Zusammenspiel. README nennt jetzt die bekannten Grenzen
  (Loeschen ohne Papierkorb, OCR fuenf Seiten, Suchindex 5.000 Zeichen),
  die Regeln ehrlich als Hinweis und 850+ Tests; Docstrings und
  ENTWICKLUNGSSTAND entsprechend angeglichen, Release-Checkliste um den
  Vergleich ergaenzt.
- **Browser-Oberfläche: Hinweis zum automatischen Start**: Die Einstellung
  „Bei der Anmeldung automatisch starten“ (standardmäßig aus) erklärt jetzt,
  dass sie nicht nötig ist – „Im Browser öffnen“ startet die Oberfläche bei
  Bedarf – und dass Virenscanner wie Microsoft Defender die Anmeldeaufgabe
  eines unsignierten Programms als verdächtig melden können (#163).
- **Neue Modell-Empfehlungen für Ollama**: Der Assistent empfiehlt bei
  16 GB Grafikspeicher und mehr `gpt-oss:20b` (14 GB), ab 10 GB das neue
  `gemma4:12b` (8 GB, mehrsprachig deutlich stärker als Gemma 3; braucht ein
  aktuelles Ollama), ab 4 GB weiter `gemma3:4b`. Die Vorschlagslisten in den
  Einstellungen sind entsprechend aktualisiert; die Liste der Ollama-Cloud-
  Modelle enthält nur noch Modelle, die es auf ollama.com noch gibt.
- **Dokumentation**: Die README beschreibt die Dokumentensuche (Suche über
  den ganzen PC, Hintergrundlauf, Textebene, Browser-Oberfläche) und wie man
  sie in Claude Code oder Claude Desktop als MCP-Server einträgt; die
  Datenschutz-Tabelle nennt Suche und MCP. Neu: `docs/SUCHE_SCHEMA.md` mit dem
  Aufbau der Such-Datenbank (Version 2) für eigene Auswertungen.
  `docs/ARCHITECTURE.md` beschreibt, dass der Chat aus diesem Index liest.

### Behoben
- **Hintergrundindexierung, wenn der Rechner nachts aus ist**: Die
  Einstellung heißt jetzt „Einmal täglich im Hintergrund indizieren, sobald
  der Rechner nicht benutzt wird“ mit „Frühestens ab“ (Standard 00:00) statt
  einer festen Uhrzeit. War der Rechner zu dieser Zeit aus, wird der Lauf
  nach dem Einschalten nachgeholt, aber erst, wenn der Rechner zehn Minuten
  nicht benutzt wurde. Unter macOS startet die Indexierung dafür zusätzlich
  bei der Anmeldung und wartet auf Leerlauf, höchstens einmal am Tag.
- **Übernahme einer vorhandenen PDFsuche** (Dokumentensuche): Korrespondent,
  Steuerjahr, Betrag und die anderen Angaben, die PDF Sortier Meister vor der
  Übernahme im Suchindex gespeichert hatte, kommen in die übernommene
  Datenbank mit. Die Datenbank wird bei der Übernahme gleich auf den neuen
  Stand gebracht.
- **Browser-Oberfläche der Suche**: Öffnet man dort ein Dokument oder seinen
  Ordner, erscheint das Programm (Excel, Word, Mailprogramm, Explorer) jetzt
  im Vordergrund statt hinter dem Browser (Windows).
- **KI-Assistenten (MCP)**: Die Beschreibungen der Werkzeuge `suche`,
  `dokument_lesen` und `index_status` erscheinen ohne überflüssige Einrückung.
- **Neuer Unterordner ist sofort markiert**: Nach „Neuen Unterordner
  erstellen“ im Kontextmenue des Zielordner-Baums wurde der ganze Baum neu
  aufgebaut und der neue Ordner musste gesucht werden. Jetzt wird er direkt
  unter seinem Elternordner eingehaengt, der Pfad aufgeklappt und der Ordner
  markiert und ins Bild gescrollt. Er wird nur markiert, nicht angeklickt:
  die ausgewaehlte PDF wird also nicht verschoben. Auch Ordner unterhalb der
  geladenen Baumtiefe erscheinen jetzt.
- **KI-Statusanzeige war gruen, obwohl die lokale KI nicht arbeiten
  konnte**: „LLM: Ollama/…“ zeigte nur, dass ein Anbieter eingestellt ist.
  Fuer lokale Server (Ollama, Strata) prueft PDFSM jetzt im Hintergrund beim
  Start, nach dem Speichern der Einstellungen, jede Minute und nach einem
  KI-Fehler, ob der Server antwortet. Bei Ollama muss auch das eingestellte
  Modell installiert sein. Die Anzeige ist grau, solange die Pruefung laeuft,
  und rot, wenn etwas fehlt. Der Tooltip nennt den Grund. Cloud-Anbieter
  bleiben wie bisher gruen.
- **KI-Statusanzeige sagt jetzt, was zu tun ist**: Antwortet Ollama zwar,
  kann aber kein Modell laden (z.B. fehlender `llama-server` nach einem
  abgebrochenen Update), wurde die Anzeige nach jeder Minutenpruefung wieder
  gruen. Jetzt zaehlt der echte Fehler einer KI-Anfrage: die Anzeige bleibt
  rot (mit ⚠), bis wieder eine Anfrage gelingt oder die Einstellungen
  geaendert werden - das gilt auch fuer Cloud-Anbieter (z.B. ungueltiger
  API-Key, Guthaben aufgebraucht). Der Tooltip nennt in einfachen Worten
  Problem und Abhilfe („Ollama neu installieren bzw. aktualisieren“,
  „ein vorhandenes Modell auswaehlen“ ...), ein Doppelklick oeffnet die
  Einstellungen. Fehler, die nur ein einzelnes Dokument betreffen („KI hat
  keinen Vorschlag geliefert“), faerben die Anzeige nicht rot. Nach einem
  Fehler fragt PDFSM jede Minute eine gescheiterte PDF erneut an; klappt das
  wieder, holt die Vorabfrage die uebrigen von selbst nach. Der Dialog
  „Hintergrund-Analyse“ zeigt denselben Hinweis und hat einen Knopf
  „Einstellungen oeffnen“.
- **Falsches Jahr im Dateinamen und Steuerjahr** (#132): Als Dokumentdatum
  galt bisher das *juengste* Datum im Text - eine Frist, ein Eingangsstempel
  oder ein OCR-Lesefehler mit spaeterem Jahr machte aus einem Brief von 2004
  ein Dokument von 2006, und das Steuerjahr folgte. Fand die Texterkennung
  gar kein Datum, nahm die KI stillschweigend das Scandatum der Datei. Jetzt
  zaehlt ein beschriftetes Datum („Datum:“, „Rechnungsdatum“, „Ort, den“)
  zuerst, danach das erste Datum in Lesereihenfolge (Briefkopf); Daten hinter
  „geboren“, „gueltig bis“, „faellig“, „Frist“ oder „Eingang“ nur als
  Notnagel. Der KI-Prompt erklaert Fristen und Scandatum ausdruecklich als
  Nicht-Dokumentdatum, verlangt das Datum als eigenes Metadatum und bekommt
  den Namen des Quellordners („Briefe 2004“) als Hinweis mit.
- **MwSt-Satz 7 % wurde staendig vorgeschlagen**, auch bei Dokumenten ohne
  jede Steuerangabe: Im KI-Prompt stand „7“ als Beispielwert, den viele
  Modelle einfach uebernahmen. Die Beispiele heissen jetzt „19 oder 7 oder
  UNBEKANNT“ bzw. „JJJJ oder UNBEKANNT“, eine Prompt-Regel verlangt
  Betraege/MwSt/IBAN nur bei Rechnungen und Belegen, und ein Steuersatz, der
  im Dokumenttext nicht vorkommt, wird verworfen. Das Feld bleibt dann leer.
- **Fehlerdialog nach „Verschieben nach…“:** Das Verschieben ueber den
  Ordnerauswahl-Dialog lief durch, meldete danach aber „Verschieben
  fehlgeschlagen“ (undefinierte Variable beim Aktualisieren der
  Ordneransicht).
- **Drop auf gruene Vorschlagskacheln** verschiebt die PDF jetzt wirklich;
  vorher passierte beim Loslassen nichts.
- **Kontextmenue der Vorschlagskacheln:** Der wirkungslose Eintrag „Aus
  Zielliste entfernen“ ist dort weg (Vorschlaege sind Unterordner, keine
  Eintraege der Zielliste).
- **Zielordner entfernen** scannt den Zielbaum nur noch einmal statt zweimal.
- **Tooltip im Zielbaum** nennt jetzt die Tastatur-Navigation (Pfeil rechts
  klappt auf, * alle Unterordner) und den Rechtsklick.

- **Lizenz-Angaben konsistent:** Der Über-Dialog nannte „MIT License“, 16
  Modul-Header ebenfalls; das Projekt steht seit Juli 2026 unter
  GPL-3.0-or-later. Beides korrigiert, der Lizenztext liegt jetzt als
  `LICENSE.txt` im Installer und im portablen ZIP (und in `_internal/`).
- **Erststart:** Die Hinweise „Erste Schritte“ und „Backup empfohlen“
  erschienen über dem noch offenen Einrichtungsassistenten. Sie kommen jetzt
  erst, wenn der Assistent geschlossen ist.

- **Klick auf eine gescannte PDF dauerte 7 Sekunden** (#108, Teil 1): Beim
  Anklicken lief die Texterkennung (OCR) noch einmal komplett durch, obwohl
  der Text laengst im Cache lag. Die Dateinamen-Vorschlaege „Automatisch
  erkannt“ nutzen jetzt den Cache und oeffnen die PDF nur noch, wenn
  wirklich etwas fehlt. Betrifft alle vier Wege: Klick, KI-Nachlieferung,
  Suchfeld leeren und den Umbenennen-Dialog. Nebenbei: Datumsangaben aus dem
  Cache erscheinen in den Vorschlaegen wieder als „2026-05-12“ statt
  „2026-05-12 00:00:00“.

## [0.23.0] - 2026-08-30

### Geaendert
- **Einheitliche Vorschlagsliste im Detail-Panel** (#106): Die Auswahl
  „Muster“ unter der Liste ist weg. Stattdessen stehen alle Vorschlaege in
  einer Liste: KI-Vorschlag, je Vorlage ein Muster-Vorschlag (Rechnungen &
  Belege, Akten & Projekte, Buero-Kuerzel, eigenes Muster aus den
  Einstellungen) sowie „Automatisch erkannt“, „Datum + Kategorie“ und
  „Kategorie + Nummer“. Wer einen Vorschlag anklickt, macht dessen Art zum
  Standard: Beim naechsten Dokument steht sie ganz oben und wird als
  Dateiname uebernommen, die uebrigen ruecken eine Stufe nach unten
  (Config-Schluessel `suggestion_kind_order`). Muster-Zeilen erscheinen nur,
  wenn mindestens zwei Platzhalter einen Wert haben; „Nur Datum“ wird nicht
  mehr angeboten.
- **„Gelernt“-Vorschlaege werden zu KI-Beispielen:** Die alten „Gelernt:
  aehnlich zu …“-Zeilen (irgendein frueherer Dateiname mit einem gemeinsamen
  Stichwort) sind aus dem Detail-Panel verschwunden. Stattdessen bekommt die
  KI die Dateinamen, die man fuer wirklich aehnliche Dokumente gewaehlt hat
  (Firma/Person aus dem Namen kommt im Text vor oder mindestens zwei
  Stichwoerter stimmen ueberein), als Stil-Beispiele in den Prompt. Was man
  waehlt oder korrigiert, praegt so den naechsten Vorschlag.
- **Kopfzeile ueber den Vorschlaegen:** Rechts neben dem Titel gibt es den
  Schalter „Ordnerstruktur im Namen“ (dieselbe Einstellung wie *Beim
  Verschieben* im Einstellungsdialog, wirkt sofort) und „Muster bearbeiten…“,
  das die Einstellungen direkt auf dem Tab *Dateinamen* oeffnet.
- **Neues Muster wirkt sofort:** Wird in *Einstellungen > Dateinamen* ein
  anderes Muster gespeichert, steht es im Detail-Panel sofort ganz oben in
  den Vorschlaegen und wird als neuer Dateiname uebernommen.
- **Muster ohne Tastatur zusammenklicken** (Einstellungen > Dateinamen):
  Unter den Platzhalter-Chips gibt es jetzt „Leerzeichen“, „_“ und „-“ sowie
  „Zuruecknehmen“, das den letzten Baustein vor dem Cursor entfernt (ganzer
  Platzhalter samt Trennzeichen, oder ein einzelnes Zeichen). Ein Chip-Klick
  setzt automatisch „_“ zwischen zwei Platzhalter; wer vorher „-“ oder
  Leerzeichen klickt, bekommt stattdessen dieses.
- **Eigene Muster speichern** (Einstellungen > Dateinamen): „Muster
  speichern…“ legt das Muster im Feld unter einem Namen ab. Es erscheint
  danach in der Vorlagen-Liste und als eigene Muster-Zeile bei den
  Vorschlaegen im Detail-Panel; „Loeschen“ entfernt es wieder
  (Config-Schluessel `custom_patterns`).
- **Text aus der Vorschau in die Metadaten** (#109): In der PDF-Vorschau
  laesst sich Text mit der Maus markieren; Rechtsklick bietet „Als … uebernehmen“
  fuer jedes Metadaten-Feld (Korrespondent, Kategorie, Zusammenfassung,
  Betrag Netto/Brutto, Waehrung, MwSt-Satz, IBAN, Steuerjahr) sowie
  „Kopieren“; IBAN, Betraege, MwSt und Steuerjahr werden dabei bereinigt.
  Funktioniert auch im grossen Vorschau-Fenster („Gross“).
  Ein so uebernommener Korrespondent wird in die Korrespondenten-Verwaltung
  aufgenommen und bei spaeteren Dokumenten, in deren Text er vorkommt,
  automatisch gesetzt - die eigene Schreibweise schlaegt den KI-Vorschlag.
- **Kategorie als Auswahlfeld** (#110): Das Feld „Kategorie“ ist jetzt eine
  editierbare Aufklappliste: zuerst die zuletzt selbst verwendeten
  Kategorien (gemerkt bei jedem Speichern/Verschieben), dann haeufige aus
  der Sammlung (ohne Bandwurm-Eintraege), aufgefuellt mit Standardwerten.

- **Metadaten: neu vs. aus dem PDF:** Hatte die PDF bereits Metadaten,
  werden Felder, deren Wert nicht (so) im PDF steht, pastellgruen
  hervorgehoben (wie Kacheln mit KI-Vorschlag) - bis zum Speichern. Der
  Status lautet dann „Quelle: aus PDF gelesen - gruen = neue Vorschlaege“
  statt des vagen „teils aus PDF, teils Vorschlag“.

### Behoben
- Bei eingeschaltetem „Ordnerstruktur im Namen“ (#42) landete der Name
  samt Ordner-Praefix in der Historie und damit als Beispiel im KI-Prompt -
  die KI haette Ordnernummern erfinden koennen. Gespeichert wird jetzt der
  vom Nutzer gewaehlte Name ohne Praefix.
- Einstellungen > Dateinamen: „Alle Platzhalter“ lag ueber dem letzten Chip
  „{betrag}“ und war unlesbar.
- Verschieben schlug unter Windows mit „Die Datei wird von einem anderen
  Prozess verwendet“ fehl, wenn direkt nach dem Anklicken verschoben wurde
  (Vorschau-/Metadaten-Leser hatten die PDF noch offen). `move_file`
  wiederholt den Vorgang jetzt bei kurzzeitigen Sperren einige Male
  (Virenscanner, OneDrive), bevor es einen Fehler meldet.

## [0.22.0] - 2026-08-29

### Neu
- **Muster-Vorschlaege im Detail-Panel** (#99): Unter der Vorschlagsliste
  gibt es eine Auswahl „Muster“. Der Dateiname nach dem Muster aus
  *Einstellungen > Dateinamen* erscheint als eigener (hellblauer) Vorschlag,
  gebildet aus den Metadaten der ausgewaehlten PDF (Korrespondent, Kategorie,
  Zusammenfassung, Datum, Betrag, Initialen). Ueber die Auswahl laesst sich
  zwischen den Vorlagen und dem eigenen Muster umschalten; die Wahl uebernimmt
  den Namen ins Feld „Neuer Dateiname“. Platzhalter ohne Wert fallen samt
  Trennzeichen weg - es werden keine Beispielwerte eingesetzt.
- **Gruene Kacheln fuer PDFs mit KI-Vorschlag** (#81): Sobald fuer eine PDF
  ein KI-Vorschlag vorliegt (Hintergrund-Abruf, Cache vom letzten Start oder
  manueller KI-Aufruf im Detail-Panel), wird ihre Kachel im Scan-Ordner gruen
  hinterlegt; der Tooltip nennt den Grund. Die Auswahl (blau) bleibt sichtbar.
- **Daten sichern und wiederherstellen** (#98): *Extras > Daten sichern
  (ZIP)…* packt Datenbank (Verlauf, Suchindex/RAG, Korrespondenten, Regeln),
  KI-Cache, ML-Modell und Einstellungen in ein ZIP - SQLite-Dateien als
  konsistenter Schnappschuss auch bei laufender Anwendung. *Extras > Daten
  aus Sicherung wiederherstellen…* merkt ein solches Archiv vor; beim
  naechsten Start werden die Dateien eingespielt, die bisherigen bleiben
  unter `restore_previous` im Datenordner erhalten. Gedacht fuer Umzug oder
  Neuinstallation.

### Geaendert
- Detail-Panel: Die gruene Vorschau-Zeile unter „Neuer Dateiname“ erscheint
  nur noch, wenn der endgueltige Name vom Eingetippten abweicht (ersetzte
  Zeichen, E-Mail-Adresse) - sonst stand derselbe Name zweimal da (#101).

### Entfernt
- Der Schalter „Nur verschieben“ samt Hinweiszeile unter den Metadaten (#100):
  unklar und Platzfresser. Reines Verschieben ohne Umbenennen geht weiter per
  Drag & Drop oder Kontextmenue „Verschieben nach…“.
- Einstellungen > LLM: die wirkungslose Option „Auto-LLM“ und der Hinweis
  zu API-Kosten/TF-IDF (#92).

### Behoben
- Die Muster-Vorschau „Mit aktueller PDF“ in den Einstellungen las die
  Zusammenfassung unter dem alten Schluessel `beschreibung` und fuellte
  `{betreff}` deshalb nie; jetzt teilt sie sich die Zuordnung mit den
  Muster-Vorschlaegen im Detail-Panel.

## [0.21.0] - 2026-08-29

### Geaendert
- **Einstellungen > Dateinamen** neu aufgebaut: Vorlage als Auswahlliste,
  die das Muster-Feld befuellt (Tippen schaltet auf „Eigenes Muster“),
  Platzhalter-Chips zum Anklicken, aufklappbare Legende und eine
  **Live-Vorschau** mit Beispieldokument bzw. „Mit aktueller PDF“ (nutzt
  die KI-Metadaten der ausgewaehlten Datei). Eine Platzhalter-Syntax fuer
  alles: `{datum}`, `{kontakt}`, `{betreff}`, `{kategorie}`, `{initialen}`,
  `{aktenzeichen}`, `{projekt}`, `{betrag}`, `{jahr}`; eigene Platzhalter
  wie `{lieferant}` fuellt die KI nach der Bezeichnung. Alte Muster in
  Grosswort-Schreibweise (`YYYY-MM-DD_Kontakt_Betreff`) werden beim Laden
  automatisch umgestellt. Der KI-Prompt bekommt die Bedeutung jedes
  Platzhalters plus ein gerendertes Beispiel-Ergebnis. Neu `{datum_kompakt}`
  (JJJJMMTT) und Vorlage „Büro-Kürzel voran“ (`{initialen} {datum}-{betreff}`).
- **Leerzeichen bleiben erlaubt** (Bestandssysteme wie
  `JK 069-01-01-20260512-Rechnung`); nur Mehrfach-Leerzeichen und
  Leerzeichen neben `_`/`-` werden entfernt. Beim Verschieben werden
  fuehrende Initialen aus dem KI-Namen nicht mehr verdoppelt
  (`JK 069-…-JK 2026-…`).
- **„Beim Verschieben in einen Ordner“** ist jetzt ein Modus (Namen
  beibehalten / Ordnernummer voranstellen) mit eigener Ergebnis-Vorschau -
  vorher war nicht erkennbar, dass diese Funktion den KI-Namen ueberschreibt.
- **Initialen** stehen unter „Persoenliche Daten“ neben dem Namen
  (Config-Schluessel `owner_initials`, wird aus `folder_naming_initials`
  uebernommen); leer = aus dem Namen abgeleitet. Das Eintippen schaltet die
  Ordner-Benennung nicht mehr heimlich ein. „Verbindung testen“ erscheint
  nur noch auf dem KI-Tab; Tab „Persoenliche Daten“ steht vor „Dateinamen“.

### Behoben
- **Dateinamen ohne verbotene/unguenstige Zeichen**: KI-Vorschlaege wie
  `..._kathrin.haerle@web.de.pdf` enthielten Punkte und Klammeraffen.
  Neue zentrale Bereinigung (`src/utils/filename_sanitizer.py`) ersetzt
  Windows-verbotene Zeichen (`<>:"/\|?*`), Steuerzeichen,
  `.` und `@` durch `_`, wandelt Umlaute/Akzente um, fasst Unterstriche
  zusammen und entschaerft reservierte Namen (CON, NUL, ...). Gilt jetzt
  fuer alle Provider (vorher fehlte sie bei Ollama/OpenRouter), im
  Detail-Panel und im Umbenennen-Dialog: Die Vorschau zeigt den
  tatsaechlich verwendeten Namen und listet ersetzte Zeichen auf, statt die
  Umbenennung zu blockieren. Der KI-Prompt verbietet Punkte/E-Mail-Adressen
  im Namen explizit und verlangt fuer Kontakt/Absender den Namen einer
  Person oder Organisation. Rutscht doch eine Adresse durch, wird sie in
  einen Namen umgewandelt (`kathrin.haerle@web.de` -> `Kathrin_Haerle`,
  `info@huk-coburg.de` -> `Huk-Coburg`); die Vorschau weist darauf hin.
  Enthaelt das Dateinamen-Muster `INITIALEN`/`INITIALIEN`, erklaert der
  Prompt jetzt, dass 2-3 Grossbuchstaben gemeint sind (vorher kam
  `J_Haerle-Wack` statt `JHW`), und gibt die Initialen aus den
  Einstellungen bzw. aus dem Besitzernamen abgeleitet vor.
- **KI-Vorschlaege fehlten still** bei Reasoning-Modellen (z.B. GLM-5.3-flash
  via OpenRouter): das Modell verbrauchte das Token-Budget fuers Nachdenken,
  die leere Antwort wurde als Erfolg ohne Vorschlag gecacht und nie wieder
  versucht. Leere/abgeschnittene Antworten gelten jetzt als Fehler (sichtbar
  in der Statusleiste und im Detail-Panel), leere Ergebnisse werden nicht mehr
  als "abgerufen" gespeichert, `max_tokens` Default 2000 (alter Wert 500 wird
  beim Laden angehoben).
- **Nachdenken minimiert**: OpenRouter `reasoning.effort=low`, OpenAI
  o*/gpt-5 `reasoning_effort=minimal`, Ollama `think:false` - jeweils mit
  Rueckfall, falls ein Modell den Parameter ablehnt. Gemessen: 3-4 s statt
  10-18 s pro PDF. Modelle, die das Denken nicht abschalten koennen (gpt-oss:
  nur low/medium/high) antworten auf `think:false` mit leerem Inhalt oder
  Denktext statt JSON; gpt-oss wird am Namen erkannt und direkt mit
  `think:"low"` gefragt, andere Modelle fallen bei unbrauchbarer Antwort
  einmalig auf `low` zurueck (gemerkt pro Sitzung). Die Anzeige „KI-Fehler“
  in der Statusleiste verschwindet von selbst, sobald die betroffene PDF ein
  Ergebnis bekommt oder der Pre-Cache-Lauf nach dem Fehler ohne weitere
  Fehler zu Ende laeuft. PDFs, deren KI-Abruf gescheitert ist, werden
  einmalig neu eingereiht, sobald danach ein Abruf gelingt.
- **Fremde PDF-Metadaten**: eine `dc:description`, die nur ein Dateiname ist
  (z.B. HUK-COBURG-Dokumente), landet nicht mehr als "Zusammenfassung" im
  Panel. "Quelle: aus PDF gelesen" nur noch, wenn alle Felder wirklich aus
  dem PDF stammen; sonst "teils aus PDF gelesen, teils Vorschlag".
- **Detail-Panel aktualisiert sich**, wenn KI-Vorschlaege fuer die gerade
  ausgewaehlte PDF im Hintergrund eintreffen (vorher: andere PDF anklicken
  und zurueck). Eigene Eingaben werden dabei nicht ueberschrieben.
- **Checkbox-Kaestchen** waren auf Retina-Macs praktisch unsichtbar
  (Fusion-Stil); jetzt kontrastreiche Indikatoren auf allen Plattformen.
  Einstellungen > Dateinamen-Muster: Initialen/Vorlage sind immer editierbar,
  Eintippen von Initialen schaltet die Funktion ein.

### Geaendert
- Statusleiste zeigt Provider und Modell (`LLM: OpenRouter/glm-5.3-flash`);
  KI-Fehler als "⚠ KI-Fehler (Doppelklick)" mit Fehlertext im Tooltip; der
  Doppelklick-Dialog hat einen Button "Log-Datei oeffnen".

## [0.20.0] - 2026-08-28

### Hinzugefuegt
- **Ollama-Empfehlung fuer Laptops ohne dedizierte GPU** (Issue #62): hat das
  System genug Arbeitsspeicher (ab 16 GB, z.B. schneller Shared-RAM), empfiehlt
  der Einrichtungs-Assistent jetzt `gemma3:1b` lokal als "moeglich, aber
  langsamer" statt direkt auf Ollama Cloud zu verweisen; Ollama Cloud bleibt
  als Alternative im Empfehlungstext genannt. Bei wenig Arbeitsspeicher bleibt
  es bei der bisherigen Cloud-Empfehlung.
- `docs/RELEASE_CHECKLISTE.md`: Ablauf fuer Releases mit Pflichtpunkt
  "LLM-Modell-Empfehlungen pruefen" (Issue #63), in README verlinkt.
- **Einrichtungs-Assistent: Default-Ordner und Zielordner-Schritt** (Issues #61, #64):
  Der Scan-Ordner-Schritt schlaegt jetzt automatisch `Dokumente/Scans` vor
  (bzw. `~/Documents/Scans` unter macOS), sobald noch kein Ordner konfiguriert
  ist - der Vorschlag kann per "Weiter" uebernommen oder ueber "Ordner
  auswaehlen" ersetzt werden. Neuer Schritt "Zielordner" direkt danach mit
  demselben Bedienkonzept (Default `Dokumente/PDF-Sammlung`); beide Ordner
  werden beim Abschluss des Assistenten angelegt, falls sie noch nicht
  existieren, der Zielordner wird zugleich als Zielordner registriert. Nach
  dem Assistenten (Erststart wie auch erneuter Aufruf ueber Extras) zeigt das
  Hauptfenster links den Scan-Ordner und rechts sofort den neuen Zielordner an.
- **Aktivitaetsanzeige fuer KI-Aufrufe** (Issue #68): Solange die KI arbeitet, zeigt
  die Statusleiste eine vorwaerts laufende Uhr ("KI arbeitet „rechnung.pdf“ seit 0:42")
  und - sobald Erfahrungswerte fuer dasselbe Provider/Modell-Setting vorliegen - eine
  Schaetzung ("ca. 30 s", Median der letzten 20 Aufrufe, gespeichert in
  `llm_timing.json` im Datenverzeichnis). Dasselbe im Chat ("KI denkt… seit 0:05 ·
  ca. 20 s") und auf dem Button "KI-Metadaten neu generieren".
- "KI-Metadaten neu generieren" laeuft jetzt im Hintergrund - vorher fror das Fenster
  fuer die Dauer der Anfrage ein (Kern: `src/core/llm_activity.py`).

### Geaendert
- `src/utils/hardware.py`: Modell-Empfehlungstabelle (`MODEL_TIERS`,
  `RAM_ONLY_MODEL`, `CLOUD_MODEL`) zu einer zentralen, kommentierten
  Datenstruktur mit Pruefdatum (`MODEL_TIERS_CHECKED_ON`) zusammengefasst,
  damit ein Update der LLM-Empfehlungen an einer Stelle passiert (Issue #63).
- Poe.com ist wieder als KI-Anbieter waehlbar (poe.com vergibt wieder API-Keys;
  in 0.19.0 entfernt).


## [0.19.0] - 2026-08-28

### Hinzugefuegt
- **Integrierte PDF-Vorschau** (Issues #74, #76) auf Basis von QtPdf (Qts eigener,
  PDFium-basierter Viewer - kein Browser, kein QtWebEngine, kein eigener Renderer):
  - Unten im mittleren Bereich zeigt das Detail-Panel die ausgewaehlte PDF mit
    Seitenblaettern, Zoom (auch Strg+Mausrad), "Breite"/"Seite"-Anpassung; ein
    vertikaler Splitter regelt die Aufteilung zwischen Metadaten und Vorschau.
  - Doppelklick auf ein Thumbnail (bzw. "PDF oeffnen" im Kontextmenue, Suchtreffer,
    Chat-Zitate) oeffnet standardmaessig ein eigenes Vorschau-Fenster statt des
    Browsers/Office. Das Fenster wird wiederverwendet, merkt sich seine Groesse,
    Esc schliesst es; "Extern oeffnen" startet das externe Programm.
  - Einstellungen > Allgemein > **PDF oeffnen**: Integrierte Vorschau (Default),
    Standardprogramm des Systems oder eigenes Programm mit Pfad (z.B. PDF-XChange,
    Acrobat); fehlt das Programm, faellt die App mit Hinweis auf das Standardprogramm
    zurueck (`src/utils/pdf_open.py`).
  - Die Vorschau haelt keinen Datei-Handle offen (PDF wird in den Speicher gelesen),
    damit Verschieben und Umbenennen waehrend der Anzeige weiter funktionieren; das
    Einlesen laeuft im Hintergrund (OneDrive Files-On-Demand blockiert die GUI nicht).
  - PyInstaller-Spec buendelt `PyQt6.QtPdf`/`QtPdfWidgets` (Qt6Pdf.dll).
  - Detail-Panel kompakter: Metadaten zweispaltig (Kategorie|Korrespondent, Netto|Brutto,
    Waehrung|MwSt, IBAN|Steuerjahr, Zusammenfassung volle Breite), Vorschlagsliste nur so
    hoch wie noetig, kleinere Abstaende; die Aufteilung Details/Vorschau wird gespeichert.
- **Update-Pruefung** (Issue #73): Kurz nach dem Start fragt die App im Hintergrund
  die Versionsnummer des neuesten GitHub-Releases ab (`src/utils/update_check.py`,
  nur `releases/latest`, keine Nutzerdaten). Gibt es eine neuere Version, erscheint
  ein Hinweis in der Statusleiste und ein Dialog mit "Download-Seite oeffnen",
  "Diese Version ueberspringen" und "Spaeter". Manuell ueber Hilfe > Nach Updates
  suchen; abschaltbar unter Einstellungen > Allgemein > Updates.

### Behoben
- **KI-Zusammenfassung blieb leer** (und teils Kategorie/MwSt-Satz): Der Prompt fragt
  die Schluessel `beschreibung`, `category`, `mwst` ab, Detail-Panel, Umbenennen-Dialog
  und Datenbank lesen aber `description`, `subject`, `mwst_satz`. Ob die Felder gefuellt
  wurden, hing davon ab, ob sich das Modell an den Prompt hielt. Jetzt werden alle
  bekannten Schluessel-Varianten beim Parsen der Antwort und beim Laden aelterer
  Cache-Eintraege auf einen Satz kanonischer Namen abgebildet
  (`normalize_llm_metadata` in `src/ml/llm_provider.py`); Platzhalter wie `UNBEKANNT`
  landen nicht mehr in den Feldern.

## [0.18.0] - 2026-08-28

### Hinzugefuegt
- **macOS-Unterstuetzung** bei gemeinsamer Codebasis: Der Build erzeugt neben der
  Windows-Version jetzt auch eine macOS-App (`.app` + DMG, Apple Silicon und Intel).
  Tesseract-OCR ist wie unter Windows gebuendelt (`scripts/prepare_tesseract_mac.py`),
  die DMGs werden mit Developer ID signiert und notarisiert. Lokaler Build: `./build.sh`.
- **GitHub-Actions-CI**: Tests laufen bei jedem PR auf Windows und macOS; ein
  Versions-Tag baut automatisch alle Release-Assets (Setup.exe, win64-Zip, zwei DMGs)
  als Draft-Release.
- Neues Modul `src/utils/platform_paths.py` buendelt alle plattformabhaengigen
  Basisfunktionen (Datenverzeichnis, Dateien/Ordner oeffnen, Dateimanager-Name).
  Unter macOS liegen Einstellungen/Lerndaten in `~/Library/Application Support/
  PDF_Sortier_Meister`; unter Windows unveraendert `%APPDATA%\PDF_Sortier_Meister`.
- Ollama-Empfehlung kennt Apple Silicon: Unified Memory zaehlt als Grafikspeicher
  (Metal), RAM-Erkennung via `sysctl`.
- **Demo-PDFs fuer Beta-Tester** (Issue #52): `python scripts/generate_demo_pdfs.py`
  erzeugt 23 fiktive Testdokumente (Rechnungen, Vertraege, Kontoauszug,
  Gehaltsabrechnung, Steuerbescheid, gescannte Belege ohne Textebene, Sammelscan
  zum Aufteilen) und packt sie als ZIP nach `data/demo/`.

### Behoben
- Doppelklick auf eine PDF haette die App unter macOS zum Absturz gebracht
  (ungeschuetztes `os.startfile`); oeffnet jetzt plattformuebergreifend den
  Standard-Viewer.
- **Absturz beim Schliessen** waehrend eines laufenden Ordner-Scans oder
  Metadaten-Lesens: Das Hauptfenster stoppt beim Schliessen seine Timer und
  wartet auf seine Hintergrund-Threads; der PDF-Cache haelt einen nach dem
  Stop-Timeout noch laufenden Analyse-Thread referenziert, statt ihn Qt im
  Betrieb loeschen zu lassen (harter Prozessabbruch).
- CI-Testlauf auf Windows und macOS repariert (`pythonpath` fuer pytest,
  Hardware-Tests unabhaengig vom Apple-Silicon-Runner).

## [0.17.0] - 2026-08-27

### Hinzugefuegt
- **Dateiname aus Ordnerstruktur** (Issue #42, Opt-in unter Einstellungen >
  Dateinamen-Muster): Beim Verschieben wird der Dateiname nach einer konfigurierbaren
  Vorlage aus dem Zielordner-Pfad aufgebaut. Platzhalter: `{initialen}`,
  `{ordnernummern}` (Nummernkette aus dem Zielordner-Namen, z.B. "069-03-05"),
  `{ordnerpfad}`, `{datum}` (JJJJMMTT), `{datum_iso}`, `{text}` (bisheriger Name ohne
  Datum). Default-Vorlage `{initialen} {ordnernummern}-{datum}-{text}` ergibt z.B.
  `JK 069-03-05-20260512-Rechnung.pdf` (Kernlogik: `src/core/folder_naming.py`).
- **Tooltips fuer den Kern-Workflow** (Issue #51): Zielordner-Baum und -Kacheln
  erklaeren Einfachklick (PDF verschieben) vs. Doppelklick (Ordner oeffnen);
  Thumbnails, Metadaten-Felder, Filterleiste und Tabs haben erklaerende Tooltips.
- **"Erste Schritte"-Hinweis** (Issue #51): einmaliger Dialog nach dem Start erklaert
  den 3-Spalten-Workflow, mit "Nicht mehr anzeigen"-Checkbox; jederzeit erneut ueber
  Hilfe > Erste Schritte.

### Behoben (Beta-Feedback, Issue #50)
- Die "uebergeordneter Ordner"-Kachel (`..`) reagiert jetzt auf Einfachklick (mit
  Zeitfenster-Guard, damit ein Doppelklick nicht zwei Ebenen springt).
- 125% Windows-Skalierung: Das PDF-Raster passt die Spaltenzahl der Panelbreite an
  (statt fix 3 Spalten, die abgeschnitten wurden); horizontale Scrollbalken erscheinen
  bei Bedarf (linkes Panel und Detail-Panel).
- Fenstergeometrie: Der maximierte Zustand wird als eigenes Flag gespeichert, die
  Normalgroesse nicht mehr mit der Bildschirmgroesse ueberschrieben und beim Start auf
  den verfuegbaren Bildschirm begrenzt ("Titelleiste breiter als das Fenster").
- Splashscreen wird beim Erststart geschlossen, bevor der Einrichtungs-Assistent
  erscheint (lag vorher bis zu 15 s darueber).

### Geaendert
- Installer heisst jetzt fest `PDF_Sortier_Meister_Setup.exe`, damit der Link
  `releases/latest/download/PDF_Sortier_Meister_Setup.exe` immer auf die neueste
  Version zeigt (Issue #49).
- Beim Drueber-Installieren entfernt der Installer die `_internal`-Dateien der
  Vorversion; README dokumentiert Update und Deinstallation inkl. verbleibender
  Nutzerdaten in `%APPDATA%\PDF_Sortier_Meister` (Issue #48).

## [0.16.0] - 2026-08-26

### Hinzugefuegt
- **Einrichtungs-Assistent erkennt Ollama und die Hardware**
  - Provider-Seite zeigt, ob Ollama installiert ist bzw. laeuft, und prueft die
    Grafikkarte (nvidia-smi, sonst Registry-Display-Adapter) - `src/utils/hardware.py`
  - Empfehlung nach Grafikspeicher: gemma3:4b (ab 4 GB), gemma3:12b (ab 10 GB),
    gemma3:27b (ab 20 GB). Ohne dedizierte Grafikkarte (nur integrierte Grafik /
    Shared Memory), unter 4 GB oder mit Intel-GPU: Ollama lokal **nicht** empfohlen,
    stattdessen Ollama Cloud. Die Empfehlung wird vorausgewaehlt, solange noch kein
    Provider konfiguriert ist.
  - Ollama-Seite listet die installierten Modelle (`/api/tags`, Server wird bei Bedarf
    gestartet) und laedt das empfohlene Modell per Klick mit Fortschrittsbalken
    (`/api/pull`, abbrechbar) - kein Terminal mehr noetig. Gewaehltes Modell wird gespeichert.
- **Ollama Cloud** als Provider (`ollama_cloud`): dieselbe API wie lokal, aber gegen
  https://ollama.com mit API-Key (Bearer). Gilt als Cloud-Provider (Einwilligung noetig).
  Standardmodell gpt-oss:120b; Einstellungen-Dialog mit Modell-Liste, "Modelle
  aktualisieren" und Verbindungstest.
- `OllamaProvider` sendet `Authorization: Bearer <key>`, wenn ein API-Key gesetzt ist.

## [0.15.1] - 2026-08-26

### Hinzugefuegt
- **Windows-Installer** (`PDF_Sortier_Meister_Setup_<version>.exe`, Inno Setup): installiert
  ohne Admin-Rechte nach `%LocalAppData%\Programs`, Startmenue-Eintrag, Deinstallation ueber
  "Apps & Features", Update durch Drueberinstallieren. Das portable ZIP bleibt erhalten.
  Bauen: `build.bat` (ruft `scripts/build_installer.py`, Version aus `src/main.py`).
- **Tesseract OCR wird mitgeliefert**: `scripts/prepare_tesseract.py` kopiert tesseract.exe,
  die benoetigten DLLs und die Sprachdaten deu/eng nach `vendor/tesseract`; PyInstaller
  buendelt sie nach `_internal/tesseract`. OCR funktioniert damit ohne separate Installation.

### Behoben
- **OCR fand Tesseract nicht**: `pytesseract` wurde ohne Pfad aufgerufen und verliess sich auf
  den PATH, in den der Tesseract-Installer nichts eintraegt - OCR schlug still fehl.
  `find_tesseract()` sucht jetzt gebuendelt -> `Programme\Tesseract-OCR` ->
  `%LocalAppData%\Programs\Tesseract-OCR` -> PATH und setzt `TESSDATA_PREFIX`.

### Geaendert
- **OneDrive-Wartezeiten aus dem UI-Thread geholt (Log-Analyse 25./26.08.)**
  - XMP-Metadaten der angeklickten PDF werden im Hintergrund gelesen und nachgetragen
    ("Files On-Demand" laedt die Datei erst beim ersten Zugriff: 2-8 s pro Klick)
  - Ordner-Cache des Klassifikators (rglob ueber alle Zielordner, 16,8 s beim ersten
    Klick) wird nach dem Start vorgewaermt und bei Aenderungen im Hintergrund neu gebaut
  - Zielordner-Baum wird in einem Worker gescannt und erst dann befuellt (Start und
    Neuaufbau blockieren nicht mehr); neue Zielordner werden inkrementell eingehaengt
- **Erster Klick nach dem Start**: blockiert nicht mehr, bis das KI-Modell geladen ist.
  Stattdessen Wartecursor + Statusmeldung "KI-Modell wird geladen, Vorschlaege folgen
  gleich..."; die Vorschlaege werden automatisch nachgezogen. pikepdf und die
  sklearn-Aehnlichkeitssuche werden direkt nach dem Start im Hintergrund vorgewaermt.
- Verzoegerte Timer (Pre-Caching, Modell-Warteschleife) sind an das Fenster gebunden
  und feuern nicht mehr nach dessen Schliessen.
- **Verschieben im echten Betrieb (Issue #28, Nachschlag)**
  - Nach einem Verschieben wird der Zielordner-Baum nicht mehr komplett neu aufgebaut
    (alle Ordner 3 Ebenen tief listen + PDFs zaehlen, auf OneDrive der teuerste Teil);
    nur Quell- und Zielordner werden neu gezaehlt (`FolderTreeWidget.refresh_counts`).
  - XMP-Metadaten werden im Hintergrund in die PDF geschrieben (pikepdf schreibt die
    Datei komplett neu); Rueckgaengig wartet auf laufende Schreibvorgaenge.
  - Stoppuhren: `Klick ...` und `Verschieben ...` erscheinen als INFO-Zeilen im Log
    (`%APPDATA%\PDF_Sortier_Meister\logs`), sobald ein Vorgang >= 100 ms dauert -
    mit Aufschluesselung pro Schritt (move | cache | metadata | learn | index | tree ...).

## [0.15.0] - 2026-08-25

### Geaendert
- **Geschwindigkeit (Issue #28)** - gemessen mit 900 Verlaufseintraegen / 100 PDFs
  - Verschieben blockiert nicht mehr: `classifier.learn()` trainierte TF-IDF bei jedem
    Vorgang synchron neu (~450 ms bei 900 Eintraegen). Jetzt entprellt (1,5 s) im
    Hintergrund-Thread mit atomarem Modell-Tausch; beim Beenden wird ausstehendes
    Training abgeschlossen.
  - scikit-learn/numpy werden nicht mehr beim Programmstart importiert (~1,3 s); das
    Modell laedt in einem Hintergrund-Thread, Vorschlaege warten bei Bedarf darauf.
  - Thumbnails werden als PNG unter `<Datenordner>/thumbnails/` gecacht (Schluessel:
    Pfad, Groesse, mtime); Rendern ~17 ms -> Laden ~1 ms pro PDF.

### Hinzugefuegt
- **Jahres-Variante bei Ordnervorschlaegen (Issue #30)**: Zu einem gelernten Vorschlag wie
  "Steuer 2025/Medikamente" wird zusaetzlich "Steuer 2026/Medikamente" angeboten, wenn der
  Ordner existiert. Passt das im Dokument erkannte Jahr, steht die Variante vorn; ohne
  erkanntes Jahr dahinter. Der gelernte Ordner bleibt immer erhalten (nichts wird
  stillschweigend umgeschrieben). Relative Pfade in Vorschlaegen nutzen jetzt einheitlich "/".
- **Explorer-Gefuehl im Scan-Bereich (Sprint 1, Issues #29/#26/#23)**
  - Ordner-Kacheln im PDF-Raster: ".." (uebergeordneter Ordner) und alle Unterordner
    mit PDF-Anzahl; Doppelklick wechselt hinein, PDFs lassen sich per Drag & Drop
    direkt in eine Kachel verschieben
  - Klickbarer Breadcrumb-Pfad unter der Kopfzeile; Menue Ansicht -> "Uebergeordneter
    Ordner" (Alt+Up), wie im Windows-Explorer
  - Zielordner-Baum: Doppelklick oeffnet den Ordner links, ohne vorher die selektierte
    PDF zu verschieben (Einfachklick wird erst nach dem Doppelklick-Intervall ausgefuehrt);
    Kontextmenue "Ordner links oeffnen"
  - Versteckte Ordner (., $, ~) werden ausgeblendet, Unterordner alphabetisch sortiert

### Tests
- `tests/conftest.py`: `patch_singletons()` ersetzt Singleton-Fabriken in allen src-Modulen
  (GUI-Tests liefen je nach Import-Reihenfolge gegen die echte Nutzer-Config)

## [0.14.0] - 2026-08-25

### Hinzugefuegt
- **OpenRouter** als LLM-Provider (OpenAI-kompatible API, viele Modelle mit einem Key)
  - Einstellungen, Setup-Wizard, HybridClassifier, Consent-Gate
- **API-Keys pro Provider** (Issue #11): Keys bleiben beim Provider-Wechsel erhalten,
  Label zeigt den Besitzer ("API-Key (OpenRouter):")
- **Datenschutz-Einwilligung** in den KI-Einstellungen (Checkbox + Hinweis); vorher gab
  es keine Bedienoberflaeche fuer das Consent-Gate
- **Statusleiste**: Doppelklick auf "LLM:" oeffnet die Einstellungen; Doppelklick auf
  den Analyse-Fortschritt zeigt Details (Fortschritt, letzter KI-Fehler, Log-Pfad)
- **Fortschritt der Hintergrund-Analyse**: "Analyse: x/n | KI-Vorschlaege: y/n" mit
  Fehlermarkierung; KI-Vorabfrage wird nach Einstellungsaenderung neu angestossen
- **Backup-Hinweis** beim Start, abhakbar (Issue #7); Macrium-Log-Parsing bleibt #14
- **App-Icon** (Mann aus dem Splash) fuer Fenster, Taskleiste und .exe
- "+ Zielordner" startet im uebergeordneten Ordner des Scan-Ordners (Issue #11)
- **pdfs-Master-Tabelle mit stabiler pdf_id** (Issue #25, Phasen 1-3)
- **Consent-Gate** fuer Cloud-Provider in HybridClassifier (`llm.cloud_consent`)

### Geaendert
- Lizenz: MIT -> **GPL-3.0-or-later** (PyQt6/PyMuPDF Copyleft), LICENSE-Datei ergaenzt
- `OpenAIProvider`: Fehlermeldungen ueber `API_NAME` parametrisiert (fuer Subklassen)

### Behoben
- Einstellungen speichern verwarf `cloud_consent` und `cached_models`
- `Config.DEFAULTS` wurde flach kopiert (verschachtelte Dicts instanzuebergreifend geteilt)
- Analyse-Fortschritt blieb bei "0/n" haengen, wenn alle PDFs bereits im Cache waren
- KI-Vorabfrage lief ins Leere, wenn das LLM beim Einreihen noch deaktiviert war
- LLM-Queue dedupliziert (keine doppelten API-Aufrufe bei erneutem Pre-Cache)

### Tests
- 339 Tests (285 -> 339): OpenRouter-Provider, Keys/Consent-GUI, Cache-LLM-Queue,
  pdf_id-Propagation, Consent-Gate

## [0.13.0] - 2026-06-17

### Hinzugefuegt
- **Phase 20: Korrespondenten-Verwaltung (Issue #21)** - Verwaltungstabelle + GUI-Sidebar
  - Neue SQLAlchemy-Tabelle `korrespondenten` (Name, Aliase, Kategorie, Farbe, Notizen, usage_count)
  - CRUD + merge_korrespondenten (FTS5-Update) + auto_collect_from_history
  - GUI: KorrespondentSidebar im rechten Bereich (Tab "Korrespondenten")
  - GUI: KorrespondentEditDialog + KorrespondentMergeDialog
  - Klick auf Korrespondent filtert PDF-Liste
- **Phase 21: Automatisierungs-Regeln (Issue #22)** - WENN-DANN-Regeln
  - DB-Tabelle `automation_rules` (priority, enabled, conditions_json, actions_json)
  - `RuleEngine.evaluate()` + `apply_actions()` mit 5 Condition-Typen
    (korrespondent, kategorie, betrag, datum, keywords) und 4 Action-Typen
    (target_folder, filename_pattern, metadata_field, tag)
  - Platzhalter: {datum}, {steuerjahr}, {korrespondent}, {kategorie},
    {betrag_brutto}
  - Confidence-Berechnung (1.0 exakt, 0.8 bei contains, N/M partial)
  - Settings-Tab "Automatisierungs-Regeln" mit visuellem Rule-Editor
- **STAB-Block: pytest-qt GUI-Tests** fuer die bestehende Haupt-GUI
  - 39 neue Tests: FolderWidget (14), RenameDialog (12), MainWindow (13)
  - Phase-20: 34 neue Tests fuer Korrespondenten-Verwaltung
  - Phase-21: 23 neue Tests fuer Rule-Edit-Dialog und Settings-Tab

### Geaendert
- `ENTWICKLUNGSSTAND.md` -> v0.13.0 (Phase 20+21 abgeschlossen)

### Behoben
- Phase-21: replace_all=true hatte `main_window.py` zwischenzeitlich
  zerschossen -> via `git checkout` zurueckgesetzt und 3 Move-Pfade
  sauber einzeln nachgepatcht (kein Produktion-Regression, war vor Commit)
- Cancel-Cooldown aus M4-Regression nochmal verifiziert (war schon im
  M4-Commit gefixt)

### Migration
- Neue Tabelle `korrespondenten` und `automation_rules` werden via
  idempotenter `CREATE TABLE IF NOT EXISTS`-Migration angelegt -
  kein Eingriff noetig fuer bestehende Datenbanken
- CHANGELOG.md-Header v0.12.0 zeigt RAG-Chat (Phase 19)
## [0.12.0] - 2026-06-14

### Hinzugefuegt
- **Phase 19: RAG-Chat (Issue #20)** - Intelligente Dokumentensuche per natuerlicher Sprache
  - Neuer Chat-Tab im Hauptfenster (3-Spalten-Layout bleibt erhalten)
  - FTS5-basiertes Retrieval (keine Embedding-Dependency) ueber bestehende `document_search`-Tabelle
  - LLM-Synthese mit klickbaren Quellenangaben `[1]`, `[2]`, ... (Whitelist-validiert; halluzinierte Quellen werden stillschweigend gedroppt)
  - Offline-Fallback: kein LLM konfiguriert -> Keyword-Trefferliste mit klickbaren Quellen
  - In-Session-History (in-memory), Read-only in v1
  - Cancel-Button mit 500ms-Cooldown (M3-Hardening, schuetzt vor Doppel-Klicks)
  - Return-Taste sendet Frage, Shift+Return fuer Zeilenumbruch (M3-UX-Polish)
  - Citation-Parser droppt ungueltige Marker (`[99]`, `[42]`, etc.)
  - Stale-Signal-Guard: `finished()`-Signal nach `cancel()` wird ignoriert
- **M3 Hardening**: Signal-Safety im ChatWorker (`_finished_emitted`/`_failed_emitted` Flags,
  idempotente `cancel()`, `is_finished` Property)
- **M3 Hardening**: Defensiv-Guards in `RAGController` und `CitationParser` (None-Toleranz,
  leere DB, kein LLM)
- **Bugfix**: Suchpfad-Bug (Issue #25) - `update_pdf_path` und `bulk_index_directory` ergaenzt
  - Vorher: nach Verschieben einer PDF blieben DB-Eintraege am alten Pfad zurueck (Orphans)
  - Nachher: atomar DELETE-old + INSERT-new, plus Bulk-Index fuer ganze Ordner
- **Test-Suite**: 112 Tests (68 -> 112), davon 35 neu fuer RAG-Pipeline
  - Pytest-qt fuer GUI-Tests
  - Headless-Smoke-Tests fuer alle 4 LLM-Provider (Ollama/Claude/OpenAI/Poe)

### Geaendert
- `database.search_documents`: akzeptiert jetzt optionale Filter (steuerjahr, kategorie,
  korrespondent, datum_von/bis, betrag_von/bis) UND optionale Text-Query (M3-Hardening,
  Bugfix fuer OR-Operator)
- `LLMProvider.answer_with_context`: neue abstrakte Methode, in allen 4 Providern
  implementiert via stdlib `urllib` (kein anthropic/openai-Import noetig fuer Tests)
- `ENTWICKLUNGSSTAND.md` -> v0.12.0 (Phase 19 abgeschlossen)

### Behoben
- Cancel-Cooldown wurde durch `_reset_input_state()` ueberschrieben (M3-Bugfix)
- FTS5-OR-Query lieferte 0 Treffer (Production-Bug, gefixt in `search_documents`)

## [0.11.0] - 2026-06-14

### Hinzugefuegt
- Phase 8: 34 Unit-Tests (vorher nur 3 in `test_file_manager.py`)
- Phase 17: Filter-Kombinationen in der Volltext-Suche (Issue #18)
  - Steuerjahr/Kategorie/Korrespondent-Dropdowns
  - Datums- und Betragsbereich
  - Live-Trefferzaehler mit Echtzeit-Aktualisierung
- Phase 6: JSON-Mode fuer LLM-Provider (Ollama native `format=json`, Cloud-Provider ueber
  Regex-Parser)
- `bulk_index_directory` fuer rekursives Neu-Indizieren ganzer Ordner

### Geaendert
- `ENTWICKLUNGSSTAND.md` -> v0.11.0

[Unreleased]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.26.0...HEAD
[0.26.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.25.0...v0.26.0
[0.25.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.24.0...v0.25.0
[0.24.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.23.0...v0.24.0
[0.23.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.22.0...v0.23.0
[0.22.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.21.0...v0.22.0
[0.21.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.20.0...v0.21.0
[0.20.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.15.1...v0.16.0
[0.15.1]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.15.0...v0.15.1
[0.15.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.13.0...v0.14.0
[0.12.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.10.0...v0.11.0
[0.13.0]: https://github.com/Josi-create/PDF_Sortier_Meister/compare/v0.12.0...v0.13.0

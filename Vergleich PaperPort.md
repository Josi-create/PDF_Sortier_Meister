# PDF Sortier Meister vs. PaperPort (Tungsten Automation)

**Stand: 19. November 2026 (PDFSM v0.31.1; PaperPort 14.8.0)** — verglichen werden PDF Sortier Meister **v0.31.1** (veröffentlicht am 19.11.2026; v0.31.0 erschien am 18.11.2026, v0.31.1 bringt nur Behebungen und ändert keine Zeile dieses Vergleichs) und **Tungsten PaperPort 14.8.0** (Standard und Professional; Technische Daten datiert 11.10.2024, Build 14.8.24565.2000). Eine neuere PaperPort-Version war am 18.11.2026 nicht zu finden. PaperPort wurde **nicht installiert und nicht ausprobiert**: Alles zu PaperPort stammt aus Unterlagen des Herstellers oder von Händlern. Die Spalte „Herkunft“ sagt, woher:

- **H** = Hersteller-Dokumentation (Getting Started Guide, Release Notes, Technische Daten zu 14.8.0). Beschreibt Funktionen sachlich, ist aber nicht nachgeprüft.
- **W** = nur aus der Werbung des Herstellers (Produktseite, Datenblatt „Product Summary“). Mit Vorsicht lesen.
- **D** = Dritte (Händler, Vergleichsportale, Wikipedia).

Anlass: Ein Nutzer im Forum Dr. Windows wies darauf hin, dass es PaperPort bei Tungsten Automation (früher Kofax, davor Nuance) weiter gibt (#401, #402). PDF Sortier Meister ist als Ersatz für PaperPort entstanden; das Stapeln per Drag & Drop ist ausdrücklich PaperPort nachgebaut (README, CHANGELOG 0.24.0).

> Kurzfassung: PaperPort ist ein **Scan- und Ablageprogramm mit Bild- und PDF-Werkzeugen**: Es scannt selbst (TWAIN/WIA/ISIS), zeigt Ordner als Kachel-Schreibtisch, stapelt und trennt PDFs, verbessert Scanbilder, versieht sie mit Anmerkungen, macht Formulare ausfüllbar und schickt Dokumente per „Senden an“-Leiste an Word, Mail oder Evernote. **Sortieren und Benennen muss der Mensch selbst**; es gibt keine Vorschläge für Ordner oder Namen, keine Erkennung von Absender, Datum oder Betrag und keine KI. Die Suche (All-in-One Search) braucht einen Index, den man anstößt oder in der Professional-Ausgabe zeitlich plant. PDFSM ist umgekehrt gebaut: **Es schlägt Ordner, Namen und Metadaten vor** und sucht über den ganzen PC samt Mails und Office-Dateien, hat aber **keine eigene Scan-Oberfläche, keine Anmerkungen, keine Formulare, keine Bildwerkzeuge** über Drehen, Geraderücken und Fotos-Entzerren hinaus. PaperPort kostet einmalig 99 $ (Standard) bzw. 199 $ (Professional), läuft nur unter Windows und wird seit Jahren nur in kleinen Schritten gepflegt (14.8.0: neuer Name, Evernote-Anbindung). PDFSM ist kostenlos (GPL-3.0) und läuft auch auf dem Mac.

---

## 1. Grundkonzept

| | **PDF Sortier Meister** | **PaperPort 14.8** | Herkunft |
|---|---|---|---|
| **Typ** | Desktop-App (Windows 10/11, macOS) | Desktop-App, nur Windows (Technische Daten 14.8.0: Windows 11 und 10; Produktseite: „not Mac compatible“) | H, W |
| **Zielgruppe** | Einzelperson, Haushalt, Selbstständige, Steuerbüro-Zuarbeit | „designed specifically for home office use“ (Datenblatt); Enterprise-Ausgabe für Firmen mit Netzwerk/SharePoint | W |
| **Bedienidee** | Scan-Ordner links als Kacheln, Zielordner rechts mit Vorschlägen; Klick oder Drag & Drop verschiebt und benennt; Reiter „Suche“ und „Chat“ | „PaperPort Desktop“: Ordnerbaum links, Dokumente als große Miniaturen; in Professional zwei Arbeitsbereiche übereinander; „Senden an“-Leiste unten | H |
| **Datenhaltung** | Dateien bleiben in den eigenen Ordnern (auch OneDrive), Metadaten in der PDF (XMP + Info-Dictionary), lokaler Suchindex (SQLite) | Dateien liegen in normalen Windows-Ordnern („My PaperPort Documents“ oder per Folder Manager eingebundene Ordner, Änderungen im Explorer werden übernommen); Name, Autor, Betreff, Stichwörter in der PDF; eigener Suchindex für die All-in-One Search | H |
| **Altes Dateiformat** | — | `.max` (eigenes Bildformat früherer Versionen) nur noch lesend; ein mitgelieferter „MAX to PDF Converter“ wandelt in PDF um | H |
| **Lizenz / Preis** | GPL-3.0, kostenlos, quelloffen | proprietär; Standard 99 $, Professional 199 $ (US-Produktseite), Enterprise auf Anfrage; Aktivierung über das Internet nötig | W, H |
| **Sprachen** | Deutsch, Englisch | Standard: 7 Sprachen (u. a. Deutsch); Professional: 11 Sprachen | H |

---

## 2. PaperPort heute: Versionen, Preis, Testversion

**Geschichte** (D, Wikipedia): Visioneer (1995) → Nuance → Kofax (Dezember 2019) → Kofax heißt seit 16.01.2024 **Tungsten Automation**. Version 14 gibt es seit 2013; seither nur Unterversionen (14.7, 14.7.1, 14.8).

**Aktuelle Version:** 14.8.0 (H: Technische Daten „Version 14.8.0, Date 2024-10-11“; Release Notes © 2024, Build 14.8.24565.2000). Neu darin laut Release Notes nur: Umbenennung von Oberfläche und Handbuch auf „Tungsten PaperPort“ und ein Evernote-Link in der „Senden an“-Leiste. Eine Liste behobener Fehler enthalten die Release Notes nicht. Entfallen sind Windows 8.1, Internet Explorer, Office 2013 und SharePoint 2013. Das Getting Started Guide (ebenfalls vom 11.10.2024) nennt noch Windows 10, 8.1 und 7 als Systeme, die Technischen Daten Windows 11 und 10; die Unterlagen sind hier nicht einheitlich.

**Weiterentwicklung und Support-Ende:** Auf der Produktseite steht kein Support-Ende. Die Tabelle „Product Release and Sunset Schedules“ von Tungsten war am 18.11.2026 nicht abrufbar (HTTP 404), ob PaperPort 14.8 dort ein Datum hat, ist **nicht geprüft**. Auch am 19.11.2026 fand sich weder im Wissensportal von Tungsten noch per Websuche ein offizielles Support-Ende. Seit Oktober 2024 ist keine neue Version erschienen (Stand der Recherche).

**Preis** (Stand 18.11.2026):

| Ausgabe | Preis | Quelle | Herkunft |
|---|---|---|---|
| Standard | 99 $ | US-Produktseite tungstenautomation.com | W |
| Professional | 199 $ | US-Produktseite | W |
| Professional | „129 €“ zuzüglich lokaler Steuern | deutsche Seite tungstenautomation.de (am 18.11. und erneut am 19.11.2026 abgerufen, beide Male „129 €“, ohne durchgestrichenen Preis oder Hinweis auf ein Angebot; nur per Abruf, nicht im Browser angesehen) | W |
| Enterprise | nur auf Anfrage („Contact Sales“) | Produktseite | W |
| Professional, Einzelplatz, Download | rund 206 € inkl. MwSt.; ein deutscher Händler meldet „nicht mehr verfügbar“ | Händler | D |

Die Produktseite sagt nichts von einem Abo; Händler und Vergleichsportale führen PaperPort als **Einmalkauf** (dauerhafte Lizenz). Upgrade-Preise für Besitzer alter Versionen waren nirgends zu finden. Tungsten gibt beim Kauf im eigenen Shop **30 Tage Geld-zurück**.

**Testversion:** Nur für **Professional**, **15 Tage** (W: Dankeseite nach dem Formular „Start your 15-day trial now“, die Restlaufzeit zeigt das Programm bei jedem Start). Das Formular fragt Vorname, Nachname, Land, Bundesland und E-Mail ab; ein Konto mit Passwort wird nicht angelegt. Einschränkungen der Testversion nennt der Hersteller nicht. Ob die Testversion deutsch installiert, ist nicht angegeben (die Installation lässt eine Sprache wählen, H).

---

## 3. Feature-Vergleich

Legende: ✅ vorhanden · ◐ teilweise · ❌ nicht vorhanden. „Beleg“ nennt bei PDFSM die Stelle im Code oder die CHANGELOG-Version; bei PaperPort die Herkunft (H/W/D, siehe oben). „Pro“ = nur in PaperPort Professional.

### 3.1 Eingang: Scannen und Importieren

| Feature | PaperPort 14.8 | PDF Sortier Meister | Beleg |
|---|---|---|---|
| **Scannen aus dem Programm** | ✅ TWAIN, WIA, ISIS; Scan-Profile (S/W, Graustufen, Farbe, durchsuchbares PDF; Pro: eigene Profile und „PDF-MRC High Compression“); Duplex mit „Scan Other Side“; Scanner-Tasten können PaperPort starten; Scanner-Einrichtungsassistent (H) | ◐ kein eigener Scan-Dialog: Der Knopf „Jetzt scannen“ startet das hinterlegte Scanprogramm (z. B. VueScan, Herstellersoftware), die neue Datei erscheint über die Ordner-Beobachtung von selbst | `src/core/scan_programm.py` (v0.30.0, #270); offen: #337, #338, #339 |
| Ordner auf neue Dateien überwachen | ✅ Pro: „DesktopDelivery“ überwacht lokale und Netzwerkordner (PDF, TIFF, JPEG, MAX) **und E-Mail-Ordner auf Anhänge** und holt sie in PaperPort-Ordner (H) | ◐ der links geöffnete Ordner wird beobachtet, neue Scans und Unterordner erscheinen von selbst (nur bei offenem Fenster); die Dokumentensuche liest täglich im Leerlauf neu ein; Mail-Anhänge per Rechtsklick in der Suche in den Scan-Ordner | `src/core/ordner_beobachter.py` (v0.28.0, #232; v0.31.0, #319); CHANGELOG 0.31.0 (#327) |
| Drucken in das Programm | ✅ „PaperPort Image Printer“ erzeugt PDF Image oder durchsuchbares PDF auf dem Schreibtisch; Pro: zusätzlich Power PDF Create (Office-Add-ins, Druckertreiber) (H) | ❌ kein Druckertreiber (Windows hat „Microsoft Print to PDF“, die Datei kann in den Scan-Ordner gespeichert werden) | — |
| Fotos von der Kamera | ✅ Import über Laufwerk oder TWAIN/WIA; „3D-Deskewing“ für abfotografierte Seiten (H) | ✅ Bilder als Kacheln, „In PDF umwandeln und automatisch entzerren“ oder von Hand mit vier Ecken, Beleuchtung ausgleichen, Texterkennung | `src/core/entzerren.py`, `src/core/bild_convert.py` (v0.26.0, #184, #205) |
| Office-Dateien | ◐ als „Text-Elemente“ mit Miniatur sichtbar, öffnen im eigenen Programm; Pro: in PDF umwandeln mit Power PDF Create (H) | ✅ Word, Excel, OpenDocument, .txt sortierbar und in PDF/PDF-A umwandelbar; Office-Dateien in der Suche | `src/core/office_convert.py` (v0.26.0, v0.28.0) |

### 3.2 Ordnen, Benennen, Metadaten

| Feature | PaperPort 14.8 | PDF Sortier Meister | Beleg |
|---|---|---|---|
| **Vorschlag, in welchen Ordner ein Dokument gehört** | ❌ nicht beschrieben; man zieht selbst (H) | ✅ lernt aus jeder Verschiebung, Jahres-Varianten („Steuer 2025“ → „Steuer 2026“), Ablageorte ähnlicher Dokumente, neue Ordner, KI bei niedriger Sicherheit | `src/ml/classifier.py`, `src/core/similar_documents.py`, `src/core/neuer_ordner.py` |
| **Vorschlag für den Dateinamen** | ❌ Scan-Profile hängen nur fortlaufende Endungen an (H: „automatically suffixed file names“) | ✅ Muster mit Platzhaltern (`{datum}_{kontakt}_{betreff}`), von der KI ausgefüllt | `src/core/filename_placeholders.py` |
| **Absender, Datum, Betrag, MwSt, IBAN, Steuerjahr erkennen** | ❌ nicht beschrieben | ✅ Metadaten-Extraktion (lokal über Ollama oder Cloud-Anbieter), in die PDF geschrieben | `src/core/pdf_metadata.py` |
| Metadaten in der PDF | ✅ Name, Autor, Betreff, Stichwörter; mehreren Dokumenten auf einmal zuweisbar; Seitennamen (H) | ✅ Kategorie, Korrespondent, Datum, Beträge, Steuerjahr, Zusammenfassung, Notiz (v0.31.0), Schlagwörter in `pdf:Keywords` | `src/core/pdf_metadata.py` (u. a. `pdf:Keywords`) |
| **Ordner-Notizen** (gleiche Stichwörter automatisch für alles, was in einen Ordner gescannt wird) | ✅ „Folder Notes“, auf Wunsch beim Scannen und bei DesktopDelivery angewendet (H) | ◐ keine festen Ordner-Notizen; Schlagwörter und Kategorie werden je Dokument vorgeschlagen | — |
| Ordner verwalten | ✅ Ordnerbaum, Farben je Ordner, Folder Manager bindet beliebige Ordner ein (auch Netzwerk); Pro: Ordnerstruktur aus Textdatei anlegen (H) | ✅ Ordnerbaum mit Suche, Favoriten, Pfad eintippen, ganze Ordner verschieben/kopieren; keine Ordnerfarben | `src/core/ordnersuche.py`, `src/core/ordner_verschieben.py` |
| Zwei Ordner nebeneinander | ✅ Pro: geteilter Schreibtisch mit zwei Arbeitsbereichen (H) | ◐ Scan-Ordner links als Kacheln, Zielordner rechts als Baum; keine zwei Kachelansichten gleichzeitig | — |
| Lesezeichen / zuletzt benutzt | ✅ Lesezeichen für Arbeitsbereiche, „zuletzt gescannt/geöffnet“ (H) | ✅ Favoriten-Leiste, „Zuletzt verschoben nach …“ | v0.26.0 (#114), v0.28.0 (#253) |
| Doppelte Dateien | ❌ nicht beschrieben | ✅ Hinweis „Doppelt: wie …“, Rückfrage beim Ablegen, Aufräum-Übersicht (v0.31.0) | `src/core/duplikate.py`, `src/gui/doppelte_aufraeumen.py` |
| Steuerauswertung | ❌ | ✅ Summen je Steuerjahr/Kategorie, CSV | `steuerauswertung_dialog.py` |

### 3.3 Suche und KI

| Feature | PaperPort 14.8 | PDF Sortier Meister | Beleg |
|---|---|---|---|
| **Volltextsuche** | ✅ „All-in-One Search“: Suche nach Name, Autor, Stichwörtern, Kommentaren, Anmerkungen und (mit Index) im Text; „genau“ oder „ähnlich“ (findet auch Wortformen bzw. ähnliche Wörter); Treffer als Tabelle mit „View Text“ (H) | ✅ Reiter „Suche“: seitenweiser Index, UND/ODER/NICHT/NAHE, Filter (Ordner, Zeitraum, Steuerjahr, Kategorie, Korrespondent, Betrag, Schlagwort), Vorschau auf der Trefferseite, gespeicherte Suchen | `src/search/db.py`, `src/gui/search_view.py` |
| Index aktuell halten | ◐ automatisch beim Hinzufügen/Ändern (einstellbar) oder von Hand; Pro: „Index Manager“ plant Läufe für lokale und Netzwerkordner (H) | ✅ täglicher Lauf im Leerlauf auch ohne geöffnetes Fenster, sortierte Dateien melden sich sofort beim Index | `src/search/zeitplan.py` |
| Suchbereich | ◐ PaperPort-Ordner (H) | ✅ frei wählbare Ordner und Laufwerke, auch Mails (Thunderbird, Apple Mail, `.eml`, `.msg`), Office-Dateien, Markdown | `src/search/konfig.py`, `src/search/mbox.py` |
| Durchsuchbare PDF für andere Programme | ✅ Scan-Profil „Searchable PDF“, „Speichern unter“, „Make Searchable PDF“; Windows-Suche kann PDFs über PaperPort indizieren (H) | ✅ unsichtbare Textebene in der Originaldatei, für neue Scans standardmäßig | `src/search/textebene.py` (v0.24.0) |
| **Chat über die eigenen Dokumente, KI-Vorschläge** | ❌ keine KI im Produkt beschrieben (das Datenblatt erwähnt „AI-powered workflow automations“ nur im Firmenporträt von Tungsten, nicht bei PaperPort) (H, W) | ✅ Chat mit Quellen, der selbst sucht und liest und Verschieben als Knopf anbietet; Bedeutungssuche lokal über Ollama; MCP-Server für KI-Assistenten | `src/rag/`, `src/search/mcp_server.py` |
| Text in Word übernehmen | ✅ Dokument auf das Word-Symbol der „Senden an“-Leiste ziehen → OCR → bearbeitbarer Text; „Copy Text“ in die Zwischenablage (H) | ◐ Text in der Vorschau markieren und kopieren oder als Metadatum übernehmen; keine Umwandlung in ein Word-Dokument | `src/gui/pdf_preview_widget.py` |

### 3.4 Bild- und PDF-Bearbeitung

| Feature | PaperPort 14.8 | PDF Sortier Meister | Beleg |
|---|---|---|---|
| **Stapeln / Entstapeln** | ✅ PDFs per Drag & Drop oder Menü zu einer PDF stapeln, eine oder alle Seiten wieder lösen (H) | ✅ Stapeln per Drag & Drop „wie in PaperPort“, Strg+Z; Trennen in Einzelseiten oder Bereiche; KI-Trennen an Dokumentgrenzen | `file_manager.py` (`stack_pdfs`, `split_pdf`), `src/core/ki_trennen.py` |
| Seiten löschen, umsortieren, einfügen | ✅ in der Seitenminiatur-Leiste und im PDF Viewer Plus (H) | ✅ „Seiten bearbeiten…“: löschen, drehen, umsortieren, leere Seiten finden; Seiten zwischen Dokumenten verschieben nur über Stapeln/Trennen | `src/core/pdf_seiten.py` (v0.30.0, #280) |
| Kombinieren mit mehreren Seiten je Blatt | ✅ „Combine Items“: vier Seiten auf eine, Miniaturseite (H) | ❌ | — |
| **Scanbild verbessern** („SET“-Werkzeuge) | ✅ Drehen, Geraderücken, Auto-Verbesserung, Schärfen, Rote Augen, Zuschneiden, Radierer, Flecken entfernen, Linien verstärken, Ränder säubern, **Lochung entfernen**, Farbe umwandeln, Weiß-/Schwarzpunkt; teils in Scan-Profilen automatisch (H) | ◐ verlustfrei drehen, gedrehte Seiten automatisch richtig herum, schiefe Seiten gerade ausrichten, Fotos entzerren und aufhellen; kein Radierer, keine Fleck- oder Lochentfernung | `src/core/pdf_rotate.py`, `src/search/gerade.py`, `src/core/entzerren.py` |
| **Anmerkungen** (Haftnotiz, Text, Markieren, Linien, Pfeile, Stempel) | ✅ im PDF Viewer Plus und ImageViewer; in PDFs als bearbeitbare Ebene (H) | ❌ keine Anmerkungen; eine Notiz je Dokument (Feld, nicht auf der Seite) seit v0.31.0. „PDF bearbeiten“ mit LibreOffice ist freigegeben, aber nicht gebaut (#335) | CHANGELOG 0.31.0 (#298) |
| **Formulare** | ✅ PDF-Formulare ausfüllen; „FormTyper“ macht gescannte Papierformulare ausfüllbar; nur Formularfelder auf Vordruck drucken (H) | ❌ | — |
| PDF schützen | ✅ Pro: Öffnen- und Berechtigungspasswort setzen (H) | ◐ nur entfernen (Kopie ohne Schutz), kein Passwort setzen | `src/core/pdf_entsperren.py` (v0.28.0, #244) |
| PDF aus anderen Dateien erzeugen | ✅ Pro: Power PDF Create (Office-Add-ins, Rechtsklick, Druckertreiber, PDF-Pakete) (H) | ✅ Word/Excel/OpenDocument/Bilder/.txt per Rechtsklick in PDF oder PDF/A | `src/core/office_convert.py`, `src/core/bild_convert.py` |
| In andere Formate speichern | ✅ JPEG, TIFF, XPS u. a. (H) | ❌ | — |

### 3.5 Weitergeben, Betrieb, Preis

| Feature | PaperPort 14.8 | PDF Sortier Meister | Beleg |
|---|---|---|---|
| **„Senden an“** (Mail, Word, Fax, Evernote, OmniPage) | ✅ Leiste unten, Dokument daraufziehen; wandelt bei Bedarf um (H) | ❌ keine Senden-an-Funktion; „Im Explorer anzeigen“, „Pfad kopieren“ | `src/gui/pfad_aktionen.py` (v0.25.0, #154) |
| Cloud / SharePoint | ◐ Evernote-Anbindung (14.8.0); Pro: SharePoint (H) | ◐ arbeitet direkt in OneDrive-/iCloud-Ordnern („Dateien bei Bedarf“ unterstützt) | CHANGELOG 0.15.1, `src/search/plattform.py` |
| Plattform | Windows 11/10 (H); kein Mac (W) | Windows 10/11, macOS | README |
| Mehrbenutzer | ◐ je Windows-Konto eigener Ordner; Enterprise für Netzwerk und SharePoint (H, W) | ❌ Einzelnutzer | — |
| Aktivierung / Konto | Aktivierung über das Internet; ohne Aktivierung nur eine begrenzte Zahl von Starts (H) | keine Aktivierung, kein Konto | — |
| Updates | „live updates“ über das Internet (H); letzte Version Oktober 2024 | Hinweis auf neue Version, Drüberinstallieren; seit November 2026 mehrere Releases je Woche | `src/utils/update_check.py`, CHANGELOG |
| Preis, Lizenz | 99 $ / 199 $ einmalig (W), proprietär | kostenlos, GPL-3.0, quelloffen | LICENSE |
| Datenschutz | lokal; Tungsten wirbt mit „full encryption of documents in transit, … intrusion detection and privacy certification“ (W, ohne nähere Angaben, wofür das bei einem lokalen Programm gilt) | lokal; KI standardmäßig aus, Cloud-Anbieter nur mit Zustimmung, lokale Modelle über Ollama | `config.py` (`cloud_consent`) |

---

## 4. Lücken-Tabelle: Was PaperPort kann und PDFSM heute nicht

Relevanz bezieht sich auf **Umsteiger von PaperPort** und Einzelnutzer. Aufwand: S < 0,5 Tag · M 0,5–1,5 Tage · L 2–4 Tage · XL > 1 Woche (Grobschätzung ohne Spike). Je Punkt ein Vorschlag, **noch kein eigenes Issue**.

| # | Feature | PaperPort | PDFSM heute | Relevanz | Aufwand | Vorschlag |
|---|---|---|---|---|---|---|
| 1 | **Alte `.max`-Dateien** | liest sie, wandelt mit „MAX to PDF Converter“ in PDF (H) | ❌ werden nicht angezeigt | **hoch für Umsteiger**, wer lange PaperPort benutzt hat, hat oft noch MAX-Dateien | S (Hinweis) / L–XL (eigener Leser) | Kurz: Abschnitt „Umstieg von PaperPort“ in README und Handbuch (#365): MAX-Dateien vor der Deinstallation mit dem Converter umwandeln; dazu ein Hinweis in PDFSM, wenn ein Ordner `.max`-Dateien enthält. Einen eigenen MAX-Leser nicht bauen (Format nicht offen dokumentiert) |
| 2 | **Anmerkungen** (Markieren, Haftnotiz, Stempel „bezahlt“) | ✅ (H) | ❌ | mittel | M | Erst #335 (PDF in LibreOffice bearbeiten) bauen und sehen, ob das reicht. Falls nicht: in der Vorschau „Markieren“ und „Haftnotiz“ als echte PDF-Anmerkungen (PyMuPDF), nichts weiter |
| 3 | **Scannen aus dem Programm** (TWAIN/WIA, Profile, Duplex) | ✅ (H) | Knopf startet externes Scanprogramm | mittel | L–XL | Nicht nachbauen. Den vorhandenen Weg verbessern (#337, #338, #339 sind freigegeben). Höchstens später: WIA-Scan unter Windows mit einem einzigen Profil, wenn Nutzer ohne Scanprogramm danach fragen |
| 4 | **„Per E-Mail senden“** | ✅ Senden-an-Leiste (H) | ❌ | mittel (Belege an Steuerberater, Vermieter) | M | Rechtsklick „Per E-Mail senden“: öffnet das Standard-Mailprogramm mit der PDF als Anhang (Windows: MAPI; macOS: Mail). Kein eigener Versand, keine Konten |
| 5 | **Passwort setzen** | ✅ Pro (H) | nur entfernen | niedrig–mittel | S | Rechtsklick „Mit Passwort schützen…“ legt eine geschützte Kopie an (Gegenstück zu #244); Original bleibt |
| 6 | Scanbild säubern (Flecken, Lochung, Ränder) | ✅ SET-Werkzeuge (H) | ◐ nur Drehen, Geraderücken, Fotos entzerren | niedrig–mittel | M–L | Nur „Lochung und dunkle Ränder entfernen“ als Rechtsklick, verlustarm, mit Vorschau; erst bei Nachfrage |
| 7 | Formulare ausfüllen, FormTyper | ✅ (H) | ❌ | niedrig | L | Nicht bauen; dafür gibt es PDF-Betrachter und LibreOffice (#335) |
| 8 | Ordner-Notizen (feste Stichwörter je Ordner) | ✅ (H) | ◐ Vorschläge je Dokument | niedrig | M | Nicht bauen; das Lernen aus Verschiebungen ersetzt es weitgehend |
| 9 | In Word umwandeln (OCR → .docx) | ✅ Senden an Word (H) | ◐ Text markieren und kopieren | niedrig | M | Nicht vorrangig; Text kopieren reicht für den Alltag |
| 10 | Mehrere Seiten je Blatt kombinieren, Speichern als JPEG/TIFF | ✅ (H) | ❌ | niedrig | S–M | Nicht bauen |
| 11 | Druckertreiber „Drucken nach PDFSM“ | ✅ (H) | ❌ | niedrig | L | Nicht bauen; „Microsoft Print to PDF“ in den Scan-Ordner reicht |
| 12 | Evernote, SharePoint, Fax | ✅ (H) | ❌ | niedrig | — | Nicht bauen |

---

## 5. Wo PDF Sortier Meister voraus ist

- **Es schlägt vor, statt nur abzulegen:** Ordner (gelernt, Jahres-Varianten, ähnliche Dokumente, neue Ordner), Dateiname nach Muster und Metadaten (Absender, Datum, Beträge, Steuerjahr). In PaperPort zieht man jede Kachel selbst in den Ordner und tippt Namen und Stichwörter selbst (H, keine Vorschlagsfunktion beschrieben).
- **Suche über den ganzen PC:** PDFs (auch gescannte, OCR im Hintergrund), Office-Dateien, Markdown und Mails, mit Filtern nach Steuerjahr, Betrag, Korrespondent; PaperPort sucht in seinen Ordnern.
- **KI-Chat über die eigenen Dokumente** mit Quellen, der auch „In welchen Ordner gehört das?“ beantwortet; Zugriff für KI-Assistenten per MCP. PaperPort hat keine KI.
- **Steuerauswertung** mit Summen je Jahr und CSV.
- **Stapel-Scans ohne Trennblätter trennen** (KI erkennt Dokumentgrenzen).
- **Doppelte Dateien** erkennen und aufräumen.
- **macOS** und **kostenlos/quelloffen**; keine Aktivierung, kein Konto. PaperPort kostet 99 bis 199 $ und läuft nur unter Windows.
- **Aktive Entwicklung:** PDFSM erscheint derzeit mehrmals pro Woche; PaperPort 14.8.0 ist vom Oktober 2024 und brachte vor allem einen neuen Namen.

---

## 6. Umstieg von PaperPort

PaperPort-Ordner sind **normale Windows-Ordner** (H: Änderungen im Explorer werden in PaperPort übernommen, eingebundene Ordner bleiben an ihrem Ort). PDFSM kann deshalb direkt auf derselben Ordnerstruktur arbeiten, ohne Import. Was beim Umstieg zu beachten ist:

- **MAX-Dateien** vorher mit dem „MAX to PDF Converter“ von PaperPort in PDF umwandeln (Startmenü › PaperPort; er findet alle MAX-Dateien in den PaperPort-Ordnern und kann Anmerkungen übernehmen, H). Nach der Deinstallation ist der Converter weg. PDFSM liest MAX nicht (siehe Lücke 1).
- **Stichwörter** aus PaperPort stehen in der PDF. PDFSM liest `pdf:Keywords` und trennt dabei seine automatischen Stichwörter von eigenen Schlagwörtern (`src/core/pdf_metadata.py`). Ob PaperPort-Stichwörter genau so ankommen, ist **nicht geprüft** (dazu bräuchte es eine von PaperPort beschriebene PDF).
- **Anmerkungen** in PDFs bleiben als PDF-Anmerkungen erhalten und sind in jedem PDF-Betrachter sichtbar; in der PDFSM-Vorschau ist das **nicht geprüft**.
- Die **Anordnung der Kacheln** auf dem PaperPort-Schreibtisch und die **Ordnerfarben** gehen nicht über; sie stehen nicht in den Dateien.
- Wer beides parallel nutzt: PaperPort hält Dateien beim Anzeigen teils so offen, dass niemand schreiben darf; PDFSM erkennt das und meldet es (`src/search/plattform.py`).

---

## 7. Fazit und Empfehlung

1. **PaperPort lebt, aber kaum weiter.** Es gibt eine Testversion (15 Tage, nur Professional, Formular ohne Konto) und einen Einmalpreis von 99 bzw. 199 $. Seit 2013 kamen nur Unterversionen; 14.8.0 (Oktober 2024) brachte vor allem den neuen Namen. Für die Werbung von PDFSM heißt das: nicht „PaperPort gibt es nicht mehr“, sondern „PaperPort gibt es noch, ohne Vorschläge, ohne KI, nur für Windows, kostenpflichtig“.
2. **PaperPort ist stärker bei Scannen, Bildbearbeitung, Anmerkungen und Formularen**, PDFSM bei Sortieren, Benennen, Suchen und KI. Das sind verschiedene Schwerpunkte; PDFSM sollte die Bild- und Formularwerkzeuge nicht nachbauen.
3. **Mögliche kleine Pakete für Umsteiger** wären (a) Umstiegs-Abschnitt und MAX-Hinweis (S), (b) „Per E-Mail senden“ (M), (c) „Mit Passwort schützen“ (S). **Entschieden am 18.11.2026: Diese drei werden nicht gebaut.** Anmerkungen werden erst nach #335 neu bewertet; Bild- und Formularwerkzeuge werden nicht nachgebaut.
4. Vor einer Aussage „besser als PaperPort“ in der Werbung den eigenen Augenschein einholen (Testversion, braucht die Zustimmung des CEO, #401).

---

## Quellen (abgerufen 18.11.2026)

- Produktseite (W): <https://www.tungstenautomation.com/products/paperport>, deutsche Fassung <https://www.tungstenautomation.de/products/paperport> und <https://www.tungstenautomation.de/products/paperport/professional>
- Testversion (W): Formular <https://www.tungstenautomation.com/products/paperport/professional-trial-version>, Dankeseite mit „15-day trial“ <https://www.tungstenautomation.com/products/paperport/professional-trial-version/thankyou>
- Release Notes 14.8.0 (H): <https://docshield.tungstenautomation.com/PaperPort/en_US/14.8.0-mq4gqduurk/help/RN/PaperPort_releasenotes/TungstenPaperPortReleaseNotes_14.8.0_EN.htm>
- Technische Daten 14.8.0, 11.10.2024 (H): <https://docshield.azurewebsites.net/PaperPort/en_US/14.8.0-mq4gqduurk/print/TungstenPaperPortTechnicalSpecifications_14.8.0_EN.pdf>
- Getting Started Guide 14.8, 11.10.2024 (H): <https://docshield.tungstenautomation.com/PaperPort/en_US/14.8.0-mq4gqduurk/print/TungstenPaperPortGettingStartedGuide_EN.pdf>
- Datenblatt „Product Summary“ (W): <https://tungstenautomation.com/-/media/files/datasheets/en/ps_tungsten-paperport_en.pdf>
- Wikipedia „PaperPort“ (D): <https://en.wikipedia.org/wiki/PaperPort>
- Preise bei Dritten (D): TrustRadius <https://www.trustradius.com/products/tungsten-paperport/pricing>, Händlerliste <https://responsive5.e-nitiative.eu/store/pbrandlist/kofax/store-2846-1308>, Preisliste <https://www.software-express.de/preislisten/kofax/kofax-18968/>
- Nicht abrufbar (HTTP 404): Tungsten „Product Release and Sunset Schedules“ <https://supportassets.tungstenautomation.com/support/Support$/sunset/Product_Release_and_Sunset_Schedules_November.04.2025.pdf>
- PDFSM: `CHANGELOG.md` (Stand `origin/main`, v0.31.1 vom 19.11.2026), Code unter `src/` wie in der Spalte „Beleg“ genannt; `Vergleich paperless-ngx.md` für die PDFSM-Seite

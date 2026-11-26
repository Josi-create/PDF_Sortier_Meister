# Häufige Fragen und Fehler

## Windows warnt beim Installieren

Das Programm ist noch nicht signiert. Im blauen Fenster „Der Computer wurde durch Windows
geschützt“ auf „Weitere Informationen“ und dann „Trotzdem ausführen“ klicken.

## Ein Scan hat keinen Text

Gescannte PDFs enthalten oft nur ein Bild. PDFSM erkennt den Text selbst (OCR). Beim Anklicken
werden die ersten fünf Seiten sofort gelesen, die übrigen im Hintergrund von der Dokumentensuche.

## Die erste Analyse mit Ollama dauert lange

Beim ersten Aufruf nach dem Start lädt Ollama das Modell in den Speicher. Das dauert ein bis zwei
Minuten, danach geht es schneller. Siehe [KI-Anbieter](06-ki.md).

## Das Modell fehlt oder Ollama läuft nicht

Doppelklick auf die Statusleiste öffnet das Fenster „Hintergrund-Analyse“. Dort steht, was fehlt,
mit einem Knopf zum Beheben.

## Etwas versehentlich verschoben oder umbenannt

`Strg+Z` macht es rückgängig. Gelöschte Dateien liegen im Papierkorb.

## PaperPort-Dateien (.max)

PDF Sortier Meister zeigt die alten PaperPort-Dateien mit der Endung `.max` nicht an. Wer noch
welche hat, wandelt sie vorher in PaperPort nach PDF um.

Die Unterstützung für `.max` wird nicht von sich aus gebaut, weil vermutlich kaum jemand diese
Dateien noch hat. Wer sie braucht, legt auf GitHub ein Issue an: Auf Wunsch (und für einen
Kaffee) baut der Entwickler das gern ein.

## Wo liegen meine Daten?

Konfiguration, Lernhistorie, Suchindex und Protokolle liegen unter Windows in
`%APPDATA%\PDF_Sortier_Meister`, unter macOS in
`~/Library/Application Support/PDF_Sortier_Meister`. Beim Deinstallieren bleiben sie absichtlich
erhalten; wer alles entfernen möchte, löscht danach diesen Ordner.

## Einen Fehler melden

Fehler und Wünsche bitte als Issue auf GitHub melden:
<https://github.com/Josi-create/PDF_Sortier_Meister/issues>

Sehr hilfreich ist die Protokolldatei `logs\pdf_sortier_meister.log` im Datenordner. Sie enthält
Dateinamen, aber keine Dokumentinhalte und keine API-Schlüssel.

## Unterstützen

PDF Sortier Meister ist freie Software (GPL-3.0). **Hilfe › Unterstützen …** zeigt, wie du die
Arbeit mit einem Kaffee unterstützen kannst. Dadurch wird nichts freigeschaltet.

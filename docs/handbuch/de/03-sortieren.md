# Sortieren und Benennen

## Namensvorschlag

Für die gewählte PDF schlägt PDFSM einen Dateinamen vor. Dafür nutzt es das erkannte **Datum**
(z. B. 12.03.2026 oder „März 2026“), die **Kategorie** (Rechnung, Vertrag, Versicherung, Bank,
Gehalt, Steuer …), den **Absender** und deine bisherigen Umbenennungen.

Beispiel: Aus `scan_0042.pdf` wird `2026-03-12_Stadtwerke Musterstadt_Stromrechnung.pdf`.

## Umbenennen

- `F2` öffnet den Dialog **Umbenennen…**. Dort lässt sich ein eigenes **Dateinamen-Muster** mit
  Platzhaltern wie `{datum}_{kontakt}_{betreff}` vorgeben, mit Live-Vorschau. Die KI füllt das
  Muster aus.
- Die Grundeinstellungen dazu stehen unter **Einstellungen › Dateinamen**.

## Verschieben

- **Ein Klick** auf einen Zielordner verschiebt die PDF, benennt sie um und speichert die
  Metadaten.
- Mit dem Schalter **„Nur verschieben“** bleibt der Dateiname, wie er ist.
- Eine PDF kann auch in **mehrere Ordner** kopiert werden.

## Metadaten in der PDF

Kategorie, Korrespondent, Betrag (netto und brutto), MwSt, IBAN, Steuerjahr und eine
Zusammenfassung schreibt PDFSM als **XMP-Metadaten in die PDF selbst**. Das ist ein
ISO-Standard; die Angaben bleiben beim Kopieren und Umziehen erhalten. Zusätzlich landen sie im
Suchindex.

Mit eingerichteter KI füllt PDFSM die Felder selbst aus; der Knopf „KI-Metadaten neu
generieren“ fragt die KI noch einmal.

## Korrespondenten

Der Reiter **„Korrespondenten“** links verwaltet die Absender: Name, andere Schreibweisen
(Aliase), Kategorie und Farbe. Ein Klick auf einen Korrespondenten filtert die PDF-Liste.

## Steuerauswertung

**Extras › Steuerauswertung…** zeigt Jahressummen nach Kategorie (brutto, netto, absetzbar) und
exportiert sie als CSV-Datei, z. B. für die Steuererklärung.

Weiter: [Stapeln, Trennen und Seiten](04-stapeln-trennen.md)

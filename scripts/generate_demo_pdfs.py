"""Erzeugt fiktive Demo-PDFs fuer Beta-Tester (Issue #52).

Zweck:
    Erstellt einen bunten Satz deutscher Beispiel-Dokumente (Rechnungen,
    Vertraege, Kontoauszug, Gehaltsabrechnung, gescannte Kassenbelege ohne
    Textlayer usw.) und packt sie in ein ZIP-Archiv. Alle Firmen, Personen,
    IBANs und Betraege sind frei erfunden.

Verwendung:
    python scripts/generate_demo_pdfs.py [--out data/demo]

Ausgabe:
    <out>/Demo_PDFs/*.pdf  und  <out>/PDFSM_Demo_PDFs.zip

Exit-Code: 0 bei Erfolg, 1 bei Fehler.
"""

import argparse
import sys
import zipfile
from pathlib import Path

import fitz  # PyMuPDF

A4 = (595, 842)
RECEIPT = (226, 520)

# Eine Zeile ist entweder ein str (10pt, normal) oder ein Tupel (text, size, bold).
H1 = lambda t: (t, 16, True)
H2 = lambda t: (t, 12, True)
B = lambda t: (t, 10, True)
SMALL = lambda t: (t, 8, False)


def _render(doc: fitz.Document, pages, pagesize, font="helv", margin=50):
    for page_lines in pages:
        page = doc.new_page(width=pagesize[0], height=pagesize[1])
        y = margin
        for line in page_lines:
            if isinstance(line, str):
                text, size, bold = line, 10, False
            else:
                text, size, bold = line
            y += size * 1.45
            if text:
                fontname = {"helv": "hebo", "cour": "cobo"}[font] if bold else font
                page.insert_text((margin, y), text, fontsize=size,
                                 fontname=fontname, color=(0.15, 0.15, 0.15))


def make_pdf(path: Path, pages, pagesize=A4, font="helv", margin=50):
    """Normales PDF mit Textlayer."""
    doc = fitz.open()
    _render(doc, pages, pagesize, font, margin)
    doc.save(path)
    doc.close()


def make_scan(path: Path, pages, pagesize=A4, font="helv", margin=50):
    """Simulierter Scan: Seiten werden als Graustufen-JPEG eingebettet,
    es gibt keinen Textlayer -> OCR noetig."""
    src = fitz.open()
    _render(src, pages, pagesize, font, margin)
    out = fitz.open()
    for src_page in src:
        pix = src_page.get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csGRAY)
        jpg = pix.tobytes("jpg", jpg_quality=55)
        page = out.new_page(width=pagesize[0], height=pagesize[1])
        page.insert_image(page.rect, stream=jpg)
    out.save(path)
    src.close()
    out.close()


# ---------------------------------------------------------------------------
# Dokument-Definitionen (alles fiktiv)
# ---------------------------------------------------------------------------

def _brief_kopf(firma, zeilen_absender, empfaenger=True):
    kopf = [H1(firma)] + [SMALL(z) for z in zeilen_absender] + [""]
    if empfaenger:
        kopf += ["Max Mustermann", "Musterstrasse 12", "12345 Musterstadt", "", ""]
    return kopf


DOCUMENTS = [
    # --- Handwerker-Rechnung ---
    dict(filename="2024-03-15_Rechnung_Elektro-Blitz.pdf", scan=False, pages=[
        _brief_kopf("Elektro Blitz GmbH",
                    ["Gewerbering 7, 12345 Musterstadt", "USt-IdNr. DE123456789"]) + [
            H2("Rechnung Nr. RE-2024-0187"),
            "Rechnungsdatum: 15.03.2024",
            "Kundennummer: K-10442",
            "",
            "Pos. 1  Austausch Sicherungskasten          320,00 EUR",
            "Pos. 2  Anfahrtspauschale                    35,00 EUR",
            "Pos. 3  Kleinmaterial                        65,00 EUR",
            "",
            "Rechnungsbetrag netto:                      420,00 EUR",
            "zzgl. 19% MwSt:                              79,80 EUR",
            B("Rechnungsbetrag brutto:                     499,80 EUR"),
            "",
            "Zahlbar innerhalb von 14 Tagen ohne Abzug auf folgendes Konto:",
            "IBAN: DE89 3704 0044 0532 0130 00",
            "BIC: MUSDE44XXX",
            "",
            SMALL("Elektro Blitz GmbH - Amtsgericht Musterstadt HRB 4711"),
        ],
    ]),

    # --- Energie-Jahresabrechnung ---
    dict(filename="Stadtwerke_Jahresabrechnung_2023.pdf", scan=False, pages=[
        _brief_kopf("Stadtwerke Musterstadt GmbH",
                    ["Energieallee 1, 12345 Musterstadt"]) + [
            H2("Jahresabrechnung Strom 2023"),
            "Vertragskonto: 300512477",
            "Verbrauchsstelle: Musterstrasse 12, 12345 Musterstadt",
            "Abrechnungszeitraum: 01.01.2023 - 31.12.2023",
            "",
            "Zaehlernummer: 1EMH0044712233",
            "Zaehlerstand alt (01.01.2023):  14.212 kWh",
            "Zaehlerstand neu (31.12.2023):  17.059 kWh",
            "Verbrauch: 2.847 kWh",
            "",
            "Arbeitspreis 2.847 kWh x 0,32 EUR/kWh:      911,04 EUR",
            "Grundpreis 12 Monate:                        144,00 EUR",
            "Summe netto:                                 913,00 EUR",
            "zzgl. 19% MwSt:                              173,45 EUR",
            B("Rechnungsbetrag brutto:                    1.086,45 EUR"),
            "abzgl. gezahlte Abschlaege:                 -960,00 EUR",
            B("Nachzahlung:                                 126,45 EUR"),
            "",
            "Ihr neuer monatlicher Abschlag betraegt 92,00 EUR.",
        ],
    ]),

    # --- Mobilfunkrechnung ---
    dict(filename="Mobilfunk_Rechnung_April_2024.pdf", scan=False, pages=[
        _brief_kopf("TeleFix GmbH", ["Netzstrasse 99, 60311 Frankfurt"]) + [
            H2("Mobilfunk-Rechnung April 2024"),
            "Rechnungsnummer: TF-2024-04-887201",
            "Kundennummer: 55817744",
            "Rufnummer: 0171 5551234",
            "",
            "Grundgebuehr Tarif SmartM:                    19,99 EUR",
            "Auslandsverbindungen:                          3,12 EUR",
            "Summe netto:                                  19,42 EUR",
            "zzgl. 19% MwSt:                                3,69 EUR",
            B("Rechnungsbetrag:                              23,11 EUR"),
            "",
            "Der Betrag wird am 02.05.2024 von Ihrem Konto abgebucht.",
            "IBAN: DE02 1203 0000 0000 2020 51",
        ],
    ]),

    # --- Versicherungspolice ---
    dict(filename="Police_Privathaftpflicht_2024.pdf", scan=False, pages=[
        _brief_kopf("Sicherheits-Versicherung AG",
                    ["Assekuranzplatz 3, 50667 Koeln"]) + [
            H2("Versicherungsschein Privathaftpflicht"),
            "Versicherungsschein-Nr. (Police): HV-556677-2024",
            "Versicherungsnehmer: Max Mustermann",
            "Versicherungsbeginn: 01.01.2024",
            "",
            "Deckungssumme pauschal: 10.000.000 EUR",
            "Selbstbeteiligung: keine",
            "",
            B("Jahrespraemie inkl. Versicherungsteuer: 89,40 EUR"),
            "Zahlweise: jaehrlich",
            "",
            "Die Praemie wird jeweils zum 01.01. faellig.",
        ],
    ]),

    # --- Kontoauszug (2 Seiten) ---
    dict(filename="Kontoauszug_2024_03.pdf", scan=False, pages=[
        _brief_kopf("Musterbank eG", ["Bankgasse 8, 12345 Musterstadt"],
                    empfaenger=False) + [
            H2("Kontoauszug Nr. 3/2024"),
            "Kontoinhaber: Max Mustermann",
            "IBAN: DE21 3012 0400 0000 0157 78",
            "BIC: MUSDE44XXX",
            "Zeitraum: 01.03.2024 - 31.03.2024",
            "",
            "Alter Saldo:                              2.418,77 EUR",
            "",
            "01.03. Gehalt Beispiel Software GmbH     +2.871,34 EUR",
            "04.03. Miete Hausverwaltung Krause       -1.050,00 EUR",
            "05.03. Lastschrift TeleFix GmbH             -23,11 EUR",
            "11.03. Kartenzahlung Supermarkt Meier       -83,29 EUR",
            "15.03. Ueberweisung Elektro Blitz GmbH     -499,80 EUR",
        ],
        [
            H2("Kontoauszug Nr. 3/2024 - Seite 2"),
            "",
            "18.03. Kartenzahlung Tank und Go            -78,90 EUR",
            "22.03. Abschlag Stadtwerke Musterstadt      -92,00 EUR",
            "28.03. Gutschrift Finanzamt Musterstadt  +1.234,56 EUR",
            "",
            B("Neuer Saldo:                              4.697,57 EUR"),
            "",
            SMALL("Dieser Kontoauszug gilt als Buchungsbestaetigung."),
        ],
    ]),

    # --- Gehaltsabrechnung ---
    dict(filename="Gehaltsabrechnung_2024_02.pdf", scan=False, pages=[
        _brief_kopf("Beispiel Software GmbH",
                    ["Codeweg 42, 80331 Muenchen"], empfaenger=False) + [
            H2("Entgeltabrechnung Februar 2024"),
            "Mitarbeiter: Max Mustermann, Personal-Nr. 1042",
            "Steuerklasse: I    Steuer-ID: 12 345 678 901",
            "",
            "Grundgehalt:                              4.500,00 EUR",
            B("Gesamt-Brutto:                            4.500,00 EUR"),
            "",
            "Lohnsteuer:                                -812,41 EUR",
            "Solidaritaetszuschlag:                        0,00 EUR",
            "Krankenversicherung:                       -366,75 EUR",
            "Rentenversicherung:                        -418,50 EUR",
            "Arbeitslosenversicherung:                   -58,50 EUR",
            "Pflegeversicherung:                         -76,50 EUR",
            "",
            B("Auszahlungsbetrag (Netto):                2.871,34 EUR"),
            "",
            "Auszahlung auf IBAN DE21 3012 0400 0000 0157 78",
        ],
    ]),

    # --- Steuerbescheid (2 Seiten) ---
    dict(filename="Einkommensteuerbescheid_2023.pdf", scan=False, pages=[
        _brief_kopf("Finanzamt Musterstadt",
                    ["Fiskalstrasse 1, 12345 Musterstadt"]) + [
            H2("Bescheid fuer 2023 ueber Einkommensteuer"),
            "Steuernummer: 123/456/78901",
            "Identifikationsnummer: 12 345 678 901",
            "Bescheiddatum: 20.03.2024",
            "",
            "Festsetzung:",
            "Einkommensteuer:                          7.412,00 EUR",
            "Solidaritaetszuschlag:                        0,00 EUR",
            "",
            "Bereits gezahlt (Lohnsteuer):             8.646,56 EUR",
            B("Erstattungsbetrag:                        1.234,56 EUR"),
            "",
            "Der Betrag wird auf das uns bekannte Konto ueberwiesen.",
        ],
        [
            H2("Erlaeuterungen zum Bescheid - Seite 2"),
            "",
            "Der Bescheid ergeht unter dem Vorbehalt der Nachpruefung",
            "gemaess Paragraph 164 Abs. 1 AO.",
            "",
            "Rechtsbehelfsbelehrung: Gegen diesen Bescheid kann innerhalb",
            "eines Monats nach Bekanntgabe Einspruch eingelegt werden.",
        ],
    ]),

    # --- Arztrechnung ---
    dict(filename="Arztrechnung_Dr_Schmidt.pdf", scan=False, pages=[
        _brief_kopf("Praxis Dr. med. Julia Schmidt",
                    ["Facharzt fuer Allgemeinmedizin",
                     "Heilweg 5, 12345 Musterstadt"]) + [
            H2("Privatrechnung / Liquidation"),
            "Rechnungsnummer: 2024-0331",
            "Behandlungsdatum: 12.02.2024",
            "Patient: Max Mustermann, geb. 01.01.1985",
            "",
            "GOAe 1    Beratung                            10,72 EUR",
            "GOAe 5    Symptombezogene Untersuchung         10,72 EUR",
            "GOAe 250  Blutentnahme                          4,66 EUR",
            "GOAe 4711 Laborleistungen                     130,62 EUR",
            "",
            B("Rechnungsbetrag:                             156,72 EUR"),
            "",
            "Aerztliche Leistungen sind gemaess Paragraph 4 Nr. 14 UStG",
            "umsatzsteuerfrei.",
            "Zahlbar innerhalb von 30 Tagen.",
        ],
    ]),

    # --- Mietvertrag (3 Seiten) ---
    dict(filename="Mietvertrag_Musterstrasse_12.pdf", scan=False, pages=[
        [
            H1("Mietvertrag"),
            "",
            "zwischen",
            "Hausverwaltung Krause GmbH, Immobilienweg 2, 12345 Musterstadt",
            "(Vermieter)",
            "",
            "und",
            "Max Mustermann",
            "(Mieter)",
            "",
            H2("Paragraph 1 Mietobjekt"),
            "Vermietet wird die Wohnung Musterstrasse 12, 2. OG links,",
            "12345 Musterstadt, bestehend aus 3 Zimmern, Kueche, Bad.",
            "Wohnflaeche: ca. 78 qm.",
        ],
        [
            H2("Paragraph 2 Mietzeit"),
            "Das Mietverhaeltnis beginnt am 01.06.2021 und laeuft auf",
            "unbestimmte Zeit.",
            "",
            H2("Paragraph 3 Miete und Nebenkosten"),
            "Die monatliche Kaltmiete betraegt 850,00 EUR.",
            "Nebenkostenvorauszahlung: 200,00 EUR.",
            B("Gesamtmiete: 1.050,00 EUR, faellig zum 3. Werktag."),
            "",
            H2("Paragraph 4 Kaution"),
            "Der Mieter leistet eine Kaution in Hoehe von 2.550,00 EUR.",
        ],
        [
            H2("Paragraph 5 Schoenheitsreparaturen"),
            "Die Schoenheitsreparaturen traegt der Mieter.",
            "",
            H2("Paragraph 6 Kuendigung"),
            "Es gelten die gesetzlichen Kuendigungsfristen.",
            "",
            "",
            "Musterstadt, den 15.05.2021",
            "",
            "____________________          ____________________",
            "Vermieter                     Mieter",
        ],
    ]),

    # --- DSL-Vertrag ---
    dict(filename="DSL_Auftragsbestaetigung.pdf", scan=False, pages=[
        _brief_kopf("TeleFix GmbH", ["Netzstrasse 99, 60311 Frankfurt"]) + [
            H2("Auftragsbestaetigung DSL-Vertrag"),
            "Vertragsnummer: DSL-2024-118844",
            "Tarif: FixDSL 100",
            "",
            "Monatlicher Grundpreis: 39,99 EUR (inkl. 19% MwSt)",
            "Mindestvertragslaufzeit: 24 Monate",
            "Bereitstellungstermin: 02.05.2024",
            "",
            "Der Vertrag verlaengert sich nach Ablauf der Mindestlaufzeit",
            "auf unbestimmte Zeit und ist monatlich kuendbar.",
        ],
    ]),

    # --- Spendenquittung ---
    dict(filename="Spendenquittung_Tierheim_2024.pdf", scan=False, pages=[
        _brief_kopf("Tierheim Musterstadt e.V.",
                    ["Am Waldrand 20, 12345 Musterstadt"]) + [
            H2("Zuwendungsbestaetigung (Spendenquittung)"),
            "",
            "Wir bestaetigen, dass uns Max Mustermann am 10.01.2024",
            "eine Geldzuwendung in Hoehe von",
            B("100,00 EUR (in Worten: einhundert Euro)"),
            "zugewendet hat.",
            "",
            "Die Zuwendung wird fuer steuerbeguenstigte Zwecke verwendet.",
            "Der Verein ist nach dem Freistellungsbescheid des Finanzamts",
            "Musterstadt, StNr. 123/456/00099, von der Koerperschaftsteuer",
            "befreit. Die Spende ist steuerlich absetzbar.",
        ],
    ]),

    # --- Nebenkostenabrechnung ---
    dict(filename="Nebenkostenabrechnung_2023.pdf", scan=False, pages=[
        _brief_kopf("Hausverwaltung Krause GmbH",
                    ["Immobilienweg 2, 12345 Musterstadt"]) + [
            H2("Betriebskostenabrechnung 2023"),
            "Objekt: Musterstrasse 12, 2. OG links",
            "Abrechnungszeitraum: 01.01.2023 - 31.12.2023",
            "",
            "Heizkosten:                                  912,40 EUR",
            "Wasser / Abwasser:                           388,12 EUR",
            "Grundsteuer:                                 240,00 EUR",
            "Hausmeister / Reinigung:                     402,36 EUR",
            "Summe Ihrer Kosten:                        2.542,88 EUR",
            "Geleistete Vorauszahlungen:               -2.400,00 EUR",
            B("Nachzahlung:                                 142,88 EUR"),
            "",
            "Bitte ueberweisen Sie den Betrag bis zum 30.06.2024.",
        ],
    ]),

    # --- Online-Bestellung ---
    dict(filename="Bestellung_74522148_Rechnung.pdf", scan=False, pages=[
        _brief_kopf("Bestellhaus24 GmbH",
                    ["Logistikpark 5, 04347 Leipzig", "USt-IdNr. DE987654321"]) + [
            H2("Rechnung zur Bestellung 74522148"),
            "Rechnungsnummer: BH24-2024-74522148",
            "Bestelldatum: 02.06.2024",
            "",
            "1x USB-C Dockingstation                       49,99 EUR",
            "1x HDMI-Kabel 2m                              14,99 EUR",
            "Versandkosten:                                 0,00 EUR",
            "",
            B("Gesamtbetrag:                                 64,98 EUR"),
            "enthaltene MwSt (19%):                        10,38 EUR",
            "",
            "Bezahlt per Lastschrift. Vielen Dank fuer Ihre Bestellung!",
        ],
    ]),

    # --- Mahnung ---
    dict(filename="Mahnung_2_TeleFix.pdf", scan=False, pages=[
        _brief_kopf("TeleFix GmbH", ["Netzstrasse 99, 60311 Frankfurt"]) + [
            H2("2. Mahnung"),
            "Rechnungsnummer: TF-2024-01-771034 vom 05.01.2024",
            "",
            "trotz unserer Zahlungserinnerung konnten wir bisher keinen",
            "Zahlungseingang feststellen.",
            "",
            "Offener Rechnungsbetrag:                      23,11 EUR",
            "Mahngebuehr:                                   5,00 EUR",
            B("Zu zahlender Gesamtbetrag:                    28,11 EUR"),
            "",
            "Bitte zahlen Sie bis spaetestens 15.02.2024 auf:",
            "IBAN: DE02 1203 0000 0000 2020 51",
            "Andernfalls behalten wir uns weitere Schritte vor.",
        ],
    ]),

    # --- Kostenvoranschlag ---
    dict(filename="Kostenvoranschlag_Badsanierung.pdf", scan=False, pages=[
        _brief_kopf("Sanitaer Wagner Meisterbetrieb",
                    ["Rohrgasse 11, 12345 Musterstadt"]) + [
            H2("Kostenvoranschlag Nr. KV-2024-031"),
            "Bauvorhaben: Badsanierung Musterstrasse 12",
            "",
            "Demontage Altbestand:                        480,00 EUR",
            "Installation Sanitaerobjekte:              1.650,00 EUR",
            "Fliesenarbeiten:                           1.350,00 EUR",
            "",
            "Summe netto:                               3.480,00 EUR",
            "zzgl. 19% MwSt:                              661,20 EUR",
            B("Gesamtsumme brutto:                        4.141,20 EUR"),
            "",
            "Dieser Kostenvoranschlag ist unverbindlich und 8 Wochen gueltig.",
        ],
    ]),

    # --- Bahnticket ---
    dict(filename="Bahnticket_2024-05-06.pdf", scan=False, pages=[
        [
            H1("Schnellzug AG"),
            SMALL("Online-Ticket / Rechnung"),
            "",
            H2("Fahrkarte Musterstadt -> Berlin Hbf"),
            "Auftragsnummer: SZ7K4M",
            "Reisedatum: 06.05.2024, Abfahrt 08:12 Uhr",
            "1 Erwachsener, 2. Klasse, Sparpreis",
            "",
            B("Gesamtpreis: 76,90 EUR"),
            "enthaltene MwSt (7%):                          5,03 EUR",
            "",
            SMALL("Dieses Ticket ist nur mit Identifikation gueltig."),
        ],
    ]),

    # --- Englische Rechnung (wild card) ---
    dict(filename="Invoice_CloudServe_2024-07.pdf", scan=False, pages=[
        [
            H1("CloudServe Ltd."),
            SMALL("221 Fictional Road, London, United Kingdom"),
            "",
            H2("Invoice #CS-2024-07-9912"),
            "Invoice date: 2024-07-01",
            "Billed to: Max Mustermann, Musterstrasse 12, Germany",
            "",
            "Cloud hosting plan 'Starter', July 2024      24.00 USD",
            "",
            B("Total due: 24.00 USD"),
            "VAT reverse charge - tax to be accounted for by the recipient.",
            "",
            "Payment received via credit card. Thank you!",
        ],
    ]),

    # --- Kuendigungsschreiben mit Scanner-Dateinamen ---
    dict(filename="Dokument (3).pdf", scan=False, pages=[
        [
            "Max Mustermann",
            "Musterstrasse 12",
            "12345 Musterstadt",
            "",
            "FitFabrik Musterstadt GmbH",
            "Hantelweg 3",
            "12345 Musterstadt",
            "",
            "Musterstadt, 04.04.2024",
            "",
            H2("Kuendigung meiner Mitgliedschaft Nr. 88451"),
            "",
            "hiermit kuendige ich meinen Vertrag fristgerecht zum",
            "naechstmoeglichen Zeitpunkt. Bitte bestaetigen Sie mir die",
            "Kuendigung und das Vertragsende schriftlich.",
            "",
            "Mit freundlichen Gruessen",
            "Max Mustermann",
        ],
    ]),

    # --- Gescannte Kassenbelege (kein Textlayer) ---
    dict(filename="Scan_0001.pdf", scan=True, pagesize=RECEIPT, font="cour",
         margin=15, pages=[
        [
            ("SUPERMARKT MEIER", 11, True),
            SMALL("Marktplatz 4, 12345 Musterstadt"),
            SMALL("Tel. 01234/55667"),
            "",
            ("12.03.2024  17:42   Kasse 2", 8, False),
            "",
            ("Vollmilch 3,5%        1,09 B", 9, False),
            ("Brot Roggen           2,49 B", 9, False),
            ("Kaffee 500g           6,99 B", 9, False),
            ("Spuelmittel           1,79 A", 9, False),
            ("Aepfel 1,2kg          3,58 B", 9, False),
            ("Schokolade            1,49 B", 9, False),
            ("Zahnpasta             2,95 A", 9, False),
            ("Bananen 0,9kg         1,62 B", 9, False),
            ("Kaese Gouda           2,47 B", 9, False),
            "",
            ("SUMME EUR            24,47", 10, True),
            ("Kartenzahlung        24,47", 9, False),
            "",
            SMALL("A = 19% MwSt   1,08"),
            SMALL("B = 7% MwSt    1,32"),
            "",
            SMALL("Vielen Dank fuer Ihren Einkauf!"),
        ],
    ]),
    dict(filename="Scan_0002.pdf", scan=True, pagesize=RECEIPT, font="cour",
         margin=15, pages=[
        [
            ("TANK UND GO", 11, True),
            SMALL("Autobahnring 2, 12345 Musterstadt"),
            "",
            ("18.03.2024  07:55", 8, False),
            ("Beleg-Nr. 4471", 8, False),
            "",
            ("Diesel", 9, False),
            ("45,20 L x 1,745 EUR/L", 9, False),
            "",
            ("SUMME EUR            78,87", 10, True),
            ("gegeben Karte        78,87", 9, False),
            "",
            SMALL("enth. 19% MwSt 12,59 EUR"),
            SMALL("TSE-Signatur 8f31a0c2"),
            "",
            SMALL("Gute Fahrt!"),
        ],
    ]),

    # --- Gescannte Rechnung (A4, kein Textlayer) ---
    dict(filename="Scan_0003.pdf", scan=True, pages=[
        _brief_kopf("Gartenbau Gruen und Sohn",
                    ["Baumschulweg 9, 12345 Musterstadt"]) + [
            H2("Rechnung Nr. 2024-77"),
            "Rechnungsdatum: 22.04.2024",
            "",
            "Heckenschnitt und Entsorgung:               240,00 EUR",
            "Summe netto:                                240,00 EUR",
            "zzgl. 19% MwSt:                              45,60 EUR",
            B("Rechnungsbetrag:                             285,60 EUR"),
            "",
            "Zahlbar innerhalb 10 Tagen.",
            "IBAN: DE45 5001 0517 5407 3249 31",
        ],
    ]),

    # --- Gescannter Behoerdenbrief (kein Textlayer) ---
    dict(filename="IMG_4711.pdf", scan=True, pages=[
        _brief_kopf("Stadtverwaltung Musterstadt",
                    ["Rathausplatz 1, 12345 Musterstadt", "Steueramt"]) + [
            H2("Bescheid ueber Hundesteuer 2024"),
            "Kassenzeichen: 9.4711.0815",
            "",
            "Fuer das Halten eines Hundes wird die Hundesteuer fuer das",
            "Jahr 2024 festgesetzt auf:",
            B("96,00 EUR"),
            "",
            "Faelligkeit: 01.07.2024",
            "Bitte ueberweisen Sie unter Angabe des Kassenzeichens an die",
            "Stadtkasse Musterstadt, IBAN DE12 3456 7800 0000 4711 00.",
        ],
    ]),

    # --- Sammelscan: zwei Belege in einer Datei (zum Testen von Splitten) ---
    dict(filename="Sammelscan_Belege_2024.pdf", scan=True, pagesize=RECEIPT,
         font="cour", margin=15, pages=[
        [
            ("APOTHEKE AM MARKT", 11, True),
            SMALL("Marktplatz 1, 12345 Musterstadt"),
            "",
            ("05.02.2024  10:12", 8, False),
            "",
            ("Ibuprofen 400 20St    5,95", 9, False),
            ("Nasenspray            4,45", 9, False),
            "",
            ("SUMME EUR            10,40", 10, True),
            SMALL("enth. 19% MwSt 1,66 EUR"),
            "",
            SMALL("Gute Besserung!"),
        ],
        [
            ("BAUMARKT HAMMER", 11, True),
            SMALL("Industriestr. 17, 12345 Musterstadt"),
            "",
            ("09.02.2024  14:31", 8, False),
            "",
            ("Duebel-Set            4,99", 9, False),
            ("Wandfarbe 10L        32,99", 9, False),
            ("Abdeckfolie           2,49", 9, False),
            "",
            ("SUMME EUR            40,47", 10, True),
            SMALL("enth. 19% MwSt 6,46 EUR"),
        ],
    ]),
]

LIESMICH = """Demo-PDFs fuer PDF Sortier Meister
==================================

Dieses Archiv enthaelt {n} fiktive Beispiel-Dokumente zum Testen:
Rechnungen, Vertraege, Kontoauszug, Gehaltsabrechnung, Steuerbescheid,
Versicherungspolice sowie gescannte Kassenbelege ohne Textlayer
(Scan_*.pdf, IMG_*.pdf - hier muss die OCR-Erkennung ran).

Die Datei "Sammelscan_Belege_2024.pdf" enthaelt absichtlich zwei
verschiedene Belege in einer Datei (zum Testen der Split-Funktion).

Alle Firmen, Personen, Adressen, IBANs und Betraege sind frei erfunden.
Aehnlichkeiten mit echten Unternehmen waeren rein zufaellig.

Erzeugt mit scripts/generate_demo_pdfs.py (Issue #52).
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Demo-PDFs erzeugen (Issue #52)")
    parser.add_argument("--out", default="data/demo",
                        help="Ausgabeverzeichnis (Default: data/demo)")
    args = parser.parse_args()

    out_dir = Path(args.out)
    pdf_dir = out_dir / "Demo_PDFs"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    for spec in DOCUMENTS:
        path = pdf_dir / spec["filename"]
        kwargs = dict(pagesize=spec.get("pagesize", A4),
                      font=spec.get("font", "helv"),
                      margin=spec.get("margin", 50))
        if spec["scan"]:
            make_scan(path, spec["pages"], **kwargs)
        else:
            make_pdf(path, spec["pages"], **kwargs)
        print(f"  {path.name}")

    liesmich = pdf_dir / "LIESMICH.txt"
    liesmich.write_text(LIESMICH.format(n=len(DOCUMENTS)), encoding="utf-8")

    zip_path = out_dir / "PDFSM_Demo_PDFs.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(pdf_dir.iterdir()):
            zf.write(file, arcname=f"Demo_PDFs/{file.name}")

    print(f"\n{len(DOCUMENTS)} PDFs erzeugt in {pdf_dir}")
    print(f"ZIP: {zip_path} ({zip_path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""MCP-Server der Dokumentensuche: gibt KI-Assistenten (z. B. Claude) lesenden Zugriff auf den Index.

Start: ``pdfsm-dienst mcp`` (stdio). Servername ``pdfsuche`` und die
Werkzeugnamen ``suche``, ``dokument_lesen``, ``index_status`` bleiben wie beim
frueheren Programm PDFsuche, damit vorhandene Konfigurationen und Gewohnheiten
weiter funktionieren. Das Paket ``mcp`` wird erst beim Erzeugen des Servers
importiert.
"""

from __future__ import annotations

from src.search import ausgabe
from src.search.konfig import SearchConfig
from src.search.suchindex import Suchindex


def beschreibung(konfig: SearchConfig) -> str:
    """Anleitung fuer den KI-Assistenten; die durchsuchten Ordner kommen aus der Konfiguration."""
    orte = ", ".join(konfig.prioritaet + [w for w in konfig.wurzeln if w not in konfig.prioritaet]) or "den eingerichteten Ordnern"
    mails = " und Mails (Thunderbird, .eml, .msg)" if konfig.mails_aktiv else " und Mails (.eml, .msg)"
    return (
        "Lokaler Volltextindex über alle PDFs (inkl. OCR gescannter Dokumente), Word-/Excel-/OpenDocument-"
        f"Dateien (doc, docx, xls, xlsx, odt), Markdown-Dateien{mails} in: {orte}. "
        "Benutze 'suche' statt Dateisystemsuche mit grep/pdftotext – es ist um Größenordnungen schneller. "
        "Mit 'dokument_lesen' den Volltext eines Treffers holen."
    )


# --------------------------------------------------------------------------- Werkzeuge (reine Funktionen, testbar)

def werkzeug_suche(idx: Suchindex, abfrage: str, typ: str | None = None, ordner: str | None = None,
                   von: str | None = None, bis: str | None = None, sortierung: str = "relevanz",
                   anzahl: int = 20) -> str:
    erg = idx.suche(abfrage, typ=typ, ordner=ordner, von=von, bis=bis, sortierung=sortierung,
                    anzahl=max(1, min(int(anzahl), 200)))
    return ausgabe.ergebnisse(erg, abfrage)


def werkzeug_dokument_lesen(idx: Suchindex, dok_id: int, seiten: str | None = None, max_zeichen: int = 40000) -> str:
    return ausgabe.dokument_text(idx, int(dok_id), seiten, int(max_zeichen))


def werkzeug_index_status(idx: Suchindex) -> str:
    return ausgabe.status_text(idx)


def erstelle_server(konfig: SearchConfig):
    from mcp.server.mcpserver import MCPServer

    idx = Suchindex(konfig)
    server = MCPServer("pdfsuche", instructions=beschreibung(konfig))

    @server.tool()
    def suche(abfrage: str, typ: str | None = None, ordner: str | None = None, von: str | None = None,
              bis: str | None = None, sortierung: str = "relevanz", anzahl: int = 20) -> str:
        """Volltextsuche im lokalen Dokumentenindex.

        abfrage: Suchbegriffe. Mehrere Wörter = alle müssen vorkommen. Syntax: "genaue Phrase",
                 ODER/OR, NICHT/NOT, Klammern, Präfix mit * (z. B. Unterhalt*), NEAR(a b, 10).
                 Umlaute/Akzente werden ignoriert (Muller findet Müller).
        typ: 'pdf', 'md', 'mail', 'office' (doc/docx/xls/xlsx/odt) oder Kombination 'pdf,office'
        ordner: Teil des Dateipfads bzw. Postfachnamens, z. B. 'Steuer' oder 'gmx'
        von / bis: Datum JJJJ-MM-TT (Mail-Datum bzw. Datei-Änderungsdatum)
        sortierung: 'relevanz' | 'neu' | 'alt'
        anzahl: maximale Zahl an Dokumenten (Standard 20)
        Ergebnis: je Dokument [ID], Pfad und Textausschnitte mit «Fundstelle» und Seitenzahl.
        """
        return werkzeug_suche(idx, abfrage, typ, ordner, von, bis, sortierung, anzahl)

    @server.tool()
    def dokument_lesen(dok_id: int, seiten: str | None = None, max_zeichen: int = 40000) -> str:
        """Volltext eines Dokuments aus dem Index (ID aus 'suche').

        seiten: optional '3' oder '2-5' (nur PDFs). Lange Dokumente seitenweise lesen.
        """
        return werkzeug_dokument_lesen(idx, dok_id, seiten, max_zeichen)

    @server.tool()
    def index_status() -> str:
        """Stand des Index: Anzahl Dokumente, OCR-Fortschritt, letzter Lauf."""
        return werkzeug_index_status(idx)

    return server


def main(konfig: SearchConfig | None = None) -> int:
    if konfig is None:
        from src.search import konfig as konfig_modul
        konfig = konfig_modul.lade()
    erstelle_server(konfig).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

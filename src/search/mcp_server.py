"""MCP-Server der Dokumentensuche: gibt KI-Assistenten (z. B. Claude) lesenden Zugriff auf den Index.

Start: ``pdfsm-dienst mcp`` (stdio). Servername ``pdfsuche`` und die
Werkzeugnamen ``suche``, ``dokument_lesen``, ``index_status`` bleiben wie beim
frueheren Programm PDFsuche, damit vorhandene Konfigurationen und Gewohnheiten
weiter funktionieren. Das Paket ``mcp`` wird erst beim Erzeugen des Servers
importiert.

Seit Baustein 1 (``docs/CHAT_MCP_PLAN.md``) kann ein MCP-Client alles, was das
Chat-Modell im Programm kann: dazu kommen ``ordner_vorschlag``,
``korrespondent_info`` und - nur wenn im Programm freigegeben
(``chat.sql_erlaubt``) - ``sql_abfrage``. Die Logik teilen sich Chat und
Server (:mod:`src.rag.werkzeug_kern`); der Server zeigt Index-IDs statt der
D-Nummern des Chats. Historie und Korrespondenten liest
:class:`~src.search.pdfsm_daten.PdfsmDaten` schreibgeschuetzt aus der
Hauptdatenbank. Alle Werkzeuge sind als nur lesend markiert
(``readOnlyHint``); keines veraendert Dateien oder Datenbanken.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path

from src.core.similar_documents import relative_folder, resolve_relative_folder
from src.rag import werkzeug_kern as kern
from src.rag.werkzeug_kern import (
    AEHNLICHKEIT_TEXT_ZEICHEN,
    SQL_ZEITLIMIT_STANDARD_S,
    Dokument,
    OrdnerVorschlag,
    WerkzeugFehler,
)
from src.search import ausgabe
from src.search.konfig import SearchConfig
from src.search.pdfsm_daten import PdfsmDaten
from src.search.suchindex import Suchindex

# Suche ueber MCP: mehr Treffer als im Chat (der Assistent hat mehr Platz)
SUCHE_ANZAHL_STANDARD = 20
SUCHE_ANZAHL_MAX = 200


@dataclass
class Umgebung:
    """Was der Server ausser der Suchkonfiguration aus der ``config.json`` von PDF Sortier Meister braucht.

    Attributes:
        db_pfad: Hauptdatenbank (``history.db``) fuer Historie und
            Korrespondenten; ``None`` = keine (z. B. alte ``config.toml``).
        zielordner: Zielordner; Ablageorte werden relativ dazu angegeben.
        scan_ordner: Scan-Eingang (unsortierte Dokumente).
        sql_erlaubt: Werkzeug ``sql_abfrage`` anbieten (derselbe Schalter wie im Chat).
        sql_zeitlimit_s: Zeitlimit einer SQL-Abfrage.
    """

    db_pfad: Path | None = None
    zielordner: list[Path] = field(default_factory=list)
    scan_ordner: Path | None = None
    sql_erlaubt: bool = False
    sql_zeitlimit_s: float = SQL_ZEITLIMIT_STANDARD_S


def umgebung_aus_config(cfg) -> Umgebung:
    """Umgebung aus einer :class:`src.utils.config.Config`."""
    return Umgebung(
        db_pfad=Path(cfg.database_path),
        # Leere Eintraege nicht zu Path(".") machen (get_target_folders wuerde das tun)
        zielordner=[Path(p) for p in (cfg.get("target_folders", []) or []) if str(p).strip()],
        scan_ordner=cfg.get_scan_folder(),
        sql_erlaubt=bool(cfg.get_chat_config().sql_erlaubt),
    )


def lade_umgebung(pfad: str | None = None) -> Umgebung:
    """Umgebung wie ``konfig.lade``: ``config.json`` am Standardort oder ``pfad``; eine ``config.toml`` hat keine."""
    if pfad and str(pfad).lower().endswith(".toml"):
        return Umgebung()
    from src.utils.config import Config, get_config

    return umgebung_aus_config(Config(pfad) if pfad else get_config())


def beschreibung(konfig: SearchConfig, umgebung: Umgebung | None = None) -> str:
    """Anleitung fuer den KI-Assistenten; die durchsuchten Ordner kommen aus der Konfiguration."""
    umgebung = umgebung or Umgebung()
    orte = ", ".join(konfig.prioritaet + [w for w in konfig.wurzeln if w not in konfig.prioritaet]) or "den eingerichteten Ordnern"
    mails = " und Mails (Thunderbird, .eml, .msg)" if konfig.mails_aktiv else " und Mails (.eml, .msg)"
    text = (
        "Lokaler Volltextindex über alle PDFs (inkl. OCR gescannter Dokumente), Word-/Excel-/OpenDocument-"
        f"Dateien (doc, docx, xls, xlsx, odt), Markdown-Dateien{mails} in: {orte}. "
        "Benutze 'suche' statt Dateisystemsuche mit grep/pdftotext – es ist um Größenordnungen schneller. "
        "Mit 'dokument_lesen' den Volltext eines Treffers holen."
    )
    eingang = f" im Scan-Eingang ({umgebung.scan_ordner})" if umgebung.scan_ordner else " im Scan-Eingang"
    text += (
        f" 'ordner_vorschlag' klärt, in welchen Ordner ein Dokument gehört – vor allem für unsortierte Dokumente"
        f"{eingang}: ähnliche, bereits einsortierte Dokumente mit Ordner und Jahr und der aktuelle Ablageort "
        "(ID aus 'suche'). 'korrespondent_info' zeigt, was PDF Sortier Meister über einen Absender gelernt hat "
        "(Schreibweisen, Kategorie, MwSt) – nützlich für den Filter korrespondent der Suche."
    )
    if umgebung.zielordner:
        text += " Zielordner: " + ", ".join(str(z) for z in umgebung.zielordner) + "."
    if umgebung.sql_erlaubt:
        text += " Für Auswertungen (Summen, Zählungen, Listen nach Betrag oder Datum) gibt es 'sql_abfrage'."
    text += " Alle Werkzeuge lesen nur; nichts wird verschoben, umbenannt oder verändert."
    return text


# --------------------------------------------------------------------------- Werkzeuge (reine Funktionen, testbar)

def werkzeug_suche(idx: Suchindex, abfrage: str, typ: str | None = None, ordner: str | None = None,
                   von: str | None = None, bis: str | None = None, sortierung: str = "relevanz",
                   anzahl: int = SUCHE_ANZAHL_STANDARD, steuerjahr: str | None = None, kategorie: str | None = None,
                   korrespondent: str | None = None) -> str:
    try:
        args = kern.such_argumente(
            {"abfrage": abfrage, "typ": typ, "ordner": ordner, "von": von, "bis": bis, "sortierung": sortierung,
             "anzahl": anzahl, "steuerjahr": steuerjahr, "kategorie": kategorie, "korrespondent": korrespondent},
            anzahl_standard=SUCHE_ANZAHL_STANDARD, anzahl_max=SUCHE_ANZAHL_MAX, abfrage_pflicht=False,
        )
    except WerkzeugFehler as e:
        return f"Fehler: {e}"
    erg = idx.suche(args["abfrage"], typ=args["typ"] or None, ordner=args.get("ordner"), von=args.get("von"),
                    bis=args.get("bis"), sortierung=args["sortierung"], anzahl=args["anzahl"],
                    steuerjahr=args.get("steuerjahr"), kategorie=args.get("kategorie"),
                    korrespondent=args.get("korrespondent"))
    return ausgabe.ergebnisse(erg, args["abfrage"])


def werkzeug_dokument_lesen(idx: Suchindex, dok_id: int, seiten: str | None = None, max_zeichen: int = 40000) -> str:
    return ausgabe.dokument_text(idx, int(dok_id), seiten, int(max_zeichen))


def werkzeug_index_status(idx: Suchindex) -> str:
    return ausgabe.status_text(idx)


def werkzeug_ordner_vorschlag(idx: Suchindex, daten, umgebung: Umgebung, dok_id) -> str:
    """Ablageort eines Dokuments aus dem Index klaeren (ID aus ``suche``)."""
    try:
        dok_id = int(dok_id)
    except (TypeError, ValueError):
        return f"Fehler: dok_id muss eine Zahl aus 'suche' sein, nicht „{dok_id}“."
    d = idx.dokument(dok_id)
    if not d:
        return f"Dokument {dok_id} nicht gefunden."
    text = idx.volltext(dok_id, AEHNLICHKEIT_TEXT_ZEICHEN) or ""
    v = kern.ordner_vorschlag(Dokument(d.get("pfad") or "", d.get("name") or "", text), daten,
                         umgebung.zielordner, umgebung.scan_ordner)
    return ordner_vorschlag_text(dok_id, v)


def ordner_vorschlag_text(dok_id: int, v: OrdnerVorschlag) -> str:
    """Textform fuer den KI-Assistenten: Index-ID, absolute Pfade zu den relativen Ordnern."""
    zeilen = [f"Ordnervorschlag für [{dok_id}] {v.name}", f"Pfad: {v.pfad}"]
    ordner = Path(v.pfad).parent if v.pfad else None
    if v.im_scan_eingang:
        zeilen.append("Lage: liegt noch unsortiert im Scan-Eingang – hat noch keinen Ablageort.")
    elif ordner is not None and relative_folder(ordner, v.wurzeln):
        zeilen.append(f"Lage: bereits einsortiert, aktueller Ablageort: {relative_folder(ordner, v.wurzeln)} "
                      f"({ordner})")
    elif ordner is not None:
        zeilen.append(f"Lage: weder im Scan-Eingang noch in einem Zielordner ({ordner}).")
    if v.wurzeln:
        zeilen.append("Zielordner: " + ", ".join(f"{w.name} ({w})" for w in v.wurzeln))
    else:
        zeilen.append("Zielordner: keine eingerichtet (PDF Sortier Meister › Einstellungen).")
    if v.aehnliche:
        zeilen.append("Ähnliche, bereits einsortierte Dokumente (Ordner relativ zum Zielordner):")
        for s in v.aehnliche:
            absolut = resolve_relative_folder(s.folder, v.wurzeln)
            zeilen.append(f"- {s.filename} – Ordner: {s.folder}" + (f" ({absolut})" if absolut else "")
                          + (f" – Jahr: {s.year}" if s.year else ""))
        zeilen.append("Hinweis: Das Dokument gehört in den Ordner seines eigenen Jahres, nicht in den eines "
                      "ähnlichen Dokuments aus einem anderen Jahr (Jahr mit 'dokument_lesen' prüfen).")
    else:
        zeilen.append("Ähnliche, bereits einsortierte Dokumente: keine gefunden.")
    return "\n".join(zeilen)


def werkzeug_korrespondent_info(daten, name: str) -> str:
    try:
        return kern.korrespondent_text(kern.korrespondent_info(name, daten))
    except WerkzeugFehler as e:
        return f"Fehler: {e}"


def werkzeug_sql_abfrage(idx: Suchindex, sql: str, zeitlimit_s: float = SQL_ZEITLIMIT_STANDARD_S) -> str:
    try:
        return kern.sql_tabelle(kern.sql_abfrage(idx.db_datei, sql, zeitlimit_s))
    except WerkzeugFehler as e:
        return f"Fehler: {e}"


# --------------------------------------------------------------------------- Server

def _nur_lesen():
    """``ToolAnnotations`` fuer lesende Werkzeuge; ``None``, wenn die installierte ``mcp``-Version sie nicht kennt."""
    try:
        from mcp.types import ToolAnnotations

        return ToolAnnotations(readOnlyHint=True, openWorldHint=False)
    except Exception:  # noqa: BLE001 - aeltere mcp-Version: ohne Annotation
        return None


def _werkzeug(server, beschreibung: str | None = None, annotationen=None):
    """Wie ``server.tool()``, aber mit bereinigter Beschreibung und Annotationen.

    Bis Python 3.12 behaelt ein Docstring die Einrueckung des Quelltexts (erst ab
    3.13 entfernt der Compiler sie). Die Werkzeugbeschreibungen sollen fuer den
    KI-Assistenten genau so aussehen wie bei PDFsuche. Kennt ``server.tool()``
    den Parameter ``annotations`` nicht, wird ohne registriert.
    """
    def dekorator(funktion):
        text = beschreibung or inspect.cleandoc(funktion.__doc__ or "")
        if annotationen is not None:
            try:
                return server.tool(description=text, annotations=annotationen)(funktion)
            except TypeError:
                pass
        return server.tool(description=text)(funktion)

    return dekorator


def erstelle_server(konfig: SearchConfig, umgebung: Umgebung | None = None):
    """MCP-Server ueber dem Index aus ``konfig``.

    ``umgebung`` (Hauptdatenbank, Zielordner, Scan-Eingang, SQL-Schalter) kommt
    beim Start aus der ``config.json`` (:func:`lade_umgebung`); ohne sie laufen
    ``ordner_vorschlag`` und ``korrespondent_info`` ohne Historie und
    Korrespondenten, und ``sql_abfrage`` fehlt.
    """
    from mcp.server.mcpserver import MCPServer

    umgebung = umgebung or Umgebung()
    idx = Suchindex(konfig)
    daten = PdfsmDaten(idx, umgebung.db_pfad)
    server = MCPServer("pdfsuche", instructions=beschreibung(konfig, umgebung))
    lesend = _nur_lesen()

    @_werkzeug(server, annotationen=lesend)
    def suche(abfrage: str, typ: str | None = None, ordner: str | None = None, von: str | None = None,
              bis: str | None = None, sortierung: str = "relevanz", anzahl: int = SUCHE_ANZAHL_STANDARD,
              steuerjahr: str | None = None, kategorie: str | None = None,
              korrespondent: str | None = None) -> str:
        """Volltextsuche im lokalen Dokumentenindex.

        abfrage: Suchbegriffe. Mehrere Wörter = alle müssen vorkommen. Syntax: "genaue Phrase",
                 ODER/OR, NICHT/NOT, Klammern, Präfix mit * (z. B. Unterhalt*), NEAR(a b, 10).
                 Umlaute/Akzente werden ignoriert (Muller findet Müller).
        typ: 'pdf', 'md', 'mail', 'office' (doc/docx/xls/xlsx/odt) oder Kombination 'pdf,office';
             auch 'excel', 'word', 'e-mail' werden verstanden
        ordner: Teil des Dateipfads bzw. Postfachnamens, z. B. 'Steuer' oder 'gmx'
        von / bis: Datum JJJJ-MM-TT (Mail-Datum bzw. Datei-Änderungsdatum)
        sortierung: 'relevanz' | 'neu' | 'alt'
        anzahl: maximale Zahl an Dokumenten (Standard 20, höchstens 200)
        steuerjahr / kategorie / korrespondent: PDFSM-Metadaten sortierter PDFs (genauer Wert),
                 z. B. steuerjahr='2024', kategorie='Rechnung', korrespondent='Telekom'
                 (Schreibweise mit korrespondent_info klären)
        Ergebnis: je Dokument [ID], Pfad und Textausschnitte mit «Fundstelle» und Seitenzahl.
        """
        return werkzeug_suche(idx, abfrage, typ, ordner, von, bis, sortierung, anzahl, steuerjahr, kategorie,
                              korrespondent)

    @_werkzeug(server, annotationen=lesend)
    def dokument_lesen(dok_id: int, seiten: str | None = None, max_zeichen: int = 40000) -> str:
        """Volltext eines Dokuments aus dem Index (ID aus 'suche').

        seiten: optional '3' oder '2-5' (nur PDFs). Lange Dokumente seitenweise lesen.
        """
        return werkzeug_dokument_lesen(idx, dok_id, seiten, max_zeichen)

    @_werkzeug(server, annotationen=lesend)
    def index_status() -> str:
        """Stand des Index: Anzahl Dokumente, OCR-Fortschritt, letzter Lauf."""
        return werkzeug_index_status(idx)

    @_werkzeug(server, annotationen=lesend)
    def ordner_vorschlag(dok_id: int) -> str:
        """Ablageort für ein Dokument klären (ID aus 'suche').

        Liefert ähnliche, bereits einsortierte Dokumente mit Ordner (relativ zum Zielordner und
        als Pfad) und Jahr, die Zielordner und ob das Dokument noch unsortiert im Scan-Eingang
        liegt. Benutze es bei Fragen wie "In welchen Ordner gehört die Rechnung X?". Ein Dokument
        gehört in den Ordner seines eigenen Jahres, nicht in den eines ähnlichen Dokuments aus
        einem anderen Jahr. Nur lesend: verschoben wird nichts.
        """
        return werkzeug_ordner_vorschlag(idx, daten, umgebung, dok_id)

    @_werkzeug(server, annotationen=lesend)
    def korrespondent_info(name: str) -> str:
        """Was PDF Sortier Meister über einen Korrespondenten gelernt hat.

        Korrespondent = Gegenpartei des Nutzers (Person, Firma, Behörde). Liefert Aliase
        (andere Schreibweisen), Kategorie, Notizen, MwSt-Satz, steuerlich absetzbar, Währung und
        wie oft er verwendet wurde. Teiltreffer im Namen oder in den Aliasen genügen.
        name: Name oder Teil des Namens, z. B. 'Stadtwerke' oder 'Telekom'
        """
        return werkzeug_korrespondent_info(daten, name)

    if umgebung.sql_erlaubt:
        @_werkzeug(server, annotationen=lesend, beschreibung=kern.sql_beschreibung(
            umgebung.sql_zeitlimit_s,
            "Ein Dokument aus dem Ergebnis liest du mit dokument_lesen und dok_id = <dokumente.id>."))
        def sql_abfrage(sql: str) -> str:
            return werkzeug_sql_abfrage(idx, sql, umgebung.sql_zeitlimit_s)

    return server


def main(konfig: SearchConfig | None = None, config_pfad: str | None = None) -> int:
    from src.search import konfig as konfig_modul

    if konfig is None:
        konfig = konfig_modul.lade(config_pfad)
    erstelle_server(konfig, lade_umgebung(config_pfad)).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

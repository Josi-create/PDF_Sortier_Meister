"""
Werkzeugkasten des Chats (Issue #166/#167, Phase 2).

Das Modell soll selbst suchen und lesen ("das kann er doch fuer mich
erledigen", Issue #167). Der :class:`Werkzeugkasten` kapselt die Werkzeuge
ueber dem Suchindex (``src/search``, Schema in ``docs/SUCHE_SCHEMA.md``) und
vergibt chat-lokale Nummern D1, D2, ... fuer Dokumente: der bestehende
:class:`~src.rag.citation.CitationParser` (``[N]``-Marker) bleibt
unveraendert, und das Modell sieht keine sechsstelligen Index-Ids.
Werkzeugbeschreibungen und Ausgabeformat lehnen sich an den MCP-Server
(``src/search/mcp_server.py``, ``src/search/ausgabe.py``) an.

Werkzeuge:

* ``suche`` - Volltextsuche mit den Filtern des MCP-Werkzeugs; Treffer
  werden registriert und als ``[D7] ...`` ausgegeben.
* ``dokument_lesen`` - Volltext (auch seitenweise) eines registrierten
  Dokuments oder einer Index-Id (``"id:260906"``, z.B. aus SQL).
* ``ordner_vorschlag`` - Vorschlaege der Sortierlogik und aehnliche, schon
  einsortierte Dokumente (:func:`src.core.similar_documents.find_similar_documents`).
* ``korrespondent_info`` - Gelerntes ueber einen Korrespondenten.
* ``sql_abfrage`` - nur wenn freigegeben: lesende SQL-Abfrage auf der
  Suchdatenbank (Nur-Lese-Verbindung, ``query_only``, Schluesselwort-Pruefung,
  Zeitlimit, Zeilen- und Zeichenkappung).

Qt-frei. Werkzeuge werfen keine Exceptions nach aussen: Fehler kommen als
Text (``"Fehler: ..."``) zurueck und stehen mit jedem Aufruf als
:class:`Schritt` im ``protokoll``.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import dataclasses
import json
import re
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.core.similar_documents import find_similar_documents
from src.ml.llm_provider import Werkzeug, WerkzeugAufruf
from src.rag.bezug import Bezug, ablageort, gleicher_pfad
from src.rag.retrieval import RetrievalService, RetrievedDoc
from src.search import ausgabe
from src.search.db import fts_abfrage
from src.utils.config import ChatConfig

# Suche: Treffer je Aufruf und Kappung der Ausgabe
SUCHE_ANZAHL_STANDARD = 8
SUCHE_ANZAHL_MAX = 20
SUCHE_MAX_ZEICHEN = 6000
FUNDSTELLEN_MAX_ZEICHEN = 600
TYPEN = ("pdf", "office", "md", "mail")
TYP_ALIASE = {
    "excel": "office", "xlsx": "office", "xls": "office", "word": "office", "docx": "office", "doc": "office",
    "odt": "office", "tabelle": "office", "tabellen": "office",
    "e-mail": "mail", "email": "mail", "mails": "mail", "e-mails": "mail", "emails": "mail", "nachricht": "mail",
    "markdown": "md", "pdfs": "pdf",
}
SORTIERUNGEN = ("relevanz", "neu", "alt")
# Erfundene Werkzeugnamen, die eindeutig ein echtes Werkzeug meinen
WERKZEUG_ALIASE = {
    "abfrage": "suche", "suchen": "suche", "search": "suche", "volltextsuche": "suche", "finde": "suche",
    "lesen": "dokument_lesen", "dokument": "dokument_lesen", "read": "dokument_lesen",
    "read_document": "dokument_lesen", "dokument_lesen_seiten": "dokument_lesen",
    "ordner": "ordner_vorschlag", "ordnervorschlag": "ordner_vorschlag", "folder_suggestion": "ordner_vorschlag",
    "korrespondent": "korrespondent_info", "korrespondenten_info": "korrespondent_info",
    "sql": "sql_abfrage", "sql_query": "sql_abfrage", "abfrage_sql": "sql_abfrage",
}

# Lesen
LESEN_ZEICHEN_STANDARD = 12000
LESEN_ZEICHEN_MAX = 40000
# Volltext fuer die Aehnlichkeitssuche (mehr liest der Scorer ohnehin nicht)
AEHNLICHKEIT_TEXT_ZEICHEN = 20000
AEHNLICHE_MAX = 8

# SQL
SQL_MAX_ZEILEN = 200
SQL_MAX_ZEICHEN = 20000
SQL_ZELLE_MAX_ZEICHEN = 300
SQL_VERBOTEN = ("ATTACH", "DETACH", "PRAGMA", "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
                "CREATE", "REPLACE", "VACUUM", "REINDEX")

# Status eines Dokuments im Chat: zitiert schlaegt gelesen schlaegt gefunden
STATUS_RANG = {"gefunden": 0, "gelesen": 1, "zitiert": 2}

_DATUM_RE = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4}|\d{4})$")
_SEITEN_RE = re.compile(r"^(\d+)(?:\s*-\s*(\d+))?$")
_INDEX_ID_RE = re.compile(r"^id\s*:\s*(\d+)$", re.IGNORECASE)
_D_NUMMER_RE = re.compile(r"^\[?\s*[dD]?\s*(\d+)\s*\]?$")


@dataclass
class Schritt:
    """Ein Werkzeugaufruf im Protokoll (fuer Oberflaeche und Tests).

    Attributes:
        werkzeug: Name des Werkzeugs.
        argumente: Argumente des Aufrufs.
        zusammenfassung: Eine Zeile fuer die Anzeige, z.B.
            ``'Suche „226541“ (typ=office): 3 Treffer (D4, D5, D6)'``.
        dokumente: Betroffene D-Nummern.
        fehler: Fehlertext; leer = ok.
    """

    werkzeug: str
    argumente: dict
    zusammenfassung: str
    dokumente: list[int] = field(default_factory=list)
    fehler: str = ""


class _WerkzeugFehler(Exception):
    """Fehler, den das Modell als Text bekommt (fehlende Argumente, unbekanntes Dokument ...)."""


def _betrag(wert) -> str:
    """REAL aus dem Suchindex als Text ("480.00"); leer, wenn nicht gesetzt."""
    if wert in (None, ""):
        return ""
    try:
        return f"{float(wert):.2f}"
    except (TypeError, ValueError):
        return str(wert)


def _text(argumente: dict, name: str) -> str:
    wert = argumente.get(name)
    if wert is None:
        return ""
    return str(wert).strip()


def _zahl(argumente: dict, name: str, standard: int, minimum: int, maximum: int) -> int:
    wert = argumente.get(name)
    if wert in (None, ""):
        return standard
    try:
        zahl = int(float(str(wert).strip()))
    except (TypeError, ValueError):
        raise _WerkzeugFehler(f"Argument „{name}“ muss eine ganze Zahl sein, nicht „{wert}“.") from None
    return max(minimum, min(maximum, zahl))


def _param(typ: str, beschreibung: str, **mehr) -> dict:
    return {"type": typ, "description": beschreibung, **mehr}


def _datum_pruefen(wert: str, name: str) -> str:
    """Datum eines Suchfilters pruefen (Format UND Kalender) und als JJJJ-MM-TT liefern.

    Angenommen werden JJJJ-MM-TT, TT.MM.JJJJ und JJJJ (wie ``src.search.db._zeit``).
    Ein kalendarisch unmoegliches Datum wie 2025-02-30 liesse der Index sonst
    still als "keine Treffer" durchgehen.
    """
    wert = str(wert).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y"):
        try:
            return datetime.strptime(wert, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise _WerkzeugFehler(f"Argument „{name}“ muss ein gültiges Datum im Format JJJJ-MM-TT sein, nicht „{wert}“.")


class Werkzeugkasten:
    """Werkzeuge des Chats ueber dem Suchindex mit chat-lokalen Dokumentnummern.

    Args:
        db: :class:`~src.utils.database.Database`; ``db.suchindex`` ist der
            :class:`~src.search.suchindex.Suchindex`. Fehlt er (Tests, fremde
            DB), melden die Werkzeuge "Suchindex nicht verfügbar".
        chat_config: :class:`ChatConfig` (Auszugslaenge, Top-K).
        bezug: Bezugsdokument des Chats (:class:`~src.rag.bezug.Bezug`) oder None.
        wurzeln: Zielordner; Ablageorte werden relativ dazu angegeben
            (Rueckfall: ``bezug.wurzeln``).
        scan_ordner: Scan-Eingang (Rueckfall: ``bezug.scan_ordner``).
        sortier_vorschlaege: Ordnervorschlaege der Sortierlogik aus der
            Oberflaeche, bester zuerst (Rueckfall: ``bezug.sortier_vorschlaege``).
        sql_erlaubt: Werkzeug ``sql_abfrage`` anbieten.
        sql_zeitlimit_s: Zeitlimit einer SQL-Abfrage in Sekunden.
        retrieval: :class:`RetrievalService` fuer die Auszuege der Treffer;
            Standard: ein neuer ueber ``db``/``chat_config``.

    Attributes:
        protokoll: Alle Aufrufe als :class:`Schritt`, auch fehlgeschlagene.
    """

    # Alle so viele VM-Schritte prueft der Fortschritts-Handler das SQL-Zeitlimit
    # (Klassenattribut, damit Tests den Timer-Weg allein pruefen koennen)
    SQL_HANDLER_SCHRITTE = 200

    def __init__(
        self,
        db,
        chat_config: ChatConfig | None = None,
        *,
        bezug: Bezug | None = None,
        wurzeln=(),
        scan_ordner=None,
        sortier_vorschlaege=(),
        sql_erlaubt: bool = False,
        sql_zeitlimit_s: float = 15,
        retrieval: RetrievalService | None = None,
    ) -> None:
        self.db = db
        self.chat_config = chat_config or ChatConfig()
        self.bezug = bezug
        self.wurzeln = [Path(w) for w in (wurzeln or ()) if w]
        if not self.wurzeln and bezug is not None:
            self.wurzeln = [Path(w) for w in (bezug.wurzeln or []) if w]
        if scan_ordner:
            self.scan_ordner: Path | None = Path(scan_ordner)
        else:
            self.scan_ordner = bezug.scan_ordner if bezug is not None else None
        self.sortier_vorschlaege = [str(v) for v in (sortier_vorschlaege or ()) if v]
        if not self.sortier_vorschlaege and bezug is not None:
            self.sortier_vorschlaege = [str(v) for v in (bezug.sortier_vorschlaege or []) if v]
        self.sql_erlaubt = bool(sql_erlaubt)
        self.sql_zeitlimit_s = float(sql_zeitlimit_s)
        self.retrieval = retrieval or RetrievalService(db, self.chat_config)
        self.protokoll: list[Schritt] = []
        self._dokumente: list[RetrievedDoc] = []

    # ------------------------------------------------------------------ #
    # Dokumentnummern                                                    #
    # ------------------------------------------------------------------ #

    def registriere(self, doc: RetrievedDoc) -> RetrievedDoc:
        """Vergibt die naechste freie Nummer (Kopie mit ``index``) oder liefert das schon registrierte Dokument.

        Gleicher Pfad (:func:`~src.rag.bezug.gleicher_pfad`) oder gleiche
        Index-Id = dasselbe Dokument; ein spaeter bekannt gewordenes
        ``dok_id``/``pdf_id`` wird am registrierten Dokument nachgetragen.
        ``extra["status"]`` wird auf ``"gefunden"`` gesetzt, falls nicht gesetzt.
        """
        vorhanden = self._vorhanden(doc.file_path, doc.dok_id)
        if vorhanden is not None:
            if doc.dok_id and not vorhanden.dok_id:
                vorhanden.dok_id = doc.dok_id
            if doc.pdf_id and not vorhanden.pdf_id:
                vorhanden.pdf_id = doc.pdf_id
            return vorhanden
        # Eigene Kopie des extra-Dicts: der Status des Chats darf nicht auf das
        # Original durchschlagen (der Rueckfallweg ohne Werkzeuge zeigt sonst
        # alle Quellen als "gefunden", Review-Befund)
        extra = dict(doc.extra) if isinstance(doc.extra, dict) else {}
        kopie = dataclasses.replace(doc, index=len(self._dokumente) + 1, extra=extra)
        kopie.extra.setdefault("status", "gefunden")
        self._dokumente.append(kopie)
        return kopie

    def dokumente(self) -> list[RetrievedDoc]:
        """Alle registrierten Dokumente in Nummernreihenfolge (Whitelist fuer den CitationParser)."""
        return list(self._dokumente)

    def nummer(self, doc_id: int) -> int | None:
        """D-Nummer zu einer Index-Id; None, wenn nicht registriert."""
        try:
            doc_id = int(doc_id)
        except (TypeError, ValueError):
            return None
        if not doc_id:
            return None
        for d in self._dokumente:
            if d.dok_id == doc_id:
                return d.index
        return None

    def markiere(self, nummer: int, status: str) -> None:
        """Status eines Dokuments anheben: "gelesen" oder "zitiert" (nie zurueck auf "gefunden")."""
        doc = self._nach_nummer(nummer)
        if doc is None or status not in STATUS_RANG:
            return
        aktuell = str(doc.extra.get("status") or "gefunden")
        if STATUS_RANG[status] > STATUS_RANG.get(aktuell, 0):
            doc.extra["status"] = status

    def _nach_nummer(self, nummer) -> RetrievedDoc | None:
        try:
            n = int(nummer)
        except (TypeError, ValueError):
            return None
        if 1 <= n <= len(self._dokumente):
            return self._dokumente[n - 1]
        return None

    def _vorhanden(self, file_path: str, dok_id: int = 0) -> RetrievedDoc | None:
        for d in self._dokumente:
            if dok_id and d.dok_id == dok_id:
                return d
            if gleicher_pfad(d.file_path, file_path):
                return d
        return None

    # ------------------------------------------------------------------ #
    # Werkzeugbeschreibungen                                             #
    # ------------------------------------------------------------------ #

    def definitionen(self) -> list[Werkzeug]:
        """Werkzeuge fuer das Modell; ``sql_abfrage`` nur, wenn freigegeben."""
        werkzeuge = [
            Werkzeug(
                name="suche",
                beschreibung=(
                    "Volltextsuche im lokalen Dokumentenindex (PDFs inkl. OCR gescannter Seiten, "
                    "Word/Excel/OpenDocument, Markdown, Mails). Benutze sie, um Dokumente zu einem Thema, "
                    "Namen, Datum oder einer Nummer (Vertrags-, Zähler-, Kunden-, Rechnungsnummer, IBAN) zu "
                    "finden; lies einen Treffer bei Bedarf mit dokument_lesen ganz.\n"
                    "Syntax von abfrage: mehrere Wörter = alle müssen vorkommen; \"genaue Phrase\" in "
                    "Anführungszeichen; ODER/OR, NICHT/NOT, Klammern; Wortanfang mit * (Unterhalt*); "
                    "Umlaute und Akzente sind egal (Muller findet Müller). Kennungen wörtlich suchen: "
                    "\"G22504020299\". Keine Treffer: Wortanfang mit *, ODER, andere oder weniger Wörter "
                    "versuchen, Filter weglassen.\n"
                    "Ergebnis: je Dokument eine Nummer [D7] (so zitieren und an dokument_lesen übergeben), "
                    "Name, Typ, Datum, Seite, Ordner, Metadaten und Fundstellen (markiert mit >>> <<<)."
                ),
                parameter={
                    "type": "object",
                    "properties": {
                        "abfrage": _param("string", "Suchbegriffe (Syntax siehe Beschreibung)."),
                        "typ": _param("string", "'pdf', 'office' (doc/docx/xls/xlsx/odt), 'md' oder 'mail', "
                                                "auch Kombination 'pdf,office'. Leer = alle."),
                        "ordner": _param("string", "Teil des Dateipfads bzw. Postfachnamens, "
                                                   "z. B. 'Steuer 2024' oder 'gmx'."),
                        "von": _param("string", "Datum JJJJ-MM-TT: nur Dokumente ab diesem Datei- bzw. Mail-Datum."),
                        "bis": _param("string", "Datum JJJJ-MM-TT: nur Dokumente bis zu diesem Datei- bzw. Mail-Datum."),
                        "steuerjahr": _param("string", "PDFSM-Metadatum sortierter PDFs, genauer Wert, z. B. '2024'."),
                        "kategorie": _param("string", "PDFSM-Metadatum, genauer Wert, z. B. 'Rechnung'."),
                        "korrespondent": _param("string", "PDFSM-Metadatum, genauer Wert, z. B. 'Telekom' "
                                                          "(Schreibweise mit korrespondent_info klären)."),
                        "sortierung": _param("string", "'relevanz' (Standard), 'neu' (neueste zuerst) oder 'alt'.",
                                             enum=list(SORTIERUNGEN)),
                        "anzahl": _param("integer", f"Höchstzahl der Dokumente (Standard {SUCHE_ANZAHL_STANDARD}, "
                                                    f"höchstens {SUCHE_ANZAHL_MAX}).",
                                         minimum=1, maximum=SUCHE_ANZAHL_MAX),
                    },
                    "required": ["abfrage"],
                },
            ),
            Werkzeug(
                name="dokument_lesen",
                beschreibung=(
                    "Volltext eines Dokuments aus dem Index lesen - eines Treffers von suche, des "
                    "Bezugsdokuments (D1) oder eines Dokuments aus dem Kontext. Benutze es, wenn die "
                    "Fundstellen nicht reichen (Beträge, Adressen, Vertragsdetails, Zählerstände). Lange "
                    "Dokumente seitenweise lesen (seiten) statt alles auf einmal."
                ),
                parameter={
                    "type": "object",
                    "properties": {
                        "dokument": _param("string", "Nummer aus Kontext oder Suche, z. B. \"D7\" (auch 7), oder "
                                                     "\"id:260906\" für eine Index-Id (dokumente.id aus sql_abfrage)."),
                        "seiten": _param("string", "Optional '3' oder '2-5' (PDF: Seiten, Excel: Tabellenblätter)."),
                        "max_zeichen": _param("integer", f"Höchstzahl der Zeichen (Standard {LESEN_ZEICHEN_STANDARD}, "
                                                         f"höchstens {LESEN_ZEICHEN_MAX}).",
                                              minimum=1, maximum=LESEN_ZEICHEN_MAX),
                    },
                    "required": ["dokument"],
                },
            ),
            Werkzeug(
                name="ordner_vorschlag",
                beschreibung=(
                    "Ablageort für ein Dokument klären: liefert die Vorschläge der Sortierlogik von PDF Sortier "
                    "Meister, ähnliche bereits einsortierte Dokumente mit Ordner und Jahr sowie den Hinweis, ob das "
                    "Dokument noch im Scan-Eingang liegt. Benutze es bei Fragen wie \"In welchen Ordner gehört "
                    "dieses PDF?\" oder \"Gibt es schon einen Ordner mit ähnlichen Dokumenten?\". Ein Dokument gehört "
                    "in den Ordner seines eigenen Jahres, nicht in den eines ähnlichen Dokuments aus einem anderen Jahr."
                ),
                parameter={
                    "type": "object",
                    "properties": {
                        "dokument": _param("string", "Nummer des Dokuments, z. B. \"D3\"; Standard D1 (Bezugsdokument)."),
                    },
                    "required": [],
                },
            ),
            Werkzeug(
                name="korrespondent_info",
                beschreibung=(
                    "Was PDF Sortier Meister über einen Korrespondenten (Absender, Firma, Behörde) gelernt hat: "
                    "Aliase (andere Schreibweisen), Kategorie, Notizen, MwSt-Satz, steuerlich absetzbar, Währung "
                    "und wie oft er verwendet wurde. Benutze es, um die genaue Schreibweise für den Filter "
                    "korrespondent der Suche zu klären oder ein Dokument einzuordnen. Teiltreffer im Namen oder "
                    "in den Aliasen genügen."
                ),
                parameter={
                    "type": "object",
                    "properties": {
                        "name": _param("string", "Name oder Teil des Namens, z. B. 'Stadtwerke' oder 'Telekom'."),
                    },
                    "required": ["name"],
                },
            ),
        ]
        if self.sql_erlaubt:
            werkzeuge.append(Werkzeug(
                name="sql_abfrage",
                beschreibung=self._sql_beschreibung(),
                parameter={
                    "type": "object",
                    "properties": {
                        "sql": _param("string", "Eine einzelne SELECT- oder WITH-Anweisung (SQLite)."),
                    },
                    "required": ["sql"],
                },
            ))
        return werkzeuge

    def _sql_beschreibung(self) -> str:
        # Kompakte Fassung von docs/SUCHE_SCHEMA.md
        return (
            "Nur lesende SQL-Abfrage (SQLite) auf der Suchdatenbank - für Auswertungen, die die Suche nicht "
            "leistet: Summen, Zählungen, Gruppierungen, Listen nach Datum oder Betrag. Genau eine SELECT- oder "
            f"WITH-Anweisung; höchstens {SQL_MAX_ZEILEN} Zeilen, Zeitlimit {self.sql_zeitlimit_s:g} s - mit WHERE "
            "und LIMIT eingrenzen. SQLite-Fehler kommen als Text zurück: Abfrage korrigieren und erneut versuchen.\n"
            "Schema:\n"
            "- dokumente: ein Datensatz je Datei bzw. Mail - id, pfad, name (Dateiname bzw. Mail-Betreff), ordner, "
            "typ ('pdf','office','md','mail'), format, datum (Unix-Zeit: Mail- bzw. Dateidatum; "
            "date(datum,'unixepoch') ergibt JJJJ-MM-TT), seiten, textstatus, pdf_id, korrespondent, kategorie, "
            "steuerjahr (Text, z. B. '2024'), betrag (REAL, brutto), buchungsdatum (JJJJ-MM-TT), zusammenfassung, "
            "schlagwoerter, mail_von, mail_an, mail_datum, mail_betreff. Die PDFSM-Metadaten (korrespondent bis "
            "schlagwoerter) sind nur bei sortierten PDFs gefüllt.\n"
            "- seiten: dok_id (-> dokumente.id), seite, quelle ('text','ocr'), text - der Text je Seite.\n"
            "- Sicht v_dokument_text: pfad, volltext - der ganze Text eines Dokuments.\n"
            "- Volltextindex (FTS5, mit MATCH abfragen, Umlaute egal): seiten_fts über seiten.text "
            "(rowid = seiten.id), dokumente_fts über name und ordner (rowid = dokumente.id), metadaten_fts über "
            "korrespondent, kategorie, zusammenfassung, schlagwoerter (rowid = dokumente.id).\n"
            "Beispiele:\n"
            "SELECT d.id, d.pfad, s.seite, snippet(seiten_fts, 0, '[', ']', ' … ', 20) AS ausschnitt "
            "FROM seiten_fts JOIN seiten s ON s.id = seiten_fts.rowid JOIN dokumente d ON d.id = s.dok_id "
            "WHERE seiten_fts MATCH 'Unterhalt 2019' ORDER BY bm25(seiten_fts) LIMIT 50\n"
            "SELECT count(*), sum(betrag) FROM dokumente WHERE korrespondent = 'Stadtwerke Musterstadt' "
            "AND kategorie = 'Rechnung' AND steuerjahr = '2025'\n"
            "SELECT volltext FROM v_dokument_text WHERE pfad = '<Pfad der Datei>'\n"
            "Ein Dokument aus dem Ergebnis liest du mit dokument_lesen und dokument = \"id:<dokumente.id>\"."
        )

    # ------------------------------------------------------------------ #
    # Ausfuehrung                                                        #
    # ------------------------------------------------------------------ #

    def ausfuehren(self, aufruf: WerkzeugAufruf) -> str:
        """Fuehrt einen Werkzeugaufruf aus und liefert das Textergebnis fuer das Modell.

        Wirft nie: unbekanntes Werkzeug, fehlende oder unbrauchbare Argumente
        und innere Fehler kommen als ``"Fehler: ..."`` zurueck. Jeder Aufruf
        haengt einen :class:`Schritt` an ``protokoll`` an.
        """
        name = str(getattr(aufruf, "name", "") or "").strip()
        argumente = self._argumente(getattr(aufruf, "argumente", None))
        handler: dict[str, Callable[[dict], tuple[str, str, list[int]]]] = {
            "suche": self._suche,
            "dokument_lesen": self._dokument_lesen,
            "ordner_vorschlag": self._ordner_vorschlag,
            "korrespondent_info": self._korrespondent_info,
            "sql_abfrage": self._sql_abfrage,
        }
        try:
            # Modelle erfinden gern Namen aus den Parametern ("abfrage" statt "suche")
            if name not in handler:
                name = WERKZEUG_ALIASE.get(name.lower(), name)
            if name == "sql_abfrage" and not self.sql_erlaubt:
                raise _WerkzeugFehler("SQL-Abfragen sind in den Einstellungen nicht freigegeben.")
            funktion = handler.get(name)
            if funktion is None:
                verfuegbar = ", ".join(w.name for w in self.definitionen())
                raise _WerkzeugFehler(f"Unbekanntes Werkzeug „{name}“. Verfügbar: {verfuegbar}.")
            text, zusammenfassung, dokumente = funktion(argumente)
        except _WerkzeugFehler as e:
            fehler = str(e)
        except Exception as e:  # noqa: BLE001 - nie nach aussen werfen, das Modell korrigiert sich
            fehler = f"{type(e).__name__}: {e}"
        else:
            self.protokoll.append(Schritt(name, argumente, zusammenfassung, list(dokumente)))
            return text
        self.protokoll.append(Schritt(name, argumente, f"{name or 'Werkzeug'}: Fehler - {fehler}", [], fehler=fehler))
        return f"Fehler: {fehler}"

    @staticmethod
    def _argumente(roh) -> dict:
        """Argumente als Dict; ein JSON-String (manche Provider) wird geparst."""
        if isinstance(roh, dict):
            return dict(roh)
        if isinstance(roh, str) and roh.strip():
            try:
                geparst = json.loads(roh)
            except ValueError:
                return {}
            return dict(geparst) if isinstance(geparst, dict) else {}
        return {}

    def _suchindex(self):
        suchindex = getattr(self.db, "suchindex", None) if self.db is not None else None
        if suchindex is None:
            raise _WerkzeugFehler("Suchindex nicht verfügbar.")
        return suchindex

    # ------------------------------------------------------------------ #
    # suche                                                              #
    # ------------------------------------------------------------------ #

    def _suche(self, argumente: dict) -> tuple[str, str, list[int]]:
        abfrage = _text(argumente, "abfrage")
        if not abfrage:
            raise _WerkzeugFehler("Argument „abfrage“ fehlt.")
        self._suchindex()

        typ = _text(argumente, "typ").lower()
        if typ:
            # Modelle schreiben gern "excel" oder "e-mail": gaengige Schreibweisen abbilden
            typen = [TYP_ALIASE.get(t.strip(), t.strip()) for t in typ.split(",") if t.strip()]
            typen = list(dict.fromkeys(typen))
            unbekannt = [t for t in typen if t not in TYPEN]
            if unbekannt:
                raise _WerkzeugFehler(f"Unbekannter typ „{unbekannt[0]}“ - erlaubt: "
                                      f"{', '.join(TYPEN)} (auch Kombination 'pdf,office').")
            typ = ",".join(typen)
        sortierung = _text(argumente, "sortierung").lower() or "relevanz"
        if sortierung not in SORTIERUNGEN:
            raise _WerkzeugFehler(f"Unbekannte sortierung „{sortierung}“ - erlaubt: {', '.join(SORTIERUNGEN)}.")
        anzahl = _zahl(argumente, "anzahl", SUCHE_ANZAHL_STANDARD, 1, SUCHE_ANZAHL_MAX)
        filter: dict[str, str] = {}
        for name in ("ordner", "von", "bis", "steuerjahr", "kategorie", "korrespondent"):
            wert = _text(argumente, name)
            if wert:
                filter[name] = wert
        for name in ("von", "bis"):
            if name in filter:
                filter[name] = _datum_pruefen(filter[name], name)

        beschreibung = ", ".join(
            f"{k}={v}" for k, v in (("typ", typ), ("sortierung", sortierung if sortierung != "relevanz" else ""),
                                    *filter.items()) if v
        )
        kennung = f"„{abfrage}“" + (f" ({beschreibung})" if beschreibung else "")

        try:
            rohe = list(self.db.search_documents(
                query=fts_abfrage(abfrage), limit=anzahl, typ=typ,
                sortierung=sortierung if sortierung != "relevanz" else "", **filter,
            ) or [])
        except Exception as e:  # noqa: BLE001 - Fehler als Text
            raise _WerkzeugFehler(f"Suche fehlgeschlagen: {e}") from e

        if not rohe:
            text = (
                f"Keine Treffer für {kennung}.\n"
                "Tipps: Wortanfang mit * suchen (z. B. Unterhalt*), Begriffe mit ODER verbinden, andere "
                "Begriffe oder weniger Wörter versuchen, Filter (typ, ordner, von/bis, Metadaten) weglassen."
            )
            return text, f"Suche {kennung}: keine Treffer", []

        zeilen = [f"{len(rohe)} Treffer für {kennung}:"]
        laenge = len(zeilen[0])
        hinweis = "[… weitere Treffer weggelassen - mit anzahl oder Filtern eingrenzen]"
        budget = SUCHE_MAX_ZEICHEN - len(hinweis) - 1
        nummern: list[int] = []
        for raw in rohe:
            vorhanden = self._vorhanden(raw.get("file_path") or "", int(raw.get("dok_id") or 0))
            nummer = vorhanden.index if vorhanden is not None else len(self._dokumente) + 1
            zeile = self._treffer_zeile(nummer, raw)
            if laenge + len(zeile) + 1 > budget and nummern:
                zeilen.append(hinweis)
                break
            doc = self.registriere(self.retrieval._to_retrieved_doc(raw, nummer))
            nummern.append(doc.index)
            zeilen.append(zeile)
            laenge += len(zeile) + 1
        text = "\n".join(zeilen)
        if len(text) > SUCHE_MAX_ZEICHEN:
            text = text[:SUCHE_MAX_ZEICHEN] + "\n[… gekürzt]"
        liste = ", ".join(f"D{n}" for n in nummern)
        return text, f"Suche {kennung}: {len(rohe)} Treffer ({liste})", nummern

    @staticmethod
    def _treffer_zeile(nummer: int, raw: dict) -> str:
        """``[D7] <name> (PDF, 12.03.2024, S. 2) - Ordner: ... - Fundstellen: ...``"""
        typ = (raw.get("typ") or "").lower()
        fmt = (raw.get("format") or "").lower()
        seite = int(raw.get("seite") or 0)
        stelle = ""
        if seite and typ == "pdf":
            stelle = f", S. {seite}"
        elif seite and typ == "office" and fmt in ("xlsx", "xlsm", "xls"):
            stelle = f", Blatt {seite}"
        datum = ausgabe.datum(raw.get("datum"))
        pfad = raw.get("file_path") or ""
        ordner = raw.get("target_folder") or (str(Path(pfad).parent) if pfad else "?")
        name = raw.get("filename") or (Path(pfad).name if pfad else "?")
        meta = []
        for feld, titel in (("korrespondent", "Korrespondent"), ("kategorie", "Kategorie"),
                            ("steuerjahr", "Steuerjahr"), ("betrag", "Betrag")):
            wert = raw.get(feld)
            if wert not in (None, ""):
                meta.append(f"{titel}: {wert}")
        fund = " ".join(str(raw.get("text_snippet") or "").split())
        if len(fund) > FUNDSTELLEN_MAX_ZEICHEN:
            fund = fund[:FUNDSTELLEN_MAX_ZEICHEN].rstrip() + " …"
        if not fund:
            fund = "(Treffer im Datei-/Ordnernamen oder in den Metadaten)"
        teile = [f"[D{nummer}] {name} ({(typ or 'datei').upper()}, {datum}{stelle})", f"Ordner: {ordner}"]
        if meta:
            teile.append(", ".join(meta))
        teile.append(f"Fundstellen: {fund}")
        return " - ".join(teile)

    # ------------------------------------------------------------------ #
    # dokument_lesen                                                     #
    # ------------------------------------------------------------------ #

    def _dokument_lesen(self, argumente: dict) -> tuple[str, str, list[int]]:
        kennung = argumente.get("dokument")
        if kennung in (None, ""):
            raise _WerkzeugFehler("Argument „dokument“ fehlt (z. B. \"D7\" oder \"id:260906\").")
        seiten = self._seiten(argumente.get("seiten"))
        max_zeichen = _zahl(argumente, "max_zeichen", LESEN_ZEICHEN_STANDARD, 1, LESEN_ZEICHEN_MAX)
        doc = self._dokument_aus_kennung(kennung)
        text = self._dokument_text(doc, seiten, max_zeichen)
        self.markiere(doc.index, "gelesen")
        zusammenfassung = f"D{doc.index} gelesen" + (f" (Seiten {seiten})" if seiten else "") + f", {len(text)} Zeichen"
        return f"[D{doc.index}]\n{text}", zusammenfassung, [doc.index]

    @staticmethod
    def _seiten(wert) -> str | None:
        if wert in (None, ""):
            return None
        m = _SEITEN_RE.match(str(wert).strip())
        if not m:
            raise _WerkzeugFehler(f"Argument „seiten“ als '3' oder '2-5' angeben, nicht „{wert}“.")
        von, bis = int(m.group(1)), int(m.group(2) or m.group(1))
        if von < 1 or bis < von:
            raise _WerkzeugFehler(f"Ungültiger Seitenbereich „{wert}“.")
        return f"{von}-{bis}" if bis != von else str(von)

    @staticmethod
    def _seitenbereich_pruefen(suchindex, dok_id: int, seiten: str, doc: RetrievedDoc) -> None:
        """Seitenangabe gegen die Seitenzahl des Dokuments pruefen (sonst kaeme nur der Kopf zurueck)."""
        try:
            d = suchindex.dokument(dok_id) or {}
            anzahl = int(d.get("seiten") or 0)
        except Exception:  # noqa: BLE001 - dann prueft niemand, das Lesen laeuft wie bisher
            return
        if anzahl <= 0:
            return
        von = int(seiten.split("-")[0])
        if von > anzahl:
            einheit = "Blätter" if (d.get("format") or "") in ("xlsx", "xlsm", "xls") else "Seiten"
            raise _WerkzeugFehler(f"Seiten „{seiten}“ gibt es nicht - D{doc.index} ({doc.filename}) hat "
                                  f"{anzahl} {einheit}.")

    def _dokument_aus_kennung(self, kennung) -> RetrievedDoc:
        """``"D7"``, ``7`` oder ``"id:260906"`` -> registriertes Dokument."""
        s = str(kennung).strip()
        m = _INDEX_ID_RE.match(s)
        if m:
            return self._dokument_aus_index_id(int(m.group(1)))
        m = _D_NUMMER_RE.match(s)
        if not m:
            raise _WerkzeugFehler(f"Unverständliche Dokumentangabe „{s}“ - erwartet \"D7\", 7 oder \"id:260906\".")
        n = int(m.group(1))
        doc = self._nach_nummer(n)
        if doc is None:
            if not self._dokumente:
                raise _WerkzeugFehler(f"Unbekanntes Dokument D{n} - es sind noch keine Dokumente bekannt, erst suchen.")
            raise _WerkzeugFehler(f"Unbekanntes Dokument D{n} - bekannt sind D1 bis D{len(self._dokumente)}.")
        return doc

    def _dokument_aus_index_id(self, dok_id: int) -> RetrievedDoc:
        suchindex = self._suchindex()
        nummer = self.nummer(dok_id)
        if nummer:
            return self._nach_nummer(nummer)
        try:
            d = suchindex.dokument(dok_id)
        except Exception as e:  # noqa: BLE001
            raise _WerkzeugFehler(f"Suchindex nicht lesbar: {e}") from e
        if not d:
            raise _WerkzeugFehler(f"Kein Dokument mit der Index-Id {dok_id}.")
        doc = RetrievedDoc(
            index=0,
            file_path=d.get("pfad") or "",
            filename=d.get("name") or "",
            text_snippet="",
            rank=0,
            kategorie=str(d.get("kategorie") or ""),
            steuerjahr=str(d.get("steuerjahr") or ""),
            betrag=_betrag(d.get("betrag")),
            korrespondent=str(d.get("korrespondent") or ""),
            pdf_id=str(d.get("pdf_id") or ""),
            dok_id=dok_id,
            seite=1,
        )
        return self.registriere(doc)

    def _dokument_text(self, doc: RetrievedDoc, seiten: str | None, max_zeichen: int) -> str:
        """Text aus dem Suchindex; ohne Index-Eintrag der Text aus dem Chat-Kontext."""
        suchindex = getattr(self.db, "suchindex", None) if self.db is not None else None
        dok_id = int(doc.dok_id or 0)
        if not dok_id and suchindex is not None and doc.file_path:
            # Bezug, der inzwischen indexiert wurde
            try:
                d = suchindex.dokument_nach_pfad(doc.file_path)
                dok_id = int(d.get("id") or 0) if d else 0
            except Exception:  # noqa: BLE001 - Index ist optional
                dok_id = 0
            if dok_id:
                doc.dok_id = dok_id
        if dok_id and suchindex is not None:
            if seiten:
                self._seitenbereich_pruefen(suchindex, dok_id, seiten, doc)
            try:
                text = ausgabe.dokument_text(suchindex, dok_id, seiten, max_zeichen)
            except Exception:  # noqa: BLE001 - Rueckfall unten
                text = ""
            if text and not text.startswith(f"Dokument {dok_id} nicht gefunden"):
                return text

        volltext = str((doc.extra or {}).get("volltext") or "")
        if not volltext.strip() and self._ist_bezug(doc) and self.bezug is not None:
            volltext = self.bezug.text or ""
        if not volltext.strip():
            volltext = doc.text_snippet or ""
        if not volltext.strip():
            raise _WerkzeugFehler(f"Für D{doc.index} ({doc.filename}) liegt kein Text vor - "
                                  "das Dokument ist noch nicht im Suchindex.")
        kopf = [f"# {doc.filename}", f"Pfad: {doc.file_path}",
                "(Text aus dem Chat-Kontext - das Dokument ist noch nicht im Suchindex"
                + (", keine Seitenauswahl möglich)" if seiten else ")")]
        erg = "\n".join(kopf) + "\n" + volltext.replace("\f", "\n")
        if len(erg) > max_zeichen:
            erg = erg[:max_zeichen] + f"\n\n[… gekürzt, insgesamt {len(erg)} Zeichen]"
        return erg

    # ------------------------------------------------------------------ #
    # ordner_vorschlag                                                   #
    # ------------------------------------------------------------------ #

    def _ordner_vorschlag(self, argumente: dict) -> tuple[str, str, list[int]]:
        kennung = argumente.get("dokument")
        if kennung in (None, ""):
            doc = self._bezug_doc()
            if doc is None:
                raise _WerkzeugFehler("Kein Bezugsdokument im Chat - Argument „dokument“ angeben (z. B. \"D3\").")
        else:
            doc = self._dokument_aus_kennung(kennung)
        ist_bezug = self._ist_bezug(doc)

        zeilen = [f"Ordnervorschlag für [D{doc.index}] {doc.filename}:"]
        if self.wurzeln:
            zeilen.append("Zielordner: " + ", ".join(w.name for w in self.wurzeln))

        # (a) Vorschlaege der Sortierlogik (liegen nur fuer das Bezugsdokument vor)
        if ist_bezug:
            vorschlaege = self.sortier_vorschlaege
            zeilen.append("Vorschläge der Sortierlogik (bester zuerst): " + ("; ".join(vorschlaege) or "keiner"))
        else:
            vorschlaege = []
            zeilen.append("Vorschläge der Sortierlogik: keiner (liegen nur für das Bezugsdokument vor)")

        # (b) aehnliche, bereits einsortierte Dokumente
        text = self._volltext_fuer(doc, AEHNLICHKEIT_TEXT_ZEICHEN)
        aehnliche = []
        if text.strip():
            try:
                aehnliche = list(find_similar_documents(text, None, self.wurzeln, db=self.db, limit=AEHNLICHE_MAX))
            except Exception:  # noqa: BLE001 - Kontext ist optional
                aehnliche = []
            # Das Dokument selbst ist kein aehnliches Dokument
            eigener = (doc.filename or "").casefold()
            aehnliche = [s for s in aehnliche if (s.filename or "").casefold() != eigener]
        if aehnliche:
            zeilen.append("Ähnliche, bereits einsortierte Dokumente (Ordner relativ zum Zielordner):")
            for s in aehnliche:
                zeilen.append(f"- {s.filename} - Ordner: {s.folder}" + (f" - Jahr: {s.year}" if s.year else ""))
            zeilen.append("Hinweis: Das Dokument gehört in den Ordner seines eigenen Jahres, nicht in den eines "
                          "ähnlichen Dokuments aus einem anderen Jahr.")
        else:
            zeilen.append("Ähnliche, bereits einsortierte Dokumente: keine gefunden.")

        # Scan-Eingang bzw. aktueller Ablageort
        wer = "Das Bezugsdokument" if ist_bezug else "Das Dokument"
        if self._im_scan_eingang(doc.file_path):
            zeilen.append(f"{wer} liegt noch unsortiert im Scan-Eingang (noch kein Ablageort).")
        else:
            ort = ablageort(doc.file_path, self.wurzeln)
            if ort:
                zeilen.append(f"{wer} liegt nicht im Scan-Eingang; aktueller Ablageort: {ort}")

        zusammenfassung = (f"Ordnervorschlag für D{doc.index}: {len(vorschlaege)} Vorschläge, "
                           f"{len(aehnliche)} ähnliche Dokumente")
        return "\n".join(zeilen), zusammenfassung, [doc.index]

    def _bezug_doc(self) -> RetrievedDoc | None:
        """Das Bezugsdokument: markiert mit ``extra["bezug"]``, sonst ueber den Pfad, sonst D1."""
        for d in self._dokumente:
            if (d.extra or {}).get("bezug"):
                return d
        if self.bezug is not None:
            for d in self._dokumente:
                if gleicher_pfad(d.file_path, self.bezug.pfad):
                    return d
        return self._nach_nummer(1)

    def _ist_bezug(self, doc: RetrievedDoc) -> bool:
        if (doc.extra or {}).get("bezug"):
            return True
        return self.bezug is not None and gleicher_pfad(doc.file_path, self.bezug.pfad)

    def _im_scan_eingang(self, pfad: str) -> bool:
        if self.bezug is not None and self.bezug.scan_ordner and gleicher_pfad(pfad, self.bezug.pfad):
            return self.bezug.im_scan_ordner()
        if not self.scan_ordner or not pfad:
            return False
        try:
            Path(pfad).resolve().relative_to(Path(self.scan_ordner).resolve())
            return True
        except (ValueError, OSError):
            return False

    def _volltext_fuer(self, doc: RetrievedDoc, max_zeichen: int) -> str:
        """Text eines Dokuments fuer die Aehnlichkeitssuche: Kontext, Suchindex, Bezug, Auszug."""
        extra = doc.extra or {}
        if extra.get("volltext"):
            return str(extra["volltext"])[:max_zeichen]
        suchindex = getattr(self.db, "suchindex", None) if self.db is not None else None
        if doc.dok_id and suchindex is not None:
            try:
                text = suchindex.volltext(int(doc.dok_id), max_zeichen) or ""
            except Exception:  # noqa: BLE001
                text = ""
            if text.strip():
                return text
        if self._ist_bezug(doc) and self.bezug is not None and (self.bezug.text or "").strip():
            return self.bezug.text[:max_zeichen]
        return (doc.text_snippet or "")[:max_zeichen]

    # ------------------------------------------------------------------ #
    # korrespondent_info                                                 #
    # ------------------------------------------------------------------ #

    def _korrespondent_info(self, argumente: dict) -> tuple[str, str, list[int]]:
        name = _text(argumente, "name")
        if not name:
            raise _WerkzeugFehler("Argument „name“ fehlt.")
        eintrag = None
        try:
            eintrag = self.db.get_korrespondent(name)
        except Exception:  # noqa: BLE001 - Verwaltung ist optional
            eintrag = None
        weitere: list[dict] = []
        if eintrag is None:
            treffer = self._korrespondenten_suchen(name)
            if treffer:
                eintrag, weitere = treffer[0], treffer[1:]
        anzeigename = (eintrag or {}).get("name") or name
        gelernt = None
        try:
            gelernt = self.db.get_korrespondent_metadata(anzeigename) or None
        except Exception:  # noqa: BLE001
            gelernt = None
        if eintrag is None and not gelernt:
            return f"Kein Korrespondent „{name}“ bekannt.", f"Korrespondent „{name}“: unbekannt", []

        zeilen = [f"Korrespondent: {anzeigename}"]
        if eintrag:
            aliase = [str(a) for a in (eintrag.get("aliases") or []) if a]
            zeilen.append("Aliase (andere Schreibweisen): " + (", ".join(aliase) if aliase else "keine"))
            zeilen.append(f"Kategorie: {eintrag.get('kategorie') or 'unbekannt'}")
            if eintrag.get("notizen"):
                zeilen.append(f"Notizen: {eintrag['notizen']}")
        if gelernt:
            if gelernt.get("subject") and not (eintrag and eintrag.get("kategorie")):
                zeilen.append(f"Kategorie (gelernt): {gelernt['subject']}")
            if gelernt.get("mwst_satz"):
                zeilen.append(f"MwSt-Satz: {gelernt['mwst_satz']}")
            if gelernt.get("steuerlich_absetzbar"):
                zeilen.append(f"Steuerlich absetzbar: {gelernt['steuerlich_absetzbar']}")
            if gelernt.get("waehrung"):
                zeilen.append(f"Währung: {gelernt['waehrung']}")
        if eintrag:
            zeilen.append(f"Verwendet: {int(eintrag.get('usage_count') or 0)}-mal")
        if weitere:
            zeilen.append("Weitere passende Korrespondenten: " + ", ".join(
                str(w.get("name") or "") for w in weitere[:5] if w.get("name")))
        return "\n".join(zeilen), f"Korrespondent „{name}“: {anzeigename}", []

    def _korrespondenten_suchen(self, name: str) -> list[dict]:
        """Korrespondenten, deren Name oder Alias den Suchbegriff enthaelt; exakte Alias-Treffer zuerst."""
        needle = name.casefold()
        try:
            alle = list(self.db.list_korrespondenten() or [])
        except Exception:  # noqa: BLE001
            return []
        exakt, teil = [], []
        for k in alle:
            kname = str(k.get("name") or "").casefold()
            aliase = [str(a).casefold() for a in (k.get("aliases") or []) if a]
            if needle == kname or needle in aliase:
                exakt.append(k)
            elif needle in kname or any(needle in a for a in aliase):
                teil.append(k)
        return exakt + teil

    # ------------------------------------------------------------------ #
    # sql_abfrage                                                        #
    # ------------------------------------------------------------------ #

    def _sql_abfrage(self, argumente: dict) -> tuple[str, str, list[int]]:
        sql = _text(argumente, "sql")
        if not sql:
            raise _WerkzeugFehler("Argument „sql“ fehlt.")
        sql = self._sql_pruefen(sql)
        suchindex = self._suchindex()
        db_datei = Path(getattr(suchindex, "db_datei", "") or "")
        if not str(db_datei) or not db_datei.is_file():
            raise _WerkzeugFehler("Suchdatenbank noch nicht vorhanden (der erste Indexlauf steht aus).")

        zeitlimit = self.sql_zeitlimit_s
        try:
            con = sqlite3.connect(db_datei.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
        except sqlite3.Error as e:
            raise _WerkzeugFehler(f"Suchdatenbank nicht lesbar: {e}") from e
        # Zeitlimit doppelt: der Fortschritts-Handler prueft alle 200 VM-Schritte,
        # ein Timer-Thread ruft zusaetzlich con.interrupt() (greift auch in langen
        # Einzelschritten wie grossen Sortierungen, die der Handler nicht sieht).
        wecker = threading.Timer(zeitlimit, con.interrupt)
        wecker.daemon = True
        try:
            con.execute("PRAGMA query_only=1")
            con.execute("PRAGMA busy_timeout=30000")
            start = time.monotonic()

            def wache() -> int:
                # 1 = abbrechen -> sqlite3.OperationalError("interrupted")
                return 1 if time.monotonic() - start > zeitlimit else 0

            con.set_progress_handler(wache, self.SQL_HANDLER_SCHRITTE)
            wecker.start()
            try:
                cursor = con.execute(sql)
                spalten = [d[0] for d in (cursor.description or [])]
                zeilen = cursor.fetchmany(SQL_MAX_ZEILEN + 1)
            except sqlite3.OperationalError as e:
                if "interrupt" in str(e).lower():
                    raise _WerkzeugFehler(f"Zeitlimit von {zeitlimit:g} s überschritten - "
                                          "Abfrage mit WHERE und LIMIT eingrenzen.") from None
                raise _WerkzeugFehler(f"SQLite: {e}") from e
            except (sqlite3.Error, sqlite3.Warning) as e:
                raise _WerkzeugFehler(f"SQLite: {e}") from e
        finally:
            wecker.cancel()
            con.close()

        gekappt = len(zeilen) > SQL_MAX_ZEILEN
        zeilen = zeilen[:SQL_MAX_ZEILEN]
        text = self._sql_tabelle(spalten, zeilen, gekappt)
        zusammenfassung = f"SQL: {len(zeilen)} Zeilen" + (" (gekappt)" if gekappt else "")
        return text, zusammenfassung, []

    @staticmethod
    def _sql_pruefen(sql: str) -> str:
        """Genau eine lesende Anweisung (SELECT/WITH) ohne verbotene Schluesselwoerter; sonst Fehler."""
        s = sql.strip()
        if s.endswith(";"):
            s = s[:-1].rstrip()
        if not s:
            raise _WerkzeugFehler("Leere SQL-Anweisung.")
        # Literale, Bezeichner in Anfuehrungszeichen und Kommentare fuer die Pruefung ausblenden
        ohne = re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|`[^`]*`|\[[^\]]*\]", " ", s)
        ohne = re.sub(r"--[^\n]*", " ", ohne)
        ohne = re.sub(r"/\*.*?\*/", " ", ohne, flags=re.S)
        if ";" in ohne:
            raise _WerkzeugFehler("Nur eine einzelne Anweisung erlaubt (kein ';' mitten in der Abfrage).")
        # Zeilenumbruch vor dem ';', damit ein Zeilenkommentar am Ende es nicht schluckt
        if not sqlite3.complete_statement(s + "\n;"):
            raise _WerkzeugFehler("Unvollständige Anweisung (fehlendes Anführungszeichen oder Klammer?).")
        m = re.match(r"\s*([A-Za-z]+)", ohne)
        erstes = m.group(1).upper() if m else ""
        if erstes not in ("SELECT", "WITH"):
            raise _WerkzeugFehler("Nur lesende Abfragen: die Anweisung muss mit SELECT oder WITH beginnen.")
        for wort in SQL_VERBOTEN:
            # replace(x, y, z) ist eine Funktion und erlaubt; REPLACE INTO nicht
            muster = r"\b" + wort + r"\b" + (r"(?!\s*\()" if wort == "REPLACE" else "")
            if re.search(muster, ohne, re.IGNORECASE):
                raise _WerkzeugFehler(f"Schlüsselwort {wort} ist nicht erlaubt (nur lesende SELECT-/WITH-Abfragen).")
        return s

    @staticmethod
    def _sql_tabelle(spalten: list[str], zeilen: list, gekappt: bool) -> str:
        """Texttabelle: Spaltennamen, Zeilen mit " | ", Zeilenzahl, Hinweis bei Kappung."""
        def zelle(wert) -> str:
            if wert is None:
                return "NULL"
            if isinstance(wert, bytes):
                return f"<{len(wert)} Bytes>"
            t = " ".join(str(wert).split())
            if len(t) > SQL_ZELLE_MAX_ZEICHEN:
                t = t[:SQL_ZELLE_MAX_ZEICHEN].rstrip() + "…"
            return t

        teile = [" | ".join(spalten)] if spalten else []
        for z in zeilen:
            teile.append(" | ".join(zelle(w) for w in z))
        koerper = "\n".join(teile)
        if len(koerper) > SQL_MAX_ZEICHEN:
            koerper = koerper[:SQL_MAX_ZEICHEN] + f"\n[… Ausgabe bei {SQL_MAX_ZEICHEN} Zeichen gekappt]"
        schluss = f"{len(zeilen)} Zeile(n)"
        if gekappt:
            schluss += f" - gekappt bei {SQL_MAX_ZEILEN}, mit WHERE und LIMIT eingrenzen"
        return f"{koerper}\n{schluss}" if koerper else schluss

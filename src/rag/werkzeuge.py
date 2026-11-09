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
* ``vorschlag_verschieben``, ``vorschlag_umbenennen``, ``vorschlag_metadaten`` -
  gepruefte Aktionsvorschlaege (Baustein 2, ``docs/CHAT_MCP_PLAN.md`` 5.1). Sie
  fuehren nichts aus: der Vorschlag landet in ``vorschlaege``, die Oberflaeche
  zeigt ihn als Knopf, erst der Klick des Nutzers handelt. Hoechstens einer je
  Art und Dokument (ein spaeterer ersetzt den frueheren).
* ``sql_abfrage`` - nur wenn freigegeben: lesende SQL-Abfrage auf der
  Suchdatenbank (Nur-Lese-Verbindung, ``query_only``, Schluesselwort-Pruefung,
  Zeitlimit, Zeilen- und Zeichenkappung).

Die nummerierungsfreie Logik (Argumente der Suche, Ordnervorschlag,
Korrespondent, SQL) liegt in :mod:`src.rag.werkzeug_kern` und wird auch vom
MCP-Server genutzt (Baustein 1, ``docs/CHAT_MCP_PLAN.md``); der
Werkzeugkasten ist die Huelle mit Registrierung, D-Nummern, Protokoll und
Fehlertexten.

Qt-frei. Werkzeuge werfen keine Exceptions nach aussen: Fehler kommen als
Text (``"Fehler: ..."``) zurueck und stehen mit jedem Aufruf als
:class:`Schritt` im ``protokoll``.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from src.ml.llm_provider import Werkzeug, WerkzeugAufruf
from src.rag.bezug import Bezug, gleicher_pfad
from src.rag.daten import ChatDaten
from src.rag.retrieval import RetrievalService, RetrievedDoc
from src.rag.werkzeug_kern import (  # noqa: F401 - Konstanten auch hier importierbar (Tests, Aufrufer)
    AEHNLICHE_MAX,
    AEHNLICHKEIT_TEXT_ZEICHEN,
    SORTIERUNGEN,
    SQL_MAX_ZEICHEN,
    SQL_MAX_ZEILEN,
    SQL_VERBOTEN,
    SQL_ZELLE_MAX_ZEICHEN,
    SUCHE_ANZAHL_MAX,
    SUCHE_ANZAHL_STANDARD,
    TYP_ALIASE,
    TYPEN,
    Dokument,
    Vorschlag,
    WerkzeugFehler,
    begruendung_kuerzen,
    datum_pruefen,
    korrespondent_info,
    korrespondent_text,
    korrespondenten_suchen,
    liegt_in,
    metadaten_pruefen,
    neuer_name_pruefen,
    ordner_vorschlag,
    quelle_pruefen,
    sql_abfrage,
    sql_beschreibung,
    sql_pruefen,
    sql_tabelle,
    such_argumente,
    such_filter,
    such_kennung,
    text_argument,
    verschieben_pruefen,
    vorschlag_aufnehmen,
    zahl_argument,
)
from src.search import ausgabe
from src.search.db import fts_abfrage
from src.utils.config import ChatConfig

# Suche: Kappung der Ausgabe
SUCHE_MAX_ZEICHEN = 6000
FUNDSTELLEN_MAX_ZEICHEN = 600
# Erfundene Werkzeugnamen, die eindeutig ein echtes Werkzeug meinen
WERKZEUG_ALIASE = {
    "abfrage": "suche", "suchen": "suche", "search": "suche", "volltextsuche": "suche", "finde": "suche",
    "lesen": "dokument_lesen", "dokument": "dokument_lesen", "read": "dokument_lesen",
    "read_document": "dokument_lesen", "dokument_lesen_seiten": "dokument_lesen",
    "ordner": "ordner_vorschlag", "ordnervorschlag": "ordner_vorschlag", "folder_suggestion": "ordner_vorschlag",
    "korrespondent": "korrespondent_info", "korrespondenten_info": "korrespondent_info",
    "sql": "sql_abfrage", "sql_query": "sql_abfrage", "abfrage_sql": "sql_abfrage",
    "verschieben": "vorschlag_verschieben", "verschieben_vorschlag": "vorschlag_verschieben",
    "umbenennen": "vorschlag_umbenennen", "umbenennen_vorschlag": "vorschlag_umbenennen",
    "metadaten": "vorschlag_metadaten", "metadaten_vorschlag": "vorschlag_metadaten",
}

# Lesen
LESEN_ZEICHEN_STANDARD = 12000
LESEN_ZEICHEN_MAX = 40000

# Status eines Dokuments im Chat: zitiert schlaegt gelesen schlaegt gefunden
STATUS_RANG = {"gefunden": 0, "gelesen": 1, "zitiert": 2}

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


# Fehler, den das Modell als Text bekommt (gemeinsam mit dem Kern und dem MCP-Server)
_WerkzeugFehler = WerkzeugFehler


def _betrag(wert) -> str:
    """REAL aus dem Suchindex als Text ("480.00"); leer, wenn nicht gesetzt."""
    if wert in (None, ""):
        return ""
    try:
        return f"{float(wert):.2f}"
    except (TypeError, ValueError):
        return str(wert)


_text = text_argument
_zahl = zahl_argument


def _param(typ: str, beschreibung: str, **mehr) -> dict:
    return {"type": typ, "description": beschreibung, **mehr}


_datum_pruefen = datum_pruefen


class Werkzeugkasten:
    """Werkzeuge des Chats ueber dem Suchindex mit chat-lokalen Dokumentnummern.

    Args:
        db: Datenquelle (:class:`~src.rag.daten.ChatDaten`), in der Oberflaeche
            :class:`~src.utils.database.Database`; ``db.suchindex`` ist der
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
        vorschlaege: Gepruefte Vorschlaege der Vorschlags-Werkzeuge
            (:class:`~src.rag.werkzeug_kern.Vorschlag`), hoechstens einer je
            Art und Dokument.
    """

    # Alle so viele VM-Schritte prueft der Fortschritts-Handler das SQL-Zeitlimit
    # (Klassenattribut, damit Tests den Timer-Weg allein pruefen koennen)
    SQL_HANDLER_SCHRITTE = 200  # wie src.rag.werkzeug_kern.SQL_HANDLER_SCHRITTE

    def __init__(
        self,
        db: ChatDaten | None,
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
        self.vorschlaege: list[Vorschlag] = []
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
                    "Was PDF Sortier Meister über einen Korrespondenten (Gegenpartei des Nutzers: Person, Firma oder Behörde) gelernt hat: "
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
            Werkzeug(
                name="vorschlag_verschieben",
                beschreibung=(
                    "Dem Nutzer vorschlagen, ein Dokument in einen Ordner zu verschieben (einsortieren). Du führst "
                    "nichts aus: Der Vorschlag erscheint als Knopf, erst der Klick des Nutzers verschiebt. Nimm "
                    "nur Ordner aus ordner_vorschlag, aus Suchtreffern oder aus der Liste der Zielordner - erfinde "
                    "keine. Ein späterer Vorschlag für dasselbe Dokument ersetzt den früheren."
                ),
                parameter={
                    "type": "object",
                    "properties": {
                        "dokument": _param("string", "Nummer des Dokuments, z. B. \"D3\"; Standard D1 (Bezugsdokument)."),
                        "zielordner": _param("string", "Ordner wie in ordner_vorschlag relativ zum Zielordner "
                                                       "(z. B. 'Ablage/Energie/2024') oder als absoluter Pfad."),
                        "begruendung": _param("string", "Ein kurzer Satz, warum dieser Ordner passt."),
                    },
                    "required": ["zielordner", "begruendung"],
                },
            ),
            Werkzeug(
                name="vorschlag_umbenennen",
                beschreibung=(
                    "Dem Nutzer einen neuen Dateinamen für ein Dokument vorschlagen. Du führst nichts aus: Der "
                    "Vorschlag erscheint als Knopf, erst der Klick des Nutzers benennt um. Nur der Dateiname, "
                    "ohne Ordner; die Endung bleibt. Unzulässige Zeichen werden ersetzt. Ein späterer Vorschlag "
                    "für dasselbe Dokument ersetzt den früheren."
                ),
                parameter={
                    "type": "object",
                    "properties": {
                        "dokument": _param("string", "Nummer des Dokuments, z. B. \"D3\"; Standard D1 (Bezugsdokument)."),
                        "name": _param("string", "Neuer Dateiname, z. B. '2024-03-01 Stadtwerke Jahresabrechnung "
                                                 "Strom'."),
                        "begruendung": _param("string", "Ein kurzer Satz, warum dieser Name passt."),
                    },
                    "required": ["name", "begruendung"],
                },
            ),
            Werkzeug(
                name="vorschlag_metadaten",
                beschreibung=(
                    "Dem Nutzer Metadaten für ein PDF vorschlagen (Korrespondent, Kategorie, Steuerjahr, Betrag, "
                    "Datum). Du führst nichts aus: Der Vorschlag erscheint als Knopf, erst der Klick des Nutzers "
                    "speichert ihn im PDF. Nur Felder angeben, die im Dokument belegt sind. Ein späterer "
                    "Vorschlag für dasselbe Dokument ersetzt den früheren."
                ),
                parameter={
                    "type": "object",
                    "properties": {
                        "dokument": _param("string", "Nummer des Dokuments, z. B. \"D3\"; Standard D1 (Bezugsdokument)."),
                        "korrespondent": _param("string", "Gegenpartei (Person, Firma, Behörde), Schreibweise wie "
                                                          "in korrespondent_info, falls bekannt."),
                        "kategorie": _param("string", "Genau eine Kategorie, z. B. 'Rechnung' oder 'Vertrag'."),
                        "steuerjahr": _param("string", "Vierstellig, z. B. '2024'."),
                        "betrag": _param("string", "Bruttobetrag als Zahl, z. B. '480.00'."),
                        "datum": _param("string", "Datum des Dokuments im Format JJJJ-MM-TT."),
                        "begruendung": _param("string", "Ein kurzer Satz, woher die Werte stammen."),
                    },
                    "required": ["begruendung"],
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
        return sql_beschreibung(
            self.sql_zeitlimit_s,
            "Ein Dokument aus dem Ergebnis liest du mit dokument_lesen und dokument = \"id:<dokumente.id>\".",
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
            "vorschlag_verschieben": self._vorschlag_verschieben,
            "vorschlag_umbenennen": self._vorschlag_umbenennen,
            "vorschlag_metadaten": self._vorschlag_metadaten,
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

        args = such_argumente(argumente)
        kennung = such_kennung(args)
        sortierung = args["sortierung"]
        try:
            rohe = list(self.db.search_documents(
                query=fts_abfrage(args["abfrage"]), limit=args["anzahl"], typ=args["typ"],
                sortierung=sortierung if sortierung != "relevanz" else "", **such_filter(args),
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

        # Vorschlaege der Sortierlogik liegen nur fuer das Bezugsdokument vor
        v = ordner_vorschlag(
            Dokument(doc.file_path, doc.filename, self._volltext_fuer(doc, AEHNLICHKEIT_TEXT_ZEICHEN)),
            self.db, self.wurzeln, self.scan_ordner,
            self.sortier_vorschlaege if ist_bezug else None,
            im_scan_eingang=self._im_scan_eingang(doc.file_path),
        )

        zeilen = [f"Ordnervorschlag für [D{doc.index}] {doc.filename}:"]
        if v.wurzeln:
            zeilen.append("Zielordner: " + ", ".join(w.name for w in v.wurzeln))
        if v.sortier_vorschlaege is not None:
            zeilen.append("Vorschläge der Sortierlogik (bester zuerst): "
                          + ("; ".join(v.sortier_vorschlaege) or "keiner"))
        else:
            zeilen.append("Vorschläge der Sortierlogik: keiner (liegen nur für das Bezugsdokument vor)")

        if v.aehnliche:
            zeilen.append("Ähnliche, bereits einsortierte Dokumente (Ordner relativ zum Zielordner):")
            for s in v.aehnliche:
                zeilen.append(f"- {s.filename} - Ordner: {s.folder}" + (f" - Jahr: {s.year}" if s.year else ""))
            zeilen.append("Hinweis: Das Dokument gehört in den Ordner seines eigenen Jahres, nicht in den eines "
                          "ähnlichen Dokuments aus einem anderen Jahr.")
        else:
            zeilen.append("Ähnliche, bereits einsortierte Dokumente: keine gefunden.")

        # Scan-Eingang bzw. aktueller Ablageort
        wer = "Das Bezugsdokument" if ist_bezug else "Das Dokument"
        if v.im_scan_eingang:
            zeilen.append(f"{wer} liegt noch unsortiert im Scan-Eingang (noch kein Ablageort).")
        elif v.ablageort:
            zeilen.append(f"{wer} liegt nicht im Scan-Eingang; aktueller Ablageort: {v.ablageort}")

        anzahl_vorschlaege = len(v.sortier_vorschlaege or [])
        zusammenfassung = (f"Ordnervorschlag für D{doc.index}: {anzahl_vorschlaege} Vorschläge, "
                           f"{len(v.aehnliche)} ähnliche Dokumente")
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
        return liegt_in(pfad, self.scan_ordner)

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
        info = korrespondent_info(_text(argumente, "name"), self.db)
        if not info.bekannt:
            return korrespondent_text(info), f"Korrespondent „{info.gesucht}“: unbekannt", []
        return korrespondent_text(info), f"Korrespondent „{info.gesucht}“: {info.name}", []

    def _korrespondenten_suchen(self, name: str) -> list[dict]:
        """Korrespondenten, deren Name oder Alias den Suchbegriff enthaelt; exakte Alias-Treffer zuerst."""
        return korrespondenten_suchen(name, self.db)

    # ------------------------------------------------------------------ #
    # Vorschlaege: pruefen und merken, nichts ausfuehren (Baustein 2)    #
    # ------------------------------------------------------------------ #

    def _vorschlag_dokument(self, argumente: dict) -> tuple[RetrievedDoc, Path]:
        """Dokument eines Vorschlags (Standard: Bezugsdokument) und sein gepruefter Pfad."""
        kennung = argumente.get("dokument")
        if kennung in (None, ""):
            doc = self._bezug_doc()
            if doc is None or not self._ist_bezug(doc):
                raise _WerkzeugFehler("Kein Bezugsdokument im Chat - Argument „dokument“ angeben (z. B. \"D3\").")
        else:
            doc = self._dokument_aus_kennung(kennung)
        quelle = quelle_pruefen(doc.file_path, self.wurzeln, self.scan_ordner, ist_bezug=self._ist_bezug(doc))
        return doc, quelle

    def _vorschlag_merken(self, doc: RetrievedDoc, vorschlag: Vorschlag, was: str) -> tuple[str, str, list[int]]:
        vorschlag_aufnehmen(self.vorschlaege, vorschlag)
        text = (f"Vorschlag notiert: [D{doc.index}] {was}. Es wurde nichts ausgeführt - der Nutzer sieht einen "
                "Knopf und entscheidet selbst. Erwähne den Vorschlag in deiner Antwort kurz.")
        return text, f"Vorschlag für D{doc.index}: {was}", [doc.index]

    def _vorschlag_verschieben(self, argumente: dict) -> tuple[str, str, list[int]]:
        doc, quelle = self._vorschlag_dokument(argumente)
        ziel, anzeige = verschieben_pruefen(quelle, _text(argumente, "zielordner"), self.wurzeln)
        vorschlag = Vorschlag("verschieben", str(quelle), ziel=str(ziel), anzeige=anzeige,
                              begruendung=begruendung_kuerzen(_text(argumente, "begruendung")))
        return self._vorschlag_merken(doc, vorschlag, f"{quelle.name} nach {anzeige} verschieben")

    def _vorschlag_umbenennen(self, argumente: dict) -> tuple[str, str, list[int]]:
        doc, quelle = self._vorschlag_dokument(argumente)
        name = neuer_name_pruefen(quelle, _text(argumente, "name"))
        vorschlag = Vorschlag("umbenennen", str(quelle), name=name,
                              begruendung=begruendung_kuerzen(_text(argumente, "begruendung")))
        return self._vorschlag_merken(doc, vorschlag, f"{quelle.name} umbenennen in {name}")

    def _vorschlag_metadaten(self, argumente: dict) -> tuple[str, str, list[int]]:
        doc, quelle = self._vorschlag_dokument(argumente)
        if quelle.suffix.lower() != ".pdf":
            raise _WerkzeugFehler(f"Metadaten lassen sich nur in PDFs speichern, nicht in „{quelle.name}“.")
        vorschlag = Vorschlag("metadaten", str(quelle), felder=metadaten_pruefen(argumente),
                              begruendung=begruendung_kuerzen(_text(argumente, "begruendung")))
        return self._vorschlag_merken(doc, vorschlag, f"Metadaten für {quelle.name}: {vorschlag.felder_text()}")

    # ------------------------------------------------------------------ #
    # sql_abfrage                                                        #
    # ------------------------------------------------------------------ #

    def _sql_abfrage(self, argumente: dict) -> tuple[str, str, list[int]]:
        sql = _text(argumente, "sql")
        if not sql:
            raise _WerkzeugFehler("Argument „sql“ fehlt.")
        sql = self._sql_pruefen(sql)
        suchindex = self._suchindex()
        erg = sql_abfrage(getattr(suchindex, "db_datei", None), sql, self.sql_zeitlimit_s,
                          handler_schritte=self.SQL_HANDLER_SCHRITTE, geprueft=True)
        zusammenfassung = f"SQL: {len(erg.zeilen)} Zeilen" + (" (gekappt)" if erg.gekappt else "")
        return sql_tabelle(erg), zusammenfassung, []

    @staticmethod
    def _sql_pruefen(sql: str) -> str:
        """Genau eine lesende Anweisung (SELECT/WITH) ohne verbotene Schluesselwoerter; sonst Fehler."""
        return sql_pruefen(sql)

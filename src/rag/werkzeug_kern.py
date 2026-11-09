"""Kernlogik der Werkzeuge, gemeinsam fuer Chat und MCP-Server (Baustein 1, ``docs/CHAT_MCP_PLAN.md``).

Der Chat (:class:`src.rag.werkzeuge.Werkzeugkasten`) zeigt dem Modell
chat-lokale Nummern D1, D2, ...; der MCP-Server (``src/search/mcp_server.py``)
zeigt Index-IDs. Die Logik darunter ist dieselbe und liegt hier -
nummerierungsfrei:

* :func:`such_argumente` - Argumente der Suche pruefen und vereinheitlichen
  (Typ-Aliase wie ``excel`` oder ``e-mail``, Sortierung, Anzahl, Datumsfilter).
* :func:`ordner_vorschlag` - aehnliche, bereits einsortierte Dokumente
  (:func:`src.core.similar_documents.find_similar_documents`), Lage im
  Scan-Eingang bzw. aktueller Ablageort, Vorschlaege der Sortierlogik.
* :func:`korrespondent_info` - was ueber einen Korrespondenten bekannt ist.
* :func:`sql_pruefen` und :func:`sql_abfrage` - lesende SQL-Abfrage auf der
  Suchdatenbank (Nur-Lese-Verbindung, ``query_only``, Schluesselwort-Pruefung,
  Zeitlimit, Zeilen- und Zeichenkappung).
* :class:`Vorschlag` mit :func:`quelle_pruefen`, :func:`verschieben_pruefen`,
  :func:`neuer_name_pruefen` und :func:`metadaten_pruefen` - gepruefte
  Aktionsvorschlaege des Chats (Baustein 2); nur der Chat bietet sie an.

Die Datenklassen tragen Daten, keinen fertigen Text; Werkzeugkasten und
MCP-Server formatieren selbst. Nur wo keine Dokumentnummer vorkommt
(Korrespondent, SQL-Tabelle), gibt es hier eine gemeinsame Textform.
Fehler, die das Modell als Text bekommen soll, sind :class:`WerkzeugFehler`.

Qt-frei, ohne SQLAlchemy, ohne Import von ``src.utils.database`` (laeuft im
Dienst ``pdfsm-dienst``).

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING

from src.core.similar_documents import SimilarDocument, find_similar_documents
from src.rag.bezug import ablageort

if TYPE_CHECKING:
    from src.rag.daten import ChatDaten

# Suche
SUCHE_ANZAHL_STANDARD = 8
SUCHE_ANZAHL_MAX = 20
TYPEN = ("pdf", "office", "md", "mail")
TYP_ALIASE = {
    "excel": "office", "xlsx": "office", "xls": "office", "word": "office", "docx": "office", "doc": "office",
    "odt": "office", "tabelle": "office", "tabellen": "office",
    "e-mail": "mail", "email": "mail", "mails": "mail", "e-mails": "mail", "emails": "mail", "nachricht": "mail",
    "markdown": "md", "pdfs": "pdf",
}
SORTIERUNGEN = ("relevanz", "neu", "alt")
# Filter der Suche in der Reihenfolge, in der sie beschrieben werden
SUCH_FILTER = ("ordner", "von", "bis", "steuerjahr", "kategorie", "korrespondent")

# Ordnervorschlag: Volltext fuer die Aehnlichkeitssuche (mehr liest der Scorer ohnehin nicht)
AEHNLICHKEIT_TEXT_ZEICHEN = 20000
AEHNLICHE_MAX = 8

# SQL
SQL_MAX_ZEILEN = 200
SQL_MAX_ZEICHEN = 20000
SQL_ZELLE_MAX_ZEICHEN = 300
SQL_VERBOTEN = ("ATTACH", "DETACH", "PRAGMA", "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
                "CREATE", "REPLACE", "VACUUM", "REINDEX")
# Alle so viele VM-Schritte prueft der Fortschritts-Handler das Zeitlimit
SQL_HANDLER_SCHRITTE = 200
SQL_ZEITLIMIT_STANDARD_S = 15.0


class WerkzeugFehler(Exception):  # noqa: N818 - Name wie im Werkzeugkasten (_WerkzeugFehler)
    """Fehler, den das Modell als Text bekommt (fehlende Argumente, unbekanntes Dokument ...)."""


# --------------------------------------------------------------------------- Argumente

def text_argument(argumente: dict, name: str) -> str:
    """Argument als Text ohne Rand; fehlend = leer."""
    wert = argumente.get(name)
    if wert is None:
        return ""
    return str(wert).strip()


def zahl_argument(argumente: dict, name: str, standard: int, minimum: int, maximum: int) -> int:
    """Ganze Zahl, auf ``[minimum, maximum]`` gekappt; fehlend = ``standard``."""
    wert = argumente.get(name)
    if wert in (None, ""):
        return standard
    try:
        zahl = int(float(str(wert).strip()))
    except (TypeError, ValueError):
        raise WerkzeugFehler(f"Argument „{name}“ muss eine ganze Zahl sein, nicht „{wert}“.") from None
    return max(minimum, min(maximum, zahl))


def datum_pruefen(wert: str, name: str) -> str:
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
    raise WerkzeugFehler(f"Argument „{name}“ muss ein gültiges Datum im Format JJJJ-MM-TT sein, nicht „{wert}“.")


def liegt_in(pfad, ordner) -> bool:
    """True, wenn ``pfad`` ``ordner`` selbst ist oder darin liegt (aufgeloeste Pfade)."""
    if not pfad or not ordner:
        return False
    try:
        Path(pfad).resolve().relative_to(Path(ordner).resolve())
        return True
    except (ValueError, OSError):
        return False


# --------------------------------------------------------------------------- suche

def such_argumente(
    argumente: dict,
    *,
    anzahl_standard: int = SUCHE_ANZAHL_STANDARD,
    anzahl_max: int = SUCHE_ANZAHL_MAX,
    abfrage_pflicht: bool = True,
) -> dict:
    """Argumente der Suche pruefen und vereinheitlichen.

    Liefert ``abfrage``, ``typ`` (Aliase abgebildet, ohne Doppelte, leer =
    alle), ``sortierung`` (``relevanz`` | ``neu`` | ``alt``), ``anzahl``
    (gekappt) und die gesetzten Filter aus :data:`SUCH_FILTER` (``von``/``bis``
    als JJJJ-MM-TT). Unbrauchbares wirft :class:`WerkzeugFehler`.
    ``abfrage_pflicht=False`` laesst eine leere Abfrage zu (MCP: nur Filter,
    der Index liefert dann alle passenden Dokumente).
    """
    abfrage = text_argument(argumente, "abfrage")
    if not abfrage and abfrage_pflicht:
        raise WerkzeugFehler("Argument „abfrage“ fehlt.")

    typ = text_argument(argumente, "typ").lower()
    if typ:
        # Modelle schreiben gern "excel" oder "e-mail": gaengige Schreibweisen abbilden
        typen = [TYP_ALIASE.get(t.strip(), t.strip()) for t in typ.split(",") if t.strip()]
        typen = list(dict.fromkeys(typen))
        unbekannt = [t for t in typen if t not in TYPEN]
        if unbekannt:
            raise WerkzeugFehler(f"Unbekannter typ „{unbekannt[0]}“ - erlaubt: "
                                 f"{', '.join(TYPEN)} (auch Kombination 'pdf,office').")
        typ = ",".join(typen)
    sortierung = text_argument(argumente, "sortierung").lower() or "relevanz"
    if sortierung not in SORTIERUNGEN:
        raise WerkzeugFehler(f"Unbekannte sortierung „{sortierung}“ - erlaubt: {', '.join(SORTIERUNGEN)}.")
    anzahl = zahl_argument(argumente, "anzahl", anzahl_standard, 1, anzahl_max)

    ergebnis: dict = {"abfrage": abfrage, "typ": typ, "sortierung": sortierung, "anzahl": anzahl}
    for name in SUCH_FILTER:
        wert = text_argument(argumente, name)
        if wert:
            ergebnis[name] = datum_pruefen(wert, name) if name in ("von", "bis") else wert
    return ergebnis


def such_filter(argumente: dict) -> dict[str, str]:
    """Nur die gesetzten Filter aus einem Ergebnis von :func:`such_argumente`."""
    return {k: argumente[k] for k in SUCH_FILTER if argumente.get(k)}


def such_kennung(argumente: dict) -> str:
    """``„abfrage“ (typ=pdf, sortierung=neu, ordner=Steuer)`` fuer Meldungen und Protokoll."""
    teile = [("typ", argumente.get("typ") or ""),
             ("sortierung", argumente.get("sortierung") if argumente.get("sortierung") != "relevanz" else ""),
             *such_filter(argumente).items()]
    beschreibung = ", ".join(f"{k}={v}" for k, v in teile if v)
    return f"„{argumente.get('abfrage', '')}“" + (f" ({beschreibung})" if beschreibung else "")


# --------------------------------------------------------------------------- ordner_vorschlag

@dataclass
class Dokument:
    """Ein Dokument, fuer das ein Ablageort gesucht wird.

    Attributes:
        pfad: Aktueller Pfad der Datei.
        name: Dateiname (bzw. Anzeigename).
        text: Volltext fuer die Aehnlichkeitssuche (leer = keine aehnlichen Dokumente).
    """

    pfad: str
    name: str
    text: str = ""


@dataclass
class OrdnerVorschlag:
    """Was ueber den Ablageort eines Dokuments bekannt ist (ohne Text, ohne Nummer).

    Attributes:
        pfad: Pfad des Dokuments.
        name: Name des Dokuments.
        wurzeln: Zielordner, relativ zu denen Ablageorte angegeben werden.
        sortier_vorschlaege: Vorschlaege der Sortierlogik, bester zuerst;
            ``None``, wenn keine vorliegen (sie entstehen nur in der
            Oberflaeche und nur fuer das Bezugsdokument).
        aehnliche: Aehnliche, bereits einsortierte Dokumente (ohne das Dokument selbst).
        im_scan_eingang: Das Dokument liegt noch unsortiert im Scan-Eingang.
        ablageort: Aktueller Ablageort relativ zu einem Zielordner
            ("Ablage/Steuer 2024/Energie"); leer im Scan-Eingang.
    """

    pfad: str
    name: str
    wurzeln: list[Path] = field(default_factory=list)
    sortier_vorschlaege: list[str] | None = None
    aehnliche: list[SimilarDocument] = field(default_factory=list)
    im_scan_eingang: bool = False
    ablageort: str = ""


def ordner_vorschlag(
    doc: Dokument,
    daten: ChatDaten | None,
    wurzeln: Sequence[Path | str] = (),
    scan_ordner: Path | str | None = None,
    sortier_vorschlaege: Sequence[str] | None = None,
    *,
    im_scan_eingang: bool | None = None,
    limit: int = AEHNLICHE_MAX,
) -> OrdnerVorschlag:
    """Ablageort eines Dokuments klaeren.

    Args:
        doc: Das Dokument mit Volltext.
        daten: Datenquelle fuer die Aehnlichkeitssuche (Historie und Index);
            ``None`` = keine aehnlichen Dokumente.
        wurzeln: Zielordner.
        scan_ordner: Scan-Eingang.
        sortier_vorschlaege: Vorschlaege der Sortierlogik oder ``None``.
        im_scan_eingang: Vorgabe des Aufrufers (z.B. ueber den Bezug des
            Chats); ``None`` = aus ``scan_ordner`` bestimmen.
        limit: Hoechstzahl aehnlicher Dokumente.

    Fehler der Datenquelle fuehren zu einer leeren Liste aehnlicher Dokumente.
    """
    wurzel_pfade = [Path(w) for w in (wurzeln or ()) if w]
    aehnliche: list[SimilarDocument] = []
    if daten is not None and (doc.text or "").strip():
        try:
            aehnliche = list(find_similar_documents(doc.text, None, wurzel_pfade, db=daten, limit=limit))
        except Exception:  # noqa: BLE001 - Kontext ist optional
            aehnliche = []
        # Das Dokument selbst ist kein aehnliches Dokument
        eigener = (doc.name or "").casefold()
        aehnliche = [s for s in aehnliche if (s.filename or "").casefold() != eigener]
    if im_scan_eingang is None:
        im_scan_eingang = liegt_in(doc.pfad, scan_ordner)
    ort = "" if im_scan_eingang else ablageort(doc.pfad, wurzel_pfade)
    return OrdnerVorschlag(
        pfad=doc.pfad,
        name=doc.name,
        wurzeln=wurzel_pfade,
        sortier_vorschlaege=None if sortier_vorschlaege is None else [str(v) for v in sortier_vorschlaege if v],
        aehnliche=aehnliche,
        im_scan_eingang=bool(im_scan_eingang),
        ablageort=ort,
    )


# --------------------------------------------------------------------------- korrespondent_info

@dataclass
class KorrespondentInfo:
    """Was ueber einen Korrespondenten bekannt ist.

    Attributes:
        gesucht: Der gesuchte Name.
        name: Anzeigename (Eintrag der Verwaltung, sonst der gesuchte Name).
        eintrag: Eintrag der Korrespondenten-Verwaltung (``aliases``,
            ``kategorie``, ``notizen``, ``usage_count``) oder ``None``.
        gelernt: Gelernte Metadaten (``subject``, ``mwst_satz``,
            ``steuerlich_absetzbar``, ``waehrung``) oder ``None``.
        weitere: Namen weiterer passender Korrespondenten.
    """

    gesucht: str
    name: str
    eintrag: dict | None = None
    gelernt: dict | None = None
    weitere: list[str] = field(default_factory=list)

    @property
    def bekannt(self) -> bool:
        return self.eintrag is not None or bool(self.gelernt)


def korrespondenten_suchen(name: str, daten: ChatDaten | None) -> list[dict]:
    """Korrespondenten, deren Name oder Alias den Suchbegriff enthaelt; exakte Treffer (auch Alias) zuerst."""
    if daten is None:
        return []
    needle = name.casefold()
    try:
        alle = list(daten.list_korrespondenten() or [])
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


def korrespondent_info(name: str, daten: ChatDaten | None) -> KorrespondentInfo:
    """Eintrag der Verwaltung (genau, sonst Name/Alias enthaelt den Suchbegriff) und gelernte Metadaten.

    Fehler der Datenquelle zaehlen als "nichts bekannt".
    """
    name = (name or "").strip()
    if not name:
        raise WerkzeugFehler("Argument „name“ fehlt.")
    eintrag = None
    if daten is not None:
        try:
            eintrag = daten.get_korrespondent(name)
        except Exception:  # noqa: BLE001 - Verwaltung ist optional
            eintrag = None
    weitere: list[dict] = []
    if eintrag is None:
        treffer = korrespondenten_suchen(name, daten)
        if treffer:
            eintrag, weitere = treffer[0], treffer[1:]
    anzeigename = (eintrag or {}).get("name") or name
    gelernt = None
    if daten is not None:
        try:
            gelernt = daten.get_korrespondent_metadata(anzeigename) or None
        except Exception:  # noqa: BLE001
            gelernt = None
    return KorrespondentInfo(
        gesucht=name,
        name=anzeigename,
        eintrag=eintrag,
        gelernt=gelernt,
        weitere=[str(w.get("name") or "") for w in weitere if w.get("name")],
    )


def korrespondent_text(info: KorrespondentInfo) -> str:
    """Textform fuer Modell und KI-Assistent (keine Dokumentnummern, daher gemeinsam)."""
    if not info.bekannt:
        return f"Kein Korrespondent „{info.gesucht}“ bekannt."
    eintrag, gelernt = info.eintrag, info.gelernt
    zeilen = [f"Korrespondent: {info.name}"]
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
    if info.weitere:
        zeilen.append("Weitere passende Korrespondenten: " + ", ".join(info.weitere[:5]))
    return "\n".join(zeilen)


# --------------------------------------------------------------------------- sql_abfrage

@dataclass
class SqlErgebnis:
    """Ergebnis einer SQL-Abfrage: Spaltennamen, hoechstens :data:`SQL_MAX_ZEILEN` Zeilen, Kappung."""

    spalten: list[str]
    zeilen: list[tuple]
    gekappt: bool = False


def sql_beschreibung(zeitlimit_s: float, lesen_hinweis: str) -> str:
    """Werkzeugbeschreibung mit kompaktem Schema (``docs/SUCHE_SCHEMA.md``).

    ``lesen_hinweis``: letzter Satz, wie ein Dokument aus dem Ergebnis gelesen
    wird (Chat: ``dokument = "id:<dokumente.id>"``, MCP: ``dok_id``).
    """
    return (
        "Nur lesende SQL-Abfrage (SQLite) auf der Suchdatenbank - für Auswertungen, die die Suche nicht "
        "leistet: Summen, Zählungen, Gruppierungen, Listen nach Datum oder Betrag. Genau eine SELECT- oder "
        f"WITH-Anweisung; höchstens {SQL_MAX_ZEILEN} Zeilen, Zeitlimit {zeitlimit_s:g} s - mit WHERE "
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
        + lesen_hinweis
    )


def sql_pruefen(sql: str) -> str:
    """Genau eine lesende Anweisung (SELECT/WITH) ohne verbotene Schluesselwoerter; sonst :class:`WerkzeugFehler`.

    Liefert die Anweisung ohne Rand und ohne abschliessendes ``;``.
    """
    s = (sql or "").strip()
    if s.endswith(";"):
        s = s[:-1].rstrip()
    if not s:
        raise WerkzeugFehler("Leere SQL-Anweisung.")
    # Literale, Bezeichner in Anfuehrungszeichen und Kommentare fuer die Pruefung ausblenden
    ohne = re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|`[^`]*`|\[[^\]]*\]", " ", s)
    ohne = re.sub(r"--[^\n]*", " ", ohne)
    ohne = re.sub(r"/\*.*?\*/", " ", ohne, flags=re.S)
    if ";" in ohne:
        raise WerkzeugFehler("Nur eine einzelne Anweisung erlaubt (kein ';' mitten in der Abfrage).")
    # Zeilenumbruch vor dem ';', damit ein Zeilenkommentar am Ende es nicht schluckt
    if not sqlite3.complete_statement(s + "\n;"):
        raise WerkzeugFehler("Unvollständige Anweisung (fehlendes Anführungszeichen oder Klammer?).")
    m = re.match(r"\s*([A-Za-z]+)", ohne)
    erstes = m.group(1).upper() if m else ""
    if erstes not in ("SELECT", "WITH"):
        raise WerkzeugFehler("Nur lesende Abfragen: die Anweisung muss mit SELECT oder WITH beginnen.")
    for wort in SQL_VERBOTEN:
        # replace(x, y, z) ist eine Funktion und erlaubt; REPLACE INTO nicht
        muster = r"\b" + wort + r"\b" + (r"(?!\s*\()" if wort == "REPLACE" else "")
        if re.search(muster, ohne, re.IGNORECASE):
            raise WerkzeugFehler(f"Schlüsselwort {wort} ist nicht erlaubt (nur lesende SELECT-/WITH-Abfragen).")
    return s


def sql_abfrage(
    db_pfad: Path | str | None,
    sql: str,
    zeitlimit_s: float = SQL_ZEITLIMIT_STANDARD_S,
    *,
    handler_schritte: int = SQL_HANDLER_SCHRITTE,
    geprueft: bool = False,
) -> SqlErgebnis:
    """Eine lesende SQL-Abfrage auf der Suchdatenbank ``db_pfad`` ausfuehren.

    Schutz in mehreren Lagen: :func:`sql_pruefen` (ausser ``geprueft``, wenn
    der Aufrufer schon geprueft hat), Nur-Lese-Verbindung (URI ``mode=ro``),
    ``PRAGMA query_only``, Zeitlimit ueber Fortschritts-Handler (alle
    ``handler_schritte`` VM-Schritte) und Timer mit ``interrupt()`` (greift
    auch in langen Einzelschritten wie grossen Sortierungen). Hoechstens
    :data:`SQL_MAX_ZEILEN` Zeilen.
    """
    if not geprueft:
        sql = sql_pruefen(sql)
    db_datei = Path(db_pfad) if db_pfad else None
    if db_datei is None or not db_datei.is_file():
        raise WerkzeugFehler("Suchdatenbank noch nicht vorhanden (der erste Indexlauf steht aus).")

    zeitlimit = float(zeitlimit_s)
    try:
        con = sqlite3.connect(db_datei.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    except sqlite3.Error as e:
        raise WerkzeugFehler(f"Suchdatenbank nicht lesbar: {e}") from e
    wecker = threading.Timer(zeitlimit, con.interrupt)
    wecker.daemon = True
    try:
        con.execute("PRAGMA query_only=1")
        con.execute("PRAGMA busy_timeout=30000")
        start = time.monotonic()

        def wache() -> int:
            # 1 = abbrechen -> sqlite3.OperationalError("interrupted")
            return 1 if time.monotonic() - start > zeitlimit else 0

        con.set_progress_handler(wache, handler_schritte)
        wecker.start()
        try:
            cursor = con.execute(sql)
            spalten = [d[0] for d in (cursor.description or [])]
            zeilen = cursor.fetchmany(SQL_MAX_ZEILEN + 1)
        except sqlite3.OperationalError as e:
            if "interrupt" in str(e).lower():
                raise WerkzeugFehler(f"Zeitlimit von {zeitlimit:g} s überschritten - "
                                     "Abfrage mit WHERE und LIMIT eingrenzen.") from None
            raise WerkzeugFehler(f"SQLite: {e}") from e
        except (sqlite3.Error, sqlite3.Warning) as e:
            raise WerkzeugFehler(f"SQLite: {e}") from e
    finally:
        wecker.cancel()
        con.close()

    gekappt = len(zeilen) > SQL_MAX_ZEILEN
    return SqlErgebnis(spalten=spalten, zeilen=[tuple(z) for z in zeilen[:SQL_MAX_ZEILEN]], gekappt=gekappt)


def sql_tabelle(ergebnis: SqlErgebnis) -> str:
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

    teile = [" | ".join(ergebnis.spalten)] if ergebnis.spalten else []
    for z in ergebnis.zeilen:
        teile.append(" | ".join(zelle(w) for w in z))
    koerper = "\n".join(teile)
    if len(koerper) > SQL_MAX_ZEICHEN:
        koerper = koerper[:SQL_MAX_ZEICHEN] + f"\n[… Ausgabe bei {SQL_MAX_ZEICHEN} Zeichen gekappt]"
    schluss = f"{len(ergebnis.zeilen)} Zeile(n)"
    if ergebnis.gekappt:
        schluss += f" - gekappt bei {SQL_MAX_ZEILEN}, mit WHERE und LIMIT eingrenzen"
    return f"{koerper}\n{schluss}" if koerper else schluss


# --------------------------------------------------------------------------- Vorschlaege (Baustein 2)
#
# Der Chat bleibt lesend: Das Modell kann Aktionen nur VORSCHLAGEN. Ein Vorschlag ist
# geprueft (Pfade gegen die Zielordner, Namen durch sanitize_filename, Kategorie durch
# clean_category), fuehrt aber nichts aus; die Oberflaeche zeigt ihn als Knopf, und erst
# der Klick des Nutzers loest die vorhandenen Ablaeufe aus (docs/CHAT_MCP_PLAN.md, 5.1).

VORSCHLAG_ARTEN = ("verschieben", "umbenennen", "metadaten")
METADATEN_FELDER = ("korrespondent", "kategorie", "steuerjahr", "betrag", "datum")
METADATEN_NAMEN = {"korrespondent": "Korrespondent", "kategorie": "Kategorie", "steuerjahr": "Steuerjahr",
                   "betrag": "Betrag", "datum": "Datum"}
BEGRUENDUNG_MAX_ZEICHEN = 300
KORRESPONDENT_MAX_ZEICHEN = 120
NAME_MAX_ZEICHEN = 180
_BETRAG_RE = re.compile(r"^-?\d+(?:\.\d{1,2})?$")


@dataclass
class Vorschlag:
    """Eine vom Modell vorgeschlagene, gepruefte Aktion; ausgefuehrt wird sie erst per Klick.

    Attributes:
        art: ``"verschieben"``, ``"umbenennen"`` oder ``"metadaten"``.
        quelle: Pfad des Dokuments.
        ziel: verschieben - Zielordner (Pfad).
        anzeige: verschieben - Zielordner relativ zum Zielordner (``"Ablage/Energie"``).
        name: umbenennen - neuer, bereinigter Dateiname mit Endung.
        felder: metadaten - gepruefte Werte (Schluessel aus ``METADATEN_FELDER``).
        begruendung: Begruendung des Modells (gekuerzt), fuer den Tooltip.
    """

    art: str
    quelle: str
    ziel: str = ""
    anzeige: str = ""
    name: str = ""
    felder: dict[str, str] = field(default_factory=dict)
    begruendung: str = ""

    def gleiche_aktion(self, anderer: Vorschlag) -> bool:
        """Gleiche Art fuer dasselbe Dokument (ein spaeterer Vorschlag ersetzt den frueheren)."""
        return self.art == anderer.art and gleicher_ort(self.quelle, anderer.quelle)

    def felder_text(self) -> str:
        """``"Korrespondent Telekom, Steuerjahr 2024"`` (Reihenfolge wie ``METADATEN_FELDER``)."""
        return ", ".join(f"{METADATEN_NAMEN[k]} {self.felder[k]}" for k in METADATEN_FELDER if self.felder.get(k))


def gleicher_ort(a, b) -> bool:
    """Dieselbe Datei bzw. derselbe Ordner (aufgeloeste Pfade; Rueckfall: Textvergleich)."""
    try:
        return Path(a).resolve() == Path(b).resolve()
    except (OSError, ValueError):
        return str(a) == str(b)


def begruendung_kuerzen(text) -> str:
    """Begruendung auf eine Zeile und ``BEGRUENDUNG_MAX_ZEICHEN`` kuerzen."""
    text = " ".join(str(text or "").split())
    if len(text) > BEGRUENDUNG_MAX_ZEICHEN:
        text = text[:BEGRUENDUNG_MAX_ZEICHEN - 1] + "…"
    return text


def quelle_pruefen(pfad, wurzeln: Sequence[Path], scan_ordner, ist_bezug: bool = False) -> Path:
    """Das Dokument eines Vorschlags: existiert und ist Bezug oder liegt im Scan-Eingang bzw. einem Zielordner."""
    if not pfad:
        raise WerkzeugFehler("Für das Dokument ist kein Dateipfad bekannt.")
    quelle = Path(pfad)
    if not quelle.is_file():
        raise WerkzeugFehler(f"„{quelle.name}“ gibt es nicht als Datei unter {quelle.parent}.")
    if not (ist_bezug or liegt_in(quelle, scan_ordner) or any(liegt_in(quelle, w) for w in wurzeln)):
        raise WerkzeugFehler(f"„{quelle.name}“ liegt weder im Scan-Eingang noch in einem Zielordner - "
                             "dafür sind keine Vorschläge möglich.")
    return quelle


def zielordner_pruefen(zielordner, wurzeln: Sequence[Path]) -> tuple[Path, str]:
    """Zielordner relativ zu einem Zielordner (``"Ablage/Energie"`` oder ``"Energie"``) oder absolut.

    Er muss existieren und innerhalb eines Zielordners liegen; ``..`` und Pfade
    ausserhalb werden abgewiesen, auch Windows-Pfade auf anderen Systemen.
    Liefert (Pfad, Anzeige relativ zum Zielordner wie ``"Ablage/Energie"``).
    """
    from src.core.similar_documents import relative_folder, resolve_relative_folder

    wert = str(zielordner or "").strip().strip('"').strip()
    if not wert:
        raise WerkzeugFehler("Argument „zielordner“ fehlt.")
    wurzeln = [Path(w) for w in wurzeln if w]
    if not wurzeln:
        raise WerkzeugFehler("Es sind keine Zielordner eingerichtet - Verschiebe-Vorschläge sind nicht möglich.")
    if any(teil == ".." for teil in re.split(r"[\\/]+", wert)):
        raise WerkzeugFehler(f"Zielordner „{wert}“ enthält „..“ - nur Ordner innerhalb der Zielordner sind erlaubt.")
    kandidat = Path(wert)
    if kandidat.is_absolute() or PureWindowsPath(wert).anchor:
        ziel = kandidat
    else:
        ziel = resolve_relative_folder(wert, wurzeln)
        if ziel is None:
            raise WerkzeugFehler(f"Zielordner „{wert}“ gibt es nicht. Nimm einen Ordner aus ordner_vorschlag, "
                                 "aus den Suchtreffern oder aus der Liste der Zielordner: "
                                 + ", ".join(w.name for w in wurzeln) + ".")
    if not any(liegt_in(ziel, w) for w in wurzeln):
        raise WerkzeugFehler(f"„{wert}“ liegt in keinem Zielordner ({', '.join(str(w) for w in wurzeln)}).")
    if not ziel.is_dir():
        raise WerkzeugFehler(f"Zielordner „{ziel}“ gibt es nicht.")
    return ziel, relative_folder(ziel.resolve(), [w.resolve() for w in wurzeln]) or ziel.name


def verschieben_pruefen(quelle: Path, zielordner, wurzeln: Sequence[Path]) -> tuple[Path, str]:
    """:func:`zielordner_pruefen` und: das Dokument liegt nicht schon dort."""
    ziel, anzeige = zielordner_pruefen(zielordner, wurzeln)
    if gleicher_ort(quelle.parent, ziel):
        raise WerkzeugFehler(f"„{quelle.name}“ liegt bereits in {anzeige}.")
    return ziel, anzeige


def neuer_name_pruefen(quelle: Path, name) -> str:
    """Neuer Dateiname: keine Pfadtrenner, bereinigt (``sanitize_filename``), Endung der Quelle bleibt."""
    from src.utils.filename_sanitizer import sanitize_filename

    roh = str(name or "").strip()
    if not roh:
        raise WerkzeugFehler("Argument „name“ fehlt.")
    if "/" in roh or "\\" in roh:
        raise WerkzeugFehler(f"Der neue Name „{roh}“ enthält einen Pfadtrenner - nur ein Dateiname ist erlaubt; "
                             "zum Verschieben vorschlag_verschieben benutzen.")
    endung = quelle.suffix.lower() or ".pdf"
    if endung == ".pdf":
        neu = sanitize_filename(roh)
    else:
        stamm = roh[: -len(endung)] if roh.lower().endswith(endung) else roh
        neu = sanitize_filename(stamm, ensure_pdf=False)
        neu = f"{neu}{quelle.suffix}" if neu else ""
    if not neu:
        raise WerkzeugFehler(f"„{roh}“ ergibt keinen brauchbaren Dateinamen.")
    if len(neu) > NAME_MAX_ZEICHEN:
        raise WerkzeugFehler(f"Der neue Name ist zu lang ({len(neu)} Zeichen, höchstens {NAME_MAX_ZEICHEN}).")
    if neu == quelle.name:
        raise WerkzeugFehler(f"„{quelle.name}“ heißt bereits so.")
    ziel = quelle.parent / neu
    try:
        belegt = ziel.exists() and not os.path.samefile(ziel, quelle)
    except OSError:
        belegt = False
    if belegt:
        raise WerkzeugFehler(f"Im selben Ordner gibt es schon eine Datei „{neu}“.")
    return neu


def betrag_pruefen(wert) -> str:
    """``"1.234,56 €"``, ``"1,234.56"``, ``12.5`` -> ``"1234.56"``, ``"12.50"``; sonst Fehler."""
    roh = str(wert).strip()
    betrag = re.sub(r"(?i)\s|€|eur", "", roh)
    if "," in betrag and "." in betrag:
        # das letzte Trennzeichen ist das Dezimalzeichen
        tausender = "." if betrag.rfind(",") > betrag.rfind(".") else ","
        betrag = betrag.replace(tausender, "")
    betrag = betrag.replace(",", ".")
    if not _BETRAG_RE.match(betrag):
        raise WerkzeugFehler(f"Betrag muss eine Zahl sein (z. B. 123.45), nicht „{roh}“.")
    return f"{float(betrag):.2f}"


def metadaten_pruefen(argumente: dict) -> dict[str, str]:
    """Metadaten eines Vorschlags pruefen; leere Felder fallen weg, mindestens eines muss bleiben.

    Kategorie ueber ``clean_category`` (eine Kategorie, keine Auswahlliste), Steuerjahr
    vierstellig, Betrag numerisch (``"1.234,56"`` -> ``"1234.56"``), Datum JJJJ-MM-TT.
    """
    from src.core.metadata_choices import clean_category

    felder: dict[str, str] = {}
    korrespondent = " ".join(text_argument(argumente, "korrespondent").split())
    if korrespondent:
        if len(korrespondent) > KORRESPONDENT_MAX_ZEICHEN:
            raise WerkzeugFehler(f"Korrespondent ist zu lang (höchstens {KORRESPONDENT_MAX_ZEICHEN} Zeichen).")
        felder["korrespondent"] = korrespondent
    kategorie = text_argument(argumente, "kategorie")
    if kategorie:
        sauber = clean_category(kategorie)
        if not sauber:
            raise WerkzeugFehler(f"„{kategorie}“ ist keine brauchbare Kategorie - genau eine Kategorie angeben.")
        felder["kategorie"] = sauber
    steuerjahr = text_argument(argumente, "steuerjahr")
    if steuerjahr:
        if not re.fullmatch(r"\d{4}", steuerjahr) or not 1900 <= int(steuerjahr) <= 2100:
            raise WerkzeugFehler(f"Steuerjahr muss vierstellig sein (z. B. 2024), nicht „{steuerjahr}“.")
        felder["steuerjahr"] = steuerjahr
    betrag = text_argument(argumente, "betrag")
    if betrag:
        felder["betrag"] = betrag_pruefen(betrag)
    datum = text_argument(argumente, "datum")
    if datum:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", datum):
            raise WerkzeugFehler(f"Datum muss im Format JJJJ-MM-TT sein, nicht „{datum}“.")
        felder["datum"] = datum_pruefen(datum, "datum")
    if not felder:
        raise WerkzeugFehler("Keine Metadaten angegeben - mindestens eines von "
                             + ", ".join(METADATEN_FELDER) + ".")
    return felder


def vorschlag_aufnehmen(liste: list[Vorschlag], neu: Vorschlag) -> list[Vorschlag]:
    """Hoechstens ein Vorschlag je Art und Dokument: ein spaeterer ersetzt den frueheren (an dessen Stelle)."""
    for i, alt in enumerate(liste):
        if alt.gleiche_aktion(neu):
            liste[i] = neu
            return liste
    liste.append(neu)
    return liste

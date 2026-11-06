"""SQLite-Datenbank der Dokumentensuche: Schema, Speichern, Suchen.

Uebernommen aus PDFsuche (``db.py``). Das Schema ist in
``docs/SUCHE_ARCHITEKTUR.md`` beschrieben. Version 1 stammt aus PDFsuche;
Version 2 (Phase 5 der Integration) ergaenzt **additiv und in-place** den
OCR-Cache nach Bildinhalt (``ocr_cache``, ``seiten.bild_hash``) und die
PDFSM-Metadaten in ``dokumente`` (``pdf_id``, ``korrespondent``, ``kategorie``,
``steuerjahr``, ``betrag``, ``buchungsdatum``, ``zusammenfassung``,
``schlagwoerter``, ``metadaten_quelle``) samt ``metadaten_fts``. Die Version
wird an der Struktur erkannt (``schema_stand``), weil das alte PDFsuche
``meta.schema_version`` bei jedem Start auf 1 zuruecksetzt.

Alle Funktionen arbeiten auf einer ``sqlite3.Connection`` aus ``verbinde()``.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    schluessel TEXT PRIMARY KEY,
    wert       TEXT
);

CREATE TABLE IF NOT EXISTS dokumente (
    id           INTEGER PRIMARY KEY,
    pfad         TEXT NOT NULL UNIQUE COLLATE NOCASE, -- Dateipfad; bei Mails aus mbox: "<mbox>#<offset>"
    datei        TEXT NOT NULL COLLATE NOCASE,        -- echte Datei auf der Platte (bei mbox die mbox-Datei)
    name         TEXT NOT NULL,                       -- Dateiname bzw. Mail-Betreff
    ordner       TEXT NOT NULL,                       -- Ordner bzw. Thunderbird-Postfach
    typ          TEXT NOT NULL,                       -- 'pdf' | 'md' | 'mail' | 'office'
    format       TEXT NOT NULL,                       -- 'pdf' | 'md' | 'eml' | 'msg' | 'mbox' | 'docx' | ...
    groesse      INTEGER,                             -- Bytes
    mtime_ns     INTEGER,                             -- Aenderungszeit der Datei (ns)
    datum        REAL,                                -- Unix-Zeit: Mail-Datum bzw. Aenderungsdatum
    seiten       INTEGER,                             -- Seitenzahl (PDF) bzw. Tabellenblaetter, sonst 1
    textstatus   TEXT NOT NULL,                       -- siehe docs/SUCHE_ARCHITEKTUR.md
    ocr_seiten   INTEGER NOT NULL DEFAULT 0,          -- Anzahl per OCR erkannter Seiten
    prioritaet   INTEGER NOT NULL DEFAULT 9,          -- 0 = erster Vorrang-Ordner, 9 = Rest
    titel        TEXT,
    autor        TEXT,
    mail_von     TEXT,
    mail_an      TEXT,
    mail_datum   TEXT,                                -- ISO 8601
    mail_betreff TEXT,
    mail_anhaenge TEXT,                               -- Dateinamen der Anhaenge, durch " | " getrennt
    mbox_offset  INTEGER,
    mbox_laenge  INTEGER,
    fehler       TEXT,
    indiziert_am TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_dok_datei  ON dokumente(datei);
CREATE INDEX IF NOT EXISTS ix_dok_status ON dokumente(textstatus, prioritaet);
CREATE INDEX IF NOT EXISTS ix_dok_typ    ON dokumente(typ, datum);
CREATE INDEX IF NOT EXISTS ix_dok_ordner ON dokumente(ordner);

CREATE TABLE IF NOT EXISTS seiten (
    id     INTEGER PRIMARY KEY,
    dok_id INTEGER NOT NULL REFERENCES dokumente(id) ON DELETE CASCADE,
    seite  INTEGER NOT NULL,     -- 1-basiert
    quelle TEXT NOT NULL,        -- 'text' | 'ocr' | 'ohne_text' (wartet auf OCR) | 'ocr_fehler'
    text   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_seiten_dok ON seiten(dok_id, seite);

CREATE VIRTUAL TABLE IF NOT EXISTS seiten_fts USING fts5(
    text, content='seiten', content_rowid='id',
    tokenize="unicode61 remove_diacritics 2"
);
CREATE TRIGGER IF NOT EXISTS seiten_ai AFTER INSERT ON seiten BEGIN
    INSERT INTO seiten_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS seiten_ad AFTER DELETE ON seiten BEGIN
    INSERT INTO seiten_fts(seiten_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS seiten_au AFTER UPDATE OF text ON seiten BEGIN
    INSERT INTO seiten_fts(seiten_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO seiten_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE VIRTUAL TABLE IF NOT EXISTS dokumente_fts USING fts5(
    name, ordner, content='dokumente', content_rowid='id',
    tokenize="unicode61 remove_diacritics 2"
);
CREATE TRIGGER IF NOT EXISTS dok_ai AFTER INSERT ON dokumente BEGIN
    INSERT INTO dokumente_fts(rowid, name, ordner) VALUES (new.id, new.name, new.ordner);
END;
CREATE TRIGGER IF NOT EXISTS dok_ad AFTER DELETE ON dokumente BEGIN
    INSERT INTO dokumente_fts(dokumente_fts, rowid, name, ordner) VALUES ('delete', old.id, old.name, old.ordner);
END;
CREATE TRIGGER IF NOT EXISTS dok_au AFTER UPDATE OF name, ordner ON dokumente BEGIN
    INSERT INTO dokumente_fts(dokumente_fts, rowid, name, ordner) VALUES ('delete', old.id, old.name, old.ordner);
    INSERT INTO dokumente_fts(rowid, name, ordner) VALUES (new.id, new.name, new.ordner);
END;

CREATE TABLE IF NOT EXISTS mbox_stand (
    datei     TEXT PRIMARY KEY COLLATE NOCASE,
    groesse   INTEGER NOT NULL,     -- bis hierher gelesen (Byte-Offset)
    mtime_ns  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS laeufe (
    id        INTEGER PRIMARY KEY,
    beginn    TEXT NOT NULL,
    ende      TEXT,
    status    TEXT NOT NULL,      -- 'laeuft' | 'fertig' | 'abgebrochen' | 'fehler'
    phase     TEXT,
    statistik TEXT                -- JSON
);

-- Bequeme Sicht: ein Datensatz pro Dokument mit Volltext (Seiten durch Seitenvorschub getrennt)
CREATE VIEW IF NOT EXISTS v_dokument_text AS
    SELECT d.id, d.pfad, d.datei, d.name, d.typ, d.textstatus, d.datum,
           group_concat(s.text, char(12)) AS volltext
    FROM dokumente d LEFT JOIN (SELECT * FROM seiten ORDER BY dok_id, seite) s ON s.dok_id = d.id
    GROUP BY d.id;
"""

# Version 2: additiv, idempotent (``ergaenze_schema``); Spalten kommen per ALTER TABLE dazu
V2_SPALTEN = {
    "pdf_id": "TEXT",            # stabile Kennung aus der pdfs-Tabelle von PDFSM
    "korrespondent": "TEXT",
    "kategorie": "TEXT",
    "steuerjahr": "TEXT",
    "betrag": "REAL",            # brutto
    "buchungsdatum": "TEXT",     # ISO
    "zusammenfassung": "TEXT",
    "schlagwoerter": "TEXT",
    "metadaten_quelle": "TEXT",  # 'pdf' = beim Indizieren aus der Datei gelesen, 'pdfsm' = von PDFSM gesetzt (Vorrang)
}
METADATEN_FELDER = ("korrespondent", "kategorie", "steuerjahr", "betrag", "buchungsdatum", "zusammenfassung",
                    "schlagwoerter")
_META_FTS = "korrespondent, kategorie, zusammenfassung, schlagwoerter"
_META_FTS_NEU = ", ".join(f"coalesce(new.{f}, '')" for f in _META_FTS.split(", "))
_META_FTS_ALT = ", ".join(f"coalesce(old.{f}, '')" for f in _META_FTS.split(", "))

SCHEMA_V2 = f"""
CREATE TABLE IF NOT EXISTS ocr_cache (
    bild_hash TEXT PRIMARY KEY,   -- BLAKE2b (16 Byte, hex) ueber die Bild-Streams einer Seite
    text      TEXT NOT NULL,
    sprachen  TEXT,
    dpi       INTEGER,
    erstellt  TEXT
);
CREATE INDEX IF NOT EXISTS ix_seiten_hash      ON seiten(bild_hash);
CREATE INDEX IF NOT EXISTS ix_dok_pdf_id       ON dokumente(pdf_id);
CREATE INDEX IF NOT EXISTS ix_dok_steuerjahr   ON dokumente(steuerjahr);
CREATE INDEX IF NOT EXISTS ix_dok_korrespondent ON dokumente(korrespondent);
CREATE INDEX IF NOT EXISTS ix_dok_kategorie    ON dokumente(kategorie);

CREATE VIRTUAL TABLE IF NOT EXISTS metadaten_fts USING fts5(
    {_META_FTS}, content='dokumente', content_rowid='id',
    tokenize="unicode61 remove_diacritics 2"
);
CREATE TRIGGER IF NOT EXISTS meta_ai AFTER INSERT ON dokumente BEGIN
    INSERT INTO metadaten_fts(rowid, {_META_FTS}) VALUES (new.id, {_META_FTS_NEU});
END;
CREATE TRIGGER IF NOT EXISTS meta_ad AFTER DELETE ON dokumente BEGIN
    INSERT INTO metadaten_fts(metadaten_fts, rowid, {_META_FTS}) VALUES ('delete', old.id, {_META_FTS_ALT});
END;
CREATE TRIGGER IF NOT EXISTS meta_au AFTER UPDATE OF {_META_FTS} ON dokumente BEGIN
    INSERT INTO metadaten_fts(metadaten_fts, rowid, {_META_FTS}) VALUES ('delete', old.id, {_META_FTS_ALT});
    INSERT INTO metadaten_fts(rowid, {_META_FTS}) VALUES (new.id, {_META_FTS_NEU});
END;
"""

# Statuswerte, die bedeuten "Text vollstaendig im Index"
FERTIG = ("text", "ocr", "leer")
# Statuswerte, bei denen der vorhandene Text verwendbar ist (ggf. unvollstaendig)
VERWENDBAR = FERTIG + ("ocr_teilweise", "ocr_ausstehend")
# 'ausstehend': von PDFSM nur mit Metadaten angelegt, Text liest der naechste Lauf (Groesse/mtime fehlen)


def jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


def verbinde(pfad: str | Path, nur_lesen: bool = False) -> sqlite3.Connection:
    """Verbindung oeffnen. Schreibend: WAL-Modus, Ordner wird angelegt. Lesend: ``mode=ro``."""
    pfad = str(pfad)
    if nur_lesen:
        uri = Path(pfad).resolve().as_uri() + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=30, check_same_thread=False)
    else:
        Path(pfad).parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(pfad, timeout=60, check_same_thread=False)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    con.row_factory = sqlite3.Row
    return con


def init(con: sqlite3.Connection) -> None:
    """Schema anlegen (neue Datenbank) bzw. eine Version-1-Datenbank additiv auf Version 2 bringen."""
    con.executescript(SCHEMA)
    ergaenze_schema(con)


def _spalten(con, tabelle: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({tabelle})")}


def _tabelle_vorhanden(con, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone() is not None


def schema_stand(con) -> int:
    """Schema-Version an der Struktur erkennen: 0 (leer), 1 (PDFsuche) oder 2 (mit OCR-Cache und Metadaten)."""
    spalten = _spalten(con, "dokumente")
    if not spalten:
        return 0
    if (set(V2_SPALTEN) <= spalten and "bild_hash" in _spalten(con, "seiten")
            and _tabelle_vorhanden(con, "ocr_cache") and _tabelle_vorhanden(con, "metadaten_fts")):
        return 2
    return 1


def ergaenze_schema(con) -> bool:
    """Version 2 additiv und idempotent ergaenzen (Spalten nur, wenn sie fehlen; Tabellen ``IF NOT EXISTS``).

    Kein Neuaufbau, keine OCR geht verloren; auch bei 3 GB unter einer Sekunde.
    Liefert True, wenn etwas geaendert wurde.
    """
    geaendert = False
    spalten = _spalten(con, "dokumente")
    for name, typ in V2_SPALTEN.items():
        if name not in spalten:
            con.execute(f"ALTER TABLE dokumente ADD COLUMN {name} {typ}")
            geaendert = True
    if "bild_hash" not in _spalten(con, "seiten"):
        con.execute("ALTER TABLE seiten ADD COLUMN bild_hash TEXT")
        geaendert = True
    fts_neu = not _tabelle_vorhanden(con, "metadaten_fts")
    con.executescript(SCHEMA_V2)
    if fts_neu:
        con.execute("INSERT INTO metadaten_fts(metadaten_fts) VALUES ('rebuild')")
        geaendert = True
    if lies_meta(con, "schema_version") != str(SCHEMA_VERSION):
        setze_meta(con, "schema_version", str(SCHEMA_VERSION))
        geaendert = True
    con.commit()
    return geaendert


def setze_meta(con, schluessel: str, wert) -> None:
    con.execute(
        "INSERT OR REPLACE INTO meta VALUES (?, ?)",
        (schluessel, wert if isinstance(wert, str) else json.dumps(wert)),
    )


def lies_meta(con, schluessel: str, standard=None):
    r = con.execute("SELECT wert FROM meta WHERE schluessel = ?", (schluessel,)).fetchone()
    return r[0] if r else standard


# --------------------------------------------------------------------------- Schreiben

DOK_FELDER = (
    "pfad", "datei", "name", "ordner", "typ", "format", "groesse", "mtime_ns", "datum", "seiten",
    "textstatus", "ocr_seiten", "prioritaet", "titel", "autor", "mail_von", "mail_an", "mail_datum",
    "mail_betreff", "mail_anhaenge", "mbox_offset", "mbox_laenge", "fehler", "indiziert_am",
)


def speichere(con: sqlite3.Connection, dok: dict, seiten: list[tuple[int, str, str]],
              bild_hashes: dict[int, str] | None = None) -> int:
    """Dokument anlegen oder ersetzen. ``seiten = [(seite, quelle, text), ...]``. Liefert die id.

    Die Metadatenspalten (Version 2) gehoeren nicht zu ``DOK_FELDER`` und bleiben
    beim Ersetzen erhalten (Vorrangregel fuer Werte von PDFSM). ``bild_hashes``
    (Seite -> Hash) kommt in ``seiten.bild_hash`` (OCR-Cache).
    """
    dok = {**dok, "indiziert_am": jetzt()}
    dok.setdefault("ocr_seiten", 0)
    dok.setdefault("prioritaet", 9)
    werte = [dok.get(f) for f in DOK_FELDER]
    r = con.execute("SELECT id FROM dokumente WHERE pfad = ?", (dok["pfad"],)).fetchone()
    if r:
        dok_id = r[0]
        con.execute("DELETE FROM seiten WHERE dok_id = ?", (dok_id,))
        con.execute(
            "UPDATE dokumente SET " + ", ".join(f"{f} = ?" for f in DOK_FELDER) + " WHERE id = ?",
            (*werte, dok_id),
        )
    else:
        cur = con.execute(
            f"INSERT INTO dokumente ({', '.join(DOK_FELDER)}) VALUES ({', '.join('?' * len(DOK_FELDER))})",
            werte,
        )
        dok_id = cur.lastrowid
    if seiten:
        hashes = bild_hashes or {}
        con.executemany(
            "INSERT INTO seiten (dok_id, seite, quelle, text, bild_hash) VALUES (?, ?, ?, ?, ?)",
            [(dok_id, s, q, t, hashes.get(s)) for s, q, t in seiten],
        )
    return dok_id


def loesche(con: sqlite3.Connection, dok_ids) -> None:
    ids = list(dok_ids)
    for i in range(0, len(ids), 500):
        teil = ids[i:i + 500]
        ph = ",".join("?" * len(teil))
        con.execute(f"DELETE FROM seiten WHERE dok_id IN ({ph})", teil)
        con.execute(f"DELETE FROM dokumente WHERE id IN ({ph})", teil)


def _betrag(wert) -> float | None:
    """'59,99 EUR' / '1.234,50' / 59.99 -> 59.99; Unbrauchbares -> None."""
    if wert is None or wert == "":
        return None
    if isinstance(wert, (int, float)):
        return float(wert)
    s = re.sub(r"[^\d,.\-]", "", str(wert))
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _meta_wert(feld: str, wert):
    if feld == "betrag":
        return _betrag(wert)
    if wert is None:
        return None
    s = str(wert).strip()
    return s or None


def metadaten_setzen(con, dok_id: int, felder: dict, pdf_id: str | None = None, quelle: str = "pdfsm") -> bool:
    """PDFSM-Metadaten eines Dokuments setzen (nur die uebergebenen Felder; None/leer loescht).

    Vorrangregel: Werte mit Quelle ``'pdfsm'`` ueberschreibt die Quelle ``'pdf'``
    (beim Indizieren aus der Datei gelesen) nie. Liefert True, wenn geschrieben wurde.
    """
    werte = {k: _meta_wert(k, v) for k, v in (felder or {}).items() if k in METADATEN_FELDER}
    gefuellt = any(v is not None for v in werte.values())
    if quelle == "pdf":
        r = con.execute("SELECT metadaten_quelle FROM dokumente WHERE id = ?", (dok_id,)).fetchone()
        if r is None or r[0] == "pdfsm" or not gefuellt:
            return False
    elif not gefuellt:
        # Nur leere Werte: nichts ueberschreiben und keinen Vorrang beanspruchen (z. B. reiner pdf_id-Nachtrag)
        werte = {}
    if pdf_id:
        werte["pdf_id"] = str(pdf_id)
    if not werte:
        return False
    if gefuellt:
        werte["metadaten_quelle"] = quelle
    cur = con.execute("UPDATE dokumente SET " + ", ".join(f"{k} = ?" for k in werte) + " WHERE id = ?",
                      (*werte.values(), dok_id))
    return cur.rowcount > 0


def metadaten_ersetzen(con, feld: str, alt: str, neu: str) -> int:
    """Einen Wert in allen Dokumenten ersetzen (z. B. Korrespondenten-Merge). Liefert die Trefferzahl."""
    if feld not in METADATEN_FELDER:
        raise ValueError(f"Unbekanntes Metadatenfeld: {feld}")
    return con.execute(f"UPDATE dokumente SET {feld} = ? WHERE {feld} = ?", (neu, alt)).rowcount


def werte(con, feld: str, absteigend: bool = False) -> list[str]:
    """Vorkommende Werte eines Metadatenfelds (ohne leere), sortiert."""
    if feld not in METADATEN_FELDER:
        raise ValueError(f"Unbekanntes Metadatenfeld: {feld}")
    return [r[0] for r in con.execute(
        f"SELECT DISTINCT {feld} FROM dokumente WHERE {feld} IS NOT NULL AND {feld} != '' "
        f"ORDER BY {feld} {'DESC' if absteigend else 'ASC'}")]


def top_werte(con, feld: str, limit: int = 10) -> list[str]:
    """Die haeufigsten Werte eines Metadatenfelds, haeufigste zuerst."""
    if feld not in METADATEN_FELDER:
        raise ValueError(f"Unbekanntes Metadatenfeld: {feld}")
    return [r[0] for r in con.execute(
        f"SELECT {feld}, count(*) n FROM dokumente WHERE {feld} IS NOT NULL AND {feld} != '' "
        f"GROUP BY {feld} ORDER BY n DESC, {feld} LIMIT ?", (int(limit),))]


def anzahl(con, typ: str | None = None) -> int:
    if typ:
        return con.execute("SELECT count(*) FROM dokumente WHERE typ = ?", (typ,)).fetchone()[0]
    return con.execute("SELECT count(*) FROM dokumente").fetchone()[0]


# --------------------------------------------------------------------------- OCR-Cache (Version 2)

def ocr_cache_holen(con, hashes) -> dict[str, str]:
    """Bekannte OCR-Texte zu Bild-Hashes: ``{hash: text}``."""
    hs = sorted({h for h in hashes if h})
    erg: dict[str, str] = {}
    for i in range(0, len(hs), 500):
        teil = hs[i:i + 500]
        for r in con.execute(f"SELECT bild_hash, text FROM ocr_cache WHERE bild_hash IN ({','.join('?' * len(teil))})",
                             teil):
            erg[r[0]] = r[1]
    return erg


def ocr_cache_eintragen(con, eintraege, sprachen: str | None = None, dpi: int | None = None) -> int:
    """``[(hash, text), ...]`` in den Cache (vorhandene Hashes bleiben). Liefert die Zahl neuer Eintraege."""
    zeilen = [(h, t, sprachen, dpi, jetzt()) for h, t in eintraege if h and t is not None]
    if not zeilen:
        return 0
    vorher = con.total_changes
    con.executemany("INSERT OR IGNORE INTO ocr_cache (bild_hash, text, sprachen, dpi, erstellt) VALUES (?, ?, ?, ?, ?)",
                    zeilen)
    return con.total_changes - vorher


def ocr_status_aktualisieren(con, dok_id: int, fehler: str | None = None) -> str:
    """Textstatus und ``ocr_seiten`` eines Dokuments aus seinen Seiten ableiten; liefert den Status."""
    r = con.execute(
        """SELECT sum(quelle = 'ohne_text') rest, sum(quelle = 'ocr') ocr, sum(quelle = 'ocr_fehler') fehl
           FROM seiten WHERE dok_id = ?""", (dok_id,)).fetchone()
    if r["rest"]:
        status = "ocr_ausstehend"
    elif r["fehl"]:
        status = "ocr_teilweise"
    else:
        status = "ocr"
    con.execute("UPDATE dokumente SET textstatus = ?, ocr_seiten = ?, fehler = coalesce(?, fehler) WHERE id = ?",
                (status, r["ocr"] or 0, fehler, dok_id))
    return status


def ocr_text_eintragen(con, dok_id: int, texte: dict, sprachen: str | None = None, dpi: int | None = None,
                       nur_offene: bool = True) -> int:
    """OCR-Ergebnis (``{seite: text | None}``) uebernehmen: Seiten fuellen, Cache befuellen, Status ableiten.

    ``None`` als Text markiert die Seite als ``ocr_fehler``. Mit ``nur_offene``
    werden nur Seiten geaendert, die noch auf OCR warten (``ohne_text``/``ocr_fehler``).
    Liefert die Zahl der erkannten Seiten.
    """
    bedingung = " AND quelle IN ('ohne_text', 'ocr_fehler')" if nur_offene else ""
    erkannt = []
    for seite, text in texte.items():
        if text is None:
            con.execute(f"UPDATE seiten SET quelle = 'ocr_fehler' WHERE dok_id = ? AND seite = ?{bedingung}",
                        (dok_id, seite))
        else:
            cur = con.execute(f"UPDATE seiten SET text = ?, quelle = 'ocr' WHERE dok_id = ? AND seite = ?{bedingung}",
                              (text, dok_id, seite))
            if cur.rowcount:
                erkannt.append(seite)
    if erkannt:
        ph = ",".join("?" * len(erkannt))
        zeilen = con.execute(f"SELECT bild_hash, text FROM seiten WHERE dok_id = ? AND seite IN ({ph})",
                             (dok_id, *erkannt)).fetchall()
        ocr_cache_eintragen(con, [(r[0], r[1]) for r in zeilen], sprachen, dpi)
        # Weitere offene Seiten desselben Dokuments mit bekanntem Bild (z. B. gleiches Deckblatt) gleich mit fuellen
        offen = con.execute("SELECT seite, bild_hash FROM seiten WHERE dok_id = ? AND quelle = 'ohne_text' "
                            "AND bild_hash IS NOT NULL", (dok_id,)).fetchall()
        if offen:
            cache = ocr_cache_holen(con, [r[1] for r in offen])
            for seite, h in offen:
                if h in cache:
                    con.execute("UPDATE seiten SET text = ?, quelle = 'ocr' WHERE dok_id = ? AND seite = ?",
                                (cache[h], dok_id, seite))
    ocr_status_aktualisieren(con, dok_id)
    return len(erkannt)


# --------------------------------------------------------------------------- Suchen

_OPS = {"UND": "AND", "ODER": "OR", "NICHT": "NOT", "NAHE": "NEAR"}


def _als_woerter(text: str) -> str:
    """Robuste Ersatzabfrage: jedes Wort in Anfuehrungszeichen, zusammengesetzte Stuecke als Phrase."""
    teile = []
    for stueck in re.findall(r'"[^"]*"|\S+', text):
        if stueck.startswith('"'):
            woerter = re.findall(r"\w+", stueck)
            if woerter:
                teile.append('"' + " ".join(woerter) + '"')
            continue
        if stueck.upper() in _OPS or stueck in ("AND", "OR", "NOT"):
            continue
        praefix = stueck.endswith("*")
        woerter = re.findall(r"\w+", stueck)
        if not woerter:
            continue
        p = '"' + " ".join(woerter) + '"'
        teile.append(p + ("*" if praefix else ""))
    return " ".join(teile)


def fts_abfrage(text: str) -> str:
    """Deutsche Operatoren (UND, ODER, NICHT, NAHE) in FTS5-Syntax uebersetzen."""
    t = text.strip()
    for de, en in _OPS.items():
        t = re.sub(rf"(?<![\w\"]){de}(?![\w\"])", en, t)
    return t


def _filter(typ=None, ordner=None, von=None, bis=None, status=None, steuerjahr=None, kategorie=None,
            korrespondent=None, betrag_von=None, betrag_bis=None, pdf_id=None, steuerjahr_von=None,
            steuerjahr_bis=None) -> tuple[str, list]:
    sql, args = [], []
    if typ:
        typen = [t.strip() for t in str(typ).split(",") if t.strip()]
        sql.append(f"d.typ IN ({','.join('?' * len(typen))})")
        args += typen
    if ordner:
        sql.append("(d.datei LIKE ? ESCAPE '\\' OR d.ordner LIKE ? ESCAPE '\\')")
        muster = "%" + (
            ordner.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("/", "\\\\")
            if os.sep == "\\" else
            ordner.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        ) + "%"
        args += [muster, muster]
    if von:
        sql.append("d.datum >= ?")
        args.append(_zeit(von))
    if bis:
        sql.append("d.datum < ?")
        args.append(_zeit(bis) + 86400)
    if status:
        sql.append("d.textstatus = ?")
        args.append(status)
    for spalte, wert in (("steuerjahr", steuerjahr), ("kategorie", kategorie), ("korrespondent", korrespondent),
                         ("pdf_id", pdf_id)):
        if wert:
            sql.append(f"d.{spalte} = ?")
            args.append(str(wert))
    if betrag_von is not None and betrag_von != "":
        sql.append("d.betrag >= ?")
        args.append(float(betrag_von))
    if betrag_bis is not None and betrag_bis != "":
        sql.append("d.betrag <= ?")
        args.append(float(betrag_bis))
    if steuerjahr_von:
        sql.append("d.steuerjahr >= ?")
        args.append(str(steuerjahr_von)[:4])
    if steuerjahr_bis:
        sql.append("d.steuerjahr <= ?")
        args.append(str(steuerjahr_bis)[:4])
    return (" AND " + " AND ".join(sql)) if sql else "", args


def _zeit(datum: str) -> float:
    datum = str(datum).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y"):
        try:
            return datetime.strptime(datum, fmt).timestamp()
        except ValueError:
            pass
    raise ValueError(f"Unbekanntes Datum: {datum!r} (erwartet JJJJ-MM-TT oder TT.MM.JJJJ)")


def suche(con, abfrage: str, typ=None, ordner=None, von=None, bis=None, sortierung="relevanz",
          anzahl=30, start=0, max_stellen=3, nur_namen=False, steuerjahr=None, kategorie=None,
          korrespondent=None, betrag_von=None, betrag_bis=None, pdf_id=None, steuerjahr_von=None,
          steuerjahr_bis=None) -> dict:
    """Volltextsuche. Liefert ``{'treffer': [...], 'gesamt': n, 'mehr': bool, 'abfrage': fts, 'dauer_ms': ms}``.

    Ausschnitte enthalten die Marker ``\\x02`` (Beginn) und ``\\x03`` (Ende) um Fundstellen.
    Bei FTS5-Syntaxfehlern wird die Abfrage als Folge einzelner Woerter wiederholt.
    Die Metadatenfilter (Version 2) sind Gleichheitsbedingungen auf ``dokumente``;
    ``betrag_von/bis`` sind Zahlen. Ohne ``abfrage`` liefert die Suche alle
    Dokumente, die zu den Filtern passen (neueste zuerst bzw. nach ``sortierung``).
    """
    filt, fargs = _filter(typ, ordner, von, bis, None, steuerjahr, kategorie, korrespondent, betrag_von, betrag_bis,
                          pdf_id, steuerjahr_von, steuerjahr_bis)
    t0 = time.perf_counter()
    if not (abfrage or "").strip():
        return _nur_filter(con, filt, fargs, sortierung, anzahl, start, t0)
    hat_meta_fts = _tabelle_vorhanden(con, "metadaten_fts")

    def ausfuehren(fts: str):
        # 1) Fundstellen im Inhalt, nach Relevanz
        grenze = 4000
        zeilen = []
        if not nur_namen:
            zeilen = con.execute(
                f"""SELECT s.dok_id, s.seite, s.quelle,
                           snippet(seiten_fts, 0, char(2), char(3), ' … ', 24) AS ausschnitt,
                           bm25(seiten_fts) AS rang
                    FROM seiten_fts
                    JOIN seiten s ON s.id = seiten_fts.rowid
                    JOIN dokumente d ON d.id = s.dok_id
                    WHERE seiten_fts MATCH ? {filt}
                    ORDER BY rang LIMIT {grenze}""",
                (fts, *fargs),
            ).fetchall()
        # 2) Treffer in Dateiname / Ordner / Betreff
        namen = con.execute(
            f"""SELECT d.id, bm25(dokumente_fts) AS rang
                FROM dokumente_fts JOIN dokumente d ON d.id = dokumente_fts.rowid
                WHERE dokumente_fts MATCH ? {filt}
                ORDER BY rang LIMIT 1000""",
            (fts, *fargs),
        ).fetchall()
        # 3) Treffer in den PDFSM-Metadaten (Korrespondent, Kategorie, Zusammenfassung, Schlagwoerter)
        meta = []
        if hat_meta_fts:
            meta = con.execute(
                f"""SELECT d.id, bm25(metadaten_fts) AS rang
                    FROM metadaten_fts JOIN dokumente d ON d.id = metadaten_fts.rowid
                    WHERE metadaten_fts MATCH ? {filt}
                    ORDER BY rang LIMIT 1000""",
                (fts, *fargs),
            ).fetchall()
        return zeilen, namen, meta, len(zeilen) >= grenze

    fts = fts_abfrage(abfrage)
    try:
        zeilen, namen, meta, abgeschnitten = ausfuehren(fts)
    except sqlite3.OperationalError:
        fts = _als_woerter(abfrage)
        if not fts:
            return {"treffer": [], "gesamt": 0, "mehr": False, "abfrage": fts, "dauer_ms": 0}
        zeilen, namen, meta, abgeschnitten = ausfuehren(fts)

    dok: dict[int, dict] = {}
    for z in zeilen:
        e = dok.setdefault(z["dok_id"], {"rang": z["rang"], "stellen": [], "treffer_seiten": 0, "im_namen": False,
                                         "im_metadaten": False})
        e["treffer_seiten"] += 1
        if len(e["stellen"]) < max_stellen:
            e["stellen"].append({"seite": z["seite"], "quelle": z["quelle"], "text": z["ausschnitt"]})
    for z in namen:
        e = dok.setdefault(z["id"], {"rang": 0.0, "stellen": [], "treffer_seiten": 0, "im_namen": True,
                                     "im_metadaten": False})
        e["im_namen"] = True
        e["rang"] = min(e["rang"], 0.0) - 5.0  # Namenstreffer nach vorn
    for z in meta:
        e = dok.setdefault(z["id"], {"rang": 0.0, "stellen": [], "treffer_seiten": 0, "im_namen": False,
                                     "im_metadaten": True})
        e["im_metadaten"] = True
        e["rang"] = min(e["rang"], 0.0) - 5.0  # Metadatentreffer ebenfalls nach vorn

    if not dok:
        return {"treffer": [], "gesamt": 0, "mehr": False, "abfrage": fts,
                "dauer_ms": round((time.perf_counter() - t0) * 1000)}

    # Metadaten laden
    ids = list(dok)
    meta = {}
    for i in range(0, len(ids), 900):
        teil = ids[i:i + 900]
        for r in con.execute(f"SELECT * FROM dokumente WHERE id IN ({','.join('?' * len(teil))})", teil):
            meta[r["id"]] = dict(r)

    liste = []
    for i, e in dok.items():
        if i in meta:
            liste.append({**_kurz(meta[i]), **e})
    if sortierung == "neu":
        liste.sort(key=lambda x: -(x["datum"] or 0))
    elif sortierung == "alt":
        liste.sort(key=lambda x: (x["datum"] or 0))
    else:
        liste.sort(key=lambda x: x["rang"])

    return {
        "treffer": liste[start:start + anzahl],
        "gesamt": len(liste),
        "mehr": abgeschnitten,
        "abfrage": fts,
        "dauer_ms": round((time.perf_counter() - t0) * 1000),
    }


def _nur_filter(con, filt: str, fargs: list, sortierung: str, anzahl: int, start: int, t0: float) -> dict:
    """Ohne Suchbegriff: alle Dokumente, die zu den Filtern passen (fuer die Metadatenfilter von PDFSM)."""
    if not filt:
        return {"treffer": [], "gesamt": 0, "mehr": False, "abfrage": "", "dauer_ms": 0}
    reihenfolge = "d.datum ASC" if sortierung == "alt" else "d.datum DESC"
    gesamt = con.execute(f"SELECT count(*) FROM dokumente d WHERE 1 = 1 {filt}", fargs).fetchone()[0]
    zeilen = con.execute(
        f"SELECT * FROM dokumente d WHERE 1 = 1 {filt} ORDER BY {reihenfolge}, d.name LIMIT ? OFFSET ?",
        (*fargs, int(anzahl), int(start)),
    ).fetchall()
    treffer = [{**_kurz(dict(r)), "rang": 0.0, "stellen": [], "treffer_seiten": 0, "im_namen": False,
                "im_metadaten": False} for r in zeilen]
    return {"treffer": treffer, "gesamt": gesamt, "mehr": False, "abfrage": "",
            "dauer_ms": round((time.perf_counter() - t0) * 1000)}


def _kurz(r: dict) -> dict:
    return {k: r.get(k) for k in (
        "id", "pfad", "datei", "name", "ordner", "typ", "format", "groesse", "datum", "seiten",
        "textstatus", "ocr_seiten", "mail_von", "mail_an", "mail_datum", "mail_betreff", "mail_anhaenge", "fehler",
        "pdf_id", "korrespondent", "kategorie", "steuerjahr", "betrag", "buchungsdatum", "zusammenfassung",
        "schlagwoerter", "metadaten_quelle",
    )}


def dokument(con, dok_id: int) -> dict | None:
    r = con.execute("SELECT * FROM dokumente WHERE id = ?", (dok_id,)).fetchone()
    return dict(r) if r else None


def dokument_nach_pfad(con, pfad: str) -> dict | None:
    r = con.execute("SELECT * FROM dokumente WHERE pfad = ?", (str(pfad),)).fetchone()
    return dict(r) if r else None


def seiten_text(con, dok_id: int, von: int | None = None, bis: int | None = None,
                hervorheben: str | None = None) -> list[dict]:
    """Seiten eines Dokuments; mit ``hervorheben`` werden Fundstellen mit \\x02/\\x03 markiert."""
    sql = "SELECT id, seite, quelle, text FROM seiten WHERE dok_id = ?"
    args: list = [dok_id]
    if von:
        sql += " AND seite >= ?"
        args.append(von)
    if bis:
        sql += " AND seite <= ?"
        args.append(bis)
    zeilen = [dict(r) for r in con.execute(sql + " ORDER BY seite", args)]
    if hervorheben and zeilen:
        markiert = {}
        for fts in (fts_abfrage(hervorheben), _als_woerter(hervorheben)):
            try:
                for r in con.execute(
                    "SELECT rowid, highlight(seiten_fts, 0, char(2), char(3)) AS h FROM seiten_fts "
                    "WHERE seiten_fts MATCH ? AND rowid IN (SELECT id FROM seiten WHERE dok_id = ?)",
                    (fts, dok_id),
                ):
                    markiert[r["rowid"]] = r["h"]
                break
            except sqlite3.OperationalError:
                continue
        for z in zeilen:
            if z["id"] in markiert:
                z["text"] = markiert[z["id"]]
                z["treffer"] = True
    return zeilen


def volltext(con, dok_id: int, max_zeichen: int = 0) -> str:
    """Gesamter Text eines Dokuments, Seiten durch Seitenvorschub (\\f) getrennt; optional gekappt."""
    teile = []
    laenge = 0
    for r in con.execute("SELECT text FROM seiten WHERE dok_id = ? ORDER BY seite", (dok_id,)):
        teile.append(r[0])
        laenge += len(r[0]) + 1
        if max_zeichen and laenge >= max_zeichen:
            break
    text = "\f".join(teile)
    return text[:max_zeichen] if max_zeichen else text


def text_fuer_datei(con, pfad: str) -> dict | None:
    """Textstand einer Datei fuer den PDF-Analyzer.

    Liefert None, wenn die Datei nicht im Index ist, sonst ein dict mit
    ``dok_id``, ``textstatus``, ``aktuell`` (Groesse und mtime der Datei stimmen
    noch mit dem Index ueberein), ``text`` (Seiten mit \\f getrennt), ``seiten``
    (``[(nr, quelle, text), ...]``) und ``ocr_offen`` (Seitennummern ohne Text).
    """
    d = dokument_nach_pfad(con, pfad)
    if not d:
        return None
    aktuell = False
    try:
        st = os.stat(d["datei"])
        aktuell = st.st_size == d["groesse"] and st.st_mtime_ns == d["mtime_ns"]
    except OSError:
        pass
    seiten = [(r["seite"], r["quelle"], r["text"]) for r in con.execute(
        "SELECT seite, quelle, text FROM seiten WHERE dok_id = ? ORDER BY seite", (d["id"],))]
    return {
        "dok_id": d["id"],
        "textstatus": d["textstatus"],
        "aktuell": aktuell,
        "text": "\f".join(t for _, _, t in seiten),
        "seiten": seiten,
        "ocr_offen": [nr for nr, q, _ in seiten if q == "ohne_text"],
    }


def status(con) -> dict:
    pro_typ = {r["typ"]: r["n"] for r in con.execute("SELECT typ, count(*) n FROM dokumente GROUP BY typ")}
    pro_status = {r["textstatus"]: r["n"] for r in con.execute(
        "SELECT textstatus, count(*) n FROM dokumente GROUP BY textstatus")}
    seiten = con.execute("SELECT count(*) FROM seiten").fetchone()[0]
    ocr = con.execute("SELECT coalesce(sum(ocr_seiten),0) FROM dokumente").fetchone()[0]
    ausstehend_seiten = con.execute("SELECT count(*) FROM seiten WHERE quelle = 'ohne_text'").fetchone()[0]
    laeufe = [dict(r) for r in con.execute("SELECT * FROM laeufe ORDER BY id DESC LIMIT 10")]
    for lauf in laeufe:
        try:
            lauf["statistik"] = json.loads(lauf["statistik"] or "{}")
        except ValueError:
            pass
    return {
        "dokumente": sum(pro_typ.values()),
        "pro_typ": pro_typ,
        "pro_status": pro_status,
        "seiten": seiten,
        "ocr_seiten": ocr,
        "ocr_ausstehend_seiten": ausstehend_seiten,
        "laeufe": laeufe,
        "fortschritt": lies_meta(con, "fortschritt", ""),
        "schema_version": lies_meta(con, "schema_version", ""),
    }

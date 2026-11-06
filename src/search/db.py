"""SQLite-Datenbank der Dokumentensuche: Schema, Speichern, Suchen.

Uebernommen aus PDFsuche (``db.py``). Das Schema (Version 1) ist in
``docs/SUCHE_ARCHITEKTUR.md`` beschrieben; die Erweiterung auf Version 2
(OCR-Cache, Metadatenspalten) folgt in Phase 5 der Integration.

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

SCHEMA_VERSION = 1

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

# Statuswerte, die bedeuten "Text vollstaendig im Index"
FERTIG = ("text", "ocr", "leer")
# Statuswerte, bei denen der vorhandene Text verwendbar ist (ggf. unvollstaendig)
VERWENDBAR = FERTIG + ("ocr_teilweise", "ocr_ausstehend")


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
    con.executescript(SCHEMA)
    con.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    con.commit()


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


def speichere(con: sqlite3.Connection, dok: dict, seiten: list[tuple[int, str, str]]) -> int:
    """Dokument anlegen oder ersetzen. ``seiten = [(seite, quelle, text), ...]``. Liefert die id."""
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
        con.executemany(
            "INSERT INTO seiten (dok_id, seite, quelle, text) VALUES (?, ?, ?, ?)",
            [(dok_id, s, q, t) for s, q, t in seiten],
        )
    return dok_id


def loesche(con: sqlite3.Connection, dok_ids) -> None:
    ids = list(dok_ids)
    for i in range(0, len(ids), 500):
        teil = ids[i:i + 500]
        ph = ",".join("?" * len(teil))
        con.execute(f"DELETE FROM seiten WHERE dok_id IN ({ph})", teil)
        con.execute(f"DELETE FROM dokumente WHERE id IN ({ph})", teil)


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


def _filter(typ=None, ordner=None, von=None, bis=None, status=None) -> tuple[str, list]:
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
          anzahl=30, start=0, max_stellen=3, nur_namen=False) -> dict:
    """Volltextsuche. Liefert ``{'treffer': [...], 'gesamt': n, 'mehr': bool, 'abfrage': fts, 'dauer_ms': ms}``.

    Ausschnitte enthalten die Marker ``\\x02`` (Beginn) und ``\\x03`` (Ende) um Fundstellen.
    Bei FTS5-Syntaxfehlern wird die Abfrage als Folge einzelner Woerter wiederholt.
    """
    filt, fargs = _filter(typ, ordner, von, bis)
    t0 = time.perf_counter()

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
        return zeilen, namen, len(zeilen) >= grenze

    fts = fts_abfrage(abfrage)
    try:
        zeilen, namen, abgeschnitten = ausfuehren(fts)
    except sqlite3.OperationalError:
        fts = _als_woerter(abfrage)
        if not fts:
            return {"treffer": [], "gesamt": 0, "mehr": False, "abfrage": fts, "dauer_ms": 0}
        zeilen, namen, abgeschnitten = ausfuehren(fts)

    dok: dict[int, dict] = {}
    for z in zeilen:
        e = dok.setdefault(z["dok_id"], {"rang": z["rang"], "stellen": [], "treffer_seiten": 0, "im_namen": False})
        e["treffer_seiten"] += 1
        if len(e["stellen"]) < max_stellen:
            e["stellen"].append({"seite": z["seite"], "quelle": z["quelle"], "text": z["ausschnitt"]})
    for z in namen:
        e = dok.setdefault(z["id"], {"rang": 0.0, "stellen": [], "treffer_seiten": 0, "im_namen": True})
        e["im_namen"] = True
        e["rang"] = min(e["rang"], 0.0) - 5.0  # Namenstreffer nach vorn

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


def _kurz(r: dict) -> dict:
    return {k: r.get(k) for k in (
        "id", "pfad", "datei", "name", "ordner", "typ", "format", "groesse", "datum", "seiten",
        "textstatus", "ocr_seiten", "mail_von", "mail_an", "mail_datum", "mail_betreff", "mail_anhaenge", "fehler",
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


def volltext(con, dok_id: int) -> str:
    """Gesamter Text eines Dokuments, Seiten durch Seitenvorschub (\\f) getrennt."""
    return "\f".join(
        r[0] for r in con.execute("SELECT text FROM seiten WHERE dok_id = ? ORDER BY seite", (dok_id,))
    )


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

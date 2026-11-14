"""Bedeutungssuche fuer den Chat (Issue #230): Seiten finden, die dasselbe meinen wie die Frage.

Die Wortsuche (FTS5) findet eine Seite nur, wenn die gesuchten Woerter darin
stehen. Hier bekommt jede Seite des Suchindex zusaetzlich einen
Bedeutungsvektor ("Embedding"), den ein lokales Modell ueber Ollama berechnet;
die Frage bekommt denselben, und die aehnlichsten Seiten sind die Treffer.
Nichts davon verlaesst den Rechner.

Ablage in der Suchdatenbank, Tabelle ``seiten_vektor`` (eine Zeile je Seite):
der Vektor wird auf :data:`DIM` Werte gekuerzt, normiert und als ``int8``
gespeichert (256 Bytes je Seite). In der Messung zu Issue #230
(``docs/BEDEUTUNGSSUCHE_MESSUNG.md``) kostete das gegenueber 768 Gleitkommawerten
keinen Treffer. Zwei Trigger loeschen den Vektor, wenn die Seite geloescht
oder ihr Text geaendert wird; der naechste Lauf rechnet ihn neu.

Die Tabelle entsteht erst, wenn die Bedeutungssuche eingeschaltet ist und der
Indexlauf sie zum ersten Mal vorbereitet (:func:`schema`). Wer sie nicht
nutzt, hat sie nicht.

Qt-frei; ``numpy`` wird erst beim Rechnen geladen.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence

log = logging.getLogger("suche")

URL_STANDARD = "http://localhost:11434"
MODELL_STANDARD = "embeddinggemma"
DIM = 256                 # gespeicherte Werte je Seite (das Modell liefert 768; die ersten 256 genuegen)
SKALA = 508.0             # float -> int8: normierte Werte liegen fast immer unter 0,25
MIN_ZEICHEN = 40          # kuerzere Seiten (Leerseiten, Seitenzahlen) bekommen keinen Vektor
MAX_ZEICHEN = 6000        # laengere Texte werden gekappt (Kontext des Modells: 2048 Tokens)
STAPEL = 16               # Seiten je Anfrage an Ollama
HOLEN = 256               # Seiten je Datenbankabfrage
KURZLAUF_SEITEN = 320     # Laeufe nur ueber Vorrang-Ordner oder einen Ordner: hoechstens so viele Seiten
MIN_AEHNLICHKEIT = 0.30   # darunter gilt eine Seite nicht als Treffer (Messung: fremde Fragen 0,19-0,22)
ZEITLIMIT_SEITEN_S = 300  # je Stapel im Indexlauf (das Modell wird beim ersten Stapel geladen)
ZEITLIMIT_FRAGE_S = 20    # im Chat: lieber ohne Bedeutungstreffer antworten als lange warten
_BLOCK = 50_000           # Zeilen je Rechenschritt beim Vergleichen (haelt den Speicherbedarf klein)

SCHEMA = """
CREATE TABLE IF NOT EXISTS seiten_vektor (
    seite_id INTEGER PRIMARY KEY,
    modell   TEXT NOT NULL,
    vektor   BLOB NOT NULL
);
CREATE TRIGGER IF NOT EXISTS seiten_vektor_ad AFTER DELETE ON seiten BEGIN
    DELETE FROM seiten_vektor WHERE seite_id = old.id;
END;
CREATE TRIGGER IF NOT EXISTS seiten_vektor_au AFTER UPDATE OF text ON seiten BEGIN
    DELETE FROM seiten_vektor WHERE seite_id = old.id;
END;
"""


class BedeutungFehler(Exception):  # noqa: N818 - Name wie WerkzeugFehler, ZeitplanFehler
    """Ollama nicht erreichbar, Modell fehlt oder unbrauchbare Antwort."""


def schema(con: sqlite3.Connection) -> None:
    """Tabelle und Trigger anlegen (idempotent)."""
    con.executescript(SCHEMA)


def vorhanden(con: sqlite3.Connection) -> bool:
    """Gibt es die Tabelle schon?"""
    return con.execute("SELECT 1 FROM sqlite_master WHERE name = 'seiten_vektor'").fetchone() is not None


# --------------------------------------------------------------------------- Ollama

def _vorsatz(modell: str, frage: bool) -> str:
    """Vom Modell empfohlener Vorsatz; EmbeddingGemma unterscheidet Frage und Dokument."""
    if "embeddinggemma" in (modell or "").lower():
        return "task: search result | query: " if frage else "title: none | text: "
    return ""


def _anfrage(url: str, pfad: str, daten: dict | None, zeitlimit: float) -> dict:
    """Eine Anfrage an Ollama; Fehler als :class:`BedeutungFehler`."""
    adresse = f"{(url or URL_STANDARD).rstrip('/')}{pfad}"
    anfrage = urllib.request.Request(
        adresse, data=json.dumps(daten).encode("utf-8") if daten is not None else None,
        headers={"Content-Type": "application/json"}, method="POST" if daten is not None else "GET",
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=zeitlimit) as antwort:
            return json.loads(antwort.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            grund = json.loads(e.read().decode("utf-8")).get("error") or str(e)
        except Exception:  # noqa: BLE001 - Fehlertext ist Beiwerk
            grund = str(e)
        raise BedeutungFehler(f"Ollama: {grund}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise BedeutungFehler(f"Ollama nicht erreichbar ({adresse}): {getattr(e, 'reason', e)}") from e


def modell_vorhanden(url: str, modell: str, zeitlimit: float = 3.0) -> bool | None:
    """Ist das Modell in Ollama geladen? ``None``: Ollama nicht erreichbar."""
    try:
        daten = _anfrage(url, "/api/tags", None, zeitlimit)
    except BedeutungFehler:
        return None
    gesucht = (modell or MODELL_STANDARD).lower()
    for m in daten.get("models") or []:
        name = str(m.get("name") or m.get("model") or "").lower()
        if name == gesucht or name.split(":")[0] == gesucht or name == f"{gesucht}:latest":
            return True
    return False


def _packen(vektoren):
    """Auf :data:`DIM` kuerzen, normieren, als ``int8`` runden."""
    import numpy as np

    v = np.asarray(vektoren, dtype=np.float32)
    if v.ndim != 2 or v.shape[1] < DIM:
        raise BedeutungFehler(f"Das Modell liefert zu kurze Vektoren ({v.shape}); gebraucht werden {DIM} Werte.")
    v = v[:, :DIM]
    v = v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)
    return np.clip(np.rint(v * SKALA), -127, 127).astype(np.int8)


def einbetten(url: str, modell: str, texte: Sequence[str], frage: bool = False,
              zeitlimit: float = ZEITLIMIT_SEITEN_S):
    """Bedeutungsvektoren (``int8``, Form ``(n, DIM)``) fuer Seitentexte oder eine Frage."""
    modell = modell or MODELL_STANDARD
    vorsatz = _vorsatz(modell, frage)
    daten = _anfrage(url, "/api/embed", {
        "model": modell, "input": [vorsatz + (t or "")[:MAX_ZEICHEN] for t in texte], "truncate": True,
    }, zeitlimit)
    vektoren = daten.get("embeddings")
    if not isinstance(vektoren, list) or len(vektoren) != len(texte):
        raise BedeutungFehler("Ollama hat keine Vektoren geliefert.")
    return _packen(vektoren)


# --------------------------------------------------------------------------- Vorbereiten (Indexlauf)

_OFFEN = """FROM seiten s JOIN dokumente d ON d.id = s.dok_id
            LEFT JOIN seiten_vektor v ON v.seite_id = s.id
            WHERE (v.seite_id IS NULL OR v.modell != ?) AND length(s.text) >= ?"""


def stand(con: sqlite3.Connection, modell: str) -> dict:
    """``{"seiten": n, "fertig": m}``: Seiten im Index und wie viele davon einen Vektor dieses Modells haben.

    Bewusst nur zwei schnelle Zaehlungen (die Einstellungen zeigen den Stand
    beim Oeffnen): ``seiten`` zaehlt auch leere und sehr kurze Seiten mit, die
    nie einen Vektor bekommen - ``fertig`` erreicht ``seiten`` deshalb selten ganz.
    """
    seiten = con.execute("SELECT count(*) FROM seiten").fetchone()[0]
    fertig = 0
    if vorhanden(con):
        fertig = con.execute("SELECT count(*) FROM seiten_vektor WHERE modell = ?",
                             (modell or MODELL_STANDARD,)).fetchone()[0]
    return {"seiten": int(seiten), "fertig": int(fertig)}


def berechnen(con: sqlite3.Connection, url: str, modell: str,
              weiter: Callable[[], None] | None = None,
              melden: Callable[[int, int], None] | None = None,
              hoechstens: int | None = None) -> int:
    """Fehlende Vektoren berechnen und speichern; liefert die Zahl der neuen Seiten.

    Dokumente zuerst, Mails danach, jeweils die zuletzt aufgenommenen Seiten
    zuerst. Nach jedem Stapel wird gespeichert, ein Abbruch verliert also
    hoechstens einen Stapel. ``weiter`` wird vor jedem Stapel gerufen und darf
    eine Ausnahme werfen (Zeitlimit, Anhalten, Pause im Indexlauf). Fehler von
    Ollama kommen als :class:`BedeutungFehler` heraus. ``hoechstens`` begrenzt
    die Seiten dieses Aufrufs (kurze Laeufe sollen den Rechner nicht
    stundenlang belegen; der Rest bleibt fuer den naechsten vollen Lauf).
    """
    modell = modell or MODELL_STANDARD
    schema(con)
    offen = con.execute(f"SELECT count(*) {_OFFEN}", (modell, MIN_ZEICHEN)).fetchone()[0]
    neu = 0
    for mails in (0, 1):
        while True:
            zeilen = con.execute(
                f"SELECT s.id, s.text {_OFFEN} AND (d.typ = 'mail') = ? ORDER BY s.id DESC LIMIT ?",
                (modell, MIN_ZEICHEN, mails, HOLEN)).fetchall()
            if not zeilen:
                break
            for i in range(0, len(zeilen), STAPEL):
                if hoechstens is not None and neu >= hoechstens:
                    return neu
                if weiter is not None:
                    weiter()
                teil = zeilen[i:i + STAPEL]
                vektoren = einbetten(url, modell, [z[1] for z in teil])
                con.executemany(
                    "INSERT OR REPLACE INTO seiten_vektor (seite_id, modell, vektor) VALUES (?, ?, ?)",
                    [(z[0], modell, v.tobytes()) for z, v in zip(teil, vektoren, strict=True)])
                con.commit()
                neu += len(teil)
                if melden is not None:
                    melden(neu, offen)
    return neu


# --------------------------------------------------------------------------- Suchen (Chat)

_matrix_sperre = threading.Lock()
_matrix_ablage: dict[tuple, tuple] = {}   # (Datei, Modell) -> (Stand, Seiten-Ids, Matrix)


def _matrix(con: sqlite3.Connection, schluessel: str, modell: str):
    """Alle Vektoren eines Modells als ``int8``-Matrix; je Datenbank und Modell im Speicher gehalten.

    Neu geladen wird, wenn Vektoren dazugekommen oder weggefallen sind
    (Anzahl und hoechste Seiten-Id).
    """
    import numpy as np

    jetzt = tuple(con.execute("SELECT count(*), coalesce(max(seite_id), 0) FROM seiten_vektor WHERE modell = ?",
                              (modell,)).fetchone())
    with _matrix_sperre:
        alt = _matrix_ablage.get((schluessel, modell))
        if alt is not None and alt[0] == jetzt:
            return alt[1], alt[2]
    ids, teile = [], []
    for seite_id, blob in con.execute("SELECT seite_id, vektor FROM seiten_vektor WHERE modell = ?", (modell,)):
        if len(blob) == DIM:
            ids.append(seite_id)
            teile.append(blob)
    matrix = np.frombuffer(b"".join(teile), dtype=np.int8).reshape(len(ids), DIM) if ids else np.zeros((0, DIM), np.int8)
    ids = np.asarray(ids, dtype=np.int64)
    with _matrix_sperre:
        _matrix_ablage.clear()   # nur eine Datenbank im Speicher halten
        _matrix_ablage[(schluessel, modell)] = (jetzt, ids, matrix)
    return ids, matrix


def suche(con: sqlite3.Connection, frage_vektor, modell: str, anzahl: int = 4,
          schluessel: str = "") -> list[dict]:
    """Die aehnlichsten Dokumente zur Frage: ``[{"dok_id", "seite", "aehnlichkeit"}]``, bestes zuerst.

    Je Dokument zaehlt die beste Seite. Seiten unter :data:`MIN_AEHNLICHKEIT`
    sind keine Treffer. ``schluessel`` (Pfad der Datenbank) trennt die im
    Speicher gehaltenen Vektoren verschiedener Datenbanken.
    """
    import numpy as np

    modell = modell or MODELL_STANDARD
    if anzahl <= 0 or not vorhanden(con):
        return []
    ids, matrix = _matrix(con, schluessel, modell)
    if not len(ids):
        return []
    q = np.asarray(frage_vektor, dtype=np.float32).reshape(-1)[:DIM]
    q = q / (np.linalg.norm(q) + 1e-9)
    werte = np.empty(len(ids), dtype=np.float32)
    for i in range(0, len(ids), _BLOCK):
        block = matrix[i:i + _BLOCK].astype(np.float32)
        werte[i:i + _BLOCK] = (block @ q) / (np.linalg.norm(block, axis=1) + 1e-9)
    # Genug Seiten ansehen, damit nach dem Zusammenfassen je Dokument ``anzahl`` uebrig bleiben
    k = min(len(ids), max(anzahl * 8, 32))
    beste = np.argpartition(-werte, k - 1)[:k]
    beste = beste[np.argsort(-werte[beste])]
    treffer: list[dict] = []
    gesehen: set[int] = set()
    for i in beste:
        if werte[i] < MIN_AEHNLICHKEIT or len(treffer) >= anzahl:
            break
        r = con.execute("SELECT dok_id, seite FROM seiten WHERE id = ?", (int(ids[i]),)).fetchone()
        if r is None or r[0] in gesehen:
            continue
        gesehen.add(r[0])
        treffer.append({"dok_id": int(r[0]), "seite": int(r[1]), "aehnlichkeit": float(werte[i])})
    return treffer

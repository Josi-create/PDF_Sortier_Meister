"""Indexierungslauf der Dokumentensuche: Dateien finden, Text gewinnen, OCR, Mails, Aufraeumen.

Uebernommen aus PDFsuche (``indexer.py``; Klasse ``Lauf`` heisst jetzt ``Indexer``).
Laeuft im Dienstprozess (``pdfsm-dienst index``); die Oberflaeche startet ihn nie
im eigenen Prozess. Plattformabhaengiges (Sperre, Job-Objekt bzw. Prozessgruppe,
Hintergrundprioritaet, Cloud-Platzhalter, Leerlaufzeit) liegt in ``plattform.py``.

Ablauf eines Laufs: Vorrang-Ordner (im ersten sofort OCR) -> Wurzeln -> Mails ->
restliche OCR -> OCR-Cache des Bestands auffuellen. Unveraenderte Dateien
(Groesse + mtime_ns) werden uebersprungen, verschobene oder kopierte Dateien
uebernehmen den vorhandenen Text samt OCR, Aufraeumen nur nach vollstaendig
durchlaufener Wurzel. Seit Schema-Version 2 (Phase 5): Bildseiten bekommen
ihren OCR-Text aus dem Cache nach Bildinhalt, PDFSM-Metadaten werden aus der
PDF gelesen (Quelle ``'pdf'``, Werte von PDFSM haben Vorrang), und von PDFSM
verwaltete Dokumente bleiben beim Aufraeumen stehen, solange die Datei
existiert. ``einzeldatei_indizieren`` liest eine Datei synchron (Meldungen der
Oberflaeche). Phase 5b: Nach der OCR schreibt der Lauf die unsichtbare
Textebene in die PDFs (``textebene.py``; Stufe ``alle`` auch fuer den
Altbestand). Issue #151: Liest die OCR eine Seite gedreht besser, dreht
derselbe Schritt die PDF (Stufe ``auto_drehen``). Eine Datei
``indexer.anhalten`` im Datenordner haelt den Lauf an; der naechste Lauf
setzt fort.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sqlite3
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from pathlib import Path

from src.search import db, extract, mbox, office, plattform, textebene
from src.search.konfig import SearchConfig
from src.i18n import tr

log = logging.getLogger("pdf_sortier_meister.suche")

TYP = {".pdf": ("pdf", "pdf"), ".md": ("md", "md"), ".eml": ("mail", "eml"), ".msg": ("mail", "msg"),
       ".docx": ("office", "docx"), ".docm": ("office", "docm"), ".xlsx": ("office", "xlsx"),
       ".xlsm": ("office", "xlsm"), ".odt": ("office", "odt"),
       ".doc": ("office", "doc"), ".xls": ("office", "xls"), ".txt": ("office", "txt")}
OFFICE = {"docx", "docm", "xlsx", "xlsm", "odt", "doc", "xls", "txt"}
# Endungen, die der Lauf nicht von sich aus aufnimmt (Issue #227): .txt liegt massenhaft als
# Protokoll oder Lizenztext herum. In den Index kommt eine solche Datei erst, wenn der Nutzer
# sie in PDFSM einsortiert (verschiebt, kopiert, Metadaten setzt); danach haelt der Lauf sie
# aktuell. Wer alle will, traegt die Endung in den Einstellungen ein (``SearchConfig.endungen``).
NUR_AUF_WUNSCH = {".txt"}
OCR_STUECK = 8            # Seiten je OCR-Auftrag
MBOX_STAPEL_MAILS = 200
MBOX_STAPEL_BYTES = 24 * 1024 * 1024
LEERLAUF_PRUEFEN_S = 30       # nur_leerlauf: so oft wird die Leerlaufzeit abgefragt ...
LEERLAUF_MIN_S = 60           # ... und so lange muss der Nutzer untaetig sein, damit der Lauf (weiter)arbeitet
LEERLAUF_PAUSE_S = 10         # Wartezeit zwischen zwei Pruefungen waehrend einer Pause
ANHALTEN_PRUEFEN_S = 2        # so oft sieht der Lauf nach, ob er angehalten werden soll


# --------------------------------------------------------------------------- Hilfen

def logging_einrichten(konfig: SearchConfig, konsole: bool = True) -> None:
    """Protokoll nach ``<Datenverzeichnis>/logs/suche.log`` (rotierend), optional auch auf die Konsole."""
    ordner = konfig.log_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    if log.handlers:
        return
    fh = logging.handlers.RotatingFileHandler(ordner / "suche.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(fh)
    if konsole:
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
        log.addHandler(sh)


_sperre_datei = None


def sperrdatei(konfig: SearchConfig) -> Path:
    return konfig.daten_ordner / "indexer.lock"


def sperre_holen(konfig: SearchConfig) -> bool:
    """Verhindert, dass zwei Laeufe gleichzeitig arbeiten (auch ueber Prozessgrenzen)."""
    global _sperre_datei
    p = sperrdatei(konfig)
    p.parent.mkdir(parents=True, exist_ok=True)
    f = open(p, "a+")
    try:
        plattform.sperren(f)
    except OSError:
        f.close()
        return False
    _sperre_datei = f
    return True


def sperre_freigeben() -> None:
    global _sperre_datei
    if _sperre_datei is not None:
        plattform.entsperren(_sperre_datei)
        _sperre_datei.close()
        _sperre_datei = None


VOLLER_LAUF_META = "voller_lauf_am"     # Ende des letzten vollstaendigen Laufs (alle Ordner)


def heute_schon_gelaufen(konfig: SearchConfig) -> bool:
    """Ist heute (Ortszeit) schon ein vollstaendiger Lauf fertig geworden? (``index --einmal-taeglich``)"""
    if not konfig.db_datei.exists():
        return False
    try:
        con = db.verbinde(konfig.db_datei, nur_lesen=True)
        try:
            wert = db.lies_meta(con, VOLLER_LAUF_META)
        finally:
            con.close()
    except sqlite3.Error:
        return False
    return bool(wert) and str(wert)[:10] == db.jetzt()[:10]


def anhalten_datei(konfig: SearchConfig) -> Path:
    """Liegt diese Datei im Datenordner, haelt der laufende Lauf an (Oberflaeche: „Anhalten“)."""
    return konfig.daten_ordner / "indexer.anhalten"


def anhalten(konfig: SearchConfig) -> bool:
    """Den laufenden Lauf bitten anzuhalten; laufende Auftraege werden noch beendet. False ohne Lauf."""
    if not laeuft_gerade(konfig):
        return False
    try:
        anhalten_datei(konfig).touch()
    except OSError:
        return False
    return True


def laeuft_gerade(konfig: SearchConfig) -> bool:
    p = sperrdatei(konfig)
    if not p.exists():
        return False
    try:
        with open(p, "a+") as f:
            plattform.sperren(f)
            plattform.entsperren(f)
        return False
    except OSError:
        return True


@dataclass
class Auftrag:
    art: str                      # 'datei' | 'ocr' | 'mbox'
    fn: object
    args: tuple
    info: dict
    zeitlimit: float
    versuche: int = 0
    gestartet: float | None = None
    eingereicht: float = field(default_factory=time.monotonic)


class Abbruch(Exception):
    pass


class _SynchronAusfuehrer:
    """Ersatz fuer den ProcessPool in Tests und zur Fehlersuche: fuehrt Auftraege sofort im Prozess aus."""

    def submit(self, fn, *args) -> Future:
        fut: Future = Future()
        try:
            fut.set_result(fn(*args))
        except BaseException as e:  # noqa: BLE001 - wie im Pool: Ausnahme im Future
            fut.set_exception(e)
        return fut

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        pass


# --------------------------------------------------------------------------- Ergebnis speichern

def dokument_speichern(con, basis: dict, fmt: str, res: dict) -> tuple[int, dict, dict]:
    """Ergebnis eines Lese-Auftrags speichern (Lauf und Einzeldatei-Meldungen der Oberflaeche).

    PDFs: Seiten ohne Text bekommen ihren OCR-Text aus dem Cache (Bild-Hash),
    die PDFSM-Metadaten aus Info-Dict und XMP landen mit Quelle ``'pdf'``
    (Werte mit Quelle ``'pdfsm'`` bleiben, Vorrangregel). Gemessene
    Schraeglagen (Issue #165) werden am Bild-Hash vorgemerkt. Liefert
    ``(dok_id, dok, zaehler)`` mit ``zaehler = {"ocr_cache": n, "schief": n}``.
    """
    zaehler = {"ocr_cache": 0, "schief": 0}
    hashes: dict = {}
    if fmt == "pdf":
        seiten = list(res["seiten"])
        hashes = dict(res.get("bild_hashes") or {})
        status = res["status"]
        if hashes:
            cache = db.ocr_cache_holen(con, hashes.values())
            if cache:
                neu = []
                for nr, quelle, text in seiten:
                    h = hashes.get(nr)
                    if quelle == "ohne_text" and h in cache:
                        neu.append((nr, "ocr", cache[h]))
                        zaehler["ocr_cache"] += 1
                    else:
                        neu.append((nr, quelle, text))
                seiten = neu
                if zaehler["ocr_cache"] and status == "ocr_ausstehend":
                    status = "ocr_ausstehend" if any(q == "ohne_text" for _, q, _ in seiten) else "ocr"
        dok = {**basis, "seiten": res["anzahl"], "textstatus": status, "fehler": res["fehler"],
               "titel": res["titel"], "autor": res["autor"],
               "ocr_seiten": sum(1 for _, q, _ in seiten if q == "ocr")}
    elif fmt in OFFICE:
        dok = {**basis, "seiten": len(res["seiten"]) or None, "textstatus": res["status"],
               "fehler": res["fehler"], "titel": res["titel"], "autor": res["autor"]}
        seiten = res["seiten"]
    elif fmt == "md":
        dok = {**basis, "seiten": 1, "textstatus": res["status"], "fehler": res["fehler"], "titel": res["titel"]}
        seiten = [(1, "text", res["text"])] if res["text"] else []
    else:
        dok = {**basis, "seiten": 1, "textstatus": res["status"], "fehler": res["fehler"],
               "mail_von": res["von"], "mail_an": res["an"], "mail_datum": res["datum_iso"],
               "mail_betreff": res["betreff"], "mail_anhaenge": res["anhaenge"], "titel": res["betreff"]}
        seiten = [(1, "text", res["text"])] if res["text"] else []
    vorher = None
    if fmt == "pdf":
        vorher = con.execute("SELECT textebene_am FROM dokumente WHERE pfad = ?", (basis["pfad"],)).fetchone()
    dok_id = db.speichere(con, dok, seiten, bild_hashes=hashes)
    if fmt == "pdf" and res.get("metadaten"):
        db.metadaten_setzen(con, dok_id, res["metadaten"], quelle="pdf")
    if fmt == "pdf" and res.get("schraeglagen"):
        zaehler["schief"] = db.schraeglagen_eintragen(con, dok_id, res["schraeglagen"])
    if vorher is not None and vorher[0] and any(q == "ocr" and (t or "").strip() for _, q, t in seiten):
        # Seiten mit Textebene lesen sich als Text; erkannte Bildseiten heissen, sie ist verloren gegangen
        # (z. B. aeltere Fassung zurueckkopiert) - der naechste Lauf schreibt sie neu
        con.execute("UPDATE dokumente SET textebene_am = NULL WHERE id = ?", (dok_id,))
    return dok_id, dok, zaehler


def datei_lesen(pfad: str, konfig: SearchConfig) -> tuple[dict, str, dict] | None:
    """Eine Datei synchron im eigenen Prozess lesen: ``(basis, format, ergebnis)``; None bei unbekannter Endung."""
    ext = os.path.splitext(pfad)[1].lower()
    if ext not in TYP:
        return None
    st = os.stat(pfad)
    typ, fmt = TYP[ext]
    basis = {"pfad": pfad, "datei": pfad, "name": os.path.basename(pfad), "ordner": os.path.dirname(pfad),
             "typ": typ, "format": fmt, "groesse": st.st_size, "mtime_ns": st.st_mtime_ns, "datum": st.st_mtime,
             "prioritaet": 9}
    if fmt == "pdf":
        res = extract.pdf_text(pfad, konfig.ocr_einstellungen()["min_zeichen"], konfig.gerade_vormerken(pfad))
    elif fmt in OFFICE:
        res = office.office_text(pfad, fmt)
    elif fmt == "md":
        res = extract.md_text(pfad)
    elif fmt == "eml":
        res = extract.eml_text(pfad)
    else:
        res = extract.msg_text(pfad)
    return basis, fmt, res


def einzeldatei_indizieren(con, konfig: SearchConfig, pfad: str, prioritaet: int | None = None,
                           vorab: dict | None = None) -> int | None:
    """Eine Datei sofort indizieren (Textebene; Bildseiten bleiben fuer den naechsten OCR-Lauf offen).

    Fuer die Schreibmeldungen der Oberflaeche (``Suchindex.datei_aufnehmen`` /
    ``datei_geaendert``). ``vorab`` ist ein schon vorliegendes Ergebnis von
    ``extract.pdf_text`` (spart das zweite Lesen im PDF-Analyzer). Die
    Prioritaet bleibt bei einem bekannten Dokument erhalten, sonst ``prioritaet``
    bzw. 9. Liefert die Dokument-Id; None, wenn die Datei fehlt oder die Endung
    unbekannt ist.
    """
    pfad = str(pfad)
    if not os.path.isfile(pfad):
        return None
    gelesen = datei_lesen(pfad, konfig) if vorab is None else None
    if vorab is not None:
        ext = os.path.splitext(pfad)[1].lower()
        if ext not in TYP:
            return None
        st = os.stat(pfad)
        typ, fmt = TYP[ext]
        basis = {"pfad": pfad, "datei": pfad, "name": os.path.basename(pfad), "ordner": os.path.dirname(pfad),
                 "typ": typ, "format": fmt, "groesse": st.st_size, "mtime_ns": st.st_mtime_ns,
                 "datum": st.st_mtime, "prioritaet": 9}
        res = vorab
    elif gelesen is None:
        return None
    else:
        basis, fmt, res = gelesen
    alt = con.execute("SELECT prioritaet FROM dokumente WHERE pfad = ?", (pfad,)).fetchone()
    if alt is not None:
        basis["prioritaet"] = alt[0]
    elif prioritaet is not None:
        basis["prioritaet"] = int(prioritaet)
    dok_id, _dok, _z = dokument_speichern(con, basis, fmt, res)
    return dok_id


# --------------------------------------------------------------------------- Lauf

class Indexer:
    """Ein Indexierungslauf. ``lauf()`` liefert 0 (fertig), 1 (abgebrochen/Fehler) oder 2 (laeuft schon)."""

    # mbox-Zwischenstand (bis wohin lueckenlos gelesen) hoechstens alle 30 s sichern
    MBOX_STAND_INTERVALL_S = 30

    def __init__(self, konfig: SearchConfig, hintergrund: bool = False, max_minuten: float = 0,
                 synchron: bool = False, nur_leerlauf: bool = False):
        self.konfig = konfig
        self.hintergrund = hintergrund
        self.synchron = synchron
        self.nur_leerlauf = nur_leerlauf
        self._leerlauf_geprueft = 0.0
        self.ende_zeit = time.monotonic() + max_minuten * 60 if max_minuten else None
        self.con = db.verbinde(konfig.db_datei)
        db.init(self.con)
        self.n = 1 if synchron else konfig.anzahl_prozesse
        self.ocr = konfig.ocr_einstellungen()
        self.pool = None
        self.offen: dict = {}
        self.stat = Counter()
        self.phase = ""
        self.letzter_commit = time.monotonic()
        self.aenderungen = 0
        self.bekannt: dict[str, list] = {}
        self.signatur: dict = {}
        self.gesehen: set[str] = set()
        self.lauf_id = None
        self._mbox_stand_zeit = 0.0
        self._anhalten_geprueft = 0.0

    # ---------------------------------------------------------------- Pool
    def _pool(self):
        if self.pool is None:
            if self.synchron:
                self.pool = _SynchronAusfuehrer()
            else:
                self.pool = ProcessPoolExecutor(max_workers=self.n, initializer=extract.arbeiter_start,
                                                initargs=(self.hintergrund,))
        return self.pool

    def _pool_beenden(self) -> None:
        if self.pool is None:
            return
        try:
            if hasattr(self.pool, "kill_workers"):          # ab Python 3.14
                self.pool.kill_workers()
            else:                                            # Python 3.11: Arbeitsprozesse selbst beenden
                for p in list(getattr(self.pool, "_processes", {}).values()):
                    p.kill()
        except Exception:
            pass
        try:
            self.pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        self.pool = None

    def _einreichen(self, a: Auftrag) -> None:
        self._zeit_pruefen()
        while len(self.offen) >= self.n * 3:
            self._abarbeiten(einmal=True)
        a.eingereicht = time.monotonic()
        a.gestartet = None
        fut = self._pool().submit(a.fn, *a.args)
        self.offen[fut] = a

    def _abarbeiten(self, einmal: bool = False) -> None:
        while self.offen:
            fertig, _ = wait(list(self.offen), timeout=2, return_when=FIRST_COMPLETED)
            betroffen: list[Auftrag] = []
            for fut in fertig:
                a = self.offen.pop(fut)
                try:
                    res = fut.result()
                except BrokenProcessPool:
                    betroffen.append(a)
                    continue
                except Exception as e:
                    self._fehlgeschlagen(a, extract.fehlertext(e, a.info.get("pfad")))
                    continue
                try:
                    self._ergebnis(a, res)
                except sqlite3.Error:
                    raise
                except Exception:
                    log.exception("Ergebnis nicht speicherbar: %s", a.info.get("pfad"))
                    self.stat["fehler"] += 1
            # Zeitlimits
            jetzt = time.monotonic()
            haengt = None
            for fut, a in self.offen.items():
                if a.gestartet is None and fut.running():
                    a.gestartet = jetzt
                if a.gestartet and jetzt - a.gestartet > a.zeitlimit:
                    haengt = fut
                    break
            if haengt is not None:
                a = self.offen.pop(haengt)
                log.warning("Zeitüberschreitung: %s", a.info.get("pfad"))
                self._fehlgeschlagen(a, tr("Zeitüberschreitung"))
                rest = list(self.offen.values())
                self.offen.clear()
                self._pool_beenden()
                for r in rest:
                    self._einreichen(r)
            if betroffen:
                # Ein Arbeitsprozess ist abgestuerzt – Schuldigen einzeln ermitteln
                betroffen += list(self.offen.values())
                self.offen.clear()
                self._pool_beenden()
                for a in betroffen:
                    self._einzeln(a)
            self._commit_wenn_noetig()
            if einmal and (fertig or haengt or betroffen):
                return

    def _einzeln(self, a: Auftrag) -> None:
        """Auftrag allein ausfuehren – stuerzt er erneut ab, ist er der Uebeltaeter."""
        fut = self._pool().submit(a.fn, *a.args)
        try:
            res = fut.result(timeout=a.zeitlimit)
        except BrokenProcessPool:
            self._pool_beenden()
            self._fehlgeschlagen(a, tr("Absturz beim Lesen (Datei beschädigt?)"))
            return
        except TimeoutError:
            self._pool_beenden()
            self._fehlgeschlagen(a, tr("Zeitüberschreitung"))
            return
        except Exception as e:
            self._fehlgeschlagen(a, extract.fehlertext(e, a.info.get("pfad")))
            return
        self._ergebnis(a, res)

    def _fehlgeschlagen(self, a: Auftrag, grund: str) -> None:
        self.stat["fehler"] += 1
        i = a.info
        if a.art == "datei":
            db.speichere(self.con, {**i["basis"], "textstatus": "fehler", "fehler": grund[:500]}, [])
        elif a.art == "ocr":
            self.con.executemany(
                "UPDATE seiten SET quelle = 'ocr_fehler' WHERE dok_id = ? AND seite = ? AND quelle = 'ohne_text'",
                [(i["dok_id"], s) for s in i["seiten"]])
            self._ocr_status(i["dok_id"], grund)
        elif a.art == "mbox":
            log.warning("mbox-Stapel fehlgeschlagen (%s, Mails ab Offset %s): %s", i["pfad"], i.get("von"), grund)
            self._mbox_stapel_fertig(i)
        elif a.art == "hash":
            log.info("OCR-Cache ergänzen fehlgeschlagen: %s – %s", i.get("pfad"), grund)
        elif a.art == "textebene":
            textebene.ergebnis_eintragen(self.con, i["dok_id"], {"status": "fehler", "grund": "fehler",
                                                                 "pfad": i.get("pfad"), "fehler": grund})
            self.stat["textebene_fehler"] += 1
        self.aenderungen += 1

    # ---------------------------------------------------------------- Ergebnisse
    def _pruefsumme_merken(self, dok_id: int, basis: dict) -> None:
        """Pruefsumme der eben gelesenen Datei mitschreiben (Issue #245: Hinweis auf doppelte Dateien).

        Sie gilt fuer den Stand, den die Datei beim Bilden hatte; aendert sie sich
        spaeter (Textebene, Metadaten), verfaellt sie von selbst.
        """
        from src.core.duplikate import pruefsumme

        try:
            vorher = os.stat(basis["pfad"])
            summe = pruefsumme(basis["pfad"])
            st = os.stat(basis["pfad"])
        except OSError:
            return
        if (vorher.st_size, vorher.st_mtime_ns) == (st.st_size, st.st_mtime_ns):
            db.pruefsumme_setzen(self.con, dok_id, summe, st.st_size, st.st_mtime_ns)

    def _ergebnis(self, a: Auftrag, res) -> None:
        i = a.info
        if a.art == "datei":
            basis = i["basis"]
            fmt = basis["format"]
            dok_id, dok, zaehler = dokument_speichern(self.con, basis, fmt, res)
            self._pruefsumme_merken(dok_id, basis)
            if zaehler["ocr_cache"]:
                self.stat["ocr_cache"] += zaehler["ocr_cache"]
            if zaehler["schief"]:
                self.stat["schief_erkannt"] += zaehler["schief"]
            alt_quelle = (self.bekannt.get(basis["pfad"].lower()) or [None] * 6)[5]
            self.bekannt[basis["pfad"].lower()] = [dok_id, basis["groesse"], basis["mtime_ns"], dok["textstatus"],
                                                   basis["prioritaet"], alt_quelle]
            self.stat["gelesen"] += 1
            if dok["textstatus"] == "ocr_ausstehend":
                self.stat["ocr_vorgemerkt"] += 1
            if dok["textstatus"] == "fehler":
                self.stat["fehler"] += 1
                log.info("Fehler: %s – %s", basis["pfad"], dok["fehler"])
        elif a.art == "ocr":
            dok_id = i["dok_id"]
            texte = dict(res["texte"])
            for s in i["seiten"]:
                texte.setdefault(s, None)   # nicht geliefert = Fehler
            drehungen = res.get("drehungen") or {}
            erkannt = db.ocr_text_eintragen(self.con, dok_id, texte, self.ocr.get("sprachen"), self.ocr.get("dpi"),
                                            nur_offene=True, ebenen=res.get("ebenen"), drehungen=drehungen,
                                            drehen=bool(drehungen) and self.konfig.drehen_vormerken(i["pfad"]),
                                            lesbarkeit=res.get("lesbarkeit"))
            self.stat["ocr_seiten"] += erkannt
            if drehungen:
                self.stat["ocr_gedreht_erkannt"] += len(drehungen)
            self._ocr_status(dok_id, res.get("fehler"))
        elif a.art == "hash":
            # OCR-Cache des Bestands auffuellen: Hashes nachtragen, Texte in den Cache
            dok_id = i["dok_id"]
            for seite, h in res.items():
                self.con.execute("UPDATE seiten SET bild_hash = ? WHERE dok_id = ? AND seite = ? AND bild_hash IS NULL",
                                 (h, dok_id, seite))
            if res:
                ph = ",".join("?" * len(res))
                zeilen = self.con.execute(
                    f"SELECT bild_hash, text FROM seiten WHERE dok_id = ? AND quelle = 'ocr' AND seite IN ({ph})",
                    (dok_id, *res.keys())).fetchall()
                self.stat["ocr_cache_ergaenzt"] += db.ocr_cache_eintragen(
                    self.con, [(r[0], r[1]) for r in zeilen], self.ocr.get("sprachen"), self.ocr.get("dpi"))
        elif a.art == "textebene":
            status = textebene.ergebnis_eintragen(self.con, i["dok_id"], res)
            self.stat[f"textebene_{status}"] += 1
            if status == "geschrieben":
                self._stand_nachziehen(res["pfad"], res["groesse"], res["mtime_ns"])
                if res.get("gedreht"):
                    self.stat["gedreht_seiten"] += len(res["gedreht"])
                if res.get("gerade"):
                    self.stat["gerade_seiten"] += len(res["gerade"])
        elif a.art == "mbox":
            for off, laenge, m in res:
                dok = {
                    "pfad": f"{i['pfad']}#{off}", "datei": i["pfad"], "name": (m["betreff"] or "(ohne Betreff)")[:500],
                    "ordner": i["postfach"], "typ": "mail", "format": "mbox", "groesse": laenge, "mtime_ns": None,
                    "datum": m["datum_ts"], "seiten": 1, "textstatus": m["status"], "fehler": m["fehler"],
                    "prioritaet": 9, "titel": m["betreff"], "mail_von": m["von"], "mail_an": m["an"],
                    "mail_datum": m["datum_iso"], "mail_betreff": m["betreff"], "mail_anhaenge": m["anhaenge"],
                    "mbox_offset": off, "mbox_laenge": laenge,
                }
                db.speichere(self.con, dok, [(1, "text", m["text"])] if m["text"] else [])
            self.stat["mails"] += len(res)
            self._mbox_stapel_fertig(i)
        self.aenderungen += 1

    def _mbox_stapel_fertig(self, info: dict) -> None:
        """Ein mbox-Stapel ist erledigt (gespeichert oder endgueltig gescheitert): Zwischenstand pruefen.

        Wasserstandsmarke wie bei TCP: gesichert wird nur, bis wohin die Stapel
        lueckenlos fertig sind - die Arbeitsprozesse liefern sie in beliebiger
        Reihenfolge. ``mbox_stand.groesse`` heisst schon immer "bis hierher gelesen",
        der naechste Lauf setzt dort fort (``anfang_passt``). Hoechstens alle
        ``MBOX_STAND_INTERVALL_S`` Sekunden, damit grosse Postfaecher nach einem
        Abbruch nicht von vorn beginnen.
        """
        info["fertig"] = True
        lauf = info.get("lauf")
        if lauf is None:
            return
        stand = lauf["stand"]
        for s in lauf["stapel"]:
            if not s["fertig"]:
                break
            stand = s["bis"]
        lauf["stand"] = stand
        jetzt = time.monotonic()
        if stand > lauf["geschrieben"] and jetzt - self._mbox_stand_zeit >= self.MBOX_STAND_INTERVALL_S:
            self.con.execute("INSERT OR REPLACE INTO mbox_stand VALUES (?, ?, ?)",
                             (lauf["pfad"], stand, lauf["mtime_ns"]))
            lauf["geschrieben"] = stand
            self._mbox_stand_zeit = jetzt
            self._commit_wenn_noetig(sofort=True)

    def _ocr_status(self, dok_id: int, fehler: str | None) -> None:
        status = db.ocr_status_aktualisieren(self.con, dok_id, fehler)
        if status != "ocr_ausstehend":
            self.stat["ocr_dokumente"] += 1

    def _commit_wenn_noetig(self, sofort: bool = False) -> None:
        if not self.aenderungen and not sofort:
            return
        if sofort or self.aenderungen >= 300 or time.monotonic() - self.letzter_commit > 3:
            db.setze_meta(self.con, "fortschritt", self._fortschritt())
            self.con.commit()
            self.letzter_commit = time.monotonic()
            self.aenderungen = 0

    def _fortschritt(self) -> str:
        s = self.stat
        text = (f"{self.phase} – gelesen {s['gelesen']}, unverändert {s['unveraendert']}, Mails {s['mails']}, "
                f"OCR-Seiten {s['ocr_seiten']}, Fehler {s['fehler']}")
        if s["textebene_dateien"]:
            erledigt = sum(s[f"textebene_{k}"] for k in ("geschrieben", "vorhanden", "uebersprungen", "fehler"))
            text += f", Textebene {erledigt} von {s['textebene_dateien']} Dateien ({s['textebene_geschrieben']} geschrieben)"
        return text

    def _zeit_pruefen(self) -> None:
        if self.ende_zeit and time.monotonic() > self.ende_zeit:
            raise Abbruch(tr("Zeitlimit erreicht"))
        if self._anhalten_angefordert():
            raise Abbruch("angehalten")
        self._leerlauf_warten()

    def _anhalten_angefordert(self) -> bool:
        jetzt = time.monotonic()
        if jetzt - self._anhalten_geprueft < ANHALTEN_PRUEFEN_S:
            return False
        self._anhalten_geprueft = jetzt
        return anhalten_datei(self.konfig).exists()

    def _leerlauf_warten(self) -> None:
        """``nur_leerlauf``: pausiert, solange der Nutzer aktiv ist.

        Die Windows-Aufgabenplanung startet und stoppt den Lauf selbst nach
        Leerlauf; ein macOS-LaunchAgent kennt keine solche Bedingung, deshalb
        prueft der Lauf dort alle ``LEERLAUF_PRUEFEN_S`` Sekunden die Zeit seit
        der letzten Eingabe und wartet, bis der Nutzer ``LEERLAUF_MIN_S``
        Sekunden untaetig war. Laufende Auftraege werden dabei noch beendet.
        """
        if not self.nur_leerlauf:
            return
        jetzt = time.monotonic()
        if jetzt - self._leerlauf_geprueft < LEERLAUF_PRUEFEN_S:
            return
        self._leerlauf_geprueft = jetzt
        if self._leerlauf():
            return
        vorher = self.phase
        log.info("Nutzer aktiv – Lauf pausiert")
        self.stat["pausen"] += 1
        self._phase(tr("{vorher} – Pause (Nutzer aktiv)").format(vorher=vorher))
        while not self._leerlauf():
            if self.ende_zeit and time.monotonic() > self.ende_zeit:
                raise Abbruch(tr("Zeitlimit erreicht"))
            time.sleep(LEERLAUF_PAUSE_S)
        log.info("Leerlauf – Lauf geht weiter")
        self._phase(vorher)
        self._leerlauf_geprueft = time.monotonic()

    @staticmethod
    def _leerlauf() -> bool:
        s = plattform.leerlauf_sekunden()
        return s is None or s >= LEERLAUF_MIN_S

    def _phase(self, name: str) -> None:
        self.phase = name
        log.info("== %s", name)
        self.con.execute("UPDATE laeufe SET phase = ? WHERE id = ?", (name, self.lauf_id))
        self._commit_wenn_noetig(sofort=True)

    # ---------------------------------------------------------------- Dateien finden
    def _bekannte_laden(self) -> None:
        self.bekannt = {
            r["pfad"].lower(): [r["id"], r["groesse"], r["mtime_ns"], r["textstatus"], r["prioritaet"],
                                r["metadaten_quelle"]]
            for r in self.con.execute(
                "SELECT id, pfad, groesse, mtime_ns, textstatus, prioritaet, metadaten_quelle "
                "FROM dokumente WHERE format != 'mbox'")
        }
        # Signatur (Groesse, Aenderungszeit) -> Pfade: erkennt verschobene, umbenannte und kopierte
        # Dateien auch ohne Meldung der Oberflaeche; der gleiche Name ist nur Vorzugskriterium
        self.signatur = {}
        for k, v in self.bekannt.items():
            self.signatur.setdefault((v[1], v[2]), []).append(k)
        log.info("%d Dateien bereits im Index", len(self.bekannt))

    def _uebernehmen(self, alt_key: str, basis: dict, verschoben: bool) -> None:
        """Text einer verschobenen/kopierten Datei uebernehmen statt neu zu lesen (spart OCR)."""
        alt = self.bekannt[alt_key]
        if verschoben:
            self.con.execute(
                "UPDATE dokumente SET pfad = ?, datei = ?, name = ?, ordner = ?, prioritaet = ?, indiziert_am = ? "
                "WHERE id = ?",
                (basis["pfad"], basis["datei"], basis["name"], basis["ordner"], basis["prioritaet"], db.jetzt(), alt[0]))
            del self.bekannt[alt_key]
            self.bekannt[basis["pfad"].lower()] = [alt[0], alt[1], alt[2], alt[3], basis["prioritaet"], alt[5]]
            self.stat["verschoben"] += 1
        else:
            r = dict(self.con.execute("SELECT * FROM dokumente WHERE id = ?", (alt[0],)).fetchone())
            neu = {**r, **basis}
            neu.pop("id", None)
            dok_id = db.speichere(self.con, neu, [])
            self.con.execute("INSERT INTO seiten (dok_id, seite, quelle, text, bild_hash) "
                             "SELECT ?, seite, quelle, text, bild_hash FROM seiten WHERE dok_id = ?", (dok_id, alt[0]))
            # Metadaten der Kopie: dieselbe Datei traegt dieselben Felder (Quelle wie das Original)
            if r.get("metadaten_quelle"):
                db.metadaten_setzen(self.con, dok_id, {k: r.get(k) for k in db.METADATEN_FELDER},
                                    quelle=r["metadaten_quelle"])
            # Dieselbe Datei traegt dieselbe Textebene (bzw. denselben Grund, keine zu haben)
            self.con.execute("UPDATE dokumente SET textebene_am = ?, textebene_grund = ? WHERE id = ?",
                             (r.get("textebene_am"), r.get("textebene_grund"), dok_id))
            self.bekannt[basis["pfad"].lower()] = [dok_id, alt[1], alt[2], alt[3], basis["prioritaet"],
                                                   r.get("metadaten_quelle")]
            self.stat["kopie"] += 1
        pfade = self.signatur.setdefault((basis["groesse"], basis["mtime_ns"]), [])
        if verschoben and alt_key in pfade:
            pfade.remove(alt_key)
        pfade.append(basis["pfad"].lower())
        self.aenderungen += 1

    def _durchlaufen(self, wurzel: str, prio: int, auslassen: set[str]) -> bool:
        if not os.path.isdir(wurzel):
            log.warning("Nicht erreichbar, übersprungen: %s", wurzel)
            return False
        log.info("Durchsuche %s", wurzel)
        konfig = self.konfig
        stapel = [wurzel]
        ordner_zahl = 0
        while stapel:
            ordner = stapel.pop()
            ordner_zahl += 1
            if ordner_zahl % 2000 == 0:
                self._commit_wenn_noetig()
                self._zeit_pruefen()
            try:
                it = os.scandir(ordner)
            except OSError:
                if ordner == wurzel:
                    return False
                continue
            unterordner = []
            with it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if e.name.lower() in konfig.ordner_ausschliessen:
                                continue
                            pl = e.path.lower()
                            if pl in konfig.pfade_ausschliessen or pl in auslassen:
                                continue
                            if plattform.verknuepfung(e.stat(follow_symlinks=False)):
                                continue
                            unterordner.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            ext = os.path.splitext(e.name)[1].lower()
                            if ext in TYP and not e.name.startswith("~$") and (
                                    ext in konfig.endungen
                                    or (ext in NUR_AUF_WUNSCH and e.path.lower() in self.bekannt)):
                                self._datei(e, ext, prio)
                            elif ext == ".icloud":
                                self._cloud_platzhalter(e, prio)
                    except OSError:
                        continue
            # Rueckwaerts, damit die Ordner in alphabetischer Reihenfolge abgearbeitet werden
            stapel.extend(sorted(unterordner, key=str.lower, reverse=True))
        return True

    def _datei(self, e: os.DirEntry, ext: str, prio: int) -> None:
        st = e.stat(follow_symlinks=False)
        pfad = e.path
        key = pfad.lower()
        self.gesehen.add(key)
        alt = self.bekannt.get(key)
        nur_cloud = plattform.nur_cloud(st) and not self.konfig.cloud_herunterladen
        if alt and alt[1] == st.st_size and alt[2] == st.st_mtime_ns and not (alt[3] == "cloud" and not nur_cloud):
            if prio < alt[4]:
                self.con.execute("UPDATE dokumente SET prioritaet = ? WHERE id = ?", (prio, alt[0]))
                alt[4] = prio
                self.aenderungen += 1
            self.stat["unveraendert"] += 1
            return
        typ, fmt = TYP[ext]
        basis = {"pfad": pfad, "datei": pfad, "name": e.name, "ordner": os.path.dirname(pfad), "typ": typ,
                 "format": fmt, "groesse": st.st_size, "mtime_ns": st.st_mtime_ns, "datum": st.st_mtime,
                 "prioritaet": prio}
        if not alt:
            quelle, verschoben = self._signatur_quelle(e.name, key, st)
            if quelle is not None:
                self._uebernehmen(quelle, basis, verschoben)
                return
        self.stat["neu" if not alt else "geaendert"] += 1
        if nur_cloud:
            self._nur_name(basis, "cloud")
            return
        if st.st_size == 0:
            # Leere Datei: nichts zu lesen, aber auch kein Fehler (frueher "Öffnen fehlgeschlagen")
            self._nur_name(basis, "leer")
            return
        if st.st_size > self.konfig.max_dateigroesse:
            self._nur_name(basis, "zu_gross")
            return
        if fmt == "pdf":
            a = Auftrag("datei", extract.pdf_text, (pfad, self.ocr["min_zeichen"], self.konfig.gerade_vormerken(pfad)),
                        {"pfad": pfad, "basis": basis}, zeitlimit=300 + st.st_size / 1_000_000 * 5)
        elif fmt in OFFICE:
            a = Auftrag("datei", office.office_text, (pfad, fmt), {"pfad": pfad, "basis": basis},
                        zeitlimit=300 + st.st_size / 1_000_000 * 10)
        elif fmt == "md":
            a = Auftrag("datei", extract.md_text, (pfad,), {"pfad": pfad, "basis": basis}, zeitlimit=120)
        elif fmt == "eml":
            a = Auftrag("datei", extract.eml_text, (pfad,), {"pfad": pfad, "basis": basis}, zeitlimit=120)
        else:
            a = Auftrag("datei", extract.msg_text, (pfad,), {"pfad": pfad, "basis": basis}, zeitlimit=120)
        self._einreichen(a)

    def _signatur_quelle(self, name: str, key: str, st: os.stat_result) -> tuple[str | None, bool]:
        """Bekannte Datei mit gleicher Groesse und Aenderungszeit: ``(pfad, verschoben)`` oder ``(None, False)``.

        Bevorzugt den gleichen Namen und darunter eine Datei, die nicht mehr da ist
        (verschoben bzw. umbenannt); sonst gilt die neue Datei als Kopie.
        """
        kandidaten = [q for q in self.signatur.get((st.st_size, st.st_mtime_ns), [])
                      if q != key and q in self.bekannt and self.bekannt[q][3] not in ("cloud", "fehler")]
        if not kandidaten:
            return None, False
        gleicher_name = [q for q in kandidaten if os.path.basename(q) == name.lower()]
        reihe = gleicher_name or kandidaten
        weg = [q for q in reihe if q not in self.gesehen and not os.path.exists(q)]
        if weg:
            return weg[0], True
        return reihe[0], False

    def _cloud_platzhalter(self, e: os.DirEntry, prio: int) -> None:
        """iCloud-Platzhalter ``.Name.pdf.icloud``: die echte Datei nur mit Namen aufnehmen (Status ``cloud``).

        Ist die Datei schon mit Text im Index (sie wurde nach dem Lesen in die
        Cloud ausgelagert), bleibt der Eintrag unveraendert erhalten.
        """
        echt = plattform.icloud_platzhalter(e.name)
        if not echt:
            return
        ext = os.path.splitext(echt)[1].lower()
        if ext not in self.konfig.endungen or ext not in TYP:
            return
        pfad = os.path.join(os.path.dirname(e.path), echt)
        key = pfad.lower()
        self.gesehen.add(key)
        st = e.stat(follow_symlinks=False)
        alt = self.bekannt.get(key)
        if alt and (alt[3] != "cloud" or (alt[1] == st.st_size and alt[2] == st.st_mtime_ns)):
            self.stat["unveraendert"] += 1
            return
        typ, fmt = TYP[ext]
        basis = {"pfad": pfad, "datei": pfad, "name": echt, "ordner": os.path.dirname(pfad), "typ": typ,
                 "format": fmt, "groesse": st.st_size, "mtime_ns": st.st_mtime_ns, "datum": st.st_mtime,
                 "prioritaet": prio}
        self.stat["neu" if not alt else "geaendert"] += 1
        self._nur_name(basis, "cloud")

    def _nur_name(self, basis: dict, status: str) -> None:
        dok_id = db.speichere(self.con, {**basis, "seiten": None, "textstatus": status}, [])
        alt_quelle = (self.bekannt.get(basis["pfad"].lower()) or [None] * 6)[5]
        self.bekannt[basis["pfad"].lower()] = [dok_id, basis["groesse"], basis["mtime_ns"], status,
                                               basis["prioritaet"], alt_quelle]
        self.stat[status] += 1
        self.aenderungen += 1

    def _bleibt(self, key: str, v: list) -> bool:
        """Von PDFSM verwaltete Dokumente (Quelle 'pdfsm') werden nie entfernt, solange die Datei existiert."""
        return v[5] == "pdfsm" and os.path.exists(key)

    def _aufraeumen(self, wurzel: str) -> None:
        """Eintraege entfernen, deren Datei unter ``wurzel`` nicht mehr existiert."""
        w = wurzel.lower().rstrip(os.sep) + os.sep
        weg = [(k, v[0]) for k, v in self.bekannt.items()
               if k.startswith(w) and k not in self.gesehen and not self._bleibt(k, v)]
        if weg:
            db.loesche(self.con, [i for _, i in weg])
            for k, _ in weg:
                del self.bekannt[k]
            self.stat["entfernt"] += len(weg)
            log.info("%d nicht mehr vorhandene Dateien unter %s entfernt", len(weg), wurzel)
            self.aenderungen += 1

    def _aufraeumen_ausserhalb(self) -> None:
        """Nach einem vollstaendigen Lauf: Eintraege loeschen, die ausserhalb aller Wurzeln und
        Vorrang-Ordner liegen (z. B. nach Aenderung der Konfiguration oder frueheren
        ``--nur-pfad``-Laeufen); bisher blieben sie fuer immer stehen. Ohne konfigurierte
        Ordner passiert nichts. Mails (mbox) verwaltet ``_mails`` selbst.
        """
        wurzeln = [os.path.normpath(w).lower().rstrip(os.sep) + os.sep
                   for w in (*self.konfig.prioritaet, *self.konfig.wurzeln)]
        if not wurzeln:
            return
        weg = [(k, v[0]) for k, v in self.bekannt.items()
               if not any(k.startswith(w) for w in wurzeln) and not self._bleibt(k, v)]
        if weg:
            db.loesche(self.con, [i for _, i in weg])
            for k, _ in weg:
                del self.bekannt[k]
            self.stat["entfernt"] += len(weg)
            log.info("%d Eintraege ausserhalb der konfigurierten Ordner entfernt", len(weg))
            self.aenderungen += 1

    # ---------------------------------------------------------------- OCR
    def _ocr(self, praefix: str | None = None) -> None:
        if not self.ocr["aktiv"]:
            if self.konfig.ocr_aktiv:
                log.warning("Texterkennung übersprungen: %s", self.ocr["grund"])
            return
        sql = "SELECT id, datei FROM dokumente WHERE textstatus = 'ocr_ausstehend'"
        args: list = []
        if praefix:
            sql += " AND datei LIKE ? ESCAPE '|'"
            args.append(praefix.replace("|", "||").replace("%", "|%").replace("_", "|_").rstrip(os.sep) + os.sep + "%")
        sql += " ORDER BY prioritaet, datum DESC"
        dokumente = self.con.execute(sql, args).fetchall()
        if not dokumente:
            return
        log.info("OCR für %d Dokumente%s", len(dokumente), f" in {praefix}" if praefix else "")
        maxs = self.ocr["max_seiten"]
        for d in dokumente:
            seiten = [r[0] for r in self.con.execute(
                "SELECT seite FROM seiten WHERE dok_id = ? AND quelle = 'ohne_text' ORDER BY seite", (d["id"],))]
            if not seiten:
                self._ocr_status(d["id"], None)
                continue
            if maxs and len(seiten) > maxs:
                self.con.execute("UPDATE dokumente SET textstatus = 'zu_gross', fehler = ? WHERE id = ?",
                                 (f"{len(seiten)} Bildseiten – OCR-Grenze {maxs}", d["id"]))
                self.aenderungen += 1
                continue
            if not os.path.exists(d["datei"]):
                continue
            cfg = dict(self.ocr, textebene=True) if self._ebene_erzeugen(d["id"], d["datei"]) else self.ocr
            for k in range(0, len(seiten), OCR_STUECK):
                teil = seiten[k:k + OCR_STUECK]
                self._einreichen(Auftrag("ocr", extract.pdf_ocr, (d["datei"], teil, cfg),
                                         {"pfad": d["datei"], "dok_id": d["id"], "seiten": teil},
                                         zeitlimit=120 + 180 * len(teil)))
        self._abarbeiten()

    def _ebene_erzeugen(self, dok_id: int, datei: str) -> bool:
        """Soll die OCR dieses Dokuments die Textebene mitliefern?

        Ja bei Stufe ``alle``, bei ``neue_scans`` fuer Dateien im ersten
        Vorrang-Ordner - und fuer Dokumente, deren erste Seiten schon mit
        Textebene erkannt wurden (der PDF-Analyzer erkennt nur die ersten Seiten,
        danach wird die Datei womoeglich aus dem Vorrang-Ordner wegsortiert).
        """
        if self.konfig.textebene == "aus":
            return False
        return self.konfig.textebene_erzeugen(datei) or textebene.hat_ebenen(self.con, dok_id)

    # ---------------------------------------------------------------- Textebene (Phase 5b)
    def _stand_nachziehen(self, pfad: str, groesse: int, mtime_ns: int) -> None:
        """Nach dem Schreiben: Groesse/Aenderungszeit in ``bekannt`` und der Signatur fuer Verschiebungen."""
        k = pfad.lower()
        alt = self.bekannt.get(k)
        if alt is None:
            return
        pfade = self.signatur.get((alt[1], alt[2]))
        if pfade and k in pfade:
            pfade.remove(k)
        alt[1], alt[2] = groesse, mtime_ns
        self.signatur.setdefault((groesse, mtime_ns), []).append(k)

    def _schreiben_an(self) -> bool:
        """Darf der Lauf PDFs aendern (Textebene, automatisches Drehen #151 oder Ausrichten #165)?"""
        return self.konfig.textebene != "aus" or self.konfig.auto_drehen != "aus" or self.konfig.auto_gerade != "aus"

    def _textebene(self, altbestand: bool = False) -> None:
        """Textebene in die PDFs schreiben: aus dem OCR-Cache bzw. (Altbestand) mit erneuter Texterkennung.

        Im selben Schritt dreht der Lauf Seiten, deren Drehung die OCR
        vorgemerkt hat (Issue #151), und richtet schief gescannte Seiten
        gerade aus (Issue #165), auch wenn die Textebene aus ist. Haelt der
        Nutzer den Lauf an oder ist die Zeit um, werden die laufenden Auftraege
        noch fertig geschrieben (keine halben Dateien, keine liegen gebliebenen
        temporaeren Dateien); der naechste Lauf setzt fort.
        """
        ebene = self.konfig.textebene != "aus"
        drehen = self.konfig.auto_drehen != "aus"
        gerade = self.konfig.auto_gerade != "aus"
        if not ebene and (altbestand or not (drehen or gerade)):
            return
        ocr = self.ocr if self.ocr["aktiv"] else None
        if altbestand and ocr is None:
            log.warning("Textebene für den Altbestand übersprungen: %s", self.ocr["grund"])
            return
        zeilen = (textebene.altbestand(self.con) if altbestand
                  else textebene.offene(self.con, ebene=ebene, drehen=drehen, gerade=gerade))
        if zeilen:
            log.info("Textebene: %d Dateien%s", len(zeilen), " (Altbestand)" if altbestand else "")
            self.stat["textebene_dateien"] += len(zeilen)
        for d in zeilen:
            if (self.ende_zeit and time.monotonic() > self.ende_zeit) or self._anhalten_angefordert():
                self._abarbeiten()
                raise Abbruch("angehalten" if anhalten_datei(self.konfig).exists() else tr("Zeitlimit erreicht"))
            a = textebene.auftrag(self.con, d, self.konfig, ocr, altbestand=altbestand)
            if a is None:
                self.aenderungen += 1
                continue
            nachholen = sum(1 for v in a["seiten"].values() if v["ebene"] is None)
            self._einreichen(Auftrag("textebene", textebene.datei_schreiben, (a,),
                                     {"pfad": d["datei"], "dok_id": d["id"]},
                                     zeitlimit=120 + 10 * (len(a["seiten"]) + len(a["drehen"]) + len(a["gerade"]))
                                     + 180 * nachholen))
        self._abarbeiten()
        if not altbestand:
            weg = textebene.aufraeumen(self.con, self.konfig)
            if weg["sicherungen"]:
                log.info("Textebene: %d abgelaufene Sicherungskopien gelöscht", weg["sicherungen"])
        self._commit_wenn_noetig(sofort=True)

    def _ocr_cache_ergaenzen(self) -> None:
        """Bild-Hashes fuer vorhandene OCR-Seiten ohne Hash nachtragen und ihre Texte in den Cache legen.

        Idempotent; danach ueberleben auch die OCR-Texte des Altbestands
        Umbenennen, Verschieben, XMP-Schreiben, Stapeln und Teilen.
        """
        zeilen = self.con.execute(
            """SELECT d.id, d.datei, s.seite FROM seiten s JOIN dokumente d ON d.id = s.dok_id
               WHERE d.typ = 'pdf' AND s.quelle = 'ocr' AND s.bild_hash IS NULL ORDER BY d.id, s.seite""").fetchall()
        if not zeilen:
            return
        je_dok: dict[int, tuple[str, list[int]]] = {}
        for r in zeilen:
            je_dok.setdefault(r["id"], (r["datei"], []))[1].append(r["seite"])
        log.info("OCR-Cache ergänzen: %d Dokumente", len(je_dok))
        for dok_id, (datei, seiten) in je_dok.items():
            if not os.path.exists(datei):
                continue
            self._einreichen(Auftrag("hash", extract.pdf_bild_hashes, (datei, seiten),
                                     {"pfad": datei, "dok_id": dok_id, "seiten": seiten},
                                     zeitlimit=120 + len(seiten)))
        self._abarbeiten()

    # ---------------------------------------------------------------- Mails
    def _mails(self) -> None:
        gefunden: set[str] = set()
        erreichbar = False
        stand = {r["datei"].lower(): dict(r) for r in self.con.execute("SELECT * FROM mbox_stand")}
        ordner = self.konfig.mail_ordner_effektiv()
        if not ordner:
            log.warning("Keine Postfach-Ordner eingestellt und kein Thunderbird-Profil gefunden")
        for wurzel in ordner:
            if not os.path.isdir(wurzel):
                log.warning("Mailordner nicht gefunden: %s", wurzel)
                continue
            erreichbar = True
            for pfad, postfach in mbox.postfaecher(wurzel):
                gefunden.add(pfad.lower())
                try:
                    st = os.stat(pfad)
                except OSError:
                    continue
                alt = stand.get(pfad.lower())
                if alt and alt["groesse"] == st.st_size:
                    continue  # nur Markierungen geaendert (gelesen/ungelesen)
                start = 0
                if alt and st.st_size > alt["groesse"] and mbox.anfang_passt(pfad, alt["groesse"]):
                    start = alt["groesse"]
                else:
                    ids = [r[0] for r in self.con.execute(
                        "SELECT id FROM dokumente WHERE datei = ? AND format = 'mbox'", (pfad,))]
                    if ids:
                        db.loesche(self.con, ids)
                        self.aenderungen += 1
                log.info("Mails: %s (%s MB%s)", postfach, round((st.st_size - start) / 1e6, 1),
                         ", nur neue" if start else "")
                stapel, groesse = [], 0
                # Lauf-Zustand dieses Postfachs fuer die Zwischenstaende (_mbox_stapel_fertig)
                lauf = {"pfad": pfad, "postfach": postfach, "mtime_ns": st.st_mtime_ns, "stapel": [],
                        "stand": start, "geschrieben": start}
                for off, laenge, roh in mbox.mails(pfad, start):
                    stapel.append((off, laenge, roh))
                    groesse += len(roh)
                    if len(stapel) >= MBOX_STAPEL_MAILS or groesse >= MBOX_STAPEL_BYTES:
                        self._mbox_einreichen(lauf, stapel)
                        stapel, groesse = [], 0
                if stapel:
                    self._mbox_einreichen(lauf, stapel)
                self._abarbeiten()
                self.con.execute("INSERT OR REPLACE INTO mbox_stand VALUES (?, ?, ?)", (pfad, st.st_size, st.st_mtime_ns))
                self._commit_wenn_noetig(sofort=True)
        if erreichbar:
            weg = [k for k in stand if k not in gefunden]
            for k in weg:
                ids = [r[0] for r in self.con.execute(
                    "SELECT id FROM dokumente WHERE datei = ? AND format = 'mbox'", (stand[k]["datei"],))]
                db.loesche(self.con, ids)
                self.con.execute("DELETE FROM mbox_stand WHERE datei = ?", (stand[k]["datei"],))
                self.stat["entfernt"] += len(ids)
            self._commit_wenn_noetig(sofort=True)

    def _mbox_einreichen(self, lauf: dict, stapel: list) -> None:
        """Einen Stapel Mails eines Postfachs an die Arbeitsprozesse geben; Offsets fuer den Zwischenstand merken."""
        info = {"pfad": lauf["pfad"], "postfach": lauf["postfach"], "lauf": lauf, "fertig": False,
                "von": stapel[0][0], "bis": stapel[-1][0] + stapel[-1][1]}
        lauf["stapel"].append(info)
        self._einreichen(Auftrag("mbox", extract.mbox_stapel, (stapel,), info, zeitlimit=600))

    # ---------------------------------------------------------------- Ablauf
    def lauf(self, nur_prioritaet: bool = False, ohne_ocr: bool = False, ohne_mail: bool = False,
             nur_pfad: str | None = None, nur_textebene: bool = False) -> int:
        """Ein Lauf; ``nur_textebene``: nur die Phasen der Textebene (``pdfsm-dienst textebene schreiben``)."""
        if not sperre_holen(self.konfig):
            log.info("Ein anderer Indexierungslauf ist bereits aktiv – Ende.")
            self.con.close()
            return 2
        plattform.kinder_an_mich_binden()
        if self.hintergrund:
            plattform.niedrige_prioritaet_setzen()
        self.con.execute("UPDATE laeufe SET status = 'abgebrochen', ende = coalesce(ende, ?) WHERE status = 'laeuft'",
                         (db.jetzt(),))
        self.lauf_id = self.con.execute("INSERT INTO laeufe (beginn, status) VALUES (?, 'laeuft')",
                                        (db.jetzt(),)).lastrowid
        self.con.commit()
        try:
            anhalten_datei(self.konfig).unlink(missing_ok=True)   # alte Bitte eines frueheren Laufs
        except OSError:
            pass
        t0 = time.monotonic()
        status = "fertig"
        try:
            self._bekannte_laden()
            erledigt: set[str] = set()
            if nur_textebene:
                self._phase(tr("Textebene schreiben"))
                self._textebene()
                if self.konfig.textebene == "alle":
                    self._phase(tr("Textebene Altbestand"))
                    self._textebene(altbestand=True)
            elif nur_pfad:
                p = os.path.normpath(nur_pfad)
                self._phase(tr("Ordner {p}").format(p=p))
                if self._durchlaufen(p, 9, set()):
                    self._abarbeiten()
                    self._aufraeumen(p)
                if not ohne_ocr:
                    self._phase(tr("Texterkennung (OCR)"))
                    self._ocr(p)
                if self._schreiben_an():
                    self._phase(tr("Textebene schreiben"))
                    self._textebene()
            else:
                for prio, wurzel in enumerate(self.konfig.prioritaet):
                    self._phase(tr("Vorrang {0}: {wurzel}").format(prio + 1, wurzel=wurzel))
                    if self._durchlaufen(wurzel, prio, erledigt):
                        self._abarbeiten()
                        self._aufraeumen(wurzel)
                    erledigt.add(wurzel.lower())
                    if prio == 0 and not ohne_ocr:
                        self._phase(tr("OCR neue Scans: {wurzel}").format(wurzel=wurzel))
                        self._ocr(wurzel)
                if not nur_prioritaet:
                    for wurzel in self.konfig.wurzeln:
                        self._phase(tr("Ordner {wurzel}").format(wurzel=wurzel))
                        if self._durchlaufen(wurzel, 9, erledigt):
                            self._abarbeiten()
                            self._aufraeumen(wurzel)
                    self._abarbeiten()
                    self._aufraeumen_ausserhalb()
                    if not ohne_mail and self.konfig.mails_aktiv:
                        self._phase(tr("Thunderbird-Mails"))
                        self._mails()
                if not ohne_ocr:
                    self._phase(tr("Texterkennung (OCR)"))
                    self._ocr()
                    if not nur_prioritaet:
                        self._phase(tr("OCR-Cache ergänzen"))
                        self._ocr_cache_ergaenzen()
                if self._schreiben_an():
                    self._phase(tr("Textebene schreiben"))
                    self._textebene()
                    if self.konfig.textebene == "alle" and not nur_prioritaet and not ohne_ocr:
                        self._phase(tr("Textebene Altbestand"))
                        self._textebene(altbestand=True)
            self._abarbeiten()
        except (KeyboardInterrupt, Abbruch) as e:
            status = "abgebrochen"
            log.info("Abgebrochen: %s", e or "Strg+C")
        except Exception:
            status = "fehler"
            log.exception("Unerwarteter Fehler")
        finally:
            self._pool_beenden()
            self.phase = "Ende" if status == "fertig" else status
            self.stat["dauer_s"] = round(time.monotonic() - t0)
            try:
                self.con.execute("UPDATE laeufe SET ende = ?, status = ?, phase = ?, statistik = ? WHERE id = ?",
                                 (db.jetzt(), status, self.phase, json.dumps(dict(self.stat)), self.lauf_id))
                self._commit_wenn_noetig(sofort=True)
                if status == "fertig":
                    if not (nur_prioritaet or nur_pfad or nur_textebene):
                        db.setze_meta(self.con, VOLLER_LAUF_META, db.jetzt())
                    self.con.execute("PRAGMA optimize")
                    if self.stat["gelesen"] + self.stat["mails"] > 5000:
                        self.con.execute("INSERT INTO seiten_fts(seiten_fts) VALUES ('optimize')")
                    self.con.commit()
            except Exception:
                log.exception("Abschluss fehlgeschlagen")
            self.con.close()
            try:
                anhalten_datei(self.konfig).unlink(missing_ok=True)
            except OSError:
                pass
            sperre_freigeben()
            log.info("Lauf %s nach %s s: %s", status, self.stat["dauer_s"], dict(self.stat))
        return 0 if status == "fertig" else 1

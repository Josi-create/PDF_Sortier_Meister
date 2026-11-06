"""Indexierungslauf der Dokumentensuche: Dateien finden, Text gewinnen, OCR, Mails, Aufraeumen.

Uebernommen aus PDFsuche (``indexer.py``; Klasse ``Lauf`` heisst jetzt ``Indexer``).
Laeuft im Dienstprozess (``pdfsm-dienst index``); die Oberflaeche startet ihn nie
im eigenen Prozess. Plattformabhaengiges (Sperre, Job-Objekt bzw. Prozessgruppe,
Hintergrundprioritaet, Cloud-Platzhalter, Leerlaufzeit) liegt in ``plattform.py``.

Ablauf eines Laufs: Vorrang-Ordner (im ersten sofort OCR) -> Wurzeln -> Mails ->
restliche OCR. Unveraenderte Dateien (Groesse + mtime_ns) werden uebersprungen,
verschobene oder kopierte Dateien uebernehmen den vorhandenen Text samt OCR,
Aufraeumen nur nach vollstaendig durchlaufener Wurzel.
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

from src.search import db, extract, mbox, office, plattform
from src.search.konfig import SearchConfig

log = logging.getLogger("pdf_sortier_meister.suche")

TYP = {".pdf": ("pdf", "pdf"), ".md": ("md", "md"), ".eml": ("mail", "eml"), ".msg": ("mail", "msg"),
       ".docx": ("office", "docx"), ".docm": ("office", "docm"), ".xlsx": ("office", "xlsx"),
       ".xlsm": ("office", "xlsm"), ".odt": ("office", "odt"),
       ".doc": ("office", "doc"), ".xls": ("office", "xls")}
OFFICE = {"docx", "docm", "xlsx", "xlsm", "odt", "doc", "xls"}
OCR_STUECK = 8            # Seiten je OCR-Auftrag
MBOX_STAPEL_MAILS = 200
MBOX_STAPEL_BYTES = 24 * 1024 * 1024
LEERLAUF_PRUEFEN_S = 30       # nur_leerlauf: so oft wird die Leerlaufzeit abgefragt ...
LEERLAUF_MIN_S = 60           # ... und so lange muss der Nutzer untaetig sein, damit der Lauf (weiter)arbeitet
LEERLAUF_PAUSE_S = 10         # Wartezeit zwischen zwei Pruefungen waehrend einer Pause


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
                self._fehlgeschlagen(a, "Zeitüberschreitung")
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
            self._fehlgeschlagen(a, "Absturz beim Lesen (Datei beschädigt?)")
            return
        except TimeoutError:
            self._pool_beenden()
            self._fehlgeschlagen(a, "Zeitüberschreitung")
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
        self.aenderungen += 1

    # ---------------------------------------------------------------- Ergebnisse
    def _ergebnis(self, a: Auftrag, res) -> None:
        i = a.info
        if a.art == "datei":
            basis = i["basis"]
            fmt = basis["format"]
            if fmt == "pdf":
                dok = {**basis, "seiten": res["anzahl"], "textstatus": res["status"], "fehler": res["fehler"],
                       "titel": res["titel"], "autor": res["autor"]}
                seiten = res["seiten"]
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
            dok_id = db.speichere(self.con, dok, seiten)
            self.bekannt[basis["pfad"].lower()] = [dok_id, basis["groesse"], basis["mtime_ns"], dok["textstatus"], basis["prioritaet"]]
            self.stat["gelesen"] += 1
            if dok["textstatus"] == "ocr_ausstehend":
                self.stat["ocr_vorgemerkt"] += 1
            if dok["textstatus"] == "fehler":
                self.stat["fehler"] += 1
                log.info("Fehler: %s – %s", basis["pfad"], dok["fehler"])
        elif a.art == "ocr":
            dok_id = i["dok_id"]
            werte, fehl = [], []
            for s, t in res["texte"].items():
                (werte if t is not None else fehl).append((t, dok_id, s) if t is not None else (dok_id, s))
            self.con.executemany(
                "UPDATE seiten SET text = ?, quelle = 'ocr' WHERE dok_id = ? AND seite = ?", werte)
            ohne = [s for s in i["seiten"] if s not in res["texte"]]
            self.con.executemany(
                "UPDATE seiten SET quelle = 'ocr_fehler' WHERE dok_id = ? AND seite = ?",
                fehl + [(dok_id, s) for s in ohne])
            self.stat["ocr_seiten"] += len(werte)
            self._ocr_status(dok_id, res.get("fehler"))
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
        r = self.con.execute(
            """SELECT sum(quelle = 'ohne_text') rest, sum(quelle = 'ocr') ocr, sum(quelle = 'ocr_fehler') fehl
               FROM seiten WHERE dok_id = ?""", (dok_id,)).fetchone()
        if r["rest"]:
            status = "ocr_ausstehend"
        elif r["fehl"]:
            status = "ocr_teilweise"
        else:
            status = "ocr"
        self.con.execute("UPDATE dokumente SET textstatus = ?, ocr_seiten = ?, fehler = coalesce(?, fehler) WHERE id = ?",
                         (status, r["ocr"] or 0, fehler, dok_id))
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
        return (f"{self.phase} – gelesen {s['gelesen']}, unverändert {s['unveraendert']}, Mails {s['mails']}, "
                f"OCR-Seiten {s['ocr_seiten']}, Fehler {s['fehler']}")

    def _zeit_pruefen(self) -> None:
        if self.ende_zeit and time.monotonic() > self.ende_zeit:
            raise Abbruch("Zeitlimit erreicht")
        self._leerlauf_warten()

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
        self._phase(f"{vorher} – Pause (Nutzer aktiv)")
        while not self._leerlauf():
            if self.ende_zeit and time.monotonic() > self.ende_zeit:
                raise Abbruch("Zeitlimit erreicht")
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
            r["pfad"].lower(): [r["id"], r["groesse"], r["mtime_ns"], r["textstatus"], r["prioritaet"]]
            for r in self.con.execute(
                "SELECT id, pfad, groesse, mtime_ns, textstatus, prioritaet FROM dokumente WHERE format != 'mbox'")
        }
        # Signatur (Name, Groesse, Aenderungszeit) -> Pfad: erkennt verschobene/kopierte Dateien
        self.signatur = {(os.path.basename(k), v[1], v[2]): k for k, v in self.bekannt.items()}
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
            self.bekannt[basis["pfad"].lower()] = [alt[0], alt[1], alt[2], alt[3], basis["prioritaet"]]
            self.stat["verschoben"] += 1
        else:
            r = dict(self.con.execute("SELECT * FROM dokumente WHERE id = ?", (alt[0],)).fetchone())
            neu = {**r, **basis}
            neu.pop("id", None)
            dok_id = db.speichere(self.con, neu, [])
            self.con.execute("INSERT INTO seiten (dok_id, seite, quelle, text) "
                             "SELECT ?, seite, quelle, text FROM seiten WHERE dok_id = ?", (dok_id, alt[0]))
            self.bekannt[basis["pfad"].lower()] = [dok_id, alt[1], alt[2], alt[3], basis["prioritaet"]]
            self.stat["kopie"] += 1
        self.signatur[(basis["name"].lower(), basis["groesse"], basis["mtime_ns"])] = basis["pfad"].lower()
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
                            if ext in konfig.endungen and ext in TYP and not e.name.startswith("~$"):
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
            quelle = self.signatur.get((e.name.lower(), st.st_size, st.st_mtime_ns))
            if quelle and quelle in self.bekannt and quelle != key and self.bekannt[quelle][3] not in ("cloud", "fehler"):
                verschoben = quelle not in self.gesehen and not os.path.exists(quelle)
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
            a = Auftrag("datei", extract.pdf_text, (pfad, self.ocr["min_zeichen"]), {"pfad": pfad, "basis": basis},
                        zeitlimit=300 + st.st_size / 1_000_000 * 5)
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
        self.bekannt[basis["pfad"].lower()] = [dok_id, basis["groesse"], basis["mtime_ns"], status, basis["prioritaet"]]
        self.stat[status] += 1
        self.aenderungen += 1

    def _aufraeumen(self, wurzel: str) -> None:
        """Eintraege entfernen, deren Datei unter ``wurzel`` nicht mehr existiert."""
        w = wurzel.lower().rstrip(os.sep) + os.sep
        weg = [(k, v[0]) for k, v in self.bekannt.items() if k.startswith(w) and k not in self.gesehen]
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
        weg = [(k, v[0]) for k, v in self.bekannt.items() if not any(k.startswith(w) for w in wurzeln)]
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
            for k in range(0, len(seiten), OCR_STUECK):
                teil = seiten[k:k + OCR_STUECK]
                self._einreichen(Auftrag("ocr", extract.pdf_ocr, (d["datei"], teil, self.ocr),
                                         {"pfad": d["datei"], "dok_id": d["id"], "seiten": teil},
                                         zeitlimit=120 + 180 * len(teil)))
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
             nur_pfad: str | None = None) -> int:
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
        t0 = time.monotonic()
        status = "fertig"
        try:
            self._bekannte_laden()
            erledigt: set[str] = set()
            if nur_pfad:
                p = os.path.normpath(nur_pfad)
                self._phase(f"Ordner {p}")
                if self._durchlaufen(p, 9, set()):
                    self._abarbeiten()
                    self._aufraeumen(p)
                if not ohne_ocr:
                    self._phase("Texterkennung (OCR)")
                    self._ocr(p)
            else:
                for prio, wurzel in enumerate(self.konfig.prioritaet):
                    self._phase(f"Vorrang {prio + 1}: {wurzel}")
                    if self._durchlaufen(wurzel, prio, erledigt):
                        self._abarbeiten()
                        self._aufraeumen(wurzel)
                    erledigt.add(wurzel.lower())
                    if prio == 0 and not ohne_ocr:
                        self._phase(f"OCR neue Scans: {wurzel}")
                        self._ocr(wurzel)
                if not nur_prioritaet:
                    for wurzel in self.konfig.wurzeln:
                        self._phase(f"Ordner {wurzel}")
                        if self._durchlaufen(wurzel, 9, erledigt):
                            self._abarbeiten()
                            self._aufraeumen(wurzel)
                    self._abarbeiten()
                    self._aufraeumen_ausserhalb()
                    if not ohne_mail and self.konfig.mails_aktiv:
                        self._phase("Thunderbird-Mails")
                        self._mails()
                if not ohne_ocr:
                    self._phase("Texterkennung (OCR)")
                    self._ocr()
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
                    self.con.execute("PRAGMA optimize")
                    if self.stat["gelesen"] + self.stat["mails"] > 5000:
                        self.con.execute("INSERT INTO seiten_fts(seiten_fts) VALUES ('optimize')")
                    self.con.commit()
            except Exception:
                log.exception("Abschluss fehlgeschlagen")
            self.con.close()
            sperre_freigeben()
            log.info("Lauf %s nach %s s: %s", status, self.stat["dauer_s"], dict(self.stat))
        return 0 if status == "fertig" else 1

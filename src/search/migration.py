"""Uebernahme einer vorhandenen PDFsuche-Einrichtung (Qt-frei).

Abschnitt 7 von ``docs/SUCHE_ARCHITEKTUR.md``: Wer das fruehere, eigenstaendige
Programm PDFsuche benutzt hat, uebernimmt Einstellungen (``config.toml``) und
Datenbank. Die Datenbank **bleibt am bisherigen Ort** - ``SearchConfig.db_pfad``
zeigt dorthin, die Sperrdatei liegt wie bisher daneben, es wird nichts kopiert.
Wer den alten Ordner loswerden will, kann die Datenbank wahlweise in das
Datenverzeichnis kopieren (``kopieren=True``, mit Pruefung der Kopie).

Ablauf: ``finde_pdfsuche()`` (Kandidaten ohne festen Pfad im Code) ->
``pruefen(ordner)`` (Vorschau: Einstellungen, Sperre, Integritaet, Zaehler) ->
``uebernehmen(...)`` (Einstellungen speichern, ``meta.migriert_von`` setzen,
PDFSM-Metadaten aus dem bisherigen Index mitnehmen).
Die alten Aufgaben der Aufgabenplanung werden hier nicht angefasst.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from src.search import db, plattform
from src.search.konfig import SearchConfig, lade_config_toml, norm_pfad
from src.utils.platform_paths import get_app_data_dir

AUFGABE_ALT = r"\PDFsuche\Indexierung"      # Windows-Aufgabe des alten Programms
KONFIG_DATEI = "config.toml"
DB_STANDARD_ALT = "data/pdfsuche.db"       # Standardpfad des alten Programms, relativ zum Projektordner
MCP_NAME = "pdfsuche"


@dataclass
class Uebernahme:
    """Ergebnis von ``pruefen``: alles, was Dialog und Kommandozeile vor der Uebernahme zeigen."""

    ordner: str
    konfig: SearchConfig | None = None
    db_pfad: str = ""
    db_vorhanden: bool = False
    laeuft: bool = False
    schema_version: str = ""
    integritaet: str = ""                      # "ok" oder der Befund von quick_check
    zaehler: dict = field(default_factory=dict)
    fehler: list[str] = field(default_factory=list)
    mitgenommen: int = 0                       # nach ``uebernehmen``: Dokumente mit PDFSM-Metadaten aus dem bisherigen Index

    @property
    def moeglich(self) -> bool:
        return not self.fehler and self.konfig is not None

    def zusammenfassung(self) -> str:
        """Mehrzeilige Vorschau fuer Dialog und ``pdfsm-dienst migration``."""
        z = [f"PDFsuche-Ordner: {self.ordner}"]
        k = self.konfig
        if k is not None:
            z.append(f"Datenbank: {self.db_pfad}" + ("" if self.db_vorhanden else "  (nicht gefunden)"))
            if self.zaehler:
                typen = ", ".join(f"{t}: {n}" for t, n in sorted(self.zaehler.get("pro_typ", {}).items()))
                z.append(f"Dokumente: {self.zaehler.get('dokumente', 0)}" + (f"  ({typen})" if typen else ""))
                z.append(f"Seiten: {self.zaehler.get('seiten', 0)}, davon per OCR erkannt: "
                         f"{self.zaehler.get('ocr_seiten', 0)}, OCR ausstehend: {self.zaehler.get('ocr_ausstehend_seiten', 0)}")
            if self.schema_version:
                z.append(f"Schema-Version: {self.schema_version}, Integrität: {self.integritaet or '–'}")
            z.append("Vorrang-Ordner: " + (", ".join(k.prioritaet) or "–"))
            z.append("Ordner/Laufwerke: " + (", ".join(k.wurzeln) or "–"))
            z.append("Mail-Ordner: " + (", ".join(k.mail_ordner) or "–"))
            z.append(f"Texterkennung: {'ein' if k.ocr_aktiv else 'aus'} ({k.ocr_sprachen})"
                     + (f", Tesseract: {k.ocr_tesseract}" if k.ocr_tesseract else ""))
            z.append(f"Ausschlüsse: {len(k.ordner_ausschliessen)} Ordnernamen, {len(k.pfade_ausschliessen)} Pfade; "
                     f"Endungen: {' '.join(sorted(k.endungen))}")
            z.append(f"Browser-Oberfläche: Port {k.web_port}; Arbeitsprozesse: {k.prozesse or 'automatisch'}")
        if self.laeuft:
            z.append("Achtung: Ein Indexierungslauf ist gerade aktiv.")
        for f in self.fehler:
            z.append(f"Fehler: {f}")
        return "\n".join(z)


# --------------------------------------------------------------------------- Finden

def ist_pdfsuche_ordner(pfad: str | Path | None) -> bool:
    """Projektordner des alten Programms: enthaelt ``config.toml``."""
    return bool(pfad) and (Path(pfad) / KONFIG_DATEI).is_file()


def finde_pdfsuche(claude_json: Path | str | None = None) -> list[str]:
    """Moegliche Projektordner einer vorhandenen PDFsuche, ohne festen Pfad im Code.

    1. Windows-Aufgabe ``\\PDFsuche\\Indexierung``: Arbeitsverzeichnis der Aktion.
    2. MCP-Eintrag ``pdfsuche`` in ``~/.claude.json``: die ``pdfsuche-mcp``-Binary
       liegt im ``.venv`` des Projekts.
    Sonst leer; der Nutzer waehlt den Ordner dann selbst.
    """
    gefunden: list[str] = []
    for quelle in (_aus_aufgabe, lambda: _aus_mcp(claude_json)):
        try:
            p = quelle()
        except Exception:  # Fremdprogramme/-dateien: jeder Fehler heisst nur "nicht gefunden"
            p = None
        if p and ist_pdfsuche_ordner(p):
            n = norm_pfad(p)
            if n.lower() not in {g.lower() for g in gefunden}:
                gefunden.append(n)
    return gefunden


def _aus_aufgabe() -> str | None:
    if sys.platform != "win32":
        return None
    r = subprocess.run(["schtasks", "/Query", "/TN", AUFGABE_ALT, "/XML"], capture_output=True, timeout=15,
                       **plattform.popen_flags())
    if r.returncode != 0 or not r.stdout:
        return None
    return arbeitsverzeichnis_aus_aufgabe(_dekodiere(r.stdout))


def _dekodiere(roh: bytes) -> str:
    if roh.startswith((b"\xff\xfe", b"\xfe\xff")):
        return roh.decode("utf-16", "replace")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return roh.decode(enc)
        except UnicodeDecodeError:
            continue
    return roh.decode("utf-8", "replace")


def arbeitsverzeichnis_aus_aufgabe(xml_text: str) -> str | None:
    """``WorkingDirectory`` der ersten Exec-Aktion aus ``schtasks /Query /XML``; sonst der Ordner des Kommandos."""
    try:
        wurzel = ET.fromstring(xml_text.strip())
    except ET.ParseError:
        return None
    for e in wurzel.iter():
        if e.tag.rsplit("}", 1)[-1] == "WorkingDirectory" and (e.text or "").strip():
            return e.text.strip().strip('"')
    for e in wurzel.iter():
        if e.tag.rsplit("}", 1)[-1] == "Command" and (e.text or "").strip():
            return _projektordner_zu(e.text.strip().strip('"'))
    return None


def _aus_mcp(claude_json: Path | str | None) -> str | None:
    pfad = Path(claude_json) if claude_json else Path.home() / ".claude.json"
    if not pfad.is_file():
        return None
    with open(pfad, encoding="utf-8") as f:
        daten = json.load(f)
    eintrag = (daten.get("mcpServers") or {}).get(MCP_NAME) or {}
    kommando = eintrag.get("command") or ""
    return _projektordner_zu(kommando) if kommando else None


def _projektordner_zu(kommando: str) -> str | None:
    """Vom Pfad einer Binary (``<Projekt>/.venv/Scripts/x.exe``) aufwaerts zum Ordner mit ``config.toml``."""
    p = Path(kommando)
    for eltern in list(p.parents)[:4]:
        if ist_pdfsuche_ordner(eltern):
            return str(eltern)
    return None


# --------------------------------------------------------------------------- Pruefen

def pruefen(ordner: str | Path) -> Uebernahme:
    """Einstellungen lesen, Datenbank am Ort pruefen (Sperre, ``quick_check``, Zaehler, Schema-Version)."""
    u = Uebernahme(ordner=norm_pfad(ordner))
    toml = Path(u.ordner) / KONFIG_DATEI
    if not toml.is_file():
        u.fehler.append(f"Keine {KONFIG_DATEI} in {u.ordner}")
        return u
    try:
        konfig = lade_config_toml(toml)
    except Exception as e:  # tomllib.TOMLDecodeError, OSError, ValueError
        u.fehler.append(f"{KONFIG_DATEI} nicht lesbar: {e}")
        return u
    db_pfad = Path(konfig.db_pfad or DB_STANDARD_ALT)
    if not db_pfad.is_absolute():
        db_pfad = Path(u.ordner) / db_pfad
    konfig.db_pfad = norm_pfad(str(db_pfad))
    konfig.aktiv = True
    u.konfig = konfig
    u.db_pfad = konfig.db_pfad
    u.db_vorhanden = db_pfad.is_file()
    if not u.db_vorhanden:
        u.fehler.append(f"Datenbank nicht gefunden: {u.db_pfad}")
        return u
    from src.search.indexer import laeuft_gerade

    u.laeuft = laeuft_gerade(konfig)
    if u.laeuft:
        u.fehler.append("Ein Indexierungslauf ist gerade aktiv – bitte warten, bis er beendet ist.")
        return u
    try:
        con = db.verbinde(db_pfad, nur_lesen=True)
        try:
            u.schema_version = str(db.lies_meta(con, "schema_version", "") or "")
            befund = con.execute("PRAGMA quick_check").fetchone()[0]
            u.integritaet = "ok" if befund == "ok" else str(befund)
            st = db.status(con)
            u.zaehler = {k: st.get(k) for k in ("dokumente", "seiten", "ocr_seiten", "ocr_ausstehend_seiten", "pro_typ")}
        finally:
            con.close()
    except sqlite3.Error as e:
        u.fehler.append(f"Datenbank nicht lesbar: {e}")
        return u
    if u.integritaet != "ok":
        u.fehler.append(f"Integritätsprüfung fehlgeschlagen: {u.integritaet}")
    if u.schema_version not in ("1", "2"):
        u.fehler.append(f"Unbekannte Schema-Version {u.schema_version!r} (erwartet 1 oder 2)")
    return u


# --------------------------------------------------------------------------- Uebernehmen

def uebernehmen(u: Uebernahme, config, kopieren: bool = False, fortschritt=None) -> SearchConfig:
    """Einstellungen in die PDFSM-Konfiguration schreiben, ``meta.migriert_von/-am`` setzen.

    ``config`` ist die ``Config`` von PDF Sortier Meister (``set_search_config``).
    ``kopieren``: Datenbank zuerst in das Datenverzeichnis kopieren (siehe
    ``kopiere_db``); ``fortschritt(kopiert, gesamt)`` wird dabei aufgerufen.
    """
    if not u.moeglich:
        raise ValueError("; ".join(u.fehler) or "Prüfung fehlt")
    konfig = u.konfig
    assert konfig is not None
    bisher = get_app_data_dir() / "suche" / "suche.db"
    if kopieren:
        kopiere_db(u.db_pfad, bisher, fortschritt)
        konfig.db_pfad = ""                      # Standardort
    con = db.verbinde(konfig.db_datei)
    try:
        db.init(con)                             # Version 1 -> 2, additiv (Abschnitt 3.3), zusammen mit migriert_von
        db.setze_meta(con, "migriert_von", u.ordner)
        db.setze_meta(con, "migriert_am", db.jetzt())
        con.commit()
    finally:
        con.close()
    if not kopieren and bisher.is_file() and not _gleiche_datei(bisher, konfig.db_datei):
        u.mitgenommen = metadaten_mitnehmen(bisher, konfig)
    konfig.aktiv = True
    config.set_search_config(konfig)
    return konfig


def _gleiche_datei(a: Path, b: Path) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve() or os.path.samefile(a, b)
    except OSError:
        return False


def metadaten_mitnehmen(alt_db: str | Path, konfig: SearchConfig) -> int:
    """PDFSM-Metadaten aus einem bisherigen Index in den Index von ``konfig`` uebertragen.

    Bis zur Uebernahme schreibt PDF Sortier Meister Korrespondent, Steuerjahr,
    Betrag usw. in den Index am Standardort; nach der Uebernahme zeigt
    ``db_pfad`` auf die PDFsuche-Datenbank. Damit nichts verloren geht, kommen
    alle Dokumente mit Quelle ``'pdfsm'`` mit: Vorhandene erhalten die Werte
    (Vorrang vor Werten aus der PDF), fehlende werden wie in PDFSM als
    Platzhalter mit dem bisherigen Text angelegt (Status ``ausstehend``, der
    naechste Lauf liest sie). Der bisherige Index wird nur gelesen.
    Liefert die Zahl der uebertragenen Dokumente.
    """
    from src.search.suchindex import Suchindex

    alt = db.verbinde(alt_db, nur_lesen=True)
    try:
        if "metadaten_quelle" not in db._spalten(alt, "dokumente"):
            return 0
        felder = ", ".join(db.METADATEN_FELDER)
        zeilen = alt.execute(f"SELECT id, pfad, name, pdf_id, {felder} FROM dokumente "
                             "WHERE metadaten_quelle = 'pdfsm' ORDER BY id").fetchall()
        eintraege = []
        for z in zeilen:
            text = "\n\n".join(t for (t,) in alt.execute(
                "SELECT text FROM seiten WHERE dok_id = ? ORDER BY seite", (z["id"],)) if t)
            eintraege.append((z["pfad"], {f: z[f] for f in db.METADATEN_FELDER}, z["pdf_id"], text or None,
                              z["name"]))
    finally:
        alt.close()
    index = Suchindex(konfig)
    n = 0
    for pfad, werte, pdf_id, text, name in eintraege:
        if index.metadaten_setzen(pfad, werte, pdf_id=pdf_id, text=text, lesen=False, name=name):
            n += 1
    return n


def kopiere_db(quelle: str | Path, ziel: str | Path, fortschritt=None) -> None:
    """Datenbank ueber die SQLite-Sicherungsschnittstelle kopieren und die Kopie pruefen.

    Die Sicherungsschnittstelle liest Hauptdatei und WAL zusammen, ein
    vorheriger Checkpoint ist nicht noetig. Die Kopie entsteht als ``.teil``,
    wird mit ``quick_check`` und Dokumentzahl gegen die Quelle geprueft und erst
    dann an ihren Platz gelegt; bei jedem Fehler bleibt die Quelle unberuehrt.
    """
    quelle, ziel = Path(quelle), Path(ziel)
    if ziel.exists():
        raise FileExistsError(f"Ziel existiert schon: {ziel}")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    teil = ziel.with_name(ziel.name + ".teil")
    if teil.exists():
        teil.unlink()
    src = sqlite3.connect(quelle.resolve().as_uri() + "?mode=ro", uri=True, timeout=60)
    dst = sqlite3.connect(str(teil))
    try:
        def _melden(status, verbleibend, gesamt):
            if fortschritt:
                fortschritt(gesamt - verbleibend, gesamt)

        src.backup(dst, pages=512, progress=_melden)
        n_quelle = src.execute("SELECT count(*) FROM dokumente").fetchone()[0]
    finally:
        dst.close()
        src.close()
    try:
        kon = sqlite3.connect(teil.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            befund = kon.execute("PRAGMA quick_check").fetchone()[0]
            n_kopie = kon.execute("SELECT count(*) FROM dokumente").fetchone()[0]
        finally:
            kon.close()
        if befund != "ok" or n_kopie != n_quelle:
            raise RuntimeError(f"Kopie fehlerhaft (quick_check: {befund}, Dokumente {n_kopie} statt {n_quelle})")
    except Exception:
        teil.unlink(missing_ok=True)
        raise
    os.replace(teil, ziel)

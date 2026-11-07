"""Fassade der Dokumentensuche fuer Oberflaeche, Dienst, MCP und Web (Qt-frei).

``Suchindex`` kapselt den Datenbankpfad aus der ``SearchConfig``, oeffnet fuer
jeden Lesezugriff eine eigene Nur-Lese-Verbindung (deshalb aus jedem Thread
nutzbar) und bietet die kurzen Schreibmeldungen, mit denen die Oberflaeche
Umbenennen, Verschieben, Loeschen, Inhaltsaenderungen, eigene OCR-Ergebnisse
und PDFSM-Metadaten sofort an den Index meldet (Phase 5). Eine
Schreibverbindung bringt eine Version-1-Datenbank beim ersten Zugriff additiv
auf Version 2.

Indexlaeufe starten immer in einem eigenen Prozess (``pdfsm-dienst index``),
nie in-process: ``lauf_starten()``.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from src.search import db, plattform
from src.search.konfig import SearchConfig, norm_pfad

# Statuswerte, bei denen der Text im Index fuer den PDF-Analyzer reicht
TEXT_AUS_INDEX = ("text", "ocr", "leer", "ocr_teilweise")


class Suchindex:
    def __init__(self, konfig: SearchConfig) -> None:
        self.konfig = konfig
        self._schema_geprueft = False

    # ------------------------------------------------------------------ Zugang

    @property
    def db_datei(self) -> Path:
        return self.konfig.db_datei

    def vorhanden(self) -> bool:
        """Gibt es schon eine Datenbank? (Vor dem ersten Lauf: nein.)"""
        return self.db_datei.is_file()

    def _lesen(self):
        if not self.vorhanden():
            return None
        return db.verbinde(self.db_datei, nur_lesen=True)

    def _schreiben(self):
        """Schreibverbindung; eine Version-1-Datenbank wird dabei einmal je Instanz auf Version 2 ergaenzt."""
        con = db.verbinde(self.db_datei)
        if not self._schema_geprueft:
            db.init(con)
            self._schema_geprueft = True
        return con

    def unter_wurzel(self, pfad: str) -> bool:
        """Liegt die Datei unter einem Vorrang-Ordner oder einer Wurzel der Konfiguration?"""
        p = norm_pfad(pfad).lower()
        for w in (*self.konfig.prioritaet, *self.konfig.wurzeln):
            w = norm_pfad(w).lower().rstrip(os.sep) + os.sep
            if p.startswith(w):
                return True
        return False

    @staticmethod
    def _leer(abfrage: str = "") -> dict:
        return {"treffer": [], "gesamt": 0, "mehr": False, "abfrage": abfrage, "dauer_ms": 0}

    # ------------------------------------------------------------------ Lesen

    FILTER = ("typ", "ordner", "von", "bis", "steuerjahr", "kategorie", "korrespondent", "betrag_von", "betrag_bis",
              "pdf_id", "steuerjahr_von", "steuerjahr_bis")

    def suche(self, abfrage: str, **argumente) -> dict:
        """Volltextsuche; Argumente wie ``db.suche`` (typ, ordner, von, bis, sortierung, anzahl, start,
        steuerjahr, kategorie, korrespondent, betrag_von, betrag_bis, pdf_id, ...).

        Ohne Suchbegriff, aber mit Filtern, kommen alle passenden Dokumente.
        """
        abfrage = (abfrage or "").strip()
        if not abfrage and not any(argumente.get(k) not in (None, "", 0, 0.0) for k in self.FILTER):
            return self._leer()
        con = self._lesen()
        if con is None:
            return self._leer(abfrage)
        try:
            return db.suche(con, abfrage, **argumente)
        finally:
            con.close()

    def werte(self, feld: str, absteigend: bool = False) -> list[str]:
        """Vorkommende Werte eines Metadatenfelds (steuerjahr, kategorie, korrespondent, ...)."""
        con = self._lesen()
        if con is None:
            return []
        try:
            return db.werte(con, feld, absteigend)
        except Exception:
            return []
        finally:
            con.close()

    def top_werte(self, feld: str, limit: int = 10) -> list[str]:
        con = self._lesen()
        if con is None:
            return []
        try:
            return db.top_werte(con, feld, limit)
        except Exception:
            return []
        finally:
            con.close()

    def anzahl(self, typ: str | None = None) -> int:
        con = self._lesen()
        if con is None:
            return 0
        try:
            return db.anzahl(con, typ)
        finally:
            con.close()

    def dokumente_kurz(self, typ: str | None = "pdf", limit: int = 20000) -> list[dict]:
        """Dokumente ohne Volltext (Aehnlichkeitssuche von PDFSM): filename, file_path, keywords, korrespondent,
        steuerjahr, target_folder."""
        con = self._lesen()
        if con is None:
            return []
        try:
            sql = ("SELECT name, pfad, schlagwoerter, korrespondent, steuerjahr, ordner FROM dokumente"
                   + (" WHERE typ = ?" if typ else "") + " ORDER BY id LIMIT ?")
            args = (typ, int(limit)) if typ else (int(limit),)
            return [{"filename": r[0], "file_path": r[1], "keywords": r[2], "korrespondent": r[3],
                     "steuerjahr": r[4], "target_folder": r[5]} for r in con.execute(sql, args)]
        finally:
            con.close()

    def dokument(self, dok_id: int) -> dict | None:
        con = self._lesen()
        if con is None:
            return None
        try:
            return db.dokument(con, dok_id)
        finally:
            con.close()

    def dokument_nach_pfad(self, pfad: str) -> dict | None:
        con = self._lesen()
        if con is None:
            return None
        try:
            return db.dokument_nach_pfad(con, norm_pfad(pfad))
        finally:
            con.close()

    def seiten_text(self, dok_id: int, von: int | None = None, bis: int | None = None,
                    hervorheben: str | None = None) -> list[dict]:
        con = self._lesen()
        if con is None:
            return []
        try:
            return db.seiten_text(con, dok_id, von, bis, hervorheben)
        finally:
            con.close()

    def volltext(self, dok_id: int, max_zeichen: int = 0) -> str:
        con = self._lesen()
        if con is None:
            return ""
        try:
            return db.volltext(con, dok_id, max_zeichen)
        finally:
            con.close()

    def text_fuer_datei(self, pfad: str) -> dict | None:
        """Textstand einer Datei (siehe ``db.text_fuer_datei``); None, wenn unbekannt."""
        con = self._lesen()
        if con is None:
            return None
        try:
            return db.text_fuer_datei(con, norm_pfad(pfad))
        finally:
            con.close()

    def status(self) -> dict:
        """Indexstand; ohne Datenbank nur Nullwerte und ``vorhanden = False``."""
        con = self._lesen()
        if con is None:
            return {"vorhanden": False, "dokumente": 0, "pro_typ": {}, "pro_status": {}, "seiten": 0,
                    "ocr_seiten": 0, "ocr_ausstehend_seiten": 0, "laeufe": [], "fortschritt": "",
                    "schema_version": "", "laeuft": self.laeuft_gerade(), "db_groesse": 0,
                    "ocr_grund": self.konfig.ocr_einstellungen()["grund"]}
        try:
            st = db.status(con)
        finally:
            con.close()
        st["vorhanden"] = True
        st["laeuft"] = self.laeuft_gerade()
        st["ocr_grund"] = self.konfig.ocr_einstellungen()["grund"]  # None = Texterkennung einsatzbereit
        st["db_groesse"] = sum(
            os.path.getsize(p) for p in (str(self.db_datei), str(self.db_datei) + "-wal") if os.path.exists(p)
        )
        return st

    def laeuft_gerade(self) -> bool:
        from src.search.indexer import laeuft_gerade
        return laeuft_gerade(self.konfig)

    # ------------------------------------------------------------------ Mails

    @staticmethod
    def eml_dateiname(name: str) -> str:
        """Betreff als Dateiname (ohne verbotene Zeichen, hoechstens 80 Zeichen)."""
        s = "".join(c if c not in '<>:"/\\|?*\r\n\t' else "_" for c in (name or "mail"))
        return s.strip()[:80] or "mail"

    def mail_als_eml(self, dok: dict) -> Path:
        """Mail eines Treffers als Datei zum Oeffnen mit dem Mailprogramm.

        Eine Mail aus einer Thunderbird-mbox wird als ``.eml`` in den
        Temp-Ordner geschrieben (die mbox bleibt unberuehrt); eine ``.eml``-
        oder ``.msg``-Datei ist schon eine Datei und wird selbst geliefert.
        """
        if dok.get("format") != "mbox":
            return Path(dok["datei"])
        if "mbox_offset" not in dok or "mbox_laenge" not in dok:
            # Treffer aus ``suche()`` tragen nur die Kurzfassung; Lage in der mbox nachladen
            voll = self.dokument(int(dok["id"]))
            if not voll:
                raise OSError(f"Mail {dok['id']} ist nicht mehr im Index")
            dok = voll
        from src.search import mbox

        roh = mbox.mail_roh(dok["datei"], dok["mbox_offset"], dok["mbox_laenge"])
        ziel = Path(tempfile.gettempdir()) / "pdfsm_suche" / f"{dok['id']}_{self.eml_dateiname(dok['name'])}.eml"
        ziel.parent.mkdir(exist_ok=True)
        ziel.write_bytes(roh)
        return ziel

    # ------------------------------------------------------------------ Schreibmeldungen der Oberflaeche

    def datei_verschoben(self, alt: str, neu: str) -> bool:
        """Umbenennen oder Verschieben melden: der Eintrag behaelt Text, OCR und Metadaten, nur der Pfad aendert sich.

        Liefert True, wenn ein Eintrag angepasst wurde. Ein Eintrag, der unter dem
        neuen Pfad schon existierte (ueberschriebene Datei), wird entfernt.
        """
        if not self.vorhanden():
            return False
        alt, neu = norm_pfad(alt), norm_pfad(neu)
        if alt == neu:
            return False
        con = self._schreiben()
        try:
            r = con.execute("SELECT id FROM dokumente WHERE pfad = ? AND format != 'mbox'", (alt,)).fetchone()
            if not r:
                return False
            ziel = con.execute("SELECT id FROM dokumente WHERE pfad = ? AND id != ?", (neu, r[0])).fetchone()
            if ziel:
                db.loesche(con, [ziel[0]])
            con.execute(
                "UPDATE dokumente SET pfad = ?, datei = ?, name = ?, ordner = ?, indiziert_am = ? WHERE id = ?",
                (neu, neu, os.path.basename(neu), os.path.dirname(neu), db.jetzt(), r[0]),
            )
            con.commit()
            return True
        finally:
            con.close()

    def datei_geloescht(self, pfad: str) -> bool:
        """Loeschen melden; liefert True, wenn ein Eintrag entfernt wurde."""
        if not self.vorhanden():
            return False
        con = self._schreiben()
        try:
            r = con.execute("SELECT id FROM dokumente WHERE pfad = ? AND format != 'mbox'", (norm_pfad(pfad),)).fetchone()
            if not r:
                return False
            db.loesche(con, [r[0]])
            con.commit()
            return True
        finally:
            con.close()

    def datei_aufnehmen(self, pfad: str, prioritaet: int | None = None, erzwingen: bool = False,
                        vorab: dict | None = None) -> int | None:
        """Eine Datei sofort indizieren (Textebene; Bildseiten bleiben fuer den naechsten OCR-Lauf offen).

        Ohne ``erzwingen`` nur, wenn die Datei schon im Index ist oder unter einer
        Wurzel bzw. einem Vorrang-Ordner liegt (sonst wuerde die Oberflaeche Dateien
        aufnehmen, die der Nutzer nie zur Suche freigegeben hat). ``vorab`` ist ein
        fertiges Ergebnis von ``extract.pdf_text`` (PDF-Analyzer). Liefert die
        Dokument-Id oder None.
        """
        from src.search.indexer import einzeldatei_indizieren

        pfad = norm_pfad(pfad)
        if not os.path.isfile(pfad):
            return None
        if not erzwingen and not self.unter_wurzel(pfad) and self.dokument_nach_pfad(pfad) is None:
            return None
        con = self._schreiben()
        try:
            dok_id = einzeldatei_indizieren(con, self.konfig, pfad, prioritaet, vorab)
            con.commit()
            return dok_id
        finally:
            con.close()

    def datei_geaendert(self, pfad: str) -> int | None:
        """Inhalt hat sich geaendert (XMP-Metadaten, Stapeln, Teilen): Textebene neu lesen, OCR aus dem Cache.

        Bekannte Dateien werden immer neu gelesen, unbekannte nur unter einer Wurzel.
        """
        return self.datei_aufnehmen(pfad)

    def ocr_eintragen(self, pfad: str, texte: dict, ebenen: dict | None = None, ersetzen: bool = False,
                      drehungen: dict | None = None, drehen: bool | None = None) -> int:
        """OCR-Ergebnis der Oberflaeche uebernehmen (``{seite: text}``), auch in den Cache; 0, wenn unbekannt.

        ``ebenen`` (``{seite: text_pdf}``) sind die Text-PDFs aus demselben
        Tesseract-Aufruf; der naechste Indexlauf schreibt sie als Textebene in
        die Datei (Phase 5b). ``drehungen`` (``{seite: grad}``, Issue #151):
        Lage, in der die OCR die Seite besser las; je nach ``auto_drehen``
        dreht der naechste Indexlauf die Datei (``drehen``: ausdruecklich
        vormerken oder nicht, None = nach Stufe und Ort). ``ersetzen`` ("OCR neu
        durchfuehren", Issue #150) ueberschreibt auch schon erkannte Seiten und
        ihre Cache-Eintraege.
        """
        if not self.vorhanden() or not texte:
            return 0
        con = self._schreiben()
        try:
            r = con.execute("SELECT id FROM dokumente WHERE pfad = ?", (norm_pfad(pfad),)).fetchone()
            if not r:
                return 0
            ocr = self.konfig.ocr_einstellungen()
            n = db.ocr_text_eintragen(con, r[0], dict(texte), ocr.get("sprachen"), ocr.get("dpi"),
                                      nur_offene=not ersetzen, ebenen=dict(ebenen) if ebenen else None,
                                      cache_ersetzen=ersetzen, drehungen=dict(drehungen) if drehungen else None,
                                      drehen=bool(drehungen) and (self.konfig.drehen_vormerken(norm_pfad(pfad))
                                                                  if drehen is None else drehen))
            con.commit()
            return n
        finally:
            con.close()

    def metadaten_setzen(self, pfad: str, felder: dict, pdf_id: str | None = None, text: str | None = None,
                         lesen: bool = True, name: str | None = None) -> bool:
        """PDFSM-Metadaten (Korrespondent, Kategorie, Steuerjahr, Betrag, Buchungsdatum, Zusammenfassung,
        Schlagwoerter) mit Quelle ``'pdfsm'`` setzen; sie haben Vorrang vor Werten aus der PDF.

        Unbekannte Dateien werden aufgenommen, auch ausserhalb der Wurzeln (PDFSM
        verwaltet sie): mit ``lesen`` sofort gelesen, sonst nur mit Namen und
        Metadaten angelegt (Status ``ausstehend``, der naechste Lauf liest sie).
        ``text`` dient dabei als Notnagel-Text, bis die Datei gelesen wurde (auch
        fuer Dateien, die es nicht mehr gibt); ``name`` ersetzt dann den
        Dateinamen aus dem Pfad. Liefert True, wenn geschrieben wurde.
        """
        pfad = norm_pfad(pfad)
        con = self._schreiben()
        try:
            r = con.execute("SELECT id, textstatus FROM dokumente WHERE pfad = ?", (pfad,)).fetchone()
            dok_id = r[0] if r else None
            if dok_id is None and lesen and os.path.isfile(pfad):
                from src.search.indexer import einzeldatei_indizieren
                dok_id = einzeldatei_indizieren(con, self.konfig, pfad)
            if dok_id is None:
                dok_id = self._platzhalter(con, pfad, text, name)
            elif text and r is not None and r[1] in ("ausstehend", "fehler") and not os.path.isfile(pfad):
                # Platzhalter ohne lesbare Datei: Notnagel-Text (und Name) erneuern
                con.execute("DELETE FROM seiten WHERE dok_id = ?", (dok_id,))
                con.execute("INSERT INTO seiten (dok_id, seite, quelle, text) VALUES (?, 1, 'pdfsm', ?)",
                            (dok_id, text))
                if name:
                    con.execute("UPDATE dokumente SET name = ? WHERE id = ?", (name, dok_id))
            ok = db.metadaten_setzen(con, dok_id, felder, pdf_id, quelle="pdfsm")
            con.commit()
            return ok
        finally:
            con.close()

    @staticmethod
    def _platzhalter(con, pfad: str, text: str | None, name: str | None = None) -> int:
        """Dokument nur mit Namen (und Notnagel-Text) anlegen; Groesse/mtime fehlen, der naechste Lauf liest es."""
        from src.search.indexer import TYP

        ext = os.path.splitext(pfad)[1].lower()
        typ, fmt = TYP.get(ext, ("pdf", "pdf"))
        vorhanden = os.path.isfile(pfad)
        dok = {"pfad": pfad, "datei": pfad, "name": name or os.path.basename(pfad), "ordner": os.path.dirname(pfad),
               "typ": typ, "format": fmt, "groesse": None, "mtime_ns": None,
               "datum": os.path.getmtime(pfad) if vorhanden else None, "seiten": None,
               "textstatus": "ausstehend" if vorhanden else "fehler",
               "fehler": None if vorhanden else "Datei nicht gefunden", "prioritaet": 9}
        seiten = [(1, "pdfsm", text)] if text else []
        return db.speichere(con, dok, seiten)

    def metadaten_ersetzen(self, feld: str, alt: str, neu: str) -> int:
        """Einen Wert in allen Dokumenten ersetzen (Korrespondenten-Merge). Liefert die Trefferzahl."""
        if not self.vorhanden():
            return 0
        con = self._schreiben()
        try:
            n = db.metadaten_ersetzen(con, feld, alt, neu)
            con.commit()
            return n
        finally:
            con.close()

    # ------------------------------------------------------------------ Laeufe

    # ------------------------------------------------------------------ Textebene (Phase 5b)

    def textebene_protokoll(self, anzahl: int = 500) -> list[dict]:
        """Von der Textebene geaenderte Dateien, neueste zuerst (``textebene.protokoll``)."""
        from src.search import textebene

        con = self._lesen()
        if con is None:
            return []
        try:
            return textebene.protokoll(con, anzahl)
        except sqlite3.OperationalError:     # Datenbank noch ohne Tabelle (Version 1, nur lesend)
            return []
        finally:
            con.close()

    def textebene_rueckgaengig(self, eintrag_id: int, erzwingen: bool = False) -> tuple[bool, str]:
        """Eine Aenderung zuruecknehmen (``textebene.rueckgaengig``); ``(ok, meldung)``."""
        from src.search import textebene

        if not self.vorhanden():
            return False, "Kein Suchindex vorhanden."
        con = self._schreiben()
        try:
            return textebene.rueckgaengig(con, self.konfig, int(eintrag_id), erzwingen=erzwingen)
        finally:
            con.close()

    def textebene_schaetzung(self) -> dict:
        """Aufwand der Stufe ``alle`` fuer den Altbestand (``textebene.schaetzung``); ohne Index lauter Nullen."""
        from src.search import textebene

        con = self._lesen()
        leer = {"dateien": 0, "seiten": 0, "prozesse": self.konfig.anzahl_prozesse, "sekunden": 0, "bytes": 0,
                "zuwachs_bytes": 0, "onedrive_dateien": 0, "onedrive_bytes": 0,
                "sicherung_tage": self.konfig.textebene_sicherung_tage}
        if con is None:
            return leer
        try:
            return textebene.schaetzung(con, self.konfig)
        except sqlite3.OperationalError:
            return leer
        finally:
            con.close()

    def lauf_anhalten(self) -> bool:
        """Den laufenden Indexlauf anhalten (laufende Auftraege werden fertig); False, wenn keiner laeuft."""
        from src.search.indexer import anhalten

        return anhalten(self.konfig)

    @staticmethod
    def dienst_kommando(zeitplan: bool = False) -> list[str]:
        """Aufruf des Hintergrunddienstes: EXE neben dem Programm (gebaut) bzw. ``python -m`` (Entwicklung).

        Gebaut ist es unter Windows ``pdfsm-dienstw.exe`` (ohne Konsolenfenster).
        ``zeitplan``: fuer die Aufgabenplanung nimmt die Entwicklungsumgebung unter
        Windows ``pythonw.exe``, sonst oeffnete jeder Lauf ein Konsolenfenster.
        """
        if getattr(sys, "frozen", False):
            name = "pdfsm-dienstw.exe" if sys.platform == "win32" else "pdfsm-dienst"
            return [str(Path(sys.executable).with_name(name))]
        python = sys.executable
        if zeitplan and sys.platform == "win32":
            fensterlos = Path(python).with_name("pythonw.exe")
            if fensterlos.exists():
                python = str(fensterlos)
        return [python, "-m", "src.search.dienst"]

    # ------------------------------------------------------------------ Browser-Oberflaeche

    def web_adresse(self) -> str:
        return f"http://127.0.0.1:{self.konfig.web_port}/"

    def web_erreichbar(self, timeout: float = 0.5) -> bool:
        """Antwortet die Browser-Oberflaeche der Dokumentensuche auf ihrem Port (und nicht ein anderes Programm)?"""
        import json
        import urllib.error
        import urllib.request

        try:
            with urllib.request.urlopen(self.web_adresse() + "api/status", timeout=timeout) as r:
                daten = json.loads(r.read().decode("utf-8"))
        except (OSError, ValueError, urllib.error.URLError):
            return False
        return isinstance(daten, dict) and ("vorhanden" in daten or "dokumente" in daten)

    def web_starten(self, oeffnen: bool = True, konfig_pfad: str | None = None) -> subprocess.Popen:
        """Browser-Oberflaeche als eigenen Prozess starten; mit ``oeffnen`` oeffnet sie den Browser selbst."""
        args = list(self.dienst_kommando())
        if konfig_pfad:
            args += ["--config", str(konfig_pfad)]
        args += ["web", "--port", str(self.konfig.web_port)]
        if not oeffnen:
            args.append("--nicht-oeffnen")
        extra: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                       **plattform.popen_flags(abgekoppelt=True)}
        if not getattr(sys, "frozen", False):
            extra["cwd"] = str(Path(__file__).resolve().parents[2])
        return subprocess.Popen(args, **extra)

    def lauf_starten(self, nur_prioritaet: bool = False, pfad: str | None = None, hintergrund: bool = True,
                     konfig_pfad: str | None = None) -> subprocess.Popen | None:
        """Indexlauf als eigenen Prozess starten; None, wenn schon einer laeuft."""
        if self.laeuft_gerade():
            return None
        args = list(self.dienst_kommando())
        if konfig_pfad:
            args += ["--config", str(konfig_pfad)]
        args.append("index")
        if hintergrund:
            args.append("--hintergrund")
        if nur_prioritaet:
            args.append("--nur-prioritaet")
        if pfad:
            args += ["--pfad", str(pfad)]
        extra: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                       **plattform.popen_flags(abgekoppelt=True)}
        if not getattr(sys, "frozen", False):
            extra["cwd"] = str(Path(__file__).resolve().parents[2])
        return subprocess.Popen(args, **extra)

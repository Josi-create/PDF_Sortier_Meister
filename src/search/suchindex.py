"""Fassade der Dokumentensuche fuer Oberflaeche, Dienst, MCP und Web (Qt-frei).

``Suchindex`` kapselt den Datenbankpfad aus der ``SearchConfig``, oeffnet fuer
jeden Lesezugriff eine eigene Nur-Lese-Verbindung (deshalb aus jedem Thread
nutzbar) und bietet die kurzen Schreibmeldungen, mit denen die Oberflaeche
Umbenennen, Verschieben und Loeschen sofort an den Index meldet.

Indexlaeufe starten immer in einem eigenen Prozess (``pdfsm-dienst index``),
nie in-process: ``lauf_starten()``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from src.search import db
from src.search.konfig import SearchConfig, norm_pfad


class Suchindex:
    def __init__(self, konfig: SearchConfig) -> None:
        self.konfig = konfig

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

    @staticmethod
    def _leer(abfrage: str = "") -> dict:
        return {"treffer": [], "gesamt": 0, "mehr": False, "abfrage": abfrage, "dauer_ms": 0}

    # ------------------------------------------------------------------ Lesen

    def suche(self, abfrage: str, **argumente) -> dict:
        """Volltextsuche; Argumente wie ``db.suche`` (typ, ordner, von, bis, sortierung, anzahl, start, ...)."""
        if not abfrage or not abfrage.strip():
            return self._leer()
        con = self._lesen()
        if con is None:
            return self._leer(abfrage)
        try:
            return db.suche(con, abfrage, **argumente)
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

    def volltext(self, dok_id: int) -> str:
        con = self._lesen()
        if con is None:
            return ""
        try:
            return db.volltext(con, dok_id)
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
                    "schema_version": "", "laeuft": self.laeuft_gerade(), "db_groesse": 0}
        try:
            st = db.status(con)
        finally:
            con.close()
        st["vorhanden"] = True
        st["laeuft"] = self.laeuft_gerade()
        st["db_groesse"] = sum(
            os.path.getsize(p) for p in (str(self.db_datei), str(self.db_datei) + "-wal") if os.path.exists(p)
        )
        return st

    def laeuft_gerade(self) -> bool:
        from src.search.indexer import laeuft_gerade
        return laeuft_gerade(self.konfig)

    # ------------------------------------------------------------------ Schreibmeldungen der Oberflaeche

    def datei_verschoben(self, alt: str, neu: str) -> bool:
        """Umbenennen oder Verschieben melden: der Eintrag behaelt Text und OCR, nur der Pfad aendert sich.

        Liefert True, wenn ein Eintrag angepasst wurde. Ein Eintrag, der unter dem
        neuen Pfad schon existierte (ueberschriebene Datei), wird entfernt.
        """
        if not self.vorhanden():
            return False
        alt, neu = norm_pfad(alt), norm_pfad(neu)
        if alt == neu:
            return False
        con = db.verbinde(self.db_datei)
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
        con = db.verbinde(self.db_datei)
        try:
            r = con.execute("SELECT id FROM dokumente WHERE pfad = ? AND format != 'mbox'", (norm_pfad(pfad),)).fetchone()
            if not r:
                return False
            db.loesche(con, [r[0]])
            con.commit()
            return True
        finally:
            con.close()

    # ------------------------------------------------------------------ Laeufe

    @staticmethod
    def dienst_kommando() -> list[str]:
        """Aufruf des Hintergrunddienstes: EXE neben dem Programm (gebaut) bzw. ``python -m`` (Entwicklung)."""
        if getattr(sys, "frozen", False):
            name = "pdfsm-dienstw.exe" if sys.platform == "win32" else "pdfsm-dienst"
            return [str(Path(sys.executable).with_name(name))]
        return [sys.executable, "-m", "src.search.dienst"]

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
        extra: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if sys.platform == "win32":
            extra["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            extra["start_new_session"] = True
        if not getattr(sys, "frozen", False):
            extra["cwd"] = str(Path(__file__).resolve().parents[2])
        return subprocess.Popen(args, **extra)

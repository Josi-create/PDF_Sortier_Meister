"""Datenquelle der Chat-Werkzeuge im Dienst, ohne SQLAlchemy (Baustein 1, ``docs/CHAT_MCP_PLAN.md``).

:class:`PdfsmDaten` erfuellt das Protokoll :class:`src.rag.daten.ChatDaten`
wie :class:`src.utils.database.Database`, damit der MCP-Server
(``pdfsm-dienst mcp``) dieselben Werkzeuge anbieten kann wie der Chat:

* ``search_documents`` und ``get_indexed_documents_brief`` lesen den
  Suchindex - mit derselben Fassadenlogik wie ``Database`` (gemeinsame
  Funktion :func:`dokumente_suchen`).
* Sortierhistorie und Korrespondenten kommen aus der Hauptdatenbank
  (``history.db``, Tabellen ``sorting_history``, ``korrespondenten``,
  ``korrespondent_metadata``), gelesen mit ``sqlite3`` ueber eine
  schreibgeschuetzte Verbindung (URI ``mode=ro``). Der Dienst schreibt nie in
  diese Datenbank.
* Fehlt die Datenbank oder eine Tabelle, liefern die Methoden leere
  Ergebnisse statt Fehler: die Werkzeuge sind dann weniger hilfreich, aber
  nie kaputt.

Qt-frei und ohne SQLAlchemy (``pdfsm-dienst`` schliesst es aus).

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("pdf_sortier_meister.suche")

# Maximale Laenge des Volltexts je Treffer in ``search_documents`` (RAG-Chat /
# Phase 19 / Architektur-Entscheidung Q3): mehr liest der Kontextblock nicht.
MAX_EXTRACTED_TEXT_LENGTH = 5000

# Wartezeit auf eine Sperre der Hauptdatenbank (die Oberflaeche schreibt gerade)
LESEN_ZEITLIMIT_S = 3

_HISTORIE_SPALTEN = ("new_filename", "original_filename", "keywords", "korrespondent",
                     "steuerjahr", "detected_date", "target_relative_path", "target_folder")
_KORRESPONDENT_SPALTEN = ("id", "name", "aliases", "kategorie", "farbe", "notizen", "usage_count",
                          "created_at", "updated_at")


# --------------------------------------------------------------------------- gemeinsame Fassadenlogik

def betrag_text(wert) -> str:
    """REAL aus dem Suchindex als Text wie frueher in ``document_search`` ("59.99")."""
    if wert is None or wert == "":
        return ""
    try:
        return f"{float(wert):.2f}"
    except (TypeError, ValueError):
        return str(wert)


def ausschnitt(stellen: list) -> str:
    """Fundstellen (``\\x02``/``\\x03``-Marker) als Ausschnitt mit den bisherigen Markern ``>>>``/``<<<``."""
    teile = []
    for s in stellen or []:
        text = " ".join((s.get("text") or "").split())
        teile.append(text.replace("\x02", ">>>").replace("\x03", "<<<"))
    return " … ".join(t for t in teile if t)


def aliase_lesen(wert) -> list[str]:
    """Alias-Spalte der Tabelle ``korrespondenten`` (JSON-Liste) als Python-Liste; robust gegen kaputte Werte."""
    if not wert:
        return []
    if isinstance(wert, (list, tuple)):
        return [str(a) for a in wert]
    try:
        geparst = json.loads(wert)
        if isinstance(geparst, list):
            return [str(a) for a in geparst]
        return [str(geparst)]
    except (ValueError, TypeError):
        # Rueckfall: als Komma-getrennte Liste lesen
        return [a.strip() for a in str(wert).split(",") if a.strip()]


def dokumente_suchen(
    suchindex,
    query: str,
    limit: int = 50,
    steuerjahr: str = "",
    kategorie: str = "",
    korrespondent: str = "",
    datum_von: str = "",
    datum_bis: str = "",
    betrag_von: float = 0.0,
    betrag_bis: float = 0.0,
    pdf_id: str = "",
    typ: str = "",
    ordner: str = "",
    von: str = "",
    bis: str = "",
    sortierung: str = "",
    *,
    pdf_id_zu_pfad: Callable[[str], str] | None = None,
) -> list[dict]:
    """Suche im Suchindex mit den Ergebnisschluesseln von ``Database.search_documents``.

    Gemeinsame Umsetzung fuer :class:`src.utils.database.Database` und
    :class:`PdfsmDaten`; Beschreibung der Argumente und Schluessel dort.
    ``pdf_id_zu_pfad`` liefert die ``pdf_id`` aus der Tabelle ``pdfs`` der
    Hauptdatenbank fuer Treffer, die im Index noch keine haben.
    """
    has_text = bool(query and query.strip())
    has_filter = any([
        steuerjahr, kategorie, korrespondent,
        datum_von, datum_bis,
        betrag_von > 0, betrag_bis > 0,
        pdf_id, typ,
        ordner, von, bis,
    ])
    if not has_text and not has_filter:
        return []

    q = ""
    if has_text:
        q = query.strip()
        # Ohne FTS5-Operatoren: Woerter als Wortanfaenge, alle muessen vorkommen (bisheriges Verhalten)
        if not any(op in q for op in (" OR ", " AND ", " NEAR ", " NOT ", '"', "*")):
            q = " AND ".join(f'"{t}"*' for t in q.split() if t)

    # Issue #166/#167: Filter der Chat-Werkzeuge nur mitgeben, wenn gesetzt
    zusatz: dict = {}
    if ordner:
        zusatz["ordner"] = ordner
    if von:
        zusatz["von"] = von
    if bis:
        zusatz["bis"] = bis
    if sortierung:
        zusatz["sortierung"] = sortierung

    try:
        erg = suchindex.suche(
            q,
            steuerjahr=steuerjahr or None,
            kategorie=kategorie or None,
            korrespondent=korrespondent or None,
            steuerjahr_von=datum_von or None,
            steuerjahr_bis=datum_bis or None,
            betrag_von=betrag_von if betrag_von and betrag_von > 0 else None,
            betrag_bis=betrag_bis if betrag_bis and betrag_bis > 0 else None,
            pdf_id=pdf_id or None,
            typ=typ or None,
            anzahl=int(limit),
            **zusatz,
        )
    except Exception as e:
        print(f"Suchindex-Suche Fehler: {e}")
        return []

    results = []
    for d in erg.get("treffer") or []:
        pid = d.get("pdf_id") or ""
        if not pid and pdf_id_zu_pfad is not None:
            pid = pdf_id_zu_pfad(d.get("pfad") or "") or ""
        stellen = d.get("stellen") or []
        results.append({
            "pdf_id": pid,
            "file_path": d.get("pfad") or "",
            "filename": d.get("name") or "",
            "text_snippet": ausschnitt(stellen),
            "keywords": d.get("schlagwoerter") or "",
            "korrespondent": d.get("korrespondent") or "",
            "kategorie": d.get("kategorie") or "",
            "steuerjahr": d.get("steuerjahr") or "",
            "betrag": betrag_text(d.get("betrag")),
            "zusammenfassung": d.get("zusammenfassung") or "",
            "target_folder": d.get("ordner") or "",
            "dok_id": d.get("id"),
            "seite": int(stellen[0].get("seite") or 1) if stellen else 1,
            "typ": d.get("typ") or "",
            "format": d.get("format") or "",
            "groesse": d.get("groesse"),
            "datum": d.get("datum"),
            "rang": d.get("rang"),
            "extracted_text": suchindex.volltext(d["id"], MAX_EXTRACTED_TEXT_LENGTH),
        })
    return results


def dokumente_kurz(suchindex, limit: int = 20000) -> list[dict]:
    """Indizierte PDFs ohne Volltext (fuer die Aehnlichkeitssuche); Fehler ergeben eine leere Liste."""
    try:
        return suchindex.dokumente_kurz(typ="pdf", limit=limit)
    except Exception as e:
        print(f"Suchindex lesen fehlgeschlagen: {e}")
        return []


def _zeitpunkt(wert):
    """Zeitstempel aus SQLite (Text wie SQLAlchemy ihn schreibt) als ``datetime``; Unlesbares bleibt stehen."""
    if isinstance(wert, str) and wert:
        try:
            return datetime.fromisoformat(wert)
        except ValueError:
            return wert
    return wert


# --------------------------------------------------------------------------- Leser

class PdfsmDaten:
    """Datenquelle der Chat-Werkzeuge im Dienst: Suchindex + Hauptdatenbank, nur lesend.

    Args:
        suchindex: :class:`~src.search.suchindex.Suchindex` (oder ``None``).
        db_pfad: Pfad der Hauptdatenbank (``Config.database_path``,
            ``history.db``); ``None`` oder eine fehlende Datei ergeben leere
            Historie und keine Korrespondenten.
    """

    def __init__(self, suchindex, db_pfad: str | Path | None) -> None:
        self.suchindex = suchindex
        self.db_pfad = Path(db_pfad) if db_pfad else None

    # ------------------------------------------------------------------ Verbindung

    def _abfrage(self, sql: str, parameter: tuple = ()) -> list[tuple]:
        """Zeilen einer Abfrage; fehlende Datei, Tabelle oder Sperre ergeben eine leere Liste."""
        if self.db_pfad is None or not self.db_pfad.is_file():
            return []
        try:
            con = sqlite3.connect(self.db_pfad.resolve().as_uri() + "?mode=ro", uri=True,
                                  timeout=LESEN_ZEITLIMIT_S)
        except sqlite3.Error as e:
            log.debug("Hauptdatenbank nicht lesbar: %s", e)
            return []
        try:
            return con.execute(sql, parameter).fetchall()
        except sqlite3.Error as e:  # fehlende Tabelle (aeltere Datenbank), Sperre ...
            log.debug("Hauptdatenbank: %s", e)
            return []
        finally:
            con.close()

    # ------------------------------------------------------------------ Suchindex

    def search_documents(
        self,
        query: str,
        limit: int = 50,
        steuerjahr: str = "",
        kategorie: str = "",
        korrespondent: str = "",
        datum_von: str = "",
        datum_bis: str = "",
        betrag_von: float = 0.0,
        betrag_bis: float = 0.0,
        pdf_id: str = "",
        typ: str = "",
        ordner: str = "",
        von: str = "",
        bis: str = "",
        sortierung: str = "",
    ) -> list[dict]:
        """Wie ``Database.search_documents``; ohne Suchindex eine leere Liste."""
        if self.suchindex is None:
            return []
        return dokumente_suchen(
            self.suchindex, query, limit, steuerjahr, kategorie, korrespondent, datum_von, datum_bis,
            betrag_von, betrag_bis, pdf_id, typ, ordner, von, bis, sortierung,
            pdf_id_zu_pfad=self._pdf_id_zu_pfad,
        )

    def get_indexed_documents_brief(self, limit: int = 20000) -> list[dict]:
        """Indizierte PDFs ohne Volltext (fuer die Aehnlichkeitssuche)."""
        if self.suchindex is None:
            return []
        return dokumente_kurz(self.suchindex, limit)

    def _pdf_id_zu_pfad(self, pfad: str) -> str:
        if not pfad:
            return ""
        zeilen = self._abfrage("SELECT pdf_id FROM pdfs WHERE file_path = ?", (pfad,))
        return str(zeilen[0][0] or "") if zeilen else ""

    # ------------------------------------------------------------------ Hauptdatenbank

    def get_history_brief(self, limit: int = 20000) -> list[dict]:
        """Sortierhistorie ohne Volltext (fuer die Aehnlichkeitssuche), neueste zuerst."""
        zeilen = self._abfrage(
            f"SELECT {', '.join(_HISTORIE_SPALTEN)} FROM sorting_history ORDER BY id DESC LIMIT ?",
            (int(limit),),
        )
        return [dict(zip(_HISTORIE_SPALTEN, z)) for z in zeilen]

    @staticmethod
    def _korrespondent_dict(zeile: tuple) -> dict:
        d = dict(zip(_KORRESPONDENT_SPALTEN, zeile))
        return {
            "id": d["id"],
            "name": d["name"],
            "aliases": aliase_lesen(d["aliases"]),
            "aliases_raw": d["aliases"],
            "kategorie": d["kategorie"],
            "farbe": d["farbe"],
            "notizen": d["notizen"],
            "usage_count": d["usage_count"] or 0,
            "created_at": _zeitpunkt(d["created_at"]),
            "updated_at": _zeitpunkt(d["updated_at"]),
        }

    def list_korrespondenten(self) -> list[dict]:
        """Alle Korrespondenten der Verwaltung, nach ``usage_count`` absteigend, dann ``name``."""
        zeilen = self._abfrage(
            f"SELECT {', '.join(_KORRESPONDENT_SPALTEN)} FROM korrespondenten "
            "ORDER BY usage_count DESC, name ASC"
        )
        return [self._korrespondent_dict(z) for z in zeilen]

    def get_korrespondent(self, name: str) -> Optional[dict]:
        """Ein Korrespondent per exaktem Namen (Gross-/Kleinschreibung zaehlt), sonst ``None``."""
        if not name or not name.strip():
            return None
        zeilen = self._abfrage(
            f"SELECT {', '.join(_KORRESPONDENT_SPALTEN)} FROM korrespondenten WHERE name = ? LIMIT 1",
            (name.strip(),),
        )
        return self._korrespondent_dict(zeilen[0]) if zeilen else None

    def get_korrespondent_metadata(self, korrespondent: str) -> Optional[dict]:
        """Gelernte Metadaten wie ``Database.get_korrespondent_metadata``.

        Reihenfolge: kanonische Schreibweise der Verwaltung, genau dieser Name,
        gleichwertige Schreibweise (:func:`~src.core.korrespondenten.schluessel`),
        Teiltreffer in beide Richtungen.
        """
        from src.core.korrespondenten import kanonisch, schluessel
        from src.core.metadata_choices import clean_category

        if not korrespondent or not korrespondent.strip():
            return None
        korrespondent = kanonisch(korrespondent, self.list_korrespondenten())
        spalten = ("korrespondent", "kategorie", "waehrung", "mwst_satz", "steuerlich_absetzbar")
        zeilen = [dict(zip(spalten, z)) for z in self._abfrage(
            f"SELECT {', '.join(spalten)} FROM korrespondent_metadata ORDER BY id")]

        eintrag = next((z for z in zeilen if z["korrespondent"] == korrespondent), None)
        if eintrag is None:
            k = schluessel(korrespondent)
            eintrag = next((z for z in zeilen if k and schluessel(z["korrespondent"] or "") == k), None)
        if eintrag is None:
            # Teiltreffer (z.B. "ista GmbH" findet "ista")
            gesucht = korrespondent.strip().lower()
            for z in zeilen:
                name = (z["korrespondent"] or "").lower()
                if name in gesucht or gesucht in name:
                    eintrag = z
                    break
        if eintrag is None:
            return None

        ergebnis: dict[str, Any] = {}
        kategorie = clean_category(eintrag["kategorie"])
        if kategorie:
            ergebnis["subject"] = kategorie
        for feld in ("waehrung", "mwst_satz", "steuerlich_absetzbar"):
            if eintrag[feld]:
                ergebnis[feld] = eintrag[feld]
        return ergebnis or None

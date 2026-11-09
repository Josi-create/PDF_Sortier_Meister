"""Datenquelle der Chat-Werkzeuge als Protokoll (Baustein 1, ``docs/CHAT_MCP_PLAN.md``).

Werkzeugkasten (:mod:`src.rag.werkzeuge`), Kernlogik (:mod:`src.rag.werkzeug_kern`),
Retrieval (:mod:`src.rag.retrieval`) und die Aehnlichkeitssuche
(:mod:`src.core.similar_documents`) brauchen von der Datenbank genau diese
sechs Methoden und den Suchindex. Zwei Klassen erfuellen das Protokoll
strukturell, ohne von ihm zu erben:

* :class:`src.utils.database.Database` - die Oberflaeche (SQLAlchemy),
* :class:`src.search.pdfsm_daten.PdfsmDaten` - der Dienst ``pdfsm-dienst mcp``
  (``sqlite3``, schreibgeschuetzt, ohne SQLAlchemy).

Signaturen und Rueckgabeformen sind 1:1 die von ``Database``. Dieses Modul
importiert nichts aus ``src.utils.database``, damit ``src.rag`` im Dienst ohne
SQLAlchemy laeuft.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class ChatDaten(Protocol):
    """Was die Chat- und MCP-Werkzeuge von der Datenbank lesen.

    Attributes:
        suchindex: :class:`~src.search.suchindex.Suchindex` fuer Volltext,
            Seiten und SQL-Abfragen; ``None``, wenn keiner verfuegbar ist
            (die Werkzeuge melden dann "Suchindex nicht verfügbar").
    """

    suchindex: Any

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
        """Volltextsuche im Suchindex; Ergebnisschluessel siehe ``Database.search_documents``."""
        ...

    def get_indexed_documents_brief(self, limit: int = 20000) -> list[dict]:
        """Indizierte PDFs ohne Volltext (fuer die Aehnlichkeitssuche)."""
        ...

    def get_history_brief(self, limit: int = 20000) -> list[dict]:
        """Sortierhistorie ohne Volltext, neueste zuerst.

        Schluessel: ``new_filename``, ``original_filename``, ``keywords``,
        ``korrespondent``, ``steuerjahr``, ``detected_date``,
        ``target_relative_path``, ``target_folder``.
        """
        ...

    def get_korrespondent(self, name: str) -> Optional[dict]:
        """Ein Korrespondent der Verwaltung per exaktem Namen, sonst ``None``."""
        ...

    def get_korrespondent_metadata(self, korrespondent: str) -> Optional[dict]:
        """Gelernte Metadaten (``subject``, ``waehrung``, ``mwst_satz``, ``steuerlich_absetzbar``) oder ``None``."""
        ...

    def list_korrespondenten(self) -> list[dict]:
        """Alle Korrespondenten der Verwaltung, haeufigste zuerst (``aliases`` als Liste)."""
        ...

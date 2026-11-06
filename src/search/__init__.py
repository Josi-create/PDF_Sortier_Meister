"""Dokumentensuche von PDF Sortier Meister (Qt-frei).

Lokaler Volltextindex (SQLite FTS5) ueber PDFs mit OCR, Office-Dateien,
Markdown-Dateien und Mails. Hervorgegangen aus dem eigenstaendigen Programm
PDFsuche; Architektur und Schnittstelle: ``docs/SUCHE_ARCHITEKTUR.md``.

Nichts in diesem Paket importiert PyQt6, damit Hintergrunddienst, MCP-Server,
Web-Oberflaeche und die Arbeitsprozesse ohne Oberflaeche laufen.

Oeffentliche Schnittstelle::

    from src.search import SearchConfig, Suchindex, Indexer
"""

from src.search.db import SCHEMA_VERSION
from src.search.indexer import Indexer, laeuft_gerade
from src.search.konfig import SearchConfig, lade, lade_config_toml
from src.search.suchindex import Suchindex

__all__ = [
    "SCHEMA_VERSION",
    "Indexer",
    "SearchConfig",
    "Suchindex",
    "lade",
    "lade_config_toml",
    "laeuft_gerade",
]

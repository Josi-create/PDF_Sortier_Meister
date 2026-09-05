"""
Retrieval-Service fuer das RAG-Chat-Feature (Phase 19 / M1).

Baut FTS5-OR-Queries auf Basis der Nutzerfrage, extrahiert
heuristische Filter (Jahr, Betrag, Korrespondent) per Regex,
und produziert ``RetrievedDoc``-Objekte mit trunc-Snippets
(erste 1000 + letzte 1000 Zeichen bei Texten > 2000).

Kein LLM noetig - alles in stdlib (re, str) plus der bestehende
``Database.search_documents``-Methode.

GPL-3.0-or-later - Copyright (c) 2026
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from src.utils.config import ChatConfig


# Deutsche Stopwords (ca. 80). Bewusst klein gehalten: FTS5 stemmt
# ohnehin nicht und kuerzere Stopwort-Listen erhoehen Recall.
STOPWORDS: set[str] = {
    "der", "die", "das", "den", "dem", "des",
    "ein", "eine", "einer", "eines", "einem",
    "und", "oder", "aber", "sondern", "denn",
    "ist", "sind", "war", "waren", "wird", "werden", "wurde", "wurden",
    "hat", "haben", "hatte", "hatten",
    "ich", "du", "er", "sie", "es", "wir", "ihr",
    "mich", "dich", "sich", "uns", "euch",
    "mein", "meine", "meinem", "meiner", "meines",
    "dein", "deine", "deinem", "deiner", "deines",
    "sein", "seine", "seinem", "seiner", "seines",
    "ihr", "ihre", "ihrem", "ihrer", "ihres",
    "von", "zu", "mit", "bei", "aus", "nach", "ueber", "ueber",
    "vor", "seit", "fuer", "gegen", "ohne", "um", "durch",
    "im", "in", "am", "an", "auf", "als", "wie", "was", "wer", "wen", "wem",
    "wann", "wo", "wieso", "warum", "weshalb",
    "auch", "noch", "schon", "mehr", "weniger", "sehr", "ganz",
    "dann", "hier", "dort", "jetzt", "heute", "morgen", "gestern",
    "ja", "nein", "nicht", "kein", "keine", "keinem", "keiner", "keines",
    "dieser", "diese", "diesem", "dieses", "jener", "jene", "jenes",
    "alle", "alles", "allem", "allen", "aller", "jede", "jeder", "jedem",
    "so", "also", "wieder", "weil", "damit", "wenn", "ob",
    "nur", "etwa", "beim",
}


# Regex fuer die heuristische Filter-Extraktion.
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
# Betrag: "von 49,99", "49.99 EUR", "EUR 49,99", "49,99 Euro"
_AMOUNT_RE = re.compile(
    r"(?:"
    r"von\s+(\d{1,6}(?:[.,]\d{2}))"          # "von 49,99"
    r"|(\d{1,6}(?:[.,]\d{2}))\s*(?:EUR|€|Euro)"  # "49,99 EUR"
    r"|(?:EUR|€|Euro)\s*(\d{1,6}(?:[.,]\d{2}))"  # "EUR 49,99"
    r")",
    re.IGNORECASE,
)
# Bekannte Korrespondenten-Keywords. Nicht exhaustiv - das System
# lernt zur Laufzeit, aber fuer den ersten Wurf reicht eine Whitelist.
_KORR_KEYWORDS = [
    "Telekom", "Vodafone", "O2", "1und1", "1&1", "Stadtwerke", "GEZ",
    "Finanzamt", "Vermieter", "Hausverwaltung", "ista", "Kabel",
    "Deutsche Bahn", "Allianz", "HUK", "Debeka", "Barmer", "AOK", "TK",
    "Sparkasse", "Volksbank", "ING", "DKB", "Commerzbank",
]
_KORR_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _KORR_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


# Tokenizer: Wortgrenzen + erlaubt deutsche Umlaute/Leerzeichen.
_TOKEN_RE = re.compile(r"[\wäöüÄÖÜß]+", re.UNICODE)


def _to_float(amount_str: str) -> float:
    """Wandelt '49,99' / '49.99' in 49.99. Bei Fehler 0.0."""
    if not amount_str:
        return 0.0
    s = amount_str.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except (ValueError, AttributeError):
        return 0.0


@dataclass
class RetrievedDoc:
    """Ein einzelnes Retrieval-Ergebnis."""
    index: int
    file_path: str
    filename: str
    text_snippet: str
    rank: int
    kategorie: str = ""
    steuerjahr: str = ""
    betrag: str = ""
    korrespondent: str = ""
    # Phase 3 (Issue #25): stabile 32-stellige Hex-UUID aus der
    # ``pdfs``-Master-Tabelle. Default leerer String, damit alte
    # Aufrufer (ohne DB-Lookup) nicht brechen.
    pdf_id: str = ""
    # Optional: Score aus FTS5 (rank). Niedriger = besser.
    extra: dict = field(default_factory=dict)


class RetrievalService:
    """
    Baut FTS5-Queries, extrahiert heuristische Filter, ruft
    ``Database.search_documents`` auf und produziert ``RetrievedDoc``s.

    Args:
        db: Eine Instanz von :class:`src.utils.database.Database`.
        chat_config: Optionale :class:`ChatConfig`. Fallback auf
            :class:`ChatConfig` mit Defaults.
    """

    def __init__(self, db, chat_config: Optional[ChatConfig] = None):
        self.db = db
        self.chat_config = chat_config or ChatConfig()

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def retrieve(self, question: str, k: int = None) -> list[RetrievedDoc]:
        """
        Durchsucht den Index nach passenden Dokumenten zur Frage.

        1. Stopwords entfernen.
        2. Heuristische Filter extrahieren (Jahr, Betrag, Korrespondent).
        3. FTS5-OR-Query bauen.
        4. ``db.search_documents`` aufrufen.
        5. Trunc-Snippets erzeugen.
        """
        if k is None:
            k = self.chat_config.max_context_docs

        if not question or not question.strip():
            return []

        stripped = self._strip_stopwords(question)
        terms = self._tokenize(stripped)
        if not terms:
            return []

        filters = self._extract_filters(question)
        fts_query = self._build_fts5_query(terms)

        try:
            raw_results = self.db.search_documents(
                query=fts_query,
                limit=k,
                **filters,
            )
        except TypeError:
            # Manche DB-Versionen unterstuetzen nicht alle Filter.
            raw_results = self.db.search_documents(query=fts_query, limit=k)
        except Exception:
            raw_results = []

        if not raw_results:
            return []

        return [
            self._to_retrieved_doc(r, idx + 1)
            for idx, r in enumerate(raw_results[:k])
        ]

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _strip_stopwords(self, text: str) -> str:
        """Entfernt deutsche Stopwords aus dem Text."""
        if not text:
            return ""
        tokens = _TOKEN_RE.findall(text)
        kept = [t for t in tokens if t.lower() not in STOPWORDS]
        return " ".join(kept)

    def _extract_filters(self, text: str) -> dict:
        """Extrahiert heuristische Filter (steuerjahr, betrag_von/bis,
        korrespondent) per Regex. Liefert ein Dict mit den von
        ``Database.search_documents`` erwarteten Schluesseln.
        """
        if not text:
            return {}

        filters: dict = {}

        # Steuerjahr: 4-stellige Jahreszahl im Format 20xx
        m_year = _YEAR_RE.search(text)
        if m_year:
            filters["steuerjahr"] = m_year.group(1)

        # Betrag: erste plausible Zahl reicht als Untergrenze
        m_amount = _AMOUNT_RE.search(text)
        if m_amount:
            # Wir suchen die erste nicht-leere Gruppe
            raw = next((g for g in m_amount.groups() if g), None)
            value = _to_float(raw or "")
            if value > 0:
                # Wertespanne: 80% .. 120% (grober Heuristik-Treffer)
                filters["betrag_von"] = round(value * 0.8, 2)
                filters["betrag_bis"] = round(value * 1.2, 2)

        # Korrespondent
        m_korr = _KORR_RE.search(text)
        if m_korr:
            filters["korrespondent"] = m_korr.group(1)

        return filters

    def _build_fts5_query(self, terms: list[str]) -> str:
        """Baut eine FTS5-OR-Query mit Prefix-Wildcards.

        Aus ``["telekom", "rechnung"]`` wird
        ``"telekom"* OR "rechnung"*``. Stopwords in den Terms werden
        sicherheitshalber nochmal herausgefiltert.
        """
        cleaned: list[str] = []
        for t in terms:
            t = t.strip().strip('"')
            if not t:
                continue
            if t.lower() in STOPWORDS:
                continue
            # Nur sichere ASCII/Buchstaben/Ziffern durchlassen
            if not _TOKEN_RE.fullmatch(t):
                continue
            cleaned.append(t)

        if not cleaned:
            return ""

        return " OR ".join(f'"{t}"*' for t in cleaned)

    def _tokenize(self, text: str) -> list[str]:
        """Tokenisiert einen Text in einzelne Woerter."""
        if not text:
            return []
        return _TOKEN_RE.findall(text)

    def _to_retrieved_doc(self, raw: dict, index: int) -> RetrievedDoc:
        """Wandelt ein DB-Dict in ein ``RetrievedDoc`` mit Trunc-Snippet."""
        text = raw.get("extracted_text") or raw.get("text_snippet") or ""
        snippet = self._build_snippet(text, self.chat_config.snippet_max_chars)

        return RetrievedDoc(
            index=index,
            file_path=raw.get("file_path", "") or "",
            filename=raw.get("filename", "") or "",
            text_snippet=snippet,
            rank=index,
            kategorie=raw.get("kategorie", "") or "",
            steuerjahr=raw.get("steuerjahr", "") or "",
            betrag=raw.get("betrag", "") or "",
            korrespondent=raw.get("korrespondent", "") or "",
            # Phase 3 (Issue #25): pdf_id aus dem DB-Dict uebernehmen.
            # Default "", damit alte Aufrufer ohne pdf_id-Feld nicht
            # brechen (rueckwaertskompatibel).
            pdf_id=raw.get("pdf_id", "") or "",
        )

    @staticmethod
    def _build_snippet(text: str, max_chars: int) -> str:
        """Erzeugt einen Trunc-Snippet.

        * Text <= max_chars: unverändert.
        * Text > max_chars: erste ``max_chars/2`` + ``...`` +
          letzte ``max_chars/2`` Zeichen.
        """
        if not text:
            return ""
        if len(text) <= max_chars:
            return text
        half = max_chars // 2
        if half <= 0:
            return text[:max_chars]
        return text[:half] + "\n[...]\n" + text[-half:]

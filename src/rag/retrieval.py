"""
Retrieval-Service fuer das RAG-Chat-Feature (Phase 19 / M1, Issue #166/#167).

Baut FTS5-OR-Queries auf Basis der Nutzerfrage, extrahiert
heuristische Filter (Jahr, Betrag, Korrespondent) per Regex,
und produziert ``RetrievedDoc``-Objekte.

Seit Issue #166/#167:

* Fragewoerter ("bitte", "welche", "zeig mir", "Dokument", "Ordner") zaehlen
  als Stoppwoerter, damit die ODER-Abfrage nicht an ihnen haengen bleibt.
* Nennt die Frage einen Dateityp ("Excel", "Tabelle", "Mail"), kommt eine
  zweite, auf diesen Typ eingeschraenkte Suche dazu; ihre Treffer stehen vorn.
* Bei nahezu gleicher Relevanz stehen neuere Dokumente vorn; Kopien derselben
  Datei (gleicher Name und Groesse, z.B. OneDrive und Archiv) zaehlen einmal.
* Der Textauszug eines Treffers besteht aus den Fundstellen der Suche und dem
  Text der Trefferseite (statt Anfang und Ende des ganzen Dokuments).
* :meth:`RetrievalService.retrieve_kennungen` sucht exakt nach Kennungen des
  Bezugsdokuments (Vertrags-, Zaehler-, Kundennummer ...) und markiert die
  Treffer mit den gemeinsamen Kennungen.

Kein LLM noetig - alles in stdlib (re, str) plus der bestehende
``Database.search_documents``-Methode.

GPL-3.0-or-later - Copyright (c) 2026
"""

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

from src.rag.bezug import Kennung, gleicher_pfad, kennungs_abfrage
from src.rag.daten import ChatDaten
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

# Fragewoerter (Issue #166/#167): tragen nichts zur Suche bei, treffen aber
# z.B. jede Projektnotiz, in der "Dokument" oder "Ordner" steht.
FRAGEWOERTER: set[str] = {
    "bitte", "mal", "mir", "uns",
    "welche", "welcher", "welchem", "welches", "welchen", "diesen", "jenem",
    "gehört", "gehoert", "gehören", "gehoeren", "gehörte",
    "zeig", "zeige", "zeigen", "gib", "gibt", "nenne", "nennen", "liste",
    "finde", "finden", "such", "suche", "suchen", "nachsehen", "nachschauen",
    "nachschlagen", "nachgucken", "sieh", "schau", "schaue", "prüfe", "pruefe",
    "kannst", "könntest", "koenntest", "kann", "könnte", "koennte", "soll", "sollte",
    "steht", "stehen", "drin", "darin", "dazu", "darüber", "darueber", "davon",
    "dokument", "dokumente", "dokumenten", "datei", "dateien", "pdf", "pdfs",
    "unterlagen", "sammlung", "ordner", "verzeichnis",
    "hast", "habe", "bereits", "ähnliche", "aehnliche", "ähnlichen", "aehnlichen",
    "ähnlich", "aehnlich", "passende", "passenden", "passt", "etwas", "irgendwas",
    "wessen", "wofür", "wofuer",
}
STOPWORDS |= FRAGEWOERTER

# Dateityp-Hinweise in der Frage -> zweite Suche nur in diesem Typ (Issue #166/#167)
TYP_HINWEISE: tuple[tuple[str, frozenset[str]], ...] = (
    ("office", frozenset({"excel", "xlsx", "xls", "tabelle", "tabellen", "arbeitsmappe",
                          "word", "docx", "office"})),
    ("mail", frozenset({"mail", "mails", "email", "emails", "e-mail", "e-mails", "nachricht"})),
)

# Hoechstens so viele Kandidaten holen, bevor Kopien entfernt und neu sortiert wird
KANDIDATEN_FAKTOR = 3


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
    # Phase 5 (PDFsuche-Integration): Dokument-Id im Suchindex und die Seite
    # der ersten Fundstelle (1-basiert; 0 = unbekannt), damit Zitate auf
    # Dokument UND Seite verlinken.
    dok_id: int = 0
    seite: int = 0
    # Zusatzangaben fuer den Prompt, z.B. ``bezug``, ``ordner``, ``hinweise``,
    # ``gemeinsame_kennungen`` (Issue #148, #166).
    extra: dict = field(default_factory=dict)


class RetrievalService:
    """
    Baut FTS5-Queries, extrahiert heuristische Filter, ruft
    ``Database.search_documents`` auf und produziert ``RetrievedDoc``s.

    Args:
        db: Datenquelle (:class:`~src.rag.daten.ChatDaten`), z.B.
            :class:`src.utils.database.Database` oder im Dienst
            :class:`src.search.pdfsm_daten.PdfsmDaten`.
        chat_config: Optionale :class:`ChatConfig`. Fallback auf
            :class:`ChatConfig` mit Defaults.
    """

    def __init__(self, db: Optional[ChatDaten], chat_config: Optional[ChatConfig] = None):
        self.db = db
        self.chat_config = chat_config or ChatConfig()

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def retrieve(self, question: str, k: int = None, zusatz: str = "") -> list[RetrievedDoc]:
        """
        Durchsucht den Index nach passenden Dokumenten zur Frage.

        1. Stopwords und Fragewoerter entfernen, Dateityp-Hinweis erkennen.
        2. Heuristische Filter extrahieren (Jahr, Betrag, Korrespondent).
        3. FTS5-OR-Query bauen und ``db.search_documents`` aufrufen; bei
           Dateityp-Hinweis eine zweite Suche nur in diesem Typ.
        4. Kopien entfernen, bei nahezu gleicher Relevanz neuere zuerst.
        5. Auszuege aus Fundstellen und Trefferseite erzeugen.

        Args:
            zusatz: Weitere Suchbegriffe (z.B. Korrespondent, Kategorie und
                Steuerjahr eines Bezugsdokuments, Issue #148). Sie erweitern
                die ODER-Abfrage, werden aber NICHT zu Filtern.
        """
        if k is None:
            k = self.chat_config.max_context_docs

        if not ((question and question.strip()) or (zusatz and zusatz.strip())):
            return []

        typ, hinweis_woerter = self._typ_hinweis(question or "")
        terms = [t for t in self._tokenize(self._strip_stopwords(question or ""))
                 if t.lower() not in hinweis_woerter]
        if zusatz:
            vorhanden = {t.lower() for t in terms}
            for t in self._tokenize(self._strip_stopwords(zusatz)):
                if t.lower() not in vorhanden:
                    vorhanden.add(t.lower())
                    terms.append(t)
        if not terms:
            return []

        filters = self._extract_filters(question or "")
        fts_query = self._build_fts5_query(terms)
        if not fts_query:
            return []

        kandidaten = self._suche(fts_query, limit=max(k * KANDIDATEN_FAKTOR, 12), **filters)
        if typ:
            typ_treffer = self._suche(fts_query, limit=k, typ=typ, **filters)
            for r in typ_treffer:
                r["_vorrang"] = 0
            kandidaten = typ_treffer + kandidaten
        if not kandidaten:
            return []

        liste = self._sortiere(self._ohne_kopien(kandidaten))
        return [self._to_retrieved_doc(r, idx + 1) for idx, r in enumerate(liste[:k])]

    def retrieve_kennungen(
        self,
        kennungen: Sequence[Kennung],
        k_je: int = 3,
        limit: Optional[int] = None,
        ausser=None,
    ) -> list[RetrievedDoc]:
        """Dokumente, die eine der Kennungen woertlich enthalten (Issue #166/#167).

        Je Kennung eine exakte Phrasensuche; vorn stehen Dokumente mit den
        meisten gemeinsamen benannten Kennungen (Vertrags-, Zaehlernummer ...),
        dann nach der Zahl aller gemeinsamen Kennungen. Jeder Treffer traegt in
        ``extra["gemeinsame_kennungen"]`` die Kennungen als Text ("226541 (Zählernummer)").

        Args:
            kennungen: Kennungen des Bezugsdokuments.
            k_je: Treffer je Kennung (das Bezugsdokument selbst zaehlt nicht mit).
            limit: Hoechstzahl der Treffer insgesamt (None = alle).
            ausser: Pfad, der nicht geliefert wird (das Bezugsdokument selbst).
        """
        treffer: dict[str, dict] = {}
        reihenfolge: list[str] = []
        k_je = max(1, int(k_je))
        for kennung in kennungen or ():
            abfrage = kennungs_abfrage(kennung.wert)
            if not abfrage:
                continue
            # Zwei mehr holen: der Bezug selbst und seine Kopie sind meist die besten Treffer
            genommen = 0
            for r in self._suche(abfrage, limit=k_je + 2):
                pfad = r.get("file_path") or ""
                if not pfad or (ausser and gleicher_pfad(pfad, ausser)):
                    continue
                if genommen >= k_je:
                    break
                genommen += 1
                schluessel = pfad.replace("\\", "/").casefold()
                if schluessel not in treffer:
                    treffer[schluessel] = {**r, "_kennungen": [], "_schluessel": schluessel}
                    reihenfolge.append(schluessel)
                if kennung not in treffer[schluessel]["_kennungen"]:
                    treffer[schluessel]["_kennungen"].append(kennung)
        if not treffer:
            return []
        liste = sorted(
            (treffer[s] for s in reihenfolge),
            key=lambda r: (
                -sum(1 for kn in r["_kennungen"] if getattr(kn, "benannt", False)),
                -len(r["_kennungen"]),
                reihenfolge.index(r["_schluessel"]),
            ),
        )
        liste = self._ohne_kopien(liste)
        if limit is not None:
            liste = liste[:max(0, int(limit))]
        docs = []
        for idx, r in enumerate(liste, start=1):
            doc = self._to_retrieved_doc(r, idx)
            doc.extra["gemeinsame_kennungen"] = [str(kn) for kn in r["_kennungen"]]
            docs.append(doc)
        return docs

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _suche(self, query: str, limit: int, **filters) -> list[dict]:
        """``db.search_documents`` defensiv: unbekannte Filter weglassen, Fehler -> leer."""
        try:
            return list(self.db.search_documents(query=query, limit=limit, **filters) or [])
        except TypeError:
            pass
        except Exception:
            return []
        # Aeltere DB-Fassungen kennen z.B. ``typ`` nicht: erst ohne typ, dann ohne alle Filter
        try:
            ohne_typ = {k: v for k, v in filters.items() if k != "typ"}
            if "typ" in filters:
                return list(self.db.search_documents(query=query, limit=limit, **ohne_typ) or [])
            return list(self.db.search_documents(query=query, limit=limit) or [])
        except TypeError:
            try:
                return list(self.db.search_documents(query=query, limit=limit) or [])
            except Exception:
                return []
        except Exception:
            return []

    @staticmethod
    def _typ_hinweis(question: str) -> tuple[str, set[str]]:
        """Dateityp aus der Frage ("Excel", "Mail") und die ausloesenden Woerter."""
        woerter = {t.lower() for t in re.findall(r"[\wäöüÄÖÜß\-]+", question or "")}
        for typ, hinweise in TYP_HINWEISE:
            if woerter & hinweise:
                return typ, set(hinweise)
        return "", set()

    @staticmethod
    def _ohne_kopien(rows: list[dict]) -> list[dict]:
        """Kopien derselben Datei nur einmal, erste Nennung gewinnt.

        Dateien: gleicher Name und gleiche Groesse (OneDrive- und Archivkopie).
        Mails: gleicher Betreff und gleiches Mail-Datum (dieselbe Mail in
        mehreren Postfaechern); ``groesse`` ist bei Mails die der mbox-Datei
        und taugt nicht als Merkmal.
        """
        gesehen: set = set()
        ergebnis = []
        for r in rows:
            pfad = (r.get("file_path") or "").replace("\\", "/").casefold()
            name = (r.get("filename") or "").casefold()
            if (r.get("typ") or "") == "mail":
                merkmal = r.get("datum")
            else:
                merkmal = r.get("groesse")
            schluessel_kopie = (name, merkmal) if name and merkmal else (name, (r.get("text_snippet") or "")[:120])
            if pfad in gesehen or schluessel_kopie in gesehen:
                continue
            gesehen.add(pfad)
            gesehen.add(schluessel_kopie)
            ergebnis.append(r)
        return ergebnis

    @staticmethod
    def _sortiere(rows: list[dict]) -> list[dict]:
        """Vorrang (Typ-Treffer) zuerst, dann Relevanz; bei nahezu gleicher Relevanz neuere zuerst.

        ``rang`` ist der bm25-Wert des Index (kleiner = besser, Namens- und
        Metadatentreffer -5). Auf ganze Zahlen gerundet bilden aehnliche
        Werte eine Gruppe, innerhalb derer das juengere Dokument vorn steht.
        Fehlen ``rang``/``datum`` (fremde DB-Fassungen), bleibt die Reihenfolge.
        """
        def schluessel(paar):
            pos, r = paar
            try:
                rang = round(float(r.get("rang"))) if r.get("rang") is not None else None
            except (TypeError, ValueError):
                rang = None
            try:
                datum = float(r.get("datum") or 0)
            except (TypeError, ValueError):
                datum = 0.0
            return (r.get("_vorrang", 1), rang if rang is not None else pos, -datum, pos)

        return [r for _pos, r in sorted(enumerate(rows), key=schluessel)]

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
        """Wandelt ein DB-Dict in ein ``RetrievedDoc`` mit Auszug."""
        return RetrievedDoc(
            index=index,
            file_path=raw.get("file_path", "") or "",
            filename=raw.get("filename", "") or "",
            text_snippet=self._auszug(raw),
            rank=index,
            kategorie=raw.get("kategorie", "") or "",
            steuerjahr=raw.get("steuerjahr", "") or "",
            betrag=raw.get("betrag", "") or "",
            korrespondent=raw.get("korrespondent", "") or "",
            # Phase 3 (Issue #25): pdf_id aus dem DB-Dict uebernehmen.
            # Default "", damit alte Aufrufer ohne pdf_id-Feld nicht
            # brechen (rueckwaertskompatibel).
            pdf_id=raw.get("pdf_id", "") or "",
            dok_id=int(raw.get("dok_id") or 0),
            seite=int(raw.get("seite") or 0),
        )

    def _auszug(self, raw: dict) -> str:
        """Textauszug eines Treffers (Issue #166/#167).

        Fundstellen der Suche (mit ``>>>``/``<<<`` markiert) und der Text der
        Trefferseite bzw. des Tabellenblatts, zusammen hoechstens
        ``snippet_max_chars``. Ohne Seitentext (fremde DB, Namenstreffer ohne
        Fundstelle) wie bisher Anfang und Ende des Dokumenttexts.
        """
        budget = int(self.chat_config.snippet_max_chars or 2000)
        stellen = " ".join((raw.get("text_snippet") or "").split())
        dok_id = int(raw.get("dok_id") or 0)
        seite = int(raw.get("seite") or 0)
        seitentext = self._seitentext(dok_id, seite) if dok_id and seite else ""
        if not seitentext:
            text = raw.get("extracted_text") or stellen
            return self._build_snippet(text, budget)

        typ = raw.get("typ") or ""
        if typ == "pdf":
            kopf = f"--- Seite {seite} ---"
        elif typ == "office" and (raw.get("format") or "") in ("xlsx", "xlsm", "xls"):
            kopf = f"--- Blatt {seite} ---"
        else:
            kopf = "--- Text ---"
        teile = []
        if stellen:
            teile.append(f"Fundstellen (markiert mit >>> <<<): {stellen}")
        rest = budget - sum(len(t) + 1 for t in teile) - len(kopf) - 1
        if rest < 200:
            rest = 200
        if len(seitentext) > rest:
            seitentext = seitentext[:rest].rstrip() + "\n[... gekürzt]"
        teile.append(kopf)
        teile.append(seitentext)
        return "\n".join(teile)

    def _seitentext(self, dok_id: int, seite: int) -> str:
        """Text einer Seite aus dem Suchindex; leer, wenn die DB keinen Index hat."""
        suchindex = getattr(self.db, "suchindex", None)
        if suchindex is None or not hasattr(suchindex, "seiten_text"):
            return ""
        try:
            seiten = suchindex.seiten_text(dok_id, seite, seite) or []
        except Exception:  # noqa: BLE001 - Index ist optional
            return ""
        texte = [(s.get("text") or "") for s in seiten if isinstance(s, dict)]
        return "\n".join(t for t in texte if t).strip()

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

"""
RAG-Controller fuer PDF Sortier Meister (Phase 19 / M1).

Orchestriert den RAG-Chat-Workflow:

    Frage -> Retrieval (FTS5) -> LLM (optional) -> CitationParser -> RAGResponse

Der Controller haelt zusaetzlich eine ``ChatSession`` (Konversationshistorie)
und einen simplen LRU-Cache fuer Frage/Antwort-Paaren, damit
wiederholt gestellte Fragen nicht erneut das LLM rufen.

Mit Bezugsdokument (Issue #148, #166/#167) laeuft das Retrieval zweigleisig:
Kennungen aus dem Bezug (Vertrags-, Zaehler-, Kundennummer ...) holen die
damit verknuepften Dokumente, die Frage selbst die uebrigen Treffer. Die
Kennungs-Treffer stehen vorn und tragen die gemeinsamen Kennungen im Prompt,
damit die KI die Kette "gleiche Vertragsnummer -> Abnahmestelle" sieht.

Werkzeuge (Issue #166/#167, Phase 2): Kann das Modell Werkzeuge
(``llm_provider.unterstuetzt_werkzeuge()``) und ist ``chat_config.werkzeuge_aktiv``,
laeuft statt des einen LLM-Aufrufs eine Schleife: Das Modell sucht und liest
selbst ueber den :class:`~src.rag.werkzeuge.Werkzeugkasten`, hoechstens
``chat_config.max_werkzeug_schritte`` Modellaufrufe lang. Das Bezugsdokument
und die Phase-1-Treffer sind vorab als D1, D2, ... registriert; die Zitate
``[N]`` der Antwort meinen diese Nummern. Schlaegt schon der erste Schritt
fehl (Modell ohne Werkzeuge), geht es auf dem alten Weg weiter.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.ml.llm_provider import WerkzeugAntwort
from src.rag.bezug import (
    BEZUG_FELDER,
    BEZUG_MAX_ZEICHEN,
    KENNUNG_TREFFER_JE,
    SUCH_FELDER,
    Bezug,
    ablageort,
    als_bezug,
    frage_betrifft_ordner,
    gleicher_pfad,
    kennungen_aus_text,
)
from src.rag.chat_session import ChatSession, ChatTurn
from src.rag.citation import Citation, CitationParser
from src.rag.prompts import (
    SCAN_EINGANG_HINWEIS,
    SORTIERLOGIK_PRAEFIX,
    SYSTEM_PROMPT,
    build_context_block,
    build_system_prompt_werkzeuge,
    build_user_prompt,
)
from src.rag.retrieval import RetrievedDoc, RetrievalService
from src.rag.werkzeuge import Werkzeugkasten

# Volltext des Bezugsdokuments hoechstens so weit lesen (der Auszug nimmt
# davon Anfang und Ende, siehe RetrievalService._build_snippet; die
# Kennungen werden aus dem ganzen gelesenen Text gezogen)
BEZUG_LESE_ZEICHEN = 50000
# Mindestens so viele Plaetze im Kontext bleiben den Treffern zur Frage,
# wenn Kennungs-Treffer dazukommen
FRAGE_TREFFER_MINDESTENS = 2
# Werkzeug-Schleife (Issue #166/#167, Phase 2): Rueckfall, falls die Konfiguration
# keinen Wert hat
WERKZEUG_SCHRITTE_STANDARD = 8
# Platz fuer die Antwort. 1000 reichten Denkmodellen (z.B. Gemini Flash) nicht:
# das Denken zaehlt mit, die Antwort brach nach wenigen Woertern ab
ANTWORT_TOKENS = 4000
ANTWORT_TOKENS_FAKTOR = 3  # Wiederholung einer abgeschnittenen Antwort
ABGESCHNITTEN_HINWEIS = "\n\n_(Die Antwort wurde vom Modell am Token-Limit abgeschnitten.)_"
ABGEBROCHEN_TEXT = "Abgebrochen."
# Aufforderungen im letzten Schritt der Schleife (Live-Test: gpt-oss rief sonst
# trotz leerer Werkzeugliste weiter auf und lieferte keinen Text)
LETZTER_SCHRITT_HINWEIS = (
    "Das war der letzte Werkzeugschritt. Beantworte die Frage jetzt mit dem, was du "
    "bisher gefunden hast - ohne weitere Werkzeugaufrufe. Nenne die Quellen als [N] und "
    "sage, was offen geblieben ist."
)
LETZTER_SCHRITT_NACHDRUCK = (
    "Es stehen keine Werkzeuge mehr zur Verfügung. Antworte jetzt in Prosa auf die Frage "
    "und fasse die bisherigen Ergebnisse zusammen."
)


@dataclass
class RAGResponse:
    """Antwort des RAG-Controllers auf eine Nutzerfrage."""

    answer_text: str
    citations: list[Citation] = field(default_factory=list)
    retrieved_docs: list[RetrievedDoc] = field(default_factory=list)
    used_llm: bool = False
    # Falls True hat das LLM mindestens eine Quelle erfunden, die im
    # Retrieval nicht vorkam. Die GUI kann darauf hinweisen.
    has_hallucinated_citations: bool = False
    # Issue #148: Zusatzinfo fuer den Offline-Rueckfall, z.B. der Vorschlag
    # der Sortierlogik bei "In welchen Ordner gehoert dieses PDF?"
    hinweis: str = ""
    # Issue #166/#167 (Phase 2): die Werkzeugaufrufe des Modells als
    # :class:`~src.rag.werkzeuge.Schritt` (fuer die Anzeige "Was hat die KI
    # getan?") und ob die Antwort auf dem Werkzeug-Weg entstand.
    schritte: list = field(default_factory=list)
    werkzeuge_benutzt: bool = False
    # Phase 3 (Issue #166/#167): Zielordner, in dem die zitierten Belege liegen
    # (absoluter Pfad, Anzeige relativ zum Zielordner, Begruendung wie
    # "belegt durch [2], [3]"); leer, wenn die Zitate keinen gemeinsamen
    # Zielordner haben. Die Oberflaeche bietet daraus "Nach … verschieben" an.
    ordner_vorschlag: str = ""
    ordner_anzeige: str = ""
    ordner_begruendung: str = ""


class RAGController:
    """Orchestriert Retrieval + LLM fuer den Chat-Tab (Phase 19 / M1).

    Verwendung in M2 (GUI)::

        controller = RAGController(db, llm_provider, chat_config)
        response = controller.ask("Was habe ich 2023 fuer Strom bezahlt?")
        if response.used_llm:
            ... Antwort im Chat anzeigen ...
        else:
            ... Offline-Treffer-Liste anzeigen ...
    """

    def __init__(self, db, llm_provider, chat_config) -> None:
        """
        Args:
            db: :class:`~src.utils.database.Database`-Instanz mit
                ``search_documents(query, limit, **filters)``.
            llm_provider: :class:`~src.ml.llm_provider.LLMProvider` (oder
                ``None`` fuer reinen Offline-Modus).
            chat_config: :class:`~src.utils.config.ChatConfig` mit
                ``max_context_docs``, ``max_history_turns``,
                ``snippet_max_chars``, ``cache_size``, ``max_tokens_answer``.
        """
        self.db = db
        self.llm_provider = llm_provider
        self.chat_config = chat_config
        self.chat_session = ChatSession()
        self.retrieval = RetrievalService(db, chat_config=chat_config)
        self.citation_parser = CitationParser()
        # LRU-Cache: Key -> RAGResponse
        cache_size = getattr(chat_config, "cache_size", 100) or 100
        self._cache: "OrderedDict[str, RAGResponse]" = OrderedDict()
        self._cache_max = cache_size

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def ask(
        self,
        question: str,
        bezug=None,
        abbruch: threading.Event | None = None,
        fortschritt: Callable[[str], None] | None = None,
    ) -> RAGResponse:
        """Beantwortet eine Nutzerfrage via Retrieval + optional LLM.

        Args:
            question: Freitext-Frage des Nutzers.
            bezug: Optionales Bezugsdokument (Issue #148): ein
                :class:`~src.rag.bezug.Bezug`, ein Pfad oder ``None``. Es
                steht als Dokument 1 unter ``BEZUGSDOKUMENT`` im Kontext;
                Dokumente mit gemeinsamen Kennungen (Issue #166/#167) folgen
                zuerst, dann die Treffer zur Frage, angereichert um
                Korrespondent, Kategorie und Steuerjahr des Bezugs.
            abbruch: Optionales ``threading.Event`` (Issue #166/#167): ist es
                gesetzt, bricht die Werkzeug-Schleife vor dem naechsten
                Modell- oder Werkzeugaufruf ab (Antwort ``"Abgebrochen."``).
            fortschritt: Optionaler Callback fuer die Statuszeile, z.B.
                ``"KI denkt (Schritt 2/6) …"`` oder ``"Suche „226541“ …"``.

        Returns:
            :class:`RAGResponse` mit Antwort, Citations und Retrieval-Docs.
        """
        question = (question or "").strip()
        if not question:
            return RAGResponse(
                answer_text="Bitte stelle eine konkrete Frage.",
                citations=[],
                retrieved_docs=[],
                used_llm=False,
            )

        bezug = als_bezug(bezug)

        # 1) Cache-Check
        cache_key = self._cache_key(question, bezug)
        if cache_key in self._cache:
            # LRU: ans Ende schieben
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        # 2) Datenbank-Leerlauf pruefen (M3-Hardening).
        # Wenn ueberhaupt nichts indexiert ist, brauchen wir weder Retrieval
        # noch LLM und liefern eine ehrliche Antwort. Mit Bezugsdokument
        # laesst sich trotzdem etwas zu diesem Dokument sagen (Issue #148).
        if bezug is None and not self._has_indexed_documents():
            return RAGResponse(
                answer_text="Keine Dokumente indiziert.",
                citations=[],
                retrieved_docs=[],
                used_llm=False,
            )

        # 3) Retrieval (immer, auch ohne LLM fuer Offline-Fallback)
        k = getattr(self.chat_config, "max_context_docs", 8) or 8
        bezug_doc = self._bezug_dokument(bezug) if bezug is not None else None
        try:
            if bezug_doc is None:
                retrieved = self.retrieval.retrieve(question, k=k) or []
            else:
                retrieved = self._treffer_zum_bezug(question, bezug, bezug_doc, k)
        except Exception as e:
            return RAGResponse(
                answer_text=f"Suche fehlgeschlagen: {e}",
                citations=[],
                retrieved_docs=[],
                used_llm=False,
            )

        hinweis = ""
        if bezug_doc is not None and frage_betrifft_ordner(question):
            vorschlaege = "; ".join(bezug.sortier_vorschlaege) or "keiner"
            bezug_doc.extra.setdefault("hinweise", []).append(f"{SORTIERLOGIK_PRAEFIX} {vorschlaege}")
            if bezug.sortier_vorschlaege:
                hinweis = f"Vorschlag der Sortierlogik: {vorschlaege}"

        # 4) LLM-Aufruf wenn verfuegbar
        if self.llm_provider is not None and self._is_llm_available():
            if bezug_doc is None:
                kontext_docs = list(retrieved)
            else:
                # Bezug ist [D1], die Suchtreffer folgen ab [D2] mit Ablageort
                weitere = [_mit_index(d, i) for i, d in enumerate(retrieved, start=2)]
                for d in weitere:
                    if not isinstance(d, dict):
                        d.extra = {**(d.extra or {}), "ordner": ablageort(d.file_path, bezug.wurzeln)}
                kontext_docs = [bezug_doc, *weitere]
            if self._werkzeuge_moeglich():
                # Issue #166/#167 (Phase 2): das Modell sucht und liest selbst
                response = self._ask_mit_werkzeugen(
                    question, bezug, kontext_docs, abbruch=abbruch, fortschritt=fortschritt,
                )
            else:
                response = self._ask_llm(question, kontext_docs)
        elif not retrieved:
            # Offline-Modus UND keine Quellen gefunden: ehrliche
            # Standard-Antwort statt leerer Text (M3-Hardening).
            response = RAGResponse(
                answer_text="Keine passenden Dokumente gefunden.",
                citations=[],
                retrieved_docs=[],
                used_llm=False,
                hinweis=hinweis,
            )
        else:
            # Offline-Modus MIT Quellen: bisheriges Verhalten (leerer
            # answer_text, damit die GUI die Treffer-Liste anzeigen kann).
            response = RAGResponse(
                answer_text="",
                citations=[],
                retrieved_docs=retrieved,
                used_llm=False,
                hinweis=hinweis,
            )

        # 4b) Phase 3: Zielordner der zitierten Belege (fuer "Nach … verschieben")
        self._ordner_vorschlag_setzen(response, bezug)

        # 5) Turn in ChatSession protokollieren - nicht nach einem Abbruch
        # (Issue #166/#167): eine Frage ohne Antwort stuende sonst als offener
        # Nutzer-Turn im Prompt der naechsten Frage (Review-Befund)
        abgebrochen = (not response.used_llm) and response.answer_text == ABGEBROCHEN_TEXT
        if abgebrochen:
            return response
        self.chat_session.add_turn(ChatTurn(
            role="user",
            content=question,
            citations=[],
            timestamp=datetime.now(),
        ))
        if response.used_llm:
            self.chat_session.add_turn(ChatTurn(
                role="assistant",
                content=response.answer_text,
                citations=[
                    {
                        "index": c.index,
                        "filename": c.filename,
                        "file_path": c.file_path,
                        # Phase 3 (Issue #25): pdf_id in der Historie
                        # mitschreiben, damit spaetere Folgefragen den
                        # stabilen Identitaetsanker haben.
                        "pdf_id": c.pdf_id,
                        "seite": getattr(c, "seite", 0),
                    }
                    for c in response.citations
                ],
                timestamp=datetime.now(),
            ))

        # 6) LRU-Cache schreiben - nicht bei Abbruch oder Werkzeugfehler
        # (Issue #166/#167): die naechste gleiche Frage soll es neu versuchen
        if response.used_llm or not response.werkzeuge_benutzt:
            self._cache_put(cache_key, response)
        return response

    def reset(self) -> None:
        """Leert Konversationshistorie UND LRU-Cache."""
        self.chat_session.clear()
        self._cache.clear()

    # ------------------------------------------------------------------ #
    # Intern
    # ------------------------------------------------------------------ #

    def _treffer_zum_bezug(self, question: str, bezug: Bezug, bezug_doc: RetrievedDoc, k: int) -> list:
        """Suchtreffer mit Bezugsdokument (Issue #148, #166/#167).

        Zuerst Dokumente, die eine Kennung des Bezugs woertlich enthalten
        (hoechstens ``k - FRAGE_TREFFER_MINDESTENS``), dann die Treffer zur
        Frage. Das Bezugsdokument selbst und Doppelte fallen heraus; die
        Nummern laufen ab 1 (der Aufrufer setzt den Bezug davor).
        """
        kennungen = bezug_doc.extra.get("kennung_objekte") or []
        kennung_treffer: list = []
        if kennungen:
            kennung_treffer = self.retrieval.retrieve_kennungen(
                kennungen, k_je=KENNUNG_TREFFER_JE,
                limit=max(1, k - FRAGE_TREFFER_MINDESTENS), ausser=bezug.pfad,
            ) or []
        # Einer mehr: das Bezugsdokument selbst kann unter den Treffern sein
        frage_treffer = self.retrieval.retrieve(
            question, k=k + 1, zusatz=self._bezug_suchbegriffe(bezug_doc),
        ) or []
        zusammen = list(kennung_treffer)
        for d in frage_treffer:
            pfad = _feld(d, "file_path")
            if gleicher_pfad(pfad, bezug.pfad):
                continue
            if any(gleicher_pfad(pfad, _feld(e, "file_path")) for e in zusammen):
                continue
            zusammen.append(d)
        return [_mit_index(d, i) for i, d in enumerate(zusammen[:k], start=1)]

    def _has_indexed_documents(self) -> bool:
        """True, wenn die DB mindestens ein indexiertes Dokument enthaelt.

        Defensiv: wenn die DB fehlt oder die Methode nicht existiert,
        wird True angenommen, damit der normale Flow weiterlaeuft
        (sonst wuerde ein falsches "Keine Dokumente indiziert." entstehen).
        """
        db = self.db
        if db is None:
            return True
        count_fn = getattr(db, "get_search_index_count", None)
        if not callable(count_fn):
            return True
        try:
            return bool(count_fn() > 0)
        except Exception:  # noqa: BLE001 - defensiv
            return True

    def _is_llm_available(self) -> bool:
        """True, wenn der LLM-Provider verfuegbar ist (defensiv gewrappt)."""
        if self.llm_provider is None:
            return False
        avail_fn = getattr(self.llm_provider, "is_available", None)
        if not callable(avail_fn):
            return False
        try:
            return bool(avail_fn())
        except Exception:  # noqa: BLE001 - defensiv
            return False

    def _ask_llm(self, question: str, retrieved: list[RetrievedDoc]) -> RAGResponse:
        """Baut Prompts, ruft das LLM und parst Citations."""
        if not retrieved:
            # Keine Quellen gefunden -> ehrliche Antwort provozieren
            user_prompt = build_user_prompt(
                question=question,
                history=self._history_for_llm(),
                context_block=(
                    "=== DOKUMENTE ===\n"
                    "(Keine Dokumente gefunden.)\n"
                    "=== ENDE DOKUMENTE ==="
                ),
            )
        else:
            # Kontext-Block mit allen retrieved Docs
            docs_for_prompt = [self._doc_to_prompt_dict(d) for d in retrieved]
            context_block = build_context_block(docs_for_prompt)
            user_prompt = build_user_prompt(
                question=question,
                history=self._history_for_llm(),
                context_block=context_block,
            )

        max_tokens = getattr(self.chat_config, "max_tokens_answer", ANTWORT_TOKENS) or ANTWORT_TOKENS

        try:
            raw_answer = self.llm_provider.answer_with_context(
                system_prompt=SYSTEM_PROMPT,
                context_docs=[
                    self._doc_to_prompt_dict(d) for d in retrieved
                ],
                user_question=question,
                max_tokens=max_tokens,
            )
        except Exception as e:
            # LLM-Fehler -> wir liefern immerhin die Quellen
            return RAGResponse(
                answer_text=f"LLM-Aufruf fehlgeschlagen: {e}",
                citations=[],
                retrieved_docs=retrieved,
                used_llm=False,
            )

        cleaned, valid, dropped = self.citation_parser.parse(raw_answer, retrieved)
        return RAGResponse(
            answer_text=cleaned,
            citations=valid,
            retrieved_docs=retrieved,
            used_llm=True,
            has_hallucinated_citations=bool(dropped),
        )

    # ------------------------------------------------------------------ #
    # Werkzeug-Schleife (Issue #166/#167, Phase 2)                       #
    # ------------------------------------------------------------------ #

    def _werkzeuge_moeglich(self) -> bool:
        """True, wenn der Chat mit Werkzeugen laufen soll: Einstellung an und Provider kann es.

        Defensiv: Provider ohne ``unterstuetzt_werkzeuge``/``chat_mit_werkzeugen``
        (Stubs, alte Fassungen) gehen den bisherigen Weg.
        """
        if not getattr(self.chat_config, "werkzeuge_aktiv", False):
            return False
        provider = self.llm_provider
        if provider is None or not callable(getattr(provider, "chat_mit_werkzeugen", None)):
            return False
        kann = getattr(provider, "unterstuetzt_werkzeuge", None)
        if not callable(kann):
            return False
        try:
            return bool(kann())
        except Exception:  # noqa: BLE001 - defensiv
            return False

    def _ask_mit_werkzeugen(
        self,
        question: str,
        bezug: Bezug | None,
        kontext_docs: list,
        abbruch: threading.Event | None = None,
        fortschritt: Callable[[str], None] | None = None,
    ) -> RAGResponse:
        """Werkzeug-Schleife: Modell ruft Werkzeuge, bis es antwortet (Issue #166/#167).

        ``kontext_docs`` (Bezug als [D1] und die Phase-1-Treffer) werden vorab
        im :class:`Werkzeugkasten` registriert und stehen wie bisher im
        ``=== DOKUMENTE ===``-Block der ersten Nutzernachricht. Dann wird
        ``chat_mit_werkzeugen`` hoechstens ``max_werkzeug_schritte``-mal
        gerufen; im letzten Schritt ohne Werkzeuge, damit das Modell antwortet.

        * Fehler (``WerkzeugAntwort.fehler``) oder leerer Text im ERSTEN
          Schritt: Rueckfall auf :meth:`_ask_llm` (Phase-1-Weg).
        * Fehler spaeter: ``"Werkzeugaufruf fehlgeschlagen: …"`` mit den bis
          dahin gesammelten Dokumenten und Schritten.
        * ``abbruch`` gesetzt (vor jedem Modell- und Werkzeugaufruf geprueft):
          ``"Abgebrochen."``.
        """
        kasten = Werkzeugkasten(
            self.db,
            self.chat_config,
            bezug=bezug,
            wurzeln=bezug.wurzeln if bezug is not None else (),
            scan_ordner=bezug.scan_ordner if bezug is not None else None,
            sortier_vorschlaege=bezug.sortier_vorschlaege if bezug is not None else (),
            sql_erlaubt=bool(getattr(self.chat_config, "sql_erlaubt", False)),
            retrieval=self.retrieval,
        )
        for d in kontext_docs:
            kasten.registriere(_als_retrieved_doc(d))

        max_schritte = getattr(self.chat_config, "max_werkzeug_schritte", WERKZEUG_SCHRITTE_STANDARD)
        try:
            max_schritte = max(1, int(max_schritte or WERKZEUG_SCHRITTE_STANDARD))
        except (TypeError, ValueError):
            max_schritte = WERKZEUG_SCHRITTE_STANDARD
        max_tokens = getattr(self.chat_config, "max_tokens_answer", ANTWORT_TOKENS) or ANTWORT_TOKENS

        docs_for_prompt = [self._doc_to_prompt_dict(d) for d in kasten.dokumente()]
        nachrichten: list[dict] = [
            {"role": "system", "content": build_system_prompt_werkzeuge(max_schritte)},
            {"role": "user", "content": build_user_prompt(
                question=question,
                history=self._history_for_llm(),
                context_block=build_context_block(docs_for_prompt),
            )},
        ]
        werkzeuge = kasten.definitionen()
        aufruf_nr = 0

        for schritt in range(1, max_schritte + 1):
            if _abgebrochen(abbruch):
                return self._antwort_abgebrochen(kasten)
            _melde(fortschritt, f"KI denkt (Schritt {schritt}/{max_schritte}) …")
            letzter = schritt == max_schritte
            if letzter:
                # Letzter Schritt: keine Werkzeuge mehr und eine klare Aufforderung
                # zu antworten - ohne sie rufen Modelle wie gpt-oss weiter auf
                nachrichten.append({"role": "user", "content": LETZTER_SCHRITT_HINWEIS})
            antwort = self._werkzeug_schritt(nachrichten, [] if letzter else werkzeuge, max_tokens)

            fehler = str(getattr(antwort, "fehler", "") or "")
            aufrufe = list(getattr(antwort, "aufrufe", None) or [])
            text = str(getattr(antwort, "text", "") or "")
            if letzter and aufrufe:
                # Das Modell wollte trotz leerer Werkzeugliste weiter rufen:
                # der Text, falls vorhanden, ist die Antwort
                aufrufe = []
            if letzter and not fehler and not text.strip():
                # Noch ein Anlauf mit Nachdruck (zaehlt nicht als Werkzeugschritt);
                # bleibt er leer, gibt es den Zwischenstand statt eines Fehlers
                _melde(fortschritt, "KI formuliert die Antwort …")
                nachrichten.append({"role": "user", "content": LETZTER_SCHRITT_NACHDRUCK})
                antwort = self._werkzeug_schritt(nachrichten, [], max_tokens)
                fehler = str(getattr(antwort, "fehler", "") or "")
                text = str(getattr(antwort, "text", "") or "")
                if not fehler and not text.strip():
                    return self._antwort_zwischenstand(kasten, max_schritte)
            if not fehler and not aufrufe and not text.strip():
                fehler = "Leere Antwort des Modells."
            if fehler:
                if schritt == 1:
                    grund = " ".join(fehler.split())[:90]
                    _melde(fortschritt, f"Werkzeuge nicht verfügbar ({grund}) - Antwort ohne Werkzeuge …")
                    return self._ask_llm(question, kontext_docs)
                return RAGResponse(
                    answer_text=f"Werkzeugaufruf fehlgeschlagen: {fehler}",
                    citations=[],
                    retrieved_docs=kasten.dokumente(),
                    used_llm=False,
                    schritte=list(kasten.protokoll),
                    werkzeuge_benutzt=True,
                )
            if not aufrufe:
                if getattr(antwort, "abgeschnitten", False):
                    # Am Token-Limit abgebrochen (Denkmodelle verbrauchen einen Teil des
                    # Budgets, bevor sie schreiben): einmal mit mehr Platz wiederholen
                    _melde(fortschritt, "Antwort war abgeschnitten - noch einmal mit mehr Platz …")
                    neu = self._werkzeug_schritt(nachrichten, [], max_tokens * ANTWORT_TOKENS_FAKTOR)
                    neu_text = str(getattr(neu, "text", "") or "")
                    if not getattr(neu, "fehler", "") and len(neu_text.strip()) > len(text.strip()):
                        antwort, text = neu, neu_text
                    if getattr(antwort, "abgeschnitten", False):
                        text = text.rstrip() + ABGESCHNITTEN_HINWEIS
                return self._antwort_mit_werkzeugen(text, kasten)

            # Werkzeuge ausfuehren; Assistenten- und tool-Nachrichten anhaengen
            for aufruf in aufrufe:
                aufruf_nr += 1
                if not getattr(aufruf, "id", ""):
                    aufruf.id = f"aufruf_{aufruf_nr}"
            nachrichten.append({
                "role": "assistant",
                "content": text,
                "aufrufe": aufrufe,
                "roh": getattr(antwort, "roh", None),
            })
            for aufruf in aufrufe:
                if _abgebrochen(abbruch):
                    return self._antwort_abgebrochen(kasten)
                _melde(fortschritt, _aufruf_beschreibung(aufruf))
                ergebnis = kasten.ausfuehren(aufruf)
                if kasten.protokoll:
                    _melde(fortschritt, kasten.protokoll[-1].zusammenfassung)
                nachrichten.append({
                    "role": "tool",
                    "content": ergebnis,
                    "aufruf_id": aufruf.id,
                    "name": str(getattr(aufruf, "name", "") or ""),
                })

        # Unerreichbar (der letzte Schritt antwortet immer), zur Sicherheit
        return RAGResponse(
            answer_text=f"Werkzeugaufruf fehlgeschlagen: keine Antwort nach {max_schritte} Schritten.",
            citations=[],
            retrieved_docs=kasten.dokumente(),
            used_llm=False,
            schritte=list(kasten.protokoll),
            werkzeuge_benutzt=True,
        )

    def _antwort_mit_werkzeugen(self, text: str, kasten: Werkzeugkasten) -> RAGResponse:
        """Endtext der Schleife: Zitate gegen die D-Nummern pruefen, zitierte Dokumente markieren."""
        cleaned, valid, dropped = self.citation_parser.parse(text, kasten.dokumente())
        for c in valid:
            kasten.markiere(c.index, "zitiert")
        return RAGResponse(
            answer_text=cleaned,
            citations=valid,
            retrieved_docs=kasten.dokumente(),
            used_llm=True,
            has_hallucinated_citations=bool(dropped),
            schritte=list(kasten.protokoll),
            werkzeuge_benutzt=True,
        )

    def _werkzeug_schritt(self, nachrichten: list[dict], werkzeuge: list, max_tokens: int) -> WerkzeugAntwort:
        """Ein Modellaufruf der Schleife; Exceptions und None werden zu ``fehler``."""
        try:
            antwort = self.llm_provider.chat_mit_werkzeugen(
                nachrichten=nachrichten, werkzeuge=werkzeuge, max_tokens=max_tokens,
            )
        except Exception as e:  # noqa: BLE001 - Provider sollen nicht werfen, zur Sicherheit
            return WerkzeugAntwort(fehler=str(e) or type(e).__name__)
        if antwort is None:
            return WerkzeugAntwort(fehler="Keine Antwort vom Provider.")
        return antwort

    @staticmethod
    def _antwort_zwischenstand(kasten: Werkzeugkasten, max_schritte: int) -> RAGResponse:
        """Das Modell hat auch nach der Aufforderung nichts formuliert: der Zwischenstand als Antwort.

        Statt "Werkzeugaufruf fehlgeschlagen" bekommt der Nutzer, was die
        Werkzeuge ergeben haben, und kann gezielt nachfragen.
        """
        zeilen = [f"Ich konnte die Frage in {max_schritte} Schritten nicht abschließend beantworten. "
                  "Das haben die Werkzeuge bisher ergeben:"]
        for s in kasten.protokoll:
            zeilen.append(f"- {s.zusammenfassung}")
        gelesen = [d for d in kasten.dokumente() if (d.extra or {}).get("status") in ("gelesen", "zitiert")]
        if gelesen:
            zeilen.append("Gelesene Dokumente: " + ", ".join(f"[{d.index}] {d.filename}" for d in gelesen))
        zeilen.append("Stelle die Frage bitte enger oder nenne das Dokument, in dem ich nachsehen soll.")
        return RAGResponse(
            answer_text="\n".join(zeilen),
            citations=[],
            retrieved_docs=kasten.dokumente(),
            used_llm=True,
            schritte=list(kasten.protokoll),
            werkzeuge_benutzt=True,
        )

    @staticmethod
    def _ordner_vorschlag_setzen(response: RAGResponse, bezug: Optional[Bezug]) -> None:
        """Traegt den Zielordner der zitierten Belege ein (Phase 3, nur mit Bezug und Zitaten)."""
        if bezug is None or not response.used_llm or not response.citations:
            return
        try:
            from src.rag.verknuepfung import belegter_ordner
            pfad, anzeige, begruendung = belegter_ordner(
                response.citations, response.retrieved_docs, bezug.wurzeln, ausser=bezug.pfad,
            )
        except Exception:  # noqa: BLE001 - der Vorschlag ist optional
            return
        response.ordner_vorschlag = pfad
        response.ordner_anzeige = anzeige
        response.ordner_begruendung = begruendung

    @staticmethod
    def _antwort_abgebrochen(kasten: Werkzeugkasten) -> RAGResponse:
        return RAGResponse(
            answer_text=ABGEBROCHEN_TEXT,
            citations=[],
            retrieved_docs=kasten.dokumente(),
            used_llm=False,
            schritte=list(kasten.protokoll),
            werkzeuge_benutzt=True,
        )

    def _history_for_llm(self) -> list[dict]:
        """Letzte N Turns als kompakte History fuer den LLM-Prompt."""
        n = getattr(self.chat_config, "max_history_turns", 4) or 4
        recent = self.chat_session.get_recent(n)
        return [{"role": t.role, "content": t.content} for t in recent]

    def _doc_to_prompt_dict(self, doc: RetrievedDoc) -> dict:
        """Wandelt einen RetrievedDoc in das Dict-Format, das die
        LLM-Provider und die Prompt-Builder erwarten."""
        if isinstance(doc, dict):
            return doc
        prompt_dict = {
            "index": getattr(doc, "index", 0),
            "filename": getattr(doc, "filename", ""),
            "file_path": getattr(doc, "file_path", ""),
            "kategorie": getattr(doc, "kategorie", ""),
            "steuerjahr": getattr(doc, "steuerjahr", ""),
            "betrag": getattr(doc, "betrag", ""),
            "korrespondent": getattr(doc, "korrespondent", ""),
            "text_snippet": getattr(doc, "text_snippet", ""),
            # Phase 3 (Issue #25): pdf_id in den Prompt-Dict
            # durchreichen, damit LLM-Provider sie ebenfalls sehen.
            "pdf_id": getattr(doc, "pdf_id", ""),
            # Phase 5: Seite der Fundstelle (fuer Zitate auf Dokument und Seite)
            "seite": getattr(doc, "seite", 0),
        }
        # Issue #148: Bezugsdokument, Ablageort und Hinweise;
        # Issue #166/#167: Kennungen (nur wenn gesetzt)
        extra = getattr(doc, "extra", None) or {}
        for key in ("bezug", "ordner", "hinweise", "kennungen", "gemeinsame_kennungen"):
            if extra.get(key):
                prompt_dict[key] = extra[key]
        return prompt_dict

    def _bezug_dokument(self, bezug: Bezug) -> RetrievedDoc:
        """Das Bezugsdokument als ``[D1]`` (Issue #148).

        Text und Metadaten kommen aus dem Suchindex; was dort fehlt (Datei
        noch nicht indexiert, keine Metadaten gespeichert), aus dem
        :class:`Bezug` (``pdf_cache`` bzw. KI-Vorschlag der GUI).

        Issue #166/#167: Die Kennungen des Texts stehen in
        ``extra["kennungen"]`` (Text fuer den Prompt) und
        ``extra["kennung_objekte"]`` (fuer die Suche). Liegt das Dokument im
        Scan-Eingang, gibt es keinen Ablageort, sondern den Hinweis
        ``SCAN_EINGANG_HINWEIS``. Der ganze gelesene Text steht in
        ``extra["volltext"]``, damit ``dokument_lesen`` (Phase 2) das
        Bezugsdokument auch ohne Suchindex liefern kann.
        """
        meta: dict = {}
        text = ""
        pdf_id = ""
        dok_id = 0
        suchindex = getattr(self.db, "suchindex", None)
        if suchindex is not None:
            try:
                dok = suchindex.dokument_nach_pfad(str(bezug.pfad))
                if dok:
                    dok_id = int(dok.get("id") or 0)
                    pdf_id = dok.get("pdf_id") or ""
                    meta = {f: dok.get(f) for f in BEZUG_FELDER if dok.get(f) not in (None, "")}
                    if dok_id:
                        text = suchindex.volltext(dok_id, BEZUG_LESE_ZEICHEN) or ""
            except Exception:  # noqa: BLE001 - Index ist optional, Rueckfall unten
                pass
        for f in BEZUG_FELDER:
            wert = (bezug.metadaten or {}).get(f)
            if not meta.get(f) and wert not in (None, ""):
                meta[f] = wert
        if not text.strip():
            text = bezug.text or ""
        text = text.replace("\f", "\n").strip()
        snippet = RetrievalService._build_snippet(text, BEZUG_MAX_ZEICHEN) or "(Kein Text erkannt.)"
        kennungen = kennungen_aus_text(text)
        extra: dict = {"bezug": True}
        if bezug.im_scan_ordner():
            extra["ordner"] = ""
            extra["hinweise"] = [SCAN_EINGANG_HINWEIS]
        else:
            extra["ordner"] = ablageort(bezug.pfad, bezug.wurzeln)
        if kennungen:
            extra["kennungen"] = [str(kn) for kn in kennungen]
            extra["kennung_objekte"] = kennungen
        if text:
            extra["volltext"] = text
        return RetrievedDoc(
            index=1,
            file_path=str(bezug.pfad),
            filename=bezug.pfad.name,
            text_snippet=snippet,
            rank=0,
            kategorie=str(meta.get("kategorie") or ""),
            steuerjahr=str(meta.get("steuerjahr") or ""),
            betrag=_betrag(meta.get("betrag")),
            korrespondent=str(meta.get("korrespondent") or ""),
            pdf_id=pdf_id,
            dok_id=dok_id,
            seite=0,
            extra=extra,
        )

    @staticmethod
    def _bezug_suchbegriffe(bezug_doc: RetrievedDoc) -> str:
        """Korrespondent, Kategorie und Steuerjahr des Bezugs als zusaetzliche Suchbegriffe."""
        return " ".join(str(getattr(bezug_doc, f, "") or "") for f in SUCH_FELDER).strip()

    def _cache_key(self, question: str, bezug: Optional[Bezug] = None) -> str:
        """Stabiler Cache-Key basierend auf Frage + Retrieval-Ergebnis-Set.

        Da die Retrieval-Ergebnisse vom DB-Zustand abhaengen, koennte der
        Cache stale werden. Wir mischen daher auch den Inhalt der
        aktuellen Session-ID (Klassenname + Objekt-ID) bei, damit
        verschiedene Sessions sich nicht gegenseitig die Antworten geben.

        Issue #148: "dieses Dokument" meint je Bezug ein anderes PDF, darum
        gehoeren Bezugspfad und Ordnervorschlaege mit in den Schluessel.
        """
        session_marker = id(self.chat_session)
        bezug_teil = ""
        if bezug is not None:
            bezug_teil = Path(bezug.pfad).as_posix().casefold()
            if bezug.sortier_vorschlaege:
                bezug_teil += "|" + "|".join(bezug.sortier_vorschlaege)
        h = hashlib.sha256(
            f"{question.strip().lower()}|{session_marker}|{bezug_teil}".encode("utf-8")
        ).hexdigest()
        return h

    def _cache_put(self, key: str, value: RAGResponse) -> None:
        """LRU-Insertion in ``self._cache``."""
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)


def _feld(doc, name: str):
    """Feld aus einem RetrievedDoc oder einem Dict."""
    if isinstance(doc, dict):
        return doc.get(name)
    return getattr(doc, name, None)


def _als_retrieved_doc(doc) -> RetrievedDoc:
    """Ein Dict (fremde Retrieval-Fassungen) als RetrievedDoc; RetrievedDocs unveraendert."""
    if not isinstance(doc, dict):
        return doc
    extra = doc.get("extra")
    if not isinstance(extra, dict):
        extra = {k: doc[k] for k in ("bezug", "ordner", "hinweise", "kennungen", "gemeinsame_kennungen")
                 if doc.get(k)}
    return RetrievedDoc(
        index=int(doc.get("index") or 0),
        file_path=str(doc.get("file_path") or ""),
        filename=str(doc.get("filename") or ""),
        text_snippet=str(doc.get("text_snippet") or ""),
        rank=int(doc.get("rank") or 0),
        kategorie=str(doc.get("kategorie") or ""),
        steuerjahr=str(doc.get("steuerjahr") or ""),
        betrag=str(doc.get("betrag") or ""),
        korrespondent=str(doc.get("korrespondent") or ""),
        pdf_id=str(doc.get("pdf_id") or ""),
        dok_id=int(doc.get("dok_id") or 0),
        seite=int(doc.get("seite") or 0),
        extra=dict(extra),
    )


def _abgebrochen(abbruch) -> bool:
    """True, wenn das Abbruch-Event gesetzt ist (None = nie)."""
    if abbruch is None:
        return False
    try:
        return bool(abbruch.is_set())
    except Exception:  # noqa: BLE001 - fremde Objekte ohne is_set
        return False


def _melde(fortschritt, text: str) -> None:
    """Statuszeile fuettern; Fehler im Callback (GUI weg) stoeren die Antwort nicht."""
    if fortschritt is None:
        return
    try:
        fortschritt(text)
    except Exception:  # noqa: BLE001 - defensiv
        pass


def _aufruf_beschreibung(aufruf) -> str:
    """Kurze Zeile fuer die Statuszeile, bevor ein Werkzeug laeuft: ``Suche „226541“ …``."""
    name = str(getattr(aufruf, "name", "") or "")
    argumente = getattr(aufruf, "argumente", None)
    if not isinstance(argumente, dict):
        argumente = {}

    def wert(schluessel: str) -> str:
        return " ".join(str(argumente.get(schluessel) or "").split())

    if name == "suche":
        return f"Suche „{wert('abfrage')}“ …"
    if name == "dokument_lesen":
        dok = wert("dokument")
        if dok.isdigit():
            dok = f"D{dok}"
        return f"Lese {dok or 'Dokument'} …"
    if name == "ordner_vorschlag":
        dok = wert("dokument")
        return f"Ordnervorschlag für {dok} …" if dok else "Ordnervorschlag …"
    if name == "korrespondent_info":
        return f"Korrespondent „{wert('name')}“ …"
    if name == "sql_abfrage":
        return "SQL-Abfrage …"
    return f"{name or 'Werkzeug'} …"


def _mit_index(doc, index: int):
    """Kopie mit neuer Nummer (``[Dn]``), Original bleibt unveraendert."""
    if isinstance(doc, dict):
        return {**doc, "index": index}
    return replace(doc, index=index, rank=index, extra=dict(doc.extra or {}))


def _betrag(wert) -> str:
    """Betrag als Text wie bei den Suchtreffern ("59.99")."""
    if wert in (None, ""):
        return ""
    if isinstance(wert, (int, float)):
        return f"{float(wert):.2f}"
    return str(wert)

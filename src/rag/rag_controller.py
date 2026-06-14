"""
RAG-Controller fuer PDF Sortier Meister (Phase 19 / M1).

Orchestriert den RAG-Chat-Workflow:

    Frage -> Retrieval (FTS5) -> LLM (optional) -> CitationParser -> RAGResponse

Der Controller haelt zusaetzlich eine ``ChatSession`` (Konversationshistorie)
und einen simplen LRU-Cache fuer Frage/Antwort-Paaren, damit
wiederholt gestellte Fragen nicht erneut das LLM rufen.

MIT License - Copyright (c) 2026
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.rag.chat_session import ChatSession, ChatTurn
from src.rag.citation import Citation, CitationParser
from src.rag.prompts import (
    SYSTEM_PROMPT,
    build_context_block,
    build_user_prompt,
)
from src.rag.retrieval import RetrievedDoc, RetrievalService


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

    def ask(self, question: str) -> RAGResponse:
        """Beantwortet eine Nutzerfrage via Retrieval + optional LLM.

        Args:
            question: Freitext-Frage des Nutzers.

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

        # 1) Cache-Check
        cache_key = self._cache_key(question)
        if cache_key in self._cache:
            # LRU: ans Ende schieben
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        # 2) Datenbank-Leerlauf pruefen (M3-Hardening).
        # Wenn ueberhaupt nichts indexiert ist, brauchen wir weder Retrieval
        # noch LLM und liefern eine ehrliche Antwort.
        if not self._has_indexed_documents():
            return RAGResponse(
                answer_text="Keine Dokumente indiziert.",
                citations=[],
                retrieved_docs=[],
                used_llm=False,
            )

        # 3) Retrieval (immer, auch ohne LLM fuer Offline-Fallback)
        k = getattr(self.chat_config, "max_context_docs", 8) or 8
        try:
            retrieved = self.retrieval.retrieve(question, k=k) or []
        except Exception as e:
            return RAGResponse(
                answer_text=f"Suche fehlgeschlagen: {e}",
                citations=[],
                retrieved_docs=[],
                used_llm=False,
            )

        # 4) LLM-Aufruf wenn verfuegbar
        if self.llm_provider is not None and self._is_llm_available():
            response = self._ask_llm(question, retrieved)
        elif not retrieved:
            # Offline-Modus UND keine Quellen gefunden: ehrliche
            # Standard-Antwort statt leerer Text (M3-Hardening).
            response = RAGResponse(
                answer_text="Keine passenden Dokumente gefunden.",
                citations=[],
                retrieved_docs=[],
                used_llm=False,
            )
        else:
            # Offline-Modus MIT Quellen: bisheriges Verhalten (leerer
            # answer_text, damit die GUI die Treffer-Liste anzeigen kann).
            response = RAGResponse(
                answer_text="",
                citations=[],
                retrieved_docs=retrieved,
                used_llm=False,
            )

        # 5) Turn in ChatSession protokollieren
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
                    }
                    for c in response.citations
                ],
                timestamp=datetime.now(),
            ))

        # 6) LRU-Cache schreiben
        self._cache_put(cache_key, response)
        return response

    def reset(self) -> None:
        """Leert Konversationshistorie UND LRU-Cache."""
        self.chat_session.clear()
        self._cache.clear()

    # ------------------------------------------------------------------ #
    # Intern
    # ------------------------------------------------------------------ #

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

        max_tokens = getattr(self.chat_config, "max_tokens_answer", 1000) or 1000

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
        return {
            "index": getattr(doc, "index", 0),
            "filename": getattr(doc, "filename", ""),
            "file_path": getattr(doc, "file_path", ""),
            "kategorie": getattr(doc, "kategorie", ""),
            "steuerjahr": getattr(doc, "steuerjahr", ""),
            "betrag": getattr(doc, "betrag", ""),
            "korrespondent": getattr(doc, "korrespondent", ""),
            "text_snippet": getattr(doc, "text_snippet", ""),
        }

    def _cache_key(self, question: str) -> str:
        """Stabiler Cache-Key basierend auf Frage + Retrieval-Ergebnis-Set.

        Da die Retrieval-Ergebnisse vom DB-Zustand abhaengen, koennte der
        Cache stale werden. Wir mischen daher auch den Inhalt der
        aktuellen Session-ID (Klassenname + Objekt-ID) bei, damit
        verschiedene Sessions sich nicht gegenseitig die Antworten geben.
        """
        session_marker = id(self.chat_session)
        h = hashlib.sha256(
            f"{question.strip().lower()}|{session_marker}".encode("utf-8")
        ).hexdigest()
        return h

    def _cache_put(self, key: str, value: RAGResponse) -> None:
        """LRU-Insertion in ``self._cache``."""
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)

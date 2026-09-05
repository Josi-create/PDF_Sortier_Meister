"""
RAG-Chat-Package fuer PDF Sortier Meister (Phase 19 / M1).

Stellt die Kernbausteine des RAG-Chat-Features bereit:

* :data:`~src.rag.prompts.SYSTEM_PROMPT` und Builder fuer Kontext
  und User-Prompt.
* :class:`~src.rag.retrieval.RetrievalService` und
  :class:`~src.rag.retrieval.RetrievedDoc` fuer FTS5-Retrieval.
* :class:`~src.rag.chat_session.ChatSession` und
  :class:`~src.rag.chat_session.ChatTurn` fuer den Konversations-State.
* :class:`~src.rag.citation.Citation` und
  :class:`~src.rag.citation.CitationParser` fuer ``[N]``-Marker.
* :class:`~src.rag.rag_controller.RAGController` und
  :class:`~src.rag.rag_controller.RAGResponse` als Orchestrator.

Die GUI-Komponenten (``ChatView``, ``ChatWorker``) sind Bestandteil
von M2 und werden hier nicht exportiert.

GPL-3.0-or-later - Copyright (c) 2026
"""

from src.rag.chat_session import ChatSession, ChatTurn
from src.rag.citation import Citation, CitationParser
from src.rag.prompts import (
    SYSTEM_PROMPT,
    build_context_block,
    build_user_prompt,
)
from src.rag.rag_controller import RAGController, RAGResponse
from src.rag.retrieval import RetrievedDoc, RetrievalService

__all__ = [
    "ChatSession",
    "ChatTurn",
    "Citation",
    "CitationParser",
    "RetrievedDoc",
    "RetrievalService",
    "RAGController",
    "RAGResponse",
    "SYSTEM_PROMPT",
    "build_context_block",
    "build_user_prompt",
]

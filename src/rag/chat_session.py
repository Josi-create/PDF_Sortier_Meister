"""
Chat-Session fuer das RAG-Chat-Feature (Phase 19 / M1).

In-Memory-Konversations-State (``list[ChatTurn]``) plus
Token-Schaetzung und History-Slicing fuer den Prompt-Builder.

Persistence (SQLite) ist explizit Q1-deferred und nicht Teil von M1.

MIT License - Copyright (c) 2026
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ChatTurn:
    """Ein einzelner Konversations-Turn.

    Attributes:
        role: ``"user"`` oder ``"assistant"`` (auch ``"system"`` ist
            technisch erlaubt, wird aber nicht aktiv genutzt).
        content: Textinhalt des Turns.
        citations: Optionale Liste von Citation-Dicts (Phase 19 / M3
            wird das Parsen uebernehmen; in M1 ist das Feld ein
            Platzhalter fuer die LLM-Antwort).
        timestamp: UTC-Zeitpunkt, wird beim ``__post_init__`` gesetzt.
    """
    role: str
    content: str
    citations: list[dict] = field(default_factory=list)
    timestamp: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        # Normalisiere die Rolle
        self.role = (self.role or "user").lower()
        if self.role not in ("user", "assistant", "system"):
            self.role = "user"


class ChatSession:
    """In-Memory-Container fuer ChatTurns.

    Wird in der Regel pro ``RAGController``-Instanz (Session-scoped)
    gehalten. Kein Thread-Lock: der Caller (typischerweise der
    ``ChatWorker``) ist fuer Serialisierung verantwortlich.
    """

    def __init__(self) -> None:
        self.turns: list[ChatTurn] = []

    def add_turn(self, turn: ChatTurn) -> None:
        """Haengt einen Turn an die Session an."""
        if not isinstance(turn, ChatTurn):
            raise TypeError(f"turn muss ein ChatTurn sein, nicht {type(turn)}")
        self.turns.append(turn)

    def get_recent(self, n: int) -> list[ChatTurn]:
        """Liefert die letzten ``n`` Turns (max)."""
        if n is None or n <= 0:
            return []
        return self.turns[-n:]

    def estimate_tokens(self) -> int:
        """
        Sehr grobe Token-Schaetzung: Wortanzahl * 1.3.

        Bewusst nicht der echte Tokenizer-Tiktoken-Counter - das waere
        eine zusaetzliche Dependency. Diese Schaetzung reicht fuer
        Token-Budget-Checks im RAGController (M1) aus.
        """
        total_words = 0
        for turn in self.turns:
            content = turn.content or ""
            # Sehr einfach: Whitespace-Split
            total_words += len(content.split())
        return int(total_words * 1.3)

    def clear(self) -> None:
        """Loescht alle Turns."""
        self.turns.clear()

    def __len__(self) -> int:
        return len(self.turns)

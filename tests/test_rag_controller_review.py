"""RAGController (Issue #166/#167): Abbruch hinterlaesst keinen offenen Nutzer-Turn (Review-Befund)."""
from __future__ import annotations

import threading

from src.rag.rag_controller import ABGEBROCHEN_TEXT, RAGController
from src.utils.config import ChatConfig
from tests.test_rag_controller import _make_db_with_docs


class _Provider:
    def __init__(self):
        self.aufrufe = 0

    def is_available(self) -> bool:
        return True

    def unterstuetzt_werkzeuge(self) -> bool:
        return True

    def chat_mit_werkzeugen(self, nachrichten, werkzeuge, max_tokens=1000):
        self.aufrufe += 1
        raise AssertionError("darf nach gesetztem Abbruch nicht gerufen werden")

    def answer_with_context(self, **kwargs):
        return "Antwort [1]."


def test_abbruch_vor_dem_ersten_schritt_protokolliert_nichts(tmp_path):
    db = _make_db_with_docs(tmp_path)
    provider = _Provider()
    ctrl = RAGController(db, provider, ChatConfig(werkzeuge_aktiv=True))
    abbruch = threading.Event()
    abbruch.set()

    response = ctrl.ask("Telekom Rechnung", abbruch=abbruch)

    assert response.answer_text == ABGEBROCHEN_TEXT and not response.used_llm and response.werkzeuge_benutzt
    assert provider.aufrufe == 0
    assert ctrl.chat_session.turns == []  # keine offene Nutzerfrage fuer den naechsten Prompt
    assert ctrl._history_for_llm() == []
    # Dieselbe Frage danach laeuft normal (kein Cache-Treffer mit "Abgebrochen.")
    abbruch.clear()
    provider.chat_mit_werkzeugen = lambda nachrichten, werkzeuge, max_tokens=1000: __import__(
        "src.ml.llm_provider", fromlist=["WerkzeugAntwort"]).WerkzeugAntwort(text="Fertig [1].")
    response = ctrl.ask("Telekom Rechnung", abbruch=abbruch)
    assert response.used_llm and len(ctrl.chat_session.turns) == 2

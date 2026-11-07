"""ChatView (Issue #166/#167): ein nicht verfuegbarer Chat-Provider wird uebergangen (Review-Befund)."""
from __future__ import annotations

from src.gui.chat_view import ChatView
from src.utils.config import ChatConfig


class _Provider:
    def __init__(self, verfuegbar: bool):
        self._verfuegbar = verfuegbar

    def is_available(self) -> bool:
        return self._verfuegbar


class _StubLLM:
    def __init__(self, provider, available: bool):
        self.llm_provider = provider
        self._available = available

    def is_llm_available(self) -> bool:
        return self._available


def test_nicht_verfuegbarer_chat_provider_faellt_auf_die_sortierung_zurueck(qtbot):
    sortierung = _Provider(True)
    view = ChatView(db=None, hybrid_classifier=_StubLLM(sortierung, True), chat_config=ChatConfig())
    qtbot.addWidget(view)
    kaputt = _Provider(False)
    view.chat_provider_quelle = lambda: kaputt

    assert view._llm_provider_fuer_chat() is sortierung
    view.refresh_llm_status()
    assert view.banner.isHidden()

    # Verfuegbarer Chat-Provider hat Vorrang
    gut = _Provider(True)
    view.chat_provider_quelle = lambda: gut
    assert view._llm_provider_fuer_chat() is gut


def test_banner_wenn_weder_chat_noch_sortier_modell_verfuegbar(qtbot):
    view = ChatView(db=None, hybrid_classifier=_StubLLM(None, False), chat_config=ChatConfig())
    qtbot.addWidget(view)
    view.chat_provider_quelle = lambda: _Provider(False)
    view.refresh_llm_status()
    assert not view.banner.isHidden()
    assert view._llm_provider_fuer_chat() is None

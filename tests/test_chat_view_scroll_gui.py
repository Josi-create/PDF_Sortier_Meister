"""ChatView (Live-Test): Scrollen ans Ende, Anfuehrungszeichen statt &quot;, eingeklappte Quellen einzeilig."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from src.gui.chat_view import ChatView
from src.utils.config import ChatConfig


class _StubLLM:
    llm_provider = None

    def is_llm_available(self) -> bool:
        return False


def _view(qtbot, kompakt: bool = True) -> ChatView:
    view = ChatView(db=None, hybrid_classifier=_StubLLM(), chat_config=ChatConfig(), kompakt=kompakt)
    qtbot.addWidget(view)
    return view


def test_anfuehrungszeichen_und_sonderzeichen_werden_als_text_gezeigt(qtbot):
    view = _view(qtbot)
    bubble = view._add_bubble('Excel "Zählerstände" & Co <ohne Tags>', "user")
    assert bubble.textFormat() == Qt.TextFormat.RichText
    assert "&quot;" in bubble.text() and "&lt;ohne Tags&gt;" in bubble.text()  # maskiert ...
    # ... aber gerendert als Text: QLabel liefert den sichtbaren Text ueber das Dokument
    from PyQt6.QtGui import QTextDocument
    doc = QTextDocument()
    doc.setHtml(bubble.text())
    assert doc.toPlainText() == 'Excel "Zählerstände" & Co <ohne Tags>'


def test_neue_antwort_scrollt_ans_ende(qtbot):
    view = _view(qtbot)
    view.resize(420, 500)
    view.show()
    qtbot.waitExposed(view)
    for i in range(12):
        view._add_bubble(f"Antwort {i}: " + "Text " * 60, "assistant")
    bar = view.history_scroll.verticalScrollBar()
    qtbot.waitUntil(lambda: bar.maximum() > 0 and bar.value() == bar.maximum(), timeout=3000)
    # Auch eine spaete Layout-Aenderung (Umbruch) haelt das Ende im Blick
    view._add_bubble("Letzte Antwort " + "Wort " * 120, "assistant")
    qtbot.waitUntil(lambda: bar.value() == bar.maximum(), timeout=3000)


def test_eingeklappte_quellen_brauchen_nur_eine_zeile(qtbot):
    view = _view(qtbot, kompakt=True)
    view.resize(420, 700)
    view.show()
    qtbot.waitExposed(view)
    assert view.sources_list.isHidden()
    assert view.sources_panel.maximumHeight() == ChatView.QUELLEN_KOPF_HOEHE
    assert view.sources_panel.height() <= ChatView.QUELLEN_KOPF_HOEHE

    view._toggle_sources()
    assert not view.sources_list.isHidden()
    assert view.sources_panel.maximumHeight() > 1000
    qtbot.waitUntil(lambda: view.split.sizes()[1] >= 150, timeout=2000)

    view._toggle_sources()
    assert view.sources_list.isHidden() and view.sources_panel.maximumHeight() == ChatView.QUELLEN_KOPF_HOEHE

    # Breiter Reiter: keine Hoehenbegrenzung
    breit = _view(qtbot, kompakt=False)
    assert breit.sources_panel.maximumHeight() > 1000
    assert isinstance(breit.sources_title, QLabel)

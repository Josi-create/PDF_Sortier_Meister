"""Markdown in Chat-Antworten (Issue #199)."""

import re
from types import SimpleNamespace

import pytest

from src.gui.chat_view import ChatView, _markdown_zu_html
from src.utils.config import ChatConfig


class _StubLLM:
    llm_provider = None

    def is_llm_available(self) -> bool:
        return False


@pytest.fixture
def chat_view(qtbot, tmp_path):
    from src.utils.database import Database

    db = Database(db_path=str(tmp_path / "md_test.db"))
    view = ChatView(db=db, hybrid_classifier=_StubLLM(), chat_config=ChatConfig())
    qtbot.addWidget(view)
    return view


def _zitat(index, valid=True):
    return SimpleNamespace(
        index=index, valid=valid, file_path=f"/tmp/{index}.pdf", pdf_id=""
    )


def _sichtbar(html: str) -> str:
    """Text ohne Tags, so wie ihn der Nutzer sieht."""
    from PyQt6.QtGui import QTextDocument

    d = QTextDocument()
    d.setHtml(html)
    return d.toPlainText()


def test_formatierung_fett_liste_ueberschrift_code_tabelle(chat_view):
    md = (
        "### Titel\n\nText **fett** und `inline`\n\n- eins\n- zwei\n\n"
        "1. a\n2. b\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```\ncode zeile\n```\n"
    )
    bubble = chat_view._add_bubble(md, "assistant")
    html = bubble.text()
    assert "font-weight:700" in html
    assert "<li" in html and "<ul" in html and "<ol" in html
    assert "<h3" in html
    assert "<table" in html
    assert "<pre" in html and "monospace" in html
    sichtbar = _sichtbar(html)
    assert "**" not in sichtbar and "###" not in sichtbar and "```" not in sichtbar
    assert "code zeile" in sichtbar and "inline" in sichtbar
    # Ueberschrift bleibt in Textgroesse
    assert "font-size:large" not in html


def test_zitat_links_in_liste_und_fett(chat_view):
    md = "- Beleg [1] hier\n- **wichtig [D2]**\n- ungueltig [3]"
    zitate = [_zitat(1), _zitat(2), _zitat(3, valid=False)]
    bubble = chat_view._add_bubble(md, "assistant", citations=zitate)
    html = bubble.text()
    assert re.search(r'<a href="1"[^>]*>.*\[1\].*</a>', html, re.S)
    assert re.search(r'<a href="2"[^>]*>.*\[D2\].*</a>', html, re.S)
    assert 'href="3"' not in html
    assert "[3]" in _sichtbar(html)


def test_zitat_klick_oeffnet_dokument(chat_view, monkeypatch):
    geoeffnet = []
    monkeypatch.setattr(chat_view, "_resolve_file_path", lambda fp, pid: fp)
    monkeypatch.setattr(chat_view, "_oeffnen", lambda p, s=0: geoeffnet.append(p))
    bubble = chat_view._add_bubble("**Beleg [1]**", "assistant", citations=[_zitat(1)])
    bubble.linkActivated.emit("1")
    assert geoeffnet == ["/tmp/1.pdf"]


def test_roh_html_wird_nicht_uebernommen(chat_view):
    md = (
        "<script>alert(1)</script> <b>roh</b> <img src=x onerror=y> "
        "[fremd](http://evil.example/x) `<i>code</i>`\n\n```\n<u>block</u>\n```"
    )
    html = chat_view._add_bubble(md, "assistant").text()
    assert "<script" not in html and "<img" not in html
    assert "evil.example" not in html
    sichtbar = _sichtbar(html)
    assert "<script>alert(1)</script>" in sichtbar
    assert "<b>roh</b>" in sichtbar
    assert "<i>code</i>" in sichtbar and "<u>block</u>" in sichtbar
    assert "fremd" in sichtbar


def test_user_system_error_bleiben_text(chat_view):
    for rolle in ("user", "system", "error"):
        html = chat_view._add_bubble("**fett** <b>x</b>\n- a", rolle).text()
        assert "**fett**" in _sichtbar(html)
        assert "&lt;b&gt;" in html
        assert "<br>" in html and "<ul" not in html


def test_text_bleibt_markierbar(chat_view):
    from PyQt6.QtCore import Qt

    bubble = chat_view._add_bubble("**fett**", "assistant")
    flags = bubble.textInteractionFlags()
    assert flags & Qt.TextInteractionFlag.TextSelectableByMouse


def test_helper_leerer_text():
    assert "<table" not in _markdown_zu_html("", ())

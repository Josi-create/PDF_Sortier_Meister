"""Issue #350: Antworten im Chat nutzen die ganze Breite der Spalte."""
from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtWidgets import QLabel

from src.gui.chat_view import ChatView
from src.utils.config import ChatConfig


class _StubLLM:
    llm_provider = None

    def is_llm_available(self) -> bool:
        return False


def _view(qtbot, breite: int) -> ChatView:
    view = ChatView(db=None, hybrid_classifier=_StubLLM(), chat_config=ChatConfig(), kompakt=True)
    qtbot.addWidget(view)
    view.resize(breite, 700)
    view.show()
    return view


def _warten(qtbot, view) -> int:
    qtbot.wait(50)
    return view.history_scroll.viewport().width()


def test_antwort_fuellt_breite_spalte(qtbot):
    view = _view(qtbot, 1200)
    lang = view._add_bubble("Lange Antwort mit vielen Woertern " * 40, "assistant")
    kurz = view._add_bubble("Kurz.", "assistant")
    fehler = view._add_bubble("Etwas ging schief.", "error")
    platz = _warten(qtbot, view)
    # Vorher blieb die Antwort bei rund 570 px stehen, der Rest war leer
    for bubble in (lang, kurz, fehler):
        assert bubble.width() >= platz - 20


def test_frage_bleibt_rechts_und_schmaler_aber_breiter_als_frueher(qtbot):
    view = _view(qtbot, 1200)
    kurz = view._add_bubble("Hallo", "user")
    lang = view._add_bubble("Eine lange Frage mit Umlauten äöü " * 30, "user")
    platz = _warten(qtbot, view)
    assert kurz.width() < 200  # kurze Frage bleibt eine kleine Blase
    assert 0.7 * platz < lang.width() < 0.95 * platz
    # rechtsbuendig: rechte Kante am Rand der Spalte
    rechts = lang.mapTo(view.history_scroll.viewport(), lang.rect().topRight()).x()
    assert rechts >= platz - 20


def test_arbeitsschritte_brechen_erst_am_spaltenrand_um(qtbot):
    view = _view(qtbot, 1200)
    schritte = [
        SimpleNamespace(werkzeug="suche", zusammenfassung="kurz", fehler=""),
        SimpleNamespace(werkzeug="suche", zusammenfassung="langer Schritt " * 60, fehler=""),
    ]
    block = view._add_schritte(schritte)
    platz = _warten(qtbot, view)
    kurz, lang = [lbl for lbl in block.findChildren(QLabel) if lbl.property("schritt")]
    assert kurz.width() < 200
    assert lang.width() >= platz - 60  # 16 px Einzug der Schritt-Box


def test_treffer_bubble_fuellt_breite(qtbot, tmp_path):
    view = _view(qtbot, 1000)
    doc = SimpleNamespace(kategorie="", steuerjahr="", betrag="", filename="a.pdf",
                          file_path=str(tmp_path / "a.pdf"), text_snippet="Auszug")
    view._add_doc_bubble(doc)
    platz = _warten(qtbot, view)
    bubble = [b for b in view._history_container.findChildren(QLabel) if "a.pdf" in b.text()][-1]
    assert bubble.width() >= platz - 20

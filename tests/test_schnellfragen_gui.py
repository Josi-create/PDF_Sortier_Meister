"""Eigene Schnellfragen (Phase 3, Issue #166): Konfiguration, Einstellungsdialog, ChatView, Hauptfenster."""
from __future__ import annotations

from pathlib import Path

from src.gui.chat_view import ChatView
from src.rag.bezug import MAX_SCHNELLFRAGEN, SCHNELLFRAGEN, schnellfragen_aus_text, schnellfragen_liste
from src.utils.config import ChatConfig
from tests.test_auto_next_after_move_gui import fresh_singletons, main_window  # noqa: F401 - Fixtures
from tests.test_settings_chat_gui import _dialog, fresh_config  # noqa: F401 - Fixtures


class _StubLLM:
    llm_provider = None

    def is_llm_available(self) -> bool:
        return False


def test_schnellfragen_aus_text_und_liste():
    assert schnellfragen_aus_text("  Wer ist der Absender?  \n\n\nWer ist der Absender?\nBetrag? ") == [
        "Wer ist der Absender?", "Betrag?"]
    assert schnellfragen_aus_text("") == []
    assert len(schnellfragen_aus_text("\n".join(f"Frage {i}" for i in range(30)))) == MAX_SCHNELLFRAGEN
    assert schnellfragen_liste(None) == list(SCHNELLFRAGEN)
    assert schnellfragen_liste(ChatConfig()) == list(SCHNELLFRAGEN)
    assert schnellfragen_liste(ChatConfig(schnellfragen=["Wer?", " ", "Wann?"])) == ["Wer?", "Wann?"]


def test_chatview_baut_knoepfe_aus_der_konfiguration_und_zieht_aenderungen_nach(qtbot):
    for kompakt in (False, True):
        view = ChatView(db=None, hybrid_classifier=_StubLLM(),
                        chat_config=ChatConfig(schnellfragen=["Wer ist der Absender?", "Wie hoch ist der Betrag?"]),
                        kompakt=kompakt)
        qtbot.addWidget(view)
        assert [b.text() for b in view.schnellfragen_btns] == ["Wer ist der Absender?", "Wie hoch ist der Betrag?"]

        gesendet = []
        view._on_send = lambda: gesendet.append(view.input_edit.toPlainText())
        view.set_bezug(Path("C:/Scan/a.pdf"))
        view.schnellfragen_btns[1].click()
        assert gesendet == ["Wie hoch ist der Betrag?"]

        view.konfig_geaendert(ChatConfig(schnellfragen=["Nur eine Frage?"], werkzeuge_aktiv=False))
        assert [b.text() for b in view.schnellfragen_btns] == ["Nur eine Frage?"]
        assert view.chat_config.werkzeuge_aktiv is False and view._controller is None
        view.konfig_geaendert(ChatConfig())
        assert [b.text() for b in view.schnellfragen_btns] == list(SCHNELLFRAGEN)


def test_einstellungen_laden_und_speichern_schnellfragen(qtbot, fresh_config):
    fresh_config.set("chat", {"schnellfragen": ["Wer?", "Wann?"]})
    d = _dialog(qtbot)
    assert d.chat_schnellfragen_edit.toPlainText() == "Wer?\nWann?"
    d.chat_schnellfragen_edit.setPlainText("Wer?\n\n  Wo?  \nWer?")
    d._save_settings()
    assert fresh_config.get("chat")["schnellfragen"] == ["Wer?", "Wo?"]

    # Standard wiederherstellen -> leer gespeichert (Standard bleibt aenderbar)
    d = _dialog(qtbot)
    d.chat_schnellfragen_standard_btn.click()
    assert d.chat_schnellfragen_edit.toPlainText() == "\n".join(SCHNELLFRAGEN)
    d._save_settings()
    assert fresh_config.get("chat")["schnellfragen"] == []
    assert fresh_config.get_chat_config().schnellfragen == []

    # Leeres Feld = Standard; der Platzhalter zeigt die Standardfragen
    d = _dialog(qtbot)
    assert d.chat_schnellfragen_edit.toPlainText() == ""
    assert d.chat_schnellfragen_edit.placeholderText() == "\n".join(SCHNELLFRAGEN)


def test_hauptfenster_reicht_neue_schnellfragen_in_den_chat(main_window, fresh_singletons):
    assert [b.text() for b in main_window.chat_view.schnellfragen_btns] == list(SCHNELLFRAGEN)
    fresh_singletons["config"].update_chat_config(schnellfragen=["Zu welchem Objekt?"], max_werkzeug_schritte=3)
    main_window._on_settings_changed()
    assert [b.text() for b in main_window.chat_view.schnellfragen_btns] == ["Zu welchem Objekt?"]
    assert main_window.chat_view.chat_config.max_werkzeug_schritte == 3

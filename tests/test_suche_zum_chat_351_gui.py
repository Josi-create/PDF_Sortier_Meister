"""Issue #351: Vom Reiter „Suche“ direkt in den Chat wechseln.

* ``sieht_nach_frage_aus`` erkennt Fragen, nicht aber Suchwoerter und Suchsyntax
* Der Reiter „Suche“ zeigt das Angebot „Diese Frage im Chat stellen“ nur bei einer Frage;
  Knopf „Im Chat fragen“ und Angebot senden ``chat_requested`` mit dem Suchtext
* ``ChatView.frage_uebernehmen`` traegt den Text ein und fragt auf Wunsch gleich
* Im Hauptfenster: Wechsel auf „Vorschau“ und den Chat, Bezug entfernt, Text uebernommen

Kein Test dieser Datei darf ins Netz und keiner fragt eine echte KI.
"""
from __future__ import annotations

import pytest
from PyQt6 import sip

from src.gui.search_view import SearchView, sieht_nach_frage_aus
from src.utils.config import Config


@pytest.fixture(autouse=True)
def kein_netz(monkeypatch):
    def _verboten(*args, **kwargs):
        raise AssertionError("Netzaufruf im Test")
    monkeypatch.setattr("urllib.request.urlopen", _verboten)


# --------------------------------------------------------------------------- Erkennung (ohne Qt)

@pytest.mark.parametrize("text", [
    "Wie viele Verträge habe ich mit Max Mustermann?",
    "Wann läuft der Mietvertrag aus?",
    "Rechnung Telekom bezahlt?",
    "welche Versicherungen habe ich abgeschlossen",
    "Gibt es eine Kündigung von der Musterbank",
    "  Was   steht im Bescheid 2025 ?  ",
    "How many invoices did I get last year",
    "Wo liegt die Urkunde für Müller?",
])
def test_fragen_werden_erkannt(text):
    assert sieht_nach_frage_aus(text)


@pytest.mark.parametrize("text", [
    "",
    "   ",
    "Telekom?",                       # ein Wort: eher Tippfehler als Frage
    "Rechnung Telekom",
    "Rechnung Telekom 2024 Mai",
    "Wie Rechnung",                   # Fragewort, aber kein Satz
    '"Wie viele Verträge" Mustermann',  # gewollte Wortfolge
    "Rechnung* NICHT Mahnung?",
    "NEAR(Kündigung Frist, 10) wann?",
    "Mietvertrag ODER Pachtvertrag was ist das",
])
def test_suchwoerter_sind_keine_frage(text):
    assert not sieht_nach_frage_aus(text)


# --------------------------------------------------------------------------- Reiter „Suche“

@pytest.fixture
def view(qtbot, tmp_path):
    v = SearchView(Config(config_path=tmp_path / "config.json"))
    qtbot.addWidget(v)
    v.suchbereich.setEnabled(True)  # ohne eingerichtete Suche ist der Bereich gesperrt
    yield v
    v.shutdown()


def test_angebot_nur_bei_einer_frage(view):
    assert view.frage_hinweis.isHidden()
    view.search_edit.setText("Wie viele Verträge habe ich?")
    assert not view.frage_hinweis.isHidden()
    view.search_edit.setText("Rechnung Telekom")
    assert view.frage_hinweis.isHidden()
    view.search_edit.setText("Wann kam die Rechnung?")
    view.search_edit.clear()
    assert view.frage_hinweis.isHidden()


def test_angebot_fragt_gleich(qtbot, view):
    view.search_edit.setText("  Wann kam die Rechnung?  ")
    with qtbot.waitSignal(view.chat_requested, timeout=1000) as sig:
        view.frage_button.click()
    assert sig.args == ["Wann kam die Rechnung?", True]


def test_knopf_wechselt_ohne_zu_fragen(qtbot, view):
    view.search_edit.setText("Mietvertrag")
    with qtbot.waitSignal(view.chat_requested, timeout=1000) as sig:
        view.chat_button.click()
    assert sig.args == ["Mietvertrag", False]
    view.search_edit.clear()
    with qtbot.waitSignal(view.chat_requested, timeout=1000) as sig:
        view.chat_button.click()
    assert sig.args == ["", False]


# --------------------------------------------------------------------------- ChatView

class _StubLLM:
    llm_provider = None

    def is_llm_available(self) -> bool:
        return False


@pytest.fixture
def chat_view(qtbot, tmp_path, monkeypatch):
    from src.gui.chat_view import ChatView
    from src.utils.config import ChatConfig
    from src.utils.database import Database

    v = ChatView(db=Database(db_path=str(tmp_path / "chat.db")), hybrid_classifier=_StubLLM(),
                 chat_config=ChatConfig())
    qtbot.addWidget(v)
    gesendet = []
    monkeypatch.setattr(v, "_on_send", lambda: gesendet.append(v.input_edit.toPlainText()))
    v.gesendet = gesendet
    return v


def test_frage_uebernehmen_ohne_senden(chat_view):
    chat_view.frage_uebernehmen("Wann kam die Rechnung?")
    assert chat_view.input_edit.toPlainText() == "Wann kam die Rechnung?"
    assert chat_view.gesendet == []


def test_frage_uebernehmen_mit_senden(chat_view):
    chat_view.frage_uebernehmen("Wann kam die Rechnung?", senden=True)
    assert chat_view.gesendet == ["Wann kam die Rechnung?"]


def test_leerer_text_laesst_eingabe_stehen(chat_view):
    chat_view.input_edit.setPlainText("angefangen")
    chat_view.frage_uebernehmen("", senden=True)
    assert chat_view.input_edit.toPlainText() == "angefangen"
    assert chat_view.gesendet == []


def test_laufende_antwort_wird_nicht_unterbrochen(chat_view):
    chat_view._chat_thread = object()  # eine Antwort laeuft noch
    try:
        chat_view.frage_uebernehmen("Und wann die nächste?", senden=True)
    finally:
        chat_view._chat_thread = None
    assert chat_view.input_edit.toPlainText() == "Und wann die nächste?"
    assert chat_view.gesendet == []


# --------------------------------------------------------------------------- Hauptfenster

@pytest.fixture
def fenster(qtbot, monkeypatch, tmp_path):
    from PyQt6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)

    from src.core import pdf_cache as pc_mod
    from src.gui import main_window as mw_mod
    from src.ml import classifier as cl_mod
    from src.ml import hybrid_classifier as hc_mod
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod
    from tests.conftest import patch_singletons

    cfg = cfg_mod.Config(config_path=tmp_path / "config.json")
    cfg.set("persist_pdf_cache", False)
    db_path = tmp_path / "mw.db"
    monkeypatch.setattr(pc_mod.PDFCache, "_instance", None)
    patch_singletons(monkeypatch, {
        "get_config": lambda: cfg,
        "get_database": lambda: db_mod.Database(db_path=str(db_path)),
        "get_classifier": cl_mod.PDFClassifier,
        "get_hybrid_classifier": hc_mod.HybridClassifier,
        "get_pdf_cache": pc_mod.PDFCache,
    })
    monkeypatch.setattr(mw_mod.QMainWindow, "showMaximized", lambda self: None)
    monkeypatch.setattr(mw_mod.QMainWindow, "show", lambda self: None)
    win = mw_mod.MainWindow()
    yield win
    win.close()
    sip.delete(win)


@pytest.mark.parametrize("senden", [False, True])
def test_hauptfenster_wechselt_in_den_chat(fenster, monkeypatch, tmp_path, senden):
    win = fenster
    gesendet = []
    monkeypatch.setattr(win.chat_view, "_on_send", lambda: gesendet.append(win.chat_view.input_edit.toPlainText()))
    win.center_tabs.setCurrentWidget(win.search_view)
    win.search_view.suchbereich.setEnabled(True)  # ohne eingerichtete Suche gesperrt
    win.chat_view.set_bezug(tmp_path / "Max_Mustermann_Rechnung.pdf")
    win.left_tabs.setCurrentIndex(0)

    win.search_view.search_edit.setText("Wie viele Verträge habe ich?")
    (win.search_view.frage_button if senden else win.search_view.chat_button).click()

    assert win.center_tabs.currentIndex() == 0
    assert win.left_tabs.currentWidget() is win.chat_view
    assert win.chat_view.bezug is None
    assert win.chat_view.input_edit.toPlainText() == "Wie viele Verträge habe ich?"
    assert gesendet == (["Wie viele Verträge habe ich?"] if senden else [])

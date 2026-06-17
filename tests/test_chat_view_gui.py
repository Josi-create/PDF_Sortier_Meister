"""GUI-Tests fuer die ChatView (Phase 19 / M4).

Verwendet ``pytest-qt`` (siehe ``pyproject.toml`` -> ``dev``-Extras).
Wir testen die Widget-Ebene:

* Return-Taste im ``input_edit`` sendet (signalisiert ``_on_send``)
* Shift+Return fuegt einen Zeilenumbruch ein, sendet NICHT
* Cancel-Button wird waehrend Worker-aktiv disabled, dann re-enabled mit Cooldown
* Reset-Button leert Chat-View + ``_controller.reset()``

Der RAGController und der LLM-Provider werden durch minimale Stubs
ersetzt, damit kein echtes LLM im Test laufen muss (kein
anthropic/openai-Import noetig).
"""

import sys

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QTextEdit

from src.gui.chat_view import ChatView, _ChatInput
from src.utils.config import ChatConfig


# --------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------- #


class _StubLLM:
    """Minimaler HybridClassifier-Stub mit ``.llm_provider`` und
    ``.is_llm_available()`` - so wie die ``ChatView`` ihn erwartet.
    """

    def __init__(self, available: bool = False):
        self.llm_provider = None
        self._available = available

    def is_llm_available(self) -> bool:
        return self._available


class _StubController:
    """Minimaler RAGController-Stub - liefert eine ``RAGResponse``-artige
    Antwort und zaehlt ``reset()``-Aufrufe."""

    def __init__(self, answer: str = ""):
        self._answer = answer
        self.reset_calls = 0
        self.ask_calls = 0

    def reset(self) -> None:
        self.reset_calls += 1

    def ask(self, question: str):
        self.ask_calls += 1
        return _FakeResponse(self._answer)


class _FakeResponse:
    """Dummy-RAGResponse - leere Antwort reicht fuer die GUI-Tests."""

    def __init__(self, text: str = ""):
        self.answer_text = text
        self.used_llm = False
        self.citations = []
        self.retrieved_docs = []


@pytest.fixture
def stub_llm():
    """LLM offline (Banner sichtbar)."""
    return _StubLLM(available=False)


@pytest.fixture
def chat_view(qtbot, tmp_path, stub_llm):
    """Eine frische ChatView mit leerer DB und Stub-LLM."""
    from src.utils.database import Database

    db = Database(db_path=str(tmp_path / "chatview_test.db"))
    view = ChatView(db=db, hybrid_classifier=stub_llm, chat_config=ChatConfig())
    qtbot.addWidget(view)
    return view


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #


def _set_input_text(view: ChatView, text: str) -> None:
    """Schreibt Text in das input_edit (QTextEdit)."""
    view.input_edit.setPlainText(text)


def _bubble_count(view: ChatView) -> int:
    """Anzahl der Bubbles in der Historie (history_layout enthaelt immer
    einen trailing Stretch, daher ``- 1``)."""
    return view.history_layout.count() - 1


# --------------------------------------------------------------------- #
# 1) Return-Taste sendet
# --------------------------------------------------------------------- #


def test_return_key_triggers_submit(qtbot, chat_view):
    """Return ohne Modifier emittiert das ``submit``-Signal der _ChatInput.

    Verifikation: Signal-Spy wird mit ``qtbot.waitSignal`` gebunden,
    danach wird Return gedrueckt. Spy muss feuern.

    Wichtig: Wir warten hier AUF DEN THREAD-ENDE, damit der QThread
    vom Hintergrund nicht in den naechsten Test durchsickert und
    dort ein Race-Condition verursacht.
    """
    _set_input_text(chat_view, "Hallo Welt")
    with qtbot.waitSignal(chat_view.input_edit.submit, timeout=1000):
        qtbot.keyClick(chat_view.input_edit, Qt.Key.Key_Return)
    # Auf sauberen Thread-Abschluss warten (sonst haengt der naechste Test)
    qtbot.waitUntil(lambda: chat_view._chat_thread is None, timeout=5000)


def test_return_key_clears_input_and_adds_bubble(qtbot, chat_view):
    """Return ohne Modifier loest ``_on_send`` aus, das die Frage als
    User-Bubble anzeigt und das Eingabefeld leert.

    Hinweis: Ohne echten LLM-Provider startet der Worker trotzdem
    einen Thread, der ``controller.ask()`` aufruft. Da unser Stub
    ohne Sleep zurueckkehrt, beendet sich der Thread schnell und die
    Historie enthaelt die User-Bubble.
    """
    _set_input_text(chat_view, "Frage")
    # Einen Stub-Controller injizieren, damit der Worker nicht None anspricht
    chat_view._controller = _StubController()
    qtbot.keyClick(chat_view.input_edit, Qt.Key.Key_Return)
    # Input ist sofort leer
    assert chat_view.input_edit.toPlainText() == ""
    # Es wurde mindestens eine Bubble hinzugefuegt
    assert _bubble_count(chat_view) >= 1
    # Auf das Ende des Worker-Threads warten (kein Zombie-Thread im Test)
    qtbot.waitUntil(lambda: chat_view._chat_thread is None, timeout=3000)


# --------------------------------------------------------------------- #
# 2) Shift+Return fuegt Zeilenumbruch ein, sendet NICHT
# --------------------------------------------------------------------- #


def test_shift_return_inserts_newline_not_submit(qtbot, chat_view):
    """Shift+Return fuegt einen Zeilenumbruch ein und emittiert KEIN
    ``submit``-Signal.

    Wir verbinden einen Spy auf ``submit`` (kein ``waitSignal``, weil
    das Signal *nicht* feuern soll) und pruefen anschliessend, dass
    der Text einen Newline enthaelt und keine Bubble hinzugefuegt wurde.
    """
    submit_spy = pytestqt_signal_spy(chat_view.input_edit.submit)

    _set_input_text(chat_view, "Zeile1")
    qtbot.keyClick(
        chat_view.input_edit,
        Qt.Key.Key_Return,
        modifier=Qt.KeyboardModifier.ShiftModifier,
    )

    # submit-Signal wurde NICHT emittiert
    assert submit_spy.count == 0
    # Zeilenumbruch wurde eingefuegt
    text = chat_view.input_edit.toPlainText()
    assert "\n" in text
    # Keine Bubble hinzugefuegt
    assert _bubble_count(chat_view) == 0


def test_shift_return_does_not_clear_input(qtbot, chat_view):
    """Shift+Return loescht das Eingabefeld NICHT (es ist ein normaler
    Zeilenumbruch)."""
    _set_input_text(chat_view, "Zeile A")
    qtbot.keyClick(
        chat_view.input_edit,
        Qt.Key.Key_Return,
        modifier=Qt.KeyboardModifier.ShiftModifier,
    )
    assert chat_view.input_edit.toPlainText() != ""
    # Originaler Text steht noch drin
    assert "Zeile A" in chat_view.input_edit.toPlainText()


# --------------------------------------------------------------------- #
# 3) Cancel-Button: disabled waehrend Worker, re-enabled nach Cooldown
# --------------------------------------------------------------------- #


def test_send_btn_shows_abbrechen_during_run(qtbot, chat_view):
    """Waehrend ein Worker laeuft, wird der Senden-Button zu 'Abbrechen'
    umbeschriftet und das Eingabefeld ist deaktiviert."""
    chat_view._controller = _StubController()
    _set_input_text(chat_view, "Starte")
    qtbot.keyClick(chat_view.input_edit, Qt.Key.Key_Return)

    # Sofort danach ist der Worker aktiv
    assert chat_view._chat_thread is not None
    assert chat_view.send_btn.text() == "Abbrechen"
    assert chat_view.send_btn.isEnabled() is True
    assert chat_view.input_edit.isEnabled() is False
    assert chat_view.reset_btn.isEnabled() is False

    # Auf saubere Beendigung warten
    qtbot.waitUntil(lambda: chat_view._chat_thread is None, timeout=3000)
    # Nach dem Thread-Ende ist der Senden-Button wieder normal
    assert chat_view.send_btn.text() == "Senden"
    assert chat_view.input_edit.isEnabled() is True


def test_cancel_disables_button_then_reenables_after_cooldown(qtbot, chat_view):
    """Klick auf 'Abbrechen' deaktiviert den Button, nach 500ms
    Cooldown wird er wieder aktiviert."""
    chat_view._controller = _StubController()
    _set_input_text(chat_view, "Starte")
    qtbot.keyClick(chat_view.input_edit, Qt.Key.Key_Return)
    # Worker laeuft
    assert chat_view._chat_thread is not None

    # Klick auf 'Abbrechen' (waehrend Worker laeuft)
    qtbot.mouseClick(chat_view.send_btn, Qt.MouseButton.LeftButton)
    # Sofort: Button ist deaktiviert
    assert chat_view.send_btn.isEnabled() is False
    # Status zeigt 'Abgebrochen.'
    assert "Abgebrochen" in chat_view.status_label.text()
    # Thread wurde abgebaut
    assert chat_view._chat_thread is None

    # Nach > 500ms (Cooldown) ist der Button wieder aktiv
    qtbot.waitUntil(
        lambda: chat_view.send_btn.isEnabled() is True, timeout=2000
    )
    assert chat_view.send_btn.isEnabled() is True


# --------------------------------------------------------------------- #
# 4) Reset-Button leert Chat + _controller.reset()
# --------------------------------------------------------------------- #


def test_reset_clears_history_and_calls_controller_reset(qtbot, chat_view):
    """Klick auf 'Zuruecksetzen' leert die Historie UND ruft
    ``_controller.reset()`` auf."""
    # Stub-Controller einsetzen + ein paar Bubbles erzeugen
    chat_view._controller = _StubController()
    chat_view._add_bubble("Frage 1", "user")
    chat_view._add_bubble("Antwort 1", "assistant")
    chat_view.sources_list.addItem("dummy")  # eine Quellen-Zeile
    assert _bubble_count(chat_view) == 2
    assert chat_view.sources_list.count() == 1

    # Reset klicken
    qtbot.mouseClick(chat_view.reset_btn, Qt.MouseButton.LeftButton)

    # Historie wurde geleert
    assert _bubble_count(chat_view) == 0
    # Quellen-Panel wurde geleert
    assert chat_view.sources_list.count() == 0
    # _controller.reset() wurde aufgerufen
    assert chat_view._controller.reset_calls == 1


def test_reset_without_controller_does_not_crash(qtbot, chat_view):
    """Reset ist auch sicher, wenn noch kein Controller existiert
    (lazy-Init). Es darf kein ``AttributeError`` fliegen."""
    assert chat_view._controller is None
    # Dummy-Bubble hinzufuegen
    chat_view._add_bubble("Hi", "user")
    assert _bubble_count(chat_view) == 1
    # Reset
    qtbot.mouseClick(chat_view.reset_btn, Qt.MouseButton.LeftButton)
    assert _bubble_count(chat_view) == 0
    # Controller ist immer noch None (Reset hat nicht versucht, einen
    # zu erzeugen)
    assert chat_view._controller is None


# --------------------------------------------------------------------- #
# 5) Bonus: open_pdf_requested-Signal
# --------------------------------------------------------------------- #


def test_open_pdf_requested_signal_for_source_click(qtbot, chat_view):
    """Klick auf einen Quellen-Eintrag emittiert ``open_pdf_requested``
    mit dem gespeicherten file_path."""
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtWidgets import QListWidgetItem

    item = QListWidgetItem("D1: test.pdf")
    item.setData(_Qt.ItemDataRole.UserRole, "/pfad/zu/test.pdf")
    chat_view.sources_list.addItem(item)

    with qtbot.waitSignal(
        chat_view.open_pdf_requested, timeout=1000
    ) as signal:
        chat_view.sources_list.itemClicked.emit(item)

    args = signal.args
    assert args == ["/pfad/zu/test.pdf"]


# --------------------------------------------------------------------- #
# 6) Phase 3 (Issue #25): pdf_id-Preferenz beim PDF-Oeffnen
# --------------------------------------------------------------------- #


def test_source_click_uses_pdf_id_via_db_lookup(qtbot, tmp_path):
    """Klick auf einen Quellen-Eintrag mit gesetzter ``pdf_id`` loest
    einen DB-Lookup aus und emittiert den aktuellen ``file_path`` aus
    der DB (nicht den ggf. veralteten Wert im Item).

    Phase 3 (Issue #25): pdf_id ist der stabile Identitaetsanker.
    """
    from src.utils.database import Database
    from src.gui.chat_view import ChatView
    from src.utils.config import ChatConfig
    from PyQt6.QtWidgets import QListWidgetItem
    from PyQt6.QtCore import Qt as _Qt

    # Echte DB mit einem Dokument
    db = Database(db_path=str(tmp_path / "chatview_pdfid.db"))
    db.index_document(
        file_path="/real/path/to/aktuell.pdf",
        filename="aktuell.pdf",
        extracted_text="Aktueller Inhalt",
    )
    # pdf_id dieses Dokuments holen
    raw = db.search_documents("aktuell", limit=1)
    assert raw, "Test-Setup fehlerhaft: kein DB-Treffer"
    pid = raw[0]["pdf_id"]
    assert len(pid) == 32

    view = ChatView(db=db, hybrid_classifier=_StubLLM(),
                    chat_config=ChatConfig())
    qtbot.addWidget(view)

    # Quellen-Item mit (alter) file_path + pdf_id simulieren.
    # Der alte file_path weicht bewusst vom echten DB-Pfad ab,
    # damit der Test prueft, dass die pdf_id bevorzugt wird.
    item = QListWidgetItem(f"D1: aktuell.pdf  [#{pid[:8]}…]")
    item.setData(_Qt.ItemDataRole.UserRole, "/alter/falscher/pfad.pdf")
    item.setData(_Qt.ItemDataRole.UserRole + 1, pid)
    view.sources_list.addItem(item)

    # Klick -> open_pdf_requested muss den DB-Pfad liefern, NICHT
    # den veralteten file_path.
    with qtbot.waitSignal(
        view.open_pdf_requested, timeout=2000
    ) as signal:
        view.sources_list.itemClicked.emit(item)

    args = signal.args
    # Der DB-Pfad wurde aufgeloest
    assert args == ["/real/path/to/aktuell.pdf"]


def test_source_click_falls_back_to_file_path_when_no_pdf_id(qtbot, chat_view):
    """Ohne ``pdf_id`` im Item faellt der Lookup auf ``file_path``
    zurueck (alte Aufrufer-Kompatibilitaet)."""
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtWidgets import QListWidgetItem

    item = QListWidgetItem("D1: legacy.pdf")
    item.setData(_Qt.ItemDataRole.UserRole, "/pfad/legacy.pdf")
    # Keine pdf_id gesetzt
    chat_view.sources_list.addItem(item)

    with qtbot.waitSignal(
        chat_view.open_pdf_requested, timeout=1000
    ) as signal:
        chat_view.sources_list.itemClicked.emit(item)

    assert signal.args == ["/pfad/legacy.pdf"]


def test_resolve_file_path_prefers_pdf_id(tmp_path):
    """_resolve_file_path bevorzugt pdf_id bei DB-Treffer."""
    from src.utils.database import Database
    from src.gui.chat_view import ChatView
    from src.utils.config import ChatConfig
    from src.ml.hybrid_classifier import HybridClassifier

    db = Database(db_path=str(tmp_path / "resolve_test.db"))
    db.index_document(
        file_path="/resolved/path.pdf",
        filename="path.pdf",
        extracted_text="hello",
    )
    raw = db.search_documents("hello", limit=1)
    pid = raw[0]["pdf_id"]

    # HybridClassifier-Stub, der nur das noetige bietet
    class _StubHC:
        llm_provider = None
        def is_llm_available(self):
            return False

    view = ChatView(db=db, hybrid_classifier=_StubHC(),
                    chat_config=ChatConfig())
    # Wenn pdf_id gesetzt ist, wird der DB-Pfad zurueckgegeben
    assert view._resolve_file_path("/old/path.pdf", pid) == "/resolved/path.pdf"
    # Wenn nur file_path: bleibt er
    assert view._resolve_file_path("/only/path.pdf", "") == "/only/path.pdf"
    # Wenn beides leer: leerer String
    assert view._resolve_file_path("", "") == ""


def test_resolve_file_path_unknown_pdf_id_falls_back(tmp_path):
    """Unbekannte pdf_id -> Fallback auf file_path, kein Crash."""
    from src.utils.database import Database
    from src.gui.chat_view import ChatView
    from src.utils.config import ChatConfig
    import uuid as _uuid

    db = Database(db_path=str(tmp_path / "resolve_fallback.db"))

    class _StubHC:
        llm_provider = None
        def is_llm_available(self):
            return False

    view = ChatView(db=db, hybrid_classifier=_StubHC(),
                    chat_config=ChatConfig())
    unknown_pid = _uuid.uuid4().hex
    # Unbekannte pdf_id -> Fallback auf file_path
    result = view._resolve_file_path("/fallback/path.pdf", unknown_pid)
    assert result == "/fallback/path.pdf"


# --------------------------------------------------------------------- #
# Helper: minimaler Signal-Spy (kein extra pytest-qt-Feature noetig)
# --------------------------------------------------------------------- #


class _SignalSpy:
    """Minimaler Ersatz fuer ``QSignalSpy``."""

    def __init__(self, signal):
        self.count = 0
        signal.connect(self._on_emit)

    def _on_emit(self, *args, **kwargs):
        self.count += 1


def pytestqt_signal_spy(signal):
    """Factory: liefert einen ``_SignalSpy`` fuer ein pyqtSignal."""
    return _SignalSpy(signal)

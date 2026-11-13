"""GUI-Tests der ChatView fuer die Werkzeug-Schleife (Issue #166/#167, Phase 2).

pytest-qt, Stubs wie in ``tests/test_chat_view_gui.py``:

* Arbeitsschritte: ein Block "🔧 Arbeitsschritte (n)" vor der Antwort, je
  Schritt eine kompakte Bubble mit Symbol je Werkzeug, Fehler-Schritte in
  der Fehlerfarbe; der Knopf blendet die Schritte aus und ein
* "Abgebrochen." und "Werkzeugaufruf fehlgeschlagen" mit Schritten
* Quellen-Panel: Gruppen "Zitiert" / "Gelesen" / "Gefunden" mit Kopfzeilen,
  Klick auf eine Kopfzeile oeffnet nichts; ohne Status flach wie bisher
* Chat-Provider: ``chat_provider_quelle`` beim Controllerbau,
  ``provider_geaendert()`` verwirft den Controller und uebernimmt die
  Session, Banner nur ohne jeden verfuegbaren Provider

Kein Test ruft ein echtes LLM; der RAGController wird durch Stubs bzw. eine
Fabrik-Attrappe (monkeypatch auf ``src.gui.chat_view.RAGController``) ersetzt.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QListWidgetItem, QToolButton, QWidget

from src.gui.chat_view import _BUBBLE_STYLES, ChatView
from src.gui.farben import css
from src.rag.rag_controller import ABGEBROCHEN_TEXT, RAGResponse
from src.rag.retrieval import RetrievedDoc
from src.rag.werkzeuge import Schritt
from src.utils.config import ChatConfig
from tests.conftest import patch_singletons

# --------------------------------------------------------------------- #
# Stubs und Fixtures
# --------------------------------------------------------------------- #


class _StubLLM:
    """HybridClassifier-Stub mit ``.llm_provider`` und ``.is_llm_available()``."""

    def __init__(self, available: bool = False, provider=None):
        self.llm_provider = provider
        self._available = available

    def is_llm_available(self) -> bool:
        return self._available


class _Provider:
    """LLMProvider-Attrappe fuer die Quelle des Chat-Modells."""

    def __init__(self, available: bool = True, name: str = "chat"):
        self._available = available
        self.name = name

    def is_available(self) -> bool:
        return self._available


class _StubController:
    """``ask(question, bezug=None)`` liefert die vorgegebene Antwort."""

    def __init__(self, antwort: RAGResponse):
        self.antwort = antwort
        self.fragen = []
        self.chat_session = object()

    def reset(self) -> None:
        pass

    def ask(self, question: str, bezug=None):
        self.fragen.append(question)
        return self.antwort


def _fabrik():
    """Fabrik-Attrappe fuer ``RAGController``: merkt sich alle Instanzen und Argumente."""

    class _FabrikController:
        instanzen: list = []

        def __init__(self, db, llm_provider, chat_config):
            self.db = db
            self.llm_provider = llm_provider
            self.chat_config = chat_config
            self.chat_session = object()
            _FabrikController.instanzen.append(self)

        def reset(self) -> None:
            pass

        def ask(self, question: str, bezug=None):
            return RAGResponse(answer_text="", used_llm=False)

    return _FabrikController


@pytest.fixture
def stub_llm():
    return _StubLLM(available=False)


@pytest.fixture
def chat_view(qtbot, tmp_path, monkeypatch, stub_llm):
    """Frische ChatView mit leerer DB, Stub-LLM und Singletons auf tmp_path."""
    from src.utils import config as cfg_mod
    from src.utils.database import Database

    cfg = cfg_mod.Config(config_path=tmp_path / "config.json")
    db = Database(db_path=str(tmp_path / "chatview_werkzeuge.db"))
    patch_singletons(monkeypatch, {"get_config": lambda: cfg, "get_database": lambda: db})
    view = ChatView(db=db, hybrid_classifier=stub_llm, chat_config=ChatConfig())
    qtbot.addWidget(view)
    return view


# --------------------------------------------------------------------- #
# Helfer
# --------------------------------------------------------------------- #


def _schritt(werkzeug: str, text: str, fehler: str = "", **argumente) -> Schritt:
    return Schritt(werkzeug, argumente, text, fehler=fehler)


def _doc(index: int, name: str, status: str | None = None, pfad: str = "") -> RetrievedDoc:
    doc = RetrievedDoc(
        index=index, file_path=pfad or f"/ablage/{name}", filename=name,
        text_snippet="", rank=index,
    )
    if status is not None:
        doc.extra["status"] = status
    return doc


def _wrappers(view: ChatView) -> list[QWidget]:
    """Alle Eintraege der Historie (ohne den abschliessenden Stretch)."""
    return [
        view.history_layout.itemAt(i).widget()
        for i in range(view.history_layout.count() - 1)
    ]


def _schritte_knopf(view: ChatView) -> QToolButton | None:
    for w in _wrappers(view):
        for btn in w.findChildren(QToolButton):
            if btn.property("arbeitsschritte"):
                return btn
    return None


def _schritte_box(view: ChatView) -> QWidget | None:
    for w in _wrappers(view):
        for box in w.findChildren(QWidget):
            if box.property("schritte_box"):
                return box
    return None


def _schritt_labels(view: ChatView) -> list[QLabel]:
    labels = []
    for w in _wrappers(view):
        labels += [lbl for lbl in w.findChildren(QLabel) if lbl.property("schritt")]
    return labels


def _bubbles(view: ChatView) -> list[QLabel]:
    """Alle Nachrichten-Bubbles (QLabel ohne Schritt-Markierung) in Reihenfolge."""
    labels = []
    for w in _wrappers(view):
        labels += [lbl for lbl in w.findChildren(QLabel) if not lbl.property("schritt")]
    return labels


def _klartext(label: QLabel) -> str:
    """Sichtbarer Text einer Bubble (Antworten sind seit #199 formatiertes HTML)."""
    from PyQt6.QtGui import QTextDocument

    doc = QTextDocument()
    doc.setHtml(label.text())
    return doc.toPlainText()


def _antwort_mit_schritten(text: str = "Die Rechnung ist da.", used_llm: bool = True) -> RAGResponse:
    return RAGResponse(
        answer_text=text,
        used_llm=used_llm,
        werkzeuge_benutzt=True,
        schritte=[
            _schritt("suche", "Suche „226541“: 2 Treffer (D2, D3)", abfrage="226541"),
            _schritt("dokument_lesen", "D2 gelesen: Jahresabrechnung.pdf (3 Seiten)", dokument="2"),
        ],
        retrieved_docs=[_doc(1, "bezug.pdf", "gefunden"), _doc(2, "Jahresabrechnung.pdf", "zitiert")],
    )


# --------------------------------------------------------------------- #
# Arbeitsschritte
# --------------------------------------------------------------------- #


def test_schritte_werden_als_block_vor_der_antwort_gerendert(chat_view):
    chat_view._zeige_antwort(_antwort_mit_schritten())

    knopf = _schritte_knopf(chat_view)
    assert knopf is not None and knopf.isCheckable() and knopf.isChecked()
    assert knopf.text() == "▾ 🔧 Arbeitsschritte (2)"

    labels = _schritt_labels(chat_view)
    assert [lbl.text() for lbl in labels] == [
        "🔎 Suche „226541“: 2 Treffer (D2, D3)",
        "📖 D2 gelesen: Jahresabrechnung.pdf (3 Seiten)",
    ]
    assert all(lbl.property("fehler") is False for lbl in labels)
    assert "abfrage=226541" in labels[0].toolTip()

    # Reihenfolge: Schritte-Block vor der Antwort-Bubble
    wrappers = _wrappers(chat_view)
    index_schritte = next(i for i, w in enumerate(wrappers) if w.findChildren(QToolButton))
    index_antwort = next(
        i for i, w in enumerate(wrappers)
        if any("Die Rechnung ist da." in lbl.text() for lbl in w.findChildren(QLabel))
    )
    assert index_schritte < index_antwort
    assert _bubbles(chat_view)[-1].styleSheet() == css(_BUBBLE_STYLES["assistant"])


def test_symbole_je_werkzeug_und_fehlerstil(chat_view):
    antwort = RAGResponse(
        answer_text="Fertig.", used_llm=True, werkzeuge_benutzt=True,
        schritte=[
            _schritt("suche", "Suche „a“: 0 Treffer"),
            _schritt("dokument_lesen", "D1 gelesen"),
            _schritt("ordner_vorschlag", "Ordnervorschlag für D1: Ablage/Energie"),
            _schritt("korrespondent_info", "Korrespondent „Stadtwerke“: 3 Dokumente"),
            _schritt("sql_abfrage", "SQL-Abfrage: 5 Zeilen"),
            _schritt("unbekannt", "Irgendwas"),
            _schritt("suche", "suche: Fehler - Suchindex nicht verfügbar",
                     fehler="Suchindex nicht verfügbar"),
        ],
    )
    chat_view._zeige_antwort(antwort)

    labels = _schritt_labels(chat_view)
    assert len(labels) == 7
    symbole = [lbl.text().split(" ", 1)[0] for lbl in labels]
    assert symbole == ["🔎", "📖", "📁", "👤", "🗄", "🔧", "🔎"]
    assert _schritte_knopf(chat_view).text().endswith("(7)")

    ok, fehler = labels[0], labels[-1]
    assert ok.property("fehler") is False and "#8a1f1f" not in ok.styleSheet()
    assert fehler.property("fehler") is True and "#8a1f1f" in fehler.styleSheet()
    assert "Suchindex nicht verfügbar" in fehler.toolTip()


def test_knopf_blendet_schritte_aus_und_ein(qtbot, chat_view):
    chat_view._zeige_antwort(_antwort_mit_schritten())
    knopf = _schritte_knopf(chat_view)
    box = _schritte_box(chat_view)
    assert box is not None and not box.isHidden()

    qtbot.mouseClick(knopf, Qt.MouseButton.LeftButton)
    assert box.isHidden()
    assert not knopf.isChecked()
    assert knopf.text() == "▸ 🔧 Arbeitsschritte (2)"

    qtbot.mouseClick(knopf, Qt.MouseButton.LeftButton)
    assert not box.isHidden()
    assert knopf.text() == "▾ 🔧 Arbeitsschritte (2)"


def test_ohne_schritte_kein_block(chat_view):
    chat_view._zeige_antwort(RAGResponse(answer_text="Hallo", used_llm=True))
    assert _schritte_knopf(chat_view) is None
    assert _schritt_labels(chat_view) == []
    assert [_klartext(b) for b in _bubbles(chat_view)] == ["Hallo"]


def test_abbruch_mit_schritten_zeigt_schritte_und_system_bubble(chat_view):
    antwort = RAGResponse(
        answer_text=ABGEBROCHEN_TEXT, used_llm=False, werkzeuge_benutzt=True,
        schritte=[_schritt("suche", "Suche „x“: 1 Treffer (D1)")],
        retrieved_docs=[_doc(1, "x.pdf", "gefunden")],
    )
    chat_view._zeige_antwort(antwort)

    assert len(_schritt_labels(chat_view)) == 1
    bubbles = _bubbles(chat_view)
    assert [b.text() for b in bubbles] == ["Abgebrochen."]
    assert bubbles[0].styleSheet() == css(_BUBBLE_STYLES["system"])
    # Kein Offline-Hinweis, die Quellen stehen trotzdem im Panel
    assert chat_view.sources_list.count() == 2  # Kopfzeile "Gefunden" + D1


def test_werkzeugfehler_mit_schritten_zeigt_fehler_bubble(chat_view):
    antwort = RAGResponse(
        answer_text="Werkzeugaufruf fehlgeschlagen: Verbindung weg",
        used_llm=False, werkzeuge_benutzt=True,
        schritte=[_schritt("suche", "Suche „x“: 0 Treffer")],
    )
    chat_view._zeige_antwort(antwort)

    bubbles = _bubbles(chat_view)
    assert [b.text() for b in bubbles] == ["Werkzeugaufruf fehlgeschlagen: Verbindung weg"]
    assert bubbles[0].styleSheet() == css(_BUBBLE_STYLES["error"])
    assert len(_schritt_labels(chat_view)) == 1


def test_offline_weg_bleibt_unveraendert(chat_view):
    chat_view._zeige_antwort(RAGResponse(answer_text="", used_llm=False))
    assert [b.text() for b in _bubbles(chat_view)] == ["Keine passenden Dokumente gefunden."]
    assert _schritte_knopf(chat_view) is None


def test_reset_entfernt_auch_den_schritte_block(qtbot, chat_view):
    chat_view._zeige_antwort(_antwort_mit_schritten())
    assert _schritte_knopf(chat_view) is not None
    qtbot.mouseClick(chat_view.reset_btn, Qt.MouseButton.LeftButton)
    assert _wrappers(chat_view) == []
    assert chat_view.sources_list.count() == 0


def test_antwort_ueber_den_worker_rendert_schritte_und_gruppen(qtbot, chat_view):
    """Der ganze Weg: Senden -> Worker-Thread -> finished -> Schritte + Quellen-Gruppen."""
    ctrl = _StubController(_antwort_mit_schritten())
    chat_view._controller = ctrl
    chat_view.input_edit.setPlainText("Wo ist die Jahresabrechnung?")
    chat_view._on_send()
    qtbot.waitUntil(lambda: chat_view._chat_thread is None, timeout=5000)

    assert ctrl.fragen == ["Wo ist die Jahresabrechnung?"]
    assert _schritte_knopf(chat_view) is not None
    assert len(_schritt_labels(chat_view)) == 2
    texte = [_klartext(b) for b in _bubbles(chat_view)]
    assert texte == ["Wo ist die Jahresabrechnung?", "Die Rechnung ist da."]
    eintraege = [chat_view.sources_list.item(i).text() for i in range(chat_view.sources_list.count())]
    assert eintraege == ["Zitiert", "D2: Jahresabrechnung.pdf", "Gefunden", "D1: bezug.pdf"]


# --------------------------------------------------------------------- #
# Quellen-Panel mit Gruppen
# --------------------------------------------------------------------- #


def test_quellen_gruppen_mit_kopfzeilen_in_fester_reihenfolge(chat_view):
    docs = [
        _doc(1, "a.pdf", "gefunden"),
        _doc(2, "b.pdf", "zitiert"),
        _doc(3, "c.pdf", "gelesen"),
        _doc(4, "d.pdf", "zitiert"),
        _doc(5, "e.pdf"),  # ohne Status -> "Gefunden"
    ]
    chat_view._populate_sources(docs)
    liste = chat_view.sources_list
    texte = [liste.item(i).text() for i in range(liste.count())]
    assert texte == [
        "Zitiert", "D2: b.pdf", "D4: d.pdf",
        "Gelesen", "D3: c.pdf",
        "Gefunden", "D1: a.pdf", "D5: e.pdf",
    ]
    for i in (0, 3, 5):
        kopf = liste.item(i)
        assert kopf.font().bold()
        assert not (kopf.flags() & Qt.ItemFlag.ItemIsSelectable)
        assert kopf.data(Qt.ItemDataRole.UserRole) is None
        assert kopf.data(Qt.ItemDataRole.UserRole + 1) is None
    eintrag = liste.item(1)
    assert not eintrag.font().bold()
    assert eintrag.flags() & Qt.ItemFlag.ItemIsSelectable
    assert eintrag.data(Qt.ItemDataRole.UserRole) == "/ablage/b.pdf"


def test_nur_nicht_leere_gruppen(chat_view):
    chat_view._populate_sources([_doc(1, "a.pdf", "zitiert"), _doc(2, "b.pdf", "zitiert")])
    liste = chat_view.sources_list
    texte = [liste.item(i).text() for i in range(liste.count())]
    assert texte == ["Zitiert", "D1: a.pdf", "D2: b.pdf"]


def test_ohne_status_flache_liste_wie_bisher(chat_view):
    chat_view._populate_sources([_doc(1, "a.pdf"), _doc(2, "b.pdf")])
    liste = chat_view.sources_list
    texte = [liste.item(i).text() for i in range(liste.count())]
    assert texte == ["D1: a.pdf", "D2: b.pdf"]
    assert all(liste.item(i).flags() & Qt.ItemFlag.ItemIsSelectable for i in range(2))


def test_klick_auf_kopfzeile_oeffnet_nichts_klick_auf_eintrag_schon(qtbot, chat_view):
    chat_view._populate_sources([_doc(1, "a.pdf", "zitiert", pfad="/pfad/a.pdf")])
    liste = chat_view.sources_list
    kopf, eintrag = liste.item(0), liste.item(1)
    assert kopf.text() == "Zitiert"

    with qtbot.assertNotEmitted(chat_view.open_pdf_requested, wait=200):
        with qtbot.assertNotEmitted(chat_view.open_pdf_page_requested, wait=200):
            liste.itemClicked.emit(kopf)

    with qtbot.waitSignal(chat_view.open_pdf_requested, timeout=1000) as blocker:
        liste.itemClicked.emit(eintrag)
    assert blocker.args == ["/pfad/a.pdf"]


def test_on_source_clicked_ignoriert_fremde_kopfzeile_und_none(qtbot, chat_view):
    from src.gui.chat_view import _kopfzeile

    with qtbot.assertNotEmitted(chat_view.open_pdf_requested, wait=100):
        chat_view._on_source_clicked(_kopfzeile("Gelesen"))
        chat_view._on_source_clicked(None)
        chat_view._on_source_clicked(QListWidgetItem("ohne Daten"))


# --------------------------------------------------------------------- #
# Chat-Provider: Quelle, provider_geaendert, Banner
# --------------------------------------------------------------------- #


def test_chat_provider_quelle_wird_beim_controllerbau_benutzt(qtbot, chat_view, monkeypatch):
    fabrik = _fabrik()
    monkeypatch.setattr("src.gui.chat_view.RAGController", fabrik)
    chat_provider = _Provider(name="chat")
    chat_view.hybrid_classifier.llm_provider = _Provider(name="sortierung")
    chat_view.chat_provider_quelle = lambda: chat_provider

    chat_view.input_edit.setPlainText("Hallo")
    chat_view._on_send()
    qtbot.waitUntil(lambda: chat_view._chat_thread is None, timeout=5000)

    assert len(fabrik.instanzen) == 1
    ctrl = fabrik.instanzen[0]
    assert chat_view._controller is ctrl
    assert ctrl.llm_provider is chat_provider
    assert ctrl.db is chat_view.db and ctrl.chat_config is chat_view.chat_config


@pytest.mark.parametrize("quelle", [None, lambda: None])
def test_ohne_chat_provider_gilt_das_modell_der_sortierung(qtbot, chat_view, monkeypatch, quelle):
    fabrik = _fabrik()
    monkeypatch.setattr("src.gui.chat_view.RAGController", fabrik)
    sortierung = _Provider(name="sortierung")
    chat_view.hybrid_classifier.llm_provider = sortierung
    chat_view.chat_provider_quelle = quelle

    chat_view.input_edit.setPlainText("Hallo")
    chat_view._on_send()
    qtbot.waitUntil(lambda: chat_view._chat_thread is None, timeout=5000)

    assert fabrik.instanzen[0].llm_provider is sortierung


def test_werfende_quelle_faellt_auf_die_sortierung_zurueck(qtbot, chat_view, monkeypatch):
    fabrik = _fabrik()
    monkeypatch.setattr("src.gui.chat_view.RAGController", fabrik)
    sortierung = _Provider(name="sortierung")
    chat_view.hybrid_classifier.llm_provider = sortierung

    def kaputt():
        raise RuntimeError("Konfiguration kaputt")

    chat_view.chat_provider_quelle = kaputt
    chat_view.refresh_llm_status()  # darf nicht werfen
    chat_view.input_edit.setPlainText("Hallo")
    chat_view._on_send()
    qtbot.waitUntil(lambda: chat_view._chat_thread is None, timeout=5000)
    assert fabrik.instanzen[0].llm_provider is sortierung


def test_provider_geaendert_verwirft_controller_und_uebernimmt_session(qtbot, chat_view, monkeypatch):
    fabrik = _fabrik()
    monkeypatch.setattr("src.gui.chat_view.RAGController", fabrik)
    alt = fabrik(chat_view.db, None, chat_view.chat_config)
    verlauf = alt.chat_session
    chat_view._controller = alt

    chat_view.provider_geaendert()
    assert chat_view._controller is None
    assert chat_view._session_uebernahme is verlauf
    # Zweiter Aufruf ohne Controller laesst den gemerkten Verlauf stehen
    chat_view.provider_geaendert()
    assert chat_view._session_uebernahme is verlauf

    neuer_provider = _Provider(name="neu")
    chat_view.chat_provider_quelle = lambda: neuer_provider
    chat_view.input_edit.setPlainText("Weiter")
    chat_view._on_send()
    qtbot.waitUntil(lambda: chat_view._chat_thread is None, timeout=5000)

    neu = chat_view._controller
    assert neu is not alt and neu is fabrik.instanzen[-1]
    assert neu.chat_session is verlauf
    assert neu.llm_provider is neuer_provider
    assert chat_view._session_uebernahme is None


def test_reset_verwirft_die_gemerkte_session(qtbot, chat_view):
    chat_view._session_uebernahme = object()
    qtbot.mouseClick(chat_view.reset_btn, Qt.MouseButton.LeftButton)
    assert chat_view._session_uebernahme is None


def test_banner_nur_ohne_jeden_verfuegbaren_provider(chat_view):
    # Sortierung aus, kein Chat-Provider -> Banner
    assert not chat_view.banner.isHidden()

    # Chat-Provider verfuegbar -> kein Banner
    chat_view.chat_provider_quelle = lambda: _Provider(available=True)
    chat_view.refresh_llm_status()
    assert chat_view.banner.isHidden()

    # Chat-Provider da, aber nicht verfuegbar; Sortierung aus -> Banner
    chat_view.chat_provider_quelle = lambda: _Provider(available=False)
    chat_view.refresh_llm_status()
    assert not chat_view.banner.isHidden()

    # Sortierung an, Chat-Provider nicht verfuegbar -> kein Banner
    chat_view.hybrid_classifier._available = True
    chat_view.refresh_llm_status()
    assert chat_view.banner.isHidden()

    # Sortierung an, Quelle liefert None -> kein Banner
    chat_view.chat_provider_quelle = lambda: None
    chat_view.refresh_llm_status()
    assert chat_view.banner.isHidden()


def test_provider_geaendert_zieht_das_banner_nach(chat_view):
    assert not chat_view.banner.isHidden()
    chat_view.chat_provider_quelle = lambda: _Provider(available=True)
    chat_view.provider_geaendert()
    assert chat_view.banner.isHidden()
    assert chat_view._controller is None and chat_view._session_uebernahme is None

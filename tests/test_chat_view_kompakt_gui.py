"""ChatView kompakt (Phase 3, Issue #166/#167): schmale Spalte, Schnellfragen-Menue, "Nach … verschieben"."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton, QToolButton

from src.gui.chat_view import ChatView
from src.rag.bezug import SCHNELLFRAGEN
from src.rag.citation import Citation
from src.rag.rag_controller import RAGResponse
from src.rag.retrieval import RetrievedDoc
from src.utils.config import ChatConfig


class _StubLLM:
    llm_provider = None

    def is_llm_available(self) -> bool:
        return False


def _view(qtbot, kompakt: bool) -> ChatView:
    view = ChatView(db=None, hybrid_classifier=_StubLLM(), chat_config=ChatConfig(), kompakt=kompakt)
    qtbot.addWidget(view)
    return view


def _antwort(tmp_path, ordner: str = "") -> RAGResponse:
    doc = RetrievedDoc(index=2, file_path=str(tmp_path / "Ablage" / "Energie" / "a.pdf"), filename="a.pdf",
                       text_snippet="", rank=1)
    return RAGResponse(
        answer_text="Gehört zur Kellermannstr. 3 [2].", used_llm=True,
        citations=[Citation(index=2, filename="a.pdf", file_path=doc.file_path, valid=True)],
        retrieved_docs=[doc], ordner_vorschlag=ordner, ordner_anzeige="Ablage/Energie" if ordner else "",
        ordner_begruendung="belegt durch [2]" if ordner else "",
    )


def test_kompakt_quellen_unter_dem_verlauf_und_schnellfragen_untereinander(qtbot):
    view = _view(qtbot, kompakt=True)
    assert view.split.orientation() == Qt.Orientation.Vertical
    assert view.sources_list.isHidden()  # eingeklappt
    assert [b.text() for b in view.schnellfragen_btns] == list(SCHNELLFRAGEN)
    assert isinstance(view.schnellfragen_toggle, QToolButton)
    assert view.schnellfragen_toggle.text() == "▾ Schnellfragen"  # ausgeklappt
    view.set_bezug(Path("C:/Scan/a.pdf"))  # Schnellfragen gehoeren zum Bezug-Block
    assert view.schnellfragen_box.isVisibleTo(view)
    # Breiter Reiter wie bisher: Raster, kein Dreieck
    breit = _view(qtbot, kompakt=False)
    assert breit.split.orientation() == Qt.Orientation.Horizontal
    assert breit.schnellfragen_toggle is None and len(breit.schnellfragen_btns) == 4


def test_schnellfrage_knopf_sendet_und_ist_waehrend_des_aufrufs_gesperrt(qtbot, monkeypatch):
    view = _view(qtbot, kompakt=True)
    gesendet = []
    monkeypatch.setattr(view, "_on_send", lambda: gesendet.append(view.input_edit.toPlainText()))
    view.set_bezug(Path("C:/Scan/a.pdf"))
    view.schnellfragen_btns[3].click()
    assert gesendet == [SCHNELLFRAGEN[3]]
    view._schnellfragen_freigeben(False)
    assert all(not b.isEnabled() for b in view.schnellfragen_btns)
    view._schnellfragen_freigeben(True)
    assert all(b.isEnabled() for b in view.schnellfragen_btns)


def test_schnellfragen_klappen_bei_wenig_hoehe_ein_bis_der_nutzer_entscheidet(qtbot):
    view = _view(qtbot, kompakt=True)
    view.set_bezug(Path("C:/Scan/a.pdf"))
    view.resize(400, 900)
    view.show()
    qtbot.waitExposed(view)
    assert view.schnellfragen_box.isVisibleTo(view)

    view.resize(400, 400)  # kleiner Monitor: automatisch eingeklappt
    qtbot.waitUntil(lambda: not view.schnellfragen_box.isVisibleTo(view), timeout=2000)
    assert view.schnellfragen_toggle.text() == "▸ Schnellfragen"
    view.resize(400, 900)  # wieder Platz: automatisch ausgeklappt
    qtbot.waitUntil(lambda: view.schnellfragen_box.isVisibleTo(view), timeout=2000)

    # Dreieck geklickt: die Wahl des Nutzers bleibt, egal wie gross das Fenster wird
    view.schnellfragen_toggle.click()
    assert not view.schnellfragen_box.isVisibleTo(view) and view._schnellfragen_manuell is False
    view.resize(400, 1000)
    qtbot.wait(50)
    assert not view.schnellfragen_box.isVisibleTo(view)
    view.schnellfragen_toggle.click()
    assert view.schnellfragen_box.isVisibleTo(view) and view._schnellfragen_manuell is True
    view.resize(400, 300)
    qtbot.wait(50)
    assert view.schnellfragen_box.isVisibleTo(view)


def test_quellen_titel_zaehlt(qtbot, tmp_path):
    view = _view(qtbot, kompakt=True)
    view._populate_sources(_antwort(tmp_path).retrieved_docs)
    assert view.sources_title.text() == "Quellen (1)"
    view._populate_sources([])
    assert view.sources_title.text() == "Quellen"


def test_verschieben_knopf_und_ordner_belegt_signal(qtbot, tmp_path):
    view = _view(qtbot, kompakt=True)
    ordner = str(tmp_path / "Ablage" / "Energie")
    belegt = []
    view.ordner_belegt.connect(lambda p, g: belegt.append((p, g)))
    view.set_bezug(tmp_path / "Scan" / "Neu.pdf")

    view._zeige_antwort(_antwort(tmp_path, ordner))

    knoepfe = [w for w in view.findChildren(QPushButton) if (w.property("ordner_pfad") or "")]
    assert len(knoepfe) == 1 and knoepfe[0].text() == "📁 Nach Ablage/Energie verschieben"
    assert knoepfe[0].property("ordner_pfad") == ordner
    assert "Neu.pdf" in knoepfe[0].toolTip() and "belegt durch [2]" in knoepfe[0].toolTip()
    assert belegt == [(ordner, "belegt durch [2]")]
    with qtbot.waitSignal(view.verschieben_requested, timeout=1000) as blocker:
        knoepfe[0].click()
    assert blocker.args == [ordner]


def test_kein_knopf_ohne_bezug_oder_ohne_ordner(qtbot, tmp_path):
    view = _view(qtbot, kompakt=True)
    view._zeige_antwort(_antwort(tmp_path, str(tmp_path / "Ablage" / "Energie")))  # kein Bezug gesetzt
    assert not [w for w in view.findChildren(QPushButton) if (w.property("ordner_pfad") or "")]
    view.set_bezug(tmp_path / "Scan" / "Neu.pdf")
    view._zeige_antwort(_antwort(tmp_path, ""))  # kein belegter Ordner
    assert not [w for w in view.findChildren(QPushButton) if (w.property("ordner_pfad") or "")]

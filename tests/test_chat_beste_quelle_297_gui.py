"""Issue #297: Die Hauptquelle einer Chat-Antwort erscheint in der Vorschau der Mitte.

* ``beste_zitierte_quelle``: am haeufigsten zitiert gewinnt, bei Gleichstand die
  zuerst zitierte; ungueltige Zitate zaehlen nicht
* ChatView meldet die Quelle (Pfad, Seite) per ``beste_quelle`` nach einer Antwort
* MainWindow laedt sie in die Vorschau, wenn keine PDF ausgewaehlt ist, und
  springt auf die Seite der Fundstelle; eine ausgewaehlte PDF bleibt stehen
"""
from __future__ import annotations

from pathlib import Path

from src.gui.chat_view import ChatView, beste_zitierte_quelle
from src.rag.citation import Citation
from src.rag.rag_controller import RAGResponse
from src.utils.config import ChatConfig
from tests.test_main_window_chat_gui import fenster, fresh_singletons, kein_netz  # noqa: F401 - Fixtures


class _StubLLM:
    llm_provider = None

    def is_llm_available(self) -> bool:
        return False


def _zitat(index: int, pfad: str = "", seite: int = 0, valid: bool = True) -> Citation:
    return Citation(index=index, filename=Path(pfad).name, file_path=pfad, valid=valid, seite=seite)


# --------------------------------------------------------------------------- Auswahl


def test_am_haeufigsten_zitiert_gewinnt():
    zitate = [_zitat(1, "a.pdf"), _zitat(2, "b.pdf")]
    assert beste_zitierte_quelle("Erst [1], dann [2] und nochmal [D2].", zitate).index == 2


def test_gleichstand_die_zuerst_zitierte():
    zitate = [_zitat(1, "a.pdf"), _zitat(3, "c.pdf")]
    assert beste_zitierte_quelle("Laut [3] und [1].", zitate).index == 3


def test_ungueltige_zitate_zaehlen_nicht():
    zitate = [_zitat(1, "a.pdf"), _zitat(9, valid=False)]
    assert beste_zitierte_quelle("[9] [9] [9] und [1]", zitate).index == 1
    assert beste_zitierte_quelle("[9]", [_zitat(9, valid=False)]) is None
    assert beste_zitierte_quelle("ohne Zitat", []) is None


# --------------------------------------------------------------------------- ChatView


def _view(qtbot) -> ChatView:
    view = ChatView(db=None, hybrid_classifier=_StubLLM(), chat_config=ChatConfig(), kompakt=True)
    qtbot.addWidget(view)
    return view


def test_chatview_meldet_beste_quelle_mit_seite(qtbot, tmp_path):
    view = _view(qtbot)
    pfad = str(tmp_path / "Ablage" / "Rechnung Mustermann.pdf")
    antwort = RAGResponse(answer_text="Der Betrag steht in [2], siehe auch [2] und [1].", used_llm=True,
                          citations=[_zitat(1, str(tmp_path / "x.pdf")), _zitat(2, pfad, seite=3)])
    with qtbot.waitSignal(view.beste_quelle, timeout=1000) as blocker:
        view._zeige_antwort(antwort)
    assert blocker.args == [pfad, 3]


def test_chatview_ohne_zitat_meldet_nichts(qtbot):
    view = _view(qtbot)
    gemeldet = []
    view.beste_quelle.connect(lambda p, s: gemeldet.append((p, s)))
    view._zeige_antwort(RAGResponse(answer_text="Dazu finde ich nichts.", used_llm=True))
    assert gemeldet == []


# --------------------------------------------------------------------------- MainWindow


def _pdf(tmp_path: Path, name: str = "Brief Müller.pdf") -> Path:
    pfad = tmp_path / "Ablage Ä" / name
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return pfad


def test_vorschau_zeigt_quelle_ohne_auswahl_und_springt_auf_seite(fenster, tmp_path, monkeypatch):
    win = fenster()
    geladen, seiten = [], []
    monkeypatch.setattr(win.detail_panel.preview, "load_pdf", lambda p: geladen.append(Path(p)))
    monkeypatch.setattr(win.detail_panel.preview, "go_to_page", lambda i: seiten.append(i))
    pfad = _pdf(tmp_path)
    assert win.selected_pdf is None

    win.chat_view.beste_quelle.emit(str(pfad), 4)
    assert geladen == [pfad]
    win._on_detail_vorschau_geladen(pfad)
    assert seiten == [3]  # 0-basiert
    win._on_detail_vorschau_geladen(pfad)  # nur einmal
    assert seiten == [3]


def test_ausgewaehlte_pdf_bleibt_in_der_vorschau(fenster, tmp_path, monkeypatch):
    win = fenster()
    geladen = []
    monkeypatch.setattr(win.detail_panel.preview, "load_pdf", lambda p: geladen.append(Path(p)))
    win.selected_pdf = _pdf(tmp_path, "Auswahl.pdf")
    win.chat_view.beste_quelle.emit(str(_pdf(tmp_path)), 0)
    assert geladen == []


def test_keine_pdf_oder_fehlende_datei_wird_nicht_geladen(fenster, tmp_path, monkeypatch):
    win = fenster()
    geladen = []
    monkeypatch.setattr(win.detail_panel.preview, "load_pdf", lambda p: geladen.append(Path(p)))
    docx = tmp_path / "Notiz.docx"
    docx.write_bytes(b"x")
    win.chat_view.beste_quelle.emit(str(docx), 0)
    win.chat_view.beste_quelle.emit(str(tmp_path / "fehlt.pdf"), 0)
    win.chat_view.beste_quelle.emit("", 0)
    assert geladen == []

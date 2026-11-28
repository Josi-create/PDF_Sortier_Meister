"""Speicherort des gezeigten Dokuments: oben in der Mitte und oben im Chat stehen Name und Ordner.

Wie links in "Sortieren" soll man auch bei einer Suche oder im Chat sehen, wo das Dokument liegt,
das die Vorschau gerade zeigt (ausgewaehlte PDF oder Quelle einer Chat-Antwort).
"""
from __future__ import annotations

from pathlib import Path

from tests.test_chat_hauptquelle_355_gui import _auswaehlen, _make_pdf, panel  # noqa: F401


def test_kopf_nennt_ordner_der_auswahl(qtbot, panel, tmp_path):  # noqa: F811
    auswahl = _make_pdf(tmp_path / "Eingang" / "Auswahl.pdf")
    gemeldet: list = []
    panel.vorschau_dokument_geaendert.connect(gemeldet.append)
    _auswaehlen(qtbot, panel, auswahl)
    text = panel.header_label.text()
    assert "Auswahl.pdf" in text
    assert str(auswahl.parent) in text
    assert gemeldet[-1] == auswahl


def test_chat_quelle_nennt_ordner_und_meldet_sich(qtbot, panel, tmp_path):  # noqa: F811
    auswahl = _make_pdf(tmp_path / "Eingang" / "Auswahl.pdf")
    quelle = _make_pdf(tmp_path / "Ablage" / "Handwerker" / "Rechnung.pdf")
    _auswaehlen(qtbot, panel, auswahl)
    gemeldet: list = []
    panel.vorschau_dokument_geaendert.connect(gemeldet.append)

    with qtbot.waitSignal(panel.preview.document_loaded, timeout=5000):
        panel.chat_quelle_zeigen(quelle)
    assert str(quelle.parent) in panel.chat_quelle_label.text()
    assert gemeldet[-1] == quelle

    with qtbot.waitSignal(panel.preview.document_loaded, timeout=5000):
        panel.zurueck_zur_auswahl_btn.click()
    assert gemeldet[-1] == auswahl

    panel.clear()
    assert gemeldet[-1] is None
    assert panel.header_label.text() == ""


def test_neue_auswahl_waehrend_chat_quelle_meldet_neue_auswahl(qtbot, panel, tmp_path):  # noqa: F811
    a = _make_pdf(tmp_path / "Eingang" / "A.pdf")
    b = _make_pdf(tmp_path / "Eingang" / "B.pdf")
    quelle = _make_pdf(tmp_path / "Ablage" / "Q.pdf")
    _auswaehlen(qtbot, panel, a)
    with qtbot.waitSignal(panel.preview.document_loaded, timeout=5000):
        panel.chat_quelle_zeigen(quelle)
    gemeldet: list = []
    panel.vorschau_dokument_geaendert.connect(gemeldet.append)
    _auswaehlen(qtbot, panel, b)
    assert gemeldet[-1] == b


def test_chat_leiste_zeigt_name_und_ordner(qtbot, tmp_path):
    from src.gui.chat_view import ChatView
    from src.utils.database import Database
    from tests.test_chat_view_gui import ChatConfig, _StubLLM

    db = Database(db_path=str(tmp_path / "chat.db"))
    view = ChatView(db=db, hybrid_classifier=_StubLLM(available=False), chat_config=ChatConfig(), kompakt=True)
    qtbot.addWidget(view)
    view.show()
    assert not view.angezeigt_leiste.isVisible()

    pfad = tmp_path / "Steuer 2026" / "Handwerker" / "Rechnung.pdf"
    view.set_angezeigt(pfad)
    assert view.angezeigt_leiste.isVisible()
    assert "Rechnung.pdf" in view.angezeigt_label.text()
    assert str(pfad.parent) in view.angezeigt_label.text()
    assert view.angezeigt_leiste.toolTip() == str(pfad)

    gesendet: list = []
    view.im_ordner_anzeigen_requested.connect(gesendet.append)
    view.angezeigt_ordner_btn.menu().actions()[0].trigger()
    assert gesendet == [Path(pfad)]

    view.set_angezeigt(None)
    assert not view.angezeigt_leiste.isVisible()

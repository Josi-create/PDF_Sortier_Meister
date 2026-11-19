"""Issue #355: Die Hauptquelle einer Chat-Antwort erscheint auch bei ausgewaehlter PDF in der Vorschau.

Ueber der Vorschau steht dann eine Leiste mit dem Namen der Quelle und dem Knopf
„Zurück zur ausgewählten PDF“. Auswahl und Felder des Detail-Panels bleiben.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest


def _make_pdf(path: Path, pages: int = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    try:
        for i in range(pages):
            doc.new_page().insert_text((72, 72), f"Seite {i + 1}")
        doc.save(str(path))
    finally:
        doc.close()
    return path


@pytest.fixture
def panel(qtbot, monkeypatch, tmp_path):
    from src.core.pdf_metadata import PDFMetadata
    from src.gui import detail_panel as dp
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod
    from tests.conftest import patch_singletons

    fresh_config = cfg_mod.Config(config_path=tmp_path / "config.json")
    patch_singletons(monkeypatch, {
        "get_config": lambda: fresh_config,
        "get_database": lambda: db_mod.Database(db_path=str(tmp_path / "p.db")),
    })
    monkeypatch.setattr("src.core.pdf_metadata.read_metadata", lambda p: PDFMetadata())
    p = dp.DetailPanel()
    qtbot.addWidget(p)
    p.resize(500, 900)
    p.show()
    return p


def _auswaehlen(qtbot, panel, pdf: Path) -> None:
    with qtbot.waitSignal(panel.preview.document_loaded, timeout=5000):
        panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="x", keywords=["rechnung"])


def test_quelle_mit_leiste_und_knopf_zurueck(qtbot, panel, tmp_path):
    auswahl = _make_pdf(tmp_path / "Eingang" / "Auswahl.pdf")
    quelle = _make_pdf(tmp_path / "Ablage Ä" / "Rechnung Max Mustermann.pdf", pages=3)
    _auswaehlen(qtbot, panel, auswahl)
    assert not panel.chat_quelle_leiste.isVisible()

    with qtbot.waitSignal(panel.preview.document_loaded, timeout=5000):
        panel.chat_quelle_zeigen(quelle)
    assert panel.preview.current_path == quelle
    assert panel.zeigt_chat_quelle()
    assert panel.chat_quelle_leiste.isVisible()
    assert quelle.name in panel.chat_quelle_label.text()
    assert panel.get_current_pdf() == auswahl  # Felder gehoeren weiter zur Auswahl

    with qtbot.waitSignal(panel.preview.document_loaded, timeout=5000):
        panel.zurueck_zur_auswahl_btn.click()
    assert panel.preview.current_path == auswahl
    assert not panel.zeigt_chat_quelle()
    assert not panel.chat_quelle_leiste.isVisible()


def test_frische_vorschlaege_fuer_dieselbe_pdf_lassen_die_quelle_stehen(qtbot, panel, tmp_path):
    auswahl = _make_pdf(tmp_path / "Auswahl.pdf")
    quelle = _make_pdf(tmp_path / "Quelle.pdf")
    _auswaehlen(qtbot, panel, auswahl)
    with qtbot.waitSignal(panel.preview.document_loaded, timeout=5000):
        panel.chat_quelle_zeigen(quelle)

    # z. B. KI-Vorschlaege fuer die ausgewaehlte PDF kommen nach der Chat-Antwort an
    panel.set_pdf(pdf_path=auswahl, suggestions=[], extracted_text="x", keywords=["rechnung"])
    assert panel.preview.current_path == quelle
    assert panel.chat_quelle_leiste.isVisible()


def test_andere_auswahl_oder_leeren_beendet_die_quelle(qtbot, panel, tmp_path):
    auswahl = _make_pdf(tmp_path / "Auswahl.pdf")
    andere = _make_pdf(tmp_path / "Andere.pdf")
    quelle = _make_pdf(tmp_path / "Quelle.pdf")
    _auswaehlen(qtbot, panel, auswahl)
    with qtbot.waitSignal(panel.preview.document_loaded, timeout=5000):
        panel.chat_quelle_zeigen(quelle)

    _auswaehlen(qtbot, panel, andere)
    assert panel.preview.current_path == andere
    assert not panel.zeigt_chat_quelle()
    assert not panel.chat_quelle_leiste.isVisible()

    with qtbot.waitSignal(panel.preview.document_loaded, timeout=5000):
        panel.chat_quelle_zeigen(quelle)
    panel.clear()
    assert not panel.zeigt_chat_quelle()
    assert not panel.chat_quelle_leiste.isVisible()


def test_quelle_ist_die_auswahl_selbst_ohne_leiste(qtbot, panel, tmp_path):
    auswahl = _make_pdf(tmp_path / "Auswahl.pdf")
    _auswaehlen(qtbot, panel, auswahl)
    panel.chat_quelle_zeigen(auswahl)
    assert not panel.zeigt_chat_quelle()
    assert not panel.chat_quelle_leiste.isVisible()


def test_ohne_auswahl_keine_leiste(qtbot, panel, tmp_path):
    quelle = _make_pdf(tmp_path / "Quelle.pdf")
    with qtbot.waitSignal(panel.preview.document_loaded, timeout=5000):
        panel.chat_quelle_zeigen(quelle)
    assert panel.preview.current_path == quelle
    assert not panel.zeigt_chat_quelle()
    assert not panel.chat_quelle_leiste.isVisible()

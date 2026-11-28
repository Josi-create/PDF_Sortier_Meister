"""Erster Klick nach dem Start: Schlagwoerter und Kategorien kommen vorgeladen aus dem Hintergrund.

Bisher las das Detail-Panel sie beim ersten Fuellen selbst aus dem Suchindex, im GUI-Thread;
bei einem grossen Index hing das Fenster dabei 10-40 s. Solange das Vorladen laeuft, fragt
das Panel nicht selbst und zeigt die Listen leer; sobald sie da sind, werden sie nachgetragen.

Alle Dokumente und Schlagwoerter sind erfunden.
"""
from __future__ import annotations

import pytest

from src.core import schlagwoerter as sw
from tests import helfer_suche as h


@pytest.fixture
def panel_klasse(monkeypatch):
    from src.gui.detail_panel import DetailPanel

    monkeypatch.setattr(DetailPanel, "_vorschau_laden", lambda self, pfad: None)
    monkeypatch.setattr(DetailPanel, "_start_metadata_reader", lambda self, pfad: None)
    return DetailPanel


def _kategorien(panel) -> list[str]:
    combo = panel._metadata_inputs["subject"]
    return [combo.itemText(i) for i in range(combo.count())]


def test_panel_fragt_waehrend_des_vorladens_nicht_selbst(qtbot, tmp_path, panel_klasse, monkeypatch):
    aufrufe = []
    sw.quelle_setzen(lambda haeufigste=None: aufrufe.append("schlagwoerter") or ["Haus"])
    from src.utils import database

    monkeypatch.setattr(database.Database, "get_top_kategorien",
                        lambda self, limit=10: aufrufe.append("kategorien") or ["Versicherung"])
    pdf = h.pdf_mit_text(tmp_path / "Brief.pdf", ["Ein Brief"])
    panel = panel_klasse()
    qtbot.addWidget(panel)
    panel.vorab_laden_ausstehend()

    panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="Ein Brief", keywords=[])
    assert aufrufe == []                                   # kein Warten im GUI-Thread
    assert "Nebenkosten" not in _kategorien(panel)

    # Das Vorladen meldet sich: die Listen erscheinen, ohne die Felder anzufassen
    panel._metadata_inputs["schlagwoerter"].setText("Eigenes")
    panel.vorab_listen_setzen({"schlagwoerter": ["Steuer", "Haus"], "kategorien": ["Nebenkosten"]})
    assert aufrufe == []
    assert panel._schlagwort_wahl == ["Haus", "Steuer"]
    assert "Nebenkosten" in _kategorien(panel)
    assert panel._metadata_inputs["schlagwoerter"].text() == "Eigenes"

    # Naechster Klick: die vorgeladenen Listen gelten, keine neue Abfrage
    panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="Ein Brief", keywords=[])
    assert aufrufe == []
    assert "Nebenkosten" in _kategorien(panel)


def test_fehlgeschlagenes_vorladen_faellt_auf_die_eigene_abfrage_zurueck(qtbot, tmp_path, panel_klasse):
    sw.quelle_setzen(lambda haeufigste=None: ["Garten"])
    pdf = h.pdf_mit_text(tmp_path / "Brief.pdf", ["Ein Brief"])
    panel = panel_klasse()
    qtbot.addWidget(panel)
    panel.vorab_laden_ausstehend()
    panel.vorab_listen_setzen({})                         # beide Abfragen sind gescheitert

    panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="Ein Brief", keywords=[])
    assert panel._schlagwort_wahl == ["Garten"]

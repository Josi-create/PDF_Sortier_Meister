"""Reiter „Suche“: Sortierung nach dem Datum im Dateinamen (Issue #352, wie die Kacheln in #296).

Treffer mit JJJJ-MM-TT am Namensanfang reihen sich nach diesem Datum ein, alle anderen nach
ihrem Dokumentdatum (Dateidatum bzw. Mail-Datum). Gilt mit Suchbegriff und bei reiner Filtersuche.
"""
from __future__ import annotations

import calendar
import os
from datetime import date

import pytest

from src.search import db


def _ts(j, m, t) -> float:
    return float(calendar.timegm(date(j, m, t).timetuple()))


def _dok(name, datum):
    pfad = f"/ablage/{name}"
    return {"pfad": pfad, "datei": pfad, "name": name, "ordner": "/ablage/Steuer", "typ": "pdf", "format": "pdf",
            "groesse": 1, "mtime_ns": 1, "datum": datum, "seiten": 1, "textstatus": "text"}


@pytest.fixture
def con(tmp_path):
    c = db.verbinde(tmp_path / "suche.db")
    db.init(c)
    # Dateidatum absichtlich gegenlaeufig zum Datum im Namen
    for name, datum in (("2021-05-01 Rechnung Beispiel.pdf", _ts(2024, 1, 1)),
                        ("2023-01-10 Rechnung Muster.pdf", _ts(2020, 1, 1)),
                        ("Rechnung ohne Datum.pdf", _ts(2022, 6, 1)),
                        ("2024-13-45 Rechnung ungueltig.pdf", _ts(2019, 1, 1))):
        db.speichere(c, _dok(name, datum), [(1, "text", "Rechnung über 10 Euro")])
    c.commit()
    yield c
    c.close()


NEU = ["2023-01-10 Rechnung Muster.pdf", "Rechnung ohne Datum.pdf", "2021-05-01 Rechnung Beispiel.pdf",
       "2024-13-45 Rechnung ungueltig.pdf"]


def test_mit_suchbegriff(con):
    neu = [t["name"] for t in db.suche(con, "Rechnung", sortierung="namensdatum_neu")["treffer"]]
    assert neu == NEU
    alt = [t["name"] for t in db.suche(con, "Rechnung", sortierung="namensdatum_alt")["treffer"]]
    assert alt == NEU[::-1]
    # Die bisherige Datumssortierung bleibt beim Dateidatum
    assert db.suche(con, "Rechnung", sortierung="neu")["treffer"][0]["name"] == "2021-05-01 Rechnung Beispiel.pdf"


def test_nur_filter_und_blaettern(con):
    neu = [t["name"] for t in db.suche(con, "", ordner="Steuer", sortierung="namensdatum_neu")["treffer"]]
    assert neu == NEU
    alt = [t["name"] for t in db.suche(con, "", ordner="Steuer", sortierung="namensdatum_alt")["treffer"]]
    assert alt == NEU[::-1]
    seite2 = db.suche(con, "", ordner="Steuer", sortierung="namensdatum_neu", anzahl=2, start=2)
    assert [t["name"] for t in seite2["treffer"]] == NEU[2:]
    assert seite2["gesamt"] == 4


def test_auswahl_im_reiter_suche(qtbot, tmp_path):
    from src.gui.search_view import SearchView
    from src.search.indexer import Indexer
    from src.utils.config import Config
    from tests import helfer_suche as h

    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    for name, datum in (("2021-05-01 Beleg.pdf", _ts(2024, 1, 1)), ("2023-01-10 Beleg.pdf", _ts(2020, 1, 1)),
                        ("Beleg ohne Datum.pdf", _ts(2022, 6, 1))):
        pfad = h.pdf_mit_text(ablage / name, ["Beleg Stichwort"])
        os.utime(pfad, (datum, datum))
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], prioritaet=[str(ablage)])
    assert Indexer(konfig, synchron=True).lauf() == 0
    cfg = Config(config_path=tmp_path / "config.json")
    cfg.set_search_config(konfig)
    view = SearchView(cfg)
    qtbot.addWidget(view)
    try:
        eintraege = [view.sort_combo.itemData(i) for i in range(view.sort_combo.count())]
        assert "namensdatum_neu" in eintraege and "namensdatum_alt" in eintraege
        view.sort_combo.setCurrentIndex(view.sort_combo.findData("namensdatum_neu"))
        with qtbot.waitSignal(view.suche_fertig, timeout=15000):
            view.search_edit.setText("Stichwort")
        namen = [k.dok["name"] for k in view.karten()]
        assert namen == ["2023-01-10 Beleg.pdf", "Beleg ohne Datum.pdf", "2021-05-01 Beleg.pdf"]
    finally:
        view.shutdown()

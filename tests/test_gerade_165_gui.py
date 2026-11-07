"""Issue #165: Rechtsklick "Drehen > Gerade ausrichten" mit Rueckgaengig."""
from pathlib import Path

import pytest

from tests import helfer_suche as h
from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401 - Fixtures
from tests.test_pdf_drehen_150_gui import _untermenue, beobachtet, thumbnail  # noqa: F401 - Fixtures

EINTRAG = "Gerade ausrichten (schief gescannt)"


def test_menue_eintrag_sendet_signal(thumbnail):  # noqa: F811
    empfangen = []
    thumbnail.straighten_requested.connect(empfangen.append)
    sub = _untermenue(thumbnail._build_context_menu(), "Drehen")
    next(a for a in sub.actions() if a.text() == EINTRAG).trigger()
    assert empfangen == [thumbnail.pdf_path]


@pytest.fixture
def schief_ordner(fresh_singletons):  # noqa: F811
    ordner = fresh_singletons["tmp_path"] / "Scan"
    ordner.mkdir()
    h.scan_schief(ordner / "a.pdf", 2.0)
    h.scan_schief(ordner / "b.pdf", -3.0)
    h.scan_schief(ordner / "c.pdf", 0)
    return ordner


def _gerade(pfad: Path) -> bool:
    rest = h.schraeglage_der_datei(pfad)
    return rest is not None and abs(rest) < 0.3


def test_gerade_ausrichten_frischt_auf_und_macht_rueckgaengig(main_window, schief_ordner, beobachtet):  # noqa: F811
    main_window._navigate_to_folder(schief_ordner)
    beobachtet["geladen"].clear()
    a = schief_ordner / "a.pdf"
    w = next(w for w in main_window.pdf_widgets if w.pdf_path == a)

    w.straighten_requested.emit(a)

    assert _gerade(a) and h.ausrichtung_der_datei(a) == pytest.approx(2.0, abs=0.15)
    assert beobachtet["vergessen"] == [a] and beobachtet["geladen"] == [a]
    assert beobachtet["index"] == [("datei_geaendert", str(a))]
    eintrag = main_window._undo_stack[-1]
    assert eintrag["type"] == "gerade" and eintrag["seiten"] == {a: [1]}
    assert "gerade ausgerichtet" in main_window.undo_action.text()
    assert "S. 1: 2,0°" in main_window.statusbar.currentMessage()

    main_window.undo_last_action()
    assert h.ausrichtung_der_datei(a) == 0 and not _gerade(a)
    assert not main_window._undo_stack


def test_mehrfachauswahl_und_schon_gerade(main_window, schief_ordner, beobachtet):  # noqa: F811
    main_window._navigate_to_folder(schief_ordner)
    a, b, c = (schief_ordner / f"{n}.pdf" for n in "abc")
    vorher_c = c.read_bytes()
    main_window.selected_pdfs = [a, b, c]

    main_window.on_pdf_straighten(b)

    assert _gerade(a) and _gerade(b) and c.read_bytes() == vorher_c
    assert main_window._undo_stack[-1]["seiten"] == {a: [1], b: [1]}
    text = main_window.statusbar.currentMessage()
    assert "2 PDFs gerade ausgerichtet (2 Seiten)" in text and "1 PDF(s) waren schon gerade" in text
    assert beobachtet["warnung"] == []


def test_nichts_schief_nichts_geaendert(main_window, schief_ordner, beobachtet):  # noqa: F811
    main_window._navigate_to_folder(schief_ordner)
    c = schief_ordner / "c.pdf"
    main_window.on_pdf_straighten(c)
    assert not main_window._undo_stack and beobachtet["index"] == []
    assert "Keine schief gescannte Seite" in main_window.statusbar.currentMessage()


def test_signierte_pdf_meldet_und_bleibt(main_window, schief_ordner, beobachtet):  # noqa: F811
    import pikepdf

    main_window._navigate_to_folder(schief_ordner)
    a = schief_ordner / "a.pdf"
    with pikepdf.open(str(a), allow_overwriting_input=True) as pdf:
        pdf.Root.AcroForm = pdf.make_indirect(pikepdf.Dictionary(Fields=pikepdf.Array(), SigFlags=3))
        pdf.save(str(a))
    vorher = a.read_bytes()
    main_window.on_pdf_straighten(a)
    assert a.read_bytes() == vorher and not main_window._undo_stack
    assert len(beobachtet["warnung"]) == 1 and "signiert" in beobachtet["warnung"][0]

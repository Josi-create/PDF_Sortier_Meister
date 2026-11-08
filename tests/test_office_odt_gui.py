"""GUI-Tests: .odt wie .docx (Kachel, Typ-Etikett, Verschieben mit Endung, Umwandeln, mehrere).

Fixtures und Hilfen aus tests/test_office_gui.py (tmp-Pfade, nie die echte Config).
"""
from __future__ import annotations

from tests.test_bild_gui import _fragen, _pdf
from tests.test_office_gui import (  # noqa: F401 - Fixtures
    _ja,
    _prime_cache_on_load,
    _prime_text,
    fresh_singletons,
    main_window,
)


def _scan(tmp_path):
    scan = tmp_path / "Scan"
    scan.mkdir()
    (scan / "a.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (scan / "Brief.odt").write_bytes(b"PK")
    (scan / "Notiz.docx").write_bytes(b"PK")
    (scan / ".~lock.Brief.odt#").write_bytes(b"lock")  # LibreOffice-Sperrdatei
    return scan


def _kachel(mw, pfad):
    return next(w for w in mw.office_widgets if w.pdf_path == pfad)


def test_odt_erscheint_als_kachel_mit_etikett_und_word_farbe(main_window, fresh_singletons):  # noqa: F811
    from src.gui.office_thumbnail import WORD_FARBE, _typfarbe

    scan = _scan(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)
    assert sorted(w.pdf_path.name for w in main_window.office_widgets) == ["Brief.odt", "Notiz.docx"]
    k = _kachel(main_window, scan / "Brief.odt")
    assert k.typ_label.text() == "ODT" and k.typ_label.toolTip() == "OpenDocument-Text"
    assert _typfarbe(k.pdf_path) == WORD_FARBE


def test_odt_menue_hat_umwandeln_auch_fuer_mehrere(main_window, fresh_singletons):  # noqa: F811
    scan = _scan(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)
    k = _kachel(main_window, scan / "Brief.odt")
    texte = [a.text() for a in k._build_context_menu().actions() if not a.isSeparator()]
    assert "In PDF umwandeln" in texte and any("PDF/A" in t for t in texte)
    main_window.selected_pdfs = [scan / "Brief.odt", scan / "Notiz.docx"]
    texte = [a.text() for a in k._build_context_menu().actions() if not a.isSeparator()]
    assert "In PDF umwandeln (2 Dateien)" in texte


def test_verschieben_behaelt_odt_endung(main_window, fresh_singletons, monkeypatch):  # noqa: F811
    tmp = fresh_singletons["tmp_path"]
    scan = _scan(tmp)
    ziel = tmp / "Ziel"
    ziel.mkdir()
    main_window._navigate_to_folder(scan)
    odt = scan / "Brief.odt"
    _prime_text(main_window, odt)
    main_window.on_pdf_clicked(odt)
    _ja(monkeypatch)
    main_window.detail_panel.name_input.setText("2026-05-12_Strom_Stadtwerke")
    main_window.on_suggestion_clicked(ziel)
    assert (ziel / "2026-05-12_Strom_Stadtwerke.odt").exists()
    assert not odt.exists() and not list(ziel.glob("*.pdf"))


def test_umwandeln_odt_legt_pdf_daneben_an(qtbot, main_window, fresh_singletons, monkeypatch):  # noqa: F811
    from src.core.office_convert import UmwandlungsErgebnis
    from src.gui import office_convert_worker as worker_mod

    scan = _scan(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)
    aufrufe = []

    def falsch(pfad, pdfa=False):
        aufrufe.append((pfad.name, pdfa))
        ziel = pfad.with_suffix(".pdf")
        _pdf(ziel)
        return UmwandlungsErgebnis(pdf=ziel, werkzeug="Word", pdfa=pdfa)

    monkeypatch.setattr(worker_mod, "umwandeln", falsch)
    fragen = _fragen(monkeypatch, (False, False))  # "Original in den Papierkorb?" -> nein
    _prime_cache_on_load(main_window, monkeypatch)
    main_window.on_office_convert(scan / "Brief.odt", False)
    qtbot.waitUntil(lambda: main_window._office_worker is None, timeout=5000)

    assert aufrufe == [("Brief.odt", False)]
    assert (scan / "Brief.pdf").exists() and (scan / "Brief.odt").exists()
    assert len(fragen) == 1 and "Brief.odt" in fragen[0]  # Frage nach dem Original wie bei .docx

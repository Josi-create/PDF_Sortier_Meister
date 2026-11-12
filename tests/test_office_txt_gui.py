"""GUI-Tests: .txt wie .docx/.odt (Issue #227) - Kachel, Etikett, Menue, Verschieben, Umwandeln.

Fixtures und Hilfen aus tests/test_office_gui.py (tmp-Pfade, nie die echte Config).
"""
from __future__ import annotations

from tests.test_bild_gui import _fragen
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
    (scan / "Notiz.txt").write_bytes("Zählerstand Sonderwort\r\n4711 kWh".encode("cp1252"))
    (scan / "Zweite.TXT").write_text("Noch eine Notiz", encoding="utf-8")
    (scan / "Brief.docx").write_bytes(b"PK")
    (scan / "daten.csv").write_text("a;b", encoding="utf-8")  # nicht unterstuetzt
    return scan


def _kachel(mw, pfad):
    return next(w for w in mw.office_widgets if w.pdf_path == pfad)


def _menue(kachel) -> list[str]:
    return [a.text() for a in kachel._build_context_menu().actions() if not a.isSeparator()]


def test_txt_erscheint_als_kachel_mit_etikett(main_window, fresh_singletons):  # noqa: F811
    from src.gui.office_thumbnail import TEXT_FARBE, _typfarbe

    scan = _scan(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)
    assert sorted(w.pdf_path.name for w in main_window.office_widgets) == ["Brief.docx", "Notiz.txt", "Zweite.TXT"]
    k = _kachel(main_window, scan / "Notiz.txt")
    assert k.typ_label.text() == "TXT" and k.typ_label.toolTip() == "Textdatei"
    assert _typfarbe(k.pdf_path) == TEXT_FARBE
    assert k._BASE_TOOLTIP.startswith("Textdatei.")
    assert _kachel(main_window, scan / "Brief.docx")._BASE_TOOLTIP.startswith("Word-/Excel-Datei.")


def test_txt_menue_umwandeln_ohne_pdfa(main_window, fresh_singletons):  # noqa: F811
    scan = _scan(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)
    k = _kachel(main_window, scan / "Notiz.txt")
    texte = _menue(k)
    assert "In PDF umwandeln" in texte and not any("PDF/A" in t for t in texte)
    # nur Textdateien markiert: weiter ohne PDF/A
    main_window.selected_pdfs = [scan / "Notiz.txt", scan / "Zweite.TXT"]
    texte = _menue(k)
    assert "In PDF umwandeln (2 Dateien)" in texte and not any("PDF/A" in t for t in texte)
    # gemischt mit Word: PDF/A wird angeboten (die Textdatei wird dann ein normales PDF)
    main_window.selected_pdfs = [scan / "Notiz.txt", scan / "Brief.docx"]
    texte = _menue(k)
    assert "In PDF umwandeln (2 Dateien)" in texte and "In PDF/A umwandeln (2 Dateien)" in texte
    # Word allein behaelt PDF/A
    main_window.selected_pdfs = []
    assert any("PDF/A" in t for t in _menue(_kachel(main_window, scan / "Brief.docx")))


def test_kachelbild_zeigt_erste_zeilen(qtbot, tmp_path):
    from src.gui.office_thumbnail import kachelbild

    p = tmp_path / "Notiz.txt"
    p.write_text("Erste Zeile\nZweite Zeile", encoding="utf-8")
    bild = kachelbild(p)
    assert bild is not None and not bild.isNull()


def test_verschieben_behaelt_txt_endung_und_macht_suchbar(main_window, fresh_singletons, monkeypatch):  # noqa: F811
    tmp = fresh_singletons["tmp_path"]
    scan = _scan(tmp)
    ziel = tmp / "Ziel"
    ziel.mkdir()
    main_window._navigate_to_folder(scan)
    txt = scan / "Notiz.txt"
    idx = main_window.db.suchindex
    assert idx.suche("Sonderwort")["gesamt"] == 0  # im Scan-Ordner: nicht in der Suche
    _prime_text(main_window, txt)
    main_window.on_pdf_clicked(txt)
    _ja(monkeypatch)
    main_window.detail_panel.name_input.setText("2026-05-12_Strom_Stadtwerke")
    main_window.on_suggestion_clicked(ziel)
    neu = ziel / "2026-05-12_Strom_Stadtwerke.txt"
    assert neu.exists() and not txt.exists() and not list(ziel.glob("*.pdf"))
    # vom Nutzer verschoben: jetzt in der Dokumentensuche, mit dem Text aus der Datei
    d = idx.dokument_nach_pfad(str(neu))
    assert d is not None and d["format"] == "txt" and d["textstatus"] == "text"
    assert idx.suche("Sonderwort")["gesamt"] == 1


def test_umwandeln_txt_legt_pdf_daneben_an(qtbot, main_window, fresh_singletons, monkeypatch):  # noqa: F811
    """Echte Umwandlung (kein Office noetig), danach die Frage nach dem Original wie bei .docx."""
    import pymupdf

    scan = _scan(fresh_singletons["tmp_path"])
    main_window._navigate_to_folder(scan)
    fragen = _fragen(monkeypatch, (False, False))  # "Original in den Papierkorb?" -> nein
    _prime_cache_on_load(main_window, monkeypatch)
    main_window.on_office_convert(scan / "Notiz.txt", False)
    qtbot.waitUntil(lambda: main_window._office_worker is None, timeout=10000)

    pdf = scan / "Notiz.pdf"
    assert pdf.exists() and (scan / "Notiz.txt").exists()
    with pymupdf.open(str(pdf)) as doc:
        assert "Zählerstand Sonderwort" in doc[0].get_text()
    assert len(fragen) == 1 and "Notiz.txt" in fragen[0]
    assert "Notiz.pdf" in main_window.statusbar.currentMessage()  # das neue PDF ist ausgewaehlt

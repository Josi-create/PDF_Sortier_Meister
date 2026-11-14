"""Issue #252: Bildkacheln im Scan-Ordner drehen (Kontextmenue wie bei PDFs, Mehrfachauswahl, Rueckgaengig).

Fixtures wie in tests/test_office_gui.py (Singletons auf tmp-Pfade, nie die echte Konfiguration).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageOps

from tests.test_office_gui import (  # noqa: F401 - Fixtures
    _prime_cache_on_load,
    fresh_singletons,
    main_window,
)

T = Image.Transpose


def _muster() -> Image.Image:
    bild = Image.new("RGB", (48, 32), "white")
    for x in range(48):
        for y in range(32):
            bild.putpixel((x, y), (x * 5 % 256, y * 7 % 256, (x + 2 * y) % 256))
    return bild


def _angezeigt(pfad: Path) -> Image.Image:
    with Image.open(pfad) as bild:
        return ImageOps.exif_transpose(bild).convert("RGB")


def _gleich(a: Image.Image, b: Image.Image) -> bool:
    return a.size == b.size and a.tobytes() == b.tobytes()


def _texte(menu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _untermenue(menu, titel_anfang: str):
    for a in menu.actions():
        if a.menu() is not None and a.text().startswith(titel_anfang):
            return a.menu()
    raise AssertionError(f"Kein Untermenue {titel_anfang!r}: {_texte(menu)}")


def _widget(win, name):
    return next(w for w in win.pdf_widgets if w.pdf_path.name == name)


@pytest.fixture
def bilder(main_window, fresh_singletons, monkeypatch):  # noqa: F811
    """Scan-Ordner (Umlaute im Pfad) mit JPG, PNG, TIFF und einer PDF; Auffrischen wird mitgeschrieben."""
    from src.gui import main_window as mw_mod
    from src.gui.office_thumbnail import OfficeThumbnailWidget

    scan = fresh_singletons["tmp_path"] / "Scan Fotos Größe"
    scan.mkdir()
    _muster().save(scan / "foto.jpg", "JPEG", quality=85)
    _muster().save(scan / "bild.png", "PNG")
    _muster().save(scan / "seiten.tif", "TIFF")
    (scan / "a.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    log = {"geladen": [], "vergessen": [], "index": [], "warnung": [], "analyse": [], "vorschau": []}
    monkeypatch.setattr(OfficeThumbnailWidget, "load_thumbnail", lambda self: log["geladen"].append(self.pdf_path))
    monkeypatch.setattr(mw_mod, "thumbnail_vergessen", lambda p: log["vergessen"].append(Path(p)))
    monkeypatch.setattr(mw_mod, "index_melden", lambda *a, **k: log["index"].append(a))
    monkeypatch.setattr(mw_mod.QMessageBox, "warning", lambda *a, **k: log["warnung"].append(a[2]))
    monkeypatch.setattr(main_window, "update_suggestions_for_pdf", lambda p: log["analyse"].append(p))
    monkeypatch.setattr(main_window, "_on_office_preview_requested", lambda p: log["vorschau"].append(p))
    _prime_cache_on_load(main_window, monkeypatch)
    main_window._navigate_to_folder(scan)
    log["geladen"].clear()
    return {"win": main_window, "scan": scan, "log": log,
            "jpg": scan / "foto.jpg", "png": scan / "bild.png", "tif": scan / "seiten.tif", "pdf": scan / "a.pdf"}


def test_menue_der_bildkachel_hat_drehen_wie_bei_pdfs(bilder):
    menu = _widget(bilder["win"], "foto.jpg")._build_context_menu()
    assert _texte(_untermenue(menu, "Drehen")) == ["90° nach links", "90° nach rechts", "180°"]
    texte = _texte(menu)
    assert texte.index("Drehen") < texte.index("Löschen")
    assert "Drehen" in _texte(_widget(bilder["win"], "bild.png")._build_context_menu())


def test_nicht_drehbare_formate_und_andere_dateien_ohne_drehen(bilder, fresh_singletons):  # noqa: F811
    assert "Drehen" not in _texte(_widget(bilder["win"], "seiten.tif")._build_context_menu())
    (bilder["scan"] / "Brief.docx").write_bytes(b"PK")
    bilder["win"].load_pdfs()
    assert not any(t.startswith("Drehen") for t in _texte(_widget(bilder["win"], "Brief.docx")._build_context_menu()))


@pytest.mark.parametrize("eintrag,methode", [("90° nach links", T.ROTATE_90), ("90° nach rechts", T.ROTATE_270),
                                             ("180°", T.ROTATE_180)])
def test_menueeintrag_dreht_das_bild_und_frischt_auf(bilder, eintrag, methode):
    win, jpg, log = bilder["win"], bilder["jpg"], bilder["log"]
    vorher = _angezeigt(jpg)
    win.on_pdf_clicked(jpg)
    log["analyse"].clear()
    assert win.pdf_cache.get(jpg) is not None

    sub = _untermenue(_widget(win, "foto.jpg")._build_context_menu(), "Drehen")
    next(a for a in sub.actions() if a.text() == eintrag).trigger()

    assert _gleich(_angezeigt(jpg), vorher.transpose(methode))
    assert log["geladen"] == [jpg]            # Kachelbild neu (im Hintergrund-Thread der Kachel)
    assert jpg not in win.pdf_cache._cache    # Analyse verworfen ...
    assert log["analyse"] == [jpg]            # ... und fuer die ausgewaehlte Datei neu angestossen
    assert log["index"] == [("datei_geaendert", str(jpg))]
    assert log["warnung"] == []
    assert win._undo_stack[-1]["type"] == "rotate" and win._undo_stack[-1]["paths"] == [jpg]
    assert "foto.jpg" in win.statusbar.currentMessage() and "Ctrl+Z" in win.statusbar.currentMessage()


def test_rueckgaengig_dreht_zurueck(bilder):
    win, png, jpg = bilder["win"], bilder["png"], bilder["jpg"]
    png_vorher, jpg_vorher = _angezeigt(png), _angezeigt(jpg)

    _widget(win, "bild.png").rotate_requested.emit(png, 90)
    _widget(win, "foto.jpg").rotate_requested.emit(jpg, -90)
    assert _gleich(_angezeigt(png), png_vorher.transpose(T.ROTATE_270))
    assert len(win._undo_stack) == 2

    win.undo_last_action()
    assert _gleich(_angezeigt(jpg), jpg_vorher)
    win.undo_last_action()
    assert _gleich(_angezeigt(png), png_vorher)
    assert win._undo_stack == []


def test_mehrfachauswahl_dreht_alle_markierten_drehbaren_bilder(bilder):
    win, jpg, png, tif, pdf = (bilder[k] for k in ("win", "jpg", "png", "tif", "pdf"))
    vorher = {p: _angezeigt(p) for p in (jpg, png, tif)}
    pdf_vorher = pdf.read_bytes()
    win.selected_pdfs = [jpg, png, tif, pdf]
    win.selected_pdf = pdf
    for w in win.pdf_widgets:
        w.selected = True

    menu = _widget(win, "foto.jpg")._build_context_menu()
    assert "Drehen (2 Bilder)" in _texte(menu)
    next(a for a in _untermenue(menu, "Drehen").actions() if a.text() == "90° nach rechts").trigger()

    assert _gleich(_angezeigt(jpg), vorher[jpg].transpose(T.ROTATE_270))
    assert _gleich(_angezeigt(png), vorher[png].transpose(T.ROTATE_270))
    assert _gleich(_angezeigt(tif), vorher[tif]) and pdf.read_bytes() == pdf_vorher  # nicht angefasst
    assert bilder["log"]["warnung"] == []
    assert win._undo_stack[-1]["paths"] == [jpg, png]
    assert "2 Bilder" in win.statusbar.currentMessage()
    assert win.selected_pdfs == [jpg, png, tif, pdf]  # die Auswahl bleibt

    win.undo_last_action()
    assert _gleich(_angezeigt(jpg), vorher[jpg]) and _gleich(_angezeigt(png), vorher[png])


def test_kachel_ausserhalb_der_auswahl_dreht_nur_sich(bilder):
    win, jpg, png = bilder["win"], bilder["jpg"], bilder["png"]
    png_vorher = _angezeigt(png)
    win.selected_pdfs = [png, bilder["pdf"]]
    assert "Drehen" in _texte(_widget(win, "foto.jpg")._build_context_menu())

    _widget(win, "foto.jpg").rotate_requested.emit(jpg, 180)

    assert win._undo_stack[-1]["paths"] == [jpg]
    assert _gleich(_angezeigt(png), png_vorher)


def test_eingaben_im_detail_panel_bleiben_nur_die_vorschau_wird_neu(bilder, monkeypatch):
    win, jpg, log = bilder["win"], bilder["jpg"], bilder["log"]
    win.on_pdf_clicked(jpg)
    log["analyse"].clear()
    log["vorschau"].clear()
    monkeypatch.setattr(win.detail_panel, "has_user_edits", lambda: True)
    geladen: list = []
    monkeypatch.setattr(win.detail_panel.preview, "load_pdf", geladen.append)

    _widget(win, "foto.jpg").rotate_requested.emit(jpg, 90)

    assert log["vorschau"] == [jpg] and log["analyse"] == []
    assert geladen == []  # die Bilddatei selbst ist kein PDF fuer die Vorschau


def test_unlesbares_bild_wird_gemeldet_und_nicht_veraendert(bilder):
    win = bilder["win"]
    kaputt = bilder["scan"] / "kaputt.jpg"
    kaputt.write_bytes(b"kein Bild")
    win.load_pdfs()
    bilder["log"]["geladen"].clear()

    _widget(win, "kaputt.jpg").rotate_requested.emit(kaputt, 90)

    assert kaputt.read_bytes() == b"kein Bild"
    assert len(bilder["log"]["warnung"]) == 1 and "kaputt.jpg" in bilder["log"]["warnung"][0]
    assert win._undo_stack == [] and bilder["log"]["geladen"] == []


def test_kachelbild_zeigt_das_gedrehte_jpeg(qtbot, tmp_path):
    """Qt (Kachel) beachtet die eingetragene EXIF-Ausrichtung, auch hinter einem JFIF-Kopf."""
    from src.core.bild_drehen import bild_drehen
    from src.gui.office_thumbnail import bild_kachelbild

    pfad = tmp_path / "foto.jpg"
    _muster().save(pfad, "JPEG", quality=85)
    quer = bild_kachelbild(pfad)
    assert quer.width() > quer.height()

    bild_drehen(pfad, 90)

    hoch = bild_kachelbild(pfad)
    assert (hoch.width(), hoch.height()) == (quer.height(), quer.width())

"""Issue #205: Entzerren fotografierter Dokumente - Menue, Dialog und die Wege im Hauptfenster.

Fixtures wie in ``tests/test_bild_gui.py`` (Singletons auf tmp-Pfade, Papierkorb umgeleitet, kein
Tesseract). Der Dialog laeuft nie modal: ``EntzerrenDialog.exec`` wird ersetzt.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pymupdf
import pytest
from PIL import Image
from PyQt6.QtWidgets import QDialog

from src.gui.entzerren_dialog import EntzerrenDialog
from tests.helfer_entzerren import ecken_abstand, foto, kamera_ecken
from tests.test_bild_gui import (  # noqa: F401 - Fixtures
    _bild,
    _fragen,
    cursor_aufraeumen,
    fresh_config_dialog,
    fresh_singletons,
    main_window,
    scan,
)

ECKEN = kamera_ecken(25, 10, 4, z=450)


def _foto(pfad: Path, ecken=ECKEN, art="dunkel") -> Path:
    foto(ecken, (1200, 900), art=art, verlauf=0.3).save(pfad, quality=95)
    return pfad


def _rauschen(pfad: Path) -> Path:
    rng = np.random.default_rng(5)
    Image.fromarray(rng.integers(0, 255, (600, 800, 3), dtype=np.uint8)).save(pfad)
    return pfad


def _kachel(mw, pfad):
    return next(w for w in mw.office_widgets if w.pdf_path == pfad)


def _menue(widget):
    return widget._build_context_menu()


def _aktion(menu, text: str):
    for a in menu.actions():
        if a.text() == text:
            return a
        if a.menu() is not None:
            for b in a.menu().actions():
                if b.text() == text:
                    return b
    raise AssertionError(f"Menueeintrag fehlt: {text}")


def _seite(pdf: Path, nr: int = 0):
    with pymupdf.open(pdf) as doc:
        return round(doc[nr].rect.width), round(doc[nr].rect.height), doc.page_count


class _Dialog:
    """Ersatz fuer ``EntzerrenDialog.exec``: merkt Aufrufe und fuehrt ein Skript aus."""

    def __init__(self, monkeypatch, annehmen=True, skript=None):
        self.aufrufe: list[dict] = []
        self.annehmen, self.skript = annehmen, skript

        def exec_(dlg):
            self.aufrufe.append({
                "bilder": [e.pfad.name for e in dlg._eintraege],
                "unsicher": sorted(p.name for p in dlg._unsicher),
                "tonwerte": dlg.tonwerte(),
                "ecken": [list(e.ecken) for e in dlg._eintraege if e.klein is not None],
            })
            if self.skript:
                self.skript(dlg)
            return QDialog.DialogCode.Accepted if self.annehmen else QDialog.DialogCode.Rejected

        monkeypatch.setattr(EntzerrenDialog, "exec", exec_)


def _verboten(monkeypatch):
    monkeypatch.setattr(EntzerrenDialog, "exec", lambda self: pytest.fail("Dialog darf nicht aufgehen"))


# --- Menue -----------------------------------------------------------------------------------

def test_menue_eines_bildes_hat_beide_entzerren_eintraege(main_window, scan):  # noqa: F811
    _bild(scan / "a.jpg")
    main_window._navigate_to_folder(scan)
    texte = [a.text() for a in _menue(main_window.office_widgets[0]).actions() if not a.isSeparator()]
    i = texte.index("In PDF umwandeln")
    assert texte[i + 1:i + 3] == ["In PDF umwandeln und automatisch entzerren",
                                  "In PDF umwandeln und von Hand entzerren"]


def test_menue_der_mehrfachauswahl_hat_untermenue(main_window, scan):  # noqa: F811
    a, b, c = (_bild(scan / n) for n in ("a.jpg", "b.jpg", "c.jpg"))
    main_window._navigate_to_folder(scan)
    main_window.selected_pdfs = [a, b, c]
    menu = _menue(_kachel(main_window, b))
    sub = next(x for x in menu.actions() if x.menu() is not None)
    assert sub.text() == "Fotos entzerren (3 Bilder)"
    assert [x.text() for x in sub.menu().actions()] == [
        "Einzeln in PDFs umwandeln und automatisch entzerren",
        "Einzeln in PDFs umwandeln und von Hand entzerren",
        "Zu einem PDF zusammenfügen und automatisch entzerren",
        "Zu einem PDF zusammenfügen und von Hand entzerren",
    ]
    # Einzeln markiert: kein Untermenue, aber die zwei Einzel-Eintraege
    main_window.selected_pdfs = [a]
    assert not any(x.menu() is not None for x in _menue(_kachel(main_window, b)).actions())


def test_office_dateien_haben_keine_entzerren_eintraege(main_window, scan):  # noqa: F811
    (scan / "x.docx").write_bytes(b"x")
    main_window._navigate_to_folder(scan)
    texte = [a.text() for a in _menue(main_window.office_widgets[0]).actions()]
    assert not any("entzerren" in t for t in texte)


# --- automatisch ---------------------------------------------------------------------------

def test_automatisch_ohne_dialog_bei_sicherer_erkennung(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    bild = _foto(scan / "foto.jpg")
    main_window._navigate_to_folder(scan)
    _verboten(monkeypatch)
    gestellt = _fragen(monkeypatch, (True, False))
    _aktion(_menue(_kachel(main_window, bild)), "In PDF umwandeln und automatisch entzerren").trigger()
    qtbot.waitUntil(lambda: main_window._bild_worker is None and main_window._erkennung_worker is None
                    and (scan / "foto.pdf").exists(), timeout=20000)
    assert _seite(scan / "foto.pdf") == (595, 842, 1)  # A4 hoch, entzerrt
    assert len(gestellt) == 1 and not bild.exists()  # die Frage nach dem Original kam, Papierkorb
    assert main_window.selected_pdf == scan / "foto.pdf"


def test_unsicher_oeffnet_den_dialog_mit_bestem_versuch(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    bild = _rauschen(scan / "kein_blatt.jpg")
    main_window._navigate_to_folder(scan)
    dlg = _Dialog(monkeypatch)
    _fragen(monkeypatch, (False, False))
    _aktion(_menue(_kachel(main_window, bild)), "In PDF umwandeln und automatisch entzerren").trigger()
    qtbot.waitUntil(lambda: bool(dlg.aufrufe), timeout=20000)
    qtbot.waitUntil(lambda: main_window._bild_worker is None and (scan / "kein_blatt.pdf").exists(), timeout=20000)
    assert dlg.aufrufe[0]["bilder"] == ["kein_blatt.jpg"] and dlg.aufrufe[0]["unsicher"] == ["kein_blatt.jpg"]
    assert len(dlg.aufrufe[0]["ecken"][0]) == 4  # vorbelegt
    assert bild.exists()  # "Original behalten"


def test_abbrechen_aendert_nichts(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    bild = _foto(scan / "foto.jpg")
    main_window._navigate_to_folder(scan)
    _Dialog(monkeypatch, annehmen=False)
    gestellt = _fragen(monkeypatch, (True, False))
    _aktion(_menue(_kachel(main_window, bild)), "In PDF umwandeln und von Hand entzerren").trigger()
    qtbot.waitUntil(lambda: main_window._erkennung_worker is None, timeout=20000)
    qtbot.wait(300)
    assert main_window._bild_worker is None
    assert bild.exists() and not (scan / "foto.pdf").exists() and not gestellt
    assert [p.name for p in scan.iterdir()] == ["foto.jpg"]


# --- von Hand ------------------------------------------------------------------------------------

def test_von_hand_dialog_ist_vorbelegt_und_verschobene_ecken_gelten(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    bild = _foto(scan / "foto.jpg")
    main_window._navigate_to_folder(scan)
    schief = [(100, 100), (1100, 100), (1100, 400), (100, 400)]  # breit: weit weg von A4

    def verschieben(dlg):
        assert ecken_abstand(dlg.ecken(), ECKEN) < 30  # Vorbelegung = Erkennung
        dlg.ecken_setzen(schief)

    dlg = _Dialog(monkeypatch, skript=verschieben)
    _fragen(monkeypatch, (False, False))
    _aktion(_menue(_kachel(main_window, bild)), "In PDF umwandeln und von Hand entzerren").trigger()
    qtbot.waitUntil(lambda: main_window._bild_worker is None and (scan / "foto.pdf").exists(), timeout=20000)
    b, h, _n = _seite(scan / "foto.pdf")
    assert dlg.aufrufe and b / h == pytest.approx(1000 / 300, rel=0.05)  # die verschobenen Ecken, nicht A4


def test_einstellung_tonwerte_gilt(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    bild = _foto(scan / "foto.jpg")
    main_window._navigate_to_folder(scan)
    main_window.config.set("bild_tonwerte", "sw")
    _verboten(monkeypatch)
    _fragen(monkeypatch, (False, False))
    _aktion(_menue(_kachel(main_window, bild)), "In PDF umwandeln und automatisch entzerren").trigger()
    qtbot.waitUntil(lambda: main_window._bild_worker is None and (scan / "foto.pdf").exists(), timeout=20000)
    with pymupdf.open(scan / "foto.pdf") as doc:
        assert doc.get_page_images(0)[0][4] == 1  # Schwarzweiss


def test_tonwahl_im_dialog_geht_vor(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    bild = _foto(scan / "foto.jpg")
    main_window._navigate_to_folder(scan)
    main_window.config.set("bild_tonwerte", "farbe")
    _Dialog(monkeypatch, skript=lambda d: d.tonwerte_combo.setCurrentIndex(d.tonwerte_combo.findData("grau")))
    _fragen(monkeypatch, (False, False))
    _aktion(_menue(_kachel(main_window, bild)), "In PDF umwandeln und von Hand entzerren").trigger()
    qtbot.waitUntil(lambda: main_window._bild_worker is None and (scan / "foto.pdf").exists(), timeout=20000)
    with pymupdf.open(scan / "foto.pdf") as doc:
        assert doc.extract_image(doc.get_page_images(0)[0][0])["colorspace"] == 1  # ein Kanal: Graustufen


# --- Mehrfachauswahl --------------------------------------------------------------------------------

def test_mehrfach_einzeln_automatisch_nur_unsichere_im_dialog(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    a, b = _foto(scan / "a.jpg"), _foto(scan / "b.jpg", art="muster")
    c = _rauschen(scan / "c.jpg")
    main_window._navigate_to_folder(scan)
    main_window.selected_pdfs = [c, a, b]
    dlg = _Dialog(monkeypatch)
    gestellt = _fragen(monkeypatch, (False, False))
    _aktion(_menue(_kachel(main_window, b)), "Einzeln in PDFs umwandeln und automatisch entzerren").trigger()
    qtbot.waitUntil(lambda: main_window._bild_worker is None
                    and all((scan / f"{n}.pdf").exists() for n in "abc"), timeout=30000)
    assert len(dlg.aufrufe) == 1 and dlg.aufrufe[0]["bilder"] == ["c.jpg"]
    assert _seite(scan / "a.pdf") == (595, 842, 1) and _seite(scan / "b.pdf") == (595, 842, 1)
    assert len(gestellt) == 1 and "3 PDFs" in gestellt[0]  # eine Frage fuer alle


def test_mehrfach_zusammen_von_hand_ein_pdf_mit_allen_seiten(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    a, b = _foto(scan / "a.jpg"), _foto(scan / "b.jpg", art="hell")
    main_window._navigate_to_folder(scan)
    main_window.selected_pdfs = [b, a]
    dlg = _Dialog(monkeypatch)
    _fragen(monkeypatch, (False, False))
    _aktion(_menue(_kachel(main_window, a)), "Zu einem PDF zusammenfügen und von Hand entzerren").trigger()
    qtbot.waitUntil(lambda: main_window._bild_worker is None and (scan / "a.pdf").exists(), timeout=30000)
    assert dlg.aufrufe[0]["bilder"] == ["a.jpg", "b.jpg"]  # Reihenfolge der Ansicht
    assert _seite(scan / "a.pdf") == (595, 842, 2)
    assert not (scan / "b.pdf").exists()


def test_mehrfach_einzeln_von_hand_zeigt_alle_im_dialog(qtbot, main_window, scan, monkeypatch):  # noqa: F811
    a, b = _foto(scan / "a.jpg"), _foto(scan / "b.jpg")
    main_window._navigate_to_folder(scan)
    main_window.selected_pdfs = [a, b]
    dlg = _Dialog(monkeypatch)
    _fragen(monkeypatch, (False, False))
    _aktion(_menue(_kachel(main_window, a)), "Einzeln in PDFs umwandeln und von Hand entzerren").trigger()
    qtbot.waitUntil(lambda: main_window._bild_worker is None
                    and (scan / "a.pdf").exists() and (scan / "b.pdf").exists(), timeout=30000)
    assert dlg.aufrufe[0]["bilder"] == ["a.jpg", "b.jpg"]


# --- Dialog selbst ----------------------------------------------------------------------------------

@pytest.fixture
def zwei_fotos(tmp_path):
    return _foto(tmp_path / "a.jpg"), _foto(tmp_path / "b.jpg", kamera_ecken(10, -10, 0, z=480))


def test_dialog_vorbelegt_ziehen_zuruecksetzen(qtbot, zwei_fotos):
    a, b = zwei_fotos
    vorgabe = [(300.0, 100.0), (900.0, 120.0), (880.0, 800.0), (320.0, 780.0)]
    dlg = EntzerrenDialog([a, b], {a: vorgabe}, "farbe")
    qtbot.addWidget(dlg)
    assert dlg.ecken() == vorgabe
    assert "Bild 1 von 2" in dlg._kopf.text()
    # Eckpunkt ziehen (Szene = verkleinerte Kopie; hier 1200 px < ARBEIT_PX, Faktor 1)
    dlg._punkte[0].setPos(350, 150)
    assert dlg.ecken()[0] == pytest.approx((350.0, 150.0))
    assert dlg._viereck.polygon().at(0).x() == pytest.approx(350.0)
    qtbot.waitUntil(lambda: dlg._vorschau._pixmap is not None, timeout=3000)
    dlg.zuruecksetzen()
    assert dlg.ecken() == vorgabe


def test_dialog_blaettern_je_bild_eigene_ecken_und_uebernehmen_fuer_alle(qtbot, zwei_fotos):
    a, b = zwei_fotos
    dlg = EntzerrenDialog([a, b], {}, "grau")
    qtbot.addWidget(dlg)
    assert dlg.tonwerte() == "grau"
    assert not dlg.zurueck_knopf.isEnabled() and dlg.weiter_knopf.isEnabled()
    erste = [(200.0, 100.0), (1000.0, 120.0), (1050.0, 800.0), (150.0, 780.0)]
    dlg.ecken_setzen(erste)
    dlg.weiter_knopf.click()
    assert "Bild 2 von 2" in dlg._kopf.text() and dlg.zurueck_knopf.isEnabled() and not dlg.weiter_knopf.isEnabled()
    standard = dlg.ecken()
    assert standard[0] == pytest.approx((60.0, 45.0))  # ohne Erkennung: eingerueckt an den Bildecken
    dlg._punkte[2].setPos(1000, 700)
    dlg.zurueck_knopf.click()
    assert dlg.ecken() == pytest.approx(erste)  # das erste Bild behielt seine Ecken
    ergebnis = dlg.ergebnis()
    assert set(ergebnis) == {a, b} and all(e.tonwerte == "grau" for e in ergebnis.values())
    assert ergebnis[b].ecken[2] == pytest.approx((1000.0, 700.0))


def test_dialog_ecken_bleiben_im_bild(qtbot, zwei_fotos):
    dlg = EntzerrenDialog([zwei_fotos[0]], {}, "farbe")
    qtbot.addWidget(dlg)
    dlg._punkte[1].setPos(5000, -300)
    x, y = dlg.ecken()[1]
    assert x == pytest.approx(1200.0) and y == pytest.approx(0.0)


def test_dialog_grosses_foto_ecken_im_vollen_pixelmass(qtbot, tmp_path):
    gross = tmp_path / "gross.jpg"
    foto([(x * 3, y * 3) for x, y in ECKEN], (3600, 2700), art="dunkel").save(gross, quality=90)
    vorgabe = [(x * 3, y * 3) for x, y in ECKEN]
    dlg = EntzerrenDialog([gross], {gross: vorgabe}, "farbe")
    qtbot.addWidget(dlg)
    e = dlg._eintrag()
    assert e.faktor == pytest.approx(3600 / 1600)
    assert dlg._punkte[0].pos().x() == pytest.approx(vorgabe[0][0] / e.faktor)  # Anzeige verkleinert
    assert dlg.ecken()[0] == pytest.approx(vorgabe[0], abs=1e-6)  # Ergebnis im vollen Mass


def test_dialog_ist_gross_und_nicht_lesbares_bild_blockiert_nicht(qtbot, tmp_path):
    kaputt = tmp_path / "kaputt.jpg"
    kaputt.write_bytes(b"kein Bild")
    dlg = EntzerrenDialog([kaputt], {}, "farbe")
    qtbot.addWidget(dlg)
    assert "nicht gelesen" in dlg._status.text() and dlg.ergebnis() == {}
    schirm = dlg.screen().availableGeometry()
    assert dlg.width() >= int(schirm.width() * 0.8)


def test_dialog_knoepfe_nehmen_an_oder_brechen_ab(qtbot, zwei_fotos):
    dlg = EntzerrenDialog(list(zwei_fotos), {}, "farbe")
    qtbot.addWidget(dlg)
    dlg.abbrechen_knopf.click()
    assert dlg.result() == QDialog.DialogCode.Rejected
    dlg.uebernehmen_knopf.click()
    assert dlg.result() == QDialog.DialogCode.Accepted


# --- Einstellungen ------------------------------------------------------------------------------------

def test_einstellung_tonwerte_laden_und_speichern(qtbot, fresh_config_dialog):  # noqa: F811
    d = fresh_config_dialog
    assert d.bild_tonwerte_combo.currentData() == "farbe"  # Standard
    d.config.set("bild_tonwerte", "grau")
    d._load_settings()
    assert d.bild_tonwerte_combo.currentData() == "grau"
    d.bild_tonwerte_combo.setCurrentIndex(d.bild_tonwerte_combo.findData("sw"))
    d._save_settings()
    assert d.config.get("bild_tonwerte") == "sw"

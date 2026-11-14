"""GUI-Tests zu Issue #245: Hinweis auf doppelte Dateien (gleicher Inhalt).

Fixtures aus tests/test_auto_next_after_move_gui.py (tmp-Pfade, nie die echte Konfiguration;
Rueckfragen bejaht, Fehlerdialoge sind Testfehler). Der Hinweis ist in Tests abgeschaltet
(tests/conftest.py) und wird hier wieder eingeschaltet. Der Papierkorb ist ein Ordner unter
tmp_path - in den echten Papierkorb wandert nichts.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton

from src.core import duplikate
from src.core.pdf_cache import PDFAnalysisResult
from src.gui import doppelte, stapel_rueckfrage
from tests.test_auto_next_after_move_gui import (  # noqa: F401 - Fixtures
    fresh_singletons,
    main_window,
)

FOTO = b"\xff\xd8 ein Foto aus dem Messenger " * 40 + b"\xff\xd9"
ANDERES = b"\xff\xd8 ein anderes Foto, gleich gross" * 40 + b"\xff\xd9"
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


@pytest.fixture
def fenster(main_window, fresh_singletons, monkeypatch):  # noqa: F811
    """Hauptfenster mit eingeschaltetem Hinweis; Klicks starten keine Analyse; Papierkorb unter tmp_path."""
    monkeypatch.setattr(doppelte, "AUTOMATISCH", True)
    monkeypatch.setattr(duplikate, "_summen", duplikate.Pruefsummen())
    tmp = fresh_singletons["tmp_path"]
    main_window.tmp = tmp
    main_window.papierkorb = tmp / "Papierkorb"
    main_window.papierkorb.mkdir()

    def in_den_papierkorb(pfad, endgueltig=False):
        ziel = main_window.papierkorb / Path(pfad).name
        shutil.move(str(pfad), str(ziel))
        return ziel

    monkeypatch.setattr(main_window.file_manager, "delete_file", in_den_papierkorb)
    monkeypatch.setattr(main_window.pdf_cache, "pre_cache", lambda pfade: (0, 0))
    original = main_window.load_pdfs

    def laden():
        original()
        for w in main_window.pdf_widgets:
            main_window.pdf_cache._cache[w.pdf_path] = PDFAnalysisResult(
                pdf_path=w.pdf_path, file_modified=w.pdf_path.stat().st_mtime)

    monkeypatch.setattr(main_window, "load_pdfs", laden)
    main_window.rueckfragen = []
    yield main_window
    while QApplication.overrideCursor() is not None:
        QApplication.restoreOverrideCursor()


def _scan(fenster, dateien: dict[str, bytes], name="Scan") -> Path:
    scan = fenster.tmp / name
    scan.mkdir()
    for datei, inhalt in dateien.items():
        (scan / datei).write_bytes(inhalt)
    fenster._navigate_to_folder(scan)
    return scan


def _geprueft(fenster, qtbot):
    """Wartet die Pruefung im Hintergrund ab (auch eine, die erst angestossen ist)."""
    d = fenster._doppelte_im_ordner
    if d._start.isActive():
        d._start.stop()
        d.pruefen()
    qtbot.waitUntil(lambda: d._lauf is None and not d._start.isActive(), timeout=5000)


def _hinweis(fenster, pfad: Path) -> str:
    return fenster._pdf_widget_for(pfad)._kopie_text


def _antwort(fenster, monkeypatch, wahl: str):
    """Die Rueckfrage „Datei schon vorhanden“ beantworten und mitschreiben."""
    def frage(dateien, doppelt):
        fenster.rueckfragen.append((list(dateien), {p: list(o) for p, o in doppelt.items()}))
        return wahl

    monkeypatch.setattr(fenster, "_doppelte_rueckfrage", frage)


# --------------------------------------------------------------------------- im Scan-Bereich

def test_zweimal_gespeichertes_foto_wird_auf_beiden_kacheln_gekennzeichnet(fenster, qtbot):
    scan = _scan(fenster, {"IMG-WA0001.jpg": FOTO, "IMG-WA0001 (1).jpg": FOTO, "IMG-WA0002.jpg": ANDERES,
                           "Rechnung Müller.pdf": PDF})
    _geprueft(fenster, qtbot)

    assert _hinweis(fenster, scan / "IMG-WA0001.jpg") == "Doppelt: wie IMG-WA0001 (1).jpg"
    assert _hinweis(fenster, scan / "IMG-WA0001 (1).jpg") == "Doppelt: wie IMG-WA0001.jpg"
    assert _hinweis(fenster, scan / "IMG-WA0002.jpg") == ""
    assert _hinweis(fenster, scan / "Rechnung Müller.pdf") == ""
    assert fenster._pdf_widget_for(scan / "IMG-WA0001.jpg").kopie_label.toolTip() == (
        "Gleicher Inhalt wie:\nIMG-WA0001 (1).jpg")
    meldung = fenster.statusbar.currentMessage()
    assert meldung.startswith("Gleicher Inhalt: ") and "IMG-WA0001 (1).jpg" in meldung


def test_f5_meldet_dieselben_doppelten_nicht_noch_einmal(fenster, qtbot):
    scan = _scan(fenster, {"a.jpg": FOTO, "b.jpg": FOTO})
    _geprueft(fenster, qtbot)
    fenster.statusbar.clearMessage()

    fenster.load_pdfs()
    _geprueft(fenster, qtbot)

    assert _hinweis(fenster, scan / "a.jpg") == "Doppelt: wie b.jpg"  # die neuen Kacheln tragen ihn wieder
    assert "Gleicher Inhalt" not in fenster.statusbar.currentMessage()


def test_hinweis_verschwindet_wenn_die_zwillingsdatei_weg_ist(fenster, qtbot):
    scan = _scan(fenster, {"a.jpg": FOTO, "b.jpg": FOTO, "c.jpg": ANDERES})
    _geprueft(fenster, qtbot)
    assert _hinweis(fenster, scan / "b.jpg")

    (scan / "a.jpg").unlink()
    fenster.remove_pdf_widget(scan / "a.jpg")
    _geprueft(fenster, qtbot)

    assert _hinweis(fenster, scan / "b.jpg") == ""


def test_umbenannte_zwillingsdatei_steht_mit_neuem_namen_im_hinweis(fenster, qtbot):
    scan = _scan(fenster, {"a.jpg": FOTO, "b.jpg": FOTO})
    _geprueft(fenster, qtbot)

    (scan / "a.jpg").rename(scan / "Urlaub.jpg")
    fenster._update_pdf_widget_path(scan / "a.jpg", scan / "Urlaub.jpg")
    _geprueft(fenster, qtbot)

    assert _hinweis(fenster, scan / "b.jpg") == "Doppelt: wie Urlaub.jpg"
    assert _hinweis(fenster, scan / "Urlaub.jpg") == "Doppelt: wie b.jpg"


def test_neu_erschienene_datei_wird_geprueft(fenster, qtbot):
    """Anbindung an die Ordner-Beobachtung (Issue #232): Die neue Datei ist der Anlass."""
    scan = _scan(fenster, {"IMG-WA0001.jpg": FOTO, "anderes.jpg": ANDERES})
    _geprueft(fenster, qtbot)
    assert _hinweis(fenster, scan / "IMG-WA0001.jpg") == ""
    b = fenster._ordner_beobachtung
    b.RUHEZEIT = 0.0

    (scan / "IMG-WA0001 (1).jpg").write_bytes(FOTO)
    for _ in range(2):
        lauf = b.lauf_sichern()
        b._uebernehmen(lauf, b.lesen(lauf), 0.0)
    assert fenster._pdf_widget_for(scan / "IMG-WA0001 (1).jpg") is not None
    assert fenster._doppelte_im_ordner._start.isActive()  # angestossen, nicht sofort gerechnet
    _geprueft(fenster, qtbot)

    assert _hinweis(fenster, scan / "IMG-WA0001 (1).jpg") == "Doppelt: wie IMG-WA0001.jpg"
    assert _hinweis(fenster, scan / "IMG-WA0001.jpg") == "Doppelt: wie IMG-WA0001 (1).jpg"
    assert "Gleicher Inhalt" in fenster.statusbar.currentMessage()


def test_ordner_ohne_doppelte_bleibt_ohne_hinweis_und_ohne_pruefsummen(fenster, qtbot):
    scan = _scan(fenster, {f"Scan_{i:03d}.pdf": PDF + b"x" * i for i in range(30)})
    _geprueft(fenster, qtbot)

    assert all(w._kopie_text == "" for w in fenster.pdf_widgets)
    assert duplikate.summen().gerechnet == 0  # keine zwei Dateien gleicher Groesse: nichts gelesen
    assert "Gleicher Inhalt" not in fenster.statusbar.currentMessage()
    assert len(fenster.pdf_widgets) == 30 and scan.exists()


def test_abgeschaltet_passiert_nichts(fenster, qtbot, monkeypatch):
    monkeypatch.setattr(doppelte, "AUTOMATISCH", False)
    scan = _scan(fenster, {"a.jpg": FOTO, "b.jpg": FOTO})
    assert not fenster._doppelte_im_ordner._start.isActive()
    assert fenster._doppelte_vor_ablage([scan / "a.jpg"], scan) == [scan / "a.jpg"]


# --------------------------------------------------------------------------- beim Ablegen

def _ziel(fenster, dateien: dict[str, bytes]) -> Path:
    ziel = fenster.tmp / "Ablage" / "Belege für 2026"
    ziel.mkdir(parents=True)
    for datei, inhalt in dateien.items():
        (ziel / datei).write_bytes(inhalt)
    return ziel


def test_ohne_gleiche_datei_im_ziel_keine_rueckfrage(fenster, monkeypatch):
    scan = _scan(fenster, {"a.pdf": PDF})
    ziel = _ziel(fenster, {"anders.pdf": PDF + b"anderer Inhalt", "gleich gross.pdf": PDF[::-1]})
    _antwort(fenster, monkeypatch, "abbrechen")
    fenster.on_pdf_clicked(scan / "a.pdf")

    fenster._move_rename_and_learn(scan / "a.pdf", ziel)

    assert fenster.rueckfragen == []
    assert not (scan / "a.pdf").exists() and len(list(ziel.iterdir())) == 3  # abgelegt


def test_abbrechen_laesst_die_datei_liegen(fenster, monkeypatch):
    scan = _scan(fenster, {"Beleg.pdf": PDF})
    ziel = _ziel(fenster, {"Beleg vom Januar.pdf": PDF})
    _antwort(fenster, monkeypatch, "abbrechen")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("es wurde weiter gefragt"))
    fenster.on_pdf_clicked(scan / "Beleg.pdf")

    fenster._move_rename_and_learn(scan / "Beleg.pdf", ziel)

    assert fenster.rueckfragen == [([scan / "Beleg.pdf"], {scan / "Beleg.pdf": [ziel / "Beleg vom Januar.pdf"]})]
    assert (scan / "Beleg.pdf").exists()
    assert sorted(p.name for p in ziel.iterdir()) == ["Beleg vom Januar.pdf"]
    assert fenster._pdf_widget_for(scan / "Beleg.pdf") is not None


def test_in_den_papierkorb_statt_ein_zweites_mal_ablegen(fenster, monkeypatch):
    scan = _scan(fenster, {"Beleg.pdf": PDF, "weiter.pdf": PDF + b"anders"})
    ziel = _ziel(fenster, {"Beleg vom Januar.pdf": PDF})
    _antwort(fenster, monkeypatch, "papierkorb")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("es wurde weiter gefragt"))
    fenster.on_pdf_clicked(scan / "Beleg.pdf")

    fenster.move_pdf_to_folder_and_learn(scan / "Beleg.pdf", ziel)

    assert not (scan / "Beleg.pdf").exists() and (fenster.papierkorb / "Beleg.pdf").exists()
    assert sorted(p.name for p in ziel.iterdir()) == ["Beleg vom Januar.pdf"]  # die vorhandene bleibt
    assert fenster._pdf_widget_for(scan / "Beleg.pdf") is None
    assert fenster.selected_pdf == scan / "weiter.pdf"  # wie nach dem Ablegen: die naechste Datei
    eintrag = fenster._undo_stack[-1]
    assert eintrag["type"] == "delete" and eintrag["original"] == scan / "Beleg.pdf"
    assert eintrag["papierkorb"] == fenster.papierkorb / "Beleg.pdf"
    assert "Papierkorb" in fenster.statusbar.currentMessage()


def test_trotzdem_ablegen_geht_den_gewohnten_weg(fenster, monkeypatch):
    scan = _scan(fenster, {"Beleg.pdf": PDF})
    ziel = _ziel(fenster, {"Beleg.pdf": PDF})
    _antwort(fenster, monkeypatch, "ablegen")
    fenster.on_pdf_clicked(scan / "Beleg.pdf")

    fenster._move_rename_and_learn(scan / "Beleg.pdf", ziel)

    assert len(fenster.rueckfragen) == 1
    assert not (scan / "Beleg.pdf").exists()
    assert len(list(ziel.iterdir())) == 2  # neben der vorhandenen, unter eigenem Namen


def test_treffer_aus_dem_suchindex_auch_in_einem_anderen_ordner(fenster, monkeypatch):
    scan = _scan(fenster, {"Beleg.pdf": PDF})
    ziel = _ziel(fenster, {})
    archiv = fenster.tmp / "Ablage" / "2025" / "Steuer"
    archiv.mkdir(parents=True)
    (archiv / "Beleg alt.pdf").write_bytes(PDF)
    gefragt = []

    def gleiche_groesse(groesse):
        gefragt.append(groesse)
        return [{"pfad": str(archiv / "Beleg alt.pdf"), "pruefsumme": duplikate.pruefsumme(scan / "Beleg.pdf"),
                 "pruefsumme_stand": duplikate.stand_text(len(PDF), (archiv / "Beleg alt.pdf").stat().st_mtime_ns)}]

    monkeypatch.setattr(fenster.db.suchindex, "gleiche_groesse", gleiche_groesse)
    _antwort(fenster, monkeypatch, "abbrechen")

    fenster.move_pdf_to_folder_and_learn(scan / "Beleg.pdf", ziel)

    assert gefragt == [len(PDF)]
    assert fenster.rueckfragen[0][1] == {scan / "Beleg.pdf": [archiv / "Beleg alt.pdf"]}
    assert (scan / "Beleg.pdf").exists()


def test_stapel_nur_die_vorhandenen_gehen_in_den_papierkorb(fenster, monkeypatch):
    scan = _scan(fenster, {"a.pdf": PDF + b"a", "b.pdf": PDF + b"bb", "c.pdf": PDF + b"ccc"})
    ziel = _ziel(fenster, {"schon da.pdf": PDF + b"bb"})
    _antwort(fenster, monkeypatch, "papierkorb")
    monkeypatch.setattr(stapel_rueckfrage, "frage", lambda *a, **k: stapel_rueckfrage.NUR_VERSCHIEBEN)
    dateien = [scan / "a.pdf", scan / "b.pdf", scan / "c.pdf"]
    fenster.selected_pdfs = list(dateien)

    fenster.move_multiple_pdfs_to_folder(dateien, ziel)

    assert fenster.rueckfragen == [(dateien, {scan / "b.pdf": [ziel / "schon da.pdf"]})]
    assert sorted(p.name for p in ziel.iterdir()) == ["a.pdf", "c.pdf", "schon da.pdf"]
    assert (fenster.papierkorb / "b.pdf").exists()
    assert fenster.pdf_widgets == []


def test_stapel_abbrechen_verschiebt_nichts(fenster, monkeypatch):
    scan = _scan(fenster, {"a.pdf": PDF + b"a", "b.pdf": PDF + b"bb"})
    ziel = _ziel(fenster, {"schon da.pdf": PDF + b"bb"})
    _antwort(fenster, monkeypatch, "abbrechen")
    monkeypatch.setattr(stapel_rueckfrage, "frage", lambda *a, **k: pytest.fail("es wurde weiter gefragt"))

    fenster.move_multiple_pdfs_to_folder([scan / "a.pdf", scan / "b.pdf"], ziel)

    assert sorted(p.name for p in scan.iterdir()) == ["a.pdf", "b.pdf"]
    assert len(fenster.pdf_widgets) == 2


def test_zwei_gleiche_dateien_im_selben_stapel_sind_kein_schon_vorhanden(fenster, monkeypatch):
    """Sonst nennte jede die andere als „liegt schon dort“, und beide gingen in den Papierkorb."""
    scan = _scan(fenster, {"a.jpg": FOTO, "a (1).jpg": FOTO})
    ziel = _ziel(fenster, {})
    monkeypatch.setattr(
        fenster.db.suchindex, "gleiche_groesse",
        lambda g: [{"pfad": str(scan / n), "pruefsumme": None, "pruefsumme_stand": None} for n in ("a.jpg", "a (1).jpg")])
    _antwort(fenster, monkeypatch, "papierkorb")
    monkeypatch.setattr(stapel_rueckfrage, "frage", lambda *a, **k: stapel_rueckfrage.NUR_VERSCHIEBEN)

    fenster.move_multiple_pdfs_to_folder([scan / "a.jpg", scan / "a (1).jpg"], ziel)

    assert fenster.rueckfragen == []
    assert sorted(p.name for p in ziel.iterdir()) == ["a (1).jpg", "a.jpg"]
    assert list(fenster.papierkorb.iterdir()) == []


def test_zwillingsdatei_im_selben_ordner_ist_kein_schon_abgelegt(fenster, monkeypatch):
    """Der Scan-Ordner steht auch im Suchindex. Die zweite Kopie dort kennzeichnet schon der
    Scan-Bereich; beim Ablegen der ersten wird nicht nachgefragt."""
    scan = _scan(fenster, {"Beleg.pdf": PDF, "Beleg (1).pdf": PDF})
    ziel = _ziel(fenster, {})
    monkeypatch.setattr(
        fenster.db.suchindex, "gleiche_groesse",
        lambda g: [{"pfad": str(scan / "Beleg (1).pdf"), "pruefsumme": None, "pruefsumme_stand": None}])
    _antwort(fenster, monkeypatch, "papierkorb")

    fenster.move_pdf_to_folder_and_learn(scan / "Beleg.pdf", ziel)

    assert fenster.rueckfragen == []
    assert (ziel / "Beleg.pdf").exists() and (scan / "Beleg (1).pdf").exists()


def test_vorhandene_datei_inzwischen_weg_dann_kein_papierkorb(fenster, monkeypatch):
    scan = _scan(fenster, {"Beleg.pdf": PDF})
    ziel = _ziel(fenster, {"Beleg.pdf": PDF})

    def frage(dateien, doppelt):
        (ziel / "Beleg.pdf").unlink()  # waehrend die Rueckfrage offen ist
        return "papierkorb"

    monkeypatch.setattr(fenster, "_doppelte_rueckfrage", frage)
    warnungen = []
    monkeypatch.setattr(doppelte.QMessageBox, "warning", lambda *a, **k: warnungen.append(a[2]))

    fenster.move_pdf_to_folder_and_learn(scan / "Beleg.pdf", ziel)

    assert (scan / "Beleg.pdf").exists() and list(fenster.papierkorb.iterdir()) == []
    assert "nicht mehr da" in warnungen[0]


def test_papierkorb_nicht_verfuegbar_laesst_die_datei_im_ordner(fenster, monkeypatch):
    from src.core.file_manager import PapierkorbNichtVerfuegbar

    scan = _scan(fenster, {"Beleg.pdf": PDF})
    ziel = _ziel(fenster, {"Beleg.pdf": PDF})
    _antwort(fenster, monkeypatch, "papierkorb")

    def kein_papierkorb(pfad, endgueltig=False):
        raise PapierkorbNichtVerfuegbar("Netzlaufwerk")

    monkeypatch.setattr(fenster.file_manager, "delete_file", kein_papierkorb)
    warnungen = []
    monkeypatch.setattr(doppelte.QMessageBox, "warning", lambda *a, **k: warnungen.append(a[2]))

    fenster.move_pdf_to_folder_and_learn(scan / "Beleg.pdf", ziel)

    assert (scan / "Beleg.pdf").exists() and len(list(ziel.iterdir())) == 1  # weder geloescht noch abgelegt
    assert "Papierkorb nicht verfügbar" in warnungen[0]
    assert fenster._pdf_widget_for(scan / "Beleg.pdf") is not None


@pytest.mark.parametrize("knopf, erwartet", [
    ("Trotzdem ablegen", "ablegen"), ("In den Papierkorb", "papierkorb"), ("Abbrechen", "abbrechen")])
def test_rueckfrage_nennt_den_ort_und_hat_drei_knoepfe(fenster, knopf, erwartet):
    quelle = fenster.tmp / "Scan" / "Beleg.pdf"
    ort = fenster.tmp / "Ablage" / "2025" / "Beleg alt.pdf"
    gesehen = {}

    def klicken():
        box = QApplication.activeModalWidget()
        assert isinstance(box, QMessageBox)
        gesehen["text"] = box.text()
        gesehen["knoepfe"] = [b.text() for b in box.findChildren(QPushButton)]
        gesehen["standard"] = box.defaultButton().text()
        next(b for b in box.findChildren(QPushButton) if b.text() == knopf).click()

    QTimer.singleShot(50, klicken)
    assert fenster._doppelte_rueckfrage([quelle], {quelle: [ort]}) == erwartet
    assert "Beleg.pdf" in gesehen["text"] and str(ort) in gesehen["text"]
    assert sorted(gesehen["knoepfe"]) == ["Abbrechen", "In den Papierkorb", "Trotzdem ablegen"]
    assert gesehen["standard"] == "Abbrechen"


def test_langsamer_vergleich_blockiert_nicht_und_laesst_sich_ueberspringen(fenster, monkeypatch, qtbot):
    """Dauert der Vergleich (grosse Datei, Netzlaufwerk), erscheint eine Fortschrittsanzeige;
    „Nicht mehr warten“ legt ohne Hinweis ab."""
    import threading

    from PyQt6.QtWidgets import QProgressDialog

    scan = _scan(fenster, {"Beleg.pdf": PDF})
    ziel = _ziel(fenster, {"Beleg.pdf": PDF})
    frei = threading.Event()
    monkeypatch.setattr(duplikate, "gleiche_anderswo", lambda *a, **k: (frei.wait(10), [ziel / "Beleg.pdf"])[1])
    _antwort(fenster, monkeypatch, "abbrechen")

    def nicht_warten():
        dialog = fenster.findChildren(QProgressDialog)[-1]
        assert "schon gibt" in dialog.labelText()
        dialog.cancel()

    QTimer.singleShot(400, nicht_warten)
    try:
        assert fenster._doppelte_vor_ablage([scan / "Beleg.pdf"], ziel) == [scan / "Beleg.pdf"]
        assert fenster.rueckfragen == []
    finally:
        frei.set()

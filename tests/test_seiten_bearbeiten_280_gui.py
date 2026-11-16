"""Issue #280 (GUI): Fenster "Seiten bearbeiten", Speichern ueber das Hauptfenster, Strg+Z."""
from __future__ import annotations

from pathlib import Path

import pikepdf
import pymupdf
import pytest
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QDialogButtonBox

from src.gui import seiten_bearbeiten as sb
from src.gui.pdf_thumbnail import PDFThumbnailWidget
from tests.test_stack_pdfs_gui import fresh_singletons, main_window, no_background_threads  # noqa: F401 - Fixtures


def _pdf(pfad: Path, seiten: int, leer: tuple[int, ...] = ()) -> Path:
    doc = pymupdf.open()
    try:
        for i in range(1, seiten + 1):
            seite = doc.new_page()
            if i not in leer:
                for zeile in range(12):
                    seite.insert_text((72, 100 + zeile * 24), f"Blatt {i} Zeile {zeile} Lorem ipsum dolor", fontsize=14)
        doc.save(str(pfad))
    finally:
        doc.close()
    return pfad


def _blaetter(pfad: Path) -> list[tuple[str, int]]:
    """Je Seite: erstes Wortpaar ("Blatt 3", leer bei leerer Seite) und Drehung."""
    with pymupdf.open(str(pfad)) as doc:
        return [(" ".join(seite.get_text().split()[:2]), seite.rotation) for seite in doc]


@pytest.fixture
def dialog(qtbot, tmp_path, fresh_config):
    pfad = _pdf(tmp_path / "Mäppchen.pdf", 5, leer=(2, 4))
    d = sb.SeitenBearbeitenDialog(pfad)
    qtbot.addWidget(d)
    d.alle_laden()
    yield d
    d.done(0)


def _waehlen(d, *seiten: int) -> None:
    d.liste.clearSelection()
    for seite in seiten:
        d._item(seite).setSelected(True)


def _speichern(d):
    return d.knoepfe.button(QDialogButtonBox.StandardButton.Save)


def test_fenster_zeigt_alle_seiten_und_speichert_erst_nach_aenderung(dialog):
    assert dialog.liste.count() == 5
    assert dialog.plan() == [(1, 0), (2, 0), (3, 0), (4, 0), (5, 0)]
    assert not dialog.geaendert()
    assert not _speichern(dialog).isEnabled()
    assert not dialog.btn_loeschen.isEnabled()  # nichts ausgewaehlt
    assert not dialog.liste.item(0).icon().isNull()


def test_loeschen_vormerken_und_wieder_aufheben(dialog):
    _waehlen(dialog, 2, 4)
    dialog.loeschen_umschalten()

    assert dialog.plan() == [(1, 0), (3, 0), (5, 0)]
    assert "wird gelöscht" in dialog._item(2).text()
    assert "2" in dialog.stand.text()
    assert _speichern(dialog).isEnabled()
    assert dialog.btn_loeschen.text() == "Doch behalten"

    dialog.loeschen_umschalten()  # dieselbe Auswahl: Vormerkung aufheben

    assert dialog.plan() == [(1, 0), (2, 0), (3, 0), (4, 0), (5, 0)]
    assert not _speichern(dialog).isEnabled()


def test_alle_seiten_loeschen_geht_nicht(dialog):
    dialog.liste.selectAll()
    dialog.loeschen_umschalten()

    assert dialog.plan() == []
    assert not _speichern(dialog).isEnabled()
    assert "mindestens eine Seite" in dialog.stand.text()


def test_drehen_einzelner_seiten(dialog):
    _waehlen(dialog, 3)
    dialog.drehen(90)
    dialog.drehen(90)
    _waehlen(dialog, 1)
    dialog.drehen(-90)

    assert dialog.plan() == [(1, 270), (2, 0), (3, 180), (4, 0), (5, 0)]
    assert _speichern(dialog).isEnabled()

    dialog.drehen(90)  # Seite 1 zurueck
    _waehlen(dialog, 3)
    dialog.drehen(180)
    assert not dialog.geaendert()


def test_gedrehte_miniatur_liegt_quer(dialog):
    item = dialog._item(1)
    hoch = dialog.gezeigt(item).size()
    _waehlen(dialog, 1)
    dialog.drehen(90)
    quer = dialog.gezeigt(item).size()

    assert hoch.height() > hoch.width()
    assert quer.width() > quer.height()


def test_schieben_mit_den_knoepfen(dialog):
    _waehlen(dialog, 4, 5)
    dialog.schieben(-1)
    assert [nr for nr, _ in dialog.plan()] == [1, 2, 4, 5, 3]
    assert dialog.liste.zeilen() == [2, 3]  # die geschobenen Seiten bleiben ausgewaehlt

    dialog.schieben(1)
    assert [nr for nr, _ in dialog.plan()] == [1, 2, 3, 4, 5]
    dialog.schieben(1)  # schon ganz hinten: nichts passiert
    assert [nr for nr, _ in dialog.plan()] == [1, 2, 3, 4, 5]

    _waehlen(dialog, 1)
    dialog.schieben(-1)  # schon ganz vorn
    assert [nr for nr, _ in dialog.plan()] == [1, 2, 3, 4, 5]


def test_ablegen_sortiert_um(dialog, qtbot):
    dialog.show()
    qtbot.waitExposed(dialog)
    liste = dialog.liste

    # Seite 5 auf die linke Haelfte von Seite 2 ziehen: sie kommt davor
    rechteck = liste.visualItemRect(dialog._item(2))
    links = QPoint(rechteck.left() + 5, rechteck.center().y())
    assert liste.zielzeile(links) == 1
    liste.verschieben([4], liste.zielzeile(links))
    assert [nr for nr, _ in dialog.plan()] == [1, 5, 2, 3, 4]

    # Seiten 1 und 5 (jetzt Zeilen 0 und 1) hinter die letzte Seite
    rechteck = liste.visualItemRect(dialog._item(4))
    rechts = QPoint(rechteck.right() - 5, rechteck.center().y())
    assert liste.zielzeile(rechts) == 5
    liste.verschieben([0, 1], liste.zielzeile(rechts))
    assert [nr for nr, _ in dialog.plan()] == [2, 3, 4, 1, 5]
    assert dialog.geaendert()

    # Dasselbe ueber das Ablege-Ereignis der Liste: Seite 2 (Zeile 0) hinter die letzte Seite
    class Ablegen(QDropEvent):
        quelle = liste

        def source(self):
            return self.quelle

    def ereignis(punkt):
        return Ablegen(QPointF(punkt), Qt.DropAction.MoveAction, QMimeData(),
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

    _waehlen(dialog, 2)
    rechteck = liste.visualItemRect(dialog._item(5))
    ablage = ereignis(QPoint(rechteck.right() - 5, rechteck.center().y()))
    liste.dropEvent(ablage)
    assert ablage.isAccepted()
    assert [nr for nr, _ in dialog.plan()] == [3, 4, 1, 5, 2]
    assert liste.count() == 5  # nichts verschwindet aus der Liste

    # Von woanders hineingezogen (anderes Fenster, Explorer): abgelehnt, nichts aendert sich
    Ablegen.quelle = None
    fremd = ereignis(QPoint(rechteck.left() + 5, rechteck.center().y()))
    liste.dropEvent(fremd)
    assert not fremd.isAccepted()
    assert [nr for nr, _ in dialog.plan()] == [3, 4, 1, 5, 2]

    # Ablegen an derselben Stelle aendert nichts
    assert liste.verschieben([0], 0) is False
    assert liste.verschieben([0], 1) is False


def test_leere_seiten_markieren_merkt_nur_vor(dialog):
    vorher = dialog.pdf_path.read_bytes()

    assert dialog.leere_markieren() == [2, 4]

    assert dialog.plan() == [(1, 0), (3, 0), (5, 0)]
    assert [i.data(sb.ROLLE_SEITE) for i in dialog.liste.selectedItems()] == [2, 4]
    assert "2 leere Seite(n)" in dialog.stand.text()
    assert dialog.pdf_path.read_bytes() == vorher  # die Datei aendert erst "Speichern"

    dialog.loeschen_umschalten()  # der Anwender nimmt beide wieder heraus
    assert not dialog.geaendert()


def test_kontextmenue_hat_seiten_bearbeiten(qtbot, tmp_path, fresh_config):
    pfad = _pdf(tmp_path / "a.pdf", 2)
    kachel = PDFThumbnailWidget(pfad)
    qtbot.addWidget(kachel)
    menu = kachel._build_context_menu()
    aktion = next(a for a in menu.actions() if a.text() == "Seiten bearbeiten…")

    with qtbot.waitSignal(kachel.seiten_requested, timeout=1000) as signal:
        aktion.trigger()
    assert signal.args == [pfad]


# --- ueber das Hauptfenster: speichern und Strg+Z ---

@pytest.fixture
def scan(main_window, fresh_singletons, monkeypatch):  # noqa: F811
    ordner = fresh_singletons["tmp_path"] / "Scan"
    ordner.mkdir()
    monkeypatch.setattr(sb, "sicherungs_ordner", lambda: fresh_singletons["tmp_path"] / "seiten_sicherung")
    return ordner


def test_speichern_schreibt_die_pdf_und_strg_z_holt_sie_zurueck(main_window, scan, monkeypatch):  # noqa: F811
    pfad = _pdf(scan / "Mäppchen.pdf", 5, leer=(2, 4))
    main_window._navigate_to_folder(scan)
    vorher = pfad.read_bytes()
    gemeldet = []
    monkeypatch.setattr(main_window, "_pdf_inhalt_geaendert", gemeldet.append)
    monkeypatch.setattr(sb, "_dialog", lambda main, p: [(5, 90), (1, 0), (3, 0)])

    main_window.on_pdf_seiten(pfad)

    assert _blaetter(pfad) == [("Blatt 5", 90), ("Blatt 1", 0), ("Blatt 3", 0)]
    assert gemeldet == [pfad]  # Kachel, Analyse, Vorschau und Suchindex werden aufgefrischt
    eintrag = main_window._undo_stack[-1]
    assert eintrag["type"] == "seiten"
    assert "2 Seite(n) gelöscht" in main_window.undo_action.text()
    assert Path(eintrag["sicherung"]).read_bytes() == vorher

    main_window.undo_last_action()

    assert pfad.read_bytes() == vorher
    assert gemeldet == [pfad, pfad]
    assert main_window._undo_stack == []


def test_abbruch_und_unveraenderter_plan_lassen_alles_wie_es_ist(main_window, scan, monkeypatch):  # noqa: F811
    pfad = _pdf(scan / "a.pdf", 3)
    main_window._navigate_to_folder(scan)
    vorher = pfad.read_bytes()

    for ergebnis in (None, [(1, 0), (2, 0), (3, 0)]):
        monkeypatch.setattr(sb, "_dialog", lambda main, p, e=ergebnis: e)
        main_window.on_pdf_seiten(pfad)

    assert pfad.read_bytes() == vorher
    assert main_window._undo_stack == []
    assert not (scan.parent / "seiten_sicherung").exists()


def test_signierte_pdf_oeffnet_das_fenster_nicht(main_window, scan, monkeypatch):  # noqa: F811
    pfad = _pdf(scan / "a.pdf", 2)
    with pikepdf.open(str(pfad), allow_overwriting_input=True) as pdf:
        pdf.Root.AcroForm = pdf.make_indirect(pikepdf.Dictionary(Fields=pikepdf.Array(), SigFlags=3))
        pdf.save(str(pfad))
    main_window._navigate_to_folder(scan)
    vorher = pfad.read_bytes()
    hinweise = []
    monkeypatch.setattr(sb.QMessageBox, "information", lambda parent, titel, text: hinweise.append(text))
    monkeypatch.setattr(sb, "_dialog", lambda main, p: pytest.fail("Fenster darf nicht aufgehen"))

    main_window.on_pdf_seiten(pfad)

    assert len(hinweise) == 1 and "signiert" in hinweise[0]
    assert pfad.read_bytes() == vorher
    assert main_window._undo_stack == []


def test_strg_z_nach_verschwundener_pdf_meldet_es_nur(main_window, scan, monkeypatch):  # noqa: F811
    pfad = _pdf(scan / "a.pdf", 3)
    main_window._navigate_to_folder(scan)
    monkeypatch.setattr(main_window, "_pdf_inhalt_geaendert", lambda p: None)
    monkeypatch.setattr(sb, "_dialog", lambda main, p: [(1, 0)])
    main_window.on_pdf_seiten(pfad)
    pfad.unlink()

    main_window.undo_last_action()

    assert main_window._undo_stack == []
    assert "nicht mehr am alten Ort" in main_window.statusbar.currentMessage()


def test_alte_sicherungen_werden_entfernt(tmp_path):
    import os
    import time

    wurzel = tmp_path / "seiten_sicherung"
    alt, neu = wurzel / "alt", wurzel / "neu"
    for ordner in (alt, neu):
        ordner.mkdir(parents=True)
        (ordner / "a.pdf").write_bytes(b"x")
    vor_40_tagen = time.time() - 40 * 86400
    os.utime(alt, (vor_40_tagen, vor_40_tagen))

    sb._alte_sicherungen_entfernen(wurzel)

    assert not alt.exists()
    assert neu.exists()

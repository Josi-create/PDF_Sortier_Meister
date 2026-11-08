"""Issue #179: Rechtsklick auf einen Ordner -> "Hierhin kopieren" und Strg+Ziehen.

Fixtures wie in ``tests/test_auto_next_after_move_gui.py``: Singletons auf
tmp-Pfade (nie die echte Nutzer-Config), keine Hintergrund-Leser, Rueckfragen
werden bejaht, Fehlerdialoge sind Testfehler.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import QDropEvent

from src.gui.favoriten_leiste import FavoritenLeiste
from src.gui.folder_tile import FolderTileWidget
from src.gui.folder_tree_widget import FolderTreeWidget
from src.gui.folder_widget import FolderWidget
from src.utils.config import Config
from tests.test_auto_next_after_move_gui import (  # noqa: F401 - Fixtures
    _make_scan_folder,
    _prime_cache,
    fresh_singletons,
    main_window,
)

KOPIEREN = "📄 PDF hierhin kopieren"
STRG = (
    Qt.KeyboardModifier.AltModifier if sys.platform == "darwin"
    else Qt.KeyboardModifier.ControlModifier
)


def _echte_pdf(pfad: Path, text: str = "Rechnung Stadtwerke Strom") -> Path:
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    doc.save(str(pfad))
    doc.close()
    return pfad


def _hash(pfad: Path) -> str:
    return hashlib.sha256(pfad.read_bytes()).hexdigest()


def _eintrag(menu, teil="hierhin kopieren"):
    for a in menu.actions():
        if teil in a.text():
            return a
    raise AssertionError(f"Eintrag mit '{teil}' fehlt: {[a.text() for a in menu.actions()]}")


def _ohne_eintrag(menu):
    assert not any("hierhin kopieren" in a.text() for a in menu.actions())


@pytest.fixture
def aufbau(main_window, fresh_singletons):  # noqa: F811
    """Scan-Ordner mit zwei echten PDFs, Zielordner, erste PDF ausgewaehlt."""
    tmp: Path = fresh_singletons["tmp_path"]
    scan = tmp / "Scan"
    scan.mkdir()
    a = _echte_pdf(scan / "a.pdf", "Rechnung Stadtwerke Strom")
    b = _echte_pdf(scan / "b.pdf", "Mahnung Telefon")
    ziel = tmp / "Ziel"
    ziel.mkdir()
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [w.pdf_path for w in main_window.pdf_widgets])
    main_window.on_pdf_clicked(a)
    main_window.selected_pdf_text = "Rechnung Stadtwerke Strom"
    main_window.selected_pdf_keywords = ["rechnung", "strom"]
    main_window.detail_panel.name_input.setText("")  # kein Namensvorschlag -> Originalname
    return {"win": main_window, "scan": scan, "a": a, "b": b, "ziel": ziel}


# --- Menueeintrag an allen vier Stellen -------------------------------------


def test_menue_folder_widget_kachel_und_vorschlag(qtbot, tmp_path):
    for vorschlag in (False, True):
        w = FolderWidget(tmp_path, 0)
        qtbot.addWidget(w)
        w.is_suggestion = vorschlag
        w.auswahl_pruefer = lambda: []
        eintrag = _eintrag(w._build_context_menu())
        assert not eintrag.isEnabled()  # keine Datei ausgewaehlt
        w.auswahl_pruefer = lambda: [tmp_path / "a.pdf"]
        gesendet = []
        w.copy_here_requested.connect(gesendet.append)
        eintrag = _eintrag(w._build_context_menu())
        assert eintrag.text() == KOPIEREN and eintrag.isEnabled()
        eintrag.trigger()
        assert gesendet == [tmp_path]


def test_menue_texte_je_auswahl(qtbot, tmp_path):
    w = FolderWidget(tmp_path, 0)
    qtbot.addWidget(w)
    w.auswahl_pruefer = lambda: [tmp_path / "a.pdf", tmp_path / "b.pdf", tmp_path / "c.pdf"]
    assert _eintrag(w._build_context_menu()).text() == "📄 3 Dateien hierhin kopieren"
    w.auswahl_pruefer = lambda: [tmp_path / "Brief.docx"]
    assert _eintrag(w._build_context_menu()).text() == "📄 Datei hierhin kopieren"
    w.auswahl_pruefer = None  # ohne Hauptfenster: Eintrag da, aber inaktiv
    assert not _eintrag(w._build_context_menu()).isEnabled()


def test_menue_ordnerzeile_nur_bei_echtem_ordner(qtbot, tmp_path):
    zeile = FolderTileWidget(tmp_path)
    qtbot.addWidget(zeile)
    zeile.auswahl_pruefer = lambda: [tmp_path / "a.pdf"]
    gesendet = []
    zeile.copy_here_requested.connect(gesendet.append)
    _eintrag(zeile._build_context_menu()).trigger()
    assert gesendet == [tmp_path]
    eltern = FolderTileWidget(tmp_path, is_parent=True)
    qtbot.addWidget(eltern)
    eltern.auswahl_pruefer = lambda: [tmp_path / "a.pdf"]
    _ohne_eintrag(eltern._build_context_menu())


def test_menue_baum(qtbot, tmp_path):
    root = tmp_path / "Ziel"
    root.mkdir()
    baum = FolderTreeWidget()
    qtbot.addWidget(baum)
    baum.async_scan = False
    baum.set_root_folders([root])
    baum.auswahl_pruefer = lambda: []
    assert not _eintrag(baum._build_context_menu(root)).isEnabled()
    baum.auswahl_pruefer = lambda: [tmp_path / "a.pdf"]
    gesendet = []
    baum.copy_here_requested.connect(gesendet.append)
    _eintrag(baum._build_context_menu(root)).trigger()
    assert gesendet == [root]


def test_menue_favorit(qtbot, tmp_path):
    ordner = tmp_path / "Fav"
    ordner.mkdir()
    leiste = FavoritenLeiste(Config(config_path=tmp_path / "config.json"))
    qtbot.addWidget(leiste)
    leiste.hinzufuegen(ordner)
    leiste.auswahl_pruefer = lambda: [tmp_path / "a.pdf"]
    gesendet = []
    leiste.copy_here_requested.connect(gesendet.append)
    _eintrag(leiste._knopf_menue(ordner)).trigger()
    assert gesendet == [ordner]


def test_hauptfenster_verdrahtet_alle_stellen(aufbau):
    win, ziel = aufbau["win"], aufbau["ziel"]
    # Die Auswahl der PDF-Ansicht erreicht jede Stelle ...
    for stelle in (win.folder_tree, win.favoriten_leiste):
        assert stelle.auswahl_pruefer() == [aufbau["a"]]
    # ... und der Eintrag im Baum loest das Kopieren aus
    win.detail_panel.name_input.setText("")  # kein neuer Name -> Originalname
    _eintrag(win.folder_tree._build_context_menu(ziel)).trigger()
    assert (ziel / "a.pdf").exists() and aufbau["a"].exists()


# --- Kopie: Name, Metadaten, Original unveraendert --------------------------


def test_kopie_mit_vorgeschlagenem_namen_und_metadaten_original_unveraendert(aufbau):
    from src.core.pdf_metadata import read_metadata

    win, a, ziel = aufbau["win"], aufbau["a"], aufbau["ziel"]
    vorher_hash, vorher_mtime = _hash(a), a.stat().st_mtime_ns
    win.detail_panel._metadata_inputs["korrespondent"].setText("Stadtwerke Musterstadt")
    win.detail_panel.name_input.setText("2026-05-12_Rechnung_Stadtwerke")  # nach den Feldern: sie bauen den Namen neu

    win.on_copy_here_requested(ziel)

    kopie = ziel / "2026-05-12_Rechnung_Stadtwerke.pdf"
    assert kopie.exists()
    win._wait_for_metadata_writes([kopie])
    assert read_metadata(kopie).korrespondent == "Stadtwerke Musterstadt"
    # Original: gleicher Name, gleicher Inhalt, keine Metadaten, bleibt ausgewaehlt
    assert a.exists() and _hash(a) == vorher_hash and a.stat().st_mtime_ns == vorher_mtime
    assert not read_metadata(a).korrespondent
    assert win.selected_pdf == a
    assert a in [w.pdf_path for w in win.pdf_widgets]
    assert "Kopiert nach" in win.statusbar.currentMessage()


def test_kachel_zeigt_hinweis_kopiert_nach(aufbau):
    win, a, ziel = aufbau["win"], aufbau["a"], aufbau["ziel"]
    win.on_copy_here_requested(ziel)
    kachel = next(w for w in win.pdf_widgets if w.pdf_path == a)
    assert not kachel.kopie_label.isHidden()
    assert kachel._kopie_text == "📄 kopiert nach Ziel" and kachel.kopie_label.text().startswith("📄")
    assert str(ziel) in kachel.kopie_label.toolTip()
    # Der Hinweis ueberlebt ein Neuaufbauen der Kacheln (nur Sitzung, nur Speicher)
    win.load_pdfs()
    neu = next(w for w in win.pdf_widgets if w.pdf_path == a)
    assert neu._kopie_text == "📄 kopiert nach Ziel" and not neu.kopie_label.isHidden()
    andere = next(w for w in win.pdf_widgets if w.pdf_path == aufbau["b"])
    assert andere.kopie_label.isHidden()


def test_kopie_aufnahme_in_pdfs_tabelle_ohne_verknuepfung(aufbau):
    win, a, ziel = aufbau["win"], aufbau["a"], aufbau["ziel"]
    win.on_copy_here_requested(ziel)
    id_original = win.db.get_or_create_pdf_id(str(a), a.name)
    id_kopie = win.db.get_or_create_pdf_id(str(ziel / "a.pdf"), "a.pdf")
    assert id_original != id_kopie


def test_namenskonflikt_wird_nummeriert(aufbau):
    win, ziel = aufbau["win"], aufbau["ziel"]
    (ziel / "a.pdf").write_bytes(b"%PDF-1.4\nvorhanden")
    win.on_copy_here_requested(ziel)
    win.on_copy_here_requested(ziel)
    assert (ziel / "a.pdf").read_bytes() == b"%PDF-1.4\nvorhanden"  # nie ueberschrieben
    assert (ziel / "a (1).pdf").exists() and (ziel / "a (2).pdf").exists()
    assert aufbau["a"].exists()


def test_mehrfachauswahl_kopiert_alle(aufbau):
    win, a, b, ziel = aufbau["win"], aufbau["a"], aufbau["b"], aufbau["ziel"]
    win.on_pdf_ctrl_clicked(b)
    assert set(win.kopier_auswahl()) == {a, b}
    hashes = {a: _hash(a), b: _hash(b)}

    win.on_copy_here_requested(ziel)

    assert (ziel / "a.pdf").exists() and (ziel / "b.pdf").exists()
    assert {p: _hash(p) for p in (a, b)} == hashes  # Originale bleiben
    assert "Kopiert nach" in win.statusbar.currentMessage()
    assert "2 Dateien" in win.statusbar.currentMessage()


def test_office_datei_behaelt_endung_und_wird_kopiert(aufbau):
    win, scan, ziel = aufbau["win"], aufbau["scan"], aufbau["ziel"]
    docx = scan / "Brief.docx"
    docx.write_bytes(b"PK")
    win.load_pdfs()
    _prime_cache(win, [docx])
    win.on_pdf_clicked(docx)
    win.detail_panel.name_input.setText("2026-05-12_Strom_Stadtwerke")

    win.on_copy_here_requested(ziel)

    assert (ziel / "2026-05-12_Strom_Stadtwerke.docx").exists()
    assert docx.exists() and docx.read_bytes() == b"PK"
    assert not list(ziel.glob("*.pdf"))


# --- Lernen --------------------------------------------------------------


def _rename_eintraege(win) -> list[str]:
    from src.utils.database import RenameHistory

    session = win.db.get_session()
    try:
        return [e.new_filename for e in session.query(RenameHistory).all()]
    finally:
        session.close()


def test_kopieren_lernt_wie_verschieben(aufbau):
    win, ziel = aufbau["win"], aufbau["ziel"]
    vorher = win.classifier.get_training_count()
    win.detail_panel.name_input.setText("2026-05-12_Rechnung_Stadtwerke")

    win.on_copy_here_requested(ziel)

    assert win.classifier.get_training_count() == vorher + 1
    assert _rename_eintraege(win) == ["2026-05-12_Rechnung_Stadtwerke.pdf"]
    assert win.training_label.text() == f"Gelernt: {vorher + 1}"


def test_kopieren_dann_verschieben_zaehlt_nicht_doppelt(aufbau):
    win, a, ziel = aufbau["win"], aufbau["a"], aufbau["ziel"]
    win.detail_panel.name_input.setText("2026-05-12_Rechnung_Stadtwerke")
    vorher = win.classifier.get_training_count()

    win.on_copy_here_requested(ziel)
    nach_kopie = win.classifier.get_training_count()
    assert nach_kopie == vorher + 1

    # Verschieben desselben Dokuments in denselben Ordner: gleicher Lernvorgang, kein zweiter Eintrag
    win.on_tree_folder_selected(ziel)
    assert not a.exists()
    assert win.classifier.get_training_count() == nach_kopie
    assert _rename_eintraege(win) == ["2026-05-12_Rechnung_Stadtwerke.pdf"]


def test_verschieben_in_anderen_ordner_lernt_nach_kopie_weiter(aufbau, fresh_singletons):
    win, ziel = aufbau["win"], aufbau["ziel"]
    anderer = fresh_singletons["tmp_path"] / "Anderer"
    anderer.mkdir()
    vorher = win.classifier.get_training_count()

    win.on_copy_here_requested(ziel)
    win.on_tree_folder_selected(anderer)

    # Kopie (Ziel) und Verschieben (Anderer) sind zwei verschiedene Beispiele
    assert win.classifier.get_training_count() == vorher + 2


def test_verschieben_ohne_kopie_lernt_unveraendert(aufbau):
    win, ziel = aufbau["win"], aufbau["ziel"]
    vorher = win.classifier.get_training_count()
    win.on_tree_folder_selected(ziel)
    assert win.classifier.get_training_count() == vorher + 1


# --- Fehlerfall -----------------------------------------------------------


def test_fehler_beim_kopieren_laesst_original_intakt(aufbau, monkeypatch):
    import shutil

    from src.gui import hierhin_kopieren as hk

    win, a, ziel = aufbau["win"], aufbau["a"], aufbau["ziel"]
    vorher_hash, vorher_mtime = _hash(a), a.stat().st_mtime_ns
    vorher = win.classifier.get_training_count()

    def kaputt(quelle, ziel_pfad, *args, **kwargs):
        Path(ziel_pfad).write_bytes(b"halb")  # halbfertige Kopie, dann Abbruch mitten im Vorgang
        raise OSError("Platte voll")

    monkeypatch.setattr(shutil, "copy2", kaputt)
    warnungen = []
    monkeypatch.setattr(hk.QMessageBox, "warning", lambda *args, **k: warnungen.append(args[2]))

    win.on_copy_here_requested(ziel)

    assert a.exists() and _hash(a) == vorher_hash and a.stat().st_mtime_ns == vorher_mtime
    assert list(ziel.iterdir()) == []  # keine halbe Kopie
    assert win.classifier.get_training_count() == vorher  # nichts gelernt
    assert len(warnungen) == 1 and "Platte voll" in warnungen[0]
    assert win.selected_pdf == a
    kachel = next(w for w in win.pdf_widgets if w.pdf_path == a)
    assert kachel.kopie_label.isHidden()


def test_copy_file_entfernt_halbe_kopie_und_beruehrt_quelle_nicht(tmp_path, monkeypatch):
    import shutil

    from src.core.file_manager import FileManager

    quelle = tmp_path / "q.pdf"
    quelle.write_bytes(b"%PDF-1.4\ninhalt")
    ziel = tmp_path / "Ziel"
    ziel.mkdir()

    def kaputt(q, z, *args, **kwargs):
        Path(z).write_bytes(b"halb")
        raise OSError("weg")

    monkeypatch.setattr(shutil, "copy2", kaputt)
    with pytest.raises(OSError):
        FileManager(tmp_path).copy_file(quelle, ziel)
    assert quelle.read_bytes() == b"%PDF-1.4\ninhalt"
    assert list(ziel.iterdir()) == []


# --- Strg beim Ziehen -----------------------------------------------------


def _drop(widget, pfade, modifiers, aktionen=Qt.DropAction.MoveAction | Qt.DropAction.CopyAction):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in pfade])
    ereignis = QDropEvent(
        QPointF(5, 5), aktionen, mime, Qt.MouseButton.LeftButton, modifiers
    )
    widget.dropEvent(ereignis)
    return ereignis


def _kachel_und_zeile(win, qtbot, ziel):
    kachel = FolderWidget(ziel, 0)
    zeile = FolderTileWidget(ziel)
    for w in (kachel, zeile):
        qtbot.addWidget(w)
        w.pdf_dropped.connect(win.on_pdf_dropped_on_folder)
        win.verbinde_hierhin_kopieren(w)
    return kachel, zeile


@pytest.mark.parametrize("art", ["kachel", "zeile"])
def test_strg_drop_kopiert_normaler_drop_verschiebt(aufbau, qtbot, art):
    win, a, b, ziel = aufbau["win"], aufbau["a"], aufbau["b"], aufbau["ziel"]
    kachel, zeile = _kachel_und_zeile(win, qtbot, ziel)
    widget = kachel if art == "kachel" else zeile

    ereignis = _drop(widget, [a], STRG)
    assert ereignis.dropAction() == Qt.DropAction.CopyAction
    assert (ziel / "a.pdf").exists() and a.exists()

    ereignis = _drop(widget, [b], Qt.KeyboardModifier.NoModifier, aktionen=Qt.DropAction.MoveAction)
    assert ereignis.dropAction() == Qt.DropAction.MoveAction
    assert (ziel / "b.pdf").exists() and not b.exists()


def test_strg_drop_mehrerer_dateien_kopiert_jede_einmal(aufbau, qtbot):
    win, a, b, ziel = aufbau["win"], aufbau["a"], aufbau["b"], aufbau["ziel"]
    win.on_pdf_ctrl_clicked(b)
    kachel, _ = _kachel_und_zeile(win, qtbot, ziel)
    _drop(kachel, [a, b], STRG)
    assert sorted(p.name for p in ziel.iterdir()) == ["a.pdf", "b.pdf"]  # keine "(1)"-Dubletten
    assert a.exists() and b.exists()


def test_strg_drop_im_baum(aufbau, qtbot):
    win, a, ziel = aufbau["win"], aufbau["a"], aufbau["ziel"]
    baum = win.folder_tree
    baum.async_scan = False
    baum.set_root_folders([ziel])
    baum.show()
    item = baum.tree.topLevelItem(0)
    pos = QPointF(baum.tree.visualItemRect(item).center())

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(a))])
    aktionen = Qt.DropAction.MoveAction | Qt.DropAction.CopyAction
    ereignis = QDropEvent(pos, aktionen, mime, Qt.MouseButton.LeftButton, STRG)
    baum._tree_drop(ereignis)

    assert ereignis.dropAction() == Qt.DropAction.CopyAction
    assert (ziel / "a.pdf").exists() and a.exists()


def test_cursor_zeigt_kopieraktion_bei_strg(qtbot, tmp_path):
    from PyQt6.QtGui import QDragMoveEvent

    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(pdf))])
    aktionen = Qt.DropAction.MoveAction | Qt.DropAction.CopyAction
    for widget in (FolderWidget(tmp_path, 0), FolderTileWidget(tmp_path)):
        qtbot.addWidget(widget)
        mit = QDragMoveEvent(QPointF(5, 5).toPoint(), aktionen, mime, Qt.MouseButton.LeftButton, STRG)
        widget.dragMoveEvent(mit)
        assert mit.isAccepted() and mit.dropAction() == Qt.DropAction.CopyAction
        ohne = QDragMoveEvent(
            QPointF(5, 5).toPoint(), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        widget.dragMoveEvent(ohne)
        assert ohne.isAccepted() and ohne.dropAction() == Qt.DropAction.MoveAction


# --- Issue #183: Ordnerzeilen links -> verschieben, im Baum zeigen, Zielordner ----


def _zeile(aufbau, name="Unter"):
    """Echte Unterordner-Zeile des Scan-Ordners (vom Hauptfenster verdrahtet)."""
    unter = aufbau["scan"] / name
    unter.mkdir()
    aufbau["win"].load_pdfs()
    zeile = next(t for t in aufbau["win"].findChildren(FolderTileWidget)
                 if not t.is_parent and t.folder_path == unter)
    return zeile, unter


def test_zeilenmenue_hat_die_neuen_eintraege(qtbot, tmp_path):
    zeile = FolderTileWidget(tmp_path)
    qtbot.addWidget(zeile)
    zeile.auswahl_pruefer = lambda: []
    menu = zeile._build_context_menu()
    assert not _eintrag(menu, "hierhin verschieben").isEnabled()
    assert _eintrag(menu, "Rechts im Baum zeigen").isEnabled()
    assert _eintrag(menu, "Als Zielordner merken").isEnabled()
    zeile.auswahl_pruefer = lambda: [tmp_path / "a.pdf", tmp_path / "b.pdf"]
    assert _eintrag(zeile._build_context_menu(), "hierhin verschieben").text() == "➡ 2 Dateien hierhin verschieben"
    zeile.auswahl_pruefer = lambda: [tmp_path / "a.pdf"]
    assert _eintrag(zeile._build_context_menu(), "hierhin verschieben").text() == "➡ PDF hierhin verschieben"
    zeile.ziel_pruefer = lambda p: True
    menu = zeile._build_context_menu()
    assert any(a.text() == "Aus Zielliste entfernen" for a in menu.actions())
    assert not any("Als Zielordner merken" in a.text() for a in menu.actions())
    eltern = FolderTileWidget(tmp_path, is_parent=True)
    qtbot.addWidget(eltern)
    eltern.auswahl_pruefer = lambda: [tmp_path / "a.pdf"]
    texte = [a.text() for a in eltern._build_context_menu().actions()]
    assert not any("verschieben" in t or "Baum" in t or "Zielordner" in t for t in texte)


def test_verschieben_per_menue_wie_vorschlag_klick(aufbau):
    win, a = aufbau["win"], aufbau["a"]
    zeile, unter = _zeile(aufbau)
    vorher = win.classifier.get_training_count()
    win.detail_panel.name_input.setText("2026-05-12_Rechnung_Stadtwerke")

    _eintrag(zeile._build_context_menu(), "hierhin verschieben").trigger()

    assert (unter / "2026-05-12_Rechnung_Stadtwerke.pdf").exists() and not a.exists()  # umbenannt
    assert win.classifier.get_training_count() == vorher + 1  # gelernt


def test_baum_zeigen_markiert_ordner(aufbau):
    win, ziel = aufbau["win"], aufbau["ziel"]
    tief = ziel / "Bank" / "2026"
    tief.mkdir(parents=True)
    win.config.add_target_folder(ziel)
    win.folder_manager.add_folder(ziel)
    win.load_folders()
    zeile = FolderTileWidget(tief)
    win.verbinde_ordnerzeile(zeile)
    zeile.deleteLater()

    zeile.show_in_tree_requested.emit(tief)

    assert win.folder_tree.get_selected_folder() == tief
    assert win.folder_tree._items[tief].isSelected() or win.folder_tree.tree.currentItem() is win.folder_tree._items[tief]
    assert aufbau["a"].exists()  # nichts verschoben


def test_baum_zeigen_ausserhalb_der_wurzeln_meldet_hinweis(aufbau, tmp_path_factory):
    win = aufbau["win"]
    draussen = tmp_path_factory.mktemp("draussen")
    zeile = FolderTileWidget(draussen)
    win.verbinde_ordnerzeile(zeile)
    zeile.show_in_tree_requested.emit(draussen)
    assert "außerhalb" in win.statusbar.currentMessage() or "nicht im sichtbaren Baum" in win.statusbar.currentMessage()


def test_als_zielordner_merken_und_wieder_entfernen(aufbau):
    win, config = aufbau["win"], aufbau["win"].config
    zeile, unter = _zeile(aufbau)
    assert unter not in config.get_target_folders()
    assert any("Als Zielordner merken" in a.text() for a in zeile._build_context_menu().actions())

    zeile.target_toggle_requested.emit(unter)

    assert unter in config.get_target_folders()  # Config liegt im tmp-Ordner der Fixture
    assert win.folder_tree.has_folder(unter)
    menu = zeile._build_context_menu()
    assert any(a.text() == "Aus Zielliste entfernen" for a in menu.actions())

    zeile.target_toggle_requested.emit(unter)
    assert unter not in config.get_target_folders()

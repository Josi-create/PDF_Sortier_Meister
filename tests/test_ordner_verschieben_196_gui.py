"""Issue #196: ganzen Ordner verschieben/kopieren - Bedienung im Hauptfenster.

Fixtures wie in ``tests/test_office_gui.py`` (Singletons auf tmp-Pfade, nie die echte
Config, kein echter Papierkorb). Rueckfragen werden bejaht und mitgeschrieben,
Warnungen mitgeschrieben.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QMimeData, QPointF, Qt
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QMessageBox

from src.core.pdf_cache import PDFAnalysisResult
from src.gui.hierhin_kopieren import ORDNER_MIME
from tests.test_office_gui import (  # noqa: F401 - Fixtures
    _prime_cache_on_load,
    fresh_singletons,
    main_window,
)

STRG = (
    Qt.KeyboardModifier.AltModifier if sys.platform == "darwin"
    else Qt.KeyboardModifier.ControlModifier
)


def _datei(pfad: Path, inhalt: bytes = b"%PDF-1.4\n%%EOF\n") -> Path:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(inhalt)
    return pfad


@pytest.fixture
def dialoge(monkeypatch):
    """Rueckfragen bejahen, Fragen und Warnungen merken."""
    erg = SimpleNamespace(fragen=[], warnungen=[], infos=[])

    def frage(parent, titel, text, *a, **k):
        erg.fragen.append((titel, text))
        return QMessageBox.StandardButton.Yes

    def warnung(parent, titel, text, *a, **k):
        erg.warnungen.append((titel, text))
        return QMessageBox.StandardButton.Ok

    def info(parent, titel, text, *a, **k):
        erg.infos.append((titel, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "question", staticmethod(frage))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(warnung))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(info))
    return erg


@pytest.fixture
def szene(main_window, fresh_singletons, monkeypatch, dialoge):
    """Scan-Ordner "Scan 2025" mit Ordner "Versicherungen"; Zielordner "Ablage" mit Jahresordnern."""
    tmp = fresh_singletons["tmp_path"]
    scan = tmp / "Scan 2025"
    vers = scan / "Versicherungen"
    _datei(vers / "a.pdf")
    _datei(vers / "Kfz" / "b.pdf")
    _datei(vers / "Brief.docx", b"PK")
    _datei(scan / "lose.pdf")
    ablage = tmp / "Ablage"
    (ablage / "Steuer 2024" / "Versicherungen").mkdir(parents=True)
    (ablage / "Steuer 2025").mkdir()
    (ablage / "Privat").mkdir()

    cfg = fresh_singletons["config"]
    cfg.add_target_folder(ablage)
    main_window.folder_manager.add_folder(ablage)
    main_window.folder_tree.async_scan = False
    main_window.load_folders()
    _prime_cache_on_load(main_window, monkeypatch)
    main_window._navigate_to_folder(scan)
    main_window.folder_tree.tree.expandAll()
    return SimpleNamespace(win=main_window, tmp=tmp, scan=scan, vers=vers, ablage=ablage, cfg=cfg,
                           ziel=ablage / "Steuer 2025", dialoge=dialoge)


def _kachel(win, name: str):
    return next(t for t in win.folder_tiles if t.full_name == name)


def _markieren(qtbot, szene, name="Versicherungen"):
    kachel = _kachel(szene.win, name)
    qtbot.mouseClick(kachel, Qt.MouseButton.LeftButton)
    return kachel


def _vorschlaege_da(qtbot, win):
    qtbot.waitUntil(lambda: bool(win.suggestion_widgets), timeout=5000)


def _fertig(qtbot, win, bedingung=lambda: True):
    qtbot.waitUntil(lambda: not win._ordner_laeuft and bedingung(), timeout=8000)


# --- Markieren -----------------------------------------------------------------------

def test_einfachklick_markiert_den_ordner_und_zeigt_vorschlaege(qtbot, szene):
    win = szene.win
    kachel = _markieren(qtbot, szene)

    assert win._markierter_ordner == szene.vers and kachel.markiert
    assert "Versicherungen" in win.suggestions_label.text()
    assert not win.ordner_ki_btn.isHidden()
    _vorschlaege_da(qtbot, win)
    ziele = [w.folder_path for w in win.suggestion_widgets]
    assert ziele[0] == szene.ziel  # "Steuer 2024/Versicherungen" -> "Steuer 2025" (Jahr aus dem Pfad)
    assert szene.scan not in ziele  # der aktuelle Elternordner nie
    assert szene.ziel in win.folder_tree._suggestion_folders  # im Baum hervorgehoben


def test_nochmal_klicken_hebt_die_markierung_auf(qtbot, szene):
    win = szene.win
    kachel = _markieren(qtbot, szene)
    _vorschlaege_da(qtbot, win)
    qtbot.mouseClick(kachel, Qt.MouseButton.LeftButton)
    assert win._markierter_ordner is None and not kachel.markiert
    assert win.ordner_ki_btn.isHidden() and not win.suggestion_widgets
    assert win.suggestions_label.text() == "Vorgeschlagene Ziele:"
    assert win.no_suggestions_label.text() == "Wählen Sie eine PDF aus für Vorschläge"


def test_doppelklick_navigiert_und_markiert_nicht_dauerhaft(qtbot, szene):
    win = szene.win
    kachel = _kachel(win, "Versicherungen")
    qtbot.mouseDClick(kachel, Qt.MouseButton.LeftButton)
    # Navigation in den Ordner: die Zeile gibt es dort nicht mehr, die Markierung ist weg
    assert win.config.get_scan_folder() == szene.vers or Path(win.config.get_scan_folder()) == szene.vers
    assert win._markierter_ordner is None


def test_markierung_und_pdf_auswahl_schliessen_sich_aus(qtbot, szene):
    win = szene.win
    kachel = _markieren(qtbot, szene)
    _vorschlaege_da(qtbot, win)
    lose = szene.scan / "lose.pdf"
    win.on_pdf_clicked(lose)
    assert win._markierter_ordner is None and not kachel.markiert
    assert win.selected_pdf == lose
    assert win.ordner_ki_btn.isHidden()

    kachel = _markieren(qtbot, szene)  # umgekehrt: Ordner markieren hebt die PDF-Auswahl auf
    assert win._markierter_ordner == szene.vers
    assert win.selected_pdf is None and win.selected_pdfs == []
    assert not any(w.selected for w in win.pdf_widgets)


def test_ctrl_klick_auf_pdf_hebt_ordnermarkierung_auf(qtbot, szene):
    win = szene.win
    _markieren(qtbot, szene)
    win.on_pdf_ctrl_clicked(szene.scan / "lose.pdf")
    assert win._markierter_ordner is None


def test_markierung_bleibt_nach_neuladen_wenn_ordner_noch_da(qtbot, szene):
    win = szene.win
    kachel = _markieren(qtbot, szene)
    win.load_pdfs()
    assert win._markierter_ordner == szene.vers
    assert _kachel(win, "Versicherungen").markiert
    szene.vers.rename(szene.scan / "Umbenannt")
    win.load_pdfs()
    assert win._markierter_ordner is None


def test_vorschlaege_veralteter_ordner_werden_verworfen(qtbot, szene):
    win = szene.win
    (szene.scan / "Zweiter").mkdir()
    win.load_pdfs()
    _markieren(qtbot, szene)
    gen = win._ordner_generation
    _markieren(qtbot, szene, "Zweiter")
    win._ordner_vorschlaege_da(gen, szene.vers, [SimpleNamespace(folder_path=szene.ziel)])
    assert win._ordner_vorschlaege == []  # kam fuer den alten Ordner


# --- Verschieben -----------------------------------------------------------------------

def test_klick_auf_vorschlag_verschiebt_den_ganzen_ordner(qtbot, szene):
    win = szene.win
    _markieren(qtbot, szene)
    _vorschlaege_da(qtbot, win)
    zeile = win.suggestion_widgets[0]
    assert zeile.folder_path == szene.ziel

    zeile.clicked.emit(zeile.folder_path)

    ziel = szene.ziel / "Versicherungen"
    _fertig(qtbot, win, lambda: ziel.exists())
    assert (ziel / "a.pdf").exists() and (ziel / "Kfz" / "b.pdf").exists() and (ziel / "Brief.docx").exists()
    assert not szene.vers.exists()  # Quellordner weg
    assert win._markierter_ordner is None  # nach dem Verschieben keine Markierung mehr
    assert win._undo_stack[-1]["type"] == "ordner"
    assert "Versicherungen" in win._undo_stack[-1]["description"]
    titel, text = szene.dialoge.fragen[-1]
    assert "verschieben" in titel and "3 Dateien" in text and "Steuer 2025" in text
    assert [t.full_name for t in win.folder_tiles if not t.is_parent] == []  # Zeile verschwunden


def test_klick_auf_baumordner_verschiebt_den_markierten_ordner(qtbot, szene):
    win = szene.win
    _markieren(qtbot, szene)
    win.folder_tree.folder_selected.emit(szene.ablage / "Privat")
    _fertig(qtbot, win, lambda: (szene.ablage / "Privat" / "Versicherungen").exists())
    assert (szene.ablage / "Privat" / "Versicherungen" / "Kfz" / "b.pdf").exists()


def test_baum_menue_hierhin_verschieben_und_kopieren_mit_markiertem_ordner(qtbot, szene):
    win = szene.win
    _markieren(qtbot, szene)
    menue = win.folder_tree._build_context_menu(szene.ablage / "Privat")
    texte = {a.text(): a for a in menue.actions()}
    assert texte["📥 Hierhin verschieben"].isEnabled()
    assert texte["📁 Ordner hierhin kopieren"].isEnabled()
    texte["📁 Ordner hierhin kopieren"].trigger()
    ziel = szene.ablage / "Privat" / "Versicherungen"
    _fertig(qtbot, win, lambda: (ziel / "a.pdf").exists())
    assert szene.vers.exists()  # kopiert: Original bleibt
    assert win._markierter_ordner == szene.vers  # und bleibt markiert


def test_sperre_ordner_in_sich_selbst(qtbot, szene):
    win = szene.win
    win.ordner_uebertragen(szene.vers, szene.vers / "Kfz", False)
    assert szene.dialoge.warnungen and "sich selbst" in szene.dialoge.warnungen[-1][1]
    assert not win._ordner_laeuft and (szene.vers / "Kfz" / "b.pdf").exists()
    assert not szene.dialoge.fragen  # gar nicht erst gefragt


def test_ablehnen_der_rueckfrage_aendert_nichts(qtbot, szene, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    szene.win.ordner_uebertragen(szene.vers, szene.ziel, False)
    assert szene.vers.exists() and not (szene.ziel / "Versicherungen").exists()
    assert not szene.win._undo_stack


def test_zusammenfuehren_nummeriert_und_nennt_es_in_der_rueckfrage(qtbot, szene):
    win = szene.win
    vorhanden = szene.ablage / "Steuer 2024"
    _datei(vorhanden / "Versicherungen" / "a.pdf", b"anderer Inhalt")
    _datei(vorhanden / "Versicherungen" / "Kfz" / "b.pdf", szene.vers.joinpath("Kfz", "b.pdf").read_bytes())  # identisch
    win.ordner_uebertragen(szene.vers, vorhanden, False)
    _fertig(qtbot, win, lambda: not szene.vers.exists())

    ziel = vorhanden / "Versicherungen"
    assert (ziel / "a.pdf").read_bytes() == b"anderer Inhalt"
    assert (ziel / "a (2).pdf").exists()
    assert sorted(p.name for p in (ziel / "Kfz").iterdir()) == ["b.pdf"]  # identische nicht doppelt
    assert "zusammengeführt" in szene.dialoge.fragen[-1][1]


def test_strg_ziehen_auf_den_baum_kopiert(qtbot, szene, monkeypatch):
    win = szene.win
    baum = win.folder_tree
    monkeypatch.setattr(baum.tree, "itemAt", lambda pos: baum._items[szene.ziel])
    mime = QMimeData()
    mime.setData(ORDNER_MIME, str(szene.vers).encode("utf-8"))
    aktionen = Qt.DropAction.MoveAction | Qt.DropAction.CopyAction
    ereignis = QDropEvent(QPointF(5, 5), aktionen, mime, Qt.MouseButton.LeftButton, STRG)
    baum.tree.dropEvent(ereignis)

    ziel = szene.ziel / "Versicherungen"
    qtbot.waitUntil(lambda: (ziel / "a.pdf").exists() and not win._ordner_laeuft, timeout=8000)
    assert szene.vers.exists()  # Strg: kopiert
    assert "kopieren" in szene.dialoge.fragen[-1][0]


def test_ziehen_auf_den_baum_verschiebt(qtbot, szene, monkeypatch):
    win = szene.win
    baum = win.folder_tree
    monkeypatch.setattr(baum.tree, "itemAt", lambda pos: baum._items[szene.ziel])
    mime = QMimeData()
    mime.setData(ORDNER_MIME, str(szene.vers).encode("utf-8"))
    ereignis = QDropEvent(QPointF(5, 5), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton,
                          Qt.KeyboardModifier.NoModifier)
    baum.tree.dropEvent(ereignis)
    ziel = szene.ziel / "Versicherungen"
    qtbot.waitUntil(lambda: (ziel / "a.pdf").exists() and not win._ordner_laeuft, timeout=8000)
    assert not szene.vers.exists()


def test_ordner_in_eigenen_unterordner_ziehen_wird_abgelehnt(qtbot, szene, monkeypatch):
    baum = szene.win.folder_tree
    (szene.ablage / "Privat" / "Sub").mkdir()
    baum.tree.expandAll()
    monkeypatch.setattr(baum.tree, "itemAt", lambda pos: baum._items[szene.ablage / "Privat"])
    mime = QMimeData()
    mime.setData(ORDNER_MIME, str(szene.ablage / "Privat").encode("utf-8"))  # auf sich selbst
    ereignis = QDropEvent(QPointF(5, 5), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton,
                          Qt.KeyboardModifier.NoModifier)
    ereignis.setAccepted(True)
    baum.tree.dropEvent(ereignis)
    assert not ereignis.isAccepted()
    assert not szene.dialoge.fragen


def test_baum_nimmt_keine_fremden_ordner_per_url_an(qtbot, szene):
    """Nur Ordnerzeilen aus dem Programm (eigener Mime-Typ), nicht beliebige URLs."""
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDragEnterEvent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(szene.vers))])
    ereignis = QDragEnterEvent(QPointF(5, 5).toPoint(), Qt.DropAction.MoveAction, mime,
                               Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    ereignis.setAccepted(True)
    szene.win.folder_tree._tree_drag_enter(ereignis)
    assert not ereignis.isAccepted()


# --- Kontextmenue der Ordnerzeile ------------------------------------------------------------

def test_kontextmenue_der_ordnerzeile_bietet_vorschlaege_an(qtbot, szene):
    win = szene.win
    kachel = _kachel(win, "Versicherungen")
    kachel.markieren_requested.emit(kachel.folder_path)  # was ein Rechtsklick zuerst tut
    _vorschlaege_da(qtbot, win)

    menue = kachel._build_context_menu()
    verschieben = next(a for a in menue.actions() if a.text() == "📁 Ordner verschieben nach …")
    kopieren = next(a for a in menue.actions() if a.text() == "📁 Ordner kopieren nach …")
    eintraege = [a.text() for a in verschieben.menu().actions() if a.text()]
    assert eintraege[0].startswith("Ablage/Steuer 2025 (")
    assert eintraege[-1] == "Anderen Ordner wählen …"
    assert kopieren.menu().actions()[0].text().startswith("Ablage/Steuer 2025 (")

    verschieben.menu().actions()[0].trigger()
    _fertig(qtbot, win, lambda: (szene.ziel / "Versicherungen" / "a.pdf").exists())
    assert not szene.vers.exists()


def test_kontextmenue_anderen_ordner_waehlen(qtbot, szene, monkeypatch):
    from PyQt6.QtWidgets import QFileDialog

    win = szene.win
    kachel = _kachel(win, "Versicherungen")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(szene.ablage / "Privat")))
    menue = kachel._build_context_menu()
    kopieren = next(a for a in menue.actions() if a.text() == "📁 Ordner kopieren nach …")
    assert kopieren.menu().actions()[0].text() == "(noch keine Vorschläge)"
    kopieren.menu().actions()[-1].trigger()
    _fertig(qtbot, win, lambda: (szene.ablage / "Privat" / "Versicherungen" / "a.pdf").exists())
    assert szene.vers.exists()


def test_rechtsklick_auf_vorschlagszeile_menue(qtbot, szene):
    win = szene.win
    _markieren(qtbot, szene)
    _vorschlaege_da(qtbot, win)
    menue = win.suggestion_widgets[0]._build_context_menu()
    texte = [a.text() for a in menue.actions() if not a.isSeparator()]
    assert texte[:2] == ["📁 Ordner hierhin verschieben", "📁 Ordner hierhin kopieren"]
    next(a for a in menue.actions() if "kopieren" in a.text()).trigger()
    _fertig(qtbot, win, lambda: (szene.ziel / "Versicherungen" / "a.pdf").exists())
    assert szene.vers.exists()


def test_pdf_hierhin_menue_wird_zu_ordner_hierhin_bei_markiertem_ordner(qtbot, szene):
    win = szene.win
    kachel = _kachel(win, "Versicherungen")
    menue = kachel._build_context_menu()
    assert any(a.text() == "📄 PDF hierhin kopieren" and not a.isEnabled() for a in menue.actions())
    _markieren(qtbot, szene)
    menue = kachel._build_context_menu()
    assert any(a.text() == "📁 Ordner hierhin kopieren" and a.isEnabled() for a in menue.actions())
    assert any(a.text() == "➡ PDF hierhin verschieben" or a.text() == "📁 Ordner hierhin verschieben"
               for a in menue.actions())


# --- Rueckgaengig -----------------------------------------------------------------------------

def test_strg_z_macht_verschieben_rueckgaengig(qtbot, szene):
    win = szene.win
    win.ordner_uebertragen(szene.vers, szene.ziel, False)
    _fertig(qtbot, win, lambda: not szene.vers.exists())
    assert win.undo_action.isEnabled() and "Versicherungen" in win.undo_action.text()

    win.undo_last_action()
    _fertig(qtbot, win, lambda: szene.vers.exists())

    assert (szene.vers / "a.pdf").exists() and (szene.vers / "Kfz" / "b.pdf").exists()
    assert not (szene.ziel / "Versicherungen").exists()
    assert not win._undo_stack
    assert [t.full_name for t in win.folder_tiles if not t.is_parent] == ["Versicherungen"]


def test_strg_z_macht_kopieren_rueckgaengig_kopie_in_den_papierkorb(qtbot, szene, monkeypatch):
    win = szene.win
    korb = []
    echt = win.file_manager.delete_file

    def merken(pfad, *a, **k):
        korb.append(Path(pfad).name)
        return echt(pfad, *a, **k)

    monkeypatch.setattr(win.file_manager, "delete_file", merken)
    win.ordner_uebertragen(szene.vers, szene.ziel, True)
    ziel = szene.ziel / "Versicherungen"
    _fertig(qtbot, win, lambda: (ziel / "a.pdf").exists())
    assert szene.vers.exists()

    win.undo_last_action()
    _fertig(qtbot, win, lambda: not ziel.exists())
    assert sorted(korb) == ["Brief.docx", "a.pdf", "b.pdf"]  # die Kopien, nicht die Originale
    assert (szene.vers / "a.pdf").exists()


def test_undo_beim_zusammenfuehren_holt_identische_aus_dem_papierkorb(qtbot, szene):
    win = szene.win
    vorhanden = szene.ablage / "Steuer 2024" / "Versicherungen"
    _datei(vorhanden / "a.pdf")  # byte-gleich zu vers/a.pdf
    win.ordner_uebertragen(szene.vers, szene.ablage / "Steuer 2024", False)
    _fertig(qtbot, win, lambda: not szene.vers.exists())
    assert not list(vorhanden.glob("a (2).pdf"))

    win.undo_last_action()
    _fertig(qtbot, win, lambda: (szene.vers / "a.pdf").exists())
    assert (vorhanden / "a.pdf").exists()  # Vorhandenes bleibt
    assert (szene.vers / "Kfz" / "b.pdf").exists()


# --- Pfade und Lernen -----------------------------------------------------------------------------

def test_gespeicherte_pfade_ziehen_mit(qtbot, szene):
    win, cfg = szene.win, szene.cfg
    cfg.add_target_folder(szene.vers)
    win.folder_manager.add_folder(szene.vers)
    cfg.set("favoriten", [{"pfad": str(szene.vers), "name": "Vers"}])
    win.db.add_sorting_entry("x.pdf", "q/x.pdf", str(szene.vers / "Kfz"), "Kfz", extracted_text="t")
    alt_pdf = szene.vers / "a.pdf"
    win.pdf_cache._cache[alt_pdf] = PDFAnalysisResult(
        pdf_path=alt_pdf, extracted_text="Cachetext", file_modified=alt_pdf.stat().st_mtime)

    win.ordner_uebertragen(szene.vers, szene.ziel, False)
    ziel = szene.ziel / "Versicherungen"
    _fertig(qtbot, win, lambda: ziel.exists())

    assert ziel in cfg.get_target_folders() and szene.vers not in cfg.get_target_folders()
    assert ziel in win.folder_manager.target_folders and szene.vers not in win.folder_manager.target_folders
    assert cfg.get("favoriten") == [{"pfad": str(ziel), "name": "Vers"}]
    assert win.db.get_all_sorting_entries()[-1].target_folder == str(ziel / "Kfz")
    assert alt_pdf not in win.pdf_cache._cache
    assert win.pdf_cache._cache[ziel / "a.pdf"].extracted_text == "Cachetext"
    assert win.favoriten_leiste.ist_favorit(ziel)


def test_verschieben_zaehlt_als_lernerfahrung_je_pdf(qtbot, szene, monkeypatch):
    win = szene.win
    gelernt = []
    monkeypatch.setattr(win.classifier, "learn", lambda **kw: gelernt.append(kw))
    for name in ("a.pdf", "Kfz/b.pdf"):
        p = szene.vers / name
        win.pdf_cache._cache[p] = PDFAnalysisResult(
            pdf_path=p, extracted_text=f"Text {name}", keywords=["kw"], file_modified=p.stat().st_mtime)
    # Brief.docx hat keinen gecachten Text und lernt nicht

    win.ordner_uebertragen(szene.vers, szene.ziel, False)
    ziel = szene.ziel / "Versicherungen"
    _fertig(qtbot, win, lambda: ziel.exists())

    ziele = {kw["pdf_path"].name: kw["target_folder"] for kw in gelernt}
    assert ziele == {"a.pdf": ziel, "b.pdf": ziel / "Kfz"}  # als waere jede einzeln dorthin sortiert worden
    assert {kw["extracted_text"] for kw in gelernt} == {"Text a.pdf", "Text Kfz/b.pdf"}
    assert all(kw["relative_path"].replace("\\", "/").startswith("Ablage/Steuer 2025/Versicherungen") for kw in gelernt)


def test_kopieren_lernt_wie_beim_kopieren_einzelner_pdfs(qtbot, szene, monkeypatch):
    win = szene.win
    gelernt = []
    monkeypatch.setattr(win.classifier, "learn", lambda **kw: gelernt.append(kw))
    p = szene.vers / "a.pdf"
    win.pdf_cache._cache[p] = PDFAnalysisResult(pdf_path=p, extracted_text="Text", file_modified=p.stat().st_mtime)
    win.ordner_uebertragen(szene.vers, szene.ziel, True)
    ziel = szene.ziel / "Versicherungen"
    _fertig(qtbot, win, lambda: ziel.exists())
    assert [kw["target_folder"] for kw in gelernt] == [ziel]
    assert p in win.pdf_cache._cache  # beim Kopieren ziehen keine Pfade um


def test_kopieren_zieht_keine_pfade_um(qtbot, szene):
    win, cfg = szene.win, szene.cfg
    cfg.add_target_folder(szene.vers)
    win.folder_manager.add_folder(szene.vers)
    win.ordner_uebertragen(szene.vers, szene.ziel, True)
    _fertig(qtbot, win, lambda: (szene.ziel / "Versicherungen").exists())
    assert szene.vers in cfg.get_target_folders()


def test_umbenennen_im_baum_zieht_jetzt_auch_gelernte_pfade_nach(szene):
    win, cfg = szene.win, szene.cfg
    alt = szene.ablage / "Privat"
    neu = szene.ablage / "Persoenlich"
    cfg.add_target_folder(alt)
    win.folder_manager.add_folder(alt)
    win.db.add_sorting_entry("x.pdf", "q/x.pdf", str(alt), "Privat", extracted_text="t")
    alt.rename(neu)
    win.folder_tree.folder_renamed.emit(alt, neu)
    assert neu in cfg.get_target_folders() and alt not in cfg.get_target_folders()
    eintrag = win.db.get_all_sorting_entries()[-1]
    assert eintrag.target_folder == str(neu) and eintrag.target_folder_name == "Persoenlich"


# --- KI auf Knopfdruck ------------------------------------------------------------------------------

class FakeProvider:
    def __init__(self, antwort):
        self.antwort = antwort
        self.fragen = []

    def answer_with_context(self, system_prompt, context_docs, user_question, max_tokens=1000):
        self.fragen.append(user_question)
        return self.antwort


def test_ki_ohne_eingerichtete_ki_zeigt_hinweis(qtbot, szene, monkeypatch):
    win = szene.win
    monkeypatch.setattr(win.hybrid_classifier, "llm_enabled", False)
    _markieren(qtbot, szene)
    win.ordner_ki_btn.click()
    assert szene.dialoge.infos and "KI" in szene.dialoge.infos[-1][0]


def test_ki_fragen_ergaenzt_den_vorschlag(qtbot, szene, monkeypatch):
    win = szene.win
    provider = FakeProvider('{"zielordner": "Ablage/Privat", "begruendung": "Privatversicherungen"}')
    monkeypatch.setattr(win.hybrid_classifier, "llm_provider", provider)
    monkeypatch.setattr(win.hybrid_classifier, "llm_enabled", True)
    _markieren(qtbot, szene)
    _vorschlaege_da(qtbot, win)
    anzahl = len(win.suggestion_widgets)

    win.ordner_ki_btn.click()
    qtbot.waitUntil(lambda: win.suggestion_widgets and win.suggestion_widgets[0].folder_path == szene.ablage / "Privat",
                    timeout=5000)

    assert len(win.suggestion_widgets) == anzahl + 1
    assert "Versicherungen" in provider.fragen[0] and "a.pdf" in provider.fragen[0]
    assert win.ordner_ki_btn.isEnabled()
    assert szene.ablage / "Privat" in win.folder_tree._suggestion_folders


def test_ki_fehler_wird_gemeldet_und_knopf_wieder_frei(qtbot, szene, monkeypatch):
    win = szene.win
    monkeypatch.setattr(win.hybrid_classifier, "llm_provider", FakeProvider("[Claude-Fehler: Zeitüberschreitung]"))
    monkeypatch.setattr(win.hybrid_classifier, "llm_enabled", True)
    _markieren(qtbot, szene)
    win.ordner_ki_btn.click()
    qtbot.waitUntil(lambda: bool(szene.dialoge.warnungen), timeout=5000)
    assert "Zeitüberschreitung" in szene.dialoge.warnungen[-1][1]
    assert win.ordner_ki_btn.isEnabled()


def test_ki_antwort_fuer_vorhandenen_vorschlag_bestaetigt_ihn(qtbot, szene, monkeypatch):
    win = szene.win
    monkeypatch.setattr(win.hybrid_classifier, "llm_provider", FakeProvider('{"zielordner": "Ablage/Steuer 2025"}'))
    monkeypatch.setattr(win.hybrid_classifier, "llm_enabled", True)
    _markieren(qtbot, szene)
    _vorschlaege_da(qtbot, win)
    anzahl = len(win.suggestion_widgets)
    win.ordner_ki_btn.click()
    qtbot.waitUntil(lambda: "KI bestätigt" in (win._ordner_vorschlaege[0].reason), timeout=5000)
    assert len(win.suggestion_widgets) == anzahl
    assert win._ordner_vorschlaege[0].confidence >= 0.9


# --- Neuer Zielordner ---------------------------------------------------------------------------------

def test_vorschlag_neuer_jahresordner_wird_beim_verschieben_angelegt(qtbot, szene):
    win = szene.win
    kaputt = szene.ablage / "Steuer 2025"
    kaputt.rmdir()  # Elternordner fuer 2025 fehlt: Vorschlag "neu"
    win.load_folders()
    _markieren(qtbot, szene)
    _vorschlaege_da(qtbot, win)
    neu = [w for w in win.suggestion_widgets if w.neu]
    assert len(neu) == 1 and neu[0].folder_path == kaputt
    neu[0].clicked.emit(neu[0].folder_path)
    ziel = kaputt / "Versicherungen"
    _fertig(qtbot, win, lambda: ziel.exists())
    assert "wird angelegt" in szene.dialoge.fragen[-1][1]
    assert (ziel / "a.pdf").exists()
    win.undo_last_action()
    _fertig(qtbot, win, lambda: szene.vers.exists())
    assert not kaputt.exists()  # neu angelegt, deshalb beim Rueckgaengig wieder weg


# --- Ordnerzeile ziehen ----------------------------------------------------------------------------

def test_ordnerzeile_ziehen_startet_drag_mit_ordner_mime(qtbot, szene, monkeypatch):
    from PyQt6.QtCore import QPoint, QEvent
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtWidgets import QApplication

    from src.gui import folder_tile as ft
    from src.gui.hierhin_kopieren import ordner_aus_mime

    erfasst = {}

    class FakeDrag:
        def __init__(self, quelle):
            pass

        def setMimeData(self, mime):
            erfasst["mime"] = mime

        def setPixmap(self, pix):
            pass

        def exec(self, aktionen, standard):
            erfasst["aktionen"] = aktionen
            return Qt.DropAction.IgnoreAction

    monkeypatch.setattr(ft, "QDrag", FakeDrag)
    kachel = _kachel(szene.win, "Versicherungen")
    start = QPoint(10, 5)
    ziel = QPoint(10 + QApplication.startDragDistance() + 5, 5)
    qtbot.mousePress(kachel, Qt.MouseButton.LeftButton, pos=start)
    bewegung = QMouseEvent(QEvent.Type.MouseMove, ziel.toPointF(), kachel.mapToGlobal(ziel).toPointF(),
                           Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(kachel, bewegung)

    assert ordner_aus_mime(erfasst["mime"]) == szene.vers
    assert erfasst["aktionen"] & Qt.DropAction.CopyAction and erfasst["aktionen"] & Qt.DropAction.MoveAction
    assert not erfasst["mime"].hasUrls()  # fremde Programme sollen den Ordner nicht selbst verschieben


def test_die_ueber_zeile_laesst_sich_nicht_ziehen(qtbot, szene, monkeypatch):
    from PyQt6.QtCore import QPoint, QEvent
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtWidgets import QApplication

    from src.gui import folder_tile as ft

    gestartet = []
    monkeypatch.setattr(ft, "QDrag", lambda q: gestartet.append(q))
    punkt = next(t for t in szene.win.folder_tiles if t.is_parent)
    qtbot.mousePress(punkt, Qt.MouseButton.LeftButton, pos=QPoint(10, 5))
    ziel = QPoint(80, 5)
    QApplication.sendEvent(punkt, QMouseEvent(
        QEvent.Type.MouseMove, ziel.toPointF(), punkt.mapToGlobal(ziel).toPointF(),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    assert not gestartet

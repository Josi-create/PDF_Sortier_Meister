"""Korrekturen aus dem Live-Test (Sammel-PR #198).

1. "Hierhin kopieren" auch in einen NEUEN Ordner (Issue #116/#179): anlegen, bei Fehler wegraeumen.
2. Korrespondenten-Reiter: volle Detailansicht, Verschieben/Umbenennen von dort (Issue #160).
3. Mehrfachauswahl im Korrespondenten-Reiter: Kopieren, Verschieben, Ziehen.

Fixtures wie in tests/test_auto_next_after_move_gui.py: Singletons auf tmp-Pfade (nie die echte
Konfiguration, nie das echte APPDATA), Rueckfragen bejaht, Fehlerdialoge sind Testfehler.
Der Suchindex liegt unter tmp_path, Datei-Papierkorb wird nie angefasst.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QMessageBox

from src.core import neuer_ordner
from src.core.pdf_cache import PDFAnalysisResult
from src.gui.folder_widget import FolderWidget
from src.ml.classifier import Suggestion
from tests.test_auto_next_after_move_gui import (  # noqa: F401 - Fixtures
    _make_scan_folder,
    _prime_cache,
    fresh_singletons,
    main_window,
)

STRG = (
    Qt.KeyboardModifier.AltModifier if sys.platform == "darwin"
    else Qt.KeyboardModifier.ControlModifier
)
KOPIEREN = "hierhin kopieren"


def _pdf(pfad: Path, text: str = "Rechnung") -> Path:
    import pymupdf

    pfad.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    doc.save(str(pfad))
    doc.close()
    return pfad


def _eintrag(menu, teil=KOPIEREN):
    for a in menu.actions():
        if teil in a.text():
            return a
    raise AssertionError(f"Eintrag '{teil}' fehlt: {[a.text() for a in menu.actions()]}")


def _drop(widget, pfade, modifiers=Qt.KeyboardModifier.NoModifier):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in pfade])
    aktionen = Qt.DropAction.MoveAction | Qt.DropAction.CopyAction
    ereignis = QDropEvent(QPointF(5, 5), aktionen, mime, Qt.MouseButton.LeftButton, modifiers)
    widget.dropEvent(ereignis)
    return ereignis


def _ablage(win, tmp: Path) -> Path:
    ablage = tmp / "Ablage"
    ablage.mkdir(exist_ok=True)
    win.config.add_target_folder(ablage)
    win.folder_manager.add_folder(ablage)
    win.load_folders()
    return ablage


def _neu_vorschlag(pfad: Path, rel: str) -> Suggestion:
    return Suggestion(pfad, pfad.name, 0.9, "neu", relative_path=rel, new_source=neuer_ordner.QUELLE_JAHR)


# ====================================================================== #
# 1. Kopieren in einen neuen Ordner
# ====================================================================== #


@pytest.fixture
def neu_aufbau(main_window, fresh_singletons):  # noqa: F811
    tmp = fresh_singletons["tmp_path"]
    scan = tmp / "Scan"
    a = _pdf(scan / "a.pdf", "Rechnung Strom")
    b = _pdf(scan / "b.pdf", "Mahnung")
    ablage = _ablage(main_window, tmp)
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [w.pdf_path for w in main_window.pdf_widgets])
    main_window.on_pdf_clicked(a)
    main_window.detail_panel.name_input.setText("")
    neu = ablage / "Steuer 2027"
    main_window.display_suggestions([_neu_vorschlag(neu, "Ablage/Steuer 2027")])
    kachel = main_window.suggestion_widgets[0]
    return {"win": main_window, "a": a, "b": b, "neu": neu, "kachel": kachel}


def test_neue_kachel_hat_kopieren_menue_und_strg_drop(neu_aufbau):
    win, a, neu, kachel = (neu_aufbau[k] for k in ("win", "a", "neu", "kachel"))
    assert kachel.neu
    eintrag = _eintrag(kachel._build_context_menu())
    assert eintrag.isEnabled()
    assert not neu.exists()

    eintrag.trigger()  # legt den Ordner an und kopiert
    assert (neu / "a.pdf").exists() and a.exists()
    assert neu.is_dir()


def test_strg_drop_auf_neue_kachel_kopiert_und_legt_an(neu_aufbau):
    win, a, b, neu, kachel = (neu_aufbau[k] for k in ("win", "a", "b", "neu", "kachel"))
    _drop(kachel, [a, b], STRG)
    assert sorted(p.name for p in neu.iterdir()) == ["a.pdf", "b.pdf"]
    assert a.exists() and b.exists()


def test_kopieren_in_neuen_ordner_nach_nein_legt_nichts_an(neu_aufbau, monkeypatch):
    win, neu = neu_aufbau["win"], neu_aufbau["neu"]
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    win.on_copy_here_requested(neu)
    assert not neu.exists()


def test_kopieren_in_neuen_ordner_raeumt_bei_fehler_weg(neu_aufbau, monkeypatch):
    win, a, neu = neu_aufbau["win"], neu_aufbau["a"], neu_aufbau["neu"]
    warnungen = []

    def kaputt(*args, **kwargs):
        raise OSError("Platte voll")

    monkeypatch.setattr(win.file_manager, "copy_file", kaputt)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **k: warnungen.append(args[2]))

    win.on_copy_here_requested(neu)

    assert warnungen and "Platte voll" in warnungen[0]
    assert not neu.exists()  # der neu angelegte (leere) Ordner ist wieder weg
    assert a.exists()


def test_kopieren_in_neuen_ordner_behaelt_ihn_bei_teilerfolg(neu_aufbau, monkeypatch):
    win, a, b, neu = (neu_aufbau[k] for k in ("win", "a", "b", "neu"))
    echt = win.file_manager.copy_file

    def manchmal(source, target_folder, new_name=None):
        if Path(source).name == "b.pdf":
            raise OSError("gesperrt")
        return echt(source, target_folder, new_name=new_name)

    monkeypatch.setattr(win.file_manager, "copy_file", manchmal)
    win.on_pdf_ctrl_clicked(b)
    win.on_copy_here_requested(neu)
    assert (neu / "a.pdf").exists() and not (neu / "b.pdf").exists()


def test_klick_auf_neue_kachel_verschiebt_weiterhin(neu_aufbau):
    win, a, neu = neu_aufbau["win"], neu_aufbau["a"], neu_aufbau["neu"]
    win.on_suggestion_clicked(neu)
    assert (neu / "a.pdf").exists() and not a.exists()


# ====================================================================== #
# 2. + 3. Korrespondenten-Reiter: volle Ansicht, Verschieben, Mehrfachauswahl
# ====================================================================== #


def _vorbereiten(win, pfad: Path, text: str = "") -> None:
    """Analyse-Ergebnis direkt in den Cache (kein Hintergrund-Worker)."""
    win.pdf_cache._cache[pfad] = PDFAnalysisResult(
        pdf_path=pfad, extracted_text=text, keywords=["rechnung"] if text else [],
        file_modified=pfad.stat().st_mtime,
    )


@pytest.fixture
def korr(main_window, fresh_singletons, monkeypatch):  # noqa: F811
    """Drei indizierte Dokumente von "Stadtwerke" in Ablage/Alt, zwei Scan-PDFs, ein Zielordner."""
    cfg = fresh_singletons["config"]
    cfg.set("suche", {"aktiv": True})
    tmp: Path = fresh_singletons["tmp_path"]
    win = main_window
    ablage = _ablage(win, tmp)
    ziel = ablage / "Ziel"
    ziel.mkdir()
    docs = [_pdf(ablage / "Alt" / f"d{i}.pdf", f"Rechnung Stadtwerke {i}") for i in (1, 2, 3)]
    for d in docs:
        win.db.suchindex.metadaten_setzen(str(d), {"korrespondent": "Stadtwerke"}, lesen=False)
    scan = tmp / "Scan"
    s1 = _pdf(scan / "s1.pdf", "Scan eins")
    s2 = _pdf(scan / "s2.pdf", "Scan zwei")
    win._navigate_to_folder(scan)
    for p in (s1, s2):
        _vorbereiten(win, p, "Scan Text")
    for d in docs:
        _vorbereiten(win, d, "Rechnung Stadtwerke")
    # feste Vorschlaege: immer der Zielordner
    monkeypatch.setattr(
        win.classifier, "suggest_with_subfolders",
        lambda **k: [Suggestion(ziel, "Ziel", 0.8, "test", relative_path="Ablage/Ziel")],
    )
    # keine Hintergrund-Analyse
    monkeypatch.setattr(win.pdf_cache, "request_analysis", lambda *a, **k: None)
    gelernt = []
    monkeypatch.setattr(win.classifier, "learn", lambda **k: gelernt.append(k))
    win.show_korrespondent("Stadtwerke")
    return {"win": win, "docs": docs, "scan": scan, "s1": s1, "s2": s2, "ziel": ziel, "ablage": ablage,
            "view": win.korrespondenten_view, "gelernt": gelernt}


def _markieren(view, *namen: str) -> None:
    """Dokumente per Namen in der Liste markieren (wie Strg-Klick)."""
    view.dokumente.clearSelection()
    for i in range(view.dokumente.topLevelItemCount()):
        item = view.dokumente.topLevelItem(i)
        if item.text(1) in namen:
            item.setSelected(True)


def test_klick_im_reiter_fuellt_felder_und_vorschlaege(korr):
    win, view, d1, ziel = korr["win"], korr["view"], korr["docs"][0], korr["ziel"]
    _markieren(view, "d1.pdf")

    panel = win.detail_panel
    assert win.selected_pdf == d1 and win.selected_pdfs == []
    assert panel.get_current_pdf() == d1
    assert not panel.detail_container.isHidden()  # volle Ansicht mit Feldern
    assert "korrespondent" in panel._metadata_inputs
    assert [w.folder_path for w in win.suggestion_widgets] == [ziel]
    assert win.selected_pdf_text == "Rechnung Stadtwerke"


def test_verschieben_aus_dem_reiter_trifft_die_richtige_datei_lernt_und_meldet_dem_index(korr):
    from src.search.meldungen import meldungen

    win, view, ziel = korr["win"], korr["view"], korr["ziel"]
    d1, d2, _d3 = korr["docs"]
    meldungen.konfigurieren(lambda: win.db.suchindex)  # Index unter tmp_path (conftest schaltet danach ab)
    _markieren(view, "d2.pdf")
    win.detail_panel.name_input.setText("d2.pdf")  # Name bleibt

    win.on_suggestion_clicked(ziel)

    assert (ziel / "d2.pdf").exists() and not d2.exists() and d1.exists()  # genau die gewaehlte Datei
    assert [k["pdf_path"] for k in korr["gelernt"]] == [d2]  # gelernt
    assert [k["target_folder"] for k in korr["gelernt"]] == [ziel]
    # Liste zeigt sofort den neuen Pfad ...
    neu = {d["name"]: Path(d["pfad"]) for d in view.angezeigte_dokumente()}
    assert neu["d2.pdf"] == ziel / "d2.pdf" and neu["d1.pdf"] == d1
    # ... und der Suchindex zieht ueber die Warteschlange nach
    assert meldungen.warten(10.0)
    view.refresh(abgleich=False)
    pfade = {Path(d["pfad"]) for d in view.angezeigte_dokumente()}
    assert ziel / "d2.pdf" in pfade and d2 not in pfade
    # nichts mehr ausgewaehlt, Mitte leer, Eingangsliste unberuehrt
    assert win.selected_pdf is None and win.detail_panel.get_current_pdf() is None
    assert not win.suggestion_widgets
    assert korr["s1"].exists() and len(win.pdf_widgets) == 2


def test_umbenennen_und_speichern_aus_dem_reiter(korr):
    win, view = korr["win"], korr["view"]
    d1 = korr["docs"][0]
    _markieren(view, "d1.pdf")
    win.detail_panel.name_input.setText("2026-01-01_Strom.pdf")

    win._on_rename_and_save_metadata()

    umbenannt = d1.with_name("2026-01-01_Strom.pdf")
    assert umbenannt.exists() and not d1.exists()
    assert win.selected_pdf == umbenannt and win.detail_panel.get_current_pdf() == umbenannt
    namen = [d["name"] for d in view.angezeigte_dokumente()]
    assert "2026-01-01_Strom.pdf" in namen and "d1.pdf" not in namen
    # Rueckgaengig stellt auch die Liste wieder her
    win.undo_last_action()
    assert d1.exists()
    assert "d1.pdf" in [d["name"] for d in view.angezeigte_dokumente()]


def test_zurueck_zu_pdfs_gilt_deren_auswahl_und_felder_gehoeren_zur_richtigen_datei(korr, monkeypatch):
    win, view, s1, d1 = korr["win"], korr["view"], korr["s1"], korr["docs"][0]
    win.left_tabs.setCurrentIndex(0)
    win.on_pdf_clicked(s1)
    assert win.detail_panel.get_current_pdf() == s1

    win.left_tabs.setCurrentWidget(view)
    _markieren(view, "d1.pdf")
    assert win.detail_panel.get_current_pdf() == d1
    win.detail_panel._metadata_inputs["korrespondent"].setText("Nur fuer d1")

    win.left_tabs.setCurrentIndex(0)  # zurueck: die Auswahl der Liste gilt wieder
    assert win.selected_pdf == s1 and win.selected_pdfs == []
    assert win.detail_panel.get_current_pdf() == s1
    assert win.detail_panel._metadata_inputs["korrespondent"].text() != "Nur fuer d1"

    # Speichern geht an die Datei, die das Panel zeigt - nie an die andere
    geschrieben = []
    monkeypatch.setattr(win, "_write_pdf_metadata", lambda p, n, k, m: geschrieben.append((p, m)))
    win.detail_panel._metadata_inputs["korrespondent"].setText("Fuer s1")
    win._on_save_metadata_in_place()
    assert [p for p, _m in geschrieben] == [s1]
    assert geschrieben[0][1]["korrespondent"] == "Fuer s1"

    win.left_tabs.setCurrentWidget(view)
    _markieren(view, "d1.pdf")
    win.detail_panel._metadata_inputs["korrespondent"].setText("Fuer d1")
    win._on_save_metadata_in_place()
    assert [p for p, _m in geschrieben] == [s1, d1]
    assert geschrieben[1][1]["korrespondent"] == "Fuer d1"


def test_ohne_fertige_analyse_zeigt_das_panel_nie_fremde_felder(korr):
    """Noch nicht analysiert: das Panel wird geleert, und Verschieben nimmt keinen fremden Namen."""
    win, view, s1, d2, ziel = korr["win"], korr["view"], korr["s1"], korr["docs"][1], korr["ziel"]
    win.left_tabs.setCurrentIndex(0)
    win.on_pdf_clicked(s1)
    win.detail_panel.name_input.setText("2026-02-02_Name_fuer_s1.pdf")
    del win.pdf_cache._cache[d2]  # Analyse von d2 steht noch aus
    win.left_tabs.setCurrentWidget(view)

    _markieren(view, "d2.pdf")
    assert win.selected_pdf == d2
    assert win.detail_panel.get_current_pdf() is None  # nicht mehr s1

    win._move_rename_and_learn(d2, ziel)  # Rueckfrage wird bejaht
    assert (ziel / "d2.pdf").exists()  # Originalname, nicht der Name von s1
    assert not list(ziel.glob("*Name_fuer_s1*"))


def test_mehrfachauswahl_im_reiter_verschiebt_alle(korr):
    win, view, ziel = korr["win"], korr["view"], korr["ziel"]
    d1, d2, d3 = korr["docs"]
    _markieren(view, "d1.pdf", "d3.pdf")
    assert win.selected_pdfs == [d1, d3]  # Reihenfolge der Liste
    assert "2 Dokumente" in win.statusbar.currentMessage()

    win.on_suggestion_clicked(ziel)

    assert sorted(p.name for p in ziel.iterdir()) == ["d1.pdf", "d3.pdf"]
    assert d2.exists() and not d1.exists() and not d3.exists()
    assert win.selected_pdfs == [] and win.selected_pdf is None
    assert {Path(d["pfad"]).parent for d in view.angezeigte_dokumente() if d["name"] != "d2.pdf"} == {ziel}
    # Rueckgaengig holt beide zurueck (ein Undo-Eintrag)
    win.undo_last_action()
    assert d1.exists() and d3.exists()
    assert {Path(d["pfad"]).parent for d in view.angezeigte_dokumente()} == {d1.parent}


def test_mehrfachauswahl_ueber_baum_verschieben_und_kopieren(korr):
    win, view, ziel = korr["win"], korr["view"], korr["ziel"]
    d1, d2, d3 = korr["docs"]
    _markieren(view, "d1.pdf", "d2.pdf")
    menue = win.folder_tree._build_context_menu(ziel)
    kopieren, verschieben = _eintrag(menue, "hierhin kopieren"), _eintrag(menue, "Hierhin verschieben")
    assert kopieren.text() == "📄 2 Dateien hierhin kopieren" and kopieren.isEnabled()
    assert verschieben.isEnabled()

    kopieren.trigger()
    assert sorted(p.name for p in ziel.iterdir()) == ["d1.pdf", "d2.pdf"]
    assert d1.exists() and d2.exists()  # Originale bleiben
    assert win.selected_pdfs == [d1, d2]  # Auswahl bleibt nach dem Kopieren

    _markieren(view, "d3.pdf", "d1.pdf")
    _eintrag(win.folder_tree._build_context_menu(ziel), "Hierhin verschieben").trigger()
    assert not d1.exists() and not d3.exists() and d2.exists()
    assert sorted(p.name for p in ziel.iterdir()) == ["d1 (1).pdf", "d1.pdf", "d2.pdf", "d3.pdf"]


def test_ziehen_aus_der_liste_auf_einen_ordner(korr, qtbot, monkeypatch):
    win, view, ziel = korr["win"], korr["view"], korr["ziel"]
    d1, d2, d3 = korr["docs"]
    fehler = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: fehler.append(a[2]))
    kachel = FolderWidget(ziel, 0)
    qtbot.addWidget(kachel)
    kachel.pdf_dropped.connect(win.on_pdf_dropped_on_folder)
    win.verbinde_hierhin_kopieren(kachel)

    _markieren(view, "d1.pdf", "d2.pdf")
    mime = view.dokumente.mimeData(view.dokumente.selectedItems())
    assert [Path(u.toLocalFile()) for u in mime.urls()] == [d1, d2]

    # Strg: kopieren, die Originale bleiben
    ereignis = _drop(kachel, [Path(u.toLocalFile()) for u in mime.urls()], STRG)
    assert ereignis.dropAction() == Qt.DropAction.CopyAction
    assert sorted(p.name for p in ziel.iterdir()) == ["d1.pdf", "d2.pdf"]
    assert d1.exists() and d2.exists()

    # ohne Strg: verschieben, beide, ohne Fehlermeldung wegen der zweiten URL
    _markieren(view, "d1.pdf", "d3.pdf")
    mime = view.dokumente.mimeData(view.dokumente.selectedItems())
    _drop(kachel, [Path(u.toLocalFile()) for u in mime.urls()])
    assert not d1.exists() and not d3.exists()
    assert fehler == []
    assert (ziel / "d3.pdf").exists()


def test_ordner_links_oeffnen_verwirft_die_auswahl(korr):
    win, view, s1 = korr["win"], korr["view"], korr["s1"]
    win.left_tabs.setCurrentIndex(0)
    win.on_pdf_clicked(s1)
    win.left_tabs.setCurrentWidget(view)
    _markieren(view, "d1.pdf")
    view.dokument_menue(view.angezeigte_dokumente()[0]).actions()[1].trigger()
    assert win.left_tabs.currentIndex() == 0
    assert not win._korr_aktiv and win.selected_pdf is None and win.selected_pdfs == []
    assert Path(win.config.get_scan_folder()) == korr["docs"][0].parent

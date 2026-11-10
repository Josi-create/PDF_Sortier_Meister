"""Issue #218: Mehrfachauswahl verschieben bzw. "Umbenennen + Metadaten speichern" - jede Datei mit Namen.

Bisher bekam beim Verschieben mehrerer Dateien keine einen neuen Namen, und "Umbenennen +
Metadaten speichern" benannte nur die im Detail-Panel angezeigte um. Jetzt bekommt jede Datei
genau den Namen (und die Metadaten), die ihr das Detail-Panel vorbelegen wuerde; fuer die
angezeigte Datei gilt, was im Panel steht. Vorher zeigt eine Rueckfrage die Liste alt -> neu;
fehlende KI-Vorschlaege werden vorher abgerufen.

Fixtures wie in tests/test_auto_next_after_move_gui.py: Singletons auf tmp-Pfade (nie die echte
Konfiguration), Rueckfragen bejaht, Fehlerdialoge sind Testfehler.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QMimeData, QPointF, Qt, QTimer, QUrl
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from src.core.pdf_cache import LLMSuggestion, LLMSuggestionWorker, PDFAnalysisResult
from src.core import neuer_ordner
from src.gui import stapel_rueckfrage
from src.ml.classifier import Suggestion
from tests.test_auto_next_after_move_gui import (  # noqa: F401 - Fixtures
    _make_scan_folder,
    fresh_singletons,
    main_window,
)

KI_NAMEN = {
    "a.pdf": ("2026-01-15_Stadtwerke_Abrechnung.pdf", "Stadtwerke"),
    "b.pdf": ("2026-02-03_Finanzamt_Bescheid.pdf", "Finanzamt"),
    "c.pdf": ("2026-03-09_Krankenkasse_Beitrag.pdf", "Krankenkasse"),
}


def _ki(name: str) -> list[LLMSuggestion]:
    dateiname, korrespondent = KI_NAMEN[name]
    return [LLMSuggestion(
        filename=dateiname, confidence=0.9,
        metadata={"korrespondent": korrespondent, "subject": dateiname.split("_")[-1][:-4]},
    )]


def _analyse(pfad: Path, mit_ki: bool = True) -> PDFAnalysisResult:
    return PDFAnalysisResult(
        pdf_path=pfad,
        extracted_text=f"Schreiben von {KI_NAMEN[pfad.name][1]} zur {pfad.stem}",
        keywords=["schreiben"],
        file_modified=pfad.stat().st_mtime,
        llm_suggestions=_ki(pfad.name) if mit_ki else [],
        llm_fetched=mit_ki,
    )


@pytest.fixture
def stapel(main_window, fresh_singletons, monkeypatch):
    """Scan-Ordner mit a/b/c (analysiert, KI-Vorschlaege da) und ein Zielordner; Metadaten-Schreiben protokolliert."""
    tmp = fresh_singletons["tmp_path"]
    scan = _make_scan_folder(tmp, ["a.pdf", "b.pdf", "c.pdf"])
    ziel = tmp / "Ziel"
    ziel.mkdir()
    a, b, c = (scan / n for n in ("a.pdf", "b.pdf", "c.pdf"))
    for p in (a, b, c):
        main_window.pdf_cache._cache[p] = _analyse(p)
    main_window._navigate_to_folder(scan)
    geschrieben: list[tuple[Path, dict]] = []
    monkeypatch.setattr(main_window, "_write_pdf_metadata_async",
                        lambda p, n, k, m: geschrieben.append((p, dict(m))))
    monkeypatch.setattr(main_window, "_write_pdf_metadata",
                        lambda p, n, k, m: geschrieben.append((p, dict(m))))
    fragen: list[tuple] = []

    def frage(parent, titel, text, zeilen, ja_text, nur_text):
        fragen.append((titel, text, list(zeilen), ja_text, nur_text))
        return stapel_rueckfrage.UMBENENNEN

    monkeypatch.setattr(stapel_rueckfrage, "frage", frage)
    return {"win": main_window, "scan": scan, "ziel": ziel, "a": a, "b": b, "c": c,
            "geschrieben": geschrieben, "fragen": fragen}


def _panel_vorbelegung(win, pfad: Path) -> tuple[str, dict]:
    """Was das sichtbare Detail-Panel dieser Datei als Namen und Metadaten vorbelegt."""
    win.on_pdf_clicked(pfad)
    assert win.detail_panel.get_current_pdf() == pfad
    return win.detail_panel.get_new_name(), win.detail_panel.get_metadata()


def _markieren(win, *pfade: Path) -> None:
    win._clear_selection()  # ein erneuter Klick auf die aktive PDF hebt sie sonst auf
    win.on_pdf_clicked(pfade[0])
    for p in pfade[1:]:
        win.on_pdf_ctrl_clicked(p)
    assert set(win.selected_pdfs) == set(pfade)


def test_verschieben_gibt_jeder_datei_den_namen_des_detail_panels(stapel):
    win, a, b, c, ziel = stapel["win"], stapel["a"], stapel["b"], stapel["c"], stapel["ziel"]
    erwartet = {p: _panel_vorbelegung(win, p) for p in (a, b)}
    assert all(name and name != p.name for p, (name, _m) in erwartet.items())
    _markieren(win, a, b)

    win.on_suggestion_clicked(ziel)

    assert sorted(p.name for p in ziel.iterdir()) == sorted(n for n, _m in erwartet.values())
    assert not a.exists() and not b.exists() and c.exists()
    # Rueckfrage mit der Liste alt -> neu und den drei Knoepfen
    (titel, text, zeilen, ja_text, nur_text), = stapel["fragen"]
    assert zeilen == [(a.name, erwartet[a][0]), (b.name, erwartet[b][0])]
    assert (ja_text, nur_text) == ("Verschieben und umbenennen", "Nur verschieben")
    assert "2 Dateien" in text
    # Metadaten wie im Panel, je Datei in die verschobene PDF
    meta = {p.name: m for p, m in stapel["geschrieben"]}
    for p in (a, b):
        assert meta[erwartet[p][0]]["korrespondent"] == erwartet[p][1]["korrespondent"]
    # Suchindex kennt den neuen Pfad
    assert win.db.get_pdf_by_path(str(ziel / erwartet[a][0])) is not None
    # ein Rueckgaengig holt beide zurueck
    win.undo_last_action()
    # ... mit den alten Namen
    assert sorted(p.name for p in stapel["scan"].iterdir()) == ["a.pdf", "b.pdf", "c.pdf"]
    assert not list(ziel.iterdir())


def test_fuer_die_angezeigte_datei_gilt_der_name_im_panel(stapel):
    win, a, b, ziel = stapel["win"], stapel["a"], stapel["b"], stapel["ziel"]
    name_a, _m = _panel_vorbelegung(win, a)
    _markieren(win, a, b)
    assert win.detail_panel.get_current_pdf() == b  # die zuletzt angeklickte ist die aktive
    win.detail_panel.name_input.setText("Von Hand korrigiert")

    win.on_suggestion_clicked(ziel)

    assert sorted(p.name for p in ziel.iterdir()) == sorted([name_a, "Von Hand korrigiert.pdf"])


def test_nur_verschieben_behaelt_die_namen(stapel, monkeypatch):
    win, a, b, ziel = stapel["win"], stapel["a"], stapel["b"], stapel["ziel"]
    monkeypatch.setattr(stapel_rueckfrage, "frage", lambda *a_, **k: stapel_rueckfrage.NUR_VERSCHIEBEN)
    _markieren(win, a, b)

    win.on_suggestion_clicked(ziel)

    assert sorted(p.name for p in ziel.iterdir()) == ["a.pdf", "b.pdf"]
    assert stapel["geschrieben"] == []  # "Nur verschieben": keine Metadaten
    assert win.db.get_pdf_by_path(str(ziel / "a.pdf")) is not None  # Suchindex trotzdem nachgefuehrt


def test_abbrechen_laesst_alles_liegen(stapel, monkeypatch):
    win, a, b, ziel = stapel["win"], stapel["a"], stapel["b"], stapel["ziel"]
    monkeypatch.setattr(stapel_rueckfrage, "frage", lambda *a_, **k: None)
    _markieren(win, a, b)

    win.on_suggestion_clicked(ziel)

    assert a.exists() and b.exists() and not list(ziel.iterdir())
    assert set(win.selected_pdfs) == {a, b}


def test_ziehen_der_auswahl_benennt_um_ohne_doppelte_versuche(stapel, monkeypatch, qtbot):
    """Die Rueckfrage hat eine eigene Ereignisschleife; die uebrigen Dateien desselben Drops
    duerfen danach nicht noch einmal einzeln verschoben werden (Fehlermeldung "nicht gefunden")."""
    win, a, b, ziel = stapel["win"], stapel["a"], stapel["b"], stapel["ziel"]
    erwartet = {_panel_vorbelegung(win, p)[0] for p in (a, b)}
    warnungen = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **k: warnungen.append(args[2]))
    gefragt = []

    def frage_mit_ereignisschleife(*args, **kwargs):
        gefragt.append(1)
        qtbot.wait(30)  # wie der modale Dialog: Ereignisse (auch 0-ms-Timer) laufen ab
        return stapel_rueckfrage.UMBENENNEN

    monkeypatch.setattr(stapel_rueckfrage, "frage", frage_mit_ereignisschleife)
    _markieren(win, a, b)

    # Ein Drop mehrerer Dateien meldet jede einzeln (so ruft FolderWidget.dropEvent auf)
    win.on_pdf_dropped_on_folder(a, ziel)
    win.on_pdf_dropped_on_folder(b, ziel)

    assert {p.name for p in ziel.iterdir()} == erwartet
    assert gefragt == [1] and warnungen == []


def test_umbenennen_und_speichern_gilt_fuer_alle_markierten(stapel):
    win, a, b, c, scan = stapel["win"], stapel["a"], stapel["b"], stapel["c"], stapel["scan"]
    erwartet = {p: _panel_vorbelegung(win, p)[0] for p in (a, b)}
    _markieren(win, a, b)

    win.detail_panel.rename_and_save_metadata_requested.emit()

    assert sorted(p.name for p in scan.iterdir()) == sorted([erwartet[a], erwartet[b], "c.pdf"])
    assert {p.name for p, _m in stapel["geschrieben"]} == {erwartet[a], erwartet[b]}
    (titel, _text, zeilen, ja_text, nur_text), = stapel["fragen"]
    assert zeilen == [(a.name, erwartet[a]), (b.name, erwartet[b])]
    assert (ja_text, nur_text) == ("Umbenennen und speichern", None)
    # Kacheln und Auswahl zeigen die neuen Namen; das Panel die angezeigte Datei
    kacheln = {w.pdf_path.name for w in win.pdf_widgets}
    assert {erwartet[a], erwartet[b], "c.pdf"} == kacheln
    assert set(win.selected_pdfs) == {scan / erwartet[a], scan / erwartet[b]}
    assert win.detail_panel.get_current_pdf() == scan / erwartet[b]

    # Ein Rueckgaengig benennt beide zurueck
    win.undo_last_action()
    assert sorted(p.name for p in scan.iterdir()) == ["a.pdf", "b.pdf", "c.pdf"]
    assert {w.pdf_path.name for w in win.pdf_widgets} == {"a.pdf", "b.pdf", "c.pdf"}


def test_einzelne_datei_bleibt_beim_alten_weg(stapel):
    """Ohne Mehrfachauswahl: "Umbenennen + Metadaten speichern" wie bisher, ohne Liste."""
    win, a, scan = stapel["win"], stapel["a"], stapel["scan"]
    name_a, _m = _panel_vorbelegung(win, a)

    win.detail_panel.rename_and_save_metadata_requested.emit()

    assert (scan / name_a).exists() and stapel["fragen"] == []


def test_wartet_auf_fehlende_ki_vorschlaege(stapel, monkeypatch, qtbot):
    win, a, b, ziel = stapel["win"], stapel["a"], stapel["b"], stapel["ziel"]
    cache = win.pdf_cache
    for p in (a, b):  # KI-Vorschlaege fehlen noch
        cache._cache[p] = _analyse(p, mit_ki=False)
    monkeypatch.setattr(win.hybrid_classifier, "is_llm_available", lambda: True)
    offen: set[Path] = set()
    vorgezogen = []

    def vorziehen(pfad, mit_ki, analysiert=None):
        vorgezogen.append((pfad, mit_ki))
        offen.add(pfad)

    def ki_kommt():  # die KI antwortet, waehrend die Fortschrittsanzeige wartet
        for p in sorted(offen):
            cache.update_llm_suggestions(p, _ki(p.name))
        offen.clear()

    monkeypatch.setattr(cache, "vorziehen", vorziehen)
    monkeypatch.setattr(cache, "ki_offen", lambda p: p in offen)
    _markieren(win, a, b)
    sah_fortschritt = []
    QTimer.singleShot(200, lambda: sah_fortschritt.append(
        isinstance(QApplication.activeModalWidget(), QProgressDialog)))
    QTimer.singleShot(400, ki_kommt)

    win.on_suggestion_clicked(ziel)

    assert sorted(vorgezogen) == [(a, True), (b, True)]
    assert sah_fortschritt == [True]
    namen = sorted(p.name for p in ziel.iterdir())
    assert namen == sorted([KI_NAMEN["a.pdf"][0], KI_NAMEN["b.pdf"][0]]) or all(
        n not in ("a.pdf", "b.pdf") for n in namen)  # KI-Name, ggf. vom Panel angepasst (#113)


def test_nicht_mehr_warten_faehrt_ohne_ki_fort(stapel, monkeypatch):
    win, a, b, ziel = stapel["win"], stapel["a"], stapel["b"], stapel["ziel"]
    cache = win.pdf_cache
    for p in (a, b):
        cache._cache[p] = _analyse(p, mit_ki=False)
    monkeypatch.setattr(win.hybrid_classifier, "is_llm_available", lambda: True)
    monkeypatch.setattr(cache, "vorziehen", lambda *args, **kwargs: None)
    monkeypatch.setattr(cache, "ki_offen", lambda p: True)  # die KI antwortet nie

    def abbrechen():
        for dialog in win.findChildren(QProgressDialog):
            dialog.cancel()

    QTimer.singleShot(300, abbrechen)
    _markieren(win, a, b)

    win.on_suggestion_clicked(ziel)

    assert len(stapel["fragen"]) == 1  # Rueckfrage kommt trotzdem
    assert len(list(ziel.iterdir())) == 2 and not a.exists() and not b.exists()


# --------------------------------------------------------------------- #
# Cache: dringende KI-Anfragen (Issue #218)
# --------------------------------------------------------------------- #


class _FakeLLMWorker:
    def __init__(self):
        self.aufgaben: list[tuple[Path, int]] = []
        self.aktuell = None

    def add_task(self, pdf_path, analysis_result, priority=5):
        self.aufgaben.append((pdf_path, priority))

    def get_current_pdf(self):
        return self.aktuell

    # Beim Schliessen des Fensters haelt der Cache seine Worker an
    def isRunning(self):
        return False

    def stop(self):
        pass

    def wait(self, *args):
        return True


def test_cache_vorziehen_reiht_die_ki_dringend_ein(main_window, fresh_singletons, monkeypatch):
    cache = main_window.pdf_cache
    tmp = fresh_singletons["tmp_path"]
    p = tmp / "a.pdf"
    p.write_bytes(b"%PDF-1.4\n%%EOF\n")
    cache._cache[p] = _analyse(p, mit_ki=False)
    fake = _FakeLLMWorker()
    monkeypatch.setattr(cache, "start_llm_worker", lambda: None)
    monkeypatch.setattr(cache, "_llm_worker", fake)

    assert cache._request_llm_suggestions(p, cache._cache[p]) is True  # Vorabfrage, Prioritaet 10
    analysiert = []
    cache.vorziehen(p, True, analysiert=analysiert.append)

    assert analysiert and analysiert[0].pdf_path == p  # Analyse lag schon vor: sofort
    assert fake.aufgaben == [(p, 10), (p, 1)]  # dringend ueberholt die wartende Vorabfrage
    assert cache.ki_offen(p)
    # Arbeitet die KI gerade an genau dieser PDF, wird sie nicht noch einmal eingereiht
    fake.aktuell = p
    cache.vorziehen(p, True)
    assert fake.aufgaben == [(p, 10), (p, 1)]
    cache._on_llm_suggestions_complete(p, _ki("a.pdf"))
    assert not cache.ki_offen(p) and cache.get_llm_suggestions(p)


def test_cache_dringend_auch_ohne_vorabfrage_nach_der_analyse(main_window, fresh_singletons, monkeypatch):
    cache = main_window.pdf_cache
    tmp = fresh_singletons["tmp_path"]
    p, q = tmp / "a.pdf", tmp / "b.pdf"
    for pfad in (p, q):
        pfad.write_bytes(b"%PDF-1.4\n%%EOF\n")
    fake = _FakeLLMWorker()
    monkeypatch.setattr(cache, "start_llm_worker", lambda: None)
    monkeypatch.setattr(cache, "_llm_worker", fake)
    angefragt = []
    monkeypatch.setattr(cache, "request_analysis",
                        lambda pfad, callback=None, urgent=False: angefragt.append((pfad, urgent)))
    cache.set_llm_precache_enabled(False)

    cache.vorziehen(p, True)
    assert angefragt == [(p, True)] and fake.aufgaben == []
    cache._on_analysis_complete(p, _analyse(p, mit_ki=False))
    cache._on_analysis_complete(q, _analyse(q, mit_ki=False))  # nicht dringend, Vorabfrage aus

    assert fake.aufgaben == [(p, 1)]


def test_llm_worker_ueberholt_wartende_anfrage(qtbot):
    worker = LLMSuggestionWorker()
    p = Path("C:/x/a.pdf")
    ergebnis = PDFAnalysisResult(pdf_path=p)
    worker.add_task(p, ergebnis, priority=10)
    worker.add_task(p, ergebnis, priority=1)
    worker.add_task(p, ergebnis, priority=10)  # schon dringender eingereiht: nichts Neues

    assert worker._queued == {p: 1} and worker._queue.qsize() == 2


def test_druecken_auf_die_mehrfachauswahl_haelt_sie_zum_ziehen(stapel, qtbot):
    """Live-Test: 4 PDFs markiert und gezogen - nur eine kam an, weil schon das Druecken
    zum Ziehen die Auswahl aufhob. Jetzt wirkt der Klick erst beim Loslassen ohne Ziehen."""
    from PyQt6.QtCore import QPoint, Qt

    win, a, b = stapel["win"], stapel["a"], stapel["b"]
    _markieren(win, a, b)
    kachel = win._pdf_widget_for(a)

    qtbot.mousePress(kachel, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert set(win.selected_pdfs) == {a, b}  # Auswahl steht noch: das Ziehen nimmt beide mit
    qtbot.mouseRelease(kachel, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert win.selected_pdfs == [] and win.selected_pdf == a  # nicht gezogen: wie ein Klick


def test_ziehen_einer_einzelnen_datei_benennt_um(stapel):
    win, a, ziel = stapel["win"], stapel["a"], stapel["ziel"]
    name_a, _m = _panel_vorbelegung(win, a)

    win.on_pdf_dropped_on_folder(a, ziel)

    assert [p.name for p in ziel.iterdir()] == [name_a]
    (titel, text, zeilen, _ja, _nur), = stapel["fragen"]
    assert titel == "Datei verschieben" and zeilen == [("a.pdf", name_a)]


def test_ziehen_auf_einen_neuen_ordner_legt_ihn_an(stapel):
    """Live-Test: vorgeschlagener neuer Unterordner ("➕ neu: Gebaeudeverwaltung") per Ziehen."""
    win, a, b, ziel = stapel["win"], stapel["a"], stapel["b"], stapel["ziel"]
    neu = ziel / "Gebäudeverwaltung"
    erwartet = {_panel_vorbelegung(win, p)[0] for p in (a, b)}
    _markieren(win, a, b)
    # Durch die echte Vorschlagskachel: vorher war ihr pdf_dropped bei neuen Ordnern nicht
    # verbunden, der Drop verpuffte (Live-Test)
    win.display_suggestions([Suggestion(neu, neu.name, 0.9, "neu", relative_path="Ziel/Gebäudeverwaltung",
                                        new_source=neuer_ordner.QUELLE_JAHR)])
    kachel, = win.suggestion_widgets
    assert kachel.neu and kachel.folder_path == neu
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(a)), QUrl.fromLocalFile(str(b))])
    kachel.dropEvent(QDropEvent(QPointF(5, 5), Qt.DropAction.MoveAction, mime,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))

    assert neu.is_dir() and {p.name for p in neu.iterdir()} == erwartet
    (_titel, text, _z, _ja, _nur), = stapel["fragen"]
    assert "neu angelegt" in text
    win.undo_last_action()  # Rueckgaengig: Dateien zurueck, leerer neuer Ordner wieder weg
    assert a.exists() and b.exists() and not neu.exists()


def test_abbrechen_beim_neuen_ordner_legt_nichts_an(stapel, monkeypatch):
    win, a, ziel = stapel["win"], stapel["a"], stapel["ziel"]
    monkeypatch.setattr(stapel_rueckfrage, "frage", lambda *a_, **k: None)
    win.on_pdf_clicked(a)

    win.on_pdf_dropped_on_folder(a, ziel / "Neu")

    assert a.exists() and not (ziel / "Neu").exists()

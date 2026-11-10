"""Vorschlags-Knoepfe im Chat (Baustein 2, docs/CHAT_MCP_PLAN.md 5.2/5.3).

ChatView: Knoepfe je Vorschlag mit Text, Tooltip und Signal; erledigte Knoepfe
gesperrt; Quellen mit „Im Ordner anzeigen“. MainWindow: Umbenennen, Metadaten
und Verschieben eines anderen Dokuments laufen ueber die vorhandenen Ablaeufe.
Fixtures des Hauptfensters aus tests/test_auto_next_after_move_gui.py (tmp-Config,
bestaetigte Rueckfragen).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QPushButton

from src.gui.chat_view import ChatView
from src.rag.rag_controller import RAGResponse
from src.rag.retrieval import RetrievedDoc
from src.rag.werkzeug_kern import Vorschlag
from src.utils.config import ChatConfig
from tests import helfer_suche as h
from tests.test_auto_next_after_move_gui import (  # noqa: F401 - Fixtures werden importiert
    _make_scan_folder,
    _prime_cache,
    fresh_singletons,
    main_window,
)


class _StubLLM:
    llm_provider = None

    def is_llm_available(self) -> bool:
        return False


def _view(qtbot) -> ChatView:
    view = ChatView(db=None, hybrid_classifier=_StubLLM(), chat_config=ChatConfig(), kompakt=True)
    qtbot.addWidget(view)
    return view


def _antwort(vorschlaege, ordner: str = "", anzeige: str = "", begruendung: str = "") -> RAGResponse:
    return RAGResponse(answer_text="Vorschläge stehen unten.", used_llm=True, vorschlaege=list(vorschlaege),
                       ordner_vorschlag=ordner, ordner_anzeige=anzeige, ordner_begruendung=begruendung)


def _knopf(view: ChatView, art: str, quelle: str | None = None) -> QPushButton:
    passende = [k for k in view.vorschlag_knoepfe() if k.property("vorschlag_art") == art
                and (quelle is None or k.property("vorschlag_quelle") == quelle)]
    assert len(passende) == 1, [k.text() for k in view.vorschlag_knoepfe()]
    return passende[0]


# --------------------------------------------------------------------------- ChatView


def test_knoepfe_fuer_den_bezug_mit_text_tooltip_und_signal(qtbot, tmp_path):
    view = _view(qtbot)
    bezug = tmp_path / "Scan" / "Neu.pdf"
    ordner = str(tmp_path / "Ablage" / "Energie")
    view.set_bezug(bezug)
    belegt = []
    view.ordner_belegt.connect(lambda p, g: belegt.append((p, g)))
    view._zeige_antwort(_antwort([
        Vorschlag("verschieben", str(bezug), ziel=ordner, anzeige="Ablage/Energie", begruendung="Stadtwerke"),
        Vorschlag("umbenennen", str(bezug), name="2024 Strom.pdf", begruendung="Jahr und Absender"),
        Vorschlag("metadaten", str(bezug), felder={"steuerjahr": "2024"}, begruendung="steht im Briefkopf"),
    ], ordner=ordner, anzeige="Ablage/Energie", begruendung="Stadtwerke"))

    # Der Verschiebe-Vorschlag fuer den Bezug ist der eine Knopf aus ordner_vorschlag - nicht doppelt
    assert [k.text() for k in view.vorschlag_knoepfe()] == [
        "📁 Nach Ablage/Energie verschieben", "✏️ Umbenennen in 2024 Strom.pdf",
        "🏷️ Metadaten übernehmen: Steuerjahr 2024"]
    assert belegt == [(ordner, "Stadtwerke")]
    umbenennen = _knopf(view, "umbenennen")
    assert str(bezug) in umbenennen.toolTip() and "Jahr und Absender" in umbenennen.toolTip()
    metadaten = _knopf(view, "metadaten")
    assert str(bezug) in metadaten.toolTip() and "steht im Briefkopf" in metadaten.toolTip()

    with qtbot.waitSignal(view.verschieben_requested, timeout=1000) as blocker:
        _knopf(view, "verschieben").click()
    assert blocker.args == [ordner, str(bezug)]
    with qtbot.waitSignal(view.umbenennen_requested, timeout=1000) as blocker:
        umbenennen.click()
    assert blocker.args == [str(bezug), "2024 Strom.pdf"]
    with qtbot.waitSignal(view.metadaten_requested, timeout=1000) as blocker:
        metadaten.click()
    assert blocker.args == [str(bezug), {"steuerjahr": "2024"}]


def test_anderes_dokument_traegt_seinen_namen_und_seinen_pfad_im_signal(qtbot, tmp_path):
    view = _view(qtbot)
    view.set_bezug(tmp_path / "Scan" / "Neu.pdf")
    alt = str(tmp_path / "Ablage" / "Alt.pdf")
    ziel = str(tmp_path / "Ablage" / "Telekom")
    view._zeige_antwort(_antwort([
        Vorschlag("verschieben", alt, ziel=ziel, anzeige="Ablage/Telekom", begruendung="Telekom-Rechnung"),
    ]))
    knopf = _knopf(view, "verschieben", alt)
    assert knopf.text() == "📁 Alt.pdf: Nach Ablage/Telekom verschieben"
    assert alt in knopf.toolTip() and ziel in knopf.toolTip() and "Telekom-Rechnung" in knopf.toolTip()
    with qtbot.waitSignal(view.verschieben_requested, timeout=1000) as blocker:
        knopf.click()
    assert blocker.args == [ziel, alt]


def test_ohne_bezug_kein_bezug_knopf_aber_vorschlaege(qtbot, tmp_path):
    view = _view(qtbot)
    datei = str(tmp_path / "Scan" / "X.pdf")
    view._zeige_antwort(_antwort([Vorschlag("umbenennen", datei, name="Y.pdf")],
                                 ordner=str(tmp_path / "Ablage"), anzeige="Ablage"))
    assert [k.text() for k in view.vorschlag_knoepfe()] == ["✏️ X.pdf: Umbenennen in Y.pdf"]
    view._zeige_antwort(_antwort([]))  # keine Vorschlaege: kein weiterer Block
    assert len(view.vorschlag_knoepfe()) == 1


def test_langer_text_wird_gekuerzt_tooltip_bleibt_voll(qtbot, tmp_path):
    view = _view(qtbot)
    bezug = tmp_path / "Neu.pdf"
    view.set_bezug(bezug)
    felder = {"korrespondent": "Stadtwerke Musterstadt Energie und Wasser GmbH", "steuerjahr": "2024",
              "betrag": "1234.56"}
    view._zeige_antwort(_antwort([Vorschlag("metadaten", str(bezug), felder=felder)]))
    knopf = _knopf(view, "metadaten")
    assert len(knopf.text()) <= 60 and knopf.text().endswith("…")
    assert "Korrespondent Stadtwerke Musterstadt Energie und Wasser GmbH, Steuerjahr 2024, Betrag 1234.56" \
        in knopf.toolTip()


def test_erledigt_sperrt_den_knopf_und_zieht_die_quelle_nach(qtbot, tmp_path):
    view = _view(qtbot)
    bezug = tmp_path / "Scan" / "Neu.pdf"
    view.set_bezug(bezug)
    view._zeige_antwort(_antwort([
        Vorschlag("umbenennen", str(bezug), name="Strom.pdf"),
        Vorschlag("metadaten", str(bezug), felder={"steuerjahr": "2024"}),
    ]))
    neu = str(tmp_path / "Scan" / "Strom.pdf")
    view.vorschlag_erledigt("umbenennen", str(bezug), neu)

    umbenennen = _knopf(view, "umbenennen")
    assert not umbenennen.isEnabled() and umbenennen.text().startswith("✓ ")
    assert "(erledigt)" in umbenennen.toolTip()
    metadaten = _knopf(view, "metadaten")
    assert metadaten.isEnabled() and metadaten.property("vorschlag_quelle") == neu
    with qtbot.waitSignal(view.metadaten_requested, timeout=1000) as blocker:
        metadaten.click()
    assert blocker.args[0] == neu


def test_quellen_im_ordner_anzeigen(qtbot, tmp_path):
    view = _view(qtbot)
    da = h.pdf_mit_text(tmp_path / "Da.pdf", ["x"])
    docs = [
        RetrievedDoc(index=1, file_path=str(da), filename="Da.pdf", text_snippet="", rank=0,
                     extra={"status": "zitiert"}),
        RetrievedDoc(index=2, file_path=str(tmp_path / "Weg.pdf"), filename="Weg.pdf", text_snippet="", rank=1,
                     extra={"status": "zitiert"}),
        RetrievedDoc(index=3, file_path="mail://gmx/INBOX/7", filename="Mail", text_snippet="", rank=2,
                     extra={"status": "gefunden"}),
    ]
    view._populate_sources(docs)
    eintraege = [view.sources_list.item(i) for i in range(view.sources_list.count())]

    assert view.quellen_menue(eintraege[0]) is None  # Kopfzeile "Zitiert"
    menue = view.quellen_menue(eintraege[1])
    aktionen = {a.text(): a for a in menue.actions()}
    assert set(aktionen) == {"Öffnen", "📂 Im Ordner anzeigen"}
    with qtbot.waitSignal(view.im_ordner_anzeigen_requested, timeout=1000) as blocker:
        aktionen["📂 Im Ordner anzeigen"].trigger()
    assert blocker.args == [da]
    assert [a.text() for a in view.quellen_menue(eintraege[2]).actions()] == ["Öffnen"]  # Datei fehlt
    assert [a.text() for a in view.quellen_menue(eintraege[4]).actions()] == ["Öffnen"]  # Mail


# --------------------------------------------------------------------------- MainWindow


def _bezug_mit_antwort(fenster, pfad: Path, vorschlaege) -> None:
    fenster.on_pdf_clicked(pfad)
    fenster.show_chat_tab()
    fenster.chat_view.set_bezug(pfad)
    fenster.chat_view._zeige_antwort(_antwort(vorschlaege))


def test_umbenennen_aus_dem_chat(main_window, fresh_singletons):
    scan = _make_scan_folder(fresh_singletons["tmp_path"], ["a.pdf", "b.pdf"])
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [scan / "a.pdf", scan / "b.pdf"])
    _bezug_mit_antwort(main_window, scan / "a.pdf", [
        Vorschlag("umbenennen", str(scan / "a.pdf"), name="2024 Strom.pdf"),
        Vorschlag("verschieben", str(scan / "a.pdf"), ziel=str(scan), anzeige="Scan"),
    ])

    _knopf(main_window.chat_view, "umbenennen").click()

    neu = scan / "2024 Strom.pdf"
    assert neu.exists() and not (scan / "a.pdf").exists()
    assert main_window._undo_stack[-1]["type"] == "rename"
    assert main_window._undo_stack[-1]["new_path"] == neu
    assert main_window._pdf_widget_for(neu) is not None
    assert main_window.chat_view.bezug == neu
    assert not _knopf(main_window.chat_view, "umbenennen").isEnabled()
    assert _knopf(main_window.chat_view, "verschieben").property("vorschlag_quelle") == str(neu)
    assert "Umbenannt zu: 2024 Strom.pdf" in main_window.statusbar.currentMessage()


def test_metadaten_aus_dem_chat(main_window, fresh_singletons):
    from src.core.pdf_metadata import read_metadata

    tmp_path = fresh_singletons["tmp_path"]
    scan = tmp_path / "Scan"
    scan.mkdir()
    pdf = h.pdf_mit_text(scan / "a.pdf", ["Stadtwerke Musterstadt Rechnung"])
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [pdf])
    felder = {"korrespondent": "Stadtwerke Musterstadt", "kategorie": "Rechnung", "steuerjahr": "2024",
              "betrag": "480.00", "datum": "2024-03-01"}
    _bezug_mit_antwort(main_window, pdf, [Vorschlag("metadaten", str(pdf), felder=felder)])

    _knopf(main_window.chat_view, "metadaten").click()

    meta = read_metadata(pdf)
    assert meta.korrespondent == "Stadtwerke Musterstadt" and meta.subject == "Rechnung"
    assert meta.steuerjahr == "2024" and meta.betrag_brutto == "480.00" and meta.buchungsdatum == "2024-03-01"
    assert not _knopf(main_window.chat_view, "metadaten").isEnabled()
    assert "Metadaten in 'a.pdf' gespeichert" in main_window.statusbar.currentMessage()


def test_verschieben_eines_anderen_dokuments_behaelt_die_auswahl(main_window, fresh_singletons, monkeypatch):
    # Seit Issue #218 bietet die Rueckfrage auch das Umbenennen an; hier: nur verschieben
    from src.gui import stapel_rueckfrage
    monkeypatch.setattr(stapel_rueckfrage, "frage", lambda *a, **k: stapel_rueckfrage.NUR_VERSCHIEBEN)
    tmp_path = fresh_singletons["tmp_path"]
    scan = _make_scan_folder(tmp_path, ["a.pdf", "b.pdf"])
    ziel = tmp_path / "Ablage" / "Energie"
    ziel.mkdir(parents=True)
    main_window.folder_manager.add_folder(tmp_path / "Ablage")
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [scan / "a.pdf", scan / "b.pdf"])
    _bezug_mit_antwort(main_window, scan / "a.pdf", [
        Vorschlag("verschieben", str(scan / "b.pdf"), ziel=str(ziel), anzeige="Ablage/Energie"),
    ])

    _knopf(main_window.chat_view, "verschieben").click()

    assert (ziel / "b.pdf").exists() and not (scan / "b.pdf").exists()
    assert (scan / "a.pdf").exists() and main_window.selected_pdf == scan / "a.pdf"
    assert main_window.chat_view.bezug == scan / "a.pdf"
    assert not _knopf(main_window.chat_view, "verschieben").isEnabled()
    assert main_window._undo_stack[-1]["type"] == "move"


def test_verschieben_signal_ohne_quelle_meint_den_bezug(main_window, fresh_singletons):
    """Leere Quelle (wie bisher nur der Ordner): das Bezugsdokument wird verschoben."""
    tmp_path = fresh_singletons["tmp_path"]
    scan = _make_scan_folder(tmp_path, ["a.pdf", "b.pdf"])
    ziel = tmp_path / "Ablage" / "Energie"
    ziel.mkdir(parents=True)
    main_window.folder_manager.add_folder(tmp_path / "Ablage")
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [scan / "a.pdf", scan / "b.pdf"])
    main_window.on_pdf_clicked(scan / "a.pdf")
    main_window.show_chat_tab()

    main_window.chat_view.verschieben_requested.emit(str(ziel), "")

    assert (ziel / "a.pdf").exists() and main_window.chat_view.bezug is None


def test_quelle_im_ordner_anzeigen_aus_dem_chat(main_window, fresh_singletons):
    scan = _make_scan_folder(fresh_singletons["tmp_path"], ["a.pdf", "b.pdf"])
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [scan / "a.pdf", scan / "b.pdf"])
    main_window.show_chat_tab()

    main_window.chat_view.im_ordner_anzeigen_requested.emit(scan / "b.pdf")

    assert main_window.left_tabs.currentIndex() == 0
    assert main_window.selected_pdf == scan / "b.pdf"

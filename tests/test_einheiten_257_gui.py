"""Einheit/Verbrauchsstelle an der Oberflaeche (Issue #257): Feld "Einheit" im Detail-Panel,
Lernen beim Ablegen, gelernter Ordner oben in den Vorschlaegen.

Fixtures aus tests/test_auto_next_after_move_gui.py (tmp-Config, Dialoge bestaetigt), kein
Netz/LLM (KI-Antworten liegen direkt im Cache). Anschriften und Zaehlernummern sind erfunden.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.core.pdf_metadata import PDFMetadata, read_metadata, write_metadata
from src.ml.classifier import Suggestion
from tests import helfer_suche as h
from tests.test_auto_next_after_move_gui import (  # noqa: F401 - Fixtures
    _make_scan_folder,
    _prime_cache,
    fresh_singletons,
    main_window,
)
from tests.test_schlagwoerter_231_gui import panel_ohne_threads  # noqa: F401 - Fixture


def _ki(**metadata):
    return SimpleNamespace(name="2026-03-12_Stadtwerke_Abschlag.pdf", filename="2026-03-12_Stadtwerke_Abschlag.pdf",
                           reason="KI", confidence=0.9, source="llm", metadata=metadata)


# --------------------------------------------------------------------------- Detail-Panel

def test_panel_zeigt_einheit_der_ki_und_der_pdf(qtbot, tmp_path, panel_ohne_threads):
    DetailPanel = panel_ohne_threads
    pdf = h.pdf_mit_text(tmp_path / "scan.pdf", ["Stromrechnung"])
    panel = DetailPanel()
    qtbot.addWidget(panel)

    panel.set_pdf(pdf_path=pdf, suggestions=[_ki(einheit="Musterweg 5 Whg 2", einheit_kennung="70471122")],
                  extracted_text="Stromrechnung", keywords=["rechnung"])
    feld = panel._metadata_inputs["einheit"]
    assert feld.text() == "Musterweg 5 Whg 2"
    assert panel.get_metadata()["einheit"] == "Musterweg 5 Whg 2"
    assert "einheit_kennung" not in panel.get_metadata()        # die Kennung ist kein sichtbares Feld

    # in der PDF gespeichert: wird wieder gelesen und gilt als gespeichert
    assert write_metadata(pdf, PDFMetadata(einheit="Musterweg 5 Whg 1"))
    panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="Stromrechnung", keywords=[])
    panel._on_pdf_metadata_read(pdf, read_metadata(pdf))
    assert feld.text() == "Musterweg 5 Whg 1" and panel._metadata_source == "pdf"


# --------------------------------------------------------------------------- Hauptfenster

def _ablage(main_window, tmp: Path, *folders) -> Path:
    ablage = tmp / "Ablage"
    for f in folders:
        (ablage / f).mkdir(parents=True, exist_ok=True)
    main_window.config.add_target_folder(ablage)
    main_window.folder_manager.add_folder(ablage)
    main_window.load_folders()
    return ablage


def _select(main_window, scan: Path, name: str) -> Path:
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [w.pdf_path for w in main_window.pdf_widgets])
    pdf = scan / name
    main_window.on_pdf_clicked(pdf)
    main_window.detail_panel.name_input.setText(name)  # Name bleibt, nur verschieben
    return pdf


def test_ablegen_lernt_die_einheit_und_schlaegt_ihren_ordner_oben_vor(main_window, fresh_singletons, monkeypatch):
    tmp = fresh_singletons["tmp_path"]
    scan = _make_scan_folder(tmp, ["a.pdf", "b.pdf", "c.pdf"])
    ablage = _ablage(main_window, tmp, "Haus/Whg 1/Strom", "Haus/Whg 2/Strom")
    whg1, whg2 = ablage / "Haus" / "Whg 1" / "Strom", ablage / "Haus" / "Whg 2" / "Strom"

    antworten = {
        "a.pdf": _ki(einheit="Musterweg 5 Whg 2", einheit_kennung="70 4711 22"),
        "b.pdf": _ki(einheit="Musterweg 5, Whg. 2"),          # andere Schreibweise, keine Kennung
        "c.pdf": _ki(korrespondent="Stadtwerke Musterstadt"),  # die KI nennt keine Einheit
    }
    monkeypatch.setattr(main_window.pdf_cache, "get_llm_suggestions",
                        lambda p: [antworten[Path(p).name]] if Path(p).name in antworten else [])

    # 1. Dokument der Wohnung 2 ablegen: Einheit und Zaehlernummer werden mit dem Ordner gelernt
    _select(main_window, scan, "a.pdf")
    assert main_window.detail_panel._metadata_inputs["einheit"].text() == "Musterweg 5 Whg 2"
    main_window.on_suggestion_clicked(whg2)
    assert (whg2 / "a.pdf").exists()
    gelernt = main_window.db.get_einheit_zuordnungen()
    assert [(z["einheit"], z["kennung"], z["target_folder"]) for z in gelernt] == [
        ("Musterweg 5 Whg 2", "70 4711 22", str(whg2))]
    assert main_window._einheiten_fuer_prompt()[0]["ablageort"] == "Ablage/Haus/Whg 2/Strom"

    # 2. Naechstes Dokument derselben Einheit: ihr Ordner steht vor dem der Nachbarwohnung
    nachbar = [Suggestion(whg1, whg1.name, 0.9, "gelernt", relative_path="Ablage/Haus/Whg 1/Strom")]
    pdf_b = _select(main_window, scan, "b.pdf")
    out = main_window._with_ki_folder(pdf_b, list(nachbar))
    assert [s.folder_path for s in out] == [whg2, whg1]
    assert "Musterweg 5 Whg 2" in out[0].reason

    # 3. Ohne Einheit von der KI zaehlt die Zaehlernummer im Text
    pdf_c = _select(main_window, scan, "c.pdf")
    main_window.selected_pdf_text = "Rechnungsanschrift: Max Mustermann, Beispielallee 9\nZähler-Nr.: 70471122"
    out = main_window._with_ki_folder(pdf_c, list(nachbar))
    assert out[0].folder_path == whg2
    # ... und ohne Bezug zur Einheit bleibt alles, wie es war
    main_window.selected_pdf_text = "Rechnung ohne Zaehler"
    assert [s.folder_path for s in main_window._with_ki_folder(pdf_c, list(nachbar))] == [whg1]


def test_geleertes_feld_einheit_lernt_nichts_ohne_kennung(main_window, fresh_singletons, monkeypatch):
    tmp = fresh_singletons["tmp_path"]
    scan = _make_scan_folder(tmp, ["a.pdf"])
    ablage = _ablage(main_window, tmp, "Haus/Whg 1/Strom")
    monkeypatch.setattr(main_window.pdf_cache, "get_llm_suggestions", lambda p: [_ki(einheit="Musterweg 5 Whg 1")])

    _select(main_window, scan, "a.pdf")
    main_window.detail_panel._metadata_inputs["einheit"].setText("")
    main_window.on_suggestion_clicked(ablage / "Haus" / "Whg 1" / "Strom")

    assert len(list((ablage / "Haus" / "Whg 1" / "Strom").iterdir())) == 1   # abgelegt (Name von der KI)
    assert main_window.db.get_einheit_zuordnungen() == []

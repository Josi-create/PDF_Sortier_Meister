"""Tests zu Issue #319: neue, verschwundene und umbenannte Unterordner im Scan-Ordner
erscheinen von selbst (ohne F5).

Fixtures und Hilfen aus den Tests zu #232 (tmp-Pfade ueber patch_singletons, nie die echte
Config); der Takt ist in Tests abgeschaltet, jeder Lesevorgang wird einzeln ausgeloest.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.ordner_beobachter import pdf_anzahl, unterordner_lesen
from tests.test_office_gui import (  # noqa: F401 - Fixtures
    _prime_cache_on_load,
    fresh_singletons,
    main_window,
)
from tests.test_ordner_beobachtung_232_gui import PDF, _ordner, fenster, lesen  # noqa: F401


# --- Qt-frei ---------------------------------------------------------------


def test_unterordner_lesen_wie_die_ansicht(tmp_path):
    from src.core.file_manager import FolderManager

    for name in ("Steuer", "äpfel Ü", "banken", ".versteckt", "$RECYCLE", "~tmp"):
        (tmp_path / name).mkdir()
    (tmp_path / "Datei.pdf").write_bytes(PDF)

    erwartet = [p.name for p in FolderManager().get_subfolders(tmp_path)]
    assert unterordner_lesen(tmp_path) == erwartet == ["banken", "Steuer", "äpfel Ü"]


def test_unterordner_lesen_meldet_fehlenden_ordner_als_fehler(tmp_path):
    with pytest.raises(OSError):
        unterordner_lesen(tmp_path / "gibt_es_nicht")


def test_pdf_anzahl(tmp_path):
    (tmp_path / "a.pdf").write_bytes(PDF)
    (tmp_path / "B.PDF").write_bytes(PDF)
    (tmp_path / "c.docx").write_bytes(b"PK")
    (tmp_path / "unter.pdf").mkdir()
    assert pdf_anzahl(tmp_path) == 2
    assert pdf_anzahl(tmp_path / "fehlt") is None


# --- Oberflaeche -------------------------------------------------------------


def ordnernamen(fenster) -> list[str]:  # noqa: F811
    return [k.folder_path.name for k in fenster.folder_tiles if not k.is_parent]


def test_neuer_unterordner_erscheint_ohne_neuaufbau(fenster, fresh_singletons, monkeypatch):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"])
    (scan / "Bestand").mkdir()
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    fenster.on_pdf_clicked(scan / "alt_001.pdf")
    kacheln = list(fenster.pdf_widgets)
    bestand = next(k for k in fenster.folder_tiles if not k.is_parent)
    eltern = [k for k in fenster.folder_tiles if k.is_parent]
    monkeypatch.setattr(fenster, "load_pdfs", lambda: pytest.fail("Ansicht wurde neu aufgebaut"))

    neu = scan / "Ärzte 2026"
    neu.mkdir()
    (neu / "x.pdf").write_bytes(PDF)
    (neu / "y.pdf").write_bytes(PDF)
    lesen(fenster, mal=1)   # Ordner brauchen keine Ruhezeit

    assert ordnernamen(fenster) == ["Bestand", "Ärzte 2026"]
    zeile = fenster.folder_tiles[-1]   # sortiert wie in get_subfolders (Umlaute hinten)
    assert zeile.folder_path == neu and zeile._pdf_count == 2
    assert fenster.folder_rows_layout.indexOf(zeile) >= 0
    # ".." bleibt oben, die vorhandene Zeile ist dasselbe Objekt, Kacheln und Auswahl unberuehrt
    assert fenster.folder_tiles[:len(eltern)] == eltern
    assert bestand in fenster.folder_tiles
    assert fenster.pdf_widgets == kacheln
    assert fenster.selected_pdf == scan / "alt_001.pdf"
    assert fenster.pdf_folder_count_label.text() == "3 Dateien · 2 Ordner"
    assert "Ärzte 2026" in fenster.statusbar.currentMessage()

    # Die neue Zeile ist voll verdrahtet: Doppelklick oeffnet den Ordner
    geoeffnet = []
    monkeypatch.setattr(fenster, "on_folder_tile_double_clicked", lambda p: geoeffnet.append(Path(p)))
    zeile2 = fenster._erzeuge_ordnerzeile(neu, 0)
    zeile2.double_clicked.emit(neu)
    zeile2.deleteLater()
    assert geoeffnet == [neu]

    # kein zweites Mal
    lesen(fenster)
    assert ordnernamen(fenster) == ["Bestand", "Ärzte 2026"]
    assert fenster.folder_tiles[-1] is zeile


def test_verschwundener_und_umbenannter_unterordner(fenster, fresh_singletons):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"], anzahl=1)
    for name in ("Alt", "Bleibt", "Weg"):
        (scan / name).mkdir()
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    bleibt = next(k for k in fenster.folder_tiles if k.folder_path.name == "Bleibt")
    weg = next(k for k in fenster.folder_tiles if k.folder_path.name == "Weg")

    (scan / "Weg").rmdir()
    (scan / "Alt").rename(scan / "Zuletzt umbenannt")
    lesen(fenster, mal=1)

    assert ordnernamen(fenster) == ["Bleibt", "Zuletzt umbenannt"]
    assert bleibt in fenster.folder_tiles and weg not in fenster.folder_tiles
    assert fenster.folder_rows_layout.indexOf(weg) < 0
    assert fenster.pdf_folder_count_label.text() == "1 Datei · 2 Ordner"


def test_nur_gross_klein_umbenannt(fenster, fresh_singletons):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"], anzahl=1)
    (scan / "rechnungen").mkdir()
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    (scan / "rechnungen").rename(scan / "Rechnungen")
    lesen(fenster, mal=1)
    assert ordnernamen(fenster) == ["Rechnungen"]


def test_markierter_ordner_verschwindet(fenster, fresh_singletons):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"], anzahl=1)
    (scan / "A").mkdir()
    (scan / "B").mkdir()
    fenster._navigate_to_folder(scan)
    lesen(fenster)

    fenster._markierter_ordner = scan / "B"
    fenster._ordner_markierung_anzeigen()
    (scan / "C").mkdir()
    lesen(fenster, mal=1)
    assert fenster._markierter_ordner == scan / "B"    # neuer Ordner: Markierung bleibt
    assert next(k for k in fenster.folder_tiles if k.folder_path.name == "B").markiert

    (scan / "B").rmdir()
    lesen(fenster, mal=1)
    assert fenster._markierter_ordner is None
    assert ordnernamen(fenster) == ["A", "C"]


def test_unterordner_waehrend_ein_dialog_offen_ist(fenster, fresh_singletons, monkeypatch):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"], anzahl=1)
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    b = fenster._ordner_beobachtung
    monkeypatch.setattr(b, "_nutzer_beschaeftigt", lambda: True)
    (scan / "Erst").mkdir()
    lesen(fenster, mal=1)
    (scan / "Erst").rename(scan / "Dann")
    lesen(fenster, mal=1)
    assert ordnernamen(fenster) == []
    monkeypatch.setattr(b, "_nutzer_beschaeftigt", lambda: False)
    b._anwenden()   # das macht der naechste Takt: nur der neueste Stand zaehlt
    assert ordnernamen(fenster) == ["Dann"]


def test_erster_unterordner_im_leeren_ordner(fenster, fresh_singletons):  # noqa: F811
    """Ohne ".." zeigt ein leerer Ordner „Keine PDFs …“; das wird hier nachgestellt."""
    scan = fresh_singletons["tmp_path"] / "Leer"
    scan.mkdir()
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    fenster.pdf_scroll_area.hide()
    (scan / "Neu").mkdir()
    lesen(fenster, mal=1)
    assert not fenster.pdf_scroll_area.isHidden()
    assert ordnernamen(fenster) == ["Neu"]


def test_abgeschaltet_kommen_keine_ordner(fenster, fresh_singletons):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"], anzahl=1)
    fenster._navigate_to_folder(scan)
    fresh_singletons["config"].set("scan_ordner_beobachten", False)
    (scan / "Neu").mkdir()
    lesen(fenster, mal=3)
    assert ordnernamen(fenster) == []
    fresh_singletons["config"].set("scan_ordner_beobachten", True)
    lesen(fenster, mal=1)
    assert ordnernamen(fenster) == ["Neu"]


def test_f5_waehrend_des_lesens_legt_keine_zeile_doppelt_an(fenster, fresh_singletons):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"], anzahl=1)
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    b = fenster._ordner_beobachtung
    lauf = b.lauf_sichern()
    (scan / "Neu").mkdir()
    spaet = b.lesen(lauf)       # der Lese-Thread hat den Ordner gefunden ...
    fenster.load_pdfs()         # ... da drueckt der Nutzer F5
    b._uebernehmen(lauf, spaet, 0.0)
    assert ordnernamen(fenster) == ["Neu"]


def test_fehler_beim_lesen_der_unterordner_verschluckt_keine_datei(fenster, fresh_singletons, monkeypatch):  # noqa: F811
    from src.gui import ordner_beobachtung as modul

    scan = _ordner(fresh_singletons["tmp_path"], anzahl=1)
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    (scan / "neu.pdf").write_bytes(PDF)

    echt = modul.unterordner_lesen
    zustand = {"getrennt": True}

    def unterordner(ordner):
        if zustand["getrennt"]:
            raise OSError(53, "Der Netzwerkpfad wurde nicht gefunden")
        return echt(ordner)

    monkeypatch.setattr(modul, "unterordner_lesen", unterordner)
    lesen(fenster, mal=3)
    assert len(fenster.pdf_widgets) == 1
    zustand["getrennt"] = False
    lesen(fenster)
    assert sorted(w.pdf_path.name for w in fenster.pdf_widgets) == ["alt_000.pdf", "neu.pdf"]

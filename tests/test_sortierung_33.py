"""Issue #33: Sortierung der Kacheln (Kern + Hauptfenster)."""
import os
from pathlib import Path

from src.core.sortierung import STANDARD_SORTIERUNG, sortiere_pfade, sortierung_id
from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401 - Fixtures


def _dateien(ordner: Path, spec: dict) -> list[Path]:
    """spec: name -> (Groesse in Bytes, mtime)"""
    pfade = []
    for name, (groesse, mtime) in spec.items():
        p = ordner / name
        p.write_bytes(b"x" * groesse)
        os.utime(p, (mtime, mtime))
        pfade.append(p)
    return pfade


def _namen(pfade):
    return [p.name for p in pfade]


def test_name_natuerlich_ohne_gross_kleinschreibung(tmp_path):
    pfade = _dateien(tmp_path, {"Scan 10.pdf": (1, 1), "scan 2.pdf": (1, 1), "Anna.pdf": (1, 1), "scan 1.pdf": (1, 1)})
    assert _namen(sortiere_pfade(pfade, "name_auf")) == ["Anna.pdf", "scan 1.pdf", "scan 2.pdf", "Scan 10.pdf"]
    assert _namen(sortiere_pfade(pfade, "name_ab")) == ["Scan 10.pdf", "scan 2.pdf", "scan 1.pdf", "Anna.pdf"]


def test_datum_und_groesse_mit_richtung(tmp_path):
    pfade = _dateien(tmp_path, {"a.pdf": (30, 100), "b.pdf": (10, 300), "c.pdf": (20, 200)})
    assert _namen(sortiere_pfade(pfade, "datum_ab")) == ["b.pdf", "c.pdf", "a.pdf"]
    assert _namen(sortiere_pfade(pfade, "datum_auf")) == ["a.pdf", "c.pdf", "b.pdf"]
    assert _namen(sortiere_pfade(pfade, "groesse_ab")) == ["a.pdf", "c.pdf", "b.pdf"]
    assert _namen(sortiere_pfade(pfade, "groesse_auf")) == ["b.pdf", "c.pdf", "a.pdf"]


def test_gleiche_werte_bleiben_nach_name_geordnet(tmp_path):
    pfade = _dateien(tmp_path, {"b.pdf": (5, 100), "a.pdf": (5, 100)})
    assert _namen(sortiere_pfade(pfade, "groesse_ab")) == ["a.pdf", "b.pdf"]


def test_standard_entspricht_file_manager(tmp_path):
    from src.core.file_manager import FileManager
    _dateien(tmp_path, {"a.pdf": (1, 100), "b.pdf": (1, 300), "c.pdf": (1, 200)})
    fm = FileManager()
    fm.set_scan_folder(tmp_path)
    assert sortiere_pfade(fm.get_pdf_files(), STANDARD_SORTIERUNG) == fm.get_pdf_files()


def test_unbekannte_id_faellt_auf_standard():
    assert sortierung_id("quatsch") == sortierung_id(None) == STANDARD_SORTIERUNG


def _scan(tmp_path, spec):
    scan = tmp_path / "scan"
    scan.mkdir()
    _dateien(scan, spec)
    return scan


def _kachelnamen(win):
    return [w.pdf_path.name for w in win.pdf_widgets]


def _grid_namen(win):
    """Reihenfolge der Kacheln, wie sie im Raster liegen."""
    g = win.pdf_layout
    pos = {w.pdf_path.name: tuple(g.getItemPosition(g.indexOf(w))[:2]) for w in win.pdf_widgets}
    return [n for n, _ in sorted(pos.items(), key=lambda kv: kv[1])]


SPEC = {"Scan 10.pdf": (10, 100), "scan 2.pdf": (30, 300), "Anna.pdf": (20, 200)}


def test_standard_ist_neueste_zuerst(main_window, fresh_singletons):
    main_window._navigate_to_folder(_scan(fresh_singletons["tmp_path"], SPEC))
    assert main_window.sort_combo.currentData() == "datum_ab"
    assert _kachelnamen(main_window) == ["scan 2.pdf", "Anna.pdf", "Scan 10.pdf"]


def test_umschalten_ordnet_um_ohne_neu_zu_bauen_und_behaelt_auswahl(main_window, fresh_singletons):
    scan = _scan(fresh_singletons["tmp_path"], SPEC)
    main_window._navigate_to_folder(scan)
    vorher = set(map(id, main_window.pdf_widgets))
    main_window.selected_pdf = scan / "Anna.pdf"
    main_window.selected_pdfs = [scan / "Anna.pdf", scan / "scan 2.pdf"]

    main_window.sort_combo.setCurrentIndex(main_window.sort_combo.findData("name_auf"))

    assert _kachelnamen(main_window) == ["Anna.pdf", "scan 2.pdf", "Scan 10.pdf"]
    assert _grid_namen(main_window) == _kachelnamen(main_window)
    assert set(map(id, main_window.pdf_widgets)) == vorher  # gleiche Widgets, nichts neu gebaut
    assert main_window.selected_pdf == scan / "Anna.pdf"
    assert main_window.selected_pdfs == [scan / "Anna.pdf", scan / "scan 2.pdf"]

    main_window.set_sortierung("groesse_auf")
    assert _kachelnamen(main_window) == ["Scan 10.pdf", "Anna.pdf", "scan 2.pdf"]
    assert _grid_namen(main_window) == _kachelnamen(main_window)


def test_sortierung_wird_gespeichert_und_beim_start_wiederhergestellt(main_window, fresh_singletons):
    main_window.set_sortierung("name_ab")
    from src.gui import main_window as mw_mod
    from src.utils.config import get_config
    assert get_config().get("kachel_sortierung") == "name_ab"
    win2 = mw_mod.MainWindow()
    try:
        assert win2._sortierung == "name_ab"
        assert win2.sort_combo.currentData() == "name_ab"
    finally:
        win2.close()


def test_neu_laden_behaelt_sortierung(main_window, fresh_singletons):
    scan = _scan(fresh_singletons["tmp_path"], SPEC)
    main_window._navigate_to_folder(scan)
    main_window.set_sortierung("name_auf")
    main_window.load_pdfs()
    assert _kachelnamen(main_window) == ["Anna.pdf", "scan 2.pdf", "Scan 10.pdf"]
    assert _grid_namen(main_window) == _kachelnamen(main_window)


# --- Issue #296: Datum im Dateinamen ---------------------------------------------------

def test_datum_aus_namen():
    from src.core.sortierung import datum_aus_namen
    assert datum_aus_namen("2010-03-01_Rechnung.pdf") < datum_aus_namen("2024-11-14 Brief.pdf")
    assert datum_aus_namen("1965-07-01_Urkunde.pdf") is not None  # vor 1970 (Windows)
    assert datum_aus_namen("Rechnung_2010-03-01.pdf") is None  # nur am Anfang
    assert datum_aus_namen("2024-13-45_kaputt.pdf") is None
    assert datum_aus_namen("2024-01-0123.pdf") is None
    assert datum_aus_namen("Scan 10.pdf") is None


def test_namensdatum_statt_dateidatum(tmp_path):
    # heute umbenannt, aber inhaltlich alt: das Dateidatum ist das juengste
    pfade = _dateien(tmp_path, {
        "2010-03-01_Max Mustermann Rechnung.pdf": (1, 3_000_000_000),
        "2024-11-14_Brief.pdf": (1, 1_000_000_000),
        "2020-05-05_Bescheid.pdf": (1, 2_000_000_000),
    })
    assert _namen(sortiere_pfade(pfade, "namensdatum_ab")) == [
        "2024-11-14_Brief.pdf", "2020-05-05_Bescheid.pdf", "2010-03-01_Max Mustermann Rechnung.pdf"]
    assert _namen(sortiere_pfade(pfade, "namensdatum_auf")) == [
        "2010-03-01_Max Mustermann Rechnung.pdf", "2020-05-05_Bescheid.pdf", "2024-11-14_Brief.pdf"]
    # die bisherige Datums-Sortierung bleibt beim Dateidatum
    assert _namen(sortiere_pfade(pfade, "datum_ab"))[0] == "2010-03-01_Max Mustermann Rechnung.pdf"


def test_ohne_datum_im_namen_zaehlt_dateidatum(tmp_path):
    from datetime import datetime, timezone
    def ts(j, m, t):
        return datetime(j, m, t, 12, tzinfo=timezone.utc).timestamp()
    pfade = _dateien(tmp_path, {
        "2015-01-01_Alt.pdf": (1, ts(2026, 1, 1)),
        "Scan Übersicht.pdf": (1, ts(2018, 6, 1)),  # ohne Datum im Namen, Umlaut
        "2022-01-01_Neu.pdf": (1, ts(2026, 1, 1)),
    })
    assert _namen(sortiere_pfade(pfade, "namensdatum_ab")) == [
        "2022-01-01_Neu.pdf", "Scan Übersicht.pdf", "2015-01-01_Alt.pdf"]
    # bekannte Staende aus der Ordner-Beobachtung werden fuer Dateien ohne Datum genutzt
    staende = {"Scan Übersicht.pdf": (ts(2010, 1, 1), 1)}
    assert _namen(sortiere_pfade(pfade, "namensdatum_ab", staende))[-1] == "Scan Übersicht.pdf"


def test_gleiches_namensdatum_nach_name(tmp_path):
    pfade = _dateien(tmp_path, {"2020-01-01_b.pdf": (1, 100), "2020-01-01_a.pdf": (1, 200)})
    assert _namen(sortiere_pfade(pfade, "namensdatum_ab")) == ["2020-01-01_a.pdf", "2020-01-01_b.pdf"]


def test_auswahl_bietet_datum_im_namen(main_window, fresh_singletons):
    scan = _scan(fresh_singletons["tmp_path"], {
        "2010-03-01_Alt.pdf": (1, 300), "2024-11-14_Neu.pdf": (1, 100)})
    main_window._navigate_to_folder(scan)
    assert _kachelnamen(main_window) == ["2010-03-01_Alt.pdf", "2024-11-14_Neu.pdf"]
    main_window.sort_combo.setCurrentIndex(main_window.sort_combo.findData("namensdatum_ab"))
    assert _kachelnamen(main_window) == ["2024-11-14_Neu.pdf", "2010-03-01_Alt.pdf"]
    assert _grid_namen(main_window) == _kachelnamen(main_window)

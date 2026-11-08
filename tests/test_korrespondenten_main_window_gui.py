"""MainWindow (Issue #160): Korrespondenten links statt rechts, Vorschau in der Mitte, Sprung aus dem Detailfeld.

Fixtures aus tests/test_auto_next_after_move_gui.py (tmp-Config, tmp-Datenbank, kein echtes APPDATA).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QTabWidget

from tests.test_auto_next_after_move_gui import (  # noqa: F401 - Fixtures werden importiert
    _make_scan_folder,
    _prime_cache,
    fresh_singletons,
    main_window,
)


def _index_dok(main_window, pfad: Path, korrespondent: str) -> Path:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(b"%PDF-1.4\n%%EOF\n")
    main_window.db.suchindex.metadaten_setzen(str(pfad), {"korrespondent": korrespondent}, lesen=False)
    return pfad


def test_rechts_nur_noch_der_zielordner_baum(main_window):
    assert not hasattr(main_window, "right_panel_tabs")
    assert not hasattr(main_window, "korrespondent_sidebar")
    reiter = []
    w = main_window.folder_tree.parentWidget()
    while w is not None and w is not main_window:
        if isinstance(w, QTabWidget):
            reiter.append(w)
        w = w.parentWidget()
    assert reiter == [main_window.center_tabs]  # keine Reiterleiste mehr ueber dem Baum
    assert main_window.left_tabs.widget(2) is main_window.korrespondenten_view
    assert main_window.left_tabs.tabText(2) == "Korrespondenten"


def test_rechtsklick_im_detailfeld_springt_in_den_reiter(main_window, fresh_singletons):
    fresh_singletons["config"].set("suche", {"aktiv": True})
    tmp = fresh_singletons["tmp_path"]
    _index_dok(main_window, tmp / "Ablage" / "a.pdf", "Stadtwerke Göttingen")
    _index_dok(main_window, tmp / "Ablage" / "b.pdf", "Stadtwerke Göttingen AG")
    _index_dok(main_window, tmp / "Ablage" / "c.pdf", "Telekom")

    feld = main_window.detail_panel._metadata_inputs["korrespondent"]
    feld.setText("stadtwerke goettingen")
    menue = main_window.detail_panel.korrespondent_menue()
    aktion = next(a for a in menue.actions() if a.text().startswith("Alle Dokumente von"))
    assert aktion.text() == "Alle Dokumente von „stadtwerke goettingen“ anzeigen"
    aktion.trigger()

    view = main_window.korrespondenten_view
    assert main_window.left_tabs.currentWidget() is view
    assert view.liste.currentItem().text().endswith("(2)")
    assert {d["name"] for d in view.angezeigte_dokumente()} == {"a.pdf", "b.pdf"}

    feld.setText("")
    leer = next(a for a in main_window.detail_panel.korrespondent_menue().actions()
                if a.text().startswith("Alle Dokumente"))
    assert not leer.isEnabled()


def test_dokument_aus_reiter_in_der_mitte_und_zurueck(main_window, fresh_singletons):
    fresh_singletons["config"].set("suche", {"aktiv": True})
    tmp = fresh_singletons["tmp_path"]
    archiv = _index_dok(main_window, tmp / "Ablage" / "Miete" / "vertrag.pdf", "Max Mieter")
    scan = _make_scan_folder(tmp, ["scan.pdf"])
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [scan / "scan.pdf", archiv])
    main_window.on_pdf_clicked(scan / "scan.pdf")
    assert main_window.detail_panel.get_current_pdf() == scan / "scan.pdf"

    main_window.show_korrespondent("Max Mieter")
    view = main_window.korrespondenten_view
    view.dokumente.topLevelItem(0).setSelected(True)

    panel = main_window.detail_panel  # volle Ansicht wie unter "PDFs": Felder und Vorschau
    assert panel.get_current_pdf() == archiv and main_window.selected_pdf == archiv
    assert not panel.detail_container.isHidden()

    main_window.left_tabs.setCurrentIndex(0)  # zurueck zu den PDFs: die Auswahl ist wieder da
    assert panel.get_current_pdf() == scan / "scan.pdf"
    assert main_window.selected_pdf == scan / "scan.pdf"
    assert not panel.detail_container.isHidden()

    # "Ordner links öffnen" zeigt den Ablageort in der Liste "PDFs"
    main_window.show_korrespondent("Max Mieter")
    view.dokument_menue(view.angezeigte_dokumente()[0]).actions()[1].trigger()
    assert main_window.left_tabs.currentIndex() == 0
    assert Path(main_window.config.get_scan_folder()) == archiv.parent

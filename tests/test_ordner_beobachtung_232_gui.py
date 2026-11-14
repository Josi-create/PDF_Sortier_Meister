"""GUI-Tests zu Issue #232: neue Dateien im Scan-Ordner erscheinen von selbst.

Fixtures aus tests/test_office_gui.py (tmp-Pfade, nie die echte Config). Der Takt der
Beobachtung ist in Tests abgeschaltet (tests/conftest.py); hier wird jeder Lesevorgang
einzeln ausgeloest - bis auf den Test mit echtem Takt und echtem Lese-Thread am Ende.
"""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from tests.test_office_gui import (  # noqa: F401 - Fixtures
    _prime_cache_on_load,
    fresh_singletons,
    main_window,
)

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _ordner(tmp_path, anzahl=3, name="Scan"):
    scan = tmp_path / name
    scan.mkdir()
    for i in range(anzahl):
        (scan / f"alt_{i:03d}.pdf").write_bytes(PDF)
    return scan


@pytest.fixture
def fenster(main_window, monkeypatch):  # noqa: F811
    """Hauptfenster; Analyse und KI werden nicht gestartet, sondern nur notiert."""
    b = main_window._ordner_beobachtung
    b.RUHEZEIT = 0.0   # eine Datei gilt beim zweiten Lesen als zur Ruhe gekommen
    main_window.vorab = []
    monkeypatch.setattr(main_window.pdf_cache, "pre_cache", lambda pfade: (main_window.vorab.extend(pfade), (0, 0))[1])
    _prime_cache_on_load(main_window, monkeypatch)   # Klicks starten keine Hintergrund-Analyse
    yield main_window
    # Ein Klick auf eine noch nicht analysierte (neue) Kachel setzt den Wartezeiger; er darf
    # nicht in spaetere Tests hineinreichen
    while QApplication.overrideCursor() is not None:
        QApplication.restoreOverrideCursor()


def lesen(fenster, mal=2):
    """Liest den Ordner wie der Hintergrund-Thread und uebernimmt das Ergebnis."""
    b = fenster._ordner_beobachtung
    for _ in range(mal):
        lauf = b.lauf_sichern()
        if lauf is None:
            return
        b._uebernehmen(lauf, b.lesen(lauf), 0.0)


def namen(fenster) -> list[str]:
    return sorted(w.pdf_path.name for w in fenster.pdf_widgets)


def test_neue_datei_erscheint_ohne_neuaufbau(fenster, fresh_singletons, monkeypatch):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"])
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    vorher = list(fenster.pdf_widgets)
    fenster.on_pdf_clicked(scan / "alt_001.pdf")
    monkeypatch.setattr(fenster, "load_pdfs", lambda: pytest.fail("Ansicht wurde neu aufgebaut"))

    (scan / "Scan_neu.pdf").write_bytes(PDF)
    lesen(fenster)

    assert namen(fenster) == ["Scan_neu.pdf", "alt_000.pdf", "alt_001.pdf", "alt_002.pdf"]
    # die alten Kacheln sind dieselben Objekte, die Auswahl steht
    assert all(w in fenster.pdf_widgets for w in vorher)
    assert fenster.selected_pdf == scan / "alt_001.pdf"
    assert fenster._pdf_widget_for(scan / "alt_001.pdf").selected
    neu = fenster._pdf_widget_for(scan / "Scan_neu.pdf")
    assert neu is not None and not neu.selected
    assert fenster.pdf_layout.indexOf(neu) >= 0
    # Vorab-Analyse und KI-Warteschlange wie nach F5, nur fuer die neue Datei
    assert fenster.vorab == [scan / "Scan_neu.pdf"]
    assert fenster.pdf_folder_count_label.text() == "4 Dateien"
    assert fenster.pdf_count_label.text() == "PDFs: 4"
    assert "Scan_neu.pdf" in fenster.statusbar.currentMessage()
    # kein zweites Mal
    lesen(fenster)
    assert len(fenster.pdf_widgets) == 4 and fenster.vorab == [scan / "Scan_neu.pdf"]


def test_neue_kachel_steht_nach_sortierung_an_ihrem_platz(fenster, fresh_singletons):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"])
    fenster._navigate_to_folder(scan)
    fenster.set_sortierung("name_auf")
    lesen(fenster)
    (scan / "alt_000a.pdf").write_bytes(PDF)
    lesen(fenster)
    assert [w.pdf_path.name for w in fenster.pdf_widgets] == [
        "alt_000.pdf", "alt_000a.pdf", "alt_001.pdf", "alt_002.pdf"]
    # Die neue Kachel ist klickbar wie jede andere
    fenster._pdf_widget_for(scan / "alt_000a.pdf").clicked.emit(scan / "alt_000a.pdf")
    assert fenster.selected_pdf == scan / "alt_000a.pdf"


def test_halb_geschriebene_datei_erscheint_erst_wenn_sie_fertig_ist(fenster, fresh_singletons):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"])
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    halb = scan / "Scan_0007.pdf"
    with open(halb, "wb") as datei:
        datei.write(PDF[:20])
        datei.flush()
        lesen(fenster, mal=4)
        assert fenster._pdf_widget_for(halb) is None and fenster.vorab == []
        datei.write(PDF[20:])
    lesen(fenster, mal=3)
    assert fenster._pdf_widget_for(halb) is not None
    assert fenster.vorab == [halb]


def test_verschwundene_datei_verliert_nur_ihre_kachel(fenster, fresh_singletons):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"], anzahl=5)
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    bleibt = fenster._pdf_widget_for(scan / "alt_003.pdf")
    fenster.on_pdf_clicked(scan / "alt_003.pdf")

    (scan / "alt_001.pdf").unlink()
    lesen(fenster, mal=1)

    assert namen(fenster) == ["alt_000.pdf", "alt_002.pdf", "alt_003.pdf", "alt_004.pdf"]
    assert fenster._pdf_widget_for(scan / "alt_003.pdf") is bleibt and bleibt.selected
    assert fenster.selected_pdf == scan / "alt_003.pdf"
    assert fenster.pdf_folder_count_label.text() == "4 Dateien"
    assert "alt_001.pdf" in fenster.statusbar.currentMessage()


def test_ausgewaehlte_datei_verschwindet_auswahl_und_details_werden_geleert(fenster, fresh_singletons):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"])
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    fenster.on_pdf_clicked(scan / "alt_001.pdf")
    (scan / "alt_001.pdf").unlink()
    lesen(fenster, mal=1)
    assert fenster.selected_pdf is None and fenster.selected_pdfs == []
    assert namen(fenster) == ["alt_000.pdf", "alt_002.pdf"]
    assert fenster.detail_panel.get_current_pdf() is None


def test_datei_aus_mehrfachauswahl_verschwindet(fenster, fresh_singletons):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"], anzahl=4)
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    fenster.on_pdf_clicked(scan / "alt_000.pdf")
    fenster.on_pdf_ctrl_clicked(scan / "alt_001.pdf")
    fenster.on_pdf_ctrl_clicked(scan / "alt_002.pdf")
    (scan / "alt_001.pdf").unlink()
    lesen(fenster, mal=1)
    assert sorted(p.name for p in fenster.selected_pdfs) == ["alt_000.pdf", "alt_002.pdf"]
    assert fenster._pdf_widget_for(scan / "alt_000.pdf").selected


def test_umbenennen_im_explorer(fenster, fresh_singletons):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"])
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    (scan / "alt_001.pdf").rename(scan / "Stromrechnung Mustermann.pdf")
    lesen(fenster, mal=3)
    assert namen(fenster) == ["Stromrechnung Mustermann.pdf", "alt_000.pdf", "alt_002.pdf"]


def test_eigenes_umbenennen_und_verschieben_stoert_nicht(fenster, fresh_singletons):  # noqa: F811
    """Aktionen des Programms fuehren die Kacheln selbst nach; die Beobachtung aendert daran nichts."""
    tmp = fresh_singletons["tmp_path"]
    scan = _ordner(tmp)
    ziel = tmp / "Ziel"
    ziel.mkdir()
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    # wie on_pdf_rename: Datei umbenennen, Kachel umhaengen
    neu = fenster.file_manager.rename_file(scan / "alt_000.pdf", "Umbenannt.pdf")
    fenster._update_pdf_widget_path(scan / "alt_000.pdf", neu)
    kachel = fenster._pdf_widget_for(neu)
    # wie Verschieben: Datei weg, Kachel entfernt
    fenster.file_manager.move_file(scan / "alt_001.pdf", ziel)
    fenster.remove_pdf_widget(scan / "alt_001.pdf")
    lesen(fenster, mal=4)
    assert namen(fenster) == ["Umbenannt.pdf", "alt_002.pdf"]
    assert fenster._pdf_widget_for(neu) is kachel   # nicht doppelt, nicht neu gebaut


def test_ersetzte_datei_behaelt_ihre_kachel_und_bekommt_ein_neues_bild(fenster, fresh_singletons, monkeypatch):  # noqa: F811
    """Der Scanner haengt Seiten an eine schon angezeigte PDF an."""
    scan = _ordner(fresh_singletons["tmp_path"])
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    kachel = fenster._pdf_widget_for(scan / "alt_001.pdf")
    geladen = []
    monkeypatch.setattr(kachel, "load_thumbnail", lambda: geladen.append(1))
    (scan / "alt_001.pdf").write_bytes(PDF + b"% zweite Seite\n%%EOF\n")
    lesen(fenster, mal=3)
    assert fenster._pdf_widget_for(scan / "alt_001.pdf") is kachel
    assert geladen == [1]
    assert fenster.vorab == [scan / "alt_001.pdf"]   # Analyse neu, wie nach F5


def test_word_und_textdateien_erscheinen_auch(fenster, fresh_singletons):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"])
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    (scan / "Notiz Zählerstand.txt").write_text("4711 kWh", encoding="utf-8")
    (scan / "~$Brief.docx").write_bytes(b"lock")
    (scan / "scan.tmp").write_bytes(b"x")
    lesen(fenster)
    assert namen(fenster) == ["Notiz Zählerstand.txt", "alt_000.pdf", "alt_001.pdf", "alt_002.pdf"]
    assert [w.pdf_path.name for w in fenster.office_widgets] == ["Notiz Zählerstand.txt"]
    assert fenster.pdf_folder_count_label.text() == "4 Dateien"
    assert fenster.pdf_count_label.text() == "PDFs: 3"


def test_erste_datei_im_leeren_ordner(fenster, fresh_singletons):  # noqa: F811
    tmp = fresh_singletons["tmp_path"]
    scan = tmp / "Leer"
    scan.mkdir()
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    (scan / "erste.pdf").write_bytes(PDF)
    lesen(fenster)
    assert namen(fenster) == ["erste.pdf"]
    assert not fenster.pdf_scroll_area.isHidden()


def test_ordnerwechsel_beginnt_neu(fenster, fresh_singletons):  # noqa: F811
    tmp = fresh_singletons["tmp_path"]
    a = _ordner(tmp, name="A")
    b = _ordner(tmp, anzahl=2, name="B")
    fenster._navigate_to_folder(a)
    lesen(fenster)
    alter_lauf = fenster._ordner_beobachtung.lauf_sichern()
    (a / "in_a.pdf").write_bytes(PDF)
    lesen(fenster, mal=1)                      # in A entdeckt, noch nicht gemeldet
    spaet = fenster._ordner_beobachtung.lesen(alter_lauf)   # Lese-Thread von A laeuft noch ...
    fenster._navigate_to_folder(b)             # ... waehrend der Nutzer nach B wechselt
    fenster._ordner_beobachtung._uebernehmen(alter_lauf, spaet, 0.0)
    assert spaet.neu == ["in_a.pdf"]
    assert namen(fenster) == ["alt_000.pdf", "alt_001.pdf"]   # nichts aus A in B
    (b / "in_b.pdf").write_bytes(PDF)
    lesen(fenster)
    assert namen(fenster) == ["alt_000.pdf", "alt_001.pdf", "in_b.pdf"]
    assert fenster._pdf_widget_for(b / "in_b.pdf") is not None
    # zurueck nach A: load_pdfs zeigt die Datei, die Beobachtung legt sie nicht doppelt an
    fenster._navigate_to_folder(a)
    lesen(fenster, mal=3)
    assert namen(fenster) == ["alt_000.pdf", "alt_001.pdf", "alt_002.pdf", "in_a.pdf"]


def test_nicht_lesbarer_ordner_laesst_die_kacheln_stehen(fenster, fresh_singletons, monkeypatch):  # noqa: F811
    """Netzlaufwerk getrennt: kein „alle Dateien sind weg“."""
    from src.gui import ordner_beobachtung as modul

    scan = _ordner(fresh_singletons["tmp_path"])
    fenster._navigate_to_folder(scan)
    lesen(fenster)

    def getrennt(ordner, endungen):
        raise OSError(53, "Der Netzwerkpfad wurde nicht gefunden")

    monkeypatch.setattr(modul, "ordner_lesen", getrennt)
    lesen(fenster, mal=3)
    assert len(fenster.pdf_widgets) == 3


def test_abgeschaltet_in_den_einstellungen(fenster, fresh_singletons):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"])
    fenster._navigate_to_folder(scan)
    fresh_singletons["config"].set("scan_ordner_beobachten", False)
    (scan / "neu.pdf").write_bytes(PDF)
    lesen(fenster, mal=3)
    fenster._ordner_beobachtung.takten()
    assert fenster._ordner_beobachtung._lauf is None
    assert len(fenster.pdf_widgets) == 3
    # wieder an: die inzwischen dazugekommene Datei erscheint
    fresh_singletons["config"].set("scan_ordner_beobachten", True)
    lesen(fenster)
    assert len(fenster.pdf_widgets) == 4


def test_waehrend_ein_dialog_offen_ist_bleibt_die_ansicht_stehen(fenster, fresh_singletons, monkeypatch):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"])
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    b = fenster._ordner_beobachtung
    monkeypatch.setattr(b, "_nutzer_beschaeftigt", lambda: True)
    (scan / "neu.pdf").write_bytes(PDF)
    (scan / "alt_000.pdf").unlink()
    lesen(fenster)
    assert namen(fenster) == ["alt_000.pdf", "alt_001.pdf", "alt_002.pdf"]
    monkeypatch.setattr(b, "_nutzer_beschaeftigt", lambda: False)
    b._anwenden()   # das macht der naechste Takt
    assert namen(fenster) == ["alt_001.pdf", "alt_002.pdf", "neu.pdf"]


def test_datei_wird_ersetzt_waehrend_ein_dialog_offen_ist(fenster, fresh_singletons, monkeypatch):  # noqa: F811
    """Weg und gleich wieder da, bevor die Kachel entfernt war: sie bleibt (mit Auswahl)."""
    scan = _ordner(fresh_singletons["tmp_path"])
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    fenster.on_pdf_clicked(scan / "alt_001.pdf")
    kachel = fenster._pdf_widget_for(scan / "alt_001.pdf")
    b = fenster._ordner_beobachtung
    monkeypatch.setattr(b, "_nutzer_beschaeftigt", lambda: True)
    (scan / "alt_001.pdf").unlink()
    lesen(fenster, mal=1)
    (scan / "alt_001.pdf").write_bytes(PDF + b"\n")
    lesen(fenster)
    monkeypatch.setattr(b, "_nutzer_beschaeftigt", lambda: False)
    b._anwenden()
    assert fenster._pdf_widget_for(scan / "alt_001.pdf") is kachel
    assert fenster.selected_pdf == scan / "alt_001.pdf"


def test_viele_neue_dateien_werden_in_portionen_angelegt(qtbot, fenster, fresh_singletons, monkeypatch):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"], anzahl=5)
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    b = fenster._ordner_beobachtung
    je_aufruf = []
    echt = b._anwenden

    def gezaehlt():
        vorher = len(fenster.pdf_widgets)
        echt()
        je_aufruf.append(len(fenster.pdf_widgets) - vorher)

    monkeypatch.setattr(b, "_anwenden", gezaehlt)
    b._portion_timer.timeout.disconnect()
    b._portion_timer.timeout.connect(gezaehlt)
    sortiert = []
    echtes_sortieren = fenster._sortiere_kacheln
    monkeypatch.setattr(fenster, "_sortiere_kacheln", lambda *a: (sortiert.append(1), echtes_sortieren(*a))[1])

    for i in range(60):
        (scan / f"stapel_{i:03d}.pdf").write_bytes(PDF)
    lesen(fenster)
    assert 0 < len(fenster.pdf_widgets) - 5 <= b.KACHELN_JE_PORTION   # erste Portion, Rest folgt
    qtbot.waitUntil(lambda: len(fenster.pdf_widgets) == 65, timeout=5000)
    qtbot.waitUntil(lambda: len(fenster.vorab) == 60, timeout=5000)

    assert max(je_aufruf) <= b.KACHELN_JE_PORTION
    assert sortiert == [1]                       # einmal am Ende, nicht je Kachel
    assert len(set(fenster.vorab)) == 60
    assert "60 neue Dateien" in fenster.statusbar.currentMessage()
    assert fenster.pdf_folder_count_label.text() == "65 Dateien"
    # jede Kachel genau einmal im Raster
    assert sorted(fenster.pdf_layout.indexOf(w) for w in fenster.pdf_widgets) == list(range(65))


def test_scrollposition_bleibt(qtbot, fenster, fresh_singletons):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"], anzahl=60)
    fenster.resize(1100, 600)
    QWidget.setVisible(fenster, True)   # show() ist in der Fixture stillgelegt
    qtbot.waitExposed(fenster)
    fenster._navigate_to_folder(scan)
    fenster.set_sortierung("name_auf")
    lesen(fenster)
    leiste = fenster.pdf_scroll_area.verticalScrollBar()
    qtbot.waitUntil(lambda: leiste.maximum() > 300, timeout=3000)
    leiste.setValue(300)
    (scan / "zz_neu.pdf").write_bytes(PDF)       # sortiert sich ans Ende
    (scan / "alt_059.pdf").unlink()
    lesen(fenster)
    qtbot.wait(100)
    assert fenster._pdf_widget_for(scan / "zz_neu.pdf") is not None
    assert leiste.value() == 300


def test_schliessen_haelt_die_beobachtung_an(fenster, fresh_singletons):  # noqa: F811
    scan = _ordner(fresh_singletons["tmp_path"])
    fenster._navigate_to_folder(scan)
    b = fenster._ordner_beobachtung
    b._takt.start()
    fenster.close()
    assert not b._takt.isActive()
    assert b.lauf_sichern() is None
    (scan / "neu.pdf").write_bytes(PDF)
    b.takten()   # ein verspaeteter Takt tut nichts mehr
    assert len(fenster.pdf_widgets) == 3


def test_echter_takt_mit_lese_thread(qtbot, fenster, fresh_singletons):  # noqa: F811
    """Ohne Zutun: Takt, Hintergrund-Thread, Signal zurueck in die Oberflaeche."""
    scan = _ordner(fresh_singletons["tmp_path"])
    fenster._navigate_to_folder(scan)
    b = fenster._ordner_beobachtung
    b.INTERVALL = b.INTERVALL_WARTEND = 0.05
    b.RUHEZEIT = 0.2
    b._takt.setInterval(20)
    b._takt.start()
    qtbot.waitUntil(lambda: b._lauf is not None and b._lauf.naechstes > 0, timeout=5000)

    (scan / "Scan_0042.pdf").write_bytes(PDF)
    qtbot.waitUntil(lambda: fenster._pdf_widget_for(scan / "Scan_0042.pdf") is not None, timeout=5000)
    (scan / "alt_000.pdf").unlink()
    qtbot.waitUntil(lambda: fenster._pdf_widget_for(scan / "alt_000.pdf") is None, timeout=5000)
    assert namen(fenster) == ["Scan_0042.pdf", "alt_001.pdf", "alt_002.pdf"]
    assert fenster.vorab == [scan / "Scan_0042.pdf"]


def test_einstellung_wird_gespeichert(qtbot, main_window, fresh_singletons):  # noqa: F811
    from src.gui.settings_dialog import SettingsDialog

    config = fresh_singletons["config"]
    assert config.get("scan_ordner_beobachten") is True    # Standard: an
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    assert dialog.scan_ordner_beobachten_check.isChecked()
    dialog.scan_ordner_beobachten_check.setChecked(False)
    dialog._save_settings()
    assert config.get("scan_ordner_beobachten") is False
    assert not main_window._ordner_beobachtung.eingeschaltet()


def test_neuer_scan_steht_bei_neueste_zuerst_vorn(fenster, fresh_singletons):  # noqa: F811
    import os

    scan = _ordner(fresh_singletons["tmp_path"])
    for i, p in enumerate(sorted(scan.iterdir())):
        os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))   # alte Scans
    fenster._navigate_to_folder(scan)
    assert fenster._sortierung == "datum_ab"
    lesen(fenster)
    (scan / "Scan_heute.pdf").write_bytes(PDF)
    lesen(fenster)
    assert [w.pdf_path.name for w in fenster.pdf_widgets] == [
        "Scan_heute.pdf", "alt_002.pdf", "alt_001.pdf", "alt_000.pdf"]
    # im Raster steht sie an erster Stelle
    assert fenster.pdf_layout.itemAtPosition(0, 0).widget() is fenster._pdf_widget_for(scan / "Scan_heute.pdf")


def test_ladende_kachelbilder_bremsen_weitere_kacheln(fenster, fresh_singletons, monkeypatch):  # noqa: F811
    """Jedes Kachelbild rendert in einem eigenen Thread; es entstehen nicht hunderte auf einmal."""
    scan = _ordner(fresh_singletons["tmp_path"])
    fenster._navigate_to_folder(scan)
    lesen(fenster)
    b = fenster._ordner_beobachtung
    b.BILDER_GLEICHZEITIG = 2
    b.PORTION_MS = 60_000   # hier bremst nur die Zahl der ladenden Bilder, nicht die Zeit

    class Thread:
        laeuft = True

        def isRunning(self):
            return self.laeuft

        def quit(self):
            self.laeuft = False

        def wait(self, ms=0):
            return True

    threads = []
    echt = b._kachel_anlegen

    def anlegen(pfad):
        widget = echt(pfad)
        widget._loader_thread = Thread()
        threads.append(widget._loader_thread)
        return widget

    monkeypatch.setattr(b, "_kachel_anlegen", anlegen)
    for i in range(7):
        (scan / f"neu_{i}.pdf").write_bytes(PDF)
    lesen(fenster)
    b._portion_timer.stop()
    assert len(fenster.pdf_widgets) == 3 + 2          # zwei Bilder laden, mehr Kacheln gibt es noch nicht
    assert fenster.vorab == []                        # Abschluss erst, wenn alle da sind
    b._anwenden()
    assert len(fenster.pdf_widgets) == 3 + 2
    for t in threads:
        t.laeuft = False                              # Bilder fertig
    b._anwenden()
    b._portion_timer.stop()
    assert len(fenster.pdf_widgets) == 3 + 4
    for t in threads:
        t.laeuft = False
    b._anwenden()
    b._portion_timer.stop()
    for t in threads:
        t.laeuft = False
    b._anwenden()
    assert len(fenster.pdf_widgets) == 3 + 7
    assert len(fenster.vorab) == 7

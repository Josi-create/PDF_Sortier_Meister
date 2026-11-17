"""GUI-Tests zu Issue #306: Schalter „Hinweis bei doppelten Dateien“ in den Einstellungen.

Fixtures und Hilfen aus tests/test_doppelte_245_gui.py (tmp-Pfade ueber patch_singletons, nie
die echte Konfiguration; Papierkorb unter tmp_path).
"""
from __future__ import annotations

from src.gui import doppelte
from tests.test_auto_next_after_move_gui import (  # noqa: F401 - Fixtures
    fresh_singletons,
    main_window,
)
from tests.test_doppelte_245_gui import (  # noqa: F401 - Fixture und Hilfen
    FOTO,
    PDF,
    _antwort,
    _geprueft,
    _hinweis,
    _scan,
    _ziel,
    fenster,
)


def _schalter(fenster, an: bool):
    fenster.config.set(doppelte.KONFIG_SCHLUESSEL, an)


def test_standard_an_und_einstellung_wird_gespeichert(fenster, qtbot, fresh_singletons):  # noqa: F811
    from src.gui.settings_dialog import SettingsDialog

    config = fresh_singletons["config"]
    assert config.get("doppelte_hinweis") is True  # Standard: an
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    assert dialog.doppelte_hinweis_check.isChecked()
    dialog.doppelte_hinweis_check.setChecked(False)
    dialog._save_settings()
    assert config.get("doppelte_hinweis") is False
    assert not fenster._doppelte_im_ordner.eingeschaltet()


def test_ausgeschaltet_kein_streifen_und_keine_meldung(fenster, qtbot):  # noqa: F811
    _schalter(fenster, False)
    fenster.statusbar.clearMessage()
    scan = _scan(fenster, {"a.jpg": FOTO, "b.jpg": FOTO})

    assert not fenster._doppelte_im_ordner._start.isActive()  # es wird gar nicht erst geprueft
    _geprueft(fenster, qtbot)
    assert _hinweis(fenster, scan / "a.jpg") == ""
    assert _hinweis(fenster, scan / "b.jpg") == ""
    assert "Gleicher Inhalt" not in fenster.statusbar.currentMessage()


def test_ausschalten_nimmt_streifen_sofort_weg_einschalten_bringt_sie_wieder(fenster, qtbot):  # noqa: F811
    scan = _scan(fenster, {"a.jpg": FOTO, "b.jpg": FOTO})
    _geprueft(fenster, qtbot)
    assert _hinweis(fenster, scan / "a.jpg") == "Doppelt: wie b.jpg"

    _schalter(fenster, False)
    fenster._on_settings_changed()
    assert _hinweis(fenster, scan / "a.jpg") == ""
    assert _hinweis(fenster, scan / "b.jpg") == ""

    _schalter(fenster, True)
    fenster._on_settings_changed()
    _geprueft(fenster, qtbot)
    assert _hinweis(fenster, scan / "a.jpg") == "Doppelt: wie b.jpg"


def test_ergebnis_einer_laufenden_pruefung_erscheint_nach_dem_ausschalten_nicht(fenster, qtbot):  # noqa: F811
    scan = _scan(fenster, {"a.jpg": FOTO, "b.jpg": FOTO})
    d = fenster._doppelte_im_ordner
    d._start.stop()
    d.pruefen()  # laeuft im Hintergrund
    _schalter(fenster, False)
    fenster._on_settings_changed()
    qtbot.waitUntil(lambda: d._lauf is None, timeout=5000)

    assert _hinweis(fenster, scan / "a.jpg") == ""


def test_ausgeschaltet_keine_rueckfrage_beim_ablegen(fenster, monkeypatch):  # noqa: F811
    _schalter(fenster, False)
    scan = _scan(fenster, {"Beleg.pdf": PDF})
    ziel = _ziel(fenster, {"Beleg vom Januar.pdf": PDF})
    _antwort(fenster, monkeypatch, "abbrechen")
    fenster.on_pdf_clicked(scan / "Beleg.pdf")

    fenster._move_rename_and_learn(scan / "Beleg.pdf", ziel)

    assert fenster.rueckfragen == []
    assert not (scan / "Beleg.pdf").exists() and len(list(ziel.iterdir())) == 2  # trotzdem abgelegt

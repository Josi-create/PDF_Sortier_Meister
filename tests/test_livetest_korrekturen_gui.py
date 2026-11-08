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

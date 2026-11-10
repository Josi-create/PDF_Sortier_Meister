"""KI-unterstuetztes Trennen im Hauptfenster: Menuepunkt, Vorschau-Dialog, Ablauf.

Fixtures wie in ``tests/test_bild_gui.py`` (tmp-Config, Papierkorb umgeleitet).
Kein Netz: der KI-Anbieter ist ein Stub mit fester Antwort.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pymupdf
import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QProgressDialog

from src.core import ki_trennen
from src.core.ki_trennen import Teil
from src.gui import ki_trennen_dialog as ktd
from src.gui import original_wegraeumen as ow
from tests.test_bild_gui import cursor_aufraeumen, scan  # noqa: F401 - Fixtures
from tests.test_office_gui import _prime_cache_on_load, fresh_singletons, main_window  # noqa: F401 - Fixtures

TEXTE = ["Stadtwerke Rechnung", "Seite 2 von 2", "Finanzamt Bescheid", "", "Arzt Rechnung", "Anlage"]


def _pdf(pfad: Path, texte=TEXTE) -> Path:
    doc = pymupdf.open()
    for text in texte:
        seite = doc.new_page()
        if text:
            seite.insert_text((50, 100), text)
    doc.save(str(pfad))
    doc.close()
    return pfad


def _seiten(pfad: Path) -> list[str]:
    with pymupdf.open(str(pfad)) as doc:
        return [s.get_text().strip() for s in doc]


class _Provider:
    def __init__(self, antwort, sperre: threading.Event | None = None):
        self.antwort = antwort
        self.sperre = sperre
        self.fragen: list[str] = []

    def answer_with_context(self, system_prompt, context_docs, user_question, max_tokens=1000):
        self.fragen.append(user_question)
        if self.sperre is not None:
            self.sperre.wait(5)
        return self.antwort


DREI = json.dumps({"dokumente": [
    {"erste_seite": 1, "name": "2026-10-05_Stadtwerke_Rechnung"},
    {"erste_seite": 3, "name": "2026-10-07_Finanzamt_Bescheid"},
    {"erste_seite": 5, "name": "2026-10-09_Arzt_Rechnung"},
]})


def _ki_an(monkeypatch, win, provider) -> None:
    monkeypatch.setattr(win.hybrid_classifier, "llm_provider", provider, raising=False)
    monkeypatch.setattr(win.hybrid_classifier, "is_llm_available", lambda: True)
    monkeypatch.setattr(ki_trennen, "seiten_texte", lambda pfad, ocr=True: list(TEXTE))


def _dialog_stub(monkeypatch, annehmen=True, aendern=None):
    """Ersetzt den Vorschau-Dialog; merkt, was er bekommen hat."""
    gesehen = []

    class _Dialog:
        def __init__(self, pdf_path, seitenzahl, teile, texte=None, parent=None):
            gesehen.append({"pfad": pdf_path, "seitenzahl": seitenzahl, "teile": list(teile), "texte": texte})
            self._teile = aendern(teile) if aendern else teile

        def exec(self):
            return QDialog.DialogCode.Accepted if annehmen else QDialog.DialogCode.Rejected

        def teile(self):
            return self._teile

    monkeypatch.setattr(ktd, "KiTrennenDialog", _Dialog)
    return gesehen


def _meldungen(monkeypatch) -> list:
    """Hinweis-/Warn-/Fehlerfenster protokollieren statt zeigen."""
    gezeigt = []
    for art in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, art, staticmethod(
            lambda parent, titel, text, *a, _art=art, **k: gezeigt.append((_art, text)) or QMessageBox.StandardButton.Ok))
    return gezeigt


def _fragen(monkeypatch, antwort=(False, False)):
    gestellt = []
    monkeypatch.setattr(ow, "_frage", lambda parent, text: gestellt.append(text) or antwort)
    return gestellt


# --- Menue --------------------------------------------------------------------------

def test_menuepunkt_steht_unter_pdf_trennen_und_ruft_das_hauptfenster(main_window, scan, monkeypatch):  # noqa: F811
    a = _pdf(scan / "a.pdf")
    main_window._navigate_to_folder(scan)
    widget = next(w for w in main_window.pdf_widgets if w.pdf_path == a)
    aktionen = [x for x in widget._build_context_menu().actions() if not x.isSeparator()]
    texte = [x.text() for x in aktionen]
    assert texte.index("KI-unterstütztes Trennen...") == texte.index("PDF trennen...") + 1

    gerufen = []
    monkeypatch.setattr(type(main_window), "on_pdf_ki_split", lambda self, pfad: gerufen.append(pfad))
    main_window.load_pdfs()  # Signale neu verbinden
    widget = next(w for w in main_window.pdf_widgets if w.pdf_path == a)
    next(x for x in widget._build_context_menu().actions() if x.text() == "KI-unterstütztes Trennen...").trigger()
    assert gerufen == [a]


# --- Ablauf im Hauptfenster -----------------------------------------------------------

def test_trennt_nach_ki_vorschlag_in_dokumente(main_window, scan, monkeypatch):  # noqa: F811
    a = _pdf(scan / "stapel.pdf")
    main_window._navigate_to_folder(scan)
    provider = _Provider(DREI)
    _ki_an(monkeypatch, main_window, provider)
    gesehen = _dialog_stub(monkeypatch)
    gestellt = _fragen(monkeypatch, (False, False))

    main_window.on_pdf_ki_split(a)

    assert len(provider.fragen) == 1 and "=== Seite 6 ===" in provider.fragen[0]
    assert gesehen[0]["seitenzahl"] == 6 and gesehen[0]["texte"] == TEXTE
    assert [t.seiten for t in gesehen[0]["teile"]] == [[1, 2], [3, 4], [5, 6]]
    assert _seiten(scan / "2026-10-05_Stadtwerke_Rechnung.pdf") == ["Stadtwerke Rechnung", "Seite 2 von 2"]
    assert _seiten(scan / "2026-10-07_Finanzamt_Bescheid.pdf") == ["Finanzamt Bescheid", ""]  # leere Seite bleibt dabei
    assert _seiten(scan / "2026-10-09_Arzt_Rechnung.pdf") == ["Arzt Rechnung", "Anlage"]
    assert a.exists() and len(gestellt) == 1  # Frage nach dem Original, hier: behalten
    namen = {w.pdf_path.name for w in main_window.pdf_widgets}
    assert {"2026-10-05_Stadtwerke_Rechnung.pdf", "2026-10-09_Arzt_Rechnung.pdf", "stapel.pdf"} <= namen


def test_aenderungen_aus_der_vorschau_gelten(main_window, scan, monkeypatch):  # noqa: F811
    a = _pdf(scan / "stapel.pdf")
    main_window._navigate_to_folder(scan)
    _ki_an(monkeypatch, main_window, _Provider(DREI))
    _dialog_stub(monkeypatch, aendern=lambda teile: [Teil([1, 2, 3, 4], "Alles_vorn"), Teil([5, 6], "Rest")])
    _fragen(monkeypatch)

    main_window.on_pdf_ki_split(a)

    assert sorted(p.name for p in scan.glob("*.pdf")) == ["Alles_vorn.pdf", "Rest.pdf", "stapel.pdf"]
    assert len(_seiten(scan / "Alles_vorn.pdf")) == 4


def test_original_in_den_papierkorb_und_strg_z(main_window, scan, monkeypatch):  # noqa: F811
    a = _pdf(scan / "stapel.pdf")
    main_window._navigate_to_folder(scan)
    _ki_an(monkeypatch, main_window, _Provider(DREI))
    _dialog_stub(monkeypatch)
    _fragen(monkeypatch, (True, False))

    main_window.on_pdf_ki_split(a)
    assert not a.exists() and main_window._undo_stack[-1]["type"] == "wegraeumen"
    assert all(w.pdf_path != a for w in main_window.pdf_widgets)

    main_window.undo_last_action()
    assert a.exists() and (scan / "2026-10-05_Stadtwerke_Rechnung.pdf").exists()


def test_abbrechen_in_der_vorschau_schreibt_nichts(main_window, scan, monkeypatch):  # noqa: F811
    a = _pdf(scan / "stapel.pdf")
    main_window._navigate_to_folder(scan)
    _ki_an(monkeypatch, main_window, _Provider(DREI))
    _dialog_stub(monkeypatch, annehmen=False)
    monkeypatch.setattr(ow, "_frage", lambda *x: pytest.fail("Frage trotz Abbruch"))

    main_window.on_pdf_ki_split(a)
    assert [p.name for p in scan.glob("*.pdf")] == ["stapel.pdf"]


def test_ohne_ki_hinweis_statt_aufruf(main_window, scan, monkeypatch):  # noqa: F811
    a = _pdf(scan / "stapel.pdf")
    main_window._navigate_to_folder(scan)
    monkeypatch.setattr(main_window.hybrid_classifier, "is_llm_available", lambda: False)
    monkeypatch.setattr(ki_trennen, "seiten_texte", lambda *x, **k: pytest.fail("Text gelesen ohne KI"))
    gezeigt = _meldungen(monkeypatch)

    main_window.on_pdf_ki_split(a)
    assert len(gezeigt) == 1 and gezeigt[0][0] == "information" and "KI" in gezeigt[0][1]
    assert [p.name for p in scan.glob("*.pdf")] == ["stapel.pdf"]


def test_einseitiges_pdf_und_andere_dateien(main_window, scan, monkeypatch):  # noqa: F811
    eins = _pdf(scan / "eins.pdf", ["nur eine"])
    main_window._navigate_to_folder(scan)
    provider = _Provider(DREI)
    _ki_an(monkeypatch, main_window, provider)
    gezeigt = _meldungen(monkeypatch)

    main_window.on_pdf_ki_split(eins)
    main_window.on_pdf_ki_split(scan / "bild.jpg")
    assert [art for art, _t in gezeigt] == ["information", "information"]
    assert "nur eine Seite" in gezeigt[0][1] and not provider.fragen


@pytest.mark.parametrize("antwort, teil", [
    ("Das weiß ich nicht.", "keine brauchbare Aufteilung"),
    ("", "nicht geantwortet"),
    ("[OpenRouter-Fehler: 401 Unauthorized]", "401"),
])
def test_ki_fehler_wird_gemeldet_und_schreibt_nichts(main_window, scan, monkeypatch, antwort, teil):  # noqa: F811
    a = _pdf(scan / "stapel.pdf")
    main_window._navigate_to_folder(scan)
    _ki_an(monkeypatch, main_window, _Provider(antwort))
    monkeypatch.setattr(ktd, "KiTrennenDialog", lambda *x, **k: pytest.fail("Vorschau trotz Fehler"))
    gezeigt = _meldungen(monkeypatch)

    main_window.on_pdf_ki_split(a)
    assert len(gezeigt) == 1 and gezeigt[0][0] == "warning" and teil in gezeigt[0][1]
    assert [p.name for p in scan.glob("*.pdf")] == ["stapel.pdf"]


def test_pdf_ohne_text_fragt_die_ki_nicht(main_window, scan, monkeypatch):  # noqa: F811
    a = _pdf(scan / "stapel.pdf", ["", "", ""])
    main_window._navigate_to_folder(scan)
    provider = _Provider(DREI)
    _ki_an(monkeypatch, main_window, provider)
    monkeypatch.setattr(ki_trennen, "seiten_texte", lambda pfad, ocr=True: ["", " ", ""])
    gezeigt = _meldungen(monkeypatch)

    main_window.on_pdf_ki_split(a)
    assert not provider.fragen
    assert gezeigt[0][0] == "warning" and "kein Text" in gezeigt[0][1]


def test_fehler_beim_schreiben_loescht_nicht(main_window, scan, monkeypatch):  # noqa: F811
    a = _pdf(scan / "stapel.pdf")
    main_window._navigate_to_folder(scan)
    _ki_an(monkeypatch, main_window, _Provider(DREI))
    _dialog_stub(monkeypatch)
    monkeypatch.setattr(main_window.file_manager, "split_pdf_teile",
                        lambda *x, **k: (_ for _ in ()).throw(ValueError("kaputt")))
    monkeypatch.setattr(ow, "_frage", lambda *x: pytest.fail("Frage trotz Fehler"))
    gezeigt = _meldungen(monkeypatch)

    main_window.on_pdf_ki_split(a)
    assert a.exists() and gezeigt[0][0] == "critical" and "kaputt" in gezeigt[0][1]


def test_abbrechen_waehrend_die_ki_arbeitet(main_window, scan, monkeypatch):  # noqa: F811
    a = _pdf(scan / "stapel.pdf")
    main_window._navigate_to_folder(scan)
    sperre = threading.Event()
    _ki_an(monkeypatch, main_window, _Provider(DREI, sperre))
    monkeypatch.setattr(ktd, "KiTrennenDialog", lambda *x, **k: pytest.fail("Vorschau trotz Abbruch"))

    def abbrechen():
        fenster = [w for w in QApplication.topLevelWidgets() if isinstance(w, QProgressDialog) and w.isVisible()]
        if fenster:
            fenster[0].cancel()
        else:
            QTimer.singleShot(50, abbrechen)

    QTimer.singleShot(100, abbrechen)
    try:
        main_window.on_pdf_ki_split(a)
    finally:
        sperre.set()
    assert [p.name for p in scan.glob("*.pdf")] == ["stapel.pdf"]
    assert "abgebrochen" in main_window.statusbar.currentMessage()


# --- Vorschau-Dialog ------------------------------------------------------------------

@pytest.fixture
def dialog(qtbot, tmp_path):
    pdf = _pdf(tmp_path / "stapel.pdf")
    d = ktd.KiTrennenDialog(pdf, 6, [Teil([1, 2], "Rechnung"), Teil([3, 4], "Bescheid"), Teil([5, 6], "Arzt")],
                            list(TEXTE))
    qtbot.addWidget(d)
    return d


def _zelle(d, zeile, spalte):
    return d.tabelle.item(zeile, spalte)


def test_dialog_zeigt_vorschlag_mit_bild_und_textanfang(dialog):
    assert dialog.tabelle.rowCount() == 3
    assert [_zelle(dialog, z, 0).text() for z in range(3)] == ["1-2", "3-4", "5-6"]
    assert [_zelle(dialog, z, 1).text() for z in range(3)] == ["Rechnung", "Bescheid", "Arzt"]
    assert not _zelle(dialog, 0, 0).icon().isNull()
    assert "Seite 3: Finanzamt Bescheid" in _zelle(dialog, 1, 0).toolTip()
    assert dialog.stand.text().startswith("✓ Alle 6 Seiten")


def test_dialog_meldet_fehlende_und_doppelte_seiten(dialog):
    _zelle(dialog, 0, 0).setText("1")
    assert "Seite(n) 2 kommen in keinem Dokument vor" in dialog.stand.text()
    _zelle(dialog, 0, 0).setText("1-3")
    assert "Seite(n) 3 sind mehrfach vergeben" in dialog.stand.text()
    _zelle(dialog, 0, 0).setText("quatsch")
    assert dialog.stand.text().startswith("⚠ Zeile 1")
    _zelle(dialog, 0, 0).setText("1-2")
    assert dialog.stand.text().startswith("✓")


def test_dialog_bild_folgt_der_ersten_seite(dialog):
    _zelle(dialog, 1, 0).setText("4")
    assert "Seite 4 (kein Text)" in _zelle(dialog, 1, 0).toolTip()
    _zelle(dialog, 1, 0).setText("x")
    assert _zelle(dialog, 1, 0).icon().isNull()


def test_dialog_annehmen_liefert_geaenderte_teile(dialog):
    _zelle(dialog, 0, 0).setText("1-3")
    _zelle(dialog, 1, 0).setText("4")
    _zelle(dialog, 1, 1).setText("Bescheid: Müller.pdf")
    dialog._annehmen()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.teile() == [Teil([1, 2, 3], "Rechnung"), Teil([4], "Bescheid_Mueller"), Teil([5, 6], "Arzt")]


def test_dialog_fehler_verhindert_annehmen(dialog, monkeypatch):
    gezeigt = _meldungen(monkeypatch)
    _zelle(dialog, 2, 1).setText("  ")
    dialog._annehmen()
    assert dialog.result() != QDialog.DialogCode.Accepted and "Dateiname fehlt" in gezeigt[0][1]
    _zelle(dialog, 2, 1).setText("Arzt")
    _zelle(dialog, 2, 0).setText("5-9")
    dialog._annehmen()
    assert dialog.result() != QDialog.DialogCode.Accepted and "zwischen 1 und 6" in gezeigt[1][1]


@pytest.mark.parametrize("antwort, angenommen", [
    (QMessageBox.StandardButton.No, False),
    (QMessageBox.StandardButton.Yes, True),
])
def test_dialog_fragt_bei_fehlenden_seiten(dialog, monkeypatch, antwort, angenommen):
    fragen = []
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda parent, titel, text, *a, **k: fragen.append(text) or antwort))
    _zelle(dialog, 2, 0).setText("5")
    dialog._annehmen()
    assert len(fragen) == 1 and "Seite(n) 6" in fragen[0]
    assert (dialog.result() == QDialog.DialogCode.Accepted) is angenommen
    if angenommen:
        assert dialog.teile()[2] == Teil([5], "Arzt")


def test_dialog_zeile_entfernen_gibt_seiten_an_das_dokument_davor(dialog):
    dialog.tabelle.setCurrentCell(1, 0)
    dialog._entfernen()
    assert dialog.tabelle.rowCount() == 2
    assert [_zelle(dialog, z, 0).text() for z in range(2)] == ["1-4", "5-6"]
    assert dialog.stand.text().startswith("✓ Alle 6 Seiten sind auf 2")


def test_dialog_erste_zeile_entfernen_gibt_seiten_an_das_naechste(dialog):
    dialog.tabelle.setCurrentCell(0, 0)
    dialog._entfernen()
    assert [_zelle(dialog, z, 0).text() for z in range(2)] == ["1-4", "5-6"]
    assert _zelle(dialog, 0, 1).text() == "Bescheid"


def test_dialog_letzte_zeile_bleibt(dialog):
    for _ in range(5):
        dialog.tabelle.setCurrentCell(0, 0)
        dialog._entfernen()
    assert dialog.tabelle.rowCount() == 1 and _zelle(dialog, 0, 0).text() == "1-6"


def test_dialog_dokument_hinzufuegen_nach_der_markierten_zeile(dialog):
    dialog.tabelle.setCurrentCell(0, 0)
    dialog._hinzufuegen()
    assert dialog.tabelle.rowCount() == 4
    assert _zelle(dialog, 1, 0).text() == "" and _zelle(dialog, 1, 1).text() == "stapel_Teil_4"
    assert dialog.stand.text().startswith("⚠ Zeile 2")
    _zelle(dialog, 0, 0).setText("1")
    _zelle(dialog, 1, 0).setText("2")
    assert dialog.stand.text().startswith("✓ Alle 6 Seiten sind auf 4")


def test_dialog_ein_dokument_erklaert_sich(qtbot, tmp_path):
    pdf = _pdf(tmp_path / "stapel.pdf")
    d = ktd.KiTrennenDialog(pdf, 6, [Teil([1, 2, 3, 4, 5, 6], "Vertrag")], list(TEXTE))
    qtbot.addWidget(d)
    from PyQt6.QtWidgets import QLabel
    assert any("ein einziges Dokument" in label.text() for label in d.findChildren(QLabel))


def test_dialog_gibt_das_pdf_wieder_frei(dialog):
    pfad = dialog.pdf_path
    dialog.reject()
    assert dialog._doc is None
    pfad.unlink()  # unter Windows nur moeglich, wenn die Datei nicht mehr offen ist
    assert not pfad.exists()

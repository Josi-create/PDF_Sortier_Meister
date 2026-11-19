"""Issue #414: Nicht lesbare Dateien - Kachel nennt den Grund, verstaendliche Meldungen vor dem
Trennen/Stapeln/Zusammenfuegen/Seiten bearbeiten, Hinweis, wenn die Metadaten beim Ablegen fehlen.

Alle Testdateien sind erfunden und entstehen in tmp_path.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from src.core import pdf_lesbarkeit as pl
from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401 - Fixtures


def _pdf(pfad: Path, seiten: int = 2, **speichern) -> Path:
    doc = fitz.open()
    for i in range(seiten):
        doc.new_page().insert_text((72, 72), f"Max Mustermann, Seite {i + 1}")
    doc.save(str(pfad), **speichern)
    doc.close()
    return pfad


def _geschuetzt(pfad: Path) -> Path:
    return _pdf(pfad, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="geheim", owner_pw="geheim2")


@pytest.fixture
def dateien(tmp_path):
    leer = tmp_path / "leer.pdf"
    leer.write_bytes(b"")
    text = tmp_path / "nur text.pdf"
    text.write_text("Das ist keine PDF.\n" * 10, encoding="utf-8")
    kaputt = tmp_path / "Größe kaputt.pdf"  # Umlaute im Namen
    kaputt.write_bytes(b"%PDF-1.7\n" + b"\x00" * 300)
    return {
        "ok": _pdf(tmp_path / "in ordnung.pdf"),
        "leer": leer,
        "text": text,
        "kaputt": kaputt,
        "geschuetzt": _geschuetzt(tmp_path / "geschützt.pdf"),
        "fehlt": tmp_path / "gibt es nicht.pdf",
    }


# --------------------------------------------------------------------- #
# Pruefung
# --------------------------------------------------------------------- #


def test_pruefen_nennt_den_grund(dateien):
    assert pl.pruefen(dateien["ok"]) is None
    assert pl.pruefen(dateien["leer"]).art == pl.LEER
    assert pl.pruefen(dateien["text"]).art == pl.KEINE_PDF
    kaputt = pl.pruefen(dateien["kaputt"])
    assert kaputt.art == pl.BESCHAEDIGT and kaputt.technisch  # Text der Bibliothek bleibt erhalten
    assert pl.pruefen(dateien["geschuetzt"]).art == pl.GESCHUETZT
    assert pl.pruefen(dateien["fehlt"]).art == pl.NICHT_LESBAR


def test_texte_sind_kurz_und_ohne_fachbegriffe(dateien):
    leer = pl.pruefen(dateien["leer"])
    assert leer.kurz == "Leere Datei"
    assert leer.satz("leer.pdf").startswith("„leer.pdf“ ist leer")
    assert pl.pruefen(dateien["text"]).kurz == "Keine PDF"
    assert pl.pruefen(dateien["kaputt"]).kurz == "Beschädigt"
    assert "Passwortschutz entfernen…" in pl.pruefen(dateien["geschuetzt"]).satz("x.pdf")
    assert pl.pruefen(dateien["geschuetzt"]).grund() == "die Datei ist passwortgeschützt"


# --------------------------------------------------------------------- #
# Kachel
# --------------------------------------------------------------------- #


@pytest.fixture
def kachel_fuer(qtbot, monkeypatch):
    from src.gui import pdf_thumbnail as th
    monkeypatch.setattr(th.ThumbnailLoaderThread, "start", lambda self: None)

    def machen(pfad: Path):
        widget = th.PDFThumbnailWidget(pfad)
        qtbot.addWidget(widget)
        # Der Lade-Thread laeuft hier im selben Thread: Signale kommen direkt an
        lader = th.ThumbnailLoaderThread(pfad)
        lader.thumbnail_loaded.connect(widget._on_thumbnail_loaded)
        lader.passwort_noetig.connect(widget._on_passwort_noetig)
        lader.error_occurred.connect(widget._on_thumbnail_error)
        lader.run()
        return widget

    return machen


@pytest.mark.parametrize("schluessel, kurz", [
    ("leer", "Leere Datei"), ("text", "Keine PDF"), ("kaputt", "Beschädigt")])
def test_kachel_nennt_den_grund_und_tooltip_den_bibliothekstext(dateien, kachel_fuer, schluessel, kurz):
    kachel = kachel_fuer(dateien[schluessel])
    assert kachel.thumbnail_label.text() == kurz
    tipp = kachel.toolTip()
    assert dateien[schluessel].name in tipp
    assert "Meldung der PDF-Bibliothek:" in tipp
    assert str(dateien[schluessel].parent) not in tipp.replace("\\\\", "\\")  # nur der Name, kein langer Pfad
    assert "Anklicken wählt diese PDF aus" in tipp  # der uebliche Tooltip bleibt


def test_kachel_geschuetzt_zeigt_weiter_das_schloss(dateien, kachel_fuer):
    kachel = kachel_fuer(dateien["geschuetzt"])
    assert kachel.geschuetzt
    assert "Leere Datei" not in kachel.thumbnail_label.text()
    assert "Meldung der PDF-Bibliothek" not in kachel.toolTip()


def test_kachel_vergisst_den_grund_wenn_das_bild_spaeter_kommt(dateien, kachel_fuer):
    kachel = kachel_fuer(dateien["leer"])
    _pdf(dateien["leer"])  # die Datei ist inzwischen fertig geschrieben
    from src.gui import pdf_thumbnail as th
    lader = th.ThumbnailLoaderThread(dateien["leer"])
    lader.thumbnail_loaded.connect(kachel._on_thumbnail_loaded)
    lader.error_occurred.connect(kachel._on_thumbnail_error)
    from src.core.pdf_analyzer import thumbnail_vergessen
    thumbnail_vergessen(dateien["leer"])
    lader.run()
    assert "Meldung der PDF-Bibliothek" not in kachel.toolTip()
    assert "ist leer" not in kachel.toolTip()


# --------------------------------------------------------------------- #
# Trennen, Stapeln, Zusammenfuegen, Seiten bearbeiten: vorher pruefen
# --------------------------------------------------------------------- #


@pytest.fixture
def hinweise(monkeypatch):
    from src.gui import nicht_lesbar
    gesehen = []
    monkeypatch.setattr(nicht_lesbar.QMessageBox, "warning",
                        lambda parent, titel, text: gesehen.append((titel, text)))
    return gesehen


def _abbruch_fenster(monkeypatch):
    """Ein Ersatz-Hauptfenster, bei dem jeder weitere Schritt auffaellt."""
    def nicht_erwartet(*a, **k):
        raise AssertionError("haette nach dem Hinweis abbrechen muessen")

    from src.gui import main_window as mw
    monkeypatch.setattr(mw.QMessageBox, "critical", nicht_erwartet)
    monkeypatch.setattr(mw.QInputDialog, "getText", nicht_erwartet)
    return SimpleNamespace(
        file_manager=SimpleNamespace(split_pdf=nicht_erwartet, merge_pdfs=nicht_erwartet,
                                     stack_pdfs=nicht_erwartet),
        _wait_for_metadata_writes=nicht_erwartet,
    )


def test_trennen_leere_datei_deutscher_satz_nichts_veraendert(dateien, hinweise, monkeypatch):
    from src.gui.main_window import MainWindow
    MainWindow.on_pdf_split(_abbruch_fenster(monkeypatch), dateien["leer"])
    assert len(hinweise) == 1
    titel, text = hinweise[0]
    assert titel == "PDF trennen"
    assert "„leer.pdf“ ist leer" in text and text.endswith("Es wurde nichts verändert.")
    assert "trailer" not in text and "Failed" not in text


def test_stapeln_mit_geschuetzter_pdf_verweist_auf_entsperren(dateien, hinweise, monkeypatch):
    from src.gui.main_window import MainWindow
    MainWindow.on_pdf_stacked(_abbruch_fenster(monkeypatch), [dateien["geschuetzt"]], dateien["ok"])
    assert "Passwortschutz entfernen…" in hinweise[0][1]
    assert "encrypted" not in hinweise[0][1]


def test_zusammenfuegen_nennt_alle_nicht_lesbaren(dateien, hinweise, monkeypatch):
    from src.gui.main_window import MainWindow
    fenster = _abbruch_fenster(monkeypatch)
    fenster.selected_pdfs = [dateien["ok"], dateien["text"], dateien["kaputt"]]
    MainWindow.on_pdf_merge(fenster)
    text = hinweise[0][1]
    assert "„nur text.pdf“ ist keine PDF" in text
    assert "„Größe kaputt.pdf“ ist beschädigt" in text
    assert "in ordnung.pdf" not in text


def test_seiten_bearbeiten_oeffnet_kein_leeres_fenster(dateien, hinweise, monkeypatch):
    from src.gui import seiten_bearbeiten
    monkeypatch.setattr(seiten_bearbeiten, "_dialog",
                        lambda *a: (_ for _ in ()).throw(AssertionError("Fenster geoeffnet")))
    assert seiten_bearbeiten.bearbeiten(SimpleNamespace(), dateien["kaputt"]) is False
    assert hinweise and "beschädigt" in hinweise[0][1]


def test_lesbare_pdf_ohne_hinweis(dateien, hinweise):
    from src.gui.nicht_lesbar import melden_falls_nicht_lesbar
    assert melden_falls_nicht_lesbar(None, "x", [dateien["ok"]]) is False
    assert hinweise == []


# --------------------------------------------------------------------- #
# Ablegen: Metadaten nicht geschrieben -> Statusleiste sagt es
# --------------------------------------------------------------------- #


def test_metadaten_nicht_geschrieben_steht_in_der_statusleiste(main_window, dateien, qtbot):
    win = main_window
    win._write_pdf_metadata(dateien["geschuetzt"], "Rechnung.pdf", ["rechnung"],
                            {"korrespondent": "Max Mustermann"})
    win.statusbar.showMessage("Verschoben nach: Archiv", 3000)  # die Meldung des Aufrufers kommt zuerst
    qtbot.waitUntil(lambda: "passwortgeschützt" in win.statusbar.currentMessage(), timeout=3000)
    assert "„geschützt.pdf“" in win.statusbar.currentMessage()
    # Eine spaetere Meldung (naechste Datei ausgewaehlt) verdraengt den Hinweis rechts nicht
    win.statusbar.showMessage("Ausgewählt: naechste.pdf - 3 Vorschläge", 3000)
    label = win.metadaten_hinweis_label
    assert not label.isHidden() and "geschützt.pdf" in label.text()
    assert "passwortgeschützt" in label.toolTip()
    label.clicked.emit()
    assert label.isHidden()


def test_metadaten_geschrieben_kein_hinweis(main_window, dateien, qtbot):
    win = main_window
    win._write_pdf_metadata(dateien["ok"], "Rechnung.pdf", ["rechnung"], {"korrespondent": "Max Mustermann"})
    win.statusbar.showMessage("Verschoben nach: Archiv", 3000)
    qtbot.wait(50)
    assert win.statusbar.currentMessage() == "Verschoben nach: Archiv"
    assert win.metadaten_hinweis_label.isHidden()

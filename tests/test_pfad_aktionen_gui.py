"""Issue #154: "Pfad kopieren" und "Im Explorer anzeigen" in allen Kontextmenues."""
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from src.gui import pfad_aktionen
from src.gui.folder_tile import FolderTileWidget
from src.gui.folder_tree_widget import FolderTreeWidget
from src.gui.folder_widget import FolderWidget


def _texte(menu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _aktion(menu, enthaelt: str):
    for a in menu.actions():
        if enthaelt in a.text():
            return a
    raise AssertionError(f"Kein Menueeintrag mit {enthaelt!r}: {_texte(menu)}")


@pytest.fixture
def gezeigt(monkeypatch):
    """Faengt den Aufruf des Dateimanagers ab (kein echter Explorer im Test)."""
    aufrufe: list[tuple[str, str]] = []
    monkeypatch.setattr(pfad_aktionen, "_datei_markieren", lambda p: aufrufe.append(("datei", p)))
    monkeypatch.setattr(pfad_aktionen, "open_with_default_app", lambda p: aufrufe.append(("ordner", str(p))))
    return aufrufe


@pytest.fixture
def thumbnail(qtbot, monkeypatch, tmp_path):
    from src.gui import pdf_thumbnail as th
    monkeypatch.setattr(th.ThumbnailLoaderThread, "start", lambda self: None)
    pdf = tmp_path / "Rechnung 2026.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    widget = th.PDFThumbnailWidget(pdf)
    qtbot.addWidget(widget)
    return widget


# --- Helfer ------------------------------------------------------------------


def test_helfer_kopiert_pfad(qtbot, tmp_path):
    pfad_aktionen.pfad_kopieren(tmp_path / "a.pdf")
    assert QApplication.clipboard().text() == str(tmp_path / "a.pdf")


def test_helfer_markiert_datei_und_oeffnet_ordner(tmp_path, gezeigt):
    datei = tmp_path / "a.pdf"
    datei.write_bytes(b"%PDF-1.4")
    pfad_aktionen.im_dateimanager_zeigen(datei)
    pfad_aktionen.im_dateimanager_zeigen(tmp_path)
    assert gezeigt == [("datei", str(datei)), ("ordner", str(tmp_path))]


def test_beschriftung_folgt_dem_system(monkeypatch):
    monkeypatch.setattr(pfad_aktionen.sys, "platform", "darwin")
    assert pfad_aktionen.zeigen_text() == "Im Finder zeigen"
    monkeypatch.setattr(pfad_aktionen.sys, "platform", "win32")
    monkeypatch.setattr(pfad_aktionen, "file_manager_name", lambda: "Explorer")
    assert pfad_aktionen.zeigen_text() == "Im Explorer anzeigen"
    assert pfad_aktionen.oeffnen_text() == "Im Explorer öffnen"


# --- PDF-Kachel --------------------------------------------------------------


def test_pdf_kachel_hat_eintraege_nach_oeffnen(thumbnail):
    texte = _texte(thumbnail._build_context_menu())
    i = texte.index("PDF öffnen")
    assert texte[i + 1] == pfad_aktionen.zeigen_text()
    assert texte[i + 2] == "Pfad kopieren"


def test_pdf_kachel_pfad_kopieren(thumbnail):
    QApplication.clipboard().clear()
    _aktion(thumbnail._build_context_menu(), "Pfad kopieren").trigger()
    assert QApplication.clipboard().text() == str(thumbnail.pdf_path)


def test_pdf_kachel_im_dateimanager_zeigen(thumbnail, gezeigt):
    _aktion(thumbnail._build_context_menu(), pfad_aktionen.zeigen_text()).trigger()
    assert gezeigt == [("datei", str(thumbnail.pdf_path))]


# --- Ordnerkachel links (auch "..") ------------------------------------------


@pytest.mark.parametrize("is_parent", [False, True])
def test_ordnerkachel_menue(qtbot, tmp_path, gezeigt, is_parent):
    ordner = tmp_path / "Steuer 2026"
    ordner.mkdir()
    tile = FolderTileWidget(ordner, pdf_count=2, is_parent=is_parent)
    qtbot.addWidget(tile)
    menu = tile._build_context_menu()
    erwartet = [pfad_aktionen.oeffnen_text(), "Pfad kopieren"]
    if not is_parent:
        erwartet.append("★ Als Favorit merken")  # Issue #114
    assert _texte(menu) == erwartet

    QApplication.clipboard().clear()
    _aktion(menu, "Pfad kopieren").trigger()
    assert QApplication.clipboard().text() == str(ordner)

    _aktion(menu, pfad_aktionen.oeffnen_text()).trigger()
    assert gezeigt == [("ordner", str(ordner))]


# --- Zielordner-Baum ---------------------------------------------------------


def test_baum_hat_pfad_kopieren_unter_explorer(qtbot, tmp_path):
    root = tmp_path / "Ziel"
    (root / "Bank").mkdir(parents=True)
    w = FolderTreeWidget()
    qtbot.addWidget(w)
    w.async_scan = False
    w.set_root_folders([root])

    menu = w._build_context_menu(root / "Bank")
    texte = _texte(menu)
    i = next(n for n, t in enumerate(texte) if "öffnen" in t and "links" not in t)
    assert "Pfad kopieren" in texte[i + 1]

    QApplication.clipboard().clear()
    _aktion(menu, "Pfad kopieren").trigger()
    assert QApplication.clipboard().text() == str(root / "Bank")


# --- Vorschlagskacheln -------------------------------------------------------


@pytest.mark.parametrize("vorschlag", [False, True])
def test_vorschlagskachel_pfad_kopieren(qtbot, tmp_path, vorschlag):
    w = FolderWidget(tmp_path, 0)
    qtbot.addWidget(w)
    w.is_suggestion = vorschlag
    menu = w._build_context_menu()
    assert "Pfad kopieren" in _texte(menu)

    QApplication.clipboard().clear()
    _aktion(menu, "Pfad kopieren").trigger()
    assert QApplication.clipboard().text() == str(Path(tmp_path))

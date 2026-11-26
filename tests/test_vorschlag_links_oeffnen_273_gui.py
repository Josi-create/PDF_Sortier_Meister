"""Issue #273: Rechtsklick auf eine Vorschlagskachel bietet "Ordner links öffnen"."""

from pathlib import Path
from types import SimpleNamespace

from PyQt6.QtWidgets import QLabel

from src.core import neuer_ordner
from src.gui.folder_tree_widget import FolderTreeWidget
from src.gui.folder_widget import FolderWidget
from src.gui.main_window import MainWindow
from src.gui.vorschlag_liste import VorschlagListe, VorschlagZeile
from src.i18n import tr

EINTRAG = "📁 Ordner links öffnen"


def _texte(menu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _aktion(menu, text: str):
    for a in menu.actions():
        if a.text() == text:
            return a
    raise AssertionError(f"Kein Menueeintrag {text!r}: {_texte(menu)}")


def _zeile(qtbot, ordner: Path, neu: bool = False) -> VorschlagZeile:
    z = VorschlagZeile(ordner)
    qtbot.addWidget(z)
    z.is_suggestion = True
    if neu:
        z.set_neu(True)
    return z


def test_vorschlag_hat_eintrag_vor_dem_dateimanager(qtbot, tmp_path):
    texte = _texte(_zeile(qtbot, tmp_path)._build_context_menu())
    assert EINTRAG in texte
    explorer = next(i for i, t in enumerate(texte) if t.startswith("Im ") and t.endswith(" öffnen"))
    assert texte[texte.index(EINTRAG):explorer] == [EINTRAG, "🌳 Im Baum zeigen"]  # #427 direkt dahinter


def test_wortlaut_wie_im_ordnerbaum(qtbot, tmp_path, fresh_config):
    baum = FolderTreeWidget()
    qtbot.addWidget(baum)
    baum.async_scan = False
    baum.set_root_folders([tmp_path])
    assert EINTRAG in _texte(baum._build_context_menu(tmp_path))
    assert tr(EINTRAG) == EINTRAG  # Tests laufen deutsch; der Text steht schon in der .po


def test_eintrag_meldet_den_ordner_auch_mit_umlauten(qtbot, tmp_path):
    ordner = tmp_path / "Ablage Müller" / "Übergröße 2026"
    ordner.mkdir(parents=True)
    z = _zeile(qtbot, ordner)
    gemeldet = []
    z.double_clicked.connect(gemeldet.append)
    _aktion(z._build_context_menu(), EINTRAG).trigger()
    assert gemeldet == [ordner]


def test_neuer_ordner_hat_den_eintrag_nicht(qtbot, tmp_path):
    texte = _texte(_zeile(qtbot, tmp_path / "Gibt es noch nicht", neu=True)._build_context_menu())
    assert EINTRAG not in texte


def test_zielordner_kachel_bleibt_wie_sie_war(qtbot, tmp_path):
    w = FolderWidget(tmp_path, 0)
    qtbot.addWidget(w)
    assert EINTRAG not in _texte(w._build_context_menu())


def test_im_hauptfenster_oeffnet_der_eintrag_den_ordner_links(qtbot, tmp_path):
    """display_suggestions verbindet den Eintrag mit der Navigation (wie der Doppelklick)."""
    liste = VorschlagListe()
    qtbot.addWidget(liste)
    geoeffnet = []
    fake = SimpleNamespace()
    fake.suggestions_layout = liste.spalten
    fake.suggestion_widgets = []
    fake.no_suggestions_label = QLabel("x")
    liste.spalten.addWidget(fake.no_suggestions_label)
    fake.clear_suggestions = lambda: MainWindow.clear_suggestions(fake)
    fake.on_suggestion_clicked = fake.on_pdf_dropped_on_folder = lambda *a: None
    fake.on_folder_double_clicked = geoeffnet.append
    fake.verbinde_hierhin_kopieren = lambda widget: None
    fake.verbinde_zielkachel = lambda widget: None  # Issue #427

    da = tmp_path / "Steuer 2026"
    da.mkdir()
    bestehend = SimpleNamespace(folder_path=da, folder_name=da.name, relative_path="Steuer 2026",
                                reason="x", confidence=0.9)
    neu = SimpleNamespace(folder_path=tmp_path / "Steuer 2027", folder_name="Steuer 2027",
                          relative_path="Steuer 2027", reason="x", confidence=0.8,
                          new_source=neuer_ordner.QUELLE_JAHR)
    MainWindow.display_suggestions(fake, [bestehend, neu])

    neu_zeile, zeile = fake.suggestion_widgets  # der neue Ordner steht vorne (#116)
    assert EINTRAG not in _texte(neu_zeile._build_context_menu())
    _aktion(zeile._build_context_menu(), EINTRAG).trigger()
    assert geoeffnet == [da]

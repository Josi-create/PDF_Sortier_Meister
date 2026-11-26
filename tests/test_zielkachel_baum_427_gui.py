"""Issue #427: Rechtsklick auf eine Vorschlagskachel bietet "Im Baum zeigen".

Der Ordnerbaum darunter springt zum Ziel, klappt es auf und stellt es oben ins Bild,
damit man die Unterordner sieht und das Dokument hineinziehen kann.
"""

from pathlib import Path
from types import SimpleNamespace

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from src.core import neuer_ordner
from src.gui.folder_tree_widget import FolderTreeWidget
from src.gui.folder_widget import FolderWidget
from src.gui.main_window import MainWindow
from src.gui.vorschlag_liste import VorschlagListe, VorschlagZeile
from src.i18n import tr

EINTRAG = "🌳 Im Baum zeigen"


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


def _baum(qtbot, wurzel: Path) -> FolderTreeWidget:
    baum = FolderTreeWidget()
    qtbot.addWidget(baum)
    baum.async_scan = False
    baum.set_root_folders([wurzel])
    return baum


def test_eintrag_nur_bei_bestehenden_vorschlaegen(qtbot, tmp_path):
    assert EINTRAG in _texte(_zeile(qtbot, tmp_path)._build_context_menu())
    assert EINTRAG not in _texte(_zeile(qtbot, tmp_path / "Gibt es noch nicht", neu=True)._build_context_menu())
    kachel = FolderWidget(tmp_path, 0)  # Zielordner-Kachel: unveraendert
    qtbot.addWidget(kachel)
    assert EINTRAG not in _texte(kachel._build_context_menu())
    assert tr(EINTRAG) == EINTRAG  # Tests laufen deutsch


def test_eintrag_meldet_den_ordner_auch_mit_umlauten(qtbot, tmp_path):
    ordner = tmp_path / "Ablage Müller" / "Übergröße 2026"
    ordner.mkdir(parents=True)
    z = _zeile(qtbot, ordner)
    gemeldet = []
    z.show_in_tree_requested.connect(gemeldet.append)
    _aktion(z._build_context_menu(), EINTRAG).trigger()
    assert gemeldet == [ordner]


def test_baum_klappt_auch_tiefe_ordner_auf_und_zeigt_die_unterordner(qtbot, tmp_path, fresh_config):
    wurzel = tmp_path / "Ablage"
    ziel = wurzel / "A" / "B" / "C" / "Steuer 2026"  # unterhalb der Scan-Tiefe
    for name in ("Handwerker", "Ärzte"):
        (ziel / name).mkdir(parents=True)
    baum = _baum(qtbot, wurzel)
    assert not baum.has_folder(ziel)

    assert baum.reveal_folder(ziel, aufklappen=True)
    item = baum._items[ziel]
    assert baum.tree.currentItem() is item and item.isExpanded()
    kinder = sorted(Path(item.child(i).data(0, Qt.ItemDataRole.UserRole)).name for i in range(item.childCount()))
    assert kinder == ["Handwerker", "Ärzte"]


def test_ohne_unterordner_nur_markiert(qtbot, tmp_path, fresh_config):
    wurzel = tmp_path / "Ablage"
    ziel = wurzel / "Leer"
    ziel.mkdir(parents=True)
    baum = _baum(qtbot, wurzel)
    assert baum.reveal_folder(ziel, aufklappen=True)
    item = baum._items[ziel]
    assert baum.tree.currentItem() is item and item.childCount() == 0


def test_ziel_weit_unten_steht_danach_oben_im_bild(qtbot, tmp_path, fresh_config):
    wurzel = tmp_path / "Ablage"
    for i in range(60):
        (wurzel / f"Ordner {i:02d}").mkdir(parents=True)
    ziel = wurzel / "Ordner 30"
    (ziel / "Unterordner").mkdir()
    baum = _baum(qtbot, wurzel)
    baum.resize(300, 250)
    baum.show()
    qtbot.waitExposed(baum)

    assert baum.reveal_folder(ziel, aufklappen=True)
    rect = baum.tree.visualItemRect(baum._items[ziel])
    kind = baum.tree.visualItemRect(baum._items[ziel].child(0))
    hoehe = baum.tree.viewport().height()
    assert 0 <= rect.top() < hoehe and 0 <= kind.top() < hoehe  # Ziel und Unterordner sichtbar
    assert rect.top() < rect.height()  # ganz oben


def test_im_hauptfenster_springt_der_baum_mit_aufklappen(qtbot, tmp_path):
    liste = VorschlagListe()
    qtbot.addWidget(liste)
    gezeigt = []
    fake = SimpleNamespace()
    fake.suggestions_layout = liste.spalten
    fake.suggestion_widgets = []
    fake.no_suggestions_label = QLabel("x")
    liste.spalten.addWidget(fake.no_suggestions_label)
    fake.clear_suggestions = lambda: MainWindow.clear_suggestions(fake)
    fake.on_suggestion_clicked = fake.on_pdf_dropped_on_folder = fake.on_folder_double_clicked = lambda *a: None
    fake.verbinde_hierhin_kopieren = lambda widget: None
    fake.verbinde_zielkachel = lambda widget: MainWindow.verbinde_zielkachel(fake, widget)
    fake.on_show_in_tree_requested = lambda p, aufklappen=False: gezeigt.append((p, aufklappen))

    da = tmp_path / "Steuer 2026"
    da.mkdir()
    bestehend = SimpleNamespace(folder_path=da, folder_name=da.name, relative_path="Steuer 2026",
                                reason="x", confidence=0.9)
    neu = SimpleNamespace(folder_path=tmp_path / "Steuer 2027", folder_name="Steuer 2027",
                          relative_path="Steuer 2027", reason="x", confidence=0.8,
                          new_source=neuer_ordner.QUELLE_JAHR)
    MainWindow.display_suggestions(fake, [bestehend, neu])

    neu_zeile, zeile = fake.suggestion_widgets
    assert EINTRAG not in _texte(neu_zeile._build_context_menu())
    _aktion(zeile._build_context_menu(), EINTRAG).trigger()
    assert gezeigt == [(da, True)]


def test_ausserhalb_des_baums_meldet_die_statusleiste(qtbot, tmp_path):
    meldungen = []
    fake = SimpleNamespace(
        folder_tree=SimpleNamespace(reveal_folder=lambda p, aufklappen=False: False),
        statusbar=SimpleNamespace(showMessage=lambda text, ms=0: meldungen.append(text)),
    )
    MainWindow.on_show_in_tree_requested(fake, tmp_path / "Woanders", aufklappen=True)
    assert meldungen and "Woanders" in meldungen[0]

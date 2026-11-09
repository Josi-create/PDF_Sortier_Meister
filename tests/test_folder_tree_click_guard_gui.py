"""Doppelklick im Zielordner-Baum: klappt auf/zu, verschiebt nichts (Issue #23/#26)."""
from src.gui.folder_tree_widget import FolderTreeWidget


def _tree_with_folder(qtbot, tmp_path):
    root = tmp_path / "Ziel"
    root.mkdir()
    w = FolderTreeWidget()
    qtbot.addWidget(w)
    w.async_scan = False
    w.set_root_folders([root])
    item = w.tree.topLevelItem(0)
    assert item is not None
    return w, root, item


def test_single_click_selects_after_interval(qtbot, tmp_path):
    w, root, item = _tree_with_folder(qtbot, tmp_path)
    with qtbot.waitSignal(w.folder_selected, timeout=2000) as blocker:
        w._on_item_clicked(item, 0)
    assert blocker.args == [root]


def test_double_click_cancels_pending_single_click(qtbot, tmp_path):
    w, root, item = _tree_with_folder(qtbot, tmp_path)
    selected = []
    w.folder_selected.connect(lambda p: selected.append(p))

    w._on_item_clicked(item, 0)  # erster Klick des Doppelklicks
    w._on_item_double_clicked(item, 0)

    qtbot.wait(w._click_timer.interval() + 100)
    assert selected == []  # kein Verschieben ausgeloest


def _baum(qtbot, root):
    w = FolderTreeWidget()
    qtbot.addWidget(w)
    w.async_scan = False
    w.set_root_folders([root])
    return w


def test_double_click_klappt_rechts_auf_und_zu_statt_links_zu_oeffnen(qtbot, tmp_path):
    """Doppelklick im Baum klappt den Ordner rechts auf/zu, links bleibt alles."""
    root = tmp_path / "Ziel"
    (root / "A" / "A1").mkdir(parents=True)
    w = _baum(qtbot, root)
    navigiert = []
    w.folder_double_clicked.connect(navigiert.append)
    item_a = w._items[root / "A"]
    assert not item_a.isExpanded()

    w._on_item_double_clicked(item_a, 0)
    assert item_a.isExpanded()
    w._on_item_double_clicked(item_a, 0)
    assert not item_a.isExpanded()
    assert navigiert == []


def test_double_click_laedt_tiefe_unterordner_nach(qtbot, tmp_path):
    """Ordner unterhalb der Scan-Tiefe (OneDrive-Baeume) klappen per Doppelklick auf."""
    root = tmp_path / "Ziel"
    tief = root / "1" / "2" / "3"
    (tief / "4").mkdir(parents=True)
    w = _baum(qtbot, root)
    item = w._items[tief]
    assert tief in w._unloaded and item.childCount() == 0

    w._on_item_double_clicked(item, 0)
    assert item.isExpanded()
    assert tief / "4" in w._items
    assert item.childCount() == 1


def test_double_click_findet_spaeter_angelegte_unterordner(qtbot, tmp_path):
    """Ohne bekannte Unterordner wird eine Ebene frisch gelesen (z.B. OneDrive-Sync)."""
    root = tmp_path / "Ziel"
    (root / "A").mkdir(parents=True)
    w = _baum(qtbot, root)
    item_a = w._items[root / "A"]
    assert item_a.childCount() == 0
    (root / "A" / "Neu").mkdir()

    w._on_item_double_clicked(item_a, 0)
    assert root / "A" / "Neu" in w._items
    assert item_a.isExpanded()


def test_double_click_ohne_unterordner_meldet_das(qtbot, tmp_path):
    root = tmp_path / "Ziel"
    (root / "Leer").mkdir(parents=True)
    w = _baum(qtbot, root)
    meldungen = []
    w.status_message.connect(meldungen.append)

    w._on_item_double_clicked(w._items[root / "Leer"], 0)
    assert not w._items[root / "Leer"].isExpanded()
    assert meldungen and "keine Unterordner" in meldungen[0]


def test_qt_eigenes_doppelklick_aufklappen_ist_aus(qtbot, tmp_path):
    """Sonst schaltet Qt zusaetzlich um und der Ordner klappt sofort wieder zu."""
    root = tmp_path / "Ziel"
    root.mkdir()
    assert not _baum(qtbot, root).tree.expandsOnDoubleClick()

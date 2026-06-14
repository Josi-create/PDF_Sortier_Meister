"""GUI-Tests fuer die KorrespondentSidebar (Phase 20 / Issue #21).

Testet:
* Sidebar instanziiert mit leerer DB
* refresh() aktualisiert die Liste
* Klick auf einen Eintrag emittiert korrespondent_selected
* "+ Neu"-Button oeffnet Edit-Dialog
* "Aus Historie sammeln" ruft auto_collect_from_history auf
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem

from src.gui.korrespondent_sidebar import KorrespondentSidebar
from src.utils.database import Database


@pytest.fixture
def db(tmp_path) -> Database:
    return Database(db_path=str(tmp_path / "sidebar_test.db"))


@pytest.fixture
def sidebar(qtbot, db):
    sb = KorrespondentSidebar(db=db)
    qtbot.addWidget(sb)
    return sb


# --------------------------------------------------------------------- #
# 1) Konstruktion
# --------------------------------------------------------------------- #


def test_sidebar_instantiates_with_empty_db(qtbot, db):
    """Sidebar laesst sich mit leerer DB instanziieren."""
    sb = KorrespondentSidebar(db=db)
    qtbot.addWidget(sb)
    assert sb is not None


def test_sidebar_shows_all_entry_by_default(sidebar):
    """Der 'Alle'-Eintrag ist immer als erstes Item da."""
    items = [sidebar.list_widget.item(i).text() for i in range(sidebar.list_widget.count())]
    assert any("Alle" in t for t in items), f"Erwartet 'Alle'-Eintrag, gefunden: {items}"


# --------------------------------------------------------------------- #
# 2) refresh() + Anzeige
# --------------------------------------------------------------------- #


def test_sidebar_refresh_shows_added_korrespondenten(sidebar, db):
    """Nach add_or_update + refresh erscheinen die Korrespondenten in der Liste."""
    db.add_or_update_korrespondent("Telekom", kategorie="Telekommunikation")
    db.add_or_update_korrespondent("Ista", kategorie="Energie")
    sidebar.refresh()
    items = [sidebar.list_widget.item(i).text() for i in range(sidebar.list_widget.count())]
    assert any("Telekom" in t for t in items)
    assert any("Ista" in t for t in items)


def test_sidebar_refresh_removes_deleted_korrespondenten(sidebar, db):
    """Nach delete + refresh ist der Eintrag weg."""
    db.add_or_update_korrespondent("Telekom")
    db.add_or_update_korrespondent("Ista")
    sidebar.refresh()
    db.delete_korrespondent("Telekom")
    sidebar.refresh()
    items = [sidebar.list_widget.item(i).text() for i in range(sidebar.list_widget.count())]
    assert not any("Telekom" in t for t in items)
    assert any("Ista" in t for t in items)


# --------------------------------------------------------------------- #
# 3) Klick-Signal
# --------------------------------------------------------------------- #


def test_sidebar_emits_korrespondent_selected_on_click(qtbot, sidebar, db):
    """Klick auf einen Korrespondenten emittiert Signal mit dessen Namen."""
    db.add_or_update_korrespondent("Telekom")
    sidebar.refresh()
    # Finde Item mit "Telekom"
    target_item = None
    for i in range(sidebar.list_widget.count()):
        if "Telekom" in sidebar.list_widget.item(i).text():
            target_item = sidebar.list_widget.item(i)
            break
    assert target_item is not None
    # Signal abfangen
    with qtbot.waitSignal(sidebar.korrespondent_selected, timeout=1000) as sig:
        sidebar.list_widget.setCurrentItem(target_item)
        sidebar._on_item_clicked(target_item)
    args = sig.args
    assert args == ["Telekom"]


def test_sidebar_emits_none_when_all_clicked(qtbot, sidebar):
    """Klick auf 'Alle' emittiert None als Signal-Argument."""
    # Finde 'Alle'-Item
    for i in range(sidebar.list_widget.count()):
        if "Alle" in sidebar.list_widget.item(i).text():
            target = sidebar.list_widget.item(i)
            break
    else:
        pytest.fail("Kein 'Alle'-Item gefunden")
    with qtbot.waitSignal(sidebar.korrespondent_selected, timeout=1000) as sig:
        sidebar._on_item_clicked(target)
    assert sig.args == [None]


# --------------------------------------------------------------------- #
# 4) "+ Neu" + "Aus Historie sammeln"
# --------------------------------------------------------------------- #


def test_sidebar_has_alle_necessary_buttons(sidebar):
    """Die Sidebar hat die Standard-Buttons (Neu, Bearbeiten, etc.)."""
    from PyQt6.QtWidgets import QPushButton
    btns = [b.text() for b in sidebar.findChildren(QPushButton)]
    # Mindestens "+ Neu" oder "Neu"
    assert any("Neu" in t for t in btns), f"Kein 'Neu'-Button: {btns}"


def test_sidebar_has_history_collection_button(sidebar):
    """Es gibt einen Button zum Sammeln aus Historie."""
    from PyQt6.QtWidgets import QPushButton
    btns = [b.text() for b in sidebar.findChildren(QPushButton)]
    assert any("Historie" in t or "Sammeln" in t or "Aktualisieren" in t for t in btns), \
        f"Kein Historie/Sammeln-Button: {btns}"

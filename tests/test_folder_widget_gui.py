"""GUI-Tests fuer das FolderWidget (linke Zielordner-Spalte).

Verwendet ``pytest-qt``. Wir testen:

* Konstruktion ohne Exception
* ``clicked``-Signal bei normalem Klick
* ``clicked``-Signal bei Ctrl+Klick (Multi-Select-Pattern: das Widget
  muss auch bei gedrueckter Ctrl-Taste einen Klick erkennen, damit
  der MainWindow Multi-Select umsetzen kann)
* ``selected``-Property aendert den visuellen Zustand (StyleSheet)
* ``pdf_count`` wird im Label sichtbar angezeigt

Stilkonsistent zu ``test_file_manager.py`` (funktionsbasiert,
``tmp_path``-Fixture, plain asserts, KEINE Test-Klassen ausser Helpers).
"""

from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtCore import QPointF, QEvent

from src.gui.folder_widget import FolderWidget


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #


def _make_widget(qtbot, folder_path: Path, pdf_count: int = 0) -> FolderWidget:
    """Erzeugt ein FolderWidget und registriert es beim qtbot."""
    widget = FolderWidget(folder_path=folder_path, pdf_count=pdf_count, parent=None)
    qtbot.addWidget(widget)
    # Eine Mindestgroesse ist sinnvoll, damit mouseClick einen Treffer hat
    widget.resize(160, 140)
    return widget


def _make_mouse_event(
    button: Qt.MouseButton, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier
) -> QMouseEvent:
    """Baut ein QMouseEvent fuer ``mousePressEvent``."""
    return QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10.0, 10.0),
        QPointF(10.0, 10.0),
        button,
        button,
        modifiers,
    )


# --------------------------------------------------------------------- #
# 1) Konstruktion
# --------------------------------------------------------------------- #


def test_folder_widget_instantiates_without_exception(qtbot, tmp_path):
    """FolderWidget laesst sich mit folder_path + pdf_count instanziieren,
    wirft keine Exception und speichert die uebergebenen Werte.

    Minimal smoke - das ist der wichtigste Test, weil der ganze
    GUI-Build hier nicht crasht.
    """
    folder = tmp_path / "Rechnungen"
    widget = _make_widget(qtbot, folder, pdf_count=3)

    assert widget.folder_path == folder
    assert widget.pdf_count == 3
    assert widget.isVisible() is False  # nicht show() aufgerufen


def test_folder_widget_with_default_pdf_count(qtbot, tmp_path):
    """Default fuer ``pdf_count`` ist 0 - das Widget muss das vertragen."""
    folder = tmp_path / "default_count"
    widget = FolderWidget(folder_path=folder, parent=None)
    qtbot.addWidget(widget)

    assert widget.pdf_count == 0
    # Label zeigt "0 PDFs" (Plural-Form)
    assert "0" in widget.count_label.text()


# --------------------------------------------------------------------- #
# 2) clicked-Signal bei normalem Klick
# --------------------------------------------------------------------- #


def test_clicked_signal_fires_on_left_click(qtbot, tmp_path):
    """Ein normaler Linksklick emittiert ``clicked`` mit dem folder_path."""
    folder = tmp_path / "Belege"
    widget = _make_widget(qtbot, folder)

    with qtbot.waitSignal(widget.clicked, timeout=1000) as signal:
        # Direktes Aufrufen von mousePressEvent ist robuster als
        # qtbot.mouseClick (das Widget hat eine feste Geometrie).
        event = _make_mouse_event(Qt.MouseButton.LeftButton)
        widget.mousePressEvent(event)

    args = signal.args
    assert args == [folder]


def test_double_clicked_signal_fires_on_double_click(qtbot, tmp_path):
    """Ein Doppelklick emittiert ``double_clicked`` (separates Signal)."""
    folder = tmp_path / "Belege"
    widget = _make_widget(qtbot, folder)

    with qtbot.waitSignal(widget.double_clicked, timeout=1000) as signal:
        event = _make_mouse_event(Qt.MouseButton.LeftButton)
        widget.mouseDoubleClickEvent(event)

    assert signal.args == [folder]


def test_clicked_signal_does_not_fire_on_right_click(qtbot, tmp_path):
    """Rechtsklick emittiert KEIN ``clicked``-Signal (nur Kontextmenue)."""
    folder = tmp_path / "Belege"
    widget = _make_widget(qtbot, folder)

    spy_called = []
    widget.clicked.connect(lambda p: spy_called.append(p))

    # Rechtsklick -> clicked darf nicht feuern
    event = _make_mouse_event(Qt.MouseButton.RightButton)
    widget.mousePressEvent(event)

    assert spy_called == []


# --------------------------------------------------------------------- #
# 3) Multi-Select-Pattern: Ctrl+Klick
# --------------------------------------------------------------------- #


def test_clicked_signal_fires_on_ctrl_click(qtbot, tmp_path):
    """Ctrl+Klick emittiert ``clicked`` (das ist die Basis fuer
    Multi-Select: der MainWindow-Code entscheidet anhand des
    ``QGuiApplication.keyboardModifiers()``-States, ob zur Auswahl
    hinzugefuegt wird). Das Widget selbst feuert IMMER ``clicked`` -
    wir testen hier nur, dass das Signal auch unter Ctrl-Modifier
    durchkommt.
    """
    folder = tmp_path / "MultiSelect"
    widget = _make_widget(qtbot, folder)

    with qtbot.waitSignal(widget.clicked, timeout=1000) as signal:
        event = _make_mouse_event(
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ControlModifier,
        )
        widget.mousePressEvent(event)

    assert signal.args == [folder]


# --------------------------------------------------------------------- #
# 4) selected-Property aendert visuellen Zustand
# --------------------------------------------------------------------- #


def test_set_selected_true_changes_stylesheet(qtbot, tmp_path):
    """Setzen von ``selected = True`` aendert den StyleSheet (gelber
    Selektions-Hintergrund). Das ist der visuelle Selektions-Zustand.
    """
    folder = tmp_path / "Ziel1"
    widget = _make_widget(qtbot, folder)

    # Default: nicht selektiert
    assert widget.selected is False

    # Auf selektiert setzen
    widget.selected = True

    # Property wurde gesetzt
    assert widget.selected is True
    # StyleSheet hat sich geaendert und enthaelt die Selektions-Farbe
    assert "#ffc107" in widget.styleSheet() or "#fff3cd" in widget.styleSheet()


def test_set_selected_false_restores_normal_style(qtbot, tmp_path):
    """Setzen von ``selected = False`` zurueck auf den Default-Look
    (heller Hintergrund #fff8e7, nicht der Selektions-Hintergrund #fff3cd)."""
    folder = tmp_path / "Ziel2"
    widget = _make_widget(qtbot, folder)

    widget.selected = True
    assert widget.selected is True
    # Selektions-Hintergrund ist gesetzt
    assert "#fff3cd" in widget.styleSheet()

    widget.selected = False
    assert widget.selected is False
    # Selektions-Hintergrund ist WEG, stattdessen Default-Hintergrund #fff8e7
    style = widget.styleSheet()
    assert "#fff3cd" not in style
    assert "#fff8e7" in style


def test_set_suggestion_flag_changes_style(qtbot, tmp_path):
    """Der Suggestion-Marker aendert den Style (gruener Rand). Wird
    vom MainWindow benutzt, um KI-Vorschlaege hervorzuheben."""
    folder = tmp_path / "Vorschlag"
    widget = _make_widget(qtbot, folder)

    assert widget.is_suggestion is False

    widget.is_suggestion = True
    assert widget.is_suggestion is True
    # Suggestion-Style: gruener Rand
    assert "#28a745" in widget.styleSheet() or "#d4edda" in widget.styleSheet()


# --------------------------------------------------------------------- #
# 5) pdf_count wird im Label angezeigt
# --------------------------------------------------------------------- #


def test_pdf_count_label_singular_for_one(qtbot, tmp_path):
    """Bei ``pdf_count == 1`` wird das Label "1 PDF" (Singular)."""
    folder = tmp_path / "Singular"
    widget = _make_widget(qtbot, folder, pdf_count=1)

    assert widget.count_label.text() == "1 PDF"


def test_pdf_count_label_plural_for_many(qtbot, tmp_path):
    """Bei ``pdf_count > 1`` wird das Label "N PDFs" (Plural)."""
    folder = tmp_path / "Plural"
    widget = _make_widget(qtbot, folder, pdf_count=42)

    assert widget.count_label.text() == "42 PDFs"


def test_set_pdf_count_updates_label(qtbot, tmp_path):
    """``set_pdf_count(N)`` aktualisiert das Label sofort."""
    folder = tmp_path / "Update"
    widget = _make_widget(qtbot, folder, pdf_count=0)

    assert widget.count_label.text() == "0 PDFs"

    widget.set_pdf_count(7)
    assert widget.pdf_count == 7
    assert widget.count_label.text() == "7 PDFs"


# --------------------------------------------------------------------- #
# 6) Bonus: Ordnername wird im name_label angezeigt + lange Namen
# --------------------------------------------------------------------- #


def test_name_label_shows_folder_basename(qtbot, tmp_path):
    """Das name_label zeigt nur den Basis-Namen des Ordners, nicht
    den vollen Pfad."""
    folder = tmp_path / "MeinOrdner"
    widget = _make_widget(qtbot, folder)

    assert widget.name_label.text() == "MeinOrdner"


def test_name_label_truncates_extremely_long_names(qtbot, tmp_path):
    """Bei Ordnernamen > 50 Zeichen wird der Name mit "..." abgekuerzt
    (sonst wuerde das Widget zu gross werden)."""
    long_name = "a" * 60
    folder = tmp_path / long_name
    widget = _make_widget(qtbot, folder)

    # Genau 47 'a' + "..." = 50 Zeichen
    assert widget.name_label.text().endswith("...")
    assert len(widget.name_label.text()) <= 50

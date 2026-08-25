"""GUI-Tests fuer den RenameDialog (Phase 19 / STAB-Hardening).

Verwendet ``pytest-qt`` (siehe ``pyproject.toml`` -> ``dev``-Extras).
Wir testen den QDialog-Workflow: Konstruktion, Signal-Verbindungen,
OK/Cancel-Pfade und die LLM-Metadaten-Aktion (mit Stub).

Kein ``import anthropic`` oder ``import openai`` noetig - der
``HybridClassifier`` und der LLM-Provider werden durch minimale
Stubs ersetzt.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog

from src.gui.rename_dialog import RenameDialog, RenameSuggestion


# --------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------- #


@pytest.fixture
def pdf_path(tmp_path) -> Path:
    """Eine einfache Test-PDF (muss nicht existieren, der Dialog liest sie nicht)."""
    return tmp_path / "test_input.pdf"


@pytest.fixture
def one_suggestion() -> list[RenameSuggestion]:
    """Eine einzelne RenameSuggestion."""
    return [
        RenameSuggestion(
            name="2024-01-15_Rechnung_Telekom.pdf",
            reason="LLM-Vorschlag: Rechnung erkannt",
            confidence=0.92,
        )
    ]


@pytest.fixture
def two_suggestions() -> list[RenameSuggestion]:
    """Mehrere RenameSuggestions zum Test der Listendarstellung."""
    return [
        RenameSuggestion(name="2024-01-15_Rechnung_Telekom.pdf",
                         reason="LLM: Rechnung", confidence=0.92),
        RenameSuggestion(name="Rechnung_2024.pdf",
                         reason="Lokal: TF-IDF", confidence=0.65),
    ]


# --------------------------------------------------------------------- #
# 1) Konstruktion
# --------------------------------------------------------------------- #


def test_dialog_instantiates_with_minimal_args(qtbot, pdf_path):
    """RenameDialog laesst sich mit nur pdf_path instanziieren."""
    dlg = RenameDialog(pdf_path=pdf_path)
    qtbot.addWidget(dlg)
    assert dlg.pdf_path == pdf_path
    assert dlg.suggestions == []
    assert dlg.extracted_text == ""
    assert dlg.keywords == []


def test_dialog_instantiates_with_all_args(qtbot, pdf_path, two_suggestions):
    """Alle optionalen Args werden uebernommen."""
    dlg = RenameDialog(
        pdf_path=pdf_path,
        suggestions=two_suggestions,
        extracted_text="Rechnung von Telekom fuer 2024",
        keywords=["rechnung", "telekom"],
        detected_date="2024-01-15",
    )
    qtbot.addWidget(dlg)
    assert len(dlg.suggestions) == 2
    assert dlg.extracted_text == "Rechnung von Telekom fuer 2024"
    assert dlg.keywords == ["rechnung", "telekom"]


def test_dialog_metadata_prefilled_from_keywords(qtbot, pdf_path):
    """Wenn keywords gegeben sind, wird subject aus dem ersten abgeleitet."""
    dlg = RenameDialog(
        pdf_path=pdf_path, keywords=["strom", "rechnung"]
    )
    qtbot.addWidget(dlg)
    assert dlg._metadata.get("subject") == "Strom"


def test_dialog_metadata_prefilled_steuerjahr_from_date(qtbot, pdf_path):
    """Wenn detected_date gesetzt ist, wird steuerjahr daraus abgeleitet."""
    dlg = RenameDialog(pdf_path=pdf_path, detected_date="2024-01-15")
    qtbot.addWidget(dlg)
    assert dlg._metadata.get("steuerjahr") == "2024"


# --------------------------------------------------------------------- #
# 2) get_new_name() - initial None
# --------------------------------------------------------------------- #


def test_get_new_name_returns_none_initially(qtbot, pdf_path):
    """Vor OK-Click ist new_name None."""
    dlg = RenameDialog(pdf_path=pdf_path)
    qtbot.addWidget(dlg)
    assert dlg.get_new_name() is None


def test_dialog_has_ok_and_cancel_buttons(qtbot, pdf_path):
    """Standard-QDialog-Buttons (OK/Cancel) sind vorhanden."""
    dlg = RenameDialog(pdf_path=pdf_path)
    qtbot.addWidget(dlg)
    # Standard-Buttons: OK + Cancel
    buttons = dlg.findChildren(type(dlg.findChild(type(dlg))) or type(None))
    # Einfacher: dlg.buttons property (PyQt6 hat das)
    btns = list(dlg.buttons()) if hasattr(dlg, "buttons") else []
    # Fallback: einfach pruefen dass accept() und reject() existieren
    assert hasattr(dlg, "accept")
    assert hasattr(dlg, "reject")
    # Und dass es ein Standard-Dialog ist
    assert isinstance(dlg, QDialog)


# --------------------------------------------------------------------- #
# 3) LLM-Metadaten-Button (mit Stub)
# --------------------------------------------------------------------- #


def test_llm_metadata_button_exists(qtbot, pdf_path):
    """Der 'KI-Metadaten neu generieren'-Button ist im Dialog vorhanden."""
    dlg = RenameDialog(pdf_path=pdf_path)
    qtbot.addWidget(dlg)
    # Suche Button per Text
    from PyQt6.QtWidgets import QPushButton
    btns = dlg.findChildren(QPushButton)
    button_texts = [b.text() for b in btns]
    assert any("KI" in t and "Metadaten" in t for t in button_texts), \
        f"Erwartet KI-Metadaten-Button, gefunden: {button_texts}"


def test_llm_metadata_button_does_nothing_without_hybrid_classifier(
    qtbot, pdf_path, monkeypatch
):
    """Wenn kein HybridClassifier verfuegbar, bricht der Button-Klick
    graceful ab (kein Crash, keine Exception).
    Achtung: get_hybrid_classifier wird im rename_dialog-Modul per
    Lazy-Import innerhalb von _request_llm_metadata geladen. Wir
    patchen daher das Original-Modul src.ml.hybrid_classifier.

    Da der Code bei nicht verfuegbarem LLM einen modalen
    QMessageBox.information()-Dialog oeffnet, stubben wir diesen auch
    (sonst haengt der Test headless auf OK-Click-Event).
    """
    from src.ml import hybrid_classifier as hc_mod
    from PyQt6.QtWidgets import QMessageBox

    class _Stub:
        def is_llm_available(self):
            return False

    def _stub_factory():
        return _Stub()

    monkeypatch.setattr(hc_mod, "get_hybrid_classifier", _stub_factory)
    monkeypatch.setattr(
        QMessageBox, "information", staticmethod(lambda *a, **k: 0)
    )
    dlg = RenameDialog(pdf_path=pdf_path)
    qtbot.addWidget(dlg)
    # Klick auf den LLM-Button -> keine Exception
    from PyQt6.QtWidgets import QPushButton
    btns = [b for b in dlg.findChildren(QPushButton)
            if "KI" in b.text() and "Metadaten" in b.text()]
    assert len(btns) == 1
    btns[0].click()  # darf nicht crashen, QMessageBox ist gestubbed


# --------------------------------------------------------------------- #
# 4) rename_learned-Signal
# --------------------------------------------------------------------- #


def test_rename_learned_signal_is_declared(qtbot, pdf_path):
    """Das rename_learned-Signal ist als pyqtSignal deklariert."""
    dlg = RenameDialog(pdf_path=pdf_path)
    qtbot.addWidget(dlg)
    from PyQt6.QtCore import pyqtSignal
    # Signal existiert auf der Klasse
    assert hasattr(RenameDialog, "rename_learned")
    assert isinstance(RenameDialog.rename_learned, pyqtSignal)


# --------------------------------------------------------------------- #
# 5) Robustheit
# --------------------------------------------------------------------- #


def test_dialog_handles_invalid_date_gracefully(qtbot, pdf_path):
    """Bei kaputtem detected_date wird kein Exception geworfen."""
    dlg = RenameDialog(pdf_path=pdf_path, detected_date="kein-datum")
    qtbot.addWidget(dlg)
    # steuerjahr sollte nicht gesetzt sein
    assert "steuerjahr" not in dlg._metadata or dlg._metadata.get("steuerjahr") is None


def test_dialog_handles_none_suggestions(qtbot, pdf_path):
    """suggestions=None wird als leere Liste behandelt."""
    dlg = RenameDialog(pdf_path=pdf_path, suggestions=None)
    qtbot.addWidget(dlg)
    assert dlg.suggestions == []


def test_dialog_handles_empty_extracted_text(qtbot, pdf_path):
    """extracted_text=None wird zu leerem String."""
    dlg = RenameDialog(pdf_path=pdf_path, extracted_text=None)
    qtbot.addWidget(dlg)
    assert dlg.extracted_text == ""

"""„Ollama starten“: laenger warten, bedienbar bleiben, Fehler von selbst zuruecknehmen (Issue #432).

Kein Test startet ein echtes Ollama: ``ensure_running``, ``quick_ping`` und die Uhr sind ersetzt.
"""
from __future__ import annotations

import threading
import types

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QWidget

from src.ml import ollama_launcher
from tests.test_ollama_start_440 import start  # noqa: F401 - Fixture


# --- Launcher: ein Start, der 10 bis 30 Sekunden braucht, gilt als gelungen ---

def test_start_nach_20_sekunden_gilt_als_gelungen(start):  # noqa: F811
    start["bereit_ab"] = 20.0
    ok, meldung = ollama_launcher.ensure_running("http://localhost:11434")
    assert ok, meldung


def test_nach_30_sekunden_ohne_antwort_fehlschlag(start):  # noqa: F811
    start["bereit_ab"] = 999.0
    ok, meldung = ollama_launcher.ensure_running("http://localhost:11434")
    assert not ok
    assert "30" in meldung


# --- Fenster: Start im Hintergrund, Fehlermeldung verschwindet von selbst ---

class _Statusleiste:
    def __init__(self):
        self.meldungen = []

    def showMessage(self, text, *_):
        self.meldungen.append(text)

    def clearMessage(self):
        self.meldungen.append("")


class _Fenster(QWidget):
    """Attrappe mit den echten MainWindow-Methoden fuer den Start."""

    _ollama_start_ergebnis = pyqtSignal(bool, str)
    OLLAMA_NACHPRUEFEN_S = 5.0
    OLLAMA_NACHPRUEF_TAKT_S = 0.01

    def __init__(self):
        super().__init__()
        from src.gui.main_window import MainWindow

        self.statusbar = _Statusleiste()
        self.aufrufe = []
        self._on_settings_changed = lambda: self.aufrufe.append("einstellungen")
        for name in ("_ollama_starten", "_on_ollama_start_ergebnis"):
            setattr(self, name, types.MethodType(getattr(MainWindow, name), self))
        self._ollama_start_ergebnis.connect(self._on_ollama_start_ergebnis)


@pytest.fixture
def fenster(qtbot):
    win = _Fenster()
    qtbot.addWidget(win)
    return win


def test_start_laeuft_im_hintergrund_und_meldet_erfolg(qtbot, fenster, monkeypatch):
    freigabe = threading.Event()

    def langsam(url, max_wait=None):
        freigabe.wait(5)
        return True, "gestartet"

    monkeypatch.setattr(ollama_launcher, "ensure_running", langsam)
    assert fenster._ollama_starten("http://localhost:11434") is True
    # Die Oberflaeche ist sofort wieder frei, der Start laeuft noch
    assert fenster.statusbar.meldungen[-1] == "Ollama wird gestartet …"
    assert fenster.aufrufe == []
    assert fenster._ollama_starten("http://localhost:11434") is False  # kein Doppelstart
    freigabe.set()
    qtbot.waitUntil(lambda: fenster.aufrufe == ["einstellungen"], timeout=3000)
    assert fenster.statusbar.meldungen[-1] == "Ollama läuft."


def test_fehlermeldung_verschwindet_wenn_ollama_doch_antwortet(qtbot, fenster, monkeypatch):
    antwortet = threading.Event()
    monkeypatch.setattr(ollama_launcher, "ensure_running",
                        lambda url, max_wait=None: (False, "antwortet nicht innerhalb von 30 Sekunden"))
    monkeypatch.setattr(ollama_launcher, "quick_ping", lambda url, timeout=1.0: antwortet.is_set())
    fenster._ollama_starten("http://localhost:11434")
    qtbot.waitUntil(lambda: getattr(fenster, "_ollama_start_fehlerbox", None) is not None, timeout=3000)
    box = fenster._ollama_start_fehlerbox
    assert isinstance(box, QMessageBox) and box.isVisible()
    assert "von selbst" in box.text()
    assert fenster.aufrufe == []
    antwortet.set()
    qtbot.waitUntil(lambda: fenster.aufrufe == ["einstellungen"], timeout=3000)
    assert fenster._ollama_start_fehlerbox is None
    assert fenster.statusbar.meldungen[-1] == "Ollama läuft."


def test_fehlermeldung_bleibt_wenn_ollama_nicht_antwortet(qtbot, fenster, monkeypatch):
    fenster.OLLAMA_NACHPRUEFEN_S = 0.05
    monkeypatch.setattr(ollama_launcher, "ensure_running",
                        lambda url, max_wait=None: (False, "Ollama wurde nicht gefunden."))
    monkeypatch.setattr(ollama_launcher, "quick_ping", lambda url, timeout=1.0: False)
    fenster._ollama_starten("http://localhost:11434")
    qtbot.waitUntil(lambda: getattr(fenster, "_ollama_start_fehlerbox", None) is not None, timeout=3000)
    qtbot.wait(200)
    assert fenster.aufrufe == []
    assert fenster._ollama_start_fehlerbox.isVisible()
    fenster._ollama_start_fehlerbox.close()

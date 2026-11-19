"""Issue #291: „Verbindung testen“ meldet bei Ollama nur Erfolg, wenn das gewaehlte Modell da ist.

Der Server antwortet auch ohne Modell; dann scheitert aber jede Anfrage. Der Test in den
Einstellungen warnt deshalb, und die Statusleiste nennt das Problem statt eines Zaehlers,
der stehen bleibt.
"""
import types

import pytest

from src.gui import settings_dialog
from src.gui.settings_dialog import SettingsDialog
from src.ml.ollama_provider import OllamaProvider

URL = "http://localhost:11434"


@pytest.fixture
def meldungen(monkeypatch):
    """Faengt die Meldungsfenster ab: Liste aus (art, titel, text)."""
    gesehen = []

    class Box:
        @staticmethod
        def information(parent, titel, text, *a, **k):
            gesehen.append(("information", titel, text))

        @staticmethod
        def warning(parent, titel, text, *a, **k):
            gesehen.append(("warning", titel, text))

        @staticmethod
        def critical(parent, titel, text, *a, **k):
            gesehen.append(("critical", titel, text))

    monkeypatch.setattr(settings_dialog, "QMessageBox", Box)
    return gesehen


def _server(monkeypatch, installiert, erreichbar=True):
    monkeypatch.setattr(OllamaProvider, "ping",
                        lambda self: (True, "0.40.0") if erreichbar else (False, "refused"))
    monkeypatch.setattr(OllamaProvider, "list_models", lambda self: list(installiert))


def test_kein_modell_auf_dem_server_ist_kein_erfolg(monkeypatch, meldungen):
    """Der Fall aus dem Issue: Server laeuft, aber es ist gar kein Modell installiert."""
    _server(monkeypatch, [])
    SettingsDialog._test_ollama(None, URL, "gemma3:4b")
    assert len(meldungen) == 1
    art, titel, text = meldungen[0]
    assert art == "warning" and titel == "Modell fehlt"
    assert "erfolgreich" not in text
    assert "noch kein Modell installiert" in text
    assert "ollama pull gemma3:4b" in text


def test_anderes_modell_installiert_nennt_die_vorhandenen(monkeypatch, meldungen):
    _server(monkeypatch, ["llama3.1:8b", "qwen2.5:7b"])
    SettingsDialog._test_ollama(None, URL, "gemma3:4b")
    art, titel, text = meldungen[0]
    assert art == "warning" and titel == "Modell fehlt"
    assert "  - llama3.1:8b" in text and "  - qwen2.5:7b" in text
    assert "ollama pull gemma3:4b" in text


@pytest.mark.parametrize("gewaehlt, installiert", [
    ("gemma3:4b", ["gemma3:4b"]),
    ("llama3.1", ["llama3.1:latest"]),   # ":latest" ist bei Ollama optional
    ("llama3.1:latest", ["llama3.1"]),
])
def test_vorhandenes_modell_meldet_erfolg(monkeypatch, meldungen, gewaehlt, installiert):
    _server(monkeypatch, installiert)
    SettingsDialog._test_ollama(None, URL, gewaehlt)
    assert len(meldungen) == 1
    art, titel, text = meldungen[0]
    assert art == "information" and titel == "Erfolg"
    assert gewaehlt in text and "Hinweis" not in text


def test_ohne_gewaehltes_modell_gilt_das_standardmodell(monkeypatch, meldungen):
    _server(monkeypatch, ["gemma3:4b"])
    SettingsDialog._test_ollama(None, URL, "")
    art, _, text = meldungen[0]
    assert art == "warning"
    assert f"ollama pull {OllamaProvider.DEFAULT_MODEL}" in text


def test_server_nicht_erreichbar_bleibt_fehler(monkeypatch, meldungen):
    _server(monkeypatch, [], erreichbar=False)
    SettingsDialog._test_ollama(None, URL, "gemma3:4b")
    assert [m[0] for m in meldungen] == ["critical"]
    assert "nicht erreichbar" in meldungen[0][2]


# --- Statusleiste ---------------------------------------------------------------

def _fenster(qtbot, request_error, llm_done=0, total=125):
    """Minimales Fenster-Objekt mit den echten MainWindow-Methoden."""
    from PyQt6.QtWidgets import QLabel

    from src.gui.main_window import MainWindow
    label = QLabel()
    qtbot.addWidget(label)
    hc = types.SimpleNamespace(
        is_llm_available=lambda: True,
        get_llm_provider_name=lambda: "Ollama",
        get_llm_model_name=lambda short=False: "gemma3:4b",
        llm_connection_checkable=lambda: True,
    )
    win = types.SimpleNamespace(
        hybrid_classifier=hc, cache_status_label=label,
        config=types.SimpleNamespace(get=lambda key, default=None: default),
        _llm_connection=(True, "0.40.0"), _llm_request_error=request_error,
        _last_llm_error=("scan.pdf", request_error) if request_error else None,
        _precache_progress=lambda: (total, llm_done, total),
    )
    for name in ("_llm_health", "_update_cache_status"):
        setattr(win, name, types.MethodType(getattr(MainWindow, name), win))
    win._update_cache_status()
    return label.text()


def test_statusleiste_nennt_das_fehlende_modell(qtbot):
    text = _fenster(qtbot, "Ollama HTTP 404: model 'gemma3:4b' not found")
    assert "KI kommt nicht weiter (0/125)" in text
    # Issue #390: Ollama hat geantwortet, also laeuft es - nur das Modell fehlt
    assert "Ollama läuft, aber das Modell „gemma3:4b“ ist dort nicht installiert." in text
    assert "abgeschlossen" not in text
    assert "KI-Fehler (Doppelklick)" in text  # der Weg zu den Details bleibt


def test_statusleiste_ohne_fehler_zaehlt_wie_bisher(qtbot):
    text = _fenster(qtbot, None, llm_done=3)
    assert text == "KI verschlagwortet Ihre PDFs… 3/125 abgeschlossen"

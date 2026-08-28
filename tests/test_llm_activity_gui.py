"""GUI-Tests fuer die KI-Aktivitaetsanzeige (Issue #68).

* Detail-Panel: "KI-Metadaten neu generieren" laeuft im Hintergrund, der Button
  zeigt die laufende Uhr, das Ergebnis wird eingetragen.
* Hauptfenster: Statusleiste zeigt laufende KI-Aufrufe mit Uhr, Timer laeuft
  nur waehrend der Aktivitaet.
* Chat: Statuszeile zeigt "seit m:ss" und ggf. die Schaetzung.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from src.core import llm_activity as la


@pytest.fixture
def activity(tmp_path):
    """Frischer Aktivitaets-Zaehler mit temporaerem Store (kein Zugriff auf %APPDATA%)."""
    return la.reset_llm_activity(la.LLMTimingStore(tmp_path / "timing.json"))


@pytest.fixture
def fresh_singletons(monkeypatch, tmp_path):
    from src.core import pdf_cache as pc_mod
    from src.ml import classifier as cl_mod
    from src.ml import hybrid_classifier as hc_mod
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod
    from tests.conftest import patch_singletons

    fresh_config = cfg_mod.Config(config_path=tmp_path / "config.json")
    fresh_config.set("persist_pdf_cache", False)
    monkeypatch.setattr(pc_mod.PDFCache, "_instance", None)
    patch_singletons(monkeypatch, {
        "get_config": lambda: fresh_config,
        "get_database": lambda: db_mod.Database(db_path=str(tmp_path / "a.db")),
        "get_classifier": cl_mod.PDFClassifier,
        "get_hybrid_classifier": hc_mod.HybridClassifier,
        "get_pdf_cache": pc_mod.PDFCache,
    })
    return fresh_config


# --------------------------------------------------------------------- #
# Detail-Panel
# --------------------------------------------------------------------- #


class _FakeClassifier:
    def __init__(self, delay: float = 0.3, fail: bool = False):
        self.delay = delay
        self.fail = fail
        self.calls = 0

    def is_llm_available(self):
        return True

    def suggest_filename(self, **kwargs):
        self.calls += 1
        time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("Cloud haengt")
        return [SimpleNamespace(
            filename="2026-08-28_Rechnung_Stadtwerke.pdf",
            confidence=0.9,
            source="llm",
            metadata={"subject": "Rechnung", "korrespondent": "Stadtwerke",
                      "description": "Stromrechnung August"},
        )]


class _FakeCache:
    def __init__(self):
        self.updated = []

    def get(self, path):
        return None

    def update_llm_suggestions(self, path, suggestions):
        self.updated.append((path, suggestions))


@pytest.fixture
def panel_with_fake_llm(qtbot, monkeypatch, activity, tmp_path):
    from src.core import pdf_cache as pc_mod
    from src.core.pdf_metadata import PDFMetadata
    from src.gui import detail_panel as dp
    from src.ml import hybrid_classifier as hc_mod

    classifier = _FakeClassifier()
    cache = _FakeCache()
    monkeypatch.setattr(hc_mod, "get_hybrid_classifier", lambda: classifier)
    monkeypatch.setattr(pc_mod, "get_pdf_cache", lambda: cache)
    monkeypatch.setattr("src.core.pdf_metadata.read_metadata", lambda p: PDFMetadata())

    panel = dp.DetailPanel()
    qtbot.addWidget(panel)
    pdf = tmp_path / "beleg.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    panel.set_pdf(pdf_path=pdf, suggestions=[], extracted_text="", keywords=[])
    qtbot.waitUntil(lambda: panel._metadata_source is not None or True, timeout=1000)
    return panel, classifier, cache, pdf


def test_metadata_request_runs_in_background_and_fills_fields(qtbot, panel_with_fake_llm, activity):
    panel, classifier, cache, pdf = panel_with_fake_llm

    panel._request_llm_metadata()

    # Sofort: Button gesperrt, Uhr laeuft, Aufruf ist als Aktivitaet sichtbar
    assert not panel.llm_btn.isEnabled()
    assert panel.llm_btn.text().startswith("KI arbeitet… 0:0")
    qtbot.waitUntil(activity.is_busy, timeout=1000)
    assert activity.jobs()[0].label == "beleg.pdf"

    qtbot.waitUntil(lambda: panel.llm_btn.isEnabled(), timeout=5000)

    assert panel.llm_btn.text() == panel.LLM_BTN_TEXT
    assert panel.name_input.text() == "2026-08-28_Rechnung_Stadtwerke"
    assert panel.get_metadata()["korrespondent"] == "Stadtwerke"
    assert panel.get_metadata()["description"] == "Stromrechnung August"
    assert panel._metadata_source == "llm"
    assert len(cache.updated) == 1 and cache.updated[0][0] == pdf
    assert not activity.is_busy()
    # Dauer wurde fuer die Schaetzung gemerkt
    assert any(activity.store.samples(k) for k in [la.current_timing_key(la.KIND_SUGGEST)])


def test_metadata_request_error_reenables_button_without_recording(qtbot, panel_with_fake_llm, activity):
    panel, classifier, cache, pdf = panel_with_fake_llm
    classifier.fail = True

    panel._request_llm_metadata()
    qtbot.waitUntil(lambda: panel.llm_btn.isEnabled(), timeout=5000)

    assert panel.name_input.text() != "2026-08-28_Rechnung_Stadtwerke"
    assert cache.updated == []
    assert activity.store.samples(la.current_timing_key(la.KIND_SUGGEST)) == []


def test_metadata_result_for_other_pdf_is_ignored(qtbot, panel_with_fake_llm, tmp_path):
    panel, classifier, cache, pdf = panel_with_fake_llm

    panel._request_llm_metadata()
    # Nutzer waehlt inzwischen eine andere PDF
    other = tmp_path / "andere.pdf"
    other.write_bytes(b"%PDF-1.4")
    panel.set_pdf(pdf_path=other, suggestions=[], extracted_text="", keywords=[])

    qtbot.waitUntil(lambda: panel.llm_btn.isEnabled(), timeout=5000)

    assert panel.name_input.text() != "2026-08-28_Rechnung_Stadtwerke"
    assert cache.updated == []


def test_second_click_while_running_is_ignored(qtbot, panel_with_fake_llm):
    panel, classifier, cache, pdf = panel_with_fake_llm
    panel._request_llm_metadata()
    panel._request_llm_metadata()
    qtbot.waitUntil(lambda: panel.llm_btn.isEnabled(), timeout=5000)
    assert classifier.calls == 1


def test_button_shows_estimate_when_history_exists(qtbot, panel_with_fake_llm, activity):
    panel, classifier, cache, pdf = panel_with_fake_llm
    key = la.current_timing_key(la.KIND_SUGGEST)
    activity.store.record(key, 20)
    activity.store.record(key, 40)

    panel._request_llm_metadata()
    assert "(ca. 30 s)" in panel.llm_btn.text()
    qtbot.waitUntil(lambda: panel.llm_btn.isEnabled(), timeout=5000)


# --------------------------------------------------------------------- #
# Hauptfenster / Statusleiste
# --------------------------------------------------------------------- #


@pytest.fixture
def main_window(qtbot, fresh_singletons, monkeypatch, activity):
    from PyQt6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)

    from src.gui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "showMaximized", lambda self: None)
    monkeypatch.setattr(mw_mod.MainWindow, "show", lambda self: None)

    win = mw_mod.MainWindow()
    qtbot.addWidget(win)
    yield win
    win.close()


def test_statusbar_shows_running_llm_call_and_ticks(qtbot, main_window, activity):
    assert main_window.cache_status_label.text() == ""
    assert not main_window._activity_timer.isActive()

    token = activity.begin(la.KIND_SUGGEST, "rechnung.pdf")
    qtbot.waitUntil(lambda: "KI arbeitet" in main_window.cache_status_label.text(), timeout=1000)

    text = main_window.cache_status_label.text()
    assert "rechnung.pdf" in text and "seit 0:0" in text
    assert main_window._activity_timer.isActive()

    activity.end(token)
    qtbot.waitUntil(lambda: main_window.cache_status_label.text() == "", timeout=1000)
    assert not main_window._activity_timer.isActive()


def test_statusbar_includes_estimate(qtbot, main_window, activity):
    activity.store.record("k", 10)
    activity.store.record("k", 20)
    token = activity.begin(la.KIND_CHAT, "Frage", key="k")
    qtbot.waitUntil(lambda: "ca. 15 s" in main_window.cache_status_label.text(), timeout=1000)
    activity.end(token)


# --------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------- #


def test_chat_status_line_ticks_with_elapsed_and_estimate(qtbot, tmp_path, activity):
    from src.gui.chat_view import ChatView
    from src.utils.config import ChatConfig
    from src.utils.database import Database

    class _StubLLM:
        llm_provider = None

        def is_llm_available(self):
            return False

    view = ChatView(db=Database(db_path=str(tmp_path / "c.db")),
                    hybrid_classifier=_StubLLM(), chat_config=ChatConfig())
    qtbot.addWidget(view)

    key = la.current_timing_key(la.KIND_CHAT)
    activity.store.record(key, 20)
    activity.store.record(key, 20)

    view._status_base = "KI denkt…"
    view._request_started = time.monotonic() - 65
    view._tick_status()

    assert view.status_label.text() == "KI denkt… seit 1:05 · ca. 20 s"

    view._on_worker_progress("Suche läuft…")
    assert view.status_label.text().startswith("Suche läuft… seit 1:05")

    view._teardown_thread()
    assert view._request_started is None
    assert not view._status_timer.isActive()

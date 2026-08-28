"""Tests fuer die KI-Aktivitaetsanzeige (Issue #68): Zeitformat, Statistik, Zaehler."""
from __future__ import annotations

import json

import pytest

from src.core import llm_activity as la

# --------------------------------------------------------------------- #
# Formatierung
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("seconds, expected", [
    (0, "0:00"), (7.9, "0:07"), (42, "0:42"), (65, "1:05"), (750, "12:30"), (-3, "0:00"),
])
def test_format_elapsed(seconds, expected):
    assert la.format_elapsed(seconds) == expected


@pytest.mark.parametrize("seconds, expected", [
    (None, ""), (0, ""), (0.4, "ca. 1 s"), (29.6, "ca. 30 s"), (59.4, "ca. 59 s"),
    (90, "ca. 1:30 min"), (125, "ca. 2:05 min"),
])
def test_format_estimate(seconds, expected):
    assert la.format_estimate(seconds) == expected


def test_timing_key_and_current_key(fresh_config):
    assert la.timing_key("ollama", "gemma3:4b", "suggest") == "ollama|gemma3:4b|suggest"
    assert la.timing_key("", "", "chat") == "none|-|chat"
    fresh_config.set_llm_provider("ollama")
    llm = fresh_config.get_llm_config()
    llm["model"] = "gemma3:4b"
    fresh_config.set("llm", llm)
    assert la.current_timing_key("chat") == "ollama|gemma3:4b|chat"


# --------------------------------------------------------------------- #
# Statistik
# --------------------------------------------------------------------- #


def test_store_estimate_needs_two_samples_and_uses_median(tmp_path):
    store = la.LLMTimingStore(tmp_path / "t.json")
    assert store.estimate("k") is None
    store.record("k", 10)
    assert store.estimate("k") is None
    store.record("k", 30)
    assert store.estimate("k") == 20
    store.record("k", 600)  # Ausreisser (haengende Cloud) verzerrt den Median kaum
    assert store.estimate("k") == 30


def test_store_persists_and_trims(tmp_path):
    path = tmp_path / "t.json"
    store = la.LLMTimingStore(path)
    for i in range(30):
        store.record("k", i + 1)
    assert len(store.samples("k")) == la.MAX_SAMPLES
    assert store.samples("k")[0] == 11  # die aeltesten sind weg

    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["k"]) == la.MAX_SAMPLES

    reloaded = la.LLMTimingStore(path)
    assert reloaded.samples("k") == store.samples("k")


def test_store_ignores_nonpositive_and_bad_file(tmp_path):
    path = tmp_path / "kaputt.json"
    path.write_text("{nicht json", encoding="utf-8")
    store = la.LLMTimingStore(path)  # darf nicht werfen
    store.record("k", 0)
    store.record("k", -5)
    assert store.samples("k") == []


def test_store_without_path_works_in_memory():
    store = la.LLMTimingStore(None)
    store.record("k", 1)
    store.record("k", 3)
    assert store.estimate("k") == 2


# --------------------------------------------------------------------- #
# Aktivitaetszaehler
# --------------------------------------------------------------------- #


def test_activity_begin_end_records_and_signals(tmp_path):
    store = la.LLMTimingStore(tmp_path / "t.json")
    activity = la.LLMActivity(store)
    changes = []
    activity.changed.connect(lambda: changes.append(1))

    assert not activity.is_busy()
    assert activity.describe() == ""

    token = activity.begin(la.KIND_SUGGEST, "a.pdf", key="k")
    assert activity.is_busy()
    jobs = activity.jobs()
    assert len(jobs) == 1 and jobs[0].label == "a.pdf" and jobs[0].kind == la.KIND_SUGGEST
    assert activity.describe().startswith("seit 0:0")
    assert len(changes) == 1

    elapsed = activity.end(token)
    assert elapsed is not None and elapsed >= 0
    assert not activity.is_busy()
    assert len(store.samples("k")) == 1
    assert len(changes) == 2


def test_activity_failed_call_is_not_recorded():
    activity = la.LLMActivity(la.LLMTimingStore(None))
    token = activity.begin(la.KIND_CHAT, key="k")
    activity.end(token, success=False)
    assert activity.store.samples("k") == []
    assert activity.end(999) is None  # unbekanntes Token ist harmlos


def test_activity_describe_includes_estimate_and_filters_kind():
    store = la.LLMTimingStore(None)
    store.record("k", 20)
    store.record("k", 40)
    activity = la.LLMActivity(store)
    activity.begin(la.KIND_CHAT, "Frage", key="k")
    assert "ca. 30 s" in activity.describe()
    assert activity.describe(la.KIND_SUGGEST) == ""
    assert activity.describe(la.KIND_CHAT).startswith("seit ")


def test_singleton_reset_for_tests(tmp_path):
    a = la.reset_llm_activity(la.LLMTimingStore(tmp_path / "x.json"))
    assert la.get_llm_activity() is a
    b = la.reset_llm_activity()
    assert la.get_llm_activity() is b and b is not a

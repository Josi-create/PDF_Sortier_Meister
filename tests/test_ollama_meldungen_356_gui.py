"""GUI-Tests der Ollama-Meldungen (Issues #356, #343, #390).

* Chat (#356): Scheitert die KI unterwegs (lokales Modell abgestuerzt), steht der Grund
  als eigene, vollstaendige Zeile im Verlauf, und die Antwort sagt, dass sie ohne Suche
  entstanden ist. Ein Reiterwechsel waehrend der Antwort haelt den Chat nicht an.
* Einstellungen (#390, #343): Laeuft Ollama, stehen die installierten Modelle in der
  Auswahl; ein gespeichertes Modell, das es nicht mehr gibt, ist markiert. Die Zeile
  darunter sagt, ob Ollama laeuft, und dass die erste Analyse dauert.
* Fenster „Hintergrund-Analyse“ (#390): trennt „Ollama laeuft“ von „Modell fehlt“,
  nennt die installierten Modelle und bietet sie (erst nach Klick) an.

Kein Test fragt ein echtes Ollama: ``ollama_lage`` ist in tests/conftest.py ersetzt und
wird hier gezielt vorgegeben.
"""
from __future__ import annotations

import threading
import types

import pytest
from PyQt6.QtWidgets import QLabel, QTabWidget, QWidget

from src.gui.chat_view import ChatView
from src.ml import ollama_launcher
from src.rag.rag_controller import RAGResponse
from src.utils.config import ChatConfig
from tests.conftest import patch_singletons

ABSTURZ_ROH = ("Ollama HTTP 500: llama-server process has terminated: exit status 2. "
               "The system does not have enough memory to load the model")
ABSTURZ_HINWEIS = ("Das Modell „gpt-oss:20b“ ist abgestürzt, meist weil der Grafikspeicher nicht "
                   "reicht. In den Einstellungen ein kleineres Modell wählen oder Ollama neu starten.")


# --------------------------------------------------------------------- #
# Chat (#356)
# --------------------------------------------------------------------- #


class _StubLLM:
    llm_provider = None

    def is_llm_available(self) -> bool:
        return False


@pytest.fixture
def chat_view(qtbot, tmp_path, monkeypatch):
    from src.utils import config as cfg_mod
    from src.utils.database import Database

    cfg = cfg_mod.Config(config_path=tmp_path / "config.json")
    db = Database(db_path=str(tmp_path / "chat356.db"))
    patch_singletons(monkeypatch, {"get_config": lambda: cfg, "get_database": lambda: db})
    view = ChatView(db=db, hybrid_classifier=_StubLLM(), chat_config=ChatConfig())
    qtbot.addWidget(view)
    return view


def _bubbles(view: ChatView) -> list[QLabel]:
    labels = []
    for i in range(view.history_layout.count() - 1):
        labels += view.history_layout.itemAt(i).widget().findChildren(QLabel)
    return labels


def test_absturz_steht_als_eigene_vollstaendige_zeile_im_verlauf(chat_view):
    antwort = RAGResponse(answer_text="Die Rechnung kam im März.", used_llm=True,
                          ki_hinweis=ABSTURZ_HINWEIS, ki_fehler_roh=ABSTURZ_ROH, ohne_suche=True)
    chat_view._zeige_antwort(antwort)
    hinweise = [b for b in _bubbles(chat_view) if b.property("ki_hinweis")]
    assert len(hinweise) == 1
    zeile = hinweise[0]
    assert zeile.wordWrap()  # bricht um statt rechts abgeschnitten zu werden
    assert "abgestürzt" in zeile.text() and "kleineres Modell" in zeile.text()
    assert "HTTP 500" not in zeile.text()
    assert ABSTURZ_ROH in zeile.toolTip()
    texte = [b.text() for b in _bubbles(chat_view)]
    # Reihenfolge: Hinweis, Antwort, Satz „ohne Suche“
    assert texte.index(zeile.text()) < next(i for i, t in enumerate(texte) if "März" in t)
    ohne = [b for b in _bubbles(chat_view) if b.property("ohne_suche")]
    assert len(ohne) == 1 and "ohne eigene Suche" in ohne[0].text()


def test_ohne_fehler_kein_hinweis(chat_view):
    chat_view._zeige_antwort(RAGResponse(answer_text="Alles gut.", used_llm=True))
    assert not [b for b in _bubbles(chat_view) if b.property("ki_hinweis") or b.property("ohne_suche")]


def test_hinweis_auch_wenn_gar_keine_antwort_kam(chat_view):
    chat_view._zeige_antwort(RAGResponse(answer_text="LLM-Aufruf fehlgeschlagen: …", used_llm=False,
                                         ki_hinweis=ABSTURZ_HINWEIS, ki_fehler_roh=ABSTURZ_ROH))
    assert [b for b in _bubbles(chat_view) if b.property("ki_hinweis")]


class _LangsamerController:
    """ask() wartet, bis der Test ``weiter`` setzt - so laesst sich mitten in der Antwort der Reiter wechseln."""

    def __init__(self):
        self.weiter = threading.Event()
        self.chat_session = object()

    def reset(self) -> None:
        pass

    def ask(self, question, bezug=None, **_):
        self.weiter.wait(10)
        return RAGResponse(answer_text="Fertig trotz Reiterwechsel.", used_llm=True)


def test_reiterwechsel_waehrend_der_antwort_haelt_den_chat_nicht_an(qtbot, chat_view):
    """Issue #356, „Zu prüfen“: Der Chat arbeitet weiter, wenn man den Reiter wechselt."""
    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    tabs.addTab(chat_view, "Chat")
    tabs.addTab(QWidget(), "Sortieren")
    tabs.show()
    controller = _LangsamerController()
    chat_view._controller = controller
    chat_view.input_edit.setPlainText("Wann kam die Rechnung?")
    chat_view._on_send()
    tabs.setCurrentIndex(1)  # weg vom Chat
    assert chat_view.isHidden() or not chat_view.isVisible()
    controller.weiter.set()
    qtbot.waitUntil(lambda: any("Reiterwechsel" in b.text() for b in _bubbles(chat_view)), timeout=5000)
    assert chat_view.send_btn.text() == "Senden"
    # Der Chat gehoert der Fixture (qtbot raeumt ihn auf), nicht dem Reiter-Widget
    tabs.removeTab(0)
    chat_view.setParent(None)


# --------------------------------------------------------------------- #
# Einstellungen (#390, #343)
# --------------------------------------------------------------------- #


@pytest.fixture
def fresh_config(monkeypatch, tmp_path):
    from src.core import pdf_cache as pc_mod
    from src.ml import classifier as cl_mod
    from src.ml import hybrid_classifier as hc_mod
    from src.utils import config as cfg_mod
    from src.utils import database as db_mod

    fresh = cfg_mod.Config(config_path=tmp_path / "config.json")
    fresh.set("persist_pdf_cache", False)
    monkeypatch.setattr(pc_mod.PDFCache, "_instance", None)
    patch_singletons(monkeypatch, {
        "get_config": lambda: fresh,
        "get_database": lambda: db_mod.Database(db_path=str(tmp_path / "t.db")),
        "get_classifier": cl_mod.PDFClassifier,
        "get_hybrid_classifier": hc_mod.HybridClassifier,
        "get_pdf_cache": pc_mod.PDFCache,
    })
    return fresh


def _ollama_mit_modell(config, modell):
    llm = config.get_llm_config()
    llm.update({"provider": "ollama", "model": modell})
    config.set("llm", llm)


def _dialog(qtbot):
    from src.gui.settings_dialog import SettingsDialog
    d = SettingsDialog()
    qtbot.addWidget(d)
    return d


def test_einstellungen_zeigen_installierte_modelle_und_markieren_fehlendes(qtbot, fresh_config, monkeypatch):
    monkeypatch.setattr(ollama_launcher, "ollama_lage", lambda url: (True, ["gemma3:4b", "qwen3:8b"]))
    _ollama_mit_modell(fresh_config, "gpt-oss:20b")
    d = _dialog(qtbot)
    eintraege = [d.model_combo.itemText(i) for i in range(d.model_combo.count())]
    assert eintraege == ["gpt-oss:20b (nicht installiert)", "gemma3:4b", "qwen3:8b"]
    assert d.model_combo.currentIndex() == 0
    status = d.ollama_status_label.text()
    assert not d.ollama_status_label.isHidden()
    assert "Ollama läuft" in status and "„gpt-oss:20b“ ist nicht installiert" in status
    assert "ein bis zwei Minuten" in status  # Issue #343
    # Nichts wird still umgestellt: Speichern behaelt den Namen
    d._apply_settings()
    assert fresh_config.get_llm_config()["model"] == "gpt-oss:20b"
    # Erst die Wahl eines installierten Modells stellt um
    d.model_combo.setCurrentIndex(2)
    d._apply_settings()
    assert fresh_config.get_llm_config()["model"] == "qwen3:8b"


def test_einstellungen_installiertes_modell_ohne_markierung(qtbot, fresh_config, monkeypatch):
    monkeypatch.setattr(ollama_launcher, "ollama_lage", lambda url: (True, ["gemma3:4b"]))
    _ollama_mit_modell(fresh_config, "gemma3:4b")
    d = _dialog(qtbot)
    assert [d.model_combo.itemText(i) for i in range(d.model_combo.count())] == ["gemma3:4b"]
    assert "1 Modell(e) installiert" in d.ollama_status_label.text()


def test_einstellungen_ollama_laeuft_nicht(qtbot, fresh_config):
    _ollama_mit_modell(fresh_config, "gpt-oss:20b")  # ollama_lage: (False, []) aus conftest
    d = _dialog(qtbot)
    status = d.ollama_status_label.text()
    assert "Ollama läuft nicht" in status and "ein bis zwei Minuten" in status
    assert d.model_combo.count() > 0  # Vorschlaege wie bisher
    assert "nicht installiert" not in d.model_combo.itemText(0)


def test_statuszeile_nur_bei_ollama(qtbot, fresh_config):
    _ollama_mit_modell(fresh_config, "gpt-oss:20b")
    d = _dialog(qtbot)
    d.provider_combo.setCurrentIndex(d._index_for_provider("openrouter"))
    assert d.ollama_status_label.isHidden()


# --------------------------------------------------------------------- #
# Fenster „Hintergrund-Analyse“ (#390)
# --------------------------------------------------------------------- #


def _fenster(modell="gpt-oss:20b", provider_name="Ollama"):
    """Fenster-Attrappe mit den echten MainWindow-Methoden fuer die Ollama-Lage."""
    from src.gui.main_window import MainWindow

    hc = types.SimpleNamespace(
        get_llm_provider_name=lambda: provider_name,
        get_llm_model_name=lambda short=False: modell,
        llm_provider=types.SimpleNamespace(_get_base_url=lambda: "http://localhost:11434"),
    )
    gesetzt = []
    win = types.SimpleNamespace(
        hybrid_classifier=hc, aufrufe=[],
        config=types.SimpleNamespace(set_llm_model=gesetzt.append), gesetzt=gesetzt,
        statusbar=types.SimpleNamespace(showMessage=lambda *a: None),
    )
    win._on_settings_changed = lambda: win.aufrufe.append("einstellungen")
    for name in ("_ollama_lage_fuer_dialog", "_ollama_modell_uebernehmen"):
        setattr(win, name, types.MethodType(getattr(MainWindow, name), win))
    return win


def _modell_fehlt():
    from src.ml.llm_hinweis import ki_hinweis
    return ki_hinweis("Ollama", "Ollama HTTP 404: model 'gpt-oss:20b' not found", "gpt-oss:20b")


def test_dialog_ollama_laeuft_modell_fehlt_nennt_installierte(monkeypatch):
    monkeypatch.setattr(ollama_launcher, "ollama_lage", lambda url: (True, ["gemma3:4b", "qwen3:8b"]))
    lage = _fenster()._ollama_lage_fuer_dialog("fehler", _modell_fehlt())
    text = "\n".join(lage["zeilen"])
    assert "Ollama läuft" in text and "gemma3:4b, qwen3:8b" in text
    assert lage["hinweis"].art == "modell_fehlt" and "„gpt-oss:20b“" in lage["hinweis"].problem
    assert lage["modelle"] == ["gemma3:4b", "qwen3:8b"] and not lage["starten"]


def test_dialog_ollama_laeuft_nicht_bietet_start_an(monkeypatch):
    monkeypatch.setattr(ollama_launcher, "find_ollama_executable", lambda: "C:/Ollama/ollama.exe")
    lage = _fenster()._ollama_lage_fuer_dialog("fehler", _modell_fehlt())
    assert lage["starten"] and lage["hinweis"].art == "laeuft_nicht"
    assert "Ollama läuft nicht" in lage["zeilen"][0]
    assert lage["modelle"] == []


def test_dialog_ollama_nicht_gefunden_sagt_wie_man_startet(monkeypatch):
    monkeypatch.setattr(ollama_launcher, "find_ollama_executable", lambda: None)
    lage = _fenster()._ollama_lage_fuer_dialog("fehler", _modell_fehlt())
    assert not lage["starten"] and "ollama.com" in lage["hinweis"].abhilfe


def test_dialog_ohne_fehler_oder_anderer_anbieter_fragt_nicht(monkeypatch):
    def verboten(url):
        raise AssertionError("Ollama gefragt")
    monkeypatch.setattr(ollama_launcher, "ollama_lage", verboten)
    assert _fenster()._ollama_lage_fuer_dialog("bereit", None) is None
    assert _fenster(provider_name="OpenRouter")._ollama_lage_fuer_dialog("fehler", _modell_fehlt()) is None


def test_modell_uebernehmen_erst_nach_klick(monkeypatch):
    win = _fenster()
    assert win._ollama_modell_uebernehmen(["gemma3:4b"])
    assert win.gesetzt == ["gemma3:4b"] and win.aufrufe == ["einstellungen"]

    from src.gui import main_window
    monkeypatch.setattr(main_window.QInputDialog, "getItem",
                        staticmethod(lambda *a, **k: ("qwen3:8b", True)))
    assert win._ollama_modell_uebernehmen(["gemma3:4b", "qwen3:8b"])
    assert win.gesetzt[-1] == "qwen3:8b"

    monkeypatch.setattr(main_window.QInputDialog, "getItem",
                        staticmethod(lambda *a, **k: ("", False)))  # Abbrechen
    assert not win._ollama_modell_uebernehmen(["gemma3:4b", "qwen3:8b"])
    assert len(win.gesetzt) == 2

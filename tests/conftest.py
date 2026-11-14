"""Gemeinsame Test-Helfer.

Die Module unter ``src`` importieren ihre Singleton-Fabriken (``get_config``,
``get_database``, ...) auf Modulebene (``from src.utils.config import get_config``).
Ein Patch nur im Ursprungsmodul greift daher nicht - jedes importierende Modul
haelt seine eigene Referenz, und zwar die, die beim *ersten* Import gebunden
wurde. Ohne diesen Helfer laufen GUI-Tests je nach Import-Reihenfolge gegen die
echte Nutzer-Config in %APPDATA% oder gegen die Temp-Config eines frueheren Tests.
"""
from __future__ import annotations

import importlib
import os
import sys

# Die Tests pruefen deutsche Texte. Die Sprache der Oberflaeche (src/i18n) wird
# deshalb fest auf Deutsch gestellt, unabhaengig von der Systemsprache des
# Rechners (CI laeuft englisch) und von der Konfiguration des Nutzers. Muss vor
# dem ersten Import eines src-Moduls stehen.
os.environ["PDFSM_LANGUAGE"] = "de"

import pytest

# Module, die Singleton-Fabriken auf Modulebene importieren. Werden vor dem
# Patchen importiert, damit ihre Referenzen sicher ersetzt werden.
_MODULES_WITH_FACTORY_IMPORTS = (
    "src.utils.database",
    "src.ml.classifier",
    "src.ml.hybrid_classifier",
    "src.core.pdf_cache",
    "src.gui.setup_wizard",
    "src.gui.settings_dialog",
    "src.gui.main_window",
)


def patch_singletons(monkeypatch: pytest.MonkeyPatch, factories: dict[str, object]) -> None:
    """Ersetzt Fabrik-Funktionen (z.B. ``get_config``) in *allen* src-Modulen.

    Args:
        monkeypatch: pytest-MonkeyPatch (macht die Patches nach dem Test rueckgaengig)
        factories: {"get_config": lambda: cfg, "get_database": lambda: db, ...}
    """
    for name in _MODULES_WITH_FACTORY_IMPORTS:
        importlib.import_module(name)

    # Hintergrund-Threads (Warmup, Modell-Laden, Pre-Cache) importieren evtl.
    # gerade ein Modul -> sys.modules aendert sich waehrend list(): kurz erneut
    # versuchen statt den Test mit "dictionary changed size" abzubrechen.
    for _ in range(50):
        try:
            modules = list(sys.modules.items())
            break
        except RuntimeError:
            continue
    else:
        modules = list(sys.modules.items())
    for mod_name, mod in modules:
        if mod is None or not mod_name.startswith("src"):
            continue
        for attr, factory in factories.items():
            if hasattr(mod, attr):
                monkeypatch.setattr(mod, attr, factory)


@pytest.fixture
def fresh_config(monkeypatch, tmp_path):
    """Frische Config in tmp_path, in allen Modulen als ``get_config`` verdrahtet."""
    from src.utils import config as cfg_mod

    cfg = cfg_mod.Config(config_path=tmp_path / "config.json")
    patch_singletons(monkeypatch, {"get_config": lambda: cfg})
    return cfg


@pytest.fixture(autouse=True)
def _index_meldungen_aus():
    """Schreibmeldungen an den Suchindex (FileManager, Hauptfenster) sind in Tests abgeschaltet:
    Die Standardquelle liest die Konfiguration des Nutzers. Tests, die die Meldungen brauchen,
    rufen ``meldungen.konfigurieren(lambda: Suchindex(konfig))`` selbst auf."""
    from src.search.meldungen import meldungen

    alt = meldungen._quelle
    meldungen.konfigurieren(None)
    yield
    meldungen.warten(5.0)
    meldungen.konfigurieren(alt)


@pytest.fixture(autouse=True)
def suchprotokoll_im_temp(monkeypatch, tmp_path_factory):
    """Protokoll (``suche.log``) und Standardorte der Dokumentensuche nie im echten Datenverzeichnis.

    ``indexer.logging_einrichten`` haengt den Datei-Handler einmal je Prozess an;
    ohne diese Umleitung schrieben danach alle Indextests in das Protokoll des Nutzers.
    """
    from src.search import konfig as konfig_modul

    ordner = tmp_path_factory.getbasetemp() / "appdata-suche"
    monkeypatch.setattr(konfig_modul, "get_app_data_dir", lambda create=True: ordner)


@pytest.fixture(autouse=True)
def kein_echtes_mac_office(monkeypatch):
    """Kein Test steuert ein echtes Word/Excel auf dem Mac (AppleScript).

    Sonst wuerden Tests, die nur LibreOffice simulieren, auf einem Mac mit
    Office dessen echtes Word starten. Tests des Mac-Wegs patchen gezielt.
    """
    from src.core import office_convert

    monkeypatch.setattr(office_convert, "mac_office_verfuegbar", lambda art: False)


@pytest.fixture(autouse=True)
def ordner_beobachtung_ohne_takt(monkeypatch):
    """Kein Hauptfenster eines Tests liest von sich aus alle zwei Sekunden den Scan-Ordner
    (Issue #232): Kacheln entstehen und verschwinden in Tests nur durch den Test selbst.
    Tests der Beobachtung rufen deren Schritte auf oder stellen ``AUTOMATISCH`` wieder an."""
    from src.gui import ordner_beobachtung

    monkeypatch.setattr(ordner_beobachtung, "AUTOMATISCH", False)


@pytest.fixture(autouse=True)
def doppelte_hinweis_aus(monkeypatch):
    """Kein Test bekommt von sich aus Hinweise oder Rueckfragen zu doppelten Dateien
    (Issue #245): Viele Tests legen mehrere Dateien mit demselben Inhalt an. Die Tests
    des Hinweises stellen ``AUTOMATISCH`` wieder an."""
    from src.gui import doppelte

    monkeypatch.setattr(doppelte, "AUTOMATISCH", False)


@pytest.fixture(autouse=True)
def kein_echtes_ollama_fuer_die_bedeutungssuche(monkeypatch):
    """Kein Test fragt ein echtes Ollama nach Bedeutungsvektoren oder Modellen (Issue #230).

    Tests der Bedeutungssuche ersetzen ``bedeutung._anfrage`` selbst und gewinnen damit."""
    from src.search import bedeutung

    def gesperrt(url, pfad, daten, zeitlimit):
        raise bedeutung.BedeutungFehler("Ollama ist in Tests abgeschaltet")

    monkeypatch.setattr(bedeutung, "_anfrage", gesperrt)


@pytest.fixture(autouse=True)
def fenster_aus(monkeypatch):
    """Kein Test sucht oder aktiviert echte Fenster (``src.search.fenster``, nur Windows)."""
    from src.search import fenster

    monkeypatch.setattr(fenster, "AKTIV", False)


@pytest.fixture(autouse=True)
def kein_echter_papierkorb(monkeypatch, tmp_path_factory):
    """Kein Test legt Dateien in den echten System-Papierkorb (Issue #124).

    ``QFile.moveToTrash`` verschiebt stattdessen in einen Test-Ordner. Tests,
    die den Papierkorb gezielt ersetzen (z. B. Fehlschlag), patchen danach
    selbst und gewinnen damit.
    """
    import os
    import shutil

    from PyQt6.QtCore import QFile

    trash = tmp_path_factory.mktemp("papierkorb")

    def move_to_trash(pfad):
        ziel = trash / os.path.basename(str(pfad))
        shutil.move(str(pfad), str(ziel))
        return True, str(ziel)

    monkeypatch.setattr(QFile, "moveToTrash", staticmethod(move_to_trash))


@pytest.fixture(autouse=True)
def zeitplan_speicher(monkeypatch):
    """Kein Test richtet echte Aufgaben ein (Windows-Aufgabenplanung, macOS-LaunchAgent).

    ``zeitplan.backend()`` liefert in Tests einen ``Speicher``, der die
    Eintraege nur merkt; ein Aufruf von ``schtasks``/``launchctl`` ueber
    ``zeitplan._ausfuehren`` schlaegt fehl. Tests der echten Backends geben
    ihren Ersatz fuer ``ausfuehren`` ausdruecklich mit.
    """
    from src.search import zeitplan

    def gesperrt(args):
        raise AssertionError(f"Test wollte das Betriebssystem aufrufen: {args}")

    speicher = zeitplan.Speicher()
    monkeypatch.setattr(zeitplan, "_backend_fuer_tests", speicher)
    monkeypatch.setattr(zeitplan, "_ausfuehren", gesperrt)
    return speicher


@pytest.fixture(autouse=True)
def original_dialog_und_ocr_aus(monkeypatch):
    """Kein Test blockiert in der Frage "Original in den Papierkorb?" (Issues #184/#187) oder liest
    die Tesseract-Einstellungen des Nutzers: Standard ist "Nein, behalten" und "keine Texterkennung".
    Tests dazu patchen ``_frage`` bzw. ``bild_convert.ocr_einstellungen`` selbst und gewinnen damit."""
    from src.core import bild_convert
    from src.gui import original_wegraeumen

    monkeypatch.setattr(original_wegraeumen, "_frage", lambda parent, text: (False, False))
    monkeypatch.setattr(bild_convert, "ocr_einstellungen", lambda: None)


@pytest.fixture(autouse=True)
def stapel_rueckfrage_ja(monkeypatch):
    """Kein Test blockiert in der Rueckfrage "Mehrere Dateien verschieben/umbenennen" (Issue #218):
    Standard ist der erste Knopf ("Verschieben und umbenennen" bzw. "Umbenennen und speichern").
    Tests dazu patchen ``stapel_rueckfrage.frage`` selbst und gewinnen damit."""
    from src.gui import stapel_rueckfrage

    monkeypatch.setattr(stapel_rueckfrage, "frage", lambda *args, **kwargs: stapel_rueckfrage.UMBENENNEN)


@pytest.fixture(autouse=True)
def keine_echten_ki_assistenten(monkeypatch):
    """Kein Test fragt das echte Claude Code (``claude mcp ...``) oder liest bzw. schreibt die echte
    Konfiguration von Claude Desktop (Einstellungen › Suche › KI-Assistenten, Baustein 3 aus
    docs/CHAT_MCP_PLAN.md). Beide gelten als nicht gefunden; Tests dazu patchen
    ``claude_programm`` bzw. ``claude_desktop_konfig`` selbst und gewinnen damit."""
    from src.search import mcp_einrichtung

    monkeypatch.setattr(mcp_einrichtung, "claude_programm", lambda: None)
    monkeypatch.setattr(mcp_einrichtung, "claude_desktop_konfig", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def schlagwort_quelle_aus():
    """Die Liste der schon benutzten Schlagwoerter (Issue #231) haengt nach keinem Test mehr am Index
    eines frueheren Hauptfensters: ohne Quelle gibt es keine Vorschlaege und keinen Abschnitt im KI-Prompt."""
    from src.core import schlagwoerter

    schlagwoerter.quelle_setzen(None)
    yield
    schlagwoerter.quelle_setzen(None)


@pytest.fixture(autouse=True)
def einheiten_quelle_aus():
    """Die gelernten Einheiten (Issue #257) haengen nach keinem Test mehr an der Datenbank eines
    frueheren Hauptfensters: ohne Quelle nennt der KI-Prompt keine Einheiten."""
    from src.core import einheiten

    einheiten.quelle_setzen(None)
    yield
    einheiten.quelle_setzen(None)

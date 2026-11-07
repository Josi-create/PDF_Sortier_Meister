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
import sys

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

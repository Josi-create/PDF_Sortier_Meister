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

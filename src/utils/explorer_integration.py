"""
Windows-Explorer-Integration fuer PDF Sortier Meister.

Stellt zwei Mechanismen bereit:

1. Launcher-Trampolin: Beim Start des Programms wird unter
   %APPDATA%\\PDF_Sortier_Meister\\launcher.cmd eine kleine Batch-Datei
   geschrieben, die das Programm so startet, wie es zuletzt gestartet wurde
   (entweder die eingefrorene .exe oder pythonw run.py). Der Registry-
   Eintrag verweist immer auf diese feste Datei, sodass die Integration
   bei einer Neuinstallation NICHT neu eingerichtet werden muss.

2. Registry-Eintraege unter HKCU\\Software\\Classes\\Directory\\shell\\...
   fuer den Rechtsklick auf einen Ordner UND auf dessen leeren
   Hintergrund. Kein Admin-Recht notwendig.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("pdf_sortier_meister.explorer_integration")

# Name unter dem der Eintrag im Registry-Pfad erscheint.
REGISTRY_KEY_NAME = "PDFSortierMeister"
# Beschriftung die im Kontextmenue erscheint.
CONTEXT_MENU_LABEL = "PDF Sortier Meister von hier oeffnen"


def _app_data_dir() -> Path:
    """Liefert das Datenverzeichnis (gleich wie Config.data_dir)."""
    app_data = os.environ.get("APPDATA", os.path.expanduser("~"))
    path = Path(app_data) / "PDF_Sortier_Meister"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _launcher_cmd_path() -> Path:
    """Pfad der festen Trampolin-Batch-Datei."""
    return _app_data_dir() / "launcher.cmd"


def _running_as_frozen() -> bool:
    """True, wenn das Programm als PyInstaller-Bundle laeuft."""
    return getattr(sys, "frozen", False)


def _current_launch_command() -> str:
    """
    Liefert den Befehl, mit dem das aktuell laufende Programm gestartet
    wurde, in einer Form, die im Batch-Skript per `start ""` benutzt
    werden kann. Der uebergebene Ordner-Pfad wird durch %* angehaengt.
    """
    if _running_as_frozen():
        exe = Path(sys.executable).resolve()
        return f'"{exe}"'

    # Dev-Modus: pythonw bevorzugt (kein Konsolenfenster), sonst python.
    py_dir = Path(sys.executable).parent
    pythonw = py_dir / "pythonw.exe"
    python_exe = Path(sys.executable).resolve()
    if pythonw.exists():
        python_exe = pythonw.resolve()

    # run.py liegt im Projekt-Root (zwei Ebenen ueber dieser Datei).
    # src/utils/explorer_integration.py -> src/utils -> src -> repo-root
    repo_root = Path(__file__).resolve().parent.parent.parent
    run_script = repo_root / "run.py"

    return f'"{python_exe}" "{run_script}"'


def update_launcher_script() -> Path:
    """
    Schreibt/aktualisiert das Trampolin-Skript launcher.cmd mit dem
    AKTUELLEN Startbefehl. Wird bei jedem Programmstart aufgerufen, damit
    der Registry-Eintrag immer korrekt auflaeuft.

    Returns:
        Den Pfad der geschriebenen cmd-Datei.
    """
    cmd_path = _launcher_cmd_path()
    launch_cmd = _current_launch_command()

    # %~1 entfernt umgebende Anfuehrungszeichen, falls vorhanden.
    # `start "" /D ...` setzt das Arbeitsverzeichnis nicht zwingend,
    # darum uebergeben wir den Ordner als Argument an das Programm.
    content = (
        "@echo off\r\n"
        "REM Auto-generiert von PDF Sortier Meister bei jedem Programmstart.\r\n"
        "REM Nicht von Hand editieren - der Inhalt wird ueberschrieben.\r\n"
        f'start "" {launch_cmd} %*\r\n'
    )

    try:
        cmd_path.write_text(content, encoding="utf-8")
    except OSError as e:
        logger.warning(f"Launcher-Skript konnte nicht geschrieben werden: {e}")
    return cmd_path


# === Registry ===

def _ensure_winreg():
    """Importiert winreg oder wirft eine aussagekraeftige Fehlermeldung."""
    if sys.platform != "win32":
        raise RuntimeError(
            "Explorer-Integration ist nur unter Windows verfuegbar."
        )
    import winreg  # type: ignore
    return winreg


# Beide Pfade werden gesetzt:
#  - Directory\shell:            Rechtsklick AUF einen Ordner
#  - Directory\Background\shell: Rechtsklick IM leeren Bereich eines Ordners
_REGISTRY_PATHS = [
    (r"Software\Classes\Directory\shell\{name}", "%1"),
    (r"Software\Classes\Directory\Background\shell\{name}", "%V"),
]


def is_context_menu_registered() -> bool:
    """Prueft, ob mindestens einer der Registry-Eintraege existiert."""
    try:
        winreg = _ensure_winreg()
    except RuntimeError:
        return False

    for path_template, _arg in _REGISTRY_PATHS:
        path = path_template.format(name=REGISTRY_KEY_NAME)
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path):
                return True
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return False


def register_context_menu() -> None:
    """
    Setzt die Registry-Eintraege fuer das Explorer-Kontextmenue.
    Stellt vorher sicher, dass das Launcher-Skript existiert.
    """
    winreg = _ensure_winreg()

    launcher = update_launcher_script()
    if not launcher.exists():
        raise RuntimeError(f"Launcher-Skript fehlt: {launcher}")

    # Icon: bevorzugt die laufende .exe, sonst leer.
    icon_path = ""
    if _running_as_frozen():
        icon_path = str(Path(sys.executable).resolve())

    for path_template, arg_token in _REGISTRY_PATHS:
        key_path = path_template.format(name=REGISTRY_KEY_NAME)
        command_path = key_path + r"\command"

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, CONTEXT_MENU_LABEL)
            if icon_path:
                winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, icon_path)

        # Befehl: "launcher.cmd" "<ordner>"
        command_value = f'"{launcher}" "{arg_token}"'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, command_path) as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, command_value)

    logger.info("Explorer-Kontextmenue registriert.")


def unregister_context_menu() -> None:
    """Entfernt die Registry-Eintraege wieder (Launcher-Skript bleibt)."""
    winreg = _ensure_winreg()

    for path_template, _arg in _REGISTRY_PATHS:
        key_path = path_template.format(name=REGISTRY_KEY_NAME)
        command_path = key_path + r"\command"

        # command-Unterschluessel zuerst loeschen.
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, command_path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f"Konnte {command_path} nicht loeschen: {e}")

        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f"Konnte {key_path} nicht loeschen: {e}")

    logger.info("Explorer-Kontextmenue entfernt.")

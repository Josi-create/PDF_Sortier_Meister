"""
Auto-Start fuer einen lokalen Ollama-Server.

Wird vom OllamaProvider lazy aufgerufen, wenn der erste API-Call mit
einem Verbindungsfehler scheitert. So bleibt der Programmstart schnell:
Die Probe und der Start passieren erst beim ersten LLM-Bedarf.

Strategie:
1. Quick-Ping (1s Timeout) - laeuft Ollama schon? -> ok.
2. ollama.exe an Standardpfaden suchen, dann im PATH.
3. `ollama serve` als detached Hintergrundprozess starten.
4. Auf Bereitschaft warten (max. ~10s, Polling alle 500ms).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger("pdf_sortier_meister.ollama_launcher")

# Relative Pfade unter %LOCALAPPDATA%, in denen der Standard-Installer die
# ollama.exe ablegt.
_WINDOWS_RELATIVE_PATHS = [
    "Programs/Ollama/ollama.exe",
]


def find_ollama_executable() -> Optional[str]:
    """Liefert den Pfad zur ollama.exe oder None, wenn nicht gefunden."""
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        if local_appdata:
            for rel in _WINDOWS_RELATIVE_PATHS:
                p = Path(local_appdata) / rel
                if p.exists():
                    return str(p)

    # Fallback: ollama im PATH
    found = shutil.which("ollama")
    if found:
        return found
    return None


def quick_ping(base_url: str, timeout: float = 1.0) -> bool:
    """Schneller Erreichbarkeits-Check ohne Logging."""
    url = f"{base_url.rstrip('/')}/api/version"
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except Exception:
        return False


def _start_server_process(exe_path: str) -> bool:
    """Startet `ollama serve` als losgeloesten Hintergrundprozess."""
    try:
        if sys.platform == "win32":
            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP - der Server
            # ueberlebt das Beenden von PDF Sortier Meister und blockiert
            # nicht durch ein offenes Konsolenfenster.
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            CREATE_NO_WINDOW = 0x08000000
            flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
            subprocess.Popen(
                [exe_path, "serve"],
                creationflags=flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )
        else:
            subprocess.Popen(
                [exe_path, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        return True
    except OSError as e:
        logger.warning(f"Konnte ollama.exe nicht starten: {e}")
        return False


def ensure_running(base_url: str, max_wait: float = 10.0) -> tuple[bool, str]:
    """
    Stellt sicher, dass der Ollama-Server unter ``base_url`` erreichbar
    ist. Falls nicht, sucht die Executable und startet sie.

    Args:
        base_url: z.B. "http://localhost:11434"
        max_wait: maximale Wartezeit nach dem Start in Sekunden.

    Returns:
        (ok, message). Bei Erfolg enthaelt message den Pfad zur
        gestarteten Executable bzw. einen Hinweis, dass schon lief.
    """
    if quick_ping(base_url, timeout=1.0):
        return True, "Ollama war bereits erreichbar."

    exe = find_ollama_executable()
    if not exe:
        return False, (
            "ollama.exe wurde nicht gefunden. Bitte Ollama installieren "
            "(https://ollama.com) oder das Programm in den PATH legen."
        )

    if not _start_server_process(exe):
        return False, f"ollama.exe ({exe}) konnte nicht gestartet werden."

    logger.info(f"Ollama-Server gestartet: {exe}")

    # Auf Bereitschaft warten - der Server braucht einen Moment.
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if quick_ping(base_url, timeout=1.0):
            return True, f"Ollama-Server gestartet ({exe})."

    return False, (
        f"Ollama-Server wurde gestartet, antwortet aber nicht innerhalb "
        f"von {max_wait:.0f} Sekunden. Bitte erneut versuchen."
    )

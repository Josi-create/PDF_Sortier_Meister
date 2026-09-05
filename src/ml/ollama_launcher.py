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

import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("pdf_sortier_meister.ollama_launcher")

# Relative Pfade unter %LOCALAPPDATA%, in denen der Standard-Installer die
# ollama.exe ablegt.
_WINDOWS_RELATIVE_PATHS = [
    "Programs/Ollama/ollama.exe",
]

# Standard-Installationsorte unter macOS (Ollama.app bzw. Homebrew).
# Aus dem Finder gestartete Apps haben Homebrew nicht im PATH.
_MACOS_PATHS = [
    "/Applications/Ollama.app/Contents/Resources/ollama",
    "/opt/homebrew/bin/ollama",
    "/usr/local/bin/ollama",
]


def find_ollama_executable() -> Optional[str]:
    """Liefert den Pfad zur Ollama-Binary oder None, wenn nicht gefunden."""
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        if local_appdata:
            for rel in _WINDOWS_RELATIVE_PATHS:
                p = Path(local_appdata) / rel
                if p.exists():
                    return str(p)
    elif sys.platform == "darwin":
        for candidate in _MACOS_PATHS:
            if Path(candidate).exists():
                return candidate

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


def list_models(base_url: str, timeout: float = 5.0) -> list[str]:
    """Namen der lokal installierten Modelle (leer bei Fehler)."""
    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    return [m.get("name", "") for m in data.get("models", []) if m.get("name")]


def pull_model(
    base_url: str,
    model: str,
    progress_cb: Optional[Callable[[int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> tuple[bool, str]:
    """
    Laedt ein Modell ueber ``POST /api/pull`` (Streaming) herunter.

    Args:
        progress_cb: wird mit (Prozent 0-100, Statustext) aufgerufen
        should_cancel: liefert True, wenn der Download abgebrochen werden soll

    Returns:
        (ok, message)
    """
    url = f"{base_url.rstrip('/')}/api/pull"
    body = json.dumps({"name": model, "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return _consume_pull_stream(resp, progress_cb, should_cancel)
    except urllib.error.HTTPError as e:
        return False, http_error_text(e)
    except urllib.error.URLError as e:
        return False, f"Keine Verbindung zu Ollama ({base_url}): {e.reason}"
    except Exception as e:
        return False, f"Download-Fehler: {e}"


def http_error_text(error: urllib.error.HTTPError, limit: int = 300) -> str:
    """Lesbarer Fehlertext fuer eine HTTP-Fehlerantwort von Ollama.

    Ollama antwortet bei 4xx/5xx mit ``{"error": "..."}``, und dieser Text
    nennt den eigentlichen Grund - etwa ``llama runner process has
    terminated: exit status 0xc0000409``, wenn das Modell beim Laden
    abstuerzt. Nur ``Ollama HTTP 500`` zu loggen zwang bisher zum Blick in
    den Ollama-Server-Log. Ohne JSON wird der rohe Body genommen; leer bleibt
    es beim Statuscode.
    """
    try:
        raw = error.read().decode("utf-8", errors="replace").strip()
    except Exception:
        raw = ""
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("error"):
                raw = str(data["error"]).strip()
        except ValueError:
            pass
        raw = " ".join(raw.split())
        if len(raw) > limit:
            raw = raw[:limit] + "…"
    return f"Ollama HTTP {error.code}: {raw}" if raw else f"Ollama HTTP {error.code}"


def _consume_pull_stream(stream, progress_cb, should_cancel) -> tuple[bool, str]:
    """Verarbeitet die NDJSON-Zeilen von /api/pull (auch fuer Tests nutzbar)."""
    last_status = ""
    for raw in stream:
        if should_cancel and should_cancel():
            return False, "Download abgebrochen."
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("error"):
            return False, str(event["error"])
        status = event.get("status", "")
        total = event.get("total") or 0
        completed = event.get("completed") or 0
        percent = int(completed * 100 / total) if total else (100 if status == "success" else 0)
        if progress_cb and (status != last_status or total):
            progress_cb(percent, status)
        last_status = status
        if status == "success":
            return True, "Modell installiert."
    return False, "Download unvollstaendig (Verbindung beendet)."


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
        logger.warning(f"Konnte Ollama nicht starten: {e}")
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
            "Ollama wurde nicht gefunden. Bitte Ollama installieren "
            "(https://ollama.com) oder das Programm in den PATH legen."
        )

    if not _start_server_process(exe):
        return False, f"Ollama ({exe}) konnte nicht gestartet werden."

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

"""
Update-Pruefung gegen die GitHub-Releases (Issue #73).

Reine Logik ohne Qt, damit sie ohne GUI testbar ist. Es wird ausschliesslich
die oeffentliche Release-Info abgerufen (``releases/latest``); dabei werden
keine Daten ueber den Nutzer oder seine Dokumente uebertragen.

Draft- und Pre-Releases liefert der ``latest``-Endpunkt von GitHub nicht,
d.h. ein Release wird erst nach dem Veroeffentlichen als Update erkannt.
"""
from __future__ import annotations

import json
import platform
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

GITHUB_REPO = "Josi-create/PDF_Sortier_Meister"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"

# Feste Asset-Namen aus dem Release-Workflow (installer.iss / build.sh)
WINDOWS_ASSET = "PDF_Sortier_Meister_Setup.exe"
MACOS_ASSET_TEMPLATE = "PDF_Sortier_Meister-macos-{arch}.dmg"

DEFAULT_TIMEOUT = 3.0

_VERSION_RE = re.compile(r"^\s*v?(\d+(?:\.\d+)*)")


class UpdateCheckError(Exception):
    """Netzwerk- oder Antwortfehler bei der Update-Pruefung."""


@dataclass
class UpdateInfo:
    """Beschreibt ein verfuegbares Update."""

    version: str       # normalisiert, z.B. "0.19.0"
    tag: str           # Git-Tag, z.B. "v0.19.0"
    page_url: str      # Release-Seite auf GitHub
    download_url: str  # Direktlink zum passenden Installer (oder Release-Seite)
    asset_name: str = ""  # Dateiname des Installers, falls gefunden
    notes: str = ""    # Release-Notes (Markdown)


def parse_version(text: str) -> tuple[int, ...]:
    """Zerlegt "v0.19.0" / "0.19" in ein Tupel; leer bei unbrauchbarem Text."""
    if not text:
        return ()
    m = _VERSION_RE.match(str(text))
    if not m:
        return ()
    return tuple(int(part) for part in m.group(1).split("."))


def is_newer(candidate: str, current: str) -> bool:
    """True, wenn ``candidate`` eine hoehere Version als ``current`` ist."""
    a, b = parse_version(candidate), parse_version(current)
    if not a or not b:
        return False
    length = max(len(a), len(b))
    a += (0,) * (length - len(a))
    b += (0,) * (length - len(b))
    return a > b


def expected_asset_name(platform_name: str | None = None,
                        arch: str | None = None) -> str | None:
    """Name des Installer-Assets fuer diese Plattform (None = unbekannt)."""
    platform_name = platform_name or sys.platform
    if platform_name == "win32":
        return WINDOWS_ASSET
    if platform_name == "darwin":
        arch = (arch or platform.machine() or "").lower()
        arch = "arm64" if arch in ("arm64", "aarch64") else "x86_64"
        return MACOS_ASSET_TEMPLATE.format(arch=arch)
    return None


def pick_download(release: dict, platform_name: str | None = None,
                  arch: str | None = None) -> tuple[str, str]:
    """Liefert (download_url, asset_name) fuer diese Plattform.

    Faellt auf die Release-Seite zurueck, wenn kein passendes Asset existiert.
    """
    page_url = release.get("html_url") or RELEASES_PAGE_URL
    name = expected_asset_name(platform_name, arch)
    if name:
        for asset in release.get("assets") or []:
            if asset.get("name") == name and asset.get("browser_download_url"):
                return asset["browser_download_url"], name
    return page_url, ""


def fetch_latest_release(timeout: float = DEFAULT_TIMEOUT,
                         user_agent: str = "PDF-Sortier-Meister") -> dict:
    """Holt die JSON-Beschreibung des neuesten veroeffentlichten Releases."""
    req = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": user_agent,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_for_update(current_version: str,
                     fetch: Callable[[], dict] = fetch_latest_release,
                     platform_name: str | None = None,
                     arch: str | None = None) -> UpdateInfo | None:
    """Prueft, ob ein neueres Release als ``current_version`` existiert.

    Returns:
        UpdateInfo bei neuerer Version, sonst None.

    Raises:
        UpdateCheckError: bei Netzwerkfehlern oder unbrauchbarer Antwort.
    """
    try:
        release = fetch()
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UpdateCheckError(str(getattr(e, "reason", None) or e)) from e

    if not isinstance(release, dict):
        raise UpdateCheckError("Unerwartete Antwort von GitHub")

    tag = release.get("tag_name") or ""
    parsed = parse_version(tag)
    if not parsed:
        raise UpdateCheckError(f"Unbrauchbare Versionsangabe: {tag!r}")
    if not is_newer(tag, current_version):
        return None

    download_url, asset_name = pick_download(release, platform_name, arch)
    return UpdateInfo(
        version=".".join(str(p) for p in parsed),
        tag=tag,
        page_url=release.get("html_url") or RELEASES_PAGE_URL,
        download_url=download_url,
        asset_name=asset_name,
        notes=release.get("body") or "",
    )

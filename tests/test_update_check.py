"""Tests fuer die Update-Pruefung gegen GitHub Releases (Issue #73).

Reine Logik-Tests ohne Qt und ohne Netzwerk: ``fetch`` wird injiziert bzw.
``urllib.request.urlopen`` gepatcht.
"""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from src.utils import update_check as uc

# --------------------------------------------------------------------- #
# Versionsvergleich
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text, expected",
    [
        ("v0.19.0", (0, 19, 0)),
        ("0.19.0", (0, 19, 0)),
        ("  v1.2 ", (1, 2)),
        ("v0.19.0-beta", (0, 19, 0)),
        ("", ()),
        ("release", ()),
        (None, ()),
    ],
)
def test_parse_version(text, expected):
    assert uc.parse_version(text) == expected


@pytest.mark.parametrize(
    "candidate, current, newer",
    [
        ("v0.19.0", "0.18.0", True),
        ("v0.18.1", "0.18.0", True),
        ("v1.0.0", "0.18.0", True),
        ("v0.18.0", "0.18.0", False),
        ("v0.17.0", "0.18.0", False),
        ("v0.18", "0.18.0", False),     # aufgefuellt: 0.18.0 == 0.18.0
        ("v0.18.0.1", "0.18.0", True),
        ("kaputt", "0.18.0", False),
        ("v0.19.0", "", False),
    ],
)
def test_is_newer(candidate, current, newer):
    assert uc.is_newer(candidate, current) is newer


# --------------------------------------------------------------------- #
# Plattform-Asset
# --------------------------------------------------------------------- #


def test_expected_asset_name_windows():
    assert uc.expected_asset_name("win32") == "PDF_Sortier_Meister_Setup.exe"


@pytest.mark.parametrize("arch, expected", [
    ("arm64", "PDF_Sortier_Meister-macos-arm64.dmg"),
    ("aarch64", "PDF_Sortier_Meister-macos-arm64.dmg"),
    ("x86_64", "PDF_Sortier_Meister-macos-x86_64.dmg"),
    ("AMD64", "PDF_Sortier_Meister-macos-x86_64.dmg"),
])
def test_expected_asset_name_macos(arch, expected):
    assert uc.expected_asset_name("darwin", arch) == expected


def test_expected_asset_name_unknown_platform():
    assert uc.expected_asset_name("linux") is None


def _release(tag="v0.19.0", assets=None, **extra):
    data = {
        "tag_name": tag,
        "html_url": f"https://github.com/{uc.GITHUB_REPO}/releases/tag/{tag}",
        "body": "## Neu\n- Update-Check",
        "assets": assets if assets is not None else [
            {"name": "PDF_Sortier_Meister_Setup.exe",
             "browser_download_url": "https://dl/Setup.exe"},
            {"name": "PDF_Sortier_Meister-macos-arm64.dmg",
             "browser_download_url": "https://dl/arm64.dmg"},
        ],
    }
    data.update(extra)
    return data


def test_pick_download_finds_platform_asset():
    url, name = uc.pick_download(_release(), "win32")
    assert (url, name) == ("https://dl/Setup.exe", "PDF_Sortier_Meister_Setup.exe")
    url, name = uc.pick_download(_release(), "darwin", "arm64")
    assert (url, name) == ("https://dl/arm64.dmg", "PDF_Sortier_Meister-macos-arm64.dmg")


def test_pick_download_falls_back_to_release_page():
    rel = _release()
    # Intel-DMG fehlt im Release -> Release-Seite
    assert uc.pick_download(rel, "darwin", "x86_64") == (rel["html_url"], "")
    # Unbekannte Plattform -> Release-Seite
    assert uc.pick_download(rel, "linux") == (rel["html_url"], "")
    # Auch ohne html_url gibt es einen brauchbaren Link
    assert uc.pick_download({"assets": []}, "win32") == (uc.RELEASES_PAGE_URL, "")


# --------------------------------------------------------------------- #
# check_for_update
# --------------------------------------------------------------------- #


def test_check_for_update_returns_info_for_newer_release():
    info = uc.check_for_update("0.18.0", fetch=lambda: _release("v0.19.0"),
                               platform_name="win32")
    assert info is not None
    assert info.version == "0.19.0"
    assert info.tag == "v0.19.0"
    assert info.page_url.endswith("/releases/tag/v0.19.0")
    assert info.download_url == "https://dl/Setup.exe"
    assert info.asset_name == "PDF_Sortier_Meister_Setup.exe"
    assert "Update-Check" in info.notes


@pytest.mark.parametrize("tag", ["v0.18.0", "v0.17.5"])
def test_check_for_update_returns_none_when_current(tag):
    assert uc.check_for_update("0.18.0", fetch=lambda: _release(tag)) is None


def test_check_for_update_network_error_raises():
    def boom():
        raise urllib.error.URLError("Name or service not known")

    with pytest.raises(uc.UpdateCheckError) as exc:
        uc.check_for_update("0.18.0", fetch=boom)
    assert "Name or service not known" in str(exc.value)


def test_check_for_update_timeout_raises():
    def boom():
        raise TimeoutError("timed out")

    with pytest.raises(uc.UpdateCheckError):
        uc.check_for_update("0.18.0", fetch=boom)


@pytest.mark.parametrize("payload", [None, [], {"message": "Not Found"}, {"tag_name": "latest"}])
def test_check_for_update_bad_payload_raises(payload):
    with pytest.raises(uc.UpdateCheckError):
        uc.check_for_update("0.18.0", fetch=lambda: payload)


# --------------------------------------------------------------------- #
# fetch_latest_release: Request-Aufbau (ohne echtes Netz)
# --------------------------------------------------------------------- #


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


def test_fetch_latest_release_builds_request(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        seen["timeout"] = timeout
        return _FakeResponse(json.dumps(_release()).encode("utf-8"))

    monkeypatch.setattr(uc.urllib.request, "urlopen", fake_urlopen)

    data = uc.fetch_latest_release(timeout=1.5, user_agent="PDF-Sortier-Meister/0.18.0")

    assert data["tag_name"] == "v0.19.0"
    assert seen["url"] == uc.LATEST_RELEASE_API
    assert seen["url"].endswith("/releases/latest")
    assert seen["headers"]["accept"] == "application/vnd.github+json"
    assert seen["headers"]["user-agent"] == "PDF-Sortier-Meister/0.18.0"
    assert seen["timeout"] == 1.5


def test_fetch_latest_release_http_error_surfaces_as_update_check_error(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 403, "rate limited", {}, None)

    monkeypatch.setattr(uc.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(uc.UpdateCheckError):
        uc.check_for_update("0.18.0")

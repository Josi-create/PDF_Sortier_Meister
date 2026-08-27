"""Tests fuer die Plattform-Abstraktion (Datenverzeichnis, Dateimanager-Name).

Wichtigster Test: Der Windows-Pfad ist byte-identisch zum bisherigen
Inline-Ausdruck ``%APPDATA%\\PDF_Sortier_Meister`` - Bestandsnutzer duerfen
ihr Datenverzeichnis nicht verlieren.
"""

import os
import sys
from pathlib import Path

import pytest

from src.utils.platform_paths import file_manager_name, get_app_data_dir


def test_windows_path_matches_legacy_expression(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))

    legacy = Path(os.environ.get("APPDATA", os.path.expanduser("~"))) / "PDF_Sortier_Meister"
    assert get_app_data_dir(create=False) == legacy


def test_windows_fallback_home_without_appdata(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("APPDATA", raising=False)

    expected = Path(os.path.expanduser("~")) / "PDF_Sortier_Meister"
    assert get_app_data_dir(create=False) == expected


def test_darwin_path_is_application_support(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    expected = Path.home() / "Library" / "Application Support" / "PDF_Sortier_Meister"
    assert get_app_data_dir(create=False) == expected


def test_linux_respects_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    assert get_app_data_dir(create=False) == tmp_path / "xdg" / "PDF_Sortier_Meister"


def test_create_flag_creates_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))

    path = get_app_data_dir()
    assert path.is_dir()


@pytest.mark.parametrize(
    "platform, expected",
    [("win32", "Explorer"), ("darwin", "Finder"), ("linux", "Dateimanager")],
)
def test_file_manager_name(monkeypatch, platform, expected):
    monkeypatch.setattr(sys, "platform", platform)
    assert file_manager_name() == expected

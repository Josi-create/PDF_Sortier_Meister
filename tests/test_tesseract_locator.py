"""Tests fuer die Tesseract-Suche (gebuendelt -> Standardpfade -> PATH)."""

import sys

import pytest

from src.core.pdf_analyzer import _tesseract_candidates, find_tesseract


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Keine echte Tesseract-Installation darf durchschlagen (win32-Sicht)."""
    # Plattform pinnen, damit die Tests auch auf macOS/Linux-Runnern laufen.
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.setenv(var, str(tmp_path / var.replace("(", "").replace(")", "")))
    monkeypatch.setattr("src.core.pdf_analyzer.shutil.which", lambda _name: None)
    return tmp_path


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_none_when_nothing_installed(isolated_env):
    assert find_tesseract() is None


def test_bundled_wins_over_system_install(isolated_env, monkeypatch):
    system_exe = _touch(isolated_env / "ProgramFiles" / "Tesseract-OCR" / "tesseract.exe")
    bundle = isolated_env / "_internal"
    bundled_exe = _touch(bundle / "tesseract" / "tesseract.exe")
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)

    assert find_tesseract() == str(bundled_exe)
    assert system_exe.exists()  # nur zur Klarheit: beide existieren


def test_program_files_install(isolated_env):
    exe = _touch(isolated_env / "ProgramFiles" / "Tesseract-OCR" / "tesseract.exe")
    assert find_tesseract() == str(exe)


def test_per_user_install(isolated_env):
    exe = _touch(isolated_env / "LOCALAPPDATA" / "Programs" / "Tesseract-OCR" / "tesseract.exe")
    assert find_tesseract() == str(exe)


def test_path_fallback(isolated_env, monkeypatch):
    monkeypatch.setattr(
        "src.core.pdf_analyzer.shutil.which", lambda _name: r"D:\tools\tesseract.exe"
    )
    assert find_tesseract() == r"D:\tools\tesseract.exe"


# --- macOS-Suchpfade ---


@pytest.fixture
def darwin_env(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr("src.core.pdf_analyzer.shutil.which", lambda _name: None)


def test_darwin_candidates_contain_homebrew_paths(darwin_env):
    candidates = [str(p) for p in _tesseract_candidates()]
    assert "/opt/homebrew/bin/tesseract" in [c.replace("\\", "/") for c in candidates]
    assert "/usr/local/bin/tesseract" in [c.replace("\\", "/") for c in candidates]


def test_darwin_bundled_binary_first(darwin_env, tmp_path, monkeypatch):
    bundle = tmp_path / "_internal"
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    candidates = _tesseract_candidates()
    assert candidates[0] == bundle / "tesseract" / "tesseract"


def test_darwin_bundled_binary_found(darwin_env, tmp_path, monkeypatch):
    bundle = tmp_path / "_internal"
    bundled = bundle / "tesseract" / "tesseract"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"")
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    assert find_tesseract() == str(bundled)

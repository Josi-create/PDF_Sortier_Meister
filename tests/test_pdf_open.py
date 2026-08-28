"""Tests fuer das externe Oeffnen von PDFs (Issue #76) - ohne Qt, ohne echte Prozesse."""
from __future__ import annotations

import sys

import pytest

from src.utils import pdf_open as po


@pytest.fixture
def spies(monkeypatch):
    """Faengt Popen und das Standardprogramm ab."""
    calls = {"popen": [], "default": []}

    class _FakeProc:
        def __init__(self, args):
            calls["popen"].append(list(args))

    monkeypatch.setattr(po.subprocess, "Popen", _FakeProc)
    monkeypatch.setattr(po, "open_with_default_app", lambda p: calls["default"].append(p))
    return calls


@pytest.mark.parametrize("mode, expected", [
    ("integrated", "integrated"),
    ("system", "system"),
    ("custom", "custom"),
    ("", "integrated"),
    (None, "integrated"),
    ("browser", "integrated"),
])
def test_normalize_open_mode(mode, expected):
    assert po.normalize_open_mode(mode) == expected


def test_open_modes_order_starts_with_integrated():
    assert [m for m, _ in po.OPEN_MODES] == ["integrated", "system", "custom"]


def test_missing_file_is_reported(tmp_path, spies):
    ok, note = po.open_pdf_externally(tmp_path / "fehlt.pdf", "system")
    assert ok is False
    assert "nicht gefunden" in note
    assert spies["popen"] == [] and spies["default"] == []


def test_system_mode_uses_default_app(tmp_path, spies):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")

    ok, note = po.open_pdf_externally(pdf, "system")

    assert (ok, note) == (True, "")
    assert spies["default"] == [pdf]


def test_integrated_mode_falls_back_to_system_when_called_externally(tmp_path, spies):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")

    ok, _ = po.open_pdf_externally(pdf, "integrated")

    assert ok and spies["default"] == [pdf]


def test_custom_mode_launches_program(tmp_path, spies):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    exe = tmp_path / "PDFXEdit.exe"
    exe.write_bytes(b"MZ")

    ok, note = po.open_pdf_externally(pdf, "custom", str(exe))

    assert (ok, note) == (True, "")
    assert spies["popen"] == [[str(exe), str(pdf)]]
    assert spies["default"] == []


def test_custom_mode_without_program_falls_back_with_note(tmp_path, spies):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")

    ok, note = po.open_pdf_externally(pdf, "custom", "")

    assert ok is True
    assert "Standardprogramm" in note
    assert spies["default"] == [pdf]


def test_custom_mode_missing_program_falls_back_with_note(tmp_path, spies):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")

    ok, note = po.open_pdf_externally(pdf, "custom", str(tmp_path / "gibtsnicht.exe"))

    assert ok is True
    assert "nicht gefunden" in note
    assert spies["popen"] == [] and spies["default"] == [pdf]


def test_custom_mode_launch_error_falls_back(tmp_path, spies, monkeypatch):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    exe = tmp_path / "kaputt.exe"
    exe.write_bytes(b"MZ")

    def boom(args):
        raise OSError("Zugriff verweigert")

    monkeypatch.setattr(po.subprocess, "Popen", boom)

    ok, note = po.open_pdf_externally(pdf, "custom", str(exe))

    assert ok is True
    assert "Zugriff verweigert" in note
    assert spies["default"] == [pdf]


def test_default_app_failure_is_reported(tmp_path, monkeypatch):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")

    def boom(p):
        raise OSError("kein Handler")

    monkeypatch.setattr(po, "open_with_default_app", boom)

    ok, note = po.open_pdf_externally(pdf, "system")
    assert ok is False and "kein Handler" in note


def test_build_custom_command_macos_app_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    pdf = tmp_path / "a.pdf"
    assert po.build_custom_command("/Applications/Preview.app", pdf) == [
        "open", "-a", "/Applications/Preview.app", str(pdf)
    ]
    assert po.build_custom_command("/usr/local/bin/viewer", pdf) == ["/usr/local/bin/viewer", str(pdf)]


def test_build_custom_command_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    pdf = tmp_path / "a.pdf"
    assert po.build_custom_command(r"C:\Tools\PDFXEdit.exe", pdf) == [r"C:\Tools\PDFXEdit.exe", str(pdf)]

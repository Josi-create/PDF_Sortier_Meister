"""Fehlt PyQt6.QtPdf (seit PyQt6 6.12 im eigenen Paket PyQt6-Pdf), nennt der Import der
PDF-Vorschau die Loesung. Im Unterprozess, damit der fehlende Modul-Eintrag den
Testprozess nicht beruehrt."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_CODE = """
import sys
sys.modules["PyQt6.QtPdf"] = None   # erzwingt ImportError wie bei fehlendem PyQt6-Pdf
try:
    import src.gui.pdf_preview_widget
except ImportError as e:
    print("MELDUNG:", e)
else:
    print("KEIN FEHLER")
"""


def test_fehlender_qtpdf_nennt_pyqt6_pdf_und_befehle():
    r = subprocess.run(
        [sys.executable, "-c", _CODE], capture_output=True, text=True, timeout=180, cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT), "QT_QPA_PLATFORM": "offscreen"},
    )
    assert "MELDUNG:" in r.stdout, r.stdout + r.stderr
    assert "PyQt6-Pdf" in r.stdout
    assert "pip install -r requirements.txt" in r.stdout
    assert "pip install --force-reinstall --no-deps PyQt6-Pdf PyQt6-Pdf-Qt6" in r.stdout

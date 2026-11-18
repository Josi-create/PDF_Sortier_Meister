"""Issue #411: Die Vorschau friert nicht ein, wenn die Seite fast genau in die Hoehe passt.

Bei „an Breite anpassen“ und Rollbalken „nur bei Bedarf“ schaukelte sich ``QPdfView``
auf: Rollbalken ein -> Seite schmaler und niedriger -> Rollbalken aus -> Seite wieder zu
hoch -> ... endlos im Hauptthread. Der Test stellt das in einem eigenen Prozess mit
Zeitgrenze nach, damit ein Rueckfall die Testsuite nicht aufhaengt.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent

SKRIPT = r"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[1])
import pymupdf
from PyQt6.QtWidgets import QApplication

app = QApplication([])
from src.gui.pdf_preview_widget import PdfPreviewWidget

pfad = os.path.join(sys.argv[2], "quer.pdf")
doc = pymupdf.open()
seite = doc.new_page(width=420.48, height=294.48)  # Querformat wie ein kleiner Scan
seite.insert_text((40, 60), "Vorschau")
doc.save(pfad); doc.close()

w = PdfPreviewWidget()
w.resize(1000, 500)
w.show()
w.load_pdf(pfad)
import time
ende = time.perf_counter() + 5
while not w.is_showing_document() and time.perf_counter() < ende:
    app.processEvents(); time.sleep(0.01)
assert w.is_showing_document()
for hoehe in range(500, 900):
    print(hoehe, flush=True)
    w.resize(1000, hoehe)
    for _ in range(4):
        app.processEvents()
print("FERTIG", flush=True)
os._exit(0)
"""


def test_vorschau_friert_bei_knapp_passender_seite_nicht_ein(tmp_path):
    skript = tmp_path / "vorschau_hoehen.py"
    skript.write_text(SKRIPT, encoding="utf-8")
    umgebung = dict(os.environ, APPDATA=str(tmp_path / "appdata"), QT_QPA_PLATFORM="offscreen")
    try:
        lauf = subprocess.run(
            [sys.executable, "-B", str(skript), str(WURZEL), str(tmp_path)],
            capture_output=True, text=True, timeout=60, env=umgebung, cwd=str(tmp_path),
        )
    except subprocess.TimeoutExpired as e:
        zeilen = (e.stdout or b"").decode("utf-8", "replace").split() if isinstance(e.stdout, bytes) \
            else (e.stdout or "").split()
        pytest.fail(f"Vorschau eingefroren bei Hoehe {zeilen[-1] if zeilen else '?'} (Issue #411)")
    assert "FERTIG" in lauf.stdout, lauf.stdout[-300:] + lauf.stderr[-600:]


def test_senkrechter_rollbalken_ist_immer_sichtbar(qtbot):
    from PyQt6.QtCore import Qt

    from src.gui.pdf_preview_widget import PdfPreviewWidget

    w = PdfPreviewWidget()
    qtbot.addWidget(w)
    try:
        assert w._view.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOn
    finally:
        w.shutdown()

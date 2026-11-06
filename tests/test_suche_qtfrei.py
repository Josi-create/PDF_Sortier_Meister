"""Das Paket src.search darf kein PyQt6 laden (Hintergrunddienst, MCP, Arbeitsprozesse laufen ohne Oberflaeche)."""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

CODE = """
import sys
import src.search
import src.search.dienst, src.search.web, src.search.mcp_server, src.search.suchindex, src.search.indexer
import src.search.extract, src.search.office, src.search.mbox, src.search.ausgabe, src.search.konfig
import src.search.plattform
import src.utils.tesseract, src.utils.config
geladen = sorted(m for m in sys.modules if m.startswith(("PyQt6", "sklearn", "src.gui")))
assert not geladen, geladen
print("ok")
"""


def test_src_search_laedt_ohne_qt():
    r = subprocess.run([sys.executable, "-c", CODE], cwd=str(REPO), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "ok"

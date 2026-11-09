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
import src.search.plattform, src.search.migration
import src.utils.tesseract, src.utils.config
geladen = sorted(m for m in sys.modules if m.startswith(("PyQt6", "sklearn", "src.gui")))
assert not geladen, geladen
print("ok")
"""


def test_src_search_laedt_ohne_qt():
    r = subprocess.run([sys.executable, "-c", CODE], cwd=str(REPO), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "ok"


# Baustein 1 (docs/CHAT_MCP_PLAN.md): der MCP-Server nutzt die Chat-Werkzeuge. Weder sie noch der
# Leser der Hauptdatenbank duerfen PyQt6 oder SQLAlchemy laden (pdfsm-dienst schliesst beides aus).
CODE_WERKZEUGE = """
import sys
import src.rag.werkzeug_kern, src.rag.daten, src.rag.werkzeuge, src.core.similar_documents
import src.search.pdfsm_daten, src.search.mcp_server
geladen = sorted(m for m in sys.modules
                 if m.startswith(("PyQt6", "sklearn", "sqlalchemy", "src.gui", "src.utils.database", "src.ml.classifier")))
assert not geladen, geladen
print("ok")
"""


def test_werkzeuge_und_mcp_laden_ohne_qt_und_sqlalchemy():
    r = subprocess.run([sys.executable, "-c", CODE_WERKZEUGE], cwd=str(REPO), capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "ok"

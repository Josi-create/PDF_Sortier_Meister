"""Verstaendliche KI-Fehlerhinweise fuer die Statusanzeige (src/ml/llm_hinweis.py)."""
import pytest

from src.ml.llm_hinweis import betrifft_nur_dokument, ki_hinweis


@pytest.mark.parametrize("provider, fehler, im_problem, in_abhilfe", [
    ("Ollama", "Ollama HTTP 500: error starting llama-server: llama-server binary not found",
     "unvollständig installiert", "neu installieren"),
    ("Ollama", 'Ollama HTTP 404: model "abc" not found, try pulling it first',
     "gibt es bei Ollama nicht", "vorhandenes Modell"),
    ("Ollama", "Modell „abc“ ist in Ollama nicht installiert (3 Modell(e) vorhanden).",
     "gibt es bei Ollama nicht", "vorhandenes Modell"),
    ("Ollama", "Ollama HTTP 500: model requires more system memory (20 GiB) than is available",
     "Speicher", "kleineres Modell"),
    ("Ollama", "Keine Verbindung zu Ollama (http://localhost:11434). Details: [WinError 10061]",
     "läuft nicht", "Ollama starten"),
    ("Strata", "Verbindung fehlgeschlagen: [WinError 10061]",
     "läuft nicht", "Den Strata-Server starten"),
    ("Strata", "API-Key wird nicht angenommen", "API-Key", "API-Key prüfen"),
    ("OpenRouter", "Error code: 401 - invalid api key", "API-Key", "API-Key prüfen"),
    ("OpenRouter", "Error code: 402 - insufficient credits", "Guthaben", "aufladen"),
    ("OpenRouter", "Error code: 429 - rate limit exceeded", "zu viele Anfragen", "warten"),
    ("OpenRouter", "Connection error.", "Keine Verbindung", "Internetverbindung"),
    ("Claude", "Request timed out.", "zu langsam", "warten"),
    ("Claude", "irgendwas Unerwartetes", "meldet einen Fehler", "Verbindung testen"),
])
def test_hinweise(provider, fehler, im_problem, in_abhilfe):
    h = ki_hinweis(provider, fehler, "gpt-oss")
    assert im_problem in h.problem
    assert in_abhilfe in h.abhilfe


def test_modellname_im_hinweis():
    h = ki_hinweis("Ollama", "Modell nicht installiert", "gpt-oss-64k:latest")
    assert "„gpt-oss-64k:latest“" in h.problem


@pytest.mark.parametrize("fehler, nur_dokument", [
    ("KI hat keinen Vorschlag geliefert.", True),
    ("KI hat keinen Dateinamen geliefert.", True),
    ("KI-Dateiname bestand nur aus ungueltigen Zeichen.", True),
    ("Ollama HTTP 500: error starting llama-server", False),
    ("", False),
])
def test_betrifft_nur_dokument(fehler, nur_dokument):
    assert betrifft_nur_dokument(fehler) is nur_dokument

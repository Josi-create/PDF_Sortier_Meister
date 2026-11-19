"""Verstaendliche KI-Fehlerhinweise fuer die Statusanzeige (src/ml/llm_hinweis.py)."""
import pytest

from src.ml.llm_hinweis import betrifft_nur_dokument, ki_hinweis


@pytest.mark.parametrize("provider, fehler, im_problem, in_abhilfe", [
    ("Ollama", "Ollama HTTP 500: error starting llama-server: llama-server binary not found",
     "unvollständig installiert", "neu installieren"),
    # Issue #390: Ollama hat geantwortet, also laeuft es - nur das Modell fehlt
    ("Ollama", 'Ollama HTTP 404: model "abc" not found, try pulling it first',
     "Ollama läuft, aber das Modell", "installierten Modelle übernehmen"),
    ("Ollama", "Ollama HTTP 404: model 'abc' not found",  # Issue #291: Name mitten in der Meldung
     "Ollama läuft, aber das Modell", "installierten Modelle übernehmen"),
    ("Ollama", "Modell „abc“ ist in Ollama nicht installiert (3 Modell(e) vorhanden).",
     "Ollama läuft, aber das Modell", "installierten Modelle übernehmen"),
    ("OpenRouter", "Error code: 404 - model does not exist",
     "gibt es bei OpenRouter nicht", "vorhandenes Modell"),
    # Issue #356: Modell waehrend der Arbeit abgestuerzt (nicht: unvollstaendig installiert)
    ("Ollama", "Ollama HTTP 500: llama runner process has terminated: exit status 0xc0000409",
     "abgestürzt", "kleineres Modell wählen oder Ollama neu starten"),
    ("Ollama", "Ollama HTTP 500: llama-server process has terminated: exit status 2. The system d",
     "Grafikspeicher", "neu starten"),
    # Live-Test 19.11.2026: Modellprozess stirbt mitten in der Antwort (nicht: unvollstaendig installiert)
    ("Ollama", "Ollama HTTP 500: error reading llama-server response: read tcp 127.0.0.1:50556->127.0.0.1:50508: "
               "wsarecv: Eine vorhandene Verbindung wurde vom Remotehost geschlossen.",
     "abgestürzt", "kleineres Modell wählen oder Ollama neu starten"),
    ("Ollama", "Das Modell 'abc' unterstützt keine Werkzeuge (Ollama HTTP 400: abc does not support tools).",
     "nicht selbst in den Dokumenten suchen", "Werkzeuge"),
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


@pytest.mark.parametrize("fehler, art", [
    ("Ollama HTTP 404: model 'abc' not found", "modell_fehlt"),
    ("Keine Verbindung zu Ollama (http://localhost:11434). Details: [WinError 10061]", "laeuft_nicht"),
    ("Ollama HTTP 500: llama runner process has terminated: exit status 2", "absturz"),
    ("Ollama HTTP 500: error reading llama-server response: read tcp 127.0.0.1:1->127.0.0.1:2: wsarecv: x", "absturz"),
    ("irgendwas Unerwartetes", ""),
])
def test_art_des_problems(fehler, art):
    """Issue #390: Das Fenster „Hintergrund-Analyse“ waehlt danach seine Knoepfe."""
    assert ki_hinweis("Ollama", fehler, "abc").art == art


def test_anbieter_name_und_modell_aus_dem_provider_objekt():
    from src.ml.llm_hinweis import anbieter_name, modell_von
    from src.ml.llm_provider import LLMConfig
    from src.ml.ollama_provider import OllamaCloudProvider, OllamaProvider

    lokal = OllamaProvider(LLMConfig(api_key="", model="gemma3:4b"))
    assert anbieter_name(lokal) == "Ollama" and modell_von(lokal) == "gemma3:4b"
    assert anbieter_name(OllamaCloudProvider(LLMConfig(api_key="k", model="m"))) == "Ollama Cloud"
    assert anbieter_name(object()) == "Die KI" and modell_von(object()) == ""


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

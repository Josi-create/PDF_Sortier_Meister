"""Dokumentensuche: Browser-Oberflaeche (Host-Pruefung, POST-Schutz, API)."""

import pytest

import helfer_suche as h
from src.search import Indexer, web

flask = pytest.importorskip("flask")


@pytest.fixture
def client(tmp_path):
    ordner = tmp_path / "Ablage"
    ordner.mkdir()
    (ordner / "Rechnung.md").write_text("Rechnung von Telekom", encoding="utf-8")
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ordner)])
    assert Indexer(konfig, synchron=True).lauf() == 0
    app = web.erstelle_app(konfig)
    app.testing = True
    return app.test_client()


def test_startseite_und_suche(client):
    r = client.get("/", headers={"Host": "127.0.0.1:18425"})
    assert r.status_code == 200 and b"PDF Sortier Meister" in r.data
    r = client.get("/api/suche?q=Telekom&typ=md", headers={"Host": "localhost:18425"})
    assert r.status_code == 200
    erg = r.get_json()
    assert erg["gesamt"] == 1 and erg["treffer"][0]["name"] == "Rechnung.md"
    assert client.get("/api/suche?q=", headers={"Host": "127.0.0.1"}).get_json()["gesamt"] == 0
    assert client.get("/api/suche?q=x&von=irgendwann", headers={"Host": "127.0.0.1"}).status_code == 400


def test_fremder_host_und_post_ohne_kopfzeile_abgewiesen(client):
    assert client.get("/api/suche?q=Telekom", headers={"Host": "boese.example"}).status_code == 403
    assert client.post("/api/ordner/1", headers={"Host": "127.0.0.1"}).status_code == 403


def test_dokument_status_und_datei(client, monkeypatch):
    dok_id = client.get("/api/suche?q=Telekom", headers={"Host": "127.0.0.1"}).get_json()["treffer"][0]["id"]
    r = client.get(f"/api/dokument/{dok_id}?q=Telekom", headers={"Host": "127.0.0.1"})
    j = r.get_json()
    assert j["dokument"]["name"] == "Rechnung.md" and j["seiten"][0]["treffer"] is True
    assert client.get("/api/dokument/999", headers={"Host": "127.0.0.1"}).status_code == 404

    st = client.get("/api/status", headers={"Host": "127.0.0.1"}).get_json()
    assert st["dokumente"] == 1 and st["laeuft"] is False and st["vorhanden"] is True

    r = client.get(f"/datei/{dok_id}", headers={"Host": "127.0.0.1"})
    assert r.status_code == 200 and b"Rechnung von Telekom" in r.data and r.mimetype == "text/plain"

    gezeigt = []
    monkeypatch.setattr(web, "_im_dateimanager_zeigen", lambda pfad: gezeigt.append(pfad))
    r = client.post(f"/api/ordner/{dok_id}", headers={"Host": "127.0.0.1", "X-PDFsuche": "1"})
    assert r.get_json() == {"ok": True} and gezeigt and gezeigt[0].endswith("Rechnung.md")

"""Dokumentensuche: geoeffnete Programme nach vorn holen (``src.search.fenster``).

Die Win32-Aufrufe selbst werden nie ausgefuehrt: ``sichtbare``, ``_klasse``
und ``_aktiviere`` sind ersetzt, ``conftest`` schaltet das Modul ohnehin ab.
"""

import helfer_suche as h
import pytest

from src.search import Indexer, fenster, web


class Fenster:
    """Ersatz fuer die Fensterliste: nach ``nach`` Abfragen erscheint ``neu``."""

    def __init__(self, alt: dict, neu: dict | None = None, nach: int = 1):
        self.alt, self.neu, self.nach, self.abfragen = alt, neu or {}, nach, 0

    def __call__(self):
        self.abfragen += 1
        return {**self.alt, **(self.neu if self.abfragen > self.nach else {})}


@pytest.fixture
def aktiviert(monkeypatch):
    liste = []
    monkeypatch.setattr(fenster, "_aktiviere", lambda hwnd: liste.append(hwnd) or True)
    monkeypatch.setattr(fenster, "_klasse", lambda hwnd: "CabinetWClass" if hwnd >= 100 else "XLMAIN")
    return liste


def test_import_ohne_win32_und_abgeschaltet(monkeypatch):
    def nie():
        raise AssertionError("Win32-Schnittstelle geladen")

    monkeypatch.setattr(fenster, "_winapi", nie)
    assert fenster.sichtbare() == {}
    fenster.nach_vorn(["x.pdf"])                       # abgeschaltet: kein Faden, kein Aufruf


def test_neues_fenster_mit_vollem_namen_hat_vorrang(monkeypatch, aktiviert):
    vorher = {1: "Mappe.xlsx - Excel"}
    monkeypatch.setattr(fenster, "sichtbare", Fenster(vorher, {2: "Mappe - Excel", 3: "Bericht.xlsx - Excel"}))
    assert fenster._warte_und_aktiviere(["Bericht.xlsx", "Bericht"], vorher, 2, False, None, 1, pause=0)
    assert aktiviert == [3]


def test_vorhandenes_fenster_nach_der_frist(monkeypatch, aktiviert):
    vorher = {1: "Bericht.xlsx - Excel", 2: "Browser"}
    monkeypatch.setattr(fenster, "sichtbare", Fenster(vorher))
    assert fenster._warte_und_aktiviere(["Bericht.xlsx"], vorher, 2, False, None, 0.05, pause=0.01)
    assert aktiviert == [1]


def test_kein_passendes_fenster_gibt_auf(monkeypatch, aktiviert):
    monkeypatch.setattr(fenster, "sichtbare", Fenster({1: "Browser"}))
    assert not fenster._warte_und_aktiviere(["Bericht.xlsx"], {}, 0.05, False, None, 0.01, pause=0.01)
    assert aktiviert == []


def test_explorer_nur_mit_titelanfang_und_fensterklasse(monkeypatch, aktiviert):
    # Excel-Fenster mit dem Ordnernamen im Titel zaehlt nicht, nur das Explorer-Fenster des Ordners
    monkeypatch.setattr(fenster, "sichtbare", Fenster({}, {5: "Ablage - Excel", 101: "Ablage – Datei-Explorer",
                                                           102: "Alte Ablage – Datei-Explorer"}, nach=0))
    assert fenster._warte_und_aktiviere(["Ablage"], {}, 1, True, "CabinetWClass", 1, pause=0)
    assert aktiviert == [101]


def test_starte_oeffnet_und_holt_nach_vorn(monkeypatch, tmp_path):
    aufrufe = []
    monkeypatch.setattr(fenster, "open_with_default_app", lambda p: aufrufe.append(("oeffnen", p)))
    monkeypatch.setattr(fenster, "sichtbare", lambda: {7: "Browser"})
    monkeypatch.setattr(fenster, "nach_vorn", lambda namen, vorher, **kw: aufrufe.append(("vorn", namen, vorher)))
    datei = tmp_path / "Bericht.xlsx"
    fenster.starte(datei)
    fenster.starte(datei, ["Betreff der Mail"])
    assert aufrufe == [("oeffnen", str(datei)), ("vorn", ["Bericht.xlsx", "Bericht"], {7: "Browser"}),
                       ("oeffnen", str(datei)), ("vorn", ["Betreff der Mail"], {7: "Browser"})]


def test_nach_vorn_startet_faden(monkeypatch):
    gestartet = []
    monkeypatch.setattr(fenster, "AKTIV", True)
    monkeypatch.setattr(fenster, "_warte_und_aktiviere", lambda *a: gestartet.append(a))
    fenster.nach_vorn(["", "Ablage"], {1: "x"}, anfang=True, klasse=fenster.EXPLORER_KLASSE)
    fenster.nach_vorn([""])                            # ohne Namen: nichts
    for f in fenster.threading.enumerate():
        if f.name == "fenster-nach-vorn":
            f.join(2)
    assert gestartet == [(["Ablage"], {1: "x"}, 15.0, True, "CabinetWClass", 5.0)]


def test_browser_oberflaeche_holt_programm_und_explorer_nach_vorn(tmp_path, monkeypatch):
    pytest.importorskip("flask")
    ordner = tmp_path / "Ablage"
    ordner.mkdir()
    (ordner / "Rechnung.md").write_text("Rechnung von Telekom", encoding="utf-8")
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ordner)])
    assert Indexer(konfig, synchron=True).lauf() == 0
    app = web.erstelle_app(konfig)
    app.testing = True
    client = app.test_client()
    dok_id = client.get("/api/suche?q=Telekom", headers={"Host": "127.0.0.1"}).get_json()["treffer"][0]["id"]

    gestartet, gezeigt = [], []
    monkeypatch.setattr(web.fenster, "starte", lambda pfad, namen=None: gestartet.append((pfad, namen)))
    monkeypatch.setattr(web.fenster, "ordner_zeigen", lambda pfad, zeigen: gezeigt.append((pfad, zeigen)))
    kopf = {"Host": "127.0.0.1", "X-PDFsuche": "1"}
    assert client.post(f"/api/oeffnen/{dok_id}", headers=kopf).get_json() == {"ok": True}
    assert client.post(f"/api/ordner/{dok_id}", headers=kopf).get_json() == {"ok": True}
    assert gestartet[0][0].endswith("Rechnung.md") and gestartet[0][1] is None
    assert gezeigt[0][0].endswith("Rechnung.md") and gezeigt[0][1] is web._im_dateimanager_zeigen


def test_ordner_zeigen_sucht_das_explorer_fenster(monkeypatch, tmp_path):
    aufrufe = []
    monkeypatch.setattr(fenster, "sichtbare", lambda: {1: "Browser"})
    monkeypatch.setattr(fenster, "nach_vorn", lambda namen, vorher, **kw: aufrufe.append((namen, vorher, kw)))
    datei = tmp_path / "Ablage" / "Rechnung.md"
    fenster.ordner_zeigen(str(datei), lambda p: aufrufe.append(("zeigen", p)))
    assert aufrufe == [("zeigen", str(datei)),
                       (["Ablage"], {1: "Browser"}, {"anfang": True, "klasse": "CabinetWClass"})]

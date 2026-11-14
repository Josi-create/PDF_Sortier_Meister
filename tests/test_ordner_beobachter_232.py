"""Scan-Ordner beobachten (Issue #232): Dateiliste lesen, „fertig geschrieben“ erkennen, Abgleich.

Ohne Qt. Die Zeit wird dem Abgleich als Zahl uebergeben, die Tests warten nicht.
"""
from __future__ import annotations

import os

import pytest

from src.core.ordner_beobachter import (
    Abgleich,
    Eintrag,
    anzeige_endungen,
    datei_fertig,
    datei_stand,
    ordner_lesen,
)

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


# --- ordner_lesen -----------------------------------------------------------

def test_ordner_lesen_nimmt_dieselben_dateien_wie_die_ansicht(tmp_path):
    from src.core.file_manager import FileManager

    (tmp_path / "Rechnung Müller.pdf").write_bytes(PDF)
    (tmp_path / "GROSS.PDF").write_bytes(PDF)
    (tmp_path / "Brief.docx").write_bytes(b"PK")
    (tmp_path / "Notiz.txt").write_text("x", encoding="utf-8")
    (tmp_path / "Foto.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (tmp_path / "~$Brief.docx").write_bytes(b"lock")   # Sperrdatei von Word
    (tmp_path / "scan.tmp").write_bytes(b"halb")       # Zwischendatei eines Scanners
    (tmp_path / "daten.csv").write_text("a;b", encoding="utf-8")
    (tmp_path / "Unterordner.pdf").mkdir()             # Ordner, der wie eine PDF heisst

    liste = ordner_lesen(tmp_path, anzeige_endungen())

    fm = FileManager(tmp_path)
    erwartet = {p.name for p in fm.get_pdf_files()} | {p.name for p in fm.get_office_files()}
    assert set(liste) == erwartet == {"Rechnung Müller.pdf", "GROSS.PDF", "Brief.docx", "Notiz.txt", "Foto.jpg"}
    assert liste["GROSS.PDF"].groesse == len(PDF)


def test_ordner_lesen_meldet_fehlenden_ordner_als_fehler(tmp_path):
    """Ein nicht lesbarer Ordner (geloescht, Netzlaufwerk getrennt) ist keine leere Liste."""
    with pytest.raises(OSError):
        ordner_lesen(tmp_path / "gibt-es-nicht", anzeige_endungen())


# --- datei_fertig -----------------------------------------------------------

def _fertig(pfad) -> bool:
    return datei_fertig(pfad, datei_stand(pfad))


def test_vollstaendiges_pdf_ist_fertig(tmp_path):
    p = tmp_path / "a.pdf"
    p.write_bytes(PDF)
    assert _fertig(p)


def test_halb_geschriebenes_pdf_ist_nicht_fertig(tmp_path):
    p = tmp_path / "a.pdf"
    p.write_bytes(PDF[:20])      # Kopf da, Endmarke fehlt
    assert not _fertig(p)
    p.write_bytes(b"")           # Scanner hat die Datei erst angelegt
    assert not _fertig(p)


def test_pdf_mit_zeilenenden_nach_der_endmarke_ist_fertig(tmp_path):
    p = tmp_path / "a.pdf"
    p.write_bytes(PDF + b"\r\n\r\n")
    assert _fertig(p)


def test_bilder_brauchen_ihre_endmarke(tmp_path):
    jpg = tmp_path / "foto.JPG"
    jpg.write_bytes(b"\xff\xd8" + b"\x00" * 500)
    assert not _fertig(jpg)
    jpg.write_bytes(b"\xff\xd8" + b"\x00" * 500 + b"\xff\xd9")
    assert _fertig(jpg)
    png = tmp_path / "bild.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    assert not _fertig(png)
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100 + b"\x00\x00\x00\x00IEND\xaeB`\x82")
    assert _fertig(png)


def test_dateien_ohne_endmarke_sind_fertig_wenn_lesbar(tmp_path):
    p = tmp_path / "Notiz.txt"
    p.write_text("Zählerstand", encoding="utf-8")
    assert _fertig(p)


def test_gesperrte_datei_ist_nicht_fertig(tmp_path, monkeypatch):
    """Das schreibende Programm haelt die Datei exklusiv offen (Windows: PermissionError)."""
    import builtins

    p = tmp_path / "a.pdf"
    p.write_bytes(PDF)
    stand = datei_stand(p)

    def gesperrt(*args, **kwargs):
        raise PermissionError(13, "Der Prozess kann nicht auf die Datei zugreifen")

    monkeypatch.setattr(builtins, "open", gesperrt)
    assert not datei_fertig(p, stand)


def test_cloud_platzhalter_wird_nicht_geoeffnet(tmp_path, monkeypatch):
    """„Nur online“ (OneDrive): Lesen wuerde die Datei herunterladen."""
    import builtins

    def nicht_oeffnen(*args, **kwargs):
        raise AssertionError("Platzhalter darf nicht geoeffnet werden")

    monkeypatch.setattr(builtins, "open", nicht_oeffnen)
    assert datei_fertig(tmp_path / "wolke.pdf", Eintrag(1000, 1, nur_online=True))


def test_datei_stand_fehlende_datei_und_ordner(tmp_path):
    assert datei_stand(tmp_path / "fehlt.pdf") is None
    assert datei_stand(tmp_path) is None


def test_nur_online_zaehlt_nicht_als_aenderung():
    """OneDrive laedt eine Datei herunter oder gibt Platz frei: der Inhalt bleibt derselbe."""
    assert Eintrag(10, 5, nur_online=True) == Eintrag(10, 5, nur_online=False)


# --- Abgleich (mit gespielter Datei-Sonde) ----------------------------------

class Ordner:
    """Gespielter Ordner: Verzeichnisliste und Datei selbst getrennt stellbar."""

    def __init__(self):
        self.liste: dict[str, Eintrag] = {}
        self.datei: dict[str, Eintrag] = {}
        self.vollstaendig: set[str] = set()
        self.geprueft: list[str] = []

    def setze(self, name, groesse, mtime=1, vollstaendig=True, liste=True):
        self.datei[name] = Eintrag(groesse, mtime)
        if liste:
            self.liste[name] = Eintrag(groesse, mtime)
        (self.vollstaendig.add if vollstaendig else self.vollstaendig.discard)(name)

    def entferne(self, name):
        self.liste.pop(name, None)
        self.datei.pop(name, None)

    def stand(self, pfad):
        return self.datei.get(os.path.basename(str(pfad)))

    def fertig(self, pfad, stand):
        name = os.path.basename(str(pfad))
        self.geprueft.append(name)
        return name in self.vollstaendig

    def abgleich(self, bekannte=(), **kw):
        return Abgleich("X:/Scan", bekannte, stand=self.stand, fertig=self.fertig, **kw)


def test_bekannte_dateien_werden_nicht_gemeldet():
    o = Ordner()
    o.setze("a.pdf", 10)
    o.setze("b.pdf", 20)
    a = o.abgleich(["a.pdf", "b.pdf"])
    for t in (0, 1, 5, 60):
        aenderung = a.schritt(dict(o.liste), t)
        assert not aenderung and aenderung.wartend == 0
    assert o.geprueft == []   # vorhandene Dateien werden nie geoeffnet


def test_neue_datei_erst_nach_der_ruhezeit():
    o = Ordner()
    o.setze("a.pdf", 10)
    a = o.abgleich(["a.pdf"])
    a.schritt(dict(o.liste), 0)
    o.setze("neu.pdf", 500)
    assert a.schritt(dict(o.liste), 10).wartend == 1       # eben entdeckt
    assert a.schritt(dict(o.liste), 11).neu == []          # 1 s Ruhe reicht nicht
    aenderung = a.schritt(dict(o.liste), 12.5)
    assert aenderung.neu == ["neu.pdf"] and aenderung.wartend == 0
    # genau einmal gemeldet
    assert not a.schritt(dict(o.liste), 13)
    assert not a.schritt(dict(o.liste), 100)


def test_wachsende_datei_wird_erst_gemeldet_wenn_sie_ruht_und_vollstaendig_ist():
    """Scanner schreibt Seite fuer Seite; zwischen zwei Seiten ruht die Datei laenger als die Ruhezeit."""
    o = Ordner()
    a = o.abgleich()
    o.setze("scan.pdf", 100, mtime=1, vollstaendig=False)
    assert not a.schritt(dict(o.liste), 0)
    assert not a.schritt(dict(o.liste), 1)
    o.setze("scan.pdf", 900, mtime=2, vollstaendig=False)   # waechst
    assert not a.schritt(dict(o.liste), 2)
    assert not a.schritt(dict(o.liste), 3)
    assert not a.schritt(dict(o.liste), 6)                  # ruht 4 s, aber Endmarke fehlt
    o.setze("scan.pdf", 2000, mtime=3, vollstaendig=True)   # letzte Seite, Datei geschlossen
    assert not a.schritt(dict(o.liste), 7)
    assert not a.schritt(dict(o.liste), 8)
    assert a.schritt(dict(o.liste), 9.5).neu == ["scan.pdf"]


def test_veralteter_verzeichniseintrag_gemessen_wird_an_der_datei():
    """Windows fuehrt Groesse und Zeit im Verzeichnis erst nach, wenn die Datei geschlossen wird."""
    o = Ordner()
    a = o.abgleich()
    o.liste["scan.pdf"] = Eintrag(0, 1)                 # Verzeichnis: leer, steht still
    o.datei["scan.pdf"] = Eintrag(100, 1)
    assert not a.schritt(dict(o.liste), 0)
    for t, groesse in ((1, 400), (2, 800), (3, 1200), (4, 1600)):
        o.datei["scan.pdf"] = Eintrag(groesse, t)       # die Datei selbst waechst
        assert not a.schritt(dict(o.liste), t), t
    o.setze("scan.pdf", 2000, mtime=5)                  # geschlossen: Verzeichnis zieht nach
    assert not a.schritt(dict(o.liste), 5)
    assert a.schritt(dict(o.liste), 7).neu == ["scan.pdf"]
    assert not a.schritt(dict(o.liste), 9)              # keine Aenderungsmeldung hinterher


def test_unvollstaendige_datei_erscheint_nach_der_hoechstwartezeit():
    """Beschaedigtes PDF ohne Endmarke: nach F5 waere es auch zu sehen."""
    o = Ordner()
    a = o.abgleich(hoechstwartezeit=30.0)
    o.setze("kaputt.pdf", 100, vollstaendig=False)
    for t in (0, 1, 3, 10, 29):
        assert not a.schritt(dict(o.liste), t), t
    assert a.schritt(dict(o.liste), 31).neu == ["kaputt.pdf"]


def test_verschwundene_datei_wird_einmal_gemeldet():
    o = Ordner()
    o.setze("a.pdf", 10)
    o.setze("b.pdf", 10)
    a = o.abgleich(["a.pdf", "b.pdf"])
    a.schritt(dict(o.liste), 0)
    o.entferne("a.pdf")
    assert a.schritt(dict(o.liste), 1).weg == ["a.pdf"]
    assert not a.schritt(dict(o.liste), 2)


def test_bekannte_datei_die_schon_vor_dem_ersten_lesen_fehlt():
    """Zwischen dem Aufbau der Ansicht und dem ersten Lesen verschoben."""
    o = Ordner()
    o.setze("b.pdf", 10)
    a = o.abgleich(["a.pdf", "b.pdf"])
    assert a.schritt(dict(o.liste), 0).weg == ["a.pdf"]


def test_datei_die_vor_dem_fertigwerden_verschwindet_wird_nie_gemeldet():
    o = Ordner()
    a = o.abgleich()
    o.setze("temp.pdf", 10, vollstaendig=False)
    assert a.schritt(dict(o.liste), 0).wartend == 1
    o.entferne("temp.pdf")
    aenderung = a.schritt(dict(o.liste), 1)
    assert not aenderung and aenderung.wartend == 0


def test_datei_verschwindet_zwischen_auflisten_und_pruefen():
    o = Ordner()
    a = o.abgleich()
    o.liste["weg.pdf"] = Eintrag(10, 1)     # steht noch in der Liste, die Datei gibt es nicht mehr
    assert not a.schritt(dict(o.liste), 0)
    assert not a.schritt(dict(o.liste), 5)


def test_umbenennen_meldet_alt_weg_und_neu_dazu():
    o = Ordner()
    o.setze("Scan_0001.pdf", 10)
    a = o.abgleich(["Scan_0001.pdf"])
    a.schritt(dict(o.liste), 0)
    o.entferne("Scan_0001.pdf")
    o.setze("Rechnung <Absender>.pdf", 10)
    aenderung = a.schritt(dict(o.liste), 1)
    assert aenderung.weg == ["Scan_0001.pdf"] and aenderung.neu == []
    a.schritt(dict(o.liste), 2)
    assert a.schritt(dict(o.liste), 4.5).neu == ["Rechnung <Absender>.pdf"]


def test_geaenderte_datei_wird_als_geaendert_gemeldet_wenn_sie_wieder_ruht():
    """Der Scanner haengt an ein schon angezeigtes PDF Seiten an."""
    o = Ordner()
    o.setze("a.pdf", 10, mtime=1)
    a = o.abgleich(["a.pdf"])
    a.schritt(dict(o.liste), 0)
    o.setze("a.pdf", 50, mtime=2)
    assert not a.schritt(dict(o.liste), 1)
    assert not a.schritt(dict(o.liste), 2)
    aenderung = a.schritt(dict(o.liste), 4.5)
    assert aenderung.geaendert == ["a.pdf"] and aenderung.neu == [] and aenderung.weg == []
    assert not a.schritt(dict(o.liste), 10)
    # verschwindet sie waehrend des Wartens, ist sie weg - nicht geaendert
    o.setze("a.pdf", 80, mtime=3)
    a.schritt(dict(o.liste), 11)
    o.entferne("a.pdf")
    aenderung = a.schritt(dict(o.liste), 12)
    assert aenderung.weg == ["a.pdf"] and aenderung.geaendert == []


def test_viele_dateien_auf_einmal():
    o = Ordner()
    for i in range(400):
        o.setze(f"alt_{i:03d}.pdf", 10)
    a = o.abgleich(list(o.liste))
    a.schritt(dict(o.liste), 0)
    for i in range(300):
        o.setze(f"neu_{i:03d}.pdf", 10)
    assert a.schritt(dict(o.liste), 1).wartend == 300
    a.schritt(dict(o.liste), 2)
    aenderung = a.schritt(dict(o.liste), 4.5)
    assert len(aenderung.neu) == 300 and aenderung.weg == [] and aenderung.wartend == 0
    assert set(o.geprueft) == {f"neu_{i:03d}.pdf" for i in range(300)}   # nur die neuen geoeffnet
    for i in range(350):
        o.entferne(f"alt_{i:03d}.pdf")
    assert len(a.schritt(dict(o.liste), 6).weg) == 350


# --- Abgleich mit echten Dateien ---------------------------------------------

def test_abgleich_mit_echten_dateien_und_umlauten(tmp_path):
    ordner = tmp_path / "Scans Müller & Söhne"
    ordner.mkdir()
    (ordner / "alt.pdf").write_bytes(PDF)
    endungen = anzeige_endungen()
    a = Abgleich(ordner, ["alt.pdf"], ruhezeit=2.0)
    assert not a.schritt(ordner_lesen(ordner, endungen), 0)

    halb = ordner / "Scän_0002.pdf"
    with open(halb, "wb") as datei:           # Scanner hat begonnen
        datei.write(PDF[:25])
        datei.flush()
        assert not a.schritt(ordner_lesen(ordner, endungen), 1)
        assert not a.schritt(ordner_lesen(ordner, endungen), 4)    # ruht, aber unvollstaendig
        datei.write(PDF[25:])
    assert not a.schritt(ordner_lesen(ordner, endungen), 5)        # eben fertig geworden
    aenderung = a.schritt(ordner_lesen(ordner, endungen), 7.5)
    assert aenderung.neu == ["Scän_0002.pdf"]

    (ordner / "alt.pdf").unlink()
    assert a.schritt(ordner_lesen(ordner, endungen), 8).weg == ["alt.pdf"]


# --- Einsortieren ohne Plattenzugriff -----------------------------------------

def test_sortieren_mit_bekannten_staenden_fragt_die_platte_nicht(monkeypatch):
    """Die Beobachtung kennt Zeit und Groesse aus der Dateiliste; im Thread der Oberflaeche wird nichts gelesen."""
    from pathlib import Path

    from src.core import sortierung

    monkeypatch.setattr(sortierung, "_stat", lambda p: pytest.fail(f"Platte gefragt: {p}"))
    pfade = [Path("X:/Scan/a.pdf"), Path("X:/Scan/b.pdf"), Path("X:/Scan/c.pdf")]
    staende = {"a.pdf": (30.0, 100), "b.pdf": (10.0, 300), "c.pdf": (20.0, 200)}

    def namen(sortierung_id):
        return [p.name for p in sortierung.sortiere_pfade(pfade, sortierung_id, staende)]

    assert namen("datum_ab") == ["a.pdf", "c.pdf", "b.pdf"]
    assert namen("datum_auf") == ["b.pdf", "c.pdf", "a.pdf"]
    assert namen("groesse_ab") == ["b.pdf", "c.pdf", "a.pdf"]
    assert namen("name_ab") == ["c.pdf", "b.pdf", "a.pdf"]


def test_sortieren_unbekannte_datei_wird_von_der_platte_gelesen(tmp_path):
    from src.core.sortierung import sortiere_pfade

    (tmp_path / "gross.pdf").write_bytes(b"x" * 500)
    (tmp_path / "klein.pdf").write_bytes(b"x")
    pfade = [tmp_path / "gross.pdf", tmp_path / "klein.pdf"]
    assert [p.name for p in sortiere_pfade(pfade, "groesse_auf", {"klein.pdf": (1.0, 1)})] == ["klein.pdf", "gross.pdf"]

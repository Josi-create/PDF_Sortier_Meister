"""Word/Excel auf dem Mac per AppleScript (ohne echtes Office: osascript wird ersetzt)."""
import subprocess
from types import SimpleNamespace

import pytest

from src.core import office_convert as oc


@pytest.fixture
def mac(tmp_path, monkeypatch):
    """Mac mit Word/Excel; osascript/open protokolliert, 'Word' schreibt ein PDF."""
    home = tmp_path / "home"
    monkeypatch.setattr(oc.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(oc, "mac_office_verfuegbar", lambda art: True)
    monkeypatch.setattr(oc, "word_com_verfuegbar", lambda: False)
    monkeypatch.setattr(oc, "excel_com_verfuegbar", lambda: False)
    monkeypatch.setattr(oc, "finde_libreoffice", lambda: None)
    zustand = SimpleNamespace(laeuft=True, aufrufe=[], fehler=None, kopien=[])

    def run(cmd, **kw):
        zustand.aufrufe.append(cmd)
        if cmd[:2] == ["osascript", "-e"] and "is running" in cmd[2]:
            return SimpleNamespace(returncode=0, stdout="true\n" if zustand.laeuft else "false\n", stderr="")
        if cmd[:2] == ["osascript", "-"]:
            name, kopie, ziel = cmd[2:5]
            zustand.kopien.append((name, kopie))
            if zustand.fehler:
                return SimpleNamespace(returncode=1, stdout="", stderr=zustand.fehler)
            oc.Path(ziel).write_bytes(b"%PDF-1.4 mac")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    zustand.home = home
    return zustand


def _docx(tmp_path):
    from tests.test_office_convert import body, docx_bauen
    return docx_bauen(tmp_path / "Brief.docx", body(""), None)


def test_word_auf_dem_mac_wandelt_im_container_um(tmp_path, mac):
    erg = oc.umwandeln(_docx(tmp_path))
    assert erg.werkzeug == "Word"
    assert erg.pdf == tmp_path / "Brief.pdf" and erg.pdf.read_bytes() == b"%PDF-1.4 mac"
    name, kopie = mac.kopien[0]
    container = mac.home / "Library/Containers/com.microsoft.Word/Data/tmp"
    assert oc.Path(kopie).parent.parent == container  # Word darf nur dort frei lesen/schreiben
    assert name.startswith("pdfsm-") and name.endswith(".docx")  # nie ein offenes Nutzerdokument
    assert list(container.iterdir()) == []  # aufgeraeumt
    # lief schon: nicht gestartet, nicht beendet
    assert not any(c[0] == "open" or "quit" in " ".join(c) for c in mac.aufrufe)


def test_nicht_laufendes_programm_startet_versteckt_und_endet(tmp_path, mac):
    mac.laeuft = False
    from tests.test_office_convert import docx_bauen  # noqa: F401
    erg = oc.umwandeln(_docx(tmp_path))
    assert erg.werkzeug == "Word"
    assert ["open", "-g", "-j", "-a", "Microsoft Word"] in mac.aufrufe
    assert any("quit saving no" in " ".join(c) for c in mac.aufrufe)


def test_excel_auf_dem_mac(tmp_path, mac):
    xlsx = tmp_path / "Tabelle.xlsx"
    xlsx.write_bytes(b"PK")
    erg = oc.umwandeln(xlsx)
    assert erg.werkzeug == "Excel"
    assert "com.microsoft.Excel" in mac.kopien[0][1]


def test_pdfa_auf_dem_mac_gibt_hinweis(tmp_path, mac):
    erg = oc.umwandeln(_docx(tmp_path), pdfa=True)
    assert not erg.pdfa
    assert any("kein PDF/A" in h for h in erg.hinweise)


def test_fehlende_automation_erlaubnis_erklaert_den_weg(tmp_path, mac):
    mac.fehler = "execution error: Not authorized to send Apple events to Microsoft Word. (-1743)"
    with pytest.raises(oc.UmwandlungFehler, match="Automation"):
        oc.umwandeln(_docx(tmp_path))
    assert not (tmp_path / "Brief.pdf").exists()


def test_umwandler_verfuegbar_kennt_mac_office(monkeypatch):
    monkeypatch.setattr(oc, "word_com_verfuegbar", lambda: False)
    monkeypatch.setattr(oc, "excel_com_verfuegbar", lambda: False)
    monkeypatch.setattr(oc, "finde_libreoffice", lambda: None)
    monkeypatch.setattr(oc, "mac_office_verfuegbar", lambda art: art == "word")
    assert oc.umwandler_verfuegbar(".docx") and oc.umwandler_verfuegbar(".odt")
    assert not oc.umwandler_verfuegbar(".xlsx")


def test_skript_wartet_wirklich_auf_das_dokument():
    """Word liefert fuer ein unbekanntes Dokument "missing value" statt eines Fehlers;
    ``delay`` innerhalb von ``tell`` wartet nicht. Beides liess die Schleife sofort enden."""
    for art in ("word", "excel"):
        skript = oc._MAC_SKRIPT[art]
        schleife = skript.split("repeat {versuche} times")[1].split("end repeat")[0]
        assert "if doc is not missing value then exit repeat" in schleife
        assert "delay" in schleife.split("end try")[-1]  # ausserhalb des tell-Blocks
        assert "tell application" not in schleife.split("end try")[-1]


def test_fehlertext_ohne_applescript_technik():
    roh = "418:454: execution error: Microsoft Word hat die Datei nicht geöffnet (vielleicht ...). (9001)"
    assert oc._mac_fehlertext("Microsoft Word", roh) == "Microsoft Word hat die Datei nicht geöffnet (vielleicht ...)."
    assert "Automation" in oc._mac_fehlertext("Microsoft Word", "x (-1743)")


# ------------------------------------------------------------------- Pages
def test_pages_wenn_weder_word_noch_libreoffice(tmp_path, mac, monkeypatch):
    monkeypatch.setattr(oc, "mac_office_verfuegbar", lambda art: art == "pages")
    erg = oc.umwandeln(_docx(tmp_path))
    assert erg.werkzeug == "Pages"
    stamm, kopie = mac.kopien[0]
    assert "com.apple.iWork.Pages" in kopie
    assert stamm.startswith("pdfsm-") and "." not in stamm  # Pages zeigt Namen teils ohne Endung


def test_libreoffice_vor_pages(tmp_path, mac, monkeypatch):
    monkeypatch.setattr(oc, "mac_office_verfuegbar", lambda art: art == "pages")
    monkeypatch.setattr(oc, "finde_libreoffice", lambda: "/fake/soffice")
    benutzt = []

    def lo(soffice, quelle, pdf, pdfa):
        benutzt.append("lo")
        pdf.write_bytes(b"%PDF lo")

    monkeypatch.setattr(oc, "_mit_libreoffice", lo)
    assert oc.umwandeln(_docx(tmp_path)).werkzeug == "LibreOffice"
    assert benutzt == ["lo"] and mac.kopien == []


def test_pages_springt_ein_wenn_libreoffice_scheitert(tmp_path, mac, monkeypatch):
    monkeypatch.setattr(oc, "mac_office_verfuegbar", lambda art: art == "pages")
    monkeypatch.setattr(oc, "finde_libreoffice", lambda: "/fake/soffice")

    def lo(*a):
        raise oc.UmwandlungFehler("LibreOffice kaputt")

    monkeypatch.setattr(oc, "_mit_libreoffice", lo)
    erg = oc.umwandeln(_docx(tmp_path), pdfa=True)
    assert erg.werkzeug == "Pages" and not erg.pdfa
    assert any("LibreOffice ging nicht" in h for h in erg.hinweise)
    assert any("Pages kann kein PDF/A" in h for h in erg.hinweise)


def test_pages_nicht_fuer_odt_und_xlsx(tmp_path, mac, monkeypatch):
    monkeypatch.setattr(oc, "mac_office_verfuegbar", lambda art: art == "pages")
    monkeypatch.setattr(oc.sys, "platform", "darwin")
    assert oc.umwandler_verfuegbar(".docx")
    assert not oc.umwandler_verfuegbar(".odt") and not oc.umwandler_verfuegbar(".xlsx")
    odt = tmp_path / "a.odt"
    odt.write_bytes(b"PK")
    with pytest.raises(oc.KeinUmwandlerGefunden):
        oc.umwandeln(odt)
    with pytest.raises(oc.KeinUmwandlerGefunden, match="Pages"):
        monkeypatch.setattr(oc, "mac_office_verfuegbar", lambda art: False)
        oc.umwandeln(_docx(tmp_path))


def test_pages_skript_ist_vollstaendig():
    skript = oc._MAC_SKRIPT["pages"]
    assert "export doc to (POSIX file ziel) as PDF" in skript
    assert "close doc saving no" in skript

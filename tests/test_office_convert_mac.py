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

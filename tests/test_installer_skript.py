"""Das Setup beendet die Dienstprogramme der Dokumentensuche selbst (Issue #229).

Das Inno-Setup-Skript laesst sich in der Testumgebung nicht ausfuehren; geprueft wird,
dass die noetigen Bausteine im Skript stehen und zu den gebauten Programmnamen passen.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROH = (ROOT / "installer.iss").read_bytes()
SKRIPT = ROH.decode("utf-8-sig")
CODE = SKRIPT.split("[Code]", 1)[1]


def _rumpf(kopf: str) -> str:
    """Text einer Routine ab ihrer Kopfzeile bis zum abschliessenden ``end;`` am Zeilenanfang."""
    start = CODE.index(kopf)
    return CODE[start:CODE.index("\nend;", start)]


def test_skript_hat_bom_wegen_der_umlaute():
    # Ohne BOM liest Inno Setup die Datei je nach Version als ANSI: Umlaute im Hinweis waeren zerstoert
    assert ROH.startswith(b"\xef\xbb\xbf")
    assert "für" in SKRIPT


def test_dienstnamen_passen_zum_build():
    spec = (ROOT / "pdf_sortier_meister.spec").read_text(encoding="utf-8")
    for name in ("pdfsm-dienst", "pdfsm-dienstw"):
        assert f'name="{name}"' in spec
        assert f"'{name}.exe'" in CODE


def test_vor_dem_kopieren_und_vor_der_deinstallation_werden_dienste_beendet():
    for kopf in ("function PrepareToInstall(", "procedure CurUninstallStepChanged("):
        assert "DienstprozesseBeenden(ExpandConstant('{app}'))" in _rumpf(kopf)


def test_nur_prozesse_aus_dem_installationsordner():
    rumpf = _rumpf("function DienstnameAus(")
    assert "CompareText(ExtractFilePath(Pfad), AddBackslash(Ordner))" in rumpf
    # kein pauschales Beenden nach Namen
    assert "taskkill" not in SKRIPT.lower()


def test_hinweis_zum_neustart_des_ki_assistenten_in_beiden_sprachen():
    sprachen = set(re.findall(r'^Name: "(\w+)"; MessagesFile', SKRIPT, re.MULTILINE))
    assert sprachen == {"german", "english"}
    for sprache in sprachen:
        assert re.search(rf"^{sprache}\.KiAssistentNeuStarten=\S", SKRIPT, re.MULTILINE)
    assert "CustomMessage('KiAssistentNeuStarten')" in _rumpf("procedure CurPageChanged(")

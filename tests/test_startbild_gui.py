"""Startbild: Versionsmarke rechts unten, gleiche Groesse bei jeder Skalierung."""

import re
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from src.utils import startbild
from src.utils.startbild import (
    BOOTLOADER_BREITE,
    BOOTLOADER_HOEHE,
    QT_BREITE,
    QT_HOEHE,
    git_kurz_hash,
    qt_startbild,
    schreibe_bild_mit_version,
    versionstext,
)

WURZEL = Path(__file__).resolve().parent.parent
BILD = WURZEL / "SplashScreen3.png"
HASH = "0123456789abcdef0123456789abcdef01234567"


def _programm_version() -> str:
    text = (WURZEL / "src" / "main.py").read_text(encoding="utf-8")
    return re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE).group(1)


# --- Versionstext -----------------------------------------------------------

def test_installierte_fassung_zeigt_nur_die_version(tmp_path):
    assert versionstext("0.27.0", entwicklung=False, wurzel=tmp_path) == "v0.27.0"


def test_quelltext_ohne_git_zeigt_dev(tmp_path):
    assert versionstext("0.27.0", entwicklung=True, wurzel=tmp_path) == "v0.27.0 dev"


def test_quelltext_zeigt_kurz_hash_des_zweigs(tmp_path):
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "refs" / "heads" / "main").write_text(HASH + "\n", encoding="utf-8")
    assert versionstext("0.27.0", entwicklung=True, wurzel=tmp_path) == "v0.27.0 dev (0123456)"


def test_kurz_hash_bei_losgeloestem_head(tmp_path):
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text(HASH + "\n", encoding="utf-8")
    assert git_kurz_hash(tmp_path) == "0123456"


def test_kurz_hash_aus_gepackten_referenzen(tmp_path):
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted\n"
        f"{'f' * 40} refs/heads/anderer\n{HASH} refs/heads/main\n",
        encoding="utf-8",
    )
    assert git_kurz_hash(tmp_path) == "0123456"


def test_kurz_hash_im_worktree(tmp_path):
    haupt = tmp_path / "haupt" / ".git"
    eigen = haupt / "worktrees" / "wt"
    eigen.mkdir(parents=True)
    (haupt / "refs" / "heads").mkdir(parents=True)
    (haupt / "refs" / "heads" / "feat").write_text(HASH + "\n", encoding="utf-8")
    (eigen / "HEAD").write_text("ref: refs/heads/feat\n", encoding="utf-8")
    (eigen / "commondir").write_text("../..\n", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {eigen.as_posix()}\n", encoding="utf-8")
    assert git_kurz_hash(wt) == "0123456"


def test_kurz_hash_ohne_git_und_bei_muell(tmp_path):
    assert git_kurz_hash(tmp_path) == ""
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("irgendwas\n", encoding="utf-8")
    assert git_kurz_hash(tmp_path) == ""


def test_erkennt_die_laufende_fassung_selbst(monkeypatch):
    version = _programm_version()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert versionstext(version) == f"v{version}"
    monkeypatch.delattr(sys, "frozen")
    assert versionstext(version).startswith(f"v{version} dev")


# --- Qt-Startbild (Start aus dem Quelltext, macOS) --------------------------

def _unterschied(a, b):
    """Umschliessendes Rechteck der Pixel, in denen sich zwei QImages unterscheiden."""
    assert a.size() == b.size()
    xs, ys = [], []
    for y in range(a.height()):
        for x in range(a.width()):
            if a.pixel(x, y) != b.pixel(x, y):
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


@pytest.mark.parametrize("dpr", [1.0, 1.5, 2.0])
def test_qt_startbild_gleich_gross_und_marke_rechts_unten(qapp, dpr):
    mit = qt_startbild(BILD, "v0.27.0 dev (0123456)", dpr)
    ohne = qt_startbild(BILD, "", dpr)

    # Bei jeder Skalierung dieselbe Groesse auf dem Bildschirm, in echten Pixeln gerechnet
    assert mit.devicePixelRatio() == dpr
    assert mit.deviceIndependentSize().width() == pytest.approx(QT_BREITE, abs=1)
    assert mit.deviceIndependentSize().height() == pytest.approx(QT_HOEHE, abs=1)
    assert mit.width() == round(QT_BREITE * dpr)

    kasten = _unterschied(mit.toImage(), ohne.toImage())
    assert kasten is not None, "Versionsmarke fehlt"
    links, oben, rechts, unten = (wert / dpr for wert in kasten)
    # ganz in der rechten unteren Ecke, mit Abstand zum Rand und nicht abgeschnitten
    assert links > QT_BREITE * 0.6
    assert oben > QT_HOEHE * 0.88
    assert 2 <= QT_BREITE - rechts <= 14
    assert 2 <= QT_HOEHE - unten <= 14


def test_qt_startbild_marke_ist_grau_auf_hellem_grund(qapp):
    bild = qt_startbild(BILD, "v0.27.0", 2.0).toImage()
    ohne = qt_startbild(BILD, "", 2.0).toImage()
    links, oben, rechts, unten = _unterschied(bild, ohne)
    # nur die Punkte der Marke selbst (die runden Ecken lassen das Bild durch)
    farben = [
        bild.pixelColor(x, y)
        for y in range(oben, unten + 1)
        for x in range(links, rechts + 1)
        if bild.pixel(x, y) != ohne.pixel(x, y)
    ]
    helle = [f for f in farben if f.lightness() > 190]
    assert len(helle) > len(farben) * 0.4, "heller Grund fehlt"
    if not qapp.platformName() == "offscreen":
        # Schrift in Grau; fast schwarz sind hoechstens Randpunkte ueber dem dunklen Aermel
        graue = [f for f in farben if 70 <= f.lightness() <= 120]
        assert len(graue) > 20, "graue Schrift fehlt"
        assert len([f for f in farben if f.lightness() < 60]) < len(farben) * 0.05


def test_qt_startbild_ohne_bild(qapp, tmp_path):
    assert qt_startbild(tmp_path / "fehlt.png", "v1", 1.0) is None


# --- Bootloader-Startbild (installierte Windows-Fassung) --------------------

def test_bootloader_bild_traegt_die_version_rechts_unten(tmp_path):
    mit = Image.open(schreibe_bild_mit_version(BILD, tmp_path / "mit.png", "v0.27.0"))
    ohne = Image.open(schreibe_bild_mit_version(BILD, tmp_path / "ohne.png", ""))
    assert mit.size == ohne.size == (BOOTLOADER_BREITE, BOOTLOADER_HOEHE)

    kasten = ImageChops.difference(mit, ohne).getbbox()
    assert kasten is not None, "Versionsmarke fehlt"
    links, oben, rechts, unten = kasten
    assert links > BOOTLOADER_BREITE * 0.8
    assert oben > BOOTLOADER_HOEHE * 0.88
    assert 3 <= BOOTLOADER_BREITE - rechts <= 20
    assert 3 <= BOOTLOADER_HOEHE - unten <= 20
    # graue Schrift: dunkelster Punkt der Marke ist grau, nicht schwarz
    # (nur Punkte der Marke selbst, die runden Ecken lassen das Bild durch)
    grau = mit.convert("L")
    anders = ImageChops.difference(mit, ohne).convert("L")
    dunkelster = min(
        grau.getpixel((x, y))
        for y in range(oben, unten)
        for x in range(links, rechts)
        if anders.getpixel((x, y))
    )
    assert 60 < dunkelster < 130


def test_bootloader_bild_vergroessert_kleine_bilder_nicht(tmp_path):
    klein = tmp_path / "klein.png"
    Image.new("RGB", (400, 200), (240, 230, 200)).save(klein)
    assert Image.open(schreibe_bild_mit_version(klein, tmp_path / "aus.png", "v1.2.3")).size == (400, 200)


def test_build_setzt_version_und_dpi_manifest():
    """Die Spec-Datei brennt die Version ein und meldet das Programm als DPI-faehig an.

    Ohne das Manifest zeigt der Bootloader das Startbild auf skalierten
    Bildschirmen erst vergroessert, und es schrumpft, sobald Qt startet.
    """
    spec = (WURZEL / "pdf_sortier_meister.spec").read_text(encoding="utf-8")
    assert "schreibe_bild_mit_version(" in spec
    assert "versionstext(APP_VERSION, entwicklung=False)" in spec
    assert "str(SPLASH_BUILD_IMG)," in spec
    assert ">PerMonitorV2</dpiAwareness>" in spec
    assert "manifest=DPI_MANIFEST" in spec
    # Ein eigenes Manifest ersetzt das von PyInstaller: dessen Eintraege muessen mit hinein
    manifest = re.search(r'DPI_MANIFEST = """(.*?)"""', spec, re.DOTALL).group(1)
    assert ">true</longPathAware>" in manifest
    assert "{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}" in manifest  # Windows 10/11
    assert 'level="asInvoker"' in manifest
    import xml.dom.minidom
    xml.dom.minidom.parseString(manifest.encode("utf-8"))
    assert f"max_img_size=({BOOTLOADER_BREITE}, {BOOTLOADER_HOEHE})" in spec
    # Seitenverhaeltnis des Bildes passt zu beiden Groessen
    breite, hoehe = Image.open(BILD).size
    assert breite * BOOTLOADER_HOEHE == hoehe * BOOTLOADER_BREITE
    assert breite * QT_HOEHE == hoehe * QT_BREITE
    assert startbild.QT_BREITE * 2 == breite

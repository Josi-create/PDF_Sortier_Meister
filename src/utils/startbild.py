"""
Startbild (Splash) mit eingeblendeter Versionsnummer.

Die Version steht rechts unten im Startbild, damit man schon beim Starten
sieht, welche Fassung laeuft. Sie kommt aus ``src/main.py`` (``__version__``),
nicht aus dem PNG.

Zwei Wege fuehren zum selben Bild:

- Start aus dem Quelltext und macOS: ``qt_startbild()`` malt den Text zur
  Laufzeit mit Qt (scharf bei jeder Bildschirmskalierung).
- Installierte Windows-Fassung: Das Startbild zeigt der PyInstaller-Bootloader,
  bevor Python laeuft. Dort laesst sich zur Laufzeit nichts malen, deshalb
  brennt ``schreibe_bild_mit_version()`` den Text beim Build ins Bild
  (aufgerufen aus ``pdf_sortier_meister.spec``).

Das Modul importiert Qt und Pillow erst in den Funktionen, damit die
Spec-Datei es ohne Qt laden kann.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Groesse des Qt-Startbilds in geraeteunabhaengigen Pixeln (halbe Bildgroesse)
QT_BREITE = 704
QT_HOEHE = 384

# Breite des Bootloader-Startbilds in echten Pixeln. Der Bootloader skaliert
# nicht mit der Bildschirmskalierung, das Bild ist auf jedem Monitor so breit.
BOOTLOADER_BREITE = 1056
BOOTLOADER_HOEHE = 576

# Aussehen der Versionsmarke, alles relativ zur Bildhoehe
_SCHRIFT_ANTEIL = 0.032      # Schrifthoehe
_RAND_ANTEIL = 0.018         # Abstand zur rechten unteren Ecke
_TEXTFARBE = (88, 88, 88)    # dezentes Grau
# Die Ecke ist halb helles Papier, halb dunkler Anzugaermel: Ein heller,
# leicht durchscheinender Grund haelt das Grau ueberall lesbar.
_GRUNDFARBE = (247, 238, 216, 215)


def git_kurz_hash(wurzel: Path) -> str:
    """Kurz-Hash des ausgecheckten Commits, gelesen aus ``.git`` (kein git-Aufruf).

    Liefert einen leeren String, wenn ``wurzel`` kein Git-Arbeitsverzeichnis ist
    oder sich der Hash nicht bestimmen laesst. Kennt auch Worktrees (``.git`` ist
    dort eine Datei mit ``gitdir: ...``) und gepackte Referenzen.
    """
    try:
        git = Path(wurzel) / ".git"
        if git.is_file():
            zeile = git.read_text(encoding="utf-8").strip()
            if not zeile.startswith("gitdir:"):
                return ""
            git = Path(zeile[len("gitdir:"):].strip())
            if not git.is_absolute():
                git = Path(wurzel) / git
        if not git.is_dir():
            return ""
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head[:7] if _ist_hash(head) else ""
        ref = head[len("ref:"):].strip()
        # In einem Worktree liegen die Zweige im gemeinsamen .git-Ordner
        gemeinsam = git
        commondir = git / "commondir"
        if commondir.is_file():
            ziel = Path(commondir.read_text(encoding="utf-8").strip())
            gemeinsam = ziel if ziel.is_absolute() else git / ziel
        for ordner in (git, gemeinsam):
            datei = ordner / ref
            if datei.is_file():
                wert = datei.read_text(encoding="utf-8").strip()
                return wert[:7] if _ist_hash(wert) else ""
        gepackt = gemeinsam / "packed-refs"
        if gepackt.is_file():
            for zeile in gepackt.read_text(encoding="utf-8").splitlines():
                teile = zeile.split(" ", 1)
                if len(teile) == 2 and teile[1].strip() == ref and _ist_hash(teile[0]):
                    return teile[0][:7]
    except (OSError, UnicodeDecodeError):
        pass
    return ""


def _ist_hash(text: str) -> bool:
    return len(text) >= 7 and all(c in "0123456789abcdef" for c in text.lower())


def versionstext(version: str, entwicklung: bool | None = None, wurzel: Path | None = None) -> str:
    """Text der Versionsmarke: ``v0.27.0``, aus dem Quelltext ``v0.27.0 dev (d4c18b0)``.

    ``entwicklung=None`` erkennt selbst, ob das Programm aus dem Quelltext
    laeuft (kein PyInstaller-Paket).
    """
    if entwicklung is None:
        entwicklung = not getattr(sys, "frozen", False)
    text = f"v{version}"
    if not entwicklung:
        return text
    if wurzel is None:
        wurzel = Path(__file__).resolve().parent.parent.parent
    kurz = git_kurz_hash(wurzel)
    return f"{text} dev ({kurz})" if kurz else f"{text} dev"


def _masse(hoehe: float) -> tuple[float, float, float, float]:
    """Schrifthoehe, Rand, Innenabstand waagerecht und senkrecht fuer eine Bildhoehe."""
    schrift = max(9.0, hoehe * _SCHRIFT_ANTEIL)
    return schrift, hoehe * _RAND_ANTEIL, schrift * 0.5, schrift * 0.22


def qt_startbild(bild_pfad: Path, text: str, dpr: float = 1.0):
    """Baut das Startbild fuer ``QSplashScreen``: halbe Bildgroesse, Version rechts unten.

    Das Bild wird in echten Pixeln fuer die Bildschirmskalierung ``dpr``
    gerechnet und traegt diesen Faktor, es erscheint also bei 100 %, 150 % und
    200 % gleich gross (704 x 384) und scharf. Gibt ``None`` zurueck, wenn sich
    das Bild nicht laden laesst.
    """
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPixmap

    quelle = QPixmap(str(bild_pfad))
    if quelle.isNull():
        return None
    dpr = max(1.0, float(dpr or 1.0))
    bild = quelle.scaled(
        round(QT_BREITE * dpr),
        round(QT_HOEHE * dpr),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    bild.setDevicePixelRatio(dpr)
    if not text:
        return bild

    breite = bild.width() / dpr
    hoehe = bild.height() / dpr
    schrift_px = _masse(hoehe)[0]

    maler = QPainter(bild)
    try:
        maler.setRenderHint(QPainter.RenderHint.Antialiasing)
        maler.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        schrift = QFont(maler.font())
        schrift.setPixelSize(max(1, round(schrift_px)))
        maler.setFont(schrift)
        metrik = QFontMetricsF(schrift, bild)
        feld = QRectF(*versionsfeld(breite, hoehe, metrik.horizontalAdvance(text), metrik.height()))
        maler.setPen(Qt.PenStyle.NoPen)
        maler.setBrush(QColor(*_GRUNDFARBE))
        maler.drawRoundedRect(feld, schrift_px * 0.3, schrift_px * 0.3)
        maler.setPen(QColor(*_TEXTFARBE))
        maler.drawText(feld, Qt.AlignmentFlag.AlignCenter, text)
    finally:
        maler.end()
    return bild


def versionsfeld(breite: float, hoehe: float, text_breite: float, text_hoehe: float) -> tuple[float, float, float, float]:
    """Lage des Versionsfelds (x, y, Breite, Hoehe) fuer ein Bild der gegebenen Groesse."""
    _, rand, innen_x, innen_y = _masse(hoehe)
    feld_b = text_breite + 2 * innen_x
    feld_h = text_hoehe + 2 * innen_y
    return breite - rand - feld_b, hoehe - rand - feld_h, feld_b, feld_h


def schreibe_bild_mit_version(
    quelle: Path,
    ziel: Path,
    text: str,
    breite: int = BOOTLOADER_BREITE,
    hoehe: int = BOOTLOADER_HOEHE,
) -> Path:
    """Schreibt das Startbild fuer den PyInstaller-Bootloader mit eingebrannter Version.

    Verkleinert ``quelle`` auf hoechstens ``breite`` x ``hoehe`` (Seitenverhaeltnis
    bleibt) und setzt ``text`` rechts unten hinein. Nur fuer den Build gedacht.
    """
    from PIL import Image, ImageDraw, ImageFont

    bild = Image.open(quelle).convert("RGBA")
    faktor = min(breite / bild.width, hoehe / bild.height, 1.0)
    if faktor < 1.0:
        bild = bild.resize(
            (max(1, round(bild.width * faktor)), max(1, round(bild.height * faktor))),
            Image.LANCZOS,
        )
    if text:
        schrift_px, _, _, _ = _masse(bild.height)
        schrift = None
        for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
            try:
                schrift = ImageFont.truetype(name, round(schrift_px))
                break
            except OSError:
                continue
        if schrift is None:
            schrift = ImageFont.load_default(round(schrift_px))
        links, oben, rechts, unten = schrift.getbbox(text)
        auf, ab = schrift.getmetrics() if hasattr(schrift, "getmetrics") else (unten, 0)
        x, y, feld_b, feld_h = versionsfeld(bild.width, bild.height, rechts - links, auf + ab)
        ebene = Image.new("RGBA", bild.size, (0, 0, 0, 0))
        zeichner = ImageDraw.Draw(ebene)
        zeichner.rounded_rectangle(
            (x, y, x + feld_b, y + feld_h), radius=schrift_px * 0.3, fill=_GRUNDFARBE
        )
        zeichner.text(
            (x + feld_b / 2, y + feld_h / 2), text, font=schrift, fill=_TEXTFARBE + (255,), anchor="mm"
        )
        bild = Image.alpha_composite(bild, ebene)
    ziel = Path(ziel)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    bild.convert("RGB").save(ziel, "PNG")
    return ziel
